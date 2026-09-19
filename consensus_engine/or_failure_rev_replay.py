"""M8.6 offline replay owner for `OR_FAILURE_REV` over supplied scenario inputs.

This module adds no rule of its own. It is the M4.1 strategy adapter that lets
the M5.3 replay runner drive the already-proved M8.2 `OrFailureRevMachine`
through one chronological sequence of supplied evaluation instants, mirroring
the pattern `orb5_replay.py`/M6.4 and `hod_comp_rs_replay.py`/M7.5 already used
for the first two playbooks. Every threshold, handed-over M8.1 handoff,
observation, confirmation, acceptance share, quote decision, structural
measurement and confidence result is supplied by the caller for one exact
instant: PLAYBOOKS section 5's unresolved `OR_FAILURE_REV` questions and
`M03B_ORB5_V1` stay exactly as M8.2 left them, so a scenario must name its own
definition reference. Nothing here reads a clock, fetches data, opens a
database, scores a setup, assembles an alert candidate or delivers anything.

Replaying a scenario describes the supplied inputs at those instants only. It
is not a trigger, an approved rule, proof of provider coverage, a backtest
result, an edge claim or permission to act.

Unlike the first two playbooks, `OrFailureRevMachine` holds one continuous gate
evaluation with no separate eligibility owner: `heads_up` and `actionable` stay
`None` for the same M4.5/M4.6 reason, and `invalidate`/`expire` keep the same
M8.2 boundary of never letting a caller assert an outcome the supplied evidence
did not produce.

State advances only after the caller records the proposed transition. `update`
returns the transitions to store and confirms them at the start of the next
evaluation, so a failed recording leaves this owner where it was.
"""

from dataclasses import dataclass
from datetime import datetime

from .confidence import ConfidenceResult
from .or_failure_handoff import FAILURE_FORMING, HandoffAssessment, STRATEGY_ID
from .or_failure_rev import (
    FailureBar, InsideAcceptance, OrFailureRevMachine, ReversalAssessment, ReversalPolicy,
    ReversalRequest, ReversalStructural, evaluate_or_failure_rev, reversal_rules,
)
from .orb5_trigger import MinuteClose, Observation
from .quote_events import QuoteEventDecision
from .state_transitions import TransitionRules
from .strategy_interface import RequiredData, Strategy, StrategyContext, StrategyState
from .trade_alerts_models import (
    AlertCandidate, ConfidenceBreakdown, RecordError, RiskLevel, SessionRecord,
    StrategyStateTransition, TargetLevel,
)
from .utils.time_context import as_utc


REPLAY_VERSION = "M86_OR_FAILURE_REV_REPLAY_V1"
DATA_MODE = "SUPPLIED_REPLAY_INPUTS"
FORMING = StrategyState("SETUP_FORMING", FAILURE_FORMING)


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


def or_failure_rev_replay_rules() -> TransitionRules:
    """Exactly the M8.2 rules; this owner adds no transition of its own."""
    return reversal_rules()


@dataclass(frozen=True)
class OrFailureRevReplayStep:
    """Every supplied input for one exact evaluation instant.

    A field left null stays an explicit unknown for its own gate. Nothing here
    is carried over from an earlier instant, and no value is defaulted.
    """

    evaluated_at: datetime
    handoff: HandoffAssessment
    breakout_extreme_price: float | None = None
    last_trade: Observation | None = None
    confirmation_close: MinuteClose | None = None
    failure_bar: FailureBar | None = None
    acceptance: InsideAcceptance | None = None
    quote: QuoteEventDecision | None = None
    structural: ReversalStructural | None = None
    confidence: ConfidenceResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if not isinstance(self.handoff, HandoffAssessment):
            raise RecordError("handoff must be the supplied M8.1 HandoffAssessment")
        if self.breakout_extreme_price is not None and not isinstance(
                self.breakout_extreme_price, (int, float)):
            raise RecordError("breakout_extreme_price must be a number or null")
        for name, expected in (("last_trade", Observation), ("confirmation_close", MinuteClose),
                               ("failure_bar", FailureBar), ("acceptance", InsideAcceptance),
                               ("quote", QuoteEventDecision), ("structural", ReversalStructural),
                               ("confidence", ConfidenceResult)):
            value = getattr(self, name)
            if value is not None and not isinstance(value, expected):
                raise RecordError(f"{name} must be its canonical record or null")


class OrFailureRevReplayStrategy(Strategy):
    """One serially owned `(session, symbol, reversal direction)` replay owner.

    The owner holds the M8.2 machine, which has no separate eligibility path: a
    handed-over M8.1 failure either forms, arms, triggers, invalidates or expires
    inside one supplied evaluation. It proposes canonical transitions for the
    M4.2 engine and the M5.1 store; it never writes, sends or advances itself.
    """

    strategy_id = STRATEGY_ID

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, definition_reference: str,
                 policy: ReversalPolicy, steps: tuple[OrFailureRevReplayStep, ...],
                 record_prefix: str):
        if not isinstance(policy, ReversalPolicy):
            raise RecordError("policy must be ReversalPolicy")
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
        self._policy = policy
        supplied: dict[datetime, OrFailureRevReplayStep] = {}
        previous: datetime | None = None
        for step in steps:
            if not isinstance(step, OrFailureRevReplayStep):
                raise RecordError("replay steps must be OrFailureRevReplayStep records")
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
        return or_failure_rev_replay_rules()

    def required_data(self) -> tuple[RequiredData, ...]:
        """Named supplied inputs only; a declaration proves no availability."""
        return (
            RequiredData("FAILURE_HANDOFF", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("LAST_TRADE", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("FAILURE_CONFIRMATION", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("INSIDE_ACCEPTANCE", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("SPREAD_QUOTE", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("RISK_TARGETS", "MANDATORY", self._definition, DATA_MODE),
            RequiredData("CONFIDENCE", "MANDATORY", self._definition, DATA_MODE),
        )

    # --- supplied state -----------------------------------------------------

    def current_state(self) -> StrategyState:
        """The confirmed state; a proposed transition is not yet an advance."""
        return self._owner.current_state()

    def last_assessment(self) -> ReversalAssessment | None:
        return self._assessment

    def outcome(self) -> ReversalAssessment | None:
        """The latest evaluated M8.2 reversal result, when supplied."""
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
        self._owner = OrFailureRevMachine(
            session=session, symbol=self._symbol, instrument_type=self._instrument_type,
            direction=self._direction, strategy_version=self._version, policy=self._policy)
        self._pending: tuple[StrategyStateTransition, ...] = ()
        self._count = 0
        self._time: datetime | None = None
        self._assessment: ReversalAssessment | None = None
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
        """Refused: M8.2 derives invalidation from supplied evidence in `update`."""
        self._check(context)
        _label(reason, "invalidation reason")
        raise RecordError(
            "M8.2 invalidation follows the supplied reversal evidence, not a caller assertion")

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
                or context.direction != self._direction):
            raise RecordError("evaluation does not match this replay owner")
        if self._time is not None and context.evaluated_at < self._time:
            raise RecordError("evaluation time cannot move backward")

    def _confirm_recorded_before(self, context: StrategyContext) -> None:
        self.confirm_recorded()
        self._time = context.evaluated_at

    def _step(self, at: datetime) -> OrFailureRevReplayStep:
        step = self._steps.get(at)
        if step is None:
            raise RecordError("no supplied replay step for this evaluation instant")
        return step

    def _next_id(self) -> str:
        self._count += 1
        return "%s-%03d" % (self._prefix, self._count)

    def _request(self, context: StrategyContext, step: OrFailureRevReplayStep) -> ReversalRequest:
        return ReversalRequest(
            handoff=step.handoff, policy=self._policy, evaluated_at=context.evaluated_at,
            strategy_version=self._version, definition_reference=self._definition,
            breakout_extreme_price=step.breakout_extreme_price, last_trade=step.last_trade,
            confirmation_close=step.confirmation_close, failure_bar=step.failure_bar,
            acceptance=step.acceptance, quote=step.quote, structural=step.structural,
            confidence=step.confidence)

    def _propose(self, request: ReversalRequest) -> tuple[StrategyStateTransition, ...]:
        assessment = evaluate_or_failure_rev(request)
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
    "DATA_MODE", "FORMING", "OrFailureRevReplayStep", "OrFailureRevReplayStrategy",
    "REPLAY_VERSION", "or_failure_rev_replay_rules",
]
