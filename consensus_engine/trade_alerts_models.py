"""Immutable, versioned records for the intraday trade-alert extension.

The records in this module contain facts only.  They do not fetch data, choose
strategy thresholds, score setups, persist rows, or deliver alerts.
"""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
import json
import math
from types import UnionType
from typing import Any, ClassVar, TypeVar, Union, get_args, get_origin, get_type_hints

from .trade_alerts_config import STRATEGY_IDS, TradeAlertsConfig
from .utils.time_context import as_utc


SCHEMA_VERSION = 1
DATA_QUALITIES = frozenset({"VALID", "STALE", "UNAVAILABLE", "DEGRADED_PROXY", "INVALID", "UNKNOWN"})
SETUP_STATES = frozenset({
    "NOT_ELIGIBLE", "WATCHING", "SETUP_FORMING", "ARMED",
    "ALERT_TRIGGERED", "INVALIDATED", "EXPIRED",
})
STRATEGY_LIFECYCLES = frozenset({
    "DEVELOPMENT", "SHADOW", "PROVISIONAL", "ACTIVE", "DEGRADED",
    "DISABLED", "REJECTED", "INSUFFICIENT_DATA",
})
EVIDENCE_STAGES = frozenset({
    "IMPLEMENTED", "UNIT_TESTED", "REPLAYABLE", "HISTORICALLY_TESTED",
    "WALK_FORWARD_TESTED", "SHADOW_TESTED", "PROVISIONAL", "ACTIVE",
    "MODIFY", "REJECTED", "INSUFFICIENT_DATA",
})
DELIVERY_STATUSES = frozenset({
    "PENDING", "ATTEMPT_CREATED", "SEND_STARTED", "CONFIRMED_DELIVERED",
    "REJECTED_BEFORE_SEND", "TIMED_OUT", "FAILED", "UNKNOWN",
})
QUOTE_STATUSES = frozenset({
    "VALID", "STALE", "MISSING", "UNAVAILABLE", "INVALID", "CROSSED",
    "NO_TWO_SIDED",
})
OUTCOME_RESULTS = frozenset({
    "UNKNOWN", "RESOLVED", "UNFILLED", "AMBIGUOUS", "CENSORED",
})
_T = TypeVar("_T", bound="Record")


class RecordError(ValueError):
    """Raised when a canonical record is incomplete or internally impossible."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{name} must be a non-empty string")
    return value


def _number(value: Any, name: str, *, optional: bool = False) -> float | int | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    if not math.isfinite(value):
        raise RecordError(f"{name} must be finite")
    return value


def _nonnegative(value: Any, name: str, *, optional: bool = False) -> float | int | None:
    result = _number(value, name, optional=optional)
    if result is not None and result < 0:
        raise RecordError(f"{name} must be non-negative")
    return result


def _instant(value: datetime | None, name: str, *, optional: bool = False) -> datetime | None:
    if optional and value is None:
        return None
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _strings(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise RecordError(f"{name} must be a tuple")
    for value in values:
        _text(value, name)
    return tuple(values)


def _strategy(value: str) -> None:
    if value not in STRATEGY_IDS:
        raise RecordError("strategy_id is not supported")


def _config_hash(value: str) -> None:
    _text(value, "config_hash")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise RecordError("config_hash must be a lowercase SHA-256 value")


def _session_date(value: str) -> None:
    _text(value, "session")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise RecordError("session must be an ISO calendar date") from exc
    if parsed.isoformat() != value:
        raise RecordError("session must be an ISO calendar date")


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return as_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _encode(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and not math.isfinite(value):
            raise RecordError("records cannot contain non-finite numbers")
        return value
    raise RecordError(f"unsupported record value: {type(value).__name__}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RecordError("record JSON cannot contain duplicate fields")
        result[key] = value
    return result


def _decode(value: Any, annotation: Any, name: str) -> Any:
    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin in (Union, UnionType):
        if value is None and type(None) in arguments:
            return None
        options = tuple(item for item in arguments if item is not type(None))
        if len(options) == 1:
            return _decode(value, options[0], name)
    if annotation is datetime:
        if not isinstance(value, str):
            raise RecordError(f"{name} must be a timestamp string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecordError(f"{name} is not a valid timestamp") from exc
        return _instant(parsed, name)
    if annotation is date:
        if not isinstance(value, str):
            raise RecordError(f"{name} must be a date string")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise RecordError(f"{name} is not a valid date") from exc
    if origin is tuple:
        if not isinstance(value, list):
            raise RecordError(f"{name} must be an array")
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(_decode(item, arguments[0], name) for item in value)
        if len(value) != len(arguments):
            raise RecordError(f"{name} has the wrong number of items")
        return tuple(_decode(item, item_type, name) for item, item_type in zip(value, arguments))
    if isinstance(annotation, type) and is_dataclass(annotation):
        return _construct(annotation, value)
    if annotation in (float, int):
        _number(value, name)
        if annotation is int and type(value) is not int:
            raise RecordError(f"{name} must be an integer")
        return value
    if annotation is bool and type(value) is not bool:
        raise RecordError(f"{name} must be true or false")
    if annotation is str and not isinstance(value, str):
        raise RecordError(f"{name} must be a string")
    return value


def _construct(record_class: type[_T], values: Any) -> _T:
    if not isinstance(values, dict):
        raise RecordError(f"{record_class.__name__} must be an object")
    hints = get_type_hints(record_class)
    expected = {item.name for item in fields(record_class)}
    supplied = set(values)
    if supplied != expected:
        missing = expected - supplied
        extra = supplied - expected
        detail = "missing" if missing else "unsupported"
        raise RecordError(f"{record_class.__name__} has {detail} fields")
    decoded = {
        name: _decode(values[name], hints[name], f"{record_class.__name__}.{name}")
        for name in expected
    }
    return record_class(**decoded)


@dataclass(frozen=True)
class Record:
    """Base for deterministic top-level record serialization."""

    RECORD_TYPE: ClassVar[str] = "Record"
    record_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "record_id")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise RecordError(f"schema_version must be {SCHEMA_VERSION}")

    def as_dict(self) -> dict[str, Any]:
        result = _encode(self)
        return {"record_type": self.RECORD_TYPE, **result}

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        )

    @classmethod
    def from_json(cls: type[_T], payload: str) -> _T:
        result = record_from_json(payload)
        if type(result) is not cls:
            raise RecordError(f"expected record_type {cls.RECORD_TYPE}")
        return result


@dataclass(frozen=True)
class SourceMetadata:
    """Provider and availability facts retained as separate absolute times.

    Archived data may have been available before this process later normalized
    it, so both must follow receipt but neither is derived from the other.
    """

    instrument_id: str
    source: str
    source_time: datetime | None
    received_time: datetime
    available_time: datetime
    normalized_time: datetime
    session: str
    instrument_type: str = "UNKNOWN"
    sequence: int | None = None
    revision: int = 0
    data_mode: str = "UNKNOWN"
    quality: str = "UNKNOWN"

    def __post_init__(self) -> None:
        _text(self.instrument_id, "instrument_id")
        if self.instrument_type not in ("EQUITY", "ETF", "OPTION", "UNKNOWN"):
            raise RecordError("instrument_type is not supported")
        _text(self.source, "source")
        _session_date(self.session)
        _text(self.data_mode, "data_mode")
        if self.quality not in DATA_QUALITIES:
            raise RecordError("quality is not supported")
        object.__setattr__(self, "source_time", _instant(self.source_time, "source_time", optional=True))
        object.__setattr__(self, "received_time", _instant(self.received_time, "received_time"))
        object.__setattr__(self, "available_time", _instant(self.available_time, "available_time"))
        object.__setattr__(self, "normalized_time", _instant(self.normalized_time, "normalized_time"))
        if self.sequence is not None and (type(self.sequence) is not int or self.sequence < 0):
            raise RecordError("sequence must be a non-negative integer or null")
        if type(self.revision) is not int or self.revision < 0:
            raise RecordError("revision must be a non-negative integer")
        if self.normalized_time < self.received_time:
            raise RecordError("normalized_time cannot precede received_time")
        if self.available_time < self.received_time:
            raise RecordError("available_time cannot precede received_time")


@dataclass(frozen=True)
class Bar(Record):
    RECORD_TYPE: ClassVar[str] = "Bar"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    start_time: datetime = None  # type: ignore[assignment]
    end_time: datetime = None  # type: ignore[assignment]
    is_final: bool = False
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None
    adjustment_basis: str = "UNSPECIFIED"
    price_convention: str = "UNSPECIFIED"
    volume_convention: str = "UNSPECIFIED"
    certified_no_trade: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        start = _instant(self.start_time, "start_time")
        end = _instant(self.end_time, "end_time")
        object.__setattr__(self, "start_time", start)
        object.__setattr__(self, "end_time", end)
        if start >= end:
            raise RecordError("bar start_time must precede end_time")
        if type(self.is_final) is not bool or type(self.certified_no_trade) is not bool:
            raise RecordError("bar finality flags must be true or false")
        for name in ("adjustment_basis", "price_convention", "volume_convention"):
            _text(getattr(self, name), name)
        _nonnegative(self.volume, "volume", optional=True)
        prices = (self.open, self.high, self.low, self.close)
        if self.certified_no_trade:
            if not self.is_final or self.metadata.quality != "VALID":
                raise RecordError("certified no-trade bars require final VALID source evidence")
            if any(value is not None for value in prices) or self.volume != 0:
                raise RecordError("certified no-trade bars require null prices and zero volume")
        elif self.metadata.quality == "UNAVAILABLE":
            if any(value is not None for value in prices) or self.volume is not None:
                raise RecordError("unavailable bars require null OHLCV")
        else:
            if any(value is None for value in prices) or self.volume is None:
                raise RecordError("traded bars require all OHLCV values")
            for name, value in zip(("open", "high", "low", "close"), prices):
                if _number(value, name) <= 0:  # type: ignore[operator]
                    raise RecordError(f"{name} must be positive")
            if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):  # type: ignore[type-var]
                raise RecordError("bar OHLC geometry is invalid")
            if self.low > self.high:  # type: ignore[operator]
                raise RecordError("bar low cannot exceed high")
        if self.is_final and self.metadata.available_time < end:
            raise RecordError("a final bar cannot be available before its end")


@dataclass(frozen=True)
class Quote(Record):
    RECORD_TYPE: ClassVar[str] = "Quote"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    quote_time: datetime | None = None
    trade_time: datetime | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    last_size: int | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    status: str = "MISSING"
    delayed: bool | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        object.__setattr__(self, "quote_time", _instant(self.quote_time, "quote_time", optional=True))
        object.__setattr__(self, "trade_time", _instant(self.trade_time, "trade_time", optional=True))
        for name in ("quote_time", "trade_time"):
            value = getattr(self, name)
            if value is not None and value > self.metadata.available_time:
                raise RecordError(f"{name} cannot follow available_time")
        if self.status not in QUOTE_STATUSES:
            raise RecordError("quote status is not supported")
        if self.delayed is not None and type(self.delayed) is not bool:
            raise RecordError("delayed must be true, false or null")
        for name in ("bid", "ask", "last", "bid_size", "ask_size", "last_size"):
            _nonnegative(getattr(self, name), name, optional=True)
        for name in ("bid_size", "ask_size", "last_size"):
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise RecordError(f"{name} must be an integer or null")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise RecordError("bid cannot exceed ask")


@dataclass(frozen=True)
class OptionQuote(Record):
    RECORD_TYPE: ClassVar[str] = "OptionQuote"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    contract_id: str = ""
    underlying_id: str = ""
    expiry: date = None  # type: ignore[assignment]
    strike: float = 0.0
    option_type: str = ""
    multiplier: float | None = None
    deliverable: str | None = None
    quote_time: datetime | None = None
    trade_time: datetime | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    open_interest: int | None = None
    open_interest_time: datetime | None = None
    volume: int | None = None
    non_standard: bool | None = None
    status: str = "MISSING"
    delayed: bool | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        if self.metadata.instrument_id != self.contract_id:
            raise RecordError("metadata instrument_id must match contract_id")
        if self.metadata.instrument_type not in ("OPTION", "UNKNOWN"):
            raise RecordError("option quote metadata cannot identify an equity or ETF")
        for name in ("contract_id", "underlying_id"):
            _text(getattr(self, name), name)
        if self.status not in QUOTE_STATUSES:
            raise RecordError("option quote status is not supported")
        if self.deliverable is not None:
            _text(self.deliverable, "deliverable")
        if not isinstance(self.expiry, date) or isinstance(self.expiry, datetime):
            raise RecordError("expiry must be a date")
        if self.option_type not in ("CALL", "PUT"):
            raise RecordError("option_type must be CALL or PUT")
        if _number(self.strike, "strike") <= 0:  # type: ignore[operator]
            raise RecordError("strike must be positive")
        multiplier = _number(self.multiplier, "multiplier", optional=True)
        if multiplier is not None and multiplier <= 0:
            raise RecordError("multiplier must be positive or null")
        object.__setattr__(self, "quote_time", _instant(self.quote_time, "quote_time", optional=True))
        object.__setattr__(self, "trade_time", _instant(self.trade_time, "trade_time", optional=True))
        object.__setattr__(self, "open_interest_time", _instant(self.open_interest_time, "open_interest_time", optional=True))
        for name in ("quote_time", "trade_time", "open_interest_time"):
            value = getattr(self, name)
            if value is not None and value > self.metadata.available_time:
                raise RecordError(f"{name} cannot follow available_time")
        for name in ("delayed", "non_standard"):
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise RecordError(f"{name} must be true, false or null")
        for name in ("bid", "ask", "last", "bid_size", "ask_size", "implied_volatility", "open_interest", "volume"):
            _nonnegative(getattr(self, name), name, optional=True)
        for name in ("delta", "gamma", "theta", "vega", "rho"):
            _number(getattr(self, name), name, optional=True)
        for name in ("bid_size", "ask_size", "open_interest", "volume"):
            value = getattr(self, name)
            if value is not None and type(value) is not int:
                raise RecordError(f"{name} must be an integer or null")
        if self.bid is not None and self.ask is not None and self.bid > self.ask:
            raise RecordError("bid cannot exceed ask")


@dataclass(frozen=True)
class CatalystEvent(Record):
    RECORD_TYPE: ClassVar[str] = "CatalystEvent"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    event_type: str = ""
    headline: str = ""
    occurred_time: datetime | None = None
    source_event_id: str | None = None
    classification: str = "UNKNOWN"
    confidence: float | None = None
    classified_at: datetime | None = None
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        _text(self.event_type, "event_type")
        _text(self.headline, "headline")
        _text(self.classification, "classification")
        _number(self.confidence, "confidence", optional=True)
        object.__setattr__(self, "classified_at", _instant(self.classified_at, "classified_at", optional=True))
        if self.classified_at is not None and self.classified_at < self.metadata.received_time:
            raise RecordError("classified_at cannot precede received_time")
        object.__setattr__(self, "occurred_time", _instant(self.occurred_time, "occurred_time", optional=True))
        if self.source_event_id is not None:
            _text(self.source_event_id, "source_event_id")
        if not isinstance(self.details, tuple):
            raise RecordError("details must be a tuple")
        for item in self.details:
            if not isinstance(item, tuple) or len(item) != 2:
                raise RecordError("details entries must be key/value tuples")
            _text(item[0], "detail key")
            if not isinstance(item[1], str):
                raise RecordError("detail value must be a string")
        detail_keys = [item[0] for item in self.details]
        if len(detail_keys) != len(set(detail_keys)):
            raise RecordError("detail keys must be unique")


@dataclass(frozen=True)
class FeatureValue:
    name: str
    value: float | None
    unit: str
    missing_reason: str | None = None
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.name, "feature name")
        _text(self.unit, "feature unit")
        _number(self.value, "feature value", optional=True)
        if self.value is None and self.missing_reason is None:
            raise RecordError("a missing feature requires missing_reason")
        if self.value is not None and self.missing_reason is not None:
            raise RecordError("an available feature cannot have missing_reason")
        if self.missing_reason is not None:
            _text(self.missing_reason, "missing_reason")
        object.__setattr__(self, "input_record_ids", _strings(self.input_record_ids, "input_record_ids"))


@dataclass(frozen=True)
class FeatureSnapshot(Record):
    RECORD_TYPE: ClassVar[str] = "FeatureSnapshot"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    evaluated_at: datetime = None  # type: ignore[assignment]
    features: tuple[FeatureValue, ...] = ()
    feature_version: str = ""
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        if self.evaluated_at < self.metadata.available_time:
            raise RecordError("evaluated_at cannot precede available_time")
        _text(self.feature_version, "feature_version")
        if not isinstance(self.features, tuple) or any(not isinstance(item, FeatureValue) for item in self.features):
            raise RecordError("features must be a tuple of FeatureValue")
        names = [item.name for item in self.features]
        if len(names) != len(set(names)):
            raise RecordError("feature names must be unique")
        object.__setattr__(self, "input_record_ids", _strings(self.input_record_ids, "input_record_ids"))


@dataclass(frozen=True)
class StrategyStateTransition(Record):
    RECORD_TYPE: ClassVar[str] = "StrategyStateTransition"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    strategy_id: str = ""
    strategy_version: str = ""
    occurred_at: datetime = None  # type: ignore[assignment]
    from_state: str = ""
    to_state: str = ""
    from_substate: str | None = None
    to_substate: str | None = None
    reason: str = ""
    input_record_ids: tuple[str, ...] = ()
    feature_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        _strategy(self.strategy_id)
        for name in ("strategy_version", "reason"):
            _text(getattr(self, name), name)
        if self.from_state not in SETUP_STATES or self.to_state not in SETUP_STATES:
            raise RecordError("transition state is not supported")
        for name in ("from_substate", "to_substate"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        object.__setattr__(self, "occurred_at", _instant(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "input_record_ids", _strings(self.input_record_ids, "input_record_ids"))
        if self.feature_snapshot_id is not None:
            _text(self.feature_snapshot_id, "feature_snapshot_id")


@dataclass(frozen=True)
class RiskLevel:
    entry_reference: float
    hard_stop: float
    risk_per_share: float
    rationale: str
    source: str

    def __post_init__(self) -> None:
        for name in ("entry_reference", "hard_stop", "risk_per_share"):
            if _number(getattr(self, name), name) <= 0:  # type: ignore[operator]
                raise RecordError(f"{name} must be positive")
        if not math.isclose(abs(self.entry_reference - self.hard_stop), self.risk_per_share):
            raise RecordError("risk_per_share must equal the entry-to-stop distance")
        _text(self.rationale, "risk rationale")
        _text(self.source, "risk source")


@dataclass(frozen=True)
class TargetLevel:
    name: str
    price: float
    r_multiple: float
    source: str

    def __post_init__(self) -> None:
        _text(self.name, "target name")
        if _number(self.price, "target price") <= 0:  # type: ignore[operator]
            raise RecordError("target price must be positive")
        if _number(self.r_multiple, "target r_multiple") <= 0:  # type: ignore[operator]
            raise RecordError("target r_multiple must be positive")
        _text(self.source, "target source")


@dataclass(frozen=True)
class ConfidenceComponent:
    name: str
    value: float
    version: str

    def __post_init__(self) -> None:
        _text(self.name, "confidence component")
        _number(self.value, "confidence value")
        _text(self.version, "confidence version")


@dataclass(frozen=True)
class ConfidenceBreakdown:
    setup_score: float
    context_score: float
    execution_score: float
    final_score: float
    factors: tuple[ConfidenceComponent, ...] = ()

    def __post_init__(self) -> None:
        for name in ("setup_score", "context_score", "execution_score", "final_score"):
            value = _number(getattr(self, name), name)
            if value < 0 or value > 100:  # type: ignore[operator]
                raise RecordError(f"{name} must be between 0 and 100")
        if not isinstance(self.factors, tuple) or any(
            not isinstance(item, ConfidenceComponent) for item in self.factors
        ):
            raise RecordError("factors must be ConfidenceComponent records")


@dataclass(frozen=True)
class ConfluenceLink:
    strategy_id: str
    candidate_id: str

    def __post_init__(self) -> None:
        _strategy(self.strategy_id)
        _text(self.candidate_id, "candidate_id")


@dataclass(frozen=True)
class AlertCandidate(Record):
    RECORD_TYPE: ClassVar[str] = "AlertCandidate"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    strategy_id: str = ""
    strategy_version: str = ""
    direction: str = ""
    alert_type: str = ""
    setup_state: str = ""
    setup_substate: str | None = None
    strategy_lifecycle: str = ""
    evidence_stage: str = ""
    delivery_status: str = ""
    structure_id: str = ""
    trigger_price: float | None = None
    alert_price: float | None = None
    risk: RiskLevel | None = None
    soft_invalidation: str | None = None
    targets: tuple[TargetLevel, ...] = ()
    confidence: ConfidenceBreakdown = None  # type: ignore[assignment]
    confluence: tuple[ConfluenceLink, ...] = ()
    human_checks: tuple[str, ...] = ()
    input_record_ids: tuple[str, ...] = ()
    feature_snapshot_id: str = ""
    session_record_id: str = ""
    config_version: str = ""
    config_hash: str = ""
    created_at: datetime = None  # type: ignore[assignment]
    expires_at: datetime = None  # type: ignore[assignment]
    data_quality: str = "UNKNOWN"
    mechanically_valid: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        _strategy(self.strategy_id)
        for name in (
            "strategy_version", "direction", "alert_type", "setup_state",
            "strategy_lifecycle", "evidence_stage", "delivery_status",
            "structure_id", "feature_snapshot_id", "session_record_id",
            "config_version",
        ):
            _text(getattr(self, name), name)
        if self.direction not in ("LONG", "SHORT"):
            raise RecordError("direction must be LONG or SHORT")
        if self.alert_type not in ("HEADS_UP", "ACTIONABLE"):
            raise RecordError("alert_type must be HEADS_UP or ACTIONABLE")
        if self.setup_state not in SETUP_STATES:
            raise RecordError("setup_state is not supported")
        if self.setup_substate is not None:
            _text(self.setup_substate, "setup_substate")
        if self.strategy_lifecycle not in STRATEGY_LIFECYCLES:
            raise RecordError("strategy_lifecycle is not supported")
        if self.evidence_stage not in EVIDENCE_STAGES:
            raise RecordError("evidence_stage is not supported")
        if self.delivery_status not in DELIVERY_STATUSES:
            raise RecordError("delivery_status is not supported")
        if self.data_quality not in DATA_QUALITIES:
            raise RecordError("data_quality is not supported")
        _config_hash(self.config_hash)
        for name in ("trigger_price", "alert_price"):
            value = _number(getattr(self, name), name, optional=True)
            if value is not None and value <= 0:
                raise RecordError(f"{name} must be positive")
        if self.risk is not None and not isinstance(self.risk, RiskLevel):
            raise RecordError("risk must be RiskLevel or null")
        if self.soft_invalidation is not None:
            _text(self.soft_invalidation, "soft_invalidation")
        if not isinstance(self.confidence, ConfidenceBreakdown):
            raise RecordError("confidence must be ConfidenceBreakdown")
        for name, values, expected in (
            ("targets", self.targets, TargetLevel),
            ("confluence", self.confluence, ConfluenceLink),
        ):
            if not isinstance(values, tuple) or any(not isinstance(item, expected) for item in values):
                raise RecordError(f"{name} has invalid entries")
        object.__setattr__(self, "input_record_ids", _strings(self.input_record_ids, "input_record_ids"))
        object.__setattr__(self, "human_checks", _strings(self.human_checks, "human_checks"))
        created = _instant(self.created_at, "created_at")
        expires = _instant(self.expires_at, "expires_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if expires <= created:
            raise RecordError("expires_at must follow created_at")
        if created < self.metadata.available_time:
            raise RecordError("created_at cannot precede available_time")
        if type(self.mechanically_valid) is not bool:
            raise RecordError("mechanically_valid must be true or false")
        if self.alert_type == "ACTIONABLE" and self.mechanically_valid:
            if (
                self.trigger_price is None or self.alert_price is None
                or self.risk is None or not self.targets
            ):
                raise RecordError("valid actionable alerts require trigger, alert and targets")
            entry = self.risk.entry_reference
            if self.direction == "LONG":
                if self.risk.hard_stop >= entry or any(target.price <= entry for target in self.targets):
                    raise RecordError("LONG risk and targets have invalid geometry")
            elif self.risk.hard_stop <= entry or any(target.price >= entry for target in self.targets):
                raise RecordError("SHORT risk and targets have invalid geometry")
            for target in self.targets:
                expected_r = abs(target.price - entry) / self.risk.risk_per_share
                if not math.isclose(target.r_multiple, expected_r):
                    raise RecordError("target r_multiple does not match candidate geometry")


@dataclass(frozen=True)
class OptionRecommendation(Record):
    """Option result without confusing poor or unavailable data with selection.

    RECOMMENDED is a complete selected contract. POOR may retain a rejected
    contract and score for research, but never a selected rank. UNAVAILABLE
    carries only the candidate link, timing, reasons, and optional policy.
    """
    RECORD_TYPE: ClassVar[str] = "OptionRecommendation"
    candidate_id: str = ""
    status: str = "UNAVAILABLE"
    ranked_at: datetime = None  # type: ignore[assignment]
    reasons: tuple[str, ...] = ()
    policy_version: str | None = None
    option_quote_id: str | None = None
    contract_id: str | None = None
    expiry: date | None = None
    strike: float | None = None
    option_type: str | None = None
    multiplier: float | None = None
    deliverable: str | None = None
    rank: int | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _text(self.candidate_id, "candidate_id")
        if self.status not in ("RECOMMENDED", "POOR", "UNAVAILABLE"):
            raise RecordError("option status is not supported")
        object.__setattr__(self, "ranked_at", _instant(self.ranked_at, "ranked_at"))
        object.__setattr__(self, "reasons", _strings(self.reasons, "reasons"))
        if not self.reasons:
            raise RecordError("option results require at least one reason")
        if self.policy_version is not None:
            _text(self.policy_version, "policy_version")
        for name in ("option_quote_id", "contract_id", "deliverable"):
            value = getattr(self, name)
            if value is not None:
                _text(value, name)
        if self.expiry is not None and (
            not isinstance(self.expiry, date) or isinstance(self.expiry, datetime)
        ):
            raise RecordError("expiry must be a date or null")
        if self.option_type is not None and self.option_type not in ("CALL", "PUT"):
            raise RecordError("option_type must be CALL, PUT or null")
        for name in ("strike", "multiplier"):
            value = _number(getattr(self, name), name, optional=True)
            if value is not None and value <= 0:
                raise RecordError(f"{name} must be positive")
        if self.rank is not None and (
            type(self.rank) is not int or isinstance(self.rank, bool) or self.rank < 1
        ):
            raise RecordError("rank must be a positive integer or null")
        score = _number(self.score, "option score", optional=True)
        if score is not None and (score < 0 or score > 100):
            raise RecordError("option score must be between 0 and 100")
        if self.status == "RECOMMENDED":
            required = (
                self.policy_version, self.option_quote_id, self.contract_id,
                self.expiry, self.strike, self.option_type, self.multiplier,
                self.deliverable, self.rank, self.score,
            )
            if any(value is None for value in required):
                raise RecordError("recommended options require complete contract and ranking facts")
        elif self.status == "POOR":
            if self.rank is not None:
                raise RecordError("poor option quality cannot claim a selected rank")
            if self.score is not None and self.policy_version is None:
                raise RecordError("a poor option score requires policy_version")
        elif any(value is not None for value in (
            self.option_quote_id, self.contract_id, self.expiry, self.strike,
            self.option_type, self.multiplier, self.deliverable, self.rank,
            self.score,
        )):
            raise RecordError("unavailable options cannot claim contract selection facts")


@dataclass(frozen=True)
class TargetOutcome:
    target_name: str
    hit: bool | None
    hit_at: datetime | None = None

    def __post_init__(self) -> None:
        _text(self.target_name, "target_name")
        if self.hit is not None and type(self.hit) is not bool:
            raise RecordError("target hit must be true, false or null")
        object.__setattr__(self, "hit_at", _instant(self.hit_at, "hit_at", optional=True))
        if self.hit is not True and self.hit_at is not None:
            raise RecordError("target hit_at requires hit=true")


@dataclass(frozen=True)
class OutcomeRecord(Record):
    RECORD_TYPE: ClassVar[str] = "OutcomeRecord"
    candidate_id: str = ""
    option_recommendation_id: str | None = None
    evaluated_at: datetime = None  # type: ignore[assignment]
    horizon: str = ""
    coverage_status: str = "UNRESOLVED"
    policy_version: str | None = None
    alert_price: float | None = None
    modeled_entry_price: float | None = None
    outcome_price: float | None = None
    mfe: float | None = None
    mae: float | None = None
    max_r: float | None = None
    stop_hit: bool | None = None
    stop_hit_at: datetime | None = None
    target_outcomes: tuple[TargetOutcome, ...] = ()
    result: str = "UNKNOWN"
    data_quality: str = "UNKNOWN"
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        _text(self.candidate_id, "candidate_id")
        if self.option_recommendation_id is not None:
            _text(self.option_recommendation_id, "option_recommendation_id")
        object.__setattr__(self, "evaluated_at", _instant(self.evaluated_at, "evaluated_at"))
        for name in ("horizon", "coverage_status"):
            _text(getattr(self, name), name)
        if self.coverage_status not in ("COMPLETE", "PARTIAL", "UNAVAILABLE", "UNRESOLVED"):
            raise RecordError("coverage_status is not supported")
        if self.result not in OUTCOME_RESULTS:
            raise RecordError("outcome result is not supported")
        if self.data_quality not in DATA_QUALITIES:
            raise RecordError("data_quality is not supported")
        if self.policy_version is not None:
            _text(self.policy_version, "policy_version")
        for name in ("alert_price", "modeled_entry_price", "outcome_price"):
            value = _number(getattr(self, name), name, optional=True)
            if value is not None and value <= 0:
                raise RecordError(f"{name} must be positive")
        for name in ("mfe", "mae", "max_r"):
            _number(getattr(self, name), name, optional=True)
        if self.stop_hit is not None and type(self.stop_hit) is not bool:
            raise RecordError("stop_hit must be true, false or null")
        object.__setattr__(self, "stop_hit_at", _instant(self.stop_hit_at, "stop_hit_at", optional=True))
        if self.stop_hit is not True and self.stop_hit_at is not None:
            raise RecordError("stop_hit_at requires stop_hit=true")
        if self.stop_hit_at is not None and self.stop_hit_at > self.evaluated_at:
            raise RecordError("stop_hit_at cannot follow evaluated_at")
        if not isinstance(self.target_outcomes, tuple) or any(
            not isinstance(item, TargetOutcome) for item in self.target_outcomes
        ):
            raise RecordError("target_outcomes must be TargetOutcome records")
        names = [item.target_name for item in self.target_outcomes]
        if len(names) != len(set(names)):
            raise RecordError("target outcome names must be unique")
        if any(
            item.hit_at is not None and item.hit_at > self.evaluated_at
            for item in self.target_outcomes
        ):
            raise RecordError("target hit_at cannot follow evaluated_at")
        if self.coverage_status in ("UNAVAILABLE", "UNRESOLVED") and (
            self.outcome_price is not None or self.mfe is not None
            or self.mae is not None or self.max_r is not None
            or self.stop_hit is not None or self.stop_hit_at is not None
            or any(item.hit is not None or item.hit_at is not None for item in self.target_outcomes)
        ):
            raise RecordError("unavailable or unresolved outcomes cannot claim measured results")
        if self.coverage_status in ("UNAVAILABLE", "UNRESOLVED") and self.result != "UNKNOWN":
            raise RecordError("unavailable or unresolved outcomes require UNKNOWN result")
        object.__setattr__(self, "input_record_ids", _strings(self.input_record_ids, "input_record_ids"))


@dataclass(frozen=True)
class SuppressionEvent(Record):
    RECORD_TYPE: ClassVar[str] = "SuppressionEvent"
    metadata: SourceMetadata = None  # type: ignore[assignment]
    candidate_id: str | None = None
    strategy_id: str = ""
    strategy_version: str = ""
    occurred_at: datetime = None  # type: ignore[assignment]
    reason: str = ""
    input_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("metadata must be SourceMetadata")
        if self.candidate_id is not None:
            _text(self.candidate_id, "candidate_id")
        _strategy(self.strategy_id)
        _text(self.strategy_version, "strategy_version")
        object.__setattr__(self, "occurred_at", _instant(self.occurred_at, "occurred_at"))
        if self.occurred_at < self.metadata.available_time:
            raise RecordError("occurred_at cannot precede available_time")
        _text(self.reason, "reason")
        object.__setattr__(self, "input_record_ids", _strings(self.input_record_ids, "input_record_ids"))


@dataclass(frozen=True)
class DeliveryRecord(Record):
    RECORD_TYPE: ClassVar[str] = "DeliveryRecord"
    candidate_id: str = ""
    attempted_at: datetime = None  # type: ignore[assignment]
    sink: str = ""
    status: str = ""
    message_reference: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _text(self.candidate_id, "candidate_id")
        if self.sink not in ("recording", "discord"):
            raise RecordError("delivery sink is not supported")
        if self.status not in DELIVERY_STATUSES:
            raise RecordError("delivery status is not supported")
        object.__setattr__(self, "attempted_at", _instant(self.attempted_at, "attempted_at"))
        if self.message_reference is not None:
            _text(self.message_reference, "message_reference")


@dataclass(frozen=True)
class HumanDecisionRecord(Record):
    RECORD_TYPE: ClassVar[str] = "HumanDecisionRecord"
    candidate_id: str = ""
    decided_at: datetime = None  # type: ignore[assignment]
    decision: str = ""
    note: str | None = None
    actual_manual_trade_price: float | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        _text(self.candidate_id, "candidate_id")
        object.__setattr__(self, "decided_at", _instant(self.decided_at, "decided_at"))
        if self.decision not in ("ACCEPTED", "REJECTED", "NO_DECISION"):
            raise RecordError("human decision is not supported")
        if self.note is not None and not isinstance(self.note, str):
            raise RecordError("note must be a string or null")
        value = _number(self.actual_manual_trade_price, "actual_manual_trade_price", optional=True)
        if value is not None and value <= 0:
            raise RecordError("actual_manual_trade_price must be positive")


@dataclass(frozen=True)
class SessionRecord(Record):
    RECORD_TYPE: ClassVar[str] = "SessionRecord"
    session: str = ""
    started_at: datetime = None  # type: ignore[assignment]
    config_version: str = ""
    config_hash: str = ""
    config_json: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        _session_date(self.session)
        object.__setattr__(self, "started_at", _instant(self.started_at, "started_at"))
        for name in ("config_version", "config_hash", "config_json"):
            _text(getattr(self, name), name)
        _config_hash(self.config_hash)
        try:
            config = TradeAlertsConfig(json.loads(self.config_json))
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            raise RecordError("config_json is not a valid trade-alert configuration") from exc
        if config.canonical_json != self.config_json:
            raise RecordError("config_json must be canonical")
        if config.config_version != self.config_version or config.config_hash != self.config_hash:
            raise RecordError("configuration version or hash does not match config_json")

    @classmethod
    def from_config(
        cls, *, record_id: str, session: str, started_at: datetime,
        config: TradeAlertsConfig,
    ) -> "SessionRecord":
        if not isinstance(config, TradeAlertsConfig):
            raise RecordError("config must be TradeAlertsConfig")
        return cls(
            record_id=record_id, session=session, started_at=started_at,
            config_version=config.config_version, config_hash=config.config_hash,
            config_json=config.canonical_json,
        )


_RECORD_TYPES: dict[str, type[Record]] = {
    record.RECORD_TYPE: record for record in (
        Bar, Quote, OptionQuote, CatalystEvent, FeatureSnapshot,
        StrategyStateTransition, AlertCandidate, OptionRecommendation,
        OutcomeRecord, SuppressionEvent, DeliveryRecord, HumanDecisionRecord,
        SessionRecord,
    )
}


def record_from_json(payload: str) -> Record:
    """Load one known versioned record and reject ambiguous input."""
    if not isinstance(payload, str):
        raise RecordError("payload must be a JSON string")
    try:
        values = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                RecordError("records cannot contain non-finite numbers")
            ),
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise RecordError("payload is not valid JSON") from exc
    if not isinstance(values, dict):
        raise RecordError("record must be a JSON object")
    record_type = values.pop("record_type", None)
    if not isinstance(record_type, str):
        raise RecordError("record_type is not supported")
    record_class = _RECORD_TYPES.get(record_type)
    if record_class is None:
        raise RecordError("record_type is not supported")
    if values.get("schema_version") != SCHEMA_VERSION:
        raise RecordError(f"schema_version must be {SCHEMA_VERSION}")
    return _construct(record_class, values)


__all__ = [
    "SCHEMA_VERSION", "RecordError", "SourceMetadata", "Bar", "Quote",
    "OptionQuote", "CatalystEvent", "FeatureValue", "FeatureSnapshot",
    "StrategyStateTransition", "RiskLevel", "TargetLevel",
    "ConfidenceComponent", "ConfidenceBreakdown", "ConfluenceLink", "AlertCandidate",
    "OptionRecommendation", "TargetOutcome", "OutcomeRecord", "SuppressionEvent",
    "DeliveryRecord", "HumanDecisionRecord", "SessionRecord",
    "record_from_json",
    "DATA_QUALITIES",
]
