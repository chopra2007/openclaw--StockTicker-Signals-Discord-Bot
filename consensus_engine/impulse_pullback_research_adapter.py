"""M9.1M research adapter: `FIRST_PULLBACK_VWAP`'s first bar-native input.

`OR_FAILURE_REV` now has every bar-native input it can ever have offline
(M9.1H-L); `FIRST_PULLBACK_VWAP` (`consensus_engine/first_pullback_vwap.py`)
remained fully unbuilt. Its `PullbackRequest.measurement` is the M8.3
`FeatureSnapshot` `impulse_pullback.build_impulse_pullback_snapshot` produces,
and that builder only admits `FINAL`/`NO_TRADE` minutes -- M9.1D's finding that
Databento history is permanently `PROVISIONAL` for this project means it can
never complete from real bars, exactly the same block M9.1D-L already found and
worked around for `HOD_COMP_RS` and `OR_FAILURE_REV`. This is the first
`FIRST_PULLBACK_VWAP` sub-step: a `PROVISIONAL`-admitting mirror of the M8.3
impulse/pullback measurement.

`impulse_pullback.py`'s own window-selection, freeze, ordering, retracement,
volume-ratio and VWAP-distance arithmetic is reused exactly, by mirroring its
private helpers with one change: `_usable` here treats `PROVISIONAL` as ready
alongside `FINAL`/`NO_TRADE`, through D-110's `research_bar_access.
research_coverage_at`, exactly as `hod_comp_rs_research_adapter.py`/M9.1E
already did for `rs_trend_eligibility`'s own window selection. `atr_1m` and
`vwap` stay caller-supplied scalars, unchanged from the live builder, since
computing either from bars is not part of this module's named scope.

The produced `FeatureSnapshot` uses its own `RESEARCH_IMPULSE_PULLBACK_
FEATURE_VERSION` and `RESEARCH_IMPULSE_PULLBACK_DATA_MODE`, distinct from
`impulse_pullback.FEATURE_VERSION`/`DATA_MODE`, so `first_pullback_vwap.
_measurement`'s strict version-and-data-mode match cannot bind a live
`PullbackRequest` to research output by accident, exactly as the M9.1E `RS`
research snapshot stays distinct from the live `RS_FEATURE_VERSION`/
`RS_DATA_MODE`. Only a policy or matcher that names these research identifiers
explicitly could ever bind to it; no such matcher exists yet, and none is added
here. The remaining `FIRST_PULLBACK_VWAP` inputs (VWAP context, relative
strength, the last-trade observation, the quote decision, the structural stop/
target and the M4.4 confidence) still need their own producers and stay open
build-scope for further M9.1 sub-steps.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at` without touching the live
`HistoryBatch`/`HistoryCoverage` contract or `impulse_pullback.py` itself, which
is untouched. No data is fetched, no parameter is searched or chosen, and no
order, alert or delivery action occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
from typing import Any

from .historical_bars import HistoryBatch, HistoryCoverage
from .impulse_pullback import PullbackPolicy
from .research_bar_access import research_coverage_at
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at

RESEARCH_IMPULSE_PULLBACK_FEATURE_VERSION = "M91M_FIRST_PULLBACK_VWAP_RESEARCH_IMPULSE_V1"
RESEARCH_IMPULSE_PULLBACK_DATA_MODE = "RESEARCH_BAR_IMPULSE_PULLBACK_V1"

_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")

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


def _usable(batch: HistoryBatch, coverage: HistoryCoverage, selected, prefix: str,
            instrument_type: str):
    """Mirrors `impulse_pullback._usable`, admitting `PROVISIONAL` as ready."""
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
    return sum((Decimal(str(bar.volume)) for bar in bars), Decimal(0))


def _impulse(batch: HistoryBatch, coverage: HistoryCoverage, moment: datetime,
             started_at: datetime, frozen_at: datetime, opened: datetime, closed: datetime,
             day: str, instrument_type: str, policy: PullbackPolicy):
    """Mirrors `impulse_pullback._impulse`, admitting `PROVISIONAL` as ready."""
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
    """Mirrors `impulse_pullback._pullback`, admitting `PROVISIONAL` as ready."""
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


@dataclass(frozen=True)
class ImpulsePullbackResearchSnapshot:
    """The research impulse/pullback `FeatureSnapshot` plus its D-110 label.

    `label` is `None` only when the session/history was absent or incompatible
    before any coverage could be computed, exactly as the M9.1H/I/J/K/L pairs'
    own label.
    """

    snapshot: FeatureSnapshot
    label: dict[str, Any] | None


def build_impulse_pullback_snapshot_from_research(
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
) -> ImpulsePullbackResearchSnapshot:
    """Measure one frozen impulse leg and its pullback over real, `PROVISIONAL`-usable bars.

    Reuses `impulse_pullback.build_impulse_pullback_snapshot`'s exact window/
    freeze/ordering/retracement/volume-ratio/VWAP-distance definitions; only the
    finality admission differs, through D-110's `research_bar_access.
    research_coverage_at`.
    """
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
    label: dict[str, Any] | None = None
    if common is not None:
        impulse, impulse_reason, impulse_ids = None, common, ()
        pullback, pullback_reason, pullback_ids = None, common, ()
    else:
        opened, closed = map(as_utc, bounds)
        research = research_coverage_at(minute_history, moment)
        label = research.label()
        coverage = research.coverage
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
        source="DERIVED_M91M_RESEARCH",
        source_time=moment,
        received_time=moment,
        available_time=moment,
        normalized_time=moment,
        session=day.isoformat(),
        data_mode=RESEARCH_IMPULSE_PULLBACK_DATA_MODE,
        quality="VALID",
    )
    snapshot = FeatureSnapshot(
        record_id=record_id,
        metadata=metadata,
        evaluated_at=moment,
        features=tuple(features),
        feature_version=RESEARCH_IMPULSE_PULLBACK_FEATURE_VERSION,
        input_record_ids=input_ids,
    )
    return ImpulsePullbackResearchSnapshot(snapshot=snapshot, label=label)


__all__ = [
    "ImpulsePullbackResearchSnapshot", "RESEARCH_IMPULSE_PULLBACK_DATA_MODE",
    "RESEARCH_IMPULSE_PULLBACK_FEATURE_VERSION", "build_impulse_pullback_snapshot_from_research",
]
