"""Per-condition ablation, multiple-testing control, and the 5-part kill-gate.

Pipeline (final-plan.md 6.4-6.5, 2):
  1. For every condition: collapse to episodes, compute the PRIMARY edge (20d
     forward-return, sign-adjusted) vs base rate + the regime-matched null, the
     block-bootstrap CI, per-fold sign-stability, and the primary-tier hit-rate edge.
  2. Build the full 320-cell grid (all horizons + all tiers) for the data-snooping
     reality check.
  3. Multiple-testing: Benjamini-Hochberg FDR across the 32 primary cells; a
     max-statistic reality check across the whole grid (conservative: per-cell
     independent nulls -> the null max is if anything too large, so we never
     over-claim significance).
  4. Kill-gate funnel -> PASS / FAIL.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base_rate import (benjamini_hochberg, block_bootstrap_ci, edge_and_null,
                        vol_regime_labels)
from .event_study import (collapse_episodes, edge_sign, event_side,
                         forward_event_hits, forward_returns)
from .metrics import correlation_matrix, correlation_vif, independent_family_count
from .walk_forward import assign_folds, directional_stability, fold_edges
from ..signals.conditions import build_conditions


def run_full_ablation(panel: pd.DataFrame, pre: dict) -> dict:
    conditions = build_conditions()
    horizons = pre["hypothesis_grid"]["forward_return_outcome"]["horizons"]
    tiers = pre["target_events"]["tiers_pct"]
    primary_h = pre["primary"]["horizon_trading_days"]
    event_window = pre["target_events"]["event_window_trading_days"]
    ep_window = pre["episodes"]["window_trading_days"]
    primary_tier = pre["target_events"]["primary_tier_pct"]
    min_eff = pre["min_effect_size"]["mean_return_edge_pct"] / 100.0
    alpha = pre["min_effect_size"]["alpha"]
    folds = pre["walk_forward"]["folds"]
    min_ep = pre["walk_forward"]["min_episodes_per_fold"]

    fwd = forward_returns(panel, horizons)
    hits, fdd, fru = forward_event_hits(panel, tiers, event_window)
    regime = vol_regime_labels(panel)
    fold_assign = assign_folds(panel.index, folds)

    fwd_arr = {h: fwd[h].to_numpy() for h in horizons}
    valid = {h: np.isfinite(fwd_arr[h]) for h in horizons}
    hit_arr = {k: v.to_numpy() for k, v in hits.items()}
    hit_valid = {k: np.isfinite(a) for k, a in hit_arr.items()}

    rows: list[dict] = []
    grid_edges: list[float] = []
    grid_nulls: list[np.ndarray] = []
    firing: dict[str, pd.Series] = {}
    per_cond: dict[str, dict] = {}

    for i, c in enumerate(conditions):
        sig = c.fn(panel)
        firing[c.name] = sig
        ep_pos = np.flatnonzero(collapse_episodes(sig, ep_window).to_numpy())
        sign = edge_sign(c.side)
        evside = event_side(c.side)

        rprim = edge_and_null(fwd_arr[primary_h], ep_pos, regime, sign, valid[primary_h],
                              seed_offset=i, return_null_array=True)
        ep_valid = np.array([p for p in ep_pos if valid[primary_h][p]], dtype=int)
        ci_lo, ci_hi, _ = block_bootstrap_ci(fwd_arr[primary_h][ep_valid], seed_offset=i)
        fe = fold_edges(fwd_arr[primary_h], ep_pos, fold_assign, sign, valid[primary_h])
        stab = directional_stability(fe, min_ep)
        hk = (evside, primary_tier)
        # same seed formula as the grid hit-cells + the per-tier report -> identical p-values
        rhit = edge_and_null(hit_arr[hk], ep_pos, regime, 1.0, hit_valid[hk],
                             seed_offset=1000 * (i + 1) + primary_tier)

        rows.append({
            "name": c.name, "family": c.family, "side": c.side, "event_side": evside,
            "n_episodes": rprim["n_episodes"], "edge": rprim["edge"],
            "cond_mean": rprim["cond_mean"], "uncond_mean": rprim["uncond_mean"],
            "null_p": rprim["null_p"], "ci_lo": ci_lo, "ci_hi": ci_hi,
            "stable": stab["stable"], "fold_testable": stab["n_testable"],
            "fold_pos": stab["n_positive"], "fold_neg": stab["n_negative"],
            "hit_edge_pp": rhit["edge"] * 100.0, "hit_cond": rhit["cond_mean"],
            "hit_uncond": rhit["uncond_mean"], "hit_p": rhit["null_p"],
        })
        per_cond[c.name] = {"sign": sign, "family": c.family, "side": c.side,
                            "firing": sig, "ep_pos": ep_pos, "edge": rprim["edge"],
                            "folds": fe}

        for h in horizons:
            r = rprim if h == primary_h else edge_and_null(
                fwd_arr[h], ep_pos, regime, sign, valid[h],
                seed_offset=100 * (i + 1) + h, return_null_array=True)
            grid_edges.append(r["edge"]); grid_nulls.append(r["null_edges"])
        for tier in tiers:
            hk2 = (evside, tier)
            r = edge_and_null(hit_arr[hk2], ep_pos, regime, 1.0, hit_valid[hk2],
                              seed_offset=1000 * (i + 1) + tier, return_null_array=True)
            grid_edges.append(r["edge"]); grid_nulls.append(r["null_edges"])

    table = pd.DataFrame(rows)
    bh = benjamini_hochberg(table["null_p"].tolist(), alpha)
    table["bh_survive"] = bh

    # data-snooping reality check across the full grid
    edges = np.array(grid_edges, dtype=float)
    nulls = np.vstack(grid_nulls)
    finite = np.isfinite(edges)
    V_obs = float(np.nanmax(edges[finite])) if finite.any() else np.nan
    null_max = np.nanmax(np.where(np.isfinite(nulls[finite]), nulls[finite], -np.inf), axis=0)
    reality_p = float((1 + np.sum(null_max >= V_obs)) / (len(null_max) + 1))

    firing_df = pd.DataFrame(firing)
    vif = correlation_vif(firing_df)

    return {
        "table": table, "per_cond": per_cond, "vif": vif,
        "corr": correlation_matrix(firing_df), "reality_p": reality_p,
        "V_obs": V_obs, "grid_cells": len(grid_edges), "alpha": alpha,
        "min_eff": min_eff, "primary_h": primary_h, "primary_tier": primary_tier,
        "fwd_arr": fwd_arr, "valid": valid, "regime": regime, "ep_window": ep_window,
        "fdd": fdd, "fru": fru, "hits": hits, "tiers": tiers,
    }


def _combined_check(res: dict, survivors: pd.DataFrame) -> dict:
    """Equal-weight combined (OR of same-side survivors) vs best single survivor (OOF)."""
    per = res["per_cond"]
    groups = {"risk_off": [], "risk_on": []}
    for _, row in survivors.iterrows():
        key = "risk_off" if per[row["name"]]["sign"] < 0 else "risk_on"
        groups[key].append(row["name"])
    group = max(groups.values(), key=len)
    if len(group) < 2:
        return {"applicable": False, "reason": "fewer than 2 same-side survivors"}
    sign = per[group[0]]["sign"]
    combined = np.logical_or.reduce([per[n]["firing"].to_numpy() for n in group])
    idx = per[group[0]]["firing"].index
    combined_sig = pd.Series(combined, index=idx)
    ep_pos = np.flatnonzero(collapse_episodes(combined_sig, res["ep_window"]).to_numpy())
    r = edge_and_null(res["fwd_arr"][res["primary_h"]], ep_pos, res["regime"], sign,
                      res["valid"][res["primary_h"]], seed_offset=99_999)
    best_single = max(per[n]["edge"] for n in group)
    return {"applicable": True, "group": group, "combined_edge": r["edge"],
            "combined_p": r["null_p"], "best_single": best_single,
            "beats": bool(np.isfinite(r["edge"]) and r["edge"] >= best_single)}


def evaluate_kill_gate(res: dict, pre: dict) -> dict:
    """The 5-part funnel. Each survivor must clear positive edge + BH-FDR + stability
    + min effect size; the reality check is a global precondition for gate 2."""
    t = res["table"]
    alpha, min_eff = res["alpha"], res["min_eff"]
    reality_ok = res["reality_p"] < alpha

    g2 = t[(t["edge"] > 0) & (t["bh_survive"])]                       # positive + FDR
    g3 = g2[g2["stable"]]                                             # + fold-stable
    g4 = g3[g3["edge"] >= min_eff]                                    # + min effect size
    final = g4
    families = sorted(set(final["family"]))

    gate2 = bool(reality_ok and len(g2) >= 1)
    gate3 = bool(len(g3) >= 1)
    gate4 = bool(len(g4) >= 1)
    gate1 = bool(independent_family_count(list(final["family"])) >= 3)
    combined = _combined_check(res, final) if len(final) >= 2 else {"applicable": False}
    gate5 = bool(combined.get("beats", False))

    verdict = gate1 and gate2 and gate3 and gate4 and gate5
    return {
        "verdict": "PASS" if verdict else "FAIL",
        "gate1_families_ge3": gate1, "gate2_edge_survives_mtc": gate2,
        "gate3_fold_stable": gate3, "gate4_min_effect": gate4,
        "gate5_combined_beats_single": gate5,
        "reality_p": res["reality_p"], "reality_ok": reality_ok,
        "n_bh_positive_survivors": int(len(g2)), "n_stable": int(len(g3)),
        "n_final_survivors": int(len(final)), "survivor_families": families,
        "final_survivors": final["name"].tolist(), "combined": combined,
    }
