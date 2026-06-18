"""Disjoint walk-forward test windows + directional-fold-stability.

Phase 1 thresholds are frozen from theory (nothing is fitted), so plain
walk-forward over disjoint test windows suffices (final-plan.md 6.6). Each fold
restricts which SIGNAL DAYS are counted; the forward-return window may extend past
the fold boundary (that is an outcome, not a feature — no leakage). The gate uses
sign-stability across folds, not a per-fold p-value.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def assign_folds(index: pd.DatetimeIndex, folds: list[dict]) -> pd.Series:
    out = pd.Series(index=index, dtype=object)
    for f in folds:
        m = (index >= pd.Timestamp(f["start"])) & (index <= pd.Timestamp(f["end"]))
        out[m] = f["name"]
    return out


def fold_edges(
    daily_values: np.ndarray,
    episode_positions: np.ndarray,
    fold_assign: pd.Series,
    sign: float,
    valid_mask: np.ndarray,
) -> dict[str, dict]:
    """Per-fold sign-adjusted edge (point estimate) + episode count."""
    vals = np.asarray(daily_values, dtype=float)
    fold_names = fold_assign.to_numpy()
    eps = np.array([p for p in episode_positions if valid_mask[p]], dtype=int)
    out: dict[str, dict] = {}
    for fname in [f for f in pd.unique(fold_names) if f is not None and not pd.isna(f)]:
        in_fold = (fold_names == fname) & valid_mask
        ep_in = eps[(fold_names[eps] == fname)]
        if not in_fold.any():
            out[str(fname)] = {"edge": np.nan, "n_episodes": 0}
            continue
        uncond = float(np.nanmean(vals[in_fold]))
        if len(ep_in) == 0 or not np.isfinite(uncond):
            out[str(fname)] = {"edge": np.nan, "n_episodes": int(len(ep_in))}
            continue
        cond = float(np.nanmean(vals[ep_in]))
        out[str(fname)] = {"edge": sign * (cond - uncond), "n_episodes": int(len(ep_in))}
    return out


def directional_stability(fold_results: dict[str, dict], min_episodes: int = 3) -> dict:
    """Same-sign edge in the MAJORITY of testable folds (>= min_episodes)?"""
    testable = [(f, r) for f, r in fold_results.items()
                if r["n_episodes"] >= min_episodes and np.isfinite(r["edge"])]
    n = len(testable)
    if n == 0:
        return {"stable": False, "n_testable": 0, "n_positive": 0, "n_negative": 0,
                "majority_sign": 0}
    n_pos = sum(1 for _, r in testable if r["edge"] > 0)
    n_neg = n - n_pos
    majority_sign = 1 if n_pos > n_neg else (-1 if n_neg > n_pos else 0)
    stable = (max(n_pos, n_neg) > n / 2) and majority_sign == 1
    return {"stable": bool(stable), "n_testable": n, "n_positive": n_pos,
            "n_negative": n_neg, "majority_sign": majority_sign}
