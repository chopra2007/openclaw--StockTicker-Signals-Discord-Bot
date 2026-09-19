"""M3.4 supplied-input VWAP context through the protected launcher."""

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

from consensus_engine.core_price_features import FEATURE_VERSION as CORE_VERSION
from consensus_engine.historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from consensus_engine.trade_alerts_models import Bar, FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, session_bounds
from consensus_engine.vwap_context_features import (
    CurrentPriceObservation, DATA_MODE, FEATURE_VERSION, build_vwap_context_snapshot,
)


PACIFIC = ZoneInfo("America/Los_Angeles")
DAY = "2026-07-06"


def at(clock):
    return datetime.fromisoformat(f"{DAY}T{clock}").replace(tzinfo=PACIFIC)


def metadata(record_id, happened, *, instrument_type="EQUITY", revision=0,
             quality="VALID", data_mode="SYNTHETIC_HISTORY"):
    return SourceMetadata(
        instrument_id="SYNTH", instrument_type=instrument_type, source="SYNTHETIC",
        source_time=happened, received_time=happened + timedelta(minutes=1),
        available_time=happened + timedelta(minutes=1),
        normalized_time=happened + timedelta(minutes=1), session=DAY,
        revision=revision, data_mode=data_mode, quality=quality,
    )


def history(*, changed=None, conventions_changed=None):
    opened = as_utc(session_bounds(at("00:00:00").date())[0])
    request = HistoryRequest("SYNTH", opened, opened + timedelta(minutes=6))
    closes = (101, 99, 100, 101, 99, 101)
    bars = []
    for number, (interval, close) in enumerate(zip(request.expected_intervals(), closes)):
        bars.append(Bar(
            record_id=f"bar-{number}", metadata=metadata(f"bar-{number}", interval.start),
            start_time=interval.start, end_time=interval.end, is_final=True,
            open=100, high=max(101, close), low=min(99, close), close=close, volume=100,
            adjustment_basis="SYNTHETIC_RAW", price_convention="USD_PER_SHARE",
            volume_convention="SHARES", certified_no_trade=False,
        ))
    if changed is not None:
        bars = changed(bars)
    conventions = HistoryConventions(
        "START", "REGULAR", "SYNTHETIC_RAW", "USD_PER_SHARE", "SHARES",
        "SYNTHETIC_COMPLETE", "SYNTHETIC_FINAL", "SYNTHETIC_RECEIPT", "M34_FIXTURE",
    )
    if conventions_changed is not None:
        conventions = conventions_changed(conventions)
    return HistoryBatch(request, "SYNTHETIC", conventions, tuple(bars))


def core(clock, vwap=100.0, atr=.5, *, changed=None, version=CORE_VERSION,
         instrument_type="EQUITY", data_mode="BAR_HLC3_WITH_EXPLICIT_OPEN"):
    moment = at(clock)
    values = [
        FeatureValue("SESSION_VWAP_BAR_HLC3_V1", vwap, "USD_PER_SHARE", None,
                     (f"vwap-{clock}",)),
        FeatureValue("ATR_1M_20_SMA_V1", atr, "USD_PER_SHARE", None, ("atr-input",)),
    ]
    if changed is not None:
        values = changed(values)
    meta = SourceMetadata(
        instrument_id="SYNTH", instrument_type=instrument_type, source="DERIVED_D090",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=DAY, data_mode=data_mode,
        quality="VALID",
    )
    return FeatureSnapshot(record_id=f"core-{clock}", metadata=meta, evaluated_at=moment,
                           features=tuple(values), feature_version=version,
                           input_record_ids=tuple(sorted({item for row in values
                                                          for item in row.input_record_ids})))


def cores(*, changed=None):
    rows = [core(f"06:{minute:02d}:00", vwap=100.3 if minute == 36 else 100.0)
            for minute in range(31, 37)]
    return tuple(changed(rows) if changed else rows)


def price(value=101.0, clock="06:35:59", **changes):
    values = dict(
        record_id="price-now", symbol="SYNTH", instrument_type="EQUITY", session=DAY,
        observed_at=at(clock), available_at=at(clock), price=value, source="SYNTHETIC",
        adjustment_basis="SYNTHETIC_RAW", coverage_basis="SYNTHETIC_COMPLETE",
        price_convention="USD_PER_SHARE",
    )
    values.update(changes)
    return CurrentPriceObservation(**values)


def snapshot(**changes):
    values = dict(record_id="m34-vwap", evaluated_at=at("06:36:00"), symbol="SYNTH",
                  instrument_type="EQUITY", minute_history=history(),
                  core_snapshots=cores(), current_price=price())
    values.update(changes)
    return build_vwap_context_snapshot(**values)


def features(output):
    return {row.name: row for row in output.features}


def test_slope_distance_cross_count_and_above_side_are_calculated():
    output = snapshot()
    values = features(output)
    assert values["VWAP_SLOPE_3M_ATR_V1"].value == pytest.approx(.6)
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].value == pytest.approx(.7)
    assert values["PRICE_TO_VWAP_DISTANCE_ATR_V1"].value == pytest.approx(1.4)
    assert values["VWAP_CLOSE_CROSSES_V1"].value == 3
    assert values["PRICE_VWAP_SIDE_V1"].value == 1
    assert values["PRICE_ABOVE_VWAP_V1"].value == 1
    assert values["PRICE_BELOW_VWAP_V1"].value == 0
    assert output.feature_version == FEATURE_VERSION
    assert output.metadata.data_mode == DATA_MODE


@pytest.mark.parametrize("value,side,above,below", (
    (99.0, -1, 0, 1), (100.3, 0, 0, 0), (101.0, 1, 1, 0),
))
def test_price_side_is_strict_and_equal_is_neutral(value, side, above, below):
    values = features(snapshot(current_price=price(value)))
    assert values["PRICE_VWAP_SIDE_V1"].value == side
    assert values["PRICE_ABOVE_VWAP_V1"].value == above
    assert values["PRICE_BELOW_VWAP_V1"].value == below


def test_equal_close_breaks_cross_adjacency():
    # +, -, equal, +, -, + gives three crosses, not four.
    assert features(snapshot())["VWAP_CLOSE_CROSSES_V1"].value == 3


def test_no_trade_breaks_cross_adjacency_without_making_coverage_missing():
    def change(bars):
        row = bars[2]
        bars[2] = replace(row, open=None, high=None, low=None, close=None, volume=0,
                          certified_no_trade=True)
        return bars
    assert features(snapshot(minute_history=history(changed=change)))[
        "VWAP_CLOSE_CROSSES_V1"].value == 3


@pytest.mark.parametrize("atr,reason", ((0, "NONPOSITIVE_MINUTE_ATR"), (-1, "NONPOSITIVE_MINUTE_ATR")))
def test_nonpositive_atr_blocks_only_atr_normalized_values(atr, reason):
    changed = tuple(core(f"06:{minute:02d}:00", vwap=100.3 if minute == 36 else 100,
                         atr=atr) for minute in range(31, 37))
    values = features(snapshot(core_snapshots=changed))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == reason
    assert values["PRICE_TO_VWAP_DISTANCE_ATR_V1"].missing_reason == reason
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].value == pytest.approx(.7)
    assert values["PRICE_VWAP_SIDE_V1"].value == 1


def test_missing_exact_three_minute_snapshot_does_not_use_a_nearby_one():
    values = features(snapshot(core_snapshots=tuple(row for row in cores()
                                                    if row.evaluated_at != as_utc(at("06:33:00")))))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == "MISSING_THREE_MINUTE_CORE_SNAPSHOT"
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].value == pytest.approx(.7)


@pytest.mark.parametrize("change,reason", (
    (lambda bars: bars[:2] + bars[3:], "VWAP_CROSS_WINDOW_MISSING"),
    (lambda bars: [replace(row, is_final=False) if number == 2 else row
                   for number, row in enumerate(bars)], "VWAP_CROSS_WINDOW_PROVISIONAL"),
    (lambda bars: [replace(row, metadata=replace(row.metadata, quality="INVALID"))
                   if number == 2 else row for number, row in enumerate(bars)],
     "VWAP_CROSS_WINDOW_QUALITY_INVALID"),
))
def test_missing_provisional_or_invalid_close_keeps_cross_count_unknown(change, reason):
    row = features(snapshot(minute_history=history(changed=change)))["VWAP_CLOSE_CROSSES_V1"]
    assert row.missing_reason == reason


def test_missing_interval_vwap_keeps_cross_count_unknown():
    rows = tuple(row for row in cores() if row.evaluated_at != as_utc(at("06:34:00")))
    assert features(snapshot(core_snapshots=rows))[
        "VWAP_CLOSE_CROSSES_V1"].missing_reason == "MISSING_INTERVAL_VWAP"


@pytest.mark.parametrize("feature_name,unit,reason", (
    ("SESSION_VWAP_BAR_HLC3_V1", "CENTS", "INCOMPATIBLE_VWAP_UNIT"),
    ("ATR_1M_20_SMA_V1", "CENTS", "INCOMPATIBLE_ATR_UNIT"),
))
def test_wrong_core_units_cannot_pass(feature_name, unit, reason):
    def change(values):
        return [replace(row, unit=unit) if row.name == feature_name else row for row in values]
    rows = list(cores())
    rows[-1] = core("06:36:00", 100.3, changed=change)
    values = features(snapshot(core_snapshots=tuple(rows)))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == reason
    if feature_name.startswith("SESSION_VWAP"):
        assert values["PRICE_TO_VWAP_DISTANCE_V1"].missing_reason == reason
    else:
        assert values["PRICE_TO_VWAP_DISTANCE_ATR_V1"].missing_reason == reason


@pytest.mark.parametrize("changes,reason", (
    ({"clock": "06:35:56"}, "STALE_CURRENT_PRICE"),
    ({"clock": "06:36:01"}, "CURRENT_PRICE_NOT_YET_AVAILABLE"),
    ({"source": "OTHER"}, "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"),
    ({"coverage_basis": "OTHER"}, "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"),
    ({"adjustment_basis": "OTHER"}, "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"),
    ({"price_convention": "CENTS"}, "INCOMPATIBLE_PRICE_UNIT"),
    ({"session": "2026-07-02"}, "INCOMPATIBLE_SESSION"),
    ({"instrument_type": "ETF"}, "INCOMPATIBLE_INSTRUMENT_TYPE"),
))
def test_bad_current_price_cannot_create_distance_or_side(changes, reason):
    values = features(snapshot(current_price=price(**changes)))
    for name in ("PRICE_TO_VWAP_DISTANCE_V1", "PRICE_TO_VWAP_DISTANCE_ATR_V1",
                 "PRICE_VWAP_SIDE_V1", "PRICE_ABOVE_VWAP_V1", "PRICE_BELOW_VWAP_V1"):
        assert values[name].missing_reason == reason


@pytest.mark.parametrize("version,reason", (("OTHER", "INCOMPATIBLE_CORE_FEATURE_VERSION"),))
def test_wrong_core_version_stays_unavailable(version, reason):
    rows = list(cores())
    rows[-1] = core("06:36:00", 100.3, version=version)
    values = features(snapshot(core_snapshots=tuple(rows)))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == reason
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].missing_reason == reason


def test_wrong_core_data_mode_stays_unavailable():
    rows = list(cores())
    rows[-1] = core("06:36:00", 100.3, data_mode="OTHER")
    values = features(snapshot(core_snapshots=tuple(rows)))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == "INCOMPATIBLE_CORE_DATA_MODE"
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].missing_reason == "INCOMPATIBLE_CORE_DATA_MODE"


@pytest.mark.parametrize("conventions_changed,reason", (
    (lambda row: replace(row, price="CENTS"), "INCOMPATIBLE_HISTORY_UNITS"),
    (lambda row: replace(row, volume="ROUND_LOTS"), "INCOMPATIBLE_HISTORY_UNITS"),
    (lambda row: replace(row, session="CALENDAR_DAY"), "INCOMPATIBLE_HISTORY_WINDOW"),
    (lambda row: replace(row, adjustment_basis="OTHER"),
     "INCOMPATIBLE_SOURCE_OR_VENUE_BASIS"),
))
def test_incompatible_history_cannot_mix_with_context(conventions_changed, reason):
    values = features(snapshot(minute_history=history(conventions_changed=conventions_changed)))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == reason
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].missing_reason == reason
    assert values["VWAP_CLOSE_CROSSES_V1"].missing_reason == reason


def test_selected_wrong_instrument_type_is_rejected():
    def change(bars):
        bars[2] = replace(bars[2], metadata=replace(
            bars[2].metadata, instrument_type="ETF"))
        return bars
    values = features(snapshot(minute_history=history(changed=change)))
    assert values["VWAP_SLOPE_3M_ATR_V1"].missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    assert values["PRICE_TO_VWAP_DISTANCE_V1"].missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"
    assert values["VWAP_CLOSE_CROSSES_V1"].missing_reason == "INCOMPATIBLE_INSTRUMENT_TYPE"


def test_duplicate_core_time_is_rejected_instead_of_silently_selected():
    with pytest.raises(RecordError, match="unique evaluation times"):
        snapshot(core_snapshots=(*cores(), core("06:36:00", 100.4)))


def test_outputs_are_immutable_serializable_and_fully_attributed():
    output = snapshot()
    assert output.schema_version == 1
    assert output.evaluated_at == as_utc(at("06:36:00"))
    assert output.input_record_ids == tuple(sorted({record_id for row in output.features
                                                    for record_id in row.input_record_ids}))
    assert FeatureSnapshot.from_json(output.to_json()).to_json() == output.to_json()
    with pytest.raises(FrozenInstanceError):
        output.features = ()
    with pytest.raises(RecordError, match="instrument type"):
        snapshot(instrument_type="OPTION")
    with pytest.raises(RecordError, match="tuple of FeatureSnapshot"):
        snapshot(core_snapshots=list(cores()))


def test_vwap_context_recording_end_to_end():
    outputs = [snapshot(), snapshot(current_price=price(99)),
               snapshot(core_snapshots=tuple(row for row in cores()
                                             if row.evaluated_at != as_utc(at("06:33:00"))))]
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "feature_version": FEATURE_VERSION, "snapshots": []}
    for output in outputs:
        restored = FeatureSnapshot.from_json(output.to_json())
        raw = restored.to_json().encode()
        payload["snapshots"].append({
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "features": [{"name": row.name, "value": row.value,
                          "missing_reason": row.missing_reason,
                          "input_count": len(row.input_record_ids)} for row in output.features],
        })
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    Path("/tmp/m34-vwap-context-proof.json").write_text(rendered)
