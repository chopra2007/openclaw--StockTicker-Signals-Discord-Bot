"""D-090 five-minute opening range from supplied canonical Bar history.

This module performs no I/O and has no live consumer.  A complete result needs
all five scheduled opening minutes to be final and available, with at least one
traded interval.  Supplied records do not prove provider coverage.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from consensus_engine.historical_bars import HistoryBatch, HistoryRequest
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot,
    FeatureValue,
    RecordError,
    SourceMetadata,
)
from consensus_engine.utils.time_context import as_utc, session_bounds, session_date_at


FEATURE_VERSION = "D090_OPENING_RANGE_5M_V1"
_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_VALUE_SPECS = (
    ("OPENING_RANGE_HIGH_5M_V1", "USD_PER_SHARE"),
    ("OPENING_RANGE_LOW_5M_V1", "USD_PER_SHARE"),
    ("OPENING_RANGE_MID_5M_V1", "USD_PER_SHARE"),
    ("OPENING_RANGE_WIDTH_5M_V1", "USD_PER_SHARE"),
)
_COMPLETE_NAME = "OPENING_RANGE_COMPLETE_5M_V1"


def _missing_features(reason: str, ids: tuple[str, ...]) -> tuple[FeatureValue, ...]:
    values = tuple(FeatureValue(name, None, unit, reason, ids) for name, unit in _VALUE_SPECS)
    return (*values, FeatureValue(_COMPLETE_NAME, 0.0, "BOOLEAN", None, ids))


def build_opening_range_snapshot(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
) -> FeatureSnapshot:
    """Build the immutable first-five-minute range for one market session."""
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("opening range symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("opening range instrument type must be EQUITY or ETF")

    day = session_date_at(moment)
    bounds = session_bounds(day)
    reason: str | None = None
    ids: tuple[str, ...] = ()
    selected = ()

    if bounds is None:
        reason = "NO_REGULAR_SESSION"
    elif minute_history is None:
        reason = "MISSING_MINUTE_HISTORY"
    elif minute_history.request.symbol != symbol:
        reason = "INCOMPATIBLE_SYMBOL"
    elif minute_history.request.interval != "1m":
        reason = "INCOMPATIBLE_HISTORY_INTERVAL"
    elif minute_history.conventions.price != "USD_PER_SHARE":
        reason = "INCOMPATIBLE_PRICE_UNIT"
    elif minute_history.conventions.volume != "SHARES":
        reason = "INCOMPATIBLE_VOLUME_UNIT"
    elif any(
        value.strip().upper() in _UNKNOWN
        for value in (
            minute_history.source,
            minute_history.conventions.adjustment_basis,
            minute_history.conventions.coverage_basis,
        )
    ):
        reason = "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    else:
        opened = as_utc(bounds[0])
        request = HistoryRequest(symbol, opened, opened + timedelta(minutes=5))
        requested = set(minute_history.request.expected_intervals())
        opening_intervals = request.expected_intervals()
        if any(interval not in requested for interval in opening_intervals):
            reason = "OPENING_RANGE_NOT_REQUESTED"
        else:
            overlapping = tuple(
                bar
                for bar in minute_history.bars
                if bar.start_time < request.end and bar.end_time > request.start
            )
            opening_history = HistoryBatch(
                request, minute_history.source, minute_history.conventions, overlapping
            )
            coverage = opening_history.coverage_at(moment)
            ids = tuple(
                sorted(
                    {item.bar.record_id for item in coverage.intervals if item.bar is not None}
                    | set(coverage.unexpected_record_ids)
                )
            )
            statuses = [item.status for item in coverage.intervals]
            if coverage.unexpected_record_ids:
                reason = "UNEXPECTED_OVERLAPPING_RECORD"
            elif any(status not in ("FINAL", "NO_TRADE") for status in statuses):
                reason = "OPENING_RANGE_" + next(
                    status for status in statuses if status not in ("FINAL", "NO_TRADE")
                )
            else:
                selected = tuple(item.bar for item in coverage.intervals if item.bar is not None)
                types = {bar.metadata.instrument_type for bar in selected}
                if types != {instrument_type}:
                    reason = "INCOMPATIBLE_INSTRUMENT_TYPE"
                elif not any(not bar.certified_no_trade for bar in selected):
                    reason = "NO_TRADED_OPENING_RANGE_INTERVAL"

    metadata = SourceMetadata(
        instrument_id=symbol,
        instrument_type=instrument_type,
        source="DERIVED_D090",
        source_time=moment,
        received_time=moment,
        available_time=moment,
        normalized_time=moment,
        session=day.isoformat(),
        data_mode="SUPPLIED_BAR_OPENING_RANGE",
        quality="VALID",
    )
    if reason is not None:
        features = _missing_features(reason, ids)
    else:
        traded = tuple(bar for bar in selected if not bar.certified_no_trade)
        high = max(Decimal(str(bar.high)) for bar in traded)
        low = min(Decimal(str(bar.low)) for bar in traded)
        values = (high, low, (high + low) / Decimal(2), high - low)
        features = tuple(
            FeatureValue(name, float(value), unit, None, ids)
            for (name, unit), value in zip(_VALUE_SPECS, values)
        ) + (FeatureValue(_COMPLETE_NAME, 1.0, "BOOLEAN", None, ids),)
    return FeatureSnapshot(
        record_id=record_id,
        metadata=metadata,
        evaluated_at=moment,
        features=features,
        feature_version=FEATURE_VERSION,
        input_record_ids=ids,
    )


__all__ = ["FEATURE_VERSION", "build_opening_range_snapshot"]
