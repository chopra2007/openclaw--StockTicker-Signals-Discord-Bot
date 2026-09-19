"""M6.1 offline `CRVOL_ORB5` eligibility path through ARMED over supplied inputs.

The caller supplies every threshold, feature binding, mandatory status fact and
preliminary geometry result. This module adopts no number of its own: the exact
ARMED thresholds and eligibility rules still belong to `M03B_ORB5_V1`, which is
PROPOSED, so a policy must name its own definition reference. Nothing here reads
a clock, fetches data, scores a setup, stores a record or delivers an alert.

ARMED means the supplied gates passed at one evaluation instant. It is not a
trigger, an approved rule, proof of provider coverage or permission to act. A
missing, stale, ambiguous or unknown mandatory input keeps the machine below the
state it would otherwise reach; it never becomes a passing gate.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
import json

from .state_transitions import TransitionRules
from .strategy_interface import StrategyContext, StrategyState
from .structural_risk import RiskTargetResult
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import RecordError, SessionRecord, SourceMetadata, StrategyStateTransition
from .utils.time_context import as_utc, session_bounds, session_date_at


ELIGIBILITY_VERSION = "M61_ORB5_ELIGIBILITY_V1"
RULES_VERSION = "M61_ORB5_ELIGIBILITY_RULES_V1"
STRATEGY_ID = "CRVOL_ORB5"
DATA_MODE = "SUPPLIED_ELIGIBILITY_INPUTS"

TRUE, FALSE, UNKNOWN = "TRUE", "FALSE", "UNKNOWN"
PASS, FAIL = "PASS", "FAIL"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

REQUIRED_ROLES = (
    "MEDIAN_DOLLAR_VOLUME", "OPEN5_RVOL", "PM_RVOL", "GAP", "DAILY_ATR",
    "SESSION_VWAP", "OPENING_RANGE_WIDTH", "OPENING_RANGE_COMPLETE",
)
WINDOW_GATE = "EVALUATION_WINDOW"
SETUP_GATES = (
    "OPENING_RANGE_READY", "MIN_PRICE", "MEDIAN_DOLLAR_VOLUME", "OPEN5_RVOL",
    "OR_WIDTH_ATR_RATIO", "STOCK_IN_PLAY",
)
ARMED_GATES = SETUP_GATES + (
    "VWAP_SIDE", "QUOTE_ACTIONABLE", "SPREAD_BPS", "MANDATORY_STATUS",
    "PRELIMINARY_RISK_TARGETS",
)
STATES = ("NOT_ELIGIBLE", "WATCHING", "SETUP_FORMING", "ARMED", "EXPIRED")


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


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


@dataclass(frozen=True)
class FeatureBinding:
    """One named role bound to an exact supplied feature definition.

    Role, name, producing version, data mode and unit must all match, so a
    feature cannot be selected by name alone or served by another definition.
    """

    role: str
    feature_name: str
    feature_version: str
    data_mode: str
    unit: str

    def __post_init__(self) -> None:
        if self.role not in REQUIRED_ROLES:
            raise RecordError("feature role is not supported")
        for name in ("feature_name", "feature_version", "data_mode", "unit"):
            _label(getattr(self, name), name)


@dataclass(frozen=True)
class EligibilityPolicy:
    """Explicitly supplied thresholds, windows and bindings; nothing defaulted.

    Values describe the caller's own definition. Supplying them neither adopts a
    proposed rule nor proves the referenced definition has been approved.
    """

    version: str
    definition_reference: str
    window_start_minutes: int
    window_end_minutes: int
    min_price: float
    min_median_dollar_volume: float
    min_open5_rvol: float
    min_or_width_atr_ratio: float
    max_or_width_atr_ratio: float
    stock_in_play_min_pm_rvol: float
    stock_in_play_min_abs_gap: float
    stock_in_play_min_open5_rvol: float
    max_spread_bps: float
    max_quote_age_seconds: float
    max_trade_age_seconds: float
    max_feature_age_seconds: float
    catalyst_classifications: tuple[str, ...]
    bindings: tuple[FeatureBinding, ...]

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        for name in ("window_start_minutes", "window_end_minutes"):
            if type(getattr(self, name)) is not int:
                raise RecordError(f"{name} must be an integer")
        if not 0 <= self.window_start_minutes < self.window_end_minutes:
            raise RecordError("the evaluation window must be a positive half-open range")
        for name in ("min_price", "min_median_dollar_volume", "min_open5_rvol",
                     "stock_in_play_min_pm_rvol", "stock_in_play_min_abs_gap",
                     "stock_in_play_min_open5_rvol", "max_spread_bps"):
            _threshold(getattr(self, name), name)
        for name in ("max_quote_age_seconds", "max_trade_age_seconds", "max_feature_age_seconds"):
            _threshold(getattr(self, name), name)
        low = _threshold(self.min_or_width_atr_ratio, "min_or_width_atr_ratio")
        high = _threshold(self.max_or_width_atr_ratio, "max_or_width_atr_ratio")
        if low > high:
            raise RecordError("the OR width band cannot start above its own maximum")
        if not isinstance(self.catalyst_classifications, tuple) or not self.catalyst_classifications:
            raise RecordError("confirmed catalyst classifications must be supplied")
        for value in self.catalyst_classifications:
            _label(value, "catalyst classification")
        if len(set(self.catalyst_classifications)) != len(self.catalyst_classifications):
            raise RecordError("catalyst classifications must be unique")
        if not isinstance(self.bindings, tuple) or any(
            not isinstance(row, FeatureBinding) for row in self.bindings
        ):
            raise RecordError("bindings must be a tuple of FeatureBinding")
        roles = [row.role for row in self.bindings]
        if sorted(roles) != sorted(REQUIRED_ROLES):
            raise RecordError("every required feature role must be bound exactly once")

    def binding(self, role: str) -> FeatureBinding:
        return next(row for row in self.bindings if row.role == role)


@dataclass(frozen=True)
class MandatoryStatus:
    """Supplied halt, macro-blackout and catalyst-coverage facts at one instant.

    None means unknown, never false. The macro-blackout interval and the news
    classifier remain M0.3B work; this record carries the caller's supplied
    answer and its evidence reference, and defines neither.
    """

    halted: bool | None
    macro_blackout_active: bool | None
    catalyst_coverage: str
    definition_reference: str
    evidence_reference: str
    available_at: datetime

    def __post_init__(self) -> None:
        for name in ("halted", "macro_blackout_active"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise RecordError(f"{name} must be true, false or null")
        if self.catalyst_coverage not in ("COMPLETE", "UNKNOWN"):
            raise RecordError("catalyst coverage must be COMPLETE or UNKNOWN")
        for name in ("definition_reference", "evidence_reference"):
            _label(getattr(self, name), name)
        object.__setattr__(self, "available_at", _instant(self.available_at, "available_at"))


@dataclass(frozen=True)
class EligibilityRequest:
    """One evaluation: supplied context, policy, status and preliminary geometry."""

    context: StrategyContext
    policy: EligibilityPolicy
    status: MandatoryStatus
    preliminary: RiskTargetResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.context, StrategyContext):
            raise RecordError("context must be StrategyContext")
        if not isinstance(self.policy, EligibilityPolicy):
            raise RecordError("policy must be EligibilityPolicy")
        if not isinstance(self.status, MandatoryStatus):
            raise RecordError("mandatory status must be supplied")
        if self.preliminary is not None and not isinstance(self.preliminary, RiskTargetResult):
            raise RecordError("preliminary geometry must be RiskTargetResult or null")


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    observed: float | None = None
    threshold: float | None = None
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name != WINDOW_GATE and self.name not in ARMED_GATES:
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
class EligibilityAssessment:
    """Immutable result of one evaluation; the caller owns storage and delivery."""

    evaluated_at: datetime
    state: StrategyState
    gates: tuple[GateResult, ...]
    stock_in_play: str
    reasons: tuple[str, ...]
    input_record_ids: tuple[str, ...]
    policy_version: str
    definition_reference: str

    def gate(self, name: str) -> GateResult:
        return next(row for row in self.gates if row.name == name)

    def as_dict(self) -> dict[str, object]:
        return {
            "eligibility_version": ELIGIBILITY_VERSION,
            "evaluated_at": self.evaluated_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.state, "substate": self.state.substate,
            "gates": [row.as_dict() for row in self.gates],
            "stock_in_play": self.stock_in_play, "reasons": list(self.reasons),
            "input_record_ids": list(self.input_record_ids),
            "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def eligibility_rules() -> TransitionRules:
    """Exactly the M6.1 states; ALERT_TRIGGERED and reset belong to M6.2."""
    states = tuple(StrategyState(name) for name in STATES[:4])
    expired = StrategyState("EXPIRED")
    allowed = tuple((old, new) for old in states for new in states if old != new)
    return TransitionRules(RULES_VERSION, StrategyState("NOT_ELIGIBLE"),
                           allowed + tuple((old, expired) for old in states))


def _resolve(request: EligibilityRequest, role: str) -> tuple[Fraction | None, str | None, tuple[str, ...]]:
    """Select one supplied feature value by full identity, or explain its absence."""
    binding, context = request.policy.binding(role), request.context
    at, limit = context.evaluated_at, _threshold(
        request.policy.max_feature_age_seconds, "max_feature_age_seconds")
    matching = [
        row for row in context.features
        if row.feature_version == binding.feature_version
        and row.metadata.data_mode == binding.data_mode
        and row.metadata.instrument_id == context.symbol
        and row.metadata.instrument_type == context.instrument_type
        and any(item.name == binding.feature_name for item in row.features)
    ]
    if not matching:
        return None, "FEATURE_ABSENT", ()
    newest = max(row.evaluated_at for row in matching)
    latest = [row for row in matching if row.evaluated_at == newest]
    ids = tuple(sorted(row.record_id for row in latest))
    if len(latest) > 1:
        return None, "AMBIGUOUS_FEATURE_INPUT", ids
    snapshot = latest[0]
    metadata = snapshot.metadata
    age = Fraction(str((at - snapshot.evaluated_at).total_seconds()))
    if age > limit:
        return None, "STALE_FEATURE", ids
    if metadata.available_time > at or snapshot.evaluated_at > at:
        return None, "NOT_YET_AVAILABLE", ids
    if metadata.source_time is None or metadata.source_time > metadata.available_time:
        return None, "INVALID_SOURCE_TIME", ids
    if metadata.quality != "VALID" or metadata.session != context.session.session:
        return None, "FEATURE_QUALITY_UNAVAILABLE", ids
    item = next(row for row in snapshot.features if row.name == binding.feature_name)
    if item.unit != binding.unit:
        return None, "WRONG_UNIT", ids
    if item.value is None:
        return None, item.missing_reason or "VALUE_UNAVAILABLE", ids
    return Fraction(str(item.value)), None, ids


def _latest_trade(request: EligibilityRequest) -> tuple[Fraction | None, str | None, tuple[str, ...]]:
    """The latest valid regular-session trade this evaluation may use."""
    decision, policy = request.context.quote, request.policy
    if decision is None:
        return None, "QUOTE_DECISION_ABSENT", ()
    if decision.quote is None:
        return None, "QUOTE_RECORD_ABSENT", ()
    quote = decision.quote
    ids = (quote.record_id,)
    if quote.status != "VALID" or quote.delayed is not False:
        return None, "QUOTE_NOT_VALID_REALTIME", ids
    if quote.last is None or quote.trade_time is None:
        return None, "LAST_TRADE_UNAVAILABLE", ids
    if decision.trade_age_seconds is None:
        return None, "TRADE_AGE_UNKNOWN", ids
    if Fraction(str(decision.trade_age_seconds)) > _threshold(
            policy.max_trade_age_seconds, "max_trade_age_seconds"):
        return None, "STALE_LAST_TRADE", ids
    price = Fraction(str(quote.last))
    if price <= 0:
        return None, "NONPOSITIVE_LAST_TRADE", ids
    return price, None, ids


def _minimum(name: str, value: Fraction | None, reason: str | None, limit: Fraction,
             ids: tuple[str, ...], *, below: str) -> GateResult:
    if value is None:
        return GateResult(name, UNKNOWN, None, float(limit), reason, ids)
    status, code = (PASS, None) if value >= limit else (FAIL, below)
    return GateResult(name, status, float(value), float(limit), code, ids)


def _branch(value: Fraction | None, limit: Fraction) -> str:
    return UNKNOWN if value is None else (TRUE if value >= limit else FALSE)


def _and(first: str, second: str) -> str:
    if FALSE in (first, second):
        return FALSE
    return UNKNOWN if UNKNOWN in (first, second) else TRUE


def _catalyst_branch(request: EligibilityRequest) -> tuple[str, tuple[str, ...]]:
    policy, context = request.policy, request.context
    confirmed = tuple(
        row for row in context.catalysts
        if row.classification in policy.catalyst_classifications
        and row.classified_at is not None and row.classified_at <= context.evaluated_at
        and row.metadata.quality == "VALID"
    )
    if confirmed:
        return TRUE, tuple(sorted(row.record_id for row in confirmed))
    ids = tuple(sorted(row.record_id for row in context.catalysts))
    if request.status.catalyst_coverage != "COMPLETE":
        return UNKNOWN, ids
    if any(row.classified_at is None or row.classification.strip().upper() == UNKNOWN
           for row in context.catalysts):
        return UNKNOWN, ids
    return FALSE, ids


def _window(request: EligibilityRequest) -> GateResult:
    policy, at = request.policy, request.context.evaluated_at
    bounds = session_bounds(session_date_at(at))
    if bounds is None:
        return GateResult(WINDOW_GATE, UNKNOWN, reason="NO_REGULAR_SESSION")
    opened = as_utc(bounds[0])
    start = opened + timedelta(minutes=policy.window_start_minutes)
    end = opened + timedelta(minutes=policy.window_end_minutes)
    if at < start:
        return GateResult(WINDOW_GATE, FAIL, reason="BEFORE_EVALUATION_WINDOW")
    if at >= end:
        return GateResult(WINDOW_GATE, FAIL, reason="AFTER_EVALUATION_WINDOW")
    return GateResult(WINDOW_GATE, PASS)


def _quote_gates(request: EligibilityRequest) -> tuple[GateResult, GateResult]:
    decision, policy = request.context.quote, request.policy
    limit = _threshold(policy.max_spread_bps, "max_spread_bps")
    if decision is None or decision.quote is None:
        reason = "QUOTE_DECISION_ABSENT" if decision is None else "QUOTE_RECORD_ABSENT"
        return (GateResult("QUOTE_ACTIONABLE", UNKNOWN, reason=reason),
                GateResult("SPREAD_BPS", UNKNOWN, threshold=float(limit), reason=reason))
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
    elif Fraction(str(decision.quote_age_seconds)) > _threshold(
            policy.max_quote_age_seconds, "max_quote_age_seconds"):
        reason = "STALE_QUOTE"
    if reason is not None:
        return (GateResult("QUOTE_ACTIONABLE", UNKNOWN, reason=reason, input_record_ids=ids),
                GateResult("SPREAD_BPS", UNKNOWN, threshold=float(limit), reason=reason,
                           input_record_ids=ids))
    bid, ask = Fraction(str(quote.bid)), Fraction(str(quote.ask))
    spread = 10000 * (ask - bid) / ((ask + bid) / 2)
    status, code = (PASS, None) if spread <= limit else (FAIL, "SPREAD_ABOVE_LIMIT")
    return (GateResult("QUOTE_ACTIONABLE", PASS, input_record_ids=ids),
            GateResult("SPREAD_BPS", status, float(spread), float(limit), code, ids))


def _status_gate(request: EligibilityRequest) -> GateResult:
    status, at = request.status, request.context.evaluated_at
    if status.available_at > at:
        return GateResult("MANDATORY_STATUS", UNKNOWN, reason="STATUS_NOT_YET_AVAILABLE")
    if status.halted is None:
        return GateResult("MANDATORY_STATUS", UNKNOWN, reason="HALT_STATUS_UNKNOWN")
    if status.halted:
        return GateResult("MANDATORY_STATUS", FAIL, reason="HALTED")
    if status.macro_blackout_active is None:
        return GateResult("MANDATORY_STATUS", UNKNOWN, reason="MACRO_BLACKOUT_UNKNOWN")
    if status.macro_blackout_active:
        return GateResult("MANDATORY_STATUS", FAIL, reason="MACRO_BLACKOUT_ACTIVE")
    return GateResult("MANDATORY_STATUS", PASS)


def _preliminary_gate(request: EligibilityRequest) -> GateResult:
    name, result = "PRELIMINARY_RISK_TARGETS", request.preliminary
    if result is None:
        return GateResult(name, UNKNOWN, reason="PRELIMINARY_GEOMETRY_UNAVAILABLE")
    supplied = result.request
    if supplied.direction != request.context.direction:
        return GateResult(name, UNKNOWN, reason="PRELIMINARY_DIRECTION_MISMATCH")
    if supplied.evaluated_at != request.context.evaluated_at:
        return GateResult(name, UNKNOWN, reason="PRELIMINARY_NOT_CURRENT")
    if result.status == "READY":
        return GateResult(name, PASS)
    reason = "PRELIMINARY_" + (result.reasons[0] if result.reasons else result.status)
    return GateResult(name, FAIL if result.status == "REJECTED" else UNKNOWN, reason=reason)


def evaluate_orb5_eligibility(request: EligibilityRequest) -> EligibilityAssessment:
    """Report every supplied gate and the state they support, with no side effect.

    Returning ARMED describes the supplied inputs at this instant only. It does
    not trigger, approve the referenced definition, prove source coverage or
    authorize delivery.
    """
    if not isinstance(request, EligibilityRequest):
        raise RecordError("EligibilityRequest is required")
    policy, context = request.policy, request.context
    window = _window(request)

    price, price_reason, price_ids = _latest_trade(request)
    dollar, dollar_reason, dollar_ids = _resolve(request, "MEDIAN_DOLLAR_VOLUME")
    open5, open5_reason, open5_ids = _resolve(request, "OPEN5_RVOL")
    pm_rvol, pm_reason, pm_ids = _resolve(request, "PM_RVOL")
    gap, gap_reason, gap_ids = _resolve(request, "GAP")
    atr, atr_reason, atr_ids = _resolve(request, "DAILY_ATR")
    vwap, vwap_reason, vwap_ids = _resolve(request, "SESSION_VWAP")
    width, width_reason, width_ids = _resolve(request, "OPENING_RANGE_WIDTH")
    complete, complete_reason, complete_ids = _resolve(request, "OPENING_RANGE_COMPLETE")

    if complete is None:
        ready = GateResult("OPENING_RANGE_READY", UNKNOWN, reason=complete_reason,
                           input_record_ids=complete_ids)
    elif complete == 1:
        ready = GateResult("OPENING_RANGE_READY", PASS, 1.0, 1.0, None, complete_ids)
    elif complete == 0:
        ready = GateResult("OPENING_RANGE_READY", FAIL, 0.0, 1.0, "OPENING_RANGE_INCOMPLETE",
                           complete_ids)
    else:
        ready = GateResult("OPENING_RANGE_READY", UNKNOWN, float(complete), 1.0,
                           "OPENING_RANGE_FLAG_NOT_BOOLEAN", complete_ids)

    ratio_ids = tuple(sorted(set(width_ids) | set(atr_ids)))
    low = _threshold(policy.min_or_width_atr_ratio, "min_or_width_atr_ratio")
    high = _threshold(policy.max_or_width_atr_ratio, "max_or_width_atr_ratio")
    if width is None or atr is None:
        ratio_gate = GateResult("OR_WIDTH_ATR_RATIO", UNKNOWN, None, float(high),
                                width_reason or atr_reason, ratio_ids)
    elif atr <= 0:
        ratio_gate = GateResult("OR_WIDTH_ATR_RATIO", UNKNOWN, None, float(high),
                                "ZERO_ATR_DENOMINATOR", ratio_ids)
    else:
        ratio = width / atr
        inside = low <= ratio <= high
        ratio_gate = GateResult("OR_WIDTH_ATR_RATIO", PASS if inside else FAIL, float(ratio),
                                float(high), None if inside else "OR_WIDTH_ATR_RATIO_OUTSIDE_BAND",
                                ratio_ids)

    catalyst, catalyst_ids = _catalyst_branch(request)
    premarket = _and(_branch(None if gap is None else abs(gap),
                             _threshold(policy.stock_in_play_min_abs_gap, "stock_in_play_min_abs_gap")),
                     _branch(pm_rvol, _threshold(policy.stock_in_play_min_pm_rvol,
                                                 "stock_in_play_min_pm_rvol")))
    participation = _branch(open5, _threshold(policy.stock_in_play_min_open5_rvol,
                                              "stock_in_play_min_open5_rvol"))
    branches = (catalyst, premarket, participation)
    in_play = TRUE if TRUE in branches else (UNKNOWN if UNKNOWN in branches else FALSE)
    in_play_ids = tuple(sorted(set(catalyst_ids) | set(pm_ids) | set(gap_ids) | set(open5_ids)))
    in_play_gate = GateResult(
        "STOCK_IN_PLAY", {TRUE: PASS, FALSE: FAIL, UNKNOWN: UNKNOWN}[in_play],
        None, None, None if in_play == TRUE else "STOCK_IN_PLAY_" + in_play, in_play_ids)

    vwap_ids_all = tuple(sorted(set(vwap_ids) | set(price_ids)))
    if price is None or vwap is None:
        vwap_gate = GateResult("VWAP_SIDE", UNKNOWN, None, None,
                               price_reason or vwap_reason, vwap_ids_all)
    else:
        sign = 1 if context.direction == "LONG" else -1
        beyond = sign * (price - vwap) > 0
        vwap_gate = GateResult("VWAP_SIDE", PASS if beyond else FAIL, float(price), float(vwap),
                               None if beyond else "PRICE_ON_WRONG_VWAP_SIDE", vwap_ids_all)

    actionable, spread_gate = _quote_gates(request)
    gates = (
        window, ready,
        _minimum("MIN_PRICE", price, price_reason,
                 _threshold(policy.min_price, "min_price"), price_ids, below="BELOW_MIN_PRICE"),
        _minimum("MEDIAN_DOLLAR_VOLUME", dollar, dollar_reason,
                 _threshold(policy.min_median_dollar_volume, "min_median_dollar_volume"),
                 dollar_ids, below="BELOW_MIN_DOLLAR_VOLUME"),
        _minimum("OPEN5_RVOL", open5, open5_reason,
                 _threshold(policy.min_open5_rvol, "min_open5_rvol"), open5_ids,
                 below="BELOW_MIN_OPEN5_RVOL"),
        ratio_gate, in_play_gate, vwap_gate, actionable, spread_gate,
        _status_gate(request), _preliminary_gate(request),
    )
    results = {row.name: row for row in gates}
    if window.status != PASS:
        state = "EXPIRED" if window.reason == "AFTER_EVALUATION_WINDOW" else "NOT_ELIGIBLE"
    elif all(results[name].status == PASS for name in ARMED_GATES):
        state = "ARMED"
    elif all(results[name].status == PASS for name in SETUP_GATES):
        state = "SETUP_FORMING"
    else:
        state = "WATCHING"
    reasons = tuple(f"{row.name}:{row.status}:{row.reason}" for row in gates if row.status != PASS)
    ids = tuple(sorted({value for row in gates for value in row.input_record_ids}))
    return EligibilityAssessment(context.evaluated_at, StrategyState(state), gates, in_play,
                                 reasons, ids, policy.version, policy.definition_reference)


class Orb5EligibilityMachine:
    """One serially owned (session, symbol, direction) eligibility state owner.

    The machine proposes canonical transitions for the M4.2 engine and the M5.1
    store; it never writes, sends or advances itself. Local state moves only when
    the caller confirms the proposed transition after storage acknowledged it.
    """

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, policy: EligibilityPolicy):
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        if not isinstance(policy, EligibilityPolicy):
            raise RecordError("policy must be EligibilityPolicy")
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
        self._rules = eligibility_rules()
        self._state = self._rules.initial_state
        self._time: datetime | None = None
        self._pending: StrategyStateTransition | None = None

    strategy_id = STRATEGY_ID

    @property
    def strategy_version(self) -> str:
        return self._version

    @property
    def rules(self) -> TransitionRules:
        return self._rules

    def current_state(self) -> StrategyState:
        return self._state

    def _check(self, request: EligibilityRequest) -> None:
        if not isinstance(request, EligibilityRequest):
            raise RecordError("EligibilityRequest is required")
        context = request.context
        if (context.session != self._session or context.symbol != self._symbol
                or context.instrument_type != self._instrument_type
                or context.direction != self._direction):
            raise RecordError("evaluation does not match this eligibility owner")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if self._time is not None and context.evaluated_at < self._time:
            raise RecordError("evaluation time cannot move backward")

    def evaluate(self, request: EligibilityRequest) -> EligibilityAssessment:
        self._check(request)
        assessment = evaluate_orb5_eligibility(request)
        self._time = request.context.evaluated_at
        return assessment

    def propose(self, request: EligibilityRequest, *, record_id: str,
                ) -> tuple[EligibilityAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transition a caller must store first."""
        _label(record_id, "transition record ID")
        assessment = self.evaluate(request)
        if assessment.state == self._state:
            self._pending = None
            return assessment, ()
        if (self._state, assessment.state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M6.1 rules")
        context = request.context
        at = context.evaluated_at
        snapshot = next(
            (row.record_id for row in context.features
             if row.record_id in assessment.gate("OPENING_RANGE_READY").input_record_ids), None)
        inputs = tuple(value for value in assessment.input_record_ids if value in {
            *(row.record_id for row in context.features),
            *(row.record_id for row in context.catalysts),
            *((context.quote.quote.record_id,)
              if context.quote is not None and context.quote.quote is not None else ()),
        })
        metadata = SourceMetadata(
            instrument_id=self._symbol, instrument_type=self._instrument_type,
            source="DERIVED_M61", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID",
        )
        transition = StrategyStateTransition(
            record_id=record_id, metadata=metadata, strategy_id=STRATEGY_ID,
            strategy_version=self._version, occurred_at=at,
            from_state=self._state.state, from_substate=self._state.substate,
            to_state=assessment.state.state, to_substate=assessment.state.substate,
            reason=(assessment.reasons[0] if assessment.reasons
                    else "ALL_SUPPLIED_ELIGIBILITY_GATES_PASSED"),
            feature_snapshot_id=snapshot, input_record_ids=inputs,
        )
        self._pending = transition
        return assessment, (transition,)

    def confirm(self, transition: StrategyStateTransition) -> StrategyState:
        """Advance only after the supplied transition was durably recorded."""
        if self._pending is None or transition != self._pending:
            raise RecordError("only the pending recorded transition can advance this owner")
        self._state = StrategyState(transition.to_state, transition.to_substate)
        self._pending = None
        return self._state

    def restore(self, state: StrategyState) -> StrategyState:
        """Position an unused owner at a state recovered from stored facts (M5.5)."""
        if self._pending is not None or self._time is not None:
            raise RecordError("restore requires an unused eligibility owner")
        if not isinstance(state, StrategyState) or state.state not in STATES:
            raise RecordError("restored state is not an M6.1 state")
        self._state = state
        return self._state


__all__ = [
    "ARMED_GATES", "DATA_MODE", "ELIGIBILITY_VERSION", "EligibilityAssessment",
    "EligibilityPolicy", "EligibilityRequest", "FeatureBinding", "GateResult",
    "MandatoryStatus", "Orb5EligibilityMachine", "REQUIRED_ROLES", "RULES_VERSION",
    "SETUP_GATES", "STATES", "STRATEGY_ID", "WINDOW_GATE", "eligibility_rules",
    "evaluate_orb5_eligibility",
]
