"""M9.1BB: retained files to adapter counts entry point (offline, synthetic)."""

import sys

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core17_bar_loader import iter_ohlcv_1m_records
from consensus_engine.retained_count_run import COUNT_RUN_VERSION, run_retained_counts
from consensus_engine.trade_alerts_models import RecordError
from tests.trade_alerts_contracts.test_retained_history_batches import CONVENTIONS, Row, HASH


def _opener(_job_dir, _name):
    return iter_ohlcv_1m_records(
        [Row(m) for m in range(390)], dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols={1: "SPY"}, condition_by_date={"2026-08-21": "available"},
        record_id_prefix="t")


def _run(**kw):
    return run_retained_counts(
        "unused", ["a.dbn"], pairs=[("SPY", "2026-08-21"), ("SPY", "2026-08-24")],
        conventions=CONVENTIONS, instrument_types={"SPY": "ETF"}, opener=_opener, **kw)


def test_counts_chain_is_deterministic_and_lists_skips_and_gaps():
    first, second = _run(), _run()
    assert first == second and first.version == COUNT_RUN_VERSION
    assert first.sessions_used == 1
    assert first.skipped == (("SPY", "2026-08-24", "NO_USABLE_BARS"),)
    assert first.without_prior_session == (("SPY", "2026-08-21"),)
    assert first.counts.moments_called == 3 * 77
    assert "atr_1m" in first.counts.not_called


def test_missing_instrument_type_and_empty_files_are_rejected():
    with pytest.raises(RecordError):
        run_retained_counts("unused", ["a.dbn"], pairs=[("SPY", "2026-08-21")],
                            conventions=CONVENTIONS, instrument_types={}, opener=_opener)
    with pytest.raises(RecordError):
        run_retained_counts("unused", [], pairs=[("SPY", "2026-08-21")],
                            conventions=CONVENTIONS, instrument_types={"SPY": "ETF"}, opener=_opener)
