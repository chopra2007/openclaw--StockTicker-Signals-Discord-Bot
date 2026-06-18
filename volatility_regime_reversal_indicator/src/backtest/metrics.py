"""Collinearity/VIF + family report, coverage & regime stratification, tails.

VIF is computed from the inverse of the correlation matrix (VIF_i = (R^-1)_ii) —
no statsmodels dependency. This is the artifact the kill-gate's ">=3 independent
families" test reads.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..features import utils as U


def correlation_vif(firing: pd.DataFrame) -> pd.DataFrame:
    """firing: DataFrame of boolean condition series (cols=condition names).

    Returns a per-condition VIF table; drops zero-variance columns (never fire)."""
    df = firing.astype(float)
    nz = df.loc[:, df.std(ddof=0) > 0]
    if nz.shape[1] < 2:
        return pd.DataFrame({"vif": []})
    R = np.corrcoef(nz.to_numpy(), rowvar=False)
    try:
        Rinv = np.linalg.inv(R)
    except np.linalg.LinAlgError:
        Rinv = np.linalg.pinv(R)
    vif = np.diag(Rinv)
    return pd.DataFrame({"vif": vif}, index=nz.columns).sort_values("vif", ascending=False)


def correlation_matrix(firing: pd.DataFrame) -> pd.DataFrame:
    df = firing.astype(float)
    nz = df.loc[:, df.std(ddof=0) > 0]
    return nz.corr()


def independent_family_count(survivor_families: list[str]) -> int:
    """Number of DISTINCT families among survivors (kill-gate condition 1)."""
    return len(set(survivor_families))


def coverage_pct(panel: pd.DataFrame, key_cols: list[str]) -> pd.Series:
    """Per-day fraction of key inputs that are present (non-NaN)."""
    present = panel[key_cols].notna().sum(axis=1)
    return present / float(len(key_cols))


def coverage_buckets(coverage: pd.Series) -> pd.Series:
    """Label each day low/mid/high coverage for stratified reporting."""
    return pd.cut(coverage, bins=[-0.01, 0.5, 0.8, 1.01], labels=["low", "mid", "high"])


def distribution_tails(values: np.ndarray) -> dict:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return {"n": 0}
    return {
        "n": int(len(v)),
        "mean": float(v.mean()),
        "median": float(np.median(v)),
        "std": float(v.std(ddof=0)),
        "p05": float(np.quantile(v, 0.05)),
        "p25": float(np.quantile(v, 0.25)),
        "p75": float(np.quantile(v, 0.75)),
        "p95": float(np.quantile(v, 0.95)),
        "min": float(v.min()),
        "max": float(v.max()),
    }


def concentration_regime(panel: pd.DataFrame, window: int = 60) -> pd.Series:
    """Mega-cap concentration proxy = trailing change in RSP/SPY (breadth). Negative =
    narrowing/concentration (the 2023-24 regime that traps standing-divergence rules)."""
    if "RSP_close" not in panel.columns:
        return pd.Series(np.nan, index=panel.index)
    ratio = panel["RSP_close"] / panel["SPY_close"]
    return U.pct_change(ratio, window)
