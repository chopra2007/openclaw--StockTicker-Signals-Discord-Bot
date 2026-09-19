"""Pure Schwab REST payload normalization for canonical trade-alert records.

These helpers consume raw candle, quote-entry, and option-contract objects before
the legacy Schwab client converts them to pandas/Finnhub-shaped values.  They do
not fetch data, create IDs or times, decide freshness, or infer provider coverage.

Schwab quote sizes, option quote sizes, Greeks, and open-interest publication
timing still need provider evidence.  Values are retained as reported, but this
module does not claim a unit or as-of convention that the payload does not state.
Schwab ``volatility`` is converted from percent points (34.066) to a fraction
(0.34066), matching the existing client convention.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Mapping

from consensus_engine.trade_alerts_models import (
    Bar,
    OptionQuote,
    Quote,
    RecordError,
    SourceMetadata,
)


_NO_DATA_FLOOR = -998.0
_ABSURD_MAGNITUDE = 1e12


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecordError(f"{name} must be an object")
    return value


def _optional_number(value: Any) -> float | None:
    """Return a finite provider number, preserving zero and rejecting booleans."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(result) or result <= _NO_DATA_FLOOR or abs(result) > _ABSURD_MAGNITUDE:
        return None
    return result


def _optional_nonnegative(value: Any) -> float | None:
    result = _optional_number(value)
    return result if result is not None and result >= 0 else None


def _optional_count(value: Any) -> int | None:
    result = _optional_nonnegative(value)
    if result is None or not result.is_integer():
        return None
    return int(result)


def _optional_bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _epoch_ms(value: Any, name: str) -> datetime | None:
    """Convert an exact positive integer epoch-millisecond value to UTC."""
    if value is None or (type(value) is int and value == 0):
        return None
    if type(value) is not int or value < 0:
        raise RecordError(f"{name} must be a positive integer epoch-millisecond timestamp or null")
    try:
        seconds, milliseconds = divmod(value, 1000)
        return datetime.fromtimestamp(seconds, tz=timezone.utc) + timedelta(milliseconds=milliseconds)
    except (OverflowError, OSError, ValueError) as exc:
        raise RecordError(f"{name} is outside the supported timestamp range") from exc


def _validate_context(metadata: SourceMetadata, raw_symbol: str, expected_symbol: str) -> None:
    if metadata.source != "SCHWAB":
        raise RecordError("Schwab normalization requires source SCHWAB")
    if not isinstance(raw_symbol, str) or not raw_symbol:
        raise RecordError("raw_symbol must identify the Schwab response entry")
    if raw_symbol != expected_symbol or metadata.instrument_id != expected_symbol:
        raise RecordError("Schwab payload identity does not match caller context")


def _validate_delayed(raw: Mapping[str, Any], delayed: bool | None) -> None:
    if "isDelayed" not in raw:
        return
    raw_delayed = raw["isDelayed"]
    if type(raw_delayed) is not bool:
        raise RecordError("raw Schwab delayed flag must be true or false")
    if raw_delayed is not delayed:
        raise RecordError("raw Schwab delayed flag conflicts with caller context")


def _validate_source_time(metadata: SourceMetadata, event_time: datetime | None) -> None:
    """Require source_time to equal the raw event time convention used here.

    Quotes and options use their raw quote timestamp, falling back to trade time
    only when quote time is absent. Bars use the raw candle timestamp. If the
    payload has no such time, source_time must remain unknown instead of becoming
    a receipt or normalization time.
    """
    if metadata.source_time != event_time:
        raise RecordError("metadata source_time does not match the raw Schwab event time")


def _validate_event_times(metadata: SourceMetadata, *times: datetime | None) -> None:
    for value in times:
        if value is not None and value > metadata.available_time:
            raise RecordError("raw Schwab event time cannot follow supplied availability")


def _validate_occ_contract(
    contract_id: str, expiry: date, option_type: str, strike: float | None,
) -> None:
    """Check the fixed OCC-style date/right/strike suffix Schwab already returns.

    The root is intentionally not compared with the underlying. Adjusted contracts
    can use a numbered root such as ``AAPL1`` while retaining ``AAPL`` underneath.
    """
    compact = contract_id.replace(" ", "")
    if len(compact) < 16:
        raise RecordError("Schwab option symbol is not an OCC-style contract symbol")
    expiry_code, right, strike_code = compact[-15:-9], compact[-9], compact[-8:]
    if not expiry_code.isdigit() or right not in "CP" or not strike_code.isdigit():
        raise RecordError("Schwab option symbol is not an OCC-style contract symbol")
    if expiry_code != expiry.strftime("%y%m%d"):
        raise RecordError("Schwab option symbol expiry contradicts caller context")
    expected_right = "C" if option_type == "CALL" else "P" if option_type == "PUT" else ""
    if right != expected_right:
        raise RecordError("Schwab option symbol side contradicts caller context")
    if strike is None or not math.isclose(int(strike_code) / 1000.0, strike, rel_tol=0.0, abs_tol=1e-9):
        raise RecordError("Schwab option symbol strike contradicts raw contract")


def _validate_quote_state(
    metadata: SourceMetadata,
    status: str,
    delayed: bool | None,
    bid: float | None,
    ask: float | None,
) -> None:
    if bid is not None and ask is not None and bid > ask:
        raise RecordError("crossed Schwab quotes cannot be normalized")
    if status == "VALID":
        if metadata.quality != "VALID" or delayed is not False:
            raise RecordError("VALID Schwab quotes require VALID quality and explicit non-delayed data")
        if bid is None or ask is None:
            raise RecordError("VALID Schwab quotes require bid and ask")
        if bid == 0 or ask == 0:
            raise RecordError("VALID Schwab quotes require positive bid and ask")
    if delayed is True and (status == "VALID" or metadata.quality == "VALID"):
        raise RecordError("delayed Schwab quotes cannot be labeled VALID")


def normalize_schwab_bar(
    candle: Mapping[str, Any],
    *,
    record_id: str,
    metadata: SourceMetadata,
    raw_symbol: str,
    start_time: datetime,
    end_time: datetime,
    is_final: bool = False,
    adjustment_basis: str = "UNKNOWN",
    price_convention: str = "SCHWAB_REPORTED",
    volume_convention: str = "SCHWAB_REPORTED_UNITS_UNKNOWN",
) -> Bar:
    """Normalize one raw ``/pricehistory`` candle.

    The raw ``datetime`` is retained as the provider event time. The caller
    supplies ``start_time``, interval-derived ``end_time``, and finality because
    the payload fixture does not prove provider start/end stamp semantics.
    Incomplete candles are rejected rather than turned into a made-up no-trade
    interval.
    """
    raw = _object(candle, "candle")
    _validate_context(metadata, raw_symbol, metadata.instrument_id)
    if metadata.instrument_type == "OPTION":
        raise RecordError("Schwab bar metadata cannot identify an option")
    raw_time = _epoch_ms(raw.get("datetime"), "candle.datetime")
    if raw_time is None:
        raise RecordError("Schwab candle datetime is required")
    _validate_source_time(metadata, raw_time)
    _validate_event_times(metadata, raw_time)
    values = {name: _optional_nonnegative(raw.get(name)) for name in ("open", "high", "low", "close", "volume")}
    if any(value is None for value in values.values()):
        raise RecordError("Schwab traded candles require finite OHLCV values")
    return Bar(
        record_id=record_id,
        metadata=metadata,
        start_time=start_time,
        end_time=end_time,
        is_final=is_final,
        open=values["open"],
        high=values["high"],
        low=values["low"],
        close=values["close"],
        volume=values["volume"],
        adjustment_basis=adjustment_basis,
        price_convention=price_convention,
        volume_convention=volume_convention,
        certified_no_trade=False,
    )


def normalize_schwab_quote(
    entry: Mapping[str, Any],
    *,
    record_id: str,
    metadata: SourceMetadata,
    raw_symbol: str,
    status: str,
    delayed: bool | None,
) -> Quote:
    """Normalize one raw ``/quotes`` entry without legacy regular-last fallback.

    Canonical ``last`` uses raw ``quote.lastPrice`` with ``quote.tradeTime``.
    The legacy client's ``c`` field may still prefer ``regularMarketLastPrice``;
    this function does not alter that older behavior. Size units remain the raw
    Schwab integers because a lot/share convention is not established here.
    """
    raw = _object(entry, "quote entry")
    _validate_context(metadata, raw_symbol, metadata.instrument_id)
    if metadata.instrument_type == "OPTION":
        raise RecordError("Schwab stock quote metadata cannot identify an option")
    entry_symbol = raw.get("symbol")
    if entry_symbol is not None and entry_symbol != raw_symbol:
        raise RecordError("Schwab quote entry symbol does not match caller context")
    _validate_delayed(raw, delayed)
    quote = _object(raw.get("quote", {}), "quote entry.quote")
    quote_time = _epoch_ms(quote.get("quoteTime"), "quote.quoteTime")
    trade_time = _epoch_ms(quote.get("tradeTime"), "quote.tradeTime")
    _validate_event_times(metadata, quote_time, trade_time)
    event_time = quote_time if quote_time is not None else trade_time
    _validate_source_time(metadata, event_time)
    bid = _optional_nonnegative(quote.get("bidPrice"))
    ask = _optional_nonnegative(quote.get("askPrice"))
    _validate_quote_state(metadata, status, delayed, bid, ask)
    if status == "VALID" and quote_time is None:
        raise RecordError("VALID Schwab quotes require a quote timestamp")
    return Quote(
        record_id=record_id,
        metadata=metadata,
        quote_time=quote_time,
        trade_time=trade_time,
        bid=bid,
        ask=ask,
        last=_optional_nonnegative(quote.get("lastPrice")),
        last_size=_optional_count(quote.get("lastSize")),
        bid_size=_optional_count(quote.get("bidSize")),
        ask_size=_optional_count(quote.get("askSize")),
        status=status,
        delayed=delayed,
    )


def normalize_schwab_option_quote(
    contract: Mapping[str, Any],
    *,
    record_id: str,
    metadata: SourceMetadata,
    raw_symbol: str,
    underlying_id: str,
    expiry: date,
    option_type: str,
    status: str,
    delayed: bool | None,
    open_interest_time: datetime | None = None,
) -> OptionQuote:
    """Normalize one raw contract from a Schwab REST option-chain map.

    Expiry and side are supplied from the enclosing response-map context and
    must agree with contract fields when those fields are present. Open-interest
    timing is caller supplied because this payload has no proven as-of field.
    Greek signs are preserved. Unknown numeric sentinels become ``None``.
    """
    raw = _object(contract, "option contract")
    contract_id = raw.get("symbol")
    if not isinstance(contract_id, str) or not contract_id:
        raise RecordError("Schwab option symbol is required")
    _validate_context(metadata, raw_symbol, contract_id)
    if metadata.instrument_type not in ("OPTION", "UNKNOWN"):
        raise RecordError("Schwab option metadata must identify an option")
    if option_type not in ("CALL", "PUT"):
        raise RecordError("Schwab option side context must be CALL or PUT")
    raw_side = raw.get("putCall")
    if raw_side is not None and raw_side != option_type:
        raise RecordError("Schwab option side does not match map context")
    if not isinstance(expiry, date) or isinstance(expiry, datetime):
        raise RecordError("option expiry context must be a date")
    raw_underlying = raw.get("underlyingSymbol")
    if raw_underlying is not None and raw_underlying != underlying_id:
        raise RecordError("Schwab option underlying does not match caller context")
    _validate_delayed(raw, delayed)
    strike = _optional_nonnegative(raw.get("strikePrice"))
    _validate_occ_contract(contract_id, expiry, option_type, strike)
    quote_time = _epoch_ms(raw.get("quoteTimeInLong"), "option.quoteTimeInLong")
    trade_time = _epoch_ms(raw.get("tradeTimeInLong"), "option.tradeTimeInLong")
    _validate_event_times(metadata, quote_time, trade_time, open_interest_time)
    event_time = quote_time if quote_time is not None else trade_time
    _validate_source_time(metadata, event_time)
    bid = _optional_nonnegative(raw.get("bid"))
    ask = _optional_nonnegative(raw.get("ask"))
    _validate_quote_state(metadata, status, delayed, bid, ask)
    if status == "VALID" and quote_time is None:
        raise RecordError("VALID Schwab option quotes require a quote timestamp")
    volatility = _optional_number(raw.get("volatility"))
    implied_volatility = volatility / 100.0 if volatility is not None and volatility > 0 else None
    deliverable = raw.get("deliverableNote")
    if not isinstance(deliverable, str) or not deliverable.strip():
        deliverable = None
    return OptionQuote(
        record_id=record_id,
        metadata=metadata,
        contract_id=contract_id,
        underlying_id=underlying_id,
        expiry=expiry,
        strike=strike,  # type: ignore[arg-type]
        option_type=option_type,
        multiplier=_optional_nonnegative(raw.get("multiplier")),
        deliverable=deliverable,
        quote_time=quote_time,
        trade_time=trade_time,
        bid=bid,
        ask=ask,
        last=_optional_nonnegative(raw.get("last")),
        bid_size=_optional_count(raw.get("bidSize")),
        ask_size=_optional_count(raw.get("askSize")),
        implied_volatility=implied_volatility,
        delta=_optional_number(raw.get("delta")),
        gamma=_optional_number(raw.get("gamma")),
        theta=_optional_number(raw.get("theta")),
        vega=_optional_number(raw.get("vega")),
        rho=_optional_number(raw.get("rho")),
        open_interest=_optional_count(raw.get("openInterest")),
        open_interest_time=open_interest_time,
        volume=_optional_count(raw.get("totalVolume")),
        non_standard=_optional_bool(raw.get("nonStandard")),
        status=status,
        delayed=delayed,
    )
