"""M9.1DY retained first-four evaluator-sample restart contracts."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_candidate_events import CandidateEventInput
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_sample_restart import (
    RUN_VERSION,
    restart_retained_first_four_sample,
)
from consensus_engine.search_run_config import HELD_OUT_TICKERS
from consensus_engine.trade_alerts_models import RecordError
from test_retained_first_four_evaluator_drive import Recorder, _drive_config
from test_retained_first_four_owner_inputs import _complete_plan
from test_retained_first_two_producers import _input


def _unavailable_inputs():
    return tuple(_input(playbook) for playbook in PLAYBOOKS)


def _planned(values):
    return tuple(dict.fromkeys((value.ticker, value.session) for value in values))


def _complete_input(playbook, direction):
    plan = _complete_plan(playbook, direction)
    base = _input(playbook)
    return CandidateEventInput(
        playbook,
        base.ticker,
        base.session,
        tuple(step.evaluated_at for step in plan.steps),
        base.history,
        base.trades,
        base.quotes,
        plan.retained_source_record_ids,
        base.disabled_rules,
    ), plan


def _complete_sample():
    values = []
    configs = {}
    recorders = {}
    plans = {}
    for index, playbook in enumerate(PLAYBOOKS):
        direction = ("LONG", "SHORT")[index % 2]
        value, plan = _complete_input(playbook, direction)
        key = (value.playbook, value.ticker, value.session)
        values.append(value)
        plans[key] = plan
        configs[key] = _drive_config(plan, direction)
        recorders[key] = Recorder()
    return tuple(values), plans, configs, recorders


def _restart_complete(values, plans, configs, recorders, monkeypatch):
    from consensus_engine import retained_first_four_sample_restart as module

    monkeypatch.setattr(
        module,
        "build_retained_first_four_evaluator_plan",
        lambda value: plans[(value.playbook, value.ticker, value.session)],
    )
    return restart_retained_first_four_sample(
        values, planned_sessions=_planned(values),
        owner_configs=configs, recorders=recorders,
    )


def test_real_retained_unknowns_restart_unavailable_without_invented_dependencies():
    values = _unavailable_inputs()
    result = restart_retained_first_four_sample(
        tuple(reversed(values)), planned_sessions=_planned(values),
    )

    assert result.version == RUN_VERSION
    assert result.status == "UNAVAILABLE"
    assert tuple(row.playbook for row in result.rows) == PLAYBOOKS
    assert all(row.result.status == "UNAVAILABLE" for row in result.rows)
    assert result.evaluated_step_count == 0
    assert result.proposed_transition_count == result.acknowledged_transition_count == 0
    assert all(row.result.missing_required_inputs for row in result.rows)
    assert not any((result.candidate_released, result.fill_calculated,
                    result.return_calculated, result.result_shard_released,
                    result.held_out_opened))


def test_complete_sample_uses_only_fully_acknowledged_evaluator_results(monkeypatch):
    values, plans, configs, recorders = _complete_sample()
    result = _restart_complete(values, plans, configs, recorders, monkeypatch)

    assert result.status == "EVALUATED"
    assert len(result.rows) == 4
    assert result.evaluated_step_count == 4
    assert result.proposed_transition_count > 0
    assert result.proposed_transition_count == result.acknowledged_transition_count
    assert all(row.result.status == "EVALUATED" for row in result.rows)
    assert not result.candidate_released


def test_changed_recording_acknowledgment_stops_before_sample_result(monkeypatch):
    values, plans, configs, recorders = _complete_sample()
    bad_key = next(iter(recorders))
    recorders[bad_key] = Recorder(acknowledge=False)

    with pytest.raises(RecordError, match="exact proposed transitions"):
        _restart_complete(values, plans, configs, recorders, monkeypatch)


def test_ready_plan_requires_exact_dependency_keys_before_any_drive(monkeypatch):
    values, plans, configs, recorders = _complete_sample()
    key = next(iter(configs))
    configs.pop(key)

    with pytest.raises(RecordError, match="exact owner config and recorder keys"):
        _restart_complete(values, plans, configs, recorders, monkeypatch)
    assert all(recorder.rows == [] for recorder in recorders.values())


def test_duplicate_or_held_out_scope_is_rejected():
    values = _unavailable_inputs()
    value = values[0]
    with pytest.raises(RecordError, match="unique playbook sessions"):
        restart_retained_first_four_sample(
            (value, value), planned_sessions=((value.ticker, value.session),),
        )
    with pytest.raises(RecordError, match="exactly cover every planned"):
        restart_retained_first_four_sample(
            values[:-1], planned_sessions=_planned(values),
        )

    held_out = replace(value, ticker=HELD_OUT_TICKERS[0])
    with pytest.raises(RecordError, match="held-out ticker"):
        restart_retained_first_four_sample(
            (held_out,), planned_sessions=((held_out.ticker, held_out.session),),
        )


def test_recorded_sample_restart_is_deterministic_and_keeps_later_release_off(
    monkeypatch,
):
    unavailable_values = _unavailable_inputs()
    unavailable = restart_retained_first_four_sample(
        unavailable_values, planned_sessions=_planned(unavailable_values),
    )
    values, plans, configs, recorders = _complete_sample()
    evaluated = _restart_complete(values, plans, configs, recorders, monkeypatch)
    full = {"unavailable": unavailable.as_dict(), "evaluated": evaluated.as_dict()}
    canonical = json.dumps(full, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "sample_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "results": full,
        "all_evaluated_transitions_acknowledged": (
            evaluated.proposed_transition_count
            == evaluated.acknowledged_transition_count
        ),
        "gap_dependent_rules": "OFF_UNTESTED",
        "candidate_released": False,
        "fill_calculated": False,
        "return_calculated": False,
        "result_shard_released": False,
        "held_out_opened": False,
        "live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dy-retained-first-four-sample-restart.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
