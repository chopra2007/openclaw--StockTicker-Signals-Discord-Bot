"""M8.2 supplied-input `OR_FAILURE_REV` reversal contracts; no approved rule is adopted.

Every number below is a synthetic fixture supplied by the caller. A passing gate
proves the offline contract only: it establishes no tape or quote coverage, no
adopted `OR_FAILURE_REV` rule, no stop or target definition, no confidence cutoff,
no alert and no permission to act. ALERT_TRIGGERED here means the supplied inputs
passed every gate at one instant in a test process.

The handed-over failure is the real M8.1 assessment over the real M6.2 attempt and
M3.6 opening range, the confidence is the real M4.4 composition, and the recorded
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

from consensus_engine import db, or_failure_rev
from consensus_engine.confidence import (
    COMPONENTS, ConfidencePolicy, ConfidenceRequest, ConfidenceTerm, compose_confidence,
)
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.or_failure_handoff import (
    FAILURE_FORMING, STRATEGY_ID, evaluate_or_failure_handoff, mirror_direction,
)
from consensus_engine.or_failure_rev import (
    ACCEPTANCE_GATE, CONFIDENCE_GATE, CONFIRMATIONS, CONFIRMATION_GATE, DATA_MODE,
    DISPLACEMENT_GATE, EXTENSION_GATE, FAILURE_BAR_CONFIRMATION, FailureBar, HANDOFF_GATE,
    INVALIDATIONS, InsideAcceptance, LAST_GATE, MINUTE_CLOSE_CONFIRMATION,
    OrFailureRevMachine, REVERSAL_GATES, REVERSAL_VERSION, RISK_GATE, RULES_VERSION,
    ReversalAssessment, ReversalGate, ReversalPolicy, ReversalRequest, ReversalStructural,
    SPREAD_GATE, UNDEFINED, evaluate_or_failure_rev, reversal_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, RiskLevel, TargetLevel,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_orb5_eligibility import decision, metadata
from test_orb5_trigger import BOUNDARY, CROSS, DAY, RANGE, TRIGGER, candidate, flip, observation
from test_or_failure_handoff import (
    ENDED_AT, EXTREME, INSIDE, opening_range, request as handoff_request,
)
from test_strategy_interface import session


VERSION = "M82_FIXTURE_ONLY_V1"
POLICY_VERSION = "M82_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M82_SUPPLIED_FIXTURE_DEFINITION"
MODE = "SUPPLIED_FIXTURE_SCORE_POINTS"
SCORES = (80.0, 60.0, 40.0)
# The failed upside break of D-090 FX-08 reverses short. Every price below is a
# synthetic fixture for that break and is mirrored for its downside twin: the last
# trade back inside, the failure bar whose low the stronger trigger breaks, the
# supplied entry, the supplied stop beyond the 101.30 breakout extreme, and two
# supplied targets at the opening-range midpoint and its opposite boundary.
LAST = 100.70
FAILURE_BAR_RANGE = (101.30, 100.80)
ENTRY = 100.70
STOP = 101.35
RISK_PER_SHARE = 0.65
TARGETS = ((100.50, 0.30), (100.00, 1.00))
ACCEPTANCE = 0.70
# Distinguishes "the fixture's own price" from a supplied price of None.
SUPPLIED = object()


def policy(**changes):
    values = dict(
        version=POLICY_VERSION, definition_reference=DEFINITION, mode="TAPE",
        confirmation=MINUTE_CLOSE_CONFIRMATION, max_observation_age_seconds=3.0,
        min_inside_acceptance=ACCEPTANCE, max_spread_bps=20.0,
        min_displacement_atr_multiple=0.05, max_extension_r_multiple=0.50,
        min_first_target_r_multiple=0.25,
    )
    values.update(changes)
    return ReversalPolicy(**values)


def handoff(direction="LONG", **changes):
    """The real M8.1 assessment for one supplied failed break."""
    return evaluate_or_failure_handoff(handoff_request(direction, **changes))


def last_trade(direction="LONG", *, price=SUPPLIED, at=ENDED_AT, **changes):
    supplied = flip(LAST if price is SUPPLIED else price, direction)
    return observation("m82-last-trade", at, supplied, **changes)


def failure_bar(direction="LONG", *, at=ENDED_AT, **changes):
    high, low = FAILURE_BAR_RANGE
    if direction == "SHORT":
        high, low = flip(low, direction), flip(high, direction)
    values = dict(record_id="m82-failure-bar", bar_end=at, available_at=at,
                  high=high, low=low, final=True, coverage_known=True)
    values.update(changes)
    return FailureBar(**values)


def acceptance(*, share=ACCEPTANCE, at=ENDED_AT, **changes):
    values = dict(record_id="m82-inside-acceptance",
                  definition_reference="M82_SUPPLIED_ACCEPTANCE_V1", available_at=at,
                  share=share, coverage_complete=True, missing_reason=None)
    values.update(changes)
    return InsideAcceptance(**values)


def risk_level(direction="LONG", *, entry=ENTRY, stop=STOP, distance=RISK_PER_SHARE):
    return RiskLevel(flip(entry, direction), flip(stop, direction), distance,
                     "Synthetic fixture stop only", "m82-fixture")


def targets(direction="LONG", supplied=TARGETS):
    return tuple(
        TargetLevel("T%d" % (number + 1), flip(price, direction), multiple, "m82-fixture")
        for number, (price, multiple) in enumerate(supplied)
    )


def structural(direction="LONG", *, at=ENDED_AT, crossed_at=CROSS, attempt_number=1, **changes):
    values = dict(
        definition_reference="M82_SUPPLIED_STRUCTURAL_V1", direction=mirror_direction(direction),
        attempt_number=attempt_number, crossed_at=crossed_at, evaluated_at=at, available_at=at,
        risk=risk_level(direction), targets=targets(direction),
        record_ids=("m82-supplied-stop", "m82-supplied-targets"),
    )
    values.update(changes)
    return ReversalStructural(**values)


def terms():
    """One supplied score and one declared factor for each M4.4 component."""
    return tuple(
        ConfidenceTerm(component.lower() + "-" + kind.lower(), component, kind,
                       component.lower() + "-" + kind.lower(), VERSION, MODE)
        for component in COMPONENTS for kind in ("SCORE", "FACTOR")
    )


def confidence_policy(*, strategy_id=STRATEGY_ID, strategy_version=VERSION):
    return ConfidencePolicy(strategy_id, strategy_version, POLICY_VERSION, .5, .3, .2, terms())


def scores_snapshot(*, at=ENDED_AT, missing=None):
    features = tuple(
        FeatureValue(term.feature_name,
                     None if term.name == missing else SCORES[COMPONENTS.index(term.component)],
                     "SCORE_POINTS", "MISSING_SOURCE" if term.name == missing else None,
                     ("m82-score-input",))
        for term in terms()
    )
    return FeatureSnapshot(record_id="m82-supplied-scores", metadata=metadata(at, data_mode=MODE),
                           evaluated_at=at, feature_version=VERSION, features=features,
                           input_record_ids=("m82-score-input",))


def confidence(direction="LONG", *, at=ENDED_AT, missing=None, supplied_policy=None,
               reversal=None):
    """The real M4.4 composition for the reversal direction at this instant."""
    rules = supplied_policy if supplied_policy is not None else confidence_policy()
    snapshot = scores_snapshot(at=at, missing=missing)
    context = StrategyContext(session(DAY), "SYNTH", "EQUITY",
                              reversal if reversal is not None else mirror_direction(direction),
                              at, (snapshot,))
    return compose_confidence(ConfidenceRequest(
        context, rules, tuple((term.name, snapshot.record_id) for term in rules.terms)))


def request(direction="LONG", *, at=ENDED_AT, **changes):
    """One reversal evaluation of one handed-over failed break."""
    values = dict(
        handoff=handoff(direction, at=at), policy=policy(), evaluated_at=at,
        strategy_version=VERSION, definition_reference=DEFINITION,
        breakout_extreme_price=EXTREME[direction], last_trade=last_trade(direction, at=at),
        confirmation_close=minute_close(direction, at=at), failure_bar=failure_bar(direction, at=at),
        acceptance=acceptance(at=at), quote=decision(at=at),
        structural=structural(direction, at=at), confidence=confidence(direction, at=at),
    )
    values.update(changes)
    return ReversalRequest(**values)


def minute_close(direction="LONG", *, at=ENDED_AT, close=None, **changes):
    """The supplied final one-minute close back inside the opening range."""
    from test_orb5_trigger import minute_close as supplied_close

    values = dict(at=at, record_id="m82-confirmation-close",
                  close=INSIDE[direction] if close is None else close)
    values.update(changes)
    return supplied_close(**values)


def owner(direction="SHORT", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION, policy=policy())
    values.update(changes)
    return OrFailureRevMachine(**values)


# --- supplied policy and record contracts -----------------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"mode": "BOTH"}, {"confirmation": "EITHER"}, {"confirmation": "minute_close"},
    {"max_observation_age_seconds": -1.0}, {"max_observation_age_seconds": "3"},
    {"min_inside_acceptance": 0.0}, {"min_inside_acceptance": 1.25},
    {"min_inside_acceptance": True}, {"max_spread_bps": 0.0}, {"max_spread_bps": float("nan")},
    {"min_displacement_atr_multiple": 0.0}, {"max_extension_r_multiple": -0.5},
    {"min_first_target_r_multiple": float("inf")},
))
def test_policy_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        policy(**changes)


def test_policy_is_immutable_and_renders_its_supplied_values():
    supplied = policy()
    with pytest.raises(FrozenInstanceError):
        supplied.max_extension_r_multiple = 9.0
    assert supplied.as_dict()["definition_reference"] == DEFINITION
    assert supplied.as_dict()["confirmation"] == MINUTE_CLOSE_CONFIRMATION
    assert CONFIRMATIONS == (MINUTE_CLOSE_CONFIRMATION, FAILURE_BAR_CONFIRMATION)


@pytest.mark.parametrize("changes", (
    {"record_id": " "}, {"definition_reference": "UNKNOWN"}, {"available_at": None},
    {"available_at": datetime(2026, 7, 6, 6, 50)}, {"share": 1.5}, {"share": -0.1},
    {"share": "0.7"}, {"share": None, "missing_reason": None},
    {"share": ACCEPTANCE, "missing_reason": "MISSING_SOURCE"}, {"coverage_complete": 1},
))
def test_inside_acceptance_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        acceptance(**changes)


def test_an_unknown_acceptance_share_stays_explicitly_unknown():
    supplied = acceptance(share=None, missing_reason="MISSING_SOURCE")
    assert supplied.share is None and supplied.as_dict()["missing_reason"] == "MISSING_SOURCE"


@pytest.mark.parametrize("changes", (
    {"record_id": "UNKNOWN"}, {"bar_end": "2026-07-06T06:50:10"},
    {"available_at": datetime(2026, 7, 6, 6, 50, 10)}, {"high": 0.0}, {"low": -1.0},
    {"high": None}, {"low": None}, {"high": 100.0, "low": 101.0}, {"final": 1},
    {"coverage_known": "yes"},
))
def test_failure_bar_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        failure_bar(**changes)


def test_a_pending_failure_bar_may_leave_its_prices_unknown():
    supplied = failure_bar(final=False, high=None, low=None)
    assert supplied.as_dict()["final"] is False and supplied.extreme("SHORT") is None
    assert failure_bar().extreme("SHORT") == FAILURE_BAR_RANGE[1]
    assert failure_bar().extreme("LONG") == FAILURE_BAR_RANGE[0]
    with pytest.raises(RecordError):
        failure_bar().extreme("BOTH")


@pytest.mark.parametrize("changes", (
    {"definition_reference": " "}, {"direction": "BOTH"}, {"attempt_number": 0},
    {"attempt_number": 1.0}, {"evaluated_at": CROSS - timedelta(seconds=1)},
    {"risk": "M82"}, {"targets": [TargetLevel("T1", 100.5, 0.3, "m82")]},
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
    values = dict(name=HANDOFF_GATE, status="FAIL", reason="HANDOFF_CLOSED")
    values.update(changes)
    with pytest.raises(RecordError):
        ReversalGate(**values)


@pytest.mark.parametrize("changes", (
    {"handoff": "M82"}, {"policy": "M82"}, {"evaluated_at": CROSS - timedelta(seconds=1)},
    {"strategy_version": "UNKNOWN"}, {"definition_reference": " "},
    {"breakout_extreme_price": 0.0}, {"last_trade": "M82"}, {"confirmation_close": "M82"},
    {"failure_bar": "M82"}, {"acceptance": "M82"}, {"quote": "M82"}, {"structural": "M82"},
    {"confidence": "M82"},
))
def test_request_requires_canonical_supplied_inputs(changes):
    with pytest.raises(RecordError):
        request(**changes)


def test_the_reversal_direction_mirrors_the_supplied_break():
    assert request("LONG").direction == "SHORT" and request("LONG").break_direction == "LONG"
    assert request("SHORT").direction == "LONG"
    assert request("LONG").failed_edge == RANGE["LONG"][0]
    assert request("SHORT").failed_edge == RANGE["SHORT"][1]
    assert request("LONG").candidate == candidate("LONG")


# --- the supplied rules ------------------------------------------------------


def test_the_rules_continue_the_m81_chain_and_never_fall_back():
    rules = reversal_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert (StrategyState("ALERT_TRIGGERED"), StrategyState("ARMED")) not in rules.allowed
    assert (rules.initial_state, StrategyState("ALERT_TRIGGERED")) not in rules.allowed


def test_the_rules_hold_exactly_the_supplied_reversal_pairs():
    failing = StrategyState("SETUP_FORMING", FAILURE_FORMING)
    armed, triggered = StrategyState("ARMED"), StrategyState("ALERT_TRIGGERED")
    invalidated, expired = StrategyState("INVALIDATED"), StrategyState("EXPIRED")
    assert set(reversal_rules().allowed) == {
        (failing, armed), (armed, triggered), (failing, invalidated), (armed, invalidated),
        (triggered, invalidated), (failing, expired), (armed, expired), (triggered, expired),
        (invalidated, expired),
    }


# --- one supplied actionable reversal ----------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_supplied_failed_break_reverses_into_an_actionable_reversal(direction):
    result = evaluate_or_failure_rev(request(direction))
    assert result.state == StrategyState("ALERT_TRIGGERED")
    assert result.direction == mirror_direction(direction) and result.reasons == ()
    assert all(row.status == "PASS" for row in result.gates)
    assert result.inside_distance == pytest.approx(0.30)
    assert result.required_displacement == pytest.approx(0.02)
    assert result.extension_r_multiple == pytest.approx(0.30 / RISK_PER_SHARE)
    assert result.acceptance_share == pytest.approx(ACCEPTANCE)
    assert result.spread_bps is not None and result.spread_bps < policy().max_spread_bps
    assert result.risk == risk_level(direction) and result.targets == targets(direction)
    assert result.confidence is not None
    assert result.structural_input_ids == ("m82-supplied-stop", "m82-supplied-targets")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_the_stronger_failure_bar_confirmation_is_its_own_supplied_arm(direction):
    supplied = policy(confirmation=FAILURE_BAR_CONFIRMATION)
    result = evaluate_or_failure_rev(request(direction, policy=supplied,
                                             confirmation_close=None))
    gate = result.gate(CONFIRMATION_GATE)
    assert gate.status == "PASS" and result.state == StrategyState("ALERT_TRIGGERED")
    assert gate.threshold == pytest.approx(
        failure_bar(direction).extreme(mirror_direction(direction)))
    # The mandatory arm cannot stand in for the stronger one, and neither repairs
    # a missing record of the other's own kind.
    missing = evaluate_or_failure_rev(request(direction, policy=supplied, failure_bar=None))
    assert missing.gate(CONFIRMATION_GATE).reason == "MISSING_FAILURE_BAR"
    assert missing.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_last_trade_short_of_the_failure_bar_is_not_the_stronger_trigger(direction):
    result = evaluate_or_failure_rev(request(
        direction, policy=policy(confirmation=FAILURE_BAR_CONFIRMATION),
        last_trade=last_trade(direction, price=100.90)))
    assert result.gate(CONFIRMATION_GATE).reason == "LAST_NOT_BEYOND_FAILURE_BAR"
    assert result.state == StrategyState("ARMED")


# --- the handed-over M8.1 failure -------------------------------------------


def test_a_handoff_that_is_not_failure_forming_arms_nothing():
    from test_or_failure_handoff import reacceptance

    supplied = handoff(minute_close=reacceptance(close=EXTREME["LONG"]))
    assert supplied.state == StrategyState("SETUP_FORMING", "BREAKOUT_ATTEMPT")
    result = evaluate_or_failure_rev(request(handoff=supplied))
    gate = result.gate(HANDOFF_GATE)
    assert gate.status == "FAIL"
    assert gate.reason == "HANDOFF_NOT_FAILURE_FORMING_REACCEPTANCE_INSIDE"
    assert result.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)


def test_an_unknown_handoff_input_keeps_the_reversal_unarmed():
    result = evaluate_or_failure_rev(request(handoff=handoff(opening_range=None)))
    gate = result.gate(HANDOFF_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "HANDOFF_UNKNOWN_OPENING_RANGE_AGREEMENT")
    assert result.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)


def test_a_closed_handoff_closes_the_reversal_with_it():
    from test_or_failure_handoff import reacceptance

    supplied = handoff(minute_close=reacceptance(coverage_known=False))
    assert supplied.state == StrategyState("INVALIDATED")
    result = evaluate_or_failure_rev(request(handoff=supplied))
    assert result.gate(HANDOFF_GATE).reason == "HANDOFF_CLOSED"
    assert result.gate(HANDOFF_GATE).reason in INVALIDATIONS
    assert result.state == StrategyState("INVALIDATED")


def test_a_handoff_from_another_instant_is_not_this_instants_fact():
    later = ENDED_AT + timedelta(minutes=1)
    result = evaluate_or_failure_rev(request(
        at=later, handoff=handoff(), last_trade=last_trade(at=later),
        confirmation_close=minute_close(at=later), failure_bar=failure_bar(at=later),
        acceptance=acceptance(at=later), quote=decision(at=later),
        structural=structural(at=later), confidence=confidence(at=later)))
    assert result.gate(HANDOFF_GATE).reason == "HANDOFF_NOT_CURRENT"
    assert result.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)


def test_the_handoff_gate_keeps_the_records_that_handoff_read():
    gate = evaluate_or_failure_rev(request()).gate(HANDOFF_GATE)
    assert "opening-range" in gate.input_record_ids
    assert "m81-breakout-extreme" in gate.input_record_ids


# --- the supplied last trade and its displacement -----------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_last_trade_still_outside_the_failed_edge_is_not_a_reversal(direction):
    result = evaluate_or_failure_rev(request(
        direction, last_trade=last_trade(direction, price=EXTREME["LONG"])))
    assert result.gate(LAST_GATE).reason == "LAST_NOT_BACK_INSIDE_RANGE"
    assert result.gate(LAST_GATE).threshold == pytest.approx(
        RANGE[direction][0] if direction == "LONG" else RANGE[direction][1])
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_last_trade_that_only_just_slipped_inside_is_refused(direction):
    result = evaluate_or_failure_rev(request(direction, last_trade=last_trade(
        direction, price=100.99)))
    gate = result.gate(DISPLACEMENT_GATE)
    assert gate.reason == "DISPLACEMENT_BELOW_SUPPLIED_MINIMUM"
    assert gate.observed == pytest.approx(0.01) and gate.threshold == pytest.approx(0.02)
    assert result.gate(LAST_GATE).status == "PASS"
    assert result.state == StrategyState("ARMED")


def test_the_same_slight_move_passes_under_a_smaller_supplied_minimum():
    result = evaluate_or_failure_rev(request(
        last_trade=last_trade(price=100.99),
        policy=policy(min_displacement_atr_multiple=0.025)))
    assert result.gate(DISPLACEMENT_GATE).status == "PASS"
    assert result.required_displacement == pytest.approx(0.01)


@pytest.mark.parametrize("changes,status,reason", (
    ({"coverage_known": False}, "FAIL", "COVERAGE_LOST"),
    ({"available_at": ENDED_AT + timedelta(minutes=1)}, "UNKNOWN",
     "LAST_TRADE_OBSERVATION_NOT_AVAILABLE"),
    ({"price": None, "missing_reason": "NO_TRADE_OBSERVED"}, "UNKNOWN",
     "LAST_TRADE_NO_TRADE_OBSERVED"),
    ({"age": None}, "UNKNOWN", "LAST_TRADE_OBSERVATION_AGE_UNKNOWN"),
    ({"age": 9.0}, "UNKNOWN", "LAST_TRADE_STALE_OBSERVATION"),
    ({"mode": "QUOTE_PROJECTED"}, "UNKNOWN", "LAST_TRADE_WRONG_ARM"),
))
def test_an_unusable_last_trade_never_becomes_a_passing_gate(changes, status, reason):
    result = evaluate_or_failure_rev(request(last_trade=last_trade(**changes)))
    for name in (LAST_GATE, DISPLACEMENT_GATE, EXTENSION_GATE):
        assert (result.gate(name).status, result.gate(name).reason) == (status, reason)
    assert result.inside_distance is None and result.extension_r_multiple is None
    assert result.state == (StrategyState("INVALIDATED") if status == "FAIL"
                            else StrategyState("ARMED"))


def test_a_missing_last_trade_still_reports_the_required_displacement():
    result = evaluate_or_failure_rev(request(last_trade=None))
    gate = result.gate(DISPLACEMENT_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "LAST_TRADE_LAST_TRADE_UNAVAILABLE")
    assert gate.threshold == pytest.approx(0.02)


# --- the supplied confirmation close ----------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_close_outside_the_range_does_not_confirm_the_failure(direction):
    result = evaluate_or_failure_rev(request(
        direction, confirmation_close=minute_close(direction, close=EXTREME[direction])))
    assert result.gate(CONFIRMATION_GATE).reason == "CLOSE_NOT_BACK_INSIDE_RANGE"
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("changes,status,reason", (
    ({"coverage_known": False}, "FAIL", "COVERAGE_LOST"),
    ({"available_at": ENDED_AT + timedelta(minutes=1)}, "UNKNOWN",
     "CONFIRMATION_NOT_AVAILABLE"),
    ({"final": False, "close": None}, "UNKNOWN", "MINUTE_BAR_PENDING"),
    ({"bar_end": CROSS}, "FAIL", "CONFIRMATION_BEFORE_CROSSING"),
))
def test_an_unusable_confirmation_close_never_becomes_a_passing_gate(changes, status, reason):
    result = evaluate_or_failure_rev(request(confirmation_close=minute_close(**changes)))
    gate = result.gate(CONFIRMATION_GATE)
    assert (gate.status, gate.reason) == (status, reason)
    assert result.state == (StrategyState("INVALIDATED") if reason == "COVERAGE_LOST"
                            else StrategyState("ARMED"))


def test_a_missing_confirmation_close_keeps_the_reversal_armed_only():
    result = evaluate_or_failure_rev(request(confirmation_close=None))
    assert result.gate(CONFIRMATION_GATE).reason == "MISSING_CONFIRMATION_CLOSE"
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("changes,status,reason", (
    ({"coverage_known": False}, "FAIL", "COVERAGE_LOST"),
    ({"available_at": ENDED_AT + timedelta(minutes=1)}, "UNKNOWN",
     "FAILURE_BAR_NOT_AVAILABLE"),
    ({"final": False, "high": None, "low": None}, "UNKNOWN", "MINUTE_BAR_PENDING"),
    ({"bar_end": CROSS}, "FAIL", "FAILURE_BAR_BEFORE_CROSSING"),
))
def test_an_unusable_failure_bar_never_becomes_a_passing_gate(changes, status, reason):
    result = evaluate_or_failure_rev(request(
        policy=policy(confirmation=FAILURE_BAR_CONFIRMATION), failure_bar=failure_bar(**changes)))
    gate = result.gate(CONFIRMATION_GATE)
    assert (gate.status, gate.reason) == (status, reason)
    assert result.state == (StrategyState("INVALIDATED") if reason == "COVERAGE_LOST"
                            else StrategyState("ARMED"))


# --- the supplied inside acceptance -----------------------------------------


def test_an_acceptance_below_the_callers_own_minimum_is_refused():
    result = evaluate_or_failure_rev(request(acceptance=acceptance(share=0.40)))
    gate = result.gate(ACCEPTANCE_GATE)
    assert gate.reason == "ACCEPTANCE_BELOW_SUPPLIED_MINIMUM"
    assert gate.observed == pytest.approx(0.40) and gate.threshold == pytest.approx(ACCEPTANCE)
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("changes,reason", (
    ({"share": None, "missing_reason": "NO_INSIDE_COVERAGE"}, "NO_INSIDE_COVERAGE"),
    ({"coverage_complete": False}, "ACCEPTANCE_COVERAGE_INCOMPLETE"),
    ({"at": ENDED_AT + timedelta(minutes=1)}, "ACCEPTANCE_NOT_AVAILABLE"),
))
def test_an_unusable_acceptance_share_stays_unknown(changes, reason):
    result = evaluate_or_failure_rev(request(acceptance=acceptance(**changes)))
    gate = result.gate(ACCEPTANCE_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.acceptance_share is None and result.state == StrategyState("ARMED")


def test_a_missing_acceptance_record_is_never_full_acceptance():
    result = evaluate_or_failure_rev(request(acceptance=None))
    assert result.gate(ACCEPTANCE_GATE).reason == "MISSING_INSIDE_ACCEPTANCE"
    assert result.state == StrategyState("ARMED")


# --- the supplied quote spread ----------------------------------------------


def test_a_spread_above_the_callers_own_limit_is_refused():
    result = evaluate_or_failure_rev(request(policy=policy(max_spread_bps=0.5)))
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
    result = evaluate_or_failure_rev(request(quote=decision(at=ENDED_AT, **changes)))
    gate = result.gate(SPREAD_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.spread_bps is None and result.state == StrategyState("ARMED")


def test_a_stale_or_absent_quote_decision_stays_unknown():
    stale = evaluate_or_failure_rev(request(quote=decision(at=ENDED_AT, age=9)))
    assert stale.gate(SPREAD_GATE).reason in ("STALE_QUOTE", "QUOTE_STREAM_QUOTE_STALE")
    absent = evaluate_or_failure_rev(request(quote=None))
    assert absent.gate(SPREAD_GATE).reason == "QUOTE_DECISION_ABSENT"
    assert absent.state == StrategyState("ARMED")


# --- the supplied staleness --------------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_reversal_that_already_ran_past_the_callers_maximum_is_stale(direction):
    result = evaluate_or_failure_rev(request(
        direction, policy=policy(max_extension_r_multiple=0.25)))
    gate = result.gate(EXTENSION_GATE)
    assert gate.reason == "STALE_EXTENSION_BEYOND_SUPPLIED_MAXIMUM"
    assert gate.reason in INVALIDATIONS
    assert gate.observed == pytest.approx(0.30 / RISK_PER_SHARE)
    assert result.state == StrategyState("INVALIDATED")


def test_staleness_without_supplied_risk_stays_unknown():
    result = evaluate_or_failure_rev(request(
        structural=structural(risk=None, targets=(), missing_reason="STOP_SOURCE_UNAVAILABLE")))
    gate = result.gate(EXTENSION_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "EXTENSION_STOP_SOURCE_UNAVAILABLE")
    assert evaluate_or_failure_rev(request(structural=None)).gate(
        EXTENSION_GATE).reason == "EXTENSION_RISK_UNAVAILABLE"
    assert result.state == StrategyState("ARMED")


# --- the supplied stop and targets ------------------------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"direction": "LONG"}, "GEOMETRY_DIRECTION_MISMATCH"),
    ({"attempt_number": 2}, "GEOMETRY_ATTEMPT_MISMATCH"),
    ({"crossed_at": CROSS - timedelta(minutes=1)}, "GEOMETRY_CROSSING_MISMATCH"),
    ({"evaluated_at": ENDED_AT + timedelta(seconds=1)}, "GEOMETRY_NOT_CURRENT"),
    ({"available_at": ENDED_AT + timedelta(seconds=1)}, "GEOMETRY_NOT_YET_AVAILABLE"),
))
def test_a_reading_framed_on_another_structure_is_not_this_geometry(changes, reason):
    result = evaluate_or_failure_rev(request(structural=replace(structural(), **changes)))
    gate = result.gate(RISK_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.risk is None and result.targets == ()
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_an_entry_outside_the_failed_range_is_refused(direction):
    result = evaluate_or_failure_rev(request(direction, structural=structural(
        direction, risk=risk_level(direction, entry=101.30, stop=101.95, distance=0.65))))
    assert result.gate(RISK_GATE).reason == "ENTRY_NOT_INSIDE_OPENING_RANGE"
    assert result.state == StrategyState("ARMED")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_stop_short_of_the_breakout_extreme_is_refused(direction):
    # The wider supplied maximum keeps the narrower supplied risk from also
    # reporting a stale extension, so this case isolates the stop itself.
    result = evaluate_or_failure_rev(request(
        direction, policy=policy(max_extension_r_multiple=0.80),
        structural=structural(direction, risk=risk_level(
            direction, stop=101.10, distance=0.40))))
    assert result.gate(RISK_GATE).reason == "STOP_NOT_BEYOND_BREAKOUT_EXTREME"
    assert result.state == StrategyState("ARMED")


def test_a_stop_on_the_wrong_side_of_the_entry_is_refused():
    result = evaluate_or_failure_rev(request(structural=structural(
        risk=risk_level(entry=100.70, stop=100.05, distance=0.65))))
    assert result.gate(RISK_GATE).reason == "STOP_ON_THE_WRONG_SIDE"


@pytest.mark.parametrize("supplied,reason", (
    (((101.20, 0.30), (100.00, 1.00)), "TARGET_NOT_BEYOND_ENTRY"),
    (((100.50, 0.95), (100.00, 1.00)), "TARGET_R_MULTIPLE_OVERSTATED"),
    (((100.65, 0.07), (100.00, 1.00)), "FIRST_TARGET_BELOW_SUPPLIED_MINIMUM"),
))
def test_a_target_the_supplied_prices_do_not_support_is_refused(supplied, reason):
    result = evaluate_or_failure_rev(request(structural=structural(
        targets=targets(supplied=supplied))))
    assert result.gate(RISK_GATE).reason == reason
    assert result.state == StrategyState("ARMED")


def test_a_breakout_extreme_that_disagrees_with_the_handoff_is_refused():
    result = evaluate_or_failure_rev(request(breakout_extreme_price=101.40))
    assert result.gate(RISK_GATE).reason == "BREAKOUT_EXTREME_DISAGREES_WITH_HANDOFF"
    missing = evaluate_or_failure_rev(request(breakout_extreme_price=None))
    assert missing.gate(RISK_GATE).reason == "MISSING_BREAKOUT_EXTREME"
    assert result.state == StrategyState("ARMED")


def test_a_handoff_without_its_own_excursion_cannot_place_the_stop():
    from test_or_failure_handoff import extreme

    supplied = handoff(breakout_extreme=extreme(price=None))
    result = evaluate_or_failure_rev(request(handoff=supplied))
    assert result.gate(RISK_GATE).reason == "HANDOFF_EXCURSION_UNAVAILABLE"


# --- the supplied confidence -------------------------------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"supplied_policy": "OTHER_STRATEGY"}, "CONFIDENCE_STRATEGY_MISMATCH"),
    ({"supplied_policy": "OTHER_VERSION"}, "CONFIDENCE_VERSION_MISMATCH"),
    ({"reversal": "LONG"}, "CONFIDENCE_DIRECTION_MISMATCH"),
    ({"at": ENDED_AT - timedelta(seconds=1)}, "CONFIDENCE_NOT_CURRENT"),
))
def test_a_confidence_result_for_another_subject_stays_unknown(changes, reason):
    if changes.get("supplied_policy") == "OTHER_STRATEGY":
        changes["supplied_policy"] = confidence_policy(strategy_id="CRVOL_ORB5")
    if changes.get("supplied_policy") == "OTHER_VERSION":
        changes["supplied_policy"] = confidence_policy(strategy_version="M82_OTHER_VERSION")
    result = evaluate_or_failure_rev(request(confidence=confidence(**changes)))
    gate = result.gate(CONFIDENCE_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", reason)
    assert result.confidence is None and result.state == StrategyState("ARMED")


def test_an_incomplete_confidence_composition_never_passes():
    supplied = confidence(missing="setup-score")
    assert supplied.status != "READY"
    result = evaluate_or_failure_rev(request(confidence=supplied))
    assert result.gate(CONFIDENCE_GATE).status == "UNKNOWN"
    assert result.gate(CONFIDENCE_GATE).reason.startswith("CONFIDENCE_")
    assert evaluate_or_failure_rev(request(confidence=None)).gate(
        CONFIDENCE_GATE).reason == "CONFIDENCE_UNAVAILABLE"


def test_no_confidence_cutoff_is_applied_to_a_low_supplied_score():
    result = evaluate_or_failure_rev(request())
    assert result.confidence.final_score == pytest.approx(
        .5 * SCORES[0] + .3 * SCORES[1] + .2 * SCORES[2])
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable


# --- the reported result -----------------------------------------------------


def test_every_reported_gate_name_is_a_supported_one():
    assert tuple(row.name for row in evaluate_or_failure_rev(request()).gates) == REVERSAL_GATES


def test_the_result_names_what_no_approved_definition_supplies():
    assert evaluate_or_failure_rev(request()).unavailable == UNDEFINED
    assert "STOP_PAD_UNDEFINED" in UNDEFINED
    assert "FAILURE_TIMER_ORIGIN_UNDEFINED" in UNDEFINED


def test_the_same_supplied_request_renders_the_same_json():
    supplied = request()
    first, second = (evaluate_or_failure_rev(supplied) for _ in range(2))
    assert first.to_json() == second.to_json()
    payload = json.loads(first.to_json())
    assert payload["reversal_version"] == REVERSAL_VERSION
    assert payload["strategy_id"] == STRATEGY_ID
    assert payload["direction"] == "SHORT" and payload["break_direction"] == "LONG"
    assert payload["state"] == "ALERT_TRIGGERED" and payload["substate"] is None
    assert payload["candidate"]["boundary"] == BOUNDARY["LONG"]
    assert payload["risk"]["hard_stop"] == STOP
    assert [row["name"] for row in payload["targets"]] == ["T1", "T2"]
    assert payload["policy_version"] == POLICY_VERSION


def test_the_result_is_immutable_and_needs_a_canonical_request():
    result = evaluate_or_failure_rev(request())
    with pytest.raises(FrozenInstanceError):
        result.state = StrategyState("INVALIDATED")
    with pytest.raises(RecordError):
        evaluate_or_failure_rev("M82")
    assert isinstance(result, ReversalAssessment)


def test_the_module_adopts_no_number_of_its_own():
    namespace = vars(or_failure_rev)
    assert not [name for name, value in namespace.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)]
    source = inspect.getsource(or_failure_rev)
    for token in ("0.70", "0.40", "0.03", "0.05", "0.08", "0.65", "1.5", "180"):
        assert token not in source


# --- the reversal owner ------------------------------------------------------


def test_the_owner_refuses_inputs_that_are_not_its_own():
    with pytest.raises(RecordError):
        owner("LONG").propose(request(), record_id="m82-armed")
    with pytest.raises(RecordError):
        owner().propose(request(policy=policy(max_spread_bps=10.0)), record_id="m82-armed")
    with pytest.raises(RecordError):
        owner().propose("M82", record_id="m82-armed")


def test_a_first_actionable_evaluation_records_the_prior_before_the_action():
    subject = owner()
    assessment, changes = subject.propose(request(), record_id="m82-armed",
                                          staged_record_id="m82-actionable")
    assert assessment.state == StrategyState("ALERT_TRIGGERED")
    assert len(changes) == 2
    assert (changes[0].from_substate, changes[0].to_state) == (FAILURE_FORMING, "ARMED")
    assert changes[0].reason == "REVERSAL_PRIOR_ARMED"
    assert (changes[1].from_state, changes[1].to_state) == ("ARMED", "ALERT_TRIGGERED")
    assert changes[1].record_id == "m82-actionable"
    assert changes[1].reason == "ALL_SUPPLIED_REVERSAL_GATES_PASSED"
    assert all(row.strategy_id == STRATEGY_ID for row in changes)
    assert all(row.metadata.data_mode == DATA_MODE for row in changes)


def test_a_two_step_evaluation_without_its_second_id_is_refused():
    with pytest.raises(RecordError):
        owner().propose(request(), record_id="m82-armed")


def test_a_single_step_evaluation_cannot_use_a_second_id():
    with pytest.raises(RecordError):
        owner().propose(request(acceptance=None), record_id="m82-armed",
                        staged_record_id="m82-unused")


def test_the_owner_advances_only_after_the_caller_confirms_the_recording():
    subject = owner()
    _, changes = subject.propose(request(acceptance=None), record_id="m82-armed")
    assert subject.current_state() == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert subject.confirm(*changes) == StrategyState("ARMED")
    assert subject.current_candidate() == candidate("LONG")
    with pytest.raises(RecordError):
        subject.confirm(*changes)


def test_a_different_break_cannot_replace_the_one_already_taken_over():
    subject = owner()
    _, changes = subject.propose(request(acceptance=None), record_id="m82-armed")
    subject.confirm(*changes)
    later = ENDED_AT + timedelta(minutes=2)
    other = request(at=later, acceptance=None,
                    handoff=handoff(at=later, attempt=None) if False else handoff(at=later))
    other = replace(other, handoff=replace(
        other.handoff, candidate=replace(other.handoff.candidate, attempt_number=2)))
    with pytest.raises(RecordError):
        subject.propose(other, record_id="m82-second")


def test_an_actionable_reversal_cannot_fall_back_or_reopen():
    subject = owner()
    _, changes = subject.propose(request(), record_id="m82-armed",
                                 staged_record_id="m82-actionable")
    assert subject.confirm(*changes) == StrategyState("ALERT_TRIGGERED")
    assert subject.last_action_at == ENDED_AT
    with pytest.raises(RecordError):
        subject.propose(request(acceptance=None), record_id="m82-back")


def test_an_armed_reversal_is_closed_rather_than_silently_dropped():
    subject = owner()
    _, changes = subject.propose(request(acceptance=None), record_id="m82-armed")
    subject.confirm(*changes)
    withdrawn = request(acceptance=None, handoff=handoff(opening_range=None))
    assessment, later = subject.propose(withdrawn, record_id="m82-withdrawn")
    assert assessment.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert later[0].to_state == "INVALIDATED"
    assert subject.confirm(*later) == StrategyState("INVALIDATED")
    with pytest.raises(RecordError):
        subject.propose(request(acceptance=None), record_id="m82-reopen")


def test_an_unchanged_evaluation_proposes_nothing():
    subject = owner()
    assessment, changes = subject.propose(request(handoff=handoff(opening_range=None)),
                                          record_id="m82-none")
    assert assessment.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert changes == ()
    with pytest.raises(RecordError):
        subject.confirm()


def test_evaluation_time_cannot_move_backward():
    subject = owner()
    _, changes = subject.propose(request(acceptance=None), record_id="m82-armed")
    subject.confirm(*changes)
    earlier = CROSS + timedelta(seconds=5)
    with pytest.raises(RecordError):
        subject.propose(request(at=earlier, acceptance=None, handoff=handoff(at=earlier),
                                last_trade=last_trade(at=earlier),
                                confirmation_close=minute_close(at=earlier),
                                failure_bar=failure_bar(at=earlier), quote=decision(at=earlier),
                                structural=structural(at=earlier),
                                confidence=confidence(at=earlier)),
                        record_id="m82-backward")


def test_the_owner_can_expire_and_names_its_own_reason():
    subject = owner()
    changes = subject.expire(at=ENDED_AT, reason="SESSION_WINDOW_CLOSED", record_id="m82-expire")
    assert subject.confirm(*changes) == StrategyState("EXPIRED")
    with pytest.raises(RecordError):
        owner().expire(at=ENDED_AT, reason=" ", record_id="m82-expire")


@pytest.mark.parametrize("changes", (
    {"session": "M82"}, {"policy": "M82"}, {"instrument_type": "OPTION"},
    {"direction": "BOTH"}, {"symbol": " "}, {"strategy_version": "UNKNOWN"},
))
def test_the_owner_requires_explicit_identity(changes):
    with pytest.raises(RecordError):
        owner(**changes)


def test_restore_positions_an_unused_owner_on_explicit_saved_facts():
    subject = owner()
    state = subject.restore(StrategyState("ALERT_TRIGGERED"), candidate=candidate("LONG"),
                            last_action_at=ENDED_AT)
    assert state == StrategyState("ALERT_TRIGGERED")
    assert subject.current_candidate() == candidate("LONG")
    assert subject.last_action_at == ENDED_AT
    with pytest.raises(RecordError):
        subject.restore(StrategyState("ARMED"))


@pytest.mark.parametrize("changes", (
    {"state": StrategyState("WATCHING")}, {"state": "ARMED"},
    {"state": StrategyState("SETUP_FORMING")},
    {"state": StrategyState("SETUP_FORMING", "OTHER")}, {"candidate": "M82"},
    {"last_action_at": "2026-07-06T06:50:10"},
))
def test_restore_refuses_facts_that_are_not_m82_ones(changes):
    values = dict(state=StrategyState("ARMED"))
    values.update(changes)
    state = values.pop("state")
    with pytest.raises(RecordError):
        owner().restore(state, **values)


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           reversal_rules())


def context(direction="SHORT", *, assessment, at=ENDED_AT, snapshot=None):
    ids = tuple(sorted({value for row in assessment.gates for value in row.input_record_ids}))
    provenance = FeatureSnapshot(
        record_id="m82-reversal-inputs", metadata=metadata(at, data_mode=DATA_MODE),
        evaluated_at=at,
        features=(FeatureValue("OR_FAILURE_REV_INPUTS_V1", 1.0, "BOOLEAN", None, ids),),
        feature_version="M82_SYNTHETIC_INPUTS_V1", input_record_ids=ids)
    return StrategyContext(
        session(DAY), "SYNTH", "EQUITY", direction, at,
        (snapshot if snapshot is not None else opening_range(mirror_direction(direction)),
         provenance))


async def test_a_refused_recording_leaves_the_owner_where_it_was():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = owner()
    assessment, changes = subject.propose(request(acceptance=None), record_id="m82-armed")
    engine = StateTransitionEngine(scope("SHORT"), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(changes[0], context=context(assessment=assessment))
    assert engine.current_state() == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert subject.current_state() == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert subject.current_candidate() is None


async def test_the_supplied_reversal_through_the_m42_engine_and_m51_store():
    proofs = []
    connection = await db.init_db()
    for direction in ("LONG", "SHORT"):
        reversal = mirror_direction(direction)
        subject = owner(reversal)
        engine = StateTransitionEngine(scope(reversal), SQLiteTransitionStore(connection))
        store = ResearchEventStore(connection)

        armed_request = request(direction, acceptance=None)
        first, armed = subject.propose(armed_request, record_id="m82-armed-" + direction)
        assert first.state == StrategyState("ARMED")
        opened = await engine.apply(armed[0], context=context(
            reversal, assessment=first, snapshot=opening_range(direction)))
        assert subject.confirm(*armed) == StrategyState("ARMED")

        supplied = request(direction)
        assessment, changes = subject.propose(supplied, record_id="m82-actionable-" + direction)
        assert assessment.state == StrategyState("ALERT_TRIGGERED")
        assert assessment.reasons == ()
        entry = await engine.apply(changes[0], context=context(
            reversal, assessment=assessment, snapshot=opening_range(direction)))
        assert engine.current_state() == StrategyState("ALERT_TRIGGERED")
        assert subject.confirm(*changes) == StrategyState("ALERT_TRIGGERED")

        stored = await store.append(changes[0], session=DAY, recorded_at=ENDED_AT)
        assert stored["kind"] == "STATE_TRANSITION"
        assert await store.append(changes[0], session=DAY, recorded_at=ENDED_AT) == stored

        repeated = evaluate_or_failure_rev(supplied)
        assert repeated.to_json() == assessment.to_json()
        proofs.append({
            "synthetic_only": True, "break_direction": direction, "direction": reversal,
            "armed_assessment": first.as_dict(), "assessment": assessment.as_dict(),
            "armed_transition": armed[0].as_dict(), "transition": changes[0].as_dict(),
            "armed_position": opened.position, "stored_position": entry.position,
            "stored_fingerprint": stored["fingerprint"],
            "gate_sha256": hashlib.sha256("".join(
                json.dumps(row.as_dict(), sort_keys=True)
                for row in assessment.gates).encode()).hexdigest(),
            "repeated_assessment_identical": True,
        })
    await db.close_db()
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "reversal_version": REVERSAL_VERSION, "runs": proofs}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m8_2_or_failure_rev_proof.json").write_text(rendered)
