"""M8.6 offline replay owner for `FIRST_PULLBACK_VWAP` over supplied scenario inputs.

This module adds no rule of its own. It is the M4.1 strategy adapter that lets
the M5.3 replay runner drive the already-proved M8.4 `FirstPullbackVwapMachine`
through one chronological sequence of supplied evaluation instants, mirroring
the pattern `orb5_replay.py`/M6.4 and `hod_comp_rs_replay.py`/M7.5 already used
for the first two playbooks. Every threshold, supplied M8.3 measurement, VWAP
context, relative-strength reading, observation, quote decision, structural
measurement and confidence result is supplied by the caller for one exact
instant: PLAYBOOKS sections 6 and 17's unresolved `FIRST_PULLBACK_VWAP`
questions and `M03B_HOD_COMP_RS_V1`/`M03B_ORB5_V1` stay exactly as M8.4 left
them, so a scenario must name its own definition reference. Nothing here reads
a clock, fetches data, opens a database, measures a leg, assembles an alert
candidate or delivers anything.

Replaying a scenario describes the supplied inputs at those instants only. It
is not a trigger, an approved rule, proof of bar, tape or quote coverage, a
backtest result, an edge claim or permission to act.

Unlike the first two playbooks, `FirstPullbackVwapMachine` holds one continuous
gate evaluation with no separate eligibility owner: `heads_up` and `actionable`
stay `None` for the same M4.5/M4.6 reason, and `invalidate`/`expire` keep the
same M8.4 boundary of never letting a caller assert an outcome the supplied
evidence did not produce. The frozen impulse window is fixed at construction, so
a scenario cannot walk it between steps any more than the machine itself allows.

State advances only after the caller records the proposed transition. `update`
returns the transitions to store and confirms them at the start of the next
evaluation, so a failed recording leaves this owner where it was.
"""

from dataclasses import dataclass
from datetime import datetime

from .confidence import ConfidenceResult
from .first_pullback_vwap import (
    FirstPullbackVwapMachine, PULLBACK_FORMING, PullbackAssessment, PullbackRequest,
    PullbackStructural, PullbackVwapPolicy, RelativeStrength, STRATEGY_ID, VwapContext,
    evaluate_first_pullback_vwap, pullback_rules,
)
from .impulse_pullback import PullbackPolicy
from .orb5_trigger import Observation
from .quote_events import QuoteEventDecision
from .state_transitions import TransitionRules
from .strategy_interface import RequiredData, Strategy, StrategyContext, StrategyState
from .trade_alerts_models import (
    AlertCandidate, ConfidenceBreakdown, FeatureSnapshot, RecordError, RiskLevel, SessionRecord,
    StrategyStateTransition, TargetLevel,
)
from .utils.time_context import as_utc


REPLAY_VERSION = "M86_FIRST_PULLBACK_VWAP_REPLAY_V1"
DATA_MODE = "SUPPLIED_REPLAY_INPUTS"
FORMING = StrategyState("SETUP_FORMING", PULLBACK_FORMING)


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


def first_pullback_vwap_replay_rules() -> TransitionRules:
    """Exactly the M8.4 rules; this owner adds no transition of its own."""
    return pullback_rules()


@dataclass(frozen=True)
class PullbackReplayStep:
    """Every supplied input for one exact evaluation instant.

    A field left null stays an explicit unknown for its own gate. Nothing here
    is carried over from an earlier instant, and no value is defaulted.
    """

    evaluated_at: datetime
    measurement: FeatureSnapshot
    atr_1m: float | None = None
    pullback_ordinal: int | None = None
    vwap: VwapContext | None = None
    relative_strength: RelativeStrength | None = None
    last_trade: Observation | None = None
    quote: QuoteEventDecision | None = None
    structural: PullbackStructural | None = None
    confidence: ConfidenceResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if not isinstance(self.measurement, FeatureSnapshot):
            raise RecordError("measurement must be the supplied M8.3 FeatureSnapshot")
        if self.atr_1m is not None and not isinstance(self.atr_1m, (int, float)):
            raise RecordError("atr_1m must be a number or null")
        if self.pullback_ordinal is not None and type(self.pullback_ordinal) is not int:
            raise RecordError("pullback_ordinal must be an integer or null")
        for name, expected in (("vwap", VwapContext), ("relative_strength", RelativeStrength),
                               ("last_trade", Observation), ("quote", QuoteEventDecision),
                               ("structural", PullbackStructural), ("confidence", ConfidenceResult)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, expected):
                raise RecordError(f"{name} must be its canonical record or null")


class FirstPullbackVwapReplayStrategy(Strategy):
    """One serially owned `(session, symbol, direction)` replay owner.

    The owner holds the M8.4 machine, which has no separate eligibility path: a
    supplied M8.3 measurement either forms, arms, triggers, invalidates or
    expires the pullback continuation inside one supplied evaluation. It
    proposes canonical transitions for the M4.2 engine and the M5.1 store; it
    never writes, sends or advances itself.
    """

    strategy_id = STRATEGY_ID

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 strategy_version: str, definition_reference: str, policy: PullbackVwapPolicy,
                 measurement_policy: PullbackPolicy, impulse_started_at: datetime,
                 impulse_frozen_at: datetime, steps: tuple[PullbackReplayStep, ...],
                 record_prefix: str):
        if not isinstance(policy, PullbackVwapPolicy):
            raise RecordError("policy must be PullbackVwapPolicy")
        if not isinstance(measurement_policy, PullbackPolicy):
            raise RecordError("measurement policy must be the supplied M8.3 PullbackPolicy")
        if instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("underlying must be EQUITY or ETF")
        if not isinstance(steps, tuple) or not steps:
            raise RecordError("replay requires a non-empty tuple of supplied steps")
        self._symbol = _label(symbol, "symbol")
        self._instrument_type = instrument_type
        self._version = _label(strategy_version, "strategy version")
        self._definition = _label(definition_reference, "definition reference")
        self._prefix = _label(record_prefix, "transition record prefix")
        self._policy = policy
        self._measurement_policy = measurement_policy
        self._impulse_started_at = _instant(impulse_started_at, "impulse_started_at")
        self._impulse_frozen_at = _instant(impulse_frozen_at, "impulse_frozen_at")
        if self._impulse_started_at >= self._impulse_frozen_at:
            raise RecordError("the impulse window must start before it freezes")
        supplied: dict[datetime, PullbackReplayStep] = {}
        previous: datetime | None = None
        for step in steps:
            if not isinstance(step, PullbackReplayStep):
                raise RecordError("replay steps must be PullbackReplayStep records")
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
    def direction(self) -> str:
        return self._policy.direction

    @property
    def rules(self) -> TransitionRules:
        return first_pullback_vwap_replay_rules()

    def required_data(self) -> tuple[RequiredData, ...]:
        """Named supplied inputs only; a declaration proves no availability."""
        return (
            RequiredData("PULLBACK_MEASUREMENT", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("VWAP_CONTEXT", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("RELATIVE_STRENGTH", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("ARM_OBSERVATION", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("SPREAD_QUOTE", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("RISK_TARGETS", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("CONFIDENCE", "MANDATORY", self._definition, DATA_MODE),
        )

    # --- supplied state -----------------------------------------------------

    def current_state(self) -> StrategyState:
        """The confirmed state; a proposed transition is not yet an advance."""
        return self._owner.current_state()

    def last_assessment(self) -> PullbackAssessment | None:
        return self._assessment

    def outcome(self) -> PullbackAssessment | None:
        """The latest evaluated M8.4 pullback result, when supplied."""
        return self._assessment

    def notes(self) -> tuple[str, ...]:
        """Why the latest evaluation proposed nothing, when it proposed nothing."""
        return self._notes

    def confirm_recorded(self) -> StrategyState:
        """Advance the owning machine once its proposed transition was stored."""
        if self._pending:
            self._owner.confirm(*self._pending)
        self._pending = ()
        return self.current_state()

    def reset(self, session: SessionRecord) -> None:
        """Start the supplied fixed session; earlier records are never mutated."""
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        self._session = session
        self._owner = FirstPullbackVwapMachine(
            session=session, symbol=self._symbol, instrument_type=self._instrument_type,
            strategy_version=self._version, policy=self._policy)
        self._pending: tuple[StrategyStateTransition, ...] = ()
        self._count = 0
        self._time: datetime | None = None
        self._assessment: PullbackAssessment | None = None
        self._notes: tuple[str, ...] = ()

    # --- one supplied evaluation -------------------------------------------

    def update(self, context: StrategyContext) -> tuple[StrategyStateTransition, ...]:
        self._check(context)
        self._confirm_recorded_before(context)
        step = self._step(context.evaluated_at)
        self._assessment, self._notes = None, ()
        if self.current_state() == StrategyState("EXPIRED"):
            self._notes = ("SESSION_EXPIRED",)
            return ()
        request = self._request(context, step)
        return self._propose(request)

    def heads_up(self) -> AlertCandidate | None:
        """Candidate assembly keeps its M4.5 owner; this owner assembles none."""
        return None

    def actionable(self) -> AlertCandidate | None:
        """Candidate assembly keeps its M4.5 owner; this owner assembles none."""
        return None

    def invalidate(self, context: StrategyContext, *, reason: str
                   ) -> tuple[StrategyStateTransition, ...]:
        """Refused: M8.4 derives invalidation from supplied evidence in `update`."""
        self._check(context)
        _label(reason, "invalidation reason")
        raise RecordError(
            "M8.4 invalidation follows the supplied pullback evidence, not a caller assertion")

    def expire(self, context: StrategyContext, *, reason: str
               ) -> tuple[StrategyStateTransition, ...]:
        """Expire this owner at the caller's own supplied session end."""
        self._check(context)
        self._confirm_recorded_before(context)
        record_id = self._next_id()
        changes = self._owner.expire(
            at=context.evaluated_at, reason=_label(reason, "expiry reason"), record_id=record_id)
        if changes:
            self._pending = changes
        return changes

    def confidence(self) -> ConfidenceBreakdown | None:
        return None if self._assessment is None else self._assessment.confidence

    def stop(self) -> RiskLevel | None:
        return None if self._assessment is None else self._assessment.risk

    def targets(self) -> tuple[TargetLevel, ...]:
        return () if self._assessment is None else self._assessment.targets

    # --- internals ----------------------------------------------------------

    def _check(self, context: StrategyContext) -> None:
        if not isinstance(context, StrategyContext):
            raise RecordError("context must be StrategyContext")
        if (context.session != self._session or context.symbol != self._symbol
                or context.instrument_type != self._instrument_type
                or context.direction != self._policy.direction):
            raise RecordError("evaluation does not match this replay owner")
        if self._time is not None and context.evaluated_at < self._time:
            raise RecordError("evaluation time cannot move backward")

    def _confirm_recorded_before(self, context: StrategyContext) -> None:
        self.confirm_recorded()
        self._time = context.evaluated_at

    def _step(self, at: datetime) -> PullbackReplayStep:
        step = self._steps.get(at)
        if step is None:
            raise RecordError("no supplied replay step for this evaluation instant")
        return step

    def _next_id(self) -> str:
        self._count += 1
        return "%s-%03d" % (self._prefix, self._count)

    def _request(self, context: StrategyContext, step: PullbackReplayStep) -> PullbackRequest:
        return PullbackRequest(
            measurement=step.measurement, measurement_policy=self._measurement_policy,
            policy=self._policy, evaluated_at=context.evaluated_at, symbol=self._symbol,
            strategy_version=self._version, definition_reference=self._definition,
            impulse_started_at=self._impulse_started_at, impulse_frozen_at=self._impulse_frozen_at,
            atr_1m=step.atr_1m, pullback_ordinal=step.pullback_ordinal, vwap=step.vwap,
            relative_strength=step.relative_strength, last_trade=step.last_trade,
            quote=step.quote, structural=step.structural, confidence=step.confidence)

    def _propose(self, request: PullbackRequest) -> tuple[StrategyStateTransition, ...]:
        assessment = evaluate_first_pullback_vwap(request)
        target = assessment.state
        initial = self._owner.rules.initial_state
        needs_two = self._owner.current_state() == initial and target.state == "ALERT_TRIGGERED"
        record_id = self._next_id()
        staged_id = self._next_id() if needs_two else None
        evaluated, changes = self._owner.propose(
            request, record_id=record_id, staged_record_id=staged_id)
        self._assessment = evaluated
        if changes:
            self._pending = changes
        else:
            self._notes = ("NO_STATE_CHANGE:" + evaluated.state.state,)
        return changes


__all__ = [
    "DATA_MODE", "FORMING", "FirstPullbackVwapReplayStrategy", "PullbackReplayStep",
    "REPLAY_VERSION", "first_pullback_vwap_replay_rules",
]
