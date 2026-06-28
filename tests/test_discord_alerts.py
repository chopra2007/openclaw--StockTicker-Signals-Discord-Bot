"""Tests for two-phase Discord alert formatting."""
import pytest
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, TweetType, Direction, Conviction,
    CrossReferenceResult, ScoreBreakdown, TechnicalResult, TechnicalFilter,
    OptionsResult,
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
    assert "WallStreetSilv" in embed["author"]["name"]
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


def test_format_detail_followup_options_flow_pct_split():
    """#53: the Options Flow field shows an intuitive call/put % split (from raw
    volumes) and a vol/OI label — not the raw P/C ratio."""
    breakdown = ScoreBreakdown(base=30, options_flow=10)
    opt = OptionsResult(
        ticker="GOOGL", unusual_calls=True, unusual_puts=True,
        max_call_ratio=17.3, max_put_ratio=10.9,
        put_call_ratio=0.56, total_call_vol=27156.0, total_put_vol=15322.0,
    )
    xref = CrossReferenceResult(
        ticker="GOOGL", breakdown=breakdown,
        catalyst_summary="x", catalyst_type="x",
        technical=None, other_analysts=[], social_summary="", llm_reasoning="",
        options=opt,
    )
    flow = next(f for f in format_detail_followup(xref)["fields"]
                if f["name"] == "Options Flow")
    assert "🟢 Calls 64% / 🔴 Puts 36% (today's volume)" in flow["value"]
    assert "vol/OI" in flow["value"]
    assert "P/C ratio:" not in flow["value"]


@pytest.mark.asyncio
async def test_trend_digest_drops_momentum(monkeypatch):
    """#53: the Reddit trend digest no longer renders the unitless momentum
    number, but still shows mentions and authors."""
    import consensus_engine.alerts.discord as d
    monkeypatch.setattr(d.cfg, "dry_run", False, raising=False)
    monkeypatch.setattr(d.cfg, "get_api_key", lambda k: "tok")
    monkeypatch.setattr(d.cfg, "get",
                        lambda k, default=None: "123456789012345678" if "channel" in k else default)
    captured = {}

    async def fake_send(url, headers, payload):
        captured["payload"] = payload
        return {"id": "x"}

    monkeypatch.setattr(d, "_safe_send", fake_send)
    trending = [{"ticker": "NVDA", "mentions": 10, "unique_authors": 5, "momentum": 2.0}]
    await d.send_trend_digest(trending)
    desc = captured["payload"]["embeds"][0]["description"]
    assert "momentum" not in desc.lower()
    assert "10 mentions" in desc
    assert "5 authors" in desc
