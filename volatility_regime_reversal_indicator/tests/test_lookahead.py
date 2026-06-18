"""LOAD-BEARING look-ahead test.

Definition of point-in-time: feature[t] computed on the FULL series must equal
feature[t] computed on the prefix series[0..t]. I.e. removing future rows cannot
change the value at t (truncation-invariance). Any utility that secretly uses a
full-sample statistic (whole-series mean/std, default percentile rank, or a
forward shift) breaks this and is caught here.

The final meta-test plants a deliberate leak and asserts the detector flags it —
so this file can never pass vacuously.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.features import utils as U


def _synth(n: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0003, 0.011, n)
    close = pd.Series(
        100.0 * np.exp(np.cumsum(ret)),
        index=pd.bdate_range("2015-01-01", periods=n),
        name="close",
    )
    high = close * (1.0 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1.0 - np.abs(rng.normal(0, 0.005, n)))
    openp = close.shift(1)
    openp.iloc[0] = close.iloc[0]
    vol = pd.Series(rng.integers(1_000_000, 5_000_000, n), index=close.index).astype(float)
    return pd.DataFrame({"open": openp, "high": high, "low": low, "close": close, "volume": vol})


# name -> fn(df) -> Series. Covers every public utility.
FEATURES = {
    "pct_change_5": lambda d: U.pct_change(d.close, 5),
    "rolling_mean_20": lambda d: U.rolling_mean(d.close, 20),
    "rolling_std_20": lambda d: U.rolling_std(d.close, 20),
    "trailing_zscore_60": lambda d: U.trailing_zscore(d.close, 60),
    "trailing_zscore_252": lambda d: U.trailing_zscore(d.close, 252),
    "trailing_percentile_126": lambda d: U.trailing_percentile(d.close, 126),
    "trailing_percentile_252": lambda d: U.trailing_percentile(d.close, 252),
    "rolling_slope_10": lambda d: U.rolling_slope(d.close, 10),
    "rolling_min_20": lambda d: U.rolling_min(d.close, 20),
    "rolling_max_20": lambda d: U.rolling_max(d.close, 20),
    "drawdown_expanding": lambda d: U.drawdown(d.close),
    "drawdown_window_60": lambda d: U.drawdown(d.close, 60),
    "atr_14": lambda d: U.atr(d.high, d.low, d.close, 14),
    "bollinger_width_20": lambda d: U.bollinger_width(d.close, 20),
    "realized_vol_20": lambda d: U.realized_vol(d.close, 20),
    "realized_vol_10": lambda d: U.realized_vol(d.close, 10),
    "obv": lambda d: U.obv(d.close, d.volume),
    "rsi_14": lambda d: U.rsi(d.close, 14),
    "ema_10": lambda d: U.ema(d.close, 10),
    "sma_50": lambda d: U.sma(d.close, 50),
    "updown_volume_ratio_20": lambda d: U.updown_volume_ratio(d.close, d.volume, 20),
    "rolling_ols_residual_60": lambda d: U.rolling_ols_residual(
        np.log(d.close), np.log(d.high), 60),
}

# t positions to probe (recompute on the prefix df[0..t] and compare value at t)
_PROBE_TS = [260, 300, 340, 380, 399]


@pytest.mark.parametrize("name", list(FEATURES))
def test_truncation_invariance(name: str) -> None:
    df = _synth()
    fn = FEATURES[name]
    full = fn(df)
    for t in _PROBE_TS:
        prefix = fn(df.iloc[: t + 1])
        a, b = full.iloc[t], prefix.iloc[t]
        if pd.isna(a) and pd.isna(b):
            continue
        assert np.isclose(a, b, rtol=1e-9, atol=1e-12), (
            f"{name} LOOK-AHEAD at t={t}: full={a!r} prefix={b!r}"
        )


def test_detector_catches_planted_leak() -> None:
    """A full-sample z-score is genuinely leaky; the detector MUST flag it."""
    df = _synth()
    leaky = lambda d: (d.close - d.close.mean()) / d.close.std()  # noqa: E731 — whole-series stat
    full = leaky(df)
    prefix = leaky(df.iloc[:301])
    assert not np.isclose(full.iloc[300], prefix.iloc[300]), (
        "truncation-invariance detector failed to flag a planted full-sample leak"
    )


def test_forward_shift_leak_is_caught() -> None:
    """A forward shift (tomorrow's value today) is leaky; detector MUST flag it."""
    df = _synth()
    leaky = lambda d: d.close.shift(-1)  # noqa: E731 — pulls the FUTURE
    full = leaky(df)
    prefix = leaky(df.iloc[:301])
    # at t=300, full sees row 301 (exists); prefix's last row is 300 -> NaN
    assert not (
        np.isclose(full.iloc[300], prefix.iloc[300]) if not pd.isna(prefix.iloc[300]) else False
    ), "detector failed to flag a forward-shift leak"
    assert pd.isna(prefix.iloc[300]) and not pd.isna(full.iloc[300])
