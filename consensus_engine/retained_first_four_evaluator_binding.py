"""M9.1DZ binding from acknowledged evaluator results to retained decisions.

The boundary accepts only an exact one-to-one match between the restarted
first-four sample and its candidate, no-event, or unavailable records.  It
does not calculate fills, returns, result shards, or held-out results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_candidate_events import DECISION_STATUSES, RetainedCandidateEvent
from .retained_first_four_evaluator_drive import RetainedFirstFourDriveResult
from .retained_first_four_sample_restart import (
    RUN_VERSION as RESTART_VERSION,
    RetainedFirstFourSampleRestart,
    RetainedFirstFourSampleRow,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91DZ_RETAINED_FIRST_FOUR_EVALUATOR_BINDING_V1"
BindingKey = tuple[str, str, str]


@dataclass(frozen=True)
class RetainedFirstFourBoundDecision:
    """One exact retained decision and its acknowledged evaluator result."""

    playbook: str
    ticker: str
    session: str
    status: str
    producer_version: str
    reason: str
    alerted_at: datetime | None
    direction: str | None
    input_record_ids: tuple[str, ...]
    retained_source_record_ids: tuple[str, ...]
    disabled_rules: tuple[str, ...]
    evaluator_result: RetainedFirstFourDriveResult

    def as_dict(self) -> dict[str, object]:
        return {
            "playbook": self.playbook,
            "ticker": self.ticker,
            "session": self.session,
            "status": self.status,
            "producer_version": self.producer_version,
            "reason": self.reason,
            "alerted_at": None if self.alerted_at is None else self.alerted_at.isoformat(),
            "direction": self.direction,
            "input_record_ids": list(self.input_record_ids),
            "retained_source_record_ids": list(self.retained_source_record_ids),
            "disabled_rules": list(self.disabled_rules),
            "evaluator_result": self.evaluator_result.as_dict(),
        }


@dataclass(frozen=True)
class RetainedFirstFourEvaluatorBinding:
    """Exact evaluator/decision bindings with every later boundary sealed."""

    version: str
    restart_version: str
    rows: tuple[RetainedFirstFourBoundDecision, ...]
    candidate_count: int
    no_event_count: int
    unavailable_count: int
    candidate_released: bool = False
    fill_calculated: bool = False
    return_calculated: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "restart_version": self.restart_version,
            "rows": [row.as_dict() for row in self.rows],
            "candidate_count": self.candidate_count,
            "no_event_count": self.no_event_count,
            "unavailable_count": self.unavailable_count,
            "candidate_released": self.candidate_released,
            "fill_calculated": self.fill_calculated,
            "return_calculated": self.return_calculated,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
        }


def _key(value: RetainedCandidateEvent | RetainedFirstFourSampleRow) -> BindingKey:
    return value.playbook, value.ticker, value.session


def _validate_result(row: RetainedFirstFourSampleRow) -> None:
    result = row.result
    if result.playbook != row.playbook:
        raise RecordError("evaluator result does not match its sample playbook")
    if result.status == "EVALUATED":
        if (result.evaluated_step_count < 1
                or result.proposed_transition_count < 0
                or result.proposed_transition_count != result.acknowledged_transition_count
                or result.final_state is None
                or result.missing_required_inputs):
            raise RecordError("evaluated decisions require a fully acknowledged evaluator result")
    elif result.status == "UNAVAILABLE":
        if (result.evaluated_step_count != 0
                or result.proposed_transition_count != 0
                or result.acknowledged_transition_count != 0
                or result.final_state is not None
                or not result.missing_required_inputs):
            raise RecordError("unavailable decisions require an untouched unavailable evaluator")
    else:
        raise RecordError("evaluator result status is unsupported")


def _validate_restart(restart: RetainedFirstFourSampleRestart) -> None:
    if type(restart) is not RetainedFirstFourSampleRestart or restart.version != RESTART_VERSION:
        raise RecordError("binding requires the accepted sample restart")
    if any((restart.candidate_released, restart.fill_calculated,
            restart.return_calculated, restart.result_shard_released,
            restart.held_out_opened)):
        raise RecordError("sample restart opened a later release boundary")
    keys = tuple(_key(row) for row in restart.rows)
    expected = tuple(
        (playbook, ticker, session)
        for ticker, session in restart.planned_sessions
        for playbook in ("CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP")
    )
    if not keys or keys != expected or len(set(keys)) != len(keys):
        raise RecordError("sample restart rows do not match its exact planned sessions")
    for row in restart.rows:
        _validate_result(row)
    results = tuple(row.result for row in restart.rows)
    expected_status = "EVALUATED" if all(row.status == "EVALUATED" for row in results) else "UNAVAILABLE"
    if (restart.status != expected_status
            or restart.evaluated_step_count != sum(row.evaluated_step_count for row in results)
            or restart.proposed_transition_count != sum(row.proposed_transition_count for row in results)
            or restart.acknowledged_transition_count
            != sum(row.acknowledged_transition_count for row in results)):
        raise RecordError("sample restart summary does not match its evaluator results")


def bind_retained_first_four_evaluator_results(
    events: Sequence[RetainedCandidateEvent],
    restart: RetainedFirstFourSampleRestart,
) -> RetainedFirstFourEvaluatorBinding:
    """Bind exact retained decisions only to matching acknowledged results."""
    _validate_restart(restart)
    supplied = tuple(events)
    if any(type(event) is not RetainedCandidateEvent for event in supplied):
        raise RecordError("binding requires retained candidate-event records")
    event_keys = tuple(_key(event) for event in supplied)
    result_keys = tuple(_key(row) for row in restart.rows)
    if len(set(event_keys)) != len(event_keys) or set(event_keys) != set(result_keys):
        raise RecordError("decisions must exactly match the restarted playbook sessions")
    by_key = dict(zip(event_keys, supplied))

    bound: list[RetainedFirstFourBoundDecision] = []
    for sample_row in restart.rows:
        event = by_key[_key(sample_row)]
        result = sample_row.result
        if event.status not in DECISION_STATUSES:
            raise RecordError("retained decision status is unsupported")
        if not event.producer_version.strip() or not event.reason.strip():
            raise RecordError("retained decision version and reason are required")
        if event.disabled_rules != REQUIRED_DISABLED_RULES:
            raise RecordError("binding must preserve all source-gap disabled rules")
        if event.retained_source_record_ids != result.retained_source_record_ids:
            raise RecordError("decision and evaluator source identities do not match")
        if (len(set(event.input_record_ids)) != len(event.input_record_ids)
                or not set(event.input_record_ids).issubset(event.retained_source_record_ids)):
            raise RecordError("decision input identities must stay inside the retained session")
        if event.status == "UNAVAILABLE":
            if (result.status != "UNAVAILABLE"
                    or event.alerted_at is not None or event.direction is not None):
                raise RecordError("unavailable decision does not match its evaluator result")
        else:
            if result.status != "EVALUATED":
                raise RecordError("candidate and no-event decisions require evaluated results")
            if event.status == "CANDIDATE":
                if (event.alerted_at is None or event.direction not in ("LONG", "SHORT")
                        or not event.input_record_ids
                        or result.proposed_transition_count < 1):
                    raise RecordError("candidate decision is incomplete")
            elif event.alerted_at is not None or event.direction is not None:
                raise RecordError("no-event decision cannot carry a candidate")
        bound.append(RetainedFirstFourBoundDecision(
            event.playbook, event.ticker, event.session, event.status,
            event.producer_version, event.reason, event.alerted_at, event.direction,
            event.input_record_ids, event.retained_source_record_ids,
            event.disabled_rules, result,
        ))

    rows = tuple(bound)
    return RetainedFirstFourEvaluatorBinding(
        RUN_VERSION,
        restart.version,
        rows,
        sum(row.status == "CANDIDATE" for row in rows),
        sum(row.status == "NO_EVENT" for row in rows),
        sum(row.status == "UNAVAILABLE" for row in rows),
    )


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourBoundDecision",
    "RetainedFirstFourEvaluatorBinding",
    "bind_retained_first_four_evaluator_results",
]
