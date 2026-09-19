"""M7.5 offline replay owner for `HOD_COMP_RS` over supplied scenario inputs.

This module adds no rule of its own. It is the M4.1 strategy adapter that lets
the M5.3 replay runner drive the already-proved M7.2 eligibility machine, M7.3
structure owner and M7.4 composition through one chronological sequence of
supplied evaluation instants. Every threshold, feature binding, mandatory status
fact, compression measurement, distance, observation, participation record,
extension, stop, target, confidence result and prior action is supplied by the
caller for one exact instant: the `HOD_COMP_RS` ratios, buffers, acceptance
share, distance cutoff, extension limit, cooldown and quota stay unresolved
under PLAYBOOKS section 13 and M0.3, and `M03B_HOD_COMP_RS_V1` is still
PROPOSED, so a scenario must name its own definition reference. Nothing here
reads a clock, fetches data, opens a database, measures a compression, scores a
setup, assembles an alert candidate or delivers anything.

Replaying a scenario describes the supplied inputs at those instants only. It is
not a trigger, an alert, an approved rule, proof of provider coverage, a
backtest result, an edge claim or permission to act.

Two boundaries are deliberate and kept explicit rather than filled in here:

* `heads_up` and `actionable` stay `None`. Candidate assembly, the suppression
  record itself, deduplication, the options path and delivery keep their
  existing M4.5/M4.6 owners; this owner reports the composed M7.4 outcome and
  the M7.3 heads-up notice instead.
* `invalidate` and `expire` never let a caller assert an outcome the supplied
  evidence did not produce. M7.3 derives invalidation from its own gates during
  `update`, and expiry applies only to a structure this owner already opened.

A heads-up names one exact frozen structure. Once that notice is recorded, this
owner keeps it and refuses any later supplied structure whose frozen prices, ATR,
buffer, boundary, anchor or arm differ, so a changed input cannot walk the
boundary the notice already described.

State advances only after the caller records the proposed transition. `update`
returns the transitions to store and confirms them at the start of the next
evaluation, so a failed recording leaves this owner where it was.
"""

from dataclasses import dataclass
from datetime import datetime

from .confidence import ConfidenceResult
from .hod_comp_rs_risk_confidence import (
    ActionHistory, HodCompRsOutcome, HodCompRsOutcomeRequest, StructuralReading,
    SuppressionPolicy, compose_hod_comp_rs_outcome,
)
from .hod_comp_rs_trigger import (
    CROSSED, DistanceReading, ExtensionReading, FrozenStructure, HEADS_UP, HeadsUpAssessment,
    HeadsUpRequest, HodCompRsTriggerMachine, MinuteClose, Observation, PASS, ProjectedVolume,
    TapeIntensity, TriggerAssessment, TriggerPolicy, TriggerRequest, evaluate_crossing,
    freeze_structure, trigger_rules,
)
from .rs_trend_eligibility import (
    HodCompRsEligibilityMachine, MandatoryStatus, RsTrendAssessment, RsTrendPolicy,
    RsTrendRequest, evaluate_rs_trend_eligibility, rs_trend_rules,
)
from .state_transitions import TransitionRules
from .strategy_interface import RequiredData, Strategy, StrategyContext, StrategyState
from .trade_alerts_models import (
    AlertCandidate, ConfidenceBreakdown, RecordError, RiskLevel, SessionRecord,
    StrategyStateTransition, TargetLevel,
)
from .utils.time_context import as_utc


REPLAY_VERSION = "M75_HOD_COMP_RS_REPLAY_V1"
RULES_VERSION = "M75_HOD_COMP_RS_REPLAY_RULES_V1"
STRATEGY_ID = "HOD_COMP_RS"
DATA_MODE = "SUPPLIED_REPLAY_INPUTS"
# The frozen facts that decide the boundary a heads-up already described. A
# later structure that differs in any of them is a different structure, not the
# one this owner noticed, so it may not replace it.
STRUCTURE_IDENTITY = ("frozen_at", "direction", "mode", "structure_number",
                      "reference_extreme", "compression_high", "compression_low",
                      "frozen_atr", "buffer", "boundary", "anchor_bar_id")
ARMED = StrategyState("ARMED")
NOTICED = StrategyState("ARMED", HEADS_UP)
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


def _identifiers(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(row, str) or not row.strip() for row in value
    ):
        raise RecordError(f"{name} must be non-empty strings")
    return value


def hod_comp_rs_replay_rules() -> TransitionRules:
    """Exactly the M7.2 and M7.3 pairs, with no new transition of its own.

    One replay owner hands the same M4.2 engine both the eligibility path and the
    structure path, so the supplied rules must hold both. Nothing is added here
    that either milestone did not already allow.
    """
    eligibility, trigger = rs_trend_rules(), trigger_rules()
    allowed = list(eligibility.allowed)
    for pair in trigger.allowed:
        if pair not in allowed:
            allowed.append(pair)
    return TransitionRules(RULES_VERSION, eligibility.initial_state, tuple(allowed))


@dataclass(frozen=True)
class StructureInputs:
    """The caller's own frozen compression, reference extreme and ATR at t0.

    The same supplied values freeze the same structure for the heads-up notice
    and for the crossing that opens it, so a later evaluation cannot walk the
    boundary this owner already acted on.
    """

    frozen_at: datetime
    reference_extreme: float
    compression_high: float
    compression_low: float
    latest_atr: float
    anchor_bar_id: str
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "frozen_at", _instant(self.frozen_at, "frozen_at"))
        _label(self.anchor_bar_id, "anchor bar ID")
        _identifiers(self.input_record_ids, "structure input IDs")


@dataclass(frozen=True)
class CrossingInputs:
    """The two consecutive same-arm observations and the structure they cross.

    The boundary tested here is the one the supplied structure freezes on, so the
    crossing and the opened structure always describe the same frozen prices. A
    crossing that follows a recorded heads-up must repeat that noticed structure;
    changed prices or a changed ATR are refused rather than crossed.
    """

    current: Observation
    structure: StructureInputs
    previous: Observation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.current, Observation):
            raise RecordError("the crossing observation must be Observation")
        if not isinstance(self.structure, StructureInputs):
            raise RecordError("the crossed structure must be StructureInputs")
        if self.previous is not None and not isinstance(self.previous, Observation):
            raise RecordError("the preceding observation must be Observation or null")

    @property
    def input_record_ids(self) -> tuple[str, ...]:
        return tuple(row.record_id for row in (self.previous, self.current) if row is not None)


@dataclass(frozen=True)
class HodCompRsReplayStep:
    """Every supplied input for one exact evaluation instant.

    A field left null stays an explicit unknown for its own gate. Nothing here is
    carried over from an earlier instant, and no value is defaulted.
    """

    evaluated_at: datetime
    status: MandatoryStatus
    structure: StructureInputs | None = None
    distance: DistanceReading | None = None
    crossing: CrossingInputs | None = None
    observations: tuple[Observation, ...] = ()
    intensity: TapeIntensity | ProjectedVolume | None = None
    last_trade: Observation | None = None
    extension: ExtensionReading | None = None
    minute_close: MinuteClose | None = None
    reset_close: MinuteClose | None = None
    structural: StructuralReading | None = None
    confidence: ConfidenceResult | None = None
    history: ActionHistory | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if not isinstance(self.status, MandatoryStatus):
            raise RecordError("mandatory status must be supplied")
        for name, expected in (("structure", StructureInputs), ("distance", DistanceReading),
                               ("crossing", CrossingInputs), ("last_trade", Observation),
                               ("extension", ExtensionReading), ("minute_close", MinuteClose),
                               ("reset_close", MinuteClose),
                               ("structural", StructuralReading),
                               ("confidence", ConfidenceResult), ("history", ActionHistory)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, expected):
                raise RecordError(f"{name} must be its canonical record or null")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(row, Observation) for row in self.observations
        ):
            raise RecordError("observations must be a tuple of Observation")
        if self.intensity is not None and not isinstance(
                self.intensity, (TapeIntensity, ProjectedVolume)):
            raise RecordError("participation must be one supported arm record or null")


class HodCompRsReplayStrategy(Strategy):
    """One serially owned `(session, symbol, direction)` replay owner.

    The owner holds the M7.2 eligibility machine below ARMED and hands control to
    the M7.3 structure owner once a supplied compression reports a heads-up or a
    supplied crossing opens a structure. Control returns after a supplied
    inside-compression close resets that structure. It proposes canonical
    transitions for the M4.2 engine and the M5.1 store; it never writes, sends or
    advances itself.
    """

    strategy_id = STRATEGY_ID

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, definition_reference: str,
                 eligibility_policy: RsTrendPolicy, trigger_policy: TriggerPolicy,
                 suppression_policy: SuppressionPolicy,
                 steps: tuple[HodCompRsReplayStep, ...], record_prefix: str):
        if not isinstance(eligibility_policy, RsTrendPolicy):
            raise RecordError("eligibility policy must be RsTrendPolicy")
        if not isinstance(trigger_policy, TriggerPolicy):
            raise RecordError("trigger policy must be TriggerPolicy")
        if not isinstance(suppression_policy, SuppressionPolicy):
            raise RecordError("suppression policy must be SuppressionPolicy")
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
        self._suppression_policy = suppression_policy
        supplied: dict[datetime, HodCompRsReplayStep] = {}
        previous: datetime | None = None
        for step in steps:
            if not isinstance(step, HodCompRsReplayStep):
                raise RecordError("replay steps must be HodCompRsReplayStep records")
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
        return hod_comp_rs_replay_rules()

    def required_data(self) -> tuple[RequiredData, ...]:
        """Named supplied inputs only; a declaration proves no availability."""
        bindings = tuple(
            RequiredData(row.feature_name, "MANDATORY", row.feature_version, row.data_mode)
            for row in self._eligibility_policy.bindings)
        reference = self._eligibility_policy.definition_reference
        structure = self._trigger_policy.definition_reference
        return bindings + (
            RequiredData("QUOTE_EVENT_DECISION", "MANDATORY", reference, DATA_MODE),
            RequiredData("MANDATORY_STATUS", "MANDATORY", reference, DATA_MODE),
            RequiredData("FROZEN_STRUCTURE", "MANDATORY", structure, DATA_MODE),
            RequiredData("ARM_OBSERVATION", "MANDATORY", structure, DATA_MODE),
            RequiredData("PARTICIPATION", "MANDATORY", structure, DATA_MODE),
            RequiredData("EXTENSION_RISK", "MANDATORY", structure, DATA_MODE),
            RequiredData("RISK_TARGETS", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("CONFIDENCE", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("ACTION_HISTORY", "MANDATORY",
                         self._suppression_policy.definition_reference, DATA_MODE),
            RequiredData("HEADS_UP_DISTANCE", "MODIFIER", structure, DATA_MODE),
            RequiredData("MINUTE_CLOSE", "MODIFIER", structure, DATA_MODE),
        )

    # --- supplied state -----------------------------------------------------

    def current_state(self) -> StrategyState:
        """The confirmed state; a proposed transition is not yet an advance."""
        state = self._trigger_owner.current_state()
        if state != ARMED or self._trigger_owner.current_structure() is not None:
            return state
        return self._eligibility_owner.current_state()

    def last_eligibility(self) -> RsTrendAssessment | None:
        return self._eligibility

    def last_notice(self) -> HeadsUpAssessment | None:
        return self._notice

    def last_trigger(self) -> TriggerAssessment | None:
        return self._trigger

    def outcome(self) -> HodCompRsOutcome | None:
        """The composed M7.4 result for the latest evaluation, when supplied."""
        return self._outcome

    def notes(self) -> tuple[str, ...]:
        """Why the latest evaluation proposed nothing, when it proposed nothing."""
        return self._notes

    def noticed_structure(self) -> FrozenStructure | None:
        """The frozen structure a recorded heads-up described, while it stands."""
        return self._noticed

    def confirm_recorded(self) -> StrategyState:
        """Advance the owning machine once its proposed transition was stored."""
        for owner, transition in self._pending:
            owner.confirm(transition)
        self._pending = ()
        if self._proposed_notice is not None:
            self._noticed = self._proposed_notice
            self._proposed_notice = None
        if self._trigger_owner.current_state() != NOTICED:
            # The crossing, the reset or the expiry closed the noticed structure.
            self._noticed = None
        return self.current_state()

    def reset(self, session: SessionRecord) -> None:
        """Start the supplied fixed session; earlier records are never mutated."""
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        self._session = session
        scope = dict(session=session, symbol=self._symbol,
                     instrument_type=self._instrument_type, direction=self._direction,
                     strategy_version=self._version)
        self._eligibility_owner = HodCompRsEligibilityMachine(
            policy=self._eligibility_policy, **scope)
        self._trigger_owner = HodCompRsTriggerMachine(policy=self._trigger_policy, **scope)
        self._pending: tuple[tuple[object, StrategyStateTransition], ...] = ()
        self._count = 0
        self._time: datetime | None = None
        self._crossed_at: datetime | None = None
        self._noticed: FrozenStructure | None = None
        self._proposed_notice: FrozenStructure | None = None
        self._eligibility: RsTrendAssessment | None = None
        self._notice: HeadsUpAssessment | None = None
        self._trigger: TriggerAssessment | None = None
        self._outcome: HodCompRsOutcome | None = None
        self._notes: tuple[str, ...] = ()

    # --- one supplied evaluation -------------------------------------------

    def update(self, context: StrategyContext) -> tuple[StrategyStateTransition, ...]:
        self._check(context)
        self._confirm_recorded_before(context)
        step = self._step(context.evaluated_at)
        self._eligibility, self._notice, self._trigger = None, None, None
        self._outcome, self._notes = None, ()
        if self.current_state() == EXPIRED:
            self._notes = ("SESSION_EXPIRED",)
            return ()
        if self._structure_open():
            return self._advance_structure(context, step)
        if self._trigger_owner.current_state() == NOTICED:
            return self._advance_notice(context, step)
        return self._advance_eligibility(context, step)

    def heads_up(self) -> AlertCandidate | None:
        """Candidate assembly keeps its M4.5 owner; this owner assembles none."""
        return None

    def actionable(self) -> AlertCandidate | None:
        """Candidate assembly keeps its M4.5 owner; this owner assembles none."""
        return None

    def invalidate(self, context: StrategyContext, *, reason: str
                   ) -> tuple[StrategyStateTransition, ...]:
        """Refused: M7.3 derives invalidation from supplied evidence in `update`."""
        self._check(context)
        _label(reason, "invalidation reason")
        raise RecordError(
            "M7.3 invalidation follows the supplied structure evidence, not a caller assertion")

    def expire(self, context: StrategyContext, *, reason: str
               ) -> tuple[StrategyStateTransition, ...]:
        """Expire one open structure; eligibility expiry follows its own window."""
        self._check(context)
        self._confirm_recorded_before(context)
        if not self._structure_open():
            raise RecordError(
                "M7.2 expiry follows the supplied evaluation window, not a caller assertion")
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

    def _step(self, at: datetime) -> HodCompRsReplayStep:
        step = self._steps.get(at)
        if step is None:
            raise RecordError("no supplied replay step for this evaluation instant")
        return step

    def _structure_open(self) -> bool:
        return self._trigger_owner.current_structure() is not None

    def _propose(self, owner, build) -> tuple[StrategyStateTransition, ...]:
        record_id = "%s-%03d" % (self._prefix, self._count + 1)
        changes = build(record_id)
        if changes:
            self._count += 1
            self._pending = ((owner, changes[0]),)
        return changes

    def _assess_eligibility(self, context: StrategyContext,
                            step: HodCompRsReplayStep) -> RsTrendAssessment:
        """Evaluate the supplied M7.2 gates without advancing that owner.

        Once a notice or a structure stands, the M7.3 owner holds the state; the
        eligibility assessment is still required at every instant, because it is
        the mandatory input the notice and the structure read.
        """
        assessment = evaluate_rs_trend_eligibility(
            RsTrendRequest(context, self._eligibility_policy, step.status))
        self._eligibility = assessment
        return assessment

    def _freeze(self, inputs: StructureInputs) -> FrozenStructure:
        return freeze_structure(
            self._trigger_policy, direction=self._direction, frozen_at=inputs.frozen_at,
            reference_extreme=inputs.reference_extreme,
            compression_high=inputs.compression_high, compression_low=inputs.compression_low,
            latest_atr=inputs.latest_atr, anchor_bar_id=inputs.anchor_bar_id,
            structure_number=self._trigger_owner.pending_structure_number,
            input_record_ids=inputs.input_record_ids)

    def _same_as_noticed(self, frozen: FrozenStructure) -> FrozenStructure:
        """Refuse a supplied structure that is not the one the notice described.

        The heads-up already reported an approaching boundary. A later step that
        supplies changed prices or a changed ATR describes a different structure,
        and accepting it would move the boundary this owner acted on.
        """
        noticed = self._noticed
        if noticed is None:
            return frozen
        changed = tuple(name for name in STRUCTURE_IDENTITY
                        if getattr(frozen, name) != getattr(noticed, name))
        if changed:
            raise RecordError("the noticed frozen structure cannot change after a heads-up: "
                              + ",".join(changed))
        return frozen

    def _advance_eligibility(self, context: StrategyContext, step: HodCompRsReplayStep
                             ) -> tuple[StrategyStateTransition, ...]:
        request = RsTrendRequest(context, self._eligibility_policy, step.status)
        held: list[RsTrendAssessment] = []

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
        return self._advance_structure_start(context, step, held[0])

    def _advance_notice(self, context: StrategyContext, step: HodCompRsReplayStep
                        ) -> tuple[StrategyStateTransition, ...]:
        return self._advance_structure_start(context, step, self._assess_eligibility(context, step))

    def _advance_structure_start(self, context: StrategyContext, step: HodCompRsReplayStep,
                                 assessment: RsTrendAssessment
                                 ) -> tuple[StrategyStateTransition, ...]:
        """One armed instant with no open structure: cross it, or notice it."""
        if step.crossing is not None:
            return self._open_structure(context, step.crossing)
        if step.structure is None:
            self._notes = ("NO_SUPPLIED_STRUCTURE",)
            return ()
        return self._propose_notice(context, step, assessment)

    def _propose_notice(self, context: StrategyContext, step: HodCompRsReplayStep,
                        assessment: RsTrendAssessment) -> tuple[StrategyStateTransition, ...]:
        frozen = self._same_as_noticed(self._freeze(step.structure))
        request = HeadsUpRequest(
            structure=frozen, policy=self._trigger_policy,
            evaluated_at=context.evaluated_at, eligibility=assessment,
            distance=step.distance, last_trade=step.last_trade)
        held: list[HeadsUpAssessment] = []

        def build(record_id: str) -> tuple[StrategyStateTransition, ...]:
            notice, changes = self._trigger_owner.propose_heads_up(request, record_id=record_id)
            held.append(notice)
            return changes

        changes = self._propose(self._trigger_owner, build)
        self._notice = held[0]
        if changes and held[0].state == NOTICED:
            # Kept only once the caller records it, like every other advance here.
            self._proposed_notice = frozen
        if not changes:
            self._notes = ("NO_STATE_CHANGE:" + str(held[0].state.substate),)
        return changes

    def _open_structure(self, context: StrategyContext, crossing: CrossingInputs
                        ) -> tuple[StrategyStateTransition, ...]:
        at = context.evaluated_at
        if crossing.current.observed_at != at:
            raise RecordError("the crossing observation must belong to this evaluation instant")
        frozen = self._same_as_noticed(self._freeze(crossing.structure))
        result = evaluate_crossing(self._trigger_policy, self._direction,
                                   boundary=frozen.boundary, previous=crossing.previous,
                                   current=crossing.current)
        if result.status != CROSSED:
            self._notes = ("CROSSING:" + result.status + ":" + str(result.reason),)
            return ()
        quota = self._trigger_owner.structure_quota(at)
        if quota.status != PASS:
            self._notes = ("STRUCTURE_QUOTA:" + str(quota.reason),)
            return ()
        changes = self._propose(self._trigger_owner, lambda record_id:
                                self._trigger_owner.open_crossing(frozen, crossed_at=at,
                                                                  record_id=record_id))
        if changes:
            self._crossed_at = at
        return changes

    def _advance_structure(self, context: StrategyContext, step: HodCompRsReplayStep
                           ) -> tuple[StrategyStateTransition, ...]:
        structure = self._trigger_owner.current_structure()
        if step.reset_close is not None:
            return self._propose(self._trigger_owner, lambda record_id:
                                 self._trigger_owner.reset(step.reset_close,
                                                           at=context.evaluated_at,
                                                           record_id=record_id))
        assessment = self._assess_eligibility(context, step)
        request = TriggerRequest(
            structure=structure, policy=self._trigger_policy,
            evaluated_at=context.evaluated_at, crossed_at=self._crossed_at,
            observations=step.observations, intensity=step.intensity,
            last_trade=step.last_trade, eligibility=assessment, extension=step.extension,
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

    def _compose(self, step: HodCompRsReplayStep, assessment: TriggerAssessment) -> None:
        if step.structural is None or step.confidence is None:
            return
        self._outcome = compose_hod_comp_rs_outcome(HodCompRsOutcomeRequest(
            assessment=assessment, structural=step.structural, confidence=step.confidence,
            suppression=self._suppression_policy, history=step.history,
            strategy_version=self._version, definition_reference=self._definition))


__all__ = [
    "ARMED", "CrossingInputs", "DATA_MODE", "EXPIRED", "HodCompRsReplayStep",
    "HodCompRsReplayStrategy", "NOTICED", "REPLAY_VERSION", "RULES_VERSION", "STRATEGY_ID",
    "STRUCTURE_IDENTITY", "StructureInputs", "hod_comp_rs_replay_rules",
]
