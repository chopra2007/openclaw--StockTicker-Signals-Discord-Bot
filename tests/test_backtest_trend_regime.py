"""Tests for the F3 trend-regime back-test pure helpers.

These exercise the regime / return / win-rate math WITHOUT any yfinance download:
  * trend_state_series reproduces the FROZEN consensus_engine.analysis.regime
    ._compute_trend components EXACTLY on sample dates (no backtest-vs-live drift);
  * forward_long_returns uses the close[i+h]/close[i]-1 long convention;
  * win_rate is the fraction of strictly-positive forward returns (NaN-safe);
  * regime_gap reports above-200DMA minus below-200DMA in percentage points;
  * permutation_gap_pvalue is small for an extreme gap and ~0.5 for no gap
    (deterministic with the frozen seed).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "volatility_regime_reversal_indicator"))

from consensus_engine.analysis.regime import _compute_trend  # noqa: E402
from scripts.backtest_trend_regime import (  # noqa: E402
    forward_long_returns,
    permutation_gap_pvalue,
    regime_gap,
    trend_state_series,
    win_rate,
)


# ---------------------------------------------------------------------------
# trend_state_series must match the FROZEN _compute_trend (no drift)
# ---------------------------------------------------------------------------

def _synthetic_closes(n: int = 300, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    # a gently trending random walk so 200DMA / slope / tsmom are all non-trivial
    steps = rng.normal(0.05, 1.0, size=n)
    levels = 100 + np.cumsum(steps)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(levels, index=idx)


def test_trend_state_series_matches_frozen_compute_trend():
    closes = _synthetic_closes(300)
    series = trend_state_series(closes)
    closes_list = closes.tolist()
    # check several point-in-time dates against the frozen scalar engine
    for i in (250, 275, 299):
        frozen = _compute_trend(closes_list[: i + 1], "2020-01-01")
        assert frozen is not None
        row = series.iloc[i]
        assert row["close"] == pytest.approx(frozen["close"])
        assert row["sma_200"] == pytest.approx(frozen["sma_200"])
        assert row["sma_50"] == pytest.approx(frozen["sma_50"])
        assert row["sma_50_slope"] == pytest.approx(frozen["sma_50_slope"])
        assert row["tsmom_3m"] == pytest.approx(frozen["tsmom_3m"])
        assert bool(row["above_200"]) == (frozen["close"] > frozen["sma_200"])
        assert row["trend_state"] == frozen["trend_state"]


def test_trend_state_series_leading_nan_before_200dma():
    closes = _synthetic_closes(300)
    series = trend_state_series(closes)
    # before 200 closes exist the 200DMA (and thus above_200) is undefined
    assert np.isnan(series["sma_200"].iloc[100])
    assert series["above_200"].iloc[100] is np.False_ or not bool(series["above_200"].iloc[100])
    # after 200 closes it is defined
    assert not np.isnan(series["sma_200"].iloc[250])


# ---------------------------------------------------------------------------
# forward_long_returns
# ---------------------------------------------------------------------------

def test_forward_long_returns_simple():
    idx = pd.bdate_range("2024-01-01", periods=5)
    closes = pd.Series([100.0, 110.0, 121.0, 121.0, 130.0], index=idx)
    fr = forward_long_returns(closes, [1, 2])
    # h=1 at i=0: 110/100-1 = +10%
    assert fr[1].iloc[0] == pytest.approx(0.10)
    # h=2 at i=0: 121/100-1 = +21%
    assert fr[2].iloc[0] == pytest.approx(0.21)
    # tail rows with no future close are NaN
    assert np.isnan(fr[1].iloc[-1])
    assert np.isnan(fr[2].iloc[-1])


# ---------------------------------------------------------------------------
# win_rate
# ---------------------------------------------------------------------------

def test_win_rate_counts_strictly_positive():
    r = np.array([0.01, -0.02, 0.0, 0.03, np.nan])
    # 2 of 4 valid (NaN dropped, 0.0 not a win) -> 0.5
    assert win_rate(r) == pytest.approx(0.5)


def test_win_rate_empty_is_nan():
    assert np.isnan(win_rate(np.array([np.nan, np.nan])))


# ---------------------------------------------------------------------------
# regime_gap
# ---------------------------------------------------------------------------

def test_regime_gap_above_minus_below():
    fwd = np.array([0.02, 0.01, -0.01, -0.02])
    above = np.array([True, True, False, False])
    below = np.array([False, False, True, True])
    g = regime_gap(fwd, above, below)
    assert g["above_wr"] == pytest.approx(1.0)
    assert g["below_wr"] == pytest.approx(0.0)
    assert g["wr_gap_pp"] == pytest.approx(100.0)
    assert g["above_mean"] == pytest.approx(0.015)
    assert g["below_mean"] == pytest.approx(-0.015)
    # unconditional baseline = all four valid rows
    assert g["baseline_wr"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# permutation_gap_pvalue (deterministic with the frozen seed)
# ---------------------------------------------------------------------------

def test_permutation_gap_pvalue_extreme_is_small():
    # perfectly separated: all above-days win, all below-days lose -> tiny p
    n = 200
    fwd = np.concatenate([np.full(n, 0.01), np.full(n, -0.01)])
    above = np.concatenate([np.ones(n, bool), np.zeros(n, bool)])
    below = ~above
    p = permutation_gap_pvalue(fwd, above, below, n_draws=500, seed=1729)
    assert p < 0.01


def test_permutation_gap_pvalue_no_gap_is_large():
    rng = np.random.default_rng(0)
    fwd = rng.normal(0, 0.01, size=400)
    above = np.array([True, False] * 200)
    below = ~above
    p = permutation_gap_pvalue(fwd, above, below, n_draws=500, seed=1729)
    assert p > 0.1
