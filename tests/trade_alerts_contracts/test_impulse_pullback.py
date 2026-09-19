"""M8.3 supplied-bar impulse freeze and pullback checks; protected launcher only."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import impulse_pullback
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.impulse_pullback import (
    DATA_MODE,
    FEATURE_NAMES,
    FEATURE_VERSION,
    PullbackPolicy,
    build_impulse_pullback_snapshot,
)
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
# One synthetic session: five rising minutes, a quieter drift back, then a new high.
PLAN = (
    (100.00, 99.00, 900), (101.00, 99.50, 1000), (102.00, 100.50, 1200),
    (103.00, 101.50, 1400), (104.00, 103.00, 1500),
    (103.50, 102.50, 900), (103.00, 102.00, 700), (102.60, 102.00, 600),
    (103.20, 102.40, 800), (104.50, 103.00, 1100),
)
# The same session read downward, so the short direction is a real mirror.
MIRROR = tuple((200.00 - low, 200.00 - high, volume) for high, low, volume in PLAN)
LONG = PullbackPolicy(
    version="M83_TEST_LEGS_V1", definition_reference="M83_SYNTHETIC_LEGS_ONLY",
    direction="LONG", min_pullback_bars=1, measure_from_close=False,
)
SHORT = replace(LONG, direction="SHORT")
FROM_CLOSE = replace(LONG, measure_from_close=True)
PATIENT = replace(LONG, min_pullback_bars=5)


def at(clock, day=DAY):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M83_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, prices, *, no_trade=False, revision=0, quality="VALID",
             is_final=True, instrument_type="EQUITY", data_mode="SYNTHETIC_HISTORY",
             available=None, symbol="SYNTH"):
    high, low, volume = prices
    middle = round((high + low) / 2, 2)
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=available or interval.end,
        available_time=available or interval.end, normalized_time=available or interval.end,
        session=interval.session, revision=revision, data_mode=data_mode, quality=quality,
    )
    empty = no_trade or quality == "UNAVAILABLE"
    return Bar(
        record_id=f"legs-{number}-r{revision}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if empty else middle, high=None if empty else high,
        low=None if empty else low, close=None if empty else middle,
        volume=(0 if no_trade else None) if empty else volume,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def history(day=DAY, *, plan=PLAN, first_minute=0, changed=None, source="SYNTHETIC",
            supplied_conventions=None, **request_changes):
    opened = as_utc(session_bounds(datetime.fromisoformat(day).date())[0])
    values = dict(
        symbol="SYNTH", start=opened + timedelta(minutes=first_minute),
        end=opened + timedelta(minutes=len(plan)),
    )
    values.update(request_changes)
    request = HistoryRequest(**values)
    bars = [make_bar(first_minute + number, interval, plan[first_minute + number],
                     symbol=request.symbol)
            for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, source, supplied_conventions or conventions(), tuple(bars))


def snapshot(supplied=None, *, evaluated=None, started=None, frozen=None, policy=LONG,
             atr_1m=0.10, vwap=101.50, day=DAY, **changes):
    if supplied is None and "minute_history" not in changes:
        supplied = history(day)
    values = dict(
        record_id="impulse-pullback", evaluated_at=evaluated or at("06:39:00", day),
        symbol="SYNTH", instrument_type="EQUITY", minute_history=supplied, policy=policy,
        impulse_started_at=started or at("06:30:00", day),
        impulse_frozen_at=frozen or at("06:35:00", day), atr_1m=atr_1m, vwap=vwap,
    )
    values.update(changes)
    return build_impulse_pullback_snapshot(**values)


def mirrored(**changes):
    values = dict(policy=SHORT, vwap=98.50)
    values.update(changes)
    return snapshot(history(plan=MIRROR), **values)


def values(output):
    return {item.name: item for item in output.features}


def numbers(output, *names):
    return [values(output)[name].value for name in names]


def reasons(output, *names):
    return [values(output)[name].missing_reason for name in names]


def test_the_impulse_leg_is_measured_over_the_supplied_frozen_window():
    output = snapshot()
    assert numbers(output, "IMPULSE_ORIGIN_V1", "IMPULSE_EXTREME_V1", "IMPULSE_DISTANCE_V1",
                   "IMPULSE_BAR_COUNT_V1", "IMPULSE_VOLUME_V1") == [99.00, 104.00, 5.00, 5, 6000]
    assert numbers(output, "IMPULSE_EXTREME_AFTER_ORIGIN_V1", "IMPULSE_COMPLETE_V1") == [1, 1]
    assert values(output)["IMPULSE_EXTREME_V1"].input_record_ids == tuple(
        f"legs-{number}-r0" for number in range(5))


def test_a_later_high_never_moves_the_frozen_impulse():
    later = snapshot(evaluated=at("06:40:00"))
    assert numbers(later, "IMPULSE_EXTREME_V1") == [104.00]
    # 104.50 prints in the pullback window; the frozen impulse must not follow it.
    assert max(high for high, _, _ in PLAN) == 104.50
    assert numbers(later, "PULLBACK_BAR_COUNT_V1", "REVERSAL_BAR_HIGH_V1") == [5, 104.50]
    shorter = snapshot(frozen=at("06:33:00"))
    assert numbers(shorter, "IMPULSE_EXTREME_V1", "IMPULSE_DISTANCE_V1",
                   "IMPULSE_BAR_COUNT_V1") == [102.00, 3.00, 3]


def test_the_pullback_is_measured_over_the_minutes_since_the_freeze():
    output = snapshot()
    assert numbers(output, "PULLBACK_EXTREME_V1", "PULLBACK_BAR_COUNT_V1",
                   "REVERSAL_BAR_HIGH_V1", "REVERSAL_BAR_LOW_V1",
                   "PULLBACK_VOLUME_V1") == [102.00, 4, 103.20, 102.40, 3000]
    assert numbers(output, "PULLBACK_DEPTH_V1", "PULLBACK_RETRACEMENT_V1",
                   "PULLBACK_VOLUME_RATIO_V1", "PULLBACK_COMPLETE_V1") == [2.00, 0.4, 0.5, 1]
    assert values(output)["PULLBACK_EXTREME_V1"].input_record_ids == tuple(
        f"legs-{number}-r0" for number in range(5, 9))


def test_the_short_direction_mirrors_the_long_measurement():
    output = mirrored()
    assert numbers(output, "IMPULSE_ORIGIN_V1", "IMPULSE_EXTREME_V1", "IMPULSE_DISTANCE_V1",
                   "IMPULSE_VOLUME_V1") == [101.00, 96.00, 5.00, 6000]
    assert numbers(output, "PULLBACK_EXTREME_V1", "PULLBACK_DEPTH_V1",
                   "PULLBACK_RETRACEMENT_V1", "PULLBACK_VOLUME_RATIO_V1") == [98.00, 2.00, 0.4, 0.5]
    assert numbers(output, "IMPULSE_EXTREME_AFTER_ORIGIN_V1", "PULLBACK_COMPLETE_V1") == [1, 1]
    assert numbers(output, "IMPULSE_DISTANCE_ATR_V1", "IMPULSE_EXTREME_FROM_VWAP_ATR_V1",
                   "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == [50.0, 25.0, 5.0]
    # The same session read in the long direction is a different leg, not a refusal:
    # its origin and extreme swap ends and the extreme no longer follows the origin.
    opposite = mirrored(policy=LONG)
    assert numbers(opposite, "IMPULSE_ORIGIN_V1", "IMPULSE_EXTREME_V1",
                   "IMPULSE_DISTANCE_V1") == [96.00, 101.00, 5.00]
    assert numbers(opposite, "IMPULSE_EXTREME_AFTER_ORIGIN_V1") == [0]
    assert numbers(opposite, "PULLBACK_EXTREME_V1", "PULLBACK_DEPTH_V1") == [96.50, 4.50]


def test_the_supplied_reading_convention_changes_the_legs_it_measures():
    output = snapshot(policy=FROM_CLOSE)
    assert numbers(output, "IMPULSE_ORIGIN_V1", "IMPULSE_EXTREME_V1",
                   "IMPULSE_DISTANCE_V1") == [99.50, 103.50, 4.00]
    assert numbers(output, "PULLBACK_EXTREME_V1", "PULLBACK_DEPTH_V1",
                   "PULLBACK_RETRACEMENT_V1") == [102.30, 1.20, 0.3]
    # The reversal bar keeps its own traded extremes under either convention.
    assert numbers(output, "REVERSAL_BAR_HIGH_V1", "REVERSAL_BAR_LOW_V1") == [103.20, 102.40]
    assert numbers(output, "IMPULSE_EXTREME_FROM_VWAP_ATR_V1",
                   "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == [20.0, 8.0]


def test_an_extreme_that_printed_before_its_origin_is_reported_not_refused():
    plan = ((104.00, 103.00, 900), (103.00, 102.00, 1000), (102.00, 101.00, 1200),
            (101.00, 100.00, 1400), (100.00, 99.00, 1500)) + PLAN[5:]
    output = snapshot(history(plan=plan))
    assert numbers(output, "IMPULSE_EXTREME_AFTER_ORIGIN_V1", "IMPULSE_COMPLETE_V1") == [0, 1]
    assert numbers(output, "IMPULSE_ORIGIN_V1", "IMPULSE_EXTREME_V1") == [99.00, 104.00]


def test_a_pullback_deeper_than_its_impulse_is_reported_as_measured():
    plan = PLAN[:7] + ((99.00, 98.00, 600),) + PLAN[8:]
    output = snapshot(history(plan=plan))
    assert numbers(output, "PULLBACK_EXTREME_V1", "PULLBACK_DEPTH_V1",
                   "PULLBACK_RETRACEMENT_V1") == [98.00, 6.00, 1.2]
    # A pullback that never gave anything back reads negative rather than zero.
    rising = PLAN[:5] + tuple((high + 3.00, low + 3.00, volume) for high, low, volume in PLAN[5:])
    output = snapshot(history(plan=rising))
    assert numbers(output, "PULLBACK_EXTREME_V1", "PULLBACK_DEPTH_V1",
                   "PULLBACK_RETRACEMENT_V1") == [105.00, -1.00, -0.2]


def test_a_flat_impulse_and_a_volumeless_impulse_report_no_ratio_instead_of_dividing():
    flat = tuple((101.50, 101.50, volume) for _, _, volume in PLAN)
    output = snapshot(history(plan=flat))
    assert numbers(output, "IMPULSE_DISTANCE_V1", "PULLBACK_DEPTH_V1") == [0.00, 0.00]
    assert reasons(output, "PULLBACK_RETRACEMENT_V1") == ["ZERO_IMPULSE_DISTANCE"]
    assert numbers(output, "PULLBACK_COMPLETE_V1", "IMPULSE_DISTANCE_ATR_V1") == [1, 0.0]

    quiet = tuple((high, low, 0) for high, low, _ in PLAN[:5]) + PLAN[5:]
    output = snapshot(history(plan=quiet))
    assert numbers(output, "IMPULSE_VOLUME_V1", "PULLBACK_VOLUME_V1") == [0, 3000]
    assert reasons(output, "PULLBACK_VOLUME_RATIO_V1") == ["ZERO_IMPULSE_VOLUME"]
    assert numbers(output, "PULLBACK_RETRACEMENT_V1") == [0.4]


def test_the_impulse_window_must_be_a_reachable_run_of_session_minutes():
    cases = {
        (at("06:30:00"), at("06:41:00")): "IMPULSE_FREEZE_AFTER_EVALUATION",
        (at("06:30:30"), at("06:35:00")): "IMPULSE_WINDOW_NOT_MINUTE_ALIGNED",
        (at("06:30:00"), at("06:35:30")): "IMPULSE_WINDOW_NOT_MINUTE_ALIGNED",
        (at("06:35:00"), at("06:35:00")): "EMPTY_IMPULSE_WINDOW",
        (at("06:36:00"), at("06:35:00")): "EMPTY_IMPULSE_WINDOW",
        (at("06:00:00"), at("06:35:00")): "IMPULSE_WINDOW_OUTSIDE_REGULAR_SESSION",
    }
    for (started, frozen), reason in cases.items():
        output = snapshot(started=started, frozen=frozen)
        assert reasons(output, "IMPULSE_ORIGIN_V1", "IMPULSE_VOLUME_V1",
                       "IMPULSE_DISTANCE_ATR_V1") == [reason] * 3
        assert numbers(output, "IMPULSE_COMPLETE_V1") == [0]
        assert reasons(output, "PULLBACK_RETRACEMENT_V1") == [reason]


def test_a_refused_impulse_does_not_block_the_pullback_measurement():
    output = snapshot(history(first_minute=2))
    assert reasons(output, "IMPULSE_ORIGIN_V1") == ["IMPULSE_WINDOW_NOT_COVERED"]
    assert numbers(output, "PULLBACK_COMPLETE_V1", "PULLBACK_EXTREME_V1") == [1, 102.00]
    assert reasons(output, "PULLBACK_DEPTH_V1", "IMPULSE_EXTREME_FROM_VWAP_ATR_V1") == [
        "IMPULSE_WINDOW_NOT_COVERED"] * 2


def test_an_unready_untraded_or_contradicted_impulse_minute_is_refused():
    def provisional(bars):
        return [replace(bar, is_final=False) if index == 1 else bar
                for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=provisional)), "IMPULSE_ORIGIN_V1") == [
        "IMPULSE_PROVISIONAL"]

    def missing(bars):
        return [bar for index, bar in enumerate(bars) if index != 3]

    assert reasons(snapshot(history(changed=missing)), "IMPULSE_ORIGIN_V1") == ["IMPULSE_MISSING"]

    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 2 else bar
                for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=quiet)), "IMPULSE_ORIGIN_V1") == [
        "NO_TRADED_IMPULSE_INTERVAL"]

    def foreign(bars):
        return [replace(bar, metadata=replace(bar.metadata, instrument_type="ETF"))
                if index == 4 else bar for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=foreign)), "IMPULSE_ORIGIN_V1") == [
        "INCOMPATIBLE_INSTRUMENT_TYPE"]

    def overlapping(bars):
        start = bars[2].start_time + timedelta(seconds=30)
        end = bars[2].end_time + timedelta(seconds=30)
        meta = replace(bars[2].metadata, source_time=start, received_time=end,
                       available_time=end, normalized_time=end)
        return [*bars, replace(bars[2], record_id="legs-overlap", metadata=meta,
                               start_time=start, end_time=end)]

    assert reasons(snapshot(history(changed=overlapping)), "IMPULSE_ORIGIN_V1") == [
        "UNEXPECTED_OVERLAPPING_RECORD"]


def test_the_pullback_needs_the_completed_minutes_its_definition_asks_for():
    assert reasons(snapshot(evaluated=at("06:35:00")), "PULLBACK_EXTREME_V1") == [
        "INCOMPLETE_PULLBACK_WINDOW"]
    assert numbers(snapshot(evaluated=at("06:35:00")), "PULLBACK_COMPLETE_V1",
                   "IMPULSE_COMPLETE_V1") == [0, 1]
    # Four completed minutes satisfy one supplied definition and not the other.
    assert numbers(snapshot(), "PULLBACK_BAR_COUNT_V1") == [4]
    assert reasons(snapshot(policy=PATIENT), "PULLBACK_EXTREME_V1") == [
        "INCOMPLETE_PULLBACK_WINDOW"]
    assert numbers(snapshot(policy=PATIENT, evaluated=at("06:40:00")),
                   "PULLBACK_BAR_COUNT_V1") == [5]


def test_an_unready_or_untraded_pullback_minute_is_refused():
    def provisional(bars):
        return [replace(bar, is_final=False) if index == 6 else bar
                for index, bar in enumerate(bars)]

    output = snapshot(history(changed=provisional))
    assert reasons(output, "PULLBACK_EXTREME_V1") == ["PULLBACK_PROVISIONAL"]
    assert numbers(output, "IMPULSE_COMPLETE_V1", "IMPULSE_DISTANCE_ATR_V1") == [1, 50.0]

    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 7 else bar
                for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=quiet)), "PULLBACK_EXTREME_V1") == [
        "NO_TRADED_PULLBACK_INTERVAL"]

    def missing(bars):
        return [bar for index, bar in enumerate(bars) if index != 6]

    assert reasons(snapshot(history(changed=missing)), "PULLBACK_EXTREME_V1") == [
        "PULLBACK_MISSING"]


def test_distances_are_reported_in_supplied_minute_atr_units_against_the_supplied_vwap():
    output = snapshot()
    assert numbers(output, "IMPULSE_DISTANCE_ATR_V1", "IMPULSE_EXTREME_FROM_VWAP_ATR_V1",
                   "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == [50.0, 25.0, 5.0]
    assert values(output)["PULLBACK_EXTREME_FROM_VWAP_ATR_V1"].unit == "RATIO"
    # A pullback that fell through the supplied VWAP reads negative, not unavailable.
    assert numbers(snapshot(vwap=102.50), "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == [-5.0]
    assert reasons(snapshot(atr_1m=None), "IMPULSE_DISTANCE_ATR_V1",
                   "IMPULSE_EXTREME_FROM_VWAP_ATR_V1") == ["MISSING_ATR_1M"] * 2
    assert reasons(snapshot(atr_1m=0.0), "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == [
        "NONPOSITIVE_ATR_1M"]
    assert reasons(snapshot(atr_1m=-0.5), "IMPULSE_DISTANCE_ATR_V1") == ["NONPOSITIVE_ATR_1M"]
    missing = snapshot(vwap=None)
    assert reasons(missing, "IMPULSE_EXTREME_FROM_VWAP_ATR_V1",
                   "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == ["MISSING_VWAP"] * 2
    assert numbers(missing, "IMPULSE_DISTANCE_ATR_V1") == [50.0]
    for bad in (float("nan"), True, "0.10"):
        with pytest.raises(RecordError, match="minute ATR"):
            snapshot(atr_1m=bad)
        with pytest.raises(RecordError, match="supplied VWAP"):
            snapshot(vwap=bad)


def test_incompatible_or_absent_history_is_named_for_every_feature():
    cases = {
        "MISSING_MINUTE_HISTORY": None,
        "INCOMPATIBLE_SYMBOL": history(symbol="OTHER"),
        "UNKNOWN_SOURCE_OR_VENUE_BASIS": history(
            supplied_conventions=conventions(coverage_basis="UNKNOWN")),
        "INCOMPATIBLE_PRICE_UNIT": history(
            supplied_conventions=conventions(price="USD_PER_CONTRACT")),
        "INCOMPATIBLE_VOLUME_UNIT": history(
            supplied_conventions=conventions(volume="CONTRACTS")),
    }
    for reason, supplied in cases.items():
        output = snapshot(minute_history=supplied)
        assert reasons(output, "IMPULSE_ORIGIN_V1", "PULLBACK_EXTREME_V1",
                       "PULLBACK_RETRACEMENT_V1",
                       "PULLBACK_EXTREME_FROM_VWAP_ATR_V1") == [reason] * 4
        assert numbers(output, "IMPULSE_COMPLETE_V1", "PULLBACK_COMPLETE_V1") == [0, 0]
        assert output.input_record_ids == ()


def test_daily_history_and_a_closed_day_are_refused_by_name():
    opened = as_utc(session_bounds(datetime.fromisoformat(DAY).date())[0])
    closed = as_utc(session_bounds(datetime.fromisoformat(DAY).date())[1])
    daily = HistoryBatch(HistoryRequest("SYNTH", opened, closed, "1d"), "SYNTHETIC",
                         conventions(), ())
    assert reasons(snapshot(daily), "IMPULSE_ORIGIN_V1") == ["INCOMPATIBLE_HISTORY_INTERVAL"]
    holiday = snapshot(None, minute_history=None, day="2026-07-03",
                       evaluated=at("06:39:00", "2026-07-03"),
                       started=at("06:30:00", "2026-07-03"),
                       frozen=at("06:35:00", "2026-07-03"))
    assert reasons(holiday, "IMPULSE_ORIGIN_V1", "PULLBACK_EXTREME_V1") == ["NO_REGULAR_SESSION"] * 2


def test_the_supplied_definition_must_be_explicit_and_coherent():
    with pytest.raises(RecordError, match="policy version"):
        replace(LONG, version=" ")
    with pytest.raises(RecordError, match="definition reference"):
        replace(LONG, definition_reference="UNKNOWN")
    for direction in ("BOTH", "long", ""):
        with pytest.raises(RecordError, match="policy direction"):
            replace(LONG, direction=direction)
    for count in (0, -1, 2.0, True):
        with pytest.raises(RecordError, match="min_pullback_bars"):
            replace(LONG, min_pullback_bars=count)
    with pytest.raises(RecordError, match="measure_from_close"):
        replace(LONG, measure_from_close=1)
    assert LONG.long is True and SHORT.long is False
    with pytest.raises(FrozenInstanceError):
        LONG.min_pullback_bars = 4


def test_public_scope_is_checked_before_any_measurement():
    with pytest.raises(RecordError, match="symbol is required"):
        snapshot(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        snapshot(instrument_type="OPTION")
    with pytest.raises(RecordError, match="PullbackPolicy"):
        snapshot(policy="M83")
    with pytest.raises(RecordError, match="impulse start instant"):
        snapshot(started=1)
    with pytest.raises(RecordError, match="impulse freeze instant"):
        snapshot(frozen="06:35:00")
    with pytest.raises(ValueError):
        snapshot(evaluated=datetime.fromisoformat(DAY + "T06:39:00"))


def test_the_module_adopts_no_rule_number_of_its_own():
    source = inspect.getsource(impulse_pullback)
    for token in ("0.40", "0.15", "0.25", "0.65", "0.70", "0.80", "0.35", "1.5", "rs_15m"):
        assert token not in source
    assert sorted(FEATURE_NAMES) == sorted(item.name for item in snapshot().features)
    assert snapshot().metadata.data_mode == DATA_MODE
    assert snapshot().metadata.source == "DERIVED_M83"


def test_snapshot_is_deeply_immutable_and_round_trips():
    output = snapshot()
    with pytest.raises(FrozenInstanceError):
        output.features = ()
    detached = output.as_dict()
    detached["features"][0]["value"] = 0
    assert numbers(output, "IMPULSE_ORIGIN_V1") == [99.00]
    assert FeatureSnapshot.from_json(output.to_json()) == output


def proof_summary(output):
    raw = output.to_json().encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "evaluated_at_pacific": output.evaluated_at.astimezone(PACIFIC).isoformat(),
        "features": [
            {"name": item.name, "value": item.value, "missing_reason": item.missing_reason,
             "input_count": len(item.input_record_ids)} for item in output.features
        ],
    }


def test_impulse_pullback_recording_end_to_end():
    supplied = history()
    detached = replace(supplied, bars=tuple(Bar.from_json(bar.to_json()) for bar in supplied.bars))
    outputs = [snapshot(detached, evaluated=at(clock)) for clock in (
        "06:35:59", "06:36:00", "06:36:01", "06:39:00", "06:40:00"
    )]
    # The pullback walks forward one whole minute at a time; the impulse does not.
    assert [numbers(output, "PULLBACK_BAR_COUNT_V1", "PULLBACK_EXTREME_V1")
            for output in outputs] == [[None, None], [1, 102.50], [1, 102.50], [4, 102.00],
                                       [5, 102.00]]
    assert [numbers(output, "IMPULSE_EXTREME_V1") for output in outputs] == [[104.00]] * 5
    frozen = outputs[3].to_json()
    outputs.append(snapshot(detached, policy=FROM_CLOSE))
    outputs.append(mirrored())
    outputs.append(snapshot(detached, atr_1m=None, vwap=None))
    outputs.append(snapshot(detached, frozen=at("06:33:00")))
    assert outputs[3].to_json() == frozen
    assert all(FeatureSnapshot.from_json(output.to_json()) == output for output in outputs)
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY", "feature_version": FEATURE_VERSION,
        "snapshots": [proof_summary(output) for output in outputs],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m8_3_impulse_pullback_proof.json").write_text(rendered)
