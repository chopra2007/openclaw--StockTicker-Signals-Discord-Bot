"""M8.4 offline `FIRST_PULLBACK_VWAP` context, trigger, risk and confidence at one instant.

This is the strategy that consumes the M8.3 measurement. M8.3 measures one frozen
impulse leg and the pullback that followed it; this module carries that measured
structure the rest of the way named by PLAYBOOKS section 6: the mandatory
continuation context, the pullback checks, the reversal-bar trigger, the supplied
stop and targets and the supplied M4.4 confidence, through
`PULLBACK_FORMING -> ARMED -> ALERT_TRIGGERED`.

The caller supplies every threshold, every observation and every measured result.
PLAYBOOKS sections 6 and 17 still own the unresolved `FIRST_PULLBACK_VWAP`
questions - the impulse and reversal-bar definitions, swing confirmation, how a
pullback is counted, the slope and cross convention, the retracement band, the
volume-contraction ratio, the VWAP distances and the AVWAP question - and M0.3B
is PROPOSED, so this module adopts no number of its own, applies no confidence
cutoff and names no rule of its own. What no approved definition supplies is
reported in `unavailable` instead of being filled in.

ALERT_TRIGGERED means the supplied inputs passed every gate at one evaluation
instant. It is not an alert, an approved rule, proof of bar, tape or quote
coverage, a backtest result or permission to act. A missing, stale, ambiguous or
mismatched input keeps the owner below the state it would otherwise reach; it
never becomes a passing gate. Nothing here reads a clock, fetches data, opens a
database, stores a record, assembles a candidate or sends anything: the alert
candidate, the suppression record, the options view and delivery keep their M4.5,
M4.6 and M15 owners.
"""

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
import json

from .confidence import ConfidenceResult
from .impulse_pullback import (
    DATA_MODE as MEASUREMENT_DATA_MODE,
    FEATURE_VERSION as MEASUREMENT_VERSION,
    IMPULSE_COMPLETE_NAME,
    IMPULSE_DISTANCE_ATR_NAME,
    IMPULSE_ORDERED_NAME,
    PULLBACK_COMPLETE_NAME,
    PULLBACK_SPECS,
    PullbackPolicy,
    RETRACEMENT_NAME,
    VOLUME_RATIO_NAME,
    VWAP_SPECS,
)
from .orb5_trigger import MODES, Observation
from .quote_events import QuoteEventDecision
from .state_transitions import TransitionRules
from .strategy_interface import StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import (
    ConfidenceBreakdown, FeatureSnapshot, RecordError, RiskLevel, SessionRecord, SourceMetadata,
    StrategyStateTransition, TargetLevel,
)
from .utils.time_context import as_utc


STRATEGY_ID = "FIRST_PULLBACK_VWAP"
PULLBACK_VERSION = "M84_FIRST_PULLBACK_VWAP_V1"
RULES_VERSION = "M84_FIRST_PULLBACK_VWAP_RULES_V1"
DATA_MODE = "SUPPLIED_FIRST_PULLBACK_VWAP_INPUTS"

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

# The M8.3 values this strategy reads, named exactly as that milestone publishes
# them so no measurement is recomputed here.
PULLBACK_EXTREME_NAME = PULLBACK_SPECS[0][0]
REVERSAL_HIGH_NAME = PULLBACK_SPECS[2][0]
REVERSAL_LOW_NAME = PULLBACK_SPECS[3][0]
IMPULSE_FROM_VWAP_NAME, PULLBACK_FROM_VWAP_NAME = tuple(name for name, _ in VWAP_SPECS)

MEASUREMENT_GATE = "PULLBACK_MEASUREMENT"
IMPULSE_GATE = "IMPULSE_SIZE"
IMPULSE_VWAP_GATE = "IMPULSE_FROM_VWAP"
VWAP_SIDE_GATE = "PRICE_VS_VWAP"
VWAP_SLOPE_GATE = "VWAP_SLOPE"
VWAP_CROSS_GATE = "VWAP_CROSSES"
RS_GATE = "RELATIVE_STRENGTH"
RETRACEMENT_GATE = "RETRACEMENT_BAND"
VOLUME_GATE = "PULLBACK_VOLUME_RATIO"
SUPPORT_GATE = "PULLBACK_SUPPORT"
TRIGGER_GATE = "REVERSAL_BAR_BREAK"
SPREAD_GATE = "SPREAD_BPS"
SEQUENCE_GATE = "PULLBACK_SEQUENCE"
RISK_GATE = "RISK_TARGETS"
CONFIDENCE_GATE = "CONFIDENCE"
PULLBACK_GATES = (
    MEASUREMENT_GATE, IMPULSE_GATE, IMPULSE_VWAP_GATE, VWAP_SIDE_GATE, VWAP_SLOPE_GATE,
    VWAP_CROSS_GATE, RS_GATE, RETRACEMENT_GATE, VOLUME_GATE, SUPPORT_GATE, TRIGGER_GATE,
    SPREAD_GATE, SEQUENCE_GATE, RISK_GATE, CONFIDENCE_GATE,
)

PULLBACK_FORMING = "PULLBACK_FORMING"
STATES = ("SETUP_FORMING", "ARMED", "ALERT_TRIGGERED", "INVALIDATED", "EXPIRED")
SUBSTATES = (PULLBACK_FORMING,)
# Only these supplied facts end a formed pullback outright. A merely failing known
# gate leaves the owner where it already stood, because the next completed minute
# may satisfy it.
INVALIDATIONS = (
    "COVERAGE_LOST", "PULLBACK_ORDINAL_BEYOND_SUPPLIED_MAXIMUM",
    "RETRACEMENT_BEYOND_SUPPLIED_KILL", "VWAP_CROSSES_ABOVE_SUPPLIED_MAXIMUM",
)
# No approved definition supplies these, so the result keeps naming them instead
# of filling them in.
UNDEFINED = (
    "AVWAP_QUESTION_UNDEFINED", "CONFIDENCE_FLOOR_UNDEFINED",
    "FIRST_PULLBACK_COUNTING_UNDEFINED", "IMPULSE_DEFINITION_UNDEFINED",
    "STOP_PAD_UNDEFINED", "TAPE_ACCELERATION_PREFERENCE_UNDEFINED",
    "TARGET_REWARD_MINIMUM_UNDEFINED", "VWAP_SLOPE_CONVENTION_UNDEFINED",
)


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in ("UNKNOWN", "UNSPECIFIED")):
        raise RecordError(f"{name} must be explicit")
    return value


def _number(value: object, name: str) -> Fraction:
    """One supplied finite number, of either sign."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    try:
        return Fraction(str(value))
    except (ValueError, ArithmeticError) as exc:  # non-finite text is not a number
        raise RecordError(f"{name} must be finite") from exc


def _threshold(value: object, name: str, *, positive: bool = False) -> Fraction:
    number = _number(value, name)
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
class PullbackVwapPolicy:
    """The caller's own continuation context, pullback, trigger and staleness values.

    Nothing is defaulted. The values describe the caller's own definition;
    supplying them neither adopts a proposed rule nor claims the referenced
    definition was approved. The slope and the relative-strength reading arrive
    already oriented to the trade's own direction, because which convention names
    a rising VWAP stays with the unresolved definition.
    """

    version: str
    definition_reference: str
    direction: str
    mode: str
    max_observation_age_seconds: float
    min_impulse_atr_multiple: float
    min_impulse_vwap_atr_multiple: float
    min_vwap_slope: float
    max_vwap_crosses: int
    min_relative_strength: float
    min_retracement: float
    max_retracement: float
    kill_retracement: float
    max_pullback_volume_ratio: float
    max_support_atr_multiple: float
    min_trigger_offset: float
    min_trigger_atr_multiple: float
    max_spread_bps: float
    max_pullback_ordinal: int
    min_first_target_r_multiple: float

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("policy direction must be LONG or SHORT")
        if self.mode not in MODES:
            raise RecordError("observation arm is not supported")
        _threshold(self.max_observation_age_seconds, "max_observation_age_seconds")
        _threshold(self.max_support_atr_multiple, "max_support_atr_multiple")
        _threshold(self.min_relative_strength, "min_relative_strength")
        _count(self.max_vwap_crosses, "max_vwap_crosses", minimum=1)
        _count(self.max_pullback_ordinal, "max_pullback_ordinal", minimum=1)
        for name in ("min_impulse_atr_multiple", "min_impulse_vwap_atr_multiple",
                     "min_vwap_slope", "max_pullback_volume_ratio", "min_trigger_offset",
                     "min_trigger_atr_multiple", "max_spread_bps",
                     "min_first_target_r_multiple"):
            _threshold(getattr(self, name), name, positive=True)
        band = tuple(_threshold(getattr(self, name), name, positive=True)
                     for name in ("min_retracement", "max_retracement", "kill_retracement"))
        if not band[0] < band[1] <= band[2]:
            raise RecordError("the retracement band must rise to its own kill value")
        if band[2] > 1:
            raise RecordError("kill_retracement must be a share of one")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version, "definition_reference": self.definition_reference,
            "direction": self.direction, "mode": self.mode,
            "max_observation_age_seconds": self.max_observation_age_seconds,
            "min_impulse_atr_multiple": self.min_impulse_atr_multiple,
            "min_impulse_vwap_atr_multiple": self.min_impulse_vwap_atr_multiple,
            "min_vwap_slope": self.min_vwap_slope,
            "max_vwap_crosses": self.max_vwap_crosses,
            "min_relative_strength": self.min_relative_strength,
            "min_retracement": self.min_retracement, "max_retracement": self.max_retracement,
            "kill_retracement": self.kill_retracement,
            "max_pullback_volume_ratio": self.max_pullback_volume_ratio,
            "max_support_atr_multiple": self.max_support_atr_multiple,
            "min_trigger_offset": self.min_trigger_offset,
            "min_trigger_atr_multiple": self.min_trigger_atr_multiple,
            "max_spread_bps": self.max_spread_bps,
            "max_pullback_ordinal": self.max_pullback_ordinal,
            "min_first_target_r_multiple": self.min_first_target_r_multiple,
        }


@dataclass(frozen=True)
class VwapContext:
    """One supplied VWAP level, its own directional slope and its cross count.

    The level is the same one the supplied M8.3 measurement used; nothing is
    recomputed here. Each part may be missing on its own, and silence is never a
    rising VWAP or an uncrossed session.
    """

    record_id: str
    definition_reference: str
    available_at: datetime
    coverage_complete: bool
    level: float | None = None
    slope: float | None = None
    crosses: int | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.record_id, "VWAP record ID")
        _label(self.definition_reference, "VWAP definition reference")
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))
        _flag(self.coverage_complete, "coverage_complete")
        if self.level is not None:
            _threshold(self.level, "VWAP level", positive=True)
        if self.slope is not None:
            _number(self.slope, "VWAP slope")
        if self.crosses is not None:
            _count(self.crosses, "VWAP crosses")
        if self.level is None or self.slope is None or self.crosses is None:
            _label(self.missing_reason, "VWAP missing reason")
        elif self.missing_reason is not None:
            raise RecordError("a complete VWAP context cannot also report a missing reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "definition_reference": self.definition_reference,
            "available_at": _text_time(self.available_at),
            "coverage_complete": self.coverage_complete, "level": self.level,
            "slope": self.slope, "crosses": self.crosses,
            "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class RelativeStrength:
    """One supplied relative-strength reading, already oriented to the direction.

    The lookback, the benchmark and the return basis belong to the caller's own
    definition reference. A missing reading stays an explicit unknown.
    """

    record_id: str
    definition_reference: str
    available_at: datetime
    coverage_complete: bool
    value: float | None = None
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _label(self.record_id, "relative-strength record ID")
        _label(self.definition_reference, "relative-strength definition reference")
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))
        _flag(self.coverage_complete, "coverage_complete")
        if self.value is None:
            _label(self.missing_reason, "relative-strength missing reason")
        else:
            _number(self.value, "relative-strength value")
            if self.missing_reason is not None:
                raise RecordError("a supplied reading cannot also report a missing reason")

    def as_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id, "definition_reference": self.definition_reference,
            "available_at": _text_time(self.available_at),
            "coverage_complete": self.coverage_complete, "value": self.value,
            "missing_reason": self.missing_reason,
        }


@dataclass(frozen=True)
class PullbackStructural:
    """One supplied stop and target set measured for this pullback continuation.

    The caller measures them under its own definition reference; this module
    reports them and never calculates a stop, a target or an R multiple. A missing
    measurement stays an explicit unknown with its own reason and carries no
    targets beside it.
    """

    definition_reference: str
    direction: str
    impulse_frozen_at: datetime
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
        for name in ("impulse_frozen_at", "evaluated_at", "available_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if self.evaluated_at < self.impulse_frozen_at:
            raise RecordError("a structural reading cannot precede its impulse freeze")
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
class PullbackGate:
    name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in PULLBACK_GATES:
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
class PullbackRequest:
    """One evaluation of one supplied M8.3 impulse and pullback measurement.

    `strategy_version` and `definition_reference` describe the caller's own
    definition. Supplying them neither adopts a proposed rule nor claims the
    referenced definition was approved. `measurement_policy` is the same M8.3
    policy that produced the snapshot, so the direction the legs were read in
    stays with the measurement instead of being assumed here.
    """

    measurement: FeatureSnapshot
    measurement_policy: PullbackPolicy
    policy: PullbackVwapPolicy
    evaluated_at: datetime
    symbol: str
    strategy_version: str
    definition_reference: str
    impulse_started_at: datetime
    impulse_frozen_at: datetime
    atr_1m: float | None = None
    pullback_ordinal: int | None = None
    vwap: VwapContext | None = None
    relative_strength: RelativeStrength | None = None
    last_trade: Observation | None = None
    quote: QuoteEventDecision | None = None
    structural: PullbackStructural | None = None
    confidence: ConfidenceResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.measurement, FeatureSnapshot):
            raise RecordError("measurement must be the supplied M8.3 FeatureSnapshot")
        if not isinstance(self.measurement_policy, PullbackPolicy):
            raise RecordError("measurement policy must be the supplied M8.3 PullbackPolicy")
        if not isinstance(self.policy, PullbackVwapPolicy):
            raise RecordError("policy must be PullbackVwapPolicy")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        for name in ("impulse_started_at", "impulse_frozen_at"):
            object.__setattr__(self, name, _instant(getattr(self, name), name))
        if self.impulse_started_at >= self.impulse_frozen_at:
            raise RecordError("the impulse window must start before it freezes")
        if self.evaluated_at < self.impulse_frozen_at:
            raise RecordError("the pullback cannot be evaluated before the impulse froze")
        _label(self.symbol, "symbol")
        _label(self.strategy_version, "strategy version")
        _label(self.definition_reference, "definition reference")
        if self.atr_1m is not None:
            _threshold(self.atr_1m, "minute ATR", positive=True)
        if self.pullback_ordinal is not None:
            _count(self.pullback_ordinal, "pullback ordinal", minimum=1)
        if self.vwap is not None and not isinstance(self.vwap, VwapContext):
            raise RecordError("vwap must be VwapContext or null")
        if self.relative_strength is not None and not isinstance(
                self.relative_strength, RelativeStrength):
            raise RecordError("relative strength must be RelativeStrength or null")
        if self.last_trade is not None and not isinstance(self.last_trade, Observation):
            raise RecordError("last trade must be the supplied M6.2 Observation or null")
        if self.quote is not None and not isinstance(self.quote, QuoteEventDecision):
            raise RecordError("quote must be the supplied QuoteEventDecision or null")
        if self.structural is not None and not isinstance(self.structural, PullbackStructural):
            raise RecordError("structural must be PullbackStructural or null")
        if self.confidence is not None and not isinstance(self.confidence, ConfidenceResult):
            raise RecordError("confidence must be the supplied M4.4 ConfidenceResult or null")

    @property
    def direction(self) -> str:
        """The continuation direction, taken from the caller's own policy."""
        return self.policy.direction

    @property
    def window(self) -> tuple[datetime, datetime]:
        """The frozen impulse window this evaluation stands on."""
        return self.impulse_started_at, self.impulse_frozen_at


@dataclass(frozen=True)
class PullbackAssessment:
    """Immutable result of one evaluation; the caller owns storage and delivery.

    Each measured field is populated only by the gate that passed for it, so a
    refused or unknown input leaves its own facts absent instead of half-stated.
    """

    evaluated_at: datetime
    state: StrategyState
    direction: str
    gates: tuple[PullbackGate, ...]
    reasons: tuple[str, ...]
    impulse_started_at: datetime
    impulse_frozen_at: datetime
    measurement_record_id: str = ""
    impulse_distance_atr: float | None = None
    impulse_from_vwap_atr: float | None = None
    retracement: float | None = None
    volume_ratio: float | None = None
    support_from_vwap_atr: float | None = None
    trigger_price: float | None = None
    last_price: float | None = None
    spread_bps: float | None = None
    pullback_ordinal: int | None = None
    risk: RiskLevel | None = None
    targets: tuple[TargetLevel, ...] = ()
    confidence: ConfidenceBreakdown | None = None
    structural_input_ids: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = UNDEFINED
    policy_version: str = ""
    definition_reference: str = ""
    strategy_version: str = ""

    def gate(self, name: str) -> PullbackGate:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        confidence = self.confidence
        return {
            "pullback_version": PULLBACK_VERSION, "strategy_id": STRATEGY_ID,
            "evaluated_at": _text_time(self.evaluated_at), "state": self.state.state,
            "substate": self.state.substate, "direction": self.direction,
            "gates": [row.as_dict() for row in self.gates], "reasons": list(self.reasons),
            "impulse_started_at": _text_time(self.impulse_started_at),
            "impulse_frozen_at": _text_time(self.impulse_frozen_at),
            "measurement_record_id": self.measurement_record_id,
            "impulse_distance_atr": self.impulse_distance_atr,
            "impulse_from_vwap_atr": self.impulse_from_vwap_atr,
            "retracement": self.retracement, "volume_ratio": self.volume_ratio,
            "support_from_vwap_atr": self.support_from_vwap_atr,
            "trigger_price": self.trigger_price, "last_price": self.last_price,
            "spread_bps": self.spread_bps, "pullback_ordinal": self.pullback_ordinal,
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


def pullback_rules() -> TransitionRules:
    """Exactly the M8.4 states, starting where the M8.3 measurement leaves off.

    PLAYBOOKS section 6 needs the formed pullback before its trigger, so an
    evaluation that already passes everything still records ARMED before its
    actionable state, and an actionable continuation never falls back to ARMED.
    """
    forming = StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    armed = StrategyState("ARMED")
    triggered = StrategyState("ALERT_TRIGGERED")
    invalidated = StrategyState("INVALIDATED")
    expired = StrategyState("EXPIRED")
    allowed = (
        (forming, armed), (armed, triggered), (forming, invalidated),
        (armed, invalidated), (triggered, invalidated),
    )
    return TransitionRules(RULES_VERSION, forming, allowed + tuple(
        (state, expired) for state in (forming, armed, triggered, invalidated)))


def _reading(request: PullbackRequest, name: str) -> tuple[Fraction | None, str | None,
                                                           tuple[str, ...]]:
    """One named M8.3 value, or the exact reason that value is unavailable."""
    supplied = next((row for row in request.measurement.features if row.name == name), None)
    if supplied is None:
        return None, "MEASUREMENT_VALUE_ABSENT_" + name, ()
    ids = tuple(supplied.input_record_ids)
    if supplied.value is None:
        return None, supplied.missing_reason or "MEASUREMENT_VALUE_UNAVAILABLE", ids
    return _number(supplied.value, name), None, ids


def _measurement(request: PullbackRequest) -> PullbackGate:
    """Only a current, complete M8.3 measurement of this subject opens the chain.

    A snapshot measured at another instant, for another symbol, in another
    direction or over another impulse window is not this evaluation's fact,
    however complete it looks.
    """
    supplied = request.measurement
    ids = tuple(supplied.input_record_ids)
    if supplied.feature_version != MEASUREMENT_VERSION:
        return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason="MEASUREMENT_VERSION_MISMATCH",
                            input_record_ids=ids)
    if supplied.metadata.data_mode != MEASUREMENT_DATA_MODE:
        return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason="MEASUREMENT_DATA_MODE_MISMATCH",
                            input_record_ids=ids)
    if supplied.metadata.instrument_id != request.symbol:
        return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason="MEASUREMENT_SYMBOL_MISMATCH",
                            input_record_ids=ids)
    if request.measurement_policy.direction != request.direction:
        return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason="MEASUREMENT_DIRECTION_MISMATCH",
                            input_record_ids=ids)
    # The canonical snapshot already refuses to be evaluated before it was
    # available, so its own instant is the only availability check needed here.
    if supplied.evaluated_at != request.evaluated_at:
        return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason="MEASUREMENT_NOT_CURRENT",
                            input_record_ids=ids)
    for name, missing in ((IMPULSE_COMPLETE_NAME, "IMPULSE_INCOMPLETE"),
                          (PULLBACK_COMPLETE_NAME, "PULLBACK_INCOMPLETE")):
        value, reason, _ids = _reading(request, name)
        if value is None:
            return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason=reason, input_record_ids=ids)
        if value == 0:
            leg = PULLBACK_EXTREME_NAME if name == PULLBACK_COMPLETE_NAME else (
                IMPULSE_DISTANCE_ATR_NAME)
            _value, leg_reason, _leg_ids = _reading(request, leg)
            return PullbackGate(MEASUREMENT_GATE, UNKNOWN, reason=(
                missing if leg_reason is None else missing + "_" + leg_reason),
                input_record_ids=ids)
    return PullbackGate(MEASUREMENT_GATE, PASS, input_record_ids=ids)


def _minimum(request: PullbackRequest, gate: str, name: str, limit: Fraction,
             reason: str) -> tuple[PullbackGate, Fraction | None]:
    """One supplied M8.3 value that must reach the caller's own minimum."""
    value, missing, ids = _reading(request, name)
    if value is None:
        return PullbackGate(gate, UNKNOWN, None, float(limit), missing, ids), None
    passed = value >= limit
    return (PullbackGate(gate, PASS if passed else FAIL, float(value), float(limit),
                         None if passed else reason, ids), value)


def _impulse(request: PullbackRequest) -> tuple[PullbackGate, Fraction | None]:
    """The frozen impulse must be large enough and must have run in order.

    An extreme that printed before its own origin is not a continuation impulse,
    however far apart the two prices sit.
    """
    ordered, missing, ids = _reading(request, IMPULSE_ORDERED_NAME)
    limit = _threshold(request.policy.min_impulse_atr_multiple,
                       "min_impulse_atr_multiple", positive=True)
    if ordered is None:
        return PullbackGate(IMPULSE_GATE, UNKNOWN, None, float(limit), missing, ids), None
    if ordered == 0:
        return (PullbackGate(IMPULSE_GATE, FAIL, None, float(limit),
                             "IMPULSE_EXTREME_BEFORE_ITS_ORIGIN", ids), None)
    return _minimum(request, IMPULSE_GATE, IMPULSE_DISTANCE_ATR_NAME, limit,
                    "IMPULSE_BELOW_SUPPLIED_MINIMUM")


def _usable(observation: Observation, policy: PullbackVwapPolicy,
            instant: datetime) -> str | None:
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


def _last_price(request: PullbackRequest) -> tuple[Fraction | None, str | None, tuple[str, ...]]:
    """The usable supplied last trade, or the exact reason there is none."""
    supplied = request.last_trade
    if supplied is None:
        return None, "LAST_TRADE_UNAVAILABLE", ()
    ids = (supplied.record_id,)
    reason = _usable(supplied, request.policy, request.evaluated_at)
    if reason is not None:
        return None, reason, ids
    return _price(supplied.price), None, ids


def _vwap_reason(request: PullbackRequest) -> tuple[str | None, tuple[str, ...]]:
    """Why the supplied VWAP context cannot be read at all, if it cannot."""
    supplied = request.vwap
    if supplied is None:
        return "VWAP_CONTEXT_ABSENT", ()
    ids = (supplied.record_id,)
    if supplied.available_at > request.evaluated_at:
        return "VWAP_NOT_AVAILABLE", ids
    if not supplied.coverage_complete:
        return "VWAP_COVERAGE_INCOMPLETE", ids
    return None, ids


def _vwap_side(request: PullbackRequest, last: Fraction | None, missing: str | None,
               last_ids: tuple[str, ...]) -> PullbackGate:
    """The supplied last trade must stand on the trade's own side of the VWAP."""
    reason, ids = _vwap_reason(request)
    supplied = request.vwap
    if reason is not None or supplied.level is None:
        return PullbackGate(VWAP_SIDE_GATE, UNKNOWN,
                            reason=reason or supplied.missing_reason, input_record_ids=ids)
    level = _price(supplied.level)
    joined = tuple(sorted({*ids, *last_ids}))
    if last is None:
        status = FAIL if missing == "COVERAGE_LOST" else UNKNOWN
        return PullbackGate(VWAP_SIDE_GATE, status, None, float(level),
                            _missing_reason(missing), joined)
    beyond = _sign(request.direction) * (last - level) > 0
    return PullbackGate(VWAP_SIDE_GATE, PASS if beyond else FAIL, float(last), float(level),
                        None if beyond else "LAST_ON_THE_WRONG_SIDE_OF_VWAP", joined)


def _vwap_slope(request: PullbackRequest) -> PullbackGate:
    """The supplied directional slope must reach the caller's own minimum."""
    limit = _threshold(request.policy.min_vwap_slope, "min_vwap_slope", positive=True)
    reason, ids = _vwap_reason(request)
    supplied = request.vwap
    if reason is not None or supplied.slope is None:
        return PullbackGate(VWAP_SLOPE_GATE, UNKNOWN, None, float(limit),
                            reason or supplied.missing_reason, ids)
    slope = _number(supplied.slope, "VWAP slope") * _sign(request.direction)
    passed = slope >= limit
    return PullbackGate(VWAP_SLOPE_GATE, PASS if passed else FAIL, float(slope), float(limit),
                        None if passed else "VWAP_SLOPE_BELOW_SUPPLIED_MINIMUM", ids)


def _vwap_crosses(request: PullbackRequest) -> PullbackGate:
    """A session that crossed its VWAP too often is closed, not merely unarmed."""
    limit = _count(request.policy.max_vwap_crosses, "max_vwap_crosses", minimum=1)
    reason, ids = _vwap_reason(request)
    supplied = request.vwap
    if reason is not None or supplied.crosses is None:
        return PullbackGate(VWAP_CROSS_GATE, UNKNOWN, None, float(limit),
                            reason or supplied.missing_reason, ids)
    crosses = _count(supplied.crosses, "VWAP crosses")
    passed = crosses <= limit
    return PullbackGate(VWAP_CROSS_GATE, PASS if passed else FAIL, float(crosses), float(limit),
                        None if passed else "VWAP_CROSSES_ABOVE_SUPPLIED_MAXIMUM", ids)


def _relative_strength(request: PullbackRequest) -> PullbackGate:
    """The supplied directional relative-strength reading and its own minimum."""
    limit = _threshold(request.policy.min_relative_strength, "min_relative_strength")
    supplied = request.relative_strength
    if supplied is None:
        return PullbackGate(RS_GATE, UNKNOWN, None, float(limit), "RELATIVE_STRENGTH_ABSENT")
    ids = (supplied.record_id,)
    if supplied.available_at > request.evaluated_at:
        return PullbackGate(RS_GATE, UNKNOWN, None, float(limit),
                            "RELATIVE_STRENGTH_NOT_AVAILABLE", ids)
    if not supplied.coverage_complete:
        return PullbackGate(RS_GATE, UNKNOWN, None, float(limit),
                            "RELATIVE_STRENGTH_COVERAGE_INCOMPLETE", ids)
    if supplied.value is None:
        return PullbackGate(RS_GATE, UNKNOWN, None, float(limit), supplied.missing_reason, ids)
    value = _number(supplied.value, "relative-strength value") * _sign(request.direction)
    # PLAYBOOKS section 6 asks for relative strength strictly beyond its own
    # minimum, so equality is not a passing reading.
    passed = value > limit
    return PullbackGate(RS_GATE, PASS if passed else FAIL, float(value), float(limit),
                        None if passed else "RELATIVE_STRENGTH_NOT_BEYOND_SUPPLIED_MINIMUM", ids)


def _retracement(request: PullbackRequest) -> tuple[PullbackGate, Fraction | None]:
    """The measured retracement against the caller's own band and kill value."""
    policy = request.policy
    lowest = _threshold(policy.min_retracement, "min_retracement", positive=True)
    highest = _threshold(policy.max_retracement, "max_retracement", positive=True)
    kill = _threshold(policy.kill_retracement, "kill_retracement", positive=True)
    value, missing, ids = _reading(request, RETRACEMENT_NAME)
    if value is None:
        return PullbackGate(RETRACEMENT_GATE, UNKNOWN, None, float(highest), missing, ids), None
    if value > kill:
        return (PullbackGate(RETRACEMENT_GATE, FAIL, float(value), float(kill),
                             "RETRACEMENT_BEYOND_SUPPLIED_KILL", ids), value)
    if value < lowest:
        return (PullbackGate(RETRACEMENT_GATE, FAIL, float(value), float(lowest),
                             "RETRACEMENT_BELOW_SUPPLIED_BAND", ids), value)
    if value > highest:
        return (PullbackGate(RETRACEMENT_GATE, FAIL, float(value), float(highest),
                             "RETRACEMENT_ABOVE_SUPPLIED_BAND", ids), value)
    return PullbackGate(RETRACEMENT_GATE, PASS, float(value), float(highest), None, ids), value


def _volume_ratio(request: PullbackRequest) -> tuple[PullbackGate, Fraction | None]:
    """The measured pullback volume must contract to the caller's own share."""
    limit = _threshold(request.policy.max_pullback_volume_ratio,
                       "max_pullback_volume_ratio", positive=True)
    value, missing, ids = _reading(request, VOLUME_RATIO_NAME)
    if value is None:
        return PullbackGate(VOLUME_GATE, UNKNOWN, None, float(limit), missing, ids), None
    passed = value <= limit
    return (PullbackGate(VOLUME_GATE, PASS if passed else FAIL, float(value), float(limit),
                         None if passed else "PULLBACK_VOLUME_ABOVE_SUPPLIED_LIMIT", ids), value)


def _support(request: PullbackRequest) -> tuple[PullbackGate, Fraction | None]:
    """How far past the supplied VWAP the pullback extreme was allowed to sit.

    The measured distance is already expressed in the caller's own minute-ATR
    units and signed in the trade's direction, so a pullback that fell through
    the VWAP reads negative and must stay within the caller's own pad.
    """
    pad = _threshold(request.policy.max_support_atr_multiple, "max_support_atr_multiple")
    value, missing, ids = _reading(request, PULLBACK_FROM_VWAP_NAME)
    if value is None:
        return PullbackGate(SUPPORT_GATE, UNKNOWN, None, float(-pad), missing, ids), None
    passed = value >= -pad
    return (PullbackGate(SUPPORT_GATE, PASS if passed else FAIL, float(value), float(-pad),
                         None if passed else "PULLBACK_BEYOND_SUPPLIED_VWAP_PAD", ids), value)


def _trigger(request: PullbackRequest, last: Fraction | None, missing: str | None,
             last_ids: tuple[str, ...]) -> tuple[PullbackGate, Fraction | None]:
    """The supplied last trade against the reversal bar plus the caller's offset.

    The offset is the larger of the caller's own absolute minimum and its own
    multiple of the supplied minute ATR, exactly as PLAYBOOKS section 6 frames it;
    neither number is this module's.
    """
    policy = request.policy
    name = REVERSAL_HIGH_NAME if request.direction == "LONG" else REVERSAL_LOW_NAME
    extreme, unavailable, ids = _reading(request, name)
    if extreme is None:
        return PullbackGate(TRIGGER_GATE, UNKNOWN, reason=unavailable,
                            input_record_ids=ids), None
    if request.atr_1m is None:
        return PullbackGate(TRIGGER_GATE, UNKNOWN, reason="MISSING_ATR_1M",
                            input_record_ids=ids), None
    offset = max(_threshold(policy.min_trigger_offset, "min_trigger_offset", positive=True),
                 _threshold(policy.min_trigger_atr_multiple, "min_trigger_atr_multiple",
                            positive=True) * _threshold(request.atr_1m, "minute ATR",
                                                        positive=True))
    level = extreme + _sign(request.direction) * offset
    joined = tuple(sorted({*ids, *last_ids}))
    if last is None:
        status = FAIL if missing == "COVERAGE_LOST" else UNKNOWN
        return (PullbackGate(TRIGGER_GATE, status, None, float(level),
                             _missing_reason(missing), joined), level)
    passed = _sign(request.direction) * (last - level) >= 0
    return (PullbackGate(TRIGGER_GATE, PASS if passed else FAIL, float(last), float(level),
                         None if passed else "LAST_NOT_BEYOND_REVERSAL_BAR", joined), level)


def _spread(request: PullbackRequest) -> tuple[PullbackGate, Fraction | None]:
    """The supplied quote decision's own two-sided spread at this instant."""
    policy, decision = request.policy, request.quote
    limit = _threshold(policy.max_spread_bps, "max_spread_bps", positive=True)
    if decision is None or decision.quote is None:
        reason = "QUOTE_DECISION_ABSENT" if decision is None else "QUOTE_RECORD_ABSENT"
        return PullbackGate(SPREAD_GATE, UNKNOWN, None, float(limit), reason), None
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
        return PullbackGate(SPREAD_GATE, UNKNOWN, None, float(limit), reason, ids), None
    bid, ask = _price(quote.bid), _price(quote.ask)
    spread = 10000 * (ask - bid) / ((ask + bid) / 2)
    passed = spread <= limit
    return (PullbackGate(SPREAD_GATE, PASS if passed else FAIL, float(spread), float(limit),
                         None if passed else "SPREAD_ABOVE_SUPPLIED_LIMIT", ids), spread)


def _sequence(request: PullbackRequest) -> PullbackGate:
    """Which pullback of the session this is, under the caller's own counting.

    PLAYBOOKS section 6 keeps the first pullback at normal priority, the second
    lower and suppresses the third by default. Which completed pullback is the
    first stays with the unresolved definition, so only the caller's own supplied
    ordinal and maximum are used here.
    """
    limit = _count(request.policy.max_pullback_ordinal, "max_pullback_ordinal", minimum=1)
    if request.pullback_ordinal is None:
        return PullbackGate(SEQUENCE_GATE, UNKNOWN, None, float(limit),
                            "PULLBACK_ORDINAL_UNAVAILABLE")
    ordinal = _count(request.pullback_ordinal, "pullback ordinal", minimum=1)
    passed = ordinal <= limit
    return PullbackGate(SEQUENCE_GATE, PASS if passed else FAIL, float(ordinal), float(limit),
                        None if passed else "PULLBACK_ORDINAL_BEYOND_SUPPLIED_MAXIMUM")


def _structural(request: PullbackRequest, measurement: PullbackGate) -> PullbackGate:
    """The supplied stop and targets, re-checked against this measured pullback.

    The identity checks come first: a reading framed on another direction, impulse
    window or instant is not this continuation's geometry. Only then are the
    supplied prices compared with the measured reversal bar the entry must stand
    beyond and the measured pullback extreme the stop must sit past. How far past
    it stays the caller's own undefined pad.
    """
    supplied = request.structural
    at, sign = request.evaluated_at, _sign(request.direction)
    if supplied is None:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_UNAVAILABLE")
    if supplied.direction != request.direction:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_DIRECTION_MISMATCH")
    if supplied.impulse_frozen_at != request.impulse_frozen_at:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_IMPULSE_WINDOW_MISMATCH")
    if supplied.evaluated_at != at:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_NOT_CURRENT")
    if supplied.available_at > at:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_NOT_YET_AVAILABLE")
    if supplied.risk is None:  # a missing measurement always names its own reason
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_" + supplied.missing_reason)
    if not supplied.targets:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_TARGETS_UNAVAILABLE")
    if measurement.status != PASS:
        return PullbackGate(RISK_GATE, UNKNOWN, reason="GEOMETRY_MEASUREMENT_UNAVAILABLE")
    name = REVERSAL_HIGH_NAME if request.direction == "LONG" else REVERSAL_LOW_NAME
    reversal, reversal_missing, _reversal_ids = _reading(request, name)
    extreme, extreme_missing, _extreme_ids = _reading(request, PULLBACK_EXTREME_NAME)
    if reversal is None or extreme is None:
        return PullbackGate(RISK_GATE, UNKNOWN,
                            reason="GEOMETRY_" + str(reversal_missing or extreme_missing))
    entry = _price(supplied.risk.entry_reference)
    stop = _price(supplied.risk.hard_stop)
    risk_per_share = _price(supplied.risk.risk_per_share)
    if sign * (entry - reversal) <= 0:
        return PullbackGate(RISK_GATE, FAIL, reason="ENTRY_NOT_BEYOND_REVERSAL_BAR")
    if sign * (entry - stop) <= 0:
        return PullbackGate(RISK_GATE, FAIL, reason="STOP_ON_THE_WRONG_SIDE")
    if sign * (stop - extreme) >= 0:
        return PullbackGate(RISK_GATE, FAIL, reason="STOP_NOT_BEYOND_PULLBACK_EXTREME")
    for row in supplied.targets:
        reward = sign * (_price(row.price) - entry)
        if reward <= 0:
            return PullbackGate(RISK_GATE, FAIL, reason="TARGET_NOT_BEYOND_ENTRY")
        # A stated reward larger than the supplied prices show is a refusal, not a
        # rounding difference.
        if _price(row.r_multiple) > reward / risk_per_share:
            return PullbackGate(RISK_GATE, FAIL, reason="TARGET_R_MULTIPLE_OVERSTATED")
    first = _price(supplied.targets[0].r_multiple)
    minimum = _threshold(request.policy.min_first_target_r_multiple,
                         "min_first_target_r_multiple", positive=True)
    if first < minimum:
        return PullbackGate(RISK_GATE, FAIL, float(first), float(minimum),
                            "FIRST_TARGET_BELOW_SUPPLIED_MINIMUM", supplied.record_ids)
    return PullbackGate(RISK_GATE, PASS, float(first), float(minimum),
                        input_record_ids=supplied.record_ids)


def _confidence(request: PullbackRequest) -> PullbackGate:
    """The supplied M4.4 composition for this strategy, direction and instant."""
    supplied = request.confidence
    if supplied is None:
        return PullbackGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_UNAVAILABLE")
    composition = supplied.request
    context, policy = composition.context, composition.policy
    if policy.strategy_id != STRATEGY_ID:
        return PullbackGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_STRATEGY_MISMATCH")
    if policy.strategy_version != request.strategy_version:
        return PullbackGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_VERSION_MISMATCH")
    if context.direction != request.direction:
        return PullbackGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_DIRECTION_MISMATCH")
    if context.evaluated_at != request.evaluated_at:
        return PullbackGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_NOT_CURRENT")
    if supplied.status != "READY" or supplied.confidence is None:
        reason = supplied.reasons[0] if supplied.reasons else supplied.status
        return PullbackGate(CONFIDENCE_GATE, UNKNOWN, reason="CONFIDENCE_" + reason)
    references = tuple(sorted({row.record_id for row in context.features}))
    return PullbackGate(CONFIDENCE_GATE, PASS, input_record_ids=references)


def evaluate_first_pullback_vwap(request: PullbackRequest) -> PullbackAssessment:
    """Report every supplied pullback gate and the state they support, with no side effect.

    ALERT_TRIGGERED describes the supplied inputs at this instant only. It opens no
    position, sends nothing, approves no referenced definition and proves no
    provider coverage. No confidence cutoff is applied: the floor stays with the
    unresolved definition and is named in `unavailable` instead.
    """
    if not isinstance(request, PullbackRequest):
        raise RecordError("PullbackRequest is required")
    last, missing, last_ids = _last_price(request)
    measurement = _measurement(request)
    impulse, impulse_atr = _impulse(request)
    impulse_vwap, from_vwap = _minimum(
        request, IMPULSE_VWAP_GATE, IMPULSE_FROM_VWAP_NAME,
        _threshold(request.policy.min_impulse_vwap_atr_multiple,
                   "min_impulse_vwap_atr_multiple", positive=True),
        "IMPULSE_TOO_CLOSE_TO_VWAP")
    side = _vwap_side(request, last, missing, last_ids)
    slope = _vwap_slope(request)
    crosses = _vwap_crosses(request)
    strength = _relative_strength(request)
    retracement, retraced = _retracement(request)
    volume, ratio = _volume_ratio(request)
    support, support_atr = _support(request)
    trigger, level = _trigger(request, last, missing, last_ids)
    spread, spread_bps = _spread(request)
    sequence = _sequence(request)
    structural = _structural(request, measurement)
    confidence = _confidence(request)
    gates = (measurement, impulse, impulse_vwap, side, slope, crosses, strength, retracement,
             volume, support, trigger, spread, sequence, structural, confidence)
    if any(row.reason in INVALIDATIONS for row in gates):
        state = StrategyState("INVALIDATED")
    elif measurement.status != PASS:
        state = StrategyState("SETUP_FORMING", PULLBACK_FORMING)
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
    return PullbackAssessment(
        request.evaluated_at, state, request.direction, gates, reasons,
        request.impulse_started_at, request.impulse_frozen_at,
        measurement_record_id=request.measurement.record_id,
        impulse_distance_atr=None if impulse_atr is None else float(impulse_atr),
        impulse_from_vwap_atr=None if from_vwap is None else float(from_vwap),
        retracement=None if retraced is None else float(retraced),
        volume_ratio=None if ratio is None else float(ratio),
        support_from_vwap_atr=None if support_atr is None else float(support_atr),
        trigger_price=None if level is None else float(level),
        last_price=None if last is None else float(last),
        spread_bps=None if spread_bps is None else float(spread_bps),
        pullback_ordinal=request.pullback_ordinal,
        policy_version=request.policy.version,
        definition_reference=request.definition_reference,
        strategy_version=request.strategy_version, **values)


class FirstPullbackVwapMachine:
    """One serially owned `(session, symbol, direction)` continuation owner.

    The machine proposes canonical transitions for the M4.2 engine; it never
    writes, sends or advances itself. Local state moves only when the caller
    confirms a proposed transition after storage acknowledged it. The impulse
    window is held here, so the frozen leg a recorded continuation stood on cannot
    be walked and a second impulse cannot take over the same owner silently.
    """

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 strategy_version: str, policy: PullbackVwapPolicy):
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        if not isinstance(policy, PullbackVwapPolicy):
            raise RecordError("policy must be PullbackVwapPolicy")
        if instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("underlying must be EQUITY or ETF")
        if STRATEGY_ID not in STRATEGY_IDS:  # keeps the shared ID list authoritative
            raise RecordError("strategy ID is not supported")
        self._session = session
        self._symbol = _label(symbol, "symbol")
        self._instrument_type = instrument_type
        self._version = _label(strategy_version, "strategy version")
        self._policy = policy
        self._rules = pullback_rules()
        self._state = self._rules.initial_state
        self._window: tuple[datetime, datetime] | None = None
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
        return self._policy.direction

    @property
    def rules(self) -> TransitionRules:
        return self._rules

    @property
    def last_action_at(self) -> datetime | None:
        """When this owner last recorded an actionable continuation, if it did."""
        return self._actioned_at

    def current_state(self) -> StrategyState:
        return self._state

    def current_window(self) -> tuple[datetime, datetime] | None:
        return self._window

    def _metadata(self, at: datetime) -> SourceMetadata:
        return SourceMetadata(
            instrument_id=self._symbol, instrument_type=self._instrument_type,
            source="DERIVED_M84", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID")

    def _transition(self, *, record_id: str, at: datetime, state: StrategyState, reason: str,
                    previous: StrategyState, input_record_ids: tuple[str, ...] = (),
                    ) -> StrategyStateTransition:
        _label(record_id, "transition record ID")
        if (previous, state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M8.4 rules")
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

    def propose(self, request: PullbackRequest, *, record_id: str,
                staged_record_id: str | None = None,
                ) -> tuple[PullbackAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transitions a caller must store first.

        A first evaluation that already passes every gate needs both the ARMED
        step and the ALERT_TRIGGERED step, so the recorded history always shows the
        formed pullback before the action. That second step needs its own
        `staged_record_id`; nothing is invented here.
        """
        if not isinstance(request, PullbackRequest):
            raise RecordError("PullbackRequest is required")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if self._window is not None and request.window != self._window:
            raise RecordError("a different impulse cannot replace the one already taken over")
        assessment = evaluate_first_pullback_vwap(request)
        self._forward(request.evaluated_at)
        target = assessment.state
        if target == self._state:
            self._pending, self._effect = (), None
            return assessment, ()
        if self._state.state == "ALERT_TRIGGERED" and target.state in ("ARMED", "SETUP_FORMING"):
            raise RecordError("an actionable continuation cannot fall back to an earlier state")
        if self._state.state == "ARMED" and target.state == "SETUP_FORMING":
            # Ownership already recorded cannot silently vanish when a supplied
            # input stops supporting it; it is closed explicitly instead.
            target = StrategyState("INVALIDATED")
        if self._state.state == "INVALIDATED":
            raise RecordError("a closed continuation cannot be reopened inside one owner")
        reason = (assessment.reasons[0] if assessment.reasons
                  else "ALL_SUPPLIED_PULLBACK_GATES_PASSED")
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
                                         state=armed, reason="PULLBACK_FORMED_ARMED",
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
            self._effect = ("TAKE", request.window)
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
            self._window = payload
        elif kind == "ACTION":
            self._actioned_at = payload
        elif kind == "CLOSE":
            self._window = None
        self._pending, self._effect = (), None
        return self._state

    def restore(self, state: StrategyState, *,
                window: tuple[datetime, datetime] | None = None,
                last_action_at: datetime | None = None) -> StrategyState:
        """Position an unused owner at facts recovered from storage (M5.5).

        Every fact is restored explicitly. Nothing is inferred from the state
        alone, so a recovered owner cannot silently regain an action it already
        reported or lose one it did.
        """
        if self._pending or self._time is not None or self._window is not None:
            raise RecordError("restore requires an unused pullback owner")
        if not isinstance(state, StrategyState) or state.state not in STATES:
            raise RecordError("restored state is not an M8.4 state")
        if state.substate not in (None, *SUBSTATES):
            raise RecordError("restored substate is not an M8.4 substate")
        if state == StrategyState("SETUP_FORMING"):
            raise RecordError("a restored SETUP_FORMING owner keeps its M8.4 substate")
        if window is not None:
            if not isinstance(window, tuple) or len(window) != 2:
                raise RecordError("a restored impulse window is a start and a freeze instant")
            window = tuple(_instant(item, "restored impulse instant") for item in window)
            if window[0] >= window[1]:
                raise RecordError("the restored impulse window must start before it freezes")
        self._window = window
        self._actioned_at = (None if last_action_at is None
                             else _instant(last_action_at, "last_action_at"))
        self._state = state
        return self._state


__all__ = [
    "CONFIDENCE_GATE", "DATA_MODE", "FirstPullbackVwapMachine", "IMPULSE_GATE",
    "IMPULSE_VWAP_GATE", "INVALIDATIONS", "MEASUREMENT_GATE", "PULLBACK_FORMING",
    "PULLBACK_GATES", "PULLBACK_VERSION", "PullbackAssessment", "PullbackGate",
    "PullbackRequest", "PullbackStructural", "PullbackVwapPolicy", "RS_GATE",
    "RETRACEMENT_GATE", "RISK_GATE", "RULES_VERSION", "RelativeStrength", "SEQUENCE_GATE",
    "SPREAD_GATE", "STATES", "STRATEGY_ID", "SUBSTATES", "SUPPORT_GATE", "TRIGGER_GATE",
    "UNDEFINED", "VOLUME_GATE", "VWAP_CROSS_GATE", "VWAP_SIDE_GATE", "VWAP_SLOPE_GATE",
    "VwapContext", "evaluate_first_pullback_vwap", "pullback_rules",
]
