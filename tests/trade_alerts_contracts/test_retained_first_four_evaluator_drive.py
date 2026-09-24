"""M9.1DX exact-context and record-before-advance contracts."""

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
from consensus_engine.retained_first_four_evaluator_drive import (
    RUN_VERSION,
    drive_retained_first_four_evaluator_owner,
    execute_retained_first_four_evaluator_drive,
)
from consensus_engine.retained_first_four_evaluator_owner import (
    construct_retained_first_four_evaluator_owner,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_first_four_evaluator_owner import _config
from test_retained_first_four_owner_inputs import _complete_plan, _plans


class Recorder:
    def __init__(self, *, acknowledge=True):
        self.acknowledge = acknowledge
        self.rows = []

    def record(self, context, transitions):
        self.rows.append((context.evaluated_at, transitions))
        return transitions if self.acknowledge else ()


def _drive_config(plan, direction="LONG"):
    config = _config(plan.playbook, direction)
    if plan.playbook == "FIRST_PULLBACK_VWAP":
        from consensus_engine.retained_first_pullback_parent_scan import (
            scan_retained_first_pullback_parents,
        )
        from test_retained_first_pullback_parent_scan import _input, _evidence

        # Use the window that produced this January measurement, not the
        # unrelated July replay fixture used by the construction-only tests.
        value = _input(direction)
        scan = scan_retained_first_pullback_parents(value, evidence=_evidence(value))
        step, = scan.pullback_steps
        window, = scan.impulse_windows
        assert step.measurement == plan.steps[0].measurement
        assert window[0] < window[1] <= plan.steps[0].evaluated_at
        config = replace(config, impulse_window=window)
    return config


@pytest.mark.parametrize("playbook", PLAYBOOKS)
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_complete_admitted_owner_uses_exact_context_and_acknowledges_before_advance(
    playbook, direction,
):
    plan = _complete_plan(playbook, direction)
    config = _drive_config(plan, direction)
    recorder = Recorder()
    result = execute_retained_first_four_evaluator_drive(
        plan, config, recorder)

    assert result.status == "EVALUATED"
    assert result.evaluated_step_count == len(plan.steps) == 1
    assert result.proposed_transition_count == result.acknowledged_transition_count
    assert result.proposed_transition_count > 0
    assert recorder.rows[0][0] == plan.steps[0].confidence.request.context.evaluated_at
    assert result.final_state != construct_retained_first_four_evaluator_owner(
        plan, config).rules.initial_state


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_future_impulse_window_is_rejected_before_recording_or_state_advance(direction):
    plan = _complete_plan("FIRST_PULLBACK_VWAP", direction)
    mismatched = _config(plan.playbook, direction)
    assert mismatched.impulse_window[1] > plan.steps[0].evaluated_at
    owner = construct_retained_first_four_evaluator_owner(plan, mismatched)
    initial = owner.current_state()
    recorder = Recorder()

    with pytest.raises(RecordError, match="pullback cannot be evaluated before the impulse froze"):
        drive_retained_first_four_evaluator_owner(owner, plan, recorder)

    assert recorder.rows == []
    assert owner.current_state() == initial
    assert owner.confirm_recorded() == initial


def test_failed_recording_acknowledgment_cannot_advance_owner():
    plan = _complete_plan("OR_FAILURE_REV", "SHORT")
    owner = construct_retained_first_four_evaluator_owner(
        plan, _config("OR_FAILURE_REV", "SHORT"))
    initial = owner.current_state()

    with pytest.raises(RecordError, match="exact proposed transitions"):
        drive_retained_first_four_evaluator_owner(owner, plan, Recorder(acknowledge=False))

    assert owner.current_state() == initial
    assert owner.confirm_recorded() == initial


def test_real_retained_unknowns_are_not_constructed_or_evaluated():
    for playbook, plan in zip(PLAYBOOKS, _plans()):
        result = execute_retained_first_four_evaluator_drive(
            plan, _config(playbook), Recorder())
        assert result.status == "UNAVAILABLE"
        assert result.evaluated_step_count == result.proposed_transition_count == 0
        assert result.acknowledged_transition_count == 0
        assert result.final_state is None
        assert result.missing_required_inputs


def test_changed_step_context_is_rejected_by_admission_before_evaluation():
    plan = _complete_plan("CRVOL_ORB5")
    step, = plan.steps
    request = step.confidence.request
    forged = replace(
        plan,
        steps=(replace(step, confidence=replace(
            step.confidence,
            request=replace(request, context=replace(request.context, symbol="OTHER")),
        )),),
    )
    result = execute_retained_first_four_evaluator_drive(
        forged, _config("CRVOL_ORB5"), Recorder())
    assert result.status == "UNAVAILABLE"
    assert "CONFIDENCE_IDENTITY_MISMATCH" in result.missing_required_inputs


def test_recorded_exact_context_drive_is_deterministic_and_keeps_release_off():
    rows = []
    recordings = []
    for playbook in PLAYBOOKS:
        for direction in ("LONG", "SHORT"):
            plan = _complete_plan(playbook, direction)
            recorder = Recorder()
            result = execute_retained_first_four_evaluator_drive(
                plan, _drive_config(plan, direction), recorder)
            rows.append({"direction": direction, **result.as_dict()})
            recordings.extend(
                transition.as_dict()
                for _at, transitions in recorder.rows
                for transition in transitions
            )
    canonical = json.dumps(
        {"results": rows, "recorded_transitions": recordings},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    recording = {
        "version": RUN_VERSION,
        "drive_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "results": rows,
        "recorded_transition_count": len(recordings),
        "all_transitions_acknowledged": all(
            row["proposed_transition_count"] == row["acknowledged_transition_count"]
            for row in rows
        ),
        "gap_dependent_rules": "OFF_UNTESTED",
        "exact_sample_released": False,
        "candidate_released": False,
        "live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dx-retained-first-four-evaluator-drive.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
