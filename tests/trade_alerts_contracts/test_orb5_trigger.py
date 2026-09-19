"""M6.2 supplied-input actionable-trigger contracts; no approved rule is adopted.

Every number below is a synthetic fixture supplied by the caller. A passing gate
proves the offline contract only: it establishes no tape or quote coverage, no
adopted `M03B_ORB5_V1` rule, no alert and no permission to act. ALERT_TRIGGERED
here means the supplied gates passed at one instant in a test process.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.orb5_eligibility import (
    EligibilityRequest, evaluate_orb5_eligibility,
)
from consensus_engine.orb5_trigger import (
    ATTEMPT_GATE, CROSSED, DATA_MODE, FrozenCandidate, GATE_NAMES, INVALIDATIONS, MODES,
    MODE_VARIANTS, MinuteClose, NOT_CROSSED, Observation, Orb5TriggerMachine, ProjectedVolume,
    QUOTA_GATE, QUOTE_PROJECTED, RULES_VERSION, STRATEGY_ID, TAPE, TRIGGER_GATES,
    TRIGGER_VERSION, TapeIntensity, TriggerGate, TriggerPolicy, TriggerRequest,
    candidate_boundary, evaluate_crossing, evaluate_orb5_trigger, freeze_candidate,
    trigger_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.structural_risk import select_b_risk_targets
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_orb5_eligibility import (
    DAY, PACIFIC, context as eligibility_context, decision, policy as eligibility_policy,
    snapshots, status,
)
from test_strategy_interface import session
from test_structural_risk import changed_value, request as risk_request


CROSS = datetime(2026, 7, 6, 6, 50, tzinfo=PACIFIC)
TRIGGER = CROSS + timedelta(seconds=10)
VERSION = "M62_FIXTURE_ONLY_V1"
POLICY_VERSION = "M62_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M62_SUPPLIED_FIXTURE_DEFINITION"
# D-090 FX-08 and FX-09: the two mirrored opening ranges and their buffered
# boundaries. Both are synthetic fixtures, not adopted thresholds.
RANGE = {"LONG": (101.0, 100.0), "SHORT": (51.0, 50.0)}
BOUNDARY = {"LONG": 101.02, "SHORT": 49.98}
# Inside the boundary, exactly at it, and beyond it.
PRICES = {"LONG": (101.01, 101.02, 101.03), "SHORT": (49.99, 49.98, 49.97)}
# FX-10: seven of ten samples lie at or beyond the frozen boundary.
FX10 = (101.01, 101.02, 101.03, 101.01, 101.02, 101.01, 101.02, 101.03, 101.02, 101.03)


def flip(value, direction):
    """Mirror a long fixture price into its short twin around the FX-08/FX-09 pair."""
    if value is None or direction == "LONG":
        return value
    return float(Decimal(151) - Decimal(str(value)))


def moved(row, at):
    """The same supplied price input, observed and available at another instant."""
    snapshot = row.snapshot
    metadata = replace(snapshot.metadata, source_time=at, received_time=at,
                       available_time=at, normalized_time=at)
    return replace(row, snapshot=replace(snapshot, metadata=metadata, evaluated_at=at))


def geometry(direction="LONG", *, mode=TAPE, crossed_at=CROSS, at=TRIGGER, outcome="READY"):
    """One supplied M4.3 result recomputed for this crossing and this instant."""
    supplied = risk_request(direction, variant=MODE_VARIANTS[mode])
    catalog = supplied.catalog
    supplied = replace(
        supplied, crossed_at=crossed_at, evaluated_at=at,
        anchor=moved(supplied.anchor, at), entry=moved(supplied.entry, at),
        frozen_atr=moved(supplied.frozen_atr, crossed_at),
        price_increment=moved(supplied.price_increment, crossed_at),
        boundary=moved(supplied.boundary, crossed_at),
        catalog=replace(
            catalog,
            metadata=replace(catalog.metadata, source_time=at, received_time=at,
                             available_time=at, normalized_time=at),
            coverage=tuple(replace(row, available_at=at, covered_through=at)
                           for row in catalog.coverage),
            levels=tuple(replace(row, price=moved(row.price, at)) for row in catalog.levels)))
    if outcome == "UNAVAILABLE":
        supplied = replace(supplied, path_complete=False)
    if outcome == "REJECTED":
        # The entry sits inside the frozen boundary, which the selector rejects
        # without moving the boundary this trigger is checked against.
        supplied = replace(supplied, entry=changed_value(
            supplied.entry, PRICES[direction][0]))
    result = select_b_risk_targets(supplied)
    assert result.status == outcome
    return result


def eligibility(direction="LONG", *, at=TRIGGER, geometry_result=None, **changes):
    """The supplied M6.1 context and assessment for one instant."""
    supplied = eligibility_context(direction, evaluated_at=at, features=snapshots(direction, at=at),
                                   quote=decision(direction, at=at))
    values = dict(context=supplied, policy=eligibility_policy(), status=status(available_at=at),
                  preliminary=geometry_result if geometry_result is not None
                  else geometry(direction, at=at))
    values.update(changes)
    request = EligibilityRequest(**values)
    return request.context, evaluate_orb5_eligibility(request)


def trigger_policy(mode=TAPE, **changes):
    values = dict(
        version=POLICY_VERSION, definition_reference=DEFINITION, mode=mode,
        buffer_floor=0.01, buffer_atr_multiple=0.05, window_open_seconds=10,
        window_close_seconds=30, sample_count=10, min_accepting_samples=7,
        sample_interval_seconds=1, max_observation_age_seconds=3.0,
        min_participation_ratio=1.50, min_projection_elapsed_seconds=10,
        max_attempts_per_direction=2, action_cooldown_seconds=600.0,
    )
    values.update(changes)
    return TriggerPolicy(**values)


def candidate(direction="LONG", *, mode=TAPE, crossed_at=CROSS, attempt_number=1, **changes):
    high, low = RANGE.get(direction, RANGE["LONG"])
    values = dict(crossed_at=crossed_at, direction=direction, mode=mode,
                  attempt_number=attempt_number, opening_range_high=high,
                  opening_range_low=low, frozen_atr=0.4, buffer=0.02,
                  boundary=BOUNDARY.get(direction, BOUNDARY["LONG"]),
                  anchor_bar_id="m62-anchor-minute",
                  input_record_ids=("m62-crossing-previous", "m62-crossing-current"))
    values.update(changes)
    return FrozenCandidate(**values)


def observation(record_id, at, price, *, mode=TAPE, age=1.0, available_at=None,
                coverage_known=True, missing_reason=None):
    return Observation(record_id=record_id, mode=mode, observed_at=at,
                       available_at=at if available_at is None else available_at, price=price,
                       age_seconds=age, coverage_known=coverage_known,
                       missing_reason=missing_reason)


def grid(direction="LONG", *, mode=TAPE, at=TRIGGER, count=10, prices=None,
         prefix="m62-sample", **changes):
    """`count` supplied observations on the one-second grid ending at `at`."""
    values = ([PRICES[direction][2]] * count if prices is None
              else [flip(value, direction) for value in prices])
    return tuple(observation("%s-%d" % (prefix, number),
                             at - timedelta(seconds=count - 1 - number), values[number],
                             mode=mode, **changes)
                 for number in range(count))


def intensity(**changes):
    values = dict(definition_reference="M62_SUPPLIED_INTENSITY_V1", ratio=1.50,
                  coverage_complete=True)
    values.update(changes)
    return TapeIntensity(**values)


def projection(*, at=TRIGGER, elapsed=10.0, volume=5000.0, reference=20000.0, **changes):
    values = dict(definition_reference="M62_SUPPLIED_PROJECTION_V1",
                  minute_start=at - timedelta(seconds=elapsed), elapsed_seconds=elapsed,
                  minute_volume=volume, reference_mean=reference, coverage_complete=True)
    values.update(changes)
    return ProjectedVolume(**values)


def request(direction="LONG", *, mode=TAPE, at=TRIGGER, crossed_at=CROSS, **changes):
    supplied = geometry(direction, mode=mode, crossed_at=crossed_at, at=at)
    values = dict(
        candidate=candidate(direction, mode=mode, crossed_at=crossed_at),
        policy=trigger_policy(mode), evaluated_at=at,
        observations=grid(direction, mode=mode, at=at),
        participation=intensity() if mode == TAPE else projection(at=at),
        last_trade=observation("m62-last-trade", at, PRICES[direction][2], mode=mode),
        eligibility=eligibility(direction, at=at, geometry_result=supplied)[1],
        geometry=supplied, minute_close=None,
    )
    values.update(changes)
    return TriggerRequest(**values)


def owner(direction="LONG", *, mode=TAPE, **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION, policy=trigger_policy(mode))
    values.update(changes)
    return Orb5TriggerMachine(**values)


def minute_close(*, at=TRIGGER, close=100.5, final=True, coverage_known=True, **changes):
    values = dict(record_id="m62-minute-close", bar_end=at, available_at=at, close=close,
                  final=final, coverage_known=coverage_known)
    values.update(changes)
    return MinuteClose(**values)


# --- supplied policy and record contracts -----------------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"mode": "BOTH"}, {"mode": "tape"}, {"buffer_floor": -0.01},
    {"buffer_atr_multiple": float("nan")}, {"buffer_atr_multiple": float("inf")},
    {"buffer_atr_multiple": "0.05"}, {"buffer_atr_multiple": True},
    {"window_open_seconds": 10.0}, {"window_open_seconds": -1}, {"window_close_seconds": 9},
    {"sample_count": 0}, {"min_accepting_samples": 11}, {"min_accepting_samples": 0},
    {"sample_interval_seconds": 0}, {"sample_interval_seconds": 2},
    {"max_attempts_per_direction": 0}, {"max_observation_age_seconds": -3.0},
    {"min_participation_ratio": float("nan")}, {"action_cooldown_seconds": -1.0},
))
def test_policy_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        trigger_policy(**changes)


def test_policy_keeps_the_first_window_after_the_crossing():
    assert trigger_policy(sample_count=10, sample_interval_seconds=1).sample_count == 10
    with pytest.raises(RecordError):
        trigger_policy(sample_count=11, window_open_seconds=10)


@pytest.mark.parametrize("mode", MODES)
def test_each_arm_keeps_its_own_d090_variant(mode):
    assert trigger_policy(mode).variant == MODE_VARIANTS[mode]
    assert len(set(MODE_VARIANTS.values())) == len(MODES)


@pytest.mark.parametrize("changes", (
    {"record_id": " "}, {"record_id": "UNKNOWN"}, {"mode": "OTHER"}, {"price": 0.0},
    {"price": -1.0}, {"price": None}, {"price": None, "missing_reason": " "},
    {"age_seconds": -1.0}, {"coverage_known": 1},
    {"observed_at": "2026-07-06T06:50:10"},
    {"available_at": datetime(2026, 7, 6, 6, 50, 10)},
))
def test_observation_requires_supported_supplied_facts(changes):
    values = dict(record_id="m62-observation", mode=TAPE, observed_at=TRIGGER,
                  available_at=TRIGGER, price=101.03, age_seconds=1.0, coverage_known=True,
                  missing_reason=None)
    values.update(changes)
    with pytest.raises(RecordError):
        Observation(**values)


def test_a_null_observation_price_stays_an_explicit_unknown():
    row = observation("m62-observation", TRIGGER, None, missing_reason="NO_ELIGIBLE_TRADE")
    assert row.price is None and row.missing_reason == "NO_ELIGIBLE_TRADE"
    assert row.as_dict()["price"] is None


@pytest.mark.parametrize("changes", (
    {"definition_reference": "UNKNOWN"}, {"ratio": -1.0}, {"coverage_complete": None},
    {"ratio": None}, {"ratio": None, "missing_reason": ""},
))
def test_supplied_tape_intensity_requires_explicit_facts(changes):
    with pytest.raises(RecordError):
        intensity(**changes)


@pytest.mark.parametrize("changes", (
    {"definition_reference": " "}, {"elapsed_seconds": None}, {"minute_volume": None},
    {"reference_mean": None}, {"minute_volume": -1.0}, {"coverage_complete": "yes"},
    {"minute_start": datetime(2026, 7, 6, 6, 50)},
))
def test_supplied_projection_requires_explicit_facts(changes):
    with pytest.raises(RecordError):
        projection(**changes)


@pytest.mark.parametrize("changes", (
    {"record_id": ""}, {"close": None}, {"close": 0.0}, {"final": 1},
    {"coverage_known": None}, {"bar_end": "2026-07-06T06:50:10"},
))
def test_minute_close_requires_supported_supplied_facts(changes):
    with pytest.raises(RecordError):
        minute_close(**changes)


def test_a_pending_minute_close_may_omit_its_price():
    row = minute_close(close=None, final=False)
    assert row.close is None and row.final is False


@pytest.mark.parametrize("changes", (
    {"direction": "FLAT"}, {"mode": "OTHER"}, {"attempt_number": 0},
    {"anchor_bar_id": "UNKNOWN"}, {"opening_range_low": 101.0}, {"opening_range_high": 0.0},
    {"buffer": 0.0}, {"boundary": 101.03}, {"boundary": 101.0}, {"frozen_atr": -0.4},
    {"input_record_ids": ["a"]}, {"input_record_ids": (" ",)},
    {"crossed_at": datetime(2026, 7, 6, 6, 50)},
))
def test_frozen_candidate_requires_a_consistent_buffered_boundary(changes):
    with pytest.raises(RecordError):
        candidate(**changes)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_frozen_candidate_keeps_the_supplied_edge(direction):
    row = candidate(direction)
    assert row.boundary == BOUNDARY[direction] and row.buffer == 0.02
    assert row.as_dict()["anchor_bar_id"] == "m62-anchor-minute"
    with pytest.raises(FrozenInstanceError):
        row.__setattr__("boundary", 1.0)


@pytest.mark.parametrize("changes", (
    {"candidate": None}, {"policy": None}, {"observations": []},
    {"observations": ("m62-sample-0",)}, {"participation": "TAPE"},
    {"last_trade": 101.03}, {"eligibility": "ARMED"}, {"geometry": "READY"},
    {"minute_close": 100.5},
))
def test_request_requires_canonical_supplied_parts(changes):
    with pytest.raises(RecordError):
        request(**changes)


def test_request_refuses_a_foreign_arm_or_a_backward_instant():
    with pytest.raises(RecordError):
        request(policy=trigger_policy(QUOTE_PROJECTED))
    with pytest.raises(RecordError):
        request(evaluated_at=CROSS - timedelta(seconds=1))
    duplicate = grid() + (observation("m62-sample-0", TRIGGER, 101.03),)
    with pytest.raises(RecordError):
        request(observations=duplicate)


# --- the pre-crossing buffer, boundary and crossing test ---------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_fx08_fx09_buffer_and_boundary(direction):
    high, low = RANGE[direction]
    buffer, boundary = candidate_boundary(trigger_policy(), direction, opening_range_high=high,
                                          opening_range_low=low, latest_atr=0.4)
    assert (buffer, boundary) == (0.02, BOUNDARY[direction])


def test_fx02_and_fx07_use_the_supplied_floor_and_multiple():
    buffer, boundary = candidate_boundary(trigger_policy(), "LONG", opening_range_high=100.8030,
                                          opening_range_low=100.0, latest_atr=0.21)
    assert (buffer, boundary) == (0.0105, 100.8135)
    small, _ = candidate_boundary(trigger_policy(), "LONG", opening_range_high=100.8030,
                                  opening_range_low=100.0, latest_atr=0.1)
    assert small == 0.01  # the supplied floor, never the smaller ATR product


@pytest.mark.parametrize("changes", (
    {"direction": "FLAT"}, {"opening_range_high": 100.0, "opening_range_low": 100.0},
    {"latest_atr": -0.4}, {"opening_range_high": None},
))
def test_candidate_boundary_refuses_unsupported_inputs(changes):
    values = dict(direction="LONG", opening_range_high=101.0, opening_range_low=100.0,
                  latest_atr=0.4)
    values.update(changes)
    with pytest.raises(RecordError):
        candidate_boundary(trigger_policy(), values.pop("direction"), **values)


def test_candidate_boundary_requires_a_positive_supplied_buffer():
    policy = trigger_policy(buffer_floor=0.0, buffer_atr_multiple=0.0)
    with pytest.raises(RecordError):
        candidate_boundary(policy, "LONG", opening_range_high=101.0, opening_range_low=100.0,
                           latest_atr=0.4)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_freeze_candidate_records_the_crossing_references(direction):
    high, low = RANGE[direction]
    frozen = freeze_candidate(trigger_policy(), direction=direction, crossed_at=CROSS,
                              opening_range_high=high, opening_range_low=low, latest_atr=0.4,
                              anchor_bar_id="m62-anchor-minute", attempt_number=1,
                              input_record_ids=("m62-crossing-current",))
    assert frozen.boundary == BOUNDARY[direction] and frozen.frozen_atr == 0.4
    assert frozen.mode == TAPE and frozen.crossed_at == CROSS


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_fresh_crossing_needs_two_consecutive_same_arm_observations(direction):
    inside, edge, _ = PRICES[direction]
    previous = observation("m62-previous", CROSS - timedelta(seconds=1), inside)
    current = observation("m62-current", CROSS, edge)
    result = evaluate_crossing(trigger_policy(), direction, boundary=BOUNDARY[direction],
                               previous=previous, current=current)
    assert result.status == CROSSED and result.reason is None
    assert result.input_record_ids == ("m62-previous", "m62-current")
    assert result.as_dict()["boundary"] == BOUNDARY[direction]


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("previous,current,expected", (
    (100.8134, 100.8135, CROSSED),
    (100.8135, 100.8136, NOT_CROSSED),
    (100.8134, 100.8134, NOT_CROSSED),
))
def test_fx07_boundary_comparison_is_exact(direction, previous, current, expected):
    """Both prices meet the same candidate boundary; display rounding cannot move it."""
    edge = flip(100.8135, direction)
    result = evaluate_crossing(
        trigger_policy(), direction, boundary=edge,
        previous=observation("m62-previous", CROSS - timedelta(seconds=1),
                             flip(previous, direction)),
        current=observation("m62-current", CROSS, flip(current, direction)))
    assert result.status == expected


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_fx18_a_falling_boundary_under_a_shrinking_atr_is_not_a_crossing(direction):
    high, low = RANGE[direction]
    policy = trigger_policy()
    _, wide = candidate_boundary(policy, direction, opening_range_high=high,
                                 opening_range_low=low, latest_atr=0.6)
    _, narrow = candidate_boundary(policy, direction, opening_range_high=high,
                                   opening_range_low=low, latest_atr=0.2)
    flat = flip(101.02, direction)
    assert (wide, narrow) == (flip(101.03, direction), flip(101.01, direction))
    result = evaluate_crossing(
        policy, direction, boundary=narrow,
        previous=observation("m62-previous", CROSS - timedelta(seconds=1), flat),
        current=observation("m62-current", CROSS, flat))
    assert result.status == NOT_CROSSED and result.reason == "NO_FRESH_CROSSING"


@pytest.mark.parametrize("changes,reason", (
    ({"mode": QUOTE_PROJECTED}, "CURRENT_WRONG_ARM"),
    ({"coverage_known": False}, "CURRENT_SAMPLE_COVERAGE_UNKNOWN"),
    ({"age": 3.01}, "CURRENT_STALE_SAMPLE"),
    ({"age": None}, "CURRENT_SAMPLE_AGE_UNKNOWN"),
    ({"price": None, "missing_reason": "NO_ELIGIBLE_TRADE"}, "CURRENT_NO_ELIGIBLE_TRADE"),
    ({"available_at": CROSS + timedelta(seconds=1)}, "CURRENT_SAMPLE_NOT_AVAILABLE"),
))
def test_an_unusable_current_observation_cannot_establish_a_crossing(changes, reason):
    values = dict(price=101.02)
    values.update(changes)
    current = observation("m62-current", CROSS, values.pop("price"), **values)
    result = evaluate_crossing(
        trigger_policy(), "LONG", boundary=101.02,
        previous=observation("m62-previous", CROSS - timedelta(seconds=1), 101.01),
        current=current)
    assert result.status == "UNKNOWN" and result.reason == reason


def test_the_first_observation_after_a_gap_cannot_cross():
    current = observation("m62-current", CROSS, 101.03)
    alone = evaluate_crossing(trigger_policy(), "LONG", boundary=101.02, previous=None,
                              current=current)
    assert alone.status == "UNKNOWN" and alone.reason == "NO_PRECEDING_OBSERVATION"
    gapped = evaluate_crossing(
        trigger_policy(), "LONG", boundary=101.02,
        previous=observation("m62-previous", CROSS - timedelta(seconds=2), 101.01),
        current=current)
    assert gapped.status == "UNKNOWN" and gapped.reason == "OBSERVATION_GAP"


@pytest.mark.parametrize("changes", (
    {"policy": "TAPE"}, {"direction": "FLAT"}, {"boundary": 0.0}, {"current": None},
    {"previous": 101.01},
))
def test_crossing_refuses_unsupported_inputs(changes):
    values = dict(policy=trigger_policy(), direction="LONG", boundary=101.02,
                  previous=observation("m62-previous", CROSS - timedelta(seconds=1), 101.01),
                  current=observation("m62-current", CROSS, 101.03))
    values.update(changes)
    with pytest.raises(RecordError):
        evaluate_crossing(values.pop("policy"), values.pop("direction"), **values)


# --- the ten-sample acceptance window ---------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_fx10_seven_of_ten_samples_accept(direction):
    result = evaluate_orb5_trigger(request(direction, observations=grid(direction, prices=FX10)))
    gate = result.gate("ACCEPTANCE_WINDOW")
    assert (gate.status, gate.observed, gate.threshold) == ("PASS", 7.0, 7.0)
    assert result.accepting_samples == 7
    assert len(result.samples) == 10
    assert [row.instant for row in result.samples] == [
        TRIGGER - timedelta(seconds=step) for step in range(9, -1, -1)]
    assert sum(1 for row in result.samples if row.accepting) == 7


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_six_of_ten_samples_fail_the_supplied_minimum(direction):
    prices = FX10[:1] + (101.01,) + FX10[2:]
    result = evaluate_orb5_trigger(request(direction, observations=grid(direction, prices=prices)))
    gate = result.gate("ACCEPTANCE_WINDOW")
    assert (gate.status, gate.observed, gate.reason) == ("FAIL", 6.0, "ACCEPTANCE_BELOW_MINIMUM")
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_a_sample_exactly_at_the_frozen_boundary_accepts():
    result = evaluate_orb5_trigger(request(observations=grid(prices=(101.02,) * 10)))
    assert result.accepting_samples == 10
    assert all(row.status == "PASS" for row in result.samples)


@pytest.mark.parametrize("changes,reason", (
    ({"age": 3.01}, "STALE_SAMPLE"),
    ({"age": None}, "SAMPLE_AGE_UNKNOWN"),
    ({"mode": QUOTE_PROJECTED}, "SAMPLE_MISSING"),
))
def test_one_unusable_sample_prevents_a_passing_window(changes, reason):
    rows = grid()[:9] + grid(count=10, **changes)[9:]
    result = evaluate_orb5_trigger(request(observations=rows))
    gate = result.gate("ACCEPTANCE_WINDOW")
    assert gate.status == "UNKNOWN" and gate.reason == reason
    assert result.accepting_samples is None
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_a_later_arrival_cannot_repair_the_sample_it_missed():
    late = observation("m62-sample-late", TRIGGER - timedelta(seconds=9), 101.03,
                       available_at=TRIGGER)
    rows = (late,) + grid()[1:]
    result = evaluate_orb5_trigger(request(observations=rows))
    assert result.gate("ACCEPTANCE_WINDOW").reason == "SAMPLE_NOT_AVAILABLE"
    assert result.samples[0].status == "UNKNOWN"


def test_an_incomplete_grid_is_unknown_not_a_shorter_window():
    result = evaluate_orb5_trigger(request(observations=grid()[1:]))
    assert result.gate("ACCEPTANCE_WINDOW").reason == "SAMPLE_MISSING"
    assert result.samples[0].reason == "SAMPLE_MISSING"


def test_many_messages_at_one_instant_supply_no_extra_sample():
    """FX-10: a burst at one grid instant is ambiguous, never two observations."""
    burst = grid() + (observation("m62-sample-burst", TRIGGER, 101.03),)
    result = evaluate_orb5_trigger(request(observations=burst))
    assert result.gate("ACCEPTANCE_WINDOW").reason == "AMBIGUOUS_SAMPLE"
    assert result.samples[-1].status == "UNKNOWN"


def test_an_observation_from_the_other_arm_is_never_borrowed():
    rows = grid(mode=QUOTE_PROJECTED, prefix="m62-quote-sample")
    result = evaluate_orb5_trigger(request(observations=grid() + rows))
    assert result.gate("ACCEPTANCE_WINDOW").status == "PASS"
    other = evaluate_orb5_trigger(request(observations=rows))
    assert other.gate("ACCEPTANCE_WINDOW").reason == "SAMPLE_MISSING"


# --- the attempt window, deadline and reset ---------------------------------


@pytest.mark.parametrize("elapsed,status,reason", (
    (5, "FAIL", "BEFORE_ACCEPTANCE_WINDOW"),
    (9, "FAIL", "BEFORE_ACCEPTANCE_WINDOW"),
    (10, "PASS", None),
    (30, "PASS", None),
    (31, "FAIL", "ACCEPTANCE_DEADLINE_PASSED"),
))
def test_the_half_open_attempt_window_uses_the_supplied_seconds(elapsed, status, reason):
    crossed = TRIGGER - timedelta(seconds=elapsed)
    result = evaluate_orb5_trigger(request(crossed_at=crossed))
    gate = result.gate(ATTEMPT_GATE)
    assert (gate.status, gate.reason, gate.observed) == (status, reason, float(elapsed))


def test_an_off_grid_evaluation_is_unknown_not_rounded():
    crossed = TRIGGER - timedelta(seconds=10, milliseconds=500)
    result = evaluate_orb5_trigger(request(crossed_at=crossed))
    gate = result.gate(ATTEMPT_GATE)
    assert gate.status == "UNKNOWN" and gate.reason == "EVALUATION_OFF_GRID"
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_passed_deadline_waits_for_the_required_reset(direction):
    result = evaluate_orb5_trigger(request(direction, crossed_at=TRIGGER - timedelta(seconds=31)))
    assert result.state == StrategyState("ARMED", "WAITING_FOR_RESET")
    assert result.reset_satisfied is False


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_final_close_inside_the_unbuffered_range_invalidates_and_resets(direction):
    inside = flip(100.5, direction)
    result = evaluate_orb5_trigger(request(direction, minute_close=minute_close(close=inside)))
    gate = result.gate(ATTEMPT_GATE)
    assert gate.reason == "INSIDE_OR_CLOSE_INVALIDATION"
    assert result.state == StrategyState("INVALIDATED") and result.reset_satisfied is True
    assert "INSIDE_OR_CLOSE_INVALIDATION" in INVALIDATIONS


@pytest.mark.parametrize("close", (101.0, 100.0, 101.5))
def test_a_close_at_or_outside_the_range_edge_is_not_a_reset(close):
    result = evaluate_orb5_trigger(request(minute_close=minute_close(close=close)))
    assert result.state == StrategyState("ALERT_TRIGGERED")
    assert result.reset_satisfied is False


def test_a_pending_bar_holds_action_without_moving_the_deadline():
    """The one D-090 exception: hold while a just-ended bar awaits its final version."""
    pending = minute_close(close=None, final=False)
    result = evaluate_orb5_trigger(request(minute_close=pending, eligibility=None))
    gate = result.gate(ATTEMPT_GATE)
    assert gate.status == "UNKNOWN" and gate.reason == "MINUTE_BAR_PENDING"
    assert gate.observed == 10.0 and gate.threshold == 30.0
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_a_close_that_is_not_yet_available_is_not_read():
    later = minute_close(close=100.5, available_at=TRIGGER + timedelta(seconds=1))
    result = evaluate_orb5_trigger(request(minute_close=later))
    assert result.state == StrategyState("ALERT_TRIGGERED")


@pytest.mark.parametrize("supplied", (
    {"minute_close": minute_close(close=None, final=False, coverage_known=False)},
    {"observations": grid()[:9] + grid(coverage_known=False)[9:]},
    {"last_trade": observation("m62-last-trade", TRIGGER, 101.03, coverage_known=False)},
))
def test_lost_coverage_invalidates_the_attempt(supplied):
    result = evaluate_orb5_trigger(request(**supplied))
    assert result.gate(ATTEMPT_GATE).reason == "COVERAGE_LOST"
    assert result.state == StrategyState("INVALIDATED")


def test_a_sample_with_unknown_coverage_is_never_read_as_accepting():
    rows = grid()[:9] + grid(coverage_known=False)[9:]
    result = evaluate_orb5_trigger(request(observations=rows))
    gate = result.gate("ACCEPTANCE_WINDOW")
    assert gate.status == "UNKNOWN" and gate.reason == "SAMPLE_COVERAGE_UNKNOWN"
    assert result.accepting_samples is None
    assert result.state == StrategyState("INVALIDATED")


def test_an_unknown_mandatory_input_invalidates_a_partially_observed_window():
    result = evaluate_orb5_trigger(request(eligibility=None))
    assert result.gate(ATTEMPT_GATE).reason == "UNKNOWN_MANDATORY_INPUT"
    assert result.state == StrategyState("INVALIDATED")


def test_a_supplied_halt_invalidates_the_attempt():
    supplied = geometry()
    context, assessment = eligibility(geometry_result=supplied,
                                      status=status(halted=True, available_at=TRIGGER))
    result = evaluate_orb5_trigger(request(eligibility=assessment, geometry=supplied))
    assert result.gate(ATTEMPT_GATE).reason == "MANDATORY_HALT"
    assert result.state == StrategyState("INVALIDATED")
    assert context.evaluated_at == TRIGGER


# --- the two participation arms ---------------------------------------------


@pytest.mark.parametrize("ratio,status", ((1.50, "PASS"), (1.4999999, "FAIL"), (0.0, "FAIL")))
def test_tape_intensity_boundary(ratio, status):
    result = evaluate_orb5_trigger(request(participation=intensity(ratio=ratio)))
    gate = result.gate("PARTICIPATION")
    assert (gate.status, gate.observed, gate.threshold) == (status, ratio, 1.5)


@pytest.mark.parametrize("changes,reason", (
    ({"coverage_complete": False}, "PARTICIPATION_COVERAGE_INCOMPLETE"),
    ({"ratio": None, "missing_reason": "INTERVAL_COVERAGE_UNKNOWN"},
     "INTERVAL_COVERAGE_UNKNOWN"),
))
def test_incomplete_tape_evidence_is_unknown_not_passing(changes, reason):
    result = evaluate_orb5_trigger(request(participation=intensity(**changes)))
    gate = result.gate("PARTICIPATION")
    assert gate.status == "UNKNOWN" and gate.reason == reason
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_a_missing_participation_result_is_reported_not_assumed():
    result = evaluate_orb5_trigger(request(participation=None))
    assert result.gate("PARTICIPATION").reason == "PARTICIPATION_UNAVAILABLE"


@pytest.mark.parametrize("mode,supplied", (
    (TAPE, "projection"), (QUOTE_PROJECTED, "intensity"),
))
def test_one_arm_can_never_supply_the_other_arms_evidence(mode, supplied):
    at = TRIGGER
    other = projection(at=at) if supplied == "projection" else intensity()
    result = evaluate_orb5_trigger(request(mode=mode, participation=other))
    gate = result.gate("PARTICIPATION")
    assert gate.status == "UNKNOWN" and gate.reason == "PARTICIPATION_ARM_MISMATCH"
    assert result.state != StrategyState("ALERT_TRIGGERED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_fx11_projected_ratio_passes_at_the_supplied_minimum(direction):
    at = CROSS + timedelta(seconds=20)
    supplied = projection(at=at, elapsed=20.0, volume=10000.0, reference=20000.0)
    result = evaluate_orb5_trigger(request(direction, mode=QUOTE_PROJECTED, at=at,
                                           participation=supplied))
    gate = result.gate("PARTICIPATION")
    assert (gate.status, gate.observed) == ("PASS", 1.5)
    assert result.state == StrategyState("ALERT_TRIGGERED")


def test_a_projected_ratio_below_the_supplied_minimum_fails():
    at = CROSS + timedelta(seconds=20)
    supplied = projection(at=at, elapsed=20.0, volume=9999.0, reference=20000.0)
    result = evaluate_orb5_trigger(request(mode=QUOTE_PROJECTED, at=at, participation=supplied))
    assert result.gate("PARTICIPATION").reason == "PARTICIPATION_BELOW_MINIMUM"


def test_fx12_the_projection_cannot_pass_in_the_first_seconds_of_a_new_minute():
    crossed = datetime(2026, 7, 6, 6, 50, 55, tzinfo=PACIFIC)
    at = crossed + timedelta(seconds=10)
    supplied = projection(at=at, elapsed=5.0, volume=10000.0, reference=20000.0)
    result = evaluate_orb5_trigger(request(mode=QUOTE_PROJECTED, at=at, crossed_at=crossed,
                                           participation=supplied))
    gate = result.gate("PARTICIPATION")
    assert gate.status == "FAIL" and gate.reason == "PROJECTION_ELAPSED_BELOW_MINIMUM"
    assert result.gate(ATTEMPT_GATE).status == "PASS"  # the deadline is unchanged


@pytest.mark.parametrize("changes,reason", (
    ({"reference": 0.0}, "PROJECTION_REFERENCE_UNAVAILABLE"),
    ({"minute_volume": None, "missing_reason": "MINUTE_BASELINE_UNKNOWN"},
     "MINUTE_BASELINE_UNKNOWN"),
    ({"coverage_complete": False}, "PARTICIPATION_COVERAGE_INCOMPLETE"),
))
def test_an_incomplete_projection_is_unknown_not_passing(changes, reason):
    result = evaluate_orb5_trigger(request(mode=QUOTE_PROJECTED,
                                           participation=projection(**changes)))
    gate = result.gate("PARTICIPATION")
    assert gate.status == "UNKNOWN" and gate.reason == reason


@pytest.mark.parametrize("start", (
    CROSS + timedelta(seconds=11), CROSS - timedelta(seconds=50), CROSS,
))
def test_a_previous_minutes_numerator_is_never_carried_forward(start):
    """Only the minute containing this instant, with its own elapsed seconds, counts."""
    supplied = projection(at=TRIGGER, elapsed=10.0)
    supplied = replace(supplied, minute_start=start)
    result = evaluate_orb5_trigger(request(mode=QUOTE_PROJECTED, participation=supplied))
    gate = result.gate("PARTICIPATION")
    if start == CROSS:
        assert gate.status == "PASS"
    else:
        assert gate.status == "UNKNOWN" and gate.reason == "PROJECTION_MINUTE_MISMATCH"


# --- the fresh last trade, eligibility and trigger geometry ------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("index,status", ((2, "PASS"), (1, "PASS"), (0, "FAIL")))
def test_the_last_trade_must_still_stand_at_or_beyond_the_frozen_boundary(direction, index,
                                                                          status):
    price = PRICES[direction][index]
    supplied = observation("m62-last-trade", TRIGGER, price)
    result = evaluate_orb5_trigger(request(direction, last_trade=supplied))
    gate = result.gate("LAST_TRADE_BEYOND_BOUNDARY")
    assert (gate.status, gate.observed) == (status, price)
    if status == "FAIL":
        assert gate.reason == "LAST_TRADE_INSIDE_BOUNDARY"


def test_the_quote_arm_still_requires_its_own_fresh_last_trade():
    stale = observation("m62-last-trade", TRIGGER, 101.03, mode=QUOTE_PROJECTED, age=3.01)
    result = evaluate_orb5_trigger(request(mode=QUOTE_PROJECTED, last_trade=stale))
    gate = result.gate("LAST_TRADE_BEYOND_BOUNDARY")
    assert gate.status == "UNKNOWN" and gate.reason == "LAST_TRADE_STALE_SAMPLE"
    missing = evaluate_orb5_trigger(request(mode=QUOTE_PROJECTED, last_trade=None))
    assert missing.gate("LAST_TRADE_BEYOND_BOUNDARY").reason == "LAST_TRADE_UNAVAILABLE"


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_the_supplied_eligibility_must_be_armed_at_this_instant(direction):
    supplied = geometry(direction)
    _, armed = eligibility(direction, geometry_result=supplied)
    assert evaluate_orb5_trigger(request(
        direction, eligibility=armed, geometry=supplied)).gate("ELIGIBILITY_ARMED").status == "PASS"
    _, blocked = eligibility(direction, geometry_result=supplied,
                             status=status(macro_blackout_active=True, available_at=TRIGGER))
    result = evaluate_orb5_trigger(request(direction, eligibility=blocked, geometry=supplied))
    gate = result.gate("ELIGIBILITY_ARMED")
    assert gate.status == "FAIL" and gate.reason == "ELIGIBILITY_FAILED_MANDATORY_STATUS"
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_an_eligibility_assessment_from_another_instant_is_not_current():
    at = CROSS + timedelta(seconds=20)
    _, earlier = eligibility(at=TRIGGER)
    result = evaluate_orb5_trigger(request(at=at, eligibility=earlier))
    assert result.gate("ELIGIBILITY_ARMED").reason == "ELIGIBILITY_NOT_CURRENT"
    assert result.state == StrategyState("INVALIDATED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("outcome,status", (
    ("READY", "PASS"), ("REJECTED", "FAIL"), ("UNAVAILABLE", "UNKNOWN")))
def test_the_trigger_geometry_gate_reports_the_supplied_m43_result(direction, outcome, status):
    supplied = geometry(direction, outcome=outcome)
    _, armed = eligibility(direction, geometry_result=geometry(direction))
    result = evaluate_orb5_trigger(request(direction, geometry=supplied, eligibility=armed))
    gate = result.gate("TRIGGER_RISK_TARGETS")
    assert gate.status == status
    assert result.state == (StrategyState("ALERT_TRIGGERED") if status == "PASS"
                            else StrategyState("ARMED", "CROSSING_OBSERVED"))


def test_missing_trigger_geometry_can_never_be_treated_as_passing():
    result = evaluate_orb5_trigger(request(geometry=None))
    assert result.gate("TRIGGER_RISK_TARGETS").reason == "TRIGGER_GEOMETRY_UNAVAILABLE"
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("supplied,reason", (
    (dict(mode=QUOTE_PROJECTED), "GEOMETRY_ARM_MISMATCH"),
    (dict(direction="SHORT"), "GEOMETRY_DIRECTION_MISMATCH"),
    (dict(crossed_at=CROSS + timedelta(seconds=1)), "GEOMETRY_CROSSING_MISMATCH"),
    (dict(at=CROSS + timedelta(seconds=20)), "GEOMETRY_NOT_CURRENT"),
))
def test_foreign_or_stale_geometry_cannot_serve_this_attempt(supplied, reason):
    result = evaluate_orb5_trigger(request(geometry=geometry(**supplied)))
    assert result.gate("TRIGGER_RISK_TARGETS").reason == reason
    assert result.state != StrategyState("ALERT_TRIGGERED")


def test_geometry_for_another_boundary_cannot_serve_this_attempt():
    supplied = geometry()
    other = replace(supplied.request,
                    boundary=changed_value(supplied.request.boundary, 101.03))
    result = evaluate_orb5_trigger(request(geometry=replace(supplied, request=other)))
    assert result.gate("TRIGGER_RISK_TARGETS").reason == "GEOMETRY_BOUNDARY_MISMATCH"


# --- the whole supplied trigger ---------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("mode", MODES)
def test_every_supplied_gate_passing_reports_alert_triggered(direction, mode):
    result = evaluate_orb5_trigger(request(direction, mode=mode))
    assert result.state == StrategyState("ALERT_TRIGGERED") and result.reasons == ()
    assert [row.name for row in result.gates] == list(TRIGGER_GATES)
    assert all(row.status == "PASS" for row in result.gates)
    assert result.elapsed_seconds == 10.0 and result.accepting_samples == 10
    assert result.definition_reference == DEFINITION
    assert result.policy_version == POLICY_VERSION
    assert result.candidate.mode == mode


def test_the_assessment_is_immutable_and_stable():
    result = evaluate_orb5_trigger(request())
    with pytest.raises(FrozenInstanceError):
        result.gates[0].__setattr__("status", "FAIL")
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("state", StrategyState("INVALIDATED"))
    assert result.to_json() == evaluate_orb5_trigger(request()).to_json()
    rendered = json.loads(result.to_json())
    assert rendered["trigger_version"] == TRIGGER_VERSION
    assert rendered["mode"] == TAPE and rendered["state"] == "ALERT_TRIGGERED"
    assert len(rendered["samples"]) == 10


@pytest.mark.parametrize("changes", (
    {"name": "NOT_A_GATE"}, {"status": "MAYBE"}, {"status": "FAIL", "reason": None},
    {"reason": "UNKNOWN"}, {"input_record_ids": ["a"]}, {"input_record_ids": (" ",)},
))
def test_gate_results_require_supported_facts(changes):
    values = dict(name="PARTICIPATION", status="FAIL", observed=1.0, threshold=1.5,
                  reason="PARTICIPATION_BELOW_MINIMUM", input_record_ids=())
    values.update(changes)
    with pytest.raises(RecordError):
        TriggerGate(**values)


def test_evaluate_requires_a_canonical_request():
    with pytest.raises(RecordError):
        evaluate_orb5_trigger("ALERT_TRIGGERED")


# --- rules, quota, reset and the storage-first owner ------------------------


def test_supplied_rules_cover_only_the_m62_states():
    rules = trigger_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("ARMED")
    armed, crossing = StrategyState("ARMED"), StrategyState("ARMED", "CROSSING_OBSERVED")
    assert (armed, crossing) in rules.allowed
    assert (armed, StrategyState("ALERT_TRIGGERED")) not in rules.allowed
    assert (crossing, StrategyState("ALERT_TRIGGERED")) in rules.allowed
    assert not any(old.state == "EXPIRED" for old, _ in rules.allowed)
    assert {new.state for _, new in rules.allowed} == {
        "ARMED", "ALERT_TRIGGERED", "INVALIDATED", "EXPIRED"}


@pytest.mark.parametrize("changes", (
    {"instrument_type": "OPTION"}, {"direction": "FLAT"}, {"symbol": " "},
    {"strategy_version": "UNKNOWN"}, {"policy": None}, {"session": None},
))
def test_owner_construction_rejects_an_unsupported_scope(changes):
    with pytest.raises(RecordError):
        owner(**changes)


def test_the_reserved_number_survives_until_the_crossing():
    subject = owner()
    assert subject.pending_attempt_number == 1 and subject.started_attempt_count == 0
    assert subject.reserve_heads_up(CROSS - timedelta(seconds=30)) == 1
    with pytest.raises(RecordError):
        subject.reserve_heads_up(CROSS)
    assert subject.pending_attempt_number == 1
    changes = subject.open_attempt(candidate(), record_id="m62-open-1")
    assert changes[0].to_substate == "CROSSING_OBSERVED"
    assert subject.current_state() == StrategyState("ARMED")
    assert subject.confirm(changes[0]) == StrategyState("ARMED", "CROSSING_OBSERVED")
    assert subject.started_attempt_count == 1 and subject.pending_attempt_number == 2


def test_a_crossing_must_use_the_reserved_number_and_this_owner():
    subject = owner()
    with pytest.raises(RecordError):
        subject.open_attempt(candidate(attempt_number=2), record_id="m62-open-1")
    with pytest.raises(RecordError):
        subject.open_attempt(candidate("SHORT"), record_id="m62-open-1")
    with pytest.raises(RecordError):
        subject.open_attempt(candidate(mode=QUOTE_PROJECTED), record_id="m62-open-1")
    with pytest.raises(RecordError):
        subject.open_attempt("CROSSED", record_id="m62-open-1")


def test_only_the_pending_recorded_transition_advances_the_owner():
    subject = owner()
    changes = subject.open_attempt(candidate(), record_id="m62-open-1")
    with pytest.raises(RecordError):
        subject.confirm(replace(changes[0], record_id="m62-other"))
    subject.confirm(changes[0])
    with pytest.raises(RecordError):
        subject.confirm(changes[0])


def test_an_unchanged_state_proposes_no_transition():
    subject = owner()
    subject.confirm(subject.open_attempt(candidate(), record_id="m62-open-1")[0])
    supplied = request(observations=grid(prices=(101.01,) * 10))
    assessment, changes = subject.propose(supplied, record_id="m62-change-1")
    assert assessment.state == StrategyState("ARMED", "CROSSING_OBSERVED") and changes == ()


def test_the_owner_refuses_a_foreign_attempt_policy_or_backward_time():
    subject = owner()
    with pytest.raises(RecordError):
        subject.propose(request(), record_id="m62-change-1")
    subject.confirm(subject.open_attempt(candidate(), record_id="m62-open-1")[0])
    with pytest.raises(RecordError):
        subject.propose(request(crossed_at=CROSS + timedelta(seconds=1)),
                        record_id="m62-change-1")
    with pytest.raises(RecordError):
        subject.propose("ALERT_TRIGGERED", record_id="m62-change-1")
    subject.propose(request(), record_id="m62-change-1")
    with pytest.raises(RecordError):
        subject.propose(request(at=TRIGGER - timedelta(seconds=1)), record_id="m62-change-2")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_second_attempt_needs_the_reset_and_the_supplied_cooldown(direction):
    subject = owner(direction)
    subject.confirm(subject.open_attempt(candidate(direction), record_id="m62-open-1")[0])
    quota = subject.attempt_quota(CROSS + timedelta(seconds=1))
    assert quota.status == "FAIL" and quota.reason == "RESET_REQUIRED"
    assessment, changes = subject.propose(request(direction), record_id="m62-change-1")
    assert assessment.state == StrategyState("ALERT_TRIGGERED")
    subject.confirm(changes[0])
    late = TRIGGER + timedelta(seconds=31)
    _, closing = subject.propose(request(direction, at=late), record_id="m62-change-2")
    assert closing[0].to_substate == "WAITING_FOR_RESET"
    subject.confirm(closing[0])
    inside = minute_close(at=late, close=flip(100.5, direction))
    subject.confirm(subject.reset(inside, at=late, record_id="m62-reset-1")[0])
    assert subject.current_state() == StrategyState("ARMED")
    assert subject.current_candidate() is None
    early = subject.attempt_quota(TRIGGER + timedelta(seconds=599))
    assert early.status == "FAIL" and early.reason == "COOLDOWN_NOT_ELAPSED"
    ready = TRIGGER + timedelta(seconds=600)
    assert subject.attempt_quota(ready).status == "PASS"  # equality passes
    second = candidate(direction, crossed_at=ready, attempt_number=2)
    subject.confirm(subject.open_attempt(second, record_id="m62-open-2")[0])
    assert subject.started_attempt_count == 2


def test_the_supplied_quota_limits_attempts_per_direction():
    subject = owner()
    subject.restore(StrategyState("ARMED"), started_attempt_count=2, reset_satisfied=True)
    quota = subject.attempt_quota(CROSS)
    assert quota.status == "FAIL" and quota.reason == "ATTEMPT_QUOTA_EXHAUSTED"
    assert (quota.observed, quota.threshold) == (2.0, 2.0)
    with pytest.raises(RecordError):
        subject.open_attempt(candidate(attempt_number=3), record_id="m62-open-3")
    assert QUOTA_GATE in GATE_NAMES


def test_a_reset_requires_an_available_final_close_inside_the_range():
    subject = owner()
    subject.confirm(subject.open_attempt(candidate(), record_id="m62-open-1")[0])
    late = TRIGGER + timedelta(seconds=31)
    _, closing = subject.propose(request(at=late), record_id="m62-change-1")
    subject.confirm(closing[0])
    for close in (minute_close(at=late, close=None, final=False),
                  minute_close(at=late, coverage_known=False),
                  minute_close(at=late, close=101.5),
                  minute_close(at=late, available_at=late + timedelta(seconds=5))):
        with pytest.raises(RecordError):
            subject.reset(close, at=late, record_id="m62-reset-1")
    with pytest.raises(RecordError):
        subject.reset("INSIDE", at=late, record_id="m62-reset-1")


def test_expiry_ends_a_pending_attempt_at_the_window_end():
    subject = owner()
    subject.confirm(subject.open_attempt(candidate(), record_id="m62-open-1")[0])
    end = datetime(2026, 7, 6, 7, 15, tzinfo=PACIFIC)
    changes = subject.expire(at=end, reason="EVALUATION_WINDOW_ENDED", record_id="m62-expire-1")
    assert changes[0].to_state == "EXPIRED"
    assert subject.confirm(changes[0]) == StrategyState("EXPIRED")
    assert subject.current_candidate() is None
    with pytest.raises(RecordError):
        subject.expire(at=end, reason="UNKNOWN", record_id="m62-expire-2")


def test_restore_requires_an_unused_owner_and_supported_facts():
    subject = owner()
    frozen = candidate()
    assert subject.restore(StrategyState("ARMED", "WAITING_FOR_RESET"), candidate=frozen,
                           started_attempt_count=1, reset_satisfied=False,
                           last_action_at=TRIGGER) == StrategyState("ARMED", "WAITING_FOR_RESET")
    assert subject.current_candidate() == frozen
    assert subject.attempt_quota(TRIGGER + timedelta(seconds=601)).reason == "RESET_REQUIRED"
    fresh = owner()
    for changes in ({"state": StrategyState("SETUP_FORMING")},
                    {"state": StrategyState("ARMED", "PENDING")},
                    {"state": "ARMED"}, {"state": StrategyState("ARMED"), "candidate": "FROZEN"},
                    {"state": StrategyState("ARMED"), "reset_satisfied": 1},
                    {"state": StrategyState("ARMED"), "started_attempt_count": -1}):
        with pytest.raises(RecordError):
            fresh.restore(**changes)
    used = owner()
    used.confirm(used.open_attempt(candidate(), record_id="m62-open-1")[0])
    with pytest.raises(RecordError):
        used.restore(StrategyState("ARMED"))


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           trigger_rules())


async def test_a_refused_recording_leaves_the_owner_where_it_was():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = owner()
    crossing_context, _ = eligibility(at=CROSS)
    opening = subject.open_attempt(candidate(), record_id="m62-refused")
    engine = StateTransitionEngine(scope("LONG"), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(opening[0], context=crossing_context)
    assert engine.current_state() == StrategyState("ARMED")
    assert subject.current_state() == StrategyState("ARMED")
    assert subject.started_attempt_count == 0 and subject.current_candidate() is None


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_the_supplied_trigger_through_the_m42_engine_and_m51_store(direction):
    supplied = geometry(direction)
    context, armed = eligibility(direction, geometry_result=supplied)
    crossing_context, _ = eligibility(direction, at=CROSS)
    frozen = freeze_candidate(trigger_policy(), direction=direction, crossed_at=CROSS,
                              opening_range_high=RANGE[direction][0],
                              opening_range_low=RANGE[direction][1], latest_atr=0.4,
                              anchor_bar_id="m62-anchor-minute", attempt_number=1)
    subject = owner(direction)
    subject.reserve_heads_up(CROSS - timedelta(seconds=30))
    opening = subject.open_attempt(frozen, record_id="m62-open-" + direction)

    connection = await db.init_db()
    engine = StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection))
    first = await engine.apply(opening[0], context=crossing_context)
    assert subject.confirm(opening[0]) == StrategyState("ARMED", "CROSSING_OBSERVED")

    evaluation = request(direction, eligibility=armed, geometry=supplied,
                         candidate=frozen)
    assessment, changes = subject.propose(evaluation, record_id="m62-trigger-" + direction)
    assert assessment.state == StrategyState("ALERT_TRIGGERED") and assessment.reasons == ()
    entry = await engine.apply(changes[0], context=context)
    assert engine.current_state() == StrategyState("ALERT_TRIGGERED")
    assert subject.confirm(changes[0]) == StrategyState("ALERT_TRIGGERED")
    assert changes[0].metadata.data_mode == DATA_MODE
    assert changes[0].strategy_id == STRATEGY_ID

    store = ResearchEventStore(connection)
    stored = await store.append(changes[0], session=DAY, recorded_at=TRIGGER)
    assert stored["kind"] == "STATE_TRANSITION"
    assert await store.append(changes[0], session=DAY, recorded_at=TRIGGER) == stored

    proof = {
        "synthetic_only": True, "direction": direction,
        "boundary": frozen.boundary, "buffer": frozen.buffer,
        "candidate": frozen.as_dict(), "assessment": assessment.as_dict(),
        "opening_transition": opening[0].as_dict(), "transition": changes[0].as_dict(),
        "opening_position": first.position, "stored_position": entry.position,
        "stored_fingerprint": stored["fingerprint"],
        "repeated_assessment_identical":
            evaluate_orb5_trigger(evaluation).to_json() == assessment.to_json(),
    }
    assert proof["repeated_assessment_identical"]
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    Path(f"/tmp/m62-orb5-trigger-{direction.lower()}-proof.json").write_text(rendered)
    await db.close_db()
