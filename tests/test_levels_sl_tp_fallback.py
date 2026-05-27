"""Pass 5 Step 11 — levels.py SL/TP fallback: confidence annotation tests."""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command import levels


def _sup(price: float) -> levels.Anchor:
    return levels.Anchor(price=price, source="s", source_type="swing")


def _res(price: float) -> levels.Anchor:
    return levels.Anchor(price=price, source="r", source_type="web")


# ---------------------------------------------------------------------------
# 1. Primary available — anchor-derived levels, confidence=None
# ---------------------------------------------------------------------------

def test_primary_available_no_confidence_annotation():
    """≥4 anchors within drawdown gate: anchor-derived levels, confidence=None."""
    supports = [_sup(p) for p in [95, 94, 93, 92]]
    resistances = [_res(p) for p in [105, 110, 115]]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0, direction="BULLISH",
    )
    assert plan["sl"] == 95.0
    assert plan["tp1"] == 105.0
    assert plan["confidence"] is None


# ---------------------------------------------------------------------------
# 2. Primary unavailable (too few anchors) + ATR available → fallback fires
# ---------------------------------------------------------------------------

def test_atr_fallback_fires_confidence_low():
    """Fewer than 4 anchors but ATR provided: ATR fallback fires, confidence='low'."""
    supports = [_sup(95.0)]
    resistances = [_res(105.0)]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0, direction="BULLISH",
    )
    assert plan["confidence"] == "low"
    assert plan["sl"] is not None
    assert plan["tp1"] is not None
    # ATR fallback SL for BULLISH = spot - 2*ATR = 94.0
    assert plan["sl"] == pytest.approx(94.0, abs=0.01)


def test_atr_fallback_fires_bearish_confidence_low():
    """BEARISH with too few anchors: ATR fallback fires (spot + 2*ATR SL)."""
    plan = levels.select_trade_plan(
        [], [], spot=100.0, atr14=5.0, direction="BEARISH",
    )
    assert plan["confidence"] == "low"
    # SL for BEARISH = spot + 2*ATR = 110.0
    assert plan["sl"] == pytest.approx(110.0, abs=0.01)


def test_atr_fallback_drawdown_gate_triggers_fallback():
    """SL from anchor exceeds 20% drawdown gate → falls through to ATR, confidence='low'."""
    supports = [_sup(70.0)]  # 30% below spot=100 → exceeds 20% gate
    resistances = [_res(p) for p in [110, 115, 120, 125]]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0, direction="BULLISH",
    )
    assert plan["confidence"] == "low"
    assert plan["sl"] == pytest.approx(94.0, abs=0.01)  # 100 - 2*3


# ---------------------------------------------------------------------------
# 3. Both primary and ATR unavailable → no levels, confidence=None
# ---------------------------------------------------------------------------

def test_no_anchors_no_atr_confidence_none():
    """No anchors and no ATR: all levels None, confidence=None."""
    plan = levels.select_trade_plan([], [], spot=None, atr14=None, direction="BULLISH")
    assert plan["sl"] is None
    assert plan["tp1"] is None
    assert plan["confidence"] is None


def test_neutral_direction_no_atr_fallback():
    """NEUTRAL direction: ATR fallback is skipped even with ATR present."""
    plan = levels.select_trade_plan(
        [], [], spot=100.0, atr14=3.0, direction="NEUTRAL",
    )
    assert plan["sl"] is None
    # NEUTRAL skips ATR fallback so confidence stays None
    assert plan["confidence"] is None


# ---------------------------------------------------------------------------
# 4. Confidence key always present in returned dict
# ---------------------------------------------------------------------------

def test_confidence_key_always_present():
    """select_trade_plan always returns a dict with 'confidence' key."""
    plan = levels.select_trade_plan([], [])
    assert "confidence" in plan

    plan2 = levels.select_trade_plan(
        [_sup(95)], [_res(105)], spot=100.0, atr14=2.0, direction="BULLISH",
    )
    assert "confidence" in plan2
