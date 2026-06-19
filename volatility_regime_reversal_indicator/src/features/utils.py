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


def rolling_ols_residual(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """Residual of a TRAILING-window OLS of y on x, evaluated at the current point.

    At index t, fit ``y = a + b*x`` on the window [t-window+1, t] (data <= t only) and
    return ``y[t] - (a + b*x[t])``. Point-in-time by construction — truncation-invariant,
    enforced by tests/test_lookahead.py. Used for the beta-adjusted VVIX-vs-VIX residual
    (vol-of-vol demand independent of spot VIX).
    """
    yv = y.to_numpy(dtype=float)
    xv = x.to_numpy(dtype=float)
    n = len(yv)
    out = np.full(n, np.nan)
    for t in range(window - 1, n):
        ys = yv[t - window + 1:t + 1]
        xs = xv[t - window + 1:t + 1]
        m = np.isfinite(ys) & np.isfinite(xs)
        if m.sum() < window:          # require a full window of valid pairs (no straddle/gaps)
            continue
        xm = xs.mean()
        denom = float(((xs - xm) ** 2).sum())
        if denom <= 0.0:
            continue
        b = float(((xs - xm) * (ys - ys.mean())).sum()) / denom
        a = float(ys.mean() - b * xm)
        out[t] = yv[t] - (a + b * xv[t])
    return pd.Series(out, index=y.index)


def variance_risk_premium(
    vix_close: pd.Series, spy_close: pd.Series, rv_window: int = 21
) -> pd.Series:
    """Variance risk premium = implied variance - realized variance (annualized).

    ``iv_var = (VIX/100)**2`` is the option-implied annualized variance (VIX is a level
    in points, 16.4 -> 0.164); ``rv_var`` is trailing realized variance over ``rv_window``
    days (the square of ``realized_vol``). VRP > 0 is the normal state (insurance costs
    more than realized risk); a COMPRESSED/low VRP near the highs is the complacency /
    under-hedging signature the research flags as top-like.

    Point-in-time: ``(VIX/100)**2`` is pointwise and ``realized_vol`` is a trailing rolling
    std — neither sees beyond t. ``rv_window=21`` horizon-matches the VIX 30-calendar-day
    window (the standard literature VRP horizon).
    """
    iv_var = (vix_close / 100.0) ** 2
    rv_var = realized_vol(spy_close, rv_window, annualize=True) ** 2
    return iv_var - rv_var


def zweig_breadth_thrust(adv: pd.Series, dec: pd.Series, ema_span: int = 10) -> pd.Series:
    """Zweig Breadth Thrust ratio = EMA of advancing / (advancing + declining) issues.

    The classic thrust fires when this 10-day EMA surges from below ~0.40 to above ~0.615
    within 10 trading days (a rare, broad re-accumulation that historically marks bottoms).
    This returns only the EMA series; the cross/within-window trigger lives in the signal layer.

    Point-in-time: the daily advance ratio is same-day (no shift) and ``ema`` is a causal
    ewm(adjust=False) — removing future rows cannot change the value at t.
    """
    ratio = adv / (adv + dec).replace(0.0, np.nan)
    return ema(ratio, ema_span)


def negative_gamma_flag(gex: pd.Series) -> pd.Series:
    """Dealer NEGATIVE-gamma flag = (gex < 0): dealers must hedge WITH the move (sell weakness,
    buy strength), so they AMPLIFY moves = a fragile / unstable / top-like regime.

    Point-in-time / NO leakage by construction: this is a PURE same-day comparison of one same-day
    column to the constant 0 — no rolling window, no shift, no future row. feature[t] depends only
    on row t, so it is trivially truncation-invariant (enforced in tests/test_lookahead_gamma.py).
    NaN gex (pre-SQZ-start, before 2011-05-02) stays NaN."""
    return gex < 0.0


def up_volume_share(adv_volume: pd.Series, dec_volume: pd.Series) -> pd.Series:
    """Same-day NYSE upside-volume share = adv_volume / (adv_volume + dec_volume).

    The exact quantity Lowry's "90% days" are defined on: the fraction of total
    directional (advancing + declining) NYSE share VOLUME that traded in advancing
    issues on THAT session. A value >= 0.90 is a "90% up day" (a breadth THRUST); the
    mirror down_volume_share >= 0.90 is a "90% down day" (capitulation). Example:
    2008-10-10 dec_volume 1.94e9 vs adv_volume 9.18e7 -> down share 0.955 (a 95.5%
    downside day); 2008-10-13 is the mirror ~95% upside day.

    Point-in-time / NO leakage by construction: this is a PURE same-day ratio of two
    same-day columns — no rolling window, no shift, no future row. feature[t] depends
    only on row t, so it is trivially truncation-invariant (enforced in
    tests/test_lookahead_phase4.py). Unchanged volume is intentionally excluded from
    the denominator (Lowry's definition uses directional volume only).
    """
    denom = (adv_volume + dec_volume).replace(0.0, np.nan)
    return adv_volume / denom


def down_volume_share(adv_volume: pd.Series, dec_volume: pd.Series) -> pd.Series:
    """Same-day NYSE downside-volume share = dec_volume / (adv_volume + dec_volume).

    The capitulation counterpart of up_volume_share; >= 0.90 is a Lowry "90% down day".
    Point-in-time: pure same-day ratio, no window/shift/future row (see up_volume_share)."""
    denom = (adv_volume + dec_volume).replace(0.0, np.nan)
    return dec_volume / denom
