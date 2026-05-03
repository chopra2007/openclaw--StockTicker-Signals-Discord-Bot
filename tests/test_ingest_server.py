"""Tests for consensus_engine.ingest_server.

Coverage:
  - Bearer token rotation (old token still accepted via PREVIOUS env var)
  - Nonce deduplication / idempotent retry (409 when in-flight)
  - signed_ts freshness rejection
  - JSON schema validation (missing required fields)
  - RedactingFilter scrubs bearer text from log records
  - Partial fan-out idempotency (409 when result row absent)
  - IPv6 /64 subnet isolation for rate-limit buckets
  - Per-routine bearer token isolation (R1 token rejected for R7)
"""

import logging
import os
import time

import aiohttp.web
import pytest
from aiohttp.test_utils import TestClient, TestServer
from unittest.mock import patch

from consensus_engine import db, config as cfg
from consensus_engine.utils.redacting_filter import RedactingFilter
import consensus_engine.ingest_server as ingest_mod
from consensus_engine.ingest_server import (
    ip_rate_limit_mw,
    redact_log_mw,
    _handle_ingest,
    _handle_heartbeat,
    _ip_prefix,
)

# ---------------------------------------------------------------------------
# Token fixtures
# ---------------------------------------------------------------------------
TOKEN_R1_CUR  = "a" * 64   # 64 hex-ish chars — passes RedactingFilter pattern
TOKEN_R1_PREV = "b" * 64
TOKEN_R7_CUR  = "c" * 64

_TOKEN_ENV = {
    "INGEST_BEARER_TOKEN_R1":          TOKEN_R1_CUR,
    "INGEST_BEARER_TOKEN_R1_PREVIOUS": TOKEN_R1_PREV,
    "INGEST_BEARER_TOKEN_R7":          TOKEN_R7_CUR,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> aiohttp.web.Application:
    """Build the ingest aiohttp app (same way serve() does, minus SSL/runner)."""
    app = aiohttp.web.Application(middlewares=[ip_rate_limit_mw, redact_log_mw])
    app.router.add_post("/ingest", _handle_ingest)
    app.router.add_post("/heartbeat", _handle_heartbeat)
    return app


def _payload(**overrides) -> dict:
    """Return a valid ingest payload dict; call-site overrides applied last."""
    base: dict = {
        "v": 1,
        "src": "pytest",
        "source_type": "desktop_auth",
        "source_detail": "unit-test",
        "raw_text": "Check $AAPL earnings today",
        "sentiment": "bullish",
        "event_ts": time.time(),
        "signed_ts": time.time(),
        "nonce": f"nonce-{time.monotonic_ns()}",
        "routine_id": "R1_AUTHED_WEB",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Autouse fixture: fresh DB + cleared rate buckets per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def isolate(tmp_path):
    """Provide a fresh SQLite DB and empty rate-limit state for every test."""
    # Clear module-level rate-limit buckets so tests don't bleed into each other
    ingest_mod._rate_buckets.clear()

    # Point db module at a fresh temp file; reset cached connection
    db.DB_PATH = str(tmp_path / "test.db")
    db._db = None
    cfg.load_config()
    await db.init_db()
    yield
    await db.close_db()
    db._db = None
    db.DB_PATH = None


# ---------------------------------------------------------------------------
# Test 1: bearer rotation overlap
# ---------------------------------------------------------------------------

async def test_bearer_rotation_overlap():
    """Previous bearer token (PREVIOUS env var) is still accepted within rotation window."""
    with patch.dict(os.environ, _TOKEN_ENV):
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/ingest",
                json=_payload(routine_id="R1_AUTHED_WEB"),
                headers={"Authorization": f"Bearer {TOKEN_R1_PREV}"},
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True


# ---------------------------------------------------------------------------
# Test 2: nonce idempotent retry
# ---------------------------------------------------------------------------

async def test_nonce_idempotent_retry():
    """Duplicate nonce returns 409 and leaves only one ticker_signals row."""
    nonce = "idempotent-nonce-001"
    # Pre-seed nonce as "in-flight" (no result row)
    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO seen_ingest_nonces (nonce, routine_id, received_at) VALUES (?, ?, ?)",
        (nonce, "R1_AUTHED_WEB", time.time()),
    )
    await conn.commit()

    with patch.dict(os.environ, _TOKEN_ENV):
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/ingest",
                json=_payload(nonce=nonce, routine_id="R1_AUTHED_WEB"),
                headers={"Authorization": f"Bearer {TOKEN_R1_CUR}"},
            )

    assert resp.status == 409

    # No ticker_signals rows were inserted (nonce was blocked before fan-out)
    cur = await conn.execute("SELECT COUNT(*) FROM ticker_signals")
    row = await cur.fetchone()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# Test 3: stale signed_ts rejected
# ---------------------------------------------------------------------------

async def test_ts_freshness_rejects_stale():
    """Payload with signed_ts older than 600 s is rejected with 400."""
    with patch.dict(os.environ, _TOKEN_ENV):
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/ingest",
                json=_payload(signed_ts=time.time() - 700),
                headers={"Authorization": f"Bearer {TOKEN_R1_CUR}"},
            )
            assert resp.status == 400
            body = await resp.text()
            assert "signed_ts" in body or "window" in body


# ---------------------------------------------------------------------------
# Test 4: malformed JSON schema rejected
# ---------------------------------------------------------------------------

async def test_json_schema_rejects_malformed():
    """Payload missing required fields returns 400 with 'missing fields' message."""
    with patch.dict(os.environ, _TOKEN_ENV):
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/ingest",
                json={"v": 1, "src": "partial"},   # many required fields absent
                headers={"Authorization": f"Bearer {TOKEN_R1_CUR}"},
            )
            assert resp.status == 400
            body = await resp.text()
            assert "missing" in body.lower()


# ---------------------------------------------------------------------------
# Test 5: redacting filter scrubs auth header value
# ---------------------------------------------------------------------------

def test_redacting_filter_scrubs_auth():
    """RedactingFilter replaces literal bearer token in log record msg."""
    token = "deadbeef" * 8  # 64 hex chars, matches _BEARER_RE pattern

    with patch.dict(os.environ, {"INGEST_BEARER_TOKEN_R1": token}):
        f = RedactingFilter()

    # Build a log record whose msg contains the raw bearer value
    record = logging.LogRecord(
        name="test.ingest",
        level=logging.WARNING,
        pathname="",
        lineno=0,
        msg=f"incoming Authorization: Bearer {token}",
        args=(),
        exc_info=None,
    )
    f.filter(record)

    assert token not in record.msg, "Bearer token must be scrubbed from log record"
    assert "***REDACTED***" in record.msg


# ---------------------------------------------------------------------------
# Test 6: partial fan-out idempotency (nonce in-flight → 409)
# ---------------------------------------------------------------------------

async def test_partial_fanout_idempotency():
    """Returns 409 with Retry-After when nonce exists but result row is absent (in-flight crash)."""
    nonce = "partial-fanout-nonce-001"
    conn = await db.get_db()

    # Simulate a crash after nonce insert but before result recording
    await conn.execute(
        "INSERT INTO seen_ingest_nonces (nonce, routine_id, received_at) VALUES (?, ?, ?)",
        (nonce, "R1_AUTHED_WEB", time.time()),
    )
    await conn.commit()

    # Confirm no result row exists
    cur = await conn.execute(
        "SELECT 1 FROM ingest_payload_results WHERE nonce = ?", (nonce,)
    )
    assert await cur.fetchone() is None

    with patch.dict(os.environ, _TOKEN_ENV):
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/ingest",
                json=_payload(nonce=nonce, routine_id="R1_AUTHED_WEB"),
                headers={"Authorization": f"Bearer {TOKEN_R1_CUR}"},
            )

    assert resp.status == 409
    assert resp.headers.get("Retry-After") == "10"


# ---------------------------------------------------------------------------
# Test 7: IPv6 /64 subnet isolation
# ---------------------------------------------------------------------------

def test_ip_rate_limit_ipv6():
    """IPv6 addresses in different /64 subnets have different rate-limit bucket keys."""
    # Two addresses in *different* /64 subnets
    ip_subnet_a1 = "2001:db8:1:0002::1"   # subnet 2001:db8:1:2::/64
    ip_subnet_b1 = "2001:db8:1:0003::1"   # subnet 2001:db8:1:3::/64
    # Another address in the SAME subnet as ip_subnet_a1
    ip_subnet_a2 = "2001:db8:1:0002::ff"

    prefix_a1 = _ip_prefix(ip_subnet_a1)
    prefix_b1 = _ip_prefix(ip_subnet_b1)
    prefix_a2 = _ip_prefix(ip_subnet_a2)

    assert prefix_a1 != prefix_b1, (
        f"Different /64 subnets must yield different bucket keys: {prefix_a1!r} == {prefix_b1!r}"
    )
    assert prefix_a1 == prefix_a2, (
        f"Same /64 subnet must yield the same bucket key: {prefix_a1!r} != {prefix_a2!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: per-routine bearer token isolation
# ---------------------------------------------------------------------------

async def test_per_routine_bearer():
    """R1 bearer token is rejected when the payload claims routine_id=R7_DISCORD_DAEMON."""
    with patch.dict(os.environ, _TOKEN_ENV):
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/ingest",
                json=_payload(routine_id="R7_DISCORD_DAEMON"),
                headers={"Authorization": f"Bearer {TOKEN_R1_CUR}"},  # R1 token, R7 routine
            )

    assert resp.status == 401
