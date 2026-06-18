"""The frozen Phase-2 pre-registration must parse and carry its required sections + the
honesty disclosures (post-selection flag, opportunity-set null, out-of-sample battery)."""
from __future__ import annotations

from pathlib import Path

import yaml

_PRE = Path(__file__).resolve().parent.parent / "backtest" / "preregistration_phase2.yaml"


def _load() -> dict:
    return yaml.safe_load(_PRE.read_text())


def test_file_exists_and_parses() -> None:
    assert _PRE.exists()
    assert isinstance(_load(), dict)


def test_required_sections_present() -> None:
    d = _load()
    for k in ["meta", "primary", "target_events", "min_effect_size", "constructions",
              "episodes", "null_model", "out_of_sample", "multiple_testing", "kill_gate"]:
        assert k in d, f"missing Phase-2 pre-registration section: {k}"


def test_honesty_disclosures_frozen() -> None:
    d = _load()
    assert d["meta"]["frozen_before_confirmatory_run"] is True
    # the post-selection of hypotheses MUST be disclosed
    assert d["meta"]["hypotheses_are_post_selected"] is True
    # the load-bearing null upgrade
    assert d["null_model"]["type"] == "opportunity_set_random_timing"
    # the out-of-sample battery both reviewers required
    assert "temporal_holdout" in d["out_of_sample"]
    assert "cross_asset_transfer" in d["out_of_sample"]
    assert "leave_one_episode_out" in d["out_of_sample"]
    assert len(d["kill_gate"]["conditions"]) == 5


def test_episode_list_has_twelve_tops() -> None:
    d = _load()
    eps = d["target_events"]["episode_list_top_8pct"]
    assert len(eps) == 12
    assert d["meta"]["ground_truth_top_episodes_8pct"] == 12
