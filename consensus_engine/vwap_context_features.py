"""Frozen supplied-input VWAP context calculations for M3.4.

This module performs no I/O.  It combines accepted canonical minute bars, M3.1
core-price snapshots and one supplied current-price observation.  Missing or
incompatible inputs remain unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import math

from .core_price_features import FEATURE_VERSION as CORE_FEATURE_VERSION
from .historical_bars import HistoryBatch, HistoryRequest
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at


FEATURE_VERSION = "M34_VWAP_CONTEXT_V1"
DATA_MODE = "SUPPLIED_BAR_HLC3_VWAP_CONTEXT"
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_VWAP = "SESSION_VWAP_BAR_HLC3_V1"
_ATR = "ATR_1M_20_SMA_V1"


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or value.strip().upper() in _UNKNOWN:
        raise RecordError(f"{name} must be explicit")
    return value


@dataclass(frozen=True)
class CurrentPriceObservation:
    """One supplied eligible regular-session price and its availability."""

    record_id: str
    symbol: str
    instrument_type: str
    session: str
    observed_at: datetime
    available_at: datetime
    price: float
    source: str
    adjustment_basis: str
    coverage_basis: str
    price_convention: str = "USD_PER_SHARE"

    def __post_init__(self) -> None:
        for name in ("record_id", "symbol", "session", "source", "adjustment_basis",
                     "coverage_basis", "price_convention"):
            _text(getattr(self, name), name)
        if self.instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("current-price instrument type must be EQUITY or ETF")
        observed = _instant(self.observed_at, "observed_at")
        available = _instant(self.available_at, "available_at")
        if available < observed:
            raise RecordError("current price cannot be available before observation")
        if (isinstance(self.price, bool) or not isinstance(self.price, (int, float))
                or not math.isfinite(self.price) or self.price <= 0):
            raise RecordError("current price must be finite and positive")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)


def _feature(name: str, value: Decimal | int | None, unit: str, reason: str | None,
             ids: tuple[str, ...]) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason,
                        tuple(sorted(set(ids))))


def _values(snapshot: FeatureSnapshot) -> dict[str, FeatureValue]:
    return {item.name: item for item in snapshot.features}


def _snapshot_reason(snapshot: FeatureSnapshot, symbol: str, instrument_type: str,
                     session: str, moment: datetime) -> str | None:
    if snapshot.feature_version != CORE_FEATURE_VERSION:
        return "INCOMPATIBLE_CORE_FEATURE_VERSION"
    if snapshot.metadata.instrument_id != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if snapshot.metadata.instrument_type != instrument_type:
        return "INCOMPATIBLE_INSTRUMENT_TYPE"
    if snapshot.metadata.session != session:
        return "INCOMPATIBLE_SESSION"
    if (snapshot.metadata.source != "DERIVED_D090"
            or snapshot.metadata.data_mode != "BAR_HLC3_WITH_EXPLICIT_OPEN"
            or snapshot.metadata.quality != "VALID"):
        return "INCOMPATIBLE_CORE_DATA_MODE"
    if snapshot.evaluated_at > moment or snapshot.metadata.available_time > moment:
        return "CORE_SNAPSHOT_NOT_YET_AVAILABLE"
    return None


def _history_reason(batch: HistoryBatch, symbol: str, instrument_type: str,
                    moment: datetime) -> str | None:
    if batch.request.symbol != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if batch.request.interval != "1m" or batch.request.session_scope != "REGULAR":
        return "INCOMPATIBLE_HISTORY_WINDOW"
    conventions = batch.conventions
    if conventions.price != "USD_PER_SHARE" or conventions.volume != "SHARES":
        return "INCOMPATIBLE_HISTORY_UNITS"
    if conventions.timestamp == "UNKNOWN" or conventions.session != "REGULAR":
        return "INCOMPATIBLE_HISTORY_WINDOW"
    if any(value.strip().upper() in _UNKNOWN for value in (
            batch.source, conventions.adjustment_basis, conventions.coverage_basis,
            conventions.finality, conventions.publication,
            conventions.evidence_reference or "")):
        return "UNKNOWN_HISTORY_BASIS"
    types = {item.bar.metadata.instrument_type for item in batch.coverage_at(moment).intervals
             if item.bar is not None}
    if types and types != {instrument_type}:
        return "INCOMPATIBLE_INSTRUMENT_TYPE"
    return None


def _price_basis_reason(price: CurrentPriceObservation, batch: HistoryBatch, symbol: str,
                        instrument_type: str, session: str) -> str | None:
    if price.symbol != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if price.instrument_type != instrument_type:
        return "INCOMPATIBLE_INSTRUMENT_TYPE"
    if price.session != session:
        return "INCOMPATIBLE_SESSION"
    if price.price_convention != batch.conventions.price:
        return "INCOMPATIBLE_PRICE_UNIT"
    if (price.source != batch.source
            or price.adjustment_basis != batch.conventions.adjustment_basis
            or price.coverage_basis != batch.conventions.coverage_basis):
        return "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"
    return None


def _price_reason(price: CurrentPriceObservation, batch: HistoryBatch, symbol: str,
                  instrument_type: str, session: str, moment: datetime) -> str | None:
    basis_reason = _price_basis_reason(price, batch, symbol, instrument_type, session)
    if basis_reason:
        return basis_reason
    if price.available_at > moment:
        return "CURRENT_PRICE_NOT_YET_AVAILABLE"
    if price.observed_at > moment:
        return "FUTURE_CURRENT_PRICE"
    if moment - price.observed_at > timedelta(seconds=3):
        return "STALE_CURRENT_PRICE"
    bounds = session_bounds(session_date_at(moment))
    if bounds is None or not as_utc(bounds[0]) <= price.observed_at < as_utc(bounds[1]):
        return "PRICE_OUTSIDE_REGULAR_SESSION"
    return None


def _cross_count(batch: HistoryBatch, snapshots: dict[datetime, FeatureSnapshot],
                 symbol: str, instrument_type: str, session: str, moment: datetime,
                 common_reason: str | None):
    if common_reason:
        return None, common_reason, ()
    bounds = session_bounds(session_date_at(moment))
    if bounds is None:
        return None, "NO_REGULAR_SESSION", ()
    opened = as_utc(bounds[0])
    latest_end = min(moment.replace(second=0, microsecond=0), as_utc(bounds[1]))
    if latest_end <= opened:
        return None, "NO_COMPLETED_REGULAR_MINUTE", ()
    required = HistoryRequest(symbol, opened, latest_end).expected_intervals()
    coverage = batch.coverage_at(moment)
    by_interval = {item.interval: item for item in coverage.intervals}
    items = [by_interval.get(interval) for interval in required]
    ids: set[str] = set()
    if any(item is None for item in items):
        return None, "VWAP_CROSS_WINDOW_NOT_REQUESTED", ()
    sides: list[int | None] = []
    for item in items:
        if item.bar is not None:
            ids.add(item.bar.record_id)
        if item.status not in ("FINAL", "NO_TRADE"):
            return None, "VWAP_CROSS_WINDOW_" + item.status, tuple(ids)
        if item.status == "NO_TRADE":
            sides.append(None)
            continue
        core = snapshots.get(item.interval.end)
        if core is None:
            return None, "MISSING_INTERVAL_VWAP", tuple(ids)
        reason = _snapshot_reason(core, symbol, instrument_type, session, moment)
        ids.add(core.record_id)
        if reason:
            return None, reason, tuple(ids)
        vwap = _values(core).get(_VWAP)
        if vwap is None:
            return None, "MISSING_INTERVAL_VWAP_FEATURE", tuple(ids)
        ids.update(vwap.input_record_ids)
        if vwap.value is None:
            return None, vwap.missing_reason, tuple(ids)
        if vwap.unit != "USD_PER_SHARE":
            return None, "INCOMPATIBLE_VWAP_UNIT", tuple(ids)
        close = Decimal(str(item.bar.close))
        level = Decimal(str(vwap.value))
        sides.append(1 if close > level else -1 if close < level else None)
    count = sum(left is not None and right is not None and left != right
                for left, right in zip(sides, sides[1:]))
    return count, None, tuple(ids)


def build_vwap_context_snapshot(
    *, record_id: str, evaluated_at: datetime, symbol: str, instrument_type: str,
    minute_history: HistoryBatch, core_snapshots: tuple[FeatureSnapshot, ...],
    current_price: CurrentPriceObservation,
) -> FeatureSnapshot:
    """Build slope, distance, cross-count and side facts from supplied records."""
    _text(record_id, "record_id")
    _text(symbol, "symbol")
    if instrument_type not in ("EQUITY", "ETF"):
        raise RecordError("VWAP-context instrument type must be EQUITY or ETF")
    moment = _instant(evaluated_at, "evaluated_at")
    if not isinstance(minute_history, HistoryBatch):
        raise RecordError("minute_history must be a HistoryBatch")
    if (not isinstance(core_snapshots, tuple)
            or any(not isinstance(item, FeatureSnapshot) for item in core_snapshots)):
        raise RecordError("core_snapshots must be a tuple of FeatureSnapshot")
    if not isinstance(current_price, CurrentPriceObservation):
        raise RecordError("current_price must be a CurrentPriceObservation")
    indexed: dict[datetime, FeatureSnapshot] = {}
    for snapshot in core_snapshots:
        if snapshot.evaluated_at in indexed:
            raise RecordError("core snapshots must have unique evaluation times")
        indexed[snapshot.evaluated_at] = snapshot

    session = session_date_at(moment).isoformat()
    history_reason = _history_reason(minute_history, symbol, instrument_type, moment)
    current = indexed.get(moment)
    current_reason = "MISSING_CURRENT_CORE_SNAPSHOT"
    if current is not None:
        current_reason = _snapshot_reason(current, symbol, instrument_type, session, moment)
    current_values = _values(current) if current is not None and current_reason is None else {}
    vwap = current_values.get(_VWAP)
    atr = current_values.get(_ATR)
    vwap_reason = current_reason or ("MISSING_CURRENT_VWAP_FEATURE" if vwap is None else
                                    vwap.missing_reason or (
                                        "INCOMPATIBLE_VWAP_UNIT"
                                        if vwap.unit != "USD_PER_SHARE" else None))
    atr_reason = current_reason or ("MISSING_CURRENT_ATR_FEATURE" if atr is None else
                                    atr.missing_reason or (
                                        "INCOMPATIBLE_ATR_UNIT"
                                        if atr.unit != "USD_PER_SHARE" else None))
    current_ids = () if current is None else (current.record_id,)
    vwap_ids = current_ids + (() if vwap is None else vwap.input_record_ids)
    atr_ids = current_ids + (() if atr is None else atr.input_record_ids)

    earlier = indexed.get(moment - timedelta(seconds=180))
    earlier_reason = "MISSING_THREE_MINUTE_CORE_SNAPSHOT"
    if earlier is not None:
        earlier_reason = _snapshot_reason(earlier, symbol, instrument_type, session, moment)
    earlier_vwap = _values(earlier).get(_VWAP) if earlier is not None and earlier_reason is None else None
    if earlier_vwap is None and earlier_reason is None:
        earlier_reason = "MISSING_THREE_MINUTE_VWAP_FEATURE"
    elif earlier_vwap is not None and earlier_vwap.value is None:
        earlier_reason = earlier_vwap.missing_reason
    elif earlier_vwap is not None and earlier_vwap.unit != "USD_PER_SHARE":
        earlier_reason = "INCOMPATIBLE_VWAP_UNIT"
    slope_ids = vwap_ids + atr_ids
    if earlier is not None:
        slope_ids += (earlier.record_id,)
    if earlier_vwap is not None:
        slope_ids += earlier_vwap.input_record_ids
    basis_reason = _price_basis_reason(
        current_price, minute_history, symbol, instrument_type, session)
    if history_reason:
        slope = (None, history_reason)
    elif basis_reason:
        slope = (None, basis_reason)
    elif vwap_reason:
        slope = (None, vwap_reason)
    elif atr_reason:
        slope = (None, atr_reason)
    elif earlier_reason:
        slope = (None, earlier_reason)
    elif atr.value <= 0:
        slope = (None, "NONPOSITIVE_MINUTE_ATR")
    else:
        slope = ((Decimal(str(vwap.value)) - Decimal(str(earlier_vwap.value)))
                 / Decimal(str(atr.value)), None)

    price_reason = _price_reason(current_price, minute_history, symbol, instrument_type,
                                 session, moment)
    distance_ids = vwap_ids + (current_price.record_id,)
    if history_reason:
        distance = (None, history_reason)
    elif vwap_reason:
        distance = (None, vwap_reason)
    elif price_reason:
        distance = (None, price_reason)
    else:
        distance = (Decimal(str(current_price.price)) - Decimal(str(vwap.value)), None)
    if distance[0] is None:
        normalized = (None, distance[1])
        side = (None, distance[1])
    elif atr_reason:
        normalized = (None, atr_reason)
        side = (1 if distance[0] > 0 else -1 if distance[0] < 0 else 0, None)
    elif atr.value <= 0:
        normalized = (None, "NONPOSITIVE_MINUTE_ATR")
        side = (1 if distance[0] > 0 else -1 if distance[0] < 0 else 0, None)
    else:
        normalized = (distance[0] / Decimal(str(atr.value)), None)
        side = (1 if distance[0] > 0 else -1 if distance[0] < 0 else 0, None)

    crosses = _cross_count(minute_history, indexed, symbol, instrument_type, session,
                           moment, history_reason or basis_reason)
    specs = (
        ("VWAP_SLOPE_3M_ATR_V1", slope, "ATR_MULTIPLE", slope_ids),
        ("PRICE_TO_VWAP_DISTANCE_V1", distance, "USD_PER_SHARE", distance_ids),
        ("PRICE_TO_VWAP_DISTANCE_ATR_V1", normalized, "ATR_MULTIPLE", distance_ids + atr_ids),
        ("VWAP_CLOSE_CROSSES_V1", crosses[:2], "COUNT", crosses[2]),
        ("PRICE_VWAP_SIDE_V1", side, "SIGNED_SIDE", distance_ids),
        ("PRICE_ABOVE_VWAP_V1", (None, side[1]) if side[0] is None else (int(side[0] == 1), None),
         "BOOLEAN", distance_ids),
        ("PRICE_BELOW_VWAP_V1", (None, side[1]) if side[0] is None else (int(side[0] == -1), None),
         "BOOLEAN", distance_ids),
    )
    features = tuple(_feature(name, result[0], unit, result[1], ids)
                     for name, result, unit, ids in specs)
    input_ids = tuple(sorted({item for feature in features for item in feature.input_record_ids}))
    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_M34",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=session, data_mode=DATA_MODE, quality="VALID",
    )
    return FeatureSnapshot(record_id=record_id, metadata=metadata, evaluated_at=moment,
                           features=features, feature_version=FEATURE_VERSION,
                           input_record_ids=input_ids)


__all__ = ["CurrentPriceObservation", "DATA_MODE", "FEATURE_VERSION",
           "build_vwap_context_snapshot"]
