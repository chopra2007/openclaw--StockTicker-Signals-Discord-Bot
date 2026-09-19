"""Offline Databento OHLCV-1m source records and canonical Bar adapter.

This module accepts already-decoded records.  It does not open a retained file,
contact Databento, combine datasets, certify missing minutes, or decide whether
history is final or correction-complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata


SUPPORTED_DATASETS = frozenset({"XNYS.PILLAR", "EQUS.MINI"})
DATASET_IDENTITIES = {
    "XNYS.PILLAR": ("DIRECT_NYSE_INTEGRATED", "XNYS"),
    "EQUS.MINI": ("DERIVED_COMPONENT_VENUE_AGGREGATE", "ANONYMIZED"),
}
PRICE_SCALE = 1_000_000_000
_MINUTE = timedelta(minutes=1)
_PACIFIC = ZoneInfo("America/Los_Angeles")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{name} must be a non-empty string")
    return value


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RecordError(f"{name} must be a non-negative integer")
    return value


def _sha256(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise RecordError(f"{name} must be a lowercase SHA-256 value")
    return text


def _ns_instant(value: Any, name: str) -> datetime:
    nanoseconds = _count(value, name)
    seconds, remainder = divmod(nanoseconds, PRICE_SCALE)
    if remainder % 1_000:
        raise RecordError(f"{name} cannot be represented without losing nanoseconds")
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=remainder // 1_000)
    except (OverflowError, OSError, ValueError) as exc:
        raise RecordError(f"{name} is outside the supported timestamp range") from exc


def _fixed_price(value: Any, name: str) -> float:
    if type(value) is not int or value <= 0:
        raise RecordError(f"{name} must be a positive fixed-point integer")
    result = value / PRICE_SCALE
    if not math.isfinite(result):
        raise RecordError(f"{name} must be finite")
    return result


@dataclass(frozen=True)
class RetainedMinuteSource:
    """One immutable retained file and its inventory-only findings."""

    dataset: str
    file_name: str
    sha256: str
    bytes: int
    record_count: int
    symbols: tuple[str, ...]
    request_start: str
    request_end_exclusive: str
    metadata_start_ns: int
    metadata_end_ns: int
    calendar_sessions: int
    opening5_complete_identity_sessions: int
    opening15_complete_identity_sessions: int
    degraded_dates: tuple[str, ...]
    has_opening_gaps: bool
    original_availability: str = "UNKNOWN"
    finality: str = "UNKNOWN"
    correction_state: str = "UNKNOWN"
    adjustment_basis: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.dataset not in SUPPORTED_DATASETS:
            raise RecordError("retained dataset is unsupported")
        _text(self.file_name, "file_name")
        _sha256(self.sha256, "sha256")
        for name in (
            "bytes", "record_count", "metadata_start_ns", "metadata_end_ns",
            "calendar_sessions", "opening5_complete_identity_sessions",
            "opening15_complete_identity_sessions",
        ):
            _count(getattr(self, name), name)
        if self.metadata_start_ns >= self.metadata_end_ns:
            raise RecordError("metadata range must be increasing")
        if not isinstance(self.symbols, tuple) or len(set(self.symbols)) != len(self.symbols):
            raise RecordError("symbols must be a unique tuple")
        for symbol in self.symbols:
            _text(symbol, "symbol")
        if not isinstance(self.degraded_dates, tuple):
            raise RecordError("degraded_dates must be a tuple")
        if type(self.has_opening_gaps) is not bool:
            raise RecordError("has_opening_gaps must be true or false")
        for name in ("original_availability", "finality", "correction_state", "adjustment_basis"):
            if getattr(self, name) != "UNKNOWN":
                raise RecordError(f"{name} must remain UNKNOWN without source proof")

    def as_dict(self) -> dict[str, Any]:
        publisher, venue = DATASET_IDENTITIES[self.dataset]
        return {
            "dataset": self.dataset,
            "publisher_identity": publisher,
            "venue_identity": venue,
            "file_name": self.file_name,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "record_count": self.record_count,
            "symbols": list(self.symbols),
            "request_start": self.request_start,
            "request_end_exclusive": self.request_end_exclusive,
            "metadata_start_ns": self.metadata_start_ns,
            "metadata_end_ns": self.metadata_end_ns,
            "calendar_sessions": self.calendar_sessions,
            "opening5_complete_identity_sessions": self.opening5_complete_identity_sessions,
            "opening15_complete_identity_sessions": self.opening15_complete_identity_sessions,
            "degraded_dates": list(self.degraded_dates),
            "has_opening_gaps": self.has_opening_gaps,
            "original_availability": self.original_availability,
            "finality": self.finality,
            "correction_state": self.correction_state,
            "adjustment_basis": self.adjustment_basis,
        }


@dataclass(frozen=True)
class DatabentoMinuteContext:
    dataset: str
    raw_symbol: str
    instrument_id: int
    session: str
    received_time: datetime
    available_time: datetime
    normalized_time: datetime
    source_file_sha256: str
    provider_condition: str
    instrument_type: str = "ETF"

    def __post_init__(self) -> None:
        if self.instrument_type not in ("ETF", "EQUITY"):
            raise RecordError("instrument_type must be ETF or EQUITY")
        if self.dataset not in SUPPORTED_DATASETS:
            raise RecordError("Databento dataset is unsupported")
        _text(self.raw_symbol, "raw_symbol")
        _count(self.instrument_id, "instrument_id")
        _sha256(self.source_file_sha256, "source_file_sha256")
        if self.provider_condition not in ("AVAILABLE", "DEGRADED"):
            raise RecordError("provider_condition must be AVAILABLE or DEGRADED")
        for name in ("received_time", "available_time", "normalized_time"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise RecordError(f"{name} must include a timezone")


@dataclass(frozen=True)
class DatabentoMinuteRecord:
    """Canonical bar plus facts that the common Bar cannot represent."""

    dataset: str
    publisher_identity: str
    venue_identity: str
    raw_publisher_id: int
    raw_instrument_id: int
    raw_ts_event_ns: int
    provider_condition: str
    source_file_sha256: str
    original_availability: str
    finality: str
    correction_state: str
    bar: Bar

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "publisher_identity": self.publisher_identity,
            "venue_identity": self.venue_identity,
            "raw_publisher_id": self.raw_publisher_id,
            "raw_instrument_id": self.raw_instrument_id,
            "raw_ts_event_ns": self.raw_ts_event_ns,
            "provider_condition": self.provider_condition,
            "source_file_sha256": self.source_file_sha256,
            "original_availability": self.original_availability,
            "finality": self.finality,
            "correction_state": self.correction_state,
            "bar": self.bar.as_dict(),
        }


def normalize_databento_ohlcv_1m(
    row: Mapping[str, Any], *, record_id: str, context: DatabentoMinuteContext,
) -> DatabentoMinuteRecord:
    """Convert one supplied DBN OHLCV-1m row without claiming file coverage."""
    if not isinstance(row, Mapping):
        raise RecordError("Databento row must be an object")
    if set(row) != {
        "publisher_id", "instrument_id", "ts_event", "open", "high", "low", "close", "volume",
    }:
        raise RecordError("Databento row fields do not match the offline OHLCV-1m contract")
    publisher_id = _count(row["publisher_id"], "publisher_id")
    instrument_id = _count(row["instrument_id"], "instrument_id")
    if instrument_id != context.instrument_id:
        raise RecordError("Databento row identity does not match caller context")
    raw_ts_event_ns = _count(row["ts_event"], "ts_event")
    start = _ns_instant(raw_ts_event_ns, "ts_event")
    if start.second or start.microsecond:
        raise RecordError("Databento OHLCV-1m event time must align to a minute")
    if start.astimezone(_PACIFIC).date().isoformat() != context.session:
        raise RecordError("Databento event time does not match caller session")
    if context.received_time > context.available_time or context.available_time > context.normalized_time:
        raise RecordError("Databento observation times are out of order")
    if context.received_time < start:
        raise RecordError("Databento receipt cannot precede its event time")
    quality = "DEGRADED_PROXY" if context.provider_condition == "DEGRADED" else "UNKNOWN"
    metadata = SourceMetadata(
        instrument_id=context.raw_symbol,
        instrument_type=context.instrument_type,
        source=context.dataset,
        source_time=start,
        received_time=context.received_time,
        available_time=context.available_time,
        normalized_time=context.normalized_time,
        session=context.session,
        sequence=None,
        revision=0,
        data_mode="RETAINED_DBN_OHLCV_1M",
        quality=quality,
    )
    bar = Bar(
        record_id=record_id,
        metadata=metadata,
        start_time=start,
        end_time=start + _MINUTE,
        is_final=False,
        open=_fixed_price(row["open"], "open"),
        high=_fixed_price(row["high"], "high"),
        low=_fixed_price(row["low"], "low"),
        close=_fixed_price(row["close"], "close"),
        volume=_count(row["volume"], "volume"),
        adjustment_basis="UNKNOWN",
        price_convention="DATABENTO_FIXED_1E9_REPORTED",
        volume_convention="DATABENTO_REPORTED_UNITS_UNKNOWN",
        certified_no_trade=False,
    )
    publisher, venue = DATASET_IDENTITIES[context.dataset]
    return DatabentoMinuteRecord(
        dataset=context.dataset,
        publisher_identity=publisher,
        venue_identity=venue,
        raw_publisher_id=publisher_id,
        raw_instrument_id=instrument_id,
        raw_ts_event_ns=raw_ts_event_ns,
        provider_condition=context.provider_condition,
        source_file_sha256=context.source_file_sha256,
        original_availability="UNKNOWN",
        finality="UNKNOWN",
        correction_state="UNKNOWN",
        bar=bar,
    )
