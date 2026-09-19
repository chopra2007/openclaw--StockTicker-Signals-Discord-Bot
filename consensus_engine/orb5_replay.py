"""M6.4 offline replay owner for `CRVOL_ORB5` over supplied scenario inputs.

This module adds no rule of its own. It is the M4.1 strategy adapter that lets
the M5.3 replay runner drive the already-proved M6.1 eligibility machine, M6.2
attempt owner and M6.3 composition through one chronological sequence of
supplied evaluation instants. Every threshold, feature binding, mandatory status
fact, observation, participation record, geometry result and confidence result
is supplied by the caller for one exact instant: the exact ARMED thresholds and
trigger values still belong to `M03B_ORB5_V1`, which is PROPOSED, so a scenario
must name its own definition reference. Nothing here reads a clock, fetches
data, opens a database, scores a setup, assembles an alert candidate or delivers
anything.

Replaying a scenario describes the supplied inputs at those instants only. It is
not a trigger, an approved rule, proof of provider coverage, a backtest result,
an edge claim or permission to act.

Two boundaries are deliberate and kept explicit rather than filled in here:

* `heads_up` and `actionable` stay `None`. Candidate assembly, suppression,
  deduplication, the options path and delivery keep their existing M4.5/M4.6
  owners; this owner reports the composed M6.3 outcome instead.
* `invalidate` and `expire` never let a caller assert an outcome the supplied
  evidence did not produce. M6.2 derives invalidation from its own gates during
  `update`, and M6.1 expiry follows the supplied evaluation window.

State advances only after the caller records the proposed transition. `update`
returns the transitions to store and confirms them at the start of the next
evaluation, so a failed recording leaves this owner where it was.
"""

from dataclasses import dataclass
from datetime import datetime

from .confidence import ConfidenceResult
from .orb5_eligibility import (
    EligibilityAssessment, EligibilityPolicy, EligibilityRequest, MandatoryStatus,
    Orb5EligibilityMachine, eligibility_rules, evaluate_orb5_eligibility,
)
from .orb5_risk_confidence import Orb5Outcome, Orb5OutcomeRequest, compose_orb5_outcome
from .orb5_trigger import (
    CROSSED, MinuteClose, Observation, Orb5TriggerMachine, PASS, ProjectedVolume,
    TapeIntensity, TriggerAssessment, TriggerPolicy, TriggerRequest, candidate_boundary,
    evaluate_crossing, freeze_candidate, trigger_rules,
)
from .state_transitions import TransitionRules
from .strategy_interface import RequiredData, Strategy, StrategyContext, StrategyState
from .structural_risk import RiskTargetResult
from .trade_alerts_models import (
    AlertCandidate, ConfidenceBreakdown, RecordError, RiskLevel, SessionRecord,
    StrategyStateTransition, TargetLevel,
)
from .utils.time_context import as_utc


REPLAY_VERSION = "M64_ORB5_REPLAY_V1"
RULES_VERSION = "M64_ORB5_REPLAY_RULES_V1"
STRATEGY_ID = "CRVOL_ORB5"
DATA_MODE = "SUPPLIED_REPLAY_INPUTS"
ARMED = StrategyState("ARMED")
EXPIRED = StrategyState("EXPIRED")


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")
    return value


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def orb5_replay_rules() -> TransitionRules:
    """Exactly the M6.1 and M6.2 pairs, with no new transition of its own.

    One replay owner hands the same M4.2 engine both the eligibility path and the
    attempt path, so the supplied rules must hold both. Nothing is added here
    that either milestone did not already allow.
    """
    eligibility, trigger = eligibility_rules(), trigger_rules()
    allowed = list(eligibility.allowed)
    for pair in trigger.allowed:
        if pair not in allowed:
            allowed.append(pair)
    return TransitionRules(RULES_VERSION, eligibility.initial_state, tuple(allowed))


@dataclass(frozen=True)
class CrossingInputs:
    """The two consecutive same-arm observations and the pre-crossing structure.

    The buffer and boundary are recomputed from these supplied values before the
    crossing test and frozen only at the crossing itself, so a moving ATR cannot
    walk an open attempt's boundary.
    """

    current: Observation
    opening_range_high: float
    opening_range_low: float
    latest_atr: float
    anchor_bar_id: str
    previous: Observation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.current, Observation):
            raise RecordError("the crossing observation must be Observation")
        if self.previous is not None and not isinstance(self.previous, Observation):
            raise RecordError("the preceding observation must be Observation or null")
        _label(self.anchor_bar_id, "anchor bar ID")

    @property
    def input_record_ids(self) -> tuple[str, ...]:
        return tuple(row.record_id for row in (self.previous, self.current) if row is not None)


@dataclass(frozen=True)
class Orb5ReplayStep:
    """Every supplied input for one exact evaluation instant.

    A field left null stays an explicit unknown for its own gate. Nothing here is
    carried over from an earlier instant, and no value is defaulted.
    """

    evaluated_at: datetime
    status: MandatoryStatus
    preliminary: RiskTargetResult | None = None
    crossing: CrossingInputs | None = None
    observations: tuple[Observation, ...] = ()
    participation: TapeIntensity | ProjectedVolume | None = None
    last_trade: Observation | None = None
    geometry: RiskTargetResult | None = None
    confidence: ConfidenceResult | None = None
    minute_close: MinuteClose | None = None
    reset_close: MinuteClose | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if not isinstance(self.status, MandatoryStatus):
            raise RecordError("mandatory status must be supplied")
        for name, expected in (("preliminary", RiskTargetResult), ("crossing", CrossingInputs),
                               ("geometry", RiskTargetResult), ("confidence", ConfidenceResult),
                               ("minute_close", MinuteClose), ("reset_close", MinuteClose),
                               ("last_trade", Observation)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, expected):
                raise RecordError(f"{name} must be its canonical record or null")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(row, Observation) for row in self.observations
        ):
            raise RecordError("observations must be a tuple of Observation")
        if self.participation is not None and not isinstance(
                self.participation, (TapeIntensity, ProjectedVolume)):
            raise RecordError("participation must be one supported arm record or null")


class Orb5ReplayStrategy(Strategy):
    """One serially owned `(session, symbol, direction)` replay owner.

    The owner holds the M6.1 eligibility machine below ARMED and hands control to
    the M6.2 attempt owner once a supplied crossing opens an attempt. Control
    returns after a supplied inside-range close resets that attempt. It proposes
    canonical transitions for the M4.2 engine and the M5.1 store; it never writes,
    sends or advances itself.
    """

    strategy_id = STRATEGY_ID

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, definition_reference: str,
                 eligibility_policy: EligibilityPolicy, trigger_policy: TriggerPolicy,
                 steps: tuple[Orb5ReplayStep, ...], record_prefix: str):
        if not isinstance(eligibility_policy, EligibilityPolicy):
            raise RecordError("eligibility policy must be EligibilityPolicy")
        if not isinstance(trigger_policy, TriggerPolicy):
            raise RecordError("trigger policy must be TriggerPolicy")
        if instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("underlying must be EQUITY or ETF")
        if direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if not isinstance(steps, tuple) or not steps:
            raise RecordError("replay requires a non-empty tuple of supplied steps")
        self._symbol = _label(symbol, "symbol")
        self._instrument_type = instrument_type
        self._direction = direction
        self._version = _label(strategy_version, "strategy version")
        self._definition = _label(definition_reference, "definition reference")
        self._prefix = _label(record_prefix, "transition record prefix")
        self._eligibility_policy = eligibility_policy
        self._trigger_policy = trigger_policy
        supplied: dict[datetime, Orb5ReplayStep] = {}
        previous: datetime | None = None
        for step in steps:
            if not isinstance(step, Orb5ReplayStep):
                raise RecordError("replay steps must be Orb5ReplayStep records")
            if previous is not None and step.evaluated_at <= previous:
                raise RecordError("replay steps must be chronological and distinct")
            previous = step.evaluated_at
            supplied[step.evaluated_at] = step
        self._steps = supplied
        self.reset(session)

    # --- M4.1 identity ------------------------------------------------------

    @property
    def strategy_version(self) -> str:
        return self._version

    @property
    def rules(self) -> TransitionRules:
        return orb5_replay_rules()

    def required_data(self) -> tuple[RequiredData, ...]:
        """Named supplied inputs only; a declaration proves no availability."""
        bindings = tuple(
            RequiredData(row.feature_name, "MANDATORY", row.feature_version, row.data_mode)
            for row in self._eligibility_policy.bindings)
        reference = self._eligibility_policy.definition_reference
        return bindings + (
            RequiredData("QUOTE_EVENT_DECISION", "MANDATORY", reference, DATA_MODE),
            RequiredData("MANDATORY_STATUS", "MANDATORY", reference, DATA_MODE),
            RequiredData("ARM_OBSERVATION", "MANDATORY", self._trigger_policy.definition_reference,
                         DATA_MODE),
            RequiredData("PARTICIPATION", "MANDATORY", self._trigger_policy.definition_reference,
                         DATA_MODE),
            RequiredData("RISK_TARGETS", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("CONFIDENCE", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("MINUTE_CLOSE", "MODIFIER", self._trigger_policy.definition_reference,
                         DATA_MODE),
            RequiredData("CATALYST_EVENT", "OPTIONAL", reference, DATA_MODE),
        )

    # --- supplied state -----------------------------------------------------

    def current_state(self) -> StrategyState:
        """The confirmed state; a proposed transition is not yet an advance."""
        state = self._trigger_owner.current_state()
        if state != ARMED or self._trigger_owner.current_candidate() is not None:
            return state
        return self._eligibility_owner.current_state()

    def last_eligibility(self) -> EligibilityAssessment | None:
        return self._eligibility

    def last_trigger(self) -> TriggerAssessment | None:
        return self._trigger

    def outcome(self) -> Orb5Outcome | None:
        """The composed M6.3 result for the latest evaluation, when supplied."""
        return self._outcome

    def notes(self) -> tuple[str, ...]:
        """Why the latest evaluation proposed nothing, when it proposed nothing."""
        return self._notes

    def confirm_recorded(self) -> StrategyState:
        """Advance the owning machine once its proposed transition was stored."""
        for owner, transition in self._pending:
            owner.confirm(transition)
        self._pending = ()
        return self.current_state()

    def reset(self, session: SessionRecord) -> None:
        """Start the supplied fixed session; earlier records are never mutated."""
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        self._session = session
        scope = dict(session=session, symbol=self._symbol,
                     instrument_type=self._instrument_type, direction=self._direction,
                     strategy_version=self._version)
        self._eligibility_owner = Orb5EligibilityMachine(
            policy=self._eligibility_policy, **scope)
        self._trigger_owner = Orb5TriggerMachine(policy=self._trigger_policy, **scope)
        self._pending: tuple[tuple[object, StrategyStateTransition], ...] = ()
        self._count = 0
        self._time: datetime | None = None
        self._eligibility: EligibilityAssessment | None = None
        self._trigger: TriggerAssessment | None = None
        self._outcome: Orb5Outcome | None = None
        self._notes: tuple[str, ...] = ()

    # --- one supplied evaluation -------------------------------------------

    def update(self, context: StrategyContext) -> tuple[StrategyStateTransition, ...]:
        self._check(context)
        self._confirm_recorded_before(context)
        step = self._step(context.evaluated_at)
        self._eligibility, self._trigger, self._outcome, self._notes = None, None, None, ()
        if self.current_state() == EXPIRED:
            self._notes = ("SESSION_EXPIRED",)
            return ()
        if self._attempt_open():
            return self._advance_attempt(context, step)
        return self._advance_eligibility(context, step)

    def heads_up(self) -> AlertCandidate | None:
        """Candidate assembly keeps its M4.5 owner; this owner assembles none."""
        return None

    def actionable(self) -> AlertCandidate | None:
        """Candidate assembly keeps its M4.5 owner; this owner assembles none."""
        return None

    def invalidate(self, context: StrategyContext, *, reason: str
                   ) -> tuple[StrategyStateTransition, ...]:
        """Refused: M6.2 derives invalidation from supplied evidence in `update`."""
        self._check(context)
        _label(reason, "invalidation reason")
        raise RecordError(
            "M6.2 invalidation follows the supplied attempt evidence, not a caller assertion")

    def expire(self, context: StrategyContext, *, reason: str
               ) -> tuple[StrategyStateTransition, ...]:
        """Expire one open attempt; M6.1 expiry follows its own supplied window."""
        self._check(context)
        self._confirm_recorded_before(context)
        if not self._attempt_open() or self._trigger_owner.current_candidate() is None:
            raise RecordError(
                "M6.1 expiry follows the supplied evaluation window, not a caller assertion")
        return self._propose(self._trigger_owner, lambda record_id: self._trigger_owner.expire(
            at=context.evaluated_at, reason=_label(reason, "expiry reason"), record_id=record_id))

    def confidence(self) -> ConfidenceBreakdown | None:
        return None if self._outcome is None else self._outcome.confidence

    def stop(self) -> RiskLevel | None:
        return None if self._outcome is None else self._outcome.risk

    def targets(self) -> tuple[TargetLevel, ...]:
        return () if self._outcome is None else self._outcome.targets

    # --- internals ----------------------------------------------------------

    def _check(self, context: StrategyContext) -> None:
        if not isinstance(context, StrategyContext):
            raise RecordError("context must be StrategyContext")
        if (context.session != self._session or context.symbol != self._symbol
                or context.instrument_type != self._instrument_type
                or context.direction != self._direction):
            raise RecordError("evaluation does not match this replay owner")
        if self._time is not None and context.evaluated_at < self._time:
            raise RecordError("evaluation time cannot move backward")

    def _confirm_recorded_before(self, context: StrategyContext) -> None:
        self.confirm_recorded()
        self._time = context.evaluated_at

    def _step(self, at: datetime) -> Orb5ReplayStep:
        step = self._steps.get(at)
        if step is None:
            raise RecordError("no supplied replay step for this evaluation instant")
        return step

    def _attempt_open(self) -> bool:
        return self._trigger_owner.current_state() != ARMED

    def _propose(self, owner, build) -> tuple[StrategyStateTransition, ...]:
        record_id = "%s-%03d" % (self._prefix, self._count + 1)
        changes = build(record_id)
        if changes:
            self._count += 1
            self._pending = ((owner, changes[0]),)
        return changes

    def _eligibility_request(self, context: StrategyContext,
                             step: Orb5ReplayStep) -> EligibilityRequest:
        return EligibilityRequest(context, self._eligibility_policy, step.status, step.preliminary)

    def _advance_eligibility(self, context: StrategyContext,
                             step: Orb5ReplayStep) -> tuple[StrategyStateTransition, ...]:
        request = self._eligibility_request(context, step)
        held: list[EligibilityAssessment] = []

        def build(record_id: str) -> tuple[StrategyStateTransition, ...]:
            assessment, changes = self._eligibility_owner.propose(request, record_id=record_id)
            held.append(assessment)
            return changes

        changes = self._propose(self._eligibility_owner, build)
        self._eligibility = held[0]
        if changes:
            return changes
        if self._eligibility_owner.current_state() != ARMED:
            self._notes = ("NOT_ARMED:" + self._eligibility_owner.current_state().state,)
            return ()
        if step.crossing is None:
            self._notes = ("NO_SUPPLIED_CROSSING",)
            return ()
        return self._open_attempt(context, step.crossing)

    def _open_attempt(self, context: StrategyContext,
                      crossing: CrossingInputs) -> tuple[StrategyStateTransition, ...]:
        at, policy = context.evaluated_at, self._trigger_policy
        if crossing.current.observed_at != at:
            raise RecordError("the crossing observation must belong to this evaluation instant")
        _, boundary = candidate_boundary(
            policy, self._direction, opening_range_high=crossing.opening_range_high,
            opening_range_low=crossing.opening_range_low, latest_atr=crossing.latest_atr)
        result = evaluate_crossing(policy, self._direction, boundary=boundary,
                                   previous=crossing.previous, current=crossing.current)
        if result.status != CROSSED:
            self._notes = ("CROSSING:" + result.status + ":" + str(result.reason),)
            return ()
        quota = self._trigger_owner.attempt_quota(at)
        if quota.status != PASS:
            self._notes = ("ATTEMPT_QUOTA:" + str(quota.reason),)
            return ()
        frozen = freeze_candidate(
            policy, direction=self._direction, crossed_at=at,
            opening_range_high=crossing.opening_range_high,
            opening_range_low=crossing.opening_range_low, latest_atr=crossing.latest_atr,
            anchor_bar_id=crossing.anchor_bar_id,
            attempt_number=self._trigger_owner.pending_attempt_number,
            input_record_ids=crossing.input_record_ids)
        return self._propose(self._trigger_owner, lambda record_id:
                             self._trigger_owner.open_attempt(frozen, record_id=record_id))

    def _advance_attempt(self, context: StrategyContext,
                         step: Orb5ReplayStep) -> tuple[StrategyStateTransition, ...]:
        candidate = self._trigger_owner.current_candidate()
        if candidate is None:
            self._notes = ("NO_OPEN_ATTEMPT",)
            return ()
        if step.reset_close is not None:
            return self._propose(self._trigger_owner, lambda record_id:
                                 self._trigger_owner.reset(step.reset_close,
                                                           at=context.evaluated_at,
                                                           record_id=record_id))
        assessment = evaluate_orb5_eligibility(self._eligibility_request(context, step))
        self._eligibility = assessment
        request = TriggerRequest(
            candidate=candidate, policy=self._trigger_policy, evaluated_at=context.evaluated_at,
            observations=step.observations, participation=step.participation,
            last_trade=step.last_trade, eligibility=assessment, geometry=step.geometry,
            minute_close=step.minute_close)
        held: list[TriggerAssessment] = []

        def build(record_id: str) -> tuple[StrategyStateTransition, ...]:
            evaluated, changes = self._trigger_owner.propose(request, record_id=record_id)
            held.append(evaluated)
            return changes

        changes = self._propose(self._trigger_owner, build)
        self._trigger = held[0]
        self._compose(step, held[0])
        if not changes:
            self._notes = ("NO_STATE_CHANGE:" + held[0].state.state,)
        return changes

    def _compose(self, step: Orb5ReplayStep, assessment: TriggerAssessment) -> None:
        if step.geometry is None or step.confidence is None:
            return
        self._outcome = compose_orb5_outcome(Orb5OutcomeRequest(
            assessment, step.geometry, step.confidence, self._version, self._definition))


__all__ = [
    "ARMED", "CrossingInputs", "DATA_MODE", "EXPIRED", "Orb5ReplayStep", "Orb5ReplayStrategy",
    "REPLAY_VERSION", "RULES_VERSION", "STRATEGY_ID", "orb5_replay_rules",
]
