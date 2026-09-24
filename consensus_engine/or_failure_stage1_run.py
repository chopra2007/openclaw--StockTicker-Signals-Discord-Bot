"""M9.1CE: connect the confirmed OR-failure runner to stage-1 measurement.

The caller supplies retained nine-name histories and already-built reversal
requests plus the D-106/D-107 trade and quote records.  This module runs the
existing OR-failure assessment, evaluates each triggered outcome on its matched
retained session, and sends only resolved, modeled-cost rows to the strict
stage-1 measurement boundary.  Missing quotes, incomplete paths and other
unresolved outcomes stay visible in ``excluded``; they are never filled in.
Every retained session needs an assessment request or an explicit no-event or
unavailable disposition. History presence alone is not evaluation coverage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .fill_cost_model import FillCostPolicy
from .or_failure_rev import MINUTE_CLOSE_CONFIRMATION, ReversalRequest, evaluate_or_failure_rev
from .playbook_outcome_evaluator import evaluate_playbook_outcome
from .retained_history_batches import RetainedHistoryBatches, SessionHistory
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import (
    ResolvedTrainingTrade, Stage1TrainingMeasurement, measure_stage1_candidate,
)
from .trade_alerts_models import Quote, RecordError

RUN_VERSION = "M91CE_OR_FAILURE_STAGE1_RUN_V2"
PLAYBOOK = "OR_FAILURE_REV"
CONFIRMED_CANDIDATE = STAGE1_CANDIDATES[PLAYBOOK][0]


@dataclass(frozen=True)
class OrFailureTrainingEvent:
    ticker: str
    session: str
    request: ReversalRequest
    trades: tuple[Quote, ...]
    quotes: tuple[Quote, ...]


@dataclass(frozen=True)
class ExcludedTrainingEvent:
    ticker: str
    session: str
    direction: str
    reason: str


@dataclass(frozen=True)
class SessionWithoutEvent:
    """Caller-supplied scan result for this candidate on one retained session.

    NO_EVENT means the candidate scan completed without a reversal request;
    UNAVAILABLE means it could not complete and prevents a ranked measurement.
    Neither may be inferred just from the existence of retained bars.
    """

    ticker: str
    session: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in ("NO_EVENT", "UNAVAILABLE"):
            raise RecordError("session disposition must be NO_EVENT or UNAVAILABLE")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise RecordError("session disposition needs an explicit reason")


@dataclass(frozen=True)
class OrFailureStage1Run:
    version: str
    candidate_id: str
    measurement: Stage1TrainingMeasurement | None
    resolved: tuple[ResolvedTrainingTrade, ...]
    excluded: tuple[ExcludedTrainingEvent, ...]
    evaluated_sessions: tuple[tuple[str, str], ...]


def _histories_by_key(retained: RetainedHistoryBatches) -> dict[tuple[str, str], SessionHistory]:
    if not isinstance(retained, RetainedHistoryBatches):
        raise RecordError("retained histories are required")
    tickers = {row.ticker for row in retained.histories}
    if tickers != set(TRAINING_TICKERS):
        raise RecordError("retained stage 1 must contain exactly the nine training names")
    rows: dict[tuple[str, str], SessionHistory] = {}
    for row in retained.histories:
        key = (row.ticker, row.session)
        if key in rows:
            raise RecordError("duplicate retained training session")
        if row.batch.request.symbol != row.ticker:
            raise RecordError("retained history symbol does not match its ticker")
        rows[key] = row
    return rows


def run_confirmed_or_failure_stage1(
    *, retained: RetainedHistoryBatches, candidate: Candidate,
    events: Sequence[OrFailureTrainingEvent], fill_policy: FillCostPolicy,
    sessions_without_events: Sequence[SessionWithoutEvent] = (),
    disabled_rules: tuple[str, ...] = (),
) -> OrFailureStage1Run:
    """Measure the frozen CONFIRMED candidate without opening held-out data.

    Incomplete scans or no resolved trades return exclusions with no measurement.
    Missing coverage declarations and mismatched record identities are errors.
    """
    if candidate != CONFIRMED_CANDIDATE:
        raise RecordError("this runner connection supports only the frozen CONFIRMED candidate")
    histories = _histories_by_key(retained)
    # Validate the whole supplied scope before evaluating any fills. A request
    # that does not trigger is still assessed and retained in the exclusions.
    supplied_sessions: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, OrFailureTrainingEvent):
            raise RecordError("events must be OrFailureTrainingEvent records")
        history = histories.get((event.ticker, event.session))
        if history is None:
            raise RecordError("event does not match a retained training session")
        if event.request.policy.confirmation != MINUTE_CLOSE_CONFIRMATION:
            raise RecordError("the CONFIRMED candidate requires minute-close confirmation")
        supplied_sessions.add((event.ticker, event.session))
        for records in (event.trades, event.quotes):
            for record in records:
                if not isinstance(record, Quote):
                    raise RecordError("trade and quote inputs must be Quote records")
                if (record.metadata.instrument_id != event.ticker
                        or record.metadata.session != event.session):
                    raise RecordError("trade or quote metadata does not match the event ticker and session")
    dispositions: dict[tuple[str, str], SessionWithoutEvent] = {}
    for row in sessions_without_events:
        if not isinstance(row, SessionWithoutEvent):
            raise RecordError("session dispositions must be SessionWithoutEvent records")
        key = (row.ticker, row.session)
        if key not in histories:
            raise RecordError("session disposition does not match a retained training session")
        if key in dispositions or key in supplied_sessions:
            raise RecordError("duplicate or conflicting session disposition")
        dispositions[key] = row
    missing = sorted(set(histories) - supplied_sessions - set(dispositions))
    if missing:
        raise RecordError(f"missing candidate evaluation coverage for retained sessions: {missing}")

    resolved: list[ResolvedTrainingTrade] = []
    excluded: list[ExcludedTrainingEvent] = [
        ExcludedTrainingEvent(ticker, session, "UNKNOWN", reason)
        for ticker, session, reason in retained.skipped
    ]
    excluded.extend(ExcludedTrainingEvent(row.ticker, row.session, "UNKNOWN",
                                         f"{row.status}:{row.reason}")
                    for row in dispositions.values())
    evaluated_sessions = {key for key, row in dispositions.items() if row.status == "NO_EVENT"}
    for event in events:
        history = histories[(event.ticker, event.session)]
        assessment = evaluate_or_failure_rev(event.request)
        evaluated_sessions.add((event.ticker, event.session))
        direction = assessment.direction
        if assessment.state.state != "ALERT_TRIGGERED":
            reason = assessment.reasons[0] if assessment.reasons else assessment.state.state
            excluded.append(ExcludedTrainingEvent(event.ticker, event.session, direction, reason))
            continue
        if assessment.risk is None or not assessment.targets:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, "RISK_OR_TARGETS_UNAVAILABLE"))
            continue

        outcome = evaluate_playbook_outcome(
            record_id=f"{RUN_VERSION}:{event.ticker}:{event.session}:{direction}",
            candidate_id=candidate.candidate_id, strategy_id=PLAYBOOK,
            direction=direction, risk=assessment.risk, targets=assessment.targets,
            alert_time=assessment.evaluated_at, evaluated_at=history.batch.request.end,
            trades=event.trades, quotes=event.quotes, policy=fill_policy,
            history=history.batch,
        )
        if outcome.resolved_r is None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, outcome.status_reason))
            continue
        input_ids = tuple(dict.fromkeys(
            (*assessment.structural_input_ids, *outcome.outcome.input_record_ids)))
        if not input_ids:
            raise RecordError("a resolved training event must retain its input record IDs")
        closed_at = max(row.at for row in outcome.unit_exits)
        resolved.append(ResolvedTrainingTrade(
            playbook=PLAYBOOK, candidate_id=candidate.candidate_id,
            ticker=event.ticker, direction=direction, closed_at=closed_at,
            resolved_r=outcome.resolved_r, cost_model_version=fill_policy.version,
            costs_complete=outcome.fill.status == "FILLED"
            and outcome.fill.total_cost_per_share is not None,
            tested_axes=("D-052",), input_record_ids=input_ids,
        ))

    evaluated_tickers = tuple(ticker for ticker in TRAINING_TICKERS
                              if any(key[0] == ticker for key in evaluated_sessions))
    measurement = measure_stage1_candidate(
        playbook=PLAYBOOK, candidate=candidate, trades=tuple(resolved),
        evaluated_tickers=evaluated_tickers, disabled_rules=disabled_rules,
    ) if resolved and evaluated_sessions == set(histories) else None
    return OrFailureStage1Run(
        RUN_VERSION, candidate.candidate_id, measurement, tuple(resolved), tuple(excluded),
        tuple(sorted(evaluated_sessions)))


__all__ = [
    "RUN_VERSION", "CONFIRMED_CANDIDATE", "ExcludedTrainingEvent",
    "OrFailureStage1Run", "OrFailureTrainingEvent", "SessionWithoutEvent",
    "run_confirmed_or_failure_stage1",
]
