"""Tests for new database tables and queries."""
import time
import pytest
from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    """Load config before each test."""
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


@pytest.mark.asyncio
async def test_seen_tweet_insert_and_check(test_db):
    url = "https://x.com/unusual_whales/status/123456"
    is_new = await db.is_new_tweet(url)
    assert is_new is True

    await db.mark_tweet_seen(url, "unusual_whales")

    is_new = await db.is_new_tweet(url)
    assert is_new is False


@pytest.mark.asyncio
async def test_seen_tweet_duplicate(test_db):
    url = "https://x.com/user/status/789"
    await db.mark_tweet_seen(url, "user")
    await db.mark_tweet_seen(url, "user")  # Should not raise
    is_new = await db.is_new_tweet(url)
    assert is_new is False


@pytest.mark.asyncio
async def test_alert_message_insert_and_get(test_db):
    msg_id = await db.insert_alert_message(
        ticker="TSLA",
        analyst="OptionMillionaire",
        instant_msg_id="discord_msg_111",
        base_score=30,
    )
    assert msg_id is not None

    row = await db.get_alert_message(msg_id)
    assert row["ticker"] == "TSLA"
    assert row["instant_msg_id"] == "discord_msg_111"
    assert row["followup_msg_id"] is None


@pytest.mark.asyncio
async def test_alert_message_update_followup(test_db):
    msg_id = await db.insert_alert_message(
        ticker="NVDA", analyst="CheddarFlow",
        instant_msg_id="discord_msg_222", base_score=25,
    )
    await db.update_alert_message_followup(msg_id, "discord_msg_333", final_score=87)

    row = await db.get_alert_message(msg_id)
    assert row["followup_msg_id"] == "discord_msg_333"
    assert row["final_score"] == 87


@pytest.mark.asyncio
async def test_ticker_metadata_cache(test_db):
    await db.cache_ticker_metadata("NVDA", "NVIDIA Corp", 2.8e12, "NASDAQ")

    meta = await db.get_ticker_metadata("NVDA")
    assert meta is not None
    assert meta["name"] == "NVIDIA Corp"
    assert meta["market_cap"] == 2.8e12

    # Unknown ticker returns None
    meta = await db.get_ticker_metadata("ZZZZ")
    assert meta is None


@pytest.mark.asyncio
async def test_ticker_metadata_stale(test_db):
    await db.cache_ticker_metadata("OLD", "Old Corp", 1e9, "NYSE")

    # Manually backdate last_checked
    conn = await db.get_db()
    stale_time = time.time() - (8 * 86400)  # 8 days ago
    await conn.execute(
        "UPDATE ticker_metadata SET last_checked = ? WHERE ticker = ?",
        (stale_time, "OLD"),
    )
    await conn.commit()

    meta = await db.get_ticker_metadata("OLD", max_age_days=7)
    assert meta is None  # Stale, should return None


@pytest.mark.asyncio
async def test_get_recent_analysts_for_ticker(test_db):
    from consensus_engine.models import TickerSignal, SourceType, Sentiment
    # Insert some twitter signals
    signals = [
        TickerSignal(ticker="TSLA", source_type=SourceType.TWITTER,
                     source_detail="analyst1", raw_text="long TSLA"),
        TickerSignal(ticker="TSLA", source_type=SourceType.TWITTER,
                     source_detail="analyst2", raw_text="buying TSLA"),
        TickerSignal(ticker="TSLA", source_type=SourceType.TWITTER,
                     source_detail="analyst1", raw_text="still long TSLA"),  # duplicate
    ]
    await db.insert_signals(signals)

    analysts = await db.get_recent_analysts_for_ticker("TSLA", window_seconds=3600)
    assert set(analysts) == {"analyst1", "analyst2"}
