"""PR3 — trade-plan suppression gate matches locked D1.

v1's `select_trade_plan` (levels.py:262) suppressed unless `len(resistances)
>= 3`. The locked D1 policy is "anchored-only ... suppress trade plan if
<4 anchors after gap-fill" — total count, not per-side. Investigation Q3
showed AMD with sup=7 res=1 (total=8) was getting an empty trade plan
because the per-side gate fired, even though total ≥ 4.

PR3 honors D1: suppress only when total < 4. With ≥4 total but fewer than
3 resistances, populate SL + TP1 from what's available and pad TP2/TP3
with None. Always return a dict so the caller can read a reason field.
"""
from __future__ import annotations

from consensus_engine.alerts.all_command import levels


def _sup(price: float) -> levels.Anchor:
    return levels.Anchor(price=price, source="s", source_type="swing")


def _res(price: float) -> levels.Anchor:
    return levels.Anchor(price=price, source="r", source_type="web")


def test_trade_plan_8_anchors_one_resistance():
    """AMD-like: 7 supports, 1 resistance → populate SL + TP1, pad TP2/TP3."""
    supports = [_sup(p) for p in [95, 94, 93, 92, 91, 90, 89]]
    resistances = [_res(105.0)]
    plan = levels.select_trade_plan(supports, resistances)
    assert plan is not None
    assert plan["sl"] == 95.0
    assert plan["tp1"] == 105.0
    assert plan["tp2"] is None
    assert plan["tp3"] is None
    assert plan["suppression_reason"]
    assert "resistance" in plan["suppression_reason"].lower()


def test_trade_plan_3_total_anchors_suppressed():
    """Total < 4 anchors → all four levels None + reason mentions the count."""
    supports = [_sup(95.0), _sup(94.0)]
    resistances = [_res(105.0)]
    plan = levels.select_trade_plan(supports, resistances)
    assert plan is not None
    assert plan["sl"] is None
    assert plan["tp1"] is None
    assert plan["tp2"] is None
    assert plan["tp3"] is None
    assert "3 anchors" in plan["suppression_reason"]


def test_trade_plan_4_supports_3_resistances():
    """≥4 total + ≥3 resistances → all four levels populated, no reason."""
    supports = [_sup(p) for p in [95, 94, 93, 92]]
    resistances = [_res(p) for p in [105, 110, 115]]
    plan = levels.select_trade_plan(supports, resistances)
    assert plan is not None
    assert plan["sl"] == 95.0
    assert plan["tp1"] == 105.0
    assert plan["tp2"] == 110.0
    assert plan["tp3"] == 115.0
    assert plan["suppression_reason"] is None


def test_trade_plan_no_supports_below_price():
    """≥4 total but only resistances → SL is None, TPs populate."""
    supports: list[levels.Anchor] = []
    resistances = [_res(p) for p in [105, 110, 115, 120]]
    plan = levels.select_trade_plan(supports, resistances)
    assert plan is not None
    assert plan["sl"] is None
    assert plan["tp1"] == 105.0
    assert plan["tp2"] == 110.0
    assert plan["tp3"] == 115.0
    assert plan["suppression_reason"]
    assert "support" in plan["suppression_reason"].lower()
