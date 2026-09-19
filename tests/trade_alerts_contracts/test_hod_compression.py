"""M7.1 supplied-Bar HOD/LOD freeze and compression checks; protected launcher only."""

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

from consensus_engine import hod_compression
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.hod_compression import (
    DATA_MODE,
    FEATURE_NAMES,
    FEATURE_VERSION,
    CompressionPolicy,
    build_hod_compression_snapshot,
)
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"
# One synthetic session: a morning high, a drift down, then a quiet stretch.
PLAN = (
    (100.00, 99.00), (101.00, 99.50), (102.00, 100.50), (101.80, 101.00),
    (101.60, 101.10), (101.70, 101.20), (101.50, 101.30), (101.45, 101.32),
    (101.44, 101.33), (101.43, 101.34), (101.60, 101.00), (103.00, 101.50),
)
OVERLAP = CompressionPolicy(
    version="M71_TEST_WINDOW_V1", definition_reference="M71_SYNTHETIC_WINDOW_ONLY",
    recent_bars=3, prior_bars=7, prior_includes_recent=True,
)
SPLIT = replace(OVERLAP, prior_bars=4, prior_includes_recent=False)


def at(clock, day=DAY):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M71_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, prices, *, no_trade=False, revision=0, quality="VALID",
             is_final=True, instrument_type="EQUITY", data_mode="SYNTHETIC_HISTORY",
             available=None, symbol="SYNTH"):
    high, low = prices
    middle = round((high + low) / 2, 2)
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=available or interval.end,
        available_time=available or interval.end, normalized_time=available or interval.end,
        session=interval.session, revision=revision, data_mode=data_mode, quality=quality,
    )
    empty = no_trade or quality == "UNAVAILABLE"
    return Bar(
        record_id=f"compression-{number}-r{revision}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if empty else middle, high=None if empty else high,
        low=None if empty else low, close=None if empty else middle,
        volume=(0 if no_trade else None) if empty else 1000 + number,
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


def snapshot(supplied=None, *, evaluated=None, frozen=None, policy=OVERLAP, atr_1m=0.10,
             day=DAY, **changes):
    if supplied is None and "minute_history" not in changes:
        supplied = history(day)
    values = dict(
        record_id="hod-compression", evaluated_at=evaluated or at("06:40:00", day),
        symbol="SYNTH", instrument_type="EQUITY", minute_history=supplied,
        policy=policy, reference_frozen_at=frozen or at("06:33:00", day), atr_1m=atr_1m,
    )
    values.update(changes)
    return build_hod_compression_snapshot(**values)


def values(output):
    return {item.name: item for item in output.features}


def numbers(output, *names):
    return [values(output)[name].value for name in names]


def reasons(output, *names):
    return [values(output)[name].missing_reason for name in names]


def test_reference_extreme_is_frozen_and_never_reads_a_later_bar():
    output = snapshot()
    assert numbers(output, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1",
                   "REFERENCE_EXTREME_COMPLETE_V1") == [102.00, 99.00, 1]
    # 103.00 prints later in the same session; the frozen reference must not move.
    later = snapshot(evaluated=at("06:42:00"))
    assert numbers(later, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1") == [102.00, 99.00]
    assert max(high for high, _ in PLAN) == 103.00
    early = snapshot(frozen=at("06:32:00"))
    assert numbers(early, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1") == [101.00, 99.00]


def test_freeze_instant_must_be_a_reachable_session_minute():
    cases = {
        at("06:41:00"): "FREEZE_INSTANT_AFTER_EVALUATION",
        at("06:33:30"): "FREEZE_INSTANT_NOT_MINUTE_ALIGNED",
        at("06:30:00"): "FREEZE_INSTANT_OUTSIDE_REGULAR_SESSION",
        at("06:00:00"): "FREEZE_INSTANT_OUTSIDE_REGULAR_SESSION",
    }
    for frozen, reason in cases.items():
        output = snapshot(frozen=frozen)
        assert reasons(output, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1") == [reason, reason]
        assert numbers(output, "REFERENCE_EXTREME_COMPLETE_V1") == [0]
        # A refused reference never blocks the window measurement itself.
        assert numbers(output, "COMPRESSION_COMPLETE_V1") == [1]
        assert reasons(output, "DISTANCE_TO_REFERENCE_HOD_ATR_V1") == [reason]


def test_reference_window_must_cover_every_minute_from_the_open():
    late = history(first_minute=2)
    output = snapshot(late)
    assert reasons(output, "REFERENCE_HOD_V1") == ["REFERENCE_WINDOW_NOT_COVERED"]
    assert numbers(output, "COMPRESSION_COMPLETE_V1") == [1]


def test_an_unready_or_untraded_reference_minute_keeps_the_reference_unavailable():
    def provisional(bars):
        return [replace(bar, is_final=False) if index == 1 else bar
                for index, bar in enumerate(bars)]

    output = snapshot(history(changed=provisional))
    assert reasons(output, "REFERENCE_HOD_V1") == ["REFERENCE_PROVISIONAL"]
    assert values(output)["REFERENCE_HOD_V1"].input_record_ids == (
        "compression-0-r0", "compression-1-r0", "compression-2-r0")

    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index < 3 else bar
                for index, bar in enumerate(bars)]

    output = snapshot(history(changed=quiet))
    assert reasons(output, "REFERENCE_HOD_V1") == ["NO_TRADED_REFERENCE_INTERVAL"]


def test_the_compression_window_measures_the_last_bars_its_definition_asks_for():
    output = snapshot()
    assert numbers(
        output, "COMPRESSION_HIGH_V1", "COMPRESSION_LOW_V1", "COMPRESSION_RECENT_RANGE_V1",
        "COMPRESSION_PRIOR_RANGE_V1", "COMPRESSION_BAR_COUNT_V1", "COMPRESSION_RANGE_RATIO_V1",
    ) == [101.80, 101.00, 0.13, 0.80, 7, 0.1625]
    assert numbers(output, "COMPRESSION_COMPLETE_V1", "COMPRESSION_WINDOW_AFTER_FREEZE_V1") == [1, 1]
    assert values(output)["COMPRESSION_HIGH_V1"].input_record_ids == tuple(
        f"compression-{number}-r0" for number in range(3, 10))


def test_the_two_supplied_window_definitions_measure_different_prior_ranges():
    plan = PLAN[:9] + ((101.43, 100.80),) + PLAN[10:]
    overlapping = snapshot(history(plan=plan))
    split = snapshot(history(plan=plan), policy=SPLIT)
    assert numbers(overlapping, "COMPRESSION_RECENT_RANGE_V1", "COMPRESSION_PRIOR_RANGE_V1",
                   "COMPRESSION_RANGE_RATIO_V1") == [0.65, 1.00, 0.65]
    assert numbers(split, "COMPRESSION_RECENT_RANGE_V1", "COMPRESSION_PRIOR_RANGE_V1",
                   "COMPRESSION_RANGE_RATIO_V1") == [0.65, 0.80, 0.8125]
    assert numbers(split, "COMPRESSION_BAR_COUNT_V1") == [7]


def test_a_flat_prior_window_reports_no_ratio_instead_of_dividing():
    flat = tuple((101.50, 101.50) for _ in PLAN)
    output = snapshot(history(plan=flat))
    assert numbers(output, "COMPRESSION_PRIOR_RANGE_V1") == [0.00]
    assert reasons(output, "COMPRESSION_RANGE_RATIO_V1") == ["ZERO_PRIOR_RANGE"]
    assert numbers(output, "COMPRESSION_COMPLETE_V1") == [1]


def test_a_window_that_is_short_unready_untraded_or_contradicted_is_refused():
    early = snapshot(evaluated=at("06:36:00"))
    assert reasons(early, "COMPRESSION_HIGH_V1") == ["INCOMPLETE_COMPRESSION_WINDOW"]
    assert numbers(early, "COMPRESSION_COMPLETE_V1", "COMPRESSION_WINDOW_AFTER_FREEZE_V1") == [0, None]

    def missing(bars):
        return [bar for index, bar in enumerate(bars) if index != 5]

    assert reasons(snapshot(history(changed=missing)), "COMPRESSION_HIGH_V1") == [
        "COMPRESSION_MISSING"]

    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 8 else bar
                for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=quiet)), "COMPRESSION_HIGH_V1") == [
        "NO_TRADED_COMPRESSION_INTERVAL"]

    def overlapping(bars):
        start = bars[5].start_time + timedelta(seconds=30)
        end = bars[5].end_time + timedelta(seconds=30)
        meta = replace(bars[5].metadata, source_time=start, received_time=end,
                       available_time=end, normalized_time=end)
        return [*bars, replace(bars[5], record_id="compression-overlap", metadata=meta,
                               start_time=start, end_time=end)]

    assert reasons(snapshot(history(changed=overlapping)), "COMPRESSION_HIGH_V1") == [
        "UNEXPECTED_OVERLAPPING_RECORD"]


def test_a_window_that_starts_before_the_freeze_is_reported_not_refused():
    output = snapshot(frozen=at("06:36:00"))
    assert numbers(output, "COMPRESSION_WINDOW_AFTER_FREEZE_V1") == [0]
    assert numbers(output, "COMPRESSION_COMPLETE_V1") == [1]
    assert numbers(output, "REFERENCE_HOD_V1") == [102.00]


def test_distances_are_reported_in_supplied_minute_atr_units():
    output = snapshot()
    assert numbers(output, "DISTANCE_TO_REFERENCE_HOD_ATR_V1",
                   "DISTANCE_TO_REFERENCE_LOD_ATR_V1") == [2.0, 20.0]
    assert values(output)["DISTANCE_TO_REFERENCE_HOD_ATR_V1"].unit == "RATIO"
    assert reasons(snapshot(atr_1m=None), "DISTANCE_TO_REFERENCE_HOD_ATR_V1") == ["MISSING_ATR_1M"]
    assert reasons(snapshot(atr_1m=0.0), "DISTANCE_TO_REFERENCE_LOD_ATR_V1") == ["NONPOSITIVE_ATR_1M"]
    assert reasons(snapshot(atr_1m=-0.5), "DISTANCE_TO_REFERENCE_HOD_ATR_V1") == ["NONPOSITIVE_ATR_1M"]
    with pytest.raises(RecordError, match="minute ATR"):
        snapshot(atr_1m=float("nan"))
    with pytest.raises(RecordError, match="minute ATR"):
        snapshot(atr_1m=True)


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
        assert reasons(output, "REFERENCE_HOD_V1", "COMPRESSION_HIGH_V1",
                       "COMPRESSION_RANGE_RATIO_V1",
                       "DISTANCE_TO_REFERENCE_HOD_ATR_V1") == [reason] * 4
        assert numbers(output, "REFERENCE_EXTREME_COMPLETE_V1", "COMPRESSION_COMPLETE_V1") == [0, 0]
        assert output.input_record_ids == ()


def test_daily_history_and_a_closed_day_are_refused_by_name():
    opened = as_utc(session_bounds(datetime.fromisoformat(DAY).date())[0])
    closed = as_utc(session_bounds(datetime.fromisoformat(DAY).date())[1])
    daily = HistoryBatch(HistoryRequest("SYNTH", opened, closed, "1d"), "SYNTHETIC",
                         conventions(), ())
    assert reasons(snapshot(daily), "REFERENCE_HOD_V1") == ["INCOMPATIBLE_HISTORY_INTERVAL"]
    holiday = snapshot(None, minute_history=None, day="2026-07-03",
                       evaluated=at("06:40:00", "2026-07-03"),
                       frozen=at("06:33:00", "2026-07-03"))
    assert reasons(holiday, "REFERENCE_HOD_V1", "COMPRESSION_HIGH_V1") == [
        "NO_REGULAR_SESSION"] * 2


def test_another_instrument_type_in_a_window_is_refused():
    def foreign(bars):
        return [replace(bar, metadata=replace(bar.metadata, instrument_type="ETF"))
                if index == 6 else bar for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=foreign)), "COMPRESSION_HIGH_V1") == [
        "INCOMPATIBLE_INSTRUMENT_TYPE"]


def test_the_supplied_window_definition_must_be_explicit_and_coherent():
    with pytest.raises(RecordError, match="policy version"):
        replace(OVERLAP, version=" ")
    with pytest.raises(RecordError, match="definition reference"):
        replace(OVERLAP, definition_reference="UNKNOWN")
    for name in ("recent_bars", "prior_bars"):
        with pytest.raises(RecordError, match=name):
            replace(OVERLAP, **{name: 0})
        with pytest.raises(RecordError, match=name):
            replace(OVERLAP, **{name: 3.0})
    with pytest.raises(RecordError, match="prior_includes_recent"):
        replace(OVERLAP, prior_includes_recent=1)
    with pytest.raises(RecordError, match="overlapping prior window"):
        replace(OVERLAP, prior_bars=3)
    assert OVERLAP.window_bars == 7 and SPLIT.window_bars == 7
    with pytest.raises(FrozenInstanceError):
        OVERLAP.recent_bars = 4


def test_public_scope_is_checked_before_any_measurement():
    with pytest.raises(RecordError, match="symbol is required"):
        snapshot(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        snapshot(instrument_type="OPTION")
    with pytest.raises(RecordError, match="CompressionPolicy"):
        snapshot(policy="M71")
    with pytest.raises(RecordError, match="freeze instant"):
        snapshot(frozen=1)
    with pytest.raises(ValueError):
        snapshot(evaluated=datetime.fromisoformat(DAY + "T06:40:00"))


def test_the_module_adopts_no_rule_number_of_its_own():
    source = inspect.getsource(hod_compression)
    for token in ("0.60", "0.35", "0.20", "0.05", "1.40", "0.70", "rs_15m"):
        assert token not in source
    assert sorted(FEATURE_NAMES) == sorted(item.name for item in snapshot().features)
    assert snapshot().metadata.data_mode == DATA_MODE


def test_snapshot_is_deeply_immutable_and_round_trips():
    output = snapshot()
    with pytest.raises(FrozenInstanceError):
        output.features = ()
    detached = output.as_dict()
    detached["features"][0]["value"] = 0
    assert numbers(output, "REFERENCE_HOD_V1") == [102.00]
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


def test_hod_compression_recording_end_to_end():
    supplied = history()
    detached = replace(supplied, bars=tuple(Bar.from_json(bar.to_json()) for bar in supplied.bars))
    outputs = [snapshot(detached, evaluated=at(clock)) for clock in (
        "06:39:59", "06:40:00", "06:40:01", "06:42:00"
    )]
    # The window walks forward one whole minute at a time; the reference does not.
    assert [numbers(output, "COMPRESSION_HIGH_V1", "COMPRESSION_WINDOW_AFTER_FREEZE_V1")
            for output in outputs] == [[102.00, 0], [101.80, 1], [101.80, 1], [103.00, 1]]
    assert [numbers(output, "REFERENCE_HOD_V1") for output in outputs] == [[102.00]] * 4
    frozen = outputs[1].to_json()
    outputs.append(snapshot(detached, policy=SPLIT))
    outputs.append(snapshot(detached, atr_1m=None))
    outputs.append(snapshot(detached, frozen=at("06:36:00")))
    assert outputs[1].to_json() == frozen
    assert all(FeatureSnapshot.from_json(output.to_json()) == output for output in outputs)
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY", "feature_version": FEATURE_VERSION,
        "snapshots": [proof_summary(output) for output in outputs],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m7_1_hod_compression_proof.json").write_text(rendered)
