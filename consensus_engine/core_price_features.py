"""Point-in-time core price features approved by D-090.

This module only consumes supplied canonical records.  It performs no I/O and
does not claim that a provider supplies complete or compatible market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
import math

from consensus_engine.historical_bars import HistoryBatch, HistoryCoverage
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, SourceMetadata,
)
from consensus_engine.utils.time_context import (
    as_utc, premarket_bounds, session_bounds, session_date_at, session_dates,
)


FEATURE_VERSION = "D090_CORE_PRICE_FEATURES_V1"
_PM_START = time(1, 0)
_KNOWN_BAD = {"", "UNKNOWN", "UNSPECIFIED"}
_PRICE_UNIT = "USD_PER_SHARE"
_VOLUME_UNIT = "SHARES"
_INSTRUMENT_TYPES = {"EQUITY", "ETF"}


@dataclass(frozen=True)
class OpeningTradeObservation:
    """A source-identified first regular-session trade, not a bar estimate."""

    record_id: str
    metadata: SourceMetadata
    trade_time: datetime
    price: float
    adjustment_basis: str
    price_convention: str
    coverage_basis: str

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id.strip():
            raise RecordError("opening trade record_id is required")
        if not isinstance(self.metadata, SourceMetadata):
            raise RecordError("opening trade metadata is required")
        try:
            moment = as_utc(self.trade_time)
        except (TypeError, ValueError) as exc:
            raise RecordError("opening trade time must include a timezone") from exc
        object.__setattr__(self, "trade_time", moment)
        if self.metadata.source_time != moment:
            raise RecordError("opening trade source time must equal its trade time")
        if moment > self.metadata.available_time:
            raise RecordError("opening trade time cannot follow its availability")
        if (isinstance(self.price, bool) or not isinstance(self.price, (int, float))
                or not math.isfinite(self.price) or self.price <= 0):
            raise RecordError("opening trade price must be finite and positive")
        if self.metadata.instrument_type not in _INSTRUMENT_TYPES:
            raise RecordError("opening trade instrument type must be EQUITY or ETF")
        for value in (self.adjustment_basis, self.price_convention, self.coverage_basis):
            if not isinstance(value, str) or value.strip().upper() in _KNOWN_BAD:
                raise RecordError("opening trade conventions must be known")
        if self.price_convention != _PRICE_UNIT:
            raise RecordError("opening trade price convention must be USD_PER_SHARE")


def _value(name: str, value: Decimal | float | None, unit: str, reason: str | None,
           ids: tuple[str, ...] = ()) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason, ids)


def _coverage(batch: HistoryBatch | None, moment: datetime) -> HistoryCoverage | None:
    return batch.coverage_at(moment) if batch is not None else None


def _ready(items) -> bool:
    return bool(items) and all(item.status in ("FINAL", "NO_TRADE") for item in items)


def _unexpected_in(batch: HistoryBatch, coverage: HistoryCoverage, items) -> bool:
    """Only malformed records overlapping this feature's required slots block it."""
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


def _traded(items):
    return [item.bar for item in items if item.status == "FINAL" and item.bar is not None]


def _instrument_types(coverages: tuple[HistoryCoverage | None, ...]) -> set[str]:
    """Use the selected available revisions, never raw future or superseded bars."""
    return {item.bar.metadata.instrument_type for coverage in coverages if coverage is not None
            for item in coverage.intervals if item.bar is not None}


def _basis_reason(batches: tuple[HistoryBatch | None, ...], symbol: str,
                  coverages: tuple[HistoryCoverage | None, ...],
                  *, require_volume: bool = False,
                  required_interval: str | None = None) -> str | None:
    supplied = [batch for batch in batches if batch is not None]
    if any(batch.request.symbol != symbol for batch in supplied):
        return "INCOMPATIBLE_SYMBOL"
    if required_interval is not None and any(
            batch.request.interval != required_interval for batch in supplied):
        return "INCOMPATIBLE_HISTORY_INTERVAL"
    sources = {batch.source for batch in supplied}
    adjustments = {batch.conventions.adjustment_basis for batch in supplied}
    coverage = {batch.conventions.coverage_basis for batch in supplied}
    types = _instrument_types(coverages)
    if any(batch.conventions.price != _PRICE_UNIT for batch in supplied):
        return "INCOMPATIBLE_PRICE_UNIT"
    if require_volume and any(batch.conventions.volume != _VOLUME_UNIT for batch in supplied):
        return "INCOMPATIBLE_VOLUME_UNIT"
    if len(sources) > 1 or len(adjustments) > 1 or len(coverage) > 1:
        return "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"
    if types and (len(types) > 1 or not types.issubset(_INSTRUMENT_TYPES)):
        return "INCOMPATIBLE_INSTRUMENT_TYPE"
    if any(value.strip().upper() in _KNOWN_BAD
           for value in (*sources, *adjustments, *coverage)):
        return "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    return None


def _minute_atr(batch: HistoryBatch | None, coverage: HistoryCoverage | None,
                moment: datetime, common: str | None):
    if common or batch is None or coverage is None:
        return None, common or "MISSING_MINUTE_HISTORY", ()
    ended = []
    for item in coverage.intervals:
        bounds = session_bounds(datetime.fromisoformat(item.interval.session).date())
        if bounds is not None and as_utc(bounds[0]) <= item.interval.start \
                and item.interval.end <= as_utc(bounds[1]) and item.interval.end <= moment:
            ended.append(item)
    selected = ended[-20:]
    expected_end = _latest_regular_end(moment)
    if (len(selected) != 20 or not _ready(selected)
            or _unexpected_in(batch, coverage, selected)
            or selected[-1].interval.end != expected_end):
        return None, "INCOMPLETE_20_MINUTE_WINDOW", ()
    all_items = list(coverage.intervals)
    total = Decimal(0)
    ids = []
    for item in selected:
        bar = item.bar
        if item.status == "NO_TRADE":
            ids.append(bar.record_id)
            continue
        earlier = all_items[:all_items.index(item)]
        bounds = session_bounds(datetime.fromisoformat(item.interval.session).date())
        regular_start = as_utc(bounds[0]) if bounds is not None else None
        regular_end = as_utc(bounds[1]) if bounds is not None else None
        same_session = [candidate for candidate in earlier
                        if candidate.interval.session == item.interval.session
                        and regular_start is not None
                        and regular_start <= candidate.interval.start
                        and candidate.interval.end <= regular_end]
        prior = None
        previous_items = []
        for candidate in reversed(same_session):
            previous_items.append(candidate)
            if candidate.status == "FINAL" and candidate.bar is not None:
                prior = candidate.bar
                break
            if candidate.status != "NO_TRADE":
                return None, "MISSING_PREVIOUS_MINUTE_CLOSE", ()
        if _unexpected_in(batch, coverage, previous_items):
            return None, "MISSING_PREVIOUS_MINUTE_CLOSE", ()
        first_slot = bounds is not None and item.interval.start == as_utc(bounds[0])
        first_traded = (bounds is not None and same_session
                        and same_session[0].interval.start == as_utc(bounds[0])
                        and all(candidate.status == "NO_TRADE" for candidate in same_session))
        if prior is None and not (first_slot or first_traded):
            return None, "MISSING_PREVIOUS_MINUTE_CLOSE", ()
        high, low = Decimal(str(bar.high)), Decimal(str(bar.low))
        tr = high - low if prior is None else max(
            high - low, abs(high - Decimal(str(prior.close))), abs(low - Decimal(str(prior.close))))
        total += tr
        ids.append(bar.record_id)
        if prior is not None:
            ids.append(prior.record_id)
    return total / Decimal(20), None, tuple(sorted(set(ids)))


def _daily(batch: HistoryBatch | None, coverage: HistoryCoverage | None,
           moment: datetime, common: str | None):
    missing_window = (None, "INCOMPLETE_15_SESSION_DAILY_WINDOW", ())
    missing_prior = (None, "INCOMPLETE_PRIOR_SESSION_DAILY_BAR", ())
    if common or batch is None or coverage is None:
        missing = (None, common or "MISSING_DAILY_HISTORY", ())
        return missing, missing, missing, missing
    day = session_date_at(moment)
    prior_days = session_dates(day - timedelta(days=60), day - timedelta(days=1))[-15:]
    by_day = {item.interval.session: item for item in coverage.intervals}
    items = [by_day.get(value.isoformat()) for value in prior_days]
    prior_day = prior_days[-1].isoformat() if prior_days else None
    prior_item = by_day.get(prior_day) if prior_day else None
    if (prior_item is not None and prior_item.status == "FINAL"
            and prior_item.bar is not None
            and not _unexpected_in(batch, coverage, [prior_item])):
        prior = prior_item.bar
        pdh = (Decimal(str(prior.high)), None, (prior.record_id,))
        pdl = (Decimal(str(prior.low)), None, (prior.record_id,))
        prior_close = (Decimal(str(prior.close)), None, (prior.record_id,))
    else:
        pdh = pdl = prior_close = missing_prior

    if (len(items) != 15 or any(item is None for item in items) or not _ready(items)
            or _unexpected_in(batch, coverage, items)):
        return missing_window, pdh, pdl, prior_close
    bars = [item.bar for item in items]
    if any(item.status != "FINAL" or bar is None for item, bar in zip(items, bars)):
        return missing_window, pdh, pdl, prior_close
    total = Decimal(0)
    for previous, bar in zip(bars, bars[1:]):
        high, low, close = map(Decimal, map(str, (bar.high, bar.low, previous.close)))
        total += max(high - low, abs(high - close), abs(low - close))
    atr_ids = tuple(bar.record_id for bar in bars)
    return (total / Decimal(14), None, atr_ids), pdh, pdl, prior_close


def _session(batch: HistoryBatch | None, coverage: HistoryCoverage | None,
             moment: datetime, common: str | None):
    missing = (None, common or "MISSING_REGULAR_SESSION_HISTORY", ())
    if common or batch is None or coverage is None:
        return missing, missing, missing
    day = session_date_at(moment).isoformat()
    bounds = session_bounds(session_date_at(moment))
    items = [item for item in coverage.intervals
             if bounds is not None and item.interval.session == day
             and item.interval.start >= as_utc(bounds[0])
             and item.interval.end <= min(moment, as_utc(bounds[1]))]
    expected_end = _latest_regular_end(moment)
    if (not items or bounds is None or items[0].interval.start != as_utc(bounds[0])
            or items[-1].interval.end != expected_end or not _ready(items)
            or _unexpected_in(batch, coverage, items)):
        reason = "INCOMPLETE_CURRENT_SESSION_WINDOW"
        return (None, reason, ()), (None, reason, ()), (None, reason, ())
    bars = _traded(items)
    if not bars:
        reason = "NO_TRADED_REGULAR_SESSION_BAR"
        return (None, reason, ()), (None, reason, ()), (None, reason, ())
    volume = sum(Decimal(str(bar.volume)) for bar in bars)
    ids = tuple(item.bar.record_id for item in items if item.bar is not None)
    vwap = None if volume == 0 else sum(
        ((Decimal(str(bar.high)) + Decimal(str(bar.low)) + Decimal(str(bar.close))) / Decimal(3))
        * Decimal(str(bar.volume)) for bar in bars) / volume
    vwap_result = (vwap, None, ids) if vwap is not None else (None, "ZERO_SESSION_VOLUME", ids)
    return vwap_result, (max(Decimal(str(bar.high)) for bar in bars), None, ids), (
        min(Decimal(str(bar.low)) for bar in bars), None, ids)


def _premarket(batch: HistoryBatch | None, coverage: HistoryCoverage | None,
               moment: datetime, common: str | None):
    missing = (None, common or "MISSING_PREMARKET_HISTORY", ())
    if common or batch is None or coverage is None:
        return missing, missing
    bounds = session_bounds(session_date_at(moment))
    if bounds is None or moment < as_utc(bounds[0]) or batch.request.premarket_start != _PM_START:
        return (None, "PREMARKET_WINDOW_NOT_COMPLETE", ()), (None, "PREMARKET_WINDOW_NOT_COMPLETE", ())
    day = session_date_at(moment).isoformat()
    started, opened = map(as_utc, premarket_bounds(session_date_at(moment), _PM_START))
    items = [item for item in coverage.intervals if item.interval.session == day
             and item.interval.start >= started and item.interval.end <= opened]
    if (not _ready(items) or _unexpected_in(batch, coverage, items)
            or items[0].interval.start != started
            or items[-1].interval.end != opened):
        return (None, "INCOMPLETE_PREMARKET_WINDOW", ()), (None, "INCOMPLETE_PREMARKET_WINDOW", ())
    bars = _traded(items)
    if not bars:
        return (None, "NO_PREMARKET_TRADES", ()), (None, "NO_PREMARKET_TRADES", ())
    ids = tuple(item.bar.record_id for item in items if item.bar is not None)
    return (max(Decimal(str(bar.high)) for bar in bars), None, ids), (
        min(Decimal(str(bar.low)) for bar in bars), None, ids)


def _opening(opening: OpeningTradeObservation | None, moment: datetime, symbol: str,
             basis: HistoryBatch, basis_coverage: HistoryCoverage | None,
             prior_close, basis_reason: str | None,
             gap_basis_reason: str | None):
    missing = (None, basis_reason or "MISSING_IDENTIFIED_OPENING_TRADE", ())
    if basis_reason or opening is None:
        return missing, missing
    bounds = session_bounds(session_date_at(moment))
    basis_types = _instrument_types((basis_coverage,))
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
        return (None, "INVALID_OR_INCOMPATIBLE_OPENING_TRADE", ()), (
            None, "INVALID_OR_INCOMPATIBLE_OPENING_TRADE", ())
    price = Decimal(str(opening.price))
    session_open = (price, None, (opening.record_id,))
    if gap_basis_reason:
        return session_open, (None, gap_basis_reason, ())
    if prior_close[0] is None:
        return session_open, (None, prior_close[1], ())
    close = Decimal(str(prior_close[0]))
    if close == 0:
        return session_open, (None, "ZERO_PRIOR_CLOSE", ())
    ids = (opening.record_id, *prior_close[2])
    return session_open, ((price - close) / close, None, ids)


def build_core_price_snapshot(*, record_id: str, evaluated_at: datetime,
                              minute_history: HistoryBatch | None,
                              daily_history: HistoryBatch | None,
                              premarket_history: HistoryBatch | None,
                              opening_trade: OpeningTradeObservation | None = None) -> FeatureSnapshot:
    """Build one immutable D-090 feature snapshot from supplied history."""
    moment = as_utc(evaluated_at)
    supplied = tuple(item for item in (minute_history, daily_history, premarket_history) if item)
    if not supplied:
        raise RecordError("at least one history batch is required")
    symbol = supplied[0].request.symbol
    minute_cov = _coverage(minute_history, moment)
    daily_cov = _coverage(daily_history, moment)
    premarket_cov = _coverage(premarket_history, moment)
    basis_cov = next(item for item in (minute_cov, daily_cov, premarket_cov) if item is not None)
    minute_reason = _basis_reason(
        (minute_history,), symbol, (minute_cov,), required_interval="1m")
    minute_volume_reason = _basis_reason(
        (minute_history,), symbol, (minute_cov,), require_volume=True,
        required_interval="1m")
    daily_reason = _basis_reason(
        (daily_history,), symbol, (daily_cov,), required_interval="1d")
    premarket_reason = _basis_reason(
        (premarket_history,), symbol, (premarket_cov,), required_interval="1m")
    opening_reason = _basis_reason((supplied[0],), symbol, (basis_cov,))
    gap_reason = _basis_reason((supplied[0], daily_history), symbol, (basis_cov, daily_cov))
    minute_atr = _minute_atr(minute_history, minute_cov, moment, minute_reason)
    daily_atr, pdh, pdl, prior_close = _daily(daily_history, daily_cov, moment, daily_reason)
    vwap, _, _ = _session(minute_history, minute_cov, moment, minute_volume_reason)
    _, hod, lod = _session(minute_history, minute_cov, moment, minute_reason)
    pmh, pml = _premarket(premarket_history, premarket_cov, moment, premarket_reason)
    session_open, gap = _opening(
        opening_trade, moment, symbol, supplied[0], basis_cov, prior_close, opening_reason, gap_reason)
    specs = (
        ("ATR_1M_20_SMA_V1", minute_atr, "USD_PER_SHARE"),
        ("DAILY_ATR_14_SMA_V1", daily_atr, "USD_PER_SHARE"),
        ("SESSION_VWAP_BAR_HLC3_V1", vwap, "USD_PER_SHARE"),
        ("CURRENT_HOD_V1", hod, "USD_PER_SHARE"), ("CURRENT_LOD_V1", lod, "USD_PER_SHARE"),
        ("SESSION_OPEN_TRADE_V1", session_open, "USD_PER_SHARE"),
        ("PDH_V1", pdh, "USD_PER_SHARE"), ("PDL_V1", pdl, "USD_PER_SHARE"),
        ("PRIOR_REGULAR_CLOSE_V1", prior_close, "USD_PER_SHARE"),
        ("PMH_V1", pmh, "USD_PER_SHARE"), ("PML_V1", pml, "USD_PER_SHARE"),
        ("GAP_OPEN_V1", gap, "RATIO"),
    )
    features = tuple(_value(name, result[0], unit, result[1], result[2]) for name, result, unit in specs)
    input_ids = tuple(sorted({item for feature in features for item in feature.input_record_ids}))
    basis_types = _instrument_types((basis_cov,))
    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=next(iter(basis_types)) if len(basis_types) == 1 else "UNKNOWN",
        source="DERIVED_D090", source_time=moment,
        received_time=moment, available_time=moment, normalized_time=moment,
        session=session_date_at(moment).isoformat(), data_mode="BAR_HLC3_WITH_EXPLICIT_OPEN",
        quality="VALID",
    )
    return FeatureSnapshot(record_id=record_id, metadata=metadata, evaluated_at=moment,
                           features=features, feature_version=FEATURE_VERSION,
                           input_record_ids=input_ids)


SWING_SESSIONS = 63


@dataclass(frozen=True)
class DailySwings:
    """`DAILY_SWING_PLATEAU_2X2_V1`: state is PRESENT, KNOWN_EMPTY or UNKNOWN."""

    state: str
    highs: tuple[float, ...] = ()
    lows: tuple[float, ...] = ()
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()


def _plateaus(series: list[Decimal | None], *, high: bool) -> list[Decimal]:
    """Confirmed plateau prices; a no-trade slot (None) breaks runs and is never a neighbor."""
    found: list[Decimal] = []
    count, i = len(series), 0
    while i < count:
        level = series[i]
        if level is None:
            i += 1
            continue
        j = i
        while j + 1 < count and series[j + 1] == level:
            j += 1
        if i >= 2 and j + 2 < count:
            around = (series[i - 2], series[i - 1], series[j + 1], series[j + 2])
            if all(item is not None and (item < level if high else item > level)
                   for item in around):
                found.append(level)
        i = j + 1
    return found


def build_daily_swings(daily_history: HistoryBatch | None, evaluated_at: datetime) -> DailySwings:
    """Confirmed 2x2 plateau swings over the 63 preceding completed sessions, daily bars only."""
    moment = as_utc(evaluated_at)
    coverage = _coverage(daily_history, moment)
    reason = _basis_reason((daily_history,), daily_history.request.symbol, (coverage,),
                           required_interval="1d") if daily_history is not None else None
    if daily_history is None or coverage is None or reason:
        return DailySwings("UNKNOWN", reason=reason or "MISSING_DAILY_HISTORY")
    day = session_date_at(moment)
    days = session_dates(day - timedelta(days=150), day - timedelta(days=1))[-SWING_SESSIONS:]
    by_day = {item.interval.session: item for item in coverage.intervals}
    items = [by_day.get(value.isoformat()) for value in days]
    if (len(items) != SWING_SESSIONS or any(item is None for item in items)
            or not _ready(items) or _unexpected_in(daily_history, coverage, items)):
        return DailySwings("UNKNOWN", reason="INCOMPLETE_63_SESSION_DAILY_WINDOW")
    highs = [Decimal(str(item.bar.high)) if item.status == "FINAL" and item.bar else None
             for item in items]
    lows = [Decimal(str(item.bar.low)) if item.status == "FINAL" and item.bar else None
            for item in items]
    top = sorted(set(_plateaus(highs, high=True)))
    bottom = sorted(set(_plateaus(lows, high=False)))
    ids = tuple(item.bar.record_id for item in items if item.bar is not None)
    state = "PRESENT" if top or bottom else "KNOWN_EMPTY"
    return DailySwings(state, tuple(float(v) for v in top), tuple(float(v) for v in bottom),
                       None, ids)


@dataclass(frozen=True)
class PriorSessionProfile:
    """`PRIOR_SESSION_BAR_PROFILE_V1` (BAR_APPROX_PROFILE): PRESENT or UNKNOWN only."""

    state: str
    poc: float | None = None
    val: float | None = None
    vah: float | None = None
    reason: str | None = None
    input_record_ids: tuple[str, ...] = ()


def _unknown_profile(reason: str) -> PriorSessionProfile:
    return PriorSessionProfile("UNKNOWN", reason=reason)


def build_prior_session_profile(
        minute_history: HistoryBatch | None, daily_history: HistoryBatch | None, *,
        prior_close: float | None, daily_atr: float | None, tick: Decimal | float | None,
        evaluated_at: datetime) -> PriorSessionProfile:
    """One-minute volume profile of the immediately prior regular session.

    `prior_close` and `daily_atr` are the snapshot's `PRIOR_REGULAR_CLOSE_V1` and
    `DAILY_ATR_14_SMA_V1` at this same evaluation time, so that ATR is the one
    that closed with the prior session. Any unexplained slot, missing input or
    incompatible basis gives UNKNOWN; nothing is filled in.
    """
    from fractions import Fraction

    moment = as_utc(evaluated_at)
    if minute_history is None:
        return _unknown_profile("MISSING_MINUTE_HISTORY")
    if daily_history is None:
        return _unknown_profile("MISSING_DAILY_HISTORY")
    if prior_close is None or daily_atr is None:
        return _unknown_profile("MISSING_PRIOR_CLOSE_OR_DAILY_ATR")
    if (tick is None or isinstance(tick, bool) or not isinstance(tick, (int, float, Decimal))
            or not Decimal(str(tick)).is_finite() or Decimal(str(tick)) <= 0):
        return _unknown_profile("MISSING_OR_INVALID_TICK")
    coverage = _coverage(minute_history, moment)
    daily_cov = _coverage(daily_history, moment)
    reason = _basis_reason((minute_history, daily_history), minute_history.request.symbol,
                           (coverage, daily_cov), require_volume=True)
    if reason is None:
        reason = _basis_reason((minute_history,), minute_history.request.symbol, (coverage,),
                               require_volume=True, required_interval="1m")
    if reason is None:
        reason = _basis_reason((daily_history,), minute_history.request.symbol, (daily_cov,),
                               required_interval="1d")
    if reason or coverage is None:
        return _unknown_profile(reason or "MISSING_MINUTE_HISTORY")
    day = session_date_at(moment)
    previous = session_dates(day - timedelta(days=10), day - timedelta(days=1))
    bounds = session_bounds(previous[-1]) if previous else None
    if bounds is None:
        return _unknown_profile("NO_PRIOR_SESSION")
    opened, closed = map(as_utc, bounds)
    items = [item for item in coverage.intervals if item.interval.start >= opened
             and item.interval.end <= closed]
    slots = int((closed - opened).total_seconds() // 60)
    if (len(items) != slots or items[0].interval.start != opened
            or items[-1].interval.end != closed or not _ready(items)
            or _unexpected_in(minute_history, coverage, items)):
        return _unknown_profile("INCOMPLETE_PRIOR_SESSION_MINUTES")
    bars = [bar for bar in _traded(items) if bar.volume is not None]
    if not bars or all(bar.volume <= 0 for bar in bars):
        return _unknown_profile("NO_POSITIVE_VOLUME_TRADED_BAR")
    tick_d = Fraction(str(tick))
    close = Fraction(str(prior_close))
    per_bin = max(1, math.ceil(Fraction("0.01") * Fraction(str(daily_atr)) / tick_d))
    width = per_bin * tick_d
    low = min(Fraction(str(bar.low)) for bar in bars)
    high = max(Fraction(str(bar.high)) for bar in bars)
    origin = math.floor(low / width) * width
    count = max(1, math.ceil((high - origin) / width))
    volumes = [Fraction(0)] * count
    for bar in bars:
        b_high, b_low, vol = Fraction(str(bar.high)), Fraction(str(bar.low)), Fraction(str(bar.volume))
        if b_high == b_low:
            volumes[min(count - 1, int((b_low - origin) // width))] += vol
            continue
        for k in range(count):
            lower, upper = origin + k * width, origin + (k + 1) * width
            overlap = min(b_high, upper) - max(b_low, lower)
            if overlap > 0:
                volumes[k] += vol * overlap / (b_high - b_low)
    total = sum(volumes)

    def middle(k: int) -> Fraction:
        return origin + (Fraction(2 * k + 1, 2)) * width

    poc = min((k for k in range(count) if volumes[k] == max(volumes)),
              key=lambda k: (abs(middle(k) - close), middle(k)))
    first = last = poc
    included = volumes[poc]
    while included * 10 < total * 7:
        below, above = first - 1, last + 1
        if below < 0:
            pick = above
        elif above >= count:
            pick = below
        else:
            pick = min((below, above),
                       key=lambda k: (-volumes[k], abs(middle(k) - close), middle(k)))
        included += volumes[pick]
        first, last = min(first, pick), max(last, pick)
    ids = tuple(sorted(item.bar.record_id for item in items if item.bar is not None))
    return PriorSessionProfile("PRESENT", float(middle(poc)), float(origin + first * width),
                               float(origin + (last + 1) * width), None, ids)


__all__ = ["DailySwings", "FEATURE_VERSION", "OpeningTradeObservation", "PriorSessionProfile",
           "build_core_price_snapshot", "build_daily_swings", "build_prior_session_profile"]
