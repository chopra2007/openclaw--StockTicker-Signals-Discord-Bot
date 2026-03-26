"""Tests for two-phase Discord alert formatting."""
import pytest
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, TweetType, Direction, Conviction,
    CrossReferenceResult, ScoreBreakdown, TechnicalResult, TechnicalFilter,
)
from consensus_engine.alerts.discord import format_instant_ping, format_detail_followup


def test_format_instant_ping_type_a():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="WallStreetSilv",
        raw_text="Strait of Hormuz closing, going long USO",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["USO"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="Going long USO on geopolitical catalyst",
    )
    embed = format_instant_ping(tweet, current_price=78.15)
    assert "WallStreetSilv" in embed["title"]
    assert "USO" in embed["title"]
    assert "LONG" in embed["title"]
    assert "78.15" in embed["fields"][0]["value"]


def test_format_instant_ping_type_c_with_options():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/456",
        analyst="OptionMillionaire",
        raw_text="Buying TSLA 500c Friday targeting 510",
        tweet_type=TweetType.OPTIONS_TRADE,
        tickers=["TSLA"],
        direction=Direction.LONG,
        options=OptionsDetail(
            present=True, strike=500.0, expiry="2026-03-28",
            option_type="call", target_price=510.0, profit_target_pct=100.0,
        ),
        conviction=Conviction.HIGH,
        summary="Buying TSLA 500c Friday expiry targeting 510",
    )
    embed = format_instant_ping(tweet, current_price=487.32)
    fields_text = " ".join(f["value"] for f in embed["fields"])
    assert "500" in fields_text
    assert "call" in fields_text.lower() or "Call" in fields_text
    assert "510" in fields_text


def test_format_detail_followup():
    breakdown = ScoreBreakdown(
        base=30, additional_analysts=40, news_catalyst=15,
        social_apewisdom=10, social_stocktwits=10,
        technical=10, llm_boost=12,
    )
    tech = TechnicalResult(
        ticker="TSLA",
        filters=[
            TechnicalFilter(name="RVOL", value=2.8, threshold="> 2.0x", passed=True),
            TechnicalFilter(name="RSI", value=62.0, threshold="40-75", passed=True),
        ],
        price=487.32, volume=50000000, price_change_pct=3.2,
    )
    xref = CrossReferenceResult(
        ticker="TSLA",
        breakdown=breakdown,
        catalyst_summary="Tesla PT raised to $550",
        catalyst_type="Analyst Upgrade",
        catalyst_sources=["reuters.com"],
        catalyst_urls=["https://reuters.com/tsla"],
        technical=tech,
        other_analysts=["unusual_whales", "CheddarFlow"],
        social_summary="StockTwits trending, ApeWisdom #4",
        llm_reasoning="Strong multi-source confirmation",
    )
    embed = format_detail_followup(xref)
    assert "TSLA" in embed["title"]
    assert "127" in embed["title"]
    assert "Analyst Upgrade" in str(embed["fields"])
    assert "unusual_whales" in str(embed["fields"])


def test_format_detail_followup_no_signals():
    breakdown = ScoreBreakdown(base=25)
    xref = CrossReferenceResult(
        ticker="NVDA", breakdown=breakdown,
        catalyst_summary="", catalyst_type="",
        technical=None, other_analysts=[],
        social_summary="", llm_reasoning="",
    )
    embed = format_detail_followup(xref)
    assert "No additional signals" in str(embed["fields"]) or "25" in embed["title"]
