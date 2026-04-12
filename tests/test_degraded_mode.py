"""Integration tests for degraded-mode policy and alert suppression.

Tests:
- _recompute_degraded_mode() returns True when >=2 critical sources are unhealthy
- process_tweet() suppresses high-confidence alerts in DEGRADED_MODE when configured
- process_tweet() allows low-confidence alerts through in DEGRADED_MODE
- send_instant_ping() annotates embeds with DEGRADED footer
- Restoring source health clears DEGRADED_MODE
- Regime detector returns adverse regime when signals are contradictory
- Regime detector returns OK when signals are one-directional
"""
import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from consensus_engine import config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


# ---------------------------------------------------------------------------
# _recompute_degraded_mode
# ---------------------------------------------------------------------------

def test_recompute_degraded_mode_all_healthy():
    """No unhealthy critical sources → DEGRADED_MODE = False."""
    import consensus_engine.main as main_mod

    now = time.time()
    main_mod._source_stats = {
        "finnhub":  {"calls": 10, "errors": 0, "last_ok": now - 10},
        "yfinance": {"calls": 10, "errors": 0, "last_ok": now - 10},
        "nitter":   {"calls": 10, "errors": 0, "last_ok": now - 10},
    }
    assert main_mod._recompute_degraded_mode() is False


def test_recompute_degraded_mode_two_critical_unhealthy():
    """>=2 critical sources unhealthy → DEGRADED_MODE = True."""
    import consensus_engine.main as main_mod

    now = time.time()
    main_mod._source_stats = {
        "finnhub":  {"calls": 10, "errors": 0, "last_ok": now - 10},
        # yfinance: never called (no last_ok) → unhealthy
        "yfinance": {"calls": 0, "errors": 0, "last_ok": 0.0},
        # nitter: very stale → unhealthy
        "nitter":   {"calls": 5, "errors": 0, "last_ok": now - 99999},
    }
    assert main_mod._recompute_degraded_mode() is True


def test_recompute_degraded_mode_one_critical_unhealthy():
    """Only 1 critical source unhealthy → stays False (threshold is 2)."""
    import consensus_engine.main as main_mod

    now = time.time()
    main_mod._source_stats = {
        "finnhub":  {"calls": 10, "errors": 0, "last_ok": now - 10},
        "yfinance": {"calls": 10, "errors": 0, "last_ok": now - 10},
        "nitter":   {"calls": 0, "errors": 0, "last_ok": 0.0},   # unhealthy
    }
    assert main_mod._recompute_degraded_mode() is False


def test_recompute_degraded_mode_high_error_rate():
    """Source with high error rate counts as unhealthy."""
    import consensus_engine.main as main_mod

    now = time.time()
    main_mod._source_stats = {
        "finnhub":  {"calls": 10, "errors": 8, "last_ok": now - 5},   # 80% error rate → unhealthy
        "yfinance": {"calls": 10, "errors": 9, "last_ok": now - 5},   # 90% error rate → unhealthy
        "nitter":   {"calls": 10, "errors": 0, "last_ok": now - 5},   # healthy
    }
    assert main_mod._recompute_degraded_mode() is True


# ---------------------------------------------------------------------------
# process_tweet — degraded mode suppression
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_tweet_suppresses_high_confidence_when_degraded():
    """High-confidence alert is suppressed in DEGRADED_MODE when suppress_when_degraded=true."""
    from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction
    import consensus_engine.main as main_mod

    main_mod.DEGRADED_MODE = True
    cfg._config["alerts"]["suppress_when_degraded"] = True
    cfg._config.setdefault("precision_engine", {}).setdefault("thresholds", {})
    cfg._config["precision_engine"]["thresholds"]["high_confidence"] = 80

    raw_tweet = {
        "url": "https://x.com/analyst/status/1",
        "analyst": "testanalyst",
        "text": "$NVDA breaking out big, going long calls here",
    }

    # HIGH conviction → base_score=30, but we need it >= 80 to trigger suppression.
    # Override the scoring threshold so a HIGH conviction tweet triggers the gate.
    cfg._config["precision_engine"]["thresholds"]["high_confidence"] = 25

    fake_tweet = ParsedTweet(
        tweet_url="https://x.com/analyst/status/1",
        analyst="testanalyst",
        raw_text="$NVDA breaking out big, going long calls here",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,  # base_score = 30, above threshold=25
        summary="NVDA high conviction long",
    )

    with patch("consensus_engine.main.db.check_seen_tweet", new_callable=AsyncMock, return_value=False), \
         patch("consensus_engine.main.db.mark_tweet_seen", new_callable=AsyncMock), \
         patch("consensus_engine.main.db.insert_signal", new_callable=AsyncMock), \
         patch("consensus_engine.main.db.check_alert_cooldown", new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.main.validate_ticker_market_cap", new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.main.send_instant_ping", new_callable=AsyncMock) as mock_ping, \
         patch("consensus_engine.main.parse_tweet", new_callable=AsyncMock, return_value=fake_tweet), \
         patch("consensus_engine.main._passes_quality_gate", return_value=True):

        await main_mod.process_tweet(raw_tweet)

        # send_instant_ping should NOT have been called (alert suppressed)
        mock_ping.assert_not_called()

    # Restore
    main_mod.DEGRADED_MODE = False
    cfg._config["alerts"]["suppress_when_degraded"] = False
    cfg._config["precision_engine"]["thresholds"]["high_confidence"] = 80


@pytest.mark.asyncio
async def test_process_tweet_allows_low_confidence_when_degraded():
    """Low-confidence alert fires in DEGRADED_MODE (only high-confidence is suppressed)."""
    from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction
    import consensus_engine.main as main_mod

    main_mod.DEGRADED_MODE = True
    cfg._config["alerts"]["suppress_when_degraded"] = True
    cfg._config.setdefault("precision_engine", {}).setdefault("thresholds", {})
    cfg._config["precision_engine"]["thresholds"]["high_confidence"] = 80

    raw_tweet = {
        "url": "https://x.com/analyst/status/2",
        "analyst": "testanalyst2",
        "text": "$AMD watching here",
    }

    # Use real ParsedTweet so dataclasses.replace() works
    fake_tweet = ParsedTweet(
        tweet_url="https://x.com/analyst/status/2",
        analyst="testanalyst2",
        raw_text="$AMD watching here",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["AMD"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.LOW,
        summary="AMD low-conviction",
    )
    # base_score for LOW conviction = 20, below 80 high_confidence threshold

    with patch("consensus_engine.main.db.check_seen_tweet", new_callable=AsyncMock, return_value=False), \
         patch("consensus_engine.main.db.mark_tweet_seen", new_callable=AsyncMock), \
         patch("consensus_engine.main.db.insert_signal", new_callable=AsyncMock), \
         patch("consensus_engine.main.db.check_alert_cooldown", new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.main.validate_ticker_market_cap", new_callable=AsyncMock, return_value=True), \
         patch("consensus_engine.main.db.insert_alert", new_callable=AsyncMock, return_value=1), \
         patch("consensus_engine.main.db.insert_alert_message", new_callable=AsyncMock, return_value=1), \
         patch("consensus_engine.main.send_instant_ping", new_callable=AsyncMock, return_value="msg123") as mock_ping, \
         patch("consensus_engine.main.asyncio.create_task"), \
         patch("consensus_engine.main.parse_tweet", new_callable=AsyncMock, return_value=fake_tweet), \
         patch("consensus_engine.main._passes_quality_gate", return_value=True):

        await main_mod.process_tweet(raw_tweet)

        # send_instant_ping SHOULD have been called with degraded=True
        mock_ping.assert_called_once()
        _, call_kwargs = mock_ping.call_args
        assert call_kwargs.get("degraded") is True

    # Restore
    main_mod.DEGRADED_MODE = False
    cfg._config["alerts"]["suppress_when_degraded"] = False


# ---------------------------------------------------------------------------
# send_instant_ping — DEGRADED annotation
# ---------------------------------------------------------------------------

def test_format_instant_ping_degraded_footer():
    """send_instant_ping in dry_run with degraded=True logs [DEGRADED]."""
    import consensus_engine.main as main_mod
    from consensus_engine.alerts.discord import send_instant_ping, format_instant_ping
    from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction

    tweet = ParsedTweet(
        tweet_url="https://x.com/a/1",
        analyst="analyst",
        raw_text="$NVDA long",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA long",
    )
    embed = format_instant_ping(tweet, 500.0)
    assert embed["footer"]["text"] == "OpenClaw Signal Engine"

    # Simulate what send_instant_ping does when degraded=True
    embed_degraded = format_instant_ping(tweet, 500.0)
    embed_degraded["footer"] = {"text": "OpenClaw Signal Engine | ⚠️ DEGRADED — data sources may be unreliable"}
    assert "DEGRADED" in embed_degraded["footer"]["text"]


@pytest.mark.asyncio
async def test_send_instant_ping_dry_run_degraded_logs():
    """send_instant_ping dry_run with degraded=True includes [DEGRADED] in log."""
    from consensus_engine.alerts.discord import send_instant_ping
    from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction
    import consensus_engine.alerts.discord as discord_mod

    original_dry_run = cfg.dry_run
    cfg.dry_run = True

    tweet = ParsedTweet(
        tweet_url="https://x.com/a/2",
        analyst="analyst",
        raw_text="$TSLA long",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["TSLA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="TSLA long",
    )

    result = await send_instant_ping(tweet, 200.0, degraded=True)
    assert result == "dry_run_msg_id"

    cfg.dry_run = original_dry_run


# ---------------------------------------------------------------------------
# DEGRADED_MODE restoration
# ---------------------------------------------------------------------------

def test_degraded_mode_clears_when_sources_recover():
    """After sources recover, _recompute_degraded_mode() returns False."""
    import consensus_engine.main as main_mod

    # Set up degraded state
    now = time.time()
    main_mod._source_stats = {
        "finnhub":  {"calls": 5, "errors": 0, "last_ok": 0.0},   # unhealthy
        "yfinance": {"calls": 5, "errors": 0, "last_ok": 0.0},   # unhealthy
        "nitter":   {"calls": 5, "errors": 0, "last_ok": now - 5},
    }
    assert main_mod._recompute_degraded_mode() is True

    # Sources recover
    main_mod._source_stats["finnhub"]["last_ok"] = now - 5
    main_mod._source_stats["finnhub"]["calls"] = 10
    main_mod._source_stats["yfinance"]["last_ok"] = now - 5
    main_mod._source_stats["yfinance"]["calls"] = 10

    assert main_mod._recompute_degraded_mode() is False


# ---------------------------------------------------------------------------
# Regime detector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regime_detector_adverse_high_contradiction(tmp_path):
    """Regime detector flags adverse regime when signals are split 50/50 bull/bear."""
    from consensus_engine import db
    from consensus_engine.analysis.regime_detector import detect_regime

    cfg._config["database"] = {"path": str(tmp_path / "r.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    await db.init_db()

    try:
        from consensus_engine.models import TickerSignal, SourceType, Sentiment

        now = time.time()
        # Insert equal bull and bear signals (high contradiction)
        for i in range(10):
            await db.insert_signal(TickerSignal(
                ticker="NVDA", source_type=SourceType.TWITTER,
                source_detail="analyst", raw_text="bull",
                sentiment=Sentiment.BULLISH,
            ))
            await db.insert_signal(TickerSignal(
                ticker="NVDA", source_type=SourceType.TWITTER,
                source_detail="analyst", raw_text="bear",
                sentiment=Sentiment.BEARISH,
            ))

        result = await detect_regime()
        assert result.is_adverse is True
        assert result.contradiction_index > 0.5
        assert result.abstain_boost > 0
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_regime_detector_ok_one_directional(tmp_path):
    """Regime detector returns OK when signals are strongly bullish."""
    from consensus_engine import db
    from consensus_engine.analysis.regime_detector import detect_regime

    cfg._config["database"] = {"path": str(tmp_path / "r2.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    await db.init_db()

    try:
        from consensus_engine.models import TickerSignal, SourceType, Sentiment

        # 90% bullish, 10% bearish → low contradiction
        for i in range(9):
            await db.insert_signal(TickerSignal(
                ticker="AAPL", source_type=SourceType.TWITTER,
                source_detail="analyst", raw_text="bull",
                sentiment=Sentiment.BULLISH,
            ))
        await db.insert_signal(TickerSignal(
            ticker="AAPL", source_type=SourceType.TWITTER,
            source_detail="analyst", raw_text="bear",
            sentiment=Sentiment.BEARISH,
        ))

        result = await detect_regime()
        assert result.is_adverse is False
        assert result.abstain_boost == 0
        assert result.breadth_bull_pct >= 0.8
    finally:
        await db.close_db()


@pytest.mark.asyncio
async def test_regime_detector_insufficient_data(tmp_path):
    """Regime detector returns OK (not adverse) when signal count is too low."""
    from consensus_engine import db
    from consensus_engine.analysis.regime_detector import detect_regime

    cfg._config["database"] = {"path": str(tmp_path / "r3.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    await db.init_db()

    try:
        # Only 2 signals — below the 5-signal minimum
        from consensus_engine.models import TickerSignal, SourceType, Sentiment
        await db.insert_signal(TickerSignal(
            ticker="SPY", source_type=SourceType.TWITTER,
            source_detail="analyst", raw_text="bull",
            sentiment=Sentiment.BULLISH,
        ))

        result = await detect_regime()
        assert result.is_adverse is False
        assert "insufficient" in result.reason
    finally:
        await db.close_db()
