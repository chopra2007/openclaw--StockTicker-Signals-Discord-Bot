"""Theory-driven candidate conditions (final-plan.md section 4).

Each condition is a PURE, point-in-time function of the wide panel -> a boolean
Series (True = signal fires on the CLOSE of that day). Every condition is tagged
with exactly one `family` (for the kill-gate's ">=3 independent families" test)
and a `side`:
    top            -> predicts a forthcoming drop  (risk-off)
    bottom         -> predicts a forthcoming rally  (risk-on)
    vol_expansion  -> predicts volatility expanding (treated risk-off for edge sign)
    vol_contraction-> predicts volatility calming    (treated risk-on for edge sign)

Thresholds are FROZEN from theory / round numbers (never fitted on returns), and a
small set of threshold VARIANTS per condition is enumerated so the multiple-testing
count is honest. BAA10Y is lagged one trading day (publication delay -> no look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..config import get
from ..features import utils as U

# sides treated as "risk-off" (signal precedes weakness) for edge-sign purposes
RISK_OFF_SIDES = {"top", "vol_expansion"}
RISK_ON_SIDES = {"bottom", "vol_contraction"}


@dataclass(frozen=True)
class Condition:
    name: str
    family: str
    side: str
    fn: Callable[[pd.DataFrame], pd.Series]


# ---- feature accessors (point-in-time) -------------------------------------

def _col(panel: pd.DataFrame, name: str) -> pd.Series:
    if name not in panel.columns:
        return pd.Series(np.nan, index=panel.index)
    return panel[name]


def _vix_term_ratio(panel: pd.DataFrame) -> pd.Series:
    return _col(panel, "VIX_close") / _col(panel, "VIX3M_close")


def _rsp_spy_ratio(panel: pd.DataFrame) -> pd.Series:
    return _col(panel, "RSP_close") / _col(panel, "SPY_close")


def _baa10y_lagged(panel: pd.DataFrame) -> pd.Series:
    lag = int(get("data.fred_lag_days", 1))
    return _col(panel, "BAA10Y_value").shift(lag)


# ---- condition builders -----------------------------------------------------
# Each returns a boolean Series; NaN inputs -> False (condition simply not firing).

def _b(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def vix_backwardation(thresh: float = 1.0):
    def f(p):
        return _b(_vix_term_ratio(p) > thresh)
    return f


def vix_term_falling(pct_thresh: float = -0.05):
    # VIX/VIX3M dropping fast = vol calming (contraction)
    def f(p):
        r = _vix_term_ratio(p)
        return _b((U.pct_change(r, 10) < pct_thresh) & (r < 0.95))
    return f


def vvix_elevated(pct: float = 0.80):
    def f(p):
        return _b(U.trailing_percentile(_col(p, "VVIX_close"), 252) > pct)
    return f


def rvol_spike(pct: float = 0.80):
    def f(p):
        rv = U.realized_vol(_col(p, "SPY_close"), 20)
        return _b((U.trailing_percentile(rv, 252) > pct) & (U.rolling_slope(rv, 10) > 0))
    return f


def rvol_compression(pct: float = 0.20):
    def f(p):
        rv = U.realized_vol(_col(p, "SPY_close"), 20)
        return _b(U.trailing_percentile(rv, 252) < pct)
    return f


def vix_complacency(pct: float = 0.20):
    # VIX in the low tail of its trailing year = complacency -> top risk
    def f(p):
        return _b(U.trailing_percentile(_col(p, "VIX_close"), 252) < pct)
    return f


def vix_capitulation(pct: float = 0.90):
    # VIX in the high tail = fear/capitulation -> bottom
    def f(p):
        return _b(U.trailing_percentile(_col(p, "VIX_close"), 252) > pct)
    return f


def overextended_top(dist_pct: float = 0.90, rsi_thresh: float = 70.0):
    def f(p):
        close = _col(p, "SPY_close")
        ma20 = U.sma(close, 20)
        dist = (close - ma20) / ma20
        return _b((U.trailing_percentile(dist, 252) > dist_pct) & (U.rsi(close, 14) > rsi_thresh))
    return f


def oversold_bottom(dist_pct: float = 0.10, rsi_thresh: float = 30.0):
    def f(p):
        close = _col(p, "SPY_close")
        ma20 = U.sma(close, 20)
        dist = (close - ma20) / ma20
        return _b((U.trailing_percentile(dist, 252) < dist_pct) & (U.rsi(close, 14) < rsi_thresh))
    return f


def breadth_break_top(ratio_drop: float = -0.01, near_high: float = 0.98):
    # SPY near a 60d high while RSP/SPY breadth ratio is ACTIVELY breaking down
    # (recent decline) — break-based, not standing non-confirmation (2023-24 trap).
    def f(p):
        spy = _col(p, "SPY_close")
        ratio = _rsp_spy_ratio(p)
        near = spy >= U.rolling_max(spy, 60) * near_high
        breaking = U.pct_change(ratio, 20) < ratio_drop
        return _b(near & breaking)
    return f


def credit_stress_rising(z_thresh: float = 1.0):
    # BAA10Y (lagged) z-score elevated AND rising = credit widening -> risk-off
    def f(p):
        baa = _baa10y_lagged(p)
        return _b((U.trailing_zscore(baa, 252) > z_thresh) & (U.rolling_slope(baa, 20) > 0))
    return f


def tlt_safe_haven(window: int = 20, thresh: float = 0.02):
    # TLT outperforming SPY over trailing window = flight to safety -> top risk
    def f(p):
        spy_ret = U.pct_change(_col(p, "SPY_close"), window)
        tlt_ret = U.pct_change(_col(p, "TLT_close"), window)
        return _b((tlt_ret - spy_ret) > thresh)
    return f


def rsi_recovering_bottom(low: float = 30.0):
    # RSI crossing back UP through `low` from below = mean-reversion off oversold
    def f(p):
        r = U.rsi(_col(p, "SPY_close"), 14)
        return _b((r > low) & (r.shift(1) <= low))
    return f


def distribution_top(near_high: float = 0.97, width_pct: float = 0.30):
    # price pinned near a trailing high, OBV rolling over, range compressing =
    # big sellers offloading into strength (distribution).
    def f(p):
        close = _col(p, "SPY_close")
        vol = _col(p, "SPY_volume")
        near = close >= U.rolling_max(close, 60) * near_high
        obv_down = U.rolling_slope(U.obv(close, vol), 20) < 0
        compressed = U.trailing_percentile(U.bollinger_width(close, 20), 126) < width_pct
        return _b(near & obv_down & compressed)
    return f


def accumulation_bottom(near_low: float = 1.03, ud_ratio: float = 1.0):
    # mirror near a trailing low: OBV rising, up/down volume improving.
    def f(p):
        close = _col(p, "SPY_close")
        vol = _col(p, "SPY_volume")
        near = close <= U.rolling_min(close, 60) * near_low
        obv_up = U.rolling_slope(U.obv(close, vol), 20) > 0
        ud_up = U.updown_volume_ratio(close, vol, 20) > ud_ratio
        return _b(near & obv_up & ud_up)
    return f


def skew_extreme(pct: float = 0.90):
    # SKEW tail-hedging in the high percentile -> top risk. Expected to FAIL ablation.
    def f(p):
        return _b(U.trailing_percentile(_col(p, "SKEW_close"), 252) > pct)
    return f


# ---- registry (canonical + threshold variants = the hypothesis grid) --------
# Each tuple: (base_name, family, side, builder_factory, [variant kwargs...])
_SPEC = [
    ("vix_backwardation", "vix_term_structure", "vol_expansion", vix_backwardation,
     [{"thresh": 1.0}, {"thresh": 1.05}]),
    ("vix_term_falling", "vix_term_structure", "vol_contraction", vix_term_falling,
     [{"pct_thresh": -0.05}, {"pct_thresh": -0.10}]),
    ("vvix_elevated", "vol_of_vol", "vol_expansion", vvix_elevated,
     [{"pct": 0.80}, {"pct": 0.90}]),
    ("rvol_spike", "realized_vol", "vol_expansion", rvol_spike,
     [{"pct": 0.80}, {"pct": 0.90}]),
    ("rvol_compression", "realized_vol", "vol_contraction", rvol_compression,
     [{"pct": 0.20}, {"pct": 0.10}]),
    ("vix_complacency", "vix_level", "top", vix_complacency,
     [{"pct": 0.20}, {"pct": 0.10}]),
    ("vix_capitulation", "vix_level", "bottom", vix_capitulation,
     [{"pct": 0.90}, {"pct": 0.95}]),
    ("overextended_top", "trend_extension", "top", overextended_top,
     [{"dist_pct": 0.90, "rsi_thresh": 70.0}, {"dist_pct": 0.95, "rsi_thresh": 75.0}]),
    ("oversold_bottom", "trend_extension", "bottom", oversold_bottom,
     [{"dist_pct": 0.10, "rsi_thresh": 30.0}, {"dist_pct": 0.05, "rsi_thresh": 25.0}]),
    ("breadth_break_top", "breadth", "top", breadth_break_top,
     [{"ratio_drop": -0.01, "near_high": 0.98}, {"ratio_drop": -0.02, "near_high": 0.97}]),
    ("credit_stress_rising", "credit", "top", credit_stress_rising,
     [{"z_thresh": 1.0}, {"z_thresh": 1.5}]),
    ("tlt_safe_haven", "safe_haven", "top", tlt_safe_haven,
     [{"window": 20, "thresh": 0.02}, {"window": 20, "thresh": 0.04}]),
    ("rsi_recovering_bottom", "mean_reversion", "bottom", rsi_recovering_bottom,
     [{"low": 30.0}, {"low": 35.0}]),
    ("distribution_top", "distribution_accumulation", "top", distribution_top,
     [{"near_high": 0.97, "width_pct": 0.30}, {"near_high": 0.98, "width_pct": 0.20}]),
    ("accumulation_bottom", "distribution_accumulation", "bottom", accumulation_bottom,
     [{"near_low": 1.03, "ud_ratio": 1.0}, {"near_low": 1.02, "ud_ratio": 1.2}]),
    ("skew_extreme", "skew", "top", skew_extreme,
     [{"pct": 0.90}, {"pct": 0.95}]),
]


def _variant_name(base: str, kwargs: dict) -> str:
    if not kwargs:
        return base
    parts = ",".join(f"{k}={v}" for k, v in kwargs.items())
    return f"{base}[{parts}]"


def build_conditions(include_variants: bool = True) -> list[Condition]:
    """Return the full enumerated condition grid (canonical + threshold variants)."""
    out: list[Condition] = []
    for base, family, side, factory, variants in _SPEC:
        vlist = variants if include_variants else variants[:1]
        for kwargs in vlist:
            out.append(Condition(_variant_name(base, kwargs), family, side, factory(**kwargs)))
    return out


def evaluate_all(panel: pd.DataFrame, include_variants: bool = True) -> dict[str, pd.Series]:
    """name -> boolean Series for every condition, aligned to the panel index."""
    return {c.name: c.fn(panel) for c in build_conditions(include_variants)}


def registry(include_variants: bool = True) -> list[dict]:
    return [
        {"name": c.name, "family": c.family, "side": c.side}
        for c in build_conditions(include_variants)
    ]
