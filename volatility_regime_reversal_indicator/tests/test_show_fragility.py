"""Smoke test for the descriptive fragility-gauge readout (display-only tool)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.show_fragility import current_reading

_LEGS = {"low_vrp_complacency", "vix_term_stress", "vvix_tail_hedge_demand", "breadth_narrowing"}


def _panel(n: int = 560, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-01", periods=n)

    def s(start: float, vol: float) -> pd.Series:
        return pd.Series(start * np.exp(np.cumsum(rng.normal(0.0, vol, n))), index=idx)

    cols = {}
    for nm, (st, v) in {"SPY": (120, 0.01), "RSP": (60, 0.01), "VIX": (16, 0.06),
                        "VIX3M": (17, 0.05), "VVIX": (90, 0.05)}.items():
        cols[f"{nm}_close"] = s(st, v)
    return pd.DataFrame(cols, index=idx)


def test_current_reading_shape_and_bounds() -> None:
    r = current_reading(_panel())
    assert r["asof"] is not None
    assert 0.0 < r["gauge"] <= 1.0
    assert set(r["components"]) == _LEGS
    for v in r["components"].values():
        assert 0.0 <= v <= 1.0
