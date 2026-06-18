"""Vectorized, point-in-time feature utilities.

EVERY function here is trailing-only: the value at index t depends solely on
observations at indices <= t. We never use a full-sample statistic (e.g. the
default pandas ``.rank(pct=True)`` or a whole-series ``mean()/std()``), because
that would leak the future into the past. ``tests/test_lookahead.py`` enforces
this mechanically (truncation-invariance) and is load-bearing — if it fails the
whole backtest is fake.

Why each primitive is point-in-time:
  - rolling(window): looks back ``window`` rows, never forward.
  - ewm(adjust=False): a causal recursive filter seeded at the first obs; removing
    FUTURE rows cannot change the value at t.
  - cummax / cumsum: expanding over past+present only.
  - shift(1): pulls the PRIOR row (used for prev-close, returns).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def pct_change(s: pd.Series, periods: int = 1) -> pd.Series:
    return s.pct_change(periods)


def rolling_mean(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).mean()


def rolling_std(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).std(ddof=0)


def trailing_zscore(s: pd.Series, window: int) -> pd.Series:
    """z of the current obs vs its trailing-``window`` mean/std (population std)."""
    m = s.rolling(window, min_periods=window).mean()
    sd = s.rolling(window, min_periods=window).std(ddof=0).replace(0.0, np.nan)
    return (s - m) / sd


def trailing_percentile(s: pd.Series, window: int) -> pd.Series:
    """Percentile rank of the current obs within the trailing window (inclusive).

    Returns a value in (0, 1]: fraction of the trailing ``window`` observations
    (including t itself) that are <= the current value. Uses rolling().apply so
    it can never see beyond t.
    """
    def _rank(x: np.ndarray) -> float:
        return float((x <= x[-1]).sum()) / float(len(x))

    return s.rolling(window, min_periods=window).apply(_rank, raw=True)


def rolling_slope(s: pd.Series, window: int) -> pd.Series:
    """OLS slope of s over the trailing window (per 1-step index)."""
    x = np.arange(window, dtype=float)
    x = x - x.mean()
    denom = float((x ** 2).sum())

    def _slope(y: np.ndarray) -> float:
        return float((x * (y - y.mean())).sum()) / denom

    return s.rolling(window, min_periods=window).apply(_slope, raw=True)


def rolling_min(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).min()


def rolling_max(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).max()


def drawdown(s: pd.Series, window: int | None = None) -> pd.Series:
    """Drawdown from the trailing peak. ``window=None`` => expanding peak (PIT)."""
    peak = s.rolling(window, min_periods=1).max() if window else s.cummax()
    return s / peak - 1.0


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average True Range, Wilder smoothing (ewm causal)."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()


def bollinger_width(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.Series:
    """Band width as a fraction of the trailing mean (range compression proxy)."""
    m = close.rolling(window, min_periods=window).mean()
    sd = close.rolling(window, min_periods=window).std(ddof=0)
    return (2.0 * n_std * sd) / m


def realized_vol(close: pd.Series, window: int = 20, annualize: bool = True) -> pd.Series:
    """Annualized realized vol = std of trailing log returns * sqrt(252).

    Ported from consensus_engine analysis/regime.py _compute_regime and re-tested
    under the look-ahead test rather than assumed clean.
    """
    logret = np.log(close / close.shift(1))
    rv = logret.rolling(window, min_periods=window).std(ddof=0)
    return rv * np.sqrt(252.0) if annualize else rv


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-balance volume (cumulative signed volume) — expanding, PIT."""
    direction = np.sign(close.diff()).fillna(0.0)
    return (direction * volume).cumsum()


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI (causal ewm)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False, min_periods=span).mean()


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window, min_periods=window).mean()


def updown_volume_ratio(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Trailing up-volume / down-volume ratio (accumulation/distribution proxy)."""
    chg = close.diff()
    up_vol = volume.where(chg > 0, 0.0).rolling(window, min_periods=window).sum()
    dn_vol = volume.where(chg < 0, 0.0).rolling(window, min_periods=window).sum()
    return up_vol / dn_vol.replace(0.0, np.nan)
