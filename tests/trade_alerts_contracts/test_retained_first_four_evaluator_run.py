"""M9.1DU fail-closed retained first-four evaluator-run contracts."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_evaluator_plan import (
    build_retained_first_four_evaluator_plan,
)
from consensus_engine.retained_first_four_evaluator_run import (
    RUN_VERSION,
    execute_retained_first_four_evaluator_plan,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_first_two_producers import _input


def _plans():
    return tuple(
        build_retained_first_four_evaluator_plan(_input(playbook))
        for playbook in PLAYBOOKS
    )


def test_every_retained_plan_returns_its_exact_missing_inputs_without_advancing():
    plans = _plans()
    results = tuple(execute_retained_first_four_evaluator_plan(plan) for plan in plans)

    assert tuple(result.playbook for result in results) == PLAYBOOKS
    assert all(result.version == RUN_VERSION for result in results)
    assert {result.status for result in results} == {"UNAVAILABLE"}
    assert all(result.evaluated_step_count == 0 for result in results)
    assert all(result.transition_count == 0 for result in results)
    assert all(result.reason.split("|") == list(result.missing_required_inputs)
               for result in results)
    assert all(result.retained_source_record_ids == plan.retained_source_record_ids
               for result, plan in zip(results, plans))


def test_removed_missing_labels_cannot_make_incomplete_records_runnable():
    for plan in _plans():
        result = execute_retained_first_four_evaluator_plan(
            replace(plan, missing_required_inputs=()),
        )
        assert result.status == "UNAVAILABLE"
        assert result.evaluated_step_count == 0
        if plan.playbook in PLAYBOOKS[:2]:
            assert result.missing_required_inputs == ("CONFIDENCE_UNAVAILABLE",)
        else:
            assert "EVALUATOR_STEPS_UNAVAILABLE" in result.missing_required_inputs


def test_rejects_a_forged_evaluator_binding_before_execution():
    plan = replace(_plans()[0], evaluator_type="OrFailureRevReplayStrategy")
    with pytest.raises(RecordError, match="binding does not match"):
        execute_retained_first_four_evaluator_plan(plan)


def test_recorded_first_four_evaluator_run_is_deterministic():
    results = tuple(execute_retained_first_four_evaluator_plan(plan) for plan in _plans())
    full = [result.as_dict() for result in results]
    canonical = json.dumps(full, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "playbooks": list(PLAYBOOKS),
        "result_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "statuses": {result.playbook: result.status for result in results},
        "planned_step_counts": {
            result.playbook: result.planned_step_count for result in results
        },
        "evaluated_step_counts": {
            result.playbook: result.evaluated_step_count for result in results
        },
        "transition_counts": {
            result.playbook: result.transition_count for result in results
        },
        "missing_required_inputs": {
            result.playbook: list(result.missing_required_inputs) for result in results
        },
        "gap_dependent_rules": "OFF_UNTESTED",
        "exact_sample_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91du-retained-first-four-evaluator-run.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert len(rendered.encode()) < 2 * 1024 * 1024
