"""M3.1 D-090 core price calculations through the protected launcher."""

from dataclasses import replace
from datetime import datetime, time, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.core_price_features import OpeningTradeObservation, build_core_price_snapshot
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds, session_dates


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = datetime.fromisoformat("2026-07-06T00:00:00").replace(tzinfo=PACIFIC)


def at(clock, day="2026-07-06"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(session="REGULAR"):
    return HistoryConventions(
        timestamp="START", session=session, adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M31_SYNTHETIC_ONLY",
    )


def metadata(record_id, start, session, *, revision=0, available=None):
    available = available or start + timedelta(minutes=1)
    return SourceMetadata(
        instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC",
        source_time=start, received_time=available, available_time=available,
        normalized_time=available, session=session, revision=revision,
        data_mode="SYNTHETIC_HISTORY", quality="VALID",
    )


def bar(record_id, start, end, *, high, low, close, volume=100, opened=None,
        no_trade=False, revision=0, available=None):
    session = start.astimezone(PACIFIC).date().isoformat()
    return Bar(
        record_id=record_id, metadata=metadata(record_id, start, session, revision=revision,
                                               available=available or end),
        start_time=start, end_time=end, is_final=True,
        open=None if no_trade else (opened if opened is not None else close),
        high=None if no_trade else high, low=None if no_trade else low,
        close=None if no_trade else close, volume=0 if no_trade else volume,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def batch(request, bars, session="REGULAR"):
    return HistoryBatch(request, "SYNTHETIC", conventions(session), tuple(bars))


@lru_cache(maxsize=4)
def _daily_history(day=DAY):
    days = session_dates(day.date() - timedelta(days=40), day.date() - timedelta(days=1))[-15:]
    first = session_bounds(days[0]); last = session_bounds(days[-1])
    request = HistoryRequest("SYNTH", as_utc(first[0]), as_utc(last[1]), interval="1d")
    bars = []
    # First close 100. The next thirteen TRs are 2 and the newest TR is 3.4.
    for number, interval in enumerate(request.expected_intervals()):
        if number == 14:
            high, low, close = 103.4, 100.0, 102.0
        else:
            high, low, close = 102.0, 100.0, 101.0
        bars.append(bar(f"daily-{number}", interval.start, interval.end,
                        high=high, low=low, close=close, volume=1000))
    return batch(request, bars)


def daily_history(*, changed=None, day=DAY):
    original = _daily_history(day)
    if changed is None:
        return original
    return batch(original.request, changed(list(original.bars)))


@lru_cache(maxsize=1)
def _minute_history():
    previous = session_dates(DAY.date() - timedelta(days=10), DAY.date() - timedelta(days=1))[-1]
    previous_bounds = session_bounds(previous); current_bounds = session_bounds(DAY.date())
    start = as_utc(previous_bounds[1]) - timedelta(minutes=21)
    request = HistoryRequest("SYNTH", start, as_utc(current_bounds[0]) + timedelta(minutes=2))
    bars = []
    intervals = request.expected_intervals()
    for number, interval in enumerate(intervals):
        # Latest selected 20 slots: 18 prior-session TRs of .2, then .2 and .4.
        width = 0.4 if interval.start == as_utc(current_bounds[0]) + timedelta(minutes=1) else 0.2
        bars.append(bar(f"minute-{number}", interval.start, interval.end,
                        high=100 + width / 2, low=100 - width / 2, close=100,
                        volume=1000 if interval.start == as_utc(current_bounds[0]) else 500))
    return batch(request, bars)


def minute_history(*, changed=None, evaluated=at("06:32:00")):
    original = _minute_history()
    if changed is None:
        return original
    return batch(original.request, changed(list(original.bars)))


@lru_cache(maxsize=2)
def mixed_session_minute_history(*, no_trade_open=False):
    opened = as_utc(session_bounds(DAY.date())[0])
    request = HistoryRequest(
        "SYNTH", opened - timedelta(minutes=1), opened + timedelta(minutes=20),
        session_scope="PREMARKET_AND_REGULAR", premarket_start=time(1),
    )
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        if interval.start < opened:
            bars.append(bar("mixed-premarket", interval.start, interval.end,
                            high=110, low=110, close=110))
        elif no_trade_open and interval.start == opened:
            bars.append(bar("mixed-opening-no-trade", interval.start, interval.end,
                            high=0, low=0, close=0, no_trade=True))
        else:
            bars.append(bar(f"mixed-regular-{number}", interval.start, interval.end,
                            high=101, low=99, close=100))
    return batch(request, bars, "PREMARKET_AND_REGULAR")


@lru_cache(maxsize=1)
def current_daily_history():
    opened, closed = map(as_utc, session_bounds(DAY.date()))
    request = HistoryRequest("SYNTH", opened, closed, interval="1d")
    interval = request.expected_intervals()[0]
    return batch(request, [bar("current-daily", interval.start, interval.end,
                               high=101, low=99, close=100, volume=1000)])


@lru_cache(maxsize=1)
def _premarket_history():
    request = HistoryRequest("SYNTH", at("01:00:00"), at("06:30:00"),
                             session_scope="PREMARKET", premarket_start=time(1))
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        if number in (10, 300):
            bars.append(bar(f"pm-{number}", interval.start, interval.end,
                            high=101 + number / 1000, low=99 - number / 1000,
                            close=100, volume=100))
        else:
            bars.append(bar(f"pm-{number}", interval.start, interval.end,
                            high=0, low=0, close=0, no_trade=True))
    return batch(request, bars, "PREMARKET")


def premarket_history(*, changed=None):
    original = _premarket_history()
    if changed is None:
        return original
    return batch(original.request, changed(list(original.bars)), "PREMARKET")


def opening_trade(*, price=102.0, trade_time=at("06:30:01"),
                  available=at("06:30:02"), instrument_type="EQUITY",
                  price_convention="USD_PER_SHARE",
                  coverage_basis="SYNTHETIC_COMPLETE"):
    meta = SourceMetadata(
        instrument_id="SYNTH", instrument_type=instrument_type, source="SYNTHETIC",
        source_time=trade_time, received_time=available, available_time=available,
        normalized_time=available, session="2026-07-06", data_mode="SYNTHETIC_TRADE",
        quality="VALID",
    )
    return OpeningTradeObservation("opening-trade", meta, trade_time, price,
                                   "SYNTHETIC_RAW", price_convention, coverage_basis)


def snapshot(**changes):
    values = dict(record_id="features-1", evaluated_at=at("06:32:00"),
                  minute_history=minute_history(), daily_history=daily_history(),
                  premarket_history=premarket_history(), opening_trade=opening_trade())
    values.update(changes)
    return build_core_price_snapshot(**values)


def values(result):
    return {feature.name: feature for feature in result.features}


def proof_summary(record):
    raw = json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    summary = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    if isinstance(record, FeatureSnapshot):
        summary.update({
            "record_id": record.record_id,
            "instrument_type": record.metadata.instrument_type,
            "evaluated_at": record.evaluated_at.isoformat(),
            "features": [
                {
                    "name": feature.name,
                    "value": feature.value,
                    "missing_reason": feature.missing_reason,
                    "input_count": len(feature.input_record_ids),
                }
                for feature in record.features
            ],
        })
    else:
        statuses = {}
        for interval in record.intervals:
            statuses[interval.status] = statuses.get(interval.status, 0) + 1
        summary.update({
            "complete": record.complete,
            "interval_count": len(record.intervals),
            "status_counts": statuses,
        })
    return summary


def with_certified_no_trade_open(bars):
    target = bars[-2]
    bars[-2] = bar("opening-no-trade", target.start_time, target.end_time,
                   high=0, low=0, close=0, no_trade=True)
    return bars


def without_older_daily_session(bars):
    return bars[:7] + bars[8:]


def with_malformed_overlap(history, index):
    original = history.bars[index]
    start = original.start_time + timedelta(seconds=10)
    malformed = replace(original, record_id="malformed-overlap", start_time=start,
                        metadata=replace(original.metadata, source_time=start))
    return replace(history, bars=(*history.bars, malformed))


def with_older_daily_record():
    history = daily_history()
    first_day = history.request.start.astimezone(PACIFIC).date()
    older_day = session_dates(first_day - timedelta(days=10), first_day - timedelta(days=1))[-1]
    opened, closed = map(as_utc, session_bounds(older_day))
    older = bar("older-daily", opened, closed, high=102, low=100, close=101)
    return replace(history, request=replace(history.request, start=opened),
                   bars=(older, *history.bars))


def shortened_session_history():
    opened, closed = map(as_utc, session_bounds(at("00:00:00", "2026-11-27").date()))
    request = HistoryRequest("SYNTH", opened, closed)
    bars = [bar(f"short-minute-{number}", interval.start, interval.end,
                high=101, low=99, close=100) for number, interval in enumerate(request.expected_intervals())]
    # The last scheduled minute is final but arrives two seconds after the close.
    bars[-1] = replace(bars[-1], metadata=replace(
        bars[-1].metadata, received_time=closed + timedelta(seconds=2),
        available_time=closed + timedelta(seconds=2), normalized_time=closed + timedelta(seconds=2)))
    return batch(request, bars)


def with_instrument_revision(history, *, prepend=False):
    original = history.bars[-1]
    available = at("06:32:01")
    revised = replace(original, record_id="instrument-revision", metadata=replace(
        original.metadata, instrument_type="ETF", revision=1,
        received_time=available, available_time=available, normalized_time=available))
    return replace(history, bars=(revised, *history.bars) if prepend else (*history.bars, revised))


def truncated_premarket_history():
    history = premarket_history()
    return replace(history, request=replace(history.request, start=at("01:01:00")),
                   bars=history.bars[1:])


def multi_session_premarket_history():
    history = premarket_history()
    prior_day = session_dates(DAY.date() - timedelta(days=10), DAY.date() - timedelta(days=1))[-1]
    start = datetime.combine(prior_day, time(1), tzinfo=PACIFIC)
    request = replace(history.request, start=start)
    earlier = [bar(f"prior-pm-{number}", interval.start, interval.end,
                   high=150, low=50, close=100)
               for number, interval in enumerate(request.expected_intervals())
               if interval.session != DAY.date().isoformat()]
    return replace(history, request=request, bars=(*earlier, *history.bars))


def test_hand_calculated_features_and_canonical_round_trip():
    result = snapshot()
    found = values(result)
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(.21)
    assert found["DAILY_ATR_14_SMA_V1"].value == pytest.approx(2.1)
    # HLC3 values 100, weighted 1000 and 500: deliberately not average bar close logic.
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value == pytest.approx(100)
    assert found["CURRENT_HOD_V1"].value == pytest.approx(100.2)
    assert found["CURRENT_LOD_V1"].value == pytest.approx(99.8)
    assert found["PDH_V1"].value == pytest.approx(103.4)
    assert found["PDL_V1"].value == pytest.approx(100)
    assert found["PMH_V1"].value == pytest.approx(101.3)
    assert found["PML_V1"].value == pytest.approx(98.7)
    assert found["SESSION_OPEN_TRADE_V1"].value == 102
    assert found["GAP_OPEN_V1"].value == pytest.approx((102 - 102) / 102)
    assert FeatureSnapshot.from_json(result.to_json()) == result
    assert result.to_json() == snapshot().to_json()


def test_vwap_matches_d090_hlc3_fixture_not_simple_mean():
    history = minute_history()
    current = list(history.bars[-2:])
    current[0] = replace(current[0], high=101, low=99, close=100, volume=1000)
    current[1] = replace(current[1], high=103, low=101, close=102, open=102, volume=500)
    history = replace(history, bars=(*history.bars[:-2], *current))
    found = values(snapshot(minute_history=history))
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value == pytest.approx(100.66666666666667)


@pytest.mark.parametrize("kind", ["missing", "late", "correction"])
def test_missing_late_or_invalid_latest_minute_never_falls_back(kind):
    def change(bars):
        if kind == "missing":
            return bars[:-1]
        if kind == "late":
            bars[-1] = replace(bars[-1], metadata=replace(
                bars[-1].metadata, received_time=at("06:35:00"),
                available_time=at("06:35:00"), normalized_time=at("06:35:00")))
        else:
            bars.append(replace(bars[-1], record_id="bad-revision", metadata=replace(
                bars[-1].metadata, revision=1, quality="INVALID")))
        return bars
    found = values(snapshot(minute_history=minute_history(changed=change)))
    assert found["ATR_1M_20_SMA_V1"].value is None
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value is None


def test_certified_no_trade_is_zero_tr_but_does_not_invent_extrema():
    def change(bars):
        target = bars[-1]
        bars[-1] = bar("minute-no-trade", target.start_time, target.end_time,
                       high=0, low=0, close=0, no_trade=True)
        return bars
    found = values(snapshot(minute_history=minute_history(changed=change)))
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(.19)
    assert found["CURRENT_HOD_V1"].value == pytest.approx(100.1)


def test_first_trade_after_certified_no_trade_open_uses_its_own_range():
    found = values(snapshot(minute_history=minute_history(
        changed=with_certified_no_trade_open)))
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(.20)
    assert found["ATR_1M_20_SMA_V1"].missing_reason is None


def test_minute_atr_does_not_use_premarket_close_for_regular_open():
    found = values(snapshot(
        evaluated_at=at("06:50:00"),
        minute_history=mixed_session_minute_history(),
    ))
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(2)
    assert found["ATR_1M_20_SMA_V1"].missing_reason is None


def test_minute_atr_does_not_use_premarket_close_after_no_trade_open():
    found = values(snapshot(
        evaluated_at=at("06:50:00"),
        minute_history=mixed_session_minute_history(no_trade_open=True),
    ))
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(1.9)
    assert found["ATR_1M_20_SMA_V1"].missing_reason is None


def test_minute_history_cannot_supply_daily_features():
    found = values(snapshot(daily_history=minute_history()))
    for name in ("DAILY_ATR_14_SMA_V1", "PDH_V1", "PDL_V1", "GAP_OPEN_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "INCOMPATIBLE_HISTORY_INTERVAL"


def test_daily_history_cannot_supply_minute_session_features():
    found = values(snapshot(
        evaluated_at=at("13:00:00"), minute_history=current_daily_history()))
    for name in ("ATR_1M_20_SMA_V1", "SESSION_VWAP_BAR_HLC3_V1",
                 "CURRENT_HOD_V1", "CURRENT_LOD_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "INCOMPATIBLE_HISTORY_INTERVAL"


def test_missing_older_daily_session_blocks_atr_but_not_prior_levels_or_open():
    history = daily_history(changed=without_older_daily_session)
    found = values(snapshot(daily_history=history))
    assert found["DAILY_ATR_14_SMA_V1"].value is None
    assert found["PDH_V1"].value == pytest.approx(103.4)
    assert found["PDL_V1"].value == pytest.approx(100)
    assert found["SESSION_OPEN_TRADE_V1"].value == pytest.approx(102)
    assert found["GAP_OPEN_V1"].value == pytest.approx(0)


def test_missing_prior_daily_session_preserves_identified_open_but_blocks_gap():
    history = daily_history(changed=lambda bars: bars[:-1])
    found = values(snapshot(daily_history=history))
    for name in ("DAILY_ATR_14_SMA_V1", "PDH_V1", "PDL_V1", "GAP_OPEN_V1"):
        assert found[name].value is None
    assert found["SESSION_OPEN_TRADE_V1"].value == 102
    assert found["SESSION_OPEN_TRADE_V1"].input_record_ids == ("opening-trade",)
    assert found["GAP_OPEN_V1"].missing_reason == "INCOMPLETE_PRIOR_SESSION_DAILY_BAR"


@pytest.mark.parametrize("daily_kind", ["absent", "invalid_prior", "no_trade_prior"])
def test_identified_open_does_not_need_a_usable_daily_close(daily_kind):
    history = daily_history()
    if daily_kind == "absent":
        history = None
    elif daily_kind == "invalid_prior":
        prior = history.bars[-1]
        history = replace(history, bars=(*history.bars[:-1], replace(
            prior, metadata=replace(prior.metadata, quality="INVALID"))))
    else:
        prior = history.bars[-1]
        history = replace(history, bars=(*history.bars[:-1], bar(
            "prior-no-trade", prior.start_time, prior.end_time,
            high=0, low=0, close=0, no_trade=True)))
    found = values(snapshot(daily_history=history))
    assert found["SESSION_OPEN_TRADE_V1"].value == 102
    assert found["SESSION_OPEN_TRADE_V1"].missing_reason is None
    assert found["GAP_OPEN_V1"].value is None
    assert found["GAP_OPEN_V1"].missing_reason == (
        "MISSING_DAILY_HISTORY" if history is None else "INCOMPLETE_PRIOR_SESSION_DAILY_BAR")


def test_older_malformed_minute_cannot_change_selected_features():
    history = with_malformed_overlap(minute_history(), 0)
    assert history.coverage_at(at("06:32:00")).unexpected_record_ids == ("malformed-overlap",)
    assert snapshot(minute_history=history).to_json() == snapshot().to_json()


def test_prior_session_malformed_minute_cannot_change_current_session_features():
    history = with_malformed_overlap(minute_history(), -3)
    found = values(snapshot(minute_history=history))
    original = values(snapshot())
    for name in ("SESSION_VWAP_BAR_HLC3_V1", "CURRENT_HOD_V1", "CURRENT_LOD_V1"):
        assert found[name] == original[name]
    # This prior-session minute is still in the latest twenty ATR slots.
    assert found["ATR_1M_20_SMA_V1"].value is None


def test_older_malformed_daily_record_cannot_change_selected_features():
    history = with_malformed_overlap(with_older_daily_record(), 0)
    assert history.coverage_at(at("06:32:00")).unexpected_record_ids == ("malformed-overlap",)
    assert snapshot(daily_history=history).to_json() == snapshot().to_json()


@pytest.mark.parametrize("index", [0, -1])
def test_malformed_daily_record_in_required_window_still_blocks_atr(index):
    found = values(snapshot(daily_history=with_malformed_overlap(daily_history(), index)))
    assert found["DAILY_ATR_14_SMA_V1"].value is None
    assert found["SESSION_OPEN_TRADE_V1"].value == 102
    if index == -1:
        for name in ("PDH_V1", "PDL_V1", "GAP_OPEN_V1"):
            assert found[name].value is None
    else:
        assert found["PDH_V1"].value == pytest.approx(103.4)
        assert found["GAP_OPEN_V1"].value == 0


def test_malformed_current_minute_still_blocks_selected_session_features():
    found = values(snapshot(minute_history=with_malformed_overlap(minute_history(), -1)))
    for name in ("ATR_1M_20_SMA_V1", "SESSION_VWAP_BAR_HLC3_V1", "CURRENT_HOD_V1", "CURRENT_LOD_V1"):
        assert found[name].value is None


@pytest.mark.parametrize("kind", ["missing", "malformed"])
def test_minute_atr_requires_its_previous_close_reference(kind):
    history = minute_history()
    if kind == "missing":
        history = replace(history, bars=(*history.bars[:2], *history.bars[3:]))
    else:
        history = with_malformed_overlap(history, 2)
    found = values(snapshot(minute_history=history))
    assert found["ATR_1M_20_SMA_V1"].value is None
    assert found["ATR_1M_20_SMA_V1"].missing_reason == "MISSING_PREVIOUS_MINUTE_CLOSE"
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value == 100


def test_insufficient_history_does_not_borrow_older_warm_up_slots():
    minutes = minute_history()
    minutes = replace(minutes, request=replace(minutes.request, start=minutes.bars[4].start_time),
                      bars=minutes.bars[4:])
    daily = daily_history()
    daily = replace(daily, request=replace(daily.request, start=daily.bars[1].start_time),
                    bars=daily.bars[1:])
    assert minutes.coverage_at(at("06:32:00")).complete
    assert daily.coverage_at(at("06:32:00")).complete
    found = values(snapshot(minute_history=minutes, daily_history=daily))
    assert found["ATR_1M_20_SMA_V1"].missing_reason == "INCOMPLETE_20_MINUTE_WINDOW"
    assert found["DAILY_ATR_14_SMA_V1"].missing_reason == "INCOMPLETE_15_SESSION_DAILY_WINDOW"
    assert found["CURRENT_HOD_V1"].value == pytest.approx(100.2)
    assert found["PDH_V1"].value == pytest.approx(103.4)


def test_zero_session_volume_is_unknown_vwap_without_erasing_price_extrema():
    history = minute_history()
    history = replace(history, bars=(*history.bars[:-2], *(
        replace(item, volume=0) for item in history.bars[-2:])))
    found = values(snapshot(minute_history=history))
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value is None
    assert found["SESSION_VWAP_BAR_HLC3_V1"].missing_reason == "ZERO_SESSION_VOLUME"
    assert found["CURRENT_HOD_V1"].value == pytest.approx(100.2)
    assert found["CURRENT_LOD_V1"].value == pytest.approx(99.8)


def test_complete_no_trade_windows_do_not_invent_prices():
    def no_trades(bars):
        return [bar(item.record_id, item.start_time, item.end_time,
                    high=0, low=0, close=0, no_trade=True) for item in bars]
    minutes = minute_history(changed=no_trades)
    premarket = premarket_history(changed=no_trades)
    assert minutes.coverage_at(at("06:32:00")).complete
    assert premarket.coverage_at(at("06:32:00")).complete
    found = values(snapshot(minute_history=minutes, premarket_history=premarket, opening_trade=None))
    assert found["ATR_1M_20_SMA_V1"].value == 0
    for name in ("SESSION_VWAP_BAR_HLC3_V1", "CURRENT_HOD_V1", "CURRENT_LOD_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "NO_TRADED_REGULAR_SESSION_BAR"
    for name in ("PMH_V1", "PML_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "NO_PREMARKET_TRADES"


def test_missing_premarket_slot_blocks_both_extrema():
    history = premarket_history(changed=lambda bars: bars[:20] + bars[21:])
    found = values(snapshot(premarket_history=history))
    assert found["PMH_V1"].value is None and found["PML_V1"].value is None


def test_premarket_request_starting_after_0100_cannot_supply_complete_levels():
    history = truncated_premarket_history()
    # Complete requested coverage still omits the required 01:00 minute.
    assert history.coverage_at(at("06:32:00")).complete
    found = values(snapshot(premarket_history=history))
    for name in ("PMH_V1", "PML_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "INCOMPLETE_PREMARKET_WINDOW"
    assert found["CURRENT_HOD_V1"].value == pytest.approx(100.2)


def test_complete_current_premarket_in_multi_session_request_keeps_current_levels():
    history = multi_session_premarket_history()
    assert history.coverage_at(at("06:32:00")).complete
    assert len(history.request.expected_intervals()) == 660
    result = snapshot(premarket_history=history)
    assert result.to_json() == snapshot().to_json()
    for name, expected in (("PMH_V1", 101.3), ("PML_V1", 98.7)):
        feature = values(result)[name]
        assert feature.value == pytest.approx(expected)
        assert len(feature.input_record_ids) == 330
        assert not any(record_id.startswith("prior-pm-") for record_id in feature.input_record_ids)


def test_open_and_gap_require_identified_compatible_trade_available_now():
    for trade in (None, opening_trade(available=at("06:35:00")),
                  replace(opening_trade(), adjustment_basis="OTHER"),
                  replace(opening_trade(), coverage_basis="OTHER"),
                  opening_trade(instrument_type="ETF")):
        found = values(snapshot(opening_trade=trade))
        assert found["SESSION_OPEN_TRADE_V1"].value is None
        assert found["GAP_OPEN_V1"].value is None


@pytest.mark.parametrize("price", [float("nan"), float("inf"), float("-inf")])
def test_opening_trade_price_must_be_finite(price):
    with pytest.raises(ValueError, match="finite and positive"):
        opening_trade(price=price)


def test_option_opening_trade_is_rejected():
    with pytest.raises(ValueError, match="instrument type must be EQUITY or ETF"):
        opening_trade(instrument_type="OPTION")


def test_wrong_price_unit_blocks_only_features_from_that_history():
    minutes = minute_history()
    minutes = replace(minutes, conventions=replace(
        minutes.conventions, price="CENTS_PER_SHARE"))
    found = values(snapshot(minute_history=minutes))
    for name in ("ATR_1M_20_SMA_V1", "SESSION_VWAP_BAR_HLC3_V1",
                 "CURRENT_HOD_V1", "CURRENT_LOD_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "INCOMPATIBLE_PRICE_UNIT"
    assert found["DAILY_ATR_14_SMA_V1"].value == pytest.approx(2.1)
    assert found["PMH_V1"].value == pytest.approx(101.3)


def test_non_share_volume_blocks_vwap_but_not_price_only_features():
    minutes = minute_history()
    minutes = replace(
        minutes,
        conventions=replace(minutes.conventions, volume="ROUND_LOTS"),
        bars=tuple(replace(item, volume_convention="ROUND_LOTS") for item in minutes.bars),
    )
    found = values(snapshot(minute_history=minutes))
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value is None
    assert found["SESSION_VWAP_BAR_HLC3_V1"].missing_reason == "INCOMPATIBLE_VOLUME_UNIT"
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(.21)
    assert found["CURRENT_HOD_V1"].value == pytest.approx(100.2)


def test_unknown_venue_basis_blocks_only_features_from_that_history():
    premarket = premarket_history()
    premarket = replace(premarket, conventions=replace(
        premarket.conventions, coverage_basis="UNKNOWN"))
    found = values(snapshot(premarket_history=premarket))
    for name in ("PMH_V1", "PML_V1"):
        assert found[name].value is None
        assert found[name].missing_reason == "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    assert found["SESSION_VWAP_BAR_HLC3_V1"].value == pytest.approx(100)
    assert found["DAILY_ATR_14_SMA_V1"].value == pytest.approx(2.1)


def test_gap_requires_matching_daily_and_opening_venue_basis():
    daily = daily_history()
    daily = replace(daily, conventions=replace(
        daily.conventions, coverage_basis="OTHER_COMPLETE"))
    found = values(snapshot(daily_history=daily))
    assert found["SESSION_OPEN_TRADE_V1"].value == 102
    assert found["GAP_OPEN_V1"].value is None
    assert found["GAP_OPEN_V1"].missing_reason == "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"
    assert found["DAILY_ATR_14_SMA_V1"].value == pytest.approx(2.1)


def test_opening_trade_time_cannot_follow_its_availability():
    with pytest.raises(ValueError, match="cannot follow its availability"):
        opening_trade(trade_time=at("06:30:03"), available=at("06:30:02"))


def test_open_and_gap_reject_opening_trade_after_evaluation_time():
    trade = opening_trade(trade_time=at("06:30:01"), available=at("06:30:02"))
    found = values(snapshot(evaluated_at=at("06:30:00"), opening_trade=trade))
    assert found["ATR_1M_20_SMA_V1"].value == pytest.approx(.2)
    assert found["SESSION_OPEN_TRADE_V1"].value is None
    assert found["GAP_OPEN_V1"].value is None


def test_future_revision_cannot_rewrite_earlier_snapshot():
    original = minute_history()
    before = snapshot(minute_history=original).to_json()
    revised = replace(original.bars[-1], record_id="future-revision", high=120,
                      metadata=replace(original.bars[-1].metadata, revision=1,
                                       received_time=at("06:40:00"),
                                       available_time=at("06:40:00"),
                                       normalized_time=at("06:40:00")))
    assert snapshot(minute_history=replace(original, bars=(*original.bars, revised))).to_json() == before


@pytest.mark.parametrize("history_name", ["minute_history", "daily_history", "premarket_history"])
@pytest.mark.parametrize("prepend", [False, True])
def test_future_instrument_revision_cannot_change_snapshot_before_availability(history_name, prepend):
    histories = {"minute_history": minute_history(), "daily_history": daily_history(),
                 "premarket_history": premarket_history()}
    original = snapshot(**histories)
    histories[history_name] = with_instrument_revision(histories[history_name], prepend=prepend)
    before = snapshot(**histories)
    assert before.to_json() == original.to_json()
    assert before.metadata.instrument_type == "EQUITY"
    assert values(before)["SESSION_OPEN_TRADE_V1"].value == 102
    assert values(before)["GAP_OPEN_V1"].value == 0

    # At exact availability the mismatch must become visible, with no fallback.
    after = values(snapshot(evaluated_at=at("06:32:01"), **histories))
    affected = {
        "minute_history": ("ATR_1M_20_SMA_V1", "SESSION_VWAP_BAR_HLC3_V1",
                           "CURRENT_HOD_V1", "CURRENT_LOD_V1", "SESSION_OPEN_TRADE_V1", "GAP_OPEN_V1"),
        "daily_history": ("DAILY_ATR_14_SMA_V1", "PDH_V1", "PDL_V1", "PRIOR_REGULAR_CLOSE_V1",
                          "GAP_OPEN_V1"),
        "premarket_history": ("PMH_V1", "PML_V1"),
    }[history_name]
    for name in affected:
        assert after[name].value is None
        assert after[name].missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    for name, feature in values(original).items():
        if name not in affected:
            assert after[name] == feature
    assert before.to_json() == original.to_json()


def test_future_only_history_cannot_supply_snapshot_instrument_identity():
    history = minute_history()
    empty = replace(history, bars=())
    future = with_instrument_revision(history, prepend=True).bars[0]
    inputs = dict(minute_history=empty, daily_history=None, premarket_history=None)
    before = snapshot(**inputs)
    inputs["minute_history"] = replace(empty, bars=(future,))
    assert snapshot(**inputs).to_json() == before.to_json()
    assert before.metadata.instrument_type == "UNKNOWN"


def test_latest_available_instrument_revision_supersedes_older_identity():
    history = with_instrument_revision(minute_history())
    original_bytes = snapshot(minute_history=history).to_json()
    revised = history.bars[-1]
    available = at("06:32:02")
    restored = replace(revised, record_id="restored-instrument", metadata=replace(
        revised.metadata, instrument_type="EQUITY", revision=2,
        received_time=available, available_time=available, normalized_time=available))
    history = replace(history, bars=(*history.bars, restored))
    assert snapshot(minute_history=history).to_json() == original_bytes
    assert values(snapshot(minute_history=history, evaluated_at=at("06:32:01")))[
        "SESSION_OPEN_TRADE_V1"].value is None
    result = snapshot(minute_history=history, evaluated_at=available)
    for name, feature in values(snapshot()).items():
        assert values(result)[name].value == feature.value
        assert values(result)[name].missing_reason == feature.missing_reason
    assert result.metadata.instrument_type == "EQUITY"
    assert "restored-instrument" in result.input_record_ids
    assert "instrument-revision" not in result.input_record_ids


def test_early_close_daily_interval_is_accepted_from_calendar():
    evaluated = at("06:32:00", "2026-11-30")
    history = daily_history(day=evaluated)
    prior = history.bars[-1]
    assert prior.metadata.session == "2026-11-27"
    assert prior.end_time.astimezone(PACIFIC).time() == time(10)
    assert prior.end_time - prior.start_time == timedelta(hours=3, minutes=30)
    assert history.coverage_at(evaluated).complete
    result = build_core_price_snapshot(
        record_id="short-daily", evaluated_at=evaluated, daily_history=history,
        minute_history=None, premarket_history=None)
    found = values(result)
    assert found["DAILY_ATR_14_SMA_V1"].value == pytest.approx(2.1)
    assert found["PDH_V1"].value == pytest.approx(103.4)
    assert found["PDH_V1"].input_record_ids == (prior.record_id,)


def test_shortened_session_last_minute_requires_final_availability():
    history = shortened_session_history()
    closed = history.request.end
    coverage = history.coverage_at(closed)
    assert len(coverage.intervals) == 210
    assert coverage.intervals[-1].status == "MISSING"
    assert not coverage.complete
    assert history.coverage_at(closed + timedelta(seconds=2)).complete
    outputs = [build_core_price_snapshot(
        record_id=f"short-session-{number}", evaluated_at=moment, minute_history=history,
        daily_history=None, premarket_history=None)
        for number, moment in enumerate((closed - timedelta(seconds=1), closed,
                                         closed + timedelta(seconds=2)))]
    for name, expected in (("ATR_1M_20_SMA_V1", 2), ("SESSION_VWAP_BAR_HLC3_V1", 100),
                           ("CURRENT_HOD_V1", 101), ("CURRENT_LOD_V1", 99)):
        assert values(outputs[0])[name].value == expected
        assert values(outputs[1])[name].value is None
        assert values(outputs[2])[name].value == expected
    assert "short-minute-209" not in outputs[0].input_record_ids
    assert "short-minute-209" in outputs[2].input_record_ids


def test_legacy_indicator_arithmetic_keeps_its_existing_contract():
    from consensus_engine.analysis.indicators import atr, vwap

    # TRs 2, 4, 8: the old two-period Wilder seed is 3, then (3 + 8) / 2.
    assert atr([101, 101, 102, 104], [99, 99, 98, 96], [100] * 4, period=2) == 5.5
    assert atr([101], [99], [100], period=2) is None
    assert vwap([100, 102], [1000, 500]) == pytest.approx(100.66666666666667)
    assert vwap([100, 102], [0, 0]) is None


def test_bar_to_coverage_to_feature_snapshot_recording_end_to_end():
    result = snapshot()
    first_trade_after_no_trade = snapshot(minute_history=minute_history(
        changed=with_certified_no_trade_open))
    incomplete_atr = snapshot(daily_history=daily_history(
        changed=without_older_daily_session))
    future_open = snapshot(evaluated_at=at("06:30:00"), opening_trade=opening_trade())
    missing_prior = snapshot(daily_history=daily_history(changed=lambda bars: bars[:-1]))
    no_daily = snapshot(daily_history=None)
    older_minute = with_malformed_overlap(minute_history(), 0)
    older_daily = with_malformed_overlap(with_older_daily_record(), 0)
    prior_minute = with_malformed_overlap(minute_history(), -3)
    off_window_snapshots = [snapshot(minute_history=older_minute), snapshot(daily_history=older_daily),
                            snapshot(minute_history=prior_minute)]
    assert off_window_snapshots[0].to_json() == result.to_json()
    assert off_window_snapshots[1].to_json() == result.to_json()
    for name in ("SESSION_VWAP_BAR_HLC3_V1", "CURRENT_HOD_V1", "CURRENT_LOD_V1"):
        assert values(off_window_snapshots[2])[name] == values(result)[name]
    for output in (missing_prior, no_daily):
        assert values(output)["SESSION_OPEN_TRADE_V1"].value == 102
        assert values(output)["GAP_OPEN_V1"].value is None
    short_history = shortened_session_history()
    short_times = [short_history.request.end + timedelta(seconds=offset) for offset in (-1, 0, 2)]
    short_snapshots = [build_core_price_snapshot(
        record_id=f"short-session-{number}", evaluated_at=moment, minute_history=short_history,
        daily_history=None, premarket_history=None) for number, moment in enumerate(short_times)]
    assert [values(output)["SESSION_VWAP_BAR_HLC3_V1"].value for output in short_snapshots] == [100, None, 100]
    after_short_session = at("06:32:00", "2026-11-30")
    short_daily = daily_history(day=after_short_session)
    short_daily_snapshot = build_core_price_snapshot(
        record_id="short-daily", evaluated_at=after_short_session, daily_history=short_daily,
        minute_history=None, premarket_history=None)
    assert values(short_daily_snapshot)["DAILY_ATR_14_SMA_V1"].value == pytest.approx(2.1)
    zero_minutes = minute_history(changed=lambda bars: [replace(item, volume=0) for item in bars])
    zero_snapshot = snapshot(minute_history=zero_minutes)
    assert values(zero_snapshot)["SESSION_VWAP_BAR_HLC3_V1"].missing_reason == "ZERO_SESSION_VOLUME"
    warmup_minutes = minute_history()
    warmup_minutes = replace(warmup_minutes, request=replace(
        warmup_minutes.request, start=warmup_minutes.bars[4].start_time), bars=warmup_minutes.bars[4:])
    warmup_snapshot = snapshot(minute_history=warmup_minutes)
    assert values(warmup_snapshot)["ATR_1M_20_SMA_V1"].missing_reason == "INCOMPLETE_20_MINUTE_WINDOW"
    price_unit_minutes = minute_history()
    price_unit_minutes = replace(price_unit_minutes, conventions=replace(
        price_unit_minutes.conventions, price="CENTS_PER_SHARE"))
    price_unit_snapshot = snapshot(minute_history=price_unit_minutes)
    volume_unit_minutes = minute_history()
    volume_unit_minutes = replace(
        volume_unit_minutes,
        conventions=replace(volume_unit_minutes.conventions, volume="ROUND_LOTS"),
        bars=tuple(replace(item, volume_convention="ROUND_LOTS")
                   for item in volume_unit_minutes.bars),
    )
    volume_unit_snapshot = snapshot(minute_history=volume_unit_minutes)
    venue_premarket = premarket_history()
    venue_premarket = replace(venue_premarket, conventions=replace(
        venue_premarket.conventions, coverage_basis="UNKNOWN"))
    venue_snapshot = snapshot(premarket_history=venue_premarket)
    gap_daily = daily_history()
    gap_daily = replace(gap_daily, conventions=replace(
        gap_daily.conventions, coverage_basis="OTHER_COMPLETE"))
    gap_basis_snapshot = snapshot(daily_history=gap_daily)
    instrument_snapshot = snapshot(opening_trade=opening_trade(instrument_type="ETF"))
    mixed_session_snapshot = snapshot(
        evaluated_at=at("06:50:00"), minute_history=mixed_session_minute_history())
    mixed_no_trade_snapshot = snapshot(
        evaluated_at=at("06:50:00"),
        minute_history=mixed_session_minute_history(no_trade_open=True))
    minute_as_daily_snapshot = snapshot(daily_history=minute_history())
    daily_as_minute_snapshot = snapshot(
        evaluated_at=at("13:00:00"), minute_history=current_daily_history())
    assert values(mixed_session_snapshot)["ATR_1M_20_SMA_V1"].value == 2
    assert values(mixed_no_trade_snapshot)["ATR_1M_20_SMA_V1"].value == 1.9
    assert values(minute_as_daily_snapshot)["PDH_V1"].missing_reason == (
        "INCOMPATIBLE_HISTORY_INTERVAL")
    assert values(daily_as_minute_snapshot)["SESSION_VWAP_BAR_HLC3_V1"].missing_reason == (
        "INCOMPATIBLE_HISTORY_INTERVAL")
    constructor_rejections = []
    for label, changes in (
            ("NAN_OPEN", {"price": float("nan")}),
            ("POSITIVE_INFINITY_OPEN", {"price": float("inf")}),
            ("NEGATIVE_INFINITY_OPEN", {"price": float("-inf")}),
            ("OPTION_OPEN", {"instrument_type": "OPTION"})):
        with pytest.raises(ValueError):
            opening_trade(**changes)
        constructor_rejections.append(label)
    identity_snapshots = []
    identity_records = {}
    for history_name, history, feature_name in (
            ("minute_history", minute_history(), "SESSION_OPEN_TRADE_V1"),
            ("daily_history", daily_history(), "GAP_OPEN_V1"),
            ("premarket_history", premarket_history(), "PMH_V1")):
        revised = with_instrument_revision(history, prepend=True)
        before = snapshot(**{history_name: revised})
        after = snapshot(evaluated_at=at("06:32:01"), **{history_name: revised})
        assert before.to_json() == result.to_json()
        assert values(after)[feature_name].missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
        identity_snapshots.extend((before, after))
        identity_records[history_name] = {
            "before_availability": proof_summary(before),
            "at_availability": proof_summary(after),
        }
    truncated_pm = truncated_premarket_history()
    multiple_pm = multi_session_premarket_history()
    truncated_snapshot = snapshot(premarket_history=truncated_pm)
    multiple_snapshot = snapshot(premarket_history=multiple_pm)
    assert truncated_pm.coverage_at(at("06:32:00")).complete
    for name in ("PMH_V1", "PML_V1"):
        assert values(truncated_snapshot)[name].missing_reason == "INCOMPLETE_PREMARKET_WINDOW"
    assert multiple_pm.coverage_at(at("06:32:00")).complete
    assert multiple_snapshot.to_json() == result.to_json()
    payload = {
        "evidence": "SYNTHETIC_ONLY",
        "format": "COMPACT_SUMMARY_WITH_CANONICAL_SHA256",
        "minute_coverage": proof_summary(minute_history().coverage_at(at("06:32:00"))),
        "daily_coverage": proof_summary(daily_history().coverage_at(at("06:32:00"))),
        "premarket_coverage": proof_summary(premarket_history().coverage_at(at("06:32:00"))),
        "snapshot": proof_summary(result),
        "review_repair": {
            "first_trade_after_no_trade": proof_summary(first_trade_after_no_trade),
            "incomplete_atr_with_valid_prior_session": proof_summary(incomplete_atr),
            "opening_trade_after_evaluation": proof_summary(future_open),
        },
        "second_review_repair": {
            "missing_prior_daily_session": proof_summary(missing_prior),
            "no_daily_history": proof_summary(no_daily),
            "out_of_window_coverages": [proof_summary(history.coverage_at(at("06:32:00")))
                                       for history in (older_minute, older_daily, prior_minute)],
            "out_of_window_snapshots": [proof_summary(output) for output in off_window_snapshots],
            "shortened_session_coverages": [proof_summary(short_history.coverage_at(moment))
                                              for moment in short_times],
            "shortened_session_snapshots": [proof_summary(output) for output in short_snapshots],
            "shortened_daily_coverage": proof_summary(short_daily.coverage_at(after_short_session)),
            "shortened_daily_snapshot": proof_summary(short_daily_snapshot),
            "zero_volume_snapshot": proof_summary(zero_snapshot),
            "insufficient_warm_up_snapshot": proof_summary(warmup_snapshot),
        },
        "third_review_repair": {
            "wrong_price_unit_snapshot": proof_summary(price_unit_snapshot),
            "wrong_volume_unit_snapshot": proof_summary(volume_unit_snapshot),
            "unknown_venue_basis_snapshot": proof_summary(venue_snapshot),
            "mismatched_gap_basis_snapshot": proof_summary(gap_basis_snapshot),
            "mismatched_open_instrument_snapshot": proof_summary(instrument_snapshot),
            "constructor_rejections": constructor_rejections,
        },
        "fourth_review_repair": {
            "future_instrument_revisions": identity_records,
            "required_premarket_start": "01:00 Pacific",
            "truncated_request_coverage": proof_summary(truncated_pm.coverage_at(at("06:32:00"))),
            "truncated_request_snapshot": proof_summary(truncated_snapshot),
            "multi_session_request_coverage": proof_summary(multiple_pm.coverage_at(at("06:32:00"))),
            "multi_session_request_snapshot": proof_summary(multiple_snapshot),
        },
        "fifth_review_repair": {
            "mixed_session_minute_snapshot": proof_summary(mixed_session_snapshot),
            "mixed_session_no_trade_open_snapshot": proof_summary(mixed_no_trade_snapshot),
            "minute_history_as_daily_snapshot": proof_summary(minute_as_daily_snapshot),
            "daily_history_as_minute_snapshot": proof_summary(daily_as_minute_snapshot),
        },
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m31-core-price-features-proof.json").write_text(rendered)
    for output in (result, missing_prior, no_daily, *off_window_snapshots, *short_snapshots,
                   short_daily_snapshot, zero_snapshot, warmup_snapshot,
                   price_unit_snapshot, volume_unit_snapshot, venue_snapshot,
                   gap_basis_snapshot, instrument_snapshot, *identity_snapshots,
                   truncated_snapshot, multiple_snapshot, mixed_session_snapshot,
                   mixed_no_trade_snapshot, minute_as_daily_snapshot,
                   daily_as_minute_snapshot):
        assert FeatureSnapshot.from_json(output.to_json()).to_json() == output.to_json()


def _swing_history(highs, lows, *, no_trade=(), drop=None):
    days = session_dates(DAY.date() - timedelta(days=150), DAY.date() - timedelta(days=1))[-63:]
    request = HistoryRequest("SYNTH", as_utc(session_bounds(days[0])[0]),
                             as_utc(session_bounds(days[-1])[1]), interval="1d")
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        if number == drop:
            continue
        bars.append(bar(f"swing-{number}", interval.start, interval.end, high=highs[number],
                        low=lows[number], close=100, no_trade=number in no_trade))
    return batch(request, bars)


def test_daily_swings_use_two_strict_neighbors_and_plateaus():
    from consensus_engine.core_price_features import build_daily_swings

    highs, lows = [105.0] * 63, [95.0] * 63
    highs[10], highs[30], highs[31] = 110.0, 112.0, 112.0   # single and plateau swing highs
    highs[0], highs[1] = 105.0, 120.0                       # edge run is unconfirmed
    highs[62] = 130.0
    lows[20] = 90.0
    found = build_daily_swings(_swing_history(highs, lows), at("06:32:00"))
    assert found.state == "PRESENT" and found.highs == (110.0, 112.0) and found.lows == (90.0,)
    flat = [105.0] * 63
    tie = list(flat); tie[10], tie[11], tie[12] = 110.0, 109.0, 110.0   # equal neighbor
    assert build_daily_swings(_swing_history(tie, [95.0] * 63), at("06:32:00")).highs == ()
    empty = build_daily_swings(_swing_history(flat, [95.0] * 63), at("06:32:00"))
    assert empty.state == "KNOWN_EMPTY" and empty.highs == () and empty.lows == ()
    near = list(flat); near[10] = 110.0; near[11] = 110.0; near[12] = 110.0; near[13] = 110.0
    near[8] = 110.0                                          # left neighbor not strictly below
    assert build_daily_swings(_swing_history(near, [95.0] * 63), at("06:32:00")).highs == ()
    breaker = build_daily_swings(_swing_history(highs, lows, no_trade=(9,)), at("06:32:00"))
    assert 110.0 not in breaker.highs and breaker.state == "PRESENT"
    missing = build_daily_swings(_swing_history(highs, lows, drop=5), at("06:32:00"))
    assert missing.state == "UNKNOWN" and missing.reason == "INCOMPLETE_63_SESSION_DAILY_WINDOW"
    assert build_daily_swings(None, at("06:32:00")).reason == "MISSING_DAILY_HISTORY"
    assert build_daily_swings(minute_history(), at("06:32:00")).reason == "INCOMPATIBLE_HISTORY_INTERVAL"


def _profile_history(rows, *, drop=None):
    """Prior session (regular minutes) with a few traded bars; every other slot is no-trade."""
    previous = session_dates(DAY.date() - timedelta(days=10), DAY.date() - timedelta(days=1))[-1]
    opened, closed = map(as_utc, session_bounds(previous))
    request = HistoryRequest("SYNTH", opened, closed)
    bars = []
    for number, interval in enumerate(request.expected_intervals()):
        if number == drop:
            continue
        if number in rows:
            high, low, volume = rows[number]
            bars.append(bar(f"profile-{number}", interval.start, interval.end, high=high,
                            low=low, close=low, volume=volume))
        else:
            bars.append(bar(f"profile-{number}", interval.start, interval.end, high=0, low=0,
                            close=0, no_trade=True))
    return batch(request, bars)


def test_prior_session_bar_profile_bins_poc_and_value_area():
    from consensus_engine.core_price_features import build_prior_session_profile

    # tick 0.5, ATR 100 -> 2 ticks per bin, width 1.0; origin 99, bins [99,100) .. [102,103).
    rows = {0: (100.5, 100.5, 40), 1: (103.0, 101.0, 20), 2: (99.5, 99.5, 10), 3: (101.5, 101.5, 30)}
    minutes, daily = _profile_history(rows), daily_history()

    def run(close=101.2, **over):
        args = dict(prior_close=close, daily_atr=100.0, tick=0.5, evaluated_at=at("06:32:00"))
        args.update(over)
        return build_prior_session_profile(minutes, daily, **args)

    # bins hold 10, 40, 40, 10: POC ties, the one nearer the prior close wins.
    high = run()
    assert (high.state, high.poc, high.val, high.vah) == ("PRESENT", 101.5, 100.0, 102.0)
    assert len(high.input_record_ids) == len(minutes.bars)
    low = run(100.6)
    assert (low.poc, low.val, low.vah) == (100.5, 100.0, 102.0)
    even = run(101.0)                      # equal distance: the lower midpoint
    assert even.poc == 100.5
    assert run(prior_close=None).reason == "MISSING_PRIOR_CLOSE_OR_DAILY_ATR"
    for bad in (None, 0, -0.5, True, float("nan")):
        assert run(tick=bad).reason == "MISSING_OR_INVALID_TICK"
    assert build_prior_session_profile(
        None, daily, prior_close=1.0, daily_atr=1.0, tick=0.5,
        evaluated_at=at("06:32:00")).reason == "MISSING_MINUTE_HISTORY"
    assert build_prior_session_profile(
        minutes, None, prior_close=1.0, daily_atr=1.0, tick=0.5,
        evaluated_at=at("06:32:00")).reason == "MISSING_DAILY_HISTORY"
    hole = build_prior_session_profile(
        _profile_history(rows, drop=7), daily, prior_close=101.2, daily_atr=100.0, tick=0.5,
        evaluated_at=at("06:32:00"))
    assert hole.state == "UNKNOWN" and hole.reason == "INCOMPLETE_PRIOR_SESSION_MINUTES"
    quiet = build_prior_session_profile(
        _profile_history({}), daily, prior_close=101.2, daily_atr=100.0, tick=0.5,
        evaluated_at=at("06:32:00"))
    assert quiet.reason == "NO_POSITIVE_VOLUME_TRADED_BAR"
    # A small ATR floors at one tick: width 0.5 puts the flat 100.5 bar in [100.5, 101).
    narrow = run(daily_atr=0.5)
    assert narrow.state == "PRESENT" and narrow.poc % 0.5 == 0.25
