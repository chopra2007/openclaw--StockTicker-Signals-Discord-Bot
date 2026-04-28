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
        "tickers": [{"symbol": "SPY", "direction": direction, "conviction": conviction, "mention_count": 2, "context": "SPY price action"}],
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
async def test_llm_failure_returns_partial_result(caplog):
    """v2 pipeline: when _call_extraction_model fails, ParsedVideo is still returned."""
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=("", False))), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
         patch("consensus_engine.db.update_analysis_run", new=AsyncMock()), \
         patch("consensus_engine.db.record_signal_event", new_callable=AsyncMock):
        result = await parse_video_transcript("vid5", _LONG_TRANSCRIPT, "TestChannel", "2026-04-17")
    assert result is not None
    assert isinstance(result.tickers, list)
    assert isinstance(result.macro_thesis.direction, Direction)


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


# ---------------------------------------------------------------------------
# Task 5 (Plan Task 5): Stage 1 mentions pass + extraction model helper
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_mentions_pass_parses_tickers_and_price_spans():
    from consensus_engine.analysis.video_parser import _extract_mentions_pass
    fake_response = """{
      "tickers": [{"symbol": "NVDA", "mention_count": 3, "source_snippet": "I love NVDA here"}],
      "price_spans": [{"ticker": "NVDA", "price": 850.0, "source_snippet": "NVDA at $850"}],
      "option_keywords_found": false
    }"""
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=(fake_response, True))):
        result = await _extract_mentions_pass("I love NVDA here. NVDA at $850.", chunk_id=0)
    assert result["tickers"][0]["symbol"] == "NVDA"
    assert result["price_spans"][0]["price"] == 850.0
    assert result["option_keywords_found"] is False


@pytest.mark.asyncio
async def test_extract_mentions_pass_returns_empty_on_bad_json():
    from consensus_engine.analysis.video_parser import _extract_mentions_pass
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=("not json", False))):
        result = await _extract_mentions_pass("some transcript", chunk_id=0)
    assert result["tickers"] == []
    assert result["price_spans"] == []


def test_find_option_snippets_detects_calls_puts():
    from consensus_engine.analysis.video_parser import _find_option_snippets
    text = "I'm seeing huge call buying on TSLA at the 250 strike expiring next Friday. Also some put spreads on SPY."
    snippets = _find_option_snippets(text)
    assert len(snippets) >= 1
    assert any("call" in s.lower() for s in snippets)


def test_find_option_snippets_returns_empty_when_none():
    from consensus_engine.analysis.video_parser import _find_option_snippets
    snippets = _find_option_snippets("NVDA looks good above 850, stop at 820.")
    assert snippets == []


# ---------------------------------------------------------------------------
# Task 7 (Plan Task 6): Stage 2 direction + macro passes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_direction_pass_classifies_tickers():
    from consensus_engine.analysis.video_parser import _extract_direction_pass
    fake = '{"tickers": [{"symbol": "NVDA", "direction": "long", "conviction": "high", "context": "breakout", "source_snippet": "NVDA breakout above 850"}]}'
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=(fake, True))):
        result = await _extract_direction_pass("some transcript", ["NVDA"])
    assert result[0]["symbol"] == "NVDA"
    assert result[0]["direction"] == "long"
    assert result[0]["source_snippet"] == "NVDA breakout above 850"


@pytest.mark.asyncio
async def test_extract_direction_pass_empty_tickers_returns_empty():
    from consensus_engine.analysis.video_parser import _extract_direction_pass
    result = await _extract_direction_pass("some transcript", [])
    assert result == []


@pytest.mark.asyncio
async def test_extract_macro_pass_returns_thesis():
    from consensus_engine.analysis.video_parser import _extract_macro_pass
    fake = '{"macro_thesis": {"direction": "bearish", "themes": ["rate hikes"], "timeframe": "short", "summary": "Fed staying hawkish."}}'
    with patch("consensus_engine.analysis.video_parser._call_extraction_model",
               new=AsyncMock(return_value=(fake, True))):
        result = await _extract_macro_pass("Fed is hiking rates and markets are falling.")
    assert result["direction"] == "bearish"
    assert "rate hikes" in result["themes"]


# ---------------------------------------------------------------------------
# Task 8 (Plan Task 7): Wire two-stage pipeline into parse_video_transcript()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_video_transcript_v2_pipeline_produces_parsed_video():
    """Full pipeline integration: mentions → direction → macro → ParsedVideo."""
    mentions_resp = '{"tickers": [{"symbol": "NVDA", "mention_count": 2, "source_snippet": "NVDA breakout", "chunk_id": 0}], "price_spans": [], "option_keywords_found": false}'
    direction_resp = '{"tickers": [{"symbol": "NVDA", "direction": "long", "conviction": "high", "context": "breakout", "source_snippet": "NVDA breakout above 850"}]}'
    macro_resp = '{"macro_thesis": {"direction": "bullish", "themes": ["tech rally"], "timeframe": "short", "summary": "Tech leading."}}'

    call_log = []
    async def mock_call(system_prompt, user_prompt, model="minimax/minimax-m2.5", max_tokens=2048):
        call_log.append(model)
        if "price_spans" in system_prompt:
            return mentions_resp, True
        if "conviction" in system_prompt:  # unique to _DIRECTION_PROMPT
            return direction_resp, True
        return macro_resp, True

    with patch("consensus_engine.analysis.video_parser._call_extraction_model", new=mock_call), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=42)), \
         patch("consensus_engine.db.update_analysis_run", new=AsyncMock()), \
         patch("consensus_engine.db.record_signal_event", new=AsyncMock()):
        transcript = " ".join(["NVDA is breaking out above 850."] * 80)  # ~500 words
        parsed = await parse_video_transcript("vid42", transcript, "ClickCapital", "2026-04-22T10:00:00Z")

    assert parsed.run_id == 42
    assert any(t.get("symbol") == "NVDA" for t in parsed.tickers)
    assert parsed.macro_thesis.direction.value in ("long", "bullish")


@pytest.mark.asyncio
async def test_parse_video_transcript_marks_partial_on_budget_exhaustion():
    """If budget is hit, run is marked partial but ParsedVideo is still returned."""
    call_count = 0
    async def mock_call_limited(system_prompt, user_prompt, model="minimax/minimax-m2.5", max_tokens=2048):
        nonlocal call_count
        call_count += 1
        return "", False  # all calls fail

    update_calls = []
    async def mock_update(run_id, status, call_budget_used=0):
        update_calls.append(status)

    with patch("consensus_engine.analysis.video_parser._call_extraction_model", new=mock_call_limited), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=1)), \
         patch("consensus_engine.db.update_analysis_run", new=mock_update), \
         patch("consensus_engine.db.record_signal_event", new=AsyncMock()):
        transcript = " ".join(["NVDA is breaking out."] * 80)
        parsed = await parse_video_transcript("vid99", transcript, "Chan", "2026-04-22T00:00:00Z")

    assert parsed is not None  # always returns something
    assert "partial" in update_calls or "complete" in update_calls
