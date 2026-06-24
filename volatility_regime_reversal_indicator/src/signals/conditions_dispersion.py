"""Dispersion constructions (frozen in backtest/preregistration_dispersion.yaml).

Cross-sectional return dispersion as a TOP precursor (Maio & Saffi 2016).
Mechanism: high constituent-return dispersion -> capital rotation / investor risk-sorting
-> lower forward equity premium -> top precursor. Distinct from every prior phase
(not VIX-derived, not breadth, not gamma/dix).

Same plug-in contract as Phases 2/3/GAMMA: each construction is a PURE point-in-time
fn(panel) -> bool Series consumed by backtest.phase2.score_construction.

SURVIVORSHIP CAVEAT: SP500_DISP and NDX_DISP are built from today's membership applied
backward. Historical dispersion is understated near stress events (delisted losers
excluded). Precision is an upper-bound estimate. The QQQ transfer is the binding test.

Thresholds: round, defensible, theory-driven (0.80 percentile trigger for "elevated
dispersion"; near-high gate k=0.97 matches Phase-2/3/GAMMA exactly). NOT re-tuned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..features import utils as U
from .conditions_phase2 import _b, _col, eligible_top, near_high
from .conditions_phase3 import (
    P3Construction,
    bench_top_200,
)

# ---- dispersion feature accessors (point-in-time) ----------------------------

def _sp500_disp(p: pd.DataFrame) -> pd.Series:
    """Daily cross-sectional std of S&P 500 constituent returns (pre-computed, stored)."""
    return _col(p, "SP500_DISP_value")


def _sp500_down_disp(p: pd.DataFrame) -> pd.Series:
    """Daily downside semi-dispersion (negative-return S&P 500 members only)."""
    return _col(p, "SP500_DOWN_DISP_value")


def _ndx_disp(p: pd.DataFrame) -> pd.Series:
    """Daily cross-sectional std of Nasdaq-100 constituent returns (pre-computed, stored)."""
    return _col(p, "NDX_DISP_value")


def _ndx_down_disp(p: pd.DataFrame) -> pd.Series:
    """Downside semi-dispersion for Nasdaq-100 members."""
    return _col(p, "NDX_DOWN_DISP_value")


# ---- dispersion percentile features -----------------------------------------

def sp500_disp_pct(p: pd.DataFrame, window: int = 252) -> pd.Series:
    """Trailing-window percentile rank of S&P 500 dispersion. Point-in-time."""
    return U.trailing_percentile(_sp500_disp(p), window)


def sp500_down_disp_pct(p: pd.DataFrame, window: int = 252) -> pd.Series:
    """Trailing-window percentile rank of S&P 500 downside semi-dispersion."""
    return U.trailing_percentile(_sp500_down_disp(p), window)


def ndx_disp_pct(p: pd.DataFrame, window: int = 252) -> pd.Series:
    """Trailing-window percentile rank of Nasdaq-100 dispersion. Point-in-time."""
    return U.trailing_percentile(_ndx_disp(p), window)


# ---- TOP constructions (point-in-time) --------------------------------------

def d_high_disp_near_high(p: pd.DataFrame, pct: float = 0.80, window: int = 252,
                           k: float = 0.97) -> pd.Series:
    """TOP (PRIMARY): dispersion in top-20th percentile AND SPY near its 60d high.

    Theory: elevated cross-sectional dispersion + price at highs = distribution-phase
    characteristic. The near-high gate is load-bearing: dispersion at a down-trending
    market is a DIFFERENT signal (risk-off panic). We want dispersion while prices
    still look healthy (Maio & Saffi top precursor regime).
    Point-in-time: both the percentile (rolling.apply) and near_high (rolling_max)
    are trailing-only.
    """
    return _b((sp500_disp_pct(p, window) >= pct) & near_high(p, k))


def d_high_disp_near_high_126(p: pd.DataFrame, pct: float = 0.80, k: float = 0.97) -> pd.Series:
    """TOP (variant): same as primary but 126-day (6-month) percentile window."""
    return d_high_disp_near_high(p, pct=pct, window=126, k=k)


def d_high_disp_near_high_60(p: pd.DataFrame, pct: float = 0.80, k: float = 0.97) -> pd.Series:
    """TOP (variant): same as primary but 60-day (3-month) percentile window."""
    return d_high_disp_near_high(p, pct=pct, window=60, k=k)


def d_high_down_disp_near_high(p: pd.DataFrame, pct: float = 0.80, window: int = 252,
                                 k: float = 0.97) -> pd.Series:
    """TOP (variant): downside semi-dispersion high AND near-high gate.

    Downside semi-dispersion (std of negative-return names only) is a sharper signal
    than full dispersion: it measures 'how badly are losers losing today?'. High
    downside dispersion near market highs = a subset of names starting to fall hard
    while the index is still elevated = internal deterioration.
    """
    return _b((sp500_down_disp_pct(p, window) >= pct) & near_high(p, k))


# ---- QQQ transfer: use NDX_DISP with the same SPY thresholds, no re-tuning ---

def d_ndx_high_disp_near_high(p: pd.DataFrame, pct: float = 0.80, window: int = 252,
                                k: float = 0.97) -> pd.Series:
    """QQQ transfer: NDX dispersion high percentile AND SPY near-high (no re-tuning).

    This is the EXACT same trigger as the primary construction, substituting
    NDX_DISP for SP500_DISP. The near-high gate uses SPY (unchanged). If the
    mechanism is real (dispersion as a market-wide stress signal), the SAME threshold
    should fire on NDX constituents' dispersion with a similar edge on QQQ returns.
    """
    return _b((ndx_disp_pct(p, window) >= pct) & near_high(p, k))


# ---- control: dispersion alone, no near-high gate (proves gate matters) ------

def ctl_disp_only(p: pd.DataFrame, pct: float = 0.80, window: int = 252) -> pd.Series:
    """CONTROL: high dispersion percentile alone, NO near-high gate.

    If this control beats the primary, the near-high gate is not load-bearing.
    If the primary beats the control (G5 stack-beats-parts), the gate is justified.
    """
    return _b(sp500_disp_pct(p, window) >= pct)


# ---- registry (the frozen confirmatory grid) ---------------------------------

def build_constructions() -> list[P3Construction]:
    C = P3Construction
    return [
        # TOP: primary + variants
        C("D_high_disp_near_high[0.80,252]", "top",
          lambda p: d_high_disp_near_high(p, 0.80, 252), "primary"),
        C("D_high_disp_near_high[0.80,126]", "top",
          lambda p: d_high_disp_near_high_126(p, 0.80), "variant"),
        C("D_high_disp_near_high[0.80,60]", "top",
          lambda p: d_high_disp_near_high_60(p, 0.80), "variant"),
        C("D_high_down_disp_near_high[0.80,252]", "top",
          lambda p: d_high_down_disp_near_high(p, 0.80, 252), "variant"),
        # control (proves near-high gate is load-bearing)
        C("ctl_disp_only[0.80,252]", "top", ctl_disp_only, "control"),
        # benchmark battle (reused from Phase-3)
        C("bench_top_200", "top", bench_top_200, "benchmark"),
    ]
