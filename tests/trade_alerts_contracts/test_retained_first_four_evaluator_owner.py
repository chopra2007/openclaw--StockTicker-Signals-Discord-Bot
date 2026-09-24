"""M9.1DW construction contracts for retained first-four evaluator owners."""

from dataclasses import replace
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_evaluator_owner import (
    RUN_VERSION,
    RetainedFirstFourOwnerConfig,
    construct_retained_first_four_evaluator_owner,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_first_four_owner_inputs import _complete_plan, _plans
def _config(playbook, direction="LONG"):
    from test_first_pullback_vwap_replay import (
        FROZEN, STARTED, MEASURE_LONG, MEASURE_SHORT, pullback_policy,
    )
    from test_hod_comp_rs_replay import (
        eligibility_policy as hod_eligibility,
        suppression_policy,
        trigger_policy as hod_trigger,
    )
    from test_or_failure_rev_replay import reversal_policy
    from test_orb5_replay import eligibility_policy as orb_eligibility, trigger_policy as orb_trigger
    from consensus_engine.orb5_trigger import TAPE

    policies = {
        "CRVOL_ORB5": (orb_eligibility(), orb_trigger(TAPE)),
        "HOD_COMP_RS": (hod_eligibility(), hod_trigger(TAPE), suppression_policy()),
        "OR_FAILURE_REV": (reversal_policy(),),
        "FIRST_PULLBACK_VWAP": (
            pullback_policy(direction), MEASURE_LONG if direction == "LONG" else MEASURE_SHORT),
    }[playbook]
    window = (STARTED, FROZEN) if playbook == "FIRST_PULLBACK_VWAP" else None
    return RetainedFirstFourOwnerConfig(
        "M91DW_SYNTHETIC_V1", RUN_VERSION, "m91dw-owner", policies, window)


@pytest.mark.parametrize("playbook", PLAYBOOKS)
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_complete_admitted_inputs_construct_the_exact_canonical_owner(playbook, direction):
    plan = _complete_plan(playbook, direction)
    owner = construct_retained_first_four_evaluator_owner(plan, _config(playbook, direction))
    assert type(owner).__name__ == plan.evaluator_type
    assert owner.strategy_id == playbook
    assert owner.current_state() == owner.rules.initial_state


@pytest.mark.parametrize("playbook", PLAYBOOKS)
def test_real_retained_unknowns_construct_no_owner(playbook):
    plan = dict(zip(PLAYBOOKS, _plans()))[playbook]
    with pytest.raises(RecordError, match="admitted complete inputs"):
        construct_retained_first_four_evaluator_owner(plan, _config(playbook))


def test_mismatched_policy_and_impulse_window_fail_closed():
    plan = _complete_plan("CRVOL_ORB5")
    with pytest.raises(RecordError, match="policies do not match"):
        construct_retained_first_four_evaluator_owner(
            plan, replace(_config("CRVOL_ORB5"), policies=()))

    pullback = _complete_plan("FIRST_PULLBACK_VWAP")
    with pytest.raises(RecordError, match="impulse window"):
        construct_retained_first_four_evaluator_owner(
            pullback, replace(_config("FIRST_PULLBACK_VWAP"), impulse_window=None))


def test_recorded_owner_construction_is_deterministic_and_does_not_advance():
    rows = []
    for playbook in PLAYBOOKS:
        for direction in ("LONG", "SHORT"):
            owner = construct_retained_first_four_evaluator_owner(
                _complete_plan(playbook, direction), _config(playbook, direction))
            rows.append({
                "playbook": playbook,
                "direction": direction,
                "owner_type": type(owner).__name__,
                "initial_state": owner.current_state().__dict__,
                "required_data": [row.__dict__ for row in owner.required_data()],
            })
    recording = {
        "version": RUN_VERSION,
        "owners": rows,
        "owner_count": len(rows),
        "evaluated_steps": 0,
        "confirmed_transitions": 0,
        "gap_dependent_rules": "OFF_UNTESTED",
        "exact_sample_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dw-retained-first-four-evaluator-owners.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
