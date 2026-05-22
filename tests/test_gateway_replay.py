"""#8 — gateway reconnect message-replay dedup layer."""
from __future__ import annotations

import time

import pytest

from consensus_engine import db
from consensus_engine.scanners.discord_tweetshift import _snowflake_age_seconds

_EPOCH_MS = 1420070400000


@pytest.fixture
async def fresh_db(tmp_path):
    db.DB_PATH = str(tmp_path / "replay.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = None


async def test_claim_message_first_caller_wins(fresh_db):
    """The first claim succeeds; a second claim of the same id fails."""
    assert await db.claim_message("100", "chan") is True
    assert await db.claim_message("100", "chan") is False


async def test_claim_message_done_is_not_reclaimable(fresh_db):
    """A message marked done is never re-claimed — replay skips it."""
    assert await db.claim_message("200", "chan") is True
    await db.mark_message_done("200")
    assert await db.claim_message("200", "chan") is False


async def test_claim_message_stale_orphan_is_redriven(fresh_db):
    """A 'claimed' row older than the staleness window is re-claimable — an
    orphan from a handler that crashed before mark_message_done."""
    assert await db.claim_message("300", "chan") is True
    conn = await db.get_db()
    await conn.execute(
        "UPDATE processed_messages SET updated_at = ? WHERE message_id = ?",
        (time.time() - db._CLAIM_STALE_SECONDS - 1, "300"),
    )
    await conn.commit()
    assert await db.claim_message("300", "chan") is True   # orphan re-driven
    assert await db.claim_message("300", "chan") is False  # now fresh again


async def test_channel_watermark_returns_newest_id(fresh_db):
    """channel_watermark returns the numerically-largest id per channel."""
    assert await db.channel_watermark("chA") is None
    await db.claim_message("1000", "chA")
    await db.claim_message("9999", "chA")
    await db.claim_message("5000", "chA")
    await db.claim_message("7777", "chB")   # other channel — must be ignored
    assert await db.channel_watermark("chA") == "9999"
    assert await db.channel_watermark("chB") == "7777"


def test_snowflake_age_seconds():
    """A snowflake's embedded timestamp yields its age; bad input -> 0.0."""
    now = time.time()
    created_ms = int((now - 600) * 1000)
    snowflake = str((created_ms - _EPOCH_MS) << 22)
    assert 595 < _snowflake_age_seconds(snowflake, now) < 605
    assert _snowflake_age_seconds("not-a-number", now) == 0.0
    fresh = str((int(now * 1000) - _EPOCH_MS) << 22)
    assert _snowflake_age_seconds(fresh, now) < 2
