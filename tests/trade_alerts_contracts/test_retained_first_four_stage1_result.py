"""M9.1EC strict stage-1 result connection for retained outcomes."""

from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.playbook_outcome_evaluator import UnitExit
from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_outcome import run_retained_first_four_outcomes
from consensus_engine.retained_first_four_stage1_result import (
    RUN_VERSION, run_retained_first_four_stage1_results,
)
from consensus_engine.search_run_config import STAGE1_CANDIDATES
from consensus_engine.trade_alerts_models import RecordError, TargetOutcome
from test_playbook_outcome_evaluator import _evaluate
from test_retained_first_four_outcome import _filled, _orb5, _resolvers, _shared


def _candidates():
    return {playbook: STAGE1_CANDIDATES[playbook][0] for playbook in PLAYBOOKS}


def _resolved_shared(row):
    base = _shared(row)
    candidate = _candidates()[row.decision.playbook]
    sign = 1 if row.decision.direction == "LONG" else -1
    risk = 2.0
    exits = (
        UnitExit(1, "T1", "TARGET", row.fill.modeled_price + sign,
                 row.fill.window_end + timedelta(minutes=10)),
        UnitExit(2, "T2", "HORIZON", row.fill.modeled_price + sign * 2.0,
                 row.fill.window_end + timedelta(hours=6)),
    )
    return replace(
        base,
        outcome=replace(
            base.outcome,
            candidate_id=candidate.candidate_id,
            evaluated_at=exits[-1].at,
            coverage_status="COMPLETE",
            outcome_price=sum(exit.price for exit in exits) / len(exits),
            target_outcomes=(TargetOutcome("T1", True, exits[0].at),
                             TargetOutcome("T2", False, None)),
            result="RESOLVED",
            data_quality="VALID",
        ),
        status_reason="RESOLVED",
        actual_risk=risk,
        unit_exits=exits,
        resolved_r=sum(sign * (exit.price - row.fill.modeled_price)
                       for exit in exits) / (len(exits) * risk),
    )


def _resolved_orb5(row):
    base = _orb5(row)
    return replace(
        base,
        status="TARGET",
        reason=None,
        record=replace(base.record, status="TARGET", r_multiple=2.0, reason=None),
    )


def _outcomes(monkeypatch, *, shared_resolver=_resolved_shared,
              orb5_resolver=_resolved_orb5):
    resolvers = _resolvers([])
    resolvers["CRVOL_ORB5"] = orb5_resolver
    resolvers["OR_FAILURE_REV"] = shared_resolver
    return run_retained_first_four_outcomes(
        _filled(monkeypatch), resolvers=resolvers,
    )


def test_entry_cost_only_shared_and_orb5_outcomes_are_excluded(monkeypatch):
    result = run_retained_first_four_stage1_results(
        _outcomes(monkeypatch), candidates=_candidates(),
    )

    assert result.version == RUN_VERSION
    assert result.outcome_count == result.resolved_outcome_count == 1 + 1
    assert result.fully_costed_count == len(result.rows) == 0
    assert result.unresolved_excluded_count == 0
    assert result.incomplete_cost_excluded_count == 2
    assert result.unfilled_excluded_count == 0
    assert result.no_event_excluded_count == 2
    assert result.unavailable_excluded_count == 0
    assert result.rows == ()
    assert not any((result.result_shard_released, result.held_out_opened,
                    result.alert_released, result.live_action))


def test_unresolved_outcome_stays_counted_and_never_reaches_stage1(monkeypatch):
    result = run_retained_first_four_stage1_results(
        _outcomes(monkeypatch, shared_resolver=_shared), candidates=_candidates(),
    )
    assert result.outcome_count == 2
    assert result.resolved_outcome_count == 1
    assert result.fully_costed_count == 0
    assert result.unresolved_excluded_count == 1
    assert result.incomplete_cost_excluded_count == 1
    assert result.rows == ()


def test_rejects_wrong_candidate_held_out_name_or_opened_release(monkeypatch):
    outcomes = _outcomes(monkeypatch)
    candidates = _candidates()
    candidates["OR_FAILURE_REV"] = STAGE1_CANDIDATES["OR_FAILURE_REV"][1]
    with pytest.raises(RecordError, match="does not match the frozen"):
        run_retained_first_four_stage1_results(outcomes, candidates=candidates)

    first = outcomes.rows[0]
    held_out = replace(
        outcomes,
        rows=(replace(
            first,
            fill_row=replace(
                first.fill_row,
                decision=replace(first.fill_row.decision, ticker="GOOGL"),
            ),
        ), outcomes.rows[1]),
    )
    with pytest.raises(RecordError, match="frozen training boundary"):
        run_retained_first_four_stage1_results(held_out, candidates=_candidates())

    with pytest.raises(RecordError, match="later release"):
        run_retained_first_four_stage1_results(
            replace(outcomes, result_shard_released=True), candidates=_candidates(),
        )


def test_rejects_resolved_input_outside_retained_session(monkeypatch):
    outcomes = _outcomes(monkeypatch)
    shared_row = outcomes.rows[1]
    changed_outcome = replace(
        shared_row.outcome,
        outcome=replace(
            shared_row.outcome.outcome,
            input_record_ids=(
                *shared_row.outcome.outcome.input_record_ids,
                "foreign:outcome",
            ),
        ),
    )
    changed = replace(
        outcomes,
        rows=(outcomes.rows[0], replace(shared_row, outcome=changed_outcome)),
    )

    with pytest.raises(RecordError, match="outside the retained session"):
        run_retained_first_four_stage1_results(
            changed, candidates=_candidates(),
        )


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_actual_shared_evaluator_return_stays_incomplete_cost(monkeypatch, direction):
    outcomes = _outcomes(monkeypatch)
    shared = outcomes.rows[1]
    evaluated = _evaluate(direction=direction, strategy_id="OR_FAILURE_REV")
    evaluated = replace(evaluated, outcome=replace(
        evaluated.outcome, candidate_id=_candidates()["OR_FAILURE_REV"].candidate_id))
    decision = replace(
        shared.fill_row.decision, direction=direction,
        retained_source_record_ids=tuple(dict.fromkeys((
            *shared.fill_row.decision.retained_source_record_ids,
            *evaluated.outcome.input_record_ids))),
    )
    shared = replace(shared, fill_row=replace(
        shared.fill_row, decision=decision, fill=evaluated.fill), outcome=evaluated)
    result = run_retained_first_four_stage1_results(
        replace(outcomes, rows=(outcomes.rows[0], shared)), candidates=_candidates())
    assert result.rows == ()
    assert result.resolved_outcome_count == result.incomplete_cost_excluded_count == 2


@pytest.mark.parametrize("change", (
    "return", "return_nan", "risk", "risk_nan", "entry", "direction",
    "exit_price", "exit_nan", "exit_missing", "exit_duplicate", "exit_unit",
    "exit_before_fill", "exit_after_evaluation", "exit_order", "exit_reason",
    "exit_target", "average_exit",
))
def test_rejects_mismatched_return_or_exits_before_cost_exclusion(monkeypatch, change):
    outcomes = _outcomes(monkeypatch)
    shared = outcomes.rows[1]
    outcome = shared.outcome
    first, second = outcome.unit_exits
    if change == "return":
        outcome = replace(outcome, resolved_r=1.5)
    elif change == "return_nan":
        outcome = replace(outcome, resolved_r=float("nan"))
    elif change == "risk":
        outcome = replace(outcome, actual_risk=outcome.actual_risk * 2)
    elif change == "risk_nan":
        outcome = replace(outcome, actual_risk=float("nan"))
    elif change == "entry":
        outcome = replace(outcome, outcome=replace(
            outcome.outcome, modeled_entry_price=outcome.fill.modeled_price + 1))
    elif change == "direction":
        shared = replace(shared, fill_row=replace(shared.fill_row, decision=replace(
            shared.fill_row.decision,
            direction="SHORT" if shared.fill_row.decision.direction == "LONG" else "LONG")))
    elif change == "average_exit":
        outcome = replace(outcome, outcome=replace(
            outcome.outcome, outcome_price=outcome.outcome.outcome_price + 1))
    else:
        exits = {
            "exit_price": (replace(first, price=first.price + 1), second),
            "exit_nan": (replace(first, price=float("nan")), second),
            "exit_missing": (first,),
            "exit_duplicate": (first, first),
            "exit_unit": (first, replace(second, unit=3)),
            "exit_before_fill": (replace(first, at=outcome.fill.trade_print_time
                                        - timedelta(seconds=1)), second),
            "exit_after_evaluation": (first, replace(second, at=outcome.outcome.evaluated_at
                                                     + timedelta(seconds=1))),
            "exit_order": (replace(first, at=second.at), replace(second, at=first.at)),
            "exit_reason": (replace(first, reason="INVENTED"), second),
            "exit_target": (replace(first, target_name="FOREIGN"), second),
        }
        outcome = replace(outcome, unit_exits=exits[change])
    changed = replace(outcomes, rows=(outcomes.rows[0], replace(shared, outcome=outcome)))
    with pytest.raises(RecordError, match="resolved (return|R)"):
        run_retained_first_four_stage1_results(changed, candidates=_candidates())


def test_recorded_stage1_result_connection_is_deterministic_and_keeps_release_off(monkeypatch):
    result = run_retained_first_four_stage1_results(
        _outcomes(monkeypatch), candidates=_candidates(),
    )
    payload = result.as_dict()
    assert payload["rows"] == []
    assert payload["fully_costed_count"] == 0
    assert payload["incomplete_cost_excluded_count"] == payload["resolved_outcome_count"] == 2
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "stage1_result_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "result": payload,
        "all_resolved_entry_cost_only_outcomes_excluded": result.rows == (),
        "unresolved_and_excluded_counts_preserved": True,
        "gap_dependent_rules": "OFF_UNTESTED",
        "result_shard_released": False,
        "held_out_opened": False,
        "alert_or_live_action": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91ec-retained-first-four-stage1-result.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert json.loads(output.read_text()) == recording
