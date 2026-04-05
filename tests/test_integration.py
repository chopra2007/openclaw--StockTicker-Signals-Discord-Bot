"""Integration test: Nitter RSS → tweet parse → cross-ref → Discord alert."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.main import process_tweet
from consensus_engine.models import (
    TweetType, Direction, Conviction, ParsedTweet, OptionsDetail,
    CrossReferenceResult, ScoreBreakdown, CatalystResult, TechnicalResult,
)


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db")}
    cfg.dry_run = True
    await db.init_db()
    yield
    await db.close_db()


SAMPLE_TWEET = {
    "url": "https://nitter.local/analyst1/status/123",
    "text": "Loading up $NVDA calls here, 150 strike Jan exp. High conviction breakout setup.",
    "analyst": "analyst1",
    "timestamp": time.time(),
}


def _make_parsed_tweet(**overrides):
    defaults = dict(
        tweet_url=SAMPLE_TWEET["url"],
        analyst="analyst1",
        raw_text=SAMPLE_TWEET["text"],
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        conviction=Conviction.HIGH,
        options=OptionsDetail(present=False),
        summary="NVDA long high conviction",
    )
    defaults.update(overrides)
    return ParsedTweet(**defaults)


@pytest.mark.asyncio
async def test_full_pipeline_actionable_tweet():
    """End-to-end: actionable tweet → instant ping → cross-ref → followup."""
    parsed = _make_parsed_tweet()
    xref = CrossReferenceResult(
        ticker="NVDA",
        breakdown=ScoreBreakdown(base=30, news_catalyst=15),
        catalyst_summary="NVDA beats earnings",
        catalyst_type="earnings",
    )

    with patch("consensus_engine.main.parse_tweet", new_callable=AsyncMock, return_value=parsed), \
         patch("consensus_engine.main.validate_ticker_market_cap", new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.main.send_instant_ping", new_callable=AsyncMock, return_value="msg_123"), \
         patch("consensus_engine.main.send_detail_followup", new_callable=AsyncMock, return_value="followup_456"), \
         patch("consensus_engine.main.cross_reference", new_callable=AsyncMock, return_value=xref), \
         patch("consensus_engine.main._fetch_price", new_callable=AsyncMock, return_value=135.50):

        await process_tweet(SAMPLE_TWEET)

        # Wait for background cross-reference task
        await asyncio.sleep(0.5)

    # Signal should be in DB
    signals = await db.get_twitter_signals("NVDA", window_seconds=60)
    assert len(signals) == 1
    assert signals[0]["source_detail"] == "analyst1"

    # Alert message should be recorded
    msg = await db.get_alert_message(1)
    assert msg is not None
    assert msg["ticker"] == "NVDA"
    assert msg["instant_msg_id"] == "msg_123"

    conn = await db.get_db()
    cursor = await conn.execute(
        "SELECT confidence_score, consensus_breakdown, analyst_mentions FROM alert_history WHERE ticker = ?",
        ("NVDA",),
    )
    alert = await cursor.fetchone()
    assert alert is not None
    assert alert["confidence_score"] == xref.final_score
    assert json.loads(alert["consensus_breakdown"])["news_catalyst"] == 15
    assert json.loads(alert["analyst_mentions"]) == []


@pytest.mark.asyncio
async def test_pipeline_skips_non_actionable():
    """Non-actionable tweets (type B/D) should be skipped entirely."""
    parsed = _make_parsed_tweet(tweet_type=TweetType.MACRO, tickers=[])

    with patch("consensus_engine.main.parse_tweet", new_callable=AsyncMock, return_value=parsed), \
         patch("consensus_engine.main.send_instant_ping", new_callable=AsyncMock) as mock_ping:

        await process_tweet(SAMPLE_TWEET)

    mock_ping.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_skips_low_market_cap():
    """Tickers failing market-cap validation should be skipped."""
    parsed = _make_parsed_tweet(tickers=["PENNY"])

    with patch("consensus_engine.main.parse_tweet", new_callable=AsyncMock, return_value=parsed), \
         patch("consensus_engine.main.validate_ticker_market_cap", new_callable=AsyncMock, return_value=False), \
         patch("consensus_engine.main.send_instant_ping", new_callable=AsyncMock) as mock_ping:

        await process_tweet(SAMPLE_TWEET)

    mock_ping.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_handles_ping_failure():
    """If instant ping fails, cross-reference should not run."""
    parsed = _make_parsed_tweet()

    with patch("consensus_engine.main.parse_tweet", new_callable=AsyncMock, return_value=parsed), \
         patch("consensus_engine.main.validate_ticker_market_cap", new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.main.send_instant_ping", new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.main._fetch_price", new_callable=AsyncMock, return_value=100.0), \
         patch("consensus_engine.main.cross_reference", new_callable=AsyncMock) as mock_xref:

        await process_tweet(SAMPLE_TWEET)
        await asyncio.sleep(0.2)

    mock_xref.assert_not_called()


@pytest.mark.asyncio
async def test_nitter_poll_processes_tweets():
    """NitterPoller.poll_all() results feed into process_tweet."""
    from consensus_engine.main import nitter_poll_loop

    stop = asyncio.Event()

    tweets = [
        {"url": "https://nitter.local/a1/1", "text": "$AAPL long", "analyst": "a1", "timestamp": time.time()},
        {"url": "https://nitter.local/a2/2", "text": "$TSLA calls", "analyst": "a2", "timestamp": time.time()},
    ]

    with patch("consensus_engine.main.NitterPoller") as MockPoller:
        instance = MockPoller.return_value
        instance.health_check = AsyncMock(return_value=True)
        instance.poll_all = AsyncMock(return_value=tweets)
        instance.get_poll_interval = MagicMock(return_value=1)

        with patch("consensus_engine.main.process_tweet", new_callable=AsyncMock) as mock_process:
            # Run one iteration then stop
            async def stop_after_one():
                await asyncio.sleep(0.3)
                stop.set()

            await asyncio.gather(
                nitter_poll_loop(stop),
                stop_after_one(),
            )

            assert mock_process.call_count == 2
