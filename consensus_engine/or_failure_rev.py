"""M8.2 offline `OR_FAILURE_REV` reversal trigger, risk and confidence at one instant.

This is the strategy that consumes the M8.1 handoff. M8.1 answers whether one
ended supplied opening-range break hands its structure over to a failure/reversal
owner; this module carries that handed-over structure the rest of the way named by
PLAYBOOKS section 5: `FAILURE_FORMING -> ARMED -> ALERT_TRIGGERED`, with the
actionable prior, the failure confirmation, the stop, the targets and the
confidence the caller already measured.

The caller supplies every threshold, every observation and every measured result.
PLAYBOOKS section 13 still owns the unresolved `OR_FAILURE_REV` questions - the
meaningful excursion, the failure timer origin, the inside-acceptance window, the
mandatory close versus the stronger failure-bar trigger, and reversal ownership
after an ORB - and M0.3B is PROPOSED, so this module adopts no number of its own,
applies no confidence cutoff and names no rule of its own. What no approved
definition supplies is reported in `unavailable` instead of being filled in.

ALERT_TRIGGERED means the supplied inputs passed every gate at one evaluation
instant. It is not an alert, an approved rule, proof of tape or quote coverage, a
backtest result or permission to act. A missing, stale, ambiguous or mismatched
input keeps the owner below the state it would otherwise reach; it never becomes a
passing gate. Nothing here reads a clock, fetches data, opens a database, stores a
record, assembles a candidate or sends anything: the alert candidate, the
suppression record, the options view and delivery keep their M4.5, M4.6 and M15
owners.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json

from .confidence import ConfidenceResult
from .or_failure_handoff import (
    FAILURE_FORMING, HandoffAssessment, STRATEGY_ID, mirror_direction,
)
from .orb5_trigger import FrozenCandidate, MODES, MinuteClose, Observation
from .quote_events import QuoteEventDecision
from .state_transitions import TransitionRules
from .strategy_interface import StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import (
    ConfidenceBreakdown, RecordError, RiskLevel, SessionRecord, SourceMetadata,
    StrategyStateTransition, TargetLevel,
)
from .utils.time_context import as_utc


REVERSAL_VERSION = "M82_OR_FAILURE_REV_V1"
RULES_VERSION = "M82_OR_FAILURE_REV_RULES_V1"
DATA_MODE = "SUPPLIED_OR_FAILURE_REV_INPUTS"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

# The two supplied confirmations PLAYBOOKS section 5 leaves unresolved: the
# mandatory one-minute close back inside the range, and the stronger break of the
# failure bar's own extreme. The caller names which one its definition requires;
# neither is adopted here.
MINUTE_CLOSE_CONFIRMATION = "MINUTE_CLOSE"
FAILURE_BAR_CONFIRMATION = "FAILURE_BAR_BREAK"
CONFIRMATIONS = (MINUTE_CLOSE_CONFIRMATION, FAILURE_BAR_CONFIRMATION)

HANDOFF_GATE = "FAILURE_HANDOFF"
LAST_GATE = "LAST_BACK_INSIDE_RANGE"
CONFIRMATION_GATE = "FAILURE_CONFIRMATION"
ACCEPTANCE_GATE = "INSIDE_ACCEPTANCE"
SPREAD_GATE = "SPREAD_BPS"
DISPLACEMENT_GATE = "DISPLACEMENT_FROM_EDGE"
EXTENSION_GATE = "STALE_EXTENSION"
RISK_GATE = "RISK_TARGETS"
CONFIDENCE_GATE = "CONFIDENCE"
REVERSAL_GATES = (
    HANDOFF_GATE, LAST_GATE, CONFIRMATION_GATE, ACCEPTANCE_GATE, SPREAD_GATE,
    DISPLACEMENT_GATE, EXTENSION_GATE, RISK_GATE, CONFIDENCE_GATE,
)

STATES = ("SETUP_FORMING", "ARMED", "ALERT_TRIGGERED", "INVALIDATED", "EXPIRED")
SUBSTATES = (FAILURE_FORMING,)
# Only these supplied facts end a handed-over reversal outright. A merely failing
# known gate leaves the owner where it already stood.
INVALIDATIONS = ("HANDOFF_CLOSED", "COVERAGE_LOST", "STALE_EXTENSION_BEYOND_SUPPLIED_MAXIMUM")
# No approved definition supplies these, so the result keeps naming them instead
# of filling them in.
UNDEFINED = (
    "CATALYST_SUPPRESSION_UNDEFINED", "CONFIDENCE_FLOOR_UNDEFINED",
    "FAILURE_TIMER_ORIGIN_UNDEFINED", "INSIDE_ACCEPTANCE_WINDOW_UNDEFINED",
    "STOP_PAD_UNDEFINED", "TARGET_REWARD_MINIMUM_UNDEFINED",
)


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


def _identifiers(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or any(
        not isinstance(row, str) or not row.strip() for row in value
    ):
        raise RecordError(f"{name} must be non-empty strings")
    return value


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def _price(value: float) -> Fraction:
    return Fraction(str(value))


def _sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1


@dataclass(frozen=True)
class ReversalPolicy:
    """The caller's own actionable prior, confirmation and staleness values.

    Nothing is defaulted. The values describe the caller's own definition;
    supplying them neither adopts a proposed rule nor claims the referenced
    definition was approved. `mode` and `max_observation_age_seconds` say which
    supplied arm the observations come from and how old one may be, exactly as the
    M6.2 records they reuse.
    """

    version: str
    definition_reference: str
    mode: str
    confirmation: str
    max_observation_age_seconds: float
    min_inside_acceptance: float
    max_spread_bps: float
    min_displacement_atr_multiple: float
    max_extension_r_multiple: float
    min_first_target_r_multiple: float

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        if self.mode not in MODES:
            raise RecordError("observation arm is not supported")
        if self.confirmation not in CONFIRMATIONS:
            raise RecordError("failure confirmation is not supported")
        _threshold(self.max_observation_age_seconds, "max_observation_age_seconds")
        acceptance = _threshold(self.min_inside_acceptance, "min_inside_acceptance", positive=True)
        if acceptance > 1:
            raise RecordError("min_inside_acceptance must be a share of one")
        for name in ("max_spread_bps", "min_displacement_atr_multiple",
                     "max_extension_r_multiple", "min_first_target_r_multiple"):
            _threshold(getattr(self, name), name, positive=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version, "definition_reference": self.definition_reference,
            "mode": self.mode, "confirmation": self.confirmation,
            "max_observation_age_seconds": self.max_observation_age_seconds,
            "min_inside_acceptance": self.min_inside_acceptance,
            "max_spread_bps": self.max_spread_bps,
            "min_displacement_atr_multiple": self.min_displacement_atr_multiple,
            "max_extension_r_multiple": self.max_extension_r_multiple,
            "min_first_target_r_multiple": self.min_first_target_r_multiple,
        }


@dataclass(frozen=True)
class InsideAcceptance:
    """One supplied share of the failure window spent back inside the range.

    The share and its coverage are supplied facts under the caller's own window
    definition. A missing share stays unknown: silence is never full acceptance.
    """

    record_id: str
    definition_reference: str
    available_at: datetime
    share: float | None
    coverage_complete: bool
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.record_id, "acceptance record ID")
        _label(self.definition_reference, "acceptance definition reference")
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))
        _flag(self.coverage_complete, "coverage_complete")
        if self.share is None:
            _label(self.missing_reason, "acceptance missing reason")
        else:
            if _threshold(self.share, "acceptance share") > 1:
                raise RecordError("acceptance share must be a share of one")
            if self.missing_reason is not None:
                raise RecordError("a supplied share cannot also report a missing reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "definition_reference": self.definition_reference,
            "available_at": _text_time(self.available_at), "share": self.share,
            "coverage_complete": self.coverage_complete, "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class FailureBar:
    """One supplied completed minute bar whose extreme the stronger trigger uses.

    A bar that is not final is a pending bar, never a failure bar, and never proof
    that coverage was lost.
    """

    record_id: str
    bar_end: datetime
    available_at: datetime
    high: float | None
    low: float | None
    final: bool
    coverage_known: bool

    def __post_init__(self) -> None:
        _label(self.record_id, "failure bar record ID")
        for name in ("bar_end", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        for name in ("final", "coverage_known"):
            _flag(getattr(self, name), name)
        for name in ("high", "low"):
            if getattr(self, name) is not None:
                _threshold(getattr(self, name), "failure bar " + name, positive=True)
        if self.high is None or self.low is None:
            if self.final:
                raise RecordError("a final failure bar requires its own high and low")
        elif _price(self.low) > _price(self.high):
            raise RecordError("the failure bar low cannot lie above its high")

    def extreme(self, direction: str) -> float | None:
        """The side of the bar the reversal would break: its low down, its high up.

        PLAYBOOKS section 5's stronger trigger for a failed upside break is a move
        below the failure bar's own low, and the mirror for a failed downside one.
        """
        if direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        return self.low if direction == "SHORT" else self.high

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "bar_end": _text_time(self.bar_end),
            "available_at": _text_time(self.available_at), "high": self.high, "low": self.low,
            "final": self.final, "coverage_known": self.coverage_known,
        }


@dataclass(frozen=True)
class ReversalStructural:
    """One supplied stop and target set measured for this handed-over reversal.

    The caller measures them under its own definition reference; this module
    reports them and never calculates a stop, a target or an R multiple. A missing
    measurement stays an explicit unknown with its own reason and carries no
    targets beside it.
    """

    definition_reference: str
    direction: str
    attempt_number: int
    crossed_at: datetime
    evaluated_at: datetime
    available_at: datetime
    risk: RiskLevel | None = None
    targets: tuple[TargetLevel, ...] = ()
    missing_reason: str | None = None
    record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _label(self.definition_reference, "structural definition reference")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        _count(self.attempt_number, "attempt_number", minimum=1)
        for name in ("crossed_at", "evaluated_at", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if self.evaluated_at < self.crossed_at:
            raise RecordError("a structural reading cannot precede its crossing")
        if self.risk is not None and not isinstance(self.risk, RiskLevel):
            raise RecordError("risk must be RiskLevel or null")
        if not isinstance(self.targets, tuple) or any(
            not isinstance(row, TargetLevel) for row in self.targets
        ):
            raise RecordError("targets must be a tuple of TargetLevel")
        names = [row.name for row in self.targets]
        if len(names) != len(set(names)):
            raise RecordError("target names must be unique")
        if self.risk is None:
            if self.targets:
                raise RecordError("targets cannot stand without their own supplied risk")
            _label(self.missing_reason, "structural missing reason")
        elif self.missing_reason is not None:
            raise RecordError("a supplied risk level cannot also report a missing reason")
        _identifiers(self.record_ids, "structural record IDs")


@dataclass(frozen=True)
class ReversalGate:
    name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in REVERSAL_GATES:
            raise RecordError("gate name is not supported")
        if self.status not in GATE_STATUSES:
            raise RecordError("gate status is not supported")
        if self.status != PASS and self.reason is None:
            raise RecordError("a gate that did not pass requires a reason")
        if self.reason is not None:
            _label(self.reason, "gate reason")
        _identifiers(self.input_record_ids, "gate input IDs")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name, "status": self.status, "observed": self.observed,
            "threshold": self.threshold, "reason": self.reason,
            "input_record_ids": list(self.input_record_ids),
        }


@dataclass(frozen=True)
class ReversalRequest:
    """One evaluation of one handed-over M8.1 failure for its reversal owner.

    `strategy_version` and `definition_reference` describe the caller's own
    definition. Supplying them neither adopts a proposed rule nor claims the
    referenced definition was approved.
    """

    handoff: HandoffAssessment
    policy: ReversalPolicy
    evaluated_at: datetime
    strategy_version: str
    definition_reference: str
    breakout_extreme_price: float | None = None
    last_trade: Observation | None = None
    confirmation_close: MinuteClose | None = None
    failure_bar: FailureBar | None = None
    acceptance: InsideAcceptance | None = None
    quote: QuoteEventDecision | None = None
    structural: ReversalStructural | None = None
    confidence: ConfidenceResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.handoff, HandoffAssessment):
            raise RecordError("handoff must be the supplied M8.1 HandoffAssessment")
        if not isinstance(self.policy, ReversalPolicy):
            raise RecordError("policy must be ReversalPolicy")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if self.evaluated_at < self.handoff.candidate.crossed_at:
            raise RecordError("the reversal cannot be evaluated before the break it reads")
        _label(self.strategy_version, "strategy version")
        _label(self.definition_reference, "definition reference")
        if self.breakout_extreme_price is not None:
            _threshold(self.breakout_extreme_price, "breakout extreme price", positive=True)
        if self.last_trade is not None and not isinstance(self.last_trade, Observation):
            raise RecordError("last trade must be the supplied M6.2 Observation or null")
        if self.confirmation_close is not None and not isinstance(
                self.confirmation_close, MinuteClose):
            raise RecordError("confirmation close must be the supplied M6.2 MinuteClose or null")
        if self.failure_bar is not None and not isinstance(self.failure_bar, FailureBar):
            raise RecordError("failure bar must be FailureBar or null")
        if self.acceptance is not None and not isinstance(self.acceptance, InsideAcceptance):
            raise RecordError("acceptance must be InsideAcceptance or null")
        if self.quote is not None and not isinstance(self.quote, QuoteEventDecision):
            raise RecordError("quote must be the supplied QuoteEventDecision or null")
        if self.structural is not None and not isinstance(self.structural, ReversalStructural):
            raise RecordError("structural must be ReversalStructural or null")
        if self.confidence is not None and not isinstance(self.confidence, ConfidenceResult):
            raise RecordError("confidence must be the supplied M4.4 ConfidenceResult or null")

    @property
    def candidate(self) -> FrozenCandidate:
        """The break's own frozen range, buffer, boundary and ATR."""
        return self.handoff.candidate

    @property
    def break_direction(self) -> str:
        return self.candidate.direction

    @property
    def direction(self) -> str:
        """The reversal direction, mirrored from the supplied break."""
        return mirror_direction(self.break_direction)

    @property
    def failed_edge(self) -> float:
        """The unbuffered opening-range edge the break ran through and failed at."""
        return (self.candidate.opening_range_high if self.break_direction == "LONG"
                else self.candidate.opening_range_low)


@dataclass(frozen=True)
class ReversalAssessment:
    """Immutable result of one evaluation; the caller owns storage and delivery.

    Each measured field is populated only by the gate that passed for it, so a
    refused or unknown input leaves its own facts absent instead of half-stated.
    """

    evaluated_at: datetime
    state: StrategyState
    direction: str
    break_direction: str
    gates: tuple[ReversalGate, ...]
    reasons: tuple[str, ...]
    candidate: FrozenCandidate
    inside_distance: float | None = None
    required_displacement: float | None = None
    extension_r_multiple: float | None = None
    acceptance_share: float | None = None
    spread_bps: float | None = None
    risk: RiskLevel | None = None
    targets: tuple[TargetLevel, ...] = ()
    confidence: ConfidenceBreakdown | None = None
    structural_input_ids: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = UNDEFINED
    policy_version: str = ""
    definition_reference: str = ""
    strategy_version: str = ""

    def gate(self, name: str) -> ReversalGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        confidence = self.confidence
        return {
            "reversal_version": REVERSAL_VERSION, "strategy_id": STRATEGY_ID,
            "evaluated_at": _text_time(self.evaluated_at), "state": self.state.state,
            "substate": self.state.substate, "direction": self.direction,
            "break_direction": self.break_direction,
            "gates": [row.as_dict() for row in self.gates], "reasons": list(self.reasons),
            "candidate": self.candidate.as_dict(), "inside_distance": self.inside_distance,
            "required_displacement": self.required_displacement,
            "extension_r_multiple": self.extension_r_multiple,
            "acceptance_share": self.acceptance_share, "spread_bps": self.spread_bps,
            "risk": None if self.risk is None else {
                "entry_reference": self.risk.entry_reference, "hard_stop": self.risk.hard_stop,
                "risk_per_share": self.risk.risk_per_share, "rationale": self.risk.rationale,
                "source": self.risk.source,
            },
            "targets": [{"name": row.name, "price": row.price, "r_multiple": row.r_multiple,
                         "source": row.source} for row in self.targets],
            "confidence": None if confidence is None else {
                "setup_score": confidence.setup_score,
                "context_score": confidence.context_score,
                "execution_score": confidence.execution_score,
                "final_score": confidence.final_score,
                "factors": [{"name": row.name, "value": row.value, "version": row.version}
                            for row in confidence.factors],
            },
            "structural_input_ids": list(self.structural_input_ids),
            "unavailable": list(self.unavailable), "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
            "strategy_version": self.strategy_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def reversal_rules() -> TransitionRules:
    """Exactly the M8.2 states, continuing the M8.1 chain at FAILURE_FORMING.

    PLAYBOOKS section 5 names `FAILURE_FORMING -> ARMED -> ALERT_TRIGGERED`, so an
    evaluation that already passes everything still records ARMED before its
    actionable state, and an actionable reversal never falls back to ARMED.
    """
    failing = StrategyState("SETUP_FORMING", FAILURE_FORMING)
    armed = StrategyState("ARMED")
    triggered = StrategyState("ALERT_TRIGGERED")
    invalidated = StrategyState("INVALIDATED")
    expired = StrategyState("EXPIRED")
    allowed = (
        (failing, armed), (armed, triggered), (failing, invalidated),
        (armed, invalidated), (triggered, invalidated),
    )
    return TransitionRules(RULES_VERSION, failing, allowed + tuple(
        (state, expired) for state in (failing, armed, triggered, invalidated)))


def _usable(observation: Observation, policy: ReversalPolicy, instant: datetime) -> str | None:
    """Why this supplied observation cannot stand at `instant`."""
    if observation.mode != policy.mode:
        return "WRONG_ARM"
    if observation.available_at > instant:
        return "OBSERVATION_NOT_AVAILABLE"
    if not observation.coverage_known:
        return "COVERAGE_LOST"
    if observation.price is None:
        return observation.missing_reason or "OBSERVATION_VALUE_UNAVAILABLE"
    if observation.age_seconds is None:
        return "OBSERVATION_AGE_UNKNOWN"
    if _threshold(observation.age_seconds, "observation age") > _threshold(
            policy.max_observation_age_seconds, "max_observation_age_seconds"):
        return "STALE_OBSERVATION"
    return None


def _missing_reason(missing: str | None) -> str:
    """Name the absent last trade, keeping lost coverage its own closing fact."""
    return str(missing) if missing == "COVERAGE_LOST" else "LAST_TRADE_" + str(missing)


def _last_price(request: ReversalRequest) -> tuple[Fraction | None, str | None, tuple[str, ...]]:
    """The usable supplied last trade, or the exact reason there is none."""
    supplied = request.last_trade
    if supplied is None:
        return None, "LAST_TRADE_UNAVAILABLE", ()
    ids = (supplied.record_id,)
    reason = _usable(supplied, request.policy, request.evaluated_at)
    if reason is not None:
        return None, reason, ids
    return _price(supplied.price), None, ids


def _handoff(request: ReversalRequest) -> ReversalGate:
    """Only a current M8.1 FAILURE_FORMING handoff opens this reversal.

    A handoff evaluated at another instant is not this instant's fact, however
    complete it looks, and a closed handoff closes the reversal with it.
    """
    supplied = request.handoff
    ids = tuple(sorted({value for row in supplied.gates for value in row.input_record_ids}))
    if supplied.evaluated_at != request.evaluated_at:
        return ReversalGate(HANDOFF_GATE, UNKNOWN, reason="HANDOFF_NOT_CURRENT",
                            input_record_ids=ids)
    if supplied.state == StrategyState("SETUP_FORMING", FAILURE_FORMING):
        return ReversalGate(HANDOFF_GATE, PASS, input_record_ids=ids)
    if supplied.state.state in ("INVALIDATED", "EXPIRED"):
        return ReversalGate(HANDOFF_GATE, FAIL, reason="HANDOFF_CLOSED", input_record_ids=ids)
    unknown = next((row for row in supplied.gates if row.status == UNKNOWN), None)
    if unknown is not None:
        return ReversalGate(HANDOFF_GATE, UNKNOWN, reason="HANDOFF_UNKNOWN_" + unknown.name,
                            input_record_ids=ids)
    failing = next((row for row in supplied.gates if row.status == FAIL), None)
    return ReversalGate(HANDOFF_GATE, FAIL, reason="HANDOFF_NOT_FAILURE_FORMING_" + (
        failing.name if failing is not None else supplied.state.state), input_record_ids=ids)


def _last_inside(request: ReversalRequest,
                 last: Fraction | None, missing: str | None,
                 ids: tuple[str, ...]) -> ReversalGate:
    """The supplied last trade must still stand back inside the failed edge."""
    edge = _price(request.failed_edge)
    if last is None:
        status = FAIL if missing == "COVERAGE_LOST" else UNKNOWN
        return ReversalGate(LAST_GATE, status, None, float(edge), _missing_reason(missing), ids)
    inside = _sign(request.direction) * (last - edge) > 0
    return ReversalGate(LAST_GATE, PASS if inside else FAIL, float(last), float(edge),
                        None if inside else "LAST_NOT_BACK_INSIDE_RANGE", ids)


def _displacement(request: ReversalRequest, last: Fraction | None, missing: str | None,
                  ids: tuple[str, ...]) -> tuple[ReversalGate, Fraction | None, Fraction]:
    """How far inside the failed edge the supplied last trade came back.

    The minimum is the caller's own multiple of the frozen ATR, so a price that
    only just slipped back inside is not an actionable reversal by itself.
    """
    policy, candidate = request.policy, request.candidate
    required = (_threshold(policy.min_displacement_atr_multiple,
                           "min_displacement_atr_multiple", positive=True)
                * _threshold(candidate.frozen_atr, "frozen_atr"))
    if last is None:
        status = FAIL if missing == "COVERAGE_LOST" else UNKNOWN
        return (ReversalGate(DISPLACEMENT_GATE, status, None, float(required),
                             _missing_reason(missing), ids), None, required)
    distance = _sign(request.direction) * (last - _price(request.failed_edge))
    passed = distance >= required
    return (ReversalGate(DISPLACEMENT_GATE, PASS if passed else FAIL, float(distance),
                         float(required),
                         None if passed else "DISPLACEMENT_BELOW_SUPPLIED_MINIMUM", ids),
            distance, required)


def _confirmation(request: ReversalRequest, last: Fraction | None, missing: str | None,
                  last_ids: tuple[str, ...]) -> ReversalGate:
    """The confirmation the caller's own definition requires, and only that one.

    The mandatory arm needs an available final close back inside the range after
    the crossing. The stronger arm needs the supplied failure bar and a last trade
    beyond that bar's own extreme. Neither arm may stand in for the other.
    """
    policy, candidate = request.policy, request.candidate
    sign, edge = _sign(request.direction), _price(request.failed_edge)
    if policy.confirmation == MINUTE_CLOSE_CONFIRMATION:
        close = request.confirmation_close
        if close is None:
            return ReversalGate(CONFIRMATION_GATE, UNKNOWN, None, float(edge),
                                "MISSING_CONFIRMATION_CLOSE")
        ids = (close.record_id,)
        if not close.coverage_known:
            return ReversalGate(CONFIRMATION_GATE, FAIL, None, float(edge), "COVERAGE_LOST", ids)
        if close.available_at > request.evaluated_at:
            return ReversalGate(CONFIRMATION_GATE, UNKNOWN, None, float(edge),
                                "CONFIRMATION_NOT_AVAILABLE", ids)
        if not close.final:
            return ReversalGate(CONFIRMATION_GATE, UNKNOWN, None, float(edge),
                                "MINUTE_BAR_PENDING", ids)
        if close.bar_end <= candidate.crossed_at:
            return ReversalGate(CONFIRMATION_GATE, FAIL, None, float(edge),
                                "CONFIRMATION_BEFORE_CROSSING", ids)
        price = _price(close.close)
        inside = sign * (price - edge) > 0
        return ReversalGate(CONFIRMATION_GATE, PASS if inside else FAIL, float(price), float(edge),
                            None if inside else "CLOSE_NOT_BACK_INSIDE_RANGE", ids)
    bar = request.failure_bar
    if bar is None:
        return ReversalGate(CONFIRMATION_GATE, UNKNOWN, reason="MISSING_FAILURE_BAR")
    ids = tuple(sorted({bar.record_id, *last_ids}))
    if not bar.coverage_known:
        return ReversalGate(CONFIRMATION_GATE, FAIL, reason="COVERAGE_LOST",
                            input_record_ids=ids)
    if bar.available_at > request.evaluated_at:
        return ReversalGate(CONFIRMATION_GATE, UNKNOWN, reason="FAILURE_BAR_NOT_AVAILABLE",
                            input_record_ids=ids)
    if not bar.final:
        return ReversalGate(CONFIRMATION_GATE, UNKNOWN, reason="MINUTE_BAR_PENDING",
                            input_record_ids=ids)
    if bar.bar_end <= candidate.crossed_at:
        return ReversalGate(CONFIRMATION_GATE, FAIL, reason="FAILURE_BAR_BEFORE_CROSSING",
                            input_record_ids=ids)
    extreme = _price(bar.extreme(request.direction))
    if last is None:
        status = FAIL if missing == "COVERAGE_LOST" else UNKNOWN
        return ReversalGate(CONFIRMATION_GATE, status, None, float(extreme),
                            _missing_reason(missing), ids)
    beyond = sign * (last - extreme) > 0
    return ReversalGate(CONFIRMATION_GATE, PASS if beyond else FAIL, float(last), float(extreme),
                        None if beyond else "LAST_NOT_BEYOND_FAILURE_BAR", ids)


def _acceptance(request: ReversalRequest) -> tuple[ReversalGate, Fraction | None]:
    """The supplied share of the failure window spent back inside the range."""
    policy, supplied = request.policy, request.acceptance
    required = _threshold(policy.min_inside_acceptance, "min_inside_acceptance", positive=True)
    if supplied is None:
        return ReversalGate(ACCEPTANCE_GATE, UNKNOWN, None, float(required),
                            "MISSING_INSIDE_ACCEPTANCE"), None
    ids = (supplied.record_id,)
    if supplied.available_at > request.evaluated_at:
        return ReversalGate(ACCEPTANCE_GATE, UNKNOWN, None, float(required),
                            "ACCEPTANCE_NOT_AVAILABLE", ids), None
    if not supplied.coverage_complete:
        return ReversalGate(ACCEPTANCE_GATE, UNKNOWN, None, float(required),
                            "ACCEPTANCE_COVERAGE_INCOMPLETE", ids), None
    if supplied.share is None:
        return ReversalGate(ACCEPTANCE_GATE, UNKNOWN, None, float(required),
                            supplied.missing_reason, ids), None
    share = _price(supplied.share)
    passed = share >= required
    return (ReversalGate(ACCEPTANCE_GATE, PASS if passed else FAIL, float(share), float(required),
                         None if passed else "ACCEPTANCE_BELOW_SUPPLIED_MINIMUM", ids), share)


def _spread(request: ReversalRequest) -> tuple[ReversalGate, Fraction | None]:
    """The supplied quote decision's own two-sided spread at this instant."""
    policy, decision = request.policy, request.quote
    limit = _threshold(policy.max_spread_bps, "max_spread_bps", positive=True)
    if decision is None or decision.quote is None:
        reason = "QUOTE_DECISION_ABSENT" if decision is None else "QUOTE_RECORD_ABSENT"
        return ReversalGate(SPREAD_GATE, UNKNOWN, None, float(limit), reason), None
    quote = decision.quote
    ids = (quote.record_id,)
    reason = None
    if not decision.usable:
        reason = "QUOTE_STREAM_" + (decision.reasons[0] if decision.reasons else UNKNOWN)
    elif quote.status != "VALID" or quote.delayed is not False:
        reason = "QUOTE_NOT_VALID_REALTIME"
    elif quote.bid is None or quote.ask is None:
        reason = "QUOTE_NOT_TWO_SIDED"
    elif quote.bid <= 0 or quote.ask <= 0:
        reason = "NONPOSITIVE_QUOTE"
    elif quote.bid > quote.ask:
        reason = "CROSSED_QUOTE"
    elif decision.quote_age_seconds is None:
        reason = "QUOTE_AGE_UNKNOWN"
    elif _threshold(decision.quote_age_seconds, "quote age") > _threshold(
            policy.max_observation_age_seconds, "max_observation_age_seconds"):
        reason = "STALE_QUOTE"
    if reason is not None:
        return ReversalGate(SPREAD_GATE, UNKNOWN, None, float(limit), reason, ids), None
    bid, ask = _price(quote.bid), _price(quote.ask)
    spread = 10000 * (ask - bid) / ((ask + bid) / 2)
    passed = spread <= limit
    return (ReversalGate(SPREAD_GATE, PASS if passed else FAIL, float(spread), float(limit),
                         None if passed else "SPREAD_ABOVE_SUPPLIED_LIMIT", ids), spread)


def _extension(request: ReversalRequest, distance: Fraction | None, missing: str | None,
               ids: tuple[str, ...]) -> tuple[ReversalGate, Fraction | None]:
    """How far the reversal already ran, in the caller's own supplied risk units.

    A move that has already travelled past the caller's own maximum is stale: the
    reversal is closed rather than reported late.
    """
    policy, supplied = request.policy, request.structural
    limit = _threshold(policy.max_extension_r_multiple, "max_extension_r_multiple", positive=True)
    if distance is None:
        status = FAIL if missing == "COVERAGE_LOST" else UNKNOWN
        return ReversalGate(EXTENSION_GATE, status, None, float(limit),
                            _missing_reason(missing), ids), None
    if supplied is None or supplied.risk is None:
        reason = ("EXTENSION_RISK_UNAVAILABLE" if supplied is None
                  else "EXTENSION_" + supplied.missing_reason)
        return ReversalGate(EXTENSION_GATE, UNKNOWN, None, float(limit), reason, ids), None
    extension = distance / _price(supplied.risk.risk_per_share)
    passed = extension <= limit
    return (ReversalGate(EXTENSION_GATE, PASS if passed else FAIL, float(extension), float(limit),
                         None if passed else "STALE_EXTENSION_BEYOND_SUPPLIED_MAXIMUM",
                         tuple(sorted({*ids, *supplied.record_ids}))), extension)


def _structural(request: ReversalRequest) -> ReversalGate:
    """The supplied stop and targets, re-checked against this handed-over break.

    The identity checks come first: a reading framed on another direction,
    attempt, crossing or instant is not this reversal's geometry. Only then are
    the supplied prices compared with the frozen range the break failed at and
    with the break's own furthest traded price, which the stop must sit beyond.
    How far beyond it stays the caller's own undefined pad.
    """
    supplied, candidate = request.structural, request.candidate
    at, sign = request.evaluated_at, _sign(request.direction)
    if supplied is None:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_UNAVAILABLE")
    if supplied.direction != request.direction:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_DIRECTION_MISMATCH")
    if supplied.attempt_number != candidate.attempt_number:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_ATTEMPT_MISMATCH")
    if supplied.crossed_at != candidate.crossed_at:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_CROSSING_MISMATCH")
    if supplied.evaluated_at != at:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_NOT_CURRENT")
    if supplied.available_at > at:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_NOT_YET_AVAILABLE")
    if supplied.risk is None:  # a missing measurement always names its own reason
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_" + supplied.missing_reason)
    if not supplied.targets:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_TARGETS_UNAVAILABLE")
    if request.breakout_extreme_price is None:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="MISSING_BREAKOUT_EXTREME")
    extreme = _price(request.breakout_extreme_price)
    excursion = request.handoff.excursion
    if excursion is None:
        return ReversalGate(RISK_GATE, UNKNOWN, reason="HANDOFF_EXCURSION_UNAVAILABLE")
    if extreme != _price(request.failed_edge) - sign * _price(excursion):
        return ReversalGate(RISK_GATE, FAIL, reason="BREAKOUT_EXTREME_DISAGREES_WITH_HANDOFF")
    entry = _price(supplied.risk.entry_reference)
    stop = _price(supplied.risk.hard_stop)
    risk_per_share = _price(supplied.risk.risk_per_share)
    if not (_price(candidate.opening_range_low) < entry < _price(candidate.opening_range_high)):
        return ReversalGate(RISK_GATE, FAIL, reason="ENTRY_NOT_INSIDE_OPENING_RANGE")
    if sign * (entry - stop) <= 0:
        return ReversalGate(RISK_GATE, FAIL, reason="STOP_ON_THE_WRONG_SIDE")
    if sign * (stop - extreme) > 0:
        return ReversalGate(RISK_GATE, FAIL, reason="STOP_NOT_BEYOND_BREAKOUT_EXTREME")
    for row in supplied.targets:
        reward = sign * (_price(row.price) - entry)
        if reward <= 0:
            return ReversalGate(RISK_GATE, FAIL, reason="TARGET_NOT_BEYOND_ENTRY")
        # A stated reward larger than the supplied prices show is a refusal, not a
        # rounding difference.
        if _price(row.r_multiple) > reward / risk_per_share:
            return ReversalGate(RISK_GATE, FAIL, reason="TARGET_R_MULTIPLE_OVERSTATED")
    first = _price(supplied.targets[0].r_multiple)
    minimum = _threshold(request.policy.min_first_target_r_multiple,
                         "min_first_target_r_multiple", positive=True)
    if first < minimum:
        return ReversalGate(RISK_GATE, FAIL, float(first), float(minimum),
                            "FIRST_TARGET_BELOW_SUPPLIED_MINIMUM", supplied.record_ids)
    return ReversalGate(RISK_GATE, PASS, float(first), float(minimum),
                        input_record_ids=supplied.record_ids)


def _confidence(request: ReversalRequest) -> ReversalGate:
    """The supplied M4.4 composition for this strategy, direction and instant."""
    supplied = request.confidence
    if supplied is None:
        return ReversalGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_UNAVAILABLE")
    composition = supplied.request
    context, policy = composition.context, composition.policy
    if policy.strategy_id != STRATEGY_ID:
        return ReversalGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_STRATEGY_MISMATCH")
    if policy.strategy_version != request.strategy_version:
        return ReversalGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_VERSION_MISMATCH")
    if context.direction != request.direction:
        return ReversalGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_DIRECTION_MISMATCH")
    if context.evaluated_at != request.evaluated_at:
        return ReversalGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_NOT_CURRENT")
    if supplied.status != "READY" or supplied.confidence is None:
        reason = supplied.reasons[0] if supplied.reasons else supplied.status
        return ReversalGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_" + reason)
    references = tuple(sorted({row.record_id for row in context.features}))
    return ReversalGate(CONFIDENCE_GATE, PASS, input_record_ids=references)


def evaluate_or_failure_rev(request: ReversalRequest) -> ReversalAssessment:
    """Report every supplied reversal gate and the state they support, with no side effect.

    ALERT_TRIGGERED describes the supplied inputs at this instant only. It opens no
    position, sends nothing, approves no referenced definition and proves no
    provider coverage. No confidence cutoff is applied: the floor stays with the
    unresolved definition and is named in `unavailable` instead.
    """
    if not isinstance(request, ReversalRequest):
        raise RecordError("ReversalRequest is required")
    last, missing, last_ids = _last_price(request)
    handoff = _handoff(request)
    last_gate = _last_inside(request, last, missing, last_ids)
    confirmation = _confirmation(request, last, missing, last_ids)
    acceptance, share = _acceptance(request)
    spread, spread_bps = _spread(request)
    displacement, distance, _required = _displacement(request, last, missing, last_ids)
    extension, extension_r = _extension(request, distance, missing, last_ids)
    structural = _structural(request)
    confidence = _confidence(request)
    gates = (handoff, last_gate, confirmation, acceptance, spread, displacement,
             extension, structural, confidence)
    if any(row.reason in INVALIDATIONS for row in gates):
        state = StrategyState("INVALIDATED")
    elif handoff.status != PASS:
        state = StrategyState("SETUP_FORMING", FAILURE_FORMING)
    elif all(row.status == PASS for row in gates):
        state = StrategyState("ALERT_TRIGGERED")
    else:
        state = StrategyState("ARMED")
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    values: dict[str, object] = {}
    if structural.status == PASS:
        values.update(risk=request.structural.risk, targets=request.structural.targets,
                      structural_input_ids=request.structural.record_ids)
    if confidence.status == PASS:
        values.update(confidence=request.confidence.confidence)
    return ReversalAssessment(
        request.evaluated_at, state, request.direction, request.break_direction, gates, reasons,
        request.candidate,
        inside_distance=None if distance is None else float(distance),
        required_displacement=float(_required),
        extension_r_multiple=None if extension_r is None else float(extension_r),
        acceptance_share=None if share is None else float(share),
        spread_bps=None if spread_bps is None else float(spread_bps),
        policy_version=request.policy.version,
        definition_reference=request.definition_reference,
        strategy_version=request.strategy_version, **values)


class OrFailureRevMachine:
    """One serially owned `(session, symbol, reversal direction)` reversal owner.

    The machine proposes canonical transitions for the M4.2 engine; it never
    writes, sends or advances itself. Local state moves only when the caller
    confirms a proposed transition after storage acknowledged it. The handed-over
    break is held here, so the frozen range a recorded reversal stood on cannot be
    walked and a second break cannot take over the same owner silently.
    """

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, policy: ReversalPolicy):
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        if not isinstance(policy, ReversalPolicy):
            raise RecordError("policy must be ReversalPolicy")
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
        self._rules = reversal_rules()
        self._state = self._rules.initial_state
        self._candidate: FrozenCandidate | None = None
        self._actioned_at: datetime | None = None
        self._time: datetime | None = None
        self._pending: tuple[StrategyStateTransition, ...] = ()
        self._effect: tuple[str, object] | None = None

    strategy_id = STRATEGY_ID

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
    def last_action_at(self) -> datetime | None:
        """When this owner last recorded an actionable reversal, if it did."""
        return self._actioned_at

    def current_state(self) -> StrategyState:
        return self._state

    def current_candidate(self) -> FrozenCandidate | None:
        return self._candidate

    def _metadata(self, at: datetime) -> SourceMetadata:
        return SourceMetadata(
            instrument_id=self._symbol, instrument_type=self._instrument_type,
            source="DERIVED_M82", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID")

    def _transition(self, *, record_id: str, at: datetime, state: StrategyState, reason: str,
                    previous: StrategyState, input_record_ids: tuple[str, ...] = (),
                    ) -> StrategyStateTransition:
        _label(record_id, "transition record ID")
        if (previous, state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M8.2 rules")
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

    def propose(self, request: ReversalRequest, *, record_id: str,
                staged_record_id: str | None = None,
                ) -> tuple[ReversalAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transitions a caller must store first.

        A first evaluation that already passes every gate needs both the ARMED
        step and the ALERT_TRIGGERED step, so the recorded history always shows the
        actionable prior before the action. That second step needs its own
        `staged_record_id`; nothing is invented here.
        """
        if not isinstance(request, ReversalRequest):
            raise RecordError("ReversalRequest is required")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if request.direction != self._direction:
            raise RecordError("the supplied break does not reverse into this owner's direction")
        if self._candidate is not None and request.candidate != self._candidate:
            raise RecordError("a different break cannot replace the one already taken over")
        assessment = evaluate_or_failure_rev(request)
        self._forward(request.evaluated_at)
        target = assessment.state
        if target == self._state:
            self._pending, self._effect = (), None
            return assessment, ()
        if self._state.state == "ALERT_TRIGGERED" and target.state in ("ARMED", "SETUP_FORMING"):
            raise RecordError("an actionable reversal cannot fall back to an earlier state")
        if self._state.state == "ARMED" and target.state == "SETUP_FORMING":
            # Ownership already recorded cannot silently vanish when a supplied
            # input stops supporting it; it is closed explicitly instead.
            target = StrategyState("INVALIDATED")
        if self._state.state == "INVALIDATED":
            raise RecordError("a closed reversal cannot be reopened inside one owner")
        reason = (assessment.reasons[0] if assessment.reasons
                  else "ALL_SUPPLIED_REVERSAL_GATES_PASSED")
        ids = tuple(sorted({value for row in assessment.gates
                            for value in row.input_record_ids}))
        armed = StrategyState("ARMED")
        staged = self._state == self._rules.initial_state and target.state == "ALERT_TRIGGERED"
        changes: tuple[StrategyStateTransition, ...] = ()
        previous = self._state
        if staged:
            if staged_record_id is None:
                raise RecordError("this evaluation advances two states and needs a second ID")
            changes += (self._transition(record_id=record_id, at=request.evaluated_at,
                                         state=armed, reason="REVERSAL_PRIOR_ARMED",
                                         previous=previous, input_record_ids=ids),)
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
            self._effect = ("TAKE", request.candidate)
        else:
            self._effect = ("CLOSE", None)
        return assessment, changes

    def expire(self, *, at: datetime, reason: str, record_id: str,
               ) -> tuple[StrategyStateTransition, ...]:
        """Propose expiry of this owner at the caller's own session end."""
        instant = _instant(at, "expiry time")
        self._forward(instant)
        transition = self._transition(record_id=record_id, at=instant,
                                      state=StrategyState("EXPIRED"),
                                      reason=_label(reason, "expiry reason"),
                                      previous=self._state)
        self._pending, self._effect = (transition,), ("CLOSE", None)
        return (transition,)

    def confirm(self, *transitions: StrategyStateTransition) -> StrategyState:
        """Advance only after every proposed transition was durably recorded."""
        if not self._pending or transitions != self._pending:
            raise RecordError("only the pending recorded transitions can advance this owner")
        kind, payload = self._effect
        self._state = StrategyState(transitions[-1].to_state, transitions[-1].to_substate)
        if kind == "TAKE":
            self._candidate = payload
        elif kind == "ACTION":
            self._actioned_at = payload
        elif kind == "CLOSE":
            self._candidate = None
        self._pending, self._effect = (), None
        return self._state

    def restore(self, state: StrategyState, *, candidate: FrozenCandidate | None = None,
                last_action_at: datetime | None = None) -> StrategyState:
        """Position an unused owner at facts recovered from storage (M5.5).

        Every fact is restored explicitly. Nothing is inferred from the state
        alone, so a recovered owner cannot silently regain an action it already
        reported or lose one it did.
        """
        if self._pending or self._time is not None or self._candidate is not None:
            raise RecordError("restore requires an unused reversal owner")
        if not isinstance(state, StrategyState) or state.state not in STATES:
            raise RecordError("restored state is not an M8.2 state")
        if state.substate not in (None, *SUBSTATES):
            raise RecordError("restored substate is not an M8.2 substate")
        if state == StrategyState("SETUP_FORMING"):
            raise RecordError("a restored SETUP_FORMING owner keeps its M8.1 substate")
        if candidate is not None and not isinstance(candidate, FrozenCandidate):
            raise RecordError("restored candidate must be FrozenCandidate or null")
        self._candidate = candidate
        self._actioned_at = (None if last_action_at is None
                             else _instant(last_action_at, "last_action_at"))
        self._state = state
        return self._state


__all__ = [
    "ACCEPTANCE_GATE", "CONFIDENCE_GATE", "CONFIRMATIONS", "CONFIRMATION_GATE", "DATA_MODE",
    "DISPLACEMENT_GATE", "EXTENSION_GATE", "FAILURE_BAR_CONFIRMATION", "FailureBar",
    "HANDOFF_GATE", "INVALIDATIONS", "InsideAcceptance", "LAST_GATE",
    "MINUTE_CLOSE_CONFIRMATION", "OrFailureRevMachine", "REVERSAL_GATES", "REVERSAL_VERSION",
    "RISK_GATE", "RULES_VERSION", "ReversalAssessment", "ReversalGate", "ReversalPolicy",
    "ReversalRequest", "ReversalStructural", "SPREAD_GATE", "STATES", "STRATEGY_ID",
    "SUBSTATES", "UNDEFINED", "evaluate_or_failure_rev", "reversal_rules",
]
