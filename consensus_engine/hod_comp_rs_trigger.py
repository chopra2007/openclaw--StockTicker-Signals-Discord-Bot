"""M7.3 offline `HOD_COMP_RS` heads-up and actionable path over supplied inputs.

Two things live here. First the heads-up notice: while the supplied M7.2
eligibility is ARMED, the supplied distance from the compression to the frozen
M7.1 reference is inside the caller's own cutoff and the last trade has not yet
reached the frozen boundary, this reports one approaching structure. Second the
actionable path: one frozen structure is crossed, held over the caller's own
acceptance grid with its own participation evidence, and reported as
ALERT_TRIGGERED only while every supplied gate passes.

Nothing here adopts a number. The trigger buffer, the acceptance share, the
trade-intensity minimum, the heads-up distance, the stale-extension limit and the
number of structures a session allows stay unresolved under PLAYBOOKS section 13
and M0.3, and `M03B_HOD_COMP_RS_V1` is not an approved definition, so a policy
must name its own definition reference. Supplying a threshold neither approves a
proposed rule nor proves a provider covers these observations.

ALERT_TRIGGERED means the supplied gates passed at one evaluation instant. It is
not an alert, an approved rule, proof of tape or quote coverage, or permission to
act. A missing, stale, ambiguous or unknown mandatory input keeps the structure
below the state it would otherwise reach; it never becomes a passing gate. The
two participation arms stay separate: an arm may only consume its own supplied
evidence, so enabling one can never repair or complete the other.

The supplied observation, intensity, projection and minute-close records are the
strategy-neutral M6.2 ones and are reused unchanged. The gates, thresholds,
states and rules below are this milestone's own; risk, confidence and suppression
keep their M7.4 owner and the replay scenarios keep their M7.5 owner.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
import json

# The supplied observation records describe a tape or quote feed, not a strategy.
from .orb5_trigger import (
    CROSSED,
    NOT_CROSSED,
    CrossingResult,
    MinuteClose,
    MODES,
    Observation,
    ProjectedVolume,
    QUOTE_PROJECTED,
    TAPE,
    TapeIntensity,
)
from .rs_trend_eligibility import RsTrendAssessment
from .state_transitions import TransitionRules
from .strategy_interface import StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import RecordError, SessionRecord, SourceMetadata, StrategyStateTransition
from .utils.time_context import as_utc


TRIGGER_VERSION = "M73_HOD_COMP_RS_TRIGGER_V1"
RULES_VERSION = "M73_HOD_COMP_RS_TRIGGER_RULES_V1"
STRATEGY_ID = "HOD_COMP_RS"
DATA_MODE = "SUPPLIED_HOD_COMP_RS_TRIGGER_INPUTS"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

STRUCTURE_GATE = "STRUCTURE_ACTIVE"
QUOTA_GATE = "STRUCTURE_QUOTA"
ELIGIBILITY_GATE = "ELIGIBILITY_ARMED"
TRIGGER_GATES = (
    STRUCTURE_GATE, "ACCEPTANCE_WINDOW", "TRADE_INTENSITY", "LAST_TRADE_BEYOND_BOUNDARY",
    ELIGIBILITY_GATE, "EXTENSION_NOT_STALE",
)
HEADS_UP_GATES = (ELIGIBILITY_GATE, "HEADS_UP_DISTANCE", "HEADS_UP_BEFORE_BOUNDARY")
GATE_NAMES = tuple(dict.fromkeys(TRIGGER_GATES + HEADS_UP_GATES + (QUOTA_GATE,)))

HEADS_UP = "HEADS_UP"
CROSSING_OBSERVED = "CROSSING_OBSERVED"
WAITING_FOR_RESET = "WAITING_FOR_RESET"
SUBSTATES = (None, HEADS_UP, CROSSING_OBSERVED, WAITING_FOR_RESET)
STATES = ("ARMED", "ALERT_TRIGGERED", "INVALIDATED", "EXPIRED")
# Only these supplied facts end a structure outright; a merely failing known gate
# leaves it running until its own deadline.
INVALIDATIONS = ("COMPRESSION_CLOSE_INVALIDATION", "STRUCTURE_BROKEN_CLOSE", "COVERAGE_LOST",
                 "MANDATORY_HALT", "UNKNOWN_MANDATORY_INPUT")


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


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _seconds(first: datetime, second: datetime) -> Fraction:
    return Fraction(str((first - second).total_seconds()))


def _sign(direction: str) -> int:
    return 1 if direction == "LONG" else -1


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TriggerPolicy:
    """Explicitly supplied arm, buffer, window, acceptance, intensity and quota values.

    Nothing is defaulted. The values describe the caller's own definition;
    supplying them neither adopts a proposed rule nor claims the referenced
    definition was approved.
    """

    version: str
    definition_reference: str
    mode: str
    buffer_floor: float
    buffer_atr_multiple: float
    window_open_seconds: int
    window_close_seconds: int
    sample_count: int
    min_acceptance_ratio: float
    sample_interval_seconds: int
    max_observation_age_seconds: float
    min_trade_intensity: float
    min_projection_elapsed_seconds: int
    max_extension_r: float
    max_heads_up_distance_atr: float
    max_structures_per_direction: int
    action_cooldown_seconds: float

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        if self.mode not in MODES:
            raise RecordError("participation arm is not supported")
        for name in ("buffer_floor", "buffer_atr_multiple", "max_observation_age_seconds",
                     "min_trade_intensity", "max_extension_r", "max_heads_up_distance_atr",
                     "action_cooldown_seconds"):
            _threshold(getattr(self, name), name)
        for name in ("window_open_seconds", "window_close_seconds",
                     "min_projection_elapsed_seconds"):
            _count(getattr(self, name), name)
        _count(self.sample_count, "sample_count", minimum=1)
        _count(self.sample_interval_seconds, "sample_interval_seconds", minimum=1)
        _count(self.max_structures_per_direction, "max_structures_per_direction", minimum=1)
        share = _threshold(self.min_acceptance_ratio, "min_acceptance_ratio", positive=True)
        if share > 1:
            raise RecordError("min_acceptance_ratio must be a share of the supplied samples")
        if self.window_open_seconds > self.window_close_seconds:
            raise RecordError("the acceptance window cannot close before it opens")
        if (self.sample_count - 1) * self.sample_interval_seconds >= self.window_open_seconds:
            raise RecordError("the first sample window must start after the crossing")

    @property
    def required_accepting_samples(self) -> int:
        """The smallest whole sample count this supplied share still accepts."""
        share = Fraction(str(self.min_acceptance_ratio)) * self.sample_count
        whole = int(share)
        return whole if share == whole else whole + 1


@dataclass(frozen=True)
class DistanceReading:
    """One supplied M7.1 distance from the compression to the frozen reference.

    The value is in the caller's own supplied minute-ATR units. A null value stays
    an explicit unknown; it never becomes a passing heads-up.
    """

    definition_reference: str
    value: float | None
    available_at: datetime
    record_ids: tuple[str, ...] = ()
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.definition_reference, "distance definition reference")
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))
        if self.value is None:
            _label(self.missing_reason, "distance missing reason")
        elif isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise RecordError("distance value must be a number or null")
        else:
            Fraction(str(self.value))
        if not isinstance(self.record_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.record_ids
        ):
            raise RecordError("distance record IDs must be non-empty strings")


@dataclass(frozen=True)
class ExtensionReading:
    """The supplied risk per share this structure's extension is measured in.

    Where that number comes from stays with M7.4; this module only divides the
    supplied distance beyond the frozen boundary by it.
    """

    definition_reference: str
    risk_per_share: float | None
    available_at: datetime
    record_ids: tuple[str, ...] = ()
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.definition_reference, "extension definition reference")
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))
        if self.risk_per_share is None:
            _label(self.missing_reason, "extension missing reason")
        else:
            _threshold(self.risk_per_share, "risk_per_share")
        if not isinstance(self.record_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.record_ids
        ):
            raise RecordError("extension record IDs must be non-empty strings")


@dataclass(frozen=True)
class FrozenStructure:
    """Reference extreme, compression range, ATR, buffer, boundary and arm at t0.

    Nothing here may move inside the structure: later evaluations reuse exactly
    these decimal values, so a changing ATR cannot walk the boundary and a later
    session extreme cannot replace the frozen reference.
    """

    frozen_at: datetime
    direction: str
    mode: str
    structure_number: int
    reference_extreme: float
    compression_high: float
    compression_low: float
    frozen_atr: float
    buffer: float
    boundary: float
    anchor_bar_id: str
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "frozen_at", _instant(self.frozen_at, "frozen_at"))
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if self.mode not in MODES:
            raise RecordError("structure arm is not supported")
        _count(self.structure_number, "structure_number", minimum=1)
        _label(self.anchor_bar_id, "anchor bar ID")
        high = _threshold(self.compression_high, "compression_high", positive=True)
        low = _threshold(self.compression_low, "compression_low", positive=True)
        if low >= high:
            raise RecordError("the compression low must lie below its high")
        reference = _threshold(self.reference_extreme, "reference_extreme", positive=True)
        # A long structure coils beneath its frozen high; a short coils above its low.
        if self.direction == "LONG" and reference < high:
            raise RecordError("a long structure cannot coil above its frozen reference high")
        if self.direction == "SHORT" and reference > low:
            raise RecordError("a short structure cannot coil below its frozen reference low")
        _threshold(self.frozen_atr, "frozen_atr")
        buffer = _threshold(self.buffer, "buffer", positive=True)
        boundary = _threshold(self.boundary, "boundary", positive=True)
        expected = reference + buffer if self.direction == "LONG" else reference - buffer
        if boundary != expected:
            raise RecordError("the frozen boundary must be the buffered reference extreme")
        if not isinstance(self.input_record_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.input_record_ids
        ):
            raise RecordError("structure input IDs must be non-empty strings")

    def as_dict(self) -> dict[str, object]:
        return {
            "frozen_at": _text_time(self.frozen_at), "direction": self.direction,
            "mode": self.mode, "structure_number": self.structure_number,
            "reference_extreme": self.reference_extreme,
            "compression_high": self.compression_high,
            "compression_low": self.compression_low, "frozen_atr": self.frozen_atr,
            "buffer": self.buffer, "boundary": self.boundary,
            "anchor_bar_id": self.anchor_bar_id,
            "input_record_ids": list(self.input_record_ids),
        }


@dataclass(frozen=True)
class TriggerGate:
    name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in GATE_NAMES:
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
class SampleResult:
    """One acceptance-grid instant, kept with its own time, age and reason."""

    instant: datetime
    status: str
    price: float | None = None
    age_seconds: float | None = None
    accepting: bool = False
    reason: str | None = None
    record_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "instant": _text_time(self.instant), "status": self.status, "price": self.price,
            "age_seconds": self.age_seconds, "accepting": self.accepting,
            "reason": self.reason, "record_id": self.record_id,
        }


@dataclass(frozen=True)
class HeadsUpRequest:
    """One heads-up evaluation of one frozen structure before any crossing."""

    structure: FrozenStructure
    policy: TriggerPolicy
    evaluated_at: datetime
    eligibility: RsTrendAssessment | None = None
    distance: DistanceReading | None = None
    last_trade: Observation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.structure, FrozenStructure):
            raise RecordError("structure must be FrozenStructure")
        if not isinstance(self.policy, TriggerPolicy):
            raise RecordError("policy must be TriggerPolicy")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if self.evaluated_at < self.structure.frozen_at:
            raise RecordError("evaluation cannot precede the frozen structure")
        if self.structure.mode != self.policy.mode:
            raise RecordError("the frozen structure arm must match the policy arm")
        if self.eligibility is not None and not isinstance(self.eligibility, RsTrendAssessment):
            raise RecordError("eligibility must be RsTrendAssessment or null")
        if self.distance is not None and not isinstance(self.distance, DistanceReading):
            raise RecordError("distance must be DistanceReading or null")
        if self.last_trade is not None and not isinstance(self.last_trade, Observation):
            raise RecordError("last trade must be Observation or null")


@dataclass(frozen=True)
class HeadsUpAssessment:
    """Immutable heads-up result; the caller owns storage and delivery."""

    evaluated_at: datetime
    state: StrategyState
    gates: tuple[TriggerGate, ...]
    reasons: tuple[str, ...]
    structure: FrozenStructure
    policy_version: str
    definition_reference: str

    def gate(self, name: str) -> TriggerGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        return {
            "trigger_version": TRIGGER_VERSION, "evaluated_at": _text_time(self.evaluated_at),
            "state": self.state.state, "substate": self.state.substate,
            "gates": [row.as_dict() for row in self.gates], "reasons": list(self.reasons),
            "structure": self.structure.as_dict(), "mode": self.structure.mode,
            "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class TriggerRequest:
    """One evaluation of one crossed structure over supplied arm evidence."""

    structure: FrozenStructure
    policy: TriggerPolicy
    evaluated_at: datetime
    crossed_at: datetime
    observations: tuple[Observation, ...] = ()
    intensity: TapeIntensity | ProjectedVolume | None = None
    last_trade: Observation | None = None
    eligibility: RsTrendAssessment | None = None
    extension: ExtensionReading | None = None
    minute_close: MinuteClose | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.structure, FrozenStructure):
            raise RecordError("structure must be FrozenStructure")
        if not isinstance(self.policy, TriggerPolicy):
            raise RecordError("policy must be TriggerPolicy")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        object.__setattr__(self, "crossed_at", _instant(self.crossed_at, "crossed_at"))
        if self.crossed_at < self.structure.frozen_at:
            raise RecordError("the crossing cannot precede the frozen structure")
        if self.evaluated_at < self.crossed_at:
            raise RecordError("evaluation cannot precede the crossing")
        if self.structure.mode != self.policy.mode:
            raise RecordError("the frozen structure arm must match the policy arm")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(row, Observation) for row in self.observations
        ):
            raise RecordError("observations must be a tuple of Observation")
        identifiers = [row.record_id for row in self.observations]
        if len(identifiers) != len(set(identifiers)):
            raise RecordError("observation record IDs must be unique")
        if self.intensity is not None and not isinstance(
                self.intensity, (TapeIntensity, ProjectedVolume)):
            raise RecordError("intensity must be one supported arm record or null")
        if self.last_trade is not None and not isinstance(self.last_trade, Observation):
            raise RecordError("last trade must be Observation or null")
        if self.eligibility is not None and not isinstance(self.eligibility, RsTrendAssessment):
            raise RecordError("eligibility must be RsTrendAssessment or null")
        if self.extension is not None and not isinstance(self.extension, ExtensionReading):
            raise RecordError("extension must be ExtensionReading or null")
        if self.minute_close is not None and not isinstance(self.minute_close, MinuteClose):
            raise RecordError("minute close must be MinuteClose or null")


@dataclass(frozen=True)
class TriggerAssessment:
    """Immutable result of one evaluation; the caller owns storage and delivery."""

    evaluated_at: datetime
    state: StrategyState
    gates: tuple[TriggerGate, ...]
    samples: tuple[SampleResult, ...]
    accepting_samples: int | None
    elapsed_seconds: float
    reset_satisfied: bool
    reasons: tuple[str, ...]
    structure: FrozenStructure
    crossed_at: datetime
    policy_version: str
    definition_reference: str

    def gate(self, name: str) -> TriggerGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        return {
            "trigger_version": TRIGGER_VERSION, "evaluated_at": _text_time(self.evaluated_at),
            "state": self.state.state, "substate": self.state.substate,
            "gates": [row.as_dict() for row in self.gates],
            "samples": [row.as_dict() for row in self.samples],
            "accepting_samples": self.accepting_samples,
            "elapsed_seconds": self.elapsed_seconds, "reset_satisfied": self.reset_satisfied,
            "reasons": list(self.reasons), "structure": self.structure.as_dict(),
            "crossed_at": _text_time(self.crossed_at), "mode": self.structure.mode,
            "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def trigger_rules() -> TransitionRules:
    """Exactly the M7.3 heads-up and actionable states; risk stays in M7.4."""
    armed = StrategyState("ARMED")
    heads_up = StrategyState("ARMED", HEADS_UP)
    crossing = StrategyState("ARMED", CROSSING_OBSERVED)
    waiting = StrategyState("ARMED", WAITING_FOR_RESET)
    triggered = StrategyState("ALERT_TRIGGERED")
    invalidated = StrategyState("INVALIDATED")
    expired = StrategyState("EXPIRED")
    allowed = (
        (armed, heads_up), (heads_up, armed), (heads_up, invalidated),
        (armed, crossing), (heads_up, crossing),
        (crossing, triggered), (crossing, waiting), (crossing, invalidated),
        (crossing, armed),
        (triggered, waiting), (triggered, invalidated),
        (waiting, armed), (invalidated, armed),
    )
    return TransitionRules(RULES_VERSION, armed, allowed + tuple(
        (state, expired)
        for state in (armed, heads_up, crossing, waiting, triggered, invalidated)))


def structure_boundary(policy: TriggerPolicy, direction: str, *, reference_extreme: float,
                       latest_atr: float) -> tuple[float, float]:
    """Return the supplied `(buffer, boundary)` for one pre-crossing observation.

    The buffer is `max(floor, multiple * latest ATR)` and the boundary is the
    frozen reference moved outward by it. Both are recomputed before every
    crossing test and frozen only with the structure itself.
    """
    if not isinstance(policy, TriggerPolicy):
        raise RecordError("TriggerPolicy is required")
    if direction not in ("LONG", "SHORT"):
        raise RecordError("direction must be LONG or SHORT")
    reference = _threshold(reference_extreme, "reference_extreme", positive=True)
    atr = _threshold(latest_atr, "latest_atr")
    buffer = max(_threshold(policy.buffer_floor, "buffer_floor"),
                 _threshold(policy.buffer_atr_multiple, "buffer_atr_multiple") * atr)
    if buffer <= 0:
        raise RecordError("the supplied buffer must be positive")
    boundary = reference + buffer if direction == "LONG" else reference - buffer
    if boundary <= 0:
        raise RecordError("the supplied boundary must be positive")
    return float(buffer), float(boundary)


def freeze_structure(policy: TriggerPolicy, *, direction: str, frozen_at: datetime,
                     reference_extreme: float, compression_high: float, compression_low: float,
                     latest_atr: float, anchor_bar_id: str, structure_number: int,
                     input_record_ids: tuple[str, ...] = ()) -> FrozenStructure:
    """Freeze the reference, compression range, ATR, buffer, boundary and arm at t0."""
    buffer, boundary = structure_boundary(
        policy, direction, reference_extreme=reference_extreme, latest_atr=latest_atr)
    return FrozenStructure(
        frozen_at=frozen_at, direction=direction, mode=policy.mode,
        structure_number=structure_number, reference_extreme=reference_extreme,
        compression_high=compression_high, compression_low=compression_low,
        frozen_atr=latest_atr, buffer=buffer, boundary=boundary, anchor_bar_id=anchor_bar_id,
        input_record_ids=input_record_ids)


def _usable(observation: Observation, policy: TriggerPolicy, instant: datetime) -> str | None:
    """Why this observation cannot supply the sample standing at `instant`."""
    if observation.mode != policy.mode:
        return "WRONG_ARM"
    if observation.available_at > instant:
        return "SAMPLE_NOT_AVAILABLE"
    if not observation.coverage_known:
        return "SAMPLE_COVERAGE_UNKNOWN"
    if observation.price is None:
        return observation.missing_reason or "SAMPLE_VALUE_UNAVAILABLE"
    if observation.age_seconds is None:
        return "SAMPLE_AGE_UNKNOWN"
    if _threshold(observation.age_seconds, "observation age") > _threshold(
            policy.max_observation_age_seconds, "max_observation_age_seconds"):
        return "STALE_SAMPLE"
    return None


def evaluate_crossing(policy: TriggerPolicy, direction: str, *, boundary: float,
                      previous: Observation | None, current: Observation) -> CrossingResult:
    """Compare two consecutive same-arm observations with one frozen boundary.

    Both prices must come from the configured arm, be consecutive covered
    observations on the fixed grid and be fresh. The first observation after a
    gap cannot establish a crossing, and a boundary that fell under a shrinking
    ATR onto already-beyond prices is not a fresh crossing either.
    """
    if not isinstance(policy, TriggerPolicy):
        raise RecordError("TriggerPolicy is required")
    if direction not in ("LONG", "SHORT"):
        raise RecordError("direction must be LONG or SHORT")
    if not isinstance(current, Observation):
        raise RecordError("the current observation is required")
    if previous is not None and not isinstance(previous, Observation):
        raise RecordError("the preceding observation must be Observation or null")
    edge = _threshold(boundary, "boundary", positive=True)
    ids = tuple(row.record_id for row in (previous, current) if row is not None)
    if previous is None:
        return CrossingResult(UNKNOWN, float(edge), "NO_PRECEDING_OBSERVATION", ids)
    for name, row in (("preceding", previous), ("current", current)):
        reason = _usable(row, policy, row.observed_at)
        if reason is not None:
            return CrossingResult(UNKNOWN, float(edge), name.upper() + "_" + reason, ids)
    step = _seconds(current.observed_at, previous.observed_at)
    if step != _threshold(policy.sample_interval_seconds, "sample_interval_seconds"):
        return CrossingResult(UNKNOWN, float(edge), "OBSERVATION_GAP", ids)
    before = Fraction(str(previous.price))
    after = Fraction(str(current.price))
    sign = _sign(direction)
    crossed = sign * (before - edge) < 0 <= sign * (after - edge)
    return CrossingResult(CROSSED if crossed else NOT_CROSSED, float(edge),
                          None if crossed else "NO_FRESH_CROSSING", ids)


def _eligibility(supplied: RsTrendAssessment | None, at: datetime) -> TriggerGate:
    """The current M7.2 assessment for this instant, which must stand at ARMED."""
    if supplied is None:
        return TriggerGate(ELIGIBILITY_GATE, UNKNOWN, reason="ELIGIBILITY_UNAVAILABLE")
    if supplied.evaluated_at != at:
        return TriggerGate(ELIGIBILITY_GATE, UNKNOWN, reason="ELIGIBILITY_NOT_CURRENT")
    if supplied.state == StrategyState("ARMED"):
        return TriggerGate(ELIGIBILITY_GATE, PASS, input_record_ids=supplied.input_record_ids)
    unknown = next((row for row in supplied.gates if row.status == UNKNOWN), None)
    if unknown is not None:
        return TriggerGate(ELIGIBILITY_GATE, UNKNOWN, reason="ELIGIBILITY_UNKNOWN_" + unknown.name,
                           input_record_ids=supplied.input_record_ids)
    failing = next((row for row in supplied.gates if row.status == FAIL), None)
    return TriggerGate(ELIGIBILITY_GATE, FAIL, reason="ELIGIBILITY_FAILED_" + (
        failing.name if failing is not None else supplied.state.state),
        input_record_ids=supplied.input_record_ids)


def _halted(supplied: RsTrendAssessment | None, at: datetime) -> bool:
    """Whether the supplied current assessment reports a mandatory halt."""
    if supplied is None or supplied.evaluated_at != at:
        return False
    status = next((row for row in supplied.gates if row.name == "MANDATORY_STATUS"), None)
    return status is not None and status.status == FAIL and status.reason == "HALTED"


def _distance(request: HeadsUpRequest) -> TriggerGate:
    """The supplied M7.1 distance from the compression to the frozen reference."""
    policy, supplied, name = request.policy, request.distance, "HEADS_UP_DISTANCE"
    limit = _threshold(policy.max_heads_up_distance_atr, "max_heads_up_distance_atr")
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, float(limit), "DISTANCE_UNAVAILABLE")
    ids = supplied.record_ids
    if supplied.available_at > request.evaluated_at:
        return TriggerGate(name, UNKNOWN, None, float(limit), "DISTANCE_NOT_AVAILABLE", ids)
    if supplied.value is None:
        return TriggerGate(name, UNKNOWN, None, float(limit),
                           supplied.missing_reason or "DISTANCE_UNAVAILABLE", ids)
    value = Fraction(str(supplied.value))
    if value < 0:
        # A compression that already stands beyond its own frozen reference is not
        # the approach this notice describes; it is a different supplied fact.
        return TriggerGate(name, UNKNOWN, float(value), float(limit),
                           "DISTANCE_BEYOND_REFERENCE", ids)
    passed = value <= limit
    return TriggerGate(name, PASS if passed else FAIL, float(value), float(limit),
                       None if passed else "DISTANCE_ABOVE_LIMIT", ids)


def _before_boundary(request: HeadsUpRequest) -> TriggerGate:
    """A heads-up describes an approach, so the last trade must still be inside."""
    policy, structure = request.policy, request.structure
    supplied, name = request.last_trade, "HEADS_UP_BEFORE_BOUNDARY"
    boundary = float(structure.boundary)
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, boundary, "LAST_TRADE_UNAVAILABLE")
    ids = (supplied.record_id,)
    reason = _usable(supplied, policy, request.evaluated_at)
    if reason is not None:
        return TriggerGate(name, UNKNOWN, None, boundary, "LAST_TRADE_" + reason, ids)
    inside = _sign(structure.direction) * (
        Fraction(str(supplied.price)) - Fraction(str(structure.boundary))) < 0
    return TriggerGate(name, PASS if inside else FAIL, supplied.price, boundary,
                       None if inside else "ALREADY_BEYOND_BOUNDARY", ids)


def evaluate_hod_comp_rs_heads_up(request: HeadsUpRequest) -> HeadsUpAssessment:
    """Report the supplied heads-up gates and the state they support, with no side effect.

    A reported heads-up is a notice about one approaching supplied structure. It
    is not a trigger, an alert, an approved rule or permission to act.
    """
    if not isinstance(request, HeadsUpRequest):
        raise RecordError("HeadsUpRequest is required")
    at = request.evaluated_at
    gates = (_eligibility(request.eligibility, at), _distance(request), _before_boundary(request))
    state = (StrategyState("ARMED", HEADS_UP) if all(row.status == PASS for row in gates)
             else StrategyState("ARMED"))
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    return HeadsUpAssessment(at, state, gates, reasons, request.structure,
                             request.policy.version, request.policy.definition_reference)


def _acceptance(request: TriggerRequest) -> tuple[TriggerGate, tuple[SampleResult, ...], int | None]:
    """The fixed-grid samples ending at this instant, all of which must be known."""
    policy, structure, at = request.policy, request.structure, request.evaluated_at
    boundary = Fraction(str(structure.boundary))
    sign = _sign(structure.direction)
    share = Fraction(str(policy.min_acceptance_ratio))
    samples, accepting, unknown, ids = [], 0, None, []
    for step in range(policy.sample_count - 1, -1, -1):
        instant = at - timedelta(seconds=step * policy.sample_interval_seconds)
        rows = [row for row in request.observations
                if row.mode == policy.mode and row.observed_at == instant]
        if not rows:
            samples.append(SampleResult(instant, UNKNOWN, reason="SAMPLE_MISSING"))
            unknown = unknown or "SAMPLE_MISSING"
            continue
        if len(rows) > 1:
            samples.append(SampleResult(instant, UNKNOWN, reason="AMBIGUOUS_SAMPLE"))
            unknown = unknown or "AMBIGUOUS_SAMPLE"
            continue
        row = rows[0]
        ids.append(row.record_id)
        reason = _usable(row, policy, instant)
        if reason is not None:
            samples.append(SampleResult(instant, UNKNOWN, row.price, row.age_seconds,
                                        False, reason, row.record_id))
            unknown = unknown or reason
            continue
        beyond = sign * (Fraction(str(row.price)) - boundary) >= 0
        accepting += 1 if beyond else 0
        samples.append(SampleResult(instant, PASS if beyond else FAIL, row.price,
                                    row.age_seconds, beyond,
                                    None if beyond else "SAMPLE_INSIDE_BOUNDARY", row.record_id))
    references = tuple(sorted(set(ids)))
    if unknown is not None:
        return (TriggerGate("ACCEPTANCE_WINDOW", UNKNOWN, None, float(share), unknown,
                            references), tuple(samples), None)
    observed = Fraction(accepting, policy.sample_count)
    passed = observed >= share
    return (TriggerGate("ACCEPTANCE_WINDOW", PASS if passed else FAIL, float(observed),
                        float(share), None if passed else "ACCEPTANCE_BELOW_MINIMUM",
                        references), tuple(samples), accepting)


def _intensity(request: TriggerRequest) -> TriggerGate:
    """The configured arm's own trade-intensity evidence; arms never substitute."""
    policy, supplied = request.policy, request.intensity
    limit = _threshold(policy.min_trade_intensity, "min_trade_intensity")
    name = "TRADE_INTENSITY"
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, float(limit), "INTENSITY_UNAVAILABLE")
    if supplied.mode != policy.mode:
        return TriggerGate(name, UNKNOWN, None, float(limit), "INTENSITY_ARM_MISMATCH")
    if not supplied.coverage_complete:
        return TriggerGate(name, UNKNOWN, None, float(limit), "INTENSITY_COVERAGE_INCOMPLETE")
    if isinstance(supplied, TapeIntensity):
        if supplied.ratio is None:
            return TriggerGate(name, UNKNOWN, None, float(limit),
                               supplied.missing_reason or "INTENSITY_UNAVAILABLE")
        ratio = Fraction(str(supplied.ratio))
    else:
        at, minute = request.evaluated_at, supplied.minute_start
        if any(getattr(supplied, field) is None
               for field in ("elapsed_seconds", "minute_volume", "reference_mean")):
            return TriggerGate(name, UNKNOWN, None, float(limit),
                               supplied.missing_reason or "PROJECTION_INPUT_UNAVAILABLE")
        elapsed = _threshold(supplied.elapsed_seconds, "elapsed_seconds")
        if minute > at or _seconds(at, minute) != elapsed or elapsed >= 60:
            return TriggerGate(name, UNKNOWN, None, float(limit), "PROJECTION_MINUTE_MISMATCH")
        reference = _threshold(supplied.reference_mean, "reference_mean")
        if reference <= 0:
            return TriggerGate(name, UNKNOWN, None, float(limit),
                               "PROJECTION_REFERENCE_UNAVAILABLE")
        if elapsed < _threshold(policy.min_projection_elapsed_seconds,
                                "min_projection_elapsed_seconds"):
            return TriggerGate(name, FAIL, None, float(limit), "PROJECTION_ELAPSED_BELOW_MINIMUM")
        ratio = (60 / elapsed) * _threshold(supplied.minute_volume, "minute_volume") / reference
    passed = ratio >= limit
    return TriggerGate(name, PASS if passed else FAIL, float(ratio), float(limit),
                       None if passed else "INTENSITY_BELOW_MINIMUM")


def _last_trade(request: TriggerRequest) -> TriggerGate:
    """The arm's fresh last trade must still stand at or beyond the frozen boundary."""
    policy, structure = request.policy, request.structure
    supplied, name = request.last_trade, "LAST_TRADE_BEYOND_BOUNDARY"
    boundary = float(structure.boundary)
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, boundary, "LAST_TRADE_UNAVAILABLE")
    ids = (supplied.record_id,)
    reason = _usable(supplied, policy, request.evaluated_at)
    if reason is not None:
        return TriggerGate(name, UNKNOWN, None, boundary, "LAST_TRADE_" + reason, ids)
    beyond = _sign(structure.direction) * (
        Fraction(str(supplied.price)) - Fraction(str(structure.boundary))) >= 0
    return TriggerGate(name, PASS if beyond else FAIL, supplied.price, boundary,
                       None if beyond else "LAST_TRADE_INSIDE_BOUNDARY", ids)


def _extension(request: TriggerRequest) -> TriggerGate:
    """How far beyond the frozen boundary this attempt already ran, in supplied R.

    A structure that already extended past the caller's own limit is stale: the
    move it described has happened, so the gate fails instead of alerting late.
    """
    policy, structure = request.policy, request.structure
    supplied, name = request.extension, "EXTENSION_NOT_STALE"
    limit = _threshold(policy.max_extension_r, "max_extension_r")
    trade = request.last_trade
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, float(limit), "EXTENSION_UNAVAILABLE")
    ids = supplied.record_ids
    if supplied.available_at > request.evaluated_at:
        return TriggerGate(name, UNKNOWN, None, float(limit), "EXTENSION_NOT_AVAILABLE", ids)
    if supplied.risk_per_share is None:
        return TriggerGate(name, UNKNOWN, None, float(limit),
                           supplied.missing_reason or "RISK_PER_SHARE_UNAVAILABLE", ids)
    risk = _threshold(supplied.risk_per_share, "risk_per_share")
    if risk <= 0:
        return TriggerGate(name, UNKNOWN, None, float(limit), "NONPOSITIVE_RISK_PER_SHARE", ids)
    if trade is None:
        return TriggerGate(name, UNKNOWN, None, float(limit), "LAST_TRADE_UNAVAILABLE", ids)
    reason = _usable(trade, policy, request.evaluated_at)
    if reason is not None:
        return TriggerGate(name, UNKNOWN, None, float(limit), "LAST_TRADE_" + reason,
                           tuple(sorted({*ids, trade.record_id})))
    extended = _sign(structure.direction) * (
        Fraction(str(trade.price)) - Fraction(str(structure.boundary))) / risk
    references = tuple(sorted({*ids, trade.record_id}))
    passed = extended <= limit
    return TriggerGate(name, PASS if passed else FAIL, float(extended), float(limit),
                       None if passed else "EXTENSION_ABOVE_LIMIT", references)


def _inside_compression(structure: FrozenStructure, close: MinuteClose) -> bool:
    """A close strictly inside the frozen compression range."""
    price = Fraction(str(close.close))
    return (Fraction(str(structure.compression_low)) < price
            < Fraction(str(structure.compression_high)))


def _broke_structure(structure: FrozenStructure, close: MinuteClose) -> bool:
    """A close at or beyond the compression range on the structure's wrong side."""
    price = Fraction(str(close.close))
    if structure.direction == "LONG":
        return price <= Fraction(str(structure.compression_low))
    return price >= Fraction(str(structure.compression_high))


def _structure(request: TriggerRequest, elapsed: Fraction) -> tuple[TriggerGate, bool]:
    """Whether this frozen structure is still open, and whether the reset happened."""
    policy, structure, at = request.policy, request.structure, request.evaluated_at
    close = request.minute_close
    pending = (close is not None and not close.final and close.coverage_known
               and close.bar_end <= at)
    if close is not None and close.available_at <= at:
        ids = (close.record_id,)
        if not close.coverage_known:
            return TriggerGate(STRUCTURE_GATE, FAIL, reason="COVERAGE_LOST",
                               input_record_ids=ids), False
        if close.final and _inside_compression(structure, close):
            return TriggerGate(STRUCTURE_GATE, FAIL, reason="COMPRESSION_CLOSE_INVALIDATION",
                               input_record_ids=ids), True
        if close.final and _broke_structure(structure, close):
            # The coil itself failed, so no later close can reset this structure.
            return TriggerGate(STRUCTURE_GATE, FAIL, reason="STRUCTURE_BROKEN_CLOSE",
                               input_record_ids=ids), False
    # Only the arm's own instant invalidates. An earlier gap inside the window
    # leaves the acceptance count unknown and keeps the structure open.
    lost = [row for row in request.observations
            if row.mode == policy.mode and not row.coverage_known
            and row.observed_at == at]
    if request.last_trade is not None and not request.last_trade.coverage_known:
        lost.append(request.last_trade)
    if lost:
        return TriggerGate(STRUCTURE_GATE, FAIL, reason="COVERAGE_LOST",
                           input_record_ids=tuple(sorted(row.record_id for row in lost))), False
    if _halted(request.eligibility, at):
        return TriggerGate(STRUCTURE_GATE, FAIL, reason="MANDATORY_HALT"), False
    # The one exception: hold action while a just-ended bar is still awaiting its
    # final version, keeping the original deadline unchanged.
    if not pending and _eligibility(request.eligibility, at).status == UNKNOWN:
        return TriggerGate(STRUCTURE_GATE, FAIL, reason="UNKNOWN_MANDATORY_INPUT"), False
    interval = _threshold(policy.sample_interval_seconds, "sample_interval_seconds")
    if elapsed % interval != 0:
        return TriggerGate(STRUCTURE_GATE, UNKNOWN, float(elapsed),
                           float(policy.window_close_seconds), "EVALUATION_OFF_GRID"), False
    if elapsed < _threshold(policy.window_open_seconds, "window_open_seconds"):
        return TriggerGate(STRUCTURE_GATE, FAIL, float(elapsed),
                           float(policy.window_close_seconds), "BEFORE_ACCEPTANCE_WINDOW"), False
    if elapsed > _threshold(policy.window_close_seconds, "window_close_seconds"):
        return TriggerGate(STRUCTURE_GATE, FAIL, float(elapsed),
                           float(policy.window_close_seconds), "ACCEPTANCE_DEADLINE_PASSED"), False
    if pending:
        return TriggerGate(STRUCTURE_GATE, UNKNOWN, float(elapsed),
                           float(policy.window_close_seconds), "MINUTE_BAR_PENDING",
                           (close.record_id,)), False
    return TriggerGate(STRUCTURE_GATE, PASS, float(elapsed),
                       float(policy.window_close_seconds)), False


def evaluate_hod_comp_rs_trigger(request: TriggerRequest) -> TriggerAssessment:
    """Report every supplied trigger gate and the state they support, with no side effect.

    Returning ALERT_TRIGGERED describes the supplied inputs at this instant only.
    It does not send, approve the referenced definition, prove tape or quote
    coverage or authorize delivery.
    """
    if not isinstance(request, TriggerRequest):
        raise RecordError("TriggerRequest is required")
    structure, policy, at = request.structure, request.policy, request.evaluated_at
    elapsed = _seconds(at, request.crossed_at)
    active, reset = _structure(request, elapsed)
    acceptance, samples, accepting = _acceptance(request)
    gates = (active, acceptance, _intensity(request), _last_trade(request),
             _eligibility(request.eligibility, at), _extension(request))
    if active.reason in INVALIDATIONS:
        state = StrategyState("INVALIDATED")
    elif active.reason == "ACCEPTANCE_DEADLINE_PASSED":
        state = StrategyState("ARMED", WAITING_FOR_RESET)
    elif all(row.status == PASS for row in gates):
        state = StrategyState("ALERT_TRIGGERED")
    else:
        state = StrategyState("ARMED", CROSSING_OBSERVED)
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    return TriggerAssessment(at, state, gates, samples, accepting, float(elapsed), reset,
                             reasons, structure, request.crossed_at, policy.version,
                             policy.definition_reference)


class HodCompRsTriggerMachine:
    """One serially owned `(session, symbol, direction, arm)` structure owner.

    The machine proposes canonical transitions for the M4.2 engine and the M5.1
    store; it never writes, sends or advances itself. Local state moves only when
    the caller confirms the proposed transition after storage acknowledged it.
    Structure identity, the reserved number, the session quota, the required reset
    and the post-action cooldown are held here so they survive one session's
    structures.
    """

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, policy: TriggerPolicy):
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        if not isinstance(policy, TriggerPolicy):
            raise RecordError("policy must be TriggerPolicy")
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
        self._rules = trigger_rules()
        self._state = self._rules.initial_state
        self._structure: FrozenStructure | None = None
        self._started = 0
        self._reserved: int | None = None
        self._reset_satisfied = True
        self._action_at: datetime | None = None
        self._time: datetime | None = None
        self._pending: StrategyStateTransition | None = None
        self._effect: tuple[str, object] | None = None

    strategy_id = STRATEGY_ID

    @property
    def strategy_version(self) -> str:
        return self._version

    @property
    def mode(self) -> str:
        return self._policy.mode

    @property
    def rules(self) -> TransitionRules:
        return self._rules

    @property
    def started_structure_count(self) -> int:
        return self._started

    @property
    def pending_structure_number(self) -> int:
        """The number reserved for the next compression, heads-up or crossing."""
        return self._reserved if self._reserved is not None else self._started + 1

    def current_state(self) -> StrategyState:
        return self._state

    def current_structure(self) -> FrozenStructure | None:
        return self._structure

    def reserve_structure(self, at: datetime) -> int:
        """Reserve this compression's structure number before any crossing.

        A pre-crossing heads-up keeps its reserved number until the crossing or
        session expiry; it never consumes the session quota by itself.
        """
        _instant(at, "reservation time")
        if self._reserved is not None:
            raise RecordError("this compression already reserved its structure number")
        self._reserved = self._started + 1
        return self._reserved

    def structure_quota(self, at: datetime) -> TriggerGate:
        """Whether a fresh crossing at `at` may open another structure."""
        instant = _instant(at, "crossing time")
        policy = self._policy
        limit = _count(policy.max_structures_per_direction, "max_structures_per_direction",
                       minimum=1)
        if self._started >= limit:
            return TriggerGate(QUOTA_GATE, FAIL, float(self._started), float(limit),
                               "STRUCTURE_QUOTA_EXHAUSTED")
        if not self._reset_satisfied:
            return TriggerGate(QUOTA_GATE, FAIL, float(self._started), float(limit),
                               "RESET_REQUIRED")
        if self._action_at is not None and _seconds(instant, self._action_at) < _threshold(
                policy.action_cooldown_seconds, "action_cooldown_seconds"):
            return TriggerGate(QUOTA_GATE, FAIL, float(self._started), float(limit),
                               "COOLDOWN_NOT_ELAPSED")
        return TriggerGate(QUOTA_GATE, PASS, float(self._started), float(limit))

    def _metadata(self, at: datetime) -> SourceMetadata:
        return SourceMetadata(
            instrument_id=self._symbol, instrument_type=self._instrument_type,
            source="DERIVED_M73", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID")

    def _transition(self, *, record_id: str, at: datetime, state: StrategyState, reason: str,
                    input_record_ids: tuple[str, ...] = ()) -> StrategyStateTransition:
        _label(record_id, "transition record ID")
        if (self._state, state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M7.3 rules")
        if self._time is not None and at < self._time:
            raise RecordError("evaluation time cannot move backward")
        self._time = at
        return StrategyStateTransition(
            record_id=record_id, metadata=self._metadata(at), strategy_id=STRATEGY_ID,
            strategy_version=self._version, occurred_at=at,
            from_state=self._state.state, from_substate=self._state.substate,
            to_state=state.state, to_substate=state.substate, reason=reason,
            feature_snapshot_id=None, input_record_ids=input_record_ids)

    def _owned(self, structure: FrozenStructure) -> None:
        if not isinstance(structure, FrozenStructure):
            raise RecordError("structure must be FrozenStructure")
        if structure.direction != self._direction or structure.mode != self._policy.mode:
            raise RecordError("structure does not match this structure owner")

    def propose_heads_up(self, request: HeadsUpRequest, *, record_id: str,
                         ) -> tuple[HeadsUpAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this heads-up evaluation and the transition a caller must store first."""
        if not isinstance(request, HeadsUpRequest):
            raise RecordError("HeadsUpRequest is required")
        self._owned(request.structure)
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if self._state not in (StrategyState("ARMED"), StrategyState("ARMED", HEADS_UP)):
            raise RecordError("only an owner with no open structure may report a heads-up")
        if request.structure.structure_number != self.pending_structure_number:
            raise RecordError("the heads-up must use the reserved structure number")
        assessment = evaluate_hod_comp_rs_heads_up(request)
        at = request.evaluated_at
        if self._time is not None and at < self._time:
            raise RecordError("evaluation time cannot move backward")
        self._time = at
        if assessment.state == self._state:
            self._pending, self._effect = None, None
            return assessment, ()
        transition = self._transition(
            record_id=record_id, at=at, state=assessment.state,
            reason=(assessment.reasons[0] if assessment.reasons
                    else "ALL_SUPPLIED_HEADS_UP_GATES_PASSED"),
            input_record_ids=(request.eligibility.input_record_ids
                              if request.eligibility is not None else ()))
        self._pending, self._effect = transition, ("HEADS_UP", None)
        return assessment, (transition,)

    def open_crossing(self, structure: FrozenStructure, *, crossed_at: datetime, record_id: str,
                      ) -> tuple[StrategyStateTransition, ...]:
        """Propose the transition that opens one frozen structure at its crossing."""
        self._owned(structure)
        instant = _instant(crossed_at, "crossing time")
        if instant < structure.frozen_at:
            raise RecordError("the crossing cannot precede the frozen structure")
        if self._state not in (StrategyState("ARMED"), StrategyState("ARMED", HEADS_UP)):
            raise RecordError("only an armed owner with no open structure may cross")
        if structure.structure_number != self.pending_structure_number:
            raise RecordError("the crossing must use the reserved structure number")
        quota = self.structure_quota(instant)
        if quota.status != PASS:
            raise RecordError("structure quota refuses this crossing: " + str(quota.reason))
        transition = self._transition(record_id=record_id, at=instant,
                                      state=StrategyState("ARMED", CROSSING_OBSERVED),
                                      reason="CROSSING_OBSERVED")
        self._pending, self._effect = transition, ("OPEN", structure)
        return (transition,)

    def propose(self, request: TriggerRequest, *, record_id: str,
                ) -> tuple[TriggerAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transition a caller must store first."""
        if not isinstance(request, TriggerRequest):
            raise RecordError("TriggerRequest is required")
        if self._structure is None or request.structure != self._structure:
            raise RecordError("evaluation does not match this owner's frozen structure")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        assessment = evaluate_hod_comp_rs_trigger(request)
        at = request.evaluated_at
        if self._time is not None and at < self._time:
            raise RecordError("evaluation time cannot move backward")
        self._time = at
        if assessment.state == self._state:
            self._pending, self._effect = None, None
            return assessment, ()
        transition = self._transition(
            record_id=record_id, at=at, state=assessment.state,
            reason=(assessment.reasons[0] if assessment.reasons
                    else "ALL_SUPPLIED_TRIGGER_GATES_PASSED"),
            input_record_ids=(request.eligibility.input_record_ids
                              if request.eligibility is not None else ()))
        effect = ("TRIGGER", at) if assessment.state.state == "ALERT_TRIGGERED" else (
            ("RESET", None) if assessment.reset_satisfied else ("CLOSE", None))
        self._pending, self._effect = transition, effect
        return assessment, (transition,)

    def reset(self, close: MinuteClose, *, at: datetime, record_id: str,
              ) -> tuple[StrategyStateTransition, ...]:
        """Propose the return toward ARMED after the required inside-compression close.

        A structure that never fired re-arms in one recorded step. One that
        already fired an alert never re-arms silently: the close is recorded
        first as WAITING_FOR_RESET, and a second recorded step re-arms the owner.
        """
        if not isinstance(close, MinuteClose):
            raise RecordError("reset requires MinuteClose")
        instant = _instant(at, "reset time")
        if self._structure is None:
            raise RecordError("reset requires a frozen structure")
        if not close.final or not close.coverage_known or close.available_at > instant:
            raise RecordError("only an available final close can reset a structure")
        if not _inside_compression(self._structure, close):
            raise RecordError("the reset close must lie strictly inside the compression range")
        fired = self._state == StrategyState("ALERT_TRIGGERED")
        transition = self._transition(
            record_id=record_id, at=instant,
            state=StrategyState("ARMED", WAITING_FOR_RESET) if fired else StrategyState("ARMED"),
            reason="INSIDE_COMPRESSION_RESET")
        self._pending, self._effect = transition, ("RESET_RECORDED" if fired else "RESET", None)
        return (transition,)

    def expire(self, *, at: datetime, reason: str, record_id: str,
               ) -> tuple[StrategyStateTransition, ...]:
        """Propose expiry of a pending structure at the evaluation-window end."""
        instant = _instant(at, "expiry time")
        transition = self._transition(record_id=record_id, at=instant,
                                      state=StrategyState("EXPIRED"),
                                      reason=_label(reason, "expiry reason"))
        self._pending, self._effect = transition, ("EXPIRE", None)
        return (transition,)

    def confirm(self, transition: StrategyStateTransition) -> StrategyState:
        """Advance only after the supplied transition was durably recorded."""
        if self._pending is None or transition != self._pending:
            raise RecordError("only the pending recorded transition can advance this owner")
        kind, payload = self._effect
        self._state = StrategyState(transition.to_state, transition.to_substate)
        if kind == "OPEN":
            self._structure = payload
            self._started += 1
            self._reserved = None
            self._reset_satisfied = False
        elif kind == "TRIGGER":
            self._action_at = payload
        elif kind == "RESET":
            self._structure = None
            self._reset_satisfied = True
        elif kind == "RESET_RECORDED":
            # The fired structure keeps its frozen record until the second step.
            self._reset_satisfied = True
        elif kind == "EXPIRE":
            self._structure = None
        self._pending, self._effect = None, None
        return self._state

    def restore(self, state: StrategyState, *, structure: FrozenStructure | None = None,
                started_structure_count: int = 0, reset_satisfied: bool = True,
                last_action_at: datetime | None = None) -> StrategyState:
        """Position an unused owner at facts recovered from storage (M5.5).

        Every quota fact is restored explicitly. Nothing is inferred from the
        state alone, so a recovered owner cannot silently regain a structure.
        """
        if self._pending is not None or self._time is not None or self._started:
            raise RecordError("restore requires an unused trigger owner")
        if not isinstance(state, StrategyState) or state.state not in STATES:
            raise RecordError("restored state is not an M7.3 state")
        if state.substate not in SUBSTATES:
            raise RecordError("restored substate is not an M7.3 substate")
        if structure is not None and not isinstance(structure, FrozenStructure):
            raise RecordError("restored structure must be FrozenStructure or null")
        if type(reset_satisfied) is not bool:
            raise RecordError("restored reset flag must be true or false")
        self._started = _count(started_structure_count, "started_structure_count")
        self._structure = structure
        self._reset_satisfied = reset_satisfied
        self._action_at = None if last_action_at is None else _instant(
            last_action_at, "last_action_at")
        self._state = state
        return self._state


__all__ = [
    "CROSSED", "CrossingResult", "DATA_MODE", "DistanceReading", "ELIGIBILITY_GATE",
    "ExtensionReading", "FrozenStructure", "GATE_NAMES", "HEADS_UP", "HEADS_UP_GATES",
    "HeadsUpAssessment", "HeadsUpRequest", "HodCompRsTriggerMachine", "INVALIDATIONS",
    "MODES", "MinuteClose", "NOT_CROSSED", "Observation", "ProjectedVolume", "QUOTA_GATE",
    "QUOTE_PROJECTED", "RULES_VERSION", "STATES", "STRATEGY_ID", "STRUCTURE_GATE",
    "SUBSTATES", "SampleResult", "TAPE", "TRIGGER_GATES", "TRIGGER_VERSION", "TapeIntensity",
    "TriggerAssessment", "TriggerGate", "TriggerPolicy", "TriggerRequest",
    "evaluate_crossing", "evaluate_hod_comp_rs_heads_up", "evaluate_hod_comp_rs_trigger",
    "freeze_structure", "structure_boundary", "trigger_rules",
]
