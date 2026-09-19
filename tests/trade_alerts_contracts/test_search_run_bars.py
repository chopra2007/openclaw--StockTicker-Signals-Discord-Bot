"""M9.1W part 1: per-ticker, per-session bar grouping for the stage-1 search."""

from dataclasses import dataclass
from datetime import datetime, timezone
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core17_bar_loader import iter_ohlcv_1m_records
from consensus_engine.search_run_bars import group_session_bars
from consensus_engine.trade_alerts_models import RecordError


START = datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc)
TS_NS = int(START.timestamp()) * 1_000_000_000
MINUTE_NS = 60 * 1_000_000_000
SYMBOLS = {1: "SPY", 2: "QQQ", 3: "GOOGL"}
HASH = "a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3"


@dataclass(frozen=True)
class Row:
    instrument_id: int
    ts_event: int
    open: int = 100_000_000_000
    high: int = 102_000_000_000
    low: int = 99_000_000_000
    close: int = 101_000_000_000
    volume: int = 10
    publisher_id: int = 1


def _records(rows, condition="available"):
    return list(iter_ohlcv_1m_records(
        rows, dataset="EQUS.MINI", source_file_sha256=HASH, instrument_symbols=SYMBOLS,
        condition_by_date={"2026-08-21": condition}, record_id_prefix="t",
    ))


def test_groups_by_ticker_and_session_in_time_order():
    rows = [Row(1, TS_NS + MINUTE_NS), Row(1, TS_NS), Row(2, TS_NS)]
    grouped = group_session_bars(_records(rows), ["SPY", "QQQ"])
    spy = grouped.bars_for("SPY", "2026-08-21")
    assert [bar.start_time for bar in spy] == [START, START.replace(minute=31)]
    assert len(grouped.bars_for("QQQ", "2026-08-21")) == 1
    assert grouped.degraded_sessions == ()


def test_other_tickers_are_counted_and_dropped():
    grouped = group_session_bars(_records([Row(1, TS_NS), Row(3, TS_NS)]), ["SPY"])
    assert grouped.ignored_ticker_count == 1
    with pytest.raises(RecordError, match="no usable bars"):
        grouped.bars_for("GOOGL", "2026-08-21")


def test_duplicate_minute_is_rejected():
    with pytest.raises(RecordError, match="duplicate bar"):
        group_session_bars(_records([Row(1, TS_NS), Row(1, TS_NS)]), ["SPY"])


def test_degraded_session_is_held_back_and_listed():
    grouped = group_session_bars(_records([Row(1, TS_NS)], condition="degraded"), ["SPY"])
    assert grouped.sessions == ()
    assert grouped.degraded_sessions == (("SPY", "2026-08-21"),)


def test_ticker_list_must_be_non_empty_and_unique():
    with pytest.raises(RecordError):
        group_session_bars([], [])
    with pytest.raises(RecordError):
        group_session_bars([], ["SPY", "SPY"])


def test_non_record_input_is_rejected():
    with pytest.raises(RecordError, match="DatabentoMinuteRecord"):
        group_session_bars([object()], ["SPY"])


from consensus_engine.historical_bars import HistoryConventions
from consensus_engine.or_failure_rev_research_adapter import (
    build_or_failure_rev_bar_inputs_from_research,
)
from consensus_engine.search_run_bars import history_batch_for

CONVENTIONS = HistoryConventions(
    timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_TEST",
    price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_TEST",
    finality="UNKNOWN", publication="SYNTHETIC_TEST", evidence_reference="synthetic-test",
)


def test_history_batch_feeds_a_research_adapter():
    grouped = group_session_bars(
        _records([Row(1, TS_NS), Row(1, TS_NS + MINUTE_NS)]), ["SPY"])
    batch = history_batch_for(grouped, "SPY", "2026-08-21", CONVENTIONS)
    assert batch.request.symbol == "SPY" and len(batch.bars) == 2
    inputs = build_or_failure_rev_bar_inputs_from_research(
        record_id_prefix="t", evaluated_at=START.replace(minute=32),
        symbol="SPY", instrument_type="ETF", minute_history=batch)
    assert inputs.last_trade.price == 101.0
    assert inputs.label["provisional_intervals"] == 2


def test_history_batch_does_not_invent_conventions():
    grouped = group_session_bars(_records([Row(1, TS_NS)]), ["SPY"])
    batch = history_batch_for(grouped, "SPY", "2026-08-21", HistoryConventions())
    inputs = build_or_failure_rev_bar_inputs_from_research(
        record_id_prefix="t", evaluated_at=START.replace(minute=32),
        symbol="SPY", instrument_type="ETF", minute_history=batch)
    assert inputs.last_trade.price is None
    with pytest.raises(RecordError, match="HistoryConventions"):
        history_batch_for(grouped, "SPY", "2026-08-21", None)


def test_history_batch_refuses_degraded_and_bad_sessions():
    degraded = group_session_bars(_records([Row(1, TS_NS)], condition="degraded"), ["SPY"])
    with pytest.raises(RecordError, match="no usable bars"):
        history_batch_for(degraded, "SPY", "2026-08-21", CONVENTIONS)
    grouped = group_session_bars(_records([Row(1, TS_NS)]), ["SPY"])
    with pytest.raises(RecordError):
        history_batch_for(grouped, "SPY", "not-a-date", CONVENTIONS)
