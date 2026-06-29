"""Tests for the F2 factor-rotation back-test pure helpers.

These exercise the NEW statistics the F2 back-test adds on top of the reused F1
helpers, WITHOUT any yfinance download:

  * controlled_regression isolates the predictor's slope AFTER partialling out a
    control column (the mandatory SPY-own-trailing-return control). On data the
    control fully explains, the predictor slope collapses to ~0; on data only the
    predictor explains, the control leaves its slope intact and positive.
  * spy_trailing_return computes the benchmark's own trailing window return
    point-in-time (no look-ahead).
  * factor_rs_autocorr reproduces the factor-momentum persistence stylised fact:
    +1 when trailing RS-momentum and forward RS return move together, NaN-safe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.backtest_factor_rotation import (
    controlled_regression,
    factor_rs_autocorr,
    spy_trailing_return,
)


# ---------------------------------------------------------------------------
# controlled_regression — the mandatory SPY-trailing control
# ---------------------------------------------------------------------------

def test_controlled_regression_predictor_only():
    # outcome = 2 * predictor exactly; control is pure noise uncorrelated -> the
    # predictor slope survives at ~2.0 and stays significant after the control.
    rng = np.random.default_rng(0)
    n = 400
    pred = rng.normal(size=n)
    control = rng.normal(size=n)
    outcome = 2.0 * pred
    beta, p, nn = controlled_regression(pred, control, outcome, alternative="greater")
    assert nn == n
    assert beta == pytest.approx(2.0, abs=1e-6)
    assert p < 1e-6


def test_controlled_regression_control_explains_everything():
    # outcome is driven by the control plus noise; the predictor shares the control
    # but also has an INDEPENDENT component that is unrelated to the outcome. Once
    # the control is partialled out, the predictor's own contribution is ~0 and not
    # significant (the realistic "spurious-because-of-the-market" case).
    rng = np.random.default_rng(0)
    n = 500
    control = rng.normal(size=n)
    indep = rng.normal(size=n)            # predictor's own component, unrelated to outcome
    pred = control + indep
    outcome = 3.0 * control + rng.normal(scale=1.0, size=n)
    beta, p, _ = controlled_regression(pred, control, outcome, alternative="greater")
    assert abs(beta) < 0.2            # predictor's own contribution is crushed (~0)
    assert p > 0.30                   # not significant after the control


def test_controlled_regression_sign_flips_after_control():
    # Raw predictor looks POSITIVE only because it rides the control. Build it so
    # the predictor's partial slope is actually NEGATIVE after removing control.
    rng = np.random.default_rng(2)
    n = 600
    control = rng.normal(size=n)
    pred = control + rng.normal(scale=0.5, size=n)
    outcome = 5.0 * control - 1.0 * pred + rng.normal(scale=0.01, size=n)
    beta, p, _ = controlled_regression(pred, control, outcome, alternative="greater")
    assert beta < 0                   # true partial slope is negative
    # one-sided 'greater' p must be large (we cannot reject in the claimed dir)
    assert p > 0.9


def test_controlled_regression_nan_safe():
    beta, p, nn = controlled_regression([1.0, np.nan], [1.0, 2.0], [1.0, 2.0])
    assert np.isnan(beta) and np.isnan(p) and nn < 3


# ---------------------------------------------------------------------------
# spy_trailing_return — point-in-time benchmark control column
# ---------------------------------------------------------------------------

def test_spy_trailing_return_is_point_in_time():
    # close doubles every 63 rows; trailing-63 return on the last row = +100%.
    n = 130
    closes = pd.Series([100.0 * (2 ** (i / 63.0)) for i in range(n)])
    tr = spy_trailing_return(closes, window=63)
    # first 63 entries undefined (no t-63 base)
    assert np.isnan(tr.iloc[62])
    assert tr.iloc[63] == pytest.approx(closes.iloc[63] / closes.iloc[0] - 1.0)
    # uses only PAST closes: value at t never references t+1
    assert tr.iloc[100] == pytest.approx(closes.iloc[100] / closes.iloc[37] - 1.0)


# ---------------------------------------------------------------------------
# factor_rs_autocorr — factor-momentum persistence precondition
# ---------------------------------------------------------------------------

def test_factor_rs_autocorr_positive_when_persistent():
    # rs rises monotonically -> trailing RS return and forward RS return are both
    # positive and co-move -> autocorrelation strongly positive.
    rs = pd.Series([100.0 + i for i in range(200)])
    ac = factor_rs_autocorr(rs, window=21)
    assert ac > 0.9


def test_factor_rs_autocorr_nan_safe_short():
    rs = pd.Series([100.0, 101.0, 102.0])
    assert np.isnan(factor_rs_autocorr(rs, window=21))
