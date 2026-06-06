"""Smart technical-levels engine (full-audit Wave 2) — unit tests.

Covers the five extractors on synthetic candle series with known answers, the
helpers, the select_trade_plan 3-rung ladder (R:R floor rejection, no-LVN-stop),
and the FLAG-OFF byte-identical guarantee (incl. a mixed swing+yt cluster to
prove the SOURCE_TIER_ORDER insertion did not reorder existing types).
"""
from __future__ import annotations

import math

import pytest

from consensus_engine.alerts.all_command import levels


# ---------------------------------------------------------------------------
# Synthetic candle helpers
# ---------------------------------------------------------------------------

def _c(high, low, close, volume=1_000_000.0):
    return {"high": high, "low": low, "close": close, "volume": volume}


def _flat_series(price, n, vol=1_000_000.0):
    """n nearly-flat bars around `price` (tiny range)."""
    return [_c(price + 0.1, price - 0.1, price, vol) for _ in range(n)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_fractal_pivots_finds_known_high_and_low_and_drops_last_n():
    # a clear peak at idx 4, a clear trough at idx 9; last n=2 bars never emitted.
    highs = [10, 11, 12, 13, 20, 13, 12, 11, 10, 5, 11, 12]
    lows = [9, 10, 11, 12, 19, 12, 11, 10, 9, 4, 10, 11]
    candles = [_c(highs[i], lows[i], (highs[i] + lows[i]) / 2) for i in range(len(highs))]
    sh, sl = levels._fractal_pivots(candles, n=2)
    high_idxs = {p["idx"] for p in sh}
    low_idxs = {p["idx"] for p in sl}
    assert 4 in high_idxs           # the peak is found
    assert 9 in low_idxs            # the trough is found
    # look-ahead guard: indices in the last n=2 bars (10, 11) are never pivots
    assert all(i < len(candles) - 2 for i in high_idxs | low_idxs)


def test_value_area_centers_on_poc():
    bins = [1.0, 2.0, 10.0, 2.0, 1.0]   # POC at idx 2
    poc, vah, val = levels._value_area(bins, 0.70)
    assert poc == 2
    assert val <= poc <= vah


def test_method_anchor_maps_strength_to_score_inputs():
    a = levels._method_anchor(100.0, "tech_sr", strength=80.0,
                              label="swing-S/R x3", freshness_days=5)
    assert a.source_type == "tech_sr"
    assert a.method_strength == 80.0
    assert a.method_label == "swing-S/R x3"
    assert a.touches == round(80.0 / 20.0)        # 4
    assert a.volume_strength == pytest.approx(80.0 / 50.0)  # 1.6
    assert a.source_count == 1
    assert a.price == 100.0


# ---------------------------------------------------------------------------
# §3a — extract_sr_levels: a strong level must sit on a real prior pivot
# ---------------------------------------------------------------------------

def _sr_test_series():
    """Build a series with a clearly-tested support at ~100 (price bounces off
    100 three times) and resistance near ~120."""
    candles = []
    # uptrend with three pivots low at 100 and highs at 120
    seq = [
        (118, 110, 115), (121, 112, 118),
        (120, 100, 105), (115, 101, 112), (122, 113, 120),   # low pivot @ idx2 ~100
        (119, 108, 112), (123, 100, 118), (121, 102, 119),   # low pivot @ idx6 ~100
        (124, 114, 121), (120, 100, 116), (122, 110, 118),   # low pivot @ idx9 ~100
        (125, 116, 122), (123, 117, 120), (126, 118, 124),
        (124, 119, 121), (127, 120, 125),
    ]
    for h, l, c in seq:
        candles.append(_c(h, l, c, 2_000_000.0))
    return candles


def test_extract_sr_levels_lands_on_real_pivot():
    candles = _sr_test_series()
    atr = levels._atr14(candles) or 5.0
    current = 122.0
    anchors = levels.extract_sr_levels(candles, current, atr, 130.0, 95.0)
    assert anchors, "expected at least one S/R level"
    # every emitted tech_sr level must sit within TOL of an actual prior pivot.
    sh, sl = levels._fractal_pivots(candles, 2)
    pivot_prices = [p["price"] for p in sh] + [p["price"] for p in sl]
    tol = levels._tol(atr, current)
    for a in anchors:
        assert a.source_type == "tech_sr"
        assert a.method_strength is not None
        nearest = min(abs(a.price - pp) for pp in pivot_prices)
        assert nearest <= tol + 0.01, (
            f"tech_sr level {a.price} is on thin air "
            f"(nearest pivot {nearest:.2f} away, tol {tol:.2f})"
        )
    # the repeatedly-tested ~100 support should be among them (multi-touch).
    assert any(abs(a.price - 100.0) <= tol for a in anchors)


# ---------------------------------------------------------------------------
# §3c — extract_fib_levels: SIGN INVARIANT (long targets above, short below)
# ---------------------------------------------------------------------------

def _uptrend_then_pullback():
    """Up-leg from ~100 to ~150 then a shallow pullback (golden-pocket setup)."""
    candles = []
    # up leg: low pivot at 100, rising to high pivot at 150
    seq = [
        (102, 98, 100), (101, 97, 99), (100, 95, 97),   # low pivot ~95 @ idx2
        (108, 99, 106), (116, 107, 114), (124, 115, 122),
        (132, 123, 130), (140, 131, 138), (152, 145, 150),  # high pivot ~152 @ idx8
        (151, 142, 145), (148, 138, 140), (146, 135, 138),  # pullback
        (144, 133, 136), (142, 132, 134),
    ]
    for h, l, c in seq:
        candles.append(_c(h, l, c, 1_500_000.0))
    return candles


def test_extract_fib_levels_long_targets_above_short_below():
    candles = _uptrend_then_pullback()
    atr = levels._atr14(candles) or 5.0
    current = 137.0
    anchors = levels.extract_fib_levels(candles, current, atr, 160.0, 90.0)
    assert anchors, "expected fib levels on a 2+ ATR up-leg"
    ext = [a for a in anchors if "ext" in (a.method_label or "")]
    assert ext, "expected at least one extension target"
    # up-leg => LONG => all extension targets must be ABOVE the leg high region.
    for a in ext:
        assert a.price > current, f"LONG ext target {a.price} not above entry {current}"


def test_extract_fib_short_leg_targets_below():
    # 33-bar series (avoids the thin-sample penalty): a clear down-leg from a
    # high pivot ~120 to a low pivot ~100, then a retrace; current inside the
    # leg. A down-leg => SHORT => extension targets must be BELOW entry.
    seq = []
    for i in range(6):
        seq.append((101 + i * 0.1, 99 + i * 0.1, 100 + i * 0.1))
    for h in [104, 108, 112, 116, 120, 118]:
        seq.append((h + 1, h - 3, h))
    for l in [116, 112, 108, 104, 100, 98, 102]:
        seq.append((l + 2, l - 1, l))
    for c in [104, 106, 108, 107, 106, 108, 110, 109, 108, 107, 106, 108, 109, 107]:
        seq.append((c + 1.5, c - 1.5, c))
    candles = [_c(h, l, c, 1_500_000.0) for h, l, c in seq]
    atr = levels._atr14(candles) or 5.0
    current = 107.0
    anchors = levels.extract_fib_levels(candles, current, atr, 140.0, 80.0)
    ext = [a for a in anchors if "ext" in (a.method_label or "")]
    assert ext, "expected extension targets on the down-leg"
    for a in ext:
        assert a.price < current, f"SHORT ext target {a.price} not below entry {current}"


# ---------------------------------------------------------------------------
# §3d — volume profile: POC lands in the highest-volume band; LVN flagged
# ---------------------------------------------------------------------------

def test_volume_profile_poc_in_high_volume_band():
    # most volume concentrated around 50; thin tails at 40 and 60.
    candles = []
    for _ in range(8):
        candles.append(_c(51, 49, 50, 5_000_000.0))   # heavy band ~50
    candles.append(_c(41, 39, 40, 200_000.0))         # thin low
    candles.append(_c(61, 59, 60, 200_000.0))         # thin high
    for _ in range(4):
        candles.append(_c(51, 49, 50, 5_000_000.0))
    atr = levels._atr14(candles) or 2.0
    anchors = levels.extract_volume_profile_levels(candles, 50.0, atr)
    poc = [a for a in anchors if a.method_label == "POC"]
    assert poc, "expected a POC anchor"
    assert abs(poc[0].price - 50.0) <= max(2.0 * atr, 2.0)


# ---------------------------------------------------------------------------
# §3e — virgin POC: an untested high-volume shelf survives; a tested one drops
# ---------------------------------------------------------------------------

def test_virgin_poc_untested_survives_tested_dropped():
    # week 1 (idx 0-4): heavy volume shelf around 100, price then RUNS UP and
    # never returns -> virgin. week 2 (idx 5-9): shelf around 110 that a later
    # bar trades back through -> filled (not virgin).
    candles = []
    # week 1 — shelf @100
    for _ in range(5):
        candles.append(_c(101, 99, 100, 9_000_000.0))
    # week 2 — shelf @110
    for _ in range(5):
        candles.append(_c(111, 109, 110, 4_000_000.0))
    # week 3 — price runs to ~130 but dips back through 110 (fills wk2), never 100
    candles.append(_c(131, 121, 130, 2_000_000.0))
    candles.append(_c(132, 109, 112, 2_000_000.0))   # low 109 fills the 110 shelf
    candles.append(_c(134, 125, 132, 2_000_000.0))
    candles.append(_c(136, 127, 134, 2_000_000.0))
    candles.append(_c(138, 129, 136, 2_000_000.0))
    atr = levels._atr14(candles) or 3.0
    current = 136.0
    anchors = levels.extract_virgin_poc_levels(candles, current, atr, period="week")
    prices = [a.price for a in anchors]
    # the 100 shelf (never retested) should survive as a virgin POC
    assert any(abs(p - 100.0) <= 2.0 * atr for p in prices), prices
    # the 110 shelf was traded back through -> must NOT be virgin
    assert not any(abs(p - 110.0) <= levels._tol(atr, current) for p in prices), prices
    for a in anchors:
        assert a.source_type == "tech_vpoc"


# ---------------------------------------------------------------------------
# build_technical_anchors orchestrator
# ---------------------------------------------------------------------------

def test_build_technical_anchors_runs_all_five():
    candles = _sr_test_series()
    atr = levels._atr14(candles) or 5.0
    anchors = levels.build_technical_anchors(candles, 122.0, atr, 130.0, 95.0)
    assert isinstance(anchors, list)
    # all anchors are tech_* and carry method metadata + 2-decimal prices
    for a in anchors:
        assert a.source_type.startswith("tech_")
        assert a.method_strength is not None
        assert a.method_label
        assert a.price == round(a.price, 2)


def test_build_technical_anchors_noops_on_empty():
    assert levels.build_technical_anchors([], 100.0, 2.0, 110.0, 90.0) == []
    assert levels.build_technical_anchors(_flat_series(100, 30), 0.0, 2.0, 110, 90) == []


# ---------------------------------------------------------------------------
# Ladder — R:R floor REJECTION (never shrink the stop)
# ---------------------------------------------------------------------------

def _tech_sup(price, strength=70.0):
    return levels._method_anchor(price, "tech_sr", strength=strength,
                                 label="swing-S/R x3", freshness_days=2)


def _tech_res(price, strength=70.0):
    return levels._method_anchor(price, "tech_fib", strength=strength,
                                 label="ext 1.272", freshness_days=2)


def test_ladder_rejects_sub_floor_rr_without_shrinking_stop():
    # stop ~95 (5 below spot=100 -> risk ~5), TP1 at 101 -> R:R = 0.2 << 1.5.
    # Must REJECT to rung 3 (ATR fallback), NOT tighten the stop to pass.
    supports = [_tech_sup(95.0)]
    resistances = [_tech_res(101.0)]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0,
        direction="BULLISH", engine_on=True)
    # rejected from rung 1/2 -> falls to rung 3 (ATR fallback, low confidence)
    assert plan["rung"] == 3
    assert plan["confidence"] == "low"
    # the rung-3 ATR stop is spot - 2*ATR = 94.0, NOT a shrunk 99-ish stop.
    assert plan["sl"] == 94.0


def test_ladder_accepts_when_rr_floor_met():
    # spot=100, stop near 96 (risk ~4), TP1 near 110 -> R:R ~3.5 -> accepted.
    supports = [_tech_sup(96.0), _tech_sup(94.0)]
    resistances = [_tech_res(110.0), _tech_res(118.0), _tech_res(126.0)]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0,
        direction="BULLISH", engine_on=True)
    assert plan["rung"] in (1, 2)
    assert plan["risk_reward"] is not None and plan["risk_reward"] >= 1.5
    assert plan["entry"] == 100.0
    assert plan["levels"] is not None
    assert plan["sl"] < 100.0 < plan["tp1"]


def test_ladder_skips_too_close_tp_to_satisfy_rr_floor():
    """A profit level closer than the R:R floor must be SKIPPED for TP1 in favor
    of a farther real level (NOT demoted to a 1.0R filler that pegs R:R at 1.0)."""
    # stop -> risk ~4. A close resistance at 101 (0.25R) plus a real one at 110.
    supports = [_tech_sup(96.0), _tech_sup(94.0)]
    resistances = [_tech_res(101.0), _tech_res(110.0), _tech_res(120.0)]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0,
        direction="BULLISH", engine_on=True)
    assert plan["rung"] in (1, 2)
    # TP1 must be the 110 level (real), not 101 floored to a 1R filler.
    assert plan["tp1"] >= 100.0 + 1.5 * abs(100.0 - plan["sl"])
    assert plan["risk_reward"] >= 1.5


def test_ladder_tp_ladder_is_monotonic_with_fillers():
    """When real levels run out, R-multiple fillers must still sit BEYOND the
    previous TP (no TP3 below TP2)."""
    supports = [_tech_sup(98.0), _tech_sup(96.0)]
    # only one real resistance; TP2/TP3 must be ascending fillers.
    resistances = [_tech_res(108.0), _tech_res(106.0)]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0,
        direction="BULLISH", engine_on=True)
    if plan["rung"] in (1, 2):
        assert plan["tp1"] < plan["tp2"] < plan["tp3"]


def test_method_strength_survives_clustering():
    """A merged tech cluster must retain method_strength/label (not lose them to
    None) so the rung-2 strength gate + embed provenance keep working. The label
    + strength track the WINNING tier so they stay coherent with source_type."""
    a = levels._method_anchor(100.0, "tech_sr", strength=70.0,
                              label="swing-S/R x3", freshness_days=2)
    b = levels._method_anchor(100.2, "tech_fib", strength=85.0,
                              label="golden-pocket 0.618", freshness_days=2)
    merged = levels.cluster_anchors([a, b], 0.005)
    assert len(merged) == 1
    # merged tier is tech_sr (higher than tech_fib); strength + label follow it.
    assert merged[0].source_type == "tech_sr"
    assert merged[0].method_strength == 70.0
    assert merged[0].method_label == "swing-S/R x3"


def test_method_strength_carried_when_no_tier_match():
    """When the winning tier has no method_strength, fall back to the overall
    strongest contributor (so a merged anchor never silently loses strength)."""
    # winning tier 'swing' (legacy, no method_strength) + a tech_sr contributor.
    legacy = levels.Anchor(price=100.0, source="swing_low", source_type="swing")
    tech = levels._method_anchor(100.2, "tech_sr", strength=66.0,
                                 label="swing-S/R x2", freshness_days=1)
    merged = levels.cluster_anchors([legacy, tech], 0.005)
    assert len(merged) == 1
    assert merged[0].source_type == "swing"           # swing tier wins
    assert merged[0].method_strength == 66.0           # carried from tech_sr
    assert merged[0].method_label == "swing-S/R x2"


# ---------------------------------------------------------------------------
# Ladder — never place a stop inside an LVN
# ---------------------------------------------------------------------------

def test_ladder_never_stops_inside_lvn():
    # best support sits right where an LVN is -> the LVN-adjacent stop must be
    # skipped; the next clean support is used instead.
    lvn = levels._method_anchor(96.0, "tech_vp", strength=40.0, label="LVN",
                                freshness_days=1)
    near_lvn_sup = _tech_sup(96.2)     # stop would land ~96 -> inside LVN band
    clean_sup = _tech_sup(90.0)        # clean support further down
    supports = [near_lvn_sup, clean_sup, lvn]
    resistances = [_tech_res(120.0), _tech_res(130.0), _tech_res(140.0)]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0,
        direction="BULLISH", engine_on=True)
    if plan["rung"] in (1, 2):
        # stop must not sit within 0.5*ATR of the LVN at 96.0
        assert abs(plan["sl"] - 96.0) > 0.5 * 3.0, plan["sl"]


# ---------------------------------------------------------------------------
# FLAG-OFF byte-identical — including a MIXED swing+yt cluster
# ---------------------------------------------------------------------------

def _sup(price, st="swing"):
    return levels.Anchor(price=price, source="s", source_type=st)


def _res(price, st="web"):
    return levels.Anchor(price=price, source="r", source_type=st)


def test_flag_off_byte_identical_no_new_keys():
    """engine_on default (False) -> exactly the 6 historical keys, no extras."""
    supports = [_sup(p) for p in [95, 94, 93, 92]]
    resistances = [_res(p) for p in [105, 110, 115]]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0, direction="BULLISH")
    assert set(plan.keys()) == {
        "sl", "tp1", "tp2", "tp3", "suppression_reason", "confidence"}


def test_flag_off_mixed_swing_yt_cluster_resolves_to_swing():
    """The SOURCE_TIER_ORDER insertion (tech_* between swing and yt) must NOT
    reorder the pre-existing types: a merged swing+yt cluster still resolves to
    swing via _max_tier (byte-identical to before Wave 2)."""
    # swing wins over yt
    assert levels._max_tier(["yt", "swing"]) == "swing"
    assert levels._max_tier(["swing", "yt"]) == "swing"
    # yt_curated still tops everything
    assert levels._max_tier(["web", "yt", "swing", "yt_curated"]) == "yt_curated"
    # web is still last
    assert levels._max_tier(["web", "yt"]) == "yt"

    # full cluster path: two anchors within 0.5% -> merged cluster source_type.
    a_swing = levels.Anchor(price=100.0, source="swing_low", source_type="swing")
    a_yt = levels.Anchor(price=100.2, source="youtube:X", source_type="yt")
    merged = levels.cluster_anchors([a_yt, a_swing], 0.005)
    assert len(merged) == 1
    assert merged[0].source_type == "swing"   # swing > yt, unchanged by Wave 2


def test_flag_off_plan_unchanged_vs_legacy_value():
    """A concrete plan must equal the pre-Wave-2 result exactly."""
    supports = [_sup(p) for p in [95, 94, 93, 92]]
    resistances = [_res(p) for p in [105, 110, 115]]
    plan = levels.select_trade_plan(
        supports, resistances, spot=100.0, atr14=3.0, direction="BULLISH")
    assert plan == {
        "sl": 95.0, "tp1": 105.0, "tp2": 110.0, "tp3": 115.0,
        "suppression_reason": None, "confidence": None,
    }


# ---------------------------------------------------------------------------
# Tier order / multiplier wiring
# ---------------------------------------------------------------------------

def test_source_tier_order_inserts_tech_between_swing_and_yt():
    order = levels.SOURCE_TIER_ORDER
    assert order.index("swing") < order.index("tech_sr") < order.index("yt")
    # relative order of pre-existing types preserved
    assert order.index("yt_curated") < order.index("swing") < order.index("yt") < order.index("web")


def test_score_v2_tier_multipliers_have_tech_keys():
    m = levels.SCORE_V2_TIER_MULTIPLIERS
    assert m["tech_sr"] == 0.75
    assert m["tech_vpoc"] == 0.70
    assert m["tech_vp"] == 0.65
    assert m["tech_zone"] == 0.6
    assert m["tech_fib"] == 0.55
