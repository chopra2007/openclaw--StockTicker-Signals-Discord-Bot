"""M7.3 supplied-input heads-up and actionable contracts for `HOD_COMP_RS`.

Every number below is a synthetic fixture supplied by the caller. A passing gate
proves the offline contract only: it establishes no tape or quote coverage, no
adopted `HOD_COMP_RS` rule, no alert and no permission to act. A reported
heads-up or ALERT_TRIGGERED here means the supplied gates passed at one instant
in a test process.

The M7.2 eligibility fixtures supply the ARMED input, and the supplied
observation, intensity, projection and minute-close records are the
strategy-neutral M6.2 ones.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db, hod_comp_rs_trigger
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.hod_comp_rs_trigger import (
    CROSSED, DATA_MODE, DistanceReading, ELIGIBILITY_GATE, ExtensionReading, FrozenStructure,
    GATE_NAMES, HEADS_UP, HEADS_UP_GATES, HeadsUpRequest, HodCompRsTriggerMachine,
    INVALIDATIONS, MODES, MinuteClose, NOT_CROSSED, Observation, ProjectedVolume, QUOTA_GATE,
    QUOTE_PROJECTED, RULES_VERSION, STATES, STRATEGY_ID, STRUCTURE_GATE, TAPE, TRIGGER_GATES,
    TRIGGER_VERSION, TapeIntensity, TriggerAssessment, TriggerGate, TriggerPolicy,
    TriggerRequest, evaluate_crossing, evaluate_hod_comp_rs_heads_up,
    evaluate_hod_comp_rs_trigger, freeze_structure, structure_boundary, trigger_rules,
)
from consensus_engine.rs_trend_eligibility import RsTrendRequest, evaluate_rs_trend_eligibility
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_models import RecordError
from consensus_engine.transition_store import SQLiteTransitionStore
from test_rs_trend_eligibility import (
    AT, DAY, PACIFIC, context as rs_context, decision, policy as rs_policy, snapshots, status,
)
from test_strategy_interface import session


CROSS = datetime(2026, 7, 6, 6, 50, tzinfo=PACIFIC)
TRIGGER = AT  # the crossing plus ten supplied seconds
EARLY = datetime(2026, 7, 6, 6, 49, tzinfo=PACIFIC)
VERSION = "M73_FIXTURE_ONLY_V1"
POLICY_VERSION = "M73_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M73_SUPPLIED_FIXTURE_DEFINITION"
# One synthetic coil under a frozen reference high, and its mirrored short twin.
# None of these numbers is an adopted threshold.
REFERENCE = {"LONG": 101.00, "SHORT": 99.00}
COMPRESSION = {"LONG": (100.95, 100.60), "SHORT": (99.40, 99.05)}
BOUNDARY = {"LONG": 101.02, "SHORT": 98.98}
# Inside the boundary, exactly at it, and beyond it.
PRICES = {"LONG": (101.01, 101.02, 101.03), "SHORT": (98.99, 98.98, 98.97)}
# Seven of ten supplied samples lie at or beyond the frozen boundary.
SEVEN = (101.01, 101.02, 101.03, 101.01, 101.02, 101.01, 101.02, 101.03, 101.02, 101.03)
SIX = (101.01, 101.02, 101.03, 101.01, 101.02, 101.01, 101.01, 101.03, 101.02, 101.03)
ATR = 0.40
RISK = 0.46
DISTANCE = 0.125  # (101.00 - 100.95) / 0.40, the supplied M7.1 measurement


def flip(value, direction):
    """Mirror a long fixture price into its short twin around the supplied pair."""
    if value is None or direction == "LONG":
        return value
    return float(Decimal(200) - Decimal(str(value)))


def eligibility(direction="LONG", *, at=TRIGGER, **changes):
    """The supplied M7.2 context and assessment for one instant."""
    supplied = rs_context(direction, evaluated_at=at, features=snapshots(direction, at=at),
                          quote=decision(direction, at=at))
    values = dict(context=supplied, policy=rs_policy(), status=status(available_at=at))
    values.update(changes)
    request = RsTrendRequest(**values)
    return supplied, evaluate_rs_trend_eligibility(request)


def armed(direction="LONG", *, at=TRIGGER, **changes):
    return eligibility(direction, at=at, **changes)[1]


def trigger_policy(mode=TAPE, **changes):
    values = dict(
        version=POLICY_VERSION, definition_reference=DEFINITION, mode=mode,
        buffer_floor=0.01, buffer_atr_multiple=0.05, window_open_seconds=10,
        window_close_seconds=30, sample_count=10, min_acceptance_ratio=0.70,
        sample_interval_seconds=1, max_observation_age_seconds=3.0,
        min_trade_intensity=1.40, min_projection_elapsed_seconds=10, max_extension_r=0.40,
        max_heads_up_distance_atr=0.35, max_structures_per_direction=2,
        action_cooldown_seconds=600.0,
    )
    values.update(changes)
    return TriggerPolicy(**values)


def structure(direction="LONG", *, mode=TAPE, frozen_at=EARLY, structure_number=1, **changes):
    high, low = COMPRESSION.get(direction, COMPRESSION["LONG"])
    values = dict(frozen_at=frozen_at, direction=direction, mode=mode,
                  structure_number=structure_number,
                  reference_extreme=REFERENCE.get(direction, REFERENCE["LONG"]),
                  compression_high=high, compression_low=low, frozen_atr=ATR, buffer=0.02,
                  boundary=BOUNDARY.get(direction, BOUNDARY["LONG"]),
                  anchor_bar_id="m73-anchor-minute",
                  input_record_ids=("m73-compression-window", "m73-reference-freeze"))
    values.update(changes)
    return FrozenStructure(**values)


def observation(record_id, at, price, *, mode=TAPE, age=1.0, available_at=None,
                coverage_known=True, missing_reason=None):
    return Observation(record_id=record_id, mode=mode, observed_at=at,
                       available_at=at if available_at is None else available_at, price=price,
                       age_seconds=age, coverage_known=coverage_known,
                       missing_reason=missing_reason)


def grid(direction="LONG", *, mode=TAPE, at=TRIGGER, count=10, prices=None,
         prefix="m73-sample", **changes):
    """`count` supplied observations on the one-second grid ending at `at`."""
    values = ([PRICES[direction][2]] * count if prices is None
              else [flip(value, direction) for value in prices])
    return tuple(observation("%s-%d" % (prefix, number),
                             at - timedelta(seconds=count - 1 - number), values[number],
                             mode=mode, **changes)
                 for number in range(count))


def intensity(**changes):
    values = dict(definition_reference="M73_SUPPLIED_INTENSITY_V1", ratio=1.40,
                  coverage_complete=True)
    values.update(changes)
    return TapeIntensity(**values)


def projection(*, at=TRIGGER, elapsed=10.0, volume=5000.0, reference=20000.0, **changes):
    values = dict(definition_reference="M73_SUPPLIED_PROJECTION_V1",
                  minute_start=at - timedelta(seconds=elapsed), elapsed_seconds=elapsed,
                  minute_volume=volume, reference_mean=reference, coverage_complete=True)
    values.update(changes)
    return ProjectedVolume(**values)


def distance(*, at=EARLY, value=DISTANCE, **changes):
    values = dict(definition_reference="M73_SUPPLIED_DISTANCE_V1", value=value,
                  available_at=at, record_ids=("m73-compression-window",))
    values.update(changes)
    return DistanceReading(**values)


def extension(*, at=TRIGGER, risk=RISK, **changes):
    values = dict(definition_reference="M73_SUPPLIED_RISK_V1", risk_per_share=risk,
                  available_at=at, record_ids=("m73-supplied-risk",))
    values.update(changes)
    return ExtensionReading(**values)


def minute_close(*, at=TRIGGER, close=100.80, final=True, coverage_known=True, **changes):
    values = dict(record_id="m73-minute-close", bar_end=at, available_at=at, close=close,
                  final=final, coverage_known=coverage_known)
    values.update(changes)
    return MinuteClose(**values)


def heads_up_request(direction="LONG", *, mode=TAPE, at=EARLY, **changes):
    values = dict(
        structure=structure(direction, mode=mode), policy=trigger_policy(mode),
        evaluated_at=at, eligibility=armed(direction, at=at), distance=distance(at=at),
        last_trade=observation("m73-heads-up-trade", at, flip(PRICES["LONG"][0], direction),
                               mode=mode),
    )
    values.update(changes)
    return HeadsUpRequest(**values)


def request(direction="LONG", *, mode=TAPE, at=TRIGGER, crossed_at=CROSS, **changes):
    values = dict(
        structure=structure(direction, mode=mode), policy=trigger_policy(mode),
        evaluated_at=at, crossed_at=crossed_at,
        observations=grid(direction, mode=mode, at=at, prices=SEVEN),
        intensity=intensity() if mode == TAPE else projection(at=at),
        last_trade=observation("m73-last-trade", at, PRICES[direction][2], mode=mode),
        eligibility=armed(direction, at=at), extension=extension(at=at), minute_close=None,
    )
    values.update(changes)
    return TriggerRequest(**values)


def owner(direction="LONG", *, mode=TAPE, **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION, policy=trigger_policy(mode))
    values.update(changes)
    return HodCompRsTriggerMachine(**values)


def state_of(supplied):
    return evaluate_hod_comp_rs_trigger(supplied).state


# --- supplied policy and record contracts -----------------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"mode": "BOTH"}, {"mode": "tape"}, {"buffer_floor": -0.01},
    {"buffer_atr_multiple": float("nan")}, {"buffer_atr_multiple": float("inf")},
    {"buffer_atr_multiple": "0.05"}, {"buffer_atr_multiple": True},
    {"window_open_seconds": 10.0}, {"window_open_seconds": -1}, {"window_close_seconds": 9},
    {"sample_count": 0}, {"min_acceptance_ratio": 0.0}, {"min_acceptance_ratio": 1.01},
    {"min_acceptance_ratio": -0.7}, {"sample_interval_seconds": 0},
    {"sample_interval_seconds": 2}, {"max_structures_per_direction": 0},
    {"max_observation_age_seconds": -3.0}, {"min_trade_intensity": float("nan")},
    {"max_extension_r": -0.4}, {"max_heads_up_distance_atr": "0.35"},
    {"action_cooldown_seconds": -1.0},
))
def test_policy_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        trigger_policy(**changes)


def test_policy_keeps_the_first_sample_window_after_the_crossing():
    assert trigger_policy(sample_count=10, sample_interval_seconds=1).sample_count == 10
    with pytest.raises(RecordError):
        trigger_policy(sample_count=11, window_open_seconds=10)


def test_the_supplied_share_names_its_own_whole_sample_count():
    """The share is the caller's; only its rounding to whole samples lives here."""
    assert trigger_policy().required_accepting_samples == 7
    assert trigger_policy(min_acceptance_ratio=0.65).required_accepting_samples == 7
    assert trigger_policy(min_acceptance_ratio=1.0).required_accepting_samples == 10
    assert trigger_policy(min_acceptance_ratio=0.5).required_accepting_samples == 5


@pytest.mark.parametrize("changes", (
    {"definition_reference": " "}, {"definition_reference": "UNKNOWN"},
    {"value": None}, {"value": None, "missing_reason": " "}, {"value": "0.1"},
    {"value": True}, {"record_ids": ["a"]}, {"record_ids": (" ",)},
    {"at": datetime(2026, 7, 6, 6, 49)},
))
def test_supplied_distance_requires_explicit_facts(changes):
    with pytest.raises(RecordError):
        distance(**changes)


@pytest.mark.parametrize("changes", (
    {"definition_reference": "UNSPECIFIED"}, {"risk": None}, {"risk": None, "missing_reason": ""},
    {"risk": -0.46}, {"risk": "0.46"}, {"record_ids": ("",)},
    {"at": datetime(2026, 7, 6, 6, 50, 10)},
))
def test_supplied_extension_requires_explicit_facts(changes):
    with pytest.raises(RecordError):
        extension(**changes)


def test_a_null_supplied_value_stays_an_explicit_unknown():
    assert distance(value=None, missing_reason="REFERENCE_WINDOW_NOT_COVERED").value is None
    assert extension(risk=None, missing_reason="STRUCTURE_NOT_MEASURED").risk_per_share is None


@pytest.mark.parametrize("changes", (
    {"direction": "FLAT"}, {"mode": "OTHER"}, {"structure_number": 0},
    {"anchor_bar_id": "UNKNOWN"}, {"compression_low": 100.95}, {"compression_high": 0.0},
    {"buffer": 0.0}, {"boundary": 101.03}, {"boundary": 101.00}, {"frozen_atr": -0.4},
    {"reference_extreme": 100.90}, {"input_record_ids": ["a"]}, {"input_record_ids": (" ",)},
    {"frozen_at": datetime(2026, 7, 6, 6, 49)},
))
def test_frozen_structure_requires_a_consistent_buffered_boundary(changes):
    with pytest.raises(RecordError):
        structure(**changes)


def test_a_short_structure_cannot_coil_below_its_frozen_reference_low():
    with pytest.raises(RecordError):
        structure("SHORT", reference_extreme=99.50)
    assert structure("SHORT").boundary == BOUNDARY["SHORT"]


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_frozen_structure_keeps_the_supplied_reference_and_boundary(direction):
    row = structure(direction)
    assert row.boundary == BOUNDARY[direction] and row.buffer == 0.02
    assert row.reference_extreme == REFERENCE[direction]
    assert row.as_dict()["anchor_bar_id"] == "m73-anchor-minute"
    with pytest.raises(FrozenInstanceError):
        row.__setattr__("boundary", 1.0)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_the_supplied_buffer_moves_the_frozen_reference_outward(direction):
    buffer, boundary = structure_boundary(trigger_policy(), direction,
                                          reference_extreme=REFERENCE[direction], latest_atr=ATR)
    assert (buffer, boundary) == (0.02, BOUNDARY[direction])
    # The supplied floor wins whenever the supplied multiple falls below it.
    floor_buffer, _ = structure_boundary(trigger_policy(), direction,
                                         reference_extreme=REFERENCE[direction], latest_atr=0.0)
    assert floor_buffer == 0.01
    frozen = freeze_structure(
        trigger_policy(), direction=direction, frozen_at=EARLY,
        reference_extreme=REFERENCE[direction], compression_high=COMPRESSION[direction][0],
        compression_low=COMPRESSION[direction][1], latest_atr=ATR,
        anchor_bar_id="m73-anchor-minute", structure_number=1)
    assert frozen.boundary == BOUNDARY[direction] and frozen.frozen_atr == ATR


def test_the_boundary_helper_refuses_unsupported_supplied_inputs():
    for changes in ({"policy": "M73"}, {"direction": "FLAT"}, {"reference_extreme": 0.0},
                    {"latest_atr": -0.4}):
        values = dict(policy=trigger_policy(), direction="LONG",
                      reference_extreme=REFERENCE["LONG"], latest_atr=ATR)
        values.update(changes)
        with pytest.raises(RecordError):
            structure_boundary(values.pop("policy"), values.pop("direction"), **values)


@pytest.mark.parametrize("changes", (
    {"structure": None}, {"policy": None}, {"observations": []},
    {"observations": ("m73-sample-0",)}, {"intensity": "TAPE"}, {"last_trade": 101.03},
    {"eligibility": "ARMED"}, {"extension": 0.46}, {"minute_close": 100.8},
))
def test_request_requires_canonical_supplied_parts(changes):
    with pytest.raises(RecordError):
        request(**changes)


def test_request_refuses_a_foreign_arm_or_a_backward_instant():
    with pytest.raises(RecordError):
        request(policy=trigger_policy(QUOTE_PROJECTED))
    with pytest.raises(RecordError):
        request(evaluated_at=CROSS - timedelta(seconds=1))
    with pytest.raises(RecordError):
        request(crossed_at=EARLY - timedelta(seconds=1))
    duplicate = grid(prices=SEVEN) + (observation("m73-sample-0", TRIGGER, 101.03),)
    with pytest.raises(RecordError):
        request(observations=duplicate)


def test_heads_up_request_requires_canonical_supplied_parts():
    for changes in ({"structure": None}, {"policy": None}, {"eligibility": "ARMED"},
                    {"distance": 0.125}, {"last_trade": 101.01},
                    {"evaluated_at": EARLY - timedelta(minutes=5)}):
        with pytest.raises(RecordError):
            heads_up_request(**changes)
    with pytest.raises(RecordError):
        heads_up_request(policy=trigger_policy(QUOTE_PROJECTED))


# --- the supplied crossing test ---------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_two_consecutive_supplied_observations_cross_the_frozen_boundary(direction):
    inside, edge, beyond = (flip(value, direction) for value in PRICES["LONG"])
    previous = observation("m73-cross-previous", CROSS - timedelta(seconds=1), inside)
    current = observation("m73-cross-current", CROSS, beyond)
    result = evaluate_crossing(trigger_policy(), direction, boundary=BOUNDARY[direction],
                               previous=previous, current=current)
    assert result.status == CROSSED and result.reason is None
    assert result.input_record_ids == ("m73-cross-previous", "m73-cross-current")
    # Exactly at the supplied boundary is already beyond it.
    at_edge = evaluate_crossing(trigger_policy(), direction, boundary=BOUNDARY[direction],
                                previous=previous,
                                current=observation("m73-cross-edge", CROSS, edge))
    assert at_edge.status == CROSSED


@pytest.mark.parametrize("changes,reason", (
    ({"previous": None}, "NO_PRECEDING_OBSERVATION"),
    ({"previous_price": 101.03}, "NO_FRESH_CROSSING"),
    ({"previous_age": 4.0}, "PRECEDING_STALE_SAMPLE"),
    ({"current_age": 4.0}, "CURRENT_STALE_SAMPLE"),
    ({"gap": 2}, "OBSERVATION_GAP"),
    ({"previous_mode": QUOTE_PROJECTED}, "PRECEDING_WRONG_ARM"),
    ({"current_coverage": False}, "CURRENT_SAMPLE_COVERAGE_UNKNOWN"),
    ({"current_price": None}, "CURRENT_NO_ELIGIBLE_TRADE"),
))
def test_a_crossing_needs_two_fresh_consecutive_covered_observations(changes, reason):
    gap = changes.get("gap", 1)
    previous = observation("m73-cross-previous", CROSS - timedelta(seconds=gap),
                           changes.get("previous_price", 101.01),
                           mode=changes.get("previous_mode", TAPE),
                           age=changes.get("previous_age", 1.0))
    current = observation("m73-cross-current", CROSS, changes.get("current_price", 101.03),
                          age=changes.get("current_age", 1.0),
                          coverage_known=changes.get("current_coverage", True),
                          missing_reason="NO_ELIGIBLE_TRADE"
                          if changes.get("current_price", 101.03) is None else None)
    result = evaluate_crossing(trigger_policy(), "LONG", boundary=BOUNDARY["LONG"],
                               previous=None if "previous" in changes else previous,
                               current=current)
    assert (result.status, result.reason) == (
        "UNKNOWN" if reason != "NO_FRESH_CROSSING" else NOT_CROSSED, reason)


def test_a_boundary_that_fell_onto_already_beyond_prices_is_not_a_crossing():
    """Both supplied prices already sit beyond the boundary, so nothing crossed."""
    previous = observation("m73-cross-previous", CROSS - timedelta(seconds=1), 101.05)
    current = observation("m73-cross-current", CROSS, 101.06)
    result = evaluate_crossing(trigger_policy(), "LONG", boundary=BOUNDARY["LONG"],
                               previous=previous, current=current)
    assert (result.status, result.reason) == (NOT_CROSSED, "NO_FRESH_CROSSING")


def test_the_crossing_helper_refuses_unsupported_supplied_inputs():
    current = observation("m73-cross-current", CROSS, 101.03)
    with pytest.raises(RecordError):
        evaluate_crossing("M73", "LONG", boundary=BOUNDARY["LONG"], previous=None, current=current)
    with pytest.raises(RecordError):
        evaluate_crossing(trigger_policy(), "FLAT", boundary=BOUNDARY["LONG"], previous=None,
                          current=current)
    with pytest.raises(RecordError):
        evaluate_crossing(trigger_policy(), "LONG", boundary=0.0, previous=None, current=current)
    with pytest.raises(RecordError):
        evaluate_crossing(trigger_policy(), "LONG", boundary=BOUNDARY["LONG"], previous=None,
                          current="101.03")
    with pytest.raises(RecordError):
        evaluate_crossing(trigger_policy(), "LONG", boundary=BOUNDARY["LONG"],
                          previous="101.01", current=current)


# --- the supplied heads-up notice -------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_an_approaching_supplied_structure_reports_one_heads_up(direction):
    result = evaluate_hod_comp_rs_heads_up(heads_up_request(direction))
    assert result.state == StrategyState("ARMED", HEADS_UP) and result.reasons == ()
    assert all(result.gate(name).status == "PASS" for name in HEADS_UP_GATES)
    assert result.gate("HEADS_UP_DISTANCE").observed == DISTANCE
    assert result.as_dict()["trigger_version"] == TRIGGER_VERSION
    assert result.structure.structure_number == 1


def heads_up_part(name):
    """One supplied heads-up part, replaced by its named refusal fixture."""
    return {
        "no_distance": {"distance": None},
        "far_distance": {"distance": distance(value=0.36)},
        "beyond_reference": {"distance": distance(value=-0.01)},
        "unmeasured_distance": {"distance": distance(
            value=None, missing_reason="REFERENCE_WINDOW_NOT_COVERED")},
        "late_distance": {"distance": distance(at=EARLY + timedelta(seconds=1))},
        "no_trade": {"last_trade": None},
        "beyond_boundary": {"last_trade": observation("m73-heads-up-trade", EARLY, 101.03)},
        "stale_trade": {"last_trade": observation("m73-heads-up-trade", EARLY, 101.01,
                                                  age=4.0)},
        "no_eligibility": {"eligibility": None},
        "old_eligibility": {"eligibility": armed(at=CROSS)},
        "halted": {"eligibility": armed(at=EARLY,
                                        status=status(halted=True, available_at=EARLY))},
    }[name]


@pytest.mark.parametrize("name,gate,reason", (
    ("no_distance", "HEADS_UP_DISTANCE", "DISTANCE_UNAVAILABLE"),
    ("far_distance", "HEADS_UP_DISTANCE", "DISTANCE_ABOVE_LIMIT"),
    ("beyond_reference", "HEADS_UP_DISTANCE", "DISTANCE_BEYOND_REFERENCE"),
    ("unmeasured_distance", "HEADS_UP_DISTANCE", "REFERENCE_WINDOW_NOT_COVERED"),
    ("late_distance", "HEADS_UP_DISTANCE", "DISTANCE_NOT_AVAILABLE"),
    ("no_trade", "HEADS_UP_BEFORE_BOUNDARY", "LAST_TRADE_UNAVAILABLE"),
    ("beyond_boundary", "HEADS_UP_BEFORE_BOUNDARY", "ALREADY_BEYOND_BOUNDARY"),
    ("stale_trade", "HEADS_UP_BEFORE_BOUNDARY", "LAST_TRADE_STALE_SAMPLE"),
    ("no_eligibility", ELIGIBILITY_GATE, "ELIGIBILITY_UNAVAILABLE"),
    ("old_eligibility", ELIGIBILITY_GATE, "ELIGIBILITY_NOT_CURRENT"),
    ("halted", ELIGIBILITY_GATE, "ELIGIBILITY_FAILED_MANDATORY_STATUS"),
))
def test_every_named_heads_up_refusal_keeps_the_notice_unreported(name, gate, reason):
    result = evaluate_hod_comp_rs_heads_up(heads_up_request(**heads_up_part(name)))
    assert result.state == StrategyState("ARMED")
    assert result.gate(gate).reason == reason
    assert result.reasons and result.reasons[0].endswith(reason)


def test_the_heads_up_evaluation_refuses_an_unsupported_request():
    with pytest.raises(RecordError):
        evaluate_hod_comp_rs_heads_up("M73")


# --- the supplied actionable path -------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("mode", MODES)
def test_the_supplied_gates_report_one_actionable_trigger(direction, mode):
    result = evaluate_hod_comp_rs_trigger(request(direction, mode=mode))
    assert result.state == StrategyState("ALERT_TRIGGERED") and result.reasons == ()
    assert all(result.gate(name).status == "PASS" for name in TRIGGER_GATES)
    assert result.accepting_samples == 7
    assert result.gate("ACCEPTANCE_WINDOW").observed == 0.7
    assert result.elapsed_seconds == 10.0 and result.reset_satisfied is False
    assert result.gate("EXTENSION_NOT_STALE").observed == pytest.approx(0.01 / RISK)
    assert len(result.samples) == 10


def test_the_supplied_acceptance_share_decides_nothing_below_itself():
    assert state_of(request()) == StrategyState("ALERT_TRIGGERED")
    six = request(observations=grid(prices=SIX))
    result = evaluate_hod_comp_rs_trigger(six)
    assert result.accepting_samples == 6
    assert result.gate("ACCEPTANCE_WINDOW").status == "FAIL"
    assert result.gate("ACCEPTANCE_WINDOW").reason == "ACCEPTANCE_BELOW_MINIMUM"
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")
    # The same six samples pass a caller who supplies a smaller share.
    smaller = TriggerRequest(
        structure=structure(), policy=trigger_policy(min_acceptance_ratio=0.6),
        evaluated_at=TRIGGER, crossed_at=CROSS, observations=grid(prices=SIX),
        intensity=intensity(), last_trade=observation("m73-last-trade", TRIGGER, 101.03),
        eligibility=armed(), extension=extension(), minute_close=None)
    assert state_of(smaller) == StrategyState("ALERT_TRIGGERED")


@pytest.mark.parametrize("changes,reason", (
    ({"missing": True}, "SAMPLE_MISSING"),
    ({"ambiguous": True}, "AMBIGUOUS_SAMPLE"),
    ({"age": 4.0}, "STALE_SAMPLE"),
    ({"coverage_known": False}, "SAMPLE_COVERAGE_UNKNOWN"),
    ({"price": None}, "NO_ELIGIBLE_SAMPLE_TRADE"),
    ({"available_late": True}, "SAMPLE_NOT_AVAILABLE"),
    ({"mode": QUOTE_PROJECTED}, "SAMPLE_MISSING"),
))
def test_one_unknown_supplied_sample_keeps_the_whole_window_unknown(changes, reason):
    rows = list(grid(prices=SEVEN))
    if changes.get("missing"):
        rows = rows[1:]
    elif changes.get("ambiguous"):
        rows.append(observation("m73-sample-twin", rows[0].observed_at, 101.03))
    elif changes.get("available_late"):
        rows[0] = observation(rows[0].record_id, rows[0].observed_at, rows[0].price,
                              available_at=TRIGGER + timedelta(seconds=1))
    elif changes.get("price", "keep") is None:
        rows[0] = observation(rows[0].record_id, rows[0].observed_at, None,
                              missing_reason="NO_ELIGIBLE_SAMPLE_TRADE")
    else:
        rows[0] = observation(rows[0].record_id, rows[0].observed_at, rows[0].price,
                              mode=changes.get("mode", TAPE), age=changes.get("age", 1.0),
                              coverage_known=changes.get("coverage_known", True))
    result = evaluate_hod_comp_rs_trigger(request(observations=tuple(rows)))
    gate = result.gate("ACCEPTANCE_WINDOW")
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.accepting_samples is None
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("changes,reason", (
    ({"intensity": None}, "INTENSITY_UNAVAILABLE"),
    ({"ratio": 1.39}, "INTENSITY_BELOW_MINIMUM"),
    ({"ratio": None}, "NO_INTENSITY_COVERAGE"),
    ({"coverage_complete": False}, "INTENSITY_COVERAGE_INCOMPLETE"),
    ({"arm": True}, "INTENSITY_ARM_MISMATCH"),
))
def test_the_supplied_tape_arm_consumes_only_its_own_evidence(changes, reason):
    if changes.get("arm"):
        supplied = projection()
    elif "intensity" in changes:
        supplied = None
    elif changes.get("ratio", 1.4) is None:
        supplied = intensity(ratio=None, missing_reason="NO_INTENSITY_COVERAGE")
    else:
        supplied = intensity(**changes)
    result = evaluate_hod_comp_rs_trigger(request(intensity=supplied))
    gate = result.gate("TRADE_INTENSITY")
    assert gate.reason == reason and gate.status != "PASS"
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("changes,status_expected,reason", (
    ({"volume": 4600.0}, "FAIL", "INTENSITY_BELOW_MINIMUM"),
    ({"elapsed": 9.0}, "FAIL", "PROJECTION_ELAPSED_BELOW_MINIMUM"),
    ({"reference": 0.0}, "UNKNOWN", "PROJECTION_REFERENCE_UNAVAILABLE"),
    ({"minute_start": TRIGGER + timedelta(seconds=1)}, "UNKNOWN", "PROJECTION_MINUTE_MISMATCH"),
    ({"minute_volume": None}, "UNKNOWN", "NO_PROJECTION_COVERAGE"),
))
def test_the_supplied_projection_arm_keeps_its_own_current_minute(changes, status_expected, reason):
    values = dict(at=TRIGGER)
    if "minute_volume" in changes:
        values.update(minute_volume=None, missing_reason="NO_PROJECTION_COVERAGE")
    else:
        # A shorter elapsed count keeps the supplied minute start consistent with it.
        values.update(changes)
    result = evaluate_hod_comp_rs_trigger(
        request(mode=QUOTE_PROJECTED, intensity=projection(**values)))
    gate = result.gate("TRADE_INTENSITY")
    assert (gate.status, gate.reason) == (status_expected, reason)
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("changes,reason", (
    ({"last_trade": None}, "LAST_TRADE_UNAVAILABLE"),
    ({"price": 101.01}, "LAST_TRADE_INSIDE_BOUNDARY"),
    ({"age": 4.0}, "LAST_TRADE_STALE_SAMPLE"),
    ({"mode": QUOTE_PROJECTED}, "LAST_TRADE_WRONG_ARM"),
    ({"price": None}, "LAST_TRADE_NO_ELIGIBLE_TRADE"),
))
def test_the_supplied_last_trade_must_still_stand_beyond_the_boundary(changes, reason):
    if "last_trade" in changes:
        supplied = None
    else:
        supplied = observation("m73-last-trade", TRIGGER, changes.get("price", 101.03),
                               mode=changes.get("mode", TAPE), age=changes.get("age", 1.0),
                               missing_reason="NO_ELIGIBLE_TRADE"
                               if changes.get("price", 101.03) is None else None)
    result = evaluate_hod_comp_rs_trigger(request(last_trade=supplied))
    assert result.gate("LAST_TRADE_BEYOND_BOUNDARY").reason == reason
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_supplied_move_already_extended_past_its_limit_is_stale(direction):
    """The supplied R and the frozen boundary decide; this module adopts neither."""
    far = flip(101.25, direction)
    result = evaluate_hod_comp_rs_trigger(request(
        direction, last_trade=observation("m73-last-trade", TRIGGER, far)))
    gate = result.gate("EXTENSION_NOT_STALE")
    assert (gate.status, gate.reason) == ("FAIL", "EXTENSION_ABOVE_LIMIT")
    assert gate.observed == pytest.approx(0.23 / RISK) and gate.threshold == 0.40
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")
    # Exactly at the supplied limit still passes.
    edge = flip(float(Decimal("101.02") + Decimal("0.40") * Decimal(str(RISK))), direction)
    passing = evaluate_hod_comp_rs_trigger(request(
        direction, last_trade=observation("m73-last-trade", TRIGGER, edge)))
    assert passing.gate("EXTENSION_NOT_STALE").status == "PASS"


@pytest.mark.parametrize("changes,reason", (
    ({"extension": None}, "EXTENSION_UNAVAILABLE"),
    ({"risk": None}, "STRUCTURE_RISK_UNAVAILABLE"),
    ({"risk": 0.0}, "NONPOSITIVE_RISK_PER_SHARE"),
    ({"available": TRIGGER + timedelta(seconds=1)}, "EXTENSION_NOT_AVAILABLE"),
    ({"no_trade": True}, "LAST_TRADE_UNAVAILABLE"),
    ({"stale_trade": True}, "LAST_TRADE_STALE_SAMPLE"),
))
def test_an_unknown_extension_input_never_becomes_a_passing_gate(changes, reason):
    values = {}
    if "extension" in changes:
        values["extension"] = None
    elif changes.get("risk", RISK) is None:
        values["extension"] = extension(risk=None, missing_reason="STRUCTURE_RISK_UNAVAILABLE")
    elif "risk" in changes:
        values["extension"] = extension(risk=changes["risk"])
    elif "available" in changes:
        values["extension"] = extension(at=changes["available"])
    if changes.get("no_trade"):
        values["last_trade"] = None
    if changes.get("stale_trade"):
        values["last_trade"] = observation("m73-last-trade", TRIGGER, 101.03, age=4.0)
    result = evaluate_hod_comp_rs_trigger(request(**values))
    gate = result.gate("EXTENSION_NOT_STALE")
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


@pytest.mark.parametrize("changes,reason", (
    ({"eligibility": None}, "ELIGIBILITY_UNAVAILABLE"),
    ({"at": CROSS}, "ELIGIBILITY_NOT_CURRENT"),
))
def test_an_unknown_mandatory_eligibility_invalidates_the_structure(changes, reason):
    supplied = None if "eligibility" in changes else armed(at=changes["at"])
    result = evaluate_hod_comp_rs_trigger(request(eligibility=supplied))
    assert result.gate(ELIGIBILITY_GATE).reason == reason
    assert result.gate(STRUCTURE_GATE).reason == "UNKNOWN_MANDATORY_INPUT"
    assert result.state == StrategyState("INVALIDATED")


def test_a_failing_eligibility_gate_keeps_the_structure_below_the_trigger():
    """A known failure is not an unknown input, so the structure stays open."""
    failing = armed(status=status(macro_blackout_active=True, available_at=TRIGGER))
    result = evaluate_hod_comp_rs_trigger(request(eligibility=failing))
    assert result.gate(ELIGIBILITY_GATE).status == "FAIL"
    assert result.gate(ELIGIBILITY_GATE).reason == "ELIGIBILITY_FAILED_MANDATORY_STATUS"
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_a_supplied_halt_invalidates_the_structure():
    halted = armed(status=status(halted=True, available_at=TRIGGER))
    result = evaluate_hod_comp_rs_trigger(request(eligibility=halted))
    assert result.gate(STRUCTURE_GATE).reason == "MANDATORY_HALT"
    assert result.state == StrategyState("INVALIDATED")
    assert "MANDATORY_HALT" in INVALIDATIONS


@pytest.mark.parametrize("changes,reason,reset,state", (
    ({"close": 100.80}, "COMPRESSION_CLOSE_INVALIDATION", True, "INVALIDATED"),
    ({"close": 100.60}, "STRUCTURE_BROKEN_CLOSE", False, "INVALIDATED"),
    ({"close": 100.50}, "STRUCTURE_BROKEN_CLOSE", False, "INVALIDATED"),
    ({"coverage_known": False, "close": None, "final": False}, "COVERAGE_LOST", False,
     "INVALIDATED"),
))
def test_a_supplied_final_close_can_end_this_structure(changes, reason, reset, state):
    result = evaluate_hod_comp_rs_trigger(request(minute_close=minute_close(**changes)))
    assert result.gate(STRUCTURE_GATE).reason == reason
    assert result.reset_satisfied is reset
    assert result.state == StrategyState(state) and reason in INVALIDATIONS


def test_a_pending_minute_close_holds_the_supplied_deadline_unchanged():
    pending = minute_close(close=None, final=False)
    result = evaluate_hod_comp_rs_trigger(request(minute_close=pending))
    gate = result.gate(STRUCTURE_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "MINUTE_BAR_PENDING")
    assert gate.observed == 10.0 and gate.threshold == 30.0
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_lost_arm_coverage_after_the_crossing_invalidates_the_structure():
    rows = list(grid(prices=SEVEN))
    rows[-1] = observation(rows[-1].record_id, rows[-1].observed_at, rows[-1].price,
                           coverage_known=False)
    result = evaluate_hod_comp_rs_trigger(request(observations=tuple(rows)))
    assert result.gate(STRUCTURE_GATE).reason == "COVERAGE_LOST"
    assert result.state == StrategyState("INVALIDATED")


@pytest.mark.parametrize("at,reason,state", (
    (CROSS + timedelta(seconds=5), "BEFORE_ACCEPTANCE_WINDOW", "ARMED"),
    (CROSS + timedelta(seconds=31), "ACCEPTANCE_DEADLINE_PASSED", "ARMED"),
))
def test_the_supplied_acceptance_window_bounds_every_evaluation(at, reason, state):
    result = evaluate_hod_comp_rs_trigger(request(
        at=at, observations=grid(at=at, prices=SEVEN),
        last_trade=observation("m73-last-trade", at, 101.03),
        eligibility=armed(at=at), extension=extension(at=at)))
    assert result.gate(STRUCTURE_GATE).reason == reason
    expected = StrategyState("ARMED", "WAITING_FOR_RESET") if reason.startswith(
        "ACCEPTANCE_DEADLINE") else StrategyState("ARMED", "CROSSING_OBSERVED")
    assert result.state == expected and result.state.state == state


def test_an_off_grid_evaluation_stays_unknown():
    at = CROSS + timedelta(seconds=10, microseconds=500000)
    result = evaluate_hod_comp_rs_trigger(request(
        at=at, observations=grid(at=at, prices=SEVEN),
        last_trade=observation("m73-last-trade", at, 101.03),
        eligibility=armed(at=at), extension=extension(at=at)))
    gate = result.gate(STRUCTURE_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "EVALUATION_OFF_GRID")
    assert result.state == StrategyState("ARMED", "CROSSING_OBSERVED")


def test_the_trigger_evaluation_refuses_an_unsupported_request():
    with pytest.raises(RecordError):
        evaluate_hod_comp_rs_trigger("M73")


# --- the supplied structure owner -------------------------------------------


def test_the_owner_reserves_one_number_and_opens_one_structure():
    subject = owner()
    assert subject.pending_structure_number == 1
    assert subject.reserve_structure(EARLY) == 1
    with pytest.raises(RecordError):
        subject.reserve_structure(EARLY)
    assert subject.structure_quota(CROSS).status == "PASS"
    frozen = structure()
    opening = subject.open_crossing(frozen, crossed_at=CROSS, record_id="m73-open")
    assert opening[0].to_substate == "CROSSING_OBSERVED"
    assert subject.started_structure_count == 0
    assert subject.confirm(opening[0]) == StrategyState("ARMED", "CROSSING_OBSERVED")
    assert subject.started_structure_count == 1 and subject.current_structure() == frozen
    assert subject.pending_structure_number == 2
    assert subject.structure_quota(CROSS).reason == "RESET_REQUIRED"


def test_the_owner_reports_a_heads_up_before_any_crossing():
    subject = owner()
    subject.reserve_structure(EARLY)
    assessment, changes = subject.propose_heads_up(heads_up_request(),
                                                   record_id="m73-heads-up")
    assert assessment.state == StrategyState("ARMED", HEADS_UP) and len(changes) == 1
    assert changes[0].to_substate == HEADS_UP and changes[0].metadata.data_mode == DATA_MODE
    assert subject.confirm(changes[0]) == StrategyState("ARMED", HEADS_UP)
    # A heads-up consumes no quota of its own.
    assert subject.started_structure_count == 0
    assert subject.structure_quota(CROSS).status == "PASS"
    repeated = subject.propose_heads_up(heads_up_request(at=EARLY + timedelta(seconds=1)),
                                        record_id="m73-heads-up-again")
    assert repeated[1] == ()


def test_a_lapsed_heads_up_returns_the_owner_to_armed():
    subject = owner()
    subject.reserve_structure(EARLY)
    _, changes = subject.propose_heads_up(heads_up_request(), record_id="m73-heads-up")
    subject.confirm(changes[0])
    later = EARLY + timedelta(seconds=30)
    lapsed = heads_up_request(at=later, distance=distance(at=later, value=0.36))
    assessment, back = subject.propose_heads_up(lapsed, record_id="m73-heads-up-lapsed")
    assert assessment.state == StrategyState("ARMED")
    assert back[0].from_substate == HEADS_UP and back[0].to_substate is None
    assert subject.confirm(back[0]) == StrategyState("ARMED")


def test_the_owner_refuses_a_heads_up_it_does_not_own():
    subject = owner()
    with pytest.raises(RecordError):
        subject.propose_heads_up(heads_up_request("SHORT"), record_id="m73-foreign")
    with pytest.raises(RecordError):
        subject.propose_heads_up(heads_up_request(structure=structure(structure_number=2)),
                                 record_id="m73-wrong-number")
    with pytest.raises(RecordError):
        subject.propose_heads_up(heads_up_request(policy=trigger_policy(
            min_trade_intensity=2.0)), record_id="m73-other-policy")
    with pytest.raises(RecordError):
        subject.propose_heads_up("M73", record_id="m73-not-a-request")


def test_the_owner_refuses_a_crossing_it_does_not_own():
    subject = owner()
    with pytest.raises(RecordError):
        subject.open_crossing(structure("SHORT"), crossed_at=CROSS, record_id="m73-foreign")
    with pytest.raises(RecordError):
        subject.open_crossing(structure(structure_number=3), crossed_at=CROSS,
                              record_id="m73-wrong-number")
    with pytest.raises(RecordError):
        subject.open_crossing(structure(), crossed_at=EARLY - timedelta(seconds=1),
                              record_id="m73-backward")
    with pytest.raises(RecordError):
        subject.open_crossing("M73", crossed_at=CROSS, record_id="m73-not-a-structure")


def test_the_supplied_session_quota_limits_the_structures_per_direction():
    subject = owner(policy=trigger_policy(max_structures_per_direction=1))
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    subject.confirm(opening[0])
    closing = subject.reset(minute_close(at=TRIGGER, close=100.80), at=TRIGGER,
                            record_id="m73-reset")
    assert closing[0].reason == "INSIDE_COMPRESSION_RESET"
    assert subject.confirm(closing[0]) == StrategyState("ARMED")
    quota = subject.structure_quota(TRIGGER + timedelta(minutes=1))
    assert (quota.name, quota.status, quota.reason) == (QUOTA_GATE, "FAIL",
                                                        "STRUCTURE_QUOTA_EXHAUSTED")
    with pytest.raises(RecordError):
        subject.open_crossing(structure(structure_number=2),
                              crossed_at=TRIGGER + timedelta(minutes=1), record_id="m73-second")


def test_the_supplied_cooldown_holds_the_next_structure_back():
    subject = owner()
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    subject.confirm(opening[0])
    assessment, changes = subject.propose(request(), record_id="m73-trigger")
    assert assessment.state == StrategyState("ALERT_TRIGGERED")
    subject.confirm(changes[0])
    reset = subject.reset(minute_close(at=TRIGGER + timedelta(minutes=1), close=100.80),
                          at=TRIGGER + timedelta(minutes=1), record_id="m73-reset")
    subject.confirm(reset[0])
    held = subject.structure_quota(TRIGGER + timedelta(minutes=1))
    assert held.reason == "COOLDOWN_NOT_ELAPSED"
    assert subject.structure_quota(TRIGGER + timedelta(seconds=600)).status == "PASS"


def test_the_owner_refuses_an_unrecorded_or_mismatched_advance():
    subject = owner()
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    subject.confirm(opening[0])
    with pytest.raises(RecordError):
        subject.confirm(opening[0])
    with pytest.raises(RecordError):
        subject.propose(request(structure=structure(structure_number=2)),
                        record_id="m73-other-structure")
    with pytest.raises(RecordError):
        subject.propose(request(policy=trigger_policy(max_extension_r=1.0)),
                        record_id="m73-other-policy")
    with pytest.raises(RecordError):
        subject.propose("M73", record_id="m73-not-a-request")


def test_the_owner_refuses_an_evaluation_that_moves_backward():
    subject = owner()
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    subject.confirm(opening[0])
    _, changes = subject.propose(request(), record_id="m73-trigger")
    subject.confirm(changes[0])
    earlier = CROSS + timedelta(seconds=9)
    with pytest.raises(RecordError):
        subject.propose(request(at=earlier, observations=grid(at=earlier, prices=SEVEN)),
                        record_id="m73-backward")


def test_the_owner_requires_a_frozen_structure_before_evaluating_or_resetting():
    subject = owner()
    with pytest.raises(RecordError):
        subject.propose(request(), record_id="m73-no-structure")
    with pytest.raises(RecordError):
        subject.reset(minute_close(), at=TRIGGER, record_id="m73-no-structure")
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    subject.confirm(opening[0])
    with pytest.raises(RecordError):
        subject.reset(minute_close(close=100.50), at=TRIGGER, record_id="m73-outside")
    with pytest.raises(RecordError):
        subject.reset(minute_close(final=False, close=None), at=TRIGGER, record_id="m73-pending")
    with pytest.raises(RecordError):
        subject.reset("M73", at=TRIGGER, record_id="m73-not-a-close")


def test_the_owner_can_expire_a_pending_structure():
    subject = owner()
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    subject.confirm(opening[0])
    changes = subject.expire(at=TRIGGER, reason="EVALUATION_WINDOW_CLOSED",
                             record_id="m73-expire")
    assert changes[0].to_state == "EXPIRED"
    assert subject.confirm(changes[0]) == StrategyState("EXPIRED")
    assert subject.current_structure() is None
    with pytest.raises(RecordError):
        owner().expire(at=TRIGGER, reason=" ", record_id="m73-expire")


def test_a_restored_owner_regains_no_structure_of_its_own():
    subject = owner()
    restored = subject.restore(StrategyState("ARMED", "CROSSING_OBSERVED"),
                               structure=structure(), started_structure_count=2,
                               reset_satisfied=False, last_action_at=TRIGGER)
    assert restored == StrategyState("ARMED", "CROSSING_OBSERVED")
    assert subject.started_structure_count == 2
    assert subject.structure_quota(TRIGGER).reason == "STRUCTURE_QUOTA_EXHAUSTED"
    for changes in ({"state": StrategyState("WATCHING")},
                    {"state": StrategyState("ARMED", "OTHER")},
                    {"structure": "M73"}, {"reset_satisfied": 1},
                    {"started_structure_count": -1}):
        values = dict(state=StrategyState("ARMED"))
        values.update(changes)
        with pytest.raises(RecordError):
            owner().restore(values.pop("state"), **values)
    used = owner()
    used.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    with pytest.raises(RecordError):
        used.restore(StrategyState("ARMED"))


@pytest.mark.parametrize("changes", (
    {"symbol": " "}, {"instrument_type": "FUTURE"}, {"direction": "FLAT"},
    {"strategy_version": "UNKNOWN"}, {"policy": None}, {"session": None},
))
def test_the_owner_requires_supported_identity(changes):
    with pytest.raises(RecordError):
        owner(**changes)


def test_the_rules_cover_exactly_the_m73_states():
    rules = trigger_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("ARMED")
    states = {row.state for pair in rules.allowed for row in pair}
    assert states == set(STATES)
    substates = {row.substate for pair in rules.allowed for row in pair}
    assert substates == {None, HEADS_UP, "CROSSING_OBSERVED", "WAITING_FOR_RESET"}
    assert (StrategyState("ARMED"), StrategyState("ARMED", HEADS_UP)) in rules.allowed
    assert (StrategyState("ALERT_TRIGGERED"), StrategyState("ARMED")) not in rules.allowed


# --- immutability, stability and adopted numbers -----------------------------


def test_assessments_and_gates_are_immutable_and_stable():
    result = evaluate_hod_comp_rs_trigger(request())
    with pytest.raises(FrozenInstanceError):
        result.gates[0].__setattr__("status", "FAIL")
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("state", StrategyState("INVALIDATED"))
    assert result.to_json() == evaluate_hod_comp_rs_trigger(request()).to_json()
    payload = json.loads(result.to_json())
    assert payload["trigger_version"] == TRIGGER_VERSION and payload["mode"] == TAPE
    assert payload["crossed_at"] == "2026-07-06T13:50:00Z"
    notice = evaluate_hod_comp_rs_heads_up(heads_up_request())
    assert notice.to_json() == evaluate_hod_comp_rs_heads_up(heads_up_request()).to_json()


@pytest.mark.parametrize("changes", (
    {"name": "NOT_A_GATE"}, {"status": "MAYBE"}, {"status": "FAIL", "reason": None},
    {"reason": "UNKNOWN"}, {"input_record_ids": ["a"]}, {"input_record_ids": (" ",)},
))
def test_gate_results_require_supported_facts(changes):
    values = dict(name=STRUCTURE_GATE, status="FAIL", observed=1.0, threshold=30.0,
                  reason="BEFORE_ACCEPTANCE_WINDOW", input_record_ids=())
    values.update(changes)
    with pytest.raises(TriggerGate and RecordError):
        TriggerGate(**values)


def test_every_reported_gate_name_is_a_supported_one():
    result = evaluate_hod_comp_rs_trigger(request())
    assert tuple(row.name for row in result.gates) == TRIGGER_GATES
    notice = evaluate_hod_comp_rs_heads_up(heads_up_request())
    assert tuple(row.name for row in notice.gates) == HEADS_UP_GATES
    assert set(TRIGGER_GATES) | set(HEADS_UP_GATES) | {QUOTA_GATE} == set(GATE_NAMES)


def test_the_module_adopts_no_rule_number_of_its_own():
    source = inspect.getsource(hod_comp_rs_trigger)
    for token in ("0.60", "0.35", "0.70", "1.40", "0.40", "0.04", "0.20", "0.05", "0.01",
                  "rs_15m"):
        assert token not in source
    assert isinstance(evaluate_hod_comp_rs_trigger(request()), TriggerAssessment)


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           trigger_rules())


async def test_a_refused_recording_leaves_the_owner_where_it_was():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = owner()
    context, _ = eligibility(at=CROSS)
    opening = subject.open_crossing(structure(), crossed_at=CROSS, record_id="m73-open")
    engine = StateTransitionEngine(scope("LONG"), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(opening[0], context=context)
    assert engine.current_state() == StrategyState("ARMED")
    assert subject.current_state() == StrategyState("ARMED")
    assert subject.started_structure_count == 0 and subject.current_structure() is None


async def test_the_supplied_heads_up_and_trigger_through_the_m42_engine_and_m51_store():
    proofs = []
    connection = await db.init_db()
    for direction in ("LONG", "SHORT"):
        frozen = freeze_structure(
            trigger_policy(), direction=direction, frozen_at=EARLY,
            reference_extreme=REFERENCE[direction], compression_high=COMPRESSION[direction][0],
            compression_low=COMPRESSION[direction][1], latest_atr=ATR,
            anchor_bar_id="m73-anchor-minute", structure_number=1,
            input_record_ids=("m73-compression-window", "m73-reference-freeze"))
        subject = owner(direction)
        subject.reserve_structure(EARLY)
        engine = StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection))
        store = ResearchEventStore(connection)

        early_context, _ = eligibility(direction, at=EARLY)
        notice, approach = subject.propose_heads_up(
            heads_up_request(direction, structure=frozen), record_id="m73-heads-up-" + direction)
        assert notice.state == StrategyState("ARMED", HEADS_UP) and notice.reasons == ()
        await engine.apply(approach[0], context=early_context)
        assert subject.confirm(approach[0]) == StrategyState("ARMED", HEADS_UP)

        crossing_context, _ = eligibility(direction, at=CROSS)
        opening = subject.open_crossing(frozen, crossed_at=CROSS,
                                        record_id="m73-open-" + direction)
        first = await engine.apply(opening[0], context=crossing_context)
        assert subject.confirm(opening[0]) == StrategyState("ARMED", "CROSSING_OBSERVED")

        context, standing = eligibility(direction, at=TRIGGER)
        evaluation = request(direction, structure=frozen, eligibility=standing)
        assessment, changes = subject.propose(evaluation, record_id="m73-trigger-" + direction)
        assert assessment.state == StrategyState("ALERT_TRIGGERED") and assessment.reasons == ()
        entry = await engine.apply(changes[0], context=context)
        assert engine.current_state() == StrategyState("ALERT_TRIGGERED")
        assert subject.confirm(changes[0]) == StrategyState("ALERT_TRIGGERED")
        assert changes[0].metadata.data_mode == DATA_MODE
        assert changes[0].strategy_id == STRATEGY_ID

        stored = await store.append(changes[0], session=DAY, recorded_at=TRIGGER)
        assert stored["kind"] == "STATE_TRANSITION"
        assert await store.append(changes[0], session=DAY, recorded_at=TRIGGER) == stored

        repeated = evaluate_hod_comp_rs_trigger(evaluation)
        assert repeated.to_json() == assessment.to_json()
        proofs.append({
            "synthetic_only": True, "direction": direction,
            "boundary": frozen.boundary, "buffer": frozen.buffer,
            "structure": frozen.as_dict(), "heads_up": notice.as_dict(),
            "assessment": assessment.as_dict(),
            "heads_up_transition": approach[0].as_dict(),
            "opening_transition": opening[0].as_dict(), "transition": changes[0].as_dict(),
            "opening_position": first.position, "stored_position": entry.position,
            "stored_fingerprint": stored["fingerprint"],
            "sample_sha256": hashlib.sha256("".join(
                json.dumps(row.as_dict(), sort_keys=True)
                for row in assessment.samples).encode()).hexdigest(),
            "repeated_assessment_identical": True,
        })
    await db.close_db()
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "trigger_version": TRIGGER_VERSION, "runs": proofs}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m7_3_hod_comp_rs_trigger_proof.json").write_text(rendered)
