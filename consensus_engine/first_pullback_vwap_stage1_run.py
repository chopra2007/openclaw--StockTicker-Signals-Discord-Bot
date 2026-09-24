"""M9.1CK: connect the default first-pullback candidate to stage 1.

The caller supplies one already-configured ``FirstPullbackVwapReplayStrategy``
and its chronological contexts for every retained training session.  This
runner drives that existing strategy, evaluates a triggered continuation on
the matching retained history, and sends only resolved, fully costed rows to
the strict stage-1 measurement boundary.  Missing policy, quote, fill, or
outcome inputs remain visible exclusions; they are never estimated.

The existing replay owner requires the mandatory VWAP gates and has no AVWAP
gate.  Therefore this connection supports only the frozen
``VWAP_MANDATORY|AVWAP_OFF`` candidate.  It reads no files, opens no held-out
name, and changes no strategy or live rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .fill_cost_model import FillCostPolicy
from .first_pullback_vwap import PullbackAssessment
from .first_pullback_vwap_replay import FirstPullbackVwapReplayStrategy
from .or_failure_stage1_run import (
    ExcludedTrainingEvent, SessionWithoutEvent, _histories_by_key,
)
from .playbook_outcome_evaluator import evaluate_playbook_outcome
from .retained_history_batches import RetainedHistoryBatches
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import (
    ResolvedTrainingTrade, Stage1TrainingMeasurement, measure_stage1_candidate,
)
from .strategy_interface import StrategyContext
from .trade_alerts_models import Quote, RecordError

RUN_VERSION = "M91CK_FIRST_PULLBACK_VWAP_STAGE1_RUN_V1"
PLAYBOOK = "FIRST_PULLBACK_VWAP"
DEFAULT_CANDIDATE = STAGE1_CANDIDATES[PLAYBOOK][0]


@dataclass(frozen=True)
class FirstPullbackTrainingEvent:
    ticker: str
    session: str
    strategy: FirstPullbackVwapReplayStrategy
    contexts: tuple[StrategyContext, ...]
    trades: tuple[Quote, ...]
    quotes: tuple[Quote, ...]


@dataclass(frozen=True)
class FirstPullbackStage1Run:
    version: str
    candidate_id: str
    measurement: Stage1TrainingMeasurement | None
    resolved: tuple[ResolvedTrainingTrade, ...]
    excluded: tuple[ExcludedTrainingEvent, ...]
    evaluated_sessions: tuple[tuple[str, str], ...]


def _validate_event(event: FirstPullbackTrainingEvent, histories) -> tuple[str, str]:
    key = (event.ticker, event.session)
    if key not in histories:
        raise RecordError("event does not match a retained training session")
    if not event.contexts:
        raise RecordError("a first-pullback event needs chronological strategy contexts")
    previous = None
    directions = set()
    for context in event.contexts:
        if not isinstance(context, StrategyContext):
            raise RecordError("event contexts must be StrategyContext records")
        if (context.symbol != event.ticker
                or context.session.session != event.session):
            raise RecordError("strategy context does not match the event ticker and session")
        if previous is not None and context.evaluated_at <= previous:
            raise RecordError("event contexts must be chronological and distinct")
        previous = context.evaluated_at
        directions.add(context.direction)
    if len(directions) != 1:
        raise RecordError("one training event cannot mix directions")
    for records in (event.trades, event.quotes):
        for record in records:
            if not isinstance(record, Quote):
                raise RecordError("trade and quote inputs must be Quote records")
            if (record.metadata.instrument_id != event.ticker
                    or record.metadata.session != event.session):
                raise RecordError(
                    "trade or quote metadata does not match the event ticker and session")
    return key


def _evaluate_event(event: FirstPullbackTrainingEvent) -> PullbackAssessment | None:
    strategy = event.strategy
    if not isinstance(strategy, FirstPullbackVwapReplayStrategy):
        raise RecordError("event strategy must be FirstPullbackVwapReplayStrategy")
    for context in event.contexts:
        strategy.update(context)
        strategy.confirm_recorded()
    return strategy.outcome()


def _input_ids(assessment: PullbackAssessment, evaluated) -> tuple[str, ...]:
    gate_ids = tuple(record_id for gate in assessment.gates
                     for record_id in gate.input_record_ids)
    return tuple(dict.fromkeys((
        assessment.measurement_record_id, *assessment.structural_input_ids,
        *gate_ids, *evaluated.outcome.input_record_ids,
    )))


def run_default_first_pullback_stage1(
    *, retained: RetainedHistoryBatches, candidate: Candidate,
    events: Sequence[FirstPullbackTrainingEvent], fill_policy: FillCostPolicy,
    sessions_without_events: Sequence[SessionWithoutEvent] = (),
    disabled_rules: tuple[str, ...] = (),
) -> FirstPullbackStage1Run:
    """Measure VWAP_MANDATORY|AVWAP_OFF without opening held-out data."""
    if candidate != DEFAULT_CANDIDATE:
        raise RecordError("this runner supports only VWAP_MANDATORY|AVWAP_OFF")
    histories = _histories_by_key(retained)
    supplied_sessions: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, FirstPullbackTrainingEvent):
            raise RecordError("events must be FirstPullbackTrainingEvent records")
        key = _validate_event(event, histories)
        if key in supplied_sessions:
            raise RecordError("duplicate first-pullback training event")
        supplied_sessions.add(key)

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
    excluded.extend(ExcludedTrainingEvent(
        row.ticker, row.session, "UNKNOWN", f"{row.status}:{row.reason}")
        for row in dispositions.values())
    evaluated_sessions = {key for key, row in dispositions.items() if row.status == "NO_EVENT"}

    for event in events:
        key = (event.ticker, event.session)
        history = histories[key]
        direction = event.contexts[0].direction
        assessment = _evaluate_event(event)
        evaluated_sessions.add(key)
        if assessment is None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, "NO_PULLBACK_ASSESSMENT"))
            continue
        if assessment.state.state != "ALERT_TRIGGERED":
            reason = assessment.reasons[0] if assessment.reasons else assessment.state.state
            excluded.append(ExcludedTrainingEvent(event.ticker, event.session, direction, reason))
            continue
        if assessment.risk is None or not assessment.targets:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, "RISK_OR_TARGETS_UNAVAILABLE"))
            continue

        evaluated = evaluate_playbook_outcome(
            record_id=f"{RUN_VERSION}:{event.ticker}:{event.session}:{direction}",
            candidate_id=candidate.candidate_id, strategy_id=PLAYBOOK,
            direction=direction, risk=assessment.risk, targets=assessment.targets,
            alert_time=assessment.evaluated_at, evaluated_at=history.batch.request.end,
            trades=event.trades, quotes=event.quotes, policy=fill_policy,
            history=history.batch,
        )
        if evaluated.resolved_r is None:
            excluded.append(ExcludedTrainingEvent(
                event.ticker, event.session, direction, evaluated.status_reason))
            continue
        input_ids = _input_ids(assessment, evaluated)
        if not input_ids:
            raise RecordError("a resolved training event must retain its input record IDs")
        resolved.append(ResolvedTrainingTrade(
            playbook=PLAYBOOK, candidate_id=candidate.candidate_id,
            ticker=event.ticker, direction=direction,
            closed_at=max(row.at for row in evaluated.unit_exits),
            resolved_r=evaluated.resolved_r, cost_model_version=fill_policy.version,
            costs_complete=evaluated.fill.status == "FILLED"
            and evaluated.fill.total_cost_per_share is not None,
            tested_axes=("D-054", "D-055"), input_record_ids=input_ids,
        ))

    evaluated_tickers = tuple(ticker for ticker in TRAINING_TICKERS
                              if any(key[0] == ticker for key in evaluated_sessions))
    measurement = measure_stage1_candidate(
        playbook=PLAYBOOK, candidate=candidate, trades=tuple(resolved),
        evaluated_tickers=evaluated_tickers, disabled_rules=disabled_rules,
    ) if resolved and evaluated_sessions == set(histories) else None
    return FirstPullbackStage1Run(
        RUN_VERSION, candidate.candidate_id, measurement, tuple(resolved), tuple(excluded),
        tuple(sorted(evaluated_sessions)))


__all__ = [
    "DEFAULT_CANDIDATE", "FirstPullbackStage1Run", "FirstPullbackTrainingEvent",
    "PLAYBOOK", "RUN_VERSION", "SessionWithoutEvent", "run_default_first_pullback_stage1",
]
