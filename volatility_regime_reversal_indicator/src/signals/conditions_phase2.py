"""Phase-2 CONFLUENCE constructions (frozen in backtest/preregistration_phase2.yaml).

Separate from the frozen Phase-1 conditions.py. Each construction is a PURE point-in-time
function panel -> boolean Series (True = the confluence fires on that close). Thresholds are
round numbers carried verbatim from the (disclosed, post-selected) research; the CONFIRMATORY
edge comes from the opportunity-set null + out-of-sample battery, not these in-sample fires.

Cross-model review (Codex + Gemini + critic) drove three changes vs the raw research stack:
  - the raw rolling_slope(VVIX/VIX,10) hard leg is DROPPED (denominator-compression artifact);
  - it is replaced by TWO vetted legs, each registered separately so the harness can judge them:
    support_loss (Codex: price confirmation after churn) and vvix_residual_high (Gemini:
    beta-adjusted VVIX-vs-VIX residual = tail-hedge demand independent of spot VIX);
  - a continuous Distribution-Stress Index (Gemini) is reported alongside the binary gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..backtest.metrics import concentration_regime
from ..features import utils as U


def _b(s: pd.Series) -> pd.Series:
    return s.fillna(False).astype(bool)


def _col(p: pd.DataFrame, name: str) -> pd.Series:
    return p[name] if name in p.columns else pd.Series(np.nan, index=p.index)


# ---- TOP legs (point-in-time) ------------------------------------------------

def near_high(p, k: float = 0.97) -> pd.Series:
    spy = _col(p, "SPY_close")
    return _b(spy >= U.rolling_max(spy, 60) * k)


def compressed(p, width_pct: float = 0.30) -> pd.Series:
    spy = _col(p, "SPY_close")
    return _b(U.trailing_percentile(U.bollinger_width(spy, 20), 126) < width_pct)


def obv_down(p) -> pd.Series:
    return _b(U.rolling_slope(U.obv(_col(p, "SPY_close"), _col(p, "SPY_volume")), 20) < 0)


def udr_down(p) -> pd.Series:
    return _b(U.rolling_slope(
        U.updown_volume_ratio(_col(p, "SPY_close"), _col(p, "SPY_volume"), 20), 20) < 0)


def breadth_narrowing(p) -> pd.Series:
    return _b(concentration_regime(p, 60) < 0)


def support_loss(p, ma: int = 20) -> pd.Series:
    spy = _col(p, "SPY_close")
    return _b(spy < U.sma(spy, ma))


def _vvix_residual(p) -> pd.Series:
    """Beta-adjusted residual of log(VVIX) on log(VIX), rolling-252 OLS (Gemini re-encoding)."""
    vvix = _col(p, "VVIX_close")
    vix = _col(p, "VIX_close")
    return U.rolling_ols_residual(np.log(vvix), np.log(vix), 252)


def vvix_residual_high(p, pct: float = 0.90) -> pd.Series:
    return _b(U.trailing_percentile(_vvix_residual(p), 252) > pct)


def abi_churn(p, pct: float = 0.20) -> pd.Series:
    abi = _col(p, "ABINYSE_abi")
    return _b(U.trailing_percentile(U.sma(abi, 20), 252) < pct)


# ---- BOTTOM legs -------------------------------------------------------------

def _capit(p, dd_thresh: float = -0.08, vix_pct: float = 0.90) -> pd.Series:
    spy = _col(p, "SPY_close")
    dd = U.drawdown(spy, 60)
    return _b((dd <= dd_thresh) & (U.trailing_percentile(_col(p, "VIX_close"), 252) > vix_pct))


def _vvix_rollover(p) -> pd.Series:
    vvix = _col(p, "VVIX_close")
    return _b(vvix < U.rolling_max(vvix, 10) * 0.95)


def _snap(p, thrust: float = 0.03) -> pd.Series:
    rsp_thrust = U.pct_change(_col(p, "RSP_close"), 5) >= thrust
    r = U.rsi(_col(p, "SPY_close"), 14)
    rsi_recover = (r > 30) & (r.shift(1) <= 30)
    return _b(rsp_thrust | rsi_recover)


def _vix_reversal(p) -> pd.Series:
    """Gemini intraday capitulation: VIX spikes to a high but closes down, SPY closes green."""
    vix_hi = _col(p, "VIX_high")
    cond = (U.trailing_percentile(vix_hi, 252) > 0.90) & \
           (_col(p, "VIX_close") < _col(p, "VIX_open")) & \
           (_col(p, "SPY_close") > _col(p, "SPY_open"))
    return _b(cond)


# ---- CONSTRUCTIONS -----------------------------------------------------------

def t1_core_gated(p, k: float = 0.97, width_pct: float = 0.30) -> pd.Series:
    return _b(near_high(p, k) & compressed(p, width_pct) & obv_down(p) & udr_down(p)
              & breadth_narrowing(p))


def t2_core_support(p) -> pd.Series:
    return _b(t1_core_gated(p) & support_loss(p, 20))


def t3_core_vvixres(p) -> pd.Series:
    return _b(t1_core_gated(p) & vvix_residual_high(p, 0.90))


def t4_core_abichurn(p) -> pd.Series:
    return _b(t1_core_gated(p) & abi_churn(p, 0.20))


def b1_capitulation(p, dd_thresh: float = -0.08, vix_pct: float = 0.90, thrust: float = 0.03) -> pd.Series:
    return _b(_capit(p, dd_thresh, vix_pct) & _vvix_rollover(p) & _snap(p, thrust))


def b2_capit_vixrev(p) -> pd.Series:
    return _b(_capit(p, -0.08, 0.90) & _vix_reversal(p) & _snap(p, 0.03))


def dist_cooccur_baseline(p) -> pd.Series:
    """CONTROL: same-day AND of distribution legs, NO breadth gate (proves the gate matters)."""
    return _b(near_high(p) & compressed(p) & obv_down(p) & udr_down(p))


def ungated_watch(p) -> pd.Series:
    """The raw 4-leg watch WITHOUT the breadth gate — the G5 'stack beats parts' comparator."""
    return _b(near_high(p) & compressed(p) & obv_down(p) & udr_down(p))


# ---- continuous Distribution-Stress Index (Gemini) ---------------------------

def distribution_stress_index(p) -> pd.Series:
    """Geometric mean of each top leg's trailing-252 percentile, oriented so HIGH = top-like.

    Cliff-free companion to the binary gate. Reported, validated under the same null — NOT a
    standalone gate (a high DSI before tops is circular unless it beats the opportunity-set null).
    """
    spy = _col(p, "SPY_close")
    comp = 1.0 - U.trailing_percentile(U.bollinger_width(spy, 20), 252)        # low width = top-like
    narrow = 1.0 - U.trailing_percentile(concentration_regime(p, 60), 252)     # narrowing = top-like
    churn = 1.0 - U.trailing_percentile(U.sma(_col(p, "ABINYSE_abi"), 20), 252)  # low ABI = top-like
    volshrink = 1.0 - U.trailing_percentile(
        U.rolling_slope(U.obv(spy, _col(p, "SPY_volume")), 20), 252)           # obv falling = top-like
    vvr = U.trailing_percentile(_vvix_residual(p), 252)                        # high resid = top-like
    legs = [comp, narrow, churn, volshrink, vvr]
    # geometric mean over available legs (clip to a tiny floor so one zero leg doesn't null it)
    stacked = np.vstack([l.to_numpy() for l in legs])
    stacked = np.clip(stacked, 1e-6, 1.0)
    all_nan = np.isnan(stacked).all(axis=0)            # warmup rows: every leg still NaN
    gm = np.full(stacked.shape[1], np.nan)
    with np.errstate(invalid="ignore"):
        gm[~all_nan] = np.exp(np.nanmean(np.log(stacked[:, ~all_nan]), axis=0))
    return pd.Series(gm, index=p.index)


# ---- eligibility masks for the OPPORTUNITY-SET null (Codex's key upgrade) -----

def eligible_top(p) -> pd.Series:
    """Days in the near-high distribution-watch state — the null draws only from here."""
    return near_high(p, 0.97)


def eligible_bottom(p) -> pd.Series:
    """Days already in a meaningful pullback — the bottom null's opportunity set."""
    return _b(U.drawdown(_col(p, "SPY_close"), 60) <= -0.05)


# ---- registry (the frozen confirmatory grid) ---------------------------------

@dataclass(frozen=True)
class P2Construction:
    name: str
    side: str               # 'top' or 'bottom'
    fn: Callable[[pd.DataFrame], pd.Series]
    role: str               # 'primary' | 'variant' | 'leg' | 'control'


def build_constructions() -> list[P2Construction]:
    C = P2Construction
    return [
        C("T1_core_gated[0.97,0.30]", "top", lambda p: t1_core_gated(p, 0.97, 0.30), "primary"),
        C("T1_core_gated[0.98,0.25]", "top", lambda p: t1_core_gated(p, 0.98, 0.25), "variant"),
        C("T2_core_support", "top", t2_core_support, "variant"),
        C("T3_core_vvixres", "top", t3_core_vvixres, "variant"),
        C("T4_core_abichurn", "top", t4_core_abichurn, "variant"),
        C("B1_capitulation[-0.08,0.90]", "bottom", lambda p: b1_capitulation(p, -0.08, 0.90, 0.03), "primary"),
        C("B1_capitulation[-0.06,0.80]", "bottom", lambda p: b1_capitulation(p, -0.06, 0.80, 0.025), "variant"),
        C("B2_capit_vixrev", "bottom", b2_capit_vixrev, "variant"),
        C("leg_vvix_residual_high", "top", lambda p: vvix_residual_high(p, 0.90), "leg"),
        C("leg_abi_churn", "top", lambda p: abi_churn(p, 0.20), "leg"),
        C("leg_support_loss", "top", lambda p: _b(support_loss(p, 20) & near_high(p)), "leg"),
    ]
