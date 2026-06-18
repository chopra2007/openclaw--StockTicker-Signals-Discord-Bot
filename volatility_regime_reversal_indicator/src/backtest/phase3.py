"""Phase-3 ADD-ON scorers: alert-budget compliance (G7) and the benchmark battle (G6).

Everything else (opportunity-set null, temporal hold-out, QQQ transfer, LOEO, max-stat reality)
is reused VERBATIM from phase2.py — P3Construction is duck-type-compatible with
phase2.score_construction (it reads only .fn/.side/.name/.role). No look-ahead is introduced
here; these are forward-outcome scorers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import phase2 as P2
from .event_study import collapse_episodes

EP_WINDOW = P2.EP_WINDOW
TIER = P2.TIER


def episodes_per_year(sig: pd.Series, index: pd.DatetimeIndex) -> float:
    """Mean COLLAPSED episodes per calendar year (what the alert budget measures)."""
    ep = int(collapse_episodes(sig, EP_WINDOW).sum())
    years = (index.max() - index.min()).days / 365.25
    return float(ep) / years if years > 0 else float("nan")


def alert_budget_compliance(sig: pd.Series, index: pd.DatetimeIndex,
                            lo: float, hi: float) -> dict:
    """G7: the cap (`hi`) is the hard constraint ('speak no more than N/yr'); firing below the
    soft floor (`lo`) is allowed but flagged 'quiet/underpowered' (too few episodes for a
    significant null — handled by G1, not here)."""
    epy = episodes_per_year(sig, index)
    return {"episodes_per_year": epy,
            "within_cap": bool(np.isfinite(epy) and epy <= hi),
            "above_min": bool(np.isfinite(epy) and epy >= lo),
            "cap": hi, "min": lo}


def beats_benchmark(panel: pd.DataFrame, hits: dict, detector_fn, bench_fn,
                    side: str, seed_offset: int = 0) -> dict:
    """G6 benchmark battle: the detector's precision must beat the late-but-robust 200-day
    trend baseline at MATCHED alert count (subsample the looser arm to the tighter's episode
    count, bootstrap CI on the difference; pass if diff_p05 > 0). Same matched-count bootstrap
    pattern as P2.stack_beats_parts."""
    hit = hits[(side, TIER)].to_numpy()
    valid = np.isfinite(hit)

    def prec_eps(sig):
        ep = np.flatnonzero(collapse_episodes(sig, EP_WINDOW).to_numpy())
        ep = [p for p in ep if valid[p]]
        return (float(hit[ep].mean()) if ep else np.nan), ep

    p_det, ep_det = prec_eps(detector_fn(panel))
    p_bench, ep_bench = prec_eps(bench_fn(panel))
    rng = np.random.default_rng(P2.SEED + seed_offset)
    if ep_det and ep_bench:
        diffs = []
        for _ in range(2000):
            sub = rng.choice(ep_bench, size=min(len(ep_det), len(ep_bench)),
                             replace=len(ep_bench) < len(ep_det))
            diffs.append(p_det - float(hit[sub].mean()))
        lo = float(np.quantile(diffs, 0.05))
        beats = bool(lo > 0)
    else:
        lo, beats = np.nan, False
    return {"detector_precision": p_det, "detector_n": len(ep_det),
            "bench_precision": p_bench, "bench_n": len(ep_bench),
            "diff_p05": lo, "beats": beats}
