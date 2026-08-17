"""T1-b (#76 menu) — VVIX "fear-of-fear" residual (scripts/market_daily.py + !market).

The gauge is the rolling-252 OLS residual of log(VVIX) on log(VIX), ranked against
its own trailing year: what vol-of-vol costs AFTER stripping out whatever the spot
VIX already explains. Maths ported from the sibling volatility project.

Asserts:
  * the ported OLS residual is 0 on an exactly-linear relationship, and equals the
    known gap when one point is displaced
  * trailing_percentile ranks the current obs within its window
  * build_vvix_rows aligns ^VVIX and ^VIX even though yfinance returns them in
    DIFFERENT timezones (New York vs Chicago) — the bug that produced zero rows
  * too little history → no row (never a half-warmed-up reading)
  * the !market field appears only when a row is passed, and the gauge is NEVER
    referenced by the scorer (descriptive-only hard constraint, TODO #47)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.market_daily as md  # noqa: E402
from consensus_engine.alerts import commands  # noqa: E402


def test_ported_ols_residual_is_zero_on_exact_line():
    """y = 3x + 2 exactly → the trailing fit explains everything, residual 0."""
    x = pd.Series([float(i) for i in range(1, 61)])
    y = 3.0 * x + 2.0
    resid = md._rolling_ols_residual(y, x, 30)
    assert resid.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_ported_ols_residual_catches_a_displaced_point():
    """Displace only the last y by +5 → the residual reports ~+5, not the level."""
    x = pd.Series([float(i) for i in range(1, 61)])
    y = 3.0 * x + 2.0
    y.iloc[-1] += 5.0
    resid = md._rolling_ols_residual(y, x, 30)
    assert resid.iloc[-1] > 4.0  # the fit absorbs a little of the jump; the bulk shows up


def test_trailing_percentile_ranks_within_window():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    pct = md._trailing_percentile(s, 5)
    assert pct.iloc[-1] == pytest.approx(1.0)      # the largest of its 5
    s2 = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
    assert md._trailing_percentile(s2, 5).iloc[-1] == pytest.approx(0.2)  # the smallest


def _fake_history(n: int, tz: str, base: float):
    """A daily Close series stamped midnight in `tz`, like yfinance returns."""
    idx = pd.date_range("2023-01-02", periods=n, freq="B", tz=tz)
    # Gently varying so the OLS window has real (non-degenerate) variance in x.
    closes = [base + (i % 17) * 0.5 for i in range(n)]
    return pd.DataFrame({"Close": closes}, index=idx)


def _patch_yf(vvix_df, vix_df):
    class _T:
        def __init__(self, sym):
            self.sym = sym

        def history(self, period=None):
            return vvix_df if self.sym == "^VVIX" else vix_df

    return patch("yfinance.Ticker", side_effect=_T)


def test_mismatched_timezones_still_align():
    """REGRESSION: yfinance returns ^VVIX in America/New_York and ^VIX in
    America/Chicago. Both are midnight-stamped daily bars, so a naive join matches
    ZERO timestamps and the producer silently wrote no rows. Aligning on the calendar
    date fixes it — this test fails if anyone reverts to joining on the raw index.
    """
    n = 700
    vvix = _fake_history(n, "America/New_York", 90.0)
    vix = _fake_history(n, "America/Chicago", 16.0)
    with _patch_yf(vvix, vix):
        rows = md.build_vvix_rows()
    assert len(rows) == 1, "differing exchange timezones must not zero out the join"
    assert rows[0]["window_days"] == md._VVIX_WINDOW
    assert 0.0 < rows[0]["residual_pct"] <= 1.0


def test_config_window_is_actually_honoured():
    """`features.vvix_residual.window` must DO something. A config knob that the code
    ignores is worse than no knob — you change it, nothing happens, and you don't know."""
    from consensus_engine import config as _cfg
    real_get = _cfg.get

    def fake_get(key, default=None):
        if key == "features.vvix_residual.window":
            return 60          # deliberately not the 252 default
        return real_get(key, default)

    n = 700
    vvix = _fake_history(n, "America/New_York", 90.0)
    vix = _fake_history(n, "America/Chicago", 16.0)
    with patch("consensus_engine.config.get", side_effect=fake_get), _patch_yf(vvix, vix):
        rows = md.build_vvix_rows()
    assert rows and rows[0]["window_days"] == 60, "the configured window must reach the row"


def test_too_little_history_yields_no_row():
    """Under ~504 aligned bars the percentile can't warm up → no row at all."""
    vvix = _fake_history(300, "America/New_York", 90.0)
    vix = _fake_history(300, "America/Chicago", 16.0)
    with _patch_yf(vvix, vix):
        assert md.build_vvix_rows() == []


def test_market_embed_field_only_with_a_row():
    row = {"date_utc": "2026-07-14", "vvix": 93.28, "vix": 16.5,
           "residual": -0.0257, "residual_pct": 0.373, "window_days": 252}
    on = commands._build_market_embed([], [], None, None, "note", vvix_row=row)
    names = [f["name"] for f in on["fields"]]
    assert any("Fear of fear" in n for n in names)
    off = commands._build_market_embed([], [], None, None, "note")
    assert not any("Fear of fear" in f["name"] for f in off["fields"])


def _vvix_row(date_utc, vvix, vix):
    return {
        "date_utc": date_utc,
        "vvix": vvix,
        "vix": vix,
        "residual": 0.0,
        "residual_pct": 0.5,
        "window_days": 252,
        "computed_at": 1.0,
    }


def _fear_line(row):
    embed = commands._build_market_embed([], [], None, None, "note", vvix_row=row)
    return next(f["value"] for f in embed["fields"] if "Fear of fear" in f["name"])


def test_daily_change_positive_sign_and_rounding():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-14", 104.0, 20.4),
        _vvix_row("2026-08-13", 100.0, 20.0),
    )
    line = _fear_line(row)
    assert "VVIX 104.0 (+4.0% today)" in line
    assert "VIX 20.4 (+2.0% today)" in line


def test_daily_change_negative_sign_and_rounding():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-14", 87.48, 14.25),
        _vvix_row("2026-08-13", 89.42, 14.63),
    )
    line = _fear_line(row)
    assert "VVIX 87.5 (−2.2% today)" in line
    assert "VIX 14.2 (−2.6% today)" in line


def test_daily_change_unchanged_value():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-14", 90.0, 15.0),
        _vvix_row("2026-08-13", 90.0, 15.0),
    )
    line = _fear_line(row)
    assert "VVIX 90.0 (0.0% today)" in line
    assert "VIX 15.0 (0.0% today)" in line


def test_daily_change_omitted_without_previous_row():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-14", 90.0, 15.0), None
    )
    assert "% today" not in _fear_line(row)


def test_daily_change_omits_only_zero_previous_value():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-14", 90.0, 15.0),
        _vvix_row("2026-08-13", 0.0, 10.0),
    )
    line = _fear_line(row)
    assert "VVIX 90.0 vs" in line
    assert "VIX 15.0 (+50.0% today)" in line


def test_daily_change_accepts_weekend_gap():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-17", 99.0, 18.0),
        _vvix_row("2026-08-14", 90.0, 15.0),
    )
    line = _fear_line(row)
    assert "VVIX 99.0 (+10.0% today)" in line
    assert "VIX 18.0 (+20.0% today)" in line


def test_daily_change_omitted_when_gap_exceeds_seven_days():
    row = commands._attach_vvix_daily_changes(
        _vvix_row("2026-08-14", 99.0, 18.0),
        _vvix_row("2026-08-06", 90.0, 15.0),
    )
    assert "% today" not in _fear_line(row)


def test_lead_streak_up_three_days():
    rows = [
        _vvix_row("2026-08-14", 110.0, 100.0),  # +10% vvix vs +5% vix -> up lead, day 3
        _vvix_row("2026-08-13", 100.0, 95.24),  # +5% vvix vs +2% vix -> up lead, day 2
        _vvix_row("2026-08-12", 95.24, 93.37),  # +3% vvix vs +1% vix -> up lead, day 1
        _vvix_row("2026-08-11", 92.47, 92.45),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "up"
    assert result["streak_days"] == 3
    assert result["lead_pts"] == pytest.approx(5.0, abs=0.05)


def test_lead_streak_down_two_days():
    rows = [
        _vvix_row("2026-08-14", 90.0, 97.0),   # -10% vvix vs -3% vix -> down lead, day 2
        _vvix_row("2026-08-13", 100.0, 100.0),  # -5% vvix vs -2% vix -> down lead, day 1
        _vvix_row("2026-08-12", 105.26, 102.04),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "down"
    assert result["streak_days"] == 2
    assert result["lead_pts"] == pytest.approx(-7.0, abs=0.05)


def test_lead_streak_mixed_direction_does_not_extend():
    rows = [
        _vvix_row("2026-08-14", 110.0, 100.0),  # up lead today
        _vvix_row("2026-08-13", 100.0, 99.0),   # yesterday was a down move for vvix -> no streak carried
        _vvix_row("2026-08-12", 105.0, 95.0),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "up"
    assert result["streak_days"] == 1


def test_lead_streak_exact_tie_is_no_lead():
    # Deliberately built off DIFFERENT price scales (VVIX ~100, VIX ~10), the way
    # the real indexes sit. Both move +1%, but the two percentages land ~1e-15
    # apart in binary — a bare `>` calls that an up-lead and renders the
    # self-contradicting "leading higher by 0.0 pts". A same-scale tie (100->105
    # vs 100->105) computes to exactly 0.0 and would pass either way, so it does
    # not test what it looks like it tests.
    rows = [
        _vvix_row("2026-08-14", 101.0, 10.10),  # both exactly +1% -> tie, no lead
        _vvix_row("2026-08-13", 100.0, 10.00),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] is None
    assert result["streak_days"] == 0
    assert result["lead_pts"] == pytest.approx(0.0)

    down = [
        _vvix_row("2026-08-14", 99.0, 19.8),   # both exactly -1% -> tie, no lead
        _vvix_row("2026-08-13", 100.0, 20.0),
    ]
    down_result = commands.compute_vvix_lead_streak(down)
    assert down_result["direction"] is None
    assert down_result["streak_days"] == 0


def test_lead_streak_tie_mid_streak_stops_it():
    """A floating-point tie must break a streak, not silently extend it."""
    rows = [
        _vvix_row("2026-08-14", 110.0, 100.0),  # +10% vs +5% -> real up lead today
        _vvix_row("2026-08-13", 100.0, 95.2381),  # tie day (both +1%) off different scales
        _vvix_row("2026-08-12", 99.0099, 94.2951),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "up"
    assert result["streak_days"] == 1


def test_lead_streak_weekend_gap_continues_streak():
    rows = [
        _vvix_row("2026-08-17", 121.0, 105.0),  # Monday, +10% vvix vs +5% vix over Fri->Mon
        _vvix_row("2026-08-14", 110.0, 100.0),  # Friday, +10% vvix vs +5% vix
        _vvix_row("2026-08-13", 100.0, 95.24),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "up"
    assert result["streak_days"] == 2


def test_lead_streak_holiday_gap_continues_streak():
    rows = [
        _vvix_row("2026-08-18", 121.0, 105.0),  # 4 calendar days after the prior row
        _vvix_row("2026-08-14", 110.0, 100.0),
        _vvix_row("2026-08-13", 100.0, 95.24),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "up"
    assert result["streak_days"] == 2


def test_lead_streak_stops_at_a_six_day_data_hole():
    rows = [
        _vvix_row("2026-08-14", 110.0, 100.0),
        _vvix_row("2026-08-13", 100.0, 95.24),
        _vvix_row("2026-08-07", 95.24, 93.37),  # 6 calendar days back -> real data hole
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result["direction"] == "up"
    assert result["streak_days"] == 1


def test_lead_streak_needs_two_rows():
    assert commands.compute_vvix_lead_streak([]) == {
        "lead_pts": None, "direction": None, "streak_days": 0,
    }
    assert commands.compute_vvix_lead_streak([_vvix_row("2026-08-14", 90.0, 15.0)]) == {
        "lead_pts": None, "direction": None, "streak_days": 0,
    }


def test_lead_streak_zero_or_none_prior_value_no_crash():
    rows = [
        _vvix_row("2026-08-14", 90.0, 15.0),
        _vvix_row("2026-08-13", 0.0, 15.0),
    ]
    result = commands.compute_vvix_lead_streak(rows)
    assert result == {"lead_pts": None, "direction": None, "streak_days": 0}

    rows2 = [
        _vvix_row("2026-08-14", 90.0, 15.0),
        {"date_utc": "2026-08-13", "vvix": None, "vix": 15.0},
    ]
    assert commands.compute_vvix_lead_streak(rows2) == {
        "lead_pts": None, "direction": None, "streak_days": 0,
    }


def test_lead_line_has_no_predictive_wording():
    rows = [
        _vvix_row("2026-08-14", 110.0, 100.0),
        _vvix_row("2026-08-13", 100.0, 95.24),
        _vvix_row("2026-08-12", 95.24, 93.37),
    ]
    row = commands._attach_vvix_daily_changes(rows[0], rows[1])
    row.update(commands.compute_vvix_lead_streak(rows))
    line = _fear_line(row)
    assert "VVIX leading higher by" in line
    for word in ("foreshadow", "signal", "expect", "suggest"):
        assert word not in line.lower()


def test_gauge_is_never_read_by_the_scorer():
    """Hard constraint (#47): descriptive only. If the scorer ever learns the word
    'vvix' or reads vol_of_vol_daily, this feature has become the VIX predictor the
    project already rejected."""
    scorer = Path(__file__).resolve().parent.parent / "consensus_engine" / "cross_reference.py"
    src = scorer.read_text().lower()
    assert "vvix" not in src
    assert "vol_of_vol" not in src
