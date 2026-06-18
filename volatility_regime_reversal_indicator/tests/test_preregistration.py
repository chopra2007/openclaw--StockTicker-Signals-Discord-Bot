"""The frozen pre-registration contract must parse and contain all 8 sections."""
from __future__ import annotations

from pathlib import Path

import yaml

_PRE = Path(__file__).resolve().parent.parent / "backtest" / "preregistration.yaml"


def _load() -> dict:
    return yaml.safe_load(_PRE.read_text())


def test_file_exists_and_parses() -> None:
    assert _PRE.exists()
    assert isinstance(_load(), dict)


def test_all_required_sections_present() -> None:
    d = _load()
    required = [
        "meta", "primary", "target_events", "min_effect_size", "hypothesis_grid",
        "episodes", "walk_forward", "structural_breaks", "null_model",
        "multiple_testing", "kill_gate",
    ]
    for k in required:
        assert k in d, f"missing pre-registration section: {k}"


def test_primary_horizon_and_tiers() -> None:
    d = _load()
    assert d["primary"]["horizon_trading_days"] == 20
    assert d["target_events"]["primary_tier_pct"] == 8
    assert set(d["target_events"]["tiers_pct"]) == {5, 8, 15, 20}


def test_frozen_flag_and_killgate_shape() -> None:
    d = _load()
    assert d["meta"]["frozen_before_returns_inspected"] is True
    assert len(d["kill_gate"]["conditions"]) == 5
    assert d["multiple_testing"]["deflated_sharpe"] is False


def test_grid_count_is_self_consistent() -> None:
    g = _load()["hypothesis_grid"]
    assert g["total_conditions_including_variants"] == g["conditions"] * g["threshold_variants_per_condition"]
    cells = g["total_conditions_including_variants"] * (
        len(g["forward_return_outcome"]["horizons"]) + len(g["target_event_outcome"]["tiers_pct"])
    )
    assert cells == g["total_grid_cells"]
