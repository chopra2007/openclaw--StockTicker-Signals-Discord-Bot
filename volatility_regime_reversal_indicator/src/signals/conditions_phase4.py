"""Phase-4 constructions (frozen in backtest/preregistration_phase4.yaml).

Builds on the Phase-2 AND Phase-3 bottom NO-GOs. The earlier phases could never test the
research-endorsed bottom thesis HONESTLY because they lacked true up/down VOLUME and had only
a 2010-2026 window (too few capitulation episodes for statistical power). We now have the
NYSE up/down-VOLUME archive (store key NYSE_UDVOL, 13,867 daily rows 1965-03..2020-02) and a
long-history S&P 500 price (store key GSPC, ^GSPC 1962-2026). 55 years finally gives real
power — the research said power was the binding constraint.

THE THESIS (Lowry 90/90, Zweig breadth thrust):
  A market bottom is signalled not by the capitulation alone but by the SEQUENCE
  capitulation -> a RARE breadth THRUST. A "90% down day" (>=90% of NYSE directional share
  VOLUME in declining issues) marks the selling washout; a "90% up day" (>=90% in advancing
  issues) days-to-weeks LATER marks broad re-accumulation. Lowry/Zweig: that pairing, not the
  panic itself, is what historically precedes durable rallies.

WHY this is the WINNABLE direction the prior phases botched: the Phase-2/3 bottoms looked
"good" only against an all-days null. Among days already in a -5% pullback ~90%+ see an 8%
bounce within 60 days, so beating ALL-days is meaningless (base-rate trap). Phase 4 keeps the
OPPORTUNITY-SET null (random timing drawn only from equally-distressed eligible days) and adds
LOAD-BEARING controls (thrust_only, capitulation_only) so the SEQUENCE must earn its edge.

Every construction is a pure point-in-time fn(panel) -> boolean Series consumed by the
UNCHANGED backtest.phase2.score_construction. side='bottom' throughout. NOTHING in Phase 1/2/3
is modified; this only ADDS reusable point-in-time pieces.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..features import utils as U


def _b(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _col(p: pd.DataFrame, name: str) -> pd.Series:
    return p[name] if name in p.columns else pd.Series(np.nan, index=p.index)


# ---- same-day 90% day primitives (pure point-in-time, no leakage) -------------

def _up_share(p) -> pd.Series:
    return U.up_volume_share(_col(p, "NYSE_UDVOL_adv_volume"), _col(p, "NYSE_UDVOL_dec_volume"))


def _down_share(p) -> pd.Series:
    return U.down_volume_share(_col(p, "NYSE_UDVOL_adv_volume"), _col(p, "NYSE_UDVOL_dec_volume"))


def capitulation_90(p, thr: float = 0.90) -> pd.Series:
    """A Lowry 90% DOWNSIDE day: down_volume_share >= thr (capitulation washout).
    Point-in-time: a pure same-day volume ratio compared to a constant — no window/shift."""
    return _b(_down_share(p) >= thr)


def thrust_90(p, thr: float = 0.90) -> pd.Series:
    """A Lowry 90% UPSIDE day: up_volume_share >= thr (a breadth THRUST).
    Point-in-time: pure same-day ratio vs a constant."""
    return _b(_up_share(p) >= thr)


# ---- the capitulation -> thrust SEQUENCE (PRIMARY bottom) ---------------------
# Fire on the THRUST day, but only if a capitulation 90% down day occurred WITHIN the prior
# `within` trading days. The "a capitulation happened recently" check uses a trailing
# rolling-max that looks ONLY BACKWARD (.rolling(within).max() over days <= t, with .shift(1)
# so the capitulation must be in a STRICTLY prior session — a 90% up and 90% down on the same
# day cannot both be true anyway, but .shift(1) makes the look-back unambiguous and PIT).

def _recent_capitulation(p, within: int, thr: float = 0.90) -> pd.Series:
    """True if a 90% down day occurred within the prior `within` sessions (t-within .. t-1).
    Point-in-time: trailing rolling-max of the same-day capitulation flag, shifted back 1."""
    cap = capitulation_90(p, thr).astype(float)
    return _b(cap.rolling(within, min_periods=1).max().shift(1).fillna(0.0).astype(bool))


def lowry_90_90(p, within: int = 10, thr: float = 0.90) -> pd.Series:
    """PRIMARY bottom: a 90% UP day (thrust) firing within `within` trading days AFTER a 90%
    DOWN day (capitulation). The rarity of the pairing is what stops the precision from being a
    base-rate echo of 'any day after a -5% pullback'. Fires on the thrust day. Point-in-time:
    same-day thrust AND a backward-only recent-capitulation check."""
    return _b(thrust_90(p, thr) & _recent_capitulation(p, within, thr))


def lowry_90_90_two_thrusts(p, within: int = 10, thr: float = 0.90,
                            two_within: int = 10) -> pd.Series:
    """STRICTER variant: the 90/90 sequence PLUS a second 90% up day within `two_within` days
    (Lowry's 'a thrust confirmed by a second thrust' — broad demand that persists, not a
    one-session spike). Fires on the SECOND thrust day. Point-in-time: today is a thrust, a
    PRIOR thrust occurred within two_within days, and a capitulation preceded that.
    """
    thr_today = thrust_90(p, thr)
    prior_thrust = _b(thrust_90(p, thr).astype(float)
                      .rolling(two_within, min_periods=1).max().shift(1).fillna(0.0).astype(bool))
    # a capitulation must precede the FIRST thrust: require one within (within + two_within) days
    recent_cap = _recent_capitulation(p, within + two_within, thr)
    return _b(thr_today & prior_thrust & recent_cap)


# ---- Zweig-breadth-thrust ON VOLUME (variant) --------------------------------
# Adapt phase3.zbt_thrust, but the underlying ratio is up_volume_SHARE (Lowry volume), not the
# issue adv-ratio. Self-normalizing percentile crossing (no fixed NYSE thresholds): the EMA of
# up_volume_share crosses ABOVE a high trailing-`win` percentile having been below a low one
# within the prior `within` days. Point-in-time: causal EMA + trailing percentile; the
# crossing uses .shift(1) and the recently-low check uses .rolling(within).max().shift(1) —
# both look only backward.

def _zbt_vol_ema(p, span: int = 10) -> pd.Series:
    return U.ema(_up_share(p), span)


def zbt_volume_thrust(p, span: int = 10, win: int = 252, lo_pct: float = 0.10,
                      hi_pct: float = 0.90, within: int = 10) -> pd.Series:
    """Zweig-breadth-thrust-on-VOLUME (variant): trailing-`win` percentile of the EMA of
    up_volume_share crosses ABOVE `hi_pct` having been below `lo_pct` within the prior `within`
    days. Volume analogue of phase3.zbt_thrust (which used issue counts). Point-in-time."""
    zp = U.trailing_percentile(_zbt_vol_ema(p, span), win)
    crossed_up = (zp >= hi_pct) & (zp.shift(1) < hi_pct)
    recently_low = (zp < lo_pct).rolling(within, min_periods=1).max().shift(1).fillna(0.0).astype(bool)
    return _b(crossed_up & recently_low)


def zbt_volume_after_capit(p, span: int = 10, win: int = 252, lo_pct: float = 0.10,
                           hi_pct: float = 0.90, within: int = 10,
                           cap_within: int = 25) -> pd.Series:
    """Variant: the volume-Zweig thrust gated on a recent 90% down day (the full sequence,
    expressed with a smooth thrust instead of a single 90% up day)."""
    return _b(zbt_volume_thrust(p, span, win, lo_pct, hi_pct, within)
              & _recent_capitulation(p, cap_within))


# ---- CONTROLS (load-bearing: prove the SEQUENCE matters, not the base rate) ---

def thrust_only(p, thr: float = 0.90) -> pd.Series:
    """CONTROL: a 90% UP day with NO preceding capitulation requirement. If lowry_90_90 does
    not beat THIS, the 'thrust' alone (not the capitulation->thrust sequence) carries any edge."""
    return thrust_90(p, thr)


def capitulation_only(p, thr: float = 0.90) -> pd.Series:
    """CONTROL (the base-rate trap): fire on ANY 90% DOWN day. Distressed days are inherently
    followed by bounces; if lowry_90_90 does not beat THIS, the detector is just the base rate."""
    return capitulation_90(p, thr)


# ---- BENCHMARK battle (kill-gate G6) -----------------------------------------

def bench_bot_200(p) -> pd.Series:
    """Late-but-robust trend baseline on GSPC: price reclaims its 200-day MA from below."""
    px = _col(p, "GSPC_close")
    ma = U.sma(px, 200)
    return _b((px > ma) & (px.shift(1) <= ma))


# ---- eligibility for the OPPORTUNITY-SET null (equally-distressed days) -------
# The make-or-break null: random timing must draw ONLY from days that are ALREADY distressed,
# not from all days. Two flavours are registered (the prereg picks the primary):
#   drawdown-based  : days in a >= 5% drawdown off the trailing-60d GSPC peak
#   capitulation-window : days within `near` sessions of a 90% down day
# Both are point-in-time (drawdown uses a trailing peak; the capitulation window is backward).

def eligible_drawdown(p, dd: float = -0.05) -> pd.Series:
    """Opportunity set = days already in a >= |dd| drawdown off the trailing-60d GSPC peak."""
    return _b(U.drawdown(_col(p, "GSPC_close"), 60) <= dd)


def eligible_post_capitulation(p, near: int = 25, thr: float = 0.90) -> pd.Series:
    """Opportunity set = days within `near` sessions of (and including) a 90% down day —
    the equally-distressed peers of the 90/90 thrust. Point-in-time: trailing rolling-max."""
    cap = capitulation_90(p, thr).astype(float)
    return _b(cap.rolling(near, min_periods=1).max().fillna(0.0).astype(bool))


# ---- registry (the frozen confirmatory grid) ---------------------------------

@dataclass(frozen=True)
class P4Construction:
    name: str
    side: str               # always 'bottom' here
    fn: Callable[[pd.DataFrame], pd.Series]
    role: str               # 'primary' | 'variant' | 'control' | 'benchmark'


def build_constructions() -> list[P4Construction]:
    C = P4Construction
    return [
        # PRIMARY: the capitulation -> thrust sequence (Lowry 90/90)
        C("lowry_90_90[w10]", "bottom", lambda p: lowry_90_90(p, 10), "primary"),
        # within-window variants
        C("lowry_90_90[w5]", "bottom", lambda p: lowry_90_90(p, 5), "variant"),
        C("lowry_90_90[w25]", "bottom", lambda p: lowry_90_90(p, 25), "variant"),
        # stricter two-thrust variant
        C("lowry_90_90_two[w10]", "bottom", lambda p: lowry_90_90_two_thrusts(p, 10), "variant"),
        # Zweig-breadth-thrust-on-VOLUME variant (smooth thrust + recent capitulation)
        C("zbt_volume_after_capit", "bottom", zbt_volume_after_capit, "variant"),
        # CONTROLS (load-bearing — must be WEAK if the SEQUENCE is what matters)
        C("ctl_thrust_only", "bottom", thrust_only, "control"),
        C("ctl_capitulation_only", "bottom", capitulation_only, "control"),
        # BENCHMARK battle
        C("bench_bot_200", "bottom", bench_bot_200, "benchmark"),
    ]
