"""M8.1 supplied-input ORB-to-failure handoff contracts; no approved rule is adopted.

Every number below is a synthetic fixture supplied by the caller. A passing gate
proves the offline contract only: it establishes no provider coverage, no adopted
`OR_FAILURE_REV` rule, no alert and no permission to act. FAILURE_FORMING here
means the supplied records supported a handoff at one instant in a test process.

The opening range is the real M3.6 snapshot, the ended attempt is the real M6.2
assessment, and the recorded transitions go through the real M4.2 engine.
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

from consensus_engine import db, or_failure_handoff
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.opening_range_features import FEATURE_VERSION as RANGE_VERSION
from consensus_engine.or_failure_handoff import (
    BREAKOUT_ATTEMPT, DATA_MODE, ENDED_GATE, EXCURSION_GATE, FAILED_BREAK_ENDINGS,
    FAILURE_FORMING, HANDOFF_GATES, HANDOFF_VERSION, BreakoutExtreme, HandoffAssessment,
    HandoffGate, HandoffPolicy, HandoffRequest, INVALIDATIONS, OWNERSHIP_GATE,
    OrFailureHandoffMachine, RANGE_GATE, REACCEPTANCE_GATE, RULES_VERSION,
    SOURCE_ORB_STRATEGY_ID, STRATEGY_ID, evaluate_or_failure_handoff, handoff_rules,
    mirror_direction,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, SourceMetadata,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_opening_range_features import at as range_at, history, snapshot as range_snapshot
from test_orb5_trigger import (
    BOUNDARY, CROSS, DAY, RANGE, TRIGGER, candidate, minute_close, request as orb_request,
)
from test_strategy_interface import session


VERSION = "M81_FIXTURE_ONLY_V1"
POLICY_VERSION = "M81_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M81_SUPPLIED_FIXTURE_DEFINITION"
# The supplied M6.2 attempt ends ten seconds after its crossing, and the handoff
# is evaluated at that same instant. None of these numbers is an adopted rule.
ENDED_AT = TRIGGER
LATE = CROSS + timedelta(seconds=40)
# The furthest supplied traded price of the break, and a one-tick twin that is
# beyond the frozen boundary but short of the caller's own minimum excursion.
EXTREME = {"LONG": 101.30, "SHORT": 49.70}
ONE_TICK = {"LONG": 101.03, "SHORT": 49.97}
INSIDE = {"LONG": 100.50, "SHORT": 50.50}


def policy(**changes):
    values = dict(version=POLICY_VERSION, definition_reference=DEFINITION,
                  minimum_excursion_atr_multiple=0.25, reacceptance_window_seconds=180,
                  owns_after_alert_triggered=False)
    values.update(changes)
    return HandoffPolicy(**values)


def opening_range(direction="LONG", **changes):
    """The real M3.6 snapshot whose extrema are this attempt's frozen range."""
    high, low = RANGE[direction]

    def fixed(bars):
        return [replace(bar, high=high, low=low, open=low, close=high) for bar in bars]

    values = dict(minute_history=history(DAY, changed=fixed), evaluated=range_at("06:35:00", DAY))
    values.update(changes)
    return range_snapshot(**values)


def attempt(direction="LONG", *, ending="INSIDE_OR_CLOSE_INVALIDATION", at=ENDED_AT, **changes):
    """One real M6.2 assessment for the supplied ending this handoff reads."""
    values = dict(direction=direction, at=at)
    if ending == "INSIDE_OR_CLOSE_INVALIDATION":
        values["minute_close"] = minute_close(at=at, close=INSIDE[direction])
    elif ending == "ACCEPTANCE_DEADLINE_PASSED":
        values["at"] = LATE
    elif ending == "COVERAGE_LOST":
        values["minute_close"] = minute_close(at=at, close=INSIDE[direction],
                                              coverage_known=False)
    elif ending == "EVALUATION_OFF_GRID":
        values["at"] = CROSS + timedelta(milliseconds=10500)
    elif ending != "STILL_OPEN":
        raise AssertionError("unsupported supplied ending fixture")
    values.update(changes)
    result = orb_request(**values)
    from consensus_engine.orb5_trigger import evaluate_orb5_trigger

    assessment = evaluate_orb5_trigger(result)
    gate = assessment.gate("ATTEMPT_ACTIVE")
    if ending == "STILL_OPEN":
        assert gate.status == "PASS"
    else:
        assert gate.reason == ending
    return assessment


def extreme(direction="LONG", **changes):
    values = dict(record_id="m81-breakout-extreme", observed_at=CROSS + timedelta(seconds=2),
                  available_at=CROSS + timedelta(seconds=2), price=EXTREME[direction],
                  coverage_known=True)
    values.update(changes)
    return BreakoutExtreme(**values)


def reacceptance(direction="LONG", *, at=ENDED_AT, **changes):
    values = dict(at=at, close=INSIDE[direction], record_id="m81-reacceptance-close")
    values.update(changes)
    return minute_close(**values)


def request(direction="LONG", *, at=ENDED_AT, **changes):
    """One handoff evaluation of a failed break into its reversal direction."""
    values = dict(
        symbol="SYNTH", instrument_type="EQUITY", attempt=attempt(direction, at=at),
        policy=policy(), evaluated_at=at, opening_range=opening_range(direction),
        breakout_extreme=extreme(direction), minute_close=reacceptance(direction, at=at),
        attempt_reached_alert=False,
    )
    values.update(changes)
    return HandoffRequest(**values)


def owner(direction="SHORT", **changes):
    values = dict(session=session(DAY), symbol="SYNTH", instrument_type="EQUITY",
                  direction=direction, strategy_version=VERSION, policy=policy())
    values.update(changes)
    return OrFailureHandoffMachine(**values)


def provenance(assessment, *, at=ENDED_AT, record_id="m81-handoff-inputs"):
    """One supplied feature snapshot naming the raw records this handoff read."""
    ids = tuple(sorted({value for row in assessment.gates for value in row.input_record_ids}))
    metadata = SourceMetadata(
        instrument_id="SYNTH", instrument_type="EQUITY", source="SYNTHETIC", source_time=at,
        received_time=at, available_time=at, normalized_time=at, session=DAY,
        data_mode="SYNTHETIC_HANDOFF_INPUTS", quality="VALID")
    return FeatureSnapshot(
        record_id=record_id, metadata=metadata, evaluated_at=at,
        features=(FeatureValue("OR_FAILURE_HANDOFF_INPUTS_V1", 1.0, "BOOLEAN", None, ids),),
        feature_version="M81_SYNTHETIC_INPUTS_V1", input_record_ids=ids)


def context(direction="SHORT", *, assessment, at=ENDED_AT, snapshot=None):
    return StrategyContext(
        session=session(DAY), symbol="SYNTH", instrument_type="EQUITY", direction=direction,
        evaluated_at=at,
        features=(snapshot if snapshot is not None else opening_range(
            mirror_direction(direction)), provenance(assessment, at=at)))


# --- supplied policy and record contracts -----------------------------------


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNKNOWN"}, {"definition_reference": "UNSPECIFIED"},
    {"definition_reference": ""}, {"minimum_excursion_atr_multiple": 0.0},
    {"minimum_excursion_atr_multiple": -0.25}, {"minimum_excursion_atr_multiple": "0.25"},
    {"minimum_excursion_atr_multiple": True}, {"minimum_excursion_atr_multiple": float("nan")},
    {"minimum_excursion_atr_multiple": float("inf")}, {"reacceptance_window_seconds": 0},
    {"reacceptance_window_seconds": 180.0}, {"reacceptance_window_seconds": -180},
    {"owns_after_alert_triggered": "false"}, {"owns_after_alert_triggered": 0},
))
def test_policy_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        policy(**changes)


def test_policy_is_immutable_and_renders_its_supplied_values():
    supplied = policy()
    with pytest.raises(FrozenInstanceError):
        supplied.minimum_excursion_atr_multiple = 0.5
    assert supplied.as_dict()["definition_reference"] == DEFINITION
    assert supplied.as_dict()["owns_after_alert_triggered"] is False


@pytest.mark.parametrize("changes", (
    {"record_id": " "}, {"record_id": "UNKNOWN"}, {"observed_at": "2026-07-06T06:50:02"},
    {"observed_at": datetime(2026, 7, 6, 6, 50, 2)}, {"available_at": None},
    {"price": 0.0}, {"price": -1.0}, {"price": "101.30"}, {"coverage_known": 1},
))
def test_breakout_extreme_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        extreme(**changes)


def test_an_unknown_breakout_price_stays_explicitly_unknown():
    supplied = extreme(price=None)
    assert supplied.price is None and supplied.as_dict()["price"] is None
    assert supplied.as_dict()["coverage_known"] is True


@pytest.mark.parametrize("changes", (
    {"name": "OTHER_GATE"}, {"status": "MAYBE"}, {"status": "FAIL", "reason": None},
    {"status": "UNKNOWN", "reason": " "}, {"input_record_ids": ["a"]},
    {"input_record_ids": (" ",)},
))
def test_gate_requires_supported_name_status_and_reason(changes):
    values = dict(name=ENDED_GATE, status="FAIL", reason="ORB_ATTEMPT_STILL_OPEN")
    values.update(changes)
    with pytest.raises(RecordError):
        HandoffGate(**values)


@pytest.mark.parametrize("changes", (
    {"symbol": " "}, {"instrument_type": "OPTION"}, {"attempt": "M81"},
    {"policy": "M81"}, {"evaluated_at": CROSS - timedelta(seconds=1)},
    {"opening_range": "M81"}, {"breakout_extreme": "M81"}, {"minute_close": "M81"},
    {"attempt_reached_alert": "no"},
))
def test_request_requires_canonical_supplied_inputs(changes):
    with pytest.raises(RecordError):
        request(**changes)


def test_the_handoff_direction_mirrors_the_supplied_break():
    assert mirror_direction("LONG") == "SHORT" and mirror_direction("SHORT") == "LONG"
    with pytest.raises(RecordError):
        mirror_direction("BOTH")
    assert request("LONG").direction == "SHORT"
    assert request("SHORT").direction == "LONG"


# --- the supplied rules ------------------------------------------------------


def test_the_rules_stop_before_the_or_failure_rev_armed_state():
    rules = handoff_rules()
    assert rules.version == RULES_VERSION
    assert rules.initial_state == StrategyState("WATCHING")
    states = {state for pair in rules.allowed for state in pair}
    assert not any(state.state in ("ARMED", "ALERT_TRIGGERED") for state in states)
    assert StrategyState("SETUP_FORMING", FAILURE_FORMING) in states


def test_the_rules_hold_exactly_the_supplied_handoff_pairs():
    watching = StrategyState("WATCHING")
    attempting = StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
    failing = StrategyState("SETUP_FORMING", FAILURE_FORMING)
    invalidated, expired = StrategyState("INVALIDATED"), StrategyState("EXPIRED")
    assert set(handoff_rules().allowed) == {
        (watching, attempting), (attempting, failing), (attempting, invalidated),
        (failing, invalidated), (invalidated, watching),
        (watching, expired), (attempting, expired), (failing, expired), (invalidated, expired),
    }


# --- one supplied failed break ----------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_supplied_failed_break_hands_over_to_the_reversal_direction(direction):
    result = evaluate_or_failure_handoff(request(direction))
    assert result.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert result.direction == mirror_direction(direction) and result.reasons == ()
    assert all(row.status == "PASS" for row in result.gates)
    assert result.candidate == candidate(direction)
    assert result.excursion == pytest.approx(0.30)
    assert result.required_excursion == pytest.approx(0.10)
    assert result.reacceptance_seconds == pytest.approx(10.0)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_deadline_ending_without_its_reacceptance_stays_at_the_breakout_attempt(direction):
    result = evaluate_or_failure_handoff(request(
        direction, at=LATE, attempt=attempt(direction, ending="ACCEPTANCE_DEADLINE_PASSED"),
        minute_close=None))
    assert result.state == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
    assert result.gate(ENDED_GATE).status == "PASS"
    assert result.gate(REACCEPTANCE_GATE).reason == "MISSING_REACCEPTANCE_CLOSE"
    assert result.reacceptance_seconds is None


def test_both_supplied_failed_endings_are_accepted_and_named():
    assert FAILED_BREAK_ENDINGS == ("INSIDE_OR_CLOSE_INVALIDATION", "ACCEPTANCE_DEADLINE_PASSED")
    for ending in FAILED_BREAK_ENDINGS:
        at = LATE if ending == "ACCEPTANCE_DEADLINE_PASSED" else ENDED_AT
        result = evaluate_or_failure_handoff(request(
            at=at, attempt=attempt(ending=ending), minute_close=reacceptance(at=at)))
        assert result.gate(ENDED_GATE).status == "PASS"


@pytest.mark.parametrize("ending,status,reason", (
    ("STILL_OPEN", "FAIL", "ORB_ATTEMPT_STILL_OPEN"),
    ("COVERAGE_LOST", "FAIL", "ORB_ATTEMPT_END_COVERAGE_LOST"),
    ("EVALUATION_OFF_GRID", "UNKNOWN", "ORB_ATTEMPT_END_EVALUATION_OFF_GRID"),
))
def test_an_attempt_that_did_not_fail_hands_nothing_over(ending, status, reason):
    supplied = attempt(ending=ending)
    result = evaluate_or_failure_handoff(request(
        at=supplied.evaluated_at, attempt=supplied,
        minute_close=reacceptance(at=supplied.evaluated_at)))
    gate = result.gate(ENDED_GATE)
    assert (gate.status, gate.reason) == (status, reason)
    assert result.state == StrategyState("WATCHING")


def test_an_attempt_that_reached_an_alert_needs_the_callers_own_ownership_rule():
    refused = evaluate_or_failure_handoff(request(attempt_reached_alert=True))
    assert refused.gate(OWNERSHIP_GATE).reason == "REVERSAL_AFTER_ALERT_NOT_OWNED"
    assert refused.state == StrategyState("WATCHING")
    owned = evaluate_or_failure_handoff(request(
        attempt_reached_alert=True, policy=policy(owns_after_alert_triggered=True)))
    assert owned.gate(OWNERSHIP_GATE).status == "PASS"
    assert owned.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)


# --- the supplied M3.6 opening range ----------------------------------------


def test_a_missing_opening_range_is_unknown_and_never_a_passing_gate():
    result = evaluate_or_failure_handoff(request(opening_range=None))
    assert result.gate(RANGE_GATE).status == "UNKNOWN"
    assert result.gate(RANGE_GATE).reason == "MISSING_OPENING_RANGE"
    assert result.state == StrategyState("WATCHING")


def test_a_range_that_disagrees_with_the_frozen_attempt_is_refused():
    result = evaluate_or_failure_handoff(request(opening_range=opening_range("SHORT")))
    assert result.gate(RANGE_GATE).reason == "OPENING_RANGE_DISAGREEMENT"
    assert result.state == StrategyState("WATCHING")


def test_an_incomplete_supplied_range_stays_unknown():
    incomplete = opening_range(minute_history=None)
    assert incomplete.features[0].value is None
    result = evaluate_or_failure_handoff(request(opening_range=incomplete))
    assert result.gate(RANGE_GATE).status == "UNKNOWN"
    assert result.gate(RANGE_GATE).reason == "OPENING_RANGE_MISSING_MINUTE_HISTORY"


def test_a_range_for_another_instrument_or_version_is_refused():
    supplied = opening_range()
    other = replace(supplied, metadata=replace(supplied.metadata, instrument_id="OTHER"))
    assert evaluate_or_failure_handoff(request(
        opening_range=other)).gate(RANGE_GATE).reason == "OPENING_RANGE_IDENTITY_MISMATCH"
    changed = replace(supplied, feature_version="M81_NOT_THE_M36_VERSION")
    assert evaluate_or_failure_handoff(request(
        opening_range=changed)).gate(
            RANGE_GATE).reason == "INCOMPATIBLE_OPENING_RANGE_VERSION"
    assert supplied.feature_version == RANGE_VERSION


def test_a_range_that_is_not_yet_available_stays_unknown():
    later = ENDED_AT + timedelta(minutes=5)
    supplied = opening_range()
    delayed = replace(supplied, evaluated_at=later, metadata=replace(
        supplied.metadata, source_time=later, received_time=later, available_time=later,
        normalized_time=later))
    result = evaluate_or_failure_handoff(request(opening_range=delayed))
    assert result.gate(RANGE_GATE).reason == "OPENING_RANGE_NOT_YET_AVAILABLE"
    assert result.state == StrategyState("WATCHING")


def test_the_supplied_range_keeps_its_own_input_records():
    gate = evaluate_or_failure_handoff(request()).gate(RANGE_GATE)
    assert gate.input_record_ids == ("opening-range",)


# --- the supplied break excursion -------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_break_that_never_left_the_frozen_boundary_is_not_a_real_break(direction):
    edge = RANGE[direction][0] if direction == "LONG" else RANGE[direction][1]
    result = evaluate_or_failure_handoff(request(
        direction, breakout_extreme=extreme(direction, price=BOUNDARY[direction])))
    gate = result.gate(EXCURSION_GATE)
    assert gate.reason == "BREAK_NOT_BEYOND_BOUNDARY"
    assert gate.observed == pytest.approx(abs(BOUNDARY[direction] - edge))
    assert result.state == StrategyState("WATCHING")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_an_excursion_below_the_callers_own_minimum_is_refused(direction):
    result = evaluate_or_failure_handoff(request(
        direction, breakout_extreme=extreme(direction, price=ONE_TICK[direction])))
    gate = result.gate(EXCURSION_GATE)
    assert gate.reason == "EXCURSION_BELOW_SUPPLIED_MINIMUM"
    assert gate.observed == pytest.approx(0.03) and gate.threshold == pytest.approx(0.10)
    assert result.state == StrategyState("WATCHING")


def test_the_same_one_tick_break_passes_under_a_smaller_supplied_minimum():
    result = evaluate_or_failure_handoff(request(
        breakout_extreme=extreme(price=ONE_TICK["LONG"]),
        policy=policy(minimum_excursion_atr_multiple=0.05)))
    assert result.gate(EXCURSION_GATE).status == "PASS"
    assert result.required_excursion == pytest.approx(0.02)


@pytest.mark.parametrize("changes,status,reason", (
    ({"coverage_known": False}, "FAIL", "COVERAGE_LOST"),
    ({"available_at": ENDED_AT + timedelta(minutes=1)}, "UNKNOWN",
     "BREAKOUT_EXTREME_NOT_AVAILABLE"),
    ({"observed_at": CROSS - timedelta(seconds=1)}, "FAIL",
     "BREAKOUT_EXTREME_BEFORE_CROSSING"),
    ({"price": None}, "UNKNOWN", "UNKNOWN_BREAKOUT_EXTREME"),
))
def test_an_unusable_breakout_extreme_never_becomes_a_passing_gate(changes, status, reason):
    result = evaluate_or_failure_handoff(request(breakout_extreme=extreme(**changes)))
    gate = result.gate(EXCURSION_GATE)
    assert (gate.status, gate.reason) == (status, reason)
    assert gate.observed is None and result.excursion is None
    assert result.state == StrategyState("WATCHING")


def test_a_missing_breakout_extreme_still_reports_the_required_minimum():
    result = evaluate_or_failure_handoff(request(breakout_extreme=None))
    gate = result.gate(EXCURSION_GATE)
    assert (gate.status, gate.reason) == ("UNKNOWN", "MISSING_BREAKOUT_EXTREME")
    assert gate.threshold == pytest.approx(0.10)


# --- the supplied reacceptance ----------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_close_outside_the_range_is_not_a_reacceptance(direction):
    result = evaluate_or_failure_handoff(request(
        direction, minute_close=reacceptance(direction, close=EXTREME[direction])))
    assert result.gate(REACCEPTANCE_GATE).reason == "CLOSE_NOT_BACK_INSIDE_RANGE"
    assert result.state == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)


def test_a_reacceptance_after_the_callers_own_window_closes_the_handoff():
    late = CROSS + timedelta(seconds=200)
    result = evaluate_or_failure_handoff(request(
        at=late, attempt=attempt(ending="ACCEPTANCE_DEADLINE_PASSED"),
        minute_close=reacceptance(at=late)))
    gate = result.gate(REACCEPTANCE_GATE)
    assert gate.reason == "REACCEPTANCE_WINDOW_PASSED"
    assert gate.observed == pytest.approx(200.0) and gate.threshold == pytest.approx(180.0)
    assert result.state == StrategyState("INVALIDATED")
    assert gate.reason in INVALIDATIONS


@pytest.mark.parametrize("changes,status,reason", (
    ({"coverage_known": False}, "FAIL", "COVERAGE_LOST"),
    ({"available_at": ENDED_AT + timedelta(minutes=1)}, "UNKNOWN",
     "REACCEPTANCE_NOT_AVAILABLE"),
    ({"final": False, "close": None}, "UNKNOWN", "MINUTE_BAR_PENDING"),
    ({"bar_end": CROSS}, "FAIL", "REACCEPTANCE_BEFORE_CROSSING"),
))
def test_an_unusable_reacceptance_close_never_becomes_a_passing_gate(changes, status, reason):
    result = evaluate_or_failure_handoff(request(minute_close=reacceptance(**changes)))
    gate = result.gate(REACCEPTANCE_GATE)
    assert (gate.status, gate.reason) == (status, reason)
    assert result.state == (StrategyState("INVALIDATED") if reason == "COVERAGE_LOST"
                            else StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT))


def test_a_lost_reacceptance_coverage_closes_a_taken_over_handoff():
    result = evaluate_or_failure_handoff(request(
        minute_close=reacceptance(coverage_known=False)))
    assert result.state == StrategyState("INVALIDATED")
    assert result.gate(REACCEPTANCE_GATE).reason in INVALIDATIONS


# --- the reported result -----------------------------------------------------


def test_every_reported_gate_name_is_a_supported_one():
    assert tuple(row.name for row in evaluate_or_failure_handoff(
        request()).gates) == HANDOFF_GATES


def test_the_same_supplied_request_renders_the_same_json():
    supplied = request()
    first, second = (evaluate_or_failure_handoff(supplied) for _ in range(2))
    assert first.to_json() == second.to_json()
    payload = json.loads(first.to_json())
    assert payload["handoff_version"] == HANDOFF_VERSION
    assert payload["direction"] == "SHORT" and payload["break_direction"] == "LONG"
    assert payload["state"] == "SETUP_FORMING" and payload["substate"] == FAILURE_FORMING
    assert payload["candidate"]["boundary"] == BOUNDARY["LONG"]
    assert payload["policy_version"] == POLICY_VERSION


def test_the_result_is_immutable_and_needs_a_canonical_request():
    result = evaluate_or_failure_handoff(request())
    with pytest.raises(FrozenInstanceError):
        result.state = StrategyState("ARMED")
    with pytest.raises(RecordError):
        evaluate_or_failure_handoff("M81")
    assert isinstance(result, HandoffAssessment)


def test_the_module_adopts_no_number_of_its_own():
    namespace = vars(or_failure_handoff)
    assert not [name for name, value in namespace.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)]
    source = inspect.getsource(or_failure_handoff)
    for token in ("0.70", "180", "0.03", "0.05", "0.08", "0.65", "1.5"):
        assert token not in source
    assert SOURCE_ORB_STRATEGY_ID == "CRVOL_ORB5" and STRATEGY_ID == "OR_FAILURE_REV"


# --- the handoff owner -------------------------------------------------------


def test_the_owner_refuses_a_break_that_does_not_reverse_into_its_direction():
    with pytest.raises(RecordError):
        owner("LONG").propose(request("LONG"), record_id="m81-open")
    with pytest.raises(RecordError):
        owner().propose(request("SHORT"), record_id="m81-open")
    with pytest.raises(RecordError):
        owner().propose(request(symbol="OTHER"), record_id="m81-open")
    with pytest.raises(RecordError):
        owner().propose(request(policy=policy(reacceptance_window_seconds=120)),
                        record_id="m81-open")
    with pytest.raises(RecordError):
        owner().propose("M81", record_id="m81-open")


def test_a_first_evaluation_that_already_failed_records_the_break_before_its_failure():
    subject = owner()
    assessment, changes = subject.propose(request(), record_id="m81-open",
                                          staged_record_id="m81-failure")
    assert assessment.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
    assert len(changes) == 2
    assert (changes[0].from_state, changes[0].to_substate) == ("WATCHING", BREAKOUT_ATTEMPT)
    assert changes[0].reason == "ORB_BREAK_HANDED_OVER"
    assert (changes[1].from_substate, changes[1].to_substate) == (BREAKOUT_ATTEMPT,
                                                                  FAILURE_FORMING)
    assert changes[1].record_id == "m81-failure"
    assert all(row.strategy_id == STRATEGY_ID for row in changes)
    assert all(row.metadata.data_mode == DATA_MODE for row in changes)


def test_a_two_step_evaluation_without_its_second_id_is_refused():
    with pytest.raises(RecordError):
        owner().propose(request(), record_id="m81-open")


def test_a_single_step_evaluation_cannot_use_a_second_id():
    subject = owner()
    with pytest.raises(RecordError):
        subject.propose(request(minute_close=None), record_id="m81-open",
                        staged_record_id="m81-unused")


def test_the_owner_advances_only_after_the_caller_confirms_the_recording():
    subject = owner()
    _, changes = subject.propose(request(minute_close=None), record_id="m81-open")
    assert subject.current_state() == StrategyState("WATCHING")
    assert subject.confirm(*changes) == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
    assert subject.current_candidate() == candidate("LONG")
    with pytest.raises(RecordError):
        subject.confirm(*changes)


def test_a_different_attempt_cannot_replace_the_one_already_taken_over():
    subject = owner()
    _, changes = subject.propose(request(minute_close=None), record_id="m81-open")
    subject.confirm(*changes)
    later = ENDED_AT + timedelta(minutes=2)
    other = request(at=later, minute_close=None,
                    attempt=attempt(at=later, crossed_at=CROSS + timedelta(minutes=2)))
    with pytest.raises(RecordError):
        subject.propose(other, record_id="m81-second")


def test_one_ended_attempt_cannot_be_handed_over_twice():
    subject = owner()
    _, opening = subject.propose(request(minute_close=reacceptance(coverage_known=False)),
                                 record_id="m81-open", staged_record_id="m81-closed")
    subject.confirm(*opening)
    assert subject.current_state() == StrategyState("INVALIDATED")
    released = subject.release(at=ENDED_AT + timedelta(minutes=1), record_id="m81-release")
    assert subject.confirm(*released) == StrategyState("WATCHING")
    assert subject.closed_attempts == (("LONG", 1, "2026-07-06T13:50:00Z"),)
    with pytest.raises(RecordError):
        subject.propose(request(), record_id="m81-again", staged_record_id="m81-again-failure")


def test_a_taken_over_handoff_is_closed_rather_than_silently_dropped():
    subject = owner()
    _, changes = subject.propose(request(minute_close=None), record_id="m81-open")
    subject.confirm(*changes)
    withdrawn = request(minute_close=None, breakout_extreme=extreme(price=None))
    assessment, later = subject.propose(withdrawn, record_id="m81-withdrawn")
    assert assessment.state == StrategyState("WATCHING")
    assert later[0].to_state == "INVALIDATED"
    assert subject.confirm(*later) == StrategyState("INVALIDATED")


def test_a_handed_over_failure_cannot_fall_back_to_the_breakout_attempt():
    subject = owner()
    _, changes = subject.propose(request(), record_id="m81-open",
                                 staged_record_id="m81-failure")
    subject.confirm(*changes)
    with pytest.raises(RecordError):
        subject.propose(request(minute_close=reacceptance(final=False, close=None)),
                        record_id="m81-back")


def test_a_closed_handoff_must_be_released_before_another_attempt():
    subject = owner()
    _, changes = subject.propose(request(minute_close=reacceptance(coverage_known=False)),
                                 record_id="m81-open", staged_record_id="m81-closed")
    subject.confirm(*changes)
    with pytest.raises(RecordError):
        subject.propose(request(), record_id="m81-retake", staged_record_id="m81-retake-2")
    with pytest.raises(RecordError):
        owner().release(at=ENDED_AT, record_id="m81-not-closed")


def test_an_unchanged_evaluation_proposes_nothing():
    subject = owner()
    assessment, changes = subject.propose(request(opening_range=None), record_id="m81-none")
    assert assessment.state == StrategyState("WATCHING") and changes == ()
    with pytest.raises(RecordError):
        subject.confirm()


def test_evaluation_time_cannot_move_backward():
    subject = owner()
    _, changes = subject.propose(request(minute_close=None), record_id="m81-open")
    subject.confirm(*changes)
    with pytest.raises(RecordError):
        subject.propose(request(at=CROSS + timedelta(seconds=5), minute_close=None),
                        record_id="m81-backward")


def test_the_owner_can_expire_and_names_its_own_reason():
    subject = owner()
    changes = subject.expire(at=ENDED_AT, reason="SESSION_WINDOW_CLOSED",
                             record_id="m81-expire")
    assert subject.confirm(*changes) == StrategyState("EXPIRED")
    with pytest.raises(RecordError):
        owner().expire(at=ENDED_AT, reason=" ", record_id="m81-expire")


@pytest.mark.parametrize("changes", (
    {"session": "M81"}, {"policy": "M81"}, {"instrument_type": "OPTION"},
    {"direction": "BOTH"}, {"symbol": " "}, {"strategy_version": "UNKNOWN"},
))
def test_the_owner_requires_explicit_identity(changes):
    with pytest.raises(RecordError):
        owner(**changes)


def test_restore_positions_an_unused_owner_on_explicit_saved_facts():
    subject = owner()
    state = subject.restore(StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT),
                            candidate=candidate("LONG"),
                            closed_attempts=(("LONG", 1, "2026-07-06T13:40:00Z"),))
    assert state == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
    assert subject.current_candidate() == candidate("LONG")
    assert subject.closed_attempts == (("LONG", 1, "2026-07-06T13:40:00Z"),)
    with pytest.raises(RecordError):
        subject.restore(StrategyState("WATCHING"))


@pytest.mark.parametrize("changes", (
    {"state": StrategyState("ARMED")}, {"state": "WATCHING"},
    {"state": StrategyState("SETUP_FORMING", "OTHER")}, {"candidate": "M81"},
    {"closed_attempts": [("LONG", 1, "x")]}, {"closed_attempts": (("LONG", 1),)},
))
def test_restore_refuses_facts_that_are_not_m81_ones(changes):
    values = dict(state=StrategyState("WATCHING"))
    values.update(changes)
    state = values.pop("state")
    with pytest.raises(RecordError):
        owner().restore(state, **values)


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           handoff_rules())


async def test_a_refused_recording_leaves_the_owner_where_it_was():
    class Refusing:
        async def append(self, entry):
            raise RecordError("synthetic storage refusal")

    subject = owner()
    supplied = request(minute_close=None)
    assessment, changes = subject.propose(supplied, record_id="m81-open")
    engine = StateTransitionEngine(scope("SHORT"), Refusing())
    with pytest.raises(RecordError):
        await engine.apply(changes[0], context=context(assessment=assessment))
    assert engine.current_state() == StrategyState("WATCHING")
    assert subject.current_state() == StrategyState("WATCHING")
    assert subject.current_candidate() is None


async def test_the_supplied_handoff_through_the_m42_engine_and_m51_store():
    proofs = []
    connection = await db.init_db()
    for direction in ("LONG", "SHORT"):
        reversal = mirror_direction(direction)
        subject = owner(reversal)
        engine = StateTransitionEngine(scope(reversal), SQLiteTransitionStore(connection))
        store = ResearchEventStore(connection)

        opening_request = request(direction, minute_close=None)
        first, opening = subject.propose(opening_request, record_id="m81-open-" + direction)
        assert first.state == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)
        opened = await engine.apply(opening[0], context=context(
            reversal, assessment=first, snapshot=opening_range(direction)))
        assert subject.confirm(*opening) == StrategyState("SETUP_FORMING", BREAKOUT_ATTEMPT)

        supplied = request(direction)
        assessment, changes = subject.propose(supplied, record_id="m81-failure-" + direction)
        assert assessment.state == StrategyState("SETUP_FORMING", FAILURE_FORMING)
        assert assessment.reasons == ()
        entry = await engine.apply(changes[0], context=context(
            reversal, assessment=assessment, snapshot=opening_range(direction)))
        assert engine.current_state() == StrategyState("SETUP_FORMING", FAILURE_FORMING)
        assert subject.confirm(*changes) == StrategyState("SETUP_FORMING", FAILURE_FORMING)

        stored = await store.append(changes[0], session=DAY, recorded_at=ENDED_AT)
        assert stored["kind"] == "STATE_TRANSITION"
        assert await store.append(changes[0], session=DAY, recorded_at=ENDED_AT) == stored

        repeated = evaluate_or_failure_handoff(supplied)
        assert repeated.to_json() == assessment.to_json()
        proofs.append({
            "synthetic_only": True, "break_direction": direction, "direction": reversal,
            "opening_assessment": first.as_dict(), "assessment": assessment.as_dict(),
            "opening_transition": opening[0].as_dict(), "transition": changes[0].as_dict(),
            "opening_position": opened.position, "stored_position": entry.position,
            "stored_fingerprint": stored["fingerprint"],
            "gate_sha256": hashlib.sha256("".join(
                json.dumps(row.as_dict(), sort_keys=True)
                for row in assessment.gates).encode()).hexdigest(),
            "repeated_assessment_identical": True,
        })
    await db.close_db()
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "handoff_version": HANDOFF_VERSION, "runs": proofs}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m8_1_or_failure_handoff_proof.json").write_text(rendered)
