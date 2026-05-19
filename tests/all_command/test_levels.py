"""Unit tests for levels.py — TODO #10 (anchor completeness + ATR fallback) +
TODO #12 (horizon-aware re-rank)."""
from __future__ import annotations

import pytest

from consensus_engine.alerts.all_command import levels
from consensus_engine.alerts.all_command.levels import Anchor, select_trade_plan


# ---------------------------------------------------------------------------
# TODO #10 — youtube freshness cutoff
# ---------------------------------------------------------------------------

def test_youtube_freshness_cutoff_drops_stale_anchors(monkeypatch):
    """Anchor 40 days old should be filtered when cutoff=30 (default)."""
    rows = [
        {"price": 220.0, "channel_name": "fresh", "freshness_days": 5},
        {"price": 203.79, "channel_name": "stale", "freshness_days": 40},
    ]
    anchors = levels.extract_anchors_from_youtube_levels(rows)
    prices = {a.price for a in anchors}
    assert 220.0 in prices
    assert 203.79 not in prices


def test_youtube_freshness_cutoff_keeps_within_window():
    """Anchor exactly at the cutoff (30d) is KEPT (cutoff is `>`, not `>=`)."""
    rows = [
        {"price": 215.0, "channel_name": "boundary", "freshness_days": 30},
    ]
    anchors = levels.extract_anchors_from_youtube_levels(rows)
    assert len(anchors) == 1
    assert anchors[0].price == 215.0


def test_youtube_freshness_missing_treated_as_zero():
    """Rows without freshness_days are treated as fresh (0 days)."""
    rows = [
        {"price": 250.0, "channel_name": "no_freshness_field"},
    ]
    anchors = levels.extract_anchors_from_youtube_levels(rows)
    assert len(anchors) == 1


# ---------------------------------------------------------------------------
# TODO #10 — drawdown sanity gate on SL
# ---------------------------------------------------------------------------

def _anchor(price: float, source_type: str = "yt_curated") -> Anchor:
    return Anchor(price=price, source="test", source_type=source_type)


def test_select_trade_plan_drawdown_gate_rejects_absurd_sl():
    """AMD 2026-05-18 case: SL $130 on $420 spot = 69% drawdown → rejected."""
    supports = [_anchor(130.0)]
    resistances = [_anchor(440.0), _anchor(460.0), _anchor(480.0)]
    plan = select_trade_plan(
        supports, resistances, spot=420.0, atr14=10.0, direction="BULLISH",
    )
    # Absurd SL replaced with ATR fallback: 420 - 2*10 = 400
    assert plan["sl"] == pytest.approx(400.0)
    # Suppression reason reflects fallback
    assert "atr_fallback" in (plan["suppression_reason"] or "")


def test_select_trade_plan_drawdown_gate_keeps_reasonable_sl():
    """SL 5% below spot — within 20% gate — should pass through."""
    supports = [_anchor(200.0)]  # 5% below 210
    resistances = [_anchor(215.0), _anchor(220.0), _anchor(225.0)]
    plan = select_trade_plan(
        supports, resistances, spot=210.0, atr14=4.0, direction="BULLISH",
    )
    assert plan["sl"] == 200.0  # unchanged


# ---------------------------------------------------------------------------
# TODO #10 — ATR fallback for missing levels
# ---------------------------------------------------------------------------

def test_select_trade_plan_atr_fallback_fills_missing_tps():
    """TSLA 2026-05-18 case: no supports, no resistances → all-ATR plan."""
    plan = select_trade_plan(
        [], [],
        spot=400.0, atr14=15.0, direction="BULLISH",
    )
    # Bullish fallback: SL = 400 - 30 = 370, TPs = 415, 430, 445
    assert plan["sl"] == pytest.approx(370.0)
    assert plan["tp1"] == pytest.approx(415.0)
    assert plan["tp2"] == pytest.approx(430.0)
    assert plan["tp3"] == pytest.approx(445.0)
    assert "atr_fallback" in (plan["suppression_reason"] or "")


def test_select_trade_plan_atr_fallback_bearish_direction():
    plan = select_trade_plan(
        [], [],
        spot=400.0, atr14=10.0, direction="BEARISH",
    )
    # Bearish fallback: SL = 400 + 20 = 420, TPs = 390, 380, 370
    assert plan["sl"] == pytest.approx(420.0)
    assert plan["tp1"] == pytest.approx(390.0)
    assert plan["tp2"] == pytest.approx(380.0)
    assert plan["tp3"] == pytest.approx(370.0)


def test_select_trade_plan_atr_fallback_partial_fill():
    """Confluence gives SL + TP1; ATR fills TP2, TP3."""
    supports = [_anchor(200.0)]
    resistances = [_anchor(215.0)]  # only 2 anchors total → would suppress
    plan = select_trade_plan(
        supports, resistances, spot=210.0, atr14=4.0, direction="BULLISH",
    )
    # total < 4 → entire plan from ATR fallback
    assert plan["sl"] == pytest.approx(202.0)  # 210 - 2*4
    assert plan["tp1"] == pytest.approx(214.0)  # 210 + 1*4
    assert plan["tp2"] == pytest.approx(218.0)
    assert plan["tp3"] == pytest.approx(222.0)
    assert "atr_fallback" in (plan["suppression_reason"] or "")


def test_select_trade_plan_atr_fallback_skipped_for_neutral():
    """NEUTRAL direction → no ATR fallback (callers wipe levels anyway)."""
    plan = select_trade_plan(
        [], [],
        spot=400.0, atr14=15.0, direction="NEUTRAL",
    )
    assert plan["sl"] is None
    assert plan["tp1"] is None


def test_select_trade_plan_atr_fallback_skipped_when_no_atr():
    """Without ATR, behavior matches pre-TODO-#10 (all-None when anchors scarce)."""
    plan = select_trade_plan([], [], spot=400.0, atr14=None, direction="BULLISH")
    assert plan["sl"] is None
    assert "atr_fallback" not in (plan["suppression_reason"] or "")


# ---------------------------------------------------------------------------
# Backward compatibility — old call sites (positional only) still work
# ---------------------------------------------------------------------------

def test_select_trade_plan_backward_compat_positional_only():
    """Old call site `select_trade_plan(supports, resistances)` still works."""
    supports = [_anchor(200.0)]
    resistances = [_anchor(215.0), _anchor(220.0), _anchor(225.0)]
    plan = select_trade_plan(supports, resistances)
    # 4 anchors, has support → full plan with original logic
    assert plan["sl"] == 200.0
    assert plan["tp1"] == 215.0
    assert plan["tp2"] == 220.0
    assert plan["tp3"] == 225.0


def test_select_trade_plan_backward_compat_suppress_when_scarce():
    """Old call site with <4 anchors → all-None (no ATR fallback without kwargs)."""
    plan = select_trade_plan([], [_anchor(215.0)])
    assert plan["sl"] is None
    assert plan["tp1"] is None
    assert "only 1 anchors" in (plan["suppression_reason"] or "")


# ---------------------------------------------------------------------------
# TODO #12 — horizon-aware re-rank: tests live in Commit 3 where the
# aggregator starts passing earnings_days into select_trade_plan and the
# rerank weights get tuned against real cases (NVDA $178 vs $209).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helper sanity
# ---------------------------------------------------------------------------

def test_compute_atr_fallback_bullish():
    sl, tps = levels._compute_atr_fallback(100.0, 5.0, "BULLISH")
    assert sl == pytest.approx(90.0)
    assert tps == pytest.approx([105.0, 110.0, 115.0])


def test_compute_atr_fallback_bearish():
    sl, tps = levels._compute_atr_fallback(100.0, 5.0, "BEARISH")
    assert sl == pytest.approx(110.0)
    assert tps == pytest.approx([95.0, 90.0, 85.0])
