"""Base-rate benchmark, edge, and the regime-matched random-timing null.

Every conditional metric is reported against the unconditional metric over the
identical horizon/sample; edge = sign-adjusted (conditional - unconditional). The
random-episode-timing null (same episode count, same vol-regime mix, random dates)
is the floor the real signal must beat — not merely the unconditional drift.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import get
from ..features import utils as U


def vol_regime_labels(panel: pd.DataFrame, n_buckets: int = 3) -> np.ndarray:
    """Bucket each day by its trailing-252 VIX percentile (0=calm .. n-1=stressed).

    Days without a VIX percentile yet are bucket 0. Used to regime-match the null.
    """
    vixp = U.trailing_percentile(panel["VIX_close"], 252)
    edges = np.linspace(0.0, 1.0, n_buckets + 1)[1:-1]
    lab = np.digitize(vixp.fillna(0.0).to_numpy(), edges)
    return lab.astype(int)


def _rng(offset: int = 0):
    return np.random.default_rng(int(get("backtest.random_seed", 1729)) + offset)


def block_bootstrap_ci(
    values: np.ndarray, n_iter: int | None = None, block: int | None = None,
    ci: float = 0.95, seed_offset: int = 0,
) -> tuple[float, float, float]:
    """Stationary block bootstrap CI for the MEAN of `values` (NaNs dropped)."""
    v = values[~np.isnan(values)]
    if len(v) == 0:
        return (np.nan, np.nan, np.nan)
    n_iter = n_iter or int(get("backtest.bootstrap_iterations", 2000))
    block = block or int(get("backtest.bootstrap_block_size", 20))
    rng = _rng(seed_offset)
    n = len(v)
    means = np.empty(n_iter)
    for b in range(n_iter):
        idx = np.empty(n, dtype=int)
        filled = 0
        while filled < n:
            start = rng.integers(0, n)
            length = rng.geometric(1.0 / block)
            take = min(length, n - filled)
            for k in range(take):
                idx[filled + k] = (start + k) % n
            filled += take
        means[b] = v[idx].mean()
    lo = float(np.quantile(means, (1 - ci) / 2))
    hi = float(np.quantile(means, 1 - (1 - ci) / 2))
    return (lo, hi, float(v.mean()))


def edge_and_null(
    daily_values: np.ndarray,
    episode_positions: np.ndarray,
    regime_labels: np.ndarray,
    sign: float,
    valid_mask: np.ndarray | None = None,
    n_draws: int | None = None,
    seed_offset: int = 0,
    return_null_array: bool = False,
) -> dict:
    """Compute sign-adjusted edge of `daily_values` at episode entries vs unconditional,
    plus a regime-matched random-timing null p-value.

    daily_values : per-day outcome (forward return at a horizon, or 0/1 hit).
    episode_positions : integer positions of episode-entry days.
    regime_labels : per-day regime bucket (for matching the null).
    sign : +1 if higher outcome is the signal's intent, -1 if lower.
    valid_mask : per-day bool; only valid days enter the unconditional pool/null.
    """
    n_draws = n_draws or int(get("backtest.null_iterations", 2000))
    vals = np.asarray(daily_values, dtype=float)
    valid = np.isfinite(vals) if valid_mask is None else (valid_mask & np.isfinite(vals))
    eps = np.array([p for p in episode_positions if valid[p]], dtype=int)
    n_ep = len(eps)
    uncond = float(np.nanmean(vals[valid])) if valid.any() else np.nan
    if n_ep == 0 or not np.isfinite(uncond):
        out = {"n_episodes": n_ep, "cond_mean": np.nan, "uncond_mean": uncond,
               "edge": np.nan, "null_p": np.nan, "null_edge_mean": np.nan}
        if return_null_array:
            out["null_edges"] = np.full(n_draws, np.nan)
        return out
    cond = float(vals[eps].mean())
    edge = sign * (cond - uncond)

    # regime-matched random-timing null
    rng = _rng(seed_offset)
    pool_by_regime: dict[int, np.ndarray] = {}
    valid_pos = np.flatnonzero(valid)
    for r in np.unique(regime_labels[valid_pos]):
        pool_by_regime[int(r)] = valid_pos[regime_labels[valid_pos] == r]
    ep_regimes = regime_labels[eps]
    counts = {int(r): int((ep_regimes == r).sum()) for r in np.unique(ep_regimes)}

    null_edges = np.empty(n_draws)
    for d in range(n_draws):
        picks = []
        for r, c in counts.items():
            pool = pool_by_regime.get(r, valid_pos)
            replace = len(pool) < c
            picks.append(rng.choice(pool, size=c, replace=replace))
        sel = np.concatenate(picks)
        null_edges[d] = sign * (vals[sel].mean() - uncond)
    p = float((1 + np.sum(null_edges >= edge)) / (n_draws + 1))
    out = {
        "n_episodes": n_ep, "cond_mean": cond, "uncond_mean": uncond,
        "edge": edge, "null_p": p, "null_edge_mean": float(null_edges.mean()),
    }
    if return_null_array:
        out["null_edges"] = null_edges
    return out


def benjamini_hochberg(pvals: list[float], alpha: float = 0.05) -> list[bool]:
    """Return a reject/keep mask (True = survives) controlling FDR at alpha."""
    arr = np.array([p if np.isfinite(p) else 1.0 for p in pvals], dtype=float)
    m = len(arr)
    order = np.argsort(arr)
    survive = np.zeros(m, dtype=bool)
    thresh_idx = -1
    for rank, idx in enumerate(order, start=1):
        if arr[idx] <= alpha * rank / m:
            thresh_idx = rank
    if thresh_idx > 0:
        survive[order[:thresh_idx]] = True
    return survive.tolist()
