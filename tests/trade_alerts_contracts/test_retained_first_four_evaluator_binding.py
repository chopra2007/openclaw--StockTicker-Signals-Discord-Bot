"""M9.1DZ exact evaluator-result to retained-decision binding contracts."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_candidate_events import RetainedCandidateEvent
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_evaluator_binding import (
    RUN_VERSION,
    bind_retained_first_four_evaluator_results,
)
from consensus_engine.retained_first_four_sample_restart import (
    restart_retained_first_four_sample,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_first_four_sample_restart import (
    _complete_sample,
    _planned,
    _restart_complete,
    _unavailable_inputs,
)


def _event(value, result, status="UNAVAILABLE"):
    candidate = status == "CANDIDATE"
    evidence = status in ("CANDIDATE", "NO_EVENT")
    return RetainedCandidateEvent(
        "SYNTHETIC_ACCEPTED_EVENT_V1",
        value.playbook,
        value.ticker,
        value.session,
        status,
        "SYNTHETIC_ACCEPTED_PRODUCER_V1",
        "TRIGGERED" if candidate else status,
        value.decision_moments[0] if candidate else None,
        "LONG" if candidate else None,
        result.retained_source_record_ids[:1] if evidence else (),
        result.retained_source_record_ids,
        value.disabled_rules,
    )


def _unavailable_binding():
    values = _unavailable_inputs()
    restart = restart_retained_first_four_sample(
        values, planned_sessions=_planned(values),
    )
    events = tuple(_event(value, row.result) for value, row in zip(values, restart.rows))
    return values, events, restart


def _evaluated_binding(monkeypatch):
    values, plans, configs, recorders = _complete_sample()
    restart = _restart_complete(values, plans, configs, recorders, monkeypatch)
    statuses = ("CANDIDATE", "NO_EVENT", "CANDIDATE", "NO_EVENT")
    events = tuple(
        _event(value, row.result, status)
        for value, row, status in zip(values, restart.rows, statuses)
    )
    return values, events, restart


def test_real_unknowns_bind_only_to_exact_unavailable_records():
    _values, events, restart = _unavailable_binding()
    result = bind_retained_first_four_evaluator_results(tuple(reversed(events)), restart)

    assert result.version == RUN_VERSION
    assert tuple(row.playbook for row in result.rows) == PLAYBOOKS
    assert result.candidate_count == result.no_event_count == 0
    assert result.unavailable_count == len(PLAYBOOKS)
    assert all(row.evaluator_result.status == "UNAVAILABLE" for row in result.rows)
    assert all(row.evaluator_result.missing_required_inputs for row in result.rows)
    assert not any((result.candidate_released, result.fill_calculated,
                    result.return_calculated, result.result_shard_released,
                    result.held_out_opened))


def test_candidate_and_no_event_records_require_fully_acknowledged_results(monkeypatch):
    _values, events, restart = _evaluated_binding(monkeypatch)
    result = bind_retained_first_four_evaluator_results(events, restart)

    assert result.candidate_count == result.no_event_count == 2
    assert result.unavailable_count == 0
    assert all(row.evaluator_result.status == "EVALUATED" for row in result.rows)
    assert all(
        row.evaluator_result.proposed_transition_count
        == row.evaluator_result.acknowledged_transition_count
        for row in result.rows
    )


def test_refuses_missing_duplicate_or_cross_session_decision_binding():
    _values, events, restart = _unavailable_binding()
    with pytest.raises(RecordError, match="exactly match"):
        bind_retained_first_four_evaluator_results(events[:-1], restart)
    with pytest.raises(RecordError, match="exactly match"):
        bind_retained_first_four_evaluator_results((events[0], *events[:-1]), restart)
    changed = replace(events[0], retained_source_record_ids=("foreign",))
    with pytest.raises(RecordError, match="source identities"):
        bind_retained_first_four_evaluator_results((changed, *events[1:]), restart)


def test_refuses_forged_acknowledgment_status_or_open_release(monkeypatch):
    _values, events, restart = _evaluated_binding(monkeypatch)
    row = restart.rows[0]
    unacknowledged = replace(
        row,
        result=replace(
            row.result,
            acknowledged_transition_count=row.result.acknowledged_transition_count - 1,
        ),
    )
    forged = replace(restart, rows=(unacknowledged, *restart.rows[1:]))
    with pytest.raises(RecordError, match="fully acknowledged"):
        bind_retained_first_four_evaluator_results(events, forged)

    unavailable = replace(events[0], status="UNAVAILABLE", alerted_at=None,
                          direction=None, input_record_ids=())
    with pytest.raises(RecordError, match="does not match"):
        bind_retained_first_four_evaluator_results((unavailable, *events[1:]), restart)

    with pytest.raises(RecordError, match="opened a later release"):
        bind_retained_first_four_evaluator_results(
            events, replace(restart, result_shard_released=True),
        )


def test_recorded_evaluator_binding_is_deterministic_and_keeps_later_release_off(
    monkeypatch,
):
    _unavailable_values, unavailable_events, unavailable_restart = _unavailable_binding()
    unavailable = bind_retained_first_four_evaluator_results(
        unavailable_events, unavailable_restart,
    )
    _values, events, restart = _evaluated_binding(monkeypatch)
    evaluated = bind_retained_first_four_evaluator_results(events, restart)
    full = {"unavailable": unavailable.as_dict(), "evaluated": evaluated.as_dict()}
    canonical = json.dumps(full, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "binding_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "results": full,
        "all_evaluated_transitions_acknowledged": all(
            row.evaluator_result.proposed_transition_count
            == row.evaluator_result.acknowledged_transition_count
            for row in evaluated.rows
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
    output = Path(os.environ["TMPDIR"], "m91dz-retained-first-four-evaluator-binding.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
