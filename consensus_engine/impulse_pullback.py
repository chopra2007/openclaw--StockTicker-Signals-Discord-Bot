"""M8.3 point-in-time impulse and pullback measurement for `FIRST_PULLBACK_VWAP`.

The caller supplies every canonical record, the evaluation instant, the frozen
impulse window and its own definition. This module measures; it decides nothing.
It adopts no impulse minimum, no retracement band, no volume-contraction ratio,
no VWAP distance and no arming rule: those `FIRST_PULLBACK_VWAP` numbers stay
unresolved under PLAYBOOKS sections 6 and 17 and M0.3, and M0.3B is still
PROPOSED. Supplying a window neither approves a proposed rule nor proves a
provider covers these minutes.

The impulse origin and extreme are frozen over the supplied window and never read
a bar that ended after it, so a later high or low cannot leak backwards into an
earlier evaluation. The pullback is measured over the completed minutes since
that freeze. Any missing, unexpected, provisional or untraded interval keeps its
own value unavailable with a named reason; it never becomes a number.

Whether the impulse extreme printed after its origin, how deep the pullback ran
and where each extreme sits against the supplied VWAP are reported as measured,
including a negative retracement, because which of them is a valid first pullback
is the unresolved definition's answer, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math

from consensus_engine.historical_bars import HistoryBatch, HistoryCoverage
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot,
    FeatureValue,
    RecordError,
    SourceMetadata,
)
from consensus_engine.utils.time_context import as_utc, session_bounds, session_date_at


FEATURE_VERSION = "M83_IMPULSE_PULLBACK_V1"
DATA_MODE = "SUPPLIED_BAR_IMPULSE_PULLBACK"
_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_DIRECTIONS = ("LONG", "SHORT")
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_READY = ("FINAL", "NO_TRADE")

IMPULSE_SPECS = (
    ("IMPULSE_ORIGIN_V1", "USD_PER_SHARE"),
    ("IMPULSE_EXTREME_V1", "USD_PER_SHARE"),
    ("IMPULSE_DISTANCE_V1", "USD_PER_SHARE"),
    ("IMPULSE_BAR_COUNT_V1", "COUNT"),
)
IMPULSE_VOLUME_NAME = "IMPULSE_VOLUME_V1"
IMPULSE_COMPLETE_NAME = "IMPULSE_COMPLETE_V1"
IMPULSE_ORDERED_NAME = "IMPULSE_EXTREME_AFTER_ORIGIN_V1"

PULLBACK_SPECS = (
    ("PULLBACK_EXTREME_V1", "USD_PER_SHARE"),
    ("PULLBACK_BAR_COUNT_V1", "COUNT"),
    ("REVERSAL_BAR_HIGH_V1", "USD_PER_SHARE"),
    ("REVERSAL_BAR_LOW_V1", "USD_PER_SHARE"),
)
PULLBACK_VOLUME_NAME = "PULLBACK_VOLUME_V1"
PULLBACK_COMPLETE_NAME = "PULLBACK_COMPLETE_V1"
DEPTH_NAME = "PULLBACK_DEPTH_V1"
RETRACEMENT_NAME = "PULLBACK_RETRACEMENT_V1"
VOLUME_RATIO_NAME = "PULLBACK_VOLUME_RATIO_V1"

IMPULSE_DISTANCE_ATR_NAME = "IMPULSE_DISTANCE_ATR_V1"
VWAP_SPECS = (
    ("IMPULSE_EXTREME_FROM_VWAP_ATR_V1", "RATIO"),
    ("PULLBACK_EXTREME_FROM_VWAP_ATR_V1", "RATIO"),
)

FEATURE_NAMES = (
    *(name for name, _ in IMPULSE_SPECS),
    IMPULSE_VOLUME_NAME,
    IMPULSE_ORDERED_NAME,
    IMPULSE_COMPLETE_NAME,
    *(name for name, _ in PULLBACK_SPECS),
    PULLBACK_VOLUME_NAME,
    PULLBACK_COMPLETE_NAME,
    DEPTH_NAME,
    RETRACEMENT_NAME,
    VOLUME_RATIO_NAME,
    IMPULSE_DISTANCE_ATR_NAME,
    *(name for name, _ in VWAP_SPECS),
)


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in _UNKNOWN):
        raise RecordError(f"{name} must be explicit")
    return value


@dataclass(frozen=True)
class PullbackPolicy:
    """The caller's own impulse and pullback definition; nothing here is defaulted.

    PLAYBOOKS section 17 still owns how an impulse and a reversal bar are
    defined, how a pullback is counted and whether the legs are read from the bar
    extremes or from the closes, so the direction, the minimum pullback length
    and the reading convention all arrive from the caller with its own definition
    reference.
    """

    version: str
    definition_reference: str
    direction: str
    min_pullback_bars: int
    measure_from_close: bool

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        if self.direction not in _DIRECTIONS:
            raise RecordError("policy direction must be LONG or SHORT")
        if type(self.min_pullback_bars) is not int or self.min_pullback_bars < 1:
            raise RecordError("min_pullback_bars must be a positive integer count")
        if type(self.measure_from_close) is not bool:
            raise RecordError("measure_from_close must be true or false")

    @property
    def long(self) -> bool:
        """Whether the supplied impulse direction reads upward."""
        return self.direction == "LONG"


def _value(name: str, value: Decimal | int | None, unit: str, reason: str | None,
           ids: tuple[str, ...]) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason, ids)


def _missing(specs, reason: str, ids: tuple[str, ...]) -> tuple[FeatureValue, ...]:
    return tuple(_value(name, None, unit, reason, ids) for name, unit in specs)


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


def _session_items(coverage: HistoryCoverage, day: str, start: datetime, end: datetime):
    return [item for item in coverage.intervals
            if item.interval.session == day
            and item.interval.start >= start and item.interval.end <= end]


def _contiguous(items) -> bool:
    return all(later.interval.start == earlier.interval.end
               for earlier, later in zip(items, items[1:]))


def _status_reason(prefix: str, items) -> str | None:
    blocking = [item.status for item in items if item.status not in _READY]
    return prefix + "_" + blocking[0] if blocking else None


def _usable(batch: HistoryBatch, coverage: HistoryCoverage, selected, prefix: str,
            instrument_type: str):
    """The shared readiness checks both legs apply to their own selected minutes."""
    status = _status_reason(prefix, selected)
    if status is not None:
        return None, status
    if _unexpected_over(batch, coverage, selected):
        return None, "UNEXPECTED_OVERLAPPING_RECORD"
    bars = [item.bar for item in selected]
    if any(bar.certified_no_trade for bar in bars):
        return None, f"NO_TRADED_{prefix}_INTERVAL"
    if {bar.metadata.instrument_type for bar in bars} != {instrument_type}:
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE"
    return bars, None


def _highs(bars, from_close: bool) -> list[Decimal]:
    return [Decimal(str(bar.close if from_close else bar.high)) for bar in bars]


def _lows(bars, from_close: bool) -> list[Decimal]:
    return [Decimal(str(bar.close if from_close else bar.low)) for bar in bars]


def _volume(bars) -> Decimal:
    """Traded ready minutes always carry their own volume; no leg invents one."""
    return sum((Decimal(str(bar.volume)) for bar in bars), Decimal(0))


def _impulse(batch: HistoryBatch, coverage: HistoryCoverage, moment: datetime,
             started_at: datetime, frozen_at: datetime, opened: datetime, closed: datetime,
             day: str, instrument_type: str, policy: PullbackPolicy):
    """The frozen impulse leg over the supplied window's completed minutes."""
    if frozen_at > moment:
        return None, "IMPULSE_FREEZE_AFTER_EVALUATION", ()
    if started_at.second or started_at.microsecond or frozen_at.second or frozen_at.microsecond:
        return None, "IMPULSE_WINDOW_NOT_MINUTE_ALIGNED", ()
    if started_at >= frozen_at:
        return None, "EMPTY_IMPULSE_WINDOW", ()
    if not (opened <= started_at and frozen_at <= closed):
        return None, "IMPULSE_WINDOW_OUTSIDE_REGULAR_SESSION", ()
    selected = _session_items(coverage, day, started_at, frozen_at)
    ids = _ids(selected)
    if (not selected or selected[0].interval.start != started_at
            or selected[-1].interval.end != frozen_at or not _contiguous(selected)):
        return None, "IMPULSE_WINDOW_NOT_COVERED", ids
    bars, reason = _usable(batch, coverage, selected, "IMPULSE", instrument_type)
    if bars is None:
        return None, reason, ids
    highs, lows = _highs(bars, policy.measure_from_close), _lows(bars, policy.measure_from_close)
    starts, ends = (lows, highs) if policy.long else (highs, lows)
    origin = min(starts) if policy.long else max(starts)
    extreme = max(ends) if policy.long else min(ends)
    ordered = ends.index(extreme) >= starts.index(origin)
    distance = extreme - origin if policy.long else origin - extreme
    return (origin, extreme, distance, len(bars), _volume(bars), ordered), None, ids


def _pullback(batch: HistoryBatch, coverage: HistoryCoverage, moment: datetime,
              frozen_at: datetime, closed: datetime, day: str, instrument_type: str,
              policy: PullbackPolicy):
    """The completed minutes since the impulse freeze, as far as this instant."""
    selected = _session_items(coverage, day, frozen_at, min(moment, closed))
    ids = _ids(selected)
    if (len(selected) < policy.min_pullback_bars or selected[0].interval.start != frozen_at
            or not _contiguous(selected)):
        return None, "INCOMPLETE_PULLBACK_WINDOW", ids
    bars, reason = _usable(batch, coverage, selected, "PULLBACK", instrument_type)
    if bars is None:
        return None, reason, ids
    extremes = (_lows(bars, policy.measure_from_close) if policy.long
                else _highs(bars, policy.measure_from_close))
    extreme = min(extremes) if policy.long else max(extremes)
    reversal = bars[-1]
    measured = (extreme, len(bars), Decimal(str(reversal.high)), Decimal(str(reversal.low)),
                _volume(bars))
    return measured, None, ids


def _finite(value: float | int | None, name: str, label: str) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, f"MISSING_{name}"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RecordError(f"{label} must be a finite number or null")
    return Decimal(str(value)), None


def _atr(atr_1m: float | int | None) -> tuple[Decimal | None, str | None]:
    value, reason = _finite(atr_1m, "ATR_1M", "minute ATR")
    if value is None:
        return None, reason
    return (None, "NONPOSITIVE_ATR_1M") if value <= 0 else (value, None)


def build_impulse_pullback_snapshot(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
    policy: PullbackPolicy,
    impulse_started_at: datetime,
    impulse_frozen_at: datetime,
    atr_1m: float | int | None = None,
    vwap: float | int | None = None,
) -> FeatureSnapshot:
    """Measure one frozen impulse leg and the pullback that followed it."""
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("impulse symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("impulse instrument type must be EQUITY or ETF")
    if not isinstance(policy, PullbackPolicy):
        raise RecordError("policy must be PullbackPolicy")
    for instant, name in ((impulse_started_at, "start"), (impulse_frozen_at, "freeze")):
        if not isinstance(instant, datetime):
            raise RecordError(f"the impulse {name} instant is required")
    started_at, frozen_at = as_utc(impulse_started_at), as_utc(impulse_frozen_at)

    day = session_date_at(moment)
    bounds = session_bounds(day)
    common = "NO_REGULAR_SESSION" if bounds is None else _basis_reason(minute_history, symbol)
    if common is not None:
        impulse, impulse_reason, impulse_ids = None, common, ()
        pullback, pullback_reason, pullback_ids = None, common, ()
    else:
        opened, closed = map(as_utc, bounds)
        coverage = minute_history.coverage_at(moment)
        session = day.isoformat()
        impulse, impulse_reason, impulse_ids = _impulse(
            minute_history, coverage, moment, started_at, frozen_at, opened, closed, session,
            instrument_type, policy)
        pullback, pullback_reason, pullback_ids = _pullback(
            minute_history, coverage, moment, frozen_at, closed, session, instrument_type, policy)

    features = []
    if impulse is None:
        features += [*_missing(IMPULSE_SPECS, impulse_reason, impulse_ids),
                     _value(IMPULSE_VOLUME_NAME, None, "SHARES", impulse_reason, impulse_ids),
                     _value(IMPULSE_ORDERED_NAME, None, "BOOLEAN", impulse_reason, impulse_ids),
                     _value(IMPULSE_COMPLETE_NAME, 0, "BOOLEAN", None, impulse_ids)]
    else:
        origin, extreme, distance, bar_count, volume, ordered = impulse
        features += [_value(name, item, unit, None, impulse_ids)
                     for (name, unit), item in zip(
                         IMPULSE_SPECS, (origin, extreme, distance, bar_count))]
        features += [
            _value(IMPULSE_VOLUME_NAME, volume, "SHARES", None, impulse_ids),
            _value(IMPULSE_ORDERED_NAME, int(ordered), "BOOLEAN", None, impulse_ids),
            _value(IMPULSE_COMPLETE_NAME, 1, "BOOLEAN", None, impulse_ids),
        ]

    if pullback is None:
        features += [*_missing(PULLBACK_SPECS, pullback_reason, pullback_ids),
                     _value(PULLBACK_VOLUME_NAME, None, "SHARES", pullback_reason, pullback_ids),
                     _value(PULLBACK_COMPLETE_NAME, 0, "BOOLEAN", None, pullback_ids)]
    else:
        extreme, bar_count, reversal_high, reversal_low, volume = pullback
        features += [_value(name, item, unit, None, pullback_ids)
                     for (name, unit), item in zip(
                         PULLBACK_SPECS, (extreme, bar_count, reversal_high, reversal_low))]
        features += [_value(PULLBACK_VOLUME_NAME, volume, "SHARES", None, pullback_ids),
                     _value(PULLBACK_COMPLETE_NAME, 1, "BOOLEAN", None, pullback_ids)]

    leg_ids = tuple(sorted(set(impulse_ids) | set(pullback_ids)))
    if impulse is None or pullback is None:
        reason = impulse_reason or pullback_reason
        features += [_value(DEPTH_NAME, None, "USD_PER_SHARE", reason, leg_ids),
                     _value(RETRACEMENT_NAME, None, "RATIO", reason, leg_ids),
                     _value(VOLUME_RATIO_NAME, None, "RATIO", reason, leg_ids)]
    else:
        impulse_extreme, impulse_distance = impulse[1], impulse[2]
        impulse_volume, pullback_volume = impulse[4], pullback[4]
        pullback_extreme = pullback[0]
        depth = (impulse_extreme - pullback_extreme if policy.long
                 else pullback_extreme - impulse_extreme)
        retracement, retracement_reason = ((None, "ZERO_IMPULSE_DISTANCE")
                                           if impulse_distance == 0
                                           else (depth / impulse_distance, None))
        ratio, ratio_reason = ((None, "ZERO_IMPULSE_VOLUME") if impulse_volume == 0
                               else (pullback_volume / impulse_volume, None))
        features += [
            _value(DEPTH_NAME, depth, "USD_PER_SHARE", None, leg_ids),
            _value(RETRACEMENT_NAME, retracement, "RATIO", retracement_reason, leg_ids),
            _value(VOLUME_RATIO_NAME, ratio, "RATIO", ratio_reason, leg_ids),
        ]

    atr, atr_reason = _atr(atr_1m)
    level, vwap_reason = _finite(vwap, "VWAP", "supplied VWAP")
    if impulse is None or atr is None:
        features.append(_value(IMPULSE_DISTANCE_ATR_NAME, None, "RATIO",
                               impulse_reason or atr_reason, impulse_ids))
    else:
        features.append(_value(IMPULSE_DISTANCE_ATR_NAME, impulse[2] / atr, "RATIO", None,
                               impulse_ids))
    if impulse is None or pullback is None or atr is None or level is None:
        reason = impulse_reason or pullback_reason or atr_reason or vwap_reason
        features += list(_missing(VWAP_SPECS, reason, leg_ids))
    else:
        sides = ((impulse[1] - level, pullback[0] - level) if policy.long
                 else (level - impulse[1], level - pullback[0]))
        features += [_value(name, item / atr, unit, None, leg_ids)
                     for (name, unit), item in zip(VWAP_SPECS, sides)]

    input_ids = tuple(sorted({item for row in features for item in row.input_record_ids}))
    metadata = SourceMetadata(
        instrument_id=symbol,
        instrument_type=instrument_type,
        source="DERIVED_M83",
        source_time=moment,
        received_time=moment,
        available_time=moment,
        normalized_time=moment,
        session=day.isoformat(),
        data_mode=DATA_MODE,
        quality="VALID",
    )
    return FeatureSnapshot(
        record_id=record_id,
        metadata=metadata,
        evaluated_at=moment,
        features=tuple(features),
        feature_version=FEATURE_VERSION,
        input_record_ids=input_ids,
    )


__all__ = [
    "DATA_MODE",
    "FEATURE_NAMES",
    "FEATURE_VERSION",
    "PullbackPolicy",
    "build_impulse_pullback_snapshot",
]
