"""M3.5 supplied-input structural geometry through the protected launcher."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.structural_geometry import (
    FEATURE_VERSION, GeometryPrice, StructuralGeometryInputs,
    build_structural_geometry_snapshot,
)
from consensus_engine.trade_alerts_models import FeatureSnapshot, RecordError
from test_core_price_features import bar


PACIFIC = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 7, 6, 6, 40, tzinfo=PACIFIC)


def price(record_id, value, second=0, **changes):
    fields = dict(
        record_id=record_id, symbol="SYNTH", instrument_type="EQUITY",
        session="2026-07-06", observed_at=NOW - timedelta(seconds=60-second),
        available_at=NOW - timedelta(seconds=60-second), source="SYNTHETIC",
        adjustment_basis="SYNTHETIC_RAW", coverage_basis="SYNTHETIC_COMPLETE",
        value=value, missing_reason="MISSING_INPUT" if value is None else None,
    )
    fields.update(changes)
    return GeometryPrice(**fields)


def swing_bars(*, lows=(100, 99, 95, 95, 96, 97), highs=(101, 102, 105, 105, 104, 103)):
    start = NOW - timedelta(minutes=len(lows))
    return tuple(bar(f"swing-{n}", start + timedelta(minutes=n),
                     start + timedelta(minutes=n + 1), high=high, low=low,
                     close=(high + low) / 2, volume=100)
                 for n, (low, high) in enumerate(zip(lows, highs)))


def supplied(direction="LONG", **changes):
    short = direction == "SHORT"
    mirror = (lambda value: 200 - value) if short else (lambda value: value)
    recent_high, recent_low = ((99.3, 99.0) if short else (101.0, 100.7))
    prior_high, prior_low = ((99.3, 98.8) if short else (101.2, 100.7))
    fields = dict(
        direction=direction,
        impulse_start=price("impulse-start", mirror(100)),
        impulse_extreme=price("impulse-extreme", mirror(101), 1),
        adverse_extreme=price("adverse-extreme", mirror(100.65), 2),
        recent_high=price("recent-high", recent_high, 3),
        recent_low=price("recent-low", recent_low, 4),
        prior_high=price("prior-high", prior_high, 5),
        prior_low=price("prior-low", prior_low, 6),
        drive_path=tuple(price(f"path-{n}", mirror(value), 10 + n)
                         for n, value in enumerate((100, 100.2, 100.1, 100.3))),
        current_price=price("current", mirror(100.7), 20),
        structural_level=price("level", mirror(101), 21),
        entry=price("entry", mirror(100), 22),
        stop=price("stop", mirror(99), 23),
        target=price("target", mirror(101.5), 24),
        atr=price("atr", .5, 25), buffer_floor=.01, buffer_atr_multiple=.03,
        swing_bars=swing_bars(),
    )
    fields.update(changes)
    return StructuralGeometryInputs(**fields)


def snapshot(direction="LONG", **changes):
    return build_structural_geometry_snapshot(
        record_id="geometry-" + direction.lower(), evaluated_at=NOW, symbol="SYNTH",
        instrument_type="EQUITY", inputs=supplied(direction, **changes))


def features(result):
    return {feature.name: feature for feature in result.features}


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_all_shared_geometry_is_exactly_mirrored(direction):
    values = features(snapshot(direction))
    assert values["RETRACEMENT_RATIO_V1"].value == pytest.approx(.35)
    assert values["COMPRESSION_RANGE_RATIO_V1"].value == pytest.approx(.6)
    assert values["DRIVE_EFFICIENCY_V1"].value == pytest.approx(.6)
    assert values["DIRECTIONAL_DISTANCE_TO_LEVEL_V1"].value == pytest.approx(.3)
    assert values["DIRECTIONAL_DISTANCE_TO_LEVEL_ATR_V1"].value == pytest.approx(.6)
    assert values["RISK_REWARD_RATIO_V1"].value == pytest.approx(1.5)
    assert values["ATR_BUFFER_V1"].value == pytest.approx(.015)
    assert values["SWING_HIGH_PLATEAU_2X2_V1"].value == 105
    assert values["SWING_LOW_PLATEAU_2X2_V1"].value == 95


def test_negative_retracement_is_recorded_as_zero_and_values_above_one_are_retained():
    assert features(snapshot(adverse_extreme=price("adverse", 101.1)))[
        "RETRACEMENT_RATIO_V1"].value == 0
    assert features(snapshot(adverse_extreme=price("adverse", 99.5)))[
        "RETRACEMENT_RATIO_V1"].value == 1.5


@pytest.mark.parametrize("prior_high,prior_low,reason", (
    (100, 100, "ZERO_PRIOR_RANGE"), (99, 100, "INVALID_RANGE_GEOMETRY"),
))
def test_compression_rejects_an_undefined_prior_range(prior_high, prior_low, reason):
    row = features(snapshot(prior_high=price("ph", prior_high),
                            prior_low=price("pl", prior_low)))["COMPRESSION_RANGE_RATIO_V1"]
    assert row.value is None and row.missing_reason == reason


def test_flat_or_nonchronological_drive_path_is_unavailable():
    flat = tuple(price(f"flat-{n}", 100, n) for n in range(3))
    assert features(snapshot(drive_path=flat))[
        "DRIVE_EFFICIENCY_V1"].missing_reason == "ZERO_PATH_DISTANCE"
    reversed_path = tuple(reversed(supplied().drive_path))
    assert features(snapshot(drive_path=reversed_path))[
        "DRIVE_EFFICIENCY_V1"].missing_reason == "NONCHRONOLOGICAL_PATH"


def test_level_distance_is_signed_and_does_not_turn_a_level_behind_price_favorable():
    values = features(snapshot(structural_level=price("behind", 100.6)))
    assert values["DIRECTIONAL_DISTANCE_TO_LEVEL_V1"].value == pytest.approx(-.1)
    assert values["DIRECTIONAL_DISTANCE_TO_LEVEL_ATR_V1"].value == pytest.approx(-.2)


@pytest.mark.parametrize("field,reason", (
    ("stop", "NONPOSITIVE_RISK"), ("target", "NEGATIVE_REWARD"),
))
def test_bad_risk_geometry_never_yields_a_favorable_ratio(field, reason):
    changed = price(field, 101 if field == "stop" else 99)
    row = features(snapshot(**{field: changed}))["RISK_REWARD_RATIO_V1"]
    assert row.value is None and row.missing_reason == reason


def test_zero_reward_is_a_real_zero_r_multiple():
    row = features(snapshot(target=price("target", 100)))["RISK_REWARD_RATIO_V1"]
    assert row.value == 0 and row.missing_reason is None


def test_buffer_uses_the_larger_floor_or_atr_multiple_without_rounding():
    assert features(snapshot(buffer_floor=.02))["ATR_BUFFER_V1"].value == .02
    assert features(snapshot(buffer_floor=.01, buffer_atr_multiple=.04))[
        "ATR_BUFFER_V1"].value == .02


def test_plateau_extends_across_equal_extremes_and_needs_two_strict_neighbors_each_side():
    rows = swing_bars(highs=(101, 102, 105, 105, 105, 104, 103),
                      lows=(100, 99, 98, 97, 98, 99, 100))
    high = features(snapshot(swing_bars=rows))["SWING_HIGH_PLATEAU_2X2_V1"]
    assert high.value == 105
    assert high.input_record_ids == tuple(f"swing-{n}" for n in range(7))
    touching_edge = swing_bars(highs=(105, 105, 104, 103, 102, 101))
    assert features(snapshot(swing_bars=touching_edge))[
        "SWING_HIGH_PLATEAU_2X2_V1"].missing_reason == "KNOWN_EMPTY"


def test_no_trade_or_gap_cannot_be_skipped_to_make_a_swing():
    rows = list(swing_bars())
    rows[1] = bar("no-trade", rows[1].start_time, rows[1].end_time,
                  high=1, low=1, close=1, no_trade=True)
    assert features(snapshot(swing_bars=tuple(rows)))[
        "SWING_HIGH_PLATEAU_2X2_V1"].missing_reason == "INCOMPLETE_SWING_WINDOW"
    rows = list(swing_bars())
    rows[2] = replace(rows[2], start_time=rows[2].start_time + timedelta(seconds=1))
    assert features(snapshot(swing_bars=tuple(rows)))[
        "SWING_HIGH_PLATEAU_2X2_V1"].missing_reason == "NONCONTIGUOUS_SWING_WINDOW"


@pytest.mark.parametrize("change,reason", (
    ({"available_at": NOW + timedelta(seconds=1)}, "NOT_YET_AVAILABLE"),
    ({"session": "2026-07-07"}, "INCOMPATIBLE_SESSION"),
    ({"symbol": "OTHER"}, "INCOMPATIBLE_SYMBOL"),
    ({"price_convention": "CENTS"}, "INCOMPATIBLE_PRICE_UNIT"),
))
def test_point_in_time_and_identity_errors_stay_unavailable(change, reason):
    row = replace(supplied().current_price, **change)
    distance = features(snapshot(current_price=row))["DIRECTIONAL_DISTANCE_TO_LEVEL_V1"]
    assert distance.value is None and distance.missing_reason == reason


def test_source_or_adjustment_mismatch_cannot_be_combined():
    level = replace(supplied().structural_level, adjustment_basis="OTHER")
    row = features(snapshot(structural_level=level))["DIRECTIONAL_DISTANCE_TO_LEVEL_V1"]
    assert row.missing_reason == "INCOMPATIBLE_SOURCE_OR_PRICE_BASIS"


def test_missing_one_input_only_hides_its_dependent_geometry():
    values = features(snapshot(structural_level=None))
    assert values["DIRECTIONAL_DISTANCE_TO_LEVEL_V1"].missing_reason == "MISSING_INPUT"
    assert values["DRIVE_EFFICIENCY_V1"].value == pytest.approx(.6)
    assert values["RISK_REWARD_RATIO_V1"].value == 1.5


def test_records_are_immutable_and_round_trip_without_losing_attribution():
    result = snapshot()
    with pytest.raises(FrozenInstanceError):
        result.features = ()
    restored = FeatureSnapshot.from_json(result.to_json())
    assert restored == result
    assert set(restored.input_record_ids) == {
        item for feature in restored.features for item in feature.input_record_ids
    }
    assert restored.feature_version == FEATURE_VERSION


def test_structural_geometry_recording_end_to_end():
    payload = {direction: json.loads(snapshot(direction).to_json())
               for direction in ("LONG", "SHORT")}
    # The protected launcher maps /tmp to this fresh process's published run folder.
    # Cross-process repeatability is checked from the two published files.
    target = Path("/tmp/m35-structural-geometry-proof.json")
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    target.write_bytes(encoded)
    assert target.read_bytes() == encoded


@pytest.mark.parametrize("bad", ("SIDEWAYS", "", None))
def test_invalid_direction_is_rejected(bad):
    with pytest.raises(RecordError, match="direction"):
        supplied(direction=bad)
