"""Pure evaluation math — no DB, no network, no sklearn.

Every function here is deterministic and unit-tested in
`tests/test_eval_metrics.py`. Keep it dependency-light (numpy only) so the
math can be checked by hand on a tiny fixture.

Conventions
-----------
- `probs`  : predicted probabilities in [0, 1].
- `scores` : any real-valued ranking score (higher = more bullish).
- `labels` : 0/1 outcomes. 1 = "hit" (price up at the horizon).
Only RESOLVED rows should ever reach these functions — a NULL outcome is not
a 0. Filtering happens in `loaders.py`; these functions assume clean inputs.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Proper scoring rules
# ---------------------------------------------------------------------------

def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float:
    """Mean squared error between predicted probability and 0/1 outcome.

    Lower is better. A perfect forecaster scores 0; always-0.5 scores 0.25.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    if p.size == 0:
        return float("nan")
    return float(np.mean((p - y) ** 2))


def base_rate_brier(labels: Sequence[int]) -> float:
    """Brier of the constant forecast p = base_rate (the no-skill benchmark).

    Any real model must beat this to justify its existence. For a base rate
    `b` this equals b*(1-b) — the variance of a Bernoulli.
    """
    y = np.asarray(labels, dtype=float)
    if y.size == 0:
        return float("nan")
    b = float(np.mean(y))
    return float(np.mean((b - y) ** 2))


def log_loss(probs: Sequence[float], labels: Sequence[int], eps: float = 1e-15) -> float:
    """Binary cross-entropy. Lower is better. Probabilities are clipped to
    [eps, 1-eps] so a confident wrong call does not produce infinity."""
    p = np.clip(np.asarray(probs, dtype=float), eps, 1 - eps)
    y = np.asarray(labels, dtype=float)
    if p.size == 0:
        return float("nan")
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


# ---------------------------------------------------------------------------
# Calibration reliability
# ---------------------------------------------------------------------------

def reliability_bins(
    probs: Sequence[float], labels: Sequence[int], n_bins: int = 10
) -> list[dict]:
    """Equal-width reliability table over [0, 1].

    Returns one dict per non-empty bin:
        {bin_lo, bin_hi, n, mean_pred, mean_actual}
    A well-calibrated model has mean_pred ~= mean_actual in every bin.
    """
    p = np.asarray(probs, dtype=float)
    y = np.asarray(labels, dtype=float)
    out: list[dict] = []
    if p.size == 0:
        return out
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        # last bin is closed on the right so p == 1.0 lands somewhere
        if i == n_bins - 1:
            mask = (p >= lo) & (p <= hi)
        else:
            mask = (p >= lo) & (p < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        out.append(
            {
                "bin_lo": float(lo),
                "bin_hi": float(hi),
                "n": n,
                "mean_pred": float(p[mask].mean()),
                "mean_actual": float(y[mask].mean()),
            }
        )
    return out


def decile_table(scores: Sequence[float], labels: Sequence[int], n_bins: int = 10) -> list[dict]:
    """Equal-count (quantile) buckets of a ranking score, low→high.

    Unlike reliability_bins (equal width on a probability), this splits by
    rank so every bucket has ~the same n — the right view for a raw score
    whose distribution is lumpy. Returns {rank, n, score_lo, score_hi, hit_rate}.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=float)
    if s.size == 0:
        return []
    order = np.argsort(s, kind="mergesort")
    s, y = s[order], y[order]
    out: list[dict] = []
    idx = np.array_split(np.arange(s.size), n_bins)
    for rank, chunk in enumerate(idx):
        if chunk.size == 0:
            continue
        out.append(
            {
                "rank": rank + 1,
                "n": int(chunk.size),
                "score_lo": float(s[chunk].min()),
                "score_hi": float(s[chunk].max()),
                "hit_rate": float(y[chunk].mean()),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Discrimination
# ---------------------------------------------------------------------------

def auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Area under the ROC curve via the Mann-Whitney U statistic, with
    correct handling of tied scores (ties contribute 0.5).

    0.5 = no discrimination. Returns nan if only one class is present.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    # average ranks (1-based), ties share the mean rank
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(s.size, dtype=float)
    sorted_s = s[order]
    i = 0
    while i < s.size:
        j = i
        while j + 1 < s.size and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank for the tie block
        ranks[order[i : j + 1]] = avg
        i = j + 1
    sum_ranks_pos = ranks[y == 1].sum()
    u = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def precision_at_k(scores: Sequence[float], labels: Sequence[int], k_frac: float) -> dict:
    """Precision among the top `k_frac` fraction ranked by score (desc).

    Returns {k, n_selected, hits, precision}. `k` is the fraction actually
    used. Ties at the cutoff are included, so n_selected may exceed the
    requested count (no arbitrary tie-breaking).
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    n = s.size
    if n == 0 or k_frac <= 0:
        return {"k": k_frac, "n_selected": 0, "hits": 0, "precision": float("nan")}
    k_count = max(1, int(round(n * k_frac)))
    thresh = np.sort(s)[::-1][min(k_count, n) - 1]
    mask = s >= thresh
    sel = int(mask.sum())
    hits = int(y[mask].sum())
    return {
        "k": k_frac,
        "n_selected": sel,
        "hits": hits,
        "precision": hits / sel if sel else float("nan"),
    }


def top_decile_lift(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Hit rate of the top-10% by score divided by the overall base rate.

    >1 means the top decile is richer in hits than average. Returns nan if
    the base rate is 0.
    """
    base = float(np.mean(labels)) if len(labels) else float("nan")
    if not base:
        return float("nan")
    p10 = precision_at_k(scores, labels, 0.10)["precision"]
    return p10 / base if base else float("nan")


def fpr_by_band(scores: Sequence[float], labels: Sequence[int], edges: Sequence[float]) -> list[dict]:
    """False-positive rate per score band. A "positive" prediction is any
    alert in the band; FPR = fraction of band members that did NOT hit
    (label 0). Returns {lo, hi, n, hit_rate, fpr}."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(labels, dtype=int)
    out: list[dict] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (s >= lo) & (s < hi)
        n = int(mask.sum())
        if n == 0:
            continue
        hr = float(y[mask].mean())
        out.append({"lo": float(lo), "hi": float(hi), "n": n, "hit_rate": hr, "fpr": 1.0 - hr})
    return out


# ---------------------------------------------------------------------------
# Confidence intervals & rank correlation
# ---------------------------------------------------------------------------

def wilson_lower_bound(hits: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval for a binomial proportion.

    This is the honest "how low could the true hit rate really be" number for
    a subgroup — it punishes small n. Returns 0.0 for n == 0.
    """
    if n == 0:
        return 0.0
    phat = hits / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """(lower, upper) Wilson score interval."""
    if n == 0:
        return (0.0, 1.0)
    phat = hits / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def pearson_ic(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson correlation (information coefficient). nan if either side is
    constant."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    if a.size < 2 or a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def spearman_ic(x: Sequence[float], y: Sequence[float]) -> float:
    """Spearman rank IC — Pearson on the ranks. Robust to the lumpy,
    non-linear score distributions here. nan if either side is constant."""
    a = np.asarray(x, dtype=float)
    b = np.asarray(y, dtype=float)
    if a.size < 2:
        return float("nan")
    ra = _rankdata(a)
    rb = _rankdata(b)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def _rankdata(a: np.ndarray) -> np.ndarray:
    """Average ranks (1-based), ties share the mean rank. Mirrors
    scipy.stats.rankdata to keep this file scipy-free."""
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(a.size, dtype=float)
    sorted_a = a[order]
    i = 0
    while i < a.size:
        j = i
        while j + 1 < a.size and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks
