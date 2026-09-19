"""M7.1 point-in-time HOD/LOD and compression measurement for `HOD_COMP_RS`.

The caller supplies every canonical record, the freeze instant and its own window
definition. This module measures; it decides nothing. It adopts no compression
ratio, no bar count, no distance cutoff and no arming rule: those `HOD_COMP_RS`
numbers stay unresolved under PLAYBOOKS section 13 and M0.3, and M3.3-M3.5 keep
the compression and structure definitions. Supplying a window neither approves a
proposed rule nor proves a provider covers these minutes.

The reference extreme is frozen at the supplied instant and never reads a bar
that ended after it, so a final-session high or low cannot leak backwards into an
earlier evaluation. Any missing, unexpected, provisional or untraded interval
keeps its own value unavailable with a named reason; it never becomes a number.
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


FEATURE_VERSION = "M71_HOD_COMPRESSION_V1"
DATA_MODE = "SUPPLIED_BAR_HOD_COMPRESSION"
_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_READY = ("FINAL", "NO_TRADE")

REFERENCE_SPECS = (
    ("REFERENCE_HOD_V1", "USD_PER_SHARE"),
    ("REFERENCE_LOD_V1", "USD_PER_SHARE"),
)
WINDOW_SPECS = (
    ("COMPRESSION_HIGH_V1", "USD_PER_SHARE"),
    ("COMPRESSION_LOW_V1", "USD_PER_SHARE"),
    ("COMPRESSION_RECENT_RANGE_V1", "USD_PER_SHARE"),
    ("COMPRESSION_PRIOR_RANGE_V1", "USD_PER_SHARE"),
    ("COMPRESSION_BAR_COUNT_V1", "COUNT"),
)
RATIO_NAME = "COMPRESSION_RANGE_RATIO_V1"
DISTANCE_SPECS = (
    ("DISTANCE_TO_REFERENCE_HOD_ATR_V1", "RATIO"),
    ("DISTANCE_TO_REFERENCE_LOD_ATR_V1", "RATIO"),
)
REFERENCE_COMPLETE_NAME = "REFERENCE_EXTREME_COMPLETE_V1"
WINDOW_COMPLETE_NAME = "COMPRESSION_COMPLETE_V1"
WINDOW_AFTER_FREEZE_NAME = "COMPRESSION_WINDOW_AFTER_FREEZE_V1"

FEATURE_NAMES = (
    *(name for name, _ in REFERENCE_SPECS),
    REFERENCE_COMPLETE_NAME,
    *(name for name, _ in WINDOW_SPECS),
    RATIO_NAME,
    WINDOW_COMPLETE_NAME,
    WINDOW_AFTER_FREEZE_NAME,
    *(name for name, _ in DISTANCE_SPECS),
)


def _label(value: object, name: str) -> str:
    if (not isinstance(value, str) or not value.strip()
            or value.strip().upper() in _UNKNOWN):
        raise RecordError(f"{name} must be explicit")
    return value


@dataclass(frozen=True)
class CompressionPolicy:
    """The caller's own window definition; nothing here is defaulted.

    PLAYBOOKS section 13 still owns whether the recent and prior windows overlap
    and how many bars seed a compression, so both counts and the overlap answer
    arrive from the caller with its own definition reference.
    """

    version: str
    definition_reference: str
    recent_bars: int
    prior_bars: int
    prior_includes_recent: bool

    def __post_init__(self) -> None:
        _label(self.version, "policy version")
        _label(self.definition_reference, "definition reference")
        for name in ("recent_bars", "prior_bars"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise RecordError(f"{name} must be a positive integer count")
        if type(self.prior_includes_recent) is not bool:
            raise RecordError("prior_includes_recent must be true or false")
        if self.prior_includes_recent and self.prior_bars <= self.recent_bars:
            raise RecordError("an overlapping prior window must be longer than the recent window")

    @property
    def window_bars(self) -> int:
        """Total completed bars this definition needs at one evaluation."""
        return self.prior_bars if self.prior_includes_recent else self.prior_bars + self.recent_bars


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


def _extremes(bars) -> tuple[Decimal, Decimal]:
    return (max(Decimal(str(bar.high)) for bar in bars),
            min(Decimal(str(bar.low)) for bar in bars))


def _reference(batch: HistoryBatch, coverage: HistoryCoverage, moment: datetime,
               frozen_at: datetime, opened: datetime, closed: datetime,
               day: str, instrument_type: str):
    """Extremes over the session minutes that had ended at the freeze instant."""
    if frozen_at > moment:
        return None, "FREEZE_INSTANT_AFTER_EVALUATION", ()
    if frozen_at.second or frozen_at.microsecond:
        return None, "FREEZE_INSTANT_NOT_MINUTE_ALIGNED", ()
    if not opened < frozen_at <= closed:
        return None, "FREEZE_INSTANT_OUTSIDE_REGULAR_SESSION", ()
    items = _session_items(coverage, day, opened, frozen_at)
    ids = _ids(items)
    if (not items or items[0].interval.start != opened
            or items[-1].interval.end != frozen_at or not _contiguous(items)):
        return None, "REFERENCE_WINDOW_NOT_COVERED", ids
    status = _status_reason("REFERENCE", items)
    if status is not None:
        return None, status, ids
    if _unexpected_over(batch, coverage, items):
        return None, "UNEXPECTED_OVERLAPPING_RECORD", ids
    bars = [item.bar for item in items if not item.bar.certified_no_trade]
    if not bars:
        return None, "NO_TRADED_REFERENCE_INTERVAL", ids
    if {bar.metadata.instrument_type for bar in bars} != {instrument_type}:
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    return _extremes(bars), None, ids


def _window(batch: HistoryBatch, coverage: HistoryCoverage, moment: datetime,
            opened: datetime, closed: datetime, day: str, instrument_type: str,
            policy: CompressionPolicy):
    """The last completed session minutes this definition's window needs."""
    ended = _session_items(coverage, day, opened, min(moment, closed))
    selected = ended[-policy.window_bars:]
    ids = _ids(selected)
    if len(selected) != policy.window_bars or not _contiguous(selected):
        return None, "INCOMPLETE_COMPRESSION_WINDOW", ids
    status = _status_reason("COMPRESSION", selected)
    if status is not None:
        return None, status, ids
    if _unexpected_over(batch, coverage, selected):
        return None, "UNEXPECTED_OVERLAPPING_RECORD", ids
    bars = [item.bar for item in selected]
    if any(bar.certified_no_trade for bar in bars):
        return None, "NO_TRADED_COMPRESSION_INTERVAL", ids
    if {bar.metadata.instrument_type for bar in bars} != {instrument_type}:
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    recent = bars[-policy.recent_bars:]
    prior = bars if policy.prior_includes_recent else bars[:policy.prior_bars]
    high, low = _extremes(bars)
    recent_high, recent_low = _extremes(recent)
    prior_high, prior_low = _extremes(prior)
    measured = (high, low, recent_high - recent_low, prior_high - prior_low,
                selected[0].interval.start)
    return measured, None, ids


def _atr(atr_1m: float | int | None) -> tuple[Decimal | None, str | None]:
    if atr_1m is None:
        return None, "MISSING_ATR_1M"
    if isinstance(atr_1m, bool) or not isinstance(atr_1m, (int, float)) or not math.isfinite(atr_1m):
        raise RecordError("minute ATR must be a finite number or null")
    value = Decimal(str(atr_1m))
    return (None, "NONPOSITIVE_ATR_1M") if value <= 0 else (value, None)


def build_hod_compression_snapshot(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
    policy: CompressionPolicy,
    reference_frozen_at: datetime,
    atr_1m: float | int | None = None,
) -> FeatureSnapshot:
    """Measure the frozen reference extreme and one compression window."""
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("compression symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("compression instrument type must be EQUITY or ETF")
    if not isinstance(policy, CompressionPolicy):
        raise RecordError("policy must be CompressionPolicy")
    if not isinstance(reference_frozen_at, datetime):
        raise RecordError("the reference freeze instant is required")
    frozen_at = as_utc(reference_frozen_at)

    day = session_date_at(moment)
    bounds = session_bounds(day)
    common = "NO_REGULAR_SESSION" if bounds is None else _basis_reason(minute_history, symbol)
    if common is not None:
        reference, reference_reason, reference_ids = None, common, ()
        window, window_reason, window_ids = None, common, ()
    else:
        opened, closed = map(as_utc, bounds)
        coverage = minute_history.coverage_at(moment)
        session = day.isoformat()
        reference, reference_reason, reference_ids = _reference(
            minute_history, coverage, moment, frozen_at, opened, closed, session, instrument_type)
        window, window_reason, window_ids = _window(
            minute_history, coverage, moment, opened, closed, session, instrument_type, policy)

    features = []
    if reference is None:
        features += [*_missing(REFERENCE_SPECS, reference_reason, reference_ids),
                     _value(REFERENCE_COMPLETE_NAME, 0, "BOOLEAN", None, reference_ids)]
    else:
        features += [_value(name, item, unit, None, reference_ids)
                     for (name, unit), item in zip(REFERENCE_SPECS, reference)]
        features.append(_value(REFERENCE_COMPLETE_NAME, 1, "BOOLEAN", None, reference_ids))

    if window is None:
        features += [*_missing(WINDOW_SPECS, window_reason, window_ids),
                     _value(RATIO_NAME, None, "RATIO", window_reason, window_ids),
                     _value(WINDOW_COMPLETE_NAME, 0, "BOOLEAN", None, window_ids),
                     _value(WINDOW_AFTER_FREEZE_NAME, None, "BOOLEAN", window_reason, window_ids)]
    else:
        high, low, recent_range, prior_range, window_start = window
        measured = (high, low, recent_range, prior_range, policy.window_bars)
        features += [_value(name, item, unit, None, window_ids)
                     for (name, unit), item in zip(WINDOW_SPECS, measured)]
        ratio, ratio_reason = ((None, "ZERO_PRIOR_RANGE") if prior_range == 0
                               else (recent_range / prior_range, None))
        features += [
            _value(RATIO_NAME, ratio, "RATIO", ratio_reason, window_ids),
            _value(WINDOW_COMPLETE_NAME, 1, "BOOLEAN", None, window_ids),
            _value(WINDOW_AFTER_FREEZE_NAME, int(window_start >= frozen_at), "BOOLEAN", None,
                   window_ids),
        ]

    atr, atr_reason = _atr(atr_1m)
    distance_ids = tuple(sorted(set(reference_ids) | set(window_ids)))
    if reference is None or window is None or atr is None:
        reason = reference_reason or window_reason or atr_reason
        features += list(_missing(DISTANCE_SPECS, reason, distance_ids))
    else:
        reference_hod, reference_lod = reference
        high, low = window[0], window[1]
        distances = ((reference_hod - high) / atr, (low - reference_lod) / atr)
        features += [_value(name, item, unit, None, distance_ids)
                     for (name, unit), item in zip(DISTANCE_SPECS, distances)]

    input_ids = tuple(sorted({item for row in features for item in row.input_record_ids}))
    metadata = SourceMetadata(
        instrument_id=symbol,
        instrument_type=instrument_type,
        source="DERIVED_M71",
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
    "CompressionPolicy",
    "build_hod_compression_snapshot",
]
