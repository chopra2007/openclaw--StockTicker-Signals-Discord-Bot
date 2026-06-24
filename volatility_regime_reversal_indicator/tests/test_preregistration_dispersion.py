"""The frozen Phase-DISPERSION pre-registration must parse and carry its required sections
+ the honesty disclosures (survivorship caveat, opportunity-set null, OOS battery including
the QQQ transfer), the 5-condition kill-gate, and the pre-registered thresholds."""
from __future__ import annotations

from pathlib import Path

import yaml

_PRE = Path(__file__).resolve().parent.parent / "backtest" / "preregistration_dispersion.yaml"


def _load() -> dict:
    return yaml.safe_load(_PRE.read_text())


def test_file_exists_and_parses() -> None:
    assert _PRE.exists()
    assert isinstance(_load(), dict)


def test_required_sections_present() -> None:
    d = _load()
    for k in ["meta", "primary", "target_events", "min_effect_size", "constructions",
              "episodes", "null_model", "out_of_sample", "multiple_testing", "kill_gate",
              "dispersion_thresholds"]:
        assert k in d, f"missing Phase-DISPERSION pre-registration section: {k}"
    assert "benchmark" in d["constructions"], "missing benchmark constructions for the G6 battle"


def test_honesty_disclosures_frozen() -> None:
    d = _load()
    assert d["meta"]["frozen_before_confirmatory_run"] is True
    assert d["meta"]["hypotheses_are_post_selected"] is True
    assert d["meta"]["phase"] == 6
    assert d["meta"]["name"] == "dispersion"
    assert d["meta"]["builds_on"] == "gamma_NO_GO"
    assert "survivorship_bias_note" in d["meta"]
    assert "mechanism_note" in d["meta"]
    assert d["null_model"]["type"] == "opportunity_set_random_timing"
    assert "temporal_holdout" in d["out_of_sample"]
    assert "cross_asset_transfer" in d["out_of_sample"]
    assert d["out_of_sample"]["cross_asset_transfer"]["asset"] == "QQQ"
    assert "leave_one_episode_out" in d["out_of_sample"]


def test_kill_gate_has_five_conditions() -> None:
    d = _load()
    assert len(d["kill_gate"]["conditions"]) == 5


def test_dispersion_thresholds_frozen() -> None:
    d = _load()
    dt = d["dispersion_thresholds"]
    assert dt["primary_pct_trigger"] == 0.80
    assert dt["near_high_gate"] == 0.97
    assert 252 in dt["windows_tested"]
    assert dt["sign"] == "HIGH_dispersion_precedes_TOP"


def test_episode_list_has_twelve_tops() -> None:
    d = _load()
    eps = d["target_events"]["episode_list_top_8pct"]
    assert len(eps) == 12
    assert d["meta"]["ground_truth_top_episodes_8pct"] == 12


def test_min_effect_size_present() -> None:
    d = _load()
    me = d["min_effect_size"]
    assert me["precision_edge_pp"] == 8.0
    assert me["recall_floor_organic"] == 4
    assert me["alpha"] == 0.05
