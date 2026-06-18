"""Candidate conditions: pure point-in-time bool Series, unique family, grid-consistent."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.data import store
from src.signals import conditions as C

_ALL = ["SPY", "QQQ", "RSP", "QQQE", "HYG", "LQD", "TLT",
        "VIX", "VIX3M", "VVIX", "VXN", "SKEW", "BAA10Y"]


def _panel():
    if not store.series_exists("SPY"):
        pytest.skip("store not populated; run `python3 -m src.run_update`")
    return store.load_panel(_ALL, start="2010-01-01")


def test_every_condition_returns_aligned_bool_series() -> None:
    panel = _panel()
    ev = C.evaluate_all(panel)
    assert len(ev) == 32  # 16 base x 2 variants
    for name, s in ev.items():
        assert isinstance(s, pd.Series), name
        assert s.dtype == bool, f"{name} not boolean"
        assert s.index.equals(panel.index), f"{name} index misaligned"
        assert not s.isna().any(), f"{name} has NaN (should be filled False)"


def test_family_assignment_unique_per_condition() -> None:
    reg = C.registry()
    names = [r["name"] for r in reg]
    assert len(names) == len(set(names)), "duplicate condition names"
    for r in reg:
        assert r["family"], r["name"]
        assert r["side"] in {"top", "bottom", "vol_expansion", "vol_contraction"}, r


def test_families_match_frozen_grid() -> None:
    pre = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "backtest" / "preregistration.yaml").read_text()
    )
    declared = set(pre["hypothesis_grid"]["condition_families"])
    used = {r["family"] for r in C.registry()}
    assert used <= declared, f"condition families not in frozen grid: {used - declared}"
