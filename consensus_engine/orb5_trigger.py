"""M6.2 offline `CRVOL_ORB5` actionable-trigger slice over supplied observations.

The caller supplies the frozen candidate, every threshold, every observation and
the mandatory eligibility, participation and geometry results. This module adopts
no number of its own: the rule-bearing thresholds still belong to `M03B_ORB5_V1`,
which is PROPOSED, so a policy must name its own definition reference. Nothing
here reads a clock, fetches data, opens a database, stores a record or delivers
an alert.

ALERT_TRIGGERED means the supplied gates passed at one evaluation instant. It is
not an alert, an approved rule, proof of tape or quote coverage, or permission to
act. A missing, stale, ambiguous or unknown mandatory input keeps the attempt
below the state it would otherwise reach; it never becomes a passing gate. The
two participation arms stay separate: an arm may only consume its own supplied
evidence, so enabling one can never repair or complete the other.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
import json

from .orb5_eligibility import EligibilityAssessment
from .state_transitions import TransitionRules
from .strategy_interface import StrategyState
from .structural_risk import RiskTargetResult, VARIANTS
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import RecordError, SessionRecord, SourceMetadata, StrategyStateTransition
from .utils.time_context import as_utc


TRIGGER_VERSION = "M62_ORB5_TRIGGER_V1"
RULES_VERSION = "M62_ORB5_TRIGGER_RULES_V1"
STRATEGY_ID = "CRVOL_ORB5"
DATA_MODE = "SUPPLIED_TRIGGER_INPUTS"

TAPE, QUOTE_PROJECTED = "TAPE", "QUOTE_PROJECTED"
MODES = (TAPE, QUOTE_PROJECTED)
# Each arm keeps its own D-090 variant, so a result produced for one arm can
# never be presented as evidence for the other.
MODE_VARIANTS = {TAPE: VARIANTS[0], QUOTE_PROJECTED: VARIANTS[1]}

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)
CROSSED, NOT_CROSSED = "CROSSED", "NOT_CROSSED"

ATTEMPT_GATE = "ATTEMPT_ACTIVE"
QUOTA_GATE = "ATTEMPT_QUOTA"
TRIGGER_GATES = (
    ATTEMPT_GATE, "ACCEPTANCE_WINDOW", "PARTICIPATION", "LAST_TRADE_BEYOND_BOUNDARY",
    "ELIGIBILITY_ARMED", "TRIGGER_RISK_TARGETS",
)
GATE_NAMES = TRIGGER_GATES + (QUOTA_GATE,)

CROSSING_OBSERVED = "CROSSING_OBSERVED"
WAITING_FOR_RESET = "WAITING_FOR_RESET"
STATES = ("ARMED", "ALERT_TRIGGERED", "INVALIDATED", "EXPIRED")
# Only these supplied facts end an attempt outright; a merely failing known gate
# leaves the attempt running until its own deadline.
INVALIDATIONS = ("INSIDE_OR_CLOSE_INVALIDATION", "COVERAGE_LOST", "MANDATORY_HALT",
                 "UNKNOWN_MANDATORY_INPUT")


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


@dataclass(frozen=True)
class TriggerPolicy:
    """Explicitly supplied arm, buffer, window, acceptance and quota values.

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
    min_accepting_samples: int
    sample_interval_seconds: int
    max_observation_age_seconds: float
    min_participation_ratio: float
    min_projection_elapsed_seconds: int
    max_attempts_per_direction: int
    action_cooldown_seconds: float

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        if self.mode not in MODES:
            raise RecordError("participation arm is not supported")
        for name in ("buffer_floor", "buffer_atr_multiple", "max_observation_age_seconds",
                     "min_participation_ratio", "action_cooldown_seconds"):
            _threshold(getattr(self, name), name)
        for name in ("window_open_seconds", "window_close_seconds",
                     "min_projection_elapsed_seconds"):
            _count(getattr(self, name), name)
        _count(self.sample_count, "sample_count", minimum=1)
        _count(self.min_accepting_samples, "min_accepting_samples", minimum=1)
        _count(self.sample_interval_seconds, "sample_interval_seconds", minimum=1)
        _count(self.max_attempts_per_direction, "max_attempts_per_direction", minimum=1)
        if self.window_open_seconds > self.window_close_seconds:
            raise RecordError("the acceptance window cannot close before it opens")
        if self.min_accepting_samples > self.sample_count:
            raise RecordError("more accepting samples than samples cannot be required")
        if (self.sample_count - 1) * self.sample_interval_seconds >= self.window_open_seconds:
            raise RecordError("the first sample window must start after the crossing")

    @property
    def variant(self) -> str:
        return MODE_VARIANTS[self.mode]


@dataclass(frozen=True)
class Observation:
    """One supplied arm observation standing for one instant on the fixed grid.

    `available_at` is when the observation could first be used; a later arrival
    cannot repair the sample it missed. `age_seconds` is the underlying event's
    age at `observed_at`. A null price stays an explicit unknown sample.
    """

    record_id: str
    mode: str
    observed_at: datetime
    available_at: datetime
    price: float | None
    age_seconds: float | None
    coverage_known: bool
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.record_id, "observation record ID")
        if self.mode not in MODES:
            raise RecordError("observation arm is not supported")
        for name in ("observed_at", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if type(self.coverage_known) is not bool:
            raise RecordError("observation coverage must be true or false")
        if self.price is None:
            _label(self.missing_reason, "observation missing reason")
        else:
            if _threshold(self.price, "observation price", positive=True) <= 0:
                raise RecordError("observation price must be positive")
        if self.age_seconds is not None:
            _threshold(self.age_seconds, "observation age")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "mode": self.mode,
            "observed_at": _text_time(self.observed_at),
            "available_at": _text_time(self.available_at), "price": self.price,
            "age_seconds": self.age_seconds, "coverage_known": self.coverage_known,
            "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class TapeIntensity:
    """Supplied `INTENSITY_15S_MEAN20_V1` result for the tape arm only."""

    definition_reference: str
    ratio: float | None
    coverage_complete: bool
    missing_reason: str | None = None

    mode = TAPE

    def __post_init__(self) -> None:
        _label(self.definition_reference, "intensity definition reference")
        if type(self.coverage_complete) is not bool:
            raise RecordError("intensity coverage must be true or false")
        if self.ratio is None:
            _label(self.missing_reason, "intensity missing reason")
        else:
            _threshold(self.ratio, "intensity ratio")


@dataclass(frozen=True)
class ProjectedVolume:
    """Supplied current-minute inputs for the projected-quote arm only.

    The projection uses the minute containing the evaluation instant and that
    minute's own reference. A previous minute's numerator is never carried over.
    """

    definition_reference: str
    minute_start: datetime
    elapsed_seconds: float | None
    minute_volume: float | None
    reference_mean: float | None
    coverage_complete: bool
    missing_reason: str | None = None

    mode = QUOTE_PROJECTED

    def __post_init__(self) -> None:
        _label(self.definition_reference, "projection definition reference")
        object.__setattr__(self, "minute_start", _instant(self.minute_start, "minute_start"))
        if type(self.coverage_complete) is not bool:
            raise RecordError("projection coverage must be true or false")
        for name in ("elapsed_seconds", "minute_volume", "reference_mean"):
            value = getattr(self, name)
            if value is None:
                _label(self.missing_reason, "projection missing reason")
            else:
                _threshold(value, name)


@dataclass(frozen=True)
class MinuteClose:
    """One supplied completed regular one-minute close for the reset test.

    A bar that is not final is a pending bar, never a close back inside the
    opening range and never proof that coverage was lost.
    """

    record_id: str
    bar_end: datetime
    available_at: datetime
    close: float | None
    final: bool
    coverage_known: bool

    def __post_init__(self) -> None:
        _label(self.record_id, "minute close record ID")
        for name in ("bar_end", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        for name in ("final", "coverage_known"):
            if type(getattr(self, name)) is not bool:
                raise RecordError(f"{name} must be true or false")
        if self.close is not None:
            _threshold(self.close, "minute close", positive=True)
        elif self.final:
            raise RecordError("a final minute close requires its price")


@dataclass(frozen=True)
class FrozenCandidate:
    """Opening range, buffer, boundary, ATR, arm and anchor frozen at t0.

    Nothing here may move inside the attempt: later evaluations reuse exactly
    these decimal values, so a changing ATR cannot walk the boundary.
    """

    crossed_at: datetime
    direction: str
    mode: str
    attempt_number: int
    opening_range_high: float
    opening_range_low: float
    frozen_atr: float
    buffer: float
    boundary: float
    anchor_bar_id: str
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "crossed_at", _instant(self.crossed_at, "crossed_at"))
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if self.mode not in MODES:
            raise RecordError("candidate arm is not supported")
        _count(self.attempt_number, "attempt_number", minimum=1)
        _label(self.anchor_bar_id, "anchor bar ID")
        high = _threshold(self.opening_range_high, "opening_range_high", positive=True)
        low = _threshold(self.opening_range_low, "opening_range_low", positive=True)
        if low >= high:
            raise RecordError("the opening range low must lie below its high")
        _threshold(self.frozen_atr, "frozen_atr")
        buffer = _threshold(self.buffer, "buffer", positive=True)
        boundary = _threshold(self.boundary, "boundary", positive=True)
        expected = high + buffer if self.direction == "LONG" else low - buffer
        if boundary != expected:
            raise RecordError("the frozen boundary must be the buffered opening-range edge")
        if not isinstance(self.input_record_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.input_record_ids
        ):
            raise RecordError("candidate input IDs must be non-empty strings")

    def as_dict(self) -> dict[str, object]:
        return {
            "crossed_at": _text_time(self.crossed_at), "direction": self.direction,
            "mode": self.mode, "attempt_number": self.attempt_number,
            "opening_range_high": self.opening_range_high,
            "opening_range_low": self.opening_range_low, "frozen_atr": self.frozen_atr,
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
class CrossingResult:
    """One consecutive-observation crossing test against one candidate boundary."""

    status: str
    boundary: float
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in (CROSSED, NOT_CROSSED, UNKNOWN):
            raise RecordError("crossing status is not supported")
        if self.status != CROSSED and self.reason is None:
            raise RecordError("a crossing that did not occur requires a reason")

    def as_dict(self) -> dict[str, object]:
        return {"status": self.status, "boundary": self.boundary, "reason": self.reason,
                "input_record_ids": list(self.input_record_ids)}


@dataclass(frozen=True)
class TriggerRequest:
    """One evaluation of one frozen attempt over supplied arm evidence."""

    candidate: FrozenCandidate
    policy: TriggerPolicy
    evaluated_at: datetime
    observations: tuple[Observation, ...] = ()
    participation: TapeIntensity | ProjectedVolume | None = None
    last_trade: Observation | None = None
    eligibility: EligibilityAssessment | None = None
    geometry: RiskTargetResult | None = None
    minute_close: MinuteClose | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, FrozenCandidate):
            raise RecordError("candidate must be FrozenCandidate")
        if not isinstance(self.policy, TriggerPolicy):
            raise RecordError("policy must be TriggerPolicy")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if self.evaluated_at < self.candidate.crossed_at:
            raise RecordError("evaluation cannot precede the frozen crossing")
        if self.candidate.mode != self.policy.mode:
            raise RecordError("the frozen candidate arm must match the policy arm")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(row, Observation) for row in self.observations
        ):
            raise RecordError("observations must be a tuple of Observation")
        identifiers = [row.record_id for row in self.observations]
        if len(identifiers) != len(set(identifiers)):
            raise RecordError("observation record IDs must be unique")
        if self.participation is not None and not isinstance(
                self.participation, (TapeIntensity, ProjectedVolume)):
            raise RecordError("participation must be one supported arm record or null")
        if self.last_trade is not None and not isinstance(self.last_trade, Observation):
            raise RecordError("last trade must be Observation or null")
        if self.eligibility is not None and not isinstance(self.eligibility, EligibilityAssessment):
            raise RecordError("eligibility must be EligibilityAssessment or null")
        if self.geometry is not None and not isinstance(self.geometry, RiskTargetResult):
            raise RecordError("geometry must be RiskTargetResult or null")
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
    candidate: FrozenCandidate
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
            "reasons": list(self.reasons), "candidate": self.candidate.as_dict(),
            "mode": self.candidate.mode, "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def _text_time(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


def trigger_rules() -> TransitionRules:
    """Exactly the M6.2 attempt states; risk, targets and scoring stay in M6.3."""
    armed = StrategyState("ARMED")
    crossing = StrategyState("ARMED", CROSSING_OBSERVED)
    waiting = StrategyState("ARMED", WAITING_FOR_RESET)
    triggered = StrategyState("ALERT_TRIGGERED")
    invalidated = StrategyState("INVALIDATED")
    expired = StrategyState("EXPIRED")
    allowed = (
        (armed, crossing),
        (crossing, triggered), (crossing, waiting), (crossing, invalidated),
        (triggered, waiting), (triggered, invalidated),
        (waiting, armed), (invalidated, armed),
    )
    return TransitionRules(RULES_VERSION, armed, allowed + tuple(
        (state, expired) for state in (armed, crossing, waiting, triggered, invalidated)))


def candidate_boundary(policy: TriggerPolicy, direction: str, *, opening_range_high: float,
                       opening_range_low: float, latest_atr: float) -> tuple[float, float]:
    """Return the supplied `(buffer, boundary)` for one pre-crossing observation.

    The buffer is `max(floor, multiple * latest ATR)` and the boundary is the
    opening-range edge moved outward by it. Both are recomputed before every
    crossing test and frozen only at the crossing itself.
    """
    if not isinstance(policy, TriggerPolicy):
        raise RecordError("TriggerPolicy is required")
    if direction not in ("LONG", "SHORT"):
        raise RecordError("direction must be LONG or SHORT")
    high = _threshold(opening_range_high, "opening_range_high", positive=True)
    low = _threshold(opening_range_low, "opening_range_low", positive=True)
    if low >= high:
        raise RecordError("the opening range low must lie below its high")
    atr = _threshold(latest_atr, "latest_atr")
    buffer = max(_threshold(policy.buffer_floor, "buffer_floor"),
                 _threshold(policy.buffer_atr_multiple, "buffer_atr_multiple") * atr)
    if buffer <= 0:
        raise RecordError("the supplied buffer must be positive")
    boundary = high + buffer if direction == "LONG" else low - buffer
    if boundary <= 0:
        raise RecordError("the supplied boundary must be positive")
    return float(buffer), float(boundary)


def freeze_candidate(policy: TriggerPolicy, *, direction: str, crossed_at: datetime,
                     opening_range_high: float, opening_range_low: float, latest_atr: float,
                     anchor_bar_id: str, attempt_number: int,
                     input_record_ids: tuple[str, ...] = ()) -> FrozenCandidate:
    """Freeze the opening range, buffer, boundary, ATR, arm and anchor at t0."""
    buffer, boundary = candidate_boundary(
        policy, direction, opening_range_high=opening_range_high,
        opening_range_low=opening_range_low, latest_atr=latest_atr)
    return FrozenCandidate(
        crossed_at=crossed_at, direction=direction, mode=policy.mode,
        attempt_number=attempt_number, opening_range_high=opening_range_high,
        opening_range_low=opening_range_low, frozen_atr=latest_atr, buffer=buffer,
        boundary=boundary, anchor_bar_id=anchor_bar_id, input_record_ids=input_record_ids)


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
    """Compare two consecutive same-arm observations with one candidate boundary.

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


def _acceptance(request: TriggerRequest) -> tuple[TriggerGate, tuple[SampleResult, ...], int | None]:
    """The ten fixed-grid samples ending at this instant, all of which must be known."""
    policy, candidate, at = request.policy, request.candidate, request.evaluated_at
    boundary = Fraction(str(candidate.boundary))
    sign = _sign(candidate.direction)
    required = _count(policy.min_accepting_samples, "min_accepting_samples", minimum=1)
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
        return (TriggerGate("ACCEPTANCE_WINDOW", UNKNOWN, None, float(required), unknown,
                            references), tuple(samples), None)
    passed = accepting >= required
    return (TriggerGate("ACCEPTANCE_WINDOW", PASS if passed else FAIL, float(accepting),
                        float(required), None if passed else "ACCEPTANCE_BELOW_MINIMUM",
                        references), tuple(samples), accepting)


def _participation(request: TriggerRequest) -> TriggerGate:
    """The configured arm's own participation evidence; arms never substitute."""
    policy, supplied = request.policy, request.participation
    limit = _threshold(policy.min_participation_ratio, "min_participation_ratio")
    name = "PARTICIPATION"
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, float(limit), "PARTICIPATION_UNAVAILABLE")
    if supplied.mode != policy.mode:
        return TriggerGate(name, UNKNOWN, None, float(limit), "PARTICIPATION_ARM_MISMATCH")
    if not supplied.coverage_complete:
        return TriggerGate(name, UNKNOWN, None, float(limit), "PARTICIPATION_COVERAGE_INCOMPLETE")
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
            return TriggerGate(name, UNKNOWN, None, float(limit), "PROJECTION_REFERENCE_UNAVAILABLE")
        if elapsed < _threshold(policy.min_projection_elapsed_seconds,
                                "min_projection_elapsed_seconds"):
            return TriggerGate(name, FAIL, None, float(limit), "PROJECTION_ELAPSED_BELOW_MINIMUM")
        ratio = (60 / elapsed) * _threshold(supplied.minute_volume, "minute_volume") / reference
    passed = ratio >= limit
    return TriggerGate(name, PASS if passed else FAIL, float(ratio), float(limit),
                       None if passed else "PARTICIPATION_BELOW_MINIMUM")


def _last_trade(request: TriggerRequest) -> TriggerGate:
    """The arm's fresh last trade must still stand at or beyond the frozen B."""
    policy, candidate, supplied = request.policy, request.candidate, request.last_trade
    name = "LAST_TRADE_BEYOND_BOUNDARY"
    boundary = float(candidate.boundary)
    if supplied is None:
        return TriggerGate(name, UNKNOWN, None, boundary, "LAST_TRADE_UNAVAILABLE")
    ids = (supplied.record_id,)
    reason = _usable(supplied, policy, request.evaluated_at)
    if reason is not None:
        return TriggerGate(name, UNKNOWN, None, boundary, "LAST_TRADE_" + reason, ids)
    beyond = _sign(candidate.direction) * (
        Fraction(str(supplied.price)) - Fraction(str(candidate.boundary))) >= 0
    return TriggerGate(name, PASS if beyond else FAIL, supplied.price, boundary,
                       None if beyond else "LAST_TRADE_INSIDE_BOUNDARY", ids)


def _eligibility(request: TriggerRequest) -> TriggerGate:
    """Every current mandatory gate, supplied as the M6.1 assessment for this instant."""
    supplied, name = request.eligibility, "ELIGIBILITY_ARMED"
    if supplied is None:
        return TriggerGate(name, UNKNOWN, reason="ELIGIBILITY_UNAVAILABLE")
    if supplied.evaluated_at != request.evaluated_at:
        return TriggerGate(name, UNKNOWN, reason="ELIGIBILITY_NOT_CURRENT")
    if supplied.state == StrategyState("ARMED"):
        return TriggerGate(name, PASS, input_record_ids=supplied.input_record_ids)
    unknown = next((row for row in supplied.gates if row.status == UNKNOWN), None)
    if unknown is not None:
        return TriggerGate(name, UNKNOWN, reason="ELIGIBILITY_UNKNOWN_" + unknown.name,
                           input_record_ids=supplied.input_record_ids)
    failing = next((row for row in supplied.gates if row.status == FAIL), None)
    return TriggerGate(name, FAIL, reason="ELIGIBILITY_FAILED_" + (
        failing.name if failing is not None else supplied.state.state),
        input_record_ids=supplied.input_record_ids)


def _geometry(request: TriggerRequest) -> TriggerGate:
    """The supplied M4.3 result, recomputed for this trigger against the frozen B."""
    supplied, candidate, name = request.geometry, request.candidate, "TRIGGER_RISK_TARGETS"
    if supplied is None:
        return TriggerGate(name, UNKNOWN, reason="TRIGGER_GEOMETRY_UNAVAILABLE")
    geometry = supplied.request
    if geometry.variant != request.policy.variant:
        return TriggerGate(name, UNKNOWN, reason="GEOMETRY_ARM_MISMATCH")
    if geometry.direction != candidate.direction:
        return TriggerGate(name, UNKNOWN, reason="GEOMETRY_DIRECTION_MISMATCH")
    if geometry.crossed_at != candidate.crossed_at:
        return TriggerGate(name, UNKNOWN, reason="GEOMETRY_CROSSING_MISMATCH")
    if geometry.evaluated_at != request.evaluated_at:
        return TriggerGate(name, UNKNOWN, reason="GEOMETRY_NOT_CURRENT")
    value = next((row.value for row in geometry.boundary.snapshot.features
                  if row.name == geometry.boundary.feature_name), None)
    if value is None or Fraction(str(value)) != Fraction(str(candidate.boundary)):
        return TriggerGate(name, UNKNOWN, reason="GEOMETRY_BOUNDARY_MISMATCH")
    if supplied.status == "READY":
        return TriggerGate(name, PASS)
    reason = "GEOMETRY_" + (supplied.reasons[0] if supplied.reasons else supplied.status)
    return TriggerGate(name, FAIL if supplied.status == "REJECTED" else UNKNOWN, reason=reason)


def _inside_range(candidate: FrozenCandidate, close: MinuteClose) -> bool:
    """A close strictly inside the unbuffered opening range."""
    price = Fraction(str(close.close))
    return (Fraction(str(candidate.opening_range_low)) < price
            < Fraction(str(candidate.opening_range_high)))


def _attempt(request: TriggerRequest, elapsed: Fraction) -> tuple[TriggerGate, bool]:
    """Whether this frozen attempt is still open, and whether the reset happened."""
    policy, candidate, at = request.policy, request.candidate, request.evaluated_at
    close = request.minute_close
    pending = (close is not None and not close.final and close.coverage_known
               and close.bar_end <= at)
    if close is not None and close.available_at <= at:
        ids = (close.record_id,)
        if not close.coverage_known:
            return TriggerGate(ATTEMPT_GATE, FAIL, reason="COVERAGE_LOST",
                               input_record_ids=ids), False
        if close.final and _inside_range(candidate, close):
            return TriggerGate(ATTEMPT_GATE, FAIL, reason="INSIDE_OR_CLOSE_INVALIDATION",
                               input_record_ids=ids), True
    lost = [row for row in request.observations
            if row.mode == policy.mode and not row.coverage_known
            and candidate.crossed_at < row.observed_at <= at]
    if request.last_trade is not None and not request.last_trade.coverage_known:
        lost.append(request.last_trade)
    if lost:
        return TriggerGate(ATTEMPT_GATE, FAIL, reason="COVERAGE_LOST",
                           input_record_ids=tuple(sorted(row.record_id for row in lost))), False
    supplied = request.eligibility
    if supplied is not None and supplied.evaluated_at == at:
        status = next((row for row in supplied.gates if row.name == "MANDATORY_STATUS"), None)
        if status is not None and status.status == FAIL and status.reason == "HALTED":
            return TriggerGate(ATTEMPT_GATE, FAIL, reason="MANDATORY_HALT"), False
    # The one D-090 exception: hold action while a just-ended bar is still
    # awaiting its final version, keeping the original deadline unchanged.
    if not pending and _eligibility(request).status == UNKNOWN:
        return TriggerGate(ATTEMPT_GATE, FAIL, reason="UNKNOWN_MANDATORY_INPUT"), False
    interval = _threshold(policy.sample_interval_seconds, "sample_interval_seconds")
    if elapsed % interval != 0:
        return TriggerGate(ATTEMPT_GATE, UNKNOWN, float(elapsed),
                           float(policy.window_close_seconds), "EVALUATION_OFF_GRID"), False
    if elapsed < _threshold(policy.window_open_seconds, "window_open_seconds"):
        return TriggerGate(ATTEMPT_GATE, FAIL, float(elapsed),
                           float(policy.window_close_seconds),
                           "BEFORE_ACCEPTANCE_WINDOW"), False
    if elapsed > _threshold(policy.window_close_seconds, "window_close_seconds"):
        return TriggerGate(ATTEMPT_GATE, FAIL, float(elapsed),
                           float(policy.window_close_seconds),
                           "ACCEPTANCE_DEADLINE_PASSED"), False
    if pending:
        return TriggerGate(ATTEMPT_GATE, UNKNOWN, float(elapsed),
                           float(policy.window_close_seconds), "MINUTE_BAR_PENDING",
                           (close.record_id,)), False
    return TriggerGate(ATTEMPT_GATE, PASS, float(elapsed),
                       float(policy.window_close_seconds)), False


def evaluate_orb5_trigger(request: TriggerRequest) -> TriggerAssessment:
    """Report every supplied trigger gate and the state they support, with no side effect.

    Returning ALERT_TRIGGERED describes the supplied inputs at this instant only.
    It does not send, approve the referenced definition, prove tape or quote
    coverage or authorize delivery.
    """
    if not isinstance(request, TriggerRequest):
        raise RecordError("TriggerRequest is required")
    candidate, policy, at = request.candidate, request.policy, request.evaluated_at
    elapsed = _seconds(at, candidate.crossed_at)
    attempt, reset = _attempt(request, elapsed)
    acceptance, samples, accepting = _acceptance(request)
    gates = (attempt, acceptance, _participation(request), _last_trade(request),
             _eligibility(request), _geometry(request))
    if attempt.reason in INVALIDATIONS:
        state = StrategyState("INVALIDATED")
    elif attempt.reason == "ACCEPTANCE_DEADLINE_PASSED":
        state = StrategyState("ARMED", WAITING_FOR_RESET)
    elif all(row.status == PASS for row in gates):
        state = StrategyState("ALERT_TRIGGERED")
    else:
        state = StrategyState("ARMED", CROSSING_OBSERVED)
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    return TriggerAssessment(at, state, gates, samples, accepting, float(elapsed), reset,
                             reasons, candidate, policy.version, policy.definition_reference)


class Orb5TriggerMachine:
    """One serially owned `(session, symbol, direction, arm)` attempt owner.

    The machine proposes canonical transitions for the M4.2 engine and the M5.1
    store; it never writes, sends or advances itself. Local state moves only when
    the caller confirms the proposed transition after storage acknowledged it.
    Attempt identity, the reserved number, the quota, the required reset and the
    post-action cooldown are held here so they survive one session's attempts.
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
        self._candidate: FrozenCandidate | None = None
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
    def started_attempt_count(self) -> int:
        return self._started

    @property
    def pending_attempt_number(self) -> int:
        """The number reserved for the next structure, heads-up or crossing."""
        return self._reserved if self._reserved is not None else self._started + 1

    def current_state(self) -> StrategyState:
        return self._state

    def current_candidate(self) -> FrozenCandidate | None:
        return self._candidate

    def reserve_heads_up(self, at: datetime) -> int:
        """Reserve this structure's attempt number before any crossing.

        A pre-crossing heads-up keeps its reserved number until the crossing or
        session expiry; it never consumes the quota by itself.
        """
        _instant(at, "reservation time")
        if self._reserved is not None:
            raise RecordError("this structure already reserved its attempt number")
        self._reserved = self._started + 1
        return self._reserved

    def attempt_quota(self, at: datetime) -> TriggerGate:
        """Whether a fresh crossing at `at` may open another attempt."""
        instant = _instant(at, "crossing time")
        policy = self._policy
        limit = _count(policy.max_attempts_per_direction, "max_attempts_per_direction", minimum=1)
        if self._started >= limit:
            return TriggerGate(QUOTA_GATE, FAIL, float(self._started), float(limit),
                               "ATTEMPT_QUOTA_EXHAUSTED")
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
            source="DERIVED_M62", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID")

    def _transition(self, *, record_id: str, at: datetime, state: StrategyState, reason: str,
                    input_record_ids: tuple[str, ...] = ()) -> StrategyStateTransition:
        _label(record_id, "transition record ID")
        if (self._state, state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M6.2 rules")
        if self._time is not None and at < self._time:
            raise RecordError("evaluation time cannot move backward")
        self._time = at
        return StrategyStateTransition(
            record_id=record_id, metadata=self._metadata(at), strategy_id=STRATEGY_ID,
            strategy_version=self._version, occurred_at=at,
            from_state=self._state.state, from_substate=self._state.substate,
            to_state=state.state, to_substate=state.substate, reason=reason,
            feature_snapshot_id=None, input_record_ids=input_record_ids)

    def open_attempt(self, candidate: FrozenCandidate, *, record_id: str,
                     ) -> tuple[StrategyStateTransition, ...]:
        """Propose the transition that opens one frozen attempt at its crossing."""
        if not isinstance(candidate, FrozenCandidate):
            raise RecordError("candidate must be FrozenCandidate")
        if (candidate.direction != self._direction or candidate.mode != self._policy.mode):
            raise RecordError("candidate does not match this attempt owner")
        if self._state != StrategyState("ARMED"):
            raise RecordError("only an armed owner with no open attempt may cross")
        if candidate.attempt_number != self.pending_attempt_number:
            raise RecordError("the crossing must use the reserved attempt number")
        quota = self.attempt_quota(candidate.crossed_at)
        if quota.status != PASS:
            raise RecordError("attempt quota refuses this crossing: " + str(quota.reason))
        transition = self._transition(record_id=record_id, at=candidate.crossed_at,
                                      state=StrategyState("ARMED", CROSSING_OBSERVED),
                                      reason="CROSSING_OBSERVED")
        self._pending, self._effect = transition, ("OPEN", candidate)
        return (transition,)

    def propose(self, request: TriggerRequest, *, record_id: str,
                ) -> tuple[TriggerAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transition a caller must store first."""
        if not isinstance(request, TriggerRequest):
            raise RecordError("TriggerRequest is required")
        if self._candidate is None or request.candidate != self._candidate:
            raise RecordError("evaluation does not match this owner's frozen attempt")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        assessment = evaluate_orb5_trigger(request)
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
        """Propose the return to ARMED after the required inside-range close."""
        if not isinstance(close, MinuteClose):
            raise RecordError("reset requires MinuteClose")
        instant = _instant(at, "reset time")
        if self._candidate is None:
            raise RecordError("reset requires a frozen attempt")
        if not close.final or not close.coverage_known or close.available_at > instant:
            raise RecordError("only an available final close can reset an attempt")
        if not _inside_range(self._candidate, close):
            raise RecordError("the reset close must lie strictly inside the opening range")
        transition = self._transition(record_id=record_id, at=instant,
                                      state=StrategyState("ARMED"),
                                      reason="INSIDE_OR_CLOSE_RESET",
                                      input_record_ids=())
        self._pending, self._effect = transition, ("RESET", None)
        return (transition,)

    def expire(self, *, at: datetime, reason: str, record_id: str,
               ) -> tuple[StrategyStateTransition, ...]:
        """Propose expiry of a pending attempt at the evaluation-window end."""
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
            self._candidate = payload
            self._started += 1
            self._reserved = None
            self._reset_satisfied = False
        elif kind == "TRIGGER":
            self._action_at = payload
        elif kind == "RESET":
            self._candidate = None
            self._reset_satisfied = True
        elif kind == "EXPIRE":
            self._candidate = None
        self._pending, self._effect = None, None
        return self._state

    def restore(self, state: StrategyState, *, candidate: FrozenCandidate | None = None,
                started_attempt_count: int = 0, reset_satisfied: bool = True,
                last_action_at: datetime | None = None) -> StrategyState:
        """Position an unused owner at facts recovered from storage (M5.5).

        Every quota fact is restored explicitly. Nothing is inferred from the
        state alone, so a recovered owner cannot silently regain an attempt.
        """
        if self._pending is not None or self._time is not None or self._started:
            raise RecordError("restore requires an unused trigger owner")
        if not isinstance(state, StrategyState) or state.state not in STATES:
            raise RecordError("restored state is not an M6.2 state")
        if state.substate not in (None, CROSSING_OBSERVED, WAITING_FOR_RESET):
            raise RecordError("restored substate is not an M6.2 substate")
        if candidate is not None and not isinstance(candidate, FrozenCandidate):
            raise RecordError("restored candidate must be FrozenCandidate or null")
        if type(reset_satisfied) is not bool:
            raise RecordError("restored reset flag must be true or false")
        self._started = _count(started_attempt_count, "started_attempt_count")
        self._candidate = candidate
        self._reset_satisfied = reset_satisfied
        self._action_at = None if last_action_at is None else _instant(
            last_action_at, "last_action_at")
        self._state = state
        return self._state


__all__ = [
    "ATTEMPT_GATE", "CROSSED", "CrossingResult", "DATA_MODE", "FrozenCandidate", "GATE_NAMES",
    "INVALIDATIONS", "MODES", "MODE_VARIANTS", "MinuteClose", "NOT_CROSSED", "Observation",
    "Orb5TriggerMachine", "ProjectedVolume", "QUOTA_GATE", "QUOTE_PROJECTED", "RULES_VERSION",
    "STATES", "STRATEGY_ID", "SampleResult", "TAPE", "TRIGGER_GATES", "TRIGGER_VERSION",
    "TapeIntensity", "TriggerAssessment", "TriggerGate", "TriggerPolicy", "TriggerRequest",
    "candidate_boundary", "evaluate_crossing", "evaluate_orb5_trigger", "freeze_candidate",
    "trigger_rules",
]
