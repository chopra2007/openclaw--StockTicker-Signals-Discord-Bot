"""The frozen Phase-4 pre-registration must parse and carry its required sections + the
honesty disclosures (post-selection flag, opportunity-set null, the equally-distressed
eligibility, the 55-year temporal hold-out, controls + benchmark), the 7-condition kill-gate,
and the recalibrated alert budget."""
from __future__ import annotations

from pathlib import Path

import yaml

_PRE = Path(__file__).resolve().parent.parent / "backtest" / "preregistration_phase4.yaml"


def _load() -> dict:
    return yaml.safe_load(_PRE.read_text())


def test_file_exists_and_parses() -> None:
    assert _PRE.exists()
    assert isinstance(_load(), dict)


def test_required_sections_present() -> None:
    d = _load()
    for k in ["meta", "primary", "target_events", "min_effect_size", "constructions",
              "episodes", "alert_budget", "null_model", "out_of_sample", "multiple_testing",
              "kill_gate"]:
        assert k in d, f"missing Phase-4 pre-registration section: {k}"
    # the benchmark battle + the controls must be declared under constructions
    assert "benchmark" in d["constructions"], "missing benchmark constructions for the G6 battle"
    assert "controls" in d["constructions"], "missing controls (load-bearing for G5)"


def test_honesty_disclosures_frozen() -> None:
    d = _load()
    assert d["meta"]["frozen_before_confirmatory_run"] is True
    assert d["meta"]["hypotheses_are_post_selected"] is True
    assert d["meta"]["side_scope"] == "bottom_only"
    assert d["null_model"]["type"] == "opportunity_set_random_timing"
    # the make-or-break null draws from EQUALLY-DISTRESSED days, not all days
    assert "drawdown" in d["null_model"]["eligibility_bottom_primary"].lower()
    assert "temporal_holdout" in d["out_of_sample"]
    assert "leave_one_episode_out" in d["out_of_sample"]


def test_long_window_and_data_sources() -> None:
    d = _load()
    assert d["meta"]["breadth_source"] == "NYSE_UDVOL"
    assert d["meta"]["price_ticker"] == "GSPC"
    assert d["meta"]["window"]["start"] == "1965-03-01"
    assert d["meta"]["window"]["end"] == "2020-02-10"
    # the disclosed limitations must name the post-2020 gap
    lims = " ".join(d["meta"]["disclosed_limitations"]).lower()
    assert "2020" in lims


def test_kill_gate_has_seven_conditions() -> None:
    d = _load()
    assert len(d["kill_gate"]["conditions"]) == 7


def test_alert_budget_recalibrated_for_long_window() -> None:
    d = _load()
    ab = d["alert_budget"]["bottoms_per_year"]
    # a 90/90 pairing is rare — the band must be sub-2/yr (NOT the Phase-3 1-3 band)
    assert ab["max"] <= 2.0
    assert ab["min"] < ab["max"]
