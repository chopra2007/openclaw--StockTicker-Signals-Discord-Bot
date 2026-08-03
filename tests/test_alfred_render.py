import pytest
from consensus_engine.briefing import alfred


async def test_render_briefing_uses_llm_and_has_fallback(monkeypatch):
    data = {
        "session_start_utc": 0, "session_end_utc": 1,
        "alerts": [{"ticker": "NVDA", "confidence_score": 90, "catalyst": "earnings", "catalyst_type": "news", "alerted_at": 0, "price_at_alert": 150}],
        "levels": [], "yt_signals": [], "macro": None,
        "top_tickers": [{"ticker": "NVDA", "sections": {"analyst": {"content": "bullish"}}}],
    }

    async def fake_llm(prompt):
        assert "NVDA" in prompt
        return "## Morning Brief\nNVDA strong overnight."
    monkeypatch.setattr(alfred, "_llm_synthesize", fake_llm)

    out = await alfred._render_briefing(data)
    assert "Morning Brief" in out
    assert "NVDA" in out


async def test_render_briefing_falls_back_when_llm_empty(monkeypatch):
    data = {
        "session_start_utc": 0, "session_end_utc": 1,
        "alerts": [], "levels": [], "yt_signals": [], "macro": None, "top_tickers": [],
    }

    async def empty(prompt): return ""
    monkeypatch.setattr(alfred, "_llm_synthesize", empty)

    out = await alfred._render_briefing(data)
    # Fallback still produces a valid non-empty brief
    assert "Morning Brief" in out


async def test_render_briefing_removes_forbidden_timezone_labels(monkeypatch):
    data = {
        "session_start_utc": 0, "session_end_utc": 1,
        "alerts": [], "levels": [], "yt_signals": [], "macro": None,
        "top_tickers": [],
    }

    async def wrong_timezone(prompt):
        return "All times EST. Energy Transfer ($ET) is unchanged."

    monkeypatch.setattr(alfred, "_llm_synthesize", wrong_timezone)
    out = await alfred._render_briefing(data)

    assert "EST" not in out
    assert "Morning Brief" in out


async def test_render_briefing_preserves_et_stock_ticker(monkeypatch):
    data = {
        "session_start_utc": 0, "session_end_utc": 1,
        "alerts": [], "levels": [], "yt_signals": [], "macro": None,
        "top_tickers": [],
    }

    async def ticker_not_timezone(prompt):
        return "Energy Transfer ($ET) is unchanged."

    monkeypatch.setattr(alfred, "_llm_synthesize", ticker_not_timezone)
    out = await alfred._render_briefing(data)

    assert "$ET" in out
