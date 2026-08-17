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
            "action": "buy_to_open",
            "strategy": "single_leg",
            "leg_count": 1,
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
    assert tweet.options.action == "buy_to_open"
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


def test_ticker_views_keep_separate_exact_clauses_for_multi_ticker_post():
    text = "$AMD broke resistance. $NVDA lost support after guidance."
    amd_reason = "$AMD broke resistance"
    nvda_reason = "$NVDA lost support after guidance"
    payload = {
        "type": "A",
        "tickers": ["AMD", "NVDA"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "medium",
        "summary": "Mixed multi-ticker setups",
        "ticker_views": [
            {
                "ticker": "AMD", "direction": "long",
                "reason_text": amd_reason,
                "reason_start": text.index(amd_reason),
                "reason_end": text.index(amd_reason) + len(amd_reason),
                "reason_kind": "setup", "decision_code": "explicit_clause",
            },
            {
                "ticker": "NVDA", "direction": "short",
                "reason_text": nvda_reason,
                "reason_start": text.index(nvda_reason),
                "reason_end": text.index(nvda_reason) + len(nvda_reason),
                "reason_kind": "setup", "decision_code": "explicit_clause",
            },
        ],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    views = {view.ticker: view for view in tweet.ticker_views}
    assert views["AMD"].direction == "long"
    assert views["AMD"].reason_text == amd_reason
    assert views["NVDA"].direction == "short"
    assert views["NVDA"].reason_text == nvda_reason
    assert tweet.direction == Direction.LONG  # legacy instant-alert meaning is untouched


@pytest.mark.parametrize(
    "decision_code",
    ["generic_activity", "neutral", "unsided_option", "multi_ticker_ambiguous"],
)
def test_unsafe_ticker_views_fail_closed(decision_code):
    text = "$NVDA options activity is elevated"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "activity",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": text,
            "reason_start": 0, "reason_end": len(text),
            "reason_kind": "position", "decision_code": decision_code,
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.direction == "unclear"
    assert view.reason_text is None
    assert view.reason_start is None
    assert view.reason_end is None


@pytest.mark.parametrize(
    "view_override",
    [
        {},
        {"reason_text": "paraphrased reason"},
        {"ticker": "AMD"},
    ],
)
def test_missing_or_malformed_ticker_view_fails_closed(view_override):
    text = "$NVDA broke resistance"
    valid = {
        "ticker": "NVDA", "direction": "long", "reason_text": text,
        "reason_start": 0, "reason_end": len(text),
        "reason_kind": "setup", "decision_code": "explicit_clause",
    }
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "breakout",
        "ticker_views": [] if not view_override else [{**valid, **view_override}],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.direction == "unclear"
    assert view.reason_text is None


def test_unsided_option_clause_fails_closed_even_if_model_calls_it_explicit():
    text = "$NVDA 150 calls expiring Friday"
    payload = {
        "type": "C", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": True, "strike": 150, "type": "call"},
        "conviction": "medium", "summary": "NVDA calls",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": text,
            "reason_start": 0, "reason_end": len(text),
            "reason_kind": "position", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].decision_code == "unsided_option"


def test_unsided_option_elsewhere_in_source_discards_selected_reason():
    text = "$NVDA reports earnings tomorrow; 150 calls expire Friday"
    reason = "$NVDA reports earnings tomorrow"
    payload = {
        "type": "C", "tickers": ["NVDA"], "direction": "neutral",
        "options": {"present": True, "strike": 150, "type": "call"},
        "conviction": "medium", "summary": "earnings and options",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "unclear", "reason_text": reason,
            "reason_start": 0, "reason_end": len(reason),
            "reason_kind": "event_claim", "decision_code": "reason_only",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].reason_text is None
    assert tweet.ticker_views[0].decision_code == "unsided_option"


def test_sided_option_elsewhere_in_source_keeps_exact_reason_eligible():
    text = "$NVDA reports earnings tomorrow; buying 150 calls for Friday"
    reason = "$NVDA reports earnings tomorrow"
    payload = {
        "type": "C", "tickers": ["NVDA"], "direction": "neutral",
        "options": {"present": True, "strike": 150, "type": "call", "action": "buy_to_open"},
        "conviction": "medium", "summary": "earnings and options",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "unclear", "reason_text": reason,
            "reason_start": 0, "reason_end": len(reason),
            "reason_kind": "event_claim", "decision_code": "reason_only",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].reason_text == reason
    assert tweet.ticker_views[0].decision_code == "reason_only"


def test_event_claim_keeps_exact_span_for_visible_attribution():
    text = "$RDDT added to the S&P 500; buying shares"
    reason = "$RDDT added to the S&P 500; buying shares"
    payload = {
        "type": "A", "tickers": ["RDDT"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "index addition",
        "ticker_views": [{
            "ticker": "RDDT", "direction": "long", "reason_text": reason,
            "reason_start": 0, "reason_end": len(reason),
            "reason_kind": "event_claim", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].reason_kind == "event_claim"
    assert tweet.ticker_views[0].reason_text == reason


def test_multi_ticker_span_with_two_symbols_fails_closed():
    text = "$AMD broke resistance while $NVDA lost support"
    payload = {
        "type": "A", "tickers": ["AMD", "NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "two setups",
        "ticker_views": [{
            "ticker": "AMD", "direction": "long", "reason_text": text,
            "reason_start": 0, "reason_end": len(text),
            "reason_kind": "setup", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    views = {view.ticker: view for view in tweet.ticker_views}
    assert views["AMD"].direction == "unclear"
    assert views["AMD"].decision_code == "multi_ticker_ambiguous"
    assert views["NVDA"].direction == "unclear"


def test_source_ticker_omitted_by_model_still_makes_clause_ambiguous():
    text = "$AMD broke resistance while $NVDA lost support"
    payload = {
        "type": "A", "tickers": ["AMD"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "setup",
        "ticker_views": [{
            "ticker": "AMD", "direction": "long", "reason_text": "broke resistance",
            "reason_start": text.index("broke resistance"),
            "reason_end": text.index("broke resistance") + len("broke resistance"),
            "reason_kind": "setup", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].reason_text is None
    assert tweet.ticker_views[0].decision_code == "multi_ticker_ambiguous"


@pytest.mark.asyncio
async def test_parse_call_failure_keeps_legacy_direction_but_group_view_is_unclear():
    text = "$NVDA bullish breakout"
    with patch(
        "consensus_engine.analysis.tweet_parser.process_multimodal_tweet",
        new_callable=AsyncMock,
        side_effect=RuntimeError("model unavailable"),
    ):
        tweet = await parse_tweet("https://example.test/post", "analyst", text)

    assert tweet.direction == Direction.LONG
    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].reason_text is None


def test_unique_exact_reason_repairs_incorrect_model_offsets():
    text = "$NVDA raised guidance after earnings"
    reason = "raised guidance after earnings"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "guidance",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": reason,
            "reason_start": 0, "reason_end": 4,
            "reason_kind": "event_claim", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.reason_text == reason
    assert view.reason_start == text.index(reason)
    assert view.reason_end == text.index(reason) + len(reason)


def test_unique_whitespace_normalized_reason_maps_to_exact_source_span():
    text = "$NVDA broke resistance\nafter   earnings"
    model_reason = "$NVDA broke resistance after earnings"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "breakout",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": model_reason,
            "reason_start": 0, "reason_end": len(model_reason),
            "reason_kind": "setup", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.reason_text == text
    assert view.reason_start == 0
    assert view.reason_end == len(text)


def test_repeated_whitespace_normalized_reason_fails_closed():
    model_reason = "$NVDA broke resistance"
    text = "$NVDA broke   resistance then $NVDA broke\nresistance"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "breakout",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": model_reason,
            "reason_start": 0, "reason_end": len(model_reason),
            "reason_kind": "setup", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].reason_text is None
    assert tweet.ticker_views[0].decision_code == "invalid_span"


def test_exact_reason_plus_whitespace_equivalent_duplicate_fails_closed():
    reason = "$NVDA broke resistance"
    text = f"{reason} then $NVDA broke   resistance"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "breakout",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": reason,
            "reason_start": 0, "reason_end": len(reason),
            "reason_kind": "setup", "decision_code": "explicit_clause",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    assert tweet.ticker_views[0].direction == "unclear"
    assert tweet.ticker_views[0].reason_text is None
    assert tweet.ticker_views[0].decision_code == "invalid_span"


def test_repeated_exact_reason_is_ambiguous_and_fails_closed():
    text = "$NVDA breakout then $NVDA breakout"
    reason = "$NVDA breakout"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "neutral",
        "options": {"present": False}, "conviction": "medium", "summary": "repeated",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "unclear", "reason_text": reason,
            "reason_start": 0, "reason_end": len(reason),
            "reason_kind": "setup", "decision_code": "reason_only",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.direction == "unclear"
    assert view.reason_text is None
    assert view.decision_code == "invalid_span"


def test_exact_reason_can_be_kept_when_direction_is_unclear():
    text = "$NVDA reports earnings tomorrow"
    reason = "$NVDA reports earnings tomorrow"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "neutral",
        "options": {"present": False}, "conviction": "medium", "summary": "earnings",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "unclear", "reason_text": reason,
            "reason_start": 0, "reason_end": len(reason),
            "reason_kind": "event_claim", "decision_code": "reason_only",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.direction == "unclear"
    assert view.reason_text == reason
    assert view.decision_code == "reason_only"


def test_supported_direction_can_be_kept_without_a_reason():
    text = "$NVDA bullish above 150"
    payload = {
        "type": "A", "tickers": ["NVDA"], "direction": "long",
        "options": {"present": False}, "conviction": "medium", "summary": "bullish",
        "ticker_views": [{
            "ticker": "NVDA", "direction": "long", "reason_text": None,
            "reason_start": None, "reason_end": None,
            "reason_kind": "none", "decision_code": "direction_only",
        }],
    }

    tweet = _parse_llm_response(payload, "https://example.test/post", "analyst", text)

    view = tweet.ticker_views[0]
    assert view.direction == "long"
    assert view.reason_text is None
    assert view.decision_code == "direction_only"


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

    with patch("consensus_engine.analysis.tweet_parser.process_multimodal_tweet",
               new_callable=AsyncMock, return_value=json.loads(mock_response)):
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
