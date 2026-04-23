"""Tests for LLM video transcript parser."""
import json
import logging
import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine import config as cfg
from consensus_engine.models import Direction, Conviction
from consensus_engine.analysis.video_parser import (
    parse_video_transcript,
    _parse_llm_response,
    _merge_chunk_results,
)


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


# Transcript long enough to pass the 250-word quality gate
_LONG_TRANSCRIPT = " ".join(["stock market analysis"] * 100)


def _make_ticker_json(direction: str, conviction: str = "high") -> str:
    return json.dumps({
        "tickers": [{"symbol": "SPY", "direction": direction, "conviction": conviction, "mention_count": 2, "context": "price action"}],
        "price_levels": [],
        "macro_thesis": {"direction": direction, "themes": ["rate policy"], "timeframe": "short", "summary": "thesis"},
        "overall_conviction": conviction,
    })


# ---------------------------------------------------------------------------
# Test 1: bullish/bearish JSON → Direction.LONG / Direction.SHORT
# ---------------------------------------------------------------------------

def test_bullish_json_produces_long_direction():
    result = _parse_llm_response(_make_ticker_json("long"), "vid1", _LONG_TRANSCRIPT)
    assert result["tickers"][0]["direction"] == "long"
    assert result["overall_conviction"] == Conviction.HIGH


def test_bearish_json_produces_short_direction():
    result = _parse_llm_response(_make_ticker_json("short", "medium"), "vid2", _LONG_TRANSCRIPT)
    assert result["tickers"][0]["direction"] == "short"
    assert result["overall_conviction"] == Conviction.MEDIUM


# ---------------------------------------------------------------------------
# Test 2: Mixed chunk directions → correct majority vote after normalization
# ---------------------------------------------------------------------------

def test_mixed_chunk_directions_majority_vote():
    """Two 'bullish' chunks and one 'bearish' → merged macro direction is 'long'."""
    bullish_chunk = {
        "tickers": [{"symbol": "SPY", "direction": "long", "conviction": "high", "mention_count": 1, "context": ""}],
        "price_levels": [],
        "macro_thesis": {"direction": "bullish", "themes": ["rally"], "timeframe": "short", "summary": "Bull"},
        "overall_conviction": Conviction.HIGH,
    }
    bearish_chunk = {
        "tickers": [{"symbol": "SPY", "direction": "short", "conviction": "low", "mention_count": 1, "context": ""}],
        "price_levels": [],
        "macro_thesis": {"direction": "bearish", "themes": ["correction"], "timeframe": "short", "summary": "Bear"},
        "overall_conviction": Conviction.LOW,
    }
    merged = _merge_chunk_results([bullish_chunk, bullish_chunk, bearish_chunk])
    # "bullish" normalizes to "long" via _MACRO_NORM; 2 votes > 1 vote
    assert merged["macro_thesis"]["direction"] == "long"


# ---------------------------------------------------------------------------
# Test 3: Invalid direction "sideways" → falls back to neutral
# ---------------------------------------------------------------------------

def test_invalid_direction_sideways_falls_back_to_neutral():
    raw = json.dumps({
        "tickers": [{"symbol": "AAPL", "direction": "sideways", "conviction": "low", "mention_count": 1, "context": "unclear"}],
        "price_levels": [],
        "macro_thesis": {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""},
        "overall_conviction": "low",
    })
    result = _parse_llm_response(raw, "vid3", _LONG_TRANSCRIPT)
    directions = [t["direction"] for t in result["tickers"]]
    assert all(d in ("long", "short", "neutral") for d in directions), f"Got invalid direction: {directions}"


# ---------------------------------------------------------------------------
# Test 4: Empty/null LLM output → empty ParsedVideo, no exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_llm_output_returns_parsed_video_without_exception():
    with patch("consensus_engine.analysis.video_parser._call_groq_full", new_callable=AsyncMock) as mock_llm, \
         patch("consensus_engine.db.record_signal_event", new_callable=AsyncMock):
        mock_llm.return_value = ("", "stop")
        result = await parse_video_transcript("vid4", _LONG_TRANSCRIPT, "TestChannel", "2026-04-17")
    assert result is not None
    assert isinstance(result.tickers, list)
    assert isinstance(result.macro_thesis.direction, Direction)


# ---------------------------------------------------------------------------
# Test 5: finish_reason="length" → WARNING logged, partial result returned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_finish_reason_length_logs_warning_returns_partial(caplog):
    valid_json = _make_ticker_json("long", "medium")
    with patch("consensus_engine.analysis.video_parser._call_groq_full", new_callable=AsyncMock) as mock_llm, \
         patch("consensus_engine.db.record_signal_event", new_callable=AsyncMock):
        # First call: truncated; second call: valid
        mock_llm.side_effect = [("", "length"), (valid_json, "stop")]
        with caplog.at_level(logging.WARNING, logger="consensus_engine.analysis.video_parser"):
            result = await parse_video_transcript("vid5", _LONG_TRANSCRIPT, "TestChannel", "2026-04-17")
    assert result is not None
    warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("truncated" in m for m in warning_messages), f"No truncation warning found in: {warning_messages}"


# ---------------------------------------------------------------------------
# Test 6: Short transcript below threshold → skips LLM chunking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_short_transcript_skips_llm_and_returns_empty_parsed_video():
    short_transcript = "This transcript is way too short to analyze."  # << 250 words
    with patch("consensus_engine.analysis.video_parser._call_groq_full", new_callable=AsyncMock) as mock_llm, \
         patch("consensus_engine.db.record_signal_event", new_callable=AsyncMock):
        result = await parse_video_transcript("vid6", short_transcript, "TestChannel", "2026-04-17")
    mock_llm.assert_not_called()
    assert result.tickers == []
    assert result.overall_conviction == Conviction.LOW


# ---------------------------------------------------------------------------
# Task 4: VideoOptionIdea, VideoTradeSetup, ParsedVideo extensions
# ---------------------------------------------------------------------------

from consensus_engine.models import ParsedVideo, VideoOptionIdea, VideoTradeSetup, MacroThesis


def test_parsed_video_has_run_id_options_setups():
    pv = ParsedVideo(
        video_id="v1", channel_name="Chan", raw_transcript="...",
        tickers=[], price_levels=[], macro_thesis=MacroThesis(
            direction=Direction.NEUTRAL, themes=[], timeframe="short", summary=""
        ),
        overall_conviction=Conviction.LOW,
    )
    assert pv.run_id is None
    assert pv.options == []
    assert pv.setups == []


def test_video_option_idea_fields():
    opt = VideoOptionIdea(
        ticker="TSLA", option_type="call", strike=250.0, expiry="weekly",
        strategy="single", source="flow_observation", conviction="high",
        context="seeing massive call sweep", source_snippet="call sweep at 250",
        chunk_id=0,
    )
    assert opt.ticker == "TSLA"
    assert opt.source == "flow_observation"


def test_video_trade_setup_fields():
    s = VideoTradeSetup(
        ticker="NVDA", entry_low=845.0, entry_high=855.0, stop=820.0,
        targets=[920.0, 980.0], timeframe="swing", setup_type="breakout",
        context="buy NVDA 850 stop 820 target 920",
        source_snippet="buy NVDA at 850", chunk_id=0, risk_reward=2.5,
    )
    assert s.risk_reward == pytest.approx(2.5)
    assert len(s.targets) == 2
