"""M9.1CN: connect the relaxed-VWAP plus AVWAP first-pullback candidate.

VWAP position and slope stay measured and visible but do not veto this research
candidate.  The frozen impulse-origin anchored-VWAP support alternative and all
other first-pullback, quote, structure, cost, and outcome gates stay strict.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .fill_cost_model import FillCostPolicy
from .first_pullback_vwap import (
    INVALIDATIONS, MEASUREMENT_GATE, PASS, VWAP_SIDE_GATE, VWAP_SLOPE_GATE,
    PullbackAssessment, PullbackRequest,
)
from .first_pullback_vwap_avwap_stage1_run import (
    AnchoredVwapSupport, AvwapFirstPullbackReplayStrategy, _avwap_assessment,
)
from .first_pullback_vwap_stage1_run import (
    FirstPullbackStage1Run, FirstPullbackTrainingEvent, _histories_by_key,
    _input_ids, _validate_event,
)
from .or_failure_stage1_run import ExcludedTrainingEvent, SessionWithoutEvent
from .playbook_outcome_evaluator import evaluate_playbook_outcome
from .retained_history_batches import RetainedHistoryBatches
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import ResolvedTrainingTrade, measure_stage1_candidate
from .strategy_interface import StrategyState
from .trade_alerts_models import RecordError, StrategyStateTransition

RUN_VERSION = "M91CN_FIRST_PULLBACK_VWAP_RELAXED_AVWAP_STAGE1_RUN_V1"
PLAYBOOK = "FIRST_PULLBACK_VWAP"
RELAXED_AVWAP_CANDIDATE = STAGE1_CANDIDATES[PLAYBOOK][3]
NON_GATING_VWAP = frozenset((VWAP_SIDE_GATE, VWAP_SLOPE_GATE))


def _relaxed_avwap_assessment(
    request: PullbackRequest, support: AnchoredVwapSupport | None,
) -> PullbackAssessment:
    """Apply AVWAP support, then remove only the two VWAP vetoes."""
    assessment = _avwap_assessment(request, support)
    strict_gates = tuple(row for row in assessment.gates if row.name not in NON_GATING_VWAP)
    if any(row.reason in INVALIDATIONS for row in strict_gates):
        state = StrategyState("INVALIDATED")
    elif assessment.gate(MEASUREMENT_GATE).status != PASS:
        state = StrategyState("SETUP_FORMING", "PULLBACK_FORMING")
    elif all(row.status == PASS for row in strict_gates):
        state = StrategyState("ALERT_TRIGGERED")
    else:
        state = StrategyState("ARMED")
    reasons = tuple(reason for reason in assessment.reasons
                    if reason.split(":", 1)[0] not in NON_GATING_VWAP)
    return replace(assessment, state=state, reasons=reasons)


class RelaxedAvwapFirstPullbackReplayStrategy(AvwapFirstPullbackReplayStrategy):
    """Research-only replay owner for VWAP_RELAXED|AVWAP_ON."""

    def _propose(self, request: PullbackRequest) -> tuple[StrategyStateTransition, ...]:
        assessment = _relaxed_avwap_assessment(
            request, self._avwap_supports.get(request.evaluated_at))
        target = assessment.state
        initial = self._owner.rules.initial_state
        needs_two = self._owner.current_state() == initial and target.state == "ALERT_TRIGGERED"
        record_id = self._next_id()
        staged_id = self._next_id() if needs_two else None
        evaluated, changes = self._owner.propose_avwap(
            request, assessment, record_id=record_id, staged_record_id=staged_id)
        self._assessment = evaluated
        if changes:
            self._pending = changes
        else:
            self._notes = ("NO_STATE_CHANGE:" + evaluated.state.state,)
        return changes


def _evaluate_event(event: FirstPullbackTrainingEvent) -> PullbackAssessment | None:
    strategy = event.strategy
    if not isinstance(strategy, RelaxedAvwapFirstPullbackReplayStrategy):
        raise RecordError(
            "relaxed-AVWAP events require RelaxedAvwapFirstPullbackReplayStrategy")
    for context in event.contexts:
        strategy.update(context)
        strategy.confirm_recorded()
    return strategy.outcome()


def run_relaxed_avwap_first_pullback_stage1(
    *, retained: RetainedHistoryBatches, candidate: Candidate,
    events: Sequence[FirstPullbackTrainingEvent], fill_policy: FillCostPolicy,
    sessions_without_events: Sequence[SessionWithoutEvent] = (),
    disabled_rules: tuple[str, ...] = (),
) -> FirstPullbackStage1Run:
    """Measure VWAP_RELAXED|AVWAP_ON without opening held-out data."""
    if candidate != RELAXED_AVWAP_CANDIDATE:
        raise RecordError("this runner supports only VWAP_RELAXED|AVWAP_ON")
    histories = _histories_by_key(retained)
    supplied_sessions: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, FirstPullbackTrainingEvent):
            raise RecordError("events must be FirstPullbackTrainingEvent records")
        if not isinstance(event.strategy, RelaxedAvwapFirstPullbackReplayStrategy):
            raise RecordError(
                "relaxed-AVWAP events require RelaxedAvwapFirstPullbackReplayStrategy")
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
            history=history.batch)
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
            tested_axes=("D-054", "D-055"), input_record_ids=input_ids))

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
    "RELAXED_AVWAP_CANDIDATE", "RUN_VERSION",
    "RelaxedAvwapFirstPullbackReplayStrategy",
    "run_relaxed_avwap_first_pullback_stage1",
]
