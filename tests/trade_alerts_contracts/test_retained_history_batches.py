"""M9.1AY: retained minute bars -> per ticker-day history batches (offline, synthetic)."""

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core17_bar_loader import iter_ohlcv_1m_records
from consensus_engine.historical_bars import HistoryConventions
from consensus_engine.retained_history_batches import (
    build_history_batches, load_retained_history_batches,
)
from consensus_engine.search_run_bars import group_session_bars
from consensus_engine.trade_alerts_models import RecordError

START = datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc)
TS_NS = int(START.timestamp()) * 1_000_000_000
MINUTE_NS = 60 * 1_000_000_000
HASH = "a3a8de614f9ac54507e61bfdeb05ce69713a6a4b68235cf9188b67939b5fc9b3"
CONVENTIONS = HistoryConventions(
    timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_TEST",
    price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_TEST",
    finality="UNKNOWN", publication="SYNTHETIC_TEST", evidence_reference="synthetic-test",
)


class Row:
    def __init__(self, minute):
        self.instrument_id = 1
        self.ts_event = TS_NS + minute * MINUTE_NS
        self.open, self.high, self.low, self.close = (
            100_000_000_000, 102_000_000_000, 99_000_000_000, 101_000_000_000)
        self.volume = 10
        self.publisher_id = 1


def _records(condition="available", name="t"):
    return iter_ohlcv_1m_records(
        [Row(m) for m in range(390)], dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols={1: "SPY"}, condition_by_date={"2026-08-21": condition},
        record_id_prefix=name)


def test_batches_are_built_per_ticker_day_without_atr_or_entry():
    grouped = group_session_bars(_records(), ["SPY"])
    result = build_history_batches(
        grouped, pairs=[("SPY", "2026-08-21"), ("SPY", "2026-08-24")], conventions=CONVENTIONS)
    assert [(h.ticker, h.session) for h in result.histories] == [("SPY", "2026-08-21")]
    assert len(result.histories[0].batch.bars) == 390
    assert result.histories[0].prior_batch is None
    assert result.without_prior_session == (("SPY", "2026-08-21"),)
    assert result.skipped == (("SPY", "2026-08-24", "NO_USABLE_BARS"),)
    assert not hasattr(result.histories[0], "atr_1m")


def test_degraded_session_is_skipped_and_duplicates_rejected():
    grouped = group_session_bars(_records("degraded"), ["SPY"])
    result = build_history_batches(grouped, pairs=[("SPY", "2026-08-21")], conventions=CONVENTIONS)
    assert result.histories == () and result.skipped == (("SPY", "2026-08-21", "DEGRADED_SESSION"),)
    with pytest.raises(RecordError):
        build_history_batches(grouped, pairs=[("SPY", "2026-08-21")] * 2, conventions=CONVENTIONS)


def test_loader_opens_named_files_and_rejects_bad_input():
    opened = []

    def opener(job_dir, name):
        opened.append((job_dir, name))
        return _records(name=name)

    result = load_retained_history_batches(
        Path("/synthetic"), ["a.dbn.zst"], pairs=[("SPY", "2026-08-21")],
        conventions=CONVENTIONS, opener=opener)
    assert opened == [(Path("/synthetic"), "a.dbn.zst")] and len(result.histories) == 1
    for names, pairs in (([], [("SPY", "2026-08-21")]), (["a", "a"], [("SPY", "2026-08-21")]),
                         (["a"], [])):
        with pytest.raises(RecordError):
            load_retained_history_batches(Path("/synthetic"), names, pairs=pairs,
                                          conventions=CONVENTIONS, opener=opener)
