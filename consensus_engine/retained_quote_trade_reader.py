"""M9.1CZ retained training-nine BBO-1m and trade reader.

The reader accepts already-decoded Databento rows and converts only the frozen
D-107 training tickers into canonical ``Quote`` records.  Every result keeps
the retained file hash and zero-based row position, plus the provider's raw
timestamps, sequence, publisher and instrument ids.  Held-out symbols are
skipped before canonical records are built.

For BBO interval rows, ``ts_recv`` is the interval end and therefore the quote
time.  ``ts_event`` is only the last trade time and may carry Databento's
unsigned null timestamp when no trade has occurred in the session.  That null
stays ``None``; it is never replaced with the interval end.

Original availability, correction state and finality are not present in these
retained files.  They remain explicit ``UNKNOWN`` gaps, and canonical metadata
quality therefore never becomes ``VALID``.  This module does not construct
events, calculate fills or returns, or open held-out results.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping
from zoneinfo import ZoneInfo

from .core17_bar_loader import reverse_symbol_map, verify_retained_files
from .databento_minute_bars import DATASET_IDENTITIES, PRICE_SCALE
from .search_run_config import TRAINING_TICKERS
from .trade_alerts_models import Quote, RecordError, SourceMetadata


_PACIFIC = ZoneInfo("America/Los_Angeles")
TRAINING_INSTRUMENT_TYPES = {
    ticker: ("ETF" if ticker in {"SPY", "QQQ", "XLV", "USO"} else "EQUITY")
    for ticker in TRAINING_TICKERS
}
SUPPORTED_SCHEMAS = frozenset({"bbo-1m", "trades"})
# Databento DBN UNDEF_TIMESTAMP: UINT64_MAX.
UNDEF_TIMESTAMP_NS = 2**64 - 1


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise RecordError(f"{name} must be a non-negative integer")
    return value


def _instant(nanoseconds: Any, name: str) -> datetime:
    value = _count(nanoseconds, name)
    seconds, remainder = divmod(value, PRICE_SCALE)
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=remainder // 1_000)
    except (OverflowError, OSError, ValueError) as exc:
        raise RecordError(f"{name} is outside the supported timestamp range") from exc


def _price(value: Any, name: str, *, optional: bool = False) -> float | None:
    if optional:
        if value is None:
            return None
        if type(value) is int and (value <= 0 or value == 2**63 - 1):
            return None
    if type(value) is not int or value <= 0:
        raise RecordError(f"{name} must be a positive fixed-point integer")
    result = value / PRICE_SCALE
    if not math.isfinite(result):
        raise RecordError(f"{name} must be finite")
    return result


def _code(value: Any, name: str) -> str:
    result = str(value)
    if not result:
        raise RecordError(f"{name} must not be empty")
    return result


@dataclass(frozen=True)
class RetainedQuoteTradeRecord:
    """Canonical record plus the exact retained file and decoded-row identity."""

    schema: str
    dataset: str
    publisher_identity: str
    venue_identity: str
    source_file_sha256: str
    source_row_index: int
    raw_publisher_id: int
    raw_instrument_id: int
    raw_ts_event_ns: int
    raw_ts_recv_ns: int
    raw_sequence: int
    raw_action: str | None
    raw_side: str
    provider_condition: str
    original_availability: str
    correction_state: str
    finality: str
    quote: Quote

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "dataset": self.dataset,
            "publisher_identity": self.publisher_identity,
            "venue_identity": self.venue_identity,
            "source_file_sha256": self.source_file_sha256,
            "source_row_index": self.source_row_index,
            "raw_publisher_id": self.raw_publisher_id,
            "raw_instrument_id": self.raw_instrument_id,
            "raw_ts_event_ns": self.raw_ts_event_ns,
            "raw_ts_recv_ns": self.raw_ts_recv_ns,
            "raw_sequence": self.raw_sequence,
            "raw_action": self.raw_action, "raw_side": self.raw_side,
            "provider_condition": self.provider_condition,
            "original_availability": self.original_availability,
            "correction_state": self.correction_state, "finality": self.finality,
            "quote": self.quote.as_dict(),
        }


def iter_quote_trade_records(
    rows: Iterable[Any], *, schema: str, dataset: str, source_file_sha256: str,
    instrument_symbols: Mapping[int, str], condition_by_date: Mapping[str, str],
) -> Iterator[RetainedQuoteTradeRecord]:
    """Convert decoded rows while keeping held-out symbols sealed."""
    if schema not in SUPPORTED_SCHEMAS:
        raise RecordError("retained quote/trade schema is unsupported")
    if dataset != "EQUS.MINI":
        raise RecordError("retained quote/trade dataset must be EQUS.MINI")
    if (len(source_file_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_file_sha256)):
        raise RecordError("source_file_sha256 must be a lowercase SHA-256 value")

    publisher, venue = DATASET_IDENTITIES[dataset]
    for row_index, row in enumerate(rows):
        instrument_id = _count(row.instrument_id, "instrument_id")
        symbol = instrument_symbols.get(instrument_id)
        if symbol is None:
            raise RecordError(
                f"row {row_index} instrument_id {instrument_id} is not in the resolved symbol map"
            )
        if symbol not in TRAINING_INSTRUMENT_TYPES:
            continue

        raw_ts_event_ns = _count(row.ts_event, "ts_event")
        ts_recv_ns = _count(row.ts_recv, "ts_recv")
        received_time = _instant(ts_recv_ns, "ts_recv")
        if schema == "bbo-1m" and raw_ts_event_ns == UNDEF_TIMESTAMP_NS:
            ts_event_ns = None
            event_time = None
        elif schema == "trades" and raw_ts_event_ns == UNDEF_TIMESTAMP_NS:
            raise RecordError(f"row {row_index} trade event time is undefined")
        else:
            ts_event_ns = raw_ts_event_ns
            event_time = _instant(ts_event_ns, "ts_event")
        if ts_event_ns is not None and ts_recv_ns < ts_event_ns:
            raise RecordError(f"row {row_index} receipt precedes its event time")
        record_time = received_time if schema == "bbo-1m" else event_time
        if schema == "bbo-1m" and ts_event_ns is None:
            # The provider emits no-trade initialization rows just before the
            # Pacific calendar day changes.  Their UTC interval date is the
            # retained trading date; the prior Pacific date is not their
            # session and must not borrow that date's condition.
            session = received_time.date().isoformat()
        else:
            session = record_time.astimezone(_PACIFIC).date().isoformat()
        condition = condition_by_date.get(session)
        if condition not in ("available", "degraded"):
            raise RecordError(f"row {row_index} session {session} is not in the retained condition list")
        provider_condition = "AVAILABLE" if condition == "available" else "DEGRADED"
        quality = "UNKNOWN" if provider_condition == "AVAILABLE" else "DEGRADED_PROXY"
        sequence = _count(row.sequence, "sequence")
        record_id = f"core17-1y:{source_file_sha256}:{schema}:{row_index}"
        metadata = SourceMetadata(
            instrument_id=symbol,
            instrument_type=TRAINING_INSTRUMENT_TYPES[symbol],
            source=dataset,
            source_time=record_time,
            received_time=received_time,
            available_time=received_time,
            normalized_time=received_time,
            session=session,
            sequence=sequence,
            revision=0,
            data_mode=f"RETAINED_DBN_{schema.upper().replace('-', '_')}",
            quality=quality,
        )
        if schema == "trades":
            assert event_time is not None
            quote = Quote(
                record_id=record_id, metadata=metadata,
                quote_time=None, trade_time=event_time,
                bid=None, ask=None, last=_price(row.price, "price"),
                last_size=_count(row.size, "size"), bid_size=None, ask_size=None,
                status="VALID",
            )
            action = _code(row.action, "action")
        else:
            bid = _price(row.bid_px_00, "bid_px_00", optional=True)
            ask = _price(row.ask_px_00, "ask_px_00", optional=True)
            if bid is not None and ask is not None and bid > ask:
                raise RecordError(f"row {row_index} has a crossed top-of-book quote")
            status = "VALID" if bid is not None and ask is not None else (
                "NO_TWO_SIDED" if bid is not None or ask is not None else "MISSING"
            )
            quote = Quote(
                record_id=record_id, metadata=metadata,
                quote_time=received_time, trade_time=event_time,
                bid=bid, ask=ask, last=None, last_size=None,
                bid_size=_count(row.bid_sz_00, "bid_sz_00"),
                ask_size=_count(row.ask_sz_00, "ask_sz_00"), status=status,
            )
            action = None
        yield RetainedQuoteTradeRecord(
            schema=schema, dataset=dataset, publisher_identity=publisher,
            venue_identity=venue, source_file_sha256=source_file_sha256,
            source_row_index=row_index, raw_publisher_id=_count(row.publisher_id, "publisher_id"),
            raw_instrument_id=instrument_id, raw_ts_event_ns=raw_ts_event_ns,
            raw_ts_recv_ns=ts_recv_ns, raw_sequence=sequence, raw_action=action,
            raw_side=_code(row.side, "side"), provider_condition=provider_condition,
            original_availability="UNKNOWN", correction_state="UNKNOWN", finality="UNKNOWN",
            quote=quote,
        )


def open_retained_quote_trade_file(
    job_dir: Path, dbn_filename: str, *, schema: str,
) -> Iterator[RetainedQuoteTradeRecord]:
    """Verify, decode and convert one retained BBO-1m or trades file offline."""
    import databento as db

    verified = {item.filename: item for item in verify_retained_files(job_dir / "manifest.json", job_dir)}
    if dbn_filename not in verified:
        raise RecordError(f"{dbn_filename} is not a verified file in {job_dir}")
    store = db.DBNStore.from_file(job_dir / dbn_filename)
    if store.schema != schema:
        raise RecordError("retained file schema does not match the requested reader")
    condition_entries = json.loads((job_dir / "condition.json").read_text())
    conditions = {entry["date"]: entry["condition"] for entry in condition_entries}
    yield from iter_quote_trade_records(
        store, schema=schema, dataset=store.dataset,
        source_file_sha256=verified[dbn_filename].sha256,
        instrument_symbols=reverse_symbol_map(store.symbology), condition_by_date=conditions,
    )


__all__ = [
    "RetainedQuoteTradeRecord", "SUPPORTED_SCHEMAS", "TRAINING_INSTRUMENT_TYPES",
    "UNDEF_TIMESTAMP_NS",
    "iter_quote_trade_records", "open_retained_quote_trade_file",
]
