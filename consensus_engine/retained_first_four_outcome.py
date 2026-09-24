"""M9.1EB filled-candidate connection to accepted offline outcomes.

Only rows with an exact D-106/D-107 fill reach a caller-supplied accepted
outcome evaluator.  Unfilled candidates and earlier no-event or unavailable
decisions remain counted exclusions.  This boundary does not release a result
shard, open held-out names, send an alert, or perform a live action.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from typing import Callable, Mapping

from .orb5_trade_walk import Orb5QuoteFilledRecord
from .playbook_outcome_evaluator import PlaybookOutcomeEvaluation
from .retained_decision_moments import PLAYBOOKS
from .retained_first_four_fill import (
    RUN_VERSION as FILL_VERSION,
    RetainedFirstFourFillRow,
    RetainedFirstFourFillRun,
)
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

RUN_VERSION = "M91EB_RETAINED_FIRST_FOUR_OUTCOME_V1"
AcceptedOutcome = Orb5QuoteFilledRecord | PlaybookOutcomeEvaluation
OutcomeResolver = Callable[[RetainedFirstFourFillRow], AcceptedOutcome]


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return as_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RecordError(f"unsupported outcome value: {type(value).__name__}")


@dataclass(frozen=True)
class RetainedFirstFourOutcomeRow:
    fill_row: RetainedFirstFourFillRow
    outcome: AcceptedOutcome

    def as_dict(self) -> dict[str, object]:
        return {
            "fill_row": self.fill_row.as_dict(),
            "outcome_type": type(self.outcome).__name__,
            "outcome": _jsonable(self.outcome),
        }


@dataclass(frozen=True)
class RetainedFirstFourOutcomeRun:
    version: str
    fill_version: str
    rows: tuple[RetainedFirstFourOutcomeRow, ...]
    filled_candidate_count: int
    outcome_count: int
    resolved_return_count: int
    unfilled_excluded_count: int
    no_event_excluded_count: int
    unavailable_excluded_count: int
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "fill_version": self.fill_version,
            "rows": [row.as_dict() for row in self.rows],
            "filled_candidate_count": self.filled_candidate_count,
            "outcome_count": self.outcome_count,
            "resolved_return_count": self.resolved_return_count,
            "unfilled_excluded_count": self.unfilled_excluded_count,
            "no_event_excluded_count": self.no_event_excluded_count,
            "unavailable_excluded_count": self.unavailable_excluded_count,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _validate_fill_run(run: RetainedFirstFourFillRun) -> None:
    if type(run) is not RetainedFirstFourFillRun or run.version != FILL_VERSION:
        raise RecordError("outcome connection requires the accepted fill run")
    if any((run.return_calculated, run.result_shard_released, run.held_out_opened)):
        raise RecordError("fill run opened a later release boundary")
    if (run.candidate_count != len(run.rows)
            or run.filled_count != sum(row.fill.status == "FILLED" for row in run.rows)
            or run.unfilled_count != sum(row.fill.status != "FILLED" for row in run.rows)):
        raise RecordError("fill run counts do not match its rows")


def _validate_outcome(row: RetainedFirstFourFillRow, outcome: object) -> AcceptedOutcome:
    decision = row.decision
    if decision.playbook == "CRVOL_ORB5":
        if type(outcome) is not Orb5QuoteFilledRecord:
            raise RecordError("CRVOL_ORB5 requires its accepted offline outcome type")
        if outcome.fill != row.fill:
            raise RecordError("ORB5 outcome does not preserve the exact accepted fill")
        candidate = outcome.record.candidate
        if candidate is None or candidate.direction != decision.direction:
            raise RecordError("ORB5 outcome does not match the filled decision")
        input_ids = row.fill.input_record_ids + candidate.input_record_ids
    else:
        if type(outcome) is not PlaybookOutcomeEvaluation:
            raise RecordError("non-ORB5 playbook requires the shared accepted outcome type")
        if outcome.fill != row.fill:
            raise RecordError("playbook outcome does not preserve the exact accepted fill")
        input_ids = outcome.outcome.input_record_ids
    if not set(input_ids).issubset(decision.retained_source_record_ids):
        raise RecordError("outcome cites a record outside the retained candidate session")
    return outcome


def run_retained_first_four_outcomes(
    fill_run: RetainedFirstFourFillRun,
    *,
    resolvers: Mapping[str, OutcomeResolver],
) -> RetainedFirstFourOutcomeRun:
    """Evaluate only filled candidate rows through accepted offline boundaries."""
    _validate_fill_run(fill_run)
    if not isinstance(resolvers, Mapping) or set(resolvers) != set(PLAYBOOKS):
        raise RecordError("outcome resolvers must name exactly the first four playbooks")
    if any(not callable(resolver) for resolver in resolvers.values()):
        raise RecordError("every outcome resolver must be callable")

    output: list[RetainedFirstFourOutcomeRow] = []
    for row in fill_run.rows:
        if row.fill.status != "FILLED":
            continue
        outcome = _validate_outcome(row, resolvers[row.decision.playbook](row))
        output.append(RetainedFirstFourOutcomeRow(row, outcome))

    rows = tuple(output)
    resolved = sum(
        (item.outcome.record.resolved if isinstance(item.outcome, Orb5QuoteFilledRecord)
         else item.outcome.resolved_r is not None)
        for item in rows
    )
    return RetainedFirstFourOutcomeRun(
        RUN_VERSION,
        fill_run.version,
        rows,
        fill_run.filled_count,
        len(rows),
        resolved,
        fill_run.unfilled_count,
        fill_run.no_event_excluded_count,
        fill_run.unavailable_excluded_count,
    )


__all__ = [
    "AcceptedOutcome", "OutcomeResolver", "RUN_VERSION",
    "RetainedFirstFourOutcomeRow", "RetainedFirstFourOutcomeRun",
    "run_retained_first_four_outcomes",
]
