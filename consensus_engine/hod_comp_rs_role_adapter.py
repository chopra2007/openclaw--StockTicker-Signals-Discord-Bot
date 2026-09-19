"""M9.1G research adapter: `HOD_COMP_RS` remaining role features from real bars.

`RsTrendPolicy` (`consensus_engine/rs_trend_eligibility.py`) binds nine
`REQUIRED_ROLES`. M9.1E built `RS`/`RS_WARMUP_COMPLETE`; M9.1F built
`REFERENCE_EXTREME_COMPLETE`/`COMPRESSION_COMPLETE`. This module builds the
remaining five bar-only roles: `MEDIAN_DOLLAR_VOLUME`, `RVOL`, `OPEN_RETURN`,
`DAILY_ATR_PCT` and `SESSION_VWAP`. The two quote-derived gates
(`QUOTE_ACTIONABLE`, `SPREAD_BPS`) need real quote data and stay out of this
bar-only adapter's scope entirely.

`MEDIAN_DOLLAR_VOLUME` and `RVOL` mirror `participation_features._calculate`'s
"daily" and "opening" window selection exactly (same required-slot, symbol,
interval, unit and mode checks, same median-of-20/ratio-of-20 arithmetic), but
admit a `PROVISIONAL` interval as ready where the live function stops at
`FINAL`/`NO_TRADE`. `OPEN_RETURN` and `SESSION_VWAP` mirror
`core_price_features`'s `_opening`/`_session` window selection the same way;
`core_price_features.py`'s own `DAILY_ATR_14_SMA_V1` is `USD_PER_SHARE`, not the
`DAILY_ATR_PCT` role's implied ratio unit, so this module explicitly derives
`DAILY_ATR_PCT` as that ATR divided by the prior regular-session close (the same
prior-close computation `core_price_features._daily`/`_opening` already use for
`GAP_OPEN_V1`), rather than passing the USD figure through unchanged.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at` without touching the live
`HistoryBatch`/`HistoryCoverage` contract; `participation_features.py` and
`core_price_features.py` are untouched (no code path here modifies a shared
production module or its status ladder). Every result carries one D-110 label
per supplied history side (`opening_history`, `daily_history`,
`minute_history`).

The produced `FeatureSnapshot` uses its own `RESEARCH_ROLE_FEATURE_VERSION` and
`RESEARCH_ROLE_DATA_MODE`, distinct from the live D-090 versions/modes, so a
live consumer cannot bind to it by accident; only a policy that names these
research identifiers explicitly can bind to it for replay.

No data is fetched, no parameter is searched or chosen, and no order, alert or
delivery action occurs here.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .core_price_features import OpeningTradeObservation
from .historical_bars import HistoryBatch, HistoryRequest
from .research_bar_access import research_coverage_at
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at, session_dates

RESEARCH_ROLE_FEATURE_VERSION = "M91G_HOD_COMP_RS_ROLE_RESEARCH_V1"
RESEARCH_ROLE_DATA_MODE = "RESEARCH_BAR_HOD_COMP_RS_ROLES_V1"

RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME = "RESEARCH_MEDIAN_DOLLAR_VOLUME_V1"
RESEARCH_RVOL_NAME = "RESEARCH_RVOL_OPEN5_MEAN20_V1"
RESEARCH_OPEN_RETURN_NAME = "RESEARCH_OPEN_RETURN_V1"
RESEARCH_DAILY_ATR_PCT_NAME = "RESEARCH_DAILY_ATR_PCT_V1"
RESEARCH_SESSION_VWAP_NAME = "RESEARCH_SESSION_VWAP_V1"
ROLE_FEATURE_NAMES = (
    RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME, RESEARCH_RVOL_NAME, RESEARCH_OPEN_RETURN_NAME,
    RESEARCH_DAILY_ATR_PCT_NAME, RESEARCH_SESSION_VWAP_NAME,
)

_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")


def _basis_reason(batch: HistoryBatch | None, symbol: str, required_interval: str,
                  *, require_volume: bool = False) -> str | None:
    if batch is None:
        return "MISSING_" + ("MINUTE" if required_interval == "1m" else "DAILY") + "_HISTORY"
    if batch.request.symbol != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if batch.request.interval != required_interval:
        return "INCOMPATIBLE_HISTORY_INTERVAL"
    if batch.conventions.price != "USD_PER_SHARE":
        return "INCOMPATIBLE_PRICE_UNIT"
    if require_volume and batch.conventions.volume != "SHARES":
        return "INCOMPATIBLE_VOLUME_UNIT"
    if any(value.strip().upper() in _UNKNOWN for value in (
            batch.source, batch.conventions.adjustment_basis, batch.conventions.coverage_basis)):
        return "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    return None


def _cross_basis_reason(a: HistoryBatch | None, b: HistoryBatch | None) -> str | None:
    if a is None or b is None:
        return None
    if (a.source != b.source or a.conventions.adjustment_basis != b.conventions.adjustment_basis
            or a.conventions.coverage_basis != b.conventions.coverage_basis):
        return "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"
    return None


def _unexpected_in(batch: HistoryBatch, coverage, items) -> bool:
    unexpected = set(coverage.unexpected_record_ids)
    return any(bar.record_id in unexpected
               and any(bar.start_time < item.interval.end and bar.end_time > item.interval.start
                       for item in items)
               for bar in batch.bars)


def _latest_regular_end(moment: datetime) -> datetime | None:
    day = session_date_at(moment)
    bounds = session_bounds(day)
    if bounds is not None:
        opened, closed = map(as_utc, bounds)
        if moment >= opened:
            current_end = min(moment.replace(second=0, microsecond=0), closed)
            if current_end > opened:
                return current_end
    previous = session_dates(day - timedelta(days=10), day - timedelta(days=1))
    return as_utc(session_bounds(previous[-1])[1]) if previous else None


# --- MEDIAN_DOLLAR_VOLUME / RVOL: mirrors participation_features._calculate ---


def _participation_windows(symbol: str, day, kind: str):
    prior = session_dates(day - timedelta(days=60), day - timedelta(days=1))[-20:]
    if len(prior) != 20 or session_bounds(day) is None:
        return ()
    days = prior if kind == "daily" else [*prior, day]
    windows = []
    for reference_day in days:
        opened, closed = map(as_utc, session_bounds(reference_day))
        if kind == "opening":
            request = HistoryRequest(symbol, opened, opened + timedelta(minutes=5))
        else:
            request = HistoryRequest(symbol, opened, closed, interval="1d")
        windows.append(request.expected_intervals())
    return tuple(windows)


def _selected_bars(batch: HistoryBatch, required, moment: datetime):
    ends = [interval.end for interval in required]
    selected = []
    for bar in batch.bars:
        if bar.metadata.available_time > moment:
            continue
        index = bisect_right(ends, bar.start_time)
        if index < len(required) and required[index].start < bar.end_time:
            selected.append(bar)
    return tuple(selected)


def _participation_role(*, batch: HistoryBatch | None, symbol: str, instrument_type: str,
                        moment: datetime, kind: str, name: str, unit: str):
    """Mirrors `participation_features._calculate`, admitting `PROVISIONAL` as ready."""
    if batch is None:
        return FeatureValue(name, None, unit, "MISSING_" + kind.upper() + "_HISTORY", ()), None
    windows = _participation_windows(symbol, session_date_at(moment), kind)
    if not windows:
        return FeatureValue(name, None, unit, "NO_CURRENT_SESSION_OR_20_REFERENCE_SESSIONS", ()), None
    if batch.request.symbol != symbol:
        return FeatureValue(name, None, unit, "INCOMPATIBLE_SYMBOL", ()), None
    expected_interval = "1d" if kind == "daily" else "1m"
    if batch.request.interval != expected_interval:
        return FeatureValue(name, None, unit, "INCOMPATIBLE_HISTORY_INTERVAL", ()), None
    if batch.conventions.volume != "SHARES":
        return FeatureValue(name, None, unit, "INCOMPATIBLE_VOLUME_UNIT", ()), None
    if kind == "daily" and batch.conventions.price != "USD_PER_SHARE":
        return FeatureValue(name, None, unit, "INCOMPATIBLE_PRICE_UNIT", ()), None

    required = tuple(interval for window in windows for interval in window)
    bars = _selected_bars(batch, required, moment)
    selected = HistoryBatch(batch.request, batch.source, batch.conventions, bars)
    research = research_coverage_at(selected, moment)
    coverage, label = research.coverage, research.label()
    by_interval = {item.interval: item for item in coverage.intervals}
    items = [by_interval.get(interval) for interval in required]
    ids = tuple(sorted({item.bar.record_id for item in items
                        if item is not None and item.bar is not None}
                       | set(coverage.unexpected_record_ids)))
    if coverage.unexpected_record_ids:
        return FeatureValue(name, None, unit, "UNEXPECTED_OVERLAPPING_RECORD", ids), label
    for interval, item in zip(required, items):
        if item is None or item.status not in _READY:
            status = item.status if item is not None else "NOT_REQUESTED"
            role = "CURRENT" if interval.session == session_date_at(moment).isoformat() else "REFERENCE"
            return FeatureValue(name, None, unit, role + "_WINDOW_" + status, ids), label
    usable = [item.bar for item in items]
    if any(bar.metadata.instrument_type != instrument_type for bar in usable):
        return FeatureValue(name, None, unit, "INCOMPATIBLE_INSTRUMENT_TYPE", ids), label
    modes = {bar.metadata.data_mode for bar in usable}
    if len(modes) != 1 or any(mode.strip().upper() in _UNKNOWN for mode in modes):
        return FeatureValue(name, None, unit, "INCOMPATIBLE_MODE", ids), label

    if kind == "daily":
        if any(bar.close is None for bar in usable):
            return FeatureValue(name, None, unit, "MISSING_REGULAR_SESSION_CLOSE", ids), label
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
            return FeatureValue(name, None, unit, "ZERO_REFERENCE_VOLUME", ids), label
        result = volumes[20] * Decimal(20) / reference_sum
    return FeatureValue(name, float(result), unit, None, ids), label


# --- DAILY_ATR_PCT / SESSION_VWAP / OPEN_RETURN: mirrors core_price_features --


def _daily_role(batch: HistoryBatch | None, moment: datetime, common: str | None):
    """Mirrors `core_price_features._daily`'s ATR/prior-close selection."""
    missing_window = (None, "INCOMPLETE_15_SESSION_DAILY_WINDOW", ())
    missing_prior = (None, "INCOMPLETE_PRIOR_SESSION_DAILY_BAR", ())
    if common or batch is None:
        missing = (None, common or "MISSING_DAILY_HISTORY", ())
        return missing, missing, None
    research = research_coverage_at(batch, moment)
    coverage, label = research.coverage, research.label()
    day = session_date_at(moment)
    prior_days = session_dates(day - timedelta(days=60), day - timedelta(days=1))[-15:]
    by_day = {item.interval.session: item for item in coverage.intervals}
    items = [by_day.get(value.isoformat()) for value in prior_days]
    prior_day = prior_days[-1].isoformat() if prior_days else None
    prior_item = by_day.get(prior_day) if prior_day else None
    if (prior_item is not None and prior_item.status in _READY and prior_item.status != "NO_TRADE"
            and prior_item.bar is not None
            and not _unexpected_in(batch, coverage, [prior_item])):
        prior = prior_item.bar
        prior_close = (Decimal(str(prior.close)), None, (prior.record_id,))
    else:
        prior_close = missing_prior

    if (len(items) != 15 or any(item is None for item in items)
            or any(item.status not in _READY for item in items)
            or _unexpected_in(batch, coverage, items)):
        return missing_window, prior_close, label
    if any(item.status == "NO_TRADE" or item.bar is None for item in items):
        return missing_window, prior_close, label
    bars = [item.bar for item in items]
    total = Decimal(0)
    for previous, bar in zip(bars, bars[1:]):
        high, low, close = map(Decimal, map(str, (bar.high, bar.low, previous.close)))
        total += max(high - low, abs(high - close), abs(low - close))
    atr_ids = tuple(bar.record_id for bar in bars)
    return (total / Decimal(14), None, atr_ids), prior_close, label


def _session_vwap(batch: HistoryBatch | None, moment: datetime, common: str | None):
    """Mirrors `core_price_features._session`'s VWAP selection."""
    if common or batch is None:
        return None, common or "MISSING_REGULAR_SESSION_HISTORY", (), None
    research = research_coverage_at(batch, moment)
    coverage, label = research.coverage, research.label()
    day = session_date_at(moment).isoformat()
    bounds = session_bounds(session_date_at(moment))
    items = [item for item in coverage.intervals
             if bounds is not None and item.interval.session == day
             and item.interval.start >= as_utc(bounds[0])
             and item.interval.end <= min(moment, as_utc(bounds[1]))]
    expected_end = _latest_regular_end(moment)
    if (not items or bounds is None or items[0].interval.start != as_utc(bounds[0])
            or items[-1].interval.end != expected_end
            or any(item.status not in _READY for item in items)
            or _unexpected_in(batch, coverage, items)):
        return None, "INCOMPLETE_CURRENT_SESSION_WINDOW", (), label
    bars = [item.bar for item in items
           if item.status in ("FINAL", "PROVISIONAL") and item.bar is not None]
    if not bars:
        return None, "NO_TRADED_REGULAR_SESSION_BAR", (), label
    volume = sum(Decimal(str(bar.volume)) for bar in bars)
    ids = tuple(item.bar.record_id for item in items if item.bar is not None)
    if volume == 0:
        return None, "ZERO_SESSION_VOLUME", ids, label
    vwap = sum(((Decimal(str(bar.high)) + Decimal(str(bar.low)) + Decimal(str(bar.close)))
               / Decimal(3)) * Decimal(str(bar.volume)) for bar in bars) / volume
    return vwap, None, ids, label


def _open_return(opening: OpeningTradeObservation | None, moment: datetime, symbol: str,
                 basis: HistoryBatch | None, basis_coverage, prior_close,
                 basis_reason: str | None, gap_reason: str | None):
    """Mirrors `core_price_features._opening`'s gap-return selection."""
    if basis_reason or opening is None:
        return None, basis_reason or "MISSING_IDENTIFIED_OPENING_TRADE", ()
    bounds = session_bounds(session_date_at(moment))
    basis_types = {item.bar.metadata.instrument_type for item in basis_coverage.intervals
                  if item.bar is not None}
    basis_type = next(iter(basis_types)) if len(basis_types) == 1 else None
    if (bounds is None or opening.metadata.instrument_id != symbol
            or opening.metadata.source != basis.source
            or opening.metadata.instrument_type != basis_type
            or opening.adjustment_basis != basis.conventions.adjustment_basis
            or opening.price_convention != basis.conventions.price
            or opening.coverage_basis != basis.conventions.coverage_basis
            or opening.metadata.quality != "VALID"
            or opening.metadata.available_time > moment
            or opening.trade_time > opening.metadata.available_time
            or opening.trade_time > moment
            or not (as_utc(bounds[0]) <= opening.trade_time < as_utc(bounds[1]))
            or opening.metadata.session != session_date_at(moment).isoformat()):
        return None, "INVALID_OR_INCOMPATIBLE_OPENING_TRADE", ()
    if gap_reason:
        return None, gap_reason, ()
    if prior_close[0] is None:
        return None, prior_close[1], ()
    price, close = Decimal(str(opening.price)), Decimal(str(prior_close[0]))
    if close == 0:
        return None, "ZERO_PRIOR_CLOSE", ()
    ids = (opening.record_id, *prior_close[2])
    return (price - close) / close, None, ids


@dataclass(frozen=True)
class HodCompRsRoleResearchSnapshot:
    """The five research role features plus one D-110 label per supplied history.

    `opening_label`/`daily_label`/`minute_label` are `ResearchCoverage.label()`
    results for `opening_history`, `daily_history` and `minute_history`
    respectively; each is `None` only when that side's history was absent or
    incompatible before any coverage could be computed.
    """

    snapshot: FeatureSnapshot
    opening_label: dict[str, Any] | None
    daily_label: dict[str, Any] | None
    minute_label: dict[str, Any] | None


def build_hod_comp_rs_role_snapshot_from_research(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    opening_history: HistoryBatch | None,
    daily_history: HistoryBatch | None,
    minute_history: HistoryBatch | None,
    opening_trade: OpeningTradeObservation | None,
) -> HodCompRsRoleResearchSnapshot:
    """Measure the five remaining bar-only `HOD_COMP_RS` roles over real,
    `PROVISIONAL`-usable bars.

    Reuses `participation_features`/`core_price_features`'s own window/basis
    contract unchanged except for admitting `PROVISIONAL` intervals; every
    other refusal reason (`INCOMPLETE_*`, `INCOMPATIBLE_*`, ...) behaves exactly
    as the live functions'. `DAILY_ATR_PCT` is an explicit price-normalized
    derivation (the daily ATR divided by the prior regular-session close), not
    a direct pass-through of the live `DAILY_ATR_14_SMA_V1` USD figure.
    """
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")

    dollar_value, daily_participation_label = _participation_role(
        batch=daily_history, symbol=symbol, instrument_type=instrument_type, moment=moment,
        kind="daily", name=RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME, unit="USD")
    rvol_value, opening_label = _participation_role(
        batch=opening_history, symbol=symbol, instrument_type=instrument_type, moment=moment,
        kind="opening", name=RESEARCH_RVOL_NAME, unit="RATIO")

    daily_reason = _basis_reason(daily_history, symbol, "1d")
    atr_result, prior_close, daily_role_label = _daily_role(daily_history, moment, daily_reason)
    daily_label = daily_role_label or daily_participation_label
    atr_value, atr_reason, atr_ids = atr_result
    atr_pct_ids = tuple(sorted(set(atr_ids) | set(prior_close[2])))
    if atr_value is None or prior_close[0] is None:
        atr_pct_value = FeatureValue(RESEARCH_DAILY_ATR_PCT_NAME, None, "RATIO",
                                     atr_reason or prior_close[1], atr_pct_ids)
    elif prior_close[0] == 0:
        atr_pct_value = FeatureValue(RESEARCH_DAILY_ATR_PCT_NAME, None, "RATIO",
                                     "ZERO_PRIOR_CLOSE", atr_pct_ids)
    else:
        atr_pct_value = FeatureValue(RESEARCH_DAILY_ATR_PCT_NAME, float(atr_value / prior_close[0]),
                                     "RATIO", None, atr_pct_ids)

    minute_reason = _basis_reason(minute_history, symbol, "1m", require_volume=True)
    vwap, vwap_reason, vwap_ids, minute_label = _session_vwap(minute_history, moment, minute_reason)
    vwap_value = FeatureValue(RESEARCH_SESSION_VWAP_NAME,
                              float(vwap) if vwap is not None else None,
                              "USD_PER_SHARE", vwap_reason, vwap_ids)

    open_basis_reason = _basis_reason(minute_history, symbol, "1m")
    minute_coverage = (research_coverage_at(minute_history, moment).coverage
                       if minute_history is not None and open_basis_reason is None else None)
    gap_reason = open_basis_reason or daily_reason or _cross_basis_reason(minute_history, daily_history)
    open_value, open_reason, open_ids = _open_return(
        opening_trade, moment, symbol, minute_history, minute_coverage, prior_close,
        open_basis_reason, gap_reason)
    open_return_value = FeatureValue(RESEARCH_OPEN_RETURN_NAME,
                                     float(open_value) if open_value is not None else None,
                                     "RATIO", open_reason, open_ids)

    features = (dollar_value, rvol_value, open_return_value, atr_pct_value, vwap_value)
    ids = tuple(sorted({item for feature in features for item in feature.input_record_ids}))
    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_M91G",
        source_time=moment, received_time=moment, available_time=moment, normalized_time=moment,
        session=session_date_at(moment).isoformat(), data_mode=RESEARCH_ROLE_DATA_MODE,
        quality="VALID",
    )
    snapshot = FeatureSnapshot(
        record_id=record_id, metadata=metadata, evaluated_at=moment, features=features,
        feature_version=RESEARCH_ROLE_FEATURE_VERSION, input_record_ids=ids,
    )
    return HodCompRsRoleResearchSnapshot(
        snapshot=snapshot, opening_label=opening_label, daily_label=daily_label,
        minute_label=minute_label,
    )


__all__ = [
    "RESEARCH_DAILY_ATR_PCT_NAME", "RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME",
    "RESEARCH_OPEN_RETURN_NAME", "RESEARCH_ROLE_DATA_MODE", "RESEARCH_ROLE_FEATURE_VERSION",
    "RESEARCH_RVOL_NAME", "RESEARCH_SESSION_VWAP_NAME", "ROLE_FEATURE_NAMES",
    "HodCompRsRoleResearchSnapshot", "build_hod_comp_rs_role_snapshot_from_research",
]
