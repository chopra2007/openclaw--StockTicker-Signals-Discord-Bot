"""M9.1E: `HOD_COMP_RS` RS/benchmark lookback from real, `PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `hod_comp_rs_research_adapter.py`: it establishes no
provider coverage, no adopted `HOD_COMP_RS` rule and no permission to act.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.hod_comp_rs_research_adapter import (
    RESEARCH_BENCHMARK_RETURN_NAME, RESEARCH_RS_DATA_MODE, RESEARCH_RS_FEATURE_VERSION,
    RESEARCH_STOCK_RETURN_NAME, RsTrendResearchSnapshot, build_rs_trend_snapshot_from_research,
)
from consensus_engine.rs_trend_eligibility import RsWindowPolicy
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
AT = datetime(2026, 7, 6, 6, 50, 10, tzinfo=PACIFIC)
BENCHMARK = "SYNTHBENCH"

LOOKBACK = RsWindowPolicy(version="M91E_TEST_LOOKBACK_V1",
                          definition_reference="M91E_SYNTHETIC_LOOKBACK_ONLY",
                          benchmark_symbol=BENCHMARK, lookback_bars=15,
                          return_basis="FIRST_BAR_OPEN")


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91E_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, opened, close, *, symbol="SYNTH", no_trade=False, revision=0,
             is_final=True, instrument_type="EQUITY", prefix="rsr"):
    high, low = max(opened, close) + 0.05, min(opened, close) - 0.05
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=interval.end, available_time=interval.end,
        normalized_time=interval.end, session=interval.session, revision=revision,
        data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )
    return Bar(
        record_id=f"{prefix}-{symbol}-{number}-r{revision}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if no_trade else opened, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else close,
        volume=0 if no_trade else 1000 + number,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def walk(first, step, count):
    values = [float(Decimal(str(first)) + Decimal(str(step)) * number)
              for number in range(count + 1)]
    return list(zip(values, values[1:]))


def history(symbol="SYNTH", *, first=100.00, step=0.10, minutes=15, path=None, changed=None,
            is_final=True, day=DAY, **request_changes):
    opened = as_utc(session_bounds(datetime.fromisoformat(day).date())[0])
    path = path or walk(first, step, minutes)
    values = dict(symbol=symbol, start=opened, end=opened + timedelta(minutes=len(path)))
    values.update(request_changes)
    request = HistoryRequest(**values)
    bars = [make_bar(number, interval, path[number][0], path[number][1],
                     symbol=request.symbol, is_final=is_final)
            for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", conventions(), tuple(bars))


def rs_snapshot(stock=None, benchmark=None, *, evaluated=None, supplied=LOOKBACK, **changes):
    values = dict(
        record_id="m91e-rs-measured", evaluated_at=evaluated or AT, symbol="SYNTH",
        instrument_type="EQUITY",
        minute_history=history() if stock is None else stock,
        benchmark_history=history(BENCHMARK, first=400.00, step=0.08)
        if benchmark is None else benchmark,
        policy=supplied,
    )
    values.update(changes)
    return build_rs_trend_snapshot_from_research(**values)


def measured(output):
    return {item.name: item for item in output.snapshot.features}


def numbers(output, *names):
    return [measured(output)[name].value for name in names]


def missing(output, *names):
    return [measured(output)[name].missing_reason for name in names]


def test_provisional_bars_are_usable_here_unlike_the_live_function():
    output = rs_snapshot(history(is_final=False), history(BENCHMARK, first=400.00, step=0.08,
                                                          is_final=False))
    assert numbers(output, RESEARCH_STOCK_RETURN_NAME, RESEARCH_BENCHMARK_RETURN_NAME,
                   "RS_LOOKBACK_V1") == [0.015, 0.003, 0.012]
    assert numbers(output, "RS_LOOKBACK_BARS_V1", "RS_WARMUP_COMPLETE_V1") == [15, 1]
    assert output.snapshot.feature_version == RESEARCH_RS_FEATURE_VERSION
    assert output.snapshot.metadata.data_mode == RESEARCH_RS_DATA_MODE


def test_labels_name_d110_and_the_provisional_count_on_each_side():
    output = rs_snapshot(history(is_final=False), history(BENCHMARK, first=400.00, step=0.08,
                                                          is_final=False))
    for label in (output.stock_label, output.benchmark_label):
        assert label["decision"] == "D-110"
        assert label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
        assert label["provisional_intervals"] == 15
        assert label["final_intervals"] == 0


def test_already_final_bars_measure_the_same_return_as_provisional_ones():
    finalized = rs_snapshot()
    provisional = rs_snapshot(history(is_final=False),
                              history(BENCHMARK, first=400.00, step=0.08, is_final=False))
    assert numbers(finalized, "RS_LOOKBACK_V1") == numbers(provisional, "RS_LOOKBACK_V1")
    assert finalized.stock_label["final_intervals"] == 15
    assert finalized.stock_label["provisional_intervals"] == 0


def test_the_lookback_never_shortens_itself_before_warm_up():
    early = datetime(2026, 7, 6, 6, 40, tzinfo=PACIFIC)
    output = rs_snapshot(evaluated=early)
    assert numbers(output, "RS_WARMUP_COMPLETE_V1") == [0]
    assert missing(output, RESEARCH_STOCK_RETURN_NAME, "RS_LOOKBACK_V1") == [
        "RS_WARMUP_INCOMPLETE"] * 2
    assert missing(output, RESEARCH_BENCHMARK_RETURN_NAME) == ["BENCHMARK_RS_WARMUP_INCOMPLETE"]


def test_a_quiet_no_trade_interval_is_still_refused_by_name():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True, is_final=True) if index == 10 else row
                for index, row in enumerate(bars)]

    output = rs_snapshot(history(changed=apply, is_final=False))
    assert missing(output, RESEARCH_STOCK_RETURN_NAME, "RS_LOOKBACK_V1") == [
        "NO_TRADED_RS_INTERVAL"] * 2


def test_a_missing_interval_is_still_incomplete_not_shortened():
    def drop(bars):
        return [row for index, row in enumerate(bars) if index != 10]

    output = rs_snapshot(history(changed=drop, is_final=False))
    assert missing(output, RESEARCH_STOCK_RETURN_NAME) == ["RS_WINDOW_MISSING"]


def test_a_missing_benchmark_history_keeps_no_stock_side_label():
    output = rs_snapshot(benchmark_history=None)
    assert numbers(output, RESEARCH_STOCK_RETURN_NAME) == [0.015]
    assert missing(output, RESEARCH_BENCHMARK_RETURN_NAME, "RS_LOOKBACK_V1") == [
        "BENCHMARK_MISSING_MINUTE_HISTORY"] * 2
    assert output.stock_label is not None
    assert output.benchmark_label is None


def test_the_symbol_and_instrument_type_are_still_required_and_explicit():
    with pytest.raises(RecordError):
        build_rs_trend_snapshot_from_research(
            record_id="bad", evaluated_at=AT, symbol="", instrument_type="EQUITY",
            minute_history=history(), benchmark_history=history(BENCHMARK), policy=LOOKBACK)
    with pytest.raises(RecordError):
        build_rs_trend_snapshot_from_research(
            record_id="bad", evaluated_at=AT, symbol="SYNTH", instrument_type="OPTION",
            minute_history=history(), benchmark_history=history(BENCHMARK), policy=LOOKBACK)
    with pytest.raises(RecordError):
        build_rs_trend_snapshot_from_research(
            record_id="bad", evaluated_at=AT, symbol="SYNTH", instrument_type="EQUITY",
            minute_history=history(), benchmark_history=history(BENCHMARK),
            policy=replace(LOOKBACK, benchmark_symbol="SYNTH"))
