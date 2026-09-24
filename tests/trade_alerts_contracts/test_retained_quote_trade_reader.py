"""M9.1CZ retained training-nine quote/trade reader contracts."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_quote_trade_reader import (
    TRAINING_INSTRUMENT_TYPES, UNDEF_TIMESTAMP_NS, iter_quote_trade_records,
)
from consensus_engine.search_run_config import TRAINING_TICKERS
from consensus_engine.trade_alerts_models import RecordError


UTC = timezone.utc
EVENT = datetime(2026, 8, 21, 13, 30, 0, 123456, tzinfo=UTC)
EVENT_NS = int(EVENT.timestamp() * 1_000_000_000) + 789
RECV_NS = EVENT_NS + 2_000
HASH = "a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3"
SYMBOLS = {1: "NVDA", 2: "SPY", 3: "GOOGL"}
CONDITIONS = {"2026-08-21": "available"}


@dataclass(frozen=True)
class FakeTrade:
    instrument_id: int = 1
    ts_event: int = EVENT_NS
    ts_recv: int = RECV_NS
    publisher_id: int = 7
    sequence: int = 11
    action: str = "T"
    side: str = "B"
    price: int = 100_250_000_000
    size: int = 200


@dataclass(frozen=True)
class FakeBbo:
    instrument_id: int = 2
    ts_event: int = EVENT_NS
    ts_recv: int = RECV_NS
    publisher_id: int = 7
    sequence: int = 12
    side: str = "N"
    bid_px_00: int = 100_000_000_000
    ask_px_00: int = 100_100_000_000
    bid_sz_00: int = 300
    ask_sz_00: int = 400


def _read(rows, schema, **changes):
    args = dict(
        schema=schema, dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols=SYMBOLS, condition_by_date=CONDITIONS,
    )
    args.update(changes)
    return tuple(iter_quote_trade_records(rows, **args))


def test_frozen_training_scope_and_types_are_exact():
    assert tuple(TRAINING_INSTRUMENT_TYPES) == TRAINING_TICKERS
    assert TRAINING_INSTRUMENT_TYPES["SPY"] == "ETF"
    assert TRAINING_INSTRUMENT_TYPES["NVDA"] == "EQUITY"


def test_trade_row_becomes_canonical_trade_with_exact_source_identity():
    record = _read([FakeTrade()], "trades")[0]
    assert record.schema == "trades"
    assert record.source_file_sha256 == HASH
    assert record.source_row_index == 0
    assert record.raw_ts_event_ns == EVENT_NS
    assert record.raw_ts_recv_ns == RECV_NS
    assert record.raw_sequence == 11
    assert record.raw_action == "T"
    assert record.quote.trade_time == EVENT
    assert record.quote.last == 100.25
    assert record.quote.last_size == 200
    assert record.quote.metadata.quality == "UNKNOWN"
    assert record.original_availability == record.correction_state == record.finality == "UNKNOWN"


def test_bbo_row_becomes_canonical_two_sided_quote():
    record = _read([FakeBbo()], "bbo-1m")[0]
    assert record.quote.quote_time == EVENT.replace(microsecond=123458)
    assert record.quote.trade_time == EVENT
    assert record.quote.bid == 100.0
    assert record.quote.ask == 100.1
    assert record.quote.bid_size == 300
    assert record.quote.ask_size == 400
    assert record.quote.status == "VALID"
    assert record.quote.metadata.instrument_type == "ETF"


def test_bbo_null_last_trade_time_stays_missing_and_uses_interval_end_for_quote():
    row = FakeBbo(ts_event=UNDEF_TIMESTAMP_NS)
    record = _read([row], "bbo-1m")[0]
    interval_end = EVENT.replace(microsecond=123458)
    assert record.raw_ts_event_ns == UNDEF_TIMESTAMP_NS
    assert record.raw_ts_recv_ns == RECV_NS
    assert record.quote.metadata.source_time == interval_end
    assert record.quote.quote_time == interval_end
    assert record.quote.trade_time is None
    assert record.quote.status == "VALID"
    assert record.as_dict()["raw_ts_event_ns"] == UNDEF_TIMESTAMP_NS


def test_empty_bbo_row_preserves_missing_book_and_last_trade_fields():
    undefined_price = 2**63 - 1
    record = _read([FakeBbo(
        ts_event=UNDEF_TIMESTAMP_NS,
        bid_px_00=undefined_price,
        ask_px_00=undefined_price,
        bid_sz_00=0,
        ask_sz_00=0,
    )], "bbo-1m")[0]
    assert record.quote.quote_time is not None
    assert record.quote.trade_time is None
    assert record.quote.bid is None
    assert record.quote.ask is None
    assert record.quote.bid_size == 0
    assert record.quote.ask_size == 0
    assert record.quote.status == "MISSING"


def test_bbo_null_initialization_uses_provider_date_not_prior_pacific_date():
    interval_end = datetime(2025, 10, 6, 5, 57, tzinfo=UTC)
    interval_end_ns = int(interval_end.timestamp() * 1_000_000_000)
    record = _read(
        [FakeBbo(ts_event=UNDEF_TIMESTAMP_NS, ts_recv=interval_end_ns)],
        "bbo-1m",
        condition_by_date={"2025-10-06": "available"},
    )[0]
    assert record.quote.quote_time == interval_end
    assert record.quote.trade_time is None
    assert record.quote.metadata.session == "2025-10-06"


def test_bbo_null_initialization_does_not_borrow_prior_date_condition():
    interval_end = datetime(2025, 10, 7, 5, 57, tzinfo=UTC)
    interval_end_ns = int(interval_end.timestamp() * 1_000_000_000)
    record = _read(
        [FakeBbo(ts_event=UNDEF_TIMESTAMP_NS, ts_recv=interval_end_ns)],
        "bbo-1m",
        condition_by_date={"2025-10-06": "degraded", "2025-10-07": "available"},
    )[0]
    assert record.quote.metadata.session == "2025-10-07"
    assert record.provider_condition == "AVAILABLE"
    assert record.quote.metadata.quality == "UNKNOWN"


def test_bbo_session_comes_from_interval_end_not_last_trade_time():
    prior_day = EVENT_NS - 14 * 60 * 60 * 1_000_000_000
    record = _read([FakeBbo(ts_event=prior_day)], "bbo-1m")[0]
    assert record.quote.metadata.session == "2026-08-21"


@pytest.mark.parametrize("received_ns", [RECV_NS, UNDEF_TIMESTAMP_NS])
def test_trade_rejects_null_event_time_instead_of_inventing_one(received_ns):
    with pytest.raises(RecordError, match="trade event time is undefined"):
        _read([FakeTrade(ts_event=UNDEF_TIMESTAMP_NS, ts_recv=received_ns)], "trades")


def test_held_out_rows_are_skipped_before_canonical_conversion():
    held_out = FakeTrade(instrument_id=3, price=0, ts_recv=0)
    assert _read([held_out], "trades") == ()


@pytest.mark.parametrize(("rows", "schema", "match"), [
    ([FakeTrade(instrument_id=999)], "trades", "resolved symbol map"),
    ([FakeTrade(ts_recv=EVENT_NS - 1)], "trades", "receipt precedes"),
    ([FakeBbo(ts_event=RECV_NS + 1)], "bbo-1m", "receipt precedes"),
    ([FakeBbo(bid_px_00=101_000_000_000, ask_px_00=100_000_000_000)], "bbo-1m", "crossed"),
])
def test_bad_identity_time_or_book_is_rejected(rows, schema, match):
    with pytest.raises(RecordError, match=match):
        _read(rows, schema)


def test_missing_side_stays_missing_instead_of_becoming_zero():
    undefined = 2**63 - 1
    record = _read([FakeBbo(bid_px_00=undefined)], "bbo-1m")[0]
    assert record.quote.bid is None
    assert record.quote.ask == 100.1
    assert record.quote.status == "NO_TWO_SIDED"


def test_degraded_date_stays_degraded_and_never_valid():
    record = _read(
        [FakeTrade()], "trades", condition_by_date={"2026-08-21": "degraded"},
    )[0]
    assert record.provider_condition == "DEGRADED"
    assert record.quote.metadata.quality == "DEGRADED_PROXY"


def test_recorded_reader_proof_is_deterministic_and_contains_both_schemas():
    early_interval_end = datetime(2025, 10, 6, 5, 57, tzinfo=UTC)
    early_interval_end_ns = int(early_interval_end.timestamp() * 1_000_000_000)
    records = _read([FakeTrade()], "trades") + _read([
        FakeBbo(),
        FakeBbo(ts_event=UNDEF_TIMESTAMP_NS),
        FakeBbo(ts_event=UNDEF_TIMESTAMP_NS, bid_px_00=2**63 - 1,
                ask_px_00=2**63 - 1, bid_sz_00=0, ask_sz_00=0),
    ], "bbo-1m") + _read([
        FakeBbo(ts_event=UNDEF_TIMESTAMP_NS, ts_recv=early_interval_end_ns),
    ], "bbo-1m", condition_by_date={"2025-10-06": "available"})
    proof = {
        "scope": list(TRAINING_TICKERS),
        "held_out_opened": False,
        "events_derived": False,
        "returns_calculated": False,
        "gap_dependent_rules": "OFF_UNTESTED",
        "records": [record.as_dict() for record in records],
    }
    rendered = json.dumps(proof, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91cz-retained-quote-trade-reader-proof.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    decoded = json.loads(rendered)
    assert decoded["records"][2]["raw_ts_event_ns"] == UNDEF_TIMESTAMP_NS
    assert decoded["records"][2]["quote"]["trade_time"] is None
    assert decoded["records"][3]["quote"]["status"] == "MISSING"
    assert decoded["records"][4]["quote"]["metadata"]["session"] == "2025-10-06"
    assert {record.schema for record in records} == {"bbo-1m", "trades"}
