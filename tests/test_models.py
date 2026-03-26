"""Tests for new data models."""
import time
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, CrossReferenceResult,
    ScoreBreakdown, AlertMessage, TweetType, Conviction, Direction,
)


def test_parsed_tweet_actionable_type_a():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/123",
        analyst="unusual_whales",
        raw_text="$NVDA looking strong, going long",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.MEDIUM,
        summary="Going long NVDA",
    )
    assert tweet.is_actionable is True
    assert tweet.base_score == 25


def test_parsed_tweet_actionable_type_c():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/456",
        analyst="OptionMillionaire",
        raw_text="Buying TSLA 500c Friday",
        tweet_type=TweetType.OPTIONS_TRADE,
        tickers=["TSLA"],
        direction=Direction.LONG,
        options=OptionsDetail(
            present=True,
            strike=500.0,
            expiry="2026-03-28",
            option_type="call",
            target_price=510.0,
            profit_target_pct=100.0,
        ),
        conviction=Conviction.HIGH,
        summary="Buying TSLA 500c Friday expiry targeting 510",
    )
    assert tweet.is_actionable is True
    assert tweet.base_score == 30
    assert tweet.options.strike == 500.0


def test_parsed_tweet_not_actionable_type_b():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/789",
        analyst="NickTimiraos",
        raw_text="Fed signaling rate pause at next meeting",
        tweet_type=TweetType.MACRO,
        tickers=[],
        direction=Direction.NEUTRAL,
        options=None,
        conviction=Conviction.LOW,
        summary="Fed rate pause signal",
    )
    assert tweet.is_actionable is False


def test_parsed_tweet_not_actionable_type_d():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/101",
        analyst="Walter_Bloomberg",
        raw_text="Market looking weak into close",
        tweet_type=TweetType.SENTIMENT,
        tickers=[],
        direction=Direction.NEUTRAL,
        options=None,
        conviction=Conviction.LOW,
        summary="Bearish market sentiment",
    )
    assert tweet.is_actionable is False


def test_score_breakdown_total():
    breakdown = ScoreBreakdown(
        base=30,
        additional_analysts=40,
        news_catalyst=15,
        sec_filing=0,
        social_apewisdom=10,
        social_stocktwits=0,
        social_reddit=0,
        google_trends=0,
        technical=10,
        llm_boost=12,
    )
    assert breakdown.total == 117


def test_cross_reference_result():
    breakdown = ScoreBreakdown(base=25)
    result = CrossReferenceResult(
        ticker="NVDA",
        breakdown=breakdown,
        catalyst_summary="",
        catalyst_type="",
        catalyst_sources=[],
        catalyst_urls=[],
        technical=None,
        other_analysts=[],
        social_summary="",
        llm_reasoning="",
    )
    assert result.final_score == 25


def test_alert_message():
    msg = AlertMessage(
        ticker="TSLA",
        analyst="OptionMillionaire",
        instant_msg_id="123456",
        followup_msg_id=None,
        base_score=30,
        final_score=30,
    )
    assert msg.followup_msg_id is None
    assert msg.final_score == 30
