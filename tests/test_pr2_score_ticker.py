"""PR2 regression tests: score_ticker() refactor from cross_reference().

Validates the tweetless scorer extraction:
  - score_ticker() runs without a tweet
  - Same mocks → identical breakdown.total in both score_ticker() and cross_reference()
  - score_ticker() does NOT consult/write the xref cache
  - cross_reference() still caches (cache hit on second call)
  - score_ticker() handles all-empty source data without exception
"""
import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine.models import (
    ParsedTweet, TweetType, Direction, Conviction,
    CatalystResult, TechnicalResult, TechnicalFilter,
)
from consensus_engine.cross_reference import (
    cross_reference, score_ticker, ScoreTickerResult,
)
from consensus_engine.utils.xref_cache import clear_xref_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_xref_cache()
    yield
    clear_xref_cache()


def _build_tweet(*, base_conviction=Conviction.HIGH, analyst="unusual_whales") -> ParsedTweet:
    return ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst=analyst,
        raw_text="$NVDA breakout",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=base_conviction,
        summary="NVDA breakout",
    )


def _patches(*, news_cascade_mock=None, technical_mock=None, options_mock=None):
    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="NVDA earnings beat",
        catalyst_type="Earnings Beat", news_sources=["reuters.com"],
        source_urls=["https://reuters.com/nvda"], confidence=0.8,
    )
    if news_cascade_mock is None:
        news_cascade_mock = AsyncMock(return_value=mock_catalyst)
    if technical_mock is None:
        technical_mock = AsyncMock(return_value=None)
    if options_mock is None:
        options_mock = AsyncMock(return_value=None)
    return [
        patch("consensus_engine.cross_reference._run_news_cascade", news_cascade_mock),
        patch("consensus_engine.cross_reference._run_sec_check",
              new_callable=AsyncMock, return_value=(False, "")),
        patch("consensus_engine.cross_reference._run_social_check",
              new_callable=AsyncMock, return_value={"apewisdom": 3}),
        patch("consensus_engine.cross_reference._run_technical", technical_mock),
        patch("consensus_engine.cross_reference._run_other_analysts",
              new_callable=AsyncMock,
              return_value={"aligned": ["CheddarFlow"], "opposing": []}),
        patch("consensus_engine.cross_reference._run_llm_score",
              new_callable=AsyncMock, return_value=(75.0, "Strong setup")),
        patch("consensus_engine.cross_reference._run_options_check", options_mock),
        patch("consensus_engine.cross_reference._get_youtube_context",
              new_callable=AsyncMock, return_value=None),
    ]


@pytest.mark.asyncio
async def test_score_ticker_runs_without_tweet():
    """score_ticker() should produce a populated ScoreTickerResult with default args."""
    stack_patches = _patches()
    for p in stack_patches:
        p.start()
    try:
        result = await score_ticker("NVDA")
    finally:
        for p in stack_patches:
            p.stop()

    assert isinstance(result, ScoreTickerResult)
    assert result.ticker == "NVDA"
    assert result.breakdown.base == 0  # default base_score
    assert result.breakdown.news_catalyst == 25  # Earnings Beat tier
    assert result.breakdown.additional_analysts == 20  # 1 analyst
    assert result.breakdown.social_apewisdom == 10
    assert result.breakdown.llm_boost > 0
    assert result.catalyst is not None
    assert result.catalyst.catalyst_type == "Earnings Beat"
    assert result.sec_hit is False
    assert result.other_analysts == ["CheddarFlow"]
    assert result.consolidation_result is not None
    assert "news_cascade_ms" in result.metrics


@pytest.mark.asyncio
async def test_score_ticker_breakdown_matches_cross_reference():
    """REFACTOR REGRESSION: same mocked sources → identical breakdown.total
    (modulo base_score) between score_ticker() and cross_reference().
    """
    tweet = _build_tweet()  # base_score=30 (Conviction.HIGH)

    # Run score_ticker with the same base_score / direction / analyst as the tweet.
    stack_patches = _patches()
    for p in stack_patches:
        p.start()
    try:
        st_result = await score_ticker(
            "NVDA",
            base_score=tweet.base_score,
            direction=tweet.direction.value,
            exclude_analyst=tweet.analyst,
        )
    finally:
        for p in stack_patches:
            p.stop()

    # Now run cross_reference with the same mock set.
    stack_patches = _patches() + [
        patch("consensus_engine.cross_reference.get_cached_xref",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference.cache_xref", new_callable=AsyncMock),
    ]
    for p in stack_patches:
        p.start()
    try:
        xref_result = await cross_reference("NVDA", tweet)
    finally:
        for p in stack_patches:
            p.stop()

    # The breakdown.total must match — score_ticker IS the scorer.
    assert st_result.breakdown.total == xref_result.breakdown.total
    assert st_result.breakdown.base == xref_result.breakdown.base
    assert st_result.breakdown.news_catalyst == xref_result.breakdown.news_catalyst
    assert st_result.breakdown.additional_analysts == xref_result.breakdown.additional_analysts
    assert st_result.breakdown.social_apewisdom == xref_result.breakdown.social_apewisdom
    assert st_result.breakdown.llm_boost == xref_result.breakdown.llm_boost
    assert st_result.final_score == xref_result.final_score


@pytest.mark.asyncio
async def test_score_ticker_no_cache_path():
    """score_ticker() must NOT consult the xref cache — calling it twice
    should re-run _run_news_cascade twice (no caching)."""
    cascade_mock = AsyncMock(return_value=CatalystResult(
        ticker="NVDA", catalyst_summary="x", catalyst_type="Earnings Beat",
        news_sources=["s"], source_urls=["u"], confidence=0.8,
    ))
    stack_patches = _patches(news_cascade_mock=cascade_mock)
    for p in stack_patches:
        p.start()
    try:
        await score_ticker("NVDA")
        await score_ticker("NVDA")
    finally:
        for p in stack_patches:
            p.stop()

    assert cascade_mock.call_count == 2  # No cache → called twice


@pytest.mark.asyncio
async def test_cross_reference_still_caches():
    """cross_reference() must still cache — second call hits cache, _run_news_cascade
    is invoked only once."""
    tweet = _build_tweet()
    cascade_mock = AsyncMock(return_value=CatalystResult(
        ticker="NVDA", catalyst_summary="x", catalyst_type="Earnings Beat",
        news_sources=["s"], source_urls=["u"], confidence=0.8,
    ))
    stack_patches = _patches(news_cascade_mock=cascade_mock)
    for p in stack_patches:
        p.start()
    try:
        # First call populates the L1 cache; second call must hit it.
        result1 = await cross_reference("NVDA", tweet)
        result2 = await cross_reference("NVDA", tweet)
    finally:
        for p in stack_patches:
            p.stop()

    # Cache hit means _run_news_cascade only fired once across two calls.
    assert cascade_mock.call_count == 1
    assert result1.final_score == result2.final_score


@pytest.mark.asyncio
async def test_score_ticker_handles_empty_sources():
    """All sources empty/None → no exception, breakdown shows zeros where appropriate."""
    stack_patches = [
        patch("consensus_engine.cross_reference._run_news_cascade",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._run_sec_check",
              new_callable=AsyncMock, return_value=(False, "")),
        patch("consensus_engine.cross_reference._run_social_check",
              new_callable=AsyncMock, return_value={}),
        patch("consensus_engine.cross_reference._run_technical",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._run_other_analysts",
              new_callable=AsyncMock, return_value=[]),
        patch("consensus_engine.cross_reference._run_llm_score",
              new_callable=AsyncMock, return_value=(0.0, "")),
        patch("consensus_engine.cross_reference._run_options_check",
              new_callable=AsyncMock, return_value=None),
        patch("consensus_engine.cross_reference._get_youtube_context",
              new_callable=AsyncMock, return_value=None),
    ]
    for p in stack_patches:
        p.start()
    try:
        result = await score_ticker("XYZ", base_score=0)
    finally:
        for p in stack_patches:
            p.stop()

    assert result.breakdown.base == 0
    assert result.breakdown.news_catalyst == 0
    assert result.breakdown.sec_filing == 0
    assert result.breakdown.additional_analysts == 0
    assert result.breakdown.technical == 0
    assert result.breakdown.options_flow == 0
    assert result.breakdown.social_apewisdom == 0
    assert result.breakdown.social_stocktwits == 0
    assert result.breakdown.social_reddit == 0
    assert result.breakdown.google_trends == 0
    assert result.catalyst is None
    assert result.technical is None
    assert result.options is None
    assert result.youtube is None
    assert result.other_analysts == []
