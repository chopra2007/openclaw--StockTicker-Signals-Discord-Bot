"""Frozen supplied-input relative-strength calculations for M3.3.

The functions in this module perform no I/O and choose no benchmark or sector.
Callers supply canonical bars or eligible trade observations.  Missing or
incompatible inputs stay unavailable instead of becoming a favorable value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import math

from .historical_bars import HistoryBatch, HistoryRequest
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at


FEATURE_VERSION = "M33_RELATIVE_STRENGTH_V1"
DATA_MODE = "SUPPLIED_RELATIVE_STRENGTH_INPUTS"
REFERENCE_ROLES = ("SPY", "QQQ", "SECTOR")
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in _UNKNOWN:
        raise RecordError(f"{name} must be explicit")
    return value


@dataclass(frozen=True)
class EligibleTradeObservation:
    """One supplied eligible regular-session trade and its original availability."""

    record_id: str
    symbol: str
    instrument_type: str
    session: str
    trade_time: datetime
    available_time: datetime
    price: float
    adjustment_basis: str
    price_convention: str = "USD_PER_SHARE"

    def __post_init__(self) -> None:
        for name in ("record_id", "symbol", "session", "adjustment_basis", "price_convention"):
            _text(getattr(self, name), name)
        if self.instrument_type not in ("EQUITY", "ETF"):
            raise RecordError("trade instrument type must be EQUITY or ETF")
        trade = _instant(self.trade_time, "trade_time")
        available = _instant(self.available_time, "available_time")
        if available < trade:
            raise RecordError("trade cannot be available before it happened")
        if (isinstance(self.price, bool) or not isinstance(self.price, (int, float))
                or not math.isfinite(self.price) or self.price <= 0):
            raise RecordError("trade price must be positive")
        object.__setattr__(self, "trade_time", trade)
        object.__setattr__(self, "available_time", available)


def _feature(name: str, value: Decimal | int | None, unit: str, reason: str | None,
             ids: tuple[str, ...]) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason, ids)


def _history_reason(batch: HistoryBatch | None, symbol: str) -> str | None:
    if batch is None:
        return "MISSING_MINUTE_HISTORY"
    if not isinstance(batch, HistoryBatch):
        raise RecordError("minute history must be a HistoryBatch or null")
    if batch.request.symbol != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if batch.request.interval != "1m" or batch.request.session_scope != "REGULAR":
        return "INCOMPATIBLE_HISTORY_WINDOW"
    conventions = batch.conventions
    if conventions.price != "USD_PER_SHARE" or conventions.volume != "SHARES":
        return "INCOMPATIBLE_HISTORY_UNITS"
    if any(value.strip().upper() in _UNKNOWN for value in (
            batch.source, conventions.adjustment_basis, conventions.coverage_basis,
            conventions.finality, conventions.publication)):
        return "UNKNOWN_HISTORY_BASIS"
    return None


def _first_fifteen_return(batch: HistoryBatch | None, symbol: str, instrument_type: str,
                          moment: datetime) -> tuple[Decimal | None, str | None, tuple[str, ...]]:
    reason = _history_reason(batch, symbol)
    if reason is not None:
        return None, reason, ()
    bounds = session_bounds(session_date_at(moment))
    if bounds is None:
        return None, "NO_REGULAR_SESSION", ()
    opened = as_utc(bounds[0])
    required = HistoryRequest(symbol, opened, opened + timedelta(minutes=15)).expected_intervals()
    coverage = batch.coverage_at(moment)
    by_interval = {item.interval: item for item in coverage.intervals}
    items = [by_interval.get(interval) for interval in required]
    ids = tuple(sorted({item.bar.record_id for item in items
                        if item is not None and item.bar is not None}))
    if moment < required[-1].end:
        return None, "RS15_WARMUP_INCOMPLETE", ids
    if any(item is None for item in items):
        return None, "RS15_WINDOW_NOT_REQUESTED", ids
    for item in items:
        if item.status != "FINAL":
            return None, "RS15_WINDOW_" + item.status, ids
    selected = [item.bar for item in items]
    if any(bar.metadata.revision > 0 for bar in selected):
        return None, "RS15_REVISED_INPUT", ids
    if any(bar.certified_no_trade for bar in selected):
        return None, "RS15_NO_TRADED_INTERVAL", ids
    if any(bar.metadata.instrument_type != instrument_type for bar in selected):
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    modes = {bar.metadata.data_mode for bar in selected}
    if len(modes) != 1 or any(mode.strip().upper() in _UNKNOWN for mode in modes):
        return None, "INCOMPATIBLE_DATA_MODE", ids
    if any(bar.adjustment_basis != batch.conventions.adjustment_basis for bar in selected):
        return None, "INCOMPATIBLE_ADJUSTMENT_BASIS", ids
    base = Decimal(str(selected[0].open))
    close = Decimal(str(selected[-1].close))
    return close / base - Decimal(1), None, ids


def _trade_pair(opening: EligibleTradeObservation | None,
                current: EligibleTradeObservation | None, symbol: str,
                instrument_type: str, session: str, moment: datetime,
                ) -> tuple[Decimal | None, str | None, tuple[str, ...]]:
    supplied = tuple(row for row in (opening, current) if row is not None)
    if any(not isinstance(row, EligibleTradeObservation) for row in supplied):
        raise RecordError("trade observations must use EligibleTradeObservation")
    ids = tuple(sorted(row.record_id for row in supplied))
    if opening is None or current is None:
        return None, "MISSING_OPEN_OR_CURRENT_TRADE", ids
    if any(row.symbol != symbol for row in supplied):
        return None, "INCOMPATIBLE_SYMBOL", ids
    if any(row.instrument_type != instrument_type for row in supplied):
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    if any(row.session != session for row in supplied):
        return None, "INCOMPATIBLE_SESSION", ids
    bounds = session_bounds(datetime.fromisoformat(session).date())
    if bounds is None:
        return None, "NO_REGULAR_SESSION", ids
    regular_open, regular_close = map(as_utc, bounds)
    if any(not regular_open <= row.trade_time < regular_close for row in supplied):
        return None, "TRADE_OUTSIDE_REGULAR_SESSION", ids
    if any(row.price_convention != "USD_PER_SHARE" for row in supplied):
        return None, "INCOMPATIBLE_PRICE_UNIT", ids
    if opening.adjustment_basis != current.adjustment_basis:
        return None, "INCOMPATIBLE_ADJUSTMENT_BASIS", ids
    if opening.available_time > moment or current.available_time > moment:
        return None, "TRADE_NOT_YET_AVAILABLE", ids
    if current.trade_time < opening.trade_time:
        return None, "CURRENT_TRADE_PRECEDES_OPEN", ids
    if opening.available_time - opening.trade_time > timedelta(seconds=3):
        return None, "STALE_OPENING_TRADE_AT_CAPTURE", ids
    if moment - current.trade_time > timedelta(seconds=3):
        return None, "STALE_CURRENT_TRADE", ids
    if current.trade_time > moment:
        return None, "FUTURE_CURRENT_TRADE", ids
    opened = Decimal(str(opening.price))
    latest = Decimal(str(current.price))
    return latest / opened - Decimal(1), None, ids


def build_relative_strength_snapshot(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    stock_history: HistoryBatch | None,
    spy_history: HistoryBatch | None,
    qqq_history: HistoryBatch | None,
    sector_history: HistoryBatch | None,
    stock_open: EligibleTradeObservation | None,
    stock_current: EligibleTradeObservation | None,
    reference_opens: dict[str, EligibleTradeObservation | None],
    reference_currents: dict[str, EligibleTradeObservation | None],
    sector_symbol: str | None,
) -> FeatureSnapshot:
    """Build frozen RS15 and same-instant from-open stock/reference features."""
    moment = _instant(evaluated_at, "evaluated_at")
    _text(record_id, "record_id")
    _text(symbol, "symbol")
    if instrument_type not in ("EQUITY", "ETF"):
        raise RecordError("relative-strength instrument type must be EQUITY or ETF")
    if not isinstance(reference_opens, dict) or not isinstance(reference_currents, dict):
        raise RecordError("reference trades must be supplied by role")
    unexpected = (set(reference_opens) | set(reference_currents)) - set(REFERENCE_ROLES)
    if unexpected:
        raise RecordError("reference trade role is not supported")
    if sector_symbol is not None:
        _text(sector_symbol, "sector_symbol")
        if sector_symbol in (symbol, "SPY", "QQQ"):
            raise RecordError("sector symbol must identify a separate sector reference")

    day = session_date_at(moment)
    session = day.isoformat()
    stock15 = _first_fifteen_return(stock_history, symbol, instrument_type, moment)
    features = [_feature("STOCK_RETURN_15M_OPEN_CLOSE_V1", stock15[0], "RATIO",
                         stock15[1], stock15[2])]
    histories = {"SPY": spy_history, "QQQ": qqq_history, "SECTOR": sector_history}
    symbols = {"SPY": "SPY", "QQQ": "QQQ", "SECTOR": sector_symbol}
    returns15 = {}
    for role in REFERENCE_ROLES:
        reference_symbol = symbols[role]
        if reference_symbol is None:
            result = (None, "SECTOR_MAPPING_UNAVAILABLE", ())
        else:
            result = _first_fifteen_return(histories[role], reference_symbol, "ETF", moment)
            if (stock15[0] is not None and result[0] is not None
                    and stock_history.conventions.adjustment_basis
                    != histories[role].conventions.adjustment_basis):
                result = (None, "INCOMPATIBLE_ADJUSTMENT_BASIS", result[2])
        returns15[role] = result
        features.append(_feature(f"{role}_RETURN_15M_OPEN_CLOSE_V1", result[0], "RATIO",
                                 result[1], result[2]))
        ids = tuple(sorted(set(stock15[2]) | set(result[2])))
        if stock15[0] is None or result[0] is None:
            features.append(_feature(f"RS15_{role}_CLOSE_V1", None, "RATIO",
                                     stock15[1] or result[1], ids))
        else:
            features.append(_feature(f"RS15_{role}_CLOSE_V1",
                                     stock15[0] - result[0], "RATIO", None, ids))
    spy15 = returns15["SPY"]
    rs15_ids = tuple(sorted(set(stock15[2]) | {value for result in returns15.values()
                                               for value in result[2]}))
    warm = stock15[0] is not None and spy15[0] is not None
    features.append(_feature("RS15_WARMUP_COMPLETE_V1", int(warm), "BOOLEAN", None, ()))

    stock_open_return = _trade_pair(stock_open, stock_current, symbol, instrument_type,
                                    session, moment)
    features.append(_feature("STOCK_RETURN_OPEN_V1", stock_open_return[0], "RATIO",
                             stock_open_return[1], stock_open_return[2]))
    role_symbols = symbols
    all_ids = set(rs15_ids) | set(stock_open_return[2])
    for role in REFERENCE_ROLES:
        reference_symbol = role_symbols[role]
        if reference_symbol is None:
            result = (None, "SECTOR_MAPPING_UNAVAILABLE", ())
        else:
            result = _trade_pair(reference_opens.get(role), reference_currents.get(role),
                                 reference_symbol, "ETF", session, moment)
        features.append(_feature(f"{role}_RETURN_OPEN_V1", result[0], "RATIO",
                                 result[1], result[2]))
        ids = tuple(sorted(set(stock_open_return[2]) | set(result[2])))
        cross_basis_reason = None
        reference_open = reference_opens.get(role)
        if (stock_open_return[0] is not None and result[0] is not None
                and stock_open.adjustment_basis != reference_open.adjustment_basis):
            cross_basis_reason = "INCOMPATIBLE_ADJUSTMENT_BASIS"
        if stock_open_return[0] is None or result[0] is None or cross_basis_reason:
            features.append(_feature(f"RS_OPEN_{role}_V1", None, "RATIO",
                                     stock_open_return[1] or result[1] or cross_basis_reason, ids))
        else:
            features.append(_feature(f"RS_OPEN_{role}_V1",
                                     stock_open_return[0] - result[0], "RATIO", None, ids))
        all_ids.update(result[2])

    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_M33",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=session, data_mode=DATA_MODE, quality="VALID",
    )
    return FeatureSnapshot(
        record_id=record_id, metadata=metadata, evaluated_at=moment,
        features=tuple(features), feature_version=FEATURE_VERSION,
        input_record_ids=tuple(sorted(all_ids)),
    )


__all__ = [
    "DATA_MODE", "EligibleTradeObservation", "FEATURE_VERSION", "REFERENCE_ROLES",
    "build_relative_strength_snapshot",
]
