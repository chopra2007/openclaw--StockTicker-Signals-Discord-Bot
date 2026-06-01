"""Unit tests for the two cheap !all levers (all-quality-cheap-levers):
  * Relative Volume — structured_fields.compute_relative_volume + embed "Rel Vol" field.
  * 52-week high/low distance — snapshot pct math + embed _format_snapshot segment.
"""
from __future__ import annotations

import math

import pytest

from consensus_engine.alerts.all_command import embed
from consensus_engine.alerts.all_command.structured_fields import compute_relative_volume


# ---------------------------------------------------------------------------
# Lever 1 — compute_relative_volume
# ---------------------------------------------------------------------------

def _candles(volumes):
    """Build minimal candle dicts carrying the given volumes."""
    return [{"high": 1.0, "low": 1.0, "close": 1.0, "volume": v} for v in volumes]


def test_relative_volume_normal():
    # 20 prior candles each at volume 100 (avg 100), last at 180 -> 1.8.
    candles = _candles([100.0] * 20 + [180.0])
    assert compute_relative_volume(candles) == 1.8


def test_relative_volume_rounds_two_places():
    candles = _candles([100.0] * 20 + [333.0])
    assert compute_relative_volume(candles) == 3.33


def test_relative_volume_too_few_candles_returns_none():
    # Only 20 candles total; needs lookback+1 = 21.
    assert compute_relative_volume(_candles([100.0] * 20)) is None


def test_relative_volume_zero_average_returns_none():
    candles = _candles([0.0] * 20 + [500.0])
    assert compute_relative_volume(candles) is None


def test_relative_volume_missing_volume_tolerated():
    # 21 numeric-volume candles survive after dropping None/NaN entries.
    good = _candles([100.0] * 20 + [200.0])
    noise = [
        {"high": 1.0, "low": 1.0, "close": 1.0, "volume": None},
        {"high": 1.0, "low": 1.0, "close": 1.0, "volume": float("nan")},
        {"high": 1.0, "low": 1.0, "close": 1.0},  # missing key entirely
    ]
    # Interleave noise; it should be skipped, leaving the same 1.8x ratio.
    candles = noise + good
    assert compute_relative_volume(candles) == 2.0


def test_relative_volume_not_enough_numeric_after_dropping_returns_none():
    candles = _candles([100.0] * 10) + [
        {"high": 1.0, "low": 1.0, "close": 1.0, "volume": None} for _ in range(15)
    ]
    assert compute_relative_volume(candles) is None


def test_relative_volume_non_list_returns_none():
    assert compute_relative_volume(None) is None
    assert compute_relative_volume("not a list") is None


# ---------------------------------------------------------------------------
# Lever 1 — embed "Rel Vol" field
# ---------------------------------------------------------------------------

class _FakeStructured:
    direction = "BULLISH"
    confidence_label = "HIGH"
    current_price = 180.00
    buy_zone_low = 178.00
    buy_zone_high = 180.00
    sl = 175.00
    tp1 = 190.00
    tp2 = 200.00
    tp3 = 210.00
    earnings_date = None
    breakout_timeframe = "TBD"
    magnitude_label = "TBD"
    next_catalyst_days = 3
    swing_horizon_days = 14
    swing_horizon_band = (10, 18)
    expected_move_typical = 5.0
    expected_move_high_vol = 8.0
    magnitude_band_label = "±$5–$8 / 2w"
    relative_volume = None


class _FakeBreakdown:
    total = 82
    news_catalyst = 20
    social_apewisdom = 0
    social_stocktwits = 0
    social_reddit = 0
    google_trends = 0
    technical = 30
    llm_boost = 20
    options_flow = 0
    consensus_boost = 12


def _build(structured):
    return embed.build_embed(
        ticker="NVDA",
        structured=structured,
        score_breakdown=_FakeBreakdown(),
        narrative="**TL;DR:** thesis.\nBody.",
        sources_used=["news"],
        cache_age_seconds=None,
    )


def test_build_embed_shows_rel_vol_when_set():
    s = _FakeStructured()
    s.relative_volume = 1.8
    payload = _build(s)
    rv = next((f for f in payload["fields"] if f["name"] == "Rel Vol"), None)
    assert rv is not None
    assert rv["value"] == "1.8×"
    assert rv["inline"] is True


def test_build_embed_omits_rel_vol_when_none():
    s = _FakeStructured()
    s.relative_volume = None
    payload = _build(s)
    assert "Rel Vol" not in [f["name"] for f in payload["fields"]]


def test_build_embed_omits_rel_vol_when_zero():
    s = _FakeStructured()
    s.relative_volume = 0.0
    payload = _build(s)
    assert "Rel Vol" not in [f["name"] for f in payload["fields"]]


# ---------------------------------------------------------------------------
# Lever 2 — 52-week pct math (mirrors snapshot.py formula)
# ---------------------------------------------------------------------------

def _wk52_high_pct(price, high):
    return (price / high - 1) * 100 if price and high and high > 0 else None


def _wk52_low_pct(price, low):
    return (price / low - 1) * 100 if price and low and low > 0 else None


def test_wk52_high_pct_below_high_is_negative():
    # Price 96 vs high 100 -> -4% (below high).
    assert _wk52_high_pct(96.0, 100.0) == pytest.approx(-4.0)


def test_wk52_low_pct_above_low_is_positive():
    # Price 110 vs low 100 -> +10% (above low).
    assert _wk52_low_pct(110.0, 100.0) == pytest.approx(10.0)


def test_wk52_pct_missing_price_or_levels_returns_none():
    assert _wk52_high_pct(None, 100.0) is None
    assert _wk52_high_pct(96.0, None) is None
    assert _wk52_high_pct(96.0, 0.0) is None
    assert _wk52_low_pct(None, 100.0) is None


# ---------------------------------------------------------------------------
# Lever 2 — _format_snapshot 52wk segment
# ---------------------------------------------------------------------------

def test_format_snapshot_includes_52wk_below_segment():
    snap = {"target_mean": 200.0, "n_analysts": 30, "wk52_high_pct": -4.0}
    out = embed._format_snapshot(snap)
    assert "4% below 52wk high" in out


def test_format_snapshot_includes_52wk_above_segment():
    snap = {"fwd_pe": 25.0, "wk52_high_pct": 3.0}
    out = embed._format_snapshot(snap)
    assert "3% above 52wk high" in out


def test_format_snapshot_omits_52wk_when_missing_but_still_renders():
    # No wk52 key: segment omitted, but analyst/fundamentals still render.
    snap = {"target_mean": 200.0, "n_analysts": 30}
    out = embed._format_snapshot(snap)
    assert "52wk" not in out
    assert out != "—"
    assert "200" in out


def test_format_snapshot_renders_on_analyst_with_52wk():
    # Missing high/low/price upstream -> wk52_high_pct is None -> segment omitted,
    # snapshot still renders because analyst data is present.
    snap = {"rating": "Buy", "wk52_high_pct": None}
    out = embed._format_snapshot(snap)
    assert "52wk" not in out
    assert out != "—"
