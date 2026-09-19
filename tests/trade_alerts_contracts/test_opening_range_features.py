"""M3.6 supplied-Bar five-minute opening-range checks; protected launcher only."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.opening_range_features import FEATURE_VERSION, build_opening_range_snapshot
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
NAMES = (
    "OPENING_RANGE_HIGH_5M_V1",
    "OPENING_RANGE_LOW_5M_V1",
    "OPENING_RANGE_MID_5M_V1",
    "OPENING_RANGE_WIDTH_5M_V1",
    "OPENING_RANGE_COMPLETE_5M_V1",
)


def at(clock, day="2026-07-06"):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M36_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, *, high=None, low=None, no_trade=False, available=None,
             revision=0, instrument_type="EQUITY", data_mode="SYNTHETIC_HISTORY",
             quality="VALID"):
    available = available or interval.end
    record_id = f"opening-{number}-r{revision}"
    meta = SourceMetadata(
        instrument_id="SYNTH", instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=available, available_time=available,
        normalized_time=available, session=interval.session, revision=revision,
        data_mode=data_mode, quality=quality,
    )
    high = 101 + number if high is None else high
    low = 99 - number if low is None else low
    return Bar(
        record_id=record_id, metadata=meta, start_time=interval.start, end_time=interval.end,
        is_final=True, open=None if no_trade else 100, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else 100,
        volume=0 if no_trade else 100 + number, adjustment_basis="SYNTHETIC_RAW",
        price_convention="USD_PER_SHARE", volume_convention="SHARES",
        certified_no_trade=no_trade,
    )


def history(day="2026-07-06", *, changed=None, broad=False):
    opened, closed = map(as_utc, session_bounds(datetime.fromisoformat(day).date()))
    request = HistoryRequest("SYNTH", opened, closed if broad else opened + timedelta(minutes=5))
    intervals = request.expected_intervals()
    if broad:
        intervals = intervals[:5]
    bars = [make_bar(number, interval) for number, interval in enumerate(intervals)]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", conventions(), tuple(bars))


def snapshot(supplied=None, *, evaluated=None, day="2026-07-06", **changes):
    minute_history = changes.pop(
        "minute_history", history(day) if supplied is None and session_bounds(
            datetime.fromisoformat(day).date()) is not None else supplied
    )
    values = dict(
        record_id="opening-range", evaluated_at=evaluated or at("06:35:00", day),
        symbol="SYNTH", instrument_type="EQUITY",
        minute_history=minute_history,
    )
    values.update(changes)
    return build_opening_range_snapshot(**values)


def values(output):
    return {value.name: value for value in output.features}


def range_values(output):
    found = values(output)
    return [found[name].value for name in NAMES]


def revised(bar, *, available=at("06:36:00"), **changes):
    meta = replace(
        bar.metadata, revision=bar.metadata.revision + 1, received_time=available,
        available_time=available, normalized_time=available,
    )
    return replace(bar, record_id=bar.record_id + "-revision", metadata=meta, **changes)


def wrong_interval_history():
    opened, closed = map(as_utc, session_bounds(datetime.fromisoformat("2026-07-06").date()))
    request = HistoryRequest("SYNTH", opened, closed, interval="1d")
    interval = request.expected_intervals()[0]
    return HistoryBatch(request, "SYNTHETIC", conventions(), (make_bar(0, interval),))


def test_hand_computed_range_and_canonical_round_trip():
    output = snapshot()
    assert range_values(output) == [105, 95, 100, 10, 1]
    assert [value.unit for value in output.features] == [
        "USD_PER_SHARE", "USD_PER_SHARE", "USD_PER_SHARE", "USD_PER_SHARE", "BOOLEAN"
    ]
    assert output.feature_version == FEATURE_VERSION
    assert len(output.input_record_ids) == 5
    assert FeatureSnapshot.from_json(output.to_json()) == output


@pytest.mark.parametrize(
    "clock,expected_reason",
    [("06:34:59", "OPENING_RANGE_NOT_ENDED"), ("06:35:00", None)],
)
def test_range_cannot_complete_before_fifth_interval_ends(clock, expected_reason):
    output = snapshot(evaluated=at(clock))
    found = values(output)
    assert found[NAMES[-1]].value == (0 if expected_reason else 1)
    assert found[NAMES[0]].missing_reason == expected_reason


def test_late_final_delays_range_availability():
    original = history()
    late = replace(
        original.bars[-1], metadata=replace(
            original.bars[-1].metadata, received_time=at("06:35:02"),
            available_time=at("06:35:02"), normalized_time=at("06:35:02"),
        ),
    )
    supplied = replace(original, bars=(*original.bars[:-1], late))
    assert values(snapshot(supplied))[NAMES[0]].missing_reason == "OPENING_RANGE_MISSING"
    assert range_values(snapshot(supplied, evaluated=at("06:35:02"))) == [105, 95, 100, 10, 1]


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda bars: bars[:-1], "OPENING_RANGE_MISSING"),
        (lambda bars: [*bars[:-1], replace(bars[-1], is_final=False)], "OPENING_RANGE_PROVISIONAL"),
        (lambda bars: [*bars[:-1], replace(bars[-1], metadata=replace(bars[-1].metadata, quality="INVALID"))],
         "OPENING_RANGE_QUALITY_INVALID"),
    ],
)
def test_missing_provisional_and_invalid_minutes_never_expose_extrema(change, reason):
    output = snapshot(history(changed=change))
    assert range_values(output) == [None, None, None, None, 0]
    assert values(output)[NAMES[0]].missing_reason == reason


def test_certified_no_trade_minute_adds_no_invented_extreme():
    supplied = history(changed=lambda bars: [
        replace(bars[0], open=None, high=None, low=None, close=None, volume=0,
                certified_no_trade=True), *bars[1:]
    ])
    assert range_values(snapshot(supplied)) == [105, 95, 100, 10, 1]


def test_all_certified_no_trade_minutes_are_not_a_range():
    supplied = history(changed=lambda bars: [
        replace(bar, open=None, high=None, low=None, close=None, volume=0,
                certified_no_trade=True) for bar in bars
    ])
    output = snapshot(supplied)
    assert range_values(output) == [None, None, None, None, 0]
    assert values(output)[NAMES[0]].missing_reason == "NO_TRADED_OPENING_RANGE_INTERVAL"


def test_duplicate_order_and_future_revision_preserve_frozen_view():
    original = history()
    duplicate = replace(
        original.bars[0], record_id="duplicate",
        metadata=replace(original.bars[0].metadata, received_time=at("06:31:01"),
                         available_time=at("06:31:01"), normalized_time=at("06:31:01")),
    )
    correction = revised(original.bars[-1], high=200)
    supplied = replace(original, bars=(correction, duplicate, *reversed(original.bars)))
    before = snapshot(supplied)
    assert range_values(before) == [105, 95, 100, 10, 1]
    assert range_values(snapshot(supplied, evaluated=at("06:36:00"))) == [200, 95, 147.5, 105, 1]
    assert range_values(before) == [105, 95, 100, 10, 1]


def test_new_invalid_revision_blocks_old_final():
    original = history()
    correction = revised(original.bars[0])
    correction = replace(correction, metadata=replace(correction.metadata, quality="INVALID"))
    supplied = replace(original, bars=(*original.bars, correction))
    assert range_values(snapshot(supplied))[-1] == 1
    assert values(snapshot(supplied, evaluated=at("06:36:00")))[NAMES[0]].missing_reason == \
        "OPENING_RANGE_QUALITY_INVALID"


def test_conflicting_and_overlapping_records_block():
    original = history()
    conflict = replace(original.bars[0], record_id="conflict", high=999)
    assert values(snapshot(replace(original, bars=(*original.bars, conflict))))[NAMES[0]].missing_reason == \
        "OPENING_RANGE_CONFLICT"
    malformed = replace(
        original.bars[0], record_id="overlap", start_time=original.bars[0].start_time + timedelta(seconds=1),
        metadata=replace(original.bars[0].metadata,
                         source_time=original.bars[0].start_time + timedelta(seconds=1)),
    )
    assert values(snapshot(replace(original, bars=(*original.bars, malformed))))[NAMES[0]].missing_reason == \
        "UNEXPECTED_OVERLAPPING_RECORD"


@pytest.mark.parametrize(
    "batch_change,reason",
    [
        (lambda item: wrong_interval_history(),
         "INCOMPATIBLE_HISTORY_INTERVAL"),
        (lambda item: replace(item, conventions=replace(item.conventions, price="CENTS")),
         "INCOMPATIBLE_PRICE_UNIT"),
        (lambda item: replace(item, conventions=replace(item.conventions, volume="LOTS")),
         "INCOMPATIBLE_VOLUME_UNIT"),
        (lambda item: replace(item, conventions=replace(item.conventions, coverage_basis="UNKNOWN")),
         "UNKNOWN_SOURCE_OR_VENUE_BASIS"),
    ],
)
def test_wrong_interval_units_and_unknown_basis_stay_incomplete(batch_change, reason):
    output = snapshot(batch_change(history()))
    assert values(output)[NAMES[0]].missing_reason == reason
    assert range_values(output)[-1] == 0


def test_wrong_symbol_instrument_type_and_mixed_mode_stay_incomplete():
    original = history()
    assert values(snapshot(original, symbol="OTHER"))[NAMES[0]].missing_reason == "INCOMPATIBLE_SYMBOL"
    wrong_type = replace(original.bars[0], metadata=replace(original.bars[0].metadata,
                                                             instrument_type="ETF"))
    assert values(snapshot(replace(original, bars=(wrong_type, *original.bars[1:]))))[NAMES[0]].missing_reason == \
        "INCOMPATIBLE_INSTRUMENT_TYPE"
    mixed = replace(original.bars[0], metadata=replace(original.bars[0].metadata,
                                                        data_mode="OTHER_MODE"))
    assert values(snapshot(replace(original, bars=(mixed, *original.bars[1:]))))[NAMES[0]].missing_reason == \
        "OPENING_RANGE_INCOMPATIBLE_MODE"


def test_future_identity_revision_cannot_change_earlier_scope():
    original = history()
    correction = revised(original.bars[0])
    correction = replace(correction, metadata=replace(correction.metadata, instrument_type="ETF"))
    supplied = replace(original, bars=(*original.bars, correction))
    assert range_values(snapshot(supplied)) == [105, 95, 100, 10, 1]
    assert values(snapshot(supplied, evaluated=at("06:36:00")))[NAMES[0]].missing_reason == \
        "INCOMPATIBLE_INSTRUMENT_TYPE"


@pytest.mark.parametrize("day", ["2026-03-09", "2026-11-02", "2026-11-27"])
def test_clock_changes_and_shortened_session_keep_open_relative_range(day):
    assert range_values(snapshot(day=day)) == [105, 95, 100, 10, 1]


def test_holiday_has_no_opening_range():
    output = snapshot(None, day="2026-07-04", minute_history=None)
    assert values(output)[NAMES[0]].missing_reason == "NO_REGULAR_SESSION"
    assert range_values(output)[-1] == 0


def test_broad_request_uses_only_the_five_opening_slots():
    output = snapshot(history(broad=True))
    assert range_values(output) == [105, 95, 100, 10, 1]
    assert len(output.input_record_ids) == 5


@pytest.mark.parametrize("start_minute,end_minute", [(0, 4), (10, 15)])
def test_request_must_cover_every_opening_interval(start_minute, end_minute):
    original = history()
    opened = original.request.start
    request = HistoryRequest(
        original.request.symbol,
        opened + timedelta(minutes=start_minute),
        opened + timedelta(minutes=end_minute),
    )
    output = snapshot(replace(original, request=request))
    assert range_values(output) == [None, None, None, None, 0]
    assert values(output)[NAMES[0]].missing_reason == "OPENING_RANGE_NOT_REQUESTED"
    assert output.input_record_ids == ()


def test_missing_input_and_invalid_public_scope_are_explicit():
    assert values(snapshot(None, minute_history=None))[NAMES[0]].missing_reason == "MISSING_MINUTE_HISTORY"
    with pytest.raises(RecordError, match="symbol is required"):
        snapshot(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        snapshot(instrument_type="OPTION")


def test_snapshot_is_deeply_immutable():
    output = snapshot()
    with pytest.raises(FrozenInstanceError):
        output.features = ()
    detached = output.as_dict()
    detached["features"][0]["value"] = 0
    assert range_values(output)[0] == 105


def proof_summary(output):
    raw = output.to_json().encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "evaluated_at_pacific": output.evaluated_at.astimezone(PACIFIC).isoformat(),
        "features": [
            {"name": value.name, "value": value.value, "missing_reason": value.missing_reason,
             "input_count": len(value.input_record_ids)} for value in output.features
        ],
    }


def test_bar_coverage_opening_range_recording_end_to_end():
    original = history(broad=True)
    request = HistoryRequest(
        original.request.symbol, original.request.start, original.request.end,
        original.request.interval, original.request.session_scope, original.request.premarket_start,
    )
    supplied = replace(
        original, request=request, bars=tuple(Bar.from_json(bar.to_json()) for bar in original.bars)
    )
    outputs = [snapshot(supplied, evaluated=at(clock)) for clock in (
        "06:34:59", "06:35:00", "06:35:01"
    )]
    assert [range_values(output) for output in outputs] == [
        [None, None, None, None, 0], [105, 95, 100, 10, 1], [105, 95, 100, 10, 1]
    ]
    frozen = outputs[1].to_json()
    late_invalid = revised(supplied.bars[0])
    late_invalid = replace(late_invalid, metadata=replace(late_invalid.metadata, quality="INVALID"))
    outputs.append(snapshot(replace(supplied, bars=(*supplied.bars, late_invalid)),
                            evaluated=at("06:36:00")))
    assert range_values(outputs[-1]) == [None, None, None, None, 0]
    assert outputs[1].to_json() == frozen
    all_empty = replace(supplied, bars=tuple(
        replace(bar, open=None, high=None, low=None, close=None, volume=0,
                certified_no_trade=True) for bar in supplied.bars
    ))
    outputs.append(snapshot(all_empty))
    assert values(outputs[-1])[NAMES[0]].missing_reason == "NO_TRADED_OPENING_RANGE_INTERVAL"
    for start_minute, end_minute in ((0, 4), (10, 15)):
        request = HistoryRequest(
            supplied.request.symbol,
            supplied.request.start + timedelta(minutes=start_minute),
            supplied.request.start + timedelta(minutes=end_minute),
        )
        outputs.append(snapshot(replace(supplied, request=request)))
        assert values(outputs[-1])[NAMES[0]].missing_reason == "OPENING_RANGE_NOT_REQUESTED"
    for day in ("2026-03-09", "2026-11-27"):
        daily = history(day, broad=True)
        outputs.append(snapshot(replace(daily, bars=tuple(
            Bar.from_json(bar.to_json()) for bar in daily.bars)), day=day))
    assert all(FeatureSnapshot.from_json(output.to_json()) == output for output in outputs)
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY", "feature_version": FEATURE_VERSION,
        "snapshots": [proof_summary(output) for output in outputs],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m36-opening-range-features-proof.json").write_text(rendered)
