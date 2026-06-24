"""Smoke test for the descriptive fragility-gauge readout (display-only tool)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.show_fragility import _breadth_reading, _gamma_reading, current_reading

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


def _sqz_panel(n: int = 560, seed: int = 7) -> pd.DataFrame:
    """Synthetic SQZ panel with SQZ_gex and SQZ_dix columns."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-01", periods=n)
    # gex alternates positive/negative so both regimes appear
    gex = pd.Series(rng.normal(0.0, 2e9, n), index=idx)
    dix = pd.Series(np.clip(rng.normal(0.45, 0.05, n), 0.0, 1.0), index=idx)
    return pd.DataFrame({"SQZ_gex": gex, "SQZ_dix": dix}, index=idx)


def _breadth_panel(n: int = 560, seed: int = 9) -> pd.DataFrame:
    """Synthetic NYSE_BREADTH panel with adv/dec volume columns."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-01", periods=n)
    adv = pd.Series(np.abs(rng.normal(2e9, 5e8, n)), index=idx)
    dec = pd.Series(np.abs(rng.normal(2e9, 5e8, n)), index=idx)
    return pd.DataFrame({"NYSE_BREADTH_adv_volume": adv, "NYSE_BREADTH_dec_volume": dec}, index=idx)


def test_current_reading_shape_and_bounds() -> None:
    r = current_reading(_panel())
    assert r["asof"] is not None
    assert 0.0 < r["gauge"] <= 1.0
    assert set(r["components"]) == _LEGS
    for v in r["components"].values():
        assert 0.0 <= v <= 1.0


def test_gamma_reading_with_sufficient_history() -> None:
    """With 560 rows of synthetic SQZ data, all gamma fields should be finite."""
    g = _gamma_reading(_sqz_panel())
    assert g["asof"] is not None
    assert np.isfinite(g["gex_pct"]), "gex_pct should be finite with 560 rows"
    assert np.isfinite(g["dix_pct"]), "dix_pct should be finite with 560 rows"
    assert 0.0 <= g["gex_pct"] <= 1.0
    assert 0.0 <= g["dix_pct"] <= 1.0
    assert isinstance(g["neg_gamma"], bool)


def test_gamma_reading_insufficient_history() -> None:
    """With fewer than 252 rows, percentiles come back nan (too short for trailing window)."""
    p = _sqz_panel(n=100)
    g = _gamma_reading(p)
    assert g["asof"] is not None
    assert not np.isfinite(g["gex_pct"]), "gex_pct should be nan with only 100 rows"
    assert not np.isfinite(g["dix_pct"]), "dix_pct should be nan with only 100 rows"


def test_gamma_reading_empty_panel() -> None:
    """Empty panel returns asof=None without crashing."""
    g = _gamma_reading(pd.DataFrame())
    assert g["asof"] is None


def test_breadth_reading_basic() -> None:
    """With synthetic breadth data, up/down shares should be in [0, 1]."""
    b = _breadth_reading(_breadth_panel())
    assert b["asof"] is not None
    assert np.isfinite(b["up_share"])
    assert np.isfinite(b["down_share"])
    assert 0.0 <= b["up_share"] <= 1.0
    assert 0.0 <= b["down_share"] <= 1.0
    assert abs(b["up_share"] + b["down_share"] - 1.0) < 1e-9, "shares must sum to 1"
    assert b["rows"] == 560


def test_breadth_reading_thrust_day() -> None:
    """A day where all volume is advancing registers as up_share=1.0, down_share=0.0."""
    idx = pd.bdate_range("2012-01-01", periods=5)
    p = pd.DataFrame({
        "NYSE_BREADTH_adv_volume": pd.Series([1e9, 1e9, 1e9, 1e9, 1e9], index=idx),
        "NYSE_BREADTH_dec_volume": pd.Series([1e9, 1e9, 1e9, 1e9, 0.0], index=idx),
    })
    b = _breadth_reading(p)
    assert b["up_share"] == 1.0
    assert b["down_share"] == 0.0


def test_breadth_reading_empty_panel() -> None:
    """Empty panel returns asof=None without crashing."""
    b = _breadth_reading(pd.DataFrame())
    assert b["asof"] is None
