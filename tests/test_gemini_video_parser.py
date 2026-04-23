"""Tests for Gemini fast-path video parser."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from consensus_engine.analysis.gemini_video_parser import parse_video_with_gemini
from consensus_engine.models import ParsedVideo, Direction, Conviction


@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_parsed_video():
    fake_json = """{
      "tickers": [{"symbol": "NVDA", "direction": "long", "conviction": "high", "mention_count": 3, "context": "breakout above 850"}],
      "price_levels": [{"ticker": "NVDA", "type": "support", "price": 820.0, "context": "key support annotated on chart"}],
      "macro_thesis": {"direction": "bullish", "themes": ["tech rally"], "timeframe": "short", "summary": "Markets rallying."},
      "options": [],
      "setups": [{"ticker": "NVDA", "entry_low": 850.0, "entry_high": 855.0, "stop": 820.0, "targets": [920.0], "timeframe": "swing", "setup_type": "breakout", "context": "buy NVDA at 850"}],
      "overall_conviction": "high"
    }"""

    mock_response = MagicMock()
    mock_response.text = fake_json

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=mock_client), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=5)):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "ClickCapital", "2026-04-22T10:00:00Z")

    assert isinstance(result, ParsedVideo)
    assert result.run_id == 5
    assert any(t["symbol"] == "NVDA" for t in result.tickers)
    assert result.overall_conviction == Conviction.HIGH
    assert len(result.setups) == 1
    assert result.setups[0].ticker == "NVDA"
    assert len(result.price_levels) == 1


@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_none_on_api_error():
    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("API error")

    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=mock_client):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    assert result is None


@pytest.mark.asyncio
async def test_parse_video_with_gemini_returns_none_when_no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=None):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    assert result is None


@pytest.mark.asyncio
async def test_parse_video_with_gemini_handles_bad_json():
    mock_response = MagicMock()
    mock_response.text = "Sorry, I cannot process this video."

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("consensus_engine.analysis.gemini_video_parser._get_gemini_client", return_value=mock_client), \
         patch("consensus_engine.db.create_analysis_run", new=AsyncMock(return_value=6)):
        result = await parse_video_with_gemini("dQw4w9WgXcQ", "Chan", "2026-04-22T10:00:00Z")

    # Bad JSON → returns None (caller will fall back to transcript pipeline)
    assert result is None
