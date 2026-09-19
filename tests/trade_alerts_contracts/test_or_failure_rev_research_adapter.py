"""M9.1H: `OR_FAILURE_REV` last-trade/confirmation-close from real, `PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `or_failure_rev_research_adapter.py`: it establishes no
provider coverage, no adopted `OR_FAILURE_REV` rule and no permission to act.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.or_failure_rev_research_adapter import (
    ACCEPTANCE_DEFINITION_REFERENCE, RESEARCH_OR_FAILURE_REV_ORIGIN,
    STRUCTURAL_DEFINITION_REFERENCE, build_or_failure_rev_acceptance_from_research,
    build_or_failure_rev_bar_inputs_from_research, build_or_failure_rev_extreme_inputs_from_research,
    build_or_failure_rev_structural_from_research,
)
from consensus_engine.orb5_trigger import TAPE
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91H_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, opened, close, *, symbol="SYNTH", no_trade=False,
            is_final=True, instrument_type="EQUITY", prefix="m91h"):
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


_UNSET = object()


def inputs(minute_history=_UNSET, *, evaluated=None, symbol="SYNTH", instrument_type="EQUITY",
          **changes):
    values = dict(
        record_id_prefix="m91h-test", evaluated_at=evaluated or opened_at() + timedelta(minutes=3),
        symbol=symbol, instrument_type=instrument_type,
        minute_history=history() if minute_history is _UNSET else minute_history,
    )
    values.update(changes)
    return build_or_failure_rev_bar_inputs_from_research(**values)


def test_the_latest_ended_bar_supplies_both_the_tape_read_and_the_minute_close():
    result = inputs()
    assert result.last_trade.price == result.confirmation_close.close == 100.30
    assert result.last_trade.mode == TAPE
    assert result.last_trade.coverage_known is True
    assert result.confirmation_close.final is True
    assert RESEARCH_OR_FAILURE_REV_ORIGIN in result.last_trade.record_id
    assert result.confirmation_close.bar_end == opened_at() + timedelta(minutes=3)


def test_provisional_bars_are_usable_here_unlike_a_live_tape_or_close_feed():
    result = inputs(history(is_final=False))
    assert result.last_trade.price == result.confirmation_close.close == 100.30
    assert result.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert result.label["decision"] == "D-110"
    assert result.label["provisional_intervals"] == 3


def test_already_final_bars_are_labelled_final_not_provisional():
    result = inputs(history(is_final=True))
    assert result.label["final_intervals"] == 3
    assert result.label["provisional_intervals"] == 0


def test_evaluating_mid_first_minute_finds_no_ready_bar_yet():
    result = inputs(evaluated=opened_at() + timedelta(seconds=30))
    assert result.last_trade.price is None
    assert result.last_trade.missing_reason == "NO_READY_BAR_BEFORE_EVALUATED_AT"
    assert result.confirmation_close.close is None
    assert result.confirmation_close.final is False
    assert result.label is not None


def test_a_certified_no_trade_bar_reports_no_trade_by_name_not_a_stale_price():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 2 else row
                for index, row in enumerate(bars)]

    result = inputs(history(changed=apply), evaluated=opened_at() + timedelta(minutes=3))
    assert result.last_trade.missing_reason == "NO_TRADE_AT_LATEST_BAR"
    assert result.confirmation_close.close is None
    assert result.confirmation_close.final is False


def test_a_missing_bar_at_the_instant_falls_back_to_the_prior_ready_bar():
    def drop(bars):
        return [row for index, row in enumerate(bars) if index != 2]

    result = inputs(history(changed=drop), evaluated=opened_at() + timedelta(minutes=3))
    assert result.last_trade.price == result.confirmation_close.close == 100.20
    assert result.confirmation_close.bar_end == opened_at() + timedelta(minutes=2)


def test_missing_minute_history_is_an_explicit_unavailable_read():
    result = inputs(minute_history=None)
    assert result.last_trade.missing_reason == "MISSING_MINUTE_HISTORY"
    assert result.last_trade.coverage_known is False
    assert result.confirmation_close.close is None
    assert result.label is None


def test_incompatible_history_is_refused_by_name():
    result = inputs(history(), symbol="OTHER")
    assert result.last_trade.missing_reason == "INCOMPATIBLE_SYMBOL"
    assert result.label is None


def test_an_incompatible_instrument_type_on_the_selected_bar_is_refused():
    result = inputs(history(), instrument_type="ETF")
    assert result.last_trade.missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    assert result.last_trade.coverage_known is True
    assert result.confirmation_close.final is False
    assert result.label is not None


def test_the_record_id_prefix_and_symbol_are_still_required_and_explicit():
    with pytest.raises(RecordError):
        build_or_failure_rev_bar_inputs_from_research(
            record_id_prefix="", evaluated_at=opened_at() + timedelta(minutes=3),
            symbol="SYNTH", instrument_type="EQUITY", minute_history=history())
    with pytest.raises(RecordError):
        build_or_failure_rev_bar_inputs_from_research(
            record_id_prefix="m91h-test", evaluated_at=opened_at() + timedelta(minutes=3),
            symbol="SYNTH", instrument_type="OPTION", minute_history=history())


# M9.1I: `BreakoutExtreme`/`FailureBar` from the one real bar carrying the
# break's own furthest traded price since it crossed the opening range.
# `history()`'s five synthetic bars walk 100.00 -> 100.50 in five 0.10 steps,
# each with high = max(open, close) + 0.05 and low = min(open, close) - 0.05,
# so the highs climb 100.15/100.25/100.35/100.45/100.55 and the lows climb
# 99.95/100.05/100.15/100.25/100.35 in lockstep.


def extremes(minute_history=_UNSET, *, crossed=None, evaluated=None, symbol="SYNTH",
            instrument_type="EQUITY", break_direction="LONG", **changes):
    values = dict(
        record_id_prefix="m91i-test", crossed_at=crossed or opened_at(),
        evaluated_at=evaluated or opened_at() + timedelta(minutes=3),
        symbol=symbol, instrument_type=instrument_type, break_direction=break_direction,
        minute_history=history() if minute_history is _UNSET else minute_history,
    )
    values.update(changes)
    return build_or_failure_rev_extreme_inputs_from_research(**values)


def test_a_failed_upside_break_takes_its_extreme_from_the_bar_with_the_furthest_high():
    result = extremes(break_direction="LONG")
    assert result.breakout_extreme.price == 100.35
    assert result.failure_bar.high == 100.35
    assert result.failure_bar.low == 100.15
    assert result.failure_bar.final is True
    assert result.breakout_extreme.coverage_known is True
    assert RESEARCH_OR_FAILURE_REV_ORIGIN in result.breakout_extreme.record_id


def test_a_failed_downside_break_takes_its_extreme_from_the_bar_with_the_furthest_low():
    result = extremes(break_direction="SHORT")
    assert result.breakout_extreme.price == 99.95
    assert result.failure_bar.low == 99.95
    assert result.failure_bar.high == pytest.approx(100.15)


def test_bars_at_or_before_the_crossing_are_excluded_from_the_extreme_search():
    result = extremes(break_direction="LONG", crossed=opened_at() + timedelta(minutes=2),
                      evaluated=opened_at() + timedelta(minutes=3))
    assert result.breakout_extreme.price == 100.35
    assert result.failure_bar.record_id.endswith("-2")


def test_no_ready_bar_since_the_crossing_reports_a_pending_extreme():
    at = opened_at() + timedelta(minutes=3)
    result = extremes(break_direction="LONG", crossed=at, evaluated=at)
    assert result.breakout_extreme.price is None
    assert result.breakout_extreme.coverage_known is True
    assert result.failure_bar.final is False
    assert result.failure_bar.high is None and result.failure_bar.low is None
    assert result.label is not None


def test_missing_minute_history_is_an_explicit_unavailable_extreme():
    result = extremes(minute_history=None)
    assert result.breakout_extreme.price is None
    assert result.breakout_extreme.coverage_known is False
    assert result.failure_bar.coverage_known is False
    assert result.label is None


def test_incompatible_history_is_refused_by_name_for_the_extreme_pair():
    result = extremes(history(), symbol="OTHER")
    assert result.breakout_extreme.coverage_known is False
    assert result.label is None


def test_an_incompatible_instrument_type_on_the_selected_bar_is_refused():
    result = extremes(history(), instrument_type="ETF")
    assert result.breakout_extreme.price is None
    assert result.breakout_extreme.coverage_known is True
    assert result.failure_bar.final is False
    assert result.label is not None


def test_a_certified_no_trade_bar_cannot_supply_the_extreme():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 2 else row
                for index, row in enumerate(bars)]

    result = extremes(history(changed=apply), break_direction="LONG",
                      evaluated=opened_at() + timedelta(minutes=3))
    assert result.breakout_extreme.price == 100.25
    assert result.failure_bar.high == 100.25


def test_provisional_bars_are_usable_for_the_extreme_pair():
    result = extremes(history(is_final=False), break_direction="LONG")
    assert result.breakout_extreme.price == 100.35
    assert result.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"


def test_the_crossing_cannot_follow_the_evaluated_instant_and_direction_is_checked():
    with pytest.raises(RecordError):
        build_or_failure_rev_extreme_inputs_from_research(
            record_id_prefix="m91i-test", crossed_at=opened_at() + timedelta(minutes=3),
            evaluated_at=opened_at(), symbol="SYNTH", instrument_type="EQUITY",
            break_direction="LONG", minute_history=history())
    with pytest.raises(RecordError):
        build_or_failure_rev_extreme_inputs_from_research(
            record_id_prefix="m91i-test", crossed_at=opened_at(),
            evaluated_at=opened_at() + timedelta(minutes=3), symbol="SYNTH",
            instrument_type="EQUITY", break_direction="FLAT", minute_history=history())


# M9.1J: `InsideAcceptance` from the real bars closing inside a caller-named
# failure window. `history()`'s five synthetic bars close 100.10/100.20/100.30/
# 100.40/100.50 in five consecutive one-minute bars starting at `opened_at()`.


def acceptance(minute_history=_UNSET, *, window_start=None, window_end=None, evaluated=None,
              symbol="SYNTH", instrument_type="EQUITY", low=100.15, high=100.35, **changes):
    values = dict(
        record_id_prefix="m91j-test",
        window_start=window_start or opened_at(),
        window_end=window_end or opened_at() + timedelta(minutes=5),
        evaluated_at=evaluated or opened_at() + timedelta(minutes=5),
        symbol=symbol, instrument_type=instrument_type,
        opening_range_low=low, opening_range_high=high,
        minute_history=history() if minute_history is _UNSET else minute_history,
    )
    values.update(changes)
    return build_or_failure_rev_acceptance_from_research(**values)


def test_the_full_window_reports_the_real_share_of_bars_closing_back_inside():
    result = acceptance()
    assert result.acceptance.share == pytest.approx(0.4)
    assert result.acceptance.coverage_complete is True
    assert result.acceptance.definition_reference == ACCEPTANCE_DEFINITION_REFERENCE
    assert RESEARCH_OR_FAILURE_REV_ORIGIN in result.acceptance.record_id
    assert result.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"


def test_provisional_bars_are_usable_for_the_acceptance_share():
    result = acceptance(history(is_final=False))
    assert result.acceptance.share == pytest.approx(0.4)
    assert result.acceptance.coverage_complete is True
    assert result.label["provisional_intervals"] == 5


def test_a_window_not_yet_fully_elapsed_reports_a_partial_incomplete_share():
    result = acceptance(evaluated=opened_at() + timedelta(minutes=3))
    assert result.acceptance.share == pytest.approx(2 / 3)
    assert result.acceptance.coverage_complete is False
    assert result.acceptance.missing_reason is None


def test_a_window_that_has_not_started_yet_is_an_explicit_unavailable_read():
    result = acceptance(window_start=opened_at() + timedelta(minutes=10),
                        window_end=opened_at() + timedelta(minutes=15),
                        evaluated=opened_at())
    assert result.acceptance.share is None
    assert result.acceptance.missing_reason == "WINDOW_NOT_YET_STARTED"
    assert result.acceptance.coverage_complete is False
    assert result.label is None


def test_a_window_with_no_ready_bar_reports_no_ready_bar_by_name():
    result = acceptance(window_start=opened_at() + timedelta(minutes=10),
                        window_end=opened_at() + timedelta(minutes=11),
                        evaluated=opened_at() + timedelta(minutes=11))
    assert result.acceptance.share is None
    assert result.acceptance.missing_reason == "NO_READY_BAR_IN_WINDOW"
    assert result.label is not None


def test_missing_minute_history_is_an_explicit_unavailable_acceptance():
    result = acceptance(minute_history=None)
    assert result.acceptance.share is None
    assert result.acceptance.missing_reason == "MISSING_MINUTE_HISTORY"
    assert result.label is None


def test_incompatible_history_is_refused_by_name_for_the_acceptance_share():
    result = acceptance(history(), symbol="OTHER")
    assert result.acceptance.missing_reason == "INCOMPATIBLE_SYMBOL"
    assert result.label is None


def test_an_incompatible_instrument_type_breaks_the_whole_window_not_just_one_bar():
    result = acceptance(history(), instrument_type="ETF")
    assert result.acceptance.share is None
    assert result.acceptance.missing_reason == "NO_READY_BAR_IN_WINDOW"
    assert result.label is not None


def test_a_certified_no_trade_bar_leaves_a_coverage_hole_but_still_shares_the_rest():
    def apply(bars):
        return [replace(row, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 2 else row
                for index, row in enumerate(bars)]

    result = acceptance(history(changed=apply))
    assert result.acceptance.share == pytest.approx(0.25)
    assert result.acceptance.coverage_complete is False


def test_acceptance_inputs_are_explicit_and_the_window_must_have_positive_duration():
    with pytest.raises(RecordError):
        build_or_failure_rev_acceptance_from_research(
            record_id_prefix="m91j-test", window_start=opened_at(), window_end=opened_at(),
            evaluated_at=opened_at() + timedelta(minutes=5), symbol="SYNTH",
            instrument_type="EQUITY", opening_range_low=100.15, opening_range_high=100.35,
            minute_history=history())
    with pytest.raises(RecordError):
        build_or_failure_rev_acceptance_from_research(
            record_id_prefix="m91j-test", window_start=opened_at(),
            window_end=opened_at() + timedelta(minutes=5),
            evaluated_at=opened_at() + timedelta(minutes=5), symbol="SYNTH",
            instrument_type="EQUITY", opening_range_low=100.35, opening_range_high=100.15,
            minute_history=history())
    with pytest.raises(RecordError):
        build_or_failure_rev_acceptance_from_research(
            record_id_prefix="m91j-test", window_start=opened_at(),
            window_end=opened_at() + timedelta(minutes=5),
            evaluated_at=opened_at() + timedelta(minutes=5), symbol="SYNTH",
            instrument_type="OPTION", opening_range_low=100.15, opening_range_high=100.35,
            minute_history=history())


# M9.1K: `ReversalStructural` (M0.3D section 6 stop/target geometry) from real
# minute bars. `history()`'s five synthetic bars have hlc3 100.0667, 100.1667,
# 100.2667, 100.3667, 100.4667 and volumes 1000-1004, giving an as-of session
# VWAP of 502337/5010 (~100.26686626746508) over all five bars.

VWAP_5BAR = 502337 / 5010


def structural(minute_history=_UNSET, *, direction="LONG", attempt_number=1, crossed=None,
              evaluated=None, available=None, symbol="SYNTH", instrument_type="EQUITY",
              entry_reference=100.00, breakout_extreme_price=99.90, frozen_atr=1.0,
              price_increment=0.01, opening_range_low=99.70, opening_range_high=100.60,
              **changes):
    values = dict(
        record_id_prefix="m91k-test", direction=direction, attempt_number=attempt_number,
        crossed_at=crossed or opened_at(), evaluated_at=evaluated or opened_at() + timedelta(minutes=5),
        available_at=available or evaluated or opened_at() + timedelta(minutes=5),
        symbol=symbol, instrument_type=instrument_type, entry_reference=entry_reference,
        breakout_extreme_price=breakout_extreme_price, frozen_atr=frozen_atr,
        price_increment=price_increment, opening_range_low=opening_range_low,
        opening_range_high=opening_range_high,
        minute_history=history() if minute_history is _UNSET else minute_history,
    )
    values.update(changes)
    return build_or_failure_rev_structural_from_research(**values)


def test_a_long_reversal_stop_is_the_downside_extreme_minus_the_atr_pad():
    result = structural()
    assert result.structural.risk.hard_stop == pytest.approx(99.85)
    assert result.structural.risk.entry_reference == 100.00
    assert result.structural.risk.risk_per_share == pytest.approx(0.15)
    assert result.structural.definition_reference == STRUCTURAL_DEFINITION_REFERENCE
    assert result.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"


def test_a_long_reversal_finds_the_vwap_target_first_then_the_opposite_edge():
    result = structural()
    targets = result.structural.targets
    assert [row.name for row in targets] == ["T1", "T2"]
    assert targets[0].price == pytest.approx(VWAP_5BAR)
    assert targets[0].r_multiple == pytest.approx((VWAP_5BAR - 100.00) / 0.15)
    assert targets[1].price == pytest.approx(100.60)
    assert targets[1].r_multiple == pytest.approx(4.0)


def test_a_short_reversal_stop_is_the_upside_extreme_plus_the_atr_pad():
    result = structural(direction="SHORT", breakout_extreme_price=100.35,
                        entry_reference=100.10, opening_range_low=99.60,
                        opening_range_high=100.30)
    assert result.structural.risk.hard_stop == pytest.approx(100.40)
    assert result.structural.risk.risk_per_share == pytest.approx(0.30)


def test_rounding_moves_the_stop_outward_up_for_short_down_for_long():
    long_result = structural(direction="LONG", breakout_extreme_price=99.93,
                             frozen_atr=1.0, price_increment=0.25, entry_reference=100.00)
    assert long_result.structural.risk.hard_stop == pytest.approx(99.75)
    short_result = structural(direction="SHORT", breakout_extreme_price=100.07,
                              frozen_atr=1.0, price_increment=0.25, entry_reference=100.00,
                              opening_range_low=99.60, opening_range_high=100.60)
    assert short_result.structural.risk.hard_stop == pytest.approx(100.25)
    assert short_result.structural.risk.risk_per_share == pytest.approx(0.25)


def test_an_unavailable_breakout_extreme_leaves_risk_unavailable_by_name():
    result = structural(breakout_extreme_price=None)
    assert result.structural.risk is None
    assert result.structural.missing_reason == "BREAKOUT_EXTREME_UNAVAILABLE"
    assert result.structural.targets == ()
    assert result.label is None


def test_an_unknown_price_increment_leaves_risk_unavailable_not_approximated():
    result = structural(price_increment=None)
    assert result.structural.risk is None
    assert result.structural.missing_reason == "PRICE_INCREMENT_UNKNOWN"
    assert result.label is None


def test_a_stop_on_the_wrong_side_of_entry_is_an_invalid_geometry_not_a_negative_risk():
    result = structural(direction="LONG", breakout_extreme_price=100.50,
                        entry_reference=100.00, frozen_atr=0.0)
    assert result.structural.risk is None
    assert result.structural.missing_reason == "INVALID_STOP_GEOMETRY"


def test_missing_minute_history_still_supplies_the_stop_but_no_targets():
    result = structural(minute_history=None)
    assert result.structural.risk is not None
    assert result.structural.risk.hard_stop == pytest.approx(99.85)
    assert result.structural.targets == ()
    assert result.structural.missing_reason is None
    assert result.label is None


def test_no_traded_bar_before_the_evaluated_instant_leaves_the_catalog_incomplete():
    result = structural(evaluated=opened_at())
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is not None


def test_incompatible_history_still_supplies_the_stop_but_no_targets():
    result = structural(history(), symbol="OTHER")
    assert result.structural.risk is not None
    assert result.structural.targets == ()
    assert result.label is None


def test_structural_inputs_are_explicit_and_direction_is_checked():
    with pytest.raises(RecordError):
        build_or_failure_rev_structural_from_research(
            record_id_prefix="m91k-test", direction="FLAT", attempt_number=1,
            crossed_at=opened_at(), evaluated_at=opened_at() + timedelta(minutes=5),
            available_at=opened_at() + timedelta(minutes=5), symbol="SYNTH",
            instrument_type="EQUITY", entry_reference=100.00, breakout_extreme_price=99.90,
            frozen_atr=1.0, price_increment=0.01, opening_range_low=99.70,
            opening_range_high=100.60, minute_history=history())
    with pytest.raises(RecordError):
        build_or_failure_rev_structural_from_research(
            record_id_prefix="m91k-test", direction="LONG", attempt_number=1,
            crossed_at=opened_at(), evaluated_at=opened_at() + timedelta(minutes=5),
            available_at=opened_at() + timedelta(minutes=5), symbol="SYNTH",
            instrument_type="EQUITY", entry_reference=100.00, breakout_extreme_price=99.90,
            frozen_atr=1.0, price_increment=0.01, opening_range_low=100.60,
            opening_range_high=99.70, minute_history=history())
