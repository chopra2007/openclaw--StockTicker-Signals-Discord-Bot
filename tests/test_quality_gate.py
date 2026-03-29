"""Tests for the pre-alert quality gate."""
import pytest
from consensus_engine.main import _passes_quality_gate
from consensus_engine.models import ParsedTweet, TweetType, Direction, Conviction


def _make_parsed(ticker="NVDA", direction=Direction.LONG, conviction=Conviction.MEDIUM,
                 raw_text="Buying NVDA here, looks great setup for next week"):
    return ParsedTweet(
        tweet_url="https://x.com/test/123",
        analyst="test_analyst",
        raw_text=raw_text,
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=[ticker],
        direction=direction,
        options=None,
        conviction=conviction,
        summary="test",
    )


def test_quality_gate_passes_valid_signal():
    parsed = _make_parsed()
    assert _passes_quality_gate(parsed, "NVDA") is True


def test_quality_gate_blocks_low_neutral():
    """LOW conviction + NEUTRAL direction = likely noise (life quotes)."""
    parsed = _make_parsed(direction=Direction.NEUTRAL, conviction=Conviction.LOW)
    assert _passes_quality_gate(parsed, "NVDA") is False


def test_quality_gate_allows_low_with_direction():
    """LOW conviction but with a direction should pass (score=20 >= threshold=20)."""
    parsed = _make_parsed(direction=Direction.LONG, conviction=Conviction.LOW)
    assert _passes_quality_gate(parsed, "NVDA") is True


def test_quality_gate_blocks_short_text():
    parsed = _make_parsed(raw_text="hi NVDA")
    assert _passes_quality_gate(parsed, "NVDA") is False


def test_quality_gate_blocks_single_char_ticker():
    parsed = _make_parsed()
    assert _passes_quality_gate(parsed, "A") is False


def test_quality_gate_blocks_blacklisted_ticker():
    parsed = _make_parsed()
    assert _passes_quality_gate(parsed, "RSI") is False


def test_quality_gate_passes_high_conviction():
    parsed = _make_parsed(conviction=Conviction.HIGH)
    assert _passes_quality_gate(parsed, "NVDA") is True


def test_quality_gate_passes_medium_long():
    parsed = _make_parsed(direction=Direction.LONG, conviction=Conviction.MEDIUM)
    assert _passes_quality_gate(parsed, "NVDA") is True


def test_quality_gate_passes_short_direction():
    """SHORT direction with HIGH conviction should pass."""
    parsed = _make_parsed(direction=Direction.SHORT, conviction=Conviction.HIGH)
    assert _passes_quality_gate(parsed, "TSLA") is True
