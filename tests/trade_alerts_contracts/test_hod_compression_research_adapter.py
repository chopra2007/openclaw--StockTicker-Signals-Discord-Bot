"""M9.1F: `HOD_COMP_RS` reference/compression from real, `PROVISIONAL`-usable bars.

Every bar below is a synthetic fixture. Passing a case proves only the offline
contract described in `hod_compression_research_adapter.py`: it establishes no
provider coverage, no adopted `HOD_COMP_RS` rule and no permission to act.
"""

from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.hod_compression import CompressionPolicy
from consensus_engine.hod_compression_research_adapter import (
    RESEARCH_HOD_COMPRESSION_DATA_MODE,
    RESEARCH_HOD_COMPRESSION_FEATURE_VERSION,
    build_hod_compression_snapshot_from_research,
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
    version="M91F_TEST_WINDOW_V1", definition_reference="M91F_SYNTHETIC_WINDOW_ONLY",
    recent_bars=3, prior_bars=7, prior_includes_recent=True,
)


def at(clock, day=DAY):
    return datetime.fromisoformat(day + "T" + clock).replace(tzinfo=PACIFIC)


def conventions(**changes):
    values = dict(
        timestamp="START", session="REGULAR", adjustment_basis="SYNTHETIC_RAW",
        price="USD_PER_SHARE", volume="SHARES", coverage_basis="SYNTHETIC_COMPLETE",
        finality="SYNTHETIC_FINAL", publication="SYNTHETIC_RECEIPT",
        evidence_reference="M91F_SYNTHETIC_ONLY",
    )
    values.update(changes)
    return HistoryConventions(**values)


def make_bar(number, interval, prices, *, no_trade=False, revision=0,
             is_final=True, instrument_type="EQUITY", symbol="SYNTH"):
    high, low = prices
    middle = round((high + low) / 2, 2)
    meta = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="SYNTHETIC",
        source_time=interval.start, received_time=interval.end,
        available_time=interval.end, normalized_time=interval.end,
        session=interval.session, revision=revision, data_mode="SYNTHETIC_HISTORY",
        quality="VALID",
    )
    return Bar(
        record_id=f"m91f-compression-{number}-r{revision}", metadata=meta,
        start_time=interval.start, end_time=interval.end, is_final=is_final,
        open=None if no_trade else middle, high=None if no_trade else high,
        low=None if no_trade else low, close=None if no_trade else middle,
        volume=0 if no_trade else 1000 + number,
        adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
        volume_convention="SHARES", certified_no_trade=no_trade,
    )


def history(day=DAY, *, plan=PLAN, first_minute=0, changed=None, is_final=True,
            supplied_conventions=None, **request_changes):
    opened = as_utc(session_bounds(datetime.fromisoformat(day).date())[0])
    values = dict(
        symbol="SYNTH", start=opened + timedelta(minutes=first_minute),
        end=opened + timedelta(minutes=len(plan)),
    )
    values.update(request_changes)
    request = HistoryRequest(**values)
    bars = [make_bar(first_minute + number, interval, plan[first_minute + number],
                     symbol=request.symbol, is_final=is_final)
            for number, interval in enumerate(request.expected_intervals())]
    if changed:
        bars = changed(bars)
    return HistoryBatch(request, "SYNTHETIC", supplied_conventions or conventions(), tuple(bars))


def snapshot(supplied=None, *, evaluated=None, frozen=None, policy=OVERLAP, atr_1m=0.10,
             day=DAY, **changes):
    if supplied is None and "minute_history" not in changes:
        supplied = history(day)
    values = dict(
        record_id="m91f-hod-compression", evaluated_at=evaluated or at("06:40:00", day),
        symbol="SYNTH", instrument_type="EQUITY", minute_history=supplied,
        policy=policy, reference_frozen_at=frozen or at("06:33:00", day), atr_1m=atr_1m,
    )
    values.update(changes)
    return build_hod_compression_snapshot_from_research(**values)


def measured(output):
    return {item.name: item for item in output.snapshot.features}


def numbers(output, *names):
    return [measured(output)[name].value for name in names]


def reasons(output, *names):
    return [measured(output)[name].missing_reason for name in names]


def test_provisional_bars_are_usable_here_unlike_the_live_function():
    output = snapshot(history(changed=lambda bars: [replace(bar, is_final=False)
                                                    for bar in bars]))
    assert numbers(output, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1",
                   "REFERENCE_EXTREME_COMPLETE_V1") == [102.00, 99.00, 1]
    assert numbers(output, "COMPRESSION_HIGH_V1", "COMPRESSION_COMPLETE_V1") == [101.80, 1]
    assert output.snapshot.feature_version == RESEARCH_HOD_COMPRESSION_FEATURE_VERSION
    assert output.snapshot.metadata.data_mode == RESEARCH_HOD_COMPRESSION_DATA_MODE


def test_the_label_names_d110_and_the_provisional_count():
    output = snapshot(history(changed=lambda bars: [replace(bar, is_final=False)
                                                    for bar in bars]))
    assert output.label["decision"] == "D-110"
    assert output.label["finality"] == "RESEARCH_PROVISIONAL_PERMITTED"
    assert output.label["provisional_intervals"] == 10
    assert output.label["final_intervals"] == 0


def test_already_final_bars_measure_the_same_result_as_provisional_ones():
    finalized = snapshot()
    provisional = snapshot(history(changed=lambda bars: [replace(bar, is_final=False)
                                                         for bar in bars]))
    assert numbers(finalized, "REFERENCE_HOD_V1", "COMPRESSION_HIGH_V1") == numbers(
        provisional, "REFERENCE_HOD_V1", "COMPRESSION_HIGH_V1")
    assert finalized.label["final_intervals"] == 10
    assert finalized.label["provisional_intervals"] == 0


def test_reference_extreme_is_still_frozen_and_never_reads_a_later_bar():
    output = snapshot()
    assert numbers(output, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1") == [102.00, 99.00]
    later = snapshot(evaluated=at("06:42:00"))
    assert numbers(later, "REFERENCE_HOD_V1", "REFERENCE_LOD_V1") == [102.00, 99.00]
    assert max(high for high, _ in PLAN) == 103.00


def test_an_unready_or_untraded_reference_minute_keeps_the_reference_unavailable():
    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index < 3 else bar
                for index, bar in enumerate(bars)]

    output = snapshot(history(changed=quiet))
    assert reasons(output, "REFERENCE_HOD_V1") == ["NO_TRADED_REFERENCE_INTERVAL"]


def test_a_window_that_is_short_unready_untraded_or_contradicted_is_refused():
    early = snapshot(evaluated=at("06:36:00"))
    assert reasons(early, "COMPRESSION_HIGH_V1") == ["INCOMPLETE_COMPRESSION_WINDOW"]
    assert numbers(early, "COMPRESSION_COMPLETE_V1") == [0]

    def missing_bar(bars):
        return [bar for index, bar in enumerate(bars) if index != 5]

    assert reasons(snapshot(history(changed=missing_bar)), "COMPRESSION_HIGH_V1") == [
        "COMPRESSION_MISSING"]

    def quiet(bars):
        return [replace(bar, open=None, high=None, low=None, close=None, volume=0,
                        certified_no_trade=True) if index == 8 else bar
                for index, bar in enumerate(bars)]

    assert reasons(snapshot(history(changed=quiet)), "COMPRESSION_HIGH_V1") == [
        "NO_TRADED_COMPRESSION_INTERVAL"]


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
        assert reasons(output, "REFERENCE_HOD_V1", "COMPRESSION_HIGH_V1") == [reason] * 2
        assert numbers(output, "REFERENCE_EXTREME_COMPLETE_V1",
                       "COMPRESSION_COMPLETE_V1") == [0, 0]
        assert output.snapshot.input_record_ids == ()
        assert output.label is None


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
    assert holiday.label is None


def test_public_scope_is_checked_before_any_measurement():
    with pytest.raises(RecordError, match="symbol is required"):
        snapshot(symbol="")
    with pytest.raises(RecordError, match="instrument type"):
        snapshot(instrument_type="OPTION")
    with pytest.raises(RecordError, match="CompressionPolicy"):
        snapshot(policy="M91F")
    with pytest.raises(RecordError, match="freeze instant"):
        snapshot(frozen=1)


def proof_summary(output):
    raw = output.snapshot.to_json().encode()
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "evaluated_at_pacific": output.snapshot.evaluated_at.astimezone(PACIFIC).isoformat(),
        "label": output.label,
        "features": [
            {"name": item.name, "value": item.value, "missing_reason": item.missing_reason,
             "input_count": len(item.input_record_ids)} for item in output.snapshot.features
        ],
    }


def test_hod_compression_research_recording_end_to_end():
    supplied = history(changed=lambda bars: [replace(bar, is_final=False) for bar in bars])
    detached = replace(supplied, bars=tuple(Bar.from_json(bar.to_json()) for bar in supplied.bars))
    outputs = [snapshot(detached, evaluated=at(clock)) for clock in (
        "06:39:59", "06:40:00", "06:40:01", "06:42:00"
    )]
    assert [numbers(output, "COMPRESSION_HIGH_V1") for output in outputs] == [
        [102.00], [101.80], [101.80], [103.00]]
    assert [numbers(output, "REFERENCE_HOD_V1") for output in outputs] == [[102.00]] * 4
    assert all(output.label["provisional_intervals"] > 0 for output in outputs)
    frozen = outputs[1].snapshot.to_json()
    assert outputs[1].snapshot.to_json() == frozen
    assert all(FeatureSnapshot.from_json(output.snapshot.to_json()) == output.snapshot
               for output in outputs)
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
        "feature_version": RESEARCH_HOD_COMPRESSION_FEATURE_VERSION,
        "snapshots": [proof_summary(output) for output in outputs],
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m91f_hod_compression_research_proof.json").write_text(rendered)
