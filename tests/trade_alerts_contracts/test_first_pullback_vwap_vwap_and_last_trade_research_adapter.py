"""M9.1P: `FIRST_PULLBACK_VWAP`'s VWAP context and last-trade observation, from
real, `PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `first_pullback_vwap_research_adapter.py`: it establishes
no provider coverage, no adopted `FIRST_PULLBACK_VWAP` rule (the VWAP slope and
cross-count conventions stay named as unresolved, per D-104) and no permission
to act. Each result is checked directly against `orb5_trigger.Observation` and
`first_pullback_vwap.VwapContext`'s own contracts, not against an assembled
`PullbackRequest`, since binding the rest of that request is a later sub-step.
"""

from dataclasses import replace
from datetime import datetime, timedelta
from fractions import Fraction
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.first_pullback_vwap import VwapContext
from consensus_engine.first_pullback_vwap_research_adapter import (
    RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE,
    RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN, VWAP_SLOPE_CONVENTION_UNDEFINED,
    build_last_trade_from_research, build_vwap_context_from_research,
)
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.orb5_trigger import TAPE, Observation
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91P_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, opened, close, *, symbol="SYNTH", no_trade=False,
            is_final=True, instrument_type="EQUITY", prefix="m91p"):
    high, low = max(opened, close) + 0.05, min(opened, close) - 0.05
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=interval.end, available_time=interval.end,
        normalized_time=interval.end, session=interval.session,
        data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )
    return Bar(
        record_id=f"{prefix}-{symbol}-{number}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if no_trade else opened, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else close,
        volume=0 if no_trade else 1000 + number,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def walk(first, step, count):
    values = [round(first + step * number, 2) for number in range(count + 1)]
    return list(zip(values, values[1:]))


def history(symbol="SYNTH", *, first=100.00, step=0.10, minutes=5, path=None, changed=None,
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


def opened_at(day=DAY):
    return as_utc(session_bounds(datetime.fromisoformat(day).date())[0])


def expected_vwap(bars):
    volume = sum(Fraction(str(bar.volume)) for bar in bars)
    weighted = sum(
        (Fraction(str(bar.high)) + Fraction(str(bar.low)) + Fraction(str(bar.close)))
        / 3 * Fraction(str(bar.volume)) for bar in bars)
    return float(weighted / volume)


_UNSET = object()


# --- last-trade `Observation` --------------------------------------------


def last_trade(minute_history=_UNSET, *, evaluated=None, symbol="SYNTH",
               instrument_type="EQUITY", **changes):
    values = dict(
        record_id_prefix="m91p-test", evaluated_at=evaluated or opened_at() + timedelta(minutes=3),
        symbol=symbol, instrument_type=instrument_type,
        minute_history=history() if minute_history is _UNSET else minute_history,
    )
    values.update(changes)
    return build_last_trade_from_research(**values)


def test_the_latest_ended_bar_supplies_the_tape_read():
    result = last_trade()
    assert isinstance(result.last_trade, Observation)
    assert result.last_trade.price == 100.30
    assert result.last_trade.mode == TAPE
    assert result.last_trade.coverage_known is True
    assert result.last_trade.observed_at == opened_at() + timedelta(minutes=3)
    assert RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN in result.last_trade.record_id


def test_provisional_bars_are_usable_here_unlike_a_live_tape_feed():
    result = last_trade(history(is_final=False))
    assert result.last_trade.price == 100.30
    assert result.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert result.label["decision"] == "D-110"
    assert result.label["provisional_intervals"] == 3


def test_evaluating_mid_first_minute_finds_no_ready_bar_yet():
    result = last_trade(evaluated=opened_at() + timedelta(seconds=30))
    assert result.last_trade.price is None
    assert result.last_trade.missing_reason == "NO_READY_BAR_BEFORE_EVALUATED_AT"
    assert result.label is not None


def test_a_certified_no_trade_bar_reports_no_trade_by_name_not_a_stale_price():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 2 else row
                for index, row in enumerate(bars)]

    result = last_trade(history(changed=apply), evaluated=opened_at() + timedelta(minutes=3))
    assert result.last_trade.missing_reason == "NO_TRADE_AT_LATEST_BAR"


def test_a_missing_bar_at_the_instant_falls_back_to_the_prior_ready_bar():
    def drop(bars):
        return [row for index, row in enumerate(bars) if index != 2]

    result = last_trade(history(changed=drop), evaluated=opened_at() + timedelta(minutes=3))
    assert result.last_trade.price == 100.20
    assert result.last_trade.observed_at == opened_at() + timedelta(minutes=2)


def test_missing_minute_history_is_an_explicit_unavailable_read():
    result = last_trade(minute_history=None)
    assert result.last_trade.missing_reason == "MISSING_MINUTE_HISTORY"
    assert result.last_trade.coverage_known is False
    assert result.label is None


def test_incompatible_history_is_refused_by_name():
    result = last_trade(history(), symbol="OTHER")
    assert result.last_trade.missing_reason == "INCOMPATIBLE_SYMBOL"
    assert result.label is None


def test_an_incompatible_instrument_type_on_the_selected_bar_is_refused():
    result = last_trade(history(), instrument_type="ETF")
    assert result.last_trade.missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    assert result.last_trade.coverage_known is True
    assert result.label is not None


def test_the_record_id_prefix_and_symbol_and_instrument_type_are_checked():
    with pytest.raises(RecordError):
        build_last_trade_from_research(
            record_id_prefix="", evaluated_at=opened_at() + timedelta(minutes=3),
            symbol="SYNTH", instrument_type="EQUITY", minute_history=history())
    with pytest.raises(RecordError):
        build_last_trade_from_research(
            record_id_prefix="m91p-test", evaluated_at=opened_at() + timedelta(minutes=3),
            symbol="SYNTH", instrument_type="OPTION", minute_history=history())


def test_the_observation_stands_as_a_supplied_arm_reading():
    result = last_trade()
    reconstructed = Observation(
        record_id=result.last_trade.record_id, mode=result.last_trade.mode,
        observed_at=result.last_trade.observed_at, available_at=result.last_trade.available_at,
        price=result.last_trade.price, age_seconds=result.last_trade.age_seconds,
        coverage_known=result.last_trade.coverage_known,
        missing_reason=result.last_trade.missing_reason)
    assert reconstructed == result.last_trade


# --- VWAP context -----------------------------------------------------


def vwap(minute_history=_UNSET, *, evaluated=None, symbol="SYNTH", instrument_type="EQUITY",
        **changes):
    values = dict(
        record_id="m91p-vwap", evaluated_at=evaluated or opened_at() + timedelta(minutes=5),
        symbol=symbol, instrument_type=instrument_type,
        minute_history=history() if minute_history is _UNSET else minute_history,
    )
    values.update(changes)
    return build_vwap_context_from_research(**values)


def test_the_level_is_the_real_volume_weighted_average_since_the_open():
    source = history()
    result = vwap(source)
    assert isinstance(result.context, VwapContext)
    assert result.context.level == pytest.approx(expected_vwap(source.bars))
    assert result.context.coverage_complete is True
    assert result.context.slope is None
    assert result.context.crosses is None
    assert result.context.missing_reason == VWAP_SLOPE_CONVENTION_UNDEFINED
    assert result.context.definition_reference == (
        RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE)


def test_provisional_bars_are_usable_here_unlike_a_live_vwap_feed():
    provisional = vwap(history(is_final=False))
    finalized = vwap(history())
    assert provisional.context.level == pytest.approx(finalized.context.level)
    assert provisional.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert provisional.label["decision"] == "D-110"


def test_only_bars_up_to_the_evaluated_instant_are_weighted():
    early = vwap(history(), evaluated=opened_at() + timedelta(minutes=2))
    source = history()
    assert early.context.level == pytest.approx(expected_vwap(source.bars[:2]))


def test_before_any_trade_the_level_is_absent_but_coverage_is_still_complete():
    result = vwap(evaluated=opened_at())
    assert result.context.level is None
    assert result.context.coverage_complete is True
    assert result.context.missing_reason == "NO_TRADED_SESSION_BAR_YET"


def test_a_certified_no_trade_bar_is_excluded_from_the_weighted_average():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 2 else row
                for index, row in enumerate(bars)]

    source = history(changed=apply)
    result = vwap(source)
    traded = [bar for index, bar in enumerate(source.bars) if index != 2]
    assert result.context.level == pytest.approx(expected_vwap(traded))


def test_missing_minute_history_is_an_explicit_unavailable_context():
    result = vwap(minute_history=None)
    assert result.context.level is None
    assert result.context.coverage_complete is False
    assert result.context.missing_reason == "MISSING_MINUTE_HISTORY"
    assert result.label is None


def test_incompatible_history_is_refused_by_name():
    result = vwap(history(), symbol="OTHER")
    assert result.context.missing_reason == "INCOMPATIBLE_SYMBOL"
    assert result.context.coverage_complete is False
    assert result.label is None


def test_an_incompatible_instrument_type_excludes_every_bar_not_just_one():
    result = vwap(history(), instrument_type="ETF")
    assert result.context.level is None
    assert result.context.coverage_complete is True
    assert result.context.missing_reason == "NO_TRADED_SESSION_BAR_YET"
    assert result.label is not None


def test_a_weekend_instant_has_no_regular_session_to_read():
    weekend = datetime(2026, 7, 4, 6, 50, 10, tzinfo=PACIFIC)
    result = vwap(evaluated=weekend)
    assert result.context.level is None
    assert result.context.coverage_complete is False
    assert result.context.missing_reason == "NO_REGULAR_SESSION"


def test_the_record_id_and_symbol_and_instrument_type_are_checked():
    with pytest.raises(RecordError):
        build_vwap_context_from_research(
            record_id="", evaluated_at=opened_at() + timedelta(minutes=5),
            symbol="SYNTH", instrument_type="EQUITY", minute_history=history())
    with pytest.raises(RecordError):
        build_vwap_context_from_research(
            record_id="m91p-vwap", evaluated_at=opened_at() + timedelta(minutes=5),
            symbol="SYNTH", instrument_type="OPTION", minute_history=history())


def test_the_context_stands_as_a_supplied_vwap_reading():
    result = vwap(history())
    reconstructed = VwapContext(
        record_id=result.context.record_id,
        definition_reference=result.context.definition_reference,
        available_at=result.context.available_at,
        coverage_complete=result.context.coverage_complete, level=result.context.level,
        slope=result.context.slope, crosses=result.context.crosses,
        missing_reason=result.context.missing_reason)
    assert reconstructed == result.context
