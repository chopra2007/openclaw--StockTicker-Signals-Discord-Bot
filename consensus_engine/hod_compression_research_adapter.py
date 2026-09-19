"""M9.1F research adapter: `HOD_COMP_RS` reference/compression from real bars.

This is the second `HOD_COMP_RS` role adapter M9.1F build-scope names, following
the M9.1E `RS`/`RS_WARMUP_COMPLETE` adapter's exact pattern. `RsTrendPolicy`
(`consensus_engine/rs_trend_eligibility.py`) binds `REFERENCE_EXTREME_COMPLETE`
and `COMPRESSION_COMPLETE` to the M7.1 `hod_compression` measurement; both are
completion flags over the *same* frozen-reference/compression-window
computation, so one adapter covers both roles.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at` without touching the live
`HistoryBatch`/`HistoryCoverage` contract. This module reuses the untouched
`HistoryBatch.coverage_at` for revision selection and interval status exactly
as `hod_compression.build_hod_compression_snapshot` does, but a `PROVISIONAL`
interval counts as ready here, where the live function stops at `FINAL`/
`NO_TRADE`. `research_coverage_at` supplies the exact D-110 label and the
final/no-trade/provisional/excluded counts this module attaches to its result;
it performs no window or reference selection of its own.

The produced `FeatureSnapshot` uses its own `RESEARCH_HOD_COMPRESSION_FEATURE_VERSION`
and `RESEARCH_HOD_COMPRESSION_DATA_MODE`, distinct from
`hod_compression.FEATURE_VERSION`/`DATA_MODE`, so a live consumer cannot bind to
it by accident; only a policy that names these research identifiers explicitly
can bind to it for replay.

No data is fetched, no parameter is searched or chosen, and no order, alert or
delivery action occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
from typing import Any

from .historical_bars import HistoryBatch, HistoryCoverage
from .hod_compression import (
    CompressionPolicy,
    DISTANCE_SPECS,
    FEATURE_NAMES,
    RATIO_NAME,
    REFERENCE_COMPLETE_NAME,
    REFERENCE_SPECS,
    WINDOW_AFTER_FREEZE_NAME,
    WINDOW_COMPLETE_NAME,
    WINDOW_SPECS,
)
from .research_bar_access import research_coverage_at
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at

RESEARCH_HOD_COMPRESSION_FEATURE_VERSION = "M91F_HOD_COMPRESSION_RESEARCH_V1"
RESEARCH_HOD_COMPRESSION_DATA_MODE = "RESEARCH_BAR_HOD_COMPRESSION_V1"

_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")


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
    """Mirrors `hod_compression._reference`, admitting `PROVISIONAL` as ready."""
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
    """Mirrors `hod_compression._window`, admitting `PROVISIONAL` as ready."""
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
    if (isinstance(atr_1m, bool) or not isinstance(atr_1m, (int, float))
            or not math.isfinite(atr_1m)):
        raise RecordError("minute ATR must be a finite number or null")
    value = Decimal(str(atr_1m))
    return (None, "NONPOSITIVE_ATR_1M") if value <= 0 else (value, None)


@dataclass(frozen=True)
class HodCompressionResearchSnapshot:
    """The research HOD/compression snapshot plus the one D-110 label.

    `label` is a `ResearchCoverage.label()` result, naming decision D-110, the
    finality gap and the final/no-trade/provisional/excluded interval counts
    feeding both the reference and window measurements. It is `None` only when
    the supplied history was absent or incompatible before any coverage could
    be computed.
    """

    snapshot: FeatureSnapshot
    label: dict[str, Any] | None


def build_hod_compression_snapshot_from_research(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
    policy: CompressionPolicy,
    reference_frozen_at: datetime,
    atr_1m: float | int | None = None,
) -> HodCompressionResearchSnapshot:
    """Measure the frozen reference extreme and compression window over real,
    `PROVISIONAL`-usable bars.

    Reuses `hod_compression`'s own reference/window contract unchanged except
    for admitting `PROVISIONAL` intervals; every other refusal reason
    (`REFERENCE_WINDOW_NOT_COVERED`, `INCOMPLETE_COMPRESSION_WINDOW`,
    `INCOMPATIBLE_*`, ...) behaves exactly as the live function's.
    """
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
    label = None
    if common is not None:
        reference, reference_reason, reference_ids = None, common, ()
        window, window_reason, window_ids = None, common, ()
    else:
        opened, closed = map(as_utc, bounds)
        research = research_coverage_at(minute_history, moment)
        label = research.label()
        coverage = research.coverage
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
        source="DERIVED_M91F",
        source_time=moment,
        received_time=moment,
        available_time=moment,
        normalized_time=moment,
        session=day.isoformat(),
        data_mode=RESEARCH_HOD_COMPRESSION_DATA_MODE,
        quality="VALID",
    )
    snapshot = FeatureSnapshot(
        record_id=record_id,
        metadata=metadata,
        evaluated_at=moment,
        features=tuple(features),
        feature_version=RESEARCH_HOD_COMPRESSION_FEATURE_VERSION,
        input_record_ids=input_ids,
    )
    return HodCompressionResearchSnapshot(snapshot=snapshot, label=label)


__all__ = [
    "FEATURE_NAMES",
    "RESEARCH_HOD_COMPRESSION_DATA_MODE",
    "RESEARCH_HOD_COMPRESSION_FEATURE_VERSION",
    "HodCompressionResearchSnapshot",
    "build_hod_compression_snapshot_from_research",
]
