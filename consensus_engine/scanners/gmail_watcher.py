"""Gmail API background watcher — polls openclaw inbox and inserts ticker signals."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
from email.utils import parseaddr
from fnmatch import fnmatch
from typing import Callable

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from consensus_engine import config as cfg, db
from consensus_engine.models import Sentiment, SourceType, TickerSignal
from consensus_engine.utils.tickers import extract_tickers

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
]

_QUOTED_RE = re.compile(
    r"(^>|^On .+ wrote:|^-+ Forwarded message -+)", re.MULTILINE | re.IGNORECASE
)

_last_scope_verify: float = 0.0
_processed_label_id: str | None = None


def _load_credentials() -> Credentials:
    """Load OAuth2 credentials from token file; refresh if expired."""
    token_path = os.environ.get(
        "GMAIL_TOKEN_PATH",
        cfg.get("gmail_watcher.token_path", "/root/.openclaw/gmail/token.json"),
    )
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                f"Gmail token not found or expired at {token_path}. "
                "Run bootstrap_gmail.py on Windows, then SCP token.json to VPS."
            )
    return creds


def _build_service():
    """Build an authenticated Gmail API service object (synchronous)."""
    creds = _load_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


async def _verify_scopes(service) -> bool:
    """Verify both required scopes are still granted. Returns True if OK."""
    loop = asyncio.get_running_loop()
    try:
        token_info = await loop.run_in_executor(
            None,
            lambda: service.users().getProfile(userId="me").execute(),
        )
        # getProfile succeeding means readonly scope is present
        # Try label list to check labels scope
        await loop.run_in_executor(
            None,
            lambda: service.users().labels().list(userId="me").execute(),
        )
        return True
    except Exception as exc:
        log.error("gmail_watcher: scope verification failed: %s", exc)
        return False


async def _ensure_processed_label(service) -> str | None:
    """Get or create the OpenClawProcessed label; returns label ID."""
    global _processed_label_id
    if _processed_label_id:
        return _processed_label_id
    loop = asyncio.get_running_loop()
    label_name = cfg.get("gmail_watcher.processed_label_name", "OpenClawProcessed")
    try:
        result = await loop.run_in_executor(
            None,
            lambda: service.users().labels().list(userId="me").execute(),
        )
        for lbl in result.get("labels", []):
            if lbl["name"] == label_name:
                _processed_label_id = lbl["id"]
                return _processed_label_id
        # Create it
        created = await loop.run_in_executor(
            None,
            lambda: service.users().labels().create(
                userId="me",
                body={"name": label_name, "labelListVisibility": "labelShow"},
            ).execute(),
        )
        _processed_label_id = created["id"]
        log.info("gmail_watcher: created label %s (id=%s)", label_name, _processed_label_id)
        return _processed_label_id
    except Exception as exc:
        log.error("gmail_watcher: label setup error: %s", exc)
        return None


def _sender_allowed(from_header: str) -> bool:
    """Check sender against allowlist (exact or *@domain.tld glob)."""
    allowlist = cfg.get("gmail_watcher.sender_allowlist", [])
    if not allowlist:
        return False
    _, addr = parseaddr(from_header)
    addr_lower = addr.lower()
    for pattern in allowlist:
        p = pattern.lower()
        if p == addr_lower or fnmatch(addr_lower, p):
            return True
    return False


def _subject_matches(subject: str) -> bool:
    """Check subject against configured substrings."""
    substrings = cfg.get("gmail_watcher.subject_substrings", ["alert", "trade", "trigger", "signal", "$"])
    subject_lower = subject.lower()
    return any(s.lower() in subject_lower for s in substrings)


def _auth_results_pass(headers: list[dict]) -> bool:
    """Return True if Authentication-Results shows dkim=pass AND spf=pass AND dmarc=pass."""
    auth_header = ""
    for h in headers:
        if h.get("name", "").lower() == "authentication-results":
            auth_header = h.get("value", "")
            break
    if not auth_header:
        return False
    return (
        "dkim=pass" in auth_header.lower()
        and "spf=pass" in auth_header.lower()
        and "dmarc=pass" in auth_header.lower()
    )


def _strip_quoted(body: str) -> str:
    """Return body text before the first quoted/forwarded block."""
    match = _QUOTED_RE.search(body)
    if match:
        return body[: match.start()].strip()
    return body.strip()


def _decode_body(msg_payload: dict) -> str:
    """Extract plain-text body from Gmail message payload."""
    def _parts(part):
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            result = _parts(sub)
            if result:
                return result
        return ""
    return _parts(msg_payload)


async def _do_cycle(
    service,
    record_ok: Callable | None,
    record_err: Callable | None,
) -> None:
    """Run one poll cycle: fetch unprocessed messages, filter, extract, insert."""
    global _last_scope_verify

    scope_interval = cfg.get("gmail_watcher.scope_verify_interval_seconds", 21600)
    if time.time() - _last_scope_verify > scope_interval:
        if not await _verify_scopes(service):
            if record_err:
                record_err("gmail_scope")
            log.error("gmail_watcher: required Gmail scopes not present — stopping watcher")
            raise RuntimeError("Gmail scopes revoked")
        _last_scope_verify = time.time()

    label_id = await _ensure_processed_label(service)
    if not label_id:
        if record_ok:
            record_ok("gmail_heartbeat")  # heartbeat even on label failure
        return

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: service.users().messages().list(
                userId="me",
                q=f"-label:OpenClawProcessed in:inbox newer_than:2d",
            ).execute(),
        )
    except Exception as exc:
        log.error("gmail_watcher: messages.list error: %s", exc)
        if record_err:
            record_err("gmail")
        if record_ok:
            record_ok("gmail_heartbeat")
        return

    messages = result.get("messages", [])
    if not messages:
        if record_ok:
            record_ok("gmail_heartbeat")
        return

    conn = await db.get_db()
    now = time.time()
    per_day_cap = cfg.get("gmail_watcher.per_day_total_cap", 200)
    per_sender_hour_cap = cfg.get("gmail_watcher.per_sender_per_hour_cap", 20)
    tickers_per_email_cap = cfg.get("gmail_watcher.tickers_per_email_cap", 5)

    # Check daily total
    cur = await conn.execute(
        "SELECT COUNT(*) as cnt FROM seen_gmail_messages WHERE received_at >= ?",
        (now - 86400,),
    )
    row = await cur.fetchone()
    daily_count = row["cnt"] if row else 0

    for msg_stub in messages:
        msg_id = msg_stub["id"]

        # Message-id dedup
        cur = await conn.execute(
            "SELECT 1 FROM seen_gmail_messages WHERE message_id = ?", (msg_id,)
        )
        if await cur.fetchone():
            continue

        # Fetch full message
        try:
            msg = await loop.run_in_executor(
                None,
                lambda: service.users().messages().get(
                    userId="me", id=msg_id, format="full",
                ).execute(),
            )
        except Exception as exc:
            log.warning("gmail_watcher: messages.get(%s) error: %s", msg_id, exc)
            continue

        headers = msg.get("payload", {}).get("headers", [])
        h = {h["name"].lower(): h["value"] for h in headers}
        from_header = h.get("from", "")
        subject = h.get("subject", "")

        # Three-of-three gate
        if not _sender_allowed(from_header):
            continue
        if not _subject_matches(subject):
            continue
        if not _auth_results_pass(headers):
            continue

        body_raw = _decode_body(msg.get("payload", {}))
        body = _strip_quoted(body_raw)
        if not body.strip():
            # Entire body was quoted — noop but still mark processed
            await _mark_processed(service, msg_id, label_id, loop)
            continue

        # Body-hash dedup
        body_sha1 = hashlib.sha1(body.encode()).hexdigest()
        cur = await conn.execute(
            "SELECT first_seen_at FROM seen_gmail_bodies WHERE body_sha1 = ?", (body_sha1,)
        )
        body_row = await cur.fetchone()
        if body_row and now - body_row["first_seen_at"] < 86400:
            await _mark_processed(service, msg_id, label_id, loop)
            continue

        _, sender_addr = parseaddr(from_header)

        # Per-sender-per-hour quota
        cur = await conn.execute(
            "SELECT COUNT(*) as cnt FROM seen_gmail_messages WHERE sender = ? AND received_at >= ?",
            (sender_addr, now - 3600),
        )
        row = await cur.fetchone()
        if (row["cnt"] if row else 0) >= per_sender_hour_cap:
            log.warning("gmail_watcher: per-sender quota hit for %s", sender_addr)
            if record_err:
                record_err("gmail_quota")
            continue

        # Daily cap
        if daily_count >= per_day_cap:
            log.warning("gmail_watcher: daily total cap reached")
            if record_err:
                record_err("gmail_quota")
            break

        # Extract tickers
        try:
            tickers = extract_tickers(body[:8000])
        except Exception as exc:
            log.warning("gmail_watcher: extract_tickers error: %s", exc)
            tickers = set()
        tickers = set(list(tickers)[:tickers_per_email_cap])
        if not tickers:
            await _mark_processed(service, msg_id, label_id, loop)
            continue

        inserted = 0
        for ticker in tickers:
            try:
                await db.insert_signal(TickerSignal(
                    ticker=ticker,
                    source_type=SourceType.DESKTOP_AUTH,
                    source_detail=f"gmail|from:{sender_addr}|subject:{subject[:80]}",
                    raw_text=body[:2000],
                    sentiment=Sentiment.NEUTRAL,
                ))
                inserted += 1
            except Exception as exc:
                log.error("gmail_watcher: insert_signal error ticker=%s: %s", ticker, exc)

        if inserted > 0:
            # Mark dedup tables
            await conn.execute(
                "INSERT OR IGNORE INTO seen_gmail_messages (message_id, sender, subject, received_at) VALUES (?, ?, ?, ?)",
                (msg_id, sender_addr, subject[:200], now),
            )
            if not body_row:
                await conn.execute(
                    "INSERT OR IGNORE INTO seen_gmail_bodies (body_sha1, sender, first_seen_at) VALUES (?, ?, ?)",
                    (body_sha1, sender_addr, now),
                )
            await conn.commit()
            await _mark_processed(service, msg_id, label_id, loop)
            daily_count += 1

        if record_ok:
            record_ok("gmail")

    if record_ok:
        record_ok("gmail_heartbeat")


async def _mark_processed(service, msg_id: str, label_id: str, loop) -> None:
    """Apply OpenClawProcessed label to a message."""
    try:
        await loop.run_in_executor(
            None,
            lambda: service.users().messages().modify(
                userId="me", id=msg_id, body={"addLabelIds": [label_id]},
            ).execute(),
        )
    except Exception as exc:
        log.warning("gmail_watcher: label apply error for %s: %s", msg_id, exc)


async def gmail_watcher_loop(
    stop_event: asyncio.Event,
    record_ok: Callable[[str], None] | None = None,
    record_err: Callable[[str], None] | None = None,
) -> None:
    """Background loop: poll Gmail inbox every poll_interval_seconds."""
    enabled = cfg.get("gmail_watcher.enabled", False)
    if not enabled:
        log.info("gmail_watcher disabled in config, not starting")
        await stop_event.wait()
        return

    # Build service once; restart wrapper handles auth errors
    _restart_count = 0
    while not stop_event.is_set():
        try:
            loop = asyncio.get_running_loop()
            service = await loop.run_in_executor(None, _build_service)
        except Exception as exc:
            log.error("gmail_watcher: auth/build error, retrying in 30s: %s", exc)
            if record_err:
                record_err("gmail")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
            _restart_count += 1
            if _restart_count > 10:
                log.error("gmail_watcher: too many auth retries, stopping")
                return
            continue

        _restart_count = 0  # Reset on successful service build

        # Inner poll loop
        while not stop_event.is_set():
            try:
                await _do_cycle(service, record_ok, record_err)
            except RuntimeError as exc:
                # Scope-revoked sentinel from _do_cycle
                log.error("gmail_watcher: scope error, restarting auth in 60s: %s", exc)
                if record_err:
                    record_err("gmail")
                break  # break inner loop, re-auth in outer loop
            except Exception as exc:
                log.error("gmail_watcher: cycle error: %s", exc, exc_info=True)
                if record_err:
                    record_err("gmail")
            interval = cfg.get("gmail_watcher.poll_interval_seconds", 60)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

        # After inner loop exits (scope error), wait before re-auth
        if not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
