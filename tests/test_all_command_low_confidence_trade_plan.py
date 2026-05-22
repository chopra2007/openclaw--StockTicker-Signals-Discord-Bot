"""Iter4 — LOW confidence must NOT wipe a populated trade plan.

User feedback 2026-05-09 (post-iter3): "NVDA, TSLA, and AMD did not
show any buy zones, TP zones, or SL zones, and all have low confidence.
Gemini has all of these for each ticker."

Locked decision D3 ("LOW CONFIDENCE → no SL/TP") is overridden by this
feedback because the user wants Gemini-equivalent actionable levels even
when conviction is thin. PR3's anchor-count gate (≥4 anchors after gap-
fill) is now the single source of truth for trade-plan suppression.

The LOW label still renders in the embed banner so the user can read it.
NEUTRAL direction (genuinely "I don't know which way") still wipes
SL/TP because levels labeled SL/TP are direction-dependent.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from consensus_engine.alerts.all_command import aggregator, narrator
from consensus_engine.alerts.all_command.embed import COLOR_NEUTRAL
from consensus_engine.models import ScoreBreakdown


def _swing_candles() -> list[dict]:
    """Synthetic 20-bar OHLC with 4 distinct swing highs and 4 swing lows."""
    pattern = [
        # Each triplet (i-1, i, i+1) where the middle bar is the extremum.
        (190, 180), (188, 178), (192, 182),  # swing low at idx 1
        (210, 200), (220, 210), (212, 202),  # swing high at idx 4
        (192, 182), (185, 175), (193, 183),  # swing low at idx 7
        (215, 205), (225, 215), (217, 207),  # swing high at idx 10
        (190, 180), (183, 173), (192, 182),  # swing low at idx 13
        (212, 202), (222, 212), (215, 205),  # swing high at idx 16
        (188, 178), (180, 170),              # swing low at idx 19
    ]
    return [{"high": h, "low": l} for h, l in pattern]


class _Tech:
    current_price = 200.0
    atr14 = 4.0
    candles = _swing_candles()


def _bullish_low_confidence_gather():
    """BULLISH direction but score below the high-confidence threshold (LOW)."""
    # base=10 + tech=5 = 15 → well below the 80 high-confidence threshold,
    # so confidence_label resolves to LOW. Direction stays BULLISH because
    # technical contribution is positive.
    bd = ScoreBreakdown(base=10, technical=5)
    score_obj = type("Score", (), {"breakdown": bd, "final_score": bd.total})()

    async def _gather(_ticker):
        return {
            "ticker_meta": {"name": "Test"}, "company_name": "Test",
            "score": score_obj,
            "technical_long": _Tech(),
            "technical_short": None,
            "twitter_signals": [], "social_signals": [],
            "yt_signals": [], "yt_options": [], "yt_levels": [],
            "yt_evidence": [],
            "alert_history": [], "decision_snapshots": [],
            "news_catalyst": None, "sec_filings": [],
            "options_unusual": None, "trends": {}, "apewisdom": None,
            "chat_msgs": [], "brief_msgs": [], "prior_vault": None,
            "sources_surfaced": ["score", "technical_long"],
            "source_failures": [],
        }
    return _gather


@pytest.mark.asyncio
async def test_low_confidence_with_anchors_keeps_trade_plan(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """LOW confidence + ≥4 anchors → trade plan SHOULD render (post-iter4)."""
    monkeypatch.setattr(
        aggregator, "_gather_all_sources", _bullish_low_confidence_gather(),
    )

    async def _empty_sanitize(**_kw):
        return {"searxng": [], "chat": [], "brief": [], "vault": ""}

    captured: dict = {}

    async def _synth(**kw):
        captured["structured"] = kw.get("structured")
        return "Bullish thesis with low conviction.\n## Catalysts\n* x\n* y\n## Risk\n* z", "ok"

    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)
    monkeypatch.setattr(narrator, "synthesize_narrative", _synth)

    await aggregator.handle_all("AAPL", "ch", "m")

    assert len(captured_sends["embed"]) == 1
    embed = captured_sends["embed"][0][2]
    fields_by_name = {f["name"]: f["value"] for f in embed["fields"]}

    # Commit 16 dropped SL/TP from the embed fields; the trade plan now lives
    # in `structured`. The 20 swing-derived candles produce >=4 anchors, and
    # after iter4 LOW confidence must NOT zero them.
    structured = captured["structured"]
    assert structured is not None
    assert structured.sl is not None, "LOW confidence should retain SL when anchors >=4"
    assert structured.tp1 is not None, "LOW confidence should retain TP1 when anchors >=4"
    assert fields_by_name["Confidence"] == "LOW", "LOW confidence label missing"


@pytest.mark.asyncio
async def test_neutral_direction_still_wipes_trade_plan(
    vault_path, captured_sends, monkeypatch, isolated_db,
):
    """NEUTRAL direction still wipes SL/TP — levels are direction-dependent."""
    # Empty score → direction defaults to NEUTRAL. _empty_gather_factory
    # produces this.
    from tests.test_pr5_all_command_e2e import _empty_gather_factory, _empty_sanitize

    monkeypatch.setattr(
        aggregator, "_gather_all_sources",
        _empty_gather_factory(["score: unavailable"]),
    )
    monkeypatch.setattr(narrator, "sanitize_hostile_text", _empty_sanitize)

    captured: dict = {}

    async def _synth(**kw):
        captured["structured"] = kw.get("structured")
        return "Some narrative.", "ok"
    monkeypatch.setattr(narrator, "synthesize_narrative", _synth)

    await aggregator.handle_all("ZZZZ", "ch", "m")

    # Commit 16 dropped SL/TP from the embed; NEUTRAL still wipes them in
    # `structured` (direction-dependent levels make no sense when neutral).
    structured = captured["structured"]
    assert structured is not None
    for key in ("sl", "tp1", "tp2", "tp3"):
        assert getattr(structured, key) is None, f"NEUTRAL must wipe {key}"


# Reuse the e2e fixtures
from tests.test_pr5_all_command_e2e import vault_path, captured_sends, isolated_db  # noqa: E402,F401
