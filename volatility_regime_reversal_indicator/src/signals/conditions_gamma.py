"""Phase-GAMMA constructions (frozen in backtest/preregistration_gamma.yaml).

Builds on the Phase-3 NO-GO. THE LAST free-data lever for TODO #47: dealer-hedging fragility
from the SqueezeMetrics SQZ feed — the ONE genuinely-new top input the project now has for free
that is NOT VIX-derived (every prior free leg was VIX/sentiment and failed Phases 1-3).

Theory (codex-research.md):
  - NEGATIVE dealer gamma (gex<0): market-makers must hedge WITH the move (sell into weakness,
    buy into strength) so they AMPLIFY moves => a fragile/unstable regime that is TOP-like.
  - HIGH dix (Dark-pool Index, a 0-1 buy ratio): institutions accumulating off-exchange =>
    BOTTOM-like / bullish.

Same plug-in contract as Phase 2/3: each construction is a PURE point-in-time fn(panel) -> bool
Series consumed by backtest.phase2.score_construction. NOTHING in Phase 1/2/3/4 is modified; this
ADDS reusable point-in-time pieces and REUSES the Phase-3 support_break + benchmarks and the
Phase-2/3 _capit/_recent_washout washout by import. Thresholds are round, defensible, NOT tuned:
gex<0 is the canonical negative-gamma line; {0.20, 0.90} trailing-252 percentiles; {20,50}-day MAs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..features import utils as U
from .conditions_phase2 import _capit
from .conditions_phase3 import (
    P3Construction,
    _recent_washout,
    bench_bot_200,
    bench_top_200,
    support_break,
)


def _b(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _col(p: pd.DataFrame, name: str) -> pd.Series:
    return p[name] if name in p.columns else pd.Series(np.nan, index=p.index)


# ---- dealer-gamma / dark-pool features (point-in-time) -----------------------

def _gex(p) -> pd.Series:
    return _col(p, "SQZ_gex")


def _dix(p) -> pd.Series:
    return _col(p, "SQZ_dix")


def neg_gamma_regime(p) -> pd.Series:
    """Persistent fragile-regime flag: dealer gamma is NEGATIVE (gex<0). Can be ON for weeks —
    this is a STATE, not an event (mirrors Phase-3 watch_on)."""
    return U.negative_gamma_flag(_gex(p))


def low_gex_regime(p, pct: float = 0.20) -> pd.Series:
    """Variant fragile-regime flag: gex in its trailing-252 LOW quintile (a softer, self-
    calibrating version of the strict sign line)."""
    return _b(U.trailing_percentile(_gex(p), 252) <= pct)


def neg_gamma_ma(p, ma: int = 20) -> pd.Series:
    """Variant fragile-regime flag: the 20-day MA of gex is negative (persistently negative-gamma,
    not a one-day blip)."""
    return _b(U.sma(_gex(p), ma) < 0.0)


def high_dix(p, pct: float = 0.90) -> pd.Series:
    """Dark-pool accumulation flag: dix in its trailing-252 TOP decile (institutions buying off
    exchange)."""
    return _b(U.trailing_percentile(_dix(p), 252) >= pct)


# ---- TOP trigger (research architecture: fragile watch-state AND a hard price break) ----

def g_neg_gamma_break(p, ma: int = 50) -> pd.Series:
    """TOP (PRIMARY): persistent NEGATIVE-gamma regime AND SPY closes below its `ma`-day MA.
    2-stage gate mirroring Phase-3 t_watch_break: a slow fragile STATE (weeks-long) AND a fast
    mechanical price EVENT. The break is what turns a regime into a dated alert."""
    return _b(neg_gamma_regime(p) & support_break(p, ma))


def g_low_gex_break(p, pct: float = 0.20, ma: int = 50) -> pd.Series:
    """TOP (variant): low-gex-percentile regime instead of the strict sign line, + price break."""
    return _b(low_gex_regime(p, pct) & support_break(p, ma))


def g_neg_gamma_ma_break(p, ma_gex: int = 20, ma: int = 50) -> pd.Series:
    """TOP (variant): 20-day-MA-negative-gamma regime + price break."""
    return _b(neg_gamma_ma(p, ma_gex) & support_break(p, ma))


# ---- BOTTOM: dark-pool accumulation within/after a capitulation washout -------

def g_dix_capitulation(p, dd: float = -0.08, vix_pct: float = 0.90,
                       lookback: int = 25, dix_pct: float = 0.90) -> pd.Series:
    """BOTTOM (PRIMARY): HIGH dix (dark-pool accumulation) firing within `lookback` days of a
    Phase-2 capitulation washout. The washout precondition is what stops the precision from being
    a base-rate echo of 'any high-dix day'."""
    return _b(high_dix(p, dix_pct) & _recent_washout(p, dd, vix_pct, lookback))


def g_neg_gamma_capitulation(p, dd: float = -0.08, vix_pct: float = 0.90,
                             lookback: int = 25, gex_pct: float = 0.20) -> pd.Series:
    """BOTTOM (variant): deeply-low-gex (a gamma-driven washout) within `lookback` days of a
    capitulation washout -> reversal (negative gamma over-extends the down move, then snaps)."""
    return _b(low_gex_regime(p, gex_pct) & _recent_washout(p, dd, vix_pct, lookback))


# ---- controls (prove the trigger/sequence matters, not the raw regime) -------

def ctl_neg_gamma_only(p) -> pd.Series:
    """CONTROL: the negative-gamma regime alone, NO price break (proves the break is load-bearing)."""
    return neg_gamma_regime(p)


def ctl_dix_only(p, dix_pct: float = 0.90) -> pd.Series:
    """CONTROL: high dix alone, NO washout (proves the washout sequence is load-bearing)."""
    return high_dix(p, dix_pct)


# ---- registry (the frozen confirmatory grid) ---------------------------------

def build_constructions() -> list[P3Construction]:
    C = P3Construction
    return [
        # TOP: negative-gamma fragile regime -> price-break trigger
        C("G_neg_gamma_break[50]", "top", lambda p: g_neg_gamma_break(p, 50), "primary"),
        C("G_low_gex_break[0.20,50]", "top", lambda p: g_low_gex_break(p, 0.20, 50), "variant"),
        C("G_neg_gamma_ma_break[20,50]", "top", lambda p: g_neg_gamma_ma_break(p, 20, 50), "variant"),
        # BOTTOM: dark-pool accumulation / gamma washout -> reversal after capitulation
        C("G_dix_capitulation[-0.08,0.90]", "bottom",
          lambda p: g_dix_capitulation(p, -0.08, 0.90, 25, 0.90), "primary"),
        C("G_neg_gamma_capitulation[-0.08,0.90]", "bottom",
          lambda p: g_neg_gamma_capitulation(p, -0.08, 0.90, 25, 0.20), "variant"),
        # controls (load-bearing-ness of the trigger/sequence)
        C("ctl_neg_gamma_only", "top", ctl_neg_gamma_only, "control"),
        C("ctl_dix_only", "bottom", ctl_dix_only, "control"),
        # benchmark battle (reused from Phase 3)
        C("bench_top_200", "top", bench_top_200, "benchmark"),
        C("bench_bot_200", "bottom", bench_bot_200, "benchmark"),
    ]
