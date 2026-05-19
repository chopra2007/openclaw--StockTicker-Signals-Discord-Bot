"""W4 ATOMIC mega-wave tests: ATR wiring, swing horizon, magnitude band,
narrator computed_signal + Trade Plan, embed shape, vault schema_version.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from consensus_engine.alerts.all_command import embed as embed_mod
from consensus_engine.alerts.all_command import narrator as narrator_mod
from consensus_engine.alerts.all_command import vault_writer
from consensus_engine.alerts.all_command.structured_fields import (
    StructuredFields,
    compute_magnitude_band,
    compute_next_catalyst_days,
    compute_swing_horizon,
)
from consensus_engine.models import OptionsResult, ScoreBreakdown, TechnicalResult


# ---------------------------------------------------------------------------
# B-M0 — ATR wiring on TechnicalResult
# ---------------------------------------------------------------------------

def test_technical_result_has_atr14_field():
    tr = TechnicalResult(ticker="NVDA")
    assert hasattr(tr, "atr14")
    assert tr.atr14 is None


def test_technical_result_atr14_assignable():
    tr = TechnicalResult(ticker="NVDA", atr14=4.2)
    assert tr.atr14 == 4.2


# ---------------------------------------------------------------------------
# Swing horizon math
# ---------------------------------------------------------------------------

def test_swing_horizon_basic_bullish():
    days, band, note = compute_swing_horizon(spot=100.0, tp1=110.0, atr14=2.0)
    # |10|/(0.7×2) = 10/1.4 ≈ 7.1 days → 7
    assert days == 7
    assert band == (5, 9)
    assert note is None


def test_swing_horizon_bearish_uses_abs_value():
    """CEF-8 fix: bearish setup (tp1 < spot) must not produce negative days."""
    days, band, note = compute_swing_horizon(spot=100.0, tp1=90.0, atr14=2.0)
    assert days == 7
    assert days > 0
    assert band == (5, 9)


def test_swing_horizon_at_target_when_tp1_within_half_pct():
    days, band, note = compute_swing_horizon(spot=100.0, tp1=100.4, atr14=2.0)
    assert days == 0
    assert band == (0, 0)
    assert note == "at target"


def test_swing_horizon_floor_holds_through_near_earnings():
    """TODO #12: earnings within the swing floor (≤5d) does NOT compress
    horizon — trade is allowed to hold through the catalyst. Pre-fix this
    case capped to 3 days; post-fix it stays at the computed swing horizon
    (14 days here) so SL drawdown % stays coherent with horizon × ATR."""
    er = (date.today() + timedelta(days=3)).isoformat()
    days, band, note = compute_swing_horizon(
        spot=100.0, tp1=120.0, atr14=2.0, earnings_date=er,
    )
    # |20|/(0.7×2) ≈ 14 days; earnings T-3 < swing floor → no cap
    assert days == 14


def test_swing_horizon_capped_at_far_earnings():
    """TODO #12: earnings BEYOND the swing floor still cap horizon (preserves
    the original swing_v2 design intent for normal earnings windows)."""
    er = (date.today() + timedelta(days=10)).isoformat()
    days, band, note = compute_swing_horizon(
        spot=100.0, tp1=120.0, atr14=2.0, earnings_date=er,
    )
    # |20|/(0.7×2) ≈ 14 days; earnings T-10 > swing floor → cap at 10
    assert days == 10


def test_swing_horizon_intraday_catalyst_skips_floor():
    """TODO #12: T-0 earnings (catalyst today) bypasses the swing floor —
    the trader is doing an intraday play, not a multi-day swing."""
    er = date.today().isoformat()
    days, band, note = compute_swing_horizon(
        spot=100.0, tp1=101.0, atr14=2.0, earnings_date=er,
    )
    # |1|/(0.7×2) = 0.71 → 1 day, T-0 catalyst preserves the 1-day est
    assert days == 1


def test_swing_horizon_floor_applied_when_no_catalyst():
    """TODO #12: with no earnings and a 1×ATR TP1 (ATR-fallback shape),
    horizon floors at SWING_FLOOR_DAYS (5) instead of dropping to 1.43d."""
    # spot=100, tp1=102, atr=2 → raw=2/(0.7×2)=1.43d → floor to 5
    days, band, note = compute_swing_horizon(spot=100.0, tp1=102.0, atr14=2.0)
    assert days == 5


def test_swing_horizon_long_horizon_cap():
    days, band, note = compute_swing_horizon(spot=100.0, tp1=2000.0, atr14=0.5)
    # |1900|/(0.7×0.5) = 1900/0.35 ≈ 5428 days → capped to 365
    assert days == 365
    assert note == "12+ months"
    assert band == (300, 450)


def test_swing_horizon_none_when_atr_missing():
    days, band, note = compute_swing_horizon(spot=100.0, tp1=110.0, atr14=None)
    assert days is None and band is None and note is None


def test_swing_horizon_none_when_spot_missing():
    days, band, note = compute_swing_horizon(spot=None, tp1=110.0, atr14=2.0)
    assert days is None and band is None and note is None


# ---------------------------------------------------------------------------
# Magnitude band math
# ---------------------------------------------------------------------------

def test_magnitude_band_typical_uses_sqrt_horizon():
    typical, high_vol, rendered = compute_magnitude_band(
        atr14=2.0, horizon_days=9, spot=100.0,
    )
    # 2.0 × sqrt(9) = 6.0
    assert typical == pytest.approx(6.0, rel=1e-3)
    assert high_vol is None
    assert "±$6" in rendered


def test_magnitude_band_with_90d_high_vol():
    typical, high_vol, rendered = compute_magnitude_band(
        atr14=2.0, horizon_days=9, spot=100.0, atr_90d_high_pct=0.08,
    )
    assert typical == pytest.approx(6.0, rel=1e-3)
    assert high_vol == pytest.approx(8.0, rel=1e-3)  # 0.08 × 100


def test_magnitude_band_none_when_atr_missing():
    typical, high_vol, rendered = compute_magnitude_band(
        atr14=None, horizon_days=10, spot=100.0,
    )
    assert typical is None and high_vol is None and rendered is None


def test_magnitude_band_none_when_horizon_zero_or_none():
    a = compute_magnitude_band(atr14=2.0, horizon_days=0, spot=100.0)
    b = compute_magnitude_band(atr14=2.0, horizon_days=None, spot=100.0)
    assert a == (None, None, None)
    assert b == (None, None, None)


# ---------------------------------------------------------------------------
# Next catalyst days
# ---------------------------------------------------------------------------

def test_next_catalyst_days_uses_earnings_when_future():
    er = (date.today() + timedelta(days=12)).isoformat()
    assert compute_next_catalyst_days(er, None) == 12


def test_next_catalyst_days_skips_past_earnings():
    er = (date.today() - timedelta(days=5)).isoformat()
    options = OptionsResult(ticker="NVDA")
    assert compute_next_catalyst_days(er, options) is None


def test_next_catalyst_days_falls_through_to_options_expiry():
    """No earnings → options top_contract date when ISO-formatted."""
    options = OptionsResult(ticker="NVDA")
    options.top_contract = (date.today() + timedelta(days=20)).isoformat()
    assert compute_next_catalyst_days(None, options) == 20


def test_next_catalyst_days_none_when_nothing_available():
    assert compute_next_catalyst_days(None, None) is None


# ---------------------------------------------------------------------------
# Embed field shape — v2 (default) renders Next Catalyst + Horizon +
# Expected Move; v0 renders Timeframe + Magnitude. 11 vs 10 fields.
# ---------------------------------------------------------------------------

def test_embed_v2_renders_next_catalyst_swing_horizon_expected_move():
    s = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=98.5, tp1=112, tp2=125, tp3=140,
        breakout_timeframe="earnings 2026-05-15",
        magnitude_label="±$8.20 (2× ATR)",
        current_price=110.0, buy_zone_low=105.0, buy_zone_high=110.0,
        next_catalyst_days=4,
        swing_horizon_days=10,
        swing_horizon_band=(8, 13),
        expected_move_typical=8.5,
        magnitude_band_label="±$8 / 10d",
    )
    sb = ScoreBreakdown(news_catalyst=20)
    out = embed_mod.build_embed("NVDA", s, sb, "n", ["a"], None)
    names = [f["name"] for f in out["fields"]]
    assert "Next Catalyst" in names
    assert "Horizon" in names
    assert "Expected Move" in names
    assert "Timeframe" not in names
    assert "Magnitude" not in names
    assert len(out["fields"]) == 11


def test_embed_v0_renders_timeframe_magnitude(monkeypatch):
    """Operator can flip swing_v2_enabled=false → revert to v0 shape."""
    monkeypatch.setattr(
        "consensus_engine.config.get",
        lambda key, default=None: False if key == "all_command.swing_v2_enabled" else default,
    )
    s = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        breakout_timeframe="earnings 2026-05-15",
        magnitude_label="±$8.20 (2× ATR)",
        current_price=110.0,
    )
    sb = ScoreBreakdown(news_catalyst=20)
    out = embed_mod.build_embed("NVDA", s, sb, "n", ["a"], None)
    names = [f["name"] for f in out["fields"]]
    assert "Timeframe" in names
    assert "Magnitude" in names
    assert "Horizon" not in names
    assert len(out["fields"]) == 10


# ---------------------------------------------------------------------------
# Narrator computed_signal — v2 dict has new keys
# ---------------------------------------------------------------------------

def test_narrator_computed_signal_v2_keys_present():
    s = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=98, tp1=112, tp2=120, tp3=140, current_price=110.0,
        next_catalyst_days=4, swing_horizon_days=10,
        swing_horizon_band=(8, 13), expected_move_typical=8.5,
        magnitude_band_label="±$8 / 10d",
    )
    sb = ScoreBreakdown()
    messages = narrator_mod._build_synthesis_prompt(
        "NVDA", s, sb, [], [], [], "", "{}",
    )
    user_msg = messages[1]["content"]
    assert '"next_catalyst_days": 4' in user_msg
    assert '"swing_horizon_days": 10' in user_msg
    assert '"expected_move_band"' in user_msg
    # Trade Plan rows in prompt
    assert "Horizon" in user_msg
    assert "Expected Move" in user_msg
    assert "Next Catalyst" in user_msg


def test_narrator_constraints_block_v0_keeps_v0_table(monkeypatch):
    monkeypatch.setattr(
        "consensus_engine.config.get",
        lambda key, default=None: False if key == "all_command.swing_v2_enabled" else default,
    )
    block = narrator_mod._build_constraints_block(swing_v2=False)
    assert "Horizon" not in block
    assert "Expected Move" not in block
    assert "Buy Zone" in block
    assert "TP1" in block


# ---------------------------------------------------------------------------
# Vault schema_version bump
# ---------------------------------------------------------------------------

def test_vault_writer_v2_includes_schema_version_2_and_new_keys():
    s = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        sl=98.5, tp1=112, tp2=125, tp3=140,
        next_catalyst_days=4,
        swing_horizon_days=10, swing_horizon_band=(8, 13),
        magnitude_band_label="±$8 / 10d",
    )
    sb = ScoreBreakdown()
    md = vault_writer.render_all_command_markdown(
        ticker="NVDA",
        structured=s,
        score_breakdown=sb,
        narrative="ok",
        sources_used=[],
        alert_history=[],
        anchors_used=[],
    )
    assert "schema_version=2" in md
    assert "Next Catalyst: 4d" in md
    assert "Horizon: 8–13 days" in md
    assert "Expected Move: ±$8 / 10d" in md
    assert "Timeframe:" not in md
    assert "Magnitude:" not in md


def test_vault_writer_v0_uses_schema_version_1(monkeypatch):
    monkeypatch.setattr(
        "consensus_engine.config.get",
        lambda key, default=None: False if key == "all_command.swing_v2_enabled" else default,
    )
    s = StructuredFields(
        direction="BULLISH", confidence_label="HIGH",
        breakout_timeframe="1-3w",
        magnitude_label="±$5.00 (2× ATR)",
    )
    sb = ScoreBreakdown()
    md = vault_writer.render_all_command_markdown(
        ticker="NVDA",
        structured=s,
        score_breakdown=sb,
        narrative="ok",
        sources_used=[],
        alert_history=[],
        anchors_used=[],
    )
    assert "schema_version=1" in md
    assert "Timeframe: 1-3w" in md
    assert "Magnitude: ±$5.00 (2× ATR)" in md
