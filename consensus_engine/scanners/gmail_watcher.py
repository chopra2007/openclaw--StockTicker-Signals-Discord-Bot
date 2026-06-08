"""Gmail watcher — reads the Wolf newsletter into the macro-brain (TODO #20).

Polls the Gmail inbox for allowlisted Wolf emails, extracts directional theses
from the HTML text + chart images (vision), updates the stateful thesis store,
and posts proactive #news alerts. Writes ONLY to the Wolf tables — never to
ticker_signals — so Wolf's macro commentary never enters the live per-ticker
alert/scoring pipeline.
"""

import asyncio
import base64
import hashlib
import logging
import os
import re
import time
from email.utils import parseaddr
from fnmatch import fnmatch
from typing import Callable

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from consensus_engine import config as cfg, db
from consensus_engine.analysis import wolf_email_parser, wolf_theses
from consensus_engine.alerts import wolf_news

log = logging.getLogger(__name__)

# gmail.modify is required: _mark_processed applies a label via messages().modify.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
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
    """Check sender against the two allowlists.

    Two explicit, clearly-labelled config lists (phase-4 #5):
      gmail_watcher.allowed_emails  — exact sender addresses (case-insensitive)
      gmail_watcher.allowed_domains — whole domains; "wolf.com" or "*@wolf.com" both accepted
    Backward-compat: the legacy combined gmail_watcher.sender_allowlist (exact or *@domain
    glob) is still honoured if present, so an un-migrated config keeps working.
    """
    _, addr = parseaddr(from_header)
    addr_lower = addr.lower()
    if not addr_lower:
        return False
    addr_domain = addr_lower.rsplit("@", 1)[-1]

    for e in (cfg.get("gmail_watcher.allowed_emails", []) or []):
        if e.lower() == addr_lower:
            return True

    for d in (cfg.get("gmail_watcher.allowed_domains", []) or []):
        dn = d.lower().lstrip("*").lstrip("@")
        if dn and (addr_domain == dn or addr_lower.endswith("@" + dn)):
            return True

    # backward-compat: legacy combined list (exact or *@domain glob)
    for pattern in (cfg.get("gmail_watcher.sender_allowlist", []) or []):
        p = pattern.lower()
        if p == addr_lower or fnmatch(addr_lower, p):
            return True

    return False


_DKIM_PASS_RE = re.compile(r"\bdkim=pass\b", re.IGNORECASE)
_SPF_PASS_RE = re.compile(r"\bspf=pass\b", re.IGNORECASE)
# dmarc=pass OR a forwarding-preserved equivalent. Gmail auto-forwarding (the Wolf
# newsletter is forwarded from the subscriber's inbox to the bot's mailbox) breaks
# DMARC alignment, so Google reports arc=pass (Authenticated Received Chain — the
# IETF standard that carries authentication across a forwarder) or dara=pass instead
# of dmarc=pass. dkim=pass on the author domain still proves authenticity, so any of
# the three satisfies the DMARC leg.
_DMARC_EQUIV_RE = re.compile(r"\b(?:dmarc|arc|dara)=pass\b", re.IGNORECASE)


def _auth_results_pass(headers: list[dict]) -> bool:
    """True if any Authentication-Results header shows dkim+spf pass AND a DMARC
    pass (dmarc=pass, or arc=/dara=pass for Gmail-forwarded mail).

    Evaluates ALL Authentication-Results headers (Gmail can add several) with
    word-boundary matching so 'dkim=pass' does not match inside another token.
    """
    auth_values = [
        h.get("value", "") for h in headers
        if h.get("name", "").lower() == "authentication-results"
    ]
    for val in auth_values:
        if _DKIM_PASS_RE.search(val) and _SPF_PASS_RE.search(val) and _DMARC_EQUIV_RE.search(val):
            return True
    return False


def _strip_quoted(body: str) -> str:
    """Return body text before the first quoted/forwarded block."""
    match = _QUOTED_RE.search(body)
    if match:
        return body[: match.start()].strip()
    return body.strip()


def _decode_body(msg_payload: dict) -> tuple[str, str]:
    """Extract (plain_text, raw_html) from a Gmail message payload.

    Wolf emails are HTML-only (no text/plain part). We collect the first of each
    MIME type found anywhere in the tree so the parser can fall back to HTML.
    """
    found = {"text/plain": "", "text/html": ""}

    def _walk(part):
        mime = part.get("mimeType", "")
        if mime in found and not found[mime]:
            data = part.get("body", {}).get("data", "")
            if data:
                found[mime] = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(msg_payload)
    return found["text/plain"], found["text/html"]


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

        # Gate: sender must be allowlisted AND DKIM/SPF/DMARC must pass.
        # The subject substring gate is SKIPPED for the trusted Wolf sender
        # (the allowlist already pins it) so "Market Wrap" subjects aren't dropped.
        if not _sender_allowed(from_header):
            continue
        if not _auth_results_pass(headers):
            log.warning("gmail_watcher: auth (dkim/spf/dmarc) not all-pass; skipping %s", subject[:80])
            continue

        _, sender_addr = parseaddr(from_header)

        # Durable Wolf-processing dedup (image-only emails aren't covered by the
        # text-body hash). If we've already durably processed this message, skip.
        if await db.wolf_email_seen(msg_id):
            await _mark_processed(service, msg_id, label_id, loop)
            continue

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

        text, html = _decode_body(msg.get("payload", {}))
        text = _strip_quoted(text)
        html_sha1 = hashlib.sha1((html or text).encode()).hexdigest()

        # Parse -> ingest theses -> post #news. Wolf data goes ONLY to wolf tables.
        parse_status, error = "ok", None
        events = []
        try:
            extraction = await wolf_email_parser.parse_email(text, html, subject, sender_addr, now)
            img_urls = [c.get("source_url", "") for c in extraction.get("chart_reads", [])]
            image_urls_sha1 = hashlib.sha1("|".join(img_urls).encode()).hexdigest()
            events = await wolf_theses.ingest(extraction, source_id=msg_id)
            await wolf_news.post_events(events)
        except Exception as exc:
            parse_status, error = "error", str(exc)[:200]
            image_urls_sha1 = ""
            log.error("gmail_watcher: wolf parse/ingest error for %s: %s", msg_id, exc, exc_info=True)

        # Durable state BEFORE applying the Gmail label (Codex review).
        # received_at = the email's true Gmail receive time (internalDate, ms→s); the
        # digest scheduler triggers off this, not processed_at.
        try:
            received_at = float(msg.get("internalDate", 0)) / 1000.0 or None
        except (TypeError, ValueError):
            received_at = None
        await db.record_wolf_email(
            msg_id, html_sha1, image_urls_sha1, parse_status, error, len(events), now,
            received_at,
        )
        await conn.execute(
            "INSERT OR IGNORE INTO seen_gmail_messages (message_id, sender, subject, received_at) VALUES (?, ?, ?, ?)",
            (msg_id, sender_addr, subject[:200], now),
        )
        await conn.commit()
        await _mark_processed(service, msg_id, label_id, loop)
        daily_count += 1
        if events:
            log.info("gmail_watcher: %s -> %d thesis event(s)", subject[:60], len(events))

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
