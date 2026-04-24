"""Tests for Q2b: signal_events tweet routing.

RED at Commit A — turns GREEN when Commit C lands.

Covers:
- insert_signal(SourceType.TWITTER, ...) also writes a signal_events row with
  matching ticker, source_type='twitter', source_detail=<analyst>
- get_signal_events_for_ticker('NVDA', 3600) returns >= 1 row after inserting a
  twitter signal
"""
import time
import pytest

from consensus_engine import db, config as cfg
from consensus_engine.models import SourceType, TickerSignal, Sentiment


@pytest.fixture(autouse=True)
def _load_cfg():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg._config.setdefault("database", {})["path"] = db_path
    db._db = None
    conn = await db.init_db()
    yield conn
    await db.close_db()


# ---------------------------------------------------------------------------
# signal_events row created on TWITTER insert (RED until Commit C)
# ---------------------------------------------------------------------------

async def test_insert_signal_twitter_also_writes_signal_events_row(test_db):
    """insert_signal() for SourceType.TWITTER must also write a signal_events row.

    RED until Commit C routes twitter signals into signal_events.
    """
    signal = TickerSignal(
        ticker="NVDA",
        source_type=SourceType.TWITTER,
        source_detail="TeresaTrades",
        raw_text="NVDA breaking out, loading calls",
        sentiment=Sentiment.BULLISH,
    )
    await db.insert_signal(signal)

    cursor = await test_db.execute(
        "SELECT * FROM signal_events WHERE ticker = 'NVDA' AND source_type = 'twitter'"
    )
    rows = await cursor.fetchall()
    assert len(rows) >= 1, (
        "Expected at least one signal_events row with ticker='NVDA' and "
        "source_type='twitter' after insert_signal(SourceType.TWITTER, ...) — "
        "RED until Commit C adds the signal_events write"
    )


async def test_insert_signal_twitter_sets_correct_source_detail(test_db):
    """signal_events row written by insert_signal has source_detail = analyst handle.

    RED until Commit C routes twitter signals into signal_events.
    """
    signal = TickerSignal(
        ticker="AAPL",
        source_type=SourceType.TWITTER,
        source_detail="kpak82",
        raw_text="AAPL catalyst, adding more",
        sentiment=Sentiment.BULLISH,
    )
    await db.insert_signal(signal)

    cursor = await test_db.execute(
        "SELECT source_detail FROM signal_events "
        "WHERE ticker = 'AAPL' AND source_type = 'twitter'"
    )
    rows = await cursor.fetchall()
    assert rows, "No signal_events rows found — RED until Commit C"
    assert rows[0]["source_detail"] == "kpak82", (
        f"source_detail mismatch: expected 'kpak82', got {rows[0]['source_detail']!r}"
    )


async def test_non_twitter_insert_signal_does_not_write_signal_events(test_db):
    """insert_signal() for non-TWITTER source types must NOT write a signal_events row
    via the twitter-routing path (each source type has its own routing).

    This verifies insert_signal remains targeted: only TWITTER gets the new row.
    """
    signal = TickerSignal(
        ticker="MSFT",
        source_type=SourceType.REDDIT,
        source_detail="r/wallstreetbets",
        raw_text="MSFT gang",
        sentiment=Sentiment.NEUTRAL,
    )
    await db.insert_signal(signal)

    cursor = await test_db.execute(
        "SELECT COUNT(*) as cnt FROM signal_events "
        "WHERE ticker = 'MSFT' AND source_type = 'twitter'"
    )
    row = await cursor.fetchone()
    assert row["cnt"] == 0, (
        "REDDIT insert_signal should not create a source_type='twitter' signal_events row"
    )


# ---------------------------------------------------------------------------
# get_signal_events_for_ticker returns the new rows (RED until Commit C)
# ---------------------------------------------------------------------------

async def test_get_signal_events_for_ticker_returns_row_after_twitter_insert(test_db):
    """get_signal_events_for_ticker('NVDA', 3600) returns >= 1 row after a twitter
    insert_signal call.

    RED until Commit C: currently insert_signal does NOT write signal_events.
    """
    signal = TickerSignal(
        ticker="NVDA",
        source_type=SourceType.TWITTER,
        source_detail="FlowAlerts",
        raw_text="NVDA huge flow",
        sentiment=Sentiment.BULLISH,
    )
    await db.insert_signal(signal)

    events = await db.get_signal_events_for_ticker("NVDA", window_seconds=3600)
    assert len(events) >= 1, (
        "get_signal_events_for_ticker must return >= 1 row after twitter insert_signal — "
        "RED until Commit C adds the signal_events write to insert_signal"
    )
