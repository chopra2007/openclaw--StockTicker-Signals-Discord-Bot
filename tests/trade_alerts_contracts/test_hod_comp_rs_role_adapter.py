"""M9.1G: `HOD_COMP_RS` remaining bar-only roles from real, `PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `hod_comp_rs_role_adapter.py`: it establishes no provider
coverage, no adopted `HOD_COMP_RS` rule and no permission to act.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core_price_features import OpeningTradeObservation
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.hod_comp_rs_role_adapter import (
    RESEARCH_DAILY_ATR_PCT_NAME, RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME, RESEARCH_OPEN_RETURN_NAME,
    RESEARCH_ROLE_DATA_MODE, RESEARCH_ROLE_FEATURE_VERSION, RESEARCH_RVOL_NAME,
    RESEARCH_SESSION_VWAP_NAME, build_hod_comp_rs_role_snapshot_from_research,
)
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds, session_dates


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
AT = datetime.fromisoformat(DAY + "T06:35:00").replace(tzinfo=PACIFIC)


def at(clock, day=DAY):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(session="REGULAR"):
    return HistoryConventions(
        timestamp="START", session=session, adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91G_SYNTHETIC_ONLY",
    )


def make_bar(record_id, start, end, *, high, low, close, volume, no_trade=False,
            is_final=True, symbol="SYNTH", instrument_type="EQUITY"):
    session = start.astimezone(PACIFIC).date().isoformat()
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=start, received_time=end, available_time=end, normalized_time=end,
        session=session, data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )
    return Bar(
        record_id=record_id, metadata=meta, start_time=start, end_time=end,
        is_final=True if no_trade else is_final,
        open=None if no_trade else close, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else close,
        volume=0 if no_trade else volume, adjustment_basis="SYNTHETIC_RAW",
        price_convention="USD_PER_SHARE", volume_convention="SHARES", certified_no_trade=no_trade,
    )


def batch(request, bars, session="REGULAR"):
    return HistoryBatch(request, "SYNTHETIC", conventions(session), tuple(bars))


def daily_history(*, is_final=True, changed=None, symbol="SYNTH"):
    """20 prior sessions, constant high/low/close so ATR/prior-close are hand-checkable."""
    day = AT.date()
    days = session_dates(day - timedelta(days=60), day - timedelta(days=1))[-20:]
    request = HistoryRequest(symbol, as_utc(session_bounds(days[0])[0]),
                             as_utc(session_bounds(days[-1])[1]), interval="1d")
    volumes = [400_000, 450_000, 500_000, 550_000, 600_000]
    bars = [make_bar(f"daily-{number}", interval.start, interval.end, high=101, low=99, close=100,
                     volume=volumes[number % 5], is_final=is_final, symbol=symbol)
           for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return batch(request, bars)


def opening_history(*, is_final=True, changed=None, symbol="SYNTH"):
    """20 prior 5-minute opening windows plus today's, mean 50,000 vs today's 100,000."""
    day = AT.date()
    days = [*session_dates(day - timedelta(days=60), day - timedelta(days=1))[-20:], day]
    totals = [40_000, 45_000, 50_000, 55_000, 60_000]
    bars = []
    for index, date in enumerate(days):
        opened = as_utc(session_bounds(date)[0])
        total = 100_000 if index == 20 else totals[index % 5]
        cursor = opened
        for slot in range(5):
            end = cursor + timedelta(minutes=1)
            bars.append(make_bar(f"opening-{index}-{slot}", cursor, end, high=101, low=99, close=100,
                                 volume=total if slot == 0 else 0, no_trade=slot != 0,
                                 is_final=is_final, symbol=symbol))
            cursor = end
    request = HistoryRequest(symbol, as_utc(session_bounds(days[0])[0]),
                             as_utc(session_bounds(days[-1])[0]) + timedelta(minutes=5))
    if changed:
        bars = changed(bars)
    return batch(request, bars)


def minute_history(*, is_final=True, changed=None, through="06:35:00", symbol="SYNTH"):
    opened = as_utc(session_bounds(AT.date())[0])
    request = HistoryRequest(symbol, opened, at(through))
    bars = [make_bar(f"minute-{number}", interval.start, interval.end, high=101, low=99, close=100,
                     volume=1000, is_final=is_final, symbol=symbol)
           for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return batch(request, bars)


def opening_trade(*, price=103.0, instrument_type="EQUITY", symbol="SYNTH"):
    opened = as_utc(session_bounds(AT.date())[0])
    trade_time, available = opened + timedelta(seconds=1), opened + timedelta(seconds=2)
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=trade_time, received_time=available, available_time=available,
        normalized_time=available, session=AT.date().isoformat(), data_mode="SYNTHETIC_TRADE",
        quality="VALID",
    )
    return OpeningTradeObservation("opening-trade", meta, trade_time, price, "SYNTHETIC_RAW",
                                   "USD_PER_SHARE", "SYNTHETIC_COMPLETE")


def snapshot(**changes):
    values = dict(record_id="m91g-roles", evaluated_at=AT, symbol="SYNTH", instrument_type="EQUITY",
                 opening_history=opening_history(), daily_history=daily_history(),
                 minute_history=minute_history(), opening_trade=opening_trade())
    values.update(changes)
    return build_hod_comp_rs_role_snapshot_from_research(**values)


def measured(output):
    return {item.name: item for item in output.snapshot.features}


def numbers(output, *names):
    return [measured(output)[name].value for name in names]


def missing(output, *names):
    return [measured(output)[name].missing_reason for name in names]


ALL_NAMES = (RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME, RESEARCH_RVOL_NAME, RESEARCH_OPEN_RETURN_NAME,
            RESEARCH_DAILY_ATR_PCT_NAME, RESEARCH_SESSION_VWAP_NAME)


def test_hand_computed_values_from_already_final_history():
    output = snapshot()
    assert numbers(output, *ALL_NAMES) == pytest.approx([50_000_000.0, 2.0, 0.03, 0.02, 100.0])
    assert output.snapshot.feature_version == RESEARCH_ROLE_FEATURE_VERSION
    assert output.snapshot.metadata.data_mode == RESEARCH_ROLE_DATA_MODE
    assert FeatureSnapshot.from_json(output.snapshot.to_json()) == output.snapshot


def test_provisional_bars_are_usable_here_unlike_the_live_functions():
    output = snapshot(opening_history=opening_history(is_final=False),
                      daily_history=daily_history(is_final=False),
                      minute_history=minute_history(is_final=False))
    assert numbers(output, *ALL_NAMES) == pytest.approx([50_000_000.0, 2.0, 0.03, 0.02, 100.0])


def test_labels_name_d110_and_the_provisional_count_on_each_side():
    output = snapshot(opening_history=opening_history(is_final=False),
                      daily_history=daily_history(is_final=False),
                      minute_history=minute_history(is_final=False))
    for label in (output.opening_label, output.daily_label, output.minute_label):
        assert label["decision"] == "D-110"
        assert label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
        assert label["provisional_intervals"] > 0
    assert output.minute_label["final_intervals"] == 0


def test_already_final_bars_measure_the_same_values_as_provisional_ones():
    finalized = snapshot()
    provisional = snapshot(opening_history=opening_history(is_final=False),
                           daily_history=daily_history(is_final=False),
                           minute_history=minute_history(is_final=False))
    assert numbers(finalized, *ALL_NAMES) == numbers(provisional, *ALL_NAMES)


def test_daily_atr_pct_is_price_normalized_not_the_live_usd_atr():
    # ATR (TR=2 every day) divided by the frozen prior close (100), not passed through.
    output = snapshot()
    assert measured(output)[RESEARCH_DAILY_ATR_PCT_NAME].value == pytest.approx(0.02)
    assert measured(output)[RESEARCH_DAILY_ATR_PCT_NAME].unit == "RATIO"


def test_missing_histories_are_named_per_role():
    output = snapshot(opening_history=None, daily_history=None, minute_history=None)
    assert missing(output, RESEARCH_RVOL_NAME) == ["MISSING_OPENING_HISTORY"]
    assert missing(output, RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME) == ["MISSING_DAILY_HISTORY"]
    assert missing(output, RESEARCH_DAILY_ATR_PCT_NAME) == ["MISSING_DAILY_HISTORY"]
    assert missing(output, RESEARCH_SESSION_VWAP_NAME) == ["MISSING_MINUTE_HISTORY"]
    assert missing(output, RESEARCH_OPEN_RETURN_NAME) == ["MISSING_MINUTE_HISTORY"]
    assert output.opening_label is None
    assert output.daily_label is None
    assert output.minute_label is None


def test_a_quiet_no_trade_reference_day_counts_as_ready_with_zero_volume():
    def apply(bars):
        # Index 10 is one reference day's traded first minute; certifying it
        # no-trade must not block the window, only contribute zero volume.
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 10 else bar
               for index, bar in enumerate(bars)]

    output = snapshot(opening_history=opening_history(changed=apply))
    assert measured(output)[RESEARCH_RVOL_NAME].missing_reason is None
    assert measured(output)[RESEARCH_RVOL_NAME].value != numbers(snapshot(), RESEARCH_RVOL_NAME)[0]


def test_a_missing_interval_stays_incomplete_not_shortened():
    def drop(bars):
        return [row for index, row in enumerate(bars) if index != 10]

    output = snapshot(daily_history=daily_history(changed=drop))
    assert missing(output, RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME) == ["REFERENCE_WINDOW_MISSING"]
    assert missing(output, RESEARCH_DAILY_ATR_PCT_NAME) == ["INCOMPLETE_15_SESSION_DAILY_WINDOW"]


def test_incompatible_symbol_and_instrument_type_are_named():
    other_symbol = daily_history(symbol="OTHER")
    output = snapshot(daily_history=other_symbol)
    assert missing(output, RESEARCH_MEDIAN_DOLLAR_VOLUME_NAME) == ["INCOMPATIBLE_SYMBOL"]

    def etf(bars):
        return [replace(bar, metadata=replace(bar.metadata, instrument_type="ETF")) for bar in bars]

    output = snapshot(opening_history=opening_history(changed=etf))
    assert missing(output, RESEARCH_RVOL_NAME) == ["INCOMPATIBLE_INSTRUMENT_TYPE"]


def test_the_symbol_and_instrument_type_are_still_required_and_explicit():
    with pytest.raises(RecordError):
        build_hod_comp_rs_role_snapshot_from_research(
            record_id="bad", evaluated_at=AT, symbol="", instrument_type="EQUITY",
            opening_history=None, daily_history=None, minute_history=None, opening_trade=None)
    with pytest.raises(RecordError):
        build_hod_comp_rs_role_snapshot_from_research(
            record_id="bad", evaluated_at=AT, symbol="SYNTH", instrument_type="OPTION",
            opening_history=None, daily_history=None, minute_history=None, opening_trade=None)
