"""M8.4 supplied-input `FIRST_PULLBACK_VWAP` contracts; no approved rule is adopted.

Every number below is a synthetic fixture supplied by the caller. A passing gate
proves the offline contract only: it establishes no bar, tape or quote coverage,
no adopted `FIRST_PULLBACK_VWAP` rule, no impulse or pullback definition, no
retracement band, no confidence cutoff, no alert and no permission to act.
ALERT_TRIGGERED here means the supplied inputs passed every gate at one instant in
a test process.

The impulse and pullback measurement is the real M8.3 snapshot over supplied
minute bars, the confidence is the real M4.4 composition, and the recorded
transitions go through the real M4.2 engine and M5.1 store.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db, first_pullback_vwap
from consensus_engine.confidence import (
    COMPONENTS, ConfidencePolicy, ConfidenceRequest, ConfidenceTerm, compose_confidence,
)
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.first_pullback_vwap import (
    CONFIDENCE_GATE, DATA_MODE, FirstPullbackVwapMachine, IMPULSE_GATE, IMPULSE_VWAP_GATE,
    INVALIDATIONS, MEASUREMENT_GATE, PULLBACK_FORMING, PULLBACK_GATES, PULLBACK_VERSION,
    PullbackAssessment, PullbackGate, PullbackRequest, PullbackStructural, PullbackVwapPolicy,
    RETRACEMENT_GATE, RISK_GATE, RS_GATE, RULES_VERSION, RelativeStrength, SEQUENCE_GATE,
    SPREAD_GATE, STRATEGY_ID, SUPPORT_GATE, TRIGGER_GATE, UNDEFINED, VOLUME_GATE,
    VWAP_CROSS_GATE, VWAP_SIDE_GATE, VWAP_SLOPE_GATE, VwapContext,
    evaluate_first_pullback_vwap, pullback_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, RiskLevel, TargetLevel,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_impulse_pullback import (
    LONG as MEASURE_LONG, MIRROR, PACIFIC, PLAN, SHORT as MEASURE_SHORT, at, history,
    snapshot as measurement_snapshot,
)
from test_orb5_eligibility import decision, metadata
from test_strategy_interface import session


DAY = "2026-07-06"
VERSION = "M84_FIXTURE_ONLY_V1"
POLICY_VERSION = "M84_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M84_SUPPLIED_FIXTURE_DEFINITION"
MODE = "SUPPLIED_FIXTURE_SCORE_POINTS"
SCORES = (80.0, 60.0, 40.0)
STARTED = at("06:30:00")
FROZEN = at("06:35:00")
EVALUATED = at("06:39:00")
# The M8.3 fixture session measures a 5.00 impulse into 104.00, a pullback to
# 102.00 whose reversal bar printed 103.20/102.40, a 0.4 retracement and a 0.5
# volume ratio, with a 0.10 minute ATR and a 101.50 VWAP. Every figure here is a
# synthetic fixture for that session and is mirrored around 200.00 for its short
# twin, exactly as the M8.3 mirror plan is.
ATR = 0.10
VWAP = 101.50
SLOPE = 0.02
CROSSES = 1
STRENGTH = 0.35
LAST = 103.25
ENTRY = 103.25
STOP = 101.90
RISK_PER_SHARE = 1.35
TARGETS = ((105.00, 1.25), (107.00, 2.50))
# Distinguishes "the fixture's own price" from a supplied price of None.
SUPPLIED = object()


def mirror(value, direction="SHORT"):
    """Mirror a long fixture level into its short twin, as the M8.3 plan does."""
    if value is None or direction == "LONG":
        return value
    return round(200.00 - value, 10)


def measurement(direction="LONG", **changes):
    """The real M8.3 snapshot for this supplied session and direction."""
    values = dict(policy=MEASURE_LONG if direction == "LONG" else MEASURE_SHORT,
                  atr_1m=ATR, vwap=mirror(VWAP, direction))
    values.update(changes)
    supplied = values.pop("supplied", None)
    plan = values.pop("plan", PLAN if direction == "LONG" else MIRROR)
    if supplied is None and "minute_history" not in values:
        supplied = history(plan=plan)
    return measurement_snapshot(supplied, **values)


def policy(direction="LONG", **changes):
    values = dict(
        version=POLICY_VERSION, definition_reference=DEFINITION, direction=direction,
        mode="TAPE", max_observation_age_seconds=3.0, min_impulse_atr_multiple=0.40,
        min_impulse_vwap_atr_multiple=0.25, min_vwap_slope=0.005, max_vwap_crosses=3,
        min_relative_strength=0.0, min_retracement=0.20, max_retracement=0.65,
        kill_retracement=0.70, max_pullback_volume_ratio=0.80, max_support_atr_multiple=0.10,
        min_trigger_offset=0.01, min_trigger_atr_multiple=0.03, max_spread_bps=20.0,
        max_pullback_ordinal=2, min_first_target_r_multiple=1.00,
    )
    values.update(changes)
    return PullbackVwapPolicy(**values)


def vwap_context(direction="LONG", *, level=SUPPLIED, slope=SUPPLIED, crosses=CROSSES,
                 at_instant=EVALUATED, **changes):
    values = dict(
        record_id="m84-vwap", definition_reference="M84_SUPPLIED_VWAP_V1",
        available_at=at_instant, coverage_complete=True,
        level=mirror(VWAP, direction) if level is SUPPLIED else level,
        slope=(SLOPE if direction == "LONG" else -SLOPE) if slope is SUPPLIED else slope,
        crosses=crosses,
    )
    values.update(changes)
    return VwapContext(**values)


def relative_strength(direction="LONG", *, value=SUPPLIED, at_instant=EVALUATED, **changes):
    values = dict(
        record_id="m84-relative-strength",
        definition_reference="M84_SUPPLIED_RELATIVE_STRENGTH_V1", available_at=at_instant,
        coverage_complete=True,
        value=(STRENGTH if direction == "LONG" else -STRENGTH) if value is SUPPLIED else value,
    )
    values.update(changes)
    return RelativeStrength(**values)


def last_trade(direction="LONG", *, price=SUPPLIED, at_instant=EVALUATED, **changes):
    from test_orb5_trigger import observation

    supplied = mirror(LAST if price is SUPPLIED else price, direction)
    return observation("m84-last-trade", at_instant, supplied, **changes)


def risk_level(direction="LONG", *, entry=ENTRY, stop=STOP, distance=RISK_PER_SHARE):
    return RiskLevel(mirror(entry, direction), mirror(stop, direction), distance,
                     "Synthetic fixture stop only", "m84-fixture")


def targets(direction="LONG", supplied=TARGETS):
    return tuple(
        TargetLevel("T%d" % (number + 1), mirror(price, direction), multiple, "m84-fixture")
        for number, (price, multiple) in enumerate(supplied)
    )


def structural(direction="LONG", *, at_instant=EVALUATED, frozen=FROZEN, **changes):
    values = dict(
        definition_reference="M84_SUPPLIED_STRUCTURAL_V1", direction=direction,
        impulse_frozen_at=frozen, evaluated_at=at_instant, available_at=at_instant,
        risk=risk_level(direction), targets=targets(direction),
        record_ids=("m84-supplied-stop", "m84-supplied-targets"),
    )
    values.update(changes)
    return PullbackStructural(**values)


def terms():
    """One supplied score and one declared factor for each M4.4 component."""
    return tuple(
        ConfidenceTerm(component.lower() + "-" + kind.lower(), component, kind,
                       component.lower() + "-" + kind.lower(), VERSION, MODE)
        for component in COMPONENTS for kind in ("SCORE", "FACTOR")
    )


def confidence_policy(*, strategy_id=STRATEGY_ID, strategy_version=VERSION):
    return ConfidencePolicy(strategy_id, strategy_version, POLICY_VERSION, .5, .3, .2, terms())


def scores_snapshot(*, at_instant=EVALUATED, missing=None):
    features = tuple(
        FeatureValue(term.feature_name,
                     None if term.name == missing else SCORES[COMPONENTS.index(term.component)],
                     "SCORE_POINTS", "MISSING_SOURCE" if term.name == missing else None,
                     ("m84-score-input",))
        for term in terms()
    )
    return FeatureSnapshot(record_id="m84-supplied-scores",
                           metadata=metadata(at_instant, data_mode=MODE),
                           evaluated_at=at_instant, feature_version=VERSION, features=features,
                           input_record_ids=("m84-score-input",))


def confidence(direction="LONG", *, at_instant=EVALUATED, missing=None, supplied_policy=None,
               traded=None):
    """The real M4.4 composition for this direction at this instant."""
    rules = supplied_policy if supplied_policy is not None else confidence_policy()
    snapshot = scores_snapshot(at_instant=at_instant, missing=missing)
    context = StrategyContext(session(DAY), "SYNTH", "EQUITY",
                              traded if traded is not None else direction,
                              at_instant, (snapshot,))
    return compose_confidence(ConfidenceRequest(
        context, rules, tuple((term.name, snapshot.record_id) for term in rules.terms)))


def request(direction="LONG", *, at_instant=EVALUATED, **changes):
    """One evaluation of one supplied M8.3 impulse and pullback measurement."""
    values = dict(
        measurement=measurement(direction, evaluated=at_instant),
        measurement_policy=MEASURE_LONG if direction == "LONG" else MEASURE_SHORT,
        policy=policy(direction), evaluated_at=at_instant, symbol="SYNTH",
        strategy_version=VERSION, definition_reference=DEFINITION,
        impulse_started_at=STARTED, impulse_frozen_at=FROZEN, atr_1m=ATR, pullback_ordinal=1,
        vwap=vwap_context(direction, at_instant=at_instant),
        relative_strength=relative_strength(direction, at_instant=at_instant),
        last_trade=last_trade(direction, at_instant=at_instant),
        quote=decision(direction, at=at_instant),
        structural=structural(direction, at_instant=at_instant),
        confidence=confidence(direction, at_instant=at_instant),
    )
    values.update(changes)
    return PullbackRequest(**values)


def owner(direction="LONG", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  strategy_version=VERSION, policy=policy(direction))
    values.update(changes)
    return FirstPullbackVwapMachine(**values)


# --- supplied policy and record contracts -----------------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"direction": "BOTH"}, {"direction": "long"}, {"mode": "BOTH"},
    {"max_observation_age_seconds": -1.0}, {"max_observation_age_seconds": "3"},
    {"min_impulse_atr_multiple": 0.0}, {"min_impulse_vwap_atr_multiple": float("nan")},
    {"min_vwap_slope": 0.0}, {"max_vwap_crosses": 0}, {"max_vwap_crosses": 3.0},
    {"min_relative_strength": -0.1}, {"min_retracement": 0.0},
    {"min_retracement": 0.70, "max_retracement": 0.65},
    {"max_retracement": 0.75, "kill_retracement": 0.70},
    {"kill_retracement": 1.25}, {"max_pullback_volume_ratio": 0.0},
    {"max_support_atr_multiple": -0.10}, {"min_trigger_offset": 0.0},
    {"min_trigger_atr_multiple": float("inf")}, {"max_spread_bps": 0.0},
    {"max_pullback_ordinal": 0}, {"min_first_target_r_multiple": 0.0},
))
def test_policy_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        policy(**changes)


def test_policy_is_immutable_and_renders_its_supplied_values():
    supplied = policy()
    with pytest.raises(FrozenInstanceError):
        supplied.max_retracement = 0.95
    rendered = supplied.as_dict()
    assert rendered["definition_reference"] == DEFINITION
    assert rendered["direction"] == "LONG" and rendered["max_pullback_ordinal"] == 2
    assert rendered["kill_retracement"] == 0.70
    # The band, its kill value and the equal-band edge case are the caller's own.
    assert policy(max_retracement=0.70, kill_retracement=0.70).max_retracement == 0.70


@pytest.mark.parametrize("changes", (
    {"record_id": " "}, {"definition_reference": "UNKNOWN"}, {"at_instant": None},
    {"coverage_complete": 1}, {"level": 0.0}, {"slope": "0.02"}, {"crosses": -1},
    {"crosses": 1.0}, {"level": None}, {"slope": None}, {"crosses": None},
    {"level": None, "slope": None, "crosses": None, "missing_reason": " "},
    {"missing_reason": "NO_VWAP_COVERAGE"},
))
def test_vwap_context_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        vwap_context(**changes)


def test_a_partly_unknown_vwap_context_names_its_own_reason():
    supplied = vwap_context(slope=None, missing_reason="NO_SLOPE_COVERAGE")
    assert supplied.slope is None and supplied.as_dict()["missing_reason"] == "NO_SLOPE_COVERAGE"
    assert supplied.as_dict()["level"] == VWAP and supplied.as_dict()["crosses"] == CROSSES


@pytest.mark.parametrize("changes", (
    {"record_id": "UNSPECIFIED"}, {"definition_reference": " "}, {"at_instant": "06:39:00"},
    {"coverage_complete": "yes"}, {"value": "0.35"}, {"value": None},
    {"value": None, "missing_reason": " "}, {"missing_reason": "MISSING_BENCHMARK"},
))
def test_relative_strength_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        relative_strength(**changes)


def test_a_negative_relative_strength_reading_is_a_supplied_value():
    supplied = relative_strength(value=-0.35)
    assert supplied.value == -0.35 and supplied.as_dict()["missing_reason"] is None


@pytest.mark.parametrize("changes", (
    {"definition_reference": " "}, {"direction": "BOTH"},
    {"frozen": EVALUATED + timedelta(minutes=1)}, {"risk": "M84"},
    {"targets": [TargetLevel("T1", 105.0, 1.25, "m84")]},
    {"risk": None, "missing_reason": None},
    {"risk": None, "targets": (), "missing_reason": " "},
    {"missing_reason": "MISSING_SOURCE"}, {"record_ids": (" ",)},
))
def test_structural_reading_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        structural(**changes)


def test_a_missing_structural_measurement_carries_no_targets():
    supplied = structural(risk=None, targets=(), missing_reason="STOP_SOURCE_UNAVAILABLE")
    assert supplied.risk is None and supplied.targets == ()
    with pytest.raises(RecordError):
        structural(risk=None, missing_reason="STOP_SOURCE_UNAVAILABLE")
    with pytest.raises(RecordError):
        structural(targets=targets() + targets())


@pytest.mark.parametrize("changes", (
    {"name": "OTHER_GATE"}, {"status": "MAYBE"}, {"status": "FAIL", "reason": None},
    {"status": "UNKNOWN", "reason": " "}, {"input_record_ids": ["a"]},
))
def test_gate_requires_supported_name_status_and_reason(changes):
    values = dict(name=TRIGGER_GATE, status="FAIL", reason="LAST_NOT_BEYOND_REVERSAL_BAR")
    values.update(changes)
    with pytest.raises(RecordError):
        PullbackGate(**values)


@pytest.mark.parametrize("changes", (
    {"measurement": "M84"}, {"measurement_policy": "M84"}, {"policy": "M84"},
    {"symbol": " "}, {"strategy_version": "UNKNOWN"}, {"definition_reference": " "},
    {"impulse_started_at": FROZEN}, {"impulse_started_at": "06:30:00"},
    {"impulse_frozen_at": EVALUATED + timedelta(minutes=1)}, {"atr_1m": 0.0},
    {"pullback_ordinal": 0}, {"pullback_ordinal": 1.0}, {"vwap": "M84"},
    {"relative_strength": "M84"}, {"last_trade": "M84"}, {"quote": "M84"},
    {"structural": "M84"}, {"confidence": "M84"},
))
def test_request_requires_canonical_supplied_inputs(changes):
    with pytest.raises(RecordError):
        request(**changes)


def test_the_direction_and_window_come_from_the_supplied_inputs():
    assert request().direction == "LONG" and request("SHORT").direction == "SHORT"
    assert request().window == (STARTED, FROZEN)


# --- the supplied rules ------------------------------------------------------


def test_the_rules_start_at_a_formed_pullback_and_never_fall_back():
    rules = pullback_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert (StrategyState("ALERT_TRIGGERED"), StrategyState("ARMED")) not in rules.allowed
    assert (rules.initial_state, StrategyState("ALERT_TRIGGERED")) not in rules.allowed


def test_the_rules_hold_exactly_the_supplied_pullback_pairs():
    forming = StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    armed, triggered = StrategyState("ARMED"), StrategyState("ALERT_TRIGGERED")
    invalidated, expired = StrategyState("INVALIDATED"), StrategyState("EXPIRED")
    assert set(pullback_rules().allowed) == {
        (forming, armed), (armed, triggered), (forming, invalidated), (armed, invalidated),
        (triggered, invalidated), (forming, expired), (armed, expired), (triggered, expired),
        (invalidated, expired),
    }


# --- one supplied actionable continuation ------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_supplied_first_pullback_becomes_an_actionable_continuation(direction):
    result = evaluate_first_pullback_vwap(request(direction))
    assert result.state == StrategyState("ALERT_TRIGGERED")
    assert result.direction == direction and result.reasons == ()
    assert all(row.status == "PASS" for row in result.gates)
    assert result.impulse_distance_atr == pytest.approx(50.0)
    assert result.impulse_from_vwap_atr == pytest.approx(25.0)
    assert result.retracement == pytest.approx(0.4)
    assert result.volume_ratio == pytest.approx(0.5)
    assert result.support_from_vwap_atr == pytest.approx(5.0)
    assert result.trigger_price == pytest.approx(mirror(103.21, direction))
    assert result.last_price == pytest.approx(mirror(LAST, direction))
    assert result.pullback_ordinal == 1
    assert result.spread_bps is not None and result.spread_bps < policy().max_spread_bps
    assert result.risk == risk_level(direction) and result.targets == targets(direction)
    assert result.confidence is not None
    assert result.structural_input_ids == ("m84-supplied-stop", "m84-supplied-targets")
    assert result.measurement_record_id == "impulse-pullback"
    assert (result.impulse_started_at, result.impulse_frozen_at) == (STARTED, FROZEN)


# --- the supplied M8.3 measurement -------------------------------------------


def test_a_snapshot_from_another_feature_version_is_not_this_measurement():
    supplied = replace(measurement(), feature_version="M83_OTHER_V1")
    result = evaluate_first_pullback_vwap(request(measurement=supplied))
    gate = result.gate(MEASUREMENT_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "MEASUREMENT_VERSION_MISMATCH")
    assert result.state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert evaluate_first_pullback_vwap(request()).gate(MEASUREMENT_GATE).status == "PASS"


def test_a_measurement_of_another_subject_or_instant_is_refused():
    supplied = measurement()
    cases = {
        "MEASUREMENT_DATA_MODE_MISMATCH": replace(
            supplied, metadata=replace(supplied.metadata, data_mode="OTHER_MODE")),
        "MEASUREMENT_SYMBOL_MISMATCH": replace(
            supplied, metadata=replace(supplied.metadata, instrument_id="OTHER")),
    }
    for reason, record in cases.items():
        result = evaluate_first_pullback_vwap(request(measurement=record))
        assert result.gate(MEASUREMENT_GATE).reason == reason
        assert result.state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    # The legs were read in the other direction, so they are not this trade's.
    crossed = evaluate_first_pullback_vwap(request(measurement_policy=MEASURE_SHORT))
    assert crossed.gate(MEASUREMENT_GATE).reason == "MEASUREMENT_DIRECTION_MISMATCH"
    # A measurement made one minute earlier is not this instant's fact.
    earlier = evaluate_first_pullback_vwap(request(
        measurement=measurement(evaluated=EVALUATED - timedelta(minutes=1))))
    assert earlier.gate(MEASUREMENT_GATE).reason == "MEASUREMENT_NOT_CURRENT"
    # The canonical snapshot cannot be measured before it was available, so a
    # snapshot that arrives late is not a reachable state to gate for.
    with pytest.raises(RecordError, match="available_time"):
        replace(supplied, metadata=replace(
            supplied.metadata, available_time=EVALUATED + timedelta(seconds=1)))


def test_an_incomplete_leg_keeps_the_owner_at_a_forming_pullback():
    # The pullback has not completed its first minute yet at the freeze itself.
    early = evaluate_first_pullback_vwap(request(
        at_instant=FROZEN, measurement=measurement(evaluated=FROZEN),
        structural=structural(at_instant=FROZEN), confidence=confidence(at_instant=FROZEN),
        vwap=vwap_context(at_instant=FROZEN),
        relative_strength=relative_strength(at_instant=FROZEN),
        last_trade=last_trade(at_instant=FROZEN), quote=decision(at=FROZEN)))
    gate = early.gate(MEASUREMENT_GATE)
    assert gate.status == "UNKNOWN"
    assert gate.reason == "PULLBACK_INCOMPLETE_INCOMPLETE_PULLBACK_WINDOW"
    assert early.state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert early.gate(RISK_GATE).reason == "GEOMETRY_MEASUREMENT_UNAVAILABLE"
    # A refused impulse leg is named on its own, with the same forming state.
    uncovered = evaluate_first_pullback_vwap(request(
        measurement=measurement(supplied=history(first_minute=2))))
    assert uncovered.gate(MEASUREMENT_GATE).reason == (
        "IMPULSE_INCOMPLETE_IMPULSE_WINDOW_NOT_COVERED")
    assert uncovered.state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)


def test_a_measurement_without_the_named_value_never_becomes_a_number():
    supplied = measurement()
    stripped = replace(supplied, features=tuple(
        row for row in supplied.features if row.name != "PULLBACK_RETRACEMENT_V1"))
    result = evaluate_first_pullback_vwap(request(measurement=stripped))
    gate = result.gate(RETRACEMENT_GATE)
    assert (gate.status, gate.reason) == (
        "UNKNOWN", "MEASUREMENT_VALUE_ABSENT_PULLBACK_RETRACEMENT_V1")
    assert result.retracement is None and result.state == StrategyState("ARMED")


# --- the mandatory continuation context --------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_an_impulse_below_the_callers_own_minimum_is_refused(direction):
    result = evaluate_first_pullback_vwap(request(
        direction, policy=policy(direction, min_impulse_atr_multiple=60.0)))
    gate = result.gate(IMPULSE_GATE)
    assert gate.reason == "IMPULSE_BELOW_SUPPLIED_MINIMUM"
    assert gate.observed == pytest.approx(50.0) and gate.threshold == pytest.approx(60.0)
    assert result.state == StrategyState("ARMED")


def test_an_impulse_whose_extreme_printed_first_is_not_a_continuation():
    plan = ((104.00, 103.00, 900), (103.00, 102.00, 1000), (102.00, 101.00, 1200),
            (101.00, 100.00, 1400), (100.00, 99.00, 1500)) + PLAN[5:]
    result = evaluate_first_pullback_vwap(request(measurement=measurement(plan=plan)))
    gate = result.gate(IMPULSE_GATE)
    assert (gate.status, gate.reason) == ("FAIL", "IMPULSE_EXTREME_BEFORE_ITS_ORIGIN")
    assert result.impulse_distance_atr is None and result.state == StrategyState("ARMED")


def test_an_impulse_that_ended_too_close_to_the_vwap_is_refused():
    result = evaluate_first_pullback_vwap(request(
        policy=policy(min_impulse_vwap_atr_multiple=30.0)))
    gate = result.gate(IMPULSE_VWAP_GATE)
    assert gate.reason == "IMPULSE_TOO_CLOSE_TO_VWAP"
    assert gate.observed == pytest.approx(25.0)
    assert result.state == StrategyState("ARMED")


def test_a_missing_supplied_atr_leaves_the_measured_distances_unknown():
    result = evaluate_first_pullback_vwap(request(
        measurement=measurement(atr_1m=None), atr_1m=None))
    for name in (IMPULSE_GATE, IMPULSE_VWAP_GATE, SUPPORT_GATE):
        assert result.gate(name).status == "UNKNOWN"
        assert result.gate(name).reason == "MISSING_ATR_1M"
    assert result.gate(TRIGGER_GATE).reason == "MISSING_ATR_1M"
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_last_trade_on_the_wrong_side_of_the_vwap_is_refused(direction):
    result = evaluate_first_pullback_vwap(request(
        direction, last_trade=last_trade(direction, price=100.90)))
    gate = result.gate(VWAP_SIDE_GATE)
    assert gate.reason == "LAST_ON_THE_WRONG_SIDE_OF_VWAP"
    assert gate.threshold == pytest.approx(mirror(VWAP, direction))
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_vwap_slope_below_the_callers_own_minimum_is_refused(direction):
    flat = vwap_context(direction, slope=0.0)
    result = evaluate_first_pullback_vwap(request(direction, vwap=flat))
    gate = result.gate(VWAP_SLOPE_GATE)
    assert gate.reason == "VWAP_SLOPE_BELOW_SUPPLIED_MINIMUM"
    assert gate.observed == pytest.approx(0.0)
    assert result.state == StrategyState("ARMED")
    # A slope that rises for a long trade falls for its short twin.
    crossed = evaluate_first_pullback_vwap(request(
        direction, vwap=vwap_context(direction, slope=SLOPE if direction == "SHORT" else -SLOPE)))
    assert crossed.gate(VWAP_SLOPE_GATE).observed == pytest.approx(-SLOPE)


def test_a_session_that_crossed_its_vwap_too_often_is_closed():
    result = evaluate_first_pullback_vwap(request(vwap=vwap_context(crosses=4)))
    gate = result.gate(VWAP_CROSS_GATE)
    assert gate.reason == "VWAP_CROSSES_ABOVE_SUPPLIED_MAXIMUM"
    assert gate.reason in INVALIDATIONS
    assert gate.observed == pytest.approx(4.0) and gate.threshold == pytest.approx(3.0)
    assert result.state == StrategyState("INVALIDATED")


@pytest.mark.parametrize("changes,reason", (
    ({"level": None, "slope": None, "crosses": None,
      "missing_reason": "NO_VWAP_COVERAGE"}, "NO_VWAP_COVERAGE"),
    ({"coverage_complete": False, "level": None, "slope": None, "crosses": None,
      "missing_reason": "PARTIAL_SESSION"}, "VWAP_COVERAGE_INCOMPLETE"),
    ({"at_instant": EVALUATED + timedelta(seconds=1)}, "VWAP_NOT_AVAILABLE"),
))
def test_an_unusable_vwap_context_keeps_all_three_gates_unknown(changes, reason):
    result = evaluate_first_pullback_vwap(request(vwap=vwap_context(**changes)))
    for name in (VWAP_SIDE_GATE, VWAP_SLOPE_GATE, VWAP_CROSS_GATE):
        assert (result.gate(name).status, result.gate(name).reason) == ("UNKNOWN", reason)
    assert result.state == StrategyState("ARMED")


def test_a_missing_vwap_context_is_never_a_rising_uncrossed_vwap():
    result = evaluate_first_pullback_vwap(request(vwap=None))
    for name in (VWAP_SIDE_GATE, VWAP_SLOPE_GATE, VWAP_CROSS_GATE):
        assert result.gate(name).reason == "VWAP_CONTEXT_ABSENT"
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_relative_strength_must_stand_beyond_the_callers_own_minimum(direction):
    zero = evaluate_first_pullback_vwap(request(
        direction, relative_strength=relative_strength(direction, value=0.0)))
    gate = zero.gate(RS_GATE)
    assert gate.reason == "RELATIVE_STRENGTH_NOT_BEYOND_SUPPLIED_MINIMUM"
    assert gate.observed == pytest.approx(0.0) and zero.state == StrategyState("ARMED")
    # The supplied reading is read in the trade's own direction.
    against = evaluate_first_pullback_vwap(request(
        direction,
        relative_strength=relative_strength(direction,
                                            value=STRENGTH if direction == "SHORT" else -STRENGTH)))
    assert against.gate(RS_GATE).observed == pytest.approx(-STRENGTH)


@pytest.mark.parametrize("changes,reason", (
    ({"value": None, "missing_reason": "MISSING_BENCHMARK"}, "MISSING_BENCHMARK"),
    ({"coverage_complete": False}, "RELATIVE_STRENGTH_COVERAGE_INCOMPLETE"),
    ({"at_instant": EVALUATED + timedelta(seconds=1)}, "RELATIVE_STRENGTH_NOT_AVAILABLE"),
))
def test_an_unusable_relative_strength_reading_stays_unknown(changes, reason):
    result = evaluate_first_pullback_vwap(request(relative_strength=relative_strength(**changes)))
    gate = result.gate(RS_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.state == StrategyState("ARMED")
    assert evaluate_first_pullback_vwap(request(relative_strength=None)).gate(
        RS_GATE).reason == "RELATIVE_STRENGTH_ABSENT"


# --- the supplied pullback checks --------------------------------------------


def test_a_retracement_outside_the_callers_own_band_is_refused():
    shallow = evaluate_first_pullback_vwap(request(policy=policy(min_retracement=0.45)))
    gate = shallow.gate(RETRACEMENT_GATE)
    assert gate.reason == "RETRACEMENT_BELOW_SUPPLIED_BAND"
    assert gate.observed == pytest.approx(0.4) and gate.threshold == pytest.approx(0.45)
    assert shallow.state == StrategyState("ARMED")
    deep = evaluate_first_pullback_vwap(request(
        policy=policy(min_retracement=0.10, max_retracement=0.30, kill_retracement=0.70)))
    assert deep.gate(RETRACEMENT_GATE).reason == "RETRACEMENT_ABOVE_SUPPLIED_BAND"
    assert deep.state == StrategyState("ARMED")


def test_a_retracement_beyond_the_callers_own_kill_value_closes_the_setup():
    result = evaluate_first_pullback_vwap(request(
        policy=policy(min_retracement=0.10, max_retracement=0.20, kill_retracement=0.30)))
    gate = result.gate(RETRACEMENT_GATE)
    assert gate.reason == "RETRACEMENT_BEYOND_SUPPLIED_KILL"
    assert gate.reason in INVALIDATIONS
    assert gate.threshold == pytest.approx(0.30)
    assert result.state == StrategyState("INVALIDATED")


def test_a_pullback_that_did_not_contract_its_volume_is_refused():
    result = evaluate_first_pullback_vwap(request(
        policy=policy(max_pullback_volume_ratio=0.40)))
    gate = result.gate(VOLUME_GATE)
    assert gate.reason == "PULLBACK_VOLUME_ABOVE_SUPPLIED_LIMIT"
    assert gate.observed == pytest.approx(0.5) and gate.threshold == pytest.approx(0.40)
    assert result.state == StrategyState("ARMED")


def test_a_flat_impulse_leaves_the_measured_ratios_unavailable():
    flat = tuple((101.50, 101.50, volume) for _, _, volume in PLAN)
    result = evaluate_first_pullback_vwap(request(measurement=measurement(plan=flat)))
    assert result.gate(RETRACEMENT_GATE).reason == "ZERO_IMPULSE_DISTANCE"
    assert result.retracement is None and result.state == StrategyState("ARMED")
    quiet = tuple((high, low, 0) for high, low, _ in PLAN[:5]) + PLAN[5:]
    volumeless = evaluate_first_pullback_vwap(request(measurement=measurement(plan=quiet)))
    assert volumeless.gate(VOLUME_GATE).reason == "ZERO_IMPULSE_VOLUME"
    assert volumeless.volume_ratio is None


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_pullback_that_fell_past_the_supplied_vwap_pad_is_refused(direction):
    # The same measured session read against a VWAP above the pullback extreme.
    result = evaluate_first_pullback_vwap(request(
        direction, measurement=measurement(direction, vwap=mirror(102.50, direction)),
        vwap=vwap_context(direction, level=mirror(102.50, direction))))
    gate = result.gate(SUPPORT_GATE)
    assert gate.reason == "PULLBACK_BEYOND_SUPPLIED_VWAP_PAD"
    assert gate.observed == pytest.approx(-5.0) and gate.threshold == pytest.approx(-0.10)
    assert result.state == StrategyState("ARMED")
    # The same distance passes under a wider supplied pad.
    wider = evaluate_first_pullback_vwap(request(
        direction, policy=policy(direction, max_support_atr_multiple=6.0),
        measurement=measurement(direction, vwap=mirror(102.50, direction)),
        vwap=vwap_context(direction, level=mirror(102.50, direction))))
    assert wider.gate(SUPPORT_GATE).status == "PASS"


# --- the supplied trigger ----------------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_last_trade_short_of_the_reversal_bar_is_not_the_trigger(direction):
    result = evaluate_first_pullback_vwap(request(
        direction, last_trade=last_trade(direction, price=103.20)))
    gate = result.gate(TRIGGER_GATE)
    assert gate.reason == "LAST_NOT_BEYOND_REVERSAL_BAR"
    assert gate.threshold == pytest.approx(mirror(103.21, direction))
    assert result.state == StrategyState("ARMED")
    # The trigger level is the reversal bar plus the larger supplied offset.
    padded = evaluate_first_pullback_vwap(request(
        direction, policy=policy(direction, min_trigger_atr_multiple=1.0)))
    assert padded.trigger_price == pytest.approx(mirror(103.30, direction))
    assert padded.gate(TRIGGER_GATE).reason == "LAST_NOT_BEYOND_REVERSAL_BAR"


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_last_trade_exactly_at_the_supplied_trigger_level_passes(direction):
    result = evaluate_first_pullback_vwap(request(
        direction, last_trade=last_trade(direction, price=103.21)))
    assert result.gate(TRIGGER_GATE).status == "PASS"
    assert result.state == StrategyState("ALERT_TRIGGERED")


@pytest.mark.parametrize("changes,status,reason", (
    ({"coverage_known": False}, "FAIL", "COVERAGE_LOST"),
    ({"available_at": EVALUATED + timedelta(minutes=1)}, "UNKNOWN",
     "LAST_TRADE_OBSERVATION_NOT_AVAILABLE"),
    ({"price": None, "missing_reason": "NO_TRADE_OBSERVED"}, "UNKNOWN",
     "LAST_TRADE_NO_TRADE_OBSERVED"),
    ({"age": None}, "UNKNOWN", "LAST_TRADE_OBSERVATION_AGE_UNKNOWN"),
    ({"age": 9.0}, "UNKNOWN", "LAST_TRADE_STALE_OBSERVATION"),
    ({"mode": "QUOTE_PROJECTED"}, "UNKNOWN", "LAST_TRADE_WRONG_ARM"),
))
def test_an_unusable_last_trade_never_becomes_a_passing_gate(changes, status, reason):
    result = evaluate_first_pullback_vwap(request(last_trade=last_trade(**changes)))
    for name in (VWAP_SIDE_GATE, TRIGGER_GATE):
        assert (result.gate(name).status, result.gate(name).reason) == (status, reason)
    assert result.last_price is None
    assert result.state == (StrategyState("INVALIDATED") if status == "FAIL"
                            else StrategyState("ARMED"))


def test_a_missing_last_trade_still_reports_the_supplied_trigger_level():
    result = evaluate_first_pullback_vwap(request(last_trade=None))
    gate = result.gate(TRIGGER_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "LAST_TRADE_LAST_TRADE_UNAVAILABLE")
    assert gate.threshold == pytest.approx(103.21)
    assert result.trigger_price == pytest.approx(103.21)


# --- the supplied quote spread ----------------------------------------------


def test_a_spread_above_the_callers_own_limit_is_refused():
    result = evaluate_first_pullback_vwap(request(policy=policy(max_spread_bps=0.5)))
    gate = result.gate(SPREAD_GATE)
    assert gate.reason == "SPREAD_ABOVE_SUPPLIED_LIMIT"
    assert gate.threshold == pytest.approx(0.5) and gate.observed > 0.5
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("changes,reason", (
    ({"bid": None}, "QUOTE_STREAM_MISSING_POSITIVE_SIDES"),
    ({"ask": None}, "QUOTE_STREAM_MISSING_POSITIVE_SIDES"),
    ({"status": "STALE"}, "QUOTE_STREAM_QUOTE_STATUS_STALE"),
    ({"delayed": True}, "QUOTE_STREAM_DELAYED"),
))
def test_an_unusable_quote_keeps_the_spread_unknown(changes, reason):
    result = evaluate_first_pullback_vwap(request(quote=decision(at=EVALUATED, **changes)))
    gate = result.gate(SPREAD_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.spread_bps is None and result.state == StrategyState("ARMED")


def test_a_stale_or_absent_quote_decision_stays_unknown():
    stale = evaluate_first_pullback_vwap(request(quote=decision(at=EVALUATED, age=9)))
    assert stale.gate(SPREAD_GATE).reason in ("STALE_QUOTE", "QUOTE_STREAM_QUOTE_STALE")
    absent = evaluate_first_pullback_vwap(request(quote=None))
    assert absent.gate(SPREAD_GATE).reason == "QUOTE_DECISION_ABSENT"
    assert absent.state == StrategyState("ARMED")


# --- which pullback of the session this is -----------------------------------


def test_the_second_supplied_pullback_still_passes_its_own_maximum():
    result = evaluate_first_pullback_vwap(request(pullback_ordinal=2))
    assert result.gate(SEQUENCE_GATE).status == "PASS"
    assert result.pullback_ordinal == 2 and result.state == StrategyState("ALERT_TRIGGERED")


def test_a_pullback_beyond_the_callers_own_maximum_is_closed():
    result = evaluate_first_pullback_vwap(request(pullback_ordinal=3))
    gate = result.gate(SEQUENCE_GATE)
    assert gate.reason == "PULLBACK_ORDINAL_BEYOND_SUPPLIED_MAXIMUM"
    assert gate.reason in INVALIDATIONS
    assert gate.observed == pytest.approx(3.0) and gate.threshold == pytest.approx(2.0)
    assert result.state == StrategyState("INVALIDATED")


def test_an_unknown_pullback_ordinal_is_never_the_first_pullback():
    result = evaluate_first_pullback_vwap(request(pullback_ordinal=None))
    gate = result.gate(SEQUENCE_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "PULLBACK_ORDINAL_UNAVAILABLE")
    assert result.pullback_ordinal is None and result.state == StrategyState("ARMED")
    assert "FIRST_PULLBACK_COUNTING_UNDEFINED" in result.unavailable


# --- the supplied stop and targets ------------------------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"direction": "SHORT"}, "GEOMETRY_DIRECTION_MISMATCH"),
    ({"impulse_frozen_at": STARTED}, "GEOMETRY_IMPULSE_WINDOW_MISMATCH"),
    ({"evaluated_at": EVALUATED + timedelta(seconds=1)}, "GEOMETRY_NOT_CURRENT"),
    ({"available_at": EVALUATED + timedelta(seconds=1)}, "GEOMETRY_NOT_YET_AVAILABLE"),
))
def test_a_reading_framed_on_another_structure_is_not_this_geometry(changes, reason):
    result = evaluate_first_pullback_vwap(request(structural=replace(structural(), **changes)))
    gate = result.gate(RISK_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.risk is None and result.targets == ()
    assert result.state == StrategyState("ARMED")


def test_a_missing_supplied_geometry_names_its_own_reason():
    absent = evaluate_first_pullback_vwap(request(structural=None))
    assert absent.gate(RISK_GATE).reason == "GEOMETRY_UNAVAILABLE"
    partial = evaluate_first_pullback_vwap(request(structural=structural(
        risk=None, targets=(), missing_reason="STOP_SOURCE_UNAVAILABLE")))
    assert partial.gate(RISK_GATE).reason == "GEOMETRY_STOP_SOURCE_UNAVAILABLE"
    empty = evaluate_first_pullback_vwap(request(structural=structural(targets=())))
    assert empty.gate(RISK_GATE).reason == "GEOMETRY_TARGETS_UNAVAILABLE"
    assert empty.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_an_entry_short_of_the_reversal_bar_is_refused(direction):
    result = evaluate_first_pullback_vwap(request(direction, structural=structural(
        direction, risk=risk_level(direction, entry=103.10, stop=101.75))))
    assert result.gate(RISK_GATE).reason == "ENTRY_NOT_BEYOND_REVERSAL_BAR"
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_stop_short_of_the_measured_pullback_extreme_is_refused(direction):
    result = evaluate_first_pullback_vwap(request(direction, structural=structural(
        direction, risk=risk_level(direction, stop=102.10, distance=1.15))))
    assert result.gate(RISK_GATE).reason == "STOP_NOT_BEYOND_PULLBACK_EXTREME"
    assert result.state == StrategyState("ARMED")


def test_a_stop_on_the_wrong_side_of_the_entry_is_refused():
    result = evaluate_first_pullback_vwap(request(structural=structural(
        risk=risk_level(entry=103.25, stop=104.60))))
    assert result.gate(RISK_GATE).reason == "STOP_ON_THE_WRONG_SIDE"


@pytest.mark.parametrize("supplied,reason", (
    (((102.00, 1.25), (107.00, 2.50)), "TARGET_NOT_BEYOND_ENTRY"),
    (((105.00, 1.40), (107.00, 2.50)), "TARGET_R_MULTIPLE_OVERSTATED"),
    (((104.00, 0.55), (107.00, 2.50)), "FIRST_TARGET_BELOW_SUPPLIED_MINIMUM"),
))
def test_a_target_the_supplied_prices_do_not_support_is_refused(supplied, reason):
    result = evaluate_first_pullback_vwap(request(structural=structural(
        targets=targets(supplied=supplied))))
    assert result.gate(RISK_GATE).reason == reason
    assert result.state == StrategyState("ARMED")


# --- the supplied confidence -------------------------------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"supplied_policy": "OTHER_STRATEGY"}, "CONFIDENCE_STRATEGY_MISMATCH"),
    ({"supplied_policy": "OTHER_VERSION"}, "CONFIDENCE_VERSION_MISMATCH"),
    ({"traded": "SHORT"}, "CONFIDENCE_DIRECTION_MISMATCH"),
    ({"at_instant": EVALUATED - timedelta(seconds=1)}, "CONFIDENCE_NOT_CURRENT"),
))
def test_a_confidence_result_for_another_subject_stays_unknown(changes, reason):
    if changes.get("supplied_policy") == "OTHER_STRATEGY":
        changes["supplied_policy"] = confidence_policy(strategy_id="CRVOL_ORB5")
    if changes.get("supplied_policy") == "OTHER_VERSION":
        changes["supplied_policy"] = confidence_policy(strategy_version="M84_OTHER_VERSION")
    result = evaluate_first_pullback_vwap(request(confidence=confidence(**changes)))
    gate = result.gate(CONFIDENCE_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.confidence is None and result.state == StrategyState("ARMED")


def test_an_incomplete_confidence_composition_never_passes():
    supplied = confidence(missing="setup-score")
    assert supplied.status != "READY"
    result = evaluate_first_pullback_vwap(request(confidence=supplied))
    assert result.gate(CONFIDENCE_GATE).status == "UNKNOWN"
    assert result.gate(CONFIDENCE_GATE).reason.startswith("CONFIDENCE_")
    assert evaluate_first_pullback_vwap(request(confidence=None)).gate(
        CONFIDENCE_GATE).reason == "CONFIDENCE_UNAVAILABLE"


def test_no_confidence_cutoff_is_applied_to_a_low_supplied_score():
    result = evaluate_first_pullback_vwap(request())
    assert result.confidence.final_score == pytest.approx(
        .5 * SCORES[0] + .3 * SCORES[1] + .2 * SCORES[2])
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable


# --- the reported result -----------------------------------------------------


def test_every_reported_gate_name_is_a_supported_one():
    assert tuple(row.name for row in evaluate_first_pullback_vwap(request()).gates) == (
        PULLBACK_GATES)


def test_the_result_names_what_no_approved_definition_supplies():
    assert evaluate_first_pullback_vwap(request()).unavailable == UNDEFINED
    for name in ("AVWAP_QUESTION_UNDEFINED", "IMPULSE_DEFINITION_UNDEFINED",
                 "STOP_PAD_UNDEFINED", "TAPE_ACCELERATION_PREFERENCE_UNDEFINED",
                 "VWAP_SLOPE_CONVENTION_UNDEFINED"):
        assert name in UNDEFINED


def test_the_same_supplied_request_renders_the_same_json():
    supplied = request()
    first, second = (evaluate_first_pullback_vwap(supplied) for _ in range(2))
    assert first.to_json() == second.to_json()
    payload = json.loads(first.to_json())
    assert payload["pullback_version"] == PULLBACK_VERSION
    assert payload["strategy_id"] == STRATEGY_ID
    assert payload["direction"] == "LONG"
    assert payload["state"] == "ALERT_TRIGGERED" and payload["substate"] is None
    assert payload["measurement_record_id"] == "impulse-pullback"
    assert payload["risk"]["hard_stop"] == STOP
    assert [row["name"] for row in payload["targets"]] == ["T1", "T2"]
    assert payload["policy_version"] == POLICY_VERSION


def test_the_result_is_immutable_and_needs_a_canonical_request():
    result = evaluate_first_pullback_vwap(request())
    with pytest.raises(FrozenInstanceError):
        result.state = StrategyState("INVALIDATED")
    with pytest.raises(RecordError):
        evaluate_first_pullback_vwap("M84")
    assert isinstance(result, PullbackAssessment)


def test_the_module_adopts_no_number_of_its_own():
    namespace = vars(first_pullback_vwap)
    assert not [name for name, value in namespace.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)]
    source = inspect.getsource(first_pullback_vwap)
    for token in ("0.40", "0.15", "0.25", "0.70", "0.65", "0.20", "0.80", "0.30", "0.50",
                  "0.10", "0.03", "1.5", "rs_15m"):
        assert token not in source


# --- the continuation owner --------------------------------------------------


def test_the_owner_refuses_inputs_that_are_not_its_own():
    with pytest.raises(RecordError):
        owner("SHORT").propose(request(), record_id="m84-armed")
    with pytest.raises(RecordError):
        owner().propose(request(policy=policy(max_spread_bps=10.0)), record_id="m84-armed")
    with pytest.raises(RecordError):
        owner().propose("M84", record_id="m84-armed")


def test_a_first_actionable_evaluation_records_the_formed_pullback_first():
    subject = owner()
    assessment, changes = subject.propose(request(), record_id="m84-armed",
                                          staged_record_id="m84-actionable")
    assert assessment.state == StrategyState("ALERT_TRIGGERED")
    assert len(changes) == 2
    assert (changes[0].from_substate, changes[0].to_state) == (PULLBACK_FORMING, "ARMED")
    assert changes[0].reason == "PULLBACK_FORMED_ARMED"
    assert (changes[1].from_state, changes[1].to_state) == ("ARMED", "ALERT_TRIGGERED")
    assert changes[1].record_id == "m84-actionable"
    assert changes[1].reason == "ALL_SUPPLIED_PULLBACK_GATES_PASSED"
    assert all(row.strategy_id == STRATEGY_ID for row in changes)
    assert all(row.metadata.data_mode == DATA_MODE for row in changes)


def test_a_two_step_evaluation_without_its_second_id_is_refused():
    with pytest.raises(RecordError):
        owner().propose(request(), record_id="m84-armed")


def test_a_single_step_evaluation_cannot_use_a_second_id():
    with pytest.raises(RecordError):
        owner().propose(request(pullback_ordinal=None), record_id="m84-armed",
                        staged_record_id="m84-unused")


def test_the_owner_advances_only_after_the_caller_confirms_the_recording():
    subject = owner()
    _, changes = subject.propose(request(pullback_ordinal=None), record_id="m84-armed")
    assert subject.current_state() == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert subject.confirm(*changes) == StrategyState("ARMED")
    assert subject.current_window() == (STARTED, FROZEN)
    with pytest.raises(RecordError):
        subject.confirm(*changes)


def test_a_different_impulse_cannot_replace_the_one_already_taken_over():
    subject = owner()
    _, changes = subject.propose(request(pullback_ordinal=None), record_id="m84-armed")
    subject.confirm(*changes)
    with pytest.raises(RecordError):
        subject.propose(request(pullback_ordinal=None, impulse_started_at=at("06:31:00")),
                        record_id="m84-second")


def test_an_actionable_continuation_cannot_fall_back_or_reopen():
    subject = owner()
    _, changes = subject.propose(request(), record_id="m84-armed",
                                 staged_record_id="m84-actionable")
    assert subject.confirm(*changes) == StrategyState("ALERT_TRIGGERED")
    assert subject.last_action_at == EVALUATED
    with pytest.raises(RecordError):
        subject.propose(request(pullback_ordinal=None), record_id="m84-back")


def test_an_armed_continuation_is_closed_rather_than_silently_dropped():
    subject = owner()
    _, changes = subject.propose(request(pullback_ordinal=None), record_id="m84-armed")
    subject.confirm(*changes)
    withdrawn = request(pullback_ordinal=None,
                        measurement=measurement(supplied=history(first_minute=2)))
    assessment, later = subject.propose(withdrawn, record_id="m84-withdrawn")
    assert assessment.state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert later[0].to_state == "INVALIDATED"
    assert subject.confirm(*later) == StrategyState("INVALIDATED")
    with pytest.raises(RecordError):
        subject.propose(request(pullback_ordinal=None), record_id="m84-reopen")


def test_an_unchanged_evaluation_proposes_nothing():
    subject = owner()
    assessment, changes = subject.propose(
        request(measurement=measurement(supplied=history(first_minute=2))),
        record_id="m84-none")
    assert assessment.state == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert changes == ()
    with pytest.raises(RecordError):
        subject.confirm()


def test_evaluation_time_cannot_move_backward():
    subject = owner()
    _, changes = subject.propose(request(pullback_ordinal=None), record_id="m84-armed")
    subject.confirm(*changes)
    earlier = at("06:38:00")
    with pytest.raises(RecordError):
        subject.propose(request(at_instant=earlier, pullback_ordinal=None), record_id="m84-back")


def test_the_owner_can_expire_and_names_its_own_reason():
    subject = owner()
    changes = subject.expire(at=EVALUATED, reason="SESSION_WINDOW_CLOSED",
                             record_id="m84-expire")
    assert subject.confirm(*changes) == StrategyState("EXPIRED")
    with pytest.raises(RecordError):
        owner().expire(at=EVALUATED, reason=" ", record_id="m84-expire")


@pytest.mark.parametrize("changes", (
    {"session": "M84"}, {"policy": "M84"}, {"instrument_type": "OPTION"},
    {"symbol": " "}, {"strategy_version": "UNKNOWN"},
))
def test_the_owner_requires_explicit_identity(changes):
    with pytest.raises(RecordError):
        owner(**changes)
    assert owner().direction == "LONG" and owner("SHORT").direction == "SHORT"


def test_restore_positions_an_unused_owner_on_explicit_saved_facts():
    subject = owner()
    state = subject.restore(StrategyState("ALERT_TRIGGERED"), window=(STARTED, FROZEN),
                            last_action_at=EVALUATED)
    assert state == StrategyState("ALERT_TRIGGERED")
    assert subject.current_window() == (STARTED, FROZEN)
    assert subject.last_action_at == EVALUATED
    with pytest.raises(RecordError):
        subject.restore(StrategyState("ARMED"))


@pytest.mark.parametrize("changes", (
    {"state": StrategyState("WATCHING")}, {"state": "ARMED"},
    {"state": StrategyState("SETUP_FORMING")},
    {"state": StrategyState("SETUP_FORMING", "OTHER")}, {"window": "M84"},
    {"window": (STARTED,)}, {"window": (FROZEN, STARTED)},
    {"window": (STARTED, "06:35:00")}, {"last_action_at": "2026-07-06T06:39:00"},
))
def test_restore_refuses_facts_that_are_not_m84_ones(changes):
    values = dict(state=StrategyState("ARMED"))
    values.update(changes)
    state = values.pop("state")
    with pytest.raises(RecordError):
        owner().restore(state, **values)


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           pullback_rules())


def context(direction="LONG", *, assessment, at_instant=EVALUATED, snapshot=None):
    ids = tuple(sorted({value for row in assessment.gates for value in row.input_record_ids}))
    provenance = FeatureSnapshot(
        record_id="m84-pullback-inputs", metadata=metadata(at_instant, data_mode=DATA_MODE),
        evaluated_at=at_instant,
        features=(FeatureValue("FIRST_PULLBACK_VWAP_INPUTS_V1", 1.0, "BOOLEAN", None, ids),),
        feature_version="M84_SYNTHETIC_INPUTS_V1", input_record_ids=ids)
    return StrategyContext(
        session(DAY), "SYNTH", "EQUITY", direction, at_instant,
        (snapshot if snapshot is not None else measurement(direction), provenance))


async def test_a_refused_recording_leaves_the_owner_where_it_was():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = owner()
    assessment, changes = subject.propose(request(pullback_ordinal=None),
                                          record_id="m84-armed")
    engine = StateTransitionEngine(scope("LONG"), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(changes[0], context=context(assessment=assessment))
    assert engine.current_state() == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert subject.current_state() == StrategyState("SETUP_FORMING", PULLBACK_FORMING)
    assert subject.current_window() is None


async def test_the_supplied_continuation_through_the_m42_engine_and_m51_store():
    proofs = []
    connection = await db.init_db()
    for direction in ("LONG", "SHORT"):
        subject = owner(direction)
        engine = StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection))
        store = ResearchEventStore(connection)

        armed_request = request(direction, pullback_ordinal=None)
        first, armed = subject.propose(armed_request, record_id="m84-armed-" + direction)
        assert first.state == StrategyState("ARMED")
        opened = await engine.apply(armed[0], context=context(direction, assessment=first))
        assert subject.confirm(*armed) == StrategyState("ARMED")

        supplied = request(direction)
        assessment, changes = subject.propose(supplied, record_id="m84-actionable-" + direction)
        assert assessment.state == StrategyState("ALERT_TRIGGERED")
        assert assessment.reasons == ()
        entry = await engine.apply(changes[0], context=context(direction, assessment=assessment))
        assert engine.current_state() == StrategyState("ALERT_TRIGGERED")
        assert subject.confirm(*changes) == StrategyState("ALERT_TRIGGERED")

        stored = await store.append(changes[0], session=DAY, recorded_at=EVALUATED)
        assert stored["kind"] == "STATE_TRANSITION"
        assert await store.append(changes[0], session=DAY, recorded_at=EVALUATED) == stored

        repeated = evaluate_first_pullback_vwap(supplied)
        assert repeated.to_json() == assessment.to_json()
        refused = evaluate_first_pullback_vwap(request(direction, pullback_ordinal=3))
        assert refused.state == StrategyState("INVALIDATED")
        proofs.append({
            "synthetic_only": True, "direction": direction,
            "armed_assessment": first.as_dict(), "assessment": assessment.as_dict(),
            "refused_assessment": refused.as_dict(),
            "armed_transition": armed[0].as_dict(), "transition": changes[0].as_dict(),
            "armed_position": opened.position, "stored_position": entry.position,
            "stored_fingerprint": stored["fingerprint"],
            "evaluated_at_pacific": assessment.evaluated_at.astimezone(PACIFIC).isoformat(),
            "gate_sha256": hashlib.sha256("".join(
                json.dumps(row.as_dict(), sort_keys=True)
                for row in assessment.gates).encode()).hexdigest(),
            "repeated_assessment_identical": True,
        })
    await db.close_db()
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "pullback_version": PULLBACK_VERSION, "runs": proofs}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m8_4_first_pullback_vwap_proof.json").write_text(rendered)
