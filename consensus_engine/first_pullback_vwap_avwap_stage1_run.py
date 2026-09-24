"""M9.1CM: connect the AVWAP-on first-pullback candidate to stage 1.

The existing first-pullback gates stay strict.  This research-only replay owner
adds the frozen D-055 support alternative: the pullback may be supported by
either session VWAP or an anchored VWAP whose anchor is the frozen impulse
origin.  Missing anchored-VWAP evidence stays visible and never becomes a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from fractions import Fraction
from typing import Sequence

from .fill_cost_model import FillCostPolicy
from .first_pullback_vwap import (
    INVALIDATIONS, MEASUREMENT_GATE, PASS, SUPPORT_GATE, UNKNOWN,
    FirstPullbackVwapMachine, PullbackAssessment, PullbackRequest,
    evaluate_first_pullback_vwap,
)
from .first_pullback_vwap_replay import FirstPullbackVwapReplayStrategy
from .first_pullback_vwap_stage1_run import (
    FirstPullbackStage1Run, FirstPullbackTrainingEvent, _histories_by_key,
    _input_ids, _validate_event,
)
from .or_failure_stage1_run import ExcludedTrainingEvent, SessionWithoutEvent
from .playbook_outcome_evaluator import evaluate_playbook_outcome
from .retained_history_batches import RetainedHistoryBatches
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import ResolvedTrainingTrade, measure_stage1_candidate
from .strategy_interface import RequiredData, StrategyState
from .trade_alerts_models import RecordError, SessionRecord, StrategyStateTransition
from .utils.time_context import as_utc

RUN_VERSION = "M91CM_FIRST_PULLBACK_VWAP_AVWAP_STAGE1_RUN_V1"
PLAYBOOK = "FIRST_PULLBACK_VWAP"
AVWAP_CANDIDATE = STAGE1_CANDIDATES[PLAYBOOK][1]


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{name} is required")
    return value


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


@dataclass(frozen=True)
class AnchoredVwapSupport:
    """One supplied pullback-distance reading from the impulse-origin AVWAP."""

    record_id: str
    definition_reference: str
    symbol: str
    direction: str
    anchor_at: datetime
    evaluated_at: datetime
    available_at: datetime
    coverage_complete: bool
    support_from_avwap_atr: float | None = None
    missing_reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _label(self.record_id, "AVWAP record ID")
        _label(self.definition_reference, "AVWAP definition reference")
        _label(self.symbol, "AVWAP symbol")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("AVWAP direction must be LONG or SHORT")
        for name in ("anchor_at", "evaluated_at", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if self.anchor_at >= self.evaluated_at:
            raise RecordError("AVWAP anchor must precede its evaluation")
        if self.available_at > self.evaluated_at:
            raise RecordError("AVWAP support cannot arrive after its evaluation")
        if type(self.coverage_complete) is not bool:
            raise RecordError("AVWAP coverage_complete must be true or false")
        if (not isinstance(self.input_record_ids, tuple)
                or not self.input_record_ids
                or any(not isinstance(row, str) or not row.strip()
                       for row in self.input_record_ids)):
            raise RecordError("AVWAP input record IDs must be non-empty strings")
        if self.support_from_avwap_atr is None:
            _label(self.missing_reason, "AVWAP missing reason")
        else:
            if isinstance(self.support_from_avwap_atr, bool) or not isinstance(
                    self.support_from_avwap_atr, (int, float)):
                raise RecordError("AVWAP support distance must be a number")
            try:
                Fraction(str(self.support_from_avwap_atr))
            except (ValueError, ArithmeticError) as exc:
                raise RecordError("AVWAP support distance must be finite") from exc
            if not self.coverage_complete:
                raise RecordError("incomplete AVWAP coverage cannot supply a distance")
            if self.missing_reason is not None:
                raise RecordError("supplied AVWAP support cannot also be missing")


def _avwap_assessment(
    request: PullbackRequest, support: AnchoredVwapSupport | None,
) -> PullbackAssessment:
    assessment = evaluate_first_pullback_vwap(request)
    session_support = assessment.gate(SUPPORT_GATE)
    pad = Fraction(str(request.policy.max_support_atr_multiple))

    if support is None:
        avwap_status, observed, reason, ids = (
            UNKNOWN, None, "AVWAP_SUPPORT_UNAVAILABLE", ())
    else:
        if (support.symbol != request.symbol or support.direction != request.direction
                or support.anchor_at != request.impulse_started_at
                or support.evaluated_at != request.evaluated_at):
            raise RecordError("AVWAP support does not match this impulse evaluation")
        ids = tuple(dict.fromkeys((support.record_id, *support.input_record_ids)))
        if support.support_from_avwap_atr is None:
            avwap_status, observed, reason = UNKNOWN, None, support.missing_reason
        else:
            value = Fraction(str(support.support_from_avwap_atr))
            avwap_status = PASS if value >= -pad else "FAIL"
            observed = float(value)
            reason = None if avwap_status == PASS else "PULLBACK_BEYOND_SUPPLIED_AVWAP_PAD"

    if session_support.status == PASS:
        combined = session_support
    elif avwap_status == PASS:
        combined = replace(
            session_support, status=PASS, observed=observed, threshold=float(-pad),
            reason=None, input_record_ids=ids)
    elif session_support.status == "FAIL" and avwap_status == "FAIL":
        combined = replace(
            session_support, reason="PULLBACK_BEYOND_SESSION_VWAP_AND_AVWAP_PAD",
            input_record_ids=tuple(dict.fromkeys((*session_support.input_record_ids, *ids))))
    else:
        combined = replace(
            session_support, status=UNKNOWN, observed=observed, threshold=float(-pad),
            reason=reason or session_support.reason,
            input_record_ids=tuple(dict.fromkeys((*session_support.input_record_ids, *ids))))

    gates = tuple(combined if row.name == SUPPORT_GATE else row for row in assessment.gates)
    if any(row.reason in INVALIDATIONS for row in gates):
        state = StrategyState("INVALIDATED")
    elif assessment.gate(MEASUREMENT_GATE).status != PASS:
        state = StrategyState("SETUP_FORMING", "PULLBACK_FORMING")
    elif all(row.status == PASS for row in gates):
        state = StrategyState("ALERT_TRIGGERED")
    else:
        state = StrategyState("ARMED")
    reasons = tuple(
        f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    unavailable = tuple(row for row in assessment.unavailable
                        if row != "AVWAP_QUESTION_UNDEFINED")
    if avwap_status == UNKNOWN:
        unavailable += (reason,)
    return replace(
        assessment, state=state, gates=gates, reasons=reasons, unavailable=unavailable)


class _AvwapMachine(FirstPullbackVwapMachine):
    """The canonical machine with the frozen D-055 assessment supplied."""

    def propose_avwap(
        self, request: PullbackRequest, assessment: PullbackAssessment, *,
        record_id: str, staged_record_id: str | None = None,
    ) -> tuple[PullbackAssessment, tuple[StrategyStateTransition, ...]]:
        if not isinstance(request, PullbackRequest):
            raise RecordError("PullbackRequest is required")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if self._window is not None and request.window != self._window:
            raise RecordError("a different impulse cannot replace the one already taken over")
        self._forward(request.evaluated_at)
        target = assessment.state
        if target == self._state:
            self._pending, self._effect = (), None
            return assessment, ()
        if self._state.state == "ALERT_TRIGGERED" and target.state in ("ARMED", "SETUP_FORMING"):
            raise RecordError("an actionable continuation cannot fall back to an earlier state")
        if self._state.state == "ARMED" and target.state == "SETUP_FORMING":
            target = StrategyState("INVALIDATED")
        if self._state.state == "INVALIDATED":
            raise RecordError("a closed continuation cannot be reopened inside one owner")
        reason = assessment.reasons[0] if assessment.reasons else "ALL_SUPPLIED_PULLBACK_GATES_PASSED"
        ids = tuple(sorted({value for row in assessment.gates
                            for value in row.input_record_ids}))
        armed = StrategyState("ARMED")
        staged = self._state == self._rules.initial_state and target.state == "ALERT_TRIGGERED"
        changes: tuple[StrategyStateTransition, ...] = ()
        previous = self._state
        if staged:
            if staged_record_id is None:
                raise RecordError("this evaluation advances two states and needs a second ID")
            changes += (self._transition(
                record_id=record_id, at=request.evaluated_at, state=armed,
                reason="PULLBACK_FORMED_ARMED", previous=previous, input_record_ids=ids),)
            previous = armed
        elif staged_record_id is not None:
            raise RecordError("a single-step evaluation cannot use a second transition ID")
        changes += (self._transition(
            record_id=staged_record_id if staged else record_id, at=request.evaluated_at,
            state=target, reason=reason, previous=previous, input_record_ids=ids),)
        self._pending = changes
        if target.state == "ALERT_TRIGGERED":
            self._effect = ("ACTION", request.evaluated_at)
        elif target.state == "ARMED":
            self._effect = ("TAKE", request.window)
        else:
            self._effect = ("CLOSE", None)
        return assessment, changes


class AvwapFirstPullbackReplayStrategy(FirstPullbackVwapReplayStrategy):
    """Research-only replay owner for VWAP_MANDATORY|AVWAP_ON."""

    def __init__(self, *, avwap_supports: tuple[AnchoredVwapSupport, ...], **kwargs):
        if not isinstance(avwap_supports, tuple) or not avwap_supports:
            raise RecordError("AVWAP replay requires supplied support readings")
        supplied: dict[datetime, AnchoredVwapSupport] = {}
        for row in avwap_supports:
            if not isinstance(row, AnchoredVwapSupport):
                raise RecordError("AVWAP supports must be AnchoredVwapSupport records")
            if row.evaluated_at in supplied:
                raise RecordError("AVWAP support evaluation times must be distinct")
            supplied[row.evaluated_at] = row
        self._avwap_supports = supplied
        super().__init__(**kwargs)

    def reset(self, session: SessionRecord) -> None:
        super().reset(session)
        self._owner = _AvwapMachine(
            session=session, symbol=self._symbol, instrument_type=self._instrument_type,
            strategy_version=self._version, policy=self._policy)

    def required_data(self) -> tuple[RequiredData, ...]:
        return super().required_data() + (RequiredData(
            "IMPULSE_ORIGIN_AVWAP_SUPPORT", "MODIFIER", self._definition,
            "SUPPLIED_REPLAY_INPUTS"),)

    def _propose(self, request: PullbackRequest):
        assessment = _avwap_assessment(request, self._avwap_supports.get(request.evaluated_at))
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
    if not isinstance(strategy, AvwapFirstPullbackReplayStrategy):
        raise RecordError("AVWAP events require AvwapFirstPullbackReplayStrategy")
    for context in event.contexts:
        strategy.update(context)
        strategy.confirm_recorded()
    return strategy.outcome()


def run_avwap_first_pullback_stage1(
    *, retained: RetainedHistoryBatches, candidate: Candidate,
    events: Sequence[FirstPullbackTrainingEvent], fill_policy: FillCostPolicy,
    sessions_without_events: Sequence[SessionWithoutEvent] = (),
    disabled_rules: tuple[str, ...] = (),
) -> FirstPullbackStage1Run:
    """Measure VWAP_MANDATORY|AVWAP_ON without opening held-out data."""
    if candidate != AVWAP_CANDIDATE:
        raise RecordError("this runner supports only VWAP_MANDATORY|AVWAP_ON")
    histories = _histories_by_key(retained)
    supplied_sessions: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, FirstPullbackTrainingEvent):
            raise RecordError("events must be FirstPullbackTrainingEvent records")
        if not isinstance(event.strategy, AvwapFirstPullbackReplayStrategy):
            raise RecordError("AVWAP events require AvwapFirstPullbackReplayStrategy")
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
    "AVWAP_CANDIDATE", "AnchoredVwapSupport", "AvwapFirstPullbackReplayStrategy",
    "RUN_VERSION", "run_avwap_first_pullback_stage1",
]
