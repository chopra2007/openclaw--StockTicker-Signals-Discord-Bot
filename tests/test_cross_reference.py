"""Tests for cross-reference scoring engine."""
import pytest
from unittest.mock import AsyncMock, patch
from consensus_engine.models import (
    ParsedTweet, TweetType, Direction, Conviction,
    CatalystResult, TechnicalResult, TechnicalFilter,
    ScoreBreakdown,
)
from consensus_engine.cross_reference import (
    compute_technical_score, compute_social_score, cross_reference,
    _get_catalyst_score,
)
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


def test_tiered_catalyst_high():
    assert _get_catalyst_score("Earnings Beat") == 25


def test_tiered_catalyst_medium():
    assert _get_catalyst_score("Analyst Upgrade") == 15


def test_tiered_catalyst_low():
    assert _get_catalyst_score("Partnership") == 8


def test_tiered_catalyst_unknown_defaults_to_medium():
    assert _get_catalyst_score("Unknown Event") == 15


def test_compute_technical_score_all_pass():
    tech = TechnicalResult(
        ticker="NVDA",
        filters=[
            TechnicalFilter(name="RVOL", value=2.5, threshold="> 2.0x", passed=True),
            TechnicalFilter(name="VWAP", value=100, threshold="> 98 (VWAP)", passed=True),
            TechnicalFilter(name="RSI", value=60, threshold="40-75", passed=True),
            TechnicalFilter(name="EMA Cross", value=0.5, threshold="9EMA > 21EMA", passed=True),
            TechnicalFilter(name="Price Change", value=3.0, threshold="> +1.0%", passed=True),
            TechnicalFilter(name="ATR Breakout", value=1.8, threshold="> 1.5x ATR", passed=True),
        ],
        price=100, volume=50000000,
    )
    score = compute_technical_score(tech)
    assert score == 12  # 6 * 2 = 12, capped at 12


def test_compute_technical_score_partial():
    tech = TechnicalResult(
        ticker="NVDA",
        filters=[
            TechnicalFilter(name="RVOL", value=2.5, threshold="> 2.0x", passed=True),
            TechnicalFilter(name="RSI", value=80, threshold="40-75", passed=False),
            TechnicalFilter(name="EMA Cross", value=0.5, threshold="9EMA > 21EMA", passed=True),
        ],
        price=100, volume=50000000,
    )
    score = compute_technical_score(tech)
    assert score == 4  # 2 * 2


def test_compute_technical_score_none():
    score = compute_technical_score(None)
    assert score == 0


def test_compute_social_score():
    social_data = {
        "apewisdom": 5,
        "stocktwits": 2,
        "reddit": 3,
        "google_trends": 1,
    }
    score = compute_social_score(social_data)
    assert score == 35


def test_compute_social_score_empty():
    score = compute_social_score({})
    assert score == 0


@pytest.mark.asyncio
async def test_cross_reference_with_mocked_sources():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="unusual_whales",
        raw_text="$NVDA breaking out",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA breakout",
    )

    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="NVDA earnings beat",
        catalyst_type="Earnings Beat", news_sources=["reuters.com"],
        source_urls=["https://reuters.com/nvda"], confidence=0.8,
    )

    with patch("consensus_engine.cross_reference.get_cached_xref",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference.cache_xref",
               new_callable=AsyncMock), \
         patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=mock_catalyst), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=(False, "")), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={"apewisdom": 3}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=["CheddarFlow"]), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new_callable=AsyncMock, return_value=(75.0, "Strong setup")):
        result = await cross_reference("NVDA", tweet)

    assert result.breakdown.base == 30
    assert result.breakdown.news_catalyst == 25  # Earnings Beat is a high-tier catalyst
    assert result.breakdown.additional_analysts == 20
    assert result.breakdown.social_apewisdom == 10
    assert result.breakdown.llm_boost > 0
    assert result.final_score > 30


@pytest.mark.asyncio
async def test_llm_called_once_with_real_data():
    """LLM should be called exactly once — with real data after gather, not with nulls."""
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="test",
        raw_text="$NVDA breaking out hard",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA breakout",
    )

    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="Earnings beat",
        catalyst_type="Earnings Beat", news_sources=["reuters"],
        source_urls=["https://reuters.com"], confidence=0.8,
    )
    mock_technical = TechnicalResult(
        ticker="NVDA",
        filters=[TechnicalFilter(name="RVOL", value=3.0, threshold="> 2.0x", passed=True)],
        price=100, volume=50000000,
    )

    llm_mock = AsyncMock(return_value=(80.0, "Strong"))

    with patch("consensus_engine.cross_reference.get_cached_xref",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference.cache_xref",
               new_callable=AsyncMock), \
         patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=mock_catalyst), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=(False, "")), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=mock_technical), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=[]), \
         patch("consensus_engine.cross_reference._run_llm_score", llm_mock), \
         patch("consensus_engine.cross_reference._run_options_check",
               new_callable=AsyncMock, return_value=None):
        result = await cross_reference("NVDA", tweet)

    assert llm_mock.call_count == 1
    args = llm_mock.call_args
    assert args[0][1] is not None  # catalyst
    assert args[0][2] is not None  # technical


@pytest.mark.asyncio
async def test_analyst_multiplier_capped():
    """Analyst multiplier should be capped at max_additional_analysts (default 3)."""
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="test",
        raw_text="$NVDA breaking out all day",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA",
    )

    ten_analysts = [f"analyst_{i}" for i in range(10)]

    with patch("consensus_engine.cross_reference.get_cached_xref",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference.cache_xref",
               new_callable=AsyncMock), \
         patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=(False, "")), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=ten_analysts), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new_callable=AsyncMock, return_value=(0.0, "")), \
         patch("consensus_engine.cross_reference._run_options_check",
               new_callable=AsyncMock, return_value=None):
        result = await cross_reference("NVDA", tweet)

    # 3 (cap) * 20 = 60, NOT 10 * 20 = 200
    assert result.breakdown.additional_analysts == 60


@pytest.mark.asyncio
async def test_get_youtube_context_uses_canonical_evidence():
    """_get_youtube_context must call get_youtube_evidence_for_ticker, not get_youtube_levels_for_ticker."""
    from consensus_engine.cross_reference import _get_youtube_context

    signals = [
        {"direction": "long", "conviction": "high", "channel_name": "Chan1",
         "evidence_spans_for_ticker": 1},
    ]
    # canonical evidence: one setup + one raw level
    evidence = [
        {
            "evidence_type": "setup", "id": 1, "ticker": "TSLA",
            "entry_low": 240.0, "entry_high": 250.0, "stop_price": 230.0,
            "setup_type": "breakout", "price": None, "level_type": None,
            "confidence": None, "channel_name": "Chan1",
        },
        {
            "evidence_type": "level", "id": 2, "ticker": "TSLA",
            "entry_low": None, "entry_high": None, "stop_price": None,
            "setup_type": None, "price": 260.0, "level_type": "resistance",
            "confidence": 0.85, "channel_name": "Chan1",
        },
    ]

    with patch("consensus_engine.cross_reference.db") as mock_db:
        mock_db.get_youtube_signals_for_ticker = AsyncMock(return_value=signals)
        mock_db.get_youtube_evidence_for_ticker = AsyncMock(return_value=evidence)
        # get_youtube_levels_for_ticker must NOT be called
        mock_db.get_youtube_levels_for_ticker = AsyncMock(side_effect=AssertionError("must not call get_youtube_levels_for_ticker"))

        ctx = await _get_youtube_context("TSLA")

    assert ctx is not None
    assert ctx.mention_count == 1
    # Both setup and level should appear in ctx.levels (price fields populated)
    assert len(ctx.levels) == 2
    prices = {lv["price"] for lv in ctx.levels}
    assert 240.0 in prices  # from setup entry_low
    assert 260.0 in prices  # from raw level


@pytest.mark.asyncio
async def test_get_youtube_context_all_zero_spans_returns_none():
    """When all mentions have evidence_spans_for_ticker=0, return None."""
    from consensus_engine.cross_reference import _get_youtube_context

    signals = [
        {"direction": "long", "conviction": "high", "channel_name": "Chan1",
         "video_id": "vid1", "video_title": "Title1", "evidence_spans_for_ticker": 0},
        {"direction": "short", "conviction": "medium", "channel_name": "Chan2",
         "video_id": "vid2", "video_title": "Title2", "evidence_spans_for_ticker": 0},
    ]

    with patch("consensus_engine.cross_reference.db") as mock_db:
        mock_db.get_youtube_signals_for_ticker = AsyncMock(return_value=signals)
        mock_db.get_youtube_evidence_for_ticker = AsyncMock(return_value=[])

        ctx = await _get_youtube_context("AAPL")

    assert ctx is None


@pytest.mark.asyncio
async def test_get_youtube_context_mixed_spans_only_passing_appear():
    """When some mentions pass the filter and others don't, only passing ones count."""
    from consensus_engine.cross_reference import _get_youtube_context

    signals = [
        {"direction": "long", "conviction": "high", "channel_name": "GoodChan",
         "video_id": "good1", "video_title": "Good Video", "evidence_spans_for_ticker": 2},
        {"direction": "short", "conviction": "low", "channel_name": "BadChan",
         "video_id": "bad1", "video_title": "Bad Video", "evidence_spans_for_ticker": 0},
    ]

    with patch("consensus_engine.cross_reference.db") as mock_db:
        mock_db.get_youtube_signals_for_ticker = AsyncMock(return_value=signals)
        mock_db.get_youtube_evidence_for_ticker = AsyncMock(return_value=[])

        ctx = await _get_youtube_context("MSFT")

    assert ctx is not None
    assert ctx.mention_count == 1
    assert ctx.videos == [{"video_id": "good1", "title": "Good Video", "channel_name": "GoodChan"}]
    assert "GoodChan" in ctx.channels
    assert "BadChan" not in ctx.channels


@pytest.mark.asyncio
async def test_get_youtube_context_all_passing_spans_unchanged():
    """When all mentions pass the filter, behaviour is same as before the filter."""
    from consensus_engine.cross_reference import _get_youtube_context

    signals = [
        {"direction": "long", "conviction": "high", "channel_name": "Chan1",
         "video_id": "v1", "video_title": "T1", "evidence_spans_for_ticker": 3},
        {"direction": "long", "conviction": "medium", "channel_name": "Chan2",
         "video_id": "v2", "video_title": "T2", "evidence_spans_for_ticker": 1},
    ]

    with patch("consensus_engine.cross_reference.db") as mock_db:
        mock_db.get_youtube_signals_for_ticker = AsyncMock(return_value=signals)
        mock_db.get_youtube_evidence_for_ticker = AsyncMock(return_value=[])

        ctx = await _get_youtube_context("NVDA")

    assert ctx is not None
    assert ctx.mention_count == 2
    assert len(ctx.videos) == 2
    assert ctx.direction.value == "long"


# ── #8 — named-insider enrichment of the SEC summary (flag-gated) ──────────

from consensus_engine import config as cfg
from consensus_engine.cross_reference import _run_sec_check

_FORM4_FILING = {
    "form": "4",
    "filing_date": "2026-06-05",
    "cik": "0000320193",
    "accession_number": "0000320193-26-000077",
    "primary_document": "form4.xml",
}


def _flag_on(monkeypatch):
    """Force only sec_watcher.named_insiders_in_alert ON; everything else default."""
    real_get = cfg.get

    def _get(key, default=None):
        if key == "sec_watcher.named_insiders_in_alert":
            return True
        return real_get(key, default)

    monkeypatch.setattr(cfg, "get", _get)


@pytest.mark.asyncio
async def test_named_insiders_flag_off_byte_identical(monkeypatch):
    """Flag OFF => summary stays exactly 'Form 4 x{n}', no enrichment fetch."""
    real_get = cfg.get
    monkeypatch.setattr(cfg, "get",
                        lambda k, d=None: False if k == "sec_watcher.named_insiders_in_alert"
                        else real_get(k, d))

    fetch = AsyncMock()
    with patch("consensus_engine.scanners.sec_edgar.check_recent_filings",
               new=AsyncMock(return_value=[_FORM4_FILING, dict(_FORM4_FILING)])), \
         patch("consensus_engine.scanners.sec_edgar.fetch_form4_details", new=fetch):
        has_filing, summary = await _run_sec_check("AAPL")

    assert has_filing is True
    assert summary == "Form 4 x2 (insider trading)"
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_named_insiders_flag_on_cfo_open_market_sell(monkeypatch):
    """Flag ON + CFO open-market sell => summary names insider, role, 'sold', figures."""
    _flag_on(monkeypatch)

    txs = [{
        "reporter_name": "Doe Jane",
        "title": "CFO",
        "security": "Common Stock",
        "date": "2026-06-05",
        "shares": 240000.0,
        "price": 52.5,
        "direction": "Sell",
        "transaction_type": "Open Market Sale",
    }]

    with patch("consensus_engine.scanners.sec_edgar.check_recent_filings",
               new=AsyncMock(return_value=[_FORM4_FILING])), \
         patch("consensus_engine.scanners.sec_edgar.fetch_form4_details",
               new=AsyncMock(return_value=txs)), \
         patch("consensus_engine.utils.rate_limiter.rate_limiter.acquire",
               new=AsyncMock(return_value=True)):
        has_filing, summary = await _run_sec_check("AAPL")

    assert has_filing is True
    # Original count line preserved
    assert "Form 4 x1 (insider trading)" in summary
    # Named-insider enrichment present
    assert "Jane Doe" in summary  # _fmt_insider_name reverses LAST FIRST
    assert "CFO" in summary
    assert "sold" in summary
    assert "240,000 sh" in summary
    # ~$12.6M open-market value (240000 * 52.5 = 12,600,000)
    assert "12,600,000" in summary
    assert "⭐" in summary  # CFO highlighted


@pytest.mark.asyncio
async def test_named_insiders_flag_on_routine_only_collapses(monkeypatch):
    """Flag ON + only routine awards/exercises => collapses to a count, no names."""
    _flag_on(monkeypatch)

    txs = [
        {
            "reporter_name": "SMITH JOHN", "title": "Director",
            "security": "Common Stock", "date": "2026-06-05",
            "shares": 1000.0, "price": 0.0, "direction": "Buy",
            "transaction_type": "Award/Grant",
        },
        {
            "reporter_name": "SMITH JOHN", "title": "Director",
            "security": "Common Stock", "date": "2026-06-05",
            "shares": 500.0, "price": 50.0, "direction": "Sell",
            "transaction_type": "Option Exercise",
        },
    ]

    with patch("consensus_engine.scanners.sec_edgar.check_recent_filings",
               new=AsyncMock(return_value=[_FORM4_FILING])), \
         patch("consensus_engine.scanners.sec_edgar.fetch_form4_details",
               new=AsyncMock(return_value=txs)), \
         patch("consensus_engine.utils.rate_limiter.rate_limiter.acquire",
               new=AsyncMock(return_value=True)):
        has_filing, summary = await _run_sec_check("AAPL")

    assert has_filing is True
    assert "Form 4 x1 (insider trading)" in summary
    # No open-market trades => collapse to a count, no insider name rendered
    assert "2 routine award/exercise(s)" in summary
    assert "John Smith" not in summary
    assert "sold" not in summary
    assert "bought" not in summary
