"""Phase-2 CONFIRMATORY scorer for the confluence detector.

Implements the test battery frozen in backtest/preregistration_phase2.yaml:
  - PRECISION + raw counts (TP/alerts, caught/in-scope tops)  -> raw ratios lead, not %
  - OPPORTUNITY-SET null (Codex): random timing drawn ONLY from eligible watch days
  - TEMPORAL hold-out (Codex): 2010-2021 discover / 2022-2026 confirm
  - CROSS-ASSET transfer (Gemini): frozen SPY params applied to QQQ, no re-tuning
  - LEAVE-ONE-EPISODE-OUT recall + leverage check
  - confirmatory max-stat reality check across the frozen grid
  - G5 stack-beats-parts at matched alert count
Reuses the Phase-1 honesty primitives verbatim (collapse_episodes, forward_event_hits,
vol_regime_labels, block_bootstrap_ci) so p-values stay comparable. Nothing here is a feature
input — these are forward-outcome scorers, so no look-ahead is introduced.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .event_study import collapse_episodes
from ..signals import conditions_phase2 as C2

SEED = 1729
EP_WINDOW = 20
EVENT_WINDOW = 60
TIER = 8


def _rng(off: int = 0):
    return np.random.default_rng(SEED + off)


# ---- the OPPORTUNITY-SET null (the load-bearing upgrade) ----------------------

def opportunity_set_null(
    hit: np.ndarray, ep_pos: np.ndarray, eligible: np.ndarray,
    regime: np.ndarray, n_draws: int = 2000, seed_offset: int = 0,
) -> dict:
    """Precision edge vs a random-timing null drawn ONLY from ELIGIBLE (watch-state) days,
    matched on vol-regime mix. Beating an all-days null is too easy because the signal only
    fires in states where the target event is inherently more likely."""
    valid = np.isfinite(hit)
    pool = np.flatnonzero(valid & eligible)                 # the opportunity set
    eps = np.array([p for p in ep_pos if valid[p]], dtype=int)
    n_ep = len(eps)
    if n_ep == 0 or len(pool) == 0:
        return {"n_ep": n_ep, "precision": np.nan, "elig_base": np.nan,
                "edge": np.nan, "null_p": np.nan, "tp": 0}
    elig_base = float(hit[pool].mean())
    precision = float(hit[eps].mean())
    edge = precision - elig_base
    # regime-matched draw from the eligible pool
    rng = _rng(seed_offset)
    pool_by_r: dict[int, np.ndarray] = {}
    for r in np.unique(regime[pool]):
        pool_by_r[int(r)] = pool[regime[pool] == r]
    ep_r = regime[eps]
    counts = {int(r): int((ep_r == r).sum()) for r in np.unique(ep_r)}
    null = np.empty(n_draws)
    for d in range(n_draws):
        picks = []
        for r, c in counts.items():
            pr = pool_by_r.get(r, pool)
            picks.append(rng.choice(pr, size=c, replace=len(pr) < c))
        sel = np.concatenate(picks)
        null[d] = hit[sel].mean() - elig_base
    p = float((1 + np.sum(null >= edge)) / (n_draws + 1))
    return {"n_ep": n_ep, "precision": precision, "elig_base": elig_base,
            "edge": edge, "null_p": p, "tp": int(round(precision * n_ep))}


# ---- recall over the enumerated episodes -------------------------------------

def _episode_positions(index: pd.DatetimeIndex, episodes: list[dict]) -> list[dict]:
    out = []
    for e in episodes:
        peak = pd.Timestamp(e["peak"])
        pos = int(index.searchsorted(peak))
        if pos >= len(index):
            continue
        out.append({**e, "peak_pos": pos})
    return out


def recall(firing: pd.Series, eps: list[dict], pre: int = 30, post: int = 10) -> dict:
    """A top is 'caught' if the construction fires in [peak_pos-pre, peak_pos+post]."""
    fired = firing.to_numpy().astype(bool)
    n = len(fired)
    caught, caught_organic, caught_scope = [], [], []
    for e in eps:
        lo, hi = max(0, e["peak_pos"] - pre), min(n, e["peak_pos"] + post + 1)
        hit = bool(fired[lo:hi].any())
        if hit:
            caught.append(e["peak"])
        if e["scope"] not in ("news_crash_excluded",):
            if hit:
                caught_organic.append(e["peak"])
        if e["scope"] == "distribution":
            if hit:
                caught_scope.append(e["peak"])
    organic = [e for e in eps if e["scope"] != "news_crash_excluded"]
    distrib = [e for e in eps if e["scope"] == "distribution"]
    return {"caught": caught, "n_caught": len(caught), "n_total": len(eps),
            "caught_organic": caught_organic, "n_caught_organic": len(caught_organic),
            "n_organic": len(organic),
            "caught_distribution": caught_scope, "n_caught_distribution": len(caught_scope),
            "n_distribution": len(distrib)}


# ---- cross-asset (QQQ) panel remap -------------------------------------------

def qqq_view(panel: pd.DataFrame) -> pd.DataFrame:
    """Relabel QQQ->SPY and QQQE->RSP so the frozen SPY constructions run on QQQ with NO
    re-tuning (VVIX/VIX/ABINYSE shared, breadth gate becomes QQQE/QQQ)."""
    out = panel.copy()
    for fld in ["open", "high", "low", "close", "volume"]:
        if f"QQQ_{fld}" in out.columns:
            out[f"SPY_{fld}"] = out[f"QQQ_{fld}"]
        if f"QQQE_{fld}" in out.columns:
            out[f"RSP_{fld}"] = out[f"QQQE_{fld}"]
    return out


# ---- per-construction scoring ------------------------------------------------

def score_construction(c: C2.P2Construction, panel: pd.DataFrame, hits: dict,
                       regime: np.ndarray, eps_top: list[dict], eps_bot: list[dict],
                       seed_offset: int = 0) -> dict:
    sig = c.fn(panel)
    ep_pos = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
    side = c.side
    hit = hits[(side, TIER)].to_numpy()
    elig = (C2.eligible_top(panel) if side == "top" else C2.eligible_bottom(panel)).to_numpy()
    res = opportunity_set_null(hit, ep_pos, elig, regime, seed_offset=seed_offset)
    # all-days base rate (the easier Phase-1-style comparison)
    valid = np.isfinite(hit)
    res["all_days_base"] = float(hit[valid].mean()) if valid.any() else np.nan
    rec = recall(sig, eps_top if side == "top" else eps_bot)
    res.update({"name": c.name, "side": side, "role": c.role,
                "raw_days": int(sig.sum()), **{f"recall_{k}": v for k, v in rec.items()}})
    return res


# ---- temporal hold-out + cross-asset for a single construction ----------------

def _precision_in_window(sig: pd.Series, hit: np.ndarray, elig: np.ndarray,
                         regime: np.ndarray, mask: np.ndarray, seed_offset: int) -> dict:
    s = sig.copy()
    s[~mask] = False
    ep = np.flatnonzero(collapse_episodes(s, EP_WINDOW).to_numpy())
    h = hit.copy(); h[~mask] = np.nan
    el = elig & mask
    return opportunity_set_null(h, ep, el, regime, seed_offset=seed_offset)


# ---- leave-one-episode-out ---------------------------------------------------

def leave_one_episode_out(sig: pd.Series, hits_top: np.ndarray, eligible: np.ndarray,
                          regime: np.ndarray, eps_top: list[dict]) -> dict:
    """Drop each enumerated top, recompute recall on the rest; leverage = does removing any one
    episode collapse precision below the all-days base rate?"""
    base = float(hits_top[np.isfinite(hits_top)].mean())
    ep_pos = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
    valid = np.isfinite(hits_top)
    eps_valid = [p for p in ep_pos if valid[p]]
    full_prec = float(hits_top[eps_valid].mean()) if eps_valid else np.nan
    leverages, recalls_without = [], []
    for drop in eps_top:
        kept = [e for e in eps_top if e["peak"] != drop["peak"]]
        rec = recall(sig, [e for e in kept if e["scope"] != "news_crash_excluded"])
        recalls_without.append(rec["n_caught"])
        # precision with this episode's alert window removed
        lo = max(0, drop["peak_pos"] - 30); hi = min(len(sig), drop["peak_pos"] + 11)
        keep_mask = np.ones(len(sig), dtype=bool); keep_mask[lo:hi] = False
        eps_k = [p for p in eps_valid if keep_mask[p]]
        prec_wo = float(hits_top[eps_k].mean()) if eps_k else np.nan
        leverages.append(base - prec_wo if np.isfinite(prec_wo) else np.nan)
    max_lev = float(np.nanmax(leverages)) if leverages else np.nan
    return {"full_precision": full_prec, "base": base,
            "max_leverage_drop": max_lev,
            "no_single_collapse": bool(np.isfinite(max_lev) and max_lev <= 0),
            "recall_distribution": recalls_without}


# ---- confirmatory max-stat across the frozen grid ----------------------------

def max_stat_reality(constructions: list, panel: pd.DataFrame, hits: dict,
                     regime: np.ndarray) -> dict:
    """Reality-check p across the frozen grid using opportunity-set null edge distributions."""
    edges, nulls = [], []
    for i, c in enumerate(constructions):
        sig = c.fn(panel)
        ep = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
        hit = hits[(c.side, TIER)].to_numpy()
        elig = (C2.eligible_top(panel) if c.side == "top" else C2.eligible_bottom(panel)).to_numpy()
        valid = np.isfinite(hit)
        pool = np.flatnonzero(valid & elig)
        eps_v = np.array([p for p in ep if valid[p]], dtype=int)
        if len(eps_v) == 0 or len(pool) == 0:
            continue
        eb = float(hit[pool].mean())
        edges.append(float(hit[eps_v].mean()) - eb)
        rng = _rng(7000 + i)
        nd = np.array([hit[rng.choice(pool, size=len(eps_v), replace=len(pool) < len(eps_v))].mean() - eb
                       for _ in range(2000)])
        nulls.append(nd)
    if not edges:
        return {"reality_p": np.nan, "v_obs": np.nan, "cells": 0}
    V = float(np.nanmax(edges))
    null_max = np.nanmax(np.vstack(nulls), axis=0)
    p = float((1 + np.sum(null_max >= V)) / (len(null_max) + 1))
    return {"reality_p": p, "v_obs": V, "cells": len(edges)}


# ---- G5 stack-beats-parts at matched alert count -----------------------------

def stack_beats_parts(panel: pd.DataFrame, hits: dict, regime: np.ndarray) -> dict:
    """Primary gated T1 precision vs the ungated watch and each standalone leg, at MATCHED
    alert count (subsample the looser arm to T1's episode count, bootstrap CI on the diff)."""
    hit = hits[("top", TIER)].to_numpy()
    valid = np.isfinite(hit)

    def prec_eps(sig):
        ep = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
        ep = [p for p in ep if valid[p]]
        return (float(hit[ep].mean()) if ep else np.nan), ep

    t1 = C2.t1_core_gated(panel)
    p_t1, ep_t1 = prec_eps(t1)
    comparators = {
        "ungated_watch": C2.ungated_watch(panel),
        "leg_vvix_residual_high": C2.vvix_residual_high(panel, 0.90),
        "leg_abi_churn": C2.abi_churn(panel, 0.20),
    }
    out = {"t1_precision": p_t1, "t1_n": len(ep_t1), "beats": {}}
    rng = _rng(8000)
    for name, sig in comparators.items():
        p_c, ep_c = prec_eps(sig)
        # matched-alert-count bootstrap: subsample comparator to len(ep_t1)
        diffs = []
        if ep_c and ep_t1:
            for _ in range(2000):
                sub = rng.choice(ep_c, size=min(len(ep_t1), len(ep_c)), replace=len(ep_c) < len(ep_t1))
                diffs.append(p_t1 - float(hit[sub].mean()))
            lo = float(np.quantile(diffs, 0.05))
            out["beats"][name] = {"comparator_precision": p_c, "diff_p05": lo,
                                  "t1_beats": bool(lo > 0)}
        else:
            out["beats"][name] = {"comparator_precision": p_c, "diff_p05": np.nan, "t1_beats": False}
    return out
