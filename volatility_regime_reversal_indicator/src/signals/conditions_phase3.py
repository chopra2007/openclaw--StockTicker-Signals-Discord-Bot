"""Phase-3 constructions (frozen in backtest/preregistration_phase3.yaml).

Builds on the Phase-2 NO-GO. Same plug-in contract as Phase 2: each construction is a pure
point-in-time fn(panel) -> boolean Series consumed by backtest.phase2.score_construction.

Two-track restructure grounded in the research mission (codex-research.md):
  TOPS    = a small, signed, monotonic WATCH-STATE composite (decomposed option-surface +
            breadth) -> a hard mechanical price-break TRIGGER inside that fragile state.
  BOTTOMS = capitulation washout -> a RARE Zweig breadth THRUST (fixes the base-rate artifact
            that made the Phase-2 bottom precision an echo of the eligible base rate).
A late-but-robust 200-day trend baseline is registered for the benchmark battle (kill-gate G6).

NOTHING in Phase 1 or Phase 2 is modified; this only ADDS reusable point-in-time pieces.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..backtest.metrics import concentration_regime
from ..features import utils as U
from .conditions import _vix_term_ratio
from .conditions_phase2 import _capit, _vvix_residual


def _b(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _col(p: pd.DataFrame, name: str) -> pd.Series:
    return p[name] if name in p.columns else pd.Series(np.nan, index=p.index)


# ---- TOP watch-state composite (research Layer 1) ----------------------------

def _vrp(p) -> pd.Series:
    return U.variance_risk_premium(_col(p, "VIX_close"), _col(p, "SPY_close"), 21)


def watch_state_components(p) -> "dict[str, pd.Series]":
    """The 4 signed, monotonic trailing-252-percentile legs of the fragility composite, each
    oriented so HIGH = top-like/fragile. Single source of truth shared by top_watch_state (which
    geomeans them) and the descriptive readout (src/show_fragility.py) so the two can't drift.
      1. LOW variance-risk-premium  (cheap crash-insurance vs realized risk = complacency)
      2. HIGH VIX/VIX3M term ratio  (flat/backwardation = near-term stress bid)
      3. HIGH VVIX-vs-VIX residual  (tail-hedge demand independent of spot VIX; reused from P2)
      4. breadth NARROWING          (RSP/SPY rolling-60 change negative)
    """
    return {
        "low_vrp_complacency": 1.0 - U.trailing_percentile(_vrp(p), 252),
        "vix_term_stress": U.trailing_percentile(_vix_term_ratio(p), 252),
        "vvix_tail_hedge_demand": U.trailing_percentile(_vvix_residual(p), 252),
        "breadth_narrowing": 1.0 - U.trailing_percentile(concentration_regime(p, 60), 252),
    }


def top_watch_state(p) -> pd.Series:
    """Continuous fragility score in (0,1], HIGH = top-like. Geometric mean of the 4 signed,
    monotonic trailing-252-percentile legs in watch_state_components() — the inputs the research
    endorses that we can compute from free data.
    Same geomean-with-floor-and-all-NaN-guard machinery as Phase-2's distribution_stress_index.
    NOTE: the VVIX-residual leg needs ~504 trading days to warm up (252-day OLS then a 252-day
    percentile), so the composite is effectively a ~2012+ detector — disclosed in the prereg.
    """
    legs = list(watch_state_components(p).values())
    stacked = np.vstack([l.to_numpy() for l in legs])
    stacked = np.clip(stacked, 1e-6, 1.0)
    all_nan = np.isnan(stacked).all(axis=0)
    gm = np.full(stacked.shape[1], np.nan)
    with np.errstate(invalid="ignore"):
        gm[~all_nan] = np.exp(np.nanmean(np.log(stacked[:, ~all_nan]), axis=0))
    return pd.Series(gm, index=p.index)


# ---- TOP trigger (research Layer 2): persistent watch-state AND a price break --

def watch_on(p, pct: float = 0.80) -> pd.Series:
    """Persistent regime flag: the watch-state composite in its own top quintile
    (self-calibrating via a second trailing-252 percentile)."""
    return _b(U.trailing_percentile(top_watch_state(p), 252) >= pct)


def support_break(p, ma: int = 50) -> pd.Series:
    """Fast mechanical price event: SPY closes below its `ma`-day MA (trend rolled over)."""
    spy = _col(p, "SPY_close")
    return _b(spy < U.sma(spy, ma))


def t_watch_break(p, watch_pct: float = 0.80, ma: int = 50) -> pd.Series:
    """2-stage gate: a fragile watch-state (slow, weeks-long) AND a price break (fast).
    Distinct from the Phase-2 all-soft-legs-same-day stack (state masquerading as event)."""
    return _b(watch_on(p, watch_pct) & support_break(p, ma))


# ---- BOTTOM: capitulation washout -> a RARE breadth thrust --------------------
# A thrust is the RECOVERY surge that fires days-to-weeks AFTER the capitulation low, so the
# washout is checked as "occurred within the prior `lookback` days", NOT same-day (a same-day
# AND yields zero — by the time breadth thrusts, the drawdown/VIX washout has already passed).

def _zbt_ema(p, span: int = 10) -> pd.Series:
    return U.zweig_breadth_thrust(_col(p, "ABINYSE_adv"), _col(p, "ABINYSE_dec"), span)


def zbt_thrust(p, span: int = 10, win: int = 252, lo_pct: float = 0.10,
               hi_pct: float = 0.90, within: int = 10) -> pd.Series:
    """Broad-US-ADAPTED Zweig thrust (PRIMARY): the adv-ratio EMA's trailing-`win` percentile
    crosses ABOVE `hi_pct` having been below `lo_pct` within the prior `within` days. We use a
    self-normalizing percentile crossing because our breadth feed is broad-US (~5,600 issues),
    NOT NYSE-only, so Zweig's fixed 0.40/0.615 NYSE thresholds do not transfer (the canonical
    version fires only ~6x in 16y, none post-2019). Point-in-time: causal EMA + trailing
    percentile; `.shift(1)` / `.rolling(within).max().shift(1)` look only backward.
    """
    zp = U.trailing_percentile(_zbt_ema(p, span), win)
    crossed_up = (zp >= hi_pct) & (zp.shift(1) < hi_pct)
    recently_low = (zp < lo_pct).rolling(within, min_periods=1).max().shift(1).fillna(0.0).astype(bool)
    return _b(crossed_up & recently_low)


def zbt_thrust_canonical(p, span: int = 10, lo: float = 0.40, hi: float = 0.615,
                         within: int = 10) -> pd.Series:
    """Canonical NYSE Zweig thrust (DISCLOSED REFERENCE VARIANT): EMA of adv/(adv+dec) crosses
    above 0.615 having been below 0.40 within `within` days. Expected to be very rare /
    underpowered on the broad-US feed — kept only for honest comparison."""
    z = _zbt_ema(p, span)
    crossed_up = (z >= hi) & (z.shift(1) < hi)
    recently_low = (z < lo).rolling(within, min_periods=1).max().shift(1).fillna(0.0).astype(bool)
    return _b(crossed_up & recently_low)


def _recent_washout(p, dd: float = -0.08, vix_pct: float = 0.90, lookback: int = 25) -> pd.Series:
    """True if a capitulation washout (deep drawdown + VIX spike, Phase-2 _capit) occurred
    within the prior `lookback` trading days (inclusive of t). Point-in-time (trailing max)."""
    return _b(_capit(p, dd, vix_pct).rolling(lookback, min_periods=1).max().astype(bool))


def b_thrust(p, dd: float = -0.08, vix_pct: float = 0.90, lookback: int = 25) -> pd.Series:
    """Bottom (PRIMARY): a rare broad-US breadth thrust firing within `lookback` days of a
    capitulation washout. The thrust's rarity is what stops the precision from being a
    base-rate echo of 'any day after a -5% pullback'."""
    return _b(zbt_thrust(p) & _recent_washout(p, dd, vix_pct, lookback))


def b_thrust_canonical(p, dd: float = -0.08, vix_pct: float = 0.90, lookback: int = 25) -> pd.Series:
    """Bottom (reference variant): canonical NYSE Zweig thrust + recent washout."""
    return _b(zbt_thrust_canonical(p) & _recent_washout(p, dd, vix_pct, lookback))


# ---- controls (prove the thrust requirement is load-bearing) -----------------

def zbt_only(p) -> pd.Series:
    """CONTROL: the adapted thrust alone, no washout precondition."""
    return zbt_thrust(p)


def washout_only(p) -> pd.Series:
    """CONTROL: the capitulation washout alone, no thrust (the base-rate trap)."""
    return _capit(p, -0.08, 0.90)


# ---- trend-following benchmark (the 'benchmark battle', kill-gate G6) ---------

def bench_top_200(p) -> pd.Series:
    """Late-but-robust trend baseline: SPY breaks DOWN through its 200-day MA."""
    spy = _col(p, "SPY_close")
    ma = U.sma(spy, 200)
    return _b((spy < ma) & (spy.shift(1) >= ma))


def bench_bot_200(p) -> pd.Series:
    """Late-but-robust trend baseline: SPY reclaims its 200-day MA from below."""
    spy = _col(p, "SPY_close")
    ma = U.sma(spy, 200)
    return _b((spy > ma) & (spy.shift(1) <= ma))


# ---- registry (the frozen confirmatory grid) ---------------------------------

@dataclass(frozen=True)
class P3Construction:
    name: str
    side: str               # 'top' or 'bottom'
    fn: Callable[[pd.DataFrame], pd.Series]
    role: str               # 'primary' | 'variant' | 'control' | 'benchmark'


def build_constructions() -> list[P3Construction]:
    C = P3Construction
    return [
        # TOP: watch-state -> price-break trigger
        C("T_watch_break[0.80,50]", "top", lambda p: t_watch_break(p, 0.80, 50), "primary"),
        C("T_watch_break[0.85,50]", "top", lambda p: t_watch_break(p, 0.85, 50), "variant"),
        C("T_watch_break[0.80,20]", "top", lambda p: t_watch_break(p, 0.80, 20), "variant"),
        # BOTTOM: capitulation washout -> broad-US breadth thrust
        C("B_thrust[-0.08,0.90]", "bottom", lambda p: b_thrust(p, -0.08, 0.90), "primary"),
        C("B_thrust[-0.05,0.80]", "bottom", lambda p: b_thrust(p, -0.05, 0.80), "variant"),
        C("B_thrust_canonical", "bottom", b_thrust_canonical, "variant"),
        # controls (load-bearing-ness of the thrust gate)
        C("ctl_zbt_only", "bottom", zbt_only, "control"),
        C("ctl_washout_only", "bottom", washout_only, "control"),
        # benchmark battle
        C("bench_top_200", "top", bench_top_200, "benchmark"),
        C("bench_bot_200", "bottom", bench_bot_200, "benchmark"),
    ]
