"""Multiple-testing (BH-FDR) conservatism + VIF on controlled toy inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.base_rate import benjamini_hochberg
from src.backtest.metrics import correlation_vif


def test_bh_is_more_conservative_than_naive_alpha() -> None:
    # 2 nominally-significant p-values among 10 -> BH (FDR) keeps FEWER than naive
    pvals = [0.02, 0.03] + [0.9] * 8
    alpha = 0.05
    naive = sum(p < alpha for p in pvals)
    bh = benjamini_hochberg(pvals, alpha)
    assert naive == 2
    assert sum(bh) < naive  # FDR control removes the borderline two


def test_bh_keeps_a_strong_signal() -> None:
    pvals = [0.0001] + [0.6] * 19
    bh = benjamini_hochberg(pvals, 0.05)
    assert bh[0] is True
    assert sum(bh) == 1


def test_vif_flags_collinear_columns() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=500)
    df = pd.DataFrame({
        "a": x,
        "b": x + rng.normal(scale=0.01, size=500),  # near-duplicate of a -> high VIF
        "c": rng.normal(size=500),                  # independent -> VIF ~ 1
    })
    vif = correlation_vif(df)
    assert vif.loc["a", "vif"] > 5
    assert vif.loc["b", "vif"] > 5
    assert vif.loc["c", "vif"] < 2
