"""M9.1DT retained first-four evaluator-plan contracts."""

import json
import hashlib
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_first_four_evaluator_plan import (
    EVALUATORS,
    RUN_VERSION,
    build_retained_first_four_evaluator_plan,
)
from consensus_engine.retained_decision_moments import PLAYBOOKS
from test_retained_first_two_producers import _input


def test_binds_every_first_four_playbook_to_its_canonical_evaluator_inputs():
    inputs = tuple(_input(playbook) for playbook in PLAYBOOKS)
    plans = tuple(build_retained_first_four_evaluator_plan(value) for value in inputs)

    assert tuple(plan.playbook for plan in plans) == PLAYBOOKS
    assert all(plan.version == RUN_VERSION for plan in plans)
    assert {plan.playbook: plan.evaluator_type for plan in plans} == EVALUATORS
    for value, plan, step_type in zip(
        inputs[:2], plans[:2], ("Orb5ReplayStep", "HodCompRsReplayStep"),
    ):
        assert value.decision_moments
        assert [type(row).__name__ for row in plan.steps] == (
            [step_type] * len(value.decision_moments)
        )
        assert tuple(row.evaluated_at for row in plan.steps) == value.decision_moments
        assert tuple(row.evaluated_at for row in plan.offline_inputs) == value.decision_moments
    assert plans[2].steps == () and plans[2].parent_records == ()
    assert plans[3].steps == () and plans[3].parent_records == ()
    assert all(plan.retained_source_record_ids == value.source_record_ids
               for value, plan in zip(inputs, plans))


def test_unknown_confidence_and_parent_inputs_keep_every_plan_not_runnable():
    plans = tuple(build_retained_first_four_evaluator_plan(_input(playbook))
                  for playbook in PLAYBOOKS)
    assert all(not plan.runnable for plan in plans)
    assert all("CONFIDENCE_UNAVAILABLE" in plan.missing_required_inputs for plan in plans)
    assert "ENDED_ORB_ATTEMPT_UNAVAILABLE" in plans[2].missing_required_inputs
    assert "ATR_1M_UNAVAILABLE" in plans[3].missing_required_inputs


def test_missing_retained_market_records_are_named_without_filling():
    value = _input("CRVOL_ORB5")
    missing = type(value)(
        value.playbook, value.ticker, value.session, value.decision_moments,
        value.history, (), (), (value.source_record_ids[0],),
    )
    plan = build_retained_first_four_evaluator_plan(missing)
    assert plan.missing_required_inputs[-2:] == (
        "RETAINED_TRADES_UNAVAILABLE", "RETAINED_QUOTES_UNAVAILABLE",
    )
    assert not plan.runnable


def test_recorded_first_four_evaluator_plan_is_deterministic():
    proof = {
        playbook: build_retained_first_four_evaluator_plan(_input(playbook)).as_dict()
        for playbook in PLAYBOOKS
    }
    canonical = json.dumps(proof, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "playbooks": list(PLAYBOOKS),
        "plan_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "step_counts": {
            playbook: len(plan["step_types"])
            for playbook, plan in proof.items()
        },
        "runnable": {
            playbook: plan["runnable"]
            for playbook, plan in proof.items()
        },
        "missing_required_inputs": {
            playbook: plan["missing_required_inputs"]
            for playbook, plan in proof.items()
        },
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dt-retained-first-four-evaluator-plan.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert len(rendered.encode()) < 2 * 1024 * 1024
