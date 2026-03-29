"""Tests for LLM tweet parser."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from consensus_engine.models import TweetType, Direction, Conviction
from consensus_engine.analysis.tweet_parser import parse_tweet, _build_parser_prompt, _parse_llm_response


def test_build_parser_prompt():
    prompt = _build_parser_prompt("unusual_whales", "$NVDA unusual call activity 950 strike")
    assert "unusual_whales" in prompt
    assert "$NVDA" in prompt
    assert "950" in prompt


def test_parse_llm_response_type_a():
    raw = json.dumps({
        "type": "A",
        "tickers": ["NVDA"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "medium",
        "summary": "Going long NVDA on unusual activity"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/123", "user", "original text")
    assert tweet.tweet_type == TweetType.TICKER_CALLOUT
    assert tweet.tickers == ["NVDA"]
    assert tweet.direction == Direction.LONG
    assert tweet.conviction == Conviction.MEDIUM
    assert tweet.is_actionable is True


def test_parse_llm_response_type_c_options():
    raw = json.dumps({
        "type": "C",
        "tickers": ["TSLA"],
        "direction": "long",
        "options": {
            "present": True,
            "strike": 500,
            "expiry": "2026-03-28",
            "type": "call",
            "target_price": 510,
            "profit_target_pct": 100
        },
        "conviction": "high",
        "summary": "Buying TSLA 500c Friday expiry, targeting 510"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/456", "OptionMillionaire", "original")
    assert tweet.tweet_type == TweetType.OPTIONS_TRADE
    assert tweet.options is not None
    assert tweet.options.strike == 500.0
    assert tweet.options.option_type == "call"
    assert tweet.options.target_price == 510.0
    assert tweet.is_actionable is True
    assert tweet.base_score == 30


def test_parse_llm_response_type_b():
    raw = json.dumps({
        "type": "B",
        "tickers": ["USO"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "medium",
        "summary": "Strait of Hormuz tensions bullish for oil"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/789", "analyst", "text")
    assert tweet.tweet_type == TweetType.MACRO
    assert tweet.is_actionable is False


def test_parse_llm_response_type_d():
    raw = json.dumps({
        "type": "D",
        "tickers": [],
        "direction": "neutral",
        "options": {"present": False},
        "conviction": "low",
        "summary": "Market looking weak"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/101", "analyst", "text")
    assert tweet.tweet_type == TweetType.SENTIMENT
    assert tweet.is_actionable is False


def test_parse_llm_response_malformed_json():
    """Malformed JSON should fall back to regex extraction."""
    tweet = _parse_llm_response(
        "not valid json at all",
        "https://x.com/user/999", "analyst",
        "$AAPL looking strong, buying calls"
    )
    assert tweet.tweet_type == TweetType.TICKER_CALLOUT
    assert tweet.conviction == Conviction.MEDIUM
    assert "AAPL" in tweet.tickers


def test_parse_llm_response_markdown_wrapped():
    """Handle LLM responses wrapped in ```json ... ```."""
    raw = '```json\n{"type":"A","tickers":["AMD"],"direction":"long","options":{"present":false},"conviction":"high","summary":"AMD breakout"}\n```'
    tweet = _parse_llm_response(raw, "https://x.com/user/555", "analyst", "AMD breakout")
    assert tweet.tweet_type == TweetType.TICKER_CALLOUT
    assert tweet.tickers == ["AMD"]


def test_fallback_parser_ignores_indicators():
    """Fallback regex parser should not extract indicator names as tickers."""
    from consensus_engine.analysis.tweet_parser import _fallback_parse
    tweet = _fallback_parse("https://x.com/test/1", "analyst", "RSI oversold on NVDA, MACD crossing")
    assert "NVDA" in tweet.tickers
    assert "RSI" not in tweet.tickers
    assert "MACD" not in tweet.tickers


def test_fallback_parser_no_tickers_returns_sentiment():
    """If no real tickers found, fallback should return SENTIMENT type."""
    from consensus_engine.analysis.tweet_parser import _fallback_parse
    tweet = _fallback_parse("https://x.com/test/2", "analyst", "RSI and MACD both looking weak today")
    assert tweet.tickers == []
    assert tweet.tweet_type == TweetType.SENTIMENT


@pytest.mark.asyncio
async def test_parse_tweet_llm_call():
    """Test full parse_tweet with mocked LLM."""
    mock_response = json.dumps({
        "type": "A",
        "tickers": ["NVDA"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "high",
        "summary": "NVDA breakout"
    })

    with patch("consensus_engine.analysis.tweet_parser._call_openrouter",
               new_callable=AsyncMock, return_value=mock_response):
        tweet = await parse_tweet(
            url="https://x.com/whales/123",
            analyst="unusual_whales",
            text="$NVDA breaking out, going long",
        )
        assert tweet.tickers == ["NVDA"]
        assert tweet.is_actionable is True


# ---------------------------------------------------------------------------
# Fallback direction detection
# ---------------------------------------------------------------------------

from consensus_engine.analysis.tweet_parser import _fallback_parse


def test_fallback_detects_long_direction():
    parsed = _fallback_parse("https://x.com/t/1", "analyst", "$NVDA bullish breakout, buying calls here")
    assert parsed.direction == Direction.LONG


def test_fallback_detects_short_direction():
    parsed = _fallback_parse("https://x.com/t/2", "analyst", "$TSLA puts printing, bearish setup")
    assert parsed.direction == Direction.SHORT


def test_fallback_defaults_to_neutral():
    parsed = _fallback_parse("https://x.com/t/3", "analyst", "$AAPL interesting chart pattern here")
    assert parsed.direction == Direction.NEUTRAL
