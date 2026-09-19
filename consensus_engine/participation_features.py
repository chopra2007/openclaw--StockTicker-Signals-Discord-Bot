"""D-090 participation features from supplied, available-time-safe Bar histories.

No I/O, live consumer or strategy threshold lives here. Opening and premarket
windows stay fixed; each returned snapshot freezes its selected input revisions.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import lru_cache
import math

from consensus_engine.historical_bars import BarInterval, HistoryBatch, HistoryRequest
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, SourceMetadata,
)
from consensus_engine.utils.time_context import (
    as_utc, premarket_bounds, session_bounds, session_date_at, session_dates,
)


FEATURE_VERSION = "D090_PARTICIPATION_FEATURES_V1"
_PM_START = time(1)
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}


@lru_cache(maxsize=32)
def _windows(symbol: str, day: date, kind: str) -> tuple[tuple[BarInterval, ...], ...]:
    """Select the required calendar windows before inspecting any observations."""
    prior = session_dates(day - timedelta(days=60), day - timedelta(days=1))[-20:]
    if len(prior) != 20 or session_bounds(day) is None:
        return ()
    days = prior if kind == "daily" else [*prior, day]
    windows = []
    for reference_day in days:
        opened, closed = map(as_utc, session_bounds(reference_day))
        if kind == "premarket":
            start, end = premarket_bounds(reference_day, _PM_START)
            request = HistoryRequest(symbol, start, end, session_scope="PREMARKET",
                                     premarket_start=_PM_START)
        elif kind == "opening":
            request = HistoryRequest(symbol, opened, opened + timedelta(minutes=5))
        else:
            request = HistoryRequest(symbol, opened, closed, interval="1d")
        windows.append(request.expected_intervals())
    return tuple(windows)


def _selected_bars(batch: HistoryBatch, required: tuple[BarInterval, ...],
                   moment: datetime):
    """Keep overlapping malformed inputs; ignore unrelated and future facts."""
    ends = [interval.end for interval in required]
    selected = []
    for bar in batch.bars:
        if bar.metadata.available_time > moment:
            continue
        index = bisect_right(ends, bar.start_time)
        if index < len(required) and required[index].start < bar.end_time:
            selected.append(bar)
    return tuple(selected)


def _calculate(*, batch: HistoryBatch | None, symbol: str, instrument_type: str,
               moment: datetime, kind: str, name: str, unit: str) -> FeatureValue:
    ids: tuple[str, ...] = ()

    def missing(reason: str) -> FeatureValue:
        return FeatureValue(name, None, unit, reason, ids)

    if batch is None:
        return missing("MISSING_" + kind.upper() + "_HISTORY")
    windows = _windows(symbol, session_date_at(moment), kind)
    if not windows:
        return missing("NO_CURRENT_SESSION_OR_20_REFERENCE_SESSIONS")
    if batch.request.symbol != symbol:
        return missing("INCOMPATIBLE_SYMBOL")
    expected_interval = "1d" if kind == "daily" else "1m"
    if batch.request.interval != expected_interval:
        return missing("INCOMPATIBLE_HISTORY_INTERVAL")
    if batch.conventions.volume != "SHARES":
        return missing("INCOMPATIBLE_VOLUME_UNIT")
    if kind == "daily" and batch.conventions.price != "USD_PER_SHARE":
        return missing("INCOMPATIBLE_PRICE_UNIT")
    if kind == "premarket" and batch.request.premarket_start != _PM_START:
        return missing("INCOMPATIBLE_PREMARKET_START")

    required = tuple(interval for window in windows for interval in window)
    # Restrict observations, not requested coverage. A truncated request cannot
    # manufacture missing scheduled slots, and off-window modes cannot leak in.
    bars = _selected_bars(batch, required, moment)
    selected = HistoryBatch(batch.request, batch.source, batch.conventions, bars)
    coverage = selected.coverage_at(moment)
    by_interval = {item.interval: item for item in coverage.intervals}
    items = [by_interval.get(interval) for interval in required]
    ids = tuple(sorted({item.bar.record_id for item in items
                        if item is not None and item.bar is not None}
                       | set(coverage.unexpected_record_ids)))
    if coverage.unexpected_record_ids:
        return missing("UNEXPECTED_OVERLAPPING_RECORD")
    for interval, item in zip(required, items):
        if item is None or item.status not in ("FINAL", "NO_TRADE"):
            status = item.status if item is not None else "NOT_REQUESTED"
            role = "CURRENT" if interval.session == session_date_at(moment).isoformat() else "REFERENCE"
            return missing(role + "_WINDOW_" + status)
    usable = [item.bar for item in items]
    if any(bar.metadata.instrument_type != instrument_type for bar in usable):
        return missing("INCOMPATIBLE_INSTRUMENT_TYPE")
    modes = {bar.metadata.data_mode for bar in usable}
    if len(modes) != 1 or any(mode.strip().upper() in _UNKNOWN for mode in modes):
        return missing("INCOMPATIBLE_MODE")

    if kind == "daily":
        if any(bar.close is None for bar in usable):
            return missing("MISSING_REGULAR_SESSION_CLOSE")
        dollars = sorted(Decimal(str(bar.close)) * Decimal(str(bar.volume)) for bar in usable)
        result = (dollars[9] + dollars[10]) / Decimal(2)
    else:
        volumes = []
        offset = 0
        for window in windows:
            volumes.append(sum((Decimal(str(bar.volume))
                                for bar in usable[offset:offset + len(window)]), Decimal(0)))
            offset += len(window)
        reference_sum = sum(volumes[:20], Decimal(0))
        if reference_sum <= 0:
            return missing("ZERO_REFERENCE_VOLUME")
        result = volumes[20] * Decimal(20) / reference_sum
    value = float(result)
    if not math.isfinite(value):
        return missing("NONFINITE_RESULT")
    return FeatureValue(name, value, unit, None, ids)


def build_participation_snapshot(*, record_id: str, evaluated_at: datetime,
                                 symbol: str, instrument_type: str,
                                 opening_history: HistoryBatch | None,
                                 premarket_history: HistoryBatch | None,
                                 daily_history: HistoryBatch | None) -> FeatureSnapshot:
    """Build the three approved F-02 participation values, independently.

    Opening/premarket ratios need their complete current window and exactly the
    20 prior scheduled sessions. Dollar volume uses only those prior daily bars.
    The explicit instrument scope cannot be inferred from a future revision.
    Missing values retain reasons; input IDs link to original source/basis facts.
    Returning a number does not certify the supplied source's actual coverage.
    """
    moment = as_utc(evaluated_at)
    if instrument_type not in ("EQUITY", "ETF"):
        raise RecordError("participation instrument type must be EQUITY or ETF")
    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_D090",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=session_date_at(moment).isoformat(),
        data_mode="SUPPLIED_BAR_PARTICIPATION_WITH_CLOSE_DOLLAR_PROXY", quality="VALID",
    )
    specs = (
        (opening_history, "opening", "RVOL_OPEN5_MEAN20_V1", "RATIO"),
        (premarket_history, "premarket", "PM_RVOL_MEAN20_V1", "RATIO"),
        (daily_history, "daily", "DOLLAR_VOLUME_CLOSE_PROXY20_V1", "USD"),
    )
    features = tuple(_calculate(batch=batch, symbol=symbol, instrument_type=instrument_type,
                                moment=moment, kind=kind, name=name, unit=unit)
                     for batch, kind, name, unit in specs)
    ids = tuple(sorted({record for feature in features for record in feature.input_record_ids}))
    return FeatureSnapshot(record_id=record_id, metadata=metadata, evaluated_at=moment,
                           features=features, feature_version=FEATURE_VERSION,
                           input_record_ids=ids)


__all__ = ["FEATURE_VERSION", "build_participation_snapshot"]
