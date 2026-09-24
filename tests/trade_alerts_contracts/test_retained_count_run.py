"""M9.1BB: retained files to adapter counts entry point (offline, synthetic)."""

import sys
from functools import partial

import pytest


if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core17_bar_loader import iter_ohlcv_1m_records
from consensus_engine.retained_count_run import COUNT_RUN_VERSION, run_retained_counts
from consensus_engine.trade_alerts_models import RecordError
from tests.trade_alerts_contracts.test_retained_history_batches import CONVENTIONS, Row, HASH


def _opener(_job_dir, _name, *, instrument_types):
    return iter_ohlcv_1m_records(
        [Row(m) for m in range(390)], dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols={1: "SPY"}, condition_by_date={"2026-08-21": "available"},
        record_id_prefix="t", instrument_types=instrument_types)


def _two_symbol_opener(_job_dir, _name, *, instrument_types, missing=None):
    spy = [Row(m) for m in range(390) if missing != ("SPY", m)]
    stock = [Row(m) for m in range(390) if missing != ("XYZ", m)]
    for row in stock:
        row.instrument_id = 2
    return iter_ohlcv_1m_records(
        [*spy, *stock], dataset="EQUS.MINI", source_file_sha256=HASH,
        instrument_symbols={1: "SPY", 2: "XYZ"},
        condition_by_date={"2026-08-21": "available"}, record_id_prefix="two",
        instrument_types=instrument_types)


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
    assert first.counts.moments_called == 4 * 77
    assert "atr_1m" in first.counts.not_called
    assert ("HOD_COMP_RS", "session_vwap", 77) in first.counts.ready
    assert ("CRVOL_ORB5", "opening_range_5m", 77) in first.counts.ready
    assert ("CRVOL_ORB5", "latest_bar_observation", 77) in first.counts.ready
    assert ("HOD_COMP_RS", "rs_15m", "SELF_BENCHMARK_UNDEFINED", 77) \
        in first.counts.not_ready


def test_missing_instrument_type_and_empty_files_are_rejected():
    with pytest.raises(RecordError):
        run_retained_counts("unused", ["a.dbn"], pairs=[("SPY", "2026-08-21")],
                            conventions=CONVENTIONS, instrument_types={}, opener=_opener)
    with pytest.raises(RecordError):
        run_retained_counts("unused", [], pairs=[("SPY", "2026-08-21")],
                            conventions=CONVENTIONS, instrument_types={"SPY": "ETF"}, opener=_opener)


def test_hod_rs_uses_the_same_session_spy_batch_and_keeps_early_warmup_missing():
    result = run_retained_counts(
        "unused", ["a.dbn"],
        pairs=[("SPY", "2026-08-21"), ("XYZ", "2026-08-21")],
        conventions=CONVENTIONS, instrument_types={"SPY": "ETF", "XYZ": "EQUITY"},
        playbooks=("HOD_COMP_RS",), opener=_two_symbol_opener,
    )
    assert ("HOD_COMP_RS", "rs_15m", 75) in result.counts.ready
    assert ("HOD_COMP_RS", "rs_15m", "RS_WARMUP_INCOMPLETE", 2) \
        in result.counts.not_ready


@pytest.mark.parametrize("symbol", ["XYZ", "SPY"])
@pytest.mark.parametrize("minute", [5, 18])
def test_retained_counts_never_roll_past_a_missing_opening_rs_bar(symbol, minute):
    result = run_retained_counts(
        "unused", ["a.dbn"],
        pairs=[("SPY", "2026-08-21"), ("XYZ", "2026-08-21")],
        conventions=CONVENTIONS, instrument_types={"SPY": "ETF", "XYZ": "EQUITY"},
        playbooks=("HOD_COMP_RS",),
        opener=partial(_two_symbol_opener, missing=(symbol, minute)),
    )
    for name in ("rs_15m", "rs_warmup"):
        assert ("HOD_COMP_RS", name, "RS_WARMUP_INCOMPLETE", 2) in result.counts.not_ready
        if minute >= 15:
            assert ("HOD_COMP_RS", name, 75) in result.counts.ready
        else:
            reason = "RS_WINDOW_MISSING" if symbol == "XYZ" else "BENCHMARK_RS_WINDOW_MISSING"
            assert ("HOD_COMP_RS", name, reason, 75) in result.counts.not_ready
            assert not any(row[:2] == ("HOD_COMP_RS", name) for row in result.counts.ready)
