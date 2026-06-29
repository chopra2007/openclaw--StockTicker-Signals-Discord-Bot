"""Tests for the F1 sector-rotation back-test pure helpers.

These exercise the statistics/return math WITHOUT any yfinance download:
  * forward_relative_returns uses the next-open entry / close-h exit convention
    and subtracts the benchmark's own forward return (sector-vs-market);
  * benjamini_hochberg matches a hand-worked BH step-up example;
  * permutation_pvalue is small when the observed mean sits at the top of the
    pool and ~0.5 at the pool median (deterministic with the frozen seed);
  * spearman is +1 / -1 on monotone data and NaN-safe;
  * collapse_episodes keeps only the first flag inside the window.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.backtest_sector_rotation import (
    benjamini_hochberg,
    collapse_episodes,
    forward_relative_returns,
    permutation_pvalue,
    spearman,
)


# ---------------------------------------------------------------------------
# forward_relative_returns
# ---------------------------------------------------------------------------

def test_forward_relative_returns_subtracts_benchmark():
    # 5 days. ETF open/close and benchmark open/close chosen so the h=1 forward
    # relative return at i=0 is hand-computable:
    #   enter ETF open[1]=110, exit ETF close[1]=121  -> +10%
    #   enter BMK open[1]=100, exit BMK close[1]=105  -> +5%
    #   relative = 10% - 5% = +5%
    idx = pd.bdate_range("2024-01-01", periods=5)
    panel = pd.DataFrame({
        "XLK_open": [100, 110, 120, 130, 140],
        "XLK_close": [105, 121, 125, 135, 145],
        "SPY_open": [100, 100, 100, 100, 100],
        "SPY_close": [100, 105, 100, 100, 100],
    }, index=idx)
    fr = forward_relative_returns(panel, "XLK", "SPY", [1])
    assert fr[1].iloc[0] == pytest.approx(0.10 - 0.05, abs=1e-12)
    # last row has no i+1 open -> NaN
    assert np.isnan(fr[1].iloc[-1])


# ---------------------------------------------------------------------------
# benjamini_hochberg
# ---------------------------------------------------------------------------

def test_benjamini_hochberg_known_example():
    # Classic BH worked example, m=4, q=0.05.
    # sorted p: .009,.011,.039,.041 ; thresholds i/m*q = .0125,.025,.0375,.05
    #   .009<=.0125 ok ; .011<=.025 ok ; .039<=.0375 NO ; .041<=.05 ok -> kmax=4
    # so ALL four reject (step-up rejects everything <= largest passing rank).
    pvals = [0.039, 0.041, 0.009, 0.011]
    rejected, adj = benjamini_hochberg(pvals, 0.05)
    assert rejected == [True, True, True, True]
    assert len(adj) == 4 and all(0.0 <= a <= 1.0 for a in adj)


def test_benjamini_hochberg_partial_rejection():
    # One tiny p, rest large -> only the small one should reject.
    pvals = [0.001, 0.40, 0.50, 0.60, 0.70]
    rejected, _ = benjamini_hochberg(pvals, 0.10)
    assert rejected[0] is True
    assert rejected[1:] == [False, False, False, False]


def test_benjamini_hochberg_empty():
    assert benjamini_hochberg([], 0.1) == ([], [])


# ---------------------------------------------------------------------------
# permutation_pvalue (deterministic with the frozen seed)
# ---------------------------------------------------------------------------

def test_permutation_pvalue_extreme_is_small():
    pool = list(range(100))                 # 0..99
    # observed far above any sample-of-5 mean -> p near the (0+1)/(n+1) floor
    p = permutation_pvalue(1000.0, pool, sample_size=5, n_draws=500, seed=1729)
    assert p < 0.01


def test_permutation_pvalue_median_is_middle():
    pool = list(range(1001))                # mean 500
    p = permutation_pvalue(500.0, pool, sample_size=20, n_draws=1000, seed=1729)
    assert 0.35 < p < 0.65


def test_permutation_pvalue_nan_when_pool_too_small():
    assert np.isnan(permutation_pvalue(1.0, [1.0, 2.0], sample_size=5))


# ---------------------------------------------------------------------------
# spearman
# ---------------------------------------------------------------------------

def test_spearman_monotone():
    x = [1, 2, 3, 4, 5]
    assert spearman(x, [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert spearman(x, [50, 40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_nan_safe():
    assert np.isnan(spearman([1.0, np.nan], [1.0, 2.0]))   # <3 valid pairs
    assert np.isnan(spearman([1, 1, 1, 1], [1, 2, 3, 4]))  # zero variance


# ---------------------------------------------------------------------------
# collapse_episodes
# ---------------------------------------------------------------------------

def test_collapse_episodes_keeps_first_in_window():
    flags = [False, True, True, False, True, False, False, False, False, False, False, True]
    # window 3: index1 kept; index2 within 3 of 1 -> dropped; index4 (>=3 from 1) kept;
    #           index11 (>=3 from 4) kept.
    out = collapse_episodes(flags, window=3)
    assert out == [False, True, False, False, True, False, False, False, False,
                   False, False, True]
