"""M7.2 offline RS and trend eligibility for `HOD_COMP_RS` over supplied inputs.

Two things live here. First, one relative-strength measurement: the stock return
and the benchmark return over the caller's own lookback of completed
regular-session minutes, and their difference. Second, the eligibility path
through ARMED, which reads that difference, the M7.1 frozen reference and
compression window, and the caller's supplied thresholds.

Nothing here adopts a number. The RS15 lookback, its warm-up answer, the return
basis, the trend thresholds and every eligibility cutoff stay unresolved under
PLAYBOOKS section 13 and M0.3, and `M03B_HOD_COMP_RS_V1` is not an approved
definition, so a policy must name its own definition reference. Supplying a
threshold neither approves a proposed rule nor proves a provider covers these
minutes.

The lookback never shortens itself. Before the supplied number of session
minutes has elapsed, the warm-up flag is false and the returns stay unavailable
with a named reason, because which shorter window would be acceptable is exactly
the open question. ARMED means the supplied gates passed at one evaluation
instant; it is not a trigger, an approved rule, proof of provider coverage or
permission to act.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
import json

from .historical_bars import HistoryBatch, HistoryCoverage
from .orb5_eligibility import MandatoryStatus  # halt/macro facts are strategy-neutral
from .state_transitions import TransitionRules
from .strategy_interface import StrategyContext, StrategyState
from .trade_alerts_config import STRATEGY_IDS
from .trade_alerts_models import (
    FeatureSnapshot,
    FeatureValue,
    RecordError,
    SessionRecord,
    SourceMetadata,
    StrategyStateTransition,
)
from .utils.time_context import as_utc, session_bounds, session_date_at


RS_FEATURE_VERSION = "M72_RS_TREND_V1"
RS_DATA_MODE = "SUPPLIED_BAR_RS_TREND"
ELIGIBILITY_VERSION = "M72_HOD_COMP_RS_ELIGIBILITY_V1"
RULES_VERSION = "M72_HOD_COMP_RS_ELIGIBILITY_RULES_V1"
DATA_MODE = "SUPPLIED_RS_TREND_ELIGIBILITY_INPUTS"
STRATEGY_ID = "HOD_COMP_RS"

_INSTRUMENT_TYPES = ("EQUITY", "ETF")
_UNKNOWN = ("", "UNKNOWN", "UNSPECIFIED")
_READY = ("FINAL", "NO_TRADE")

RETURN_BASES = ("FIRST_BAR_OPEN", "PRIOR_BAR_CLOSE")
STOCK_RETURN_NAME = "STOCK_RETURN_LOOKBACK_V1"
BENCHMARK_RETURN_NAME = "BENCHMARK_RETURN_LOOKBACK_V1"
RS_NAME = "RS_LOOKBACK_V1"
RS_BARS_NAME = "RS_LOOKBACK_BARS_V1"
RS_WARMUP_NAME = "RS_WARMUP_COMPLETE_V1"
RS_FEATURE_NAMES = (STOCK_RETURN_NAME, BENCHMARK_RETURN_NAME, RS_NAME, RS_BARS_NAME,
                    RS_WARMUP_NAME)

TRUE, FALSE, UNKNOWN = "TRUE", "FALSE", "UNKNOWN"
PASS, FAIL = "PASS", "FAIL"
GATE_STATUSES = (PASS, FAIL, UNKNOWN)

REQUIRED_ROLES = (
    "MEDIAN_DOLLAR_VOLUME", "RVOL", "OPEN_RETURN", "DAILY_ATR_PCT", "SESSION_VWAP",
    "RS", "RS_WARMUP_COMPLETE", "REFERENCE_EXTREME_COMPLETE", "COMPRESSION_COMPLETE",
)
WINDOW_GATE = "EVALUATION_WINDOW"
SETUP_GATES = (
    "REFERENCE_FROZEN", "COMPRESSION_MEASURED", "MIN_PRICE", "MEDIAN_DOLLAR_VOLUME",
    "RVOL", "OPEN_RETURN",
)
ARMED_GATES = SETUP_GATES + (
    "RS_WARMUP", "RS_TREND", "VWAP_SIDE", "QUOTE_ACTIONABLE", "SPREAD_BPS",
    "MANDATORY_STATUS",
)
STATES = ("NOT_ELIGIBLE", "WATCHING", "SETUP_FORMING", "ARMED", "EXPIRED")


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in _UNKNOWN):
        raise RecordError(f"{name} must be explicit")
    return value


def _threshold(value: object, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    try:
        number = Fraction(str(value))
    except (ValueError, ArithmeticError) as exc:  # non-finite text is not a threshold
        raise RecordError(f"{name} must be finite") from exc
    if number < 0:
        raise RecordError(f"{name} must be a supported threshold")
    return number


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


# --- one relative-strength measurement -------------------------------------


@dataclass(frozen=True)
class RsWindowPolicy:
    """The caller's own RS lookback; nothing here is defaulted.

    PLAYBOOKS section 13 still owns the RS15 lookback, its warm-up answer and
    which price starts the return, so the bar count, the benchmark and the return
    basis all arrive from the caller with its own definition reference.
    """

    version: str
    definition_reference: str
    benchmark_symbol: str
    lookback_bars: int
    return_basis: str

    def __post_init__(self) -> None:
        for name in ("version", "definition_reference", "benchmark_symbol"):
            _label(getattr(self, name), name)
        if type(self.lookback_bars) is not int or self.lookback_bars < 1:
            raise RecordError("lookback_bars must be a positive integer count")
        if self.return_basis not in RETURN_BASES:
            raise RecordError("return basis is not supported")

    @property
    def required_bars(self) -> int:
        """Completed session minutes this definition needs at one evaluation."""
        return self.lookback_bars + (1 if self.return_basis == "PRIOR_BAR_CLOSE" else 0)


def _value(name: str, value: Decimal | int | None, unit: str, reason: str | None,
           ids: tuple[str, ...]) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason, ids)


def _basis_reason(batch: HistoryBatch | None, symbol: str) -> str | None:
    if batch is None:
        return "MISSING_MINUTE_HISTORY"
    if batch.request.symbol != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if batch.request.interval != "1m":
        return "INCOMPATIBLE_HISTORY_INTERVAL"
    if batch.conventions.price != "USD_PER_SHARE":
        return "INCOMPATIBLE_PRICE_UNIT"
    if batch.conventions.volume != "SHARES":
        return "INCOMPATIBLE_VOLUME_UNIT"
    if any(value.strip().upper() in _UNKNOWN for value in (
            batch.source, batch.conventions.adjustment_basis, batch.conventions.coverage_basis)):
        return "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    return None


def _unexpected_over(batch: HistoryBatch, coverage: HistoryCoverage, items) -> bool:
    """Only malformed records overlapping the selected slots block them."""
    unexpected = set(coverage.unexpected_record_ids)
    return any(bar.record_id in unexpected
               and any(bar.start_time < item.interval.end and bar.end_time > item.interval.start
                       for item in items)
               for bar in batch.bars)


def _ids(items) -> tuple[str, ...]:
    return tuple(sorted({item.bar.record_id for item in items if item.bar is not None}))


def _contiguous(items) -> bool:
    return all(later.interval.start == earlier.interval.end
               for earlier, later in zip(items, items[1:]))


def _lookback_return(batch: HistoryBatch, coverage: HistoryCoverage, moment: datetime,
                     opened: datetime, closed: datetime, day: str,
                     policy: RsWindowPolicy, instrument_type: str | None):
    """The return over the last completed minutes this lookback asks for."""
    ended = [item for item in coverage.intervals
             if item.interval.session == day and item.interval.start >= opened
             and item.interval.end <= min(moment, closed)]
    selected = ended[-policy.required_bars:]
    ids = _ids(selected)
    if len(selected) != policy.required_bars or not _contiguous(selected):
        return None, "INCOMPLETE_RS_WINDOW", ids
    blocking = [item.status for item in selected if item.status not in _READY]
    if blocking:
        return None, "RS_WINDOW_" + blocking[0], ids
    if _unexpected_over(batch, coverage, selected):
        return None, "UNEXPECTED_OVERLAPPING_RECORD", ids
    bars = [item.bar for item in selected]
    if any(bar.certified_no_trade for bar in bars):
        return None, "NO_TRADED_RS_INTERVAL", ids
    types = {bar.metadata.instrument_type for bar in bars}
    if len(types) != 1 or (instrument_type is not None and types != {instrument_type}):
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    # A traded canonical bar always carries positive OHLCV, so the basis is safe.
    base = bars[0].open if policy.return_basis == "FIRST_BAR_OPEN" else bars[0].close
    start = Decimal(str(base))
    return (Decimal(str(bars[-1].close)) - start) / start, None, ids


def build_rs_trend_snapshot(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
    benchmark_history: HistoryBatch | None,
    policy: RsWindowPolicy,
) -> FeatureSnapshot:
    """Measure the stock return, the benchmark return and their difference."""
    moment = _instant(evaluated_at, "evaluated_at")
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("RS symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("RS instrument type must be EQUITY or ETF")
    if not isinstance(policy, RsWindowPolicy):
        raise RecordError("policy must be RsWindowPolicy")
    if policy.benchmark_symbol == symbol:
        raise RecordError("the benchmark must differ from the measured symbol")

    day = session_date_at(moment)
    bounds = session_bounds(day)
    session = day.isoformat()
    if bounds is None:
        warm = False
        stock = benchmark = (None, "NO_REGULAR_SESSION", ())
    else:
        opened, closed = map(as_utc, bounds)
        elapsed = (min(moment, closed) - opened) // timedelta(minutes=1)
        warm = elapsed >= policy.required_bars
        measured = []
        for batch, wanted, kind in (
            (minute_history, symbol, instrument_type),
            (benchmark_history, policy.benchmark_symbol, None),
        ):
            reason = _basis_reason(batch, wanted)
            if reason is not None:
                measured.append((None, reason, ()))
            elif not warm:
                measured.append((None, "RS_WARMUP_INCOMPLETE", ()))
            else:
                measured.append(_lookback_return(batch, batch.coverage_at(moment), moment,
                                                 opened, closed, session, policy, kind))
        stock, benchmark = measured
        benchmark = (benchmark[0],
                     None if benchmark[1] is None else "BENCHMARK_" + benchmark[1],
                     benchmark[2])

    features = [_value(STOCK_RETURN_NAME, stock[0], "RATIO", stock[1], stock[2]),
                _value(BENCHMARK_RETURN_NAME, benchmark[0], "RATIO", benchmark[1], benchmark[2])]
    ids = tuple(sorted(set(stock[2]) | set(benchmark[2])))
    if stock[0] is None or benchmark[0] is None:
        features.append(_value(RS_NAME, None, "RATIO", stock[1] or benchmark[1], ids))
    else:
        features.append(_value(RS_NAME, stock[0] - benchmark[0], "RATIO", None, ids))
    features += [_value(RS_BARS_NAME, policy.lookback_bars, "COUNT", None, ()),
                 _value(RS_WARMUP_NAME, int(warm), "BOOLEAN", None, ())]

    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_M72",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=session, data_mode=RS_DATA_MODE, quality="VALID",
    )
    return FeatureSnapshot(
        record_id=record_id, metadata=metadata, evaluated_at=moment,
        features=tuple(features), feature_version=RS_FEATURE_VERSION, input_record_ids=ids,
    )


# --- RS and trend eligibility ----------------------------------------------


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
class RsTrendPolicy:
    """Explicitly supplied thresholds, windows and bindings; nothing defaulted.

    Values describe the caller's own definition. Supplying them neither adopts a
    proposed rule nor proves the referenced definition has been approved. The two
    floor-and-volatility minimums each take both of their parts from the caller.
    """

    version: str
    definition_reference: str
    window_start_minutes: int
    window_end_minutes: int
    min_price: float
    min_median_dollar_volume: float
    min_rvol: float
    min_abs_open_return: float
    open_return_atr_multiple: float
    min_rs: float
    rs_atr_multiple: float
    max_spread_bps: float
    max_quote_age_seconds: float
    max_trade_age_seconds: float
    max_feature_age_seconds: float
    bindings: tuple[FeatureBinding, ...]

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        for name in ("window_start_minutes", "window_end_minutes"):
            if type(getattr(self, name)) is not int:
                raise RecordError(f"{name} must be an integer")
        if not 0 <= self.window_start_minutes < self.window_end_minutes:
            raise RecordError("the evaluation window must be a positive half-open range")
        for name in ("min_price", "min_median_dollar_volume", "min_rvol",
                     "min_abs_open_return", "open_return_atr_multiple", "min_rs",
                     "rs_atr_multiple", "max_spread_bps", "max_quote_age_seconds",
                     "max_trade_age_seconds", "max_feature_age_seconds"):
            _threshold(getattr(self, name), name)
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
class RsTrendRequest:
    """One evaluation: supplied context, policy and mandatory status facts."""

    context: StrategyContext
    policy: RsTrendPolicy
    status: MandatoryStatus

    def __post_init__(self) -> None:
        if not isinstance(self.context, StrategyContext):
            raise RecordError("context must be StrategyContext")
        if not isinstance(self.policy, RsTrendPolicy):
            raise RecordError("policy must be RsTrendPolicy")
        if not isinstance(self.status, MandatoryStatus):
            raise RecordError("mandatory status must be supplied")


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
class RsTrendAssessment:
    """Immutable result of one evaluation; the caller owns storage and delivery."""

    evaluated_at: datetime
    state: StrategyState
    gates: tuple[GateResult, ...]
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
            "reasons": list(self.reasons),
            "input_record_ids": list(self.input_record_ids),
            "policy_version": self.policy_version,
            "definition_reference": self.definition_reference,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)


def rs_trend_rules() -> TransitionRules:
    """Exactly the M7.2 states; the trigger and reset belong to M7.3."""
    states = tuple(StrategyState(name) for name in STATES[:4])
    expired = StrategyState("EXPIRED")
    allowed = tuple((old, new) for old in states for new in states if old != new)
    return TransitionRules(RULES_VERSION, StrategyState("NOT_ELIGIBLE"),
                           allowed + tuple((old, expired) for old in states))


def _resolve(request: RsTrendRequest, role: str) -> tuple[Fraction | None, str | None, tuple[str, ...]]:
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


def _latest_trade(request: RsTrendRequest) -> tuple[Fraction | None, str | None, tuple[str, ...]]:
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


def _flag(name: str, value: Fraction | None, reason: str | None, ids: tuple[str, ...],
          *, unset: str, not_boolean: str) -> GateResult:
    """One supplied boolean fact: complete, not complete, or not known."""
    if value is None:
        return GateResult(name, UNKNOWN, None, 1.0, reason, ids)
    if value == 1:
        return GateResult(name, PASS, 1.0, 1.0, None, ids)
    if value == 0:
        return GateResult(name, FAIL, 0.0, 1.0, unset, ids)
    return GateResult(name, UNKNOWN, float(value), 1.0, not_boolean, ids)


def _window(request: RsTrendRequest) -> GateResult:
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


def _quote_gates(request: RsTrendRequest) -> tuple[GateResult, GateResult]:
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


def _status_gate(request: RsTrendRequest) -> GateResult:
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


def evaluate_rs_trend_eligibility(request: RsTrendRequest) -> RsTrendAssessment:
    """Report every supplied gate and the state they support, with no side effect.

    Returning ARMED describes the supplied inputs at this instant only. It does
    not trigger, approve the referenced definition, prove source coverage or
    authorize delivery.
    """
    if not isinstance(request, RsTrendRequest):
        raise RecordError("RsTrendRequest is required")
    policy, context = request.policy, request.context
    window = _window(request)

    price, price_reason, price_ids = _latest_trade(request)
    dollar, dollar_reason, dollar_ids = _resolve(request, "MEDIAN_DOLLAR_VOLUME")
    rvol, rvol_reason, rvol_ids = _resolve(request, "RVOL")
    open_return, open_reason, open_ids = _resolve(request, "OPEN_RETURN")
    atr_pct, atr_reason, atr_ids = _resolve(request, "DAILY_ATR_PCT")
    vwap, vwap_reason, vwap_ids = _resolve(request, "SESSION_VWAP")
    rs, rs_reason, rs_ids = _resolve(request, "RS")
    warm, warm_reason, warm_ids = _resolve(request, "RS_WARMUP_COMPLETE")
    frozen, frozen_reason, frozen_ids = _resolve(request, "REFERENCE_EXTREME_COMPLETE")
    measured, measured_reason, measured_ids = _resolve(request, "COMPRESSION_COMPLETE")

    open_gate_ids = tuple(sorted(set(open_ids) | set(atr_ids)))
    if atr_pct is None:
        open_gate = GateResult("OPEN_RETURN", UNKNOWN, None, None, atr_reason, open_gate_ids)
    else:
        limit = max(_threshold(policy.min_abs_open_return, "min_abs_open_return"),
                    _threshold(policy.open_return_atr_multiple, "open_return_atr_multiple")
                    * atr_pct)
        open_gate = _minimum("OPEN_RETURN", None if open_return is None else abs(open_return),
                             open_reason, limit, open_gate_ids, below="BELOW_MIN_OPEN_RETURN")

    rs_gate_ids = tuple(sorted(set(rs_ids) | set(atr_ids)))
    if atr_pct is None:
        rs_gate = GateResult("RS_TREND", UNKNOWN, None, None, atr_reason, rs_gate_ids)
    else:
        limit = max(_threshold(policy.min_rs, "min_rs"),
                    _threshold(policy.rs_atr_multiple, "rs_atr_multiple") * atr_pct)
        # A short setup needs the same strength against the benchmark, mirrored.
        signed = None if rs is None else (rs if context.direction == "LONG" else -rs)
        rs_gate = _minimum("RS_TREND", signed, rs_reason, limit, rs_gate_ids,
                           below="RS_BELOW_DIRECTIONAL_MINIMUM")

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
        window,
        _flag("REFERENCE_FROZEN", frozen, frozen_reason, frozen_ids,
              unset="REFERENCE_NOT_FROZEN", not_boolean="REFERENCE_FLAG_NOT_BOOLEAN"),
        _flag("COMPRESSION_MEASURED", measured, measured_reason, measured_ids,
              unset="COMPRESSION_NOT_MEASURED", not_boolean="COMPRESSION_FLAG_NOT_BOOLEAN"),
        _minimum("MIN_PRICE", price, price_reason,
                 _threshold(policy.min_price, "min_price"), price_ids, below="BELOW_MIN_PRICE"),
        _minimum("MEDIAN_DOLLAR_VOLUME", dollar, dollar_reason,
                 _threshold(policy.min_median_dollar_volume, "min_median_dollar_volume"),
                 dollar_ids, below="BELOW_MIN_DOLLAR_VOLUME"),
        _minimum("RVOL", rvol, rvol_reason, _threshold(policy.min_rvol, "min_rvol"),
                 rvol_ids, below="BELOW_MIN_RVOL"),
        open_gate,
        _flag("RS_WARMUP", warm, warm_reason, warm_ids,
              unset="RS_WARMUP_INCOMPLETE", not_boolean="RS_WARMUP_FLAG_NOT_BOOLEAN"),
        rs_gate, vwap_gate, actionable, spread_gate, _status_gate(request),
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
    return RsTrendAssessment(context.evaluated_at, StrategyState(state), gates, reasons, ids,
                             policy.version, policy.definition_reference)


class HodCompRsEligibilityMachine:
    """One serially owned (session, symbol, direction) eligibility state owner.

    The machine proposes canonical transitions for the M4.2 engine and the M5.1
    store; it never writes, sends or advances itself. Local state moves only when
    the caller confirms the proposed transition after storage acknowledged it.
    """

    def __init__(self, *, session: SessionRecord, symbol: str, instrument_type: str,
                 direction: str, strategy_version: str, policy: RsTrendPolicy):
        if not isinstance(session, SessionRecord):
            raise RecordError("session must be SessionRecord")
        if not isinstance(policy, RsTrendPolicy):
            raise RecordError("policy must be RsTrendPolicy")
        if instrument_type not in _INSTRUMENT_TYPES:
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
        self._rules = rs_trend_rules()
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

    def _check(self, request: RsTrendRequest) -> None:
        if not isinstance(request, RsTrendRequest):
            raise RecordError("RsTrendRequest is required")
        context = request.context
        if (context.session != self._session or context.symbol != self._symbol
                or context.instrument_type != self._instrument_type
                or context.direction != self._direction):
            raise RecordError("evaluation does not match this eligibility owner")
        if request.policy != self._policy:
            raise RecordError("policy cannot change inside one owner")
        if self._time is not None and context.evaluated_at < self._time:
            raise RecordError("evaluation time cannot move backward")

    def evaluate(self, request: RsTrendRequest) -> RsTrendAssessment:
        self._check(request)
        assessment = evaluate_rs_trend_eligibility(request)
        self._time = request.context.evaluated_at
        return assessment

    def propose(self, request: RsTrendRequest, *, record_id: str,
                ) -> tuple[RsTrendAssessment, tuple[StrategyStateTransition, ...]]:
        """Return this evaluation and the transition a caller must store first."""
        _label(record_id, "transition record ID")
        assessment = self.evaluate(request)
        if assessment.state == self._state:
            self._pending = None
            return assessment, ()
        if (self._state, assessment.state) not in self._rules.allowed:
            raise RecordError("computed state is not in the M7.2 rules")
        context = request.context
        at = context.evaluated_at
        snapshot = next(
            (row.record_id for row in context.features
             if row.record_id in assessment.gate("RS_WARMUP").input_record_ids), None)
        inputs = tuple(value for value in assessment.input_record_ids if value in {
            *(row.record_id for row in context.features),
            *((context.quote.quote.record_id,)
              if context.quote is not None and context.quote.quote is not None else ()),
        })
        metadata = SourceMetadata(
            instrument_id=self._symbol, instrument_type=self._instrument_type,
            source="DERIVED_M72", source_time=at, received_time=at, available_time=at,
            normalized_time=at, session=self._session.session, data_mode=DATA_MODE,
            quality="VALID",
        )
        transition = StrategyStateTransition(
            record_id=record_id, metadata=metadata, strategy_id=STRATEGY_ID,
            strategy_version=self._version, occurred_at=at,
            from_state=self._state.state, from_substate=self._state.substate,
            to_state=assessment.state.state, to_substate=assessment.state.substate,
            reason=(assessment.reasons[0] if assessment.reasons
                    else "ALL_SUPPLIED_RS_TREND_GATES_PASSED"),
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
            raise RecordError("restored state is not an M7.2 state")
        self._state = state
        return self._state


__all__ = [
    "ARMED_GATES", "DATA_MODE", "ELIGIBILITY_VERSION", "FeatureBinding", "GateResult",
    "HodCompRsEligibilityMachine", "MandatoryStatus", "REQUIRED_ROLES", "RETURN_BASES",
    "RS_DATA_MODE", "RS_FEATURE_NAMES", "RS_FEATURE_VERSION", "RULES_VERSION",
    "RsTrendAssessment", "RsTrendPolicy", "RsTrendRequest", "RsWindowPolicy",
    "SETUP_GATES", "STATES", "STRATEGY_ID", "WINDOW_GATE", "build_rs_trend_snapshot",
    "evaluate_rs_trend_eligibility", "rs_trend_rules",
]
