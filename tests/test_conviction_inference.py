"""Tests for Q9 conviction inference heuristic.

Spec: .omc/specs/milestone1/01-conviction-parser.md

Background: 99.1% of alerts ship base_score=25 (MEDIUM) because the LLM defaults
to "medium" with no rubric and the fallback parser hard-codes MEDIUM. This spec
adds a deterministic heuristic that resolves HIGH/LOW from text + options
shape, and wins over the LLM only when decisive.
"""
import json

import pytest

from consensus_engine.models import Conviction, Direction, OptionsDetail, TweetType
from consensus_engine.analysis.tweet_parser import (
    _fallback_parse,
    _infer_conviction,
    _parse_llm_response,
    _resolve_conviction,
)


# ---------------------------------------------------------------------------
# _infer_conviction — pure heuristic table
# ---------------------------------------------------------------------------

def _opts(strike=None, expiry=None, target=None, profit_pct=None, present=True):
    return OptionsDetail(
        present=present,
        strike=strike,
        expiry=expiry,
        option_type="call",
        target_price=target,
        profit_target_pct=profit_pct,
    )


class TestInferConvictionHigh:
    def test_options_with_full_levels_and_sl(self):
        text = "$MU 4/24 490C at 471 | 🎯 490, 500 SL 460"
        opts = _opts(strike=490, expiry="2026-04-24", target=490)
        assert _infer_conviction(text, opts) == Conviction.HIGH

    def test_options_with_profit_target_and_stop(self):
        text = "Buying TSLA 500c — stop at 490, taking profits at +100%"
        opts = _opts(strike=500, expiry="2026-03-28", profit_pct=100)
        assert _infer_conviction(text, opts) == Conviction.HIGH

    def test_explicit_high_conviction_keyword(self):
        text = "$NVDA highest conviction long here, breakout setup"
        assert _infer_conviction(text, None) == Conviction.HIGH

    def test_yolo_keyword(self):
        text = "$AMD YOLO calls"
        assert _infer_conviction(text, None) == Conviction.HIGH

    def test_loaded_up_keyword(self):
        text = "Loaded up on $SPY puts at the open"
        assert _infer_conviction(text, None) == Conviction.HIGH

    def test_entry_target_sl_trio_no_options(self):
        text = "$SPX 7180 at 7100 🎯 7172, 7200 SL 7055"
        assert _infer_conviction(text, None) == Conviction.HIGH


class TestInferConvictionLow:
    def test_watching_keyword(self):
        text = "$AAPL watching for a reversal here"
        assert _infer_conviction(text, None) == Conviction.LOW

    def test_might_keyword(self):
        text = "Might buy $TSLA if it holds 400"
        assert _infer_conviction(text, None) == Conviction.LOW

    def test_considering_keyword(self):
        text = "Considering some $QQQ puts into the close"
        assert _infer_conviction(text, None) == Conviction.LOW

    def test_on_watch_keyword(self):
        text = "$NVDA on watch over 950"
        assert _infer_conviction(text, None) == Conviction.LOW


class TestInferConvictionMedium:
    def test_plain_ticker_callout_is_medium(self):
        text = "$AAPL looking strong, buying calls"
        assert _infer_conviction(text, None) == Conviction.MEDIUM

    def test_directional_with_no_signals(self):
        text = "$MSFT bullish breakout"
        assert _infer_conviction(text, None) == Conviction.MEDIUM

    def test_options_present_but_no_sl(self):
        text = "Got some $AMD 200c for next week"
        opts = _opts(strike=200, expiry="2026-05-02")
        assert _infer_conviction(text, opts) == Conviction.MEDIUM

    def test_empty_text(self):
        assert _infer_conviction("", None) == Conviction.MEDIUM


# ---------------------------------------------------------------------------
# _resolve_conviction — heuristic-vs-LLM precedence
# ---------------------------------------------------------------------------

class TestResolveConviction:
    def test_heuristic_high_wins_over_llm_medium(self):
        assert _resolve_conviction(Conviction.MEDIUM, Conviction.HIGH) == Conviction.HIGH

    def test_heuristic_low_wins_over_llm_medium(self):
        assert _resolve_conviction(Conviction.MEDIUM, Conviction.LOW) == Conviction.LOW

    def test_heuristic_high_wins_over_llm_low(self):
        assert _resolve_conviction(Conviction.LOW, Conviction.HIGH) == Conviction.HIGH

    def test_heuristic_low_wins_over_llm_high(self):
        assert _resolve_conviction(Conviction.HIGH, Conviction.LOW) == Conviction.LOW

    def test_indecisive_heuristic_preserves_llm_high(self):
        assert _resolve_conviction(Conviction.HIGH, Conviction.MEDIUM) == Conviction.HIGH

    def test_indecisive_heuristic_preserves_llm_low(self):
        assert _resolve_conviction(Conviction.LOW, Conviction.MEDIUM) == Conviction.LOW

    def test_both_medium(self):
        assert _resolve_conviction(Conviction.MEDIUM, Conviction.MEDIUM) == Conviction.MEDIUM


# ---------------------------------------------------------------------------
# Integration with _parse_llm_response
# ---------------------------------------------------------------------------

class TestParseLlmResponseConvictionIntegration:
    def test_llm_medium_upgraded_when_heuristic_high(self):
        """LLM says medium but text matches HIGH heuristic — heuristic wins."""
        raw = json.dumps({
            "type": "A",
            "tickers": ["NVDA"],
            "direction": "long",
            "options": {"present": False},
            "conviction": "medium",
            "summary": "NVDA highest conviction breakout",
        })
        tweet = _parse_llm_response(
            raw, "https://x.com/user/1", "analyst",
            "$NVDA highest conviction long here",
        )
        assert tweet.conviction == Conviction.HIGH
        assert tweet.base_score == 30

    def test_llm_medium_downgraded_when_heuristic_low(self):
        raw = json.dumps({
            "type": "A",
            "tickers": ["AAPL"],
            "direction": "long",
            "options": {"present": False},
            "conviction": "medium",
            "summary": "AAPL watch",
        })
        tweet = _parse_llm_response(
            raw, "https://x.com/user/2", "analyst",
            "$AAPL watching for a reversal here",
        )
        assert tweet.conviction == Conviction.LOW
        assert tweet.base_score == 20

    def test_llm_high_preserved_when_heuristic_medium(self):
        """LLM said high, heuristic indecisive — LLM is preserved."""
        raw = json.dumps({
            "type": "A",
            "tickers": ["AMD"],
            "direction": "long",
            "options": {"present": False},
            "conviction": "high",
            "summary": "AMD breakout",
        })
        tweet = _parse_llm_response(
            raw, "https://x.com/user/3", "analyst",
            "$AMD bullish breakout",
        )
        assert tweet.conviction == Conviction.HIGH
        assert tweet.base_score == 30

    def test_llm_medium_preserved_when_heuristic_medium(self):
        """Existing baseline behaviour: plain ticker callout, LLM=medium → MEDIUM."""
        raw = json.dumps({
            "type": "A",
            "tickers": ["NVDA"],
            "direction": "long",
            "options": {"present": False},
            "conviction": "medium",
            "summary": "Going long NVDA",
        })
        tweet = _parse_llm_response(
            raw, "https://x.com/user/4", "analyst",
            "original text",
        )
        assert tweet.conviction == Conviction.MEDIUM
        assert tweet.base_score == 25


# ---------------------------------------------------------------------------
# Fallback path — replaces hard-coded MEDIUM with heuristic
# ---------------------------------------------------------------------------

class TestFallbackParseConviction:
    def test_fallback_high_keyword(self):
        tweet = _fallback_parse(
            "https://x.com/t/1", "analyst",
            "$NVDA highest conviction long, loading up",
        )
        assert tweet.conviction == Conviction.HIGH

    def test_fallback_low_keyword(self):
        tweet = _fallback_parse(
            "https://x.com/t/2", "analyst",
            "$AAPL watching here, might add",
        )
        assert tweet.conviction == Conviction.LOW

    def test_fallback_medium_default(self):
        """Existing test_parse_llm_response_malformed_json must stay green."""
        tweet = _fallback_parse(
            "https://x.com/t/3", "analyst",
            "$AAPL looking strong, buying calls",
        )
        assert tweet.conviction == Conviction.MEDIUM
        assert tweet.tweet_type == TweetType.TICKER_CALLOUT
