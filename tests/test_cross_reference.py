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
)


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

    with patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=mock_catalyst), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=False), \
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
    assert result.breakdown.news_catalyst == 15
    assert result.breakdown.additional_analysts == 20
    assert result.breakdown.social_apewisdom == 10
    assert result.breakdown.llm_boost > 0
    assert result.final_score > 30
