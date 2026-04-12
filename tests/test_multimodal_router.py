import pytest
from unittest.mock import AsyncMock, patch

from models.router import process_tweet
from consensus_engine.analysis.tweet_parser import parse_tweet


@pytest.mark.asyncio
async def test_router_text_only_calls_text_model_only():
    with patch("models.router.analyze_tweet", new_callable=AsyncMock, return_value={"type": "D", "tickers": [], "direction": "neutral", "options": {"present": False}, "conviction": "medium", "summary": "", "final_signal": {"ticker": "", "signal": "neutral", "confidence": 0.1, "reason": "", "key_levels": {"bull_case": None, "base_case": None, "bear_case": None}, "source_types": ["text"]}}) as mock_text, \
         patch("models.router.analyze_image", new_callable=AsyncMock) as mock_vision:
        out = await process_tweet({"text": "No image tweet", "analyst": "a"})

    assert out["vision_outputs"] == []
    mock_text.assert_awaited_once()
    mock_vision.assert_not_called()


@pytest.mark.asyncio
async def test_router_with_image_runs_vision_then_text():
    vision = {
        "source": "Morgan Stanley",
        "ticker": "TSLA",
        "analysis_type": "bull/base/bear",
        "scenarios": {
            "bull_case": {"price": 500, "details": "upside"},
            "base_case": {"price": 300, "details": "base"},
            "bear_case": {"price": 150, "details": "downside"},
        },
        "probabilities": {"bull": 0.3, "base": 0.5, "bear": 0.2},
        "sentiment": "bullish",
        "confidence": 0.9,
        "summary": "TSLA scenario matrix",
    }
    text = {"type": "A", "tickers": ["TSLA"], "direction": "long", "options": {"present": False}, "conviction": "high", "summary": "", "final_signal": {"ticker": "TSLA", "signal": "bullish", "confidence": 0.82, "reason": "", "key_levels": {"bull_case": 500, "base_case": 300, "bear_case": 150}, "source_types": ["text", "image"]}}

    with patch("models.router.analyze_image", new_callable=AsyncMock, return_value=vision) as mock_vision, \
         patch("models.router.analyze_tweet", new_callable=AsyncMock, return_value=text) as mock_text:
        out = await process_tweet({"text": "TSLA report", "analyst": "a", "image_urls": ["https://img"]})

    assert len(out["vision_outputs"]) == 1
    assert out["vision_outputs"][0]["scenarios"]["bull_case"]["price"] == 500
    mock_vision.assert_awaited_once()
    mock_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_parse_tweet_broken_image_or_model_failure_fallback():
    with patch("consensus_engine.analysis.tweet_parser.process_multimodal_tweet", new_callable=AsyncMock, side_effect=TimeoutError("timeout")):
        parsed = await parse_tweet("https://x.com/t/1", "analyst", "$TSLA bullish", image_urls=["https://broken"])

    assert parsed.tickers == ["TSLA"]
    assert parsed.image_urls == ["https://broken"]
    assert parsed.final_signal is not None
