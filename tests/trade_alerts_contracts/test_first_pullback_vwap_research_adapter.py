"""M9.1N: `FIRST_PULLBACK_VWAP`'s relative-strength input from real,
`PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `first_pullback_vwap_research_adapter.py`: it establishes
no provider coverage, no adopted `FIRST_PULLBACK_VWAP` rule and no permission to
act. The produced `RelativeStrength` is checked directly against
`first_pullback_vwap.RelativeStrength`'s own contract, not against an assembled
`PullbackRequest`, since binding the rest of that request is a later sub-step.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.first_pullback_vwap import RelativeStrength
from consensus_engine.first_pullback_vwap_research_adapter import (
    RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE, build_relative_strength_from_research,
)
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.rs_trend_eligibility import RsWindowPolicy
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
AT = datetime(2026, 7, 6, 6, 50, 10, tzinfo=PACIFIC)
BENCHMARK = "SYNTHBENCH"

LOOKBACK = RsWindowPolicy(version="M91N_TEST_LOOKBACK_V1",
                          definition_reference="M91N_SYNTHETIC_LOOKBACK_ONLY",
                          benchmark_symbol=BENCHMARK, lookback_bars=15,
                          return_basis="FIRST_BAR_OPEN")


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91N_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, opened, close, *, symbol="SYNTH", no_trade=False, revision=0,
             is_final=True, instrument_type="EQUITY", prefix="fpvr"):
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


def built(*, evaluated=None, minute=None, benchmark=None, supplied=LOOKBACK, **changes):
    values = dict(
        record_id="m91n-rs-measured", evaluated_at=evaluated or AT, symbol="SYNTH",
        instrument_type="EQUITY",
        minute_history=history() if minute is None else minute,
        benchmark_history=history(BENCHMARK, first=400.00, step=0.08)
        if benchmark is None else benchmark,
        policy=supplied,
    )
    values.update(changes)
    return build_relative_strength_from_research(**values)


def test_provisional_bars_produce_the_same_reading_as_final_ones():
    provisional = built(minute=history(is_final=False),
                        benchmark=history(BENCHMARK, first=400.00, step=0.08, is_final=False))
    finalized = built()
    assert isinstance(provisional, RelativeStrength)
    assert provisional.value == pytest.approx(0.012)
    assert provisional.value == finalized.value
    assert provisional.coverage_complete is True
    assert provisional.missing_reason is None
    assert provisional.definition_reference == (
        RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE)
    assert provisional.available_at == AT


def test_before_warm_up_coverage_is_complete_but_the_value_is_not():
    early = datetime(2026, 7, 6, 6, 40, tzinfo=PACIFIC)
    result = built(evaluated=early)
    assert result.coverage_complete is True
    assert result.value is None
    assert result.missing_reason == "RS_WARMUP_INCOMPLETE"


def test_a_missing_benchmark_history_is_incomplete_coverage():
    result = built(benchmark_history=None)
    assert result.coverage_complete is False
    assert result.value is None
    assert result.missing_reason == "BENCHMARK_MISSING_MINUTE_HISTORY"


def test_a_missing_stock_history_is_incomplete_coverage():
    result = built(minute_history=None)
    assert result.coverage_complete is False
    assert result.value is None
    assert result.missing_reason == "MISSING_MINUTE_HISTORY"


def test_no_regular_session_is_incomplete_coverage():
    weekend = datetime(2026, 7, 4, 6, 50, 10, tzinfo=PACIFIC)
    result = built(evaluated=weekend)
    assert result.coverage_complete is False
    assert result.value is None
    assert result.missing_reason == "NO_REGULAR_SESSION"


def test_a_quiet_no_trade_interval_is_still_refused_by_name():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True, is_final=True) if index == 10 else row
                for index, row in enumerate(bars)]

    result = built(minute=history(changed=apply, is_final=False))
    assert result.coverage_complete is True
    assert result.value is None
    assert result.missing_reason == "NO_TRADED_RS_INTERVAL"


def test_the_record_id_is_required_and_explicit():
    with pytest.raises(RecordError):
        build_relative_strength_from_research(
            record_id="", evaluated_at=AT, symbol="SYNTH", instrument_type="EQUITY",
            minute_history=history(), benchmark_history=history(BENCHMARK), policy=LOOKBACK)


def test_the_result_stands_as_a_supplied_relative_strength_reading():
    result = built()
    reconstructed = RelativeStrength(
        record_id=result.record_id, definition_reference=result.definition_reference,
        available_at=result.available_at, coverage_complete=result.coverage_complete,
        value=result.value, missing_reason=result.missing_reason)
    assert reconstructed == result
