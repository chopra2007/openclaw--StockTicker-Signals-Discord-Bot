"""Tests for consensus_engine.scanners.gmail_watcher.

Coverage:
  - Three-gate: blocked sender
  - Three-gate: blocked subject (independently of sender gate)
  - Body-hash deduplication (same body, different message-id → skip)
  - Quoted/forwarded chain tickers not extracted
  - Per-sender per-hour quota (21st message blocked)
  - RuntimeError in inner _do_cycle breaks inner loop; outer loop retries auth
  - Message-id deduplication (second submission of same ID → one row only)
"""

import asyncio
import base64
import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest

from consensus_engine import db, config as cfg
import consensus_engine.scanners.gmail_watcher as gw
from consensus_engine.scanners.gmail_watcher import _do_cycle


# ---------------------------------------------------------------------------
# Message / service helpers
# ---------------------------------------------------------------------------

def _b64(text: str) -> str:
    """URL-safe base64 encode without padding (Gmail API format)."""
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _make_gmail_msg(
    msg_id: str,
    from_addr: str,
    subject: str,
    body_text: str,
    auth_pass: bool = True,
) -> dict:
    """Build a minimal Gmail API full-message dict."""
    auth_val = (
        "dkim=pass; spf=pass; dmarc=pass"
        if auth_pass
        else "dkim=fail; spf=fail; dmarc=fail"
    )
    return {
        "id": msg_id,
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "Subject", "value": subject},
                {"name": "Authentication-Results", "value": auth_val},
            ],
            "body": {"data": _b64(body_text)},
            "parts": [],
        },
    }


def _make_service(
    messages: list,
    full_msg: dict | None = None,
    label_id: str = "lbl-001",
) -> MagicMock:
    """Build a MagicMock Gmail service with sensible defaults."""
    svc = MagicMock()
    users = svc.users.return_value

    # Scope verification (getProfile + labels.list)
    users.getProfile.return_value.execute.return_value = {
        "emailAddress": "test@example.com"
    }

    # Labels
    users.labels.return_value.list.return_value.execute.return_value = {
        "labels": [{"id": label_id, "name": "OpenClawProcessed"}]
    }
    users.labels.return_value.create.return_value.execute.return_value = {
        "id": label_id
    }

    # Messages list
    users.messages.return_value.list.return_value.execute.return_value = {
        "messages": messages
    }

    # Messages get (single fixed return; sufficient for one-message tests)
    if full_msg is not None:
        users.messages.return_value.get.return_value.execute.return_value = full_msg

    # Messages modify (label application)
    users.messages.return_value.modify.return_value.execute.return_value = {}

    return svc


# ---------------------------------------------------------------------------
# Autouse fixture: fresh DB + reset module globals per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def isolate(tmp_path):
    """Fresh DB + reset gmail_watcher module state for every test."""
    # Reset module-level globals that persist across calls
    gw._last_scope_verify = time.time()  # skip scope verification
    gw._processed_label_id = None

    # Fresh isolated DB
    db.DB_PATH = str(tmp_path / "test.db")
    db._db = None
    cfg.load_config()

    # Inject test gmail config into global config dict
    orig_gw = cfg._config.get("gmail_watcher", {})
    cfg._config["gmail_watcher"] = {
        "sender_allowlist": ["trusted@example.com", "*@trusted-domain.com"],
        "subject_substrings": ["alert", "trade", "$", "signal"],
        "processed_label_name": "OpenClawProcessed",
        "scope_verify_interval_seconds": 99999,
        "poll_interval_seconds": 0,
        "per_day_total_cap": 200,
        "per_sender_per_hour_cap": 20,
        "tickers_per_email_cap": 5,
        "enabled": True,
    }

    await db.init_db()
    yield

    # Restore original config
    cfg._config["gmail_watcher"] = orig_gw
    await db.close_db()
    db._db = None
    db.DB_PATH = None


# ---------------------------------------------------------------------------
# Test 1: three-gate — blocked sender
# ---------------------------------------------------------------------------

async def test_three_gate_sender_blocks():
    """Sender not in allowlist blocks all processing regardless of subject/auth."""
    msg = _make_gmail_msg(
        "msg-bad-sender",
        "attacker@evil.com",          # NOT in allowlist
        "AAPL alert $AAPL today",
        "Buy $AAPL call options now",
    )
    svc = _make_service([{"id": "msg-bad-sender"}], full_msg=msg)

    await _do_cycle(svc, None, None)

    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM ticker_signals")
    row = await cur.fetchone()
    assert row[0] == 0, "Blocked-sender message must not produce any ticker_signals"


# ---------------------------------------------------------------------------
# Test 2: three-gate — blocked subject
# ---------------------------------------------------------------------------

async def test_three_gate_subject_blocks():
    """Subject that matches no keyword independently blocks processing."""
    msg = _make_gmail_msg(
        "msg-bad-subject",
        "trusted@example.com",         # sender is allowed
        "Hello, just checking in",     # no keyword in subject_substrings
        "Buy $AAPL call options now",
    )
    svc = _make_service([{"id": "msg-bad-subject"}], full_msg=msg)

    await _do_cycle(svc, None, None)

    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) FROM ticker_signals")
    row = await cur.fetchone()
    assert row[0] == 0, "Non-matching subject must not produce ticker_signals"


# ---------------------------------------------------------------------------
# Test 3: body-hash deduplication
# ---------------------------------------------------------------------------

async def test_body_hash_dedup():
    """Same body content with a different message-id is skipped via seen_gmail_bodies."""
    body_text = "Buy $AAPL call options today"
    body_sha1 = hashlib.sha1(body_text.encode()).hexdigest()
    now = time.time()

    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO seen_gmail_bodies (body_sha1, sender, first_seen_at) VALUES (?, ?, ?)",
        (body_sha1, "trusted@example.com", now - 60),  # seen 60 s ago (within 24h)
    )
    await conn.commit()

    msg = _make_gmail_msg(
        "msg-different-id",
        "trusted@example.com",
        "AAPL alert $AAPL",
        body_text,
    )
    svc = _make_service([{"id": "msg-different-id"}], full_msg=msg)

    await _do_cycle(svc, None, None)

    cur = await conn.execute("SELECT COUNT(*) FROM ticker_signals")
    row = await cur.fetchone()
    assert row[0] == 0, "Duplicate body must not produce ticker_signals"


# ---------------------------------------------------------------------------
# Test 4: quoted content stripping
# ---------------------------------------------------------------------------

async def test_quoted_content_stripping():
    """Tickers appearing only in forwarded/quoted chains are not extracted."""
    # Tickers $TSLA and $NVDA are buried inside the quoted chain;
    # $AAPL appears before the quotation marker and SHOULD be extracted.
    body_text = (
        "Buy $AAPL options today.\n\n"
        "On Jan 1, 2024 Alice <alice@example.com> wrote:\n"
        "> I was watching $TSLA and $NVDA yesterday\n"
    )
    msg = _make_gmail_msg(
        "msg-quoted",
        "trusted@example.com",
        "AAPL alert $AAPL",
        body_text,
    )
    svc = _make_service([{"id": "msg-quoted"}], full_msg=msg)

    await _do_cycle(svc, None, None)

    conn = await db.get_db()
    # TSLA and NVDA must NOT appear in ticker_signals
    cur = await conn.execute(
        "SELECT ticker FROM ticker_signals WHERE ticker IN ('TSLA', 'NVDA')"
    )
    rows = await cur.fetchall()
    assert len(rows) == 0, f"Quoted tickers must not be extracted, got: {[r[0] for r in rows]}"

    # AAPL (from the non-quoted prefix) SHOULD have been inserted
    cur2 = await conn.execute(
        "SELECT COUNT(*) FROM ticker_signals WHERE ticker = 'AAPL'"
    )
    row2 = await cur2.fetchone()
    assert row2[0] >= 1, "Non-quoted ticker $AAPL must be extracted"


# ---------------------------------------------------------------------------
# Test 5: per-sender per-hour quota
# ---------------------------------------------------------------------------

async def test_per_sender_quota():
    """21st message from the same sender within one hour is blocked by per_sender_per_hour_cap."""
    sender = "trusted@example.com"
    now = time.time()
    conn = await db.get_db()

    # Pre-seed exactly 20 rows for this sender in the past hour (at the cap limit)
    for i in range(20):
        await conn.execute(
            "INSERT INTO seen_gmail_messages"
            " (message_id, sender, subject, received_at) VALUES (?, ?, ?, ?)",
            (f"msg-prior-{i}", sender, "prior alert", now - 100),
        )
    await conn.commit()

    # The 21st message should be blocked
    msg = _make_gmail_msg(
        "msg-21st",
        sender,
        "AAPL alert $AAPL",
        "Buy $AAPL now",
    )
    svc = _make_service([{"id": "msg-21st"}], full_msg=msg)

    errs: list[str] = []
    await _do_cycle(svc, None, lambda k: errs.append(k))

    cur = await conn.execute("SELECT COUNT(*) FROM ticker_signals")
    row = await cur.fetchone()
    assert row[0] == 0, "Quota-exceeded message must not produce ticker_signals"
    assert "gmail_quota" in errs, "record_err('gmail_quota') must be called when quota is hit"


# ---------------------------------------------------------------------------
# Test 6: restart on RuntimeError
# ---------------------------------------------------------------------------

async def test_restart_on_exception():
    """RuntimeError from _do_cycle breaks inner loop; gmail_watcher_loop catches it cleanly."""
    stop_event = asyncio.Event()
    errs: list[str] = []

    async def mock_cycle(svc, ok, err):
        # Schedule stop_event so the outer loop's re-auth wait completes quickly
        asyncio.get_event_loop().call_soon(stop_event.set)
        raise RuntimeError("Gmail scope revoked — test trigger")

    with patch.object(gw, "_build_service", return_value=MagicMock()), \
         patch.object(gw, "_do_cycle", side_effect=mock_cycle):
        # gmail_watcher_loop should not re-raise the RuntimeError
        await gw.gmail_watcher_loop(stop_event, None, lambda k: errs.append(k))

    assert "gmail" in errs, "record_err('gmail') must be called when RuntimeError is raised"


# ---------------------------------------------------------------------------
# Test 7: message-id deduplication
# ---------------------------------------------------------------------------

async def test_message_id_dedup():
    """Processing the same message-id twice inserts exactly one row in seen_gmail_messages."""
    msg_id = "msg-dedup-001"
    msg = _make_gmail_msg(
        msg_id,
        "trusted@example.com",
        "AAPL alert $AAPL",
        "Buy $AAPL call options today",
    )
    svc = _make_service([{"id": msg_id}], full_msg=msg)

    # First cycle: message processed → row inserted
    await _do_cycle(svc, None, None)

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) FROM seen_gmail_messages WHERE message_id = ?", (msg_id,)
    )
    row = await cur.fetchone()
    assert row[0] == 1, "After first cycle, exactly one seen_gmail_messages row expected"

    # Second cycle with the same message_id in the list → skipped
    await _do_cycle(svc, None, None)

    cur2 = await conn.execute(
        "SELECT COUNT(*) FROM seen_gmail_messages WHERE message_id = ?", (msg_id,)
    )
    row2 = await cur2.fetchone()
    assert row2[0] == 1, "After second cycle, still exactly one row (dedup working)"
