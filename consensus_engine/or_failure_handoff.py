"""M8.1 offline ORB-to-failure handoff support over supplied records.

This is shared support, not the `OR_FAILURE_REV` strategy. It answers one
question from records the caller already holds: may a supplied opening-range
break that ended without acceptance hand its structure over to a
failure/reversal owner, and in which direction? The M3.6 opening range, the M6.2
attempt records and the M4.2 transition engine are reused exactly as they are.

The caller supplies every threshold. PLAYBOOKS section 13 still owns the
unresolved `OR_FAILURE_REV` questions - meaningful excursion versus a one-tick
break, the failure timer origin, the inside-acceptance window, the mandatory
close, and reversal ownership after an ORB - and M0.3B is PROPOSED, so this
module adopts no number of its own and names no rule of its own.

Reporting FAILURE_FORMING means the supplied facts supported a handoff at one
evaluation instant. It is not an alert, an approved rule, evidence of provider
coverage, or permission to act. ARMED, the actionable trigger, the stop, the
targets, the score and delivery all stay with M8.2 and the existing M4.x owners.
Nothing here reads a clock, fetches data, opens a database, stores a record or
sends anything.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json

from .opening_range_features import FEATURE_VERSION as OPENING_RANGE_VERSION
from .orb5_trigger import FrozenCandidate, MinuteClose, TriggerAssessment
from .state_transitions import TransitionRules
from .strategy_interface import StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import (
    FeatureSnapshot, RecordError, SessionRecord, SourceMetadata, StrategyStateTransition,
)
from .utils.time_context import as_utc


HANDOFF_VERSION = "M81_OR_FAILURE_HANDOFF_V1"
RULES_VERSION = "M81_OR_FAILURE_HANDOFF_RULES_V1"
STRATEGY_ID = "OR_FAILURE_REV"
SOURCE_ORB_STRATEGY_ID = "CRVOL_ORB5"
DATA_MODE = "SUPPLIED_OR_FAILURE_HANDOFF"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

BREAKOUT_ATTEMPT = "BREAKOUT_ATTEMPT"
FAILURE_FORMING = "FAILURE_FORMING"
STATES = ("WATCHING", "SETUP_FORMING", "INVALIDATED", "EXPIRED")
SUBSTATES = (BREAKOUT_ATTEMPT, FAILURE_FORMING)

ENDED_GATE = "ORB_ATTEMPT_ENDED"
OWNERSHIP_GATE = "REVERSAL_OWNERSHIP"
RANGE_GATE = "OPENING_RANGE_AGREEMENT"
EXCURSION_GATE = "REAL_BREAK_EXCURSION"
REACCEPTANCE_GATE = "REACCEPTANCE_INSIDE"
HANDOFF_GATES = (ENDED_GATE, OWNERSHIP_GATE, RANGE_GATE, EXCURSION_GATE, REACCEPTANCE_GATE)
# The supplied M6.2 attempt endings this support treats as a failed break. Any
# other ending, including a still-running or an already triggered attempt, keeps
# the reversal owner at WATCHING.
FAILED_BREAK_ENDINGS = ("INSIDE_OR_CLOSE_INVALIDATION", "ACCEPTANCE_DEADLINE_PASSED")
# Only these supplied facts end a taken-over handoff outright.
INVALIDATIONS = ("REACCEPTANCE_WINDOW_PASSED", "COVERAGE_LOST")

_ORB_ATTEMPT_GATE = "ATTEMPT_ACTIVE"
_RANGE_HIGH = "OPENING_RANGE_HIGH_5M_V1"
_RANGE_LOW = "OPENING_RANGE_LOW_5M_V1"
_RANGE_COMPLETE = "OPENING_RANGE_COMPLETE_5M_V1"


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")
    return value


def _threshold(value: object, name: str, *, positive: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    try:
        number = Fraction(str(value))
    except (ValueError, ArithmeticError) as exc:  # non-finite text is not a threshold
        raise RecordError(f"{name} must be finite") from exc
    if number < 0 or (positive and number <= 0):
        raise RecordError(f"{name} must be a supported threshold")
    return number


def _count(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise RecordError(f"{name} must be an integer of at least {minimum}")
    return value


def _flag(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise RecordError(f"{name} must be true or false")
    return value


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _seconds(first: datetime, second: datetime) -> Fraction:
    return Fraction(str((first - second).total_seconds()))


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1


def mirror_direction(direction: str) -> str:
    """The reversal direction of one supplied break direction.

    A failed upside break hands over to a short reversal owner, and a failed
    downside break to a long one. Nothing else about the reversal is decided.
    """
    if direction not in ("LONG", "SHORT"):
        raise RecordError("direction must be LONG or SHORT")
    return "SHORT" if direction == "LONG" else "LONG"


@dataclass(frozen=True)
class HandoffPolicy:
    """The caller's own excursion minimum, reacceptance window and ownership rule.

    Nothing is defaulted. The values describe the caller's own definition;
    supplying them neither adopts a proposed rule nor claims the referenced
    definition was approved.
    """

    version: str
    definition_reference: str
    minimum_excursion_atr_multiple: float
    reacceptance_window_seconds: int
    owns_after_alert_triggered: bool

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        _threshold(self.minimum_excursion_atr_multiple, "minimum_excursion_atr_multiple",
                   positive=True)
        _count(self.reacceptance_window_seconds, "reacceptance_window_seconds", minimum=1)
        _flag(self.owns_after_alert_triggered, "owns_after_alert_triggered")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version, "definition_reference": self.definition_reference,
            "minimum_excursion_atr_multiple": self.minimum_excursion_atr_multiple,
            "reacceptance_window_seconds": self.reacceptance_window_seconds,
            "owns_after_alert_triggered": self.owns_after_alert_triggered,
        }


@dataclass(frozen=True)
class BreakoutExtreme:
    """One supplied furthest traded price of the break, with its own coverage.

    An unknown price stays unknown: an absent extreme is never read as a small
    excursion, and it never becomes a passing gate.
    """

    record_id: str
    observed_at: datetime
    available_at: datetime
    price: float | None
    coverage_known: bool

    def __post_init__(self) -> None:
        _label(self.record_id, "breakout extreme record ID")
        for name in ("observed_at", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        _flag(self.coverage_known, "coverage_known")
        if self.price is not None:
            _threshold(self.price, "breakout extreme price", positive=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "observed_at": _text_time(self.observed_at),
            "available_at": _text_time(self.available_at), "price": self.price,
            "coverage_known": self.coverage_known,
        }


@dataclass(frozen=True)
class HandoffGate:
    name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in HANDOFF_GATES:
            raise RecordError("gate name is not supported")
        if self.status not in GATE_STATUSES:
            raise RecordError("gate status is not supported")
        if self.status != PASS and self.reason is None:
            raise RecordError("a gate that did not pass requires a reason")
        if self.reason is not None:
            _label(self.reason, "gate reason")
        if not isinstance(self.input_record_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.input_record_ids
        ):
            raise RecordError("gate input IDs must be non-empty strings")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "status": self.status, "observed": self.observed,
            "threshold": self.threshold, "reason": self.reason,
            "input_record_ids": list(self.input_record_ids),
        }


@dataclass(frozen=True)
class HandoffRequest:
    """One evaluation of one supplied ended ORB attempt for one reversal owner."""

    symbol: str
    instrument_type: str
    attempt: TriggerAssessment
    policy: HandoffPolicy
    evaluated_at: datetime
    opening_range: FeatureSnapshot | None = None
    breakout_extreme: BreakoutExtreme | None = None
    minute_close: MinuteClose | None = None
    attempt_reached_alert: bool = False

    def __post_init__(self) -> None:
        _label(self.symbol, "symbol")
        if self.instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("underlying must be EQUITY or ETF")
        if not isinstance(self.attempt, TriggerAssessment):
            raise RecordError("attempt must be the supplied M6.2 TriggerAssessment")
        if not isinstance(self.policy, HandoffPolicy):
            raise RecordError("policy must be HandoffPolicy")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if self.evaluated_at < self.attempt.evaluated_at:
            raise RecordError("the handoff cannot be evaluated before the attempt it reads")
        if self.opening_range is not None and not isinstance(self.opening_range, FeatureSnapshot):
            raise RecordError("opening range must be the supplied M3.6 FeatureSnapshot or null")
        if self.breakout_extreme is not None and not isinstance(
                self.breakout_extreme, BreakoutExtreme):
            raise RecordError("breakout extreme must be BreakoutExtreme or null")
        if self.minute_close is not None and not isinstance(self.minute_close, MinuteClose):
            raise RecordError("reacceptance close must be the supplied M6.2 MinuteClose or null")
        _flag(self.attempt_reached_alert, "attempt_reached_alert")

    @property
    def candidate(self) -> FrozenCandidate:
        return self.attempt.candidate

    @property
    def direction(self) -> str:
        """The reversal direction this handoff would open."""
        return mirror_direction(self.attempt.candidate.direction)


@dataclass(frozen=True)
class HandoffAssessment:
    """Immutable result of one evaluation; the caller owns storage and delivery."""

    evaluated_at: datetime
    state: StrategyState
    direction: str
    gates: tuple[HandoffGate, ...]
    reasons: tuple[str, ...]
    candidate: FrozenCandidate
    excursion: float | None
    required_excursion: float
    reacceptance_seconds: float | None
    policy_version: str
    definition_reference: str

    def gate(self, name: str) -> HandoffGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        return {
            "handoff_version": HANDOFF_VERSION, "evaluated_at": _text_time(self.evaluated_at),
            "state": self.state.state, "substate": self.state.substate,
            "direction": self.direction, "break_direction": self.candidate.direction,
            "gates": [row.as_dict() for row in self.gates], "reasons": list(self.reasons),
            "candidate": self.candidate.as_dict(), "excursion": self.excursion,
            "required_excursion": self.required_excursion,
            "reacceptance_seconds": self.reacceptance_seconds,
            "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def handoff_rules() -> TransitionRules:
    """Exactly the M8.1 handoff states, stopping before `OR_FAILURE_REV` ARMED.

    The PLAYBOOKS section 5 chain continues `FAILURE_FORMING -> ARMED ->
    ALERT_TRIGGERED`. Those two belong to M8.2 with the unresolved thresholds, so
    no rule here can reach them.
    """
    watching = StrategyState("WATCHING")
    attempt = StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
    failing = StrategyState("SETUP_FORMING", FAILURE_FORMING)
    invalidated = StrategyState("INVALIDATED")
    expired = StrategyState("EXPIRED")
    allowed = (
        (watching, attempt), (attempt, failing),
        (attempt, invalidated), (failing, invalidated), (invalidated, watching),
    )
    return TransitionRules(RULES_VERSION, watching, allowed + tuple(
        (state, expired) for state in (watching, attempt, failing, invalidated)))


def _attempt_ended(request: HandoffRequest) -> HandoffGate:
    """Whether the supplied M6.2 attempt already ended as a failed break."""
    name = ENDED_GATE
    assessment = request.attempt
    if assessment.candidate.direction not in ("LONG", "SHORT"):
        raise RecordError("the supplied attempt has no usable break direction")
    gate = next((row for row in assessment.gates if row.name == _ORB_ATTEMPT_GATE), None)
    if gate is None:
        return HandoffGate(name, UNKNOWN, reason="ORB_ATTEMPT_END_UNKNOWN")
    if gate.status == UNKNOWN:
        return HandoffGate(name, UNKNOWN, reason="ORB_ATTEMPT_END_" + str(gate.reason))
    if gate.status == PASS:
        return HandoffGate(name, FAIL, reason="ORB_ATTEMPT_STILL_OPEN")
    if gate.reason not in FAILED_BREAK_ENDINGS:
        return HandoffGate(name, FAIL, reason="ORB_ATTEMPT_END_" + str(gate.reason))
    return HandoffGate(name, PASS, reason=None, input_record_ids=gate.input_record_ids)


def _ownership(request: HandoffRequest) -> HandoffGate:
    """Whether the caller's own policy takes this ending's reversal.

    PLAYBOOKS section 13 leaves reversal ownership after an ORB unresolved, so an
    attempt that already reached ALERT_TRIGGERED is refused unless the caller
    explicitly owns that case in its own definition.
    """
    if request.attempt_reached_alert and not request.policy.owns_after_alert_triggered:
        return HandoffGate(OWNERSHIP_GATE, FAIL, reason="REVERSAL_AFTER_ALERT_NOT_OWNED")
    return HandoffGate(OWNERSHIP_GATE, PASS)


def _opening_range(request: HandoffRequest) -> HandoffGate:
    """Whether the supplied M3.6 range is complete and matches the frozen attempt."""
    name = RANGE_GATE
    snapshot = request.opening_range
    if snapshot is None:
        return HandoffGate(name, UNKNOWN, reason="MISSING_OPENING_RANGE")
    ids = (snapshot.record_id,)
    if snapshot.feature_version != OPENING_RANGE_VERSION:
        return HandoffGate(name, FAIL, reason="INCOMPATIBLE_OPENING_RANGE_VERSION",
                           input_record_ids=ids)
    if (snapshot.metadata.instrument_id != request.symbol
            or snapshot.metadata.instrument_type != request.instrument_type):
        return HandoffGate(name, FAIL, reason="OPENING_RANGE_IDENTITY_MISMATCH",
                           input_record_ids=ids)
    if snapshot.metadata.available_time > request.evaluated_at:
        return HandoffGate(name, UNKNOWN, reason="OPENING_RANGE_NOT_YET_AVAILABLE",
                           input_record_ids=ids)
    values = {row.name: row for row in snapshot.features}
    complete = values.get(_RANGE_COMPLETE)
    high, low = values.get(_RANGE_HIGH), values.get(_RANGE_LOW)
    if complete is None or high is None or low is None:
        return HandoffGate(name, UNKNOWN, reason="OPENING_RANGE_VALUES_ABSENT",
                           input_record_ids=ids)
    if high.value is None or low.value is None or complete.value != 1:
        reason = high.missing_reason or low.missing_reason or "INCOMPLETE"
        return HandoffGate(name, UNKNOWN, reason="OPENING_RANGE_" + reason,
                           input_record_ids=ids)
    candidate = request.candidate
    if (Fraction(str(high.value)) != Fraction(str(candidate.opening_range_high))
            or Fraction(str(low.value)) != Fraction(str(candidate.opening_range_low))):
        return HandoffGate(name, FAIL, reason="OPENING_RANGE_DISAGREEMENT",
                           input_record_ids=ids)
    return HandoffGate(name, PASS, input_record_ids=ids)


def _excursion(request: HandoffRequest) -> tuple[HandoffGate, Fraction | None, Fraction]:
    """Whether the supplied extreme is a real break by the caller's own minimum."""
    name = EXCURSION_GATE
    candidate, policy = request.candidate, request.policy
    required = (_threshold(policy.minimum_excursion_atr_multiple,
                           "minimum_excursion_atr_multiple", positive=True)
                * _threshold(candidate.frozen_atr, "frozen_atr"))
    extreme = request.breakout_extreme
    if extreme is None:
        return HandoffGate(name, UNKNOWN, None, float(required),
                           "MISSING_BREAKOUT_EXTREME"), None, required
    ids = (extreme.record_id,)
    if not extreme.coverage_known:
        return HandoffGate(name, FAIL, None, float(required), "COVERAGE_LOST", ids), None, required
    if extreme.available_at > request.evaluated_at:
        return HandoffGate(name, UNKNOWN, None, float(required),
                           "BREAKOUT_EXTREME_NOT_AVAILABLE", ids), None, required
    if extreme.observed_at < candidate.crossed_at:
        return HandoffGate(name, FAIL, None, float(required),
                           "BREAKOUT_EXTREME_BEFORE_CROSSING", ids), None, required
    if extreme.price is None:
        return HandoffGate(name, UNKNOWN, None, float(required),
                           "UNKNOWN_BREAKOUT_EXTREME", ids), None, required
    sign = _sign(candidate.direction)
    price = Fraction(str(extreme.price))
    edge = Fraction(str(candidate.opening_range_high if candidate.direction == "LONG"
                        else candidate.opening_range_low))
    excursion = sign * (price - edge)
    beyond = sign * (price - Fraction(str(candidate.boundary)))
    if beyond <= 0:
        return (HandoffGate(name, FAIL, float(excursion), float(required),
                            "BREAK_NOT_BEYOND_BOUNDARY", ids), excursion, required)
    if excursion < required:
        return (HandoffGate(name, FAIL, float(excursion), float(required),
                            "EXCURSION_BELOW_SUPPLIED_MINIMUM", ids), excursion, required)
    return HandoffGate(name, PASS, float(excursion), float(required), None, ids), excursion, required


def _reacceptance(request: HandoffRequest) -> tuple[HandoffGate, Fraction | None]:
    """Whether a supplied final close came back inside the range in the caller's window."""
    name = REACCEPTANCE_GATE
    candidate, policy = request.candidate, request.policy
    window = _threshold(policy.reacceptance_window_seconds, "reacceptance_window_seconds",
                        positive=True)
    close = request.minute_close
    if close is None:
        return HandoffGate(name, UNKNOWN, None, float(window), "MISSING_REACCEPTANCE_CLOSE"), None
    ids = (close.record_id,)
    if not close.coverage_known:
        return HandoffGate(name, FAIL, None, float(window), "COVERAGE_LOST", ids), None
    if close.available_at > request.evaluated_at:
        return HandoffGate(name, UNKNOWN, None, float(window),
                           "REACCEPTANCE_NOT_AVAILABLE", ids), None
    if not close.final:
        return HandoffGate(name, UNKNOWN, None, float(window), "MINUTE_BAR_PENDING", ids), None
    if close.bar_end <= candidate.crossed_at:
        return HandoffGate(name, FAIL, None, float(window),
                           "REACCEPTANCE_BEFORE_CROSSING", ids), None
    elapsed = _seconds(close.bar_end, candidate.crossed_at)
    price = Fraction(str(close.close))
    inside = (Fraction(str(candidate.opening_range_low)) < price
              < Fraction(str(candidate.opening_range_high)))
    if not inside:
        return HandoffGate(name, FAIL, float(elapsed), float(window),
                           "CLOSE_NOT_BACK_INSIDE_RANGE", ids), elapsed
    if elapsed > window:
        return HandoffGate(name, FAIL, float(elapsed), float(window),
                           "REACCEPTANCE_WINDOW_PASSED", ids), elapsed
    return HandoffGate(name, PASS, float(elapsed), float(window), None, ids), elapsed


def evaluate_or_failure_handoff(request: HandoffRequest) -> HandoffAssessment:
    """Report every supplied handoff gate and the state they support, with no side effect.

    FAILURE_FORMING describes the supplied records at this instant only. It opens
    no reversal setup by itself: ARMED, the actionable trigger, the stop, the
    targets, the score and delivery stay with M8.2 and the M4.x owners.
    """
    if not isinstance(request, HandoffRequest):
        raise RecordError("HandoffRequest is required")
    ended, ownership = _attempt_ended(request), _ownership(request)
    opening = _opening_range(request)
    excursion_gate, excursion, required = _excursion(request)
    reacceptance, elapsed = _reacceptance(request)
    gates = (ended, ownership, opening, excursion_gate, reacceptance)
    if any(row.status != PASS for row in (ended, ownership, opening, excursion_gate)):
        state = StrategyState("WATCHING")
    elif reacceptance.reason in INVALIDATIONS:
        state = StrategyState("INVALIDATED")
    elif reacceptance.status == PASS:
        state = StrategyState("SETUP_FORMING", FAILURE_FORMING)
    else:
        state = StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    return HandoffAssessment(
        request.evaluated_at, state, request.direction, gates, reasons, request.candidate,
        None if excursion is None else float(excursion), float(required),
        None if elapsed is None else float(elapsed),
        request.policy.version, request.policy.definition_reference)


class OrFailureHandoffMachine:
    """One serially owned `(session, symbol, reversal direction)` handoff owner.

    The machine proposes canonical transitions for the M4.2 engine; it never
    writes, sends or advances itself. Local state moves only when the caller
    confirms a proposed transition after storage acknowledged it. The taken-over
    attempt is held here, so the frozen range and boundary a recorded handoff
    stood on cannot be walked and one ended attempt cannot be handed over twice.
    """

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, policy: HandoffPolicy):
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        if not isinstance(policy, HandoffPolicy):
            raise RecordError("policy must be HandoffPolicy")
        if instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("underlying must be EQUITY or ETF")
        if direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if STRATEGY_ID not in STRATEGY_IDS:  # keeps the shared ID list authoritative
            raise RecordError("strategy ID is not supported")
        self._session = session
        self._symbol = _label(symbol, "symbol")
        self._instrument_type = instrument_type
        self._direction = direction
        self._version = _label(strategy_version, "strategy version")
        self._policy = policy
        self._rules = handoff_rules()
        self._state = self._rules.initial_state
        self._candidate: FrozenCandidate | None = None
        self._closed: tuple[tuple[str, int, str], ...] = ()
        self._time: datetime | None = None
        self._pending: tuple[StrategyStateTransition, ...] = ()
        self._effect: tuple[str, object] | None = None

    strategy_id = STRATEGY_ID
    source_strategy_id = SOURCE_ORB_STRATEGY_ID

    @property
    def strategy_version(self) -> str:
        return self._version

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def rules(self) -> TransitionRules:
        return self._rules

    @property
    def closed_attempts(self) -> tuple[tuple[str, int, str], ...]:
        """Every ORB attempt key this owner already finished with."""
        return self._closed

    def current_state(self) -> StrategyState:
        return self._state

    def current_candidate(self) -> FrozenCandidate | None:
        return self._candidate

    @staticmethod
    def attempt_key(candidate: FrozenCandidate) -> tuple[str, int, str]:
        if not isinstance(candidate, FrozenCandidate):
            raise RecordError("candidate must be FrozenCandidate")
        return (candidate.direction, candidate.attempt_number, _text_time(candidate.crossed_at))

    def _metadata(self, at: datetime) -> SourceMetadata:
        return SourceMetadata(
            instrument_id=self._symbol, instrument_type=self._instrument_type,
            source="DERIVED_M81", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID")

    def _transition(self, *, record_id: str, at: datetime, state: StrategyState, reason: str,
                    previous: StrategyState, input_record_ids: tuple[str, ...] = (),
                    ) -> StrategyStateTransition:
        _label(record_id, "transition record ID")
        if (previous, state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M8.1 rules")
        return StrategyStateTransition(
            record_id=record_id, metadata=self._metadata(at), strategy_id=STRATEGY_ID,
            strategy_version=self._version, occurred_at=at,
            from_state=previous.state, from_substate=previous.substate,
            to_state=state.state, to_substate=state.substate, reason=reason,
            feature_snapshot_id=None, input_record_ids=input_record_ids)

    def _forward(self, at: datetime) -> None:
        if self._time is not None and at < self._time:
            raise RecordError("evaluation time cannot move backward")
        self._time = at

    def propose(self, request: HandoffRequest, *, record_id: str,
                staged_record_id: str | None = None,
                ) -> tuple[HandoffAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transitions a caller must store first.

        A first evaluation that already reports the reacceptance needs both the
        opening `BREAKOUT_ATTEMPT` step and the `FAILURE_FORMING` step, so the
        recorded history always shows the break before its failure. That second
        step needs its own `staged_record_id`; nothing is invented here.
        """
        if not isinstance(request, HandoffRequest):
            raise RecordError("HandoffRequest is required")
        if request.symbol != self._symbol or request.instrument_type != self._instrument_type:
            raise RecordError("evaluation does not match this handoff owner")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if request.direction != self._direction:
            raise RecordError("the supplied break does not reverse into this owner's direction")
        key = self.attempt_key(request.candidate)
        if self._candidate is not None and request.candidate != self._candidate:
            raise RecordError("a different ORB attempt cannot replace the one already taken over")
        if self._candidate is None and key in self._closed:
            raise RecordError("this ORB attempt was already handed over once")
        assessment = evaluate_or_failure_handoff(request)
        self._forward(request.evaluated_at)
        target = assessment.state
        if self._state.state == "SETUP_FORMING" and target.state == "WATCHING":
            # Ownership already recorded cannot silently vanish when a supplied
            # input stops supporting it; it is closed explicitly instead.
            target = StrategyState("INVALIDATED")
        if (self._state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
                and target == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)):
            raise RecordError("a handed-over failure cannot fall back to the breakout attempt")
        if self._state == StrategyState("INVALIDATED") and target.state == "SETUP_FORMING":
            raise RecordError("a closed handoff must be released before another attempt")
        if target == self._state:
            self._pending, self._effect = (), None
            return assessment, ()
        reason = (assessment.reasons[0] if assessment.reasons
                  else "ALL_SUPPLIED_HANDOFF_GATES_PASSED")
        ids = tuple(sorted({value for row in assessment.gates
                            for value in row.input_record_ids}))
        opening = StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
        staged = (self._state == StrategyState("WATCHING") and target != opening
                  and target.state != "EXPIRED")
        changes: tuple[StrategyStateTransition, ...] = ()
        previous = self._state
        if staged:
            if staged_record_id is None:
                raise RecordError("this evaluation advances two states and needs a second ID")
            changes += (self._transition(record_id=record_id, at=request.evaluated_at,
                                         state=opening, reason="ORB_BREAK_HANDED_OVER",
                                         previous=previous, input_record_ids=ids),)
            previous = opening
        elif staged_record_id is not None:
            raise RecordError("a single-step evaluation cannot use a second transition ID")
        changes += (self._transition(
            record_id=staged_record_id if staged else record_id, at=request.evaluated_at,
            state=target, reason=reason, previous=previous, input_record_ids=ids),)
        self._pending = changes
        if target.state in ("INVALIDATED", "EXPIRED"):
            self._effect = ("CLOSE", key)
        elif target.state == "SETUP_FORMING":
            self._effect = ("TAKE", request.candidate)
        else:
            self._effect = ("RELEASE", None)
        return assessment, changes

    def release(self, *, at: datetime, record_id: str) -> tuple[StrategyStateTransition, ...]:
        """Propose the return to WATCHING after a closed handoff, keeping its key."""
        instant = _instant(at, "release time")
        if self._state != StrategyState("INVALIDATED"):
            raise RecordError("only a closed handoff can be released")
        self._forward(instant)
        transition = self._transition(record_id=record_id, at=instant,
                                      state=StrategyState("WATCHING"),
                                      reason="HANDOFF_RELEASED", previous=self._state)
        self._pending, self._effect = (transition,), ("RELEASE", None)
        return (transition,)

    def expire(self, *, at: datetime, reason: str, record_id: str,
               ) -> tuple[StrategyStateTransition, ...]:
        """Propose expiry of this owner at the caller's own session end."""
        instant = _instant(at, "expiry time")
        self._forward(instant)
        transition = self._transition(record_id=record_id, at=instant,
                                      state=StrategyState("EXPIRED"),
                                      reason=_label(reason, "expiry reason"),
                                      previous=self._state)
        self._pending = (transition,)
        self._effect = ("CLOSE", None if self._candidate is None
                        else self.attempt_key(self._candidate))
        return (transition,)

    def confirm(self, *transitions: StrategyStateTransition) -> StrategyState:
        """Advance only after every proposed transition was durably recorded."""
        if not self._pending or transitions != self._pending:
            raise RecordError("only the pending recorded transitions can advance this owner")
        kind, payload = self._effect
        self._state = StrategyState(transitions[-1].to_state, transitions[-1].to_substate)
        if kind == "TAKE":
            self._candidate = payload
        elif kind == "CLOSE":
            if payload is not None and payload not in self._closed:
                self._closed += (payload,)
            self._candidate = None
        self._pending, self._effect = (), None
        return self._state

    def restore(self, state: StrategyState, *, candidate: FrozenCandidate | None = None,
                closed_attempts: tuple[tuple[str, int, str], ...] = ()) -> StrategyState:
        """Position an unused owner at facts recovered from storage (M5.5).

        Every fact is restored explicitly. Nothing is inferred from the state
        alone, so a recovered owner cannot silently retake a finished attempt.
        """
        if self._pending or self._time is not None or self._candidate is not None:
            raise RecordError("restore requires an unused handoff owner")
        if not isinstance(state, StrategyState) or state.state not in STATES:
            raise RecordError("restored state is not an M8.1 state")
        if state.substate not in (None, *SUBSTATES):
            raise RecordError("restored substate is not an M8.1 substate")
        if candidate is not None and not isinstance(candidate, FrozenCandidate):
            raise RecordError("restored candidate must be FrozenCandidate or null")
        if not isinstance(closed_attempts, tuple) or any(
            not isinstance(row, tuple) or len(row) != 3 for row in closed_attempts
        ):
            raise RecordError("restored closed attempts must be complete attempt keys")
        self._candidate = candidate
        self._closed = closed_attempts
        self._state = state
        return self._state


__all__ = [
    "BREAKOUT_ATTEMPT", "BreakoutExtreme", "DATA_MODE", "ENDED_GATE",
    "EXCURSION_GATE", "FAILED_BREAK_ENDINGS",
    "FAILURE_FORMING", "HANDOFF_GATES", "HANDOFF_VERSION", "HandoffAssessment", "HandoffGate",
    "HandoffPolicy", "HandoffRequest", "INVALIDATIONS", "OWNERSHIP_GATE",
    "OrFailureHandoffMachine", "RANGE_GATE", "REACCEPTANCE_GATE", "RULES_VERSION",
    "SOURCE_ORB_STRATEGY_ID", "STATES", "STRATEGY_ID",
    "SUBSTATES", "evaluate_or_failure_handoff", "handoff_rules", "mirror_direction",
]
