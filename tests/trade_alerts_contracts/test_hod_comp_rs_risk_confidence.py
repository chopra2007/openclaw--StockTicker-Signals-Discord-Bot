"""M7.4 supplied risk, confidence and suppression contracts for `HOD_COMP_RS`.

Every number below is a synthetic fixture supplied by the caller. A READY
composition proves the offline contract only: it establishes no source coverage,
no adopted `HOD_COMP_RS` rule, no approved stop or target definition, no quality
cutoff, no alert and no permission to act. A SUPPRESSED composition reports the
caller's own history decision; it writes no `SuppressionEvent`, which keeps its
M4.5 owner.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
import inspect
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db, hod_comp_rs_risk_confidence
from consensus_engine.confidence import (
    COMPONENTS, ConfidencePolicy, ConfidenceRequest, ConfidenceTerm, compose_confidence,
)
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.hod_comp_rs_risk_confidence import (
    ACTIONABLE_ACTION, ActionHistory, CONFIDENCE_GATE, HEADS_UP_ACTION, HodCompRsOutcome,
    HodCompRsOutcomeRequest, OUTCOME_GATES, OUTCOME_VERSION, OutcomeGate, PriorAction,
    READY, REJECTED, RISK_GATE, STRATEGY_ID, SUPPRESSED, SUPPRESSION_GATE,
    SUPPRESSION_REASONS, StructuralReading, SuppressionPolicy, TRIGGER_GATE, UNAVAILABLE,
    UNDEFINED, compose_hod_comp_rs_outcome,
)
from consensus_engine.hod_comp_rs_trigger import (
    FAIL, PASS, QUOTE_PROJECTED, TAPE, UNKNOWN, evaluate_hod_comp_rs_trigger,
    freeze_structure, trigger_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, RiskLevel, TargetLevel,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_hod_comp_rs_trigger import (
    ATR, BOUNDARY, COMPRESSION, CROSS, EARLY, REFERENCE, SIX, TRIGGER, eligibility, flip,
    grid, owner, request as trigger_request, structure, trigger_policy,
)
from test_rs_trend_eligibility import DAY, metadata
from test_strategy_interface import session


VERSION = "M74_FIXTURE_ONLY_V1"
POLICY_VERSION = "M74_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M74_SUPPLIED_FIXTURE_DEFINITION"
MODE = "SUPPLIED_FIXTURE_SCORE_POINTS"
SCORES = (80.0, 60.0, 40.0)
# One synthetic supplied stop and two supplied targets for the long coil, each
# mirrored for the short twin. None of these numbers is an adopted threshold.
ENTRY = 101.03
STOP = 100.57
RISK_PER_SHARE = 0.46
TARGETS = ((101.75, 1.5), (102.20, 2.5))
EARLIER = TRIGGER - timedelta(minutes=5)


def terms():
    """One supplied score and one declared factor for each M4.4 component."""
    return tuple(
        ConfidenceTerm(component.lower() + "-" + kind.lower(), component, kind,
                       component.lower() + "-" + kind.lower(), VERSION, MODE)
        for component in COMPONENTS for kind in ("SCORE", "FACTOR")
    )


def confidence_policy(*, strategy_id=STRATEGY_ID, strategy_version=VERSION, weights=(.5, .3, .2)):
    return ConfidencePolicy(strategy_id, strategy_version, POLICY_VERSION, *weights, terms())


def scores_snapshot(scores=SCORES, *, at=TRIGGER, record_id="m74-supplied-scores", missing=None):
    features = tuple(
        FeatureValue(term.feature_name,
                     None if term.name == missing else scores[COMPONENTS.index(term.component)],
                     "SCORE_POINTS", "MISSING_SOURCE" if term.name == missing else None,
                     ("m74-score-input",))
        for term in terms()
    )
    return FeatureSnapshot(record_id=record_id, metadata=metadata(at, data_mode=MODE),
                           evaluated_at=at, feature_version=VERSION, features=features,
                           input_record_ids=("m74-score-input",))


def confidence_request(direction="LONG", *, at=TRIGGER, scores=SCORES, missing=None,
                       supplied_policy=None):
    rules = supplied_policy if supplied_policy is not None else confidence_policy()
    snapshot = scores_snapshot(scores, at=at, missing=missing)
    context = StrategyContext(session(DAY), "SYNTH", "EQUITY", direction, at, (snapshot,))
    return ConfidenceRequest(
        context, rules, tuple((term.name, snapshot.record_id) for term in rules.terms))


def composed(direction="LONG", **changes):
    return compose_confidence(confidence_request(direction, **changes))


def risk_level(direction="LONG", *, entry=ENTRY, stop=STOP, distance=RISK_PER_SHARE):
    return RiskLevel(flip(entry, direction), flip(stop, direction), distance,
                     "Synthetic fixture stop only", "m74-fixture")


def targets(direction="LONG", supplied=TARGETS):
    return tuple(
        TargetLevel("T%d" % (number + 1), flip(price, direction), multiple, "m74-fixture")
        for number, (price, multiple) in enumerate(supplied)
    )


def structural(direction="LONG", *, mode=TAPE, at=TRIGGER, crossed_at=CROSS,
               structure_number=1, **changes):
    values = dict(
        definition_reference="M74_SUPPLIED_STRUCTURAL_V1", direction=direction, mode=mode,
        structure_number=structure_number, crossed_at=crossed_at, evaluated_at=at,
        available_at=at, risk=risk_level(direction), targets=targets(direction),
        record_ids=("m74-supplied-stop", "m74-supplied-targets"),
    )
    values.update(changes)
    return StructuralReading(**values)


def suppression_policy(**changes):
    values = dict(version=POLICY_VERSION, definition_reference=DEFINITION,
                  cooldown_seconds=600.0, max_actionable_per_structure=1,
                  max_structures_per_direction=2, suppress_opposite_direction=True,
                  conflict_window_seconds=180.0)
    values.update(changes)
    return SuppressionPolicy(**values)


def prior(record_id="m74-prior", *, kind=ACTIONABLE_ACTION, direction="LONG",
          structure_number=1, at=EARLIER, outstanding=False):
    return PriorAction(record_id, kind, direction, structure_number, at, outstanding)


def history(*actions, at=TRIGGER, complete=True, **changes):
    values = dict(definition_reference="M74_SUPPLIED_HISTORY_V1", as_of=at,
                  complete=complete, actions=actions)
    values.update(changes)
    return ActionHistory(**values)


def assessment_of(direction="LONG", *, mode=TAPE, at=TRIGGER, **changes):
    return evaluate_hod_comp_rs_trigger(trigger_request(direction, mode=mode, at=at, **changes))


def outcome_request(direction="LONG", *, mode=TAPE, at=TRIGGER, **changes):
    values = dict(assessment=assessment_of(direction, mode=mode, at=at),
                  structural=structural(direction, mode=mode, at=at),
                  confidence=composed(direction, at=at), suppression=suppression_policy(),
                  history=history(at=at), strategy_version=VERSION,
                  definition_reference=DEFINITION)
    values.update(changes)
    return HodCompRsOutcomeRequest(**values)


def outcome(direction="LONG", **changes):
    return compose_hod_comp_rs_outcome(outcome_request(direction, **changes))


def status_of(result, name):
    row = result.gate(name)
    return row.status, row.reason


# --- supplied record contracts ----------------------------------------------


@pytest.mark.parametrize("changes", (
    {"assessment": "ALERT_TRIGGERED"}, {"assessment": None}, {"structural": "READY"},
    {"structural": None}, {"confidence": "READY"}, {"confidence": None},
    {"suppression": None}, {"suppression": POLICY_VERSION}, {"history": "NONE"},
    {"history": ()}, {"strategy_version": ""}, {"strategy_version": " "},
    {"strategy_version": "UNKNOWN"}, {"strategy_version": 1},
    {"definition_reference": ""}, {"definition_reference": "UNSPECIFIED"},
    {"definition_reference": None},
))
def test_request_requires_canonical_supplied_parts(changes):
    with pytest.raises(RecordError):
        outcome_request(**changes)


def test_composition_refuses_anything_but_its_own_request():
    for supplied in ("READY", None, outcome_request().assessment):
        with pytest.raises(RecordError):
            compose_hod_comp_rs_outcome(supplied)


@pytest.mark.parametrize("changes", (
    {"definition_reference": " "}, {"definition_reference": "UNKNOWN"},
    {"direction": "FLAT"}, {"mode": "BOTH"}, {"structure_number": 0},
    {"structure_number": 1.0}, {"at": datetime(2026, 7, 6, 6, 50, 10)},
    {"crossed_at": TRIGGER + timedelta(seconds=1)}, {"risk": "100.57"},
    {"targets": [TargetLevel("T1", 101.75, 1.5, "m74-fixture")]},
    {"targets": (TargetLevel("T1", 101.75, 1.5, "m74-fixture"),
                 TargetLevel("T1", 102.20, 2.5, "m74-fixture"))},
    {"record_ids": ["m74-supplied-stop"]}, {"record_ids": (" ",)},
))
def test_supplied_structural_reading_requires_explicit_facts(changes):
    with pytest.raises(RecordError):
        structural(**changes)


def test_a_missing_structural_measurement_stays_an_explicit_unknown():
    row = structural(risk=None, targets=(), missing_reason="STRUCTURE_NOT_MEASURED")
    assert row.risk is None and row.targets == ()
    with pytest.raises(RecordError):  # a missing stop cannot carry targets beside it
        structural(risk=None, missing_reason="STRUCTURE_NOT_MEASURED")
    with pytest.raises(RecordError):  # nor may a supplied stop claim it is missing
        structural(missing_reason="STRUCTURE_NOT_MEASURED")
    with pytest.raises(RecordError):
        structural(risk=None, targets=(), missing_reason="UNKNOWN")


@pytest.mark.parametrize("changes", (
    {"version": " "}, {"version": "UNSPECIFIED"}, {"definition_reference": "UNKNOWN"},
    {"cooldown_seconds": -1.0}, {"cooldown_seconds": "600"},
    {"cooldown_seconds": float("nan")}, {"cooldown_seconds": True},
    {"max_actionable_per_structure": 0}, {"max_actionable_per_structure": 1.0},
    {"max_structures_per_direction": 0}, {"suppress_opposite_direction": "YES"},
    {"suppress_opposite_direction": 1}, {"conflict_window_seconds": -180.0},
))
def test_suppression_policy_requires_explicit_supported_values(changes):
    with pytest.raises(RecordError):
        suppression_policy(**changes)


@pytest.mark.parametrize("changes", (
    {"record_id": " "}, {"record_id": "UNKNOWN"}, {"kind": "ALERT"},
    {"direction": "FLAT"}, {"structure_number": 0}, {"outstanding": "YES"},
    {"at": datetime(2026, 7, 6, 6, 45)},
))
def test_prior_actions_require_explicit_supported_facts(changes):
    with pytest.raises(RecordError):
        prior(**changes)


@pytest.mark.parametrize("changes", (
    {"definition_reference": "UNSPECIFIED"}, {"complete": "YES"}, {"complete": None},
    {"as_of": datetime(2026, 7, 6, 6, 50, 10)}, {"actions": [prior()]},
    {"actions": (prior(), prior())}, {"actions": ("m74-prior",)},
))
def test_action_history_requires_explicit_supported_facts(changes):
    values = dict(definition_reference="M74_SUPPLIED_HISTORY_V1", as_of=TRIGGER,
                  complete=True, actions=())
    values.update(changes)
    with pytest.raises(RecordError):
        ActionHistory(**values)


# --- the composed READY path -------------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("mode", (TAPE, QUOTE_PROJECTED))
def test_the_supplied_stop_targets_and_confidence_are_reported_unchanged(direction, mode):
    result = outcome(direction, mode=mode)
    assert result.status == READY and result.reasons == ()
    assert all(row.status == PASS for row in result.gates)
    assert result.risk == risk_level(direction)
    assert result.targets == targets(direction)
    assert result.confidence == composed(direction).confidence
    assert result.suppression_reasons == ()
    assert result.structure.mode == mode
    assert result.state == StrategyState("ALERT_TRIGGERED")
    assert result.crossed_at == CROSS and result.evaluated_at == TRIGGER
    assert result.strategy_version == VERSION
    assert result.definition_reference == DEFINITION
    assert result.suppression_version == POLICY_VERSION
    assert result.structural_input_ids == ("m74-supplied-stop", "m74-supplied-targets")


def test_the_caller_keeps_its_own_supplied_weights_and_scores():
    result = outcome()
    assert result.confidence.final_score == 66.0
    other = outcome(confidence=composed(supplied_policy=confidence_policy(
        strategy_version=VERSION, weights=(.2, .3, .5))))
    assert other.status == READY and other.confidence.final_score == 54.0


def test_no_quality_cutoff_is_applied_to_a_supplied_score():
    for scores in ((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (100.0, 100.0, 100.0)):
        result = outcome(confidence=composed(scores=scores))
        assert result.status == READY
    assert outcome().unavailable == UNDEFINED
    assert "CONFIDENCE_FLOOR_UNDEFINED" in UNDEFINED


def test_what_stays_undefined_is_named_rather_than_filled_in():
    assert set(UNDEFINED) == {
        "CONFIDENCE_FLOOR_UNDEFINED", "RUNNER_UNDEFINED", "SOFT_INVALIDATION_UNDEFINED",
        "STOP_PAD_UNDEFINED", "TARGET_REWARD_MINIMUM_UNDEFINED"}
    assert outcome(direction="SHORT").unavailable == UNDEFINED


# --- the M7.3 trigger gate ---------------------------------------------------


def test_only_a_reported_actionable_trigger_composes_a_ready_outcome():
    refused = outcome(assessment=assessment_of(observations=grid(prices=SIX)))
    assert refused.status == REJECTED
    assert status_of(refused, TRIGGER_GATE) == (FAIL, "TRIGGER_NOT_ACTIONABLE_ACCEPTANCE_WINDOW")
    assert refused.state == StrategyState("ARMED", "CROSSING_OBSERVED")
    # The supplied stop and confidence keep their own passing gates; only a READY
    # outcome says this composition held together.
    assert refused.risk == risk_level() and refused.confidence is not None


def test_an_unknown_trigger_input_keeps_the_whole_outcome_unavailable():
    result = outcome(assessment=assessment_of(intensity=None))
    assert result.status == UNAVAILABLE
    assert status_of(result, TRIGGER_GATE) == (UNKNOWN, "TRIGGER_UNKNOWN_TRADE_INTENSITY")
    assert result.reasons[0] == TRIGGER_GATE + ":" + UNKNOWN + ":TRIGGER_UNKNOWN_TRADE_INTENSITY"


def test_the_trigger_gate_keeps_the_frozen_structure_references():
    result = outcome()
    assert result.gate(TRIGGER_GATE).input_record_ids == structure().input_record_ids
    assert result.gate(TRIGGER_GATE).input_record_ids != ()


# --- the supplied stop and targets, re-checked -------------------------------


@pytest.mark.parametrize("changes,reason", (
    ({"mode": QUOTE_PROJECTED}, "GEOMETRY_ARM_MISMATCH"),
    ({"direction": "SHORT"}, "GEOMETRY_DIRECTION_MISMATCH"),
    ({"structure_number": 2}, "GEOMETRY_STRUCTURE_MISMATCH"),
    ({"crossed_at": CROSS + timedelta(seconds=1)}, "GEOMETRY_CROSSING_MISMATCH"),
    ({"at": TRIGGER + timedelta(seconds=1)}, "GEOMETRY_NOT_CURRENT"),
))
def test_a_reading_framed_on_another_structure_or_instant_is_never_used(changes, reason):
    result = outcome(structural=structural(**changes))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, reason)
    assert result.risk is None and result.targets == ()
    # The confidence composed for this instant is still reported.
    assert result.gate(CONFIDENCE_GATE).status == PASS and result.confidence is not None


def test_a_reading_that_was_not_available_yet_is_unknown():
    result = outcome(structural=structural(available_at=TRIGGER + timedelta(seconds=1)))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, "GEOMETRY_NOT_YET_AVAILABLE")


def test_a_missing_stop_or_missing_target_never_becomes_a_reported_level():
    missing = outcome(structural=structural(
        risk=None, targets=(), missing_reason="STRUCTURE_NOT_MEASURED"))
    assert missing.status == UNAVAILABLE
    assert status_of(missing, RISK_GATE) == (UNKNOWN, "GEOMETRY_STRUCTURE_NOT_MEASURED")
    empty = outcome(structural=structural(targets=()))
    assert empty.status == UNAVAILABLE
    assert status_of(empty, RISK_GATE) == (UNKNOWN, "GEOMETRY_TARGETS_UNAVAILABLE")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("values,reason", (
    ((101.01, 100.57, 0.44), "ENTRY_INSIDE_FROZEN_BOUNDARY"),
    ((101.03, 101.49, 0.46), "STOP_ON_THE_WRONG_SIDE"),
    ((101.03, 100.62, 0.41), "STOP_INSIDE_FROZEN_COMPRESSION"),
))
def test_a_supplied_stop_must_be_framed_on_this_frozen_structure(direction, values, reason):
    entry, stop, distance = values
    supplied = structural(direction, risk=risk_level(direction, entry=entry, stop=stop,
                                                     distance=distance))
    result = compose_hod_comp_rs_outcome(outcome_request(direction, structural=supplied))
    assert result.status == REJECTED
    assert status_of(result, RISK_GATE) == (FAIL, reason)
    assert result.risk is None and result.targets == ()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_target_that_is_not_beyond_the_entry_refuses_the_outcome(direction):
    behind = structural(direction, targets=targets(direction, ((100.90, 1.5), (102.20, 2.5))))
    result = compose_hod_comp_rs_outcome(outcome_request(direction, structural=behind))
    assert result.status == REJECTED
    assert status_of(result, RISK_GATE) == (FAIL, "TARGET_NOT_BEYOND_ENTRY")


def test_a_target_claiming_more_reward_than_its_own_prices_show_is_refused():
    overstated = structural(targets=targets(supplied=((101.75, 1.6), (102.20, 2.5))))
    result = outcome(structural=overstated)
    assert result.status == REJECTED
    assert status_of(result, RISK_GATE) == (FAIL, "TARGET_R_MULTIPLE_OVERSTATED")
    # The same prices with the reward they actually measure still pass, and no
    # reward minimum of any size is applied.
    modest = structural(targets=targets(supplied=((101.75, 0.1), (102.20, 0.2))))
    assert outcome(structural=modest).status == READY


def test_the_risk_gate_keeps_the_supplied_level_references():
    result = outcome()
    assert result.gate(RISK_GATE).input_record_ids == (
        "m74-supplied-stop", "m74-supplied-targets")


# --- the M4.4 confidence for this instant ------------------------------------


@pytest.mark.parametrize("changes,reason", (
    (dict(supplied_policy=confidence_policy(strategy_id="CRVOL_ORB5")),
     "CONFIDENCE_STRATEGY_MISMATCH"),
    (dict(supplied_policy=confidence_policy(strategy_version="M74_OTHER_VERSION")),
     "CONFIDENCE_VERSION_MISMATCH"),
    (dict(direction="SHORT"), "CONFIDENCE_DIRECTION_MISMATCH"),
    (dict(at=CROSS), "CONFIDENCE_NOT_CURRENT"),
))
def test_confidence_from_another_strategy_direction_or_instant_is_never_used(changes, reason):
    result = outcome(confidence=composed(**changes))
    assert result.status == UNAVAILABLE
    assert status_of(result, CONFIDENCE_GATE) == (UNKNOWN, reason)
    assert result.confidence is None
    # The stop this trigger acted on is still reported.
    assert result.gate(RISK_GATE).status == PASS and result.risk is not None


@pytest.mark.parametrize("name", ("setup-score", "context-score", "execution-score",
                                  "setup-factor", "context-factor", "execution-factor"))
def test_a_missing_score_or_declared_factor_never_becomes_a_composed_confidence(name):
    supplied = composed(missing=name)
    assert supplied.status == UNAVAILABLE
    result = outcome(confidence=supplied)
    assert result.status == UNAVAILABLE
    assert status_of(result, CONFIDENCE_GATE) == (
        UNKNOWN, "CONFIDENCE_" + name + ":MISSING_SOURCE")
    assert result.confidence is None


def test_the_confidence_gate_keeps_its_supplied_snapshot_references():
    assert outcome().gate(CONFIDENCE_GATE).input_record_ids == ("m74-supplied-scores",)


# --- the supplied suppression decision ---------------------------------------


@pytest.mark.parametrize("supplied,reason", (
    (None, "SUPPRESSION_HISTORY_UNKNOWN"),
    (history(complete=False), "SUPPRESSION_HISTORY_INCOMPLETE"),
    (history(at=TRIGGER - timedelta(seconds=1)), "SUPPRESSION_HISTORY_STALE"),
    (history(prior(at=TRIGGER + timedelta(seconds=1)), at=TRIGGER + timedelta(minutes=1)),
     "SUPPRESSION_HISTORY_AHEAD"),
))
def test_a_history_the_caller_cannot_vouch_for_never_allows_the_action(supplied, reason):
    result = outcome(history=supplied)
    assert result.status == UNAVAILABLE
    assert status_of(result, SUPPRESSION_GATE) == (UNKNOWN, reason)
    assert result.suppression_reasons == ()
    # Everything the caller did supply for this instant is still reported.
    assert result.risk is not None and result.confidence is not None


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_second_actionable_for_the_same_structure_is_suppressed(direction):
    supplied = history(prior(direction=direction, at=EARLIER), at=TRIGGER)
    result = compose_hod_comp_rs_outcome(outcome_request(
        direction, history=supplied,
        suppression=suppression_policy(cooldown_seconds=0.0)))
    assert result.status == SUPPRESSED
    assert result.suppression_reasons == (SUPPRESSION_REASONS[0],)
    assert status_of(result, SUPPRESSION_GATE) == (FAIL, "DUPLICATE_STRUCTURE_ACTIONABLE")
    # A caller whose own definition allows two keeps the same history passing.
    allowed = compose_hod_comp_rs_outcome(outcome_request(
        direction, history=supplied,
        suppression=suppression_policy(cooldown_seconds=0.0,
                                       max_actionable_per_structure=2)))
    assert allowed.status == READY and allowed.suppression_reasons == ()


def test_the_session_structure_quota_is_the_callers_own_number():
    supplied = history(prior("m74-prior-2", structure_number=2, at=EARLIER),
                       prior("m74-prior-3", structure_number=3, at=EARLIER), at=TRIGGER)
    result = outcome(history=supplied, suppression=suppression_policy(cooldown_seconds=0.0))
    assert result.status == SUPPRESSED
    assert result.suppression_reasons == (SUPPRESSION_REASONS[1],)
    larger = outcome(history=supplied, suppression=suppression_policy(
        cooldown_seconds=0.0, max_structures_per_direction=3))
    assert larger.status == READY


def test_a_structure_already_counted_does_not_consume_the_quota_twice():
    """The quota counts structures already actioned, not this one again."""
    supplied = history(prior("m74-prior-1", structure_number=1, at=EARLIER),
                       prior("m74-prior-2", structure_number=2, at=EARLIER), at=TRIGGER)
    result = outcome(history=supplied, suppression=suppression_policy(
        cooldown_seconds=0.0, max_actionable_per_structure=2))
    assert result.status == READY and result.suppression_reasons == ()


@pytest.mark.parametrize("elapsed,expected", ((299.0, SUPPRESSED), (300.0, READY),
                                              (301.0, READY)))
def test_the_supplied_cooldown_is_measured_from_the_latest_action(elapsed, expected):
    supplied = history(prior("m74-prior-2", structure_number=2,
                             at=TRIGGER - timedelta(seconds=elapsed)), at=TRIGGER)
    result = outcome(history=supplied, suppression=suppression_policy(cooldown_seconds=300.0))
    assert result.status == expected
    if expected == SUPPRESSED:
        assert result.suppression_reasons == (SUPPRESSION_REASONS[2],)


def test_an_opposite_direction_conflict_only_suppresses_while_it_stands():
    outstanding = prior("m74-prior-short", direction="SHORT", structure_number=2,
                        at=TRIGGER - timedelta(seconds=60), outstanding=True)
    result = outcome(history=history(outstanding, at=TRIGGER))
    assert result.status == SUPPRESSED
    assert result.suppression_reasons == (SUPPRESSION_REASONS[3],)
    settled = outcome(history=history(replace(outstanding, outstanding=False), at=TRIGGER))
    assert settled.status == READY
    lapsed = outcome(history=history(
        replace(outstanding, occurred_at=TRIGGER - timedelta(seconds=181)), at=TRIGGER))
    assert lapsed.status == READY
    disabled = outcome(history=history(outstanding, at=TRIGGER),
                       suppression=suppression_policy(suppress_opposite_direction=False))
    assert disabled.status == READY


def test_another_direction_never_consumes_this_direction_quota_or_cooldown():
    supplied = history(prior("m74-prior-short-1", direction="SHORT", structure_number=1,
                             at=TRIGGER - timedelta(seconds=30)),
                       prior("m74-prior-short-2", direction="SHORT", structure_number=2,
                             at=TRIGGER - timedelta(seconds=30)), at=TRIGGER)
    result = outcome(history=supplied,
                     suppression=suppression_policy(suppress_opposite_direction=False))
    assert result.status == READY and result.suppression_reasons == ()


def test_an_earlier_heads_up_does_not_suppress_the_actionable():
    """One heads-up per structure is the M7.3 owner's substate, not a suppression."""
    supplied = history(prior("m74-prior-notice", kind=HEADS_UP_ACTION, at=EARLIER), at=TRIGGER)
    result = outcome(history=supplied)
    assert result.status == READY and result.suppression_reasons == ()


def test_every_supplied_suppression_reason_is_reported_in_one_fixed_order():
    """A structure already actioned cannot also be a new one against the quota."""
    repeated = history(
        prior("m74-prior-1", structure_number=1, at=TRIGGER - timedelta(seconds=30)),
        prior("m74-prior-short", direction="SHORT", structure_number=1,
              at=TRIGGER - timedelta(seconds=60), outstanding=True),
        at=TRIGGER)
    result = outcome(history=repeated)
    assert result.status == SUPPRESSED
    assert result.suppression_reasons == (
        SUPPRESSION_REASONS[0], SUPPRESSION_REASONS[2], SUPPRESSION_REASONS[3])
    assert status_of(result, SUPPRESSION_GATE) == (FAIL, SUPPRESSION_REASONS[0])
    assert result.gate(SUPPRESSION_GATE).input_record_ids == (
        "m74-prior-1", "m74-prior-short")
    fresh = history(
        prior("m74-prior-2", structure_number=2, at=TRIGGER - timedelta(seconds=30)),
        prior("m74-prior-short", direction="SHORT", structure_number=1,
              at=TRIGGER - timedelta(seconds=60), outstanding=True),
        at=TRIGGER)
    quota = outcome(history=fresh,
                    suppression=suppression_policy(max_structures_per_direction=1))
    assert quota.suppression_reasons == (
        SUPPRESSION_REASONS[1], SUPPRESSION_REASONS[2], SUPPRESSION_REASONS[3])


def test_a_suppressed_action_still_reports_the_facts_it_was_built_from():
    supplied = history(prior(at=EARLIER), at=TRIGGER)
    result = outcome(history=supplied)
    assert result.status == SUPPRESSED
    assert result.risk == risk_level() and result.targets == targets()
    assert result.confidence is not None
    assert result.reasons == (SUPPRESSION_GATE + ":" + FAIL + ":" + SUPPRESSION_REASONS[0],)


def test_a_refusal_or_an_unknown_input_outranks_a_suppression():
    supplied = history(prior(at=EARLIER), at=TRIGGER)
    refused = outcome(history=supplied, assessment=assessment_of(observations=grid(prices=SIX)))
    assert refused.status == REJECTED
    assert refused.gate(SUPPRESSION_GATE).status == FAIL
    unknown = outcome(history=supplied, confidence=composed(at=CROSS))
    assert unknown.status == UNAVAILABLE
    assert unknown.gate(SUPPRESSION_GATE).status == FAIL


def test_one_unknown_input_and_one_refusal_stay_unavailable():
    result = outcome(structural=structural(targets=targets(
        supplied=((100.90, 1.5), (102.20, 2.5)))), confidence=composed(at=CROSS))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (FAIL, "TARGET_NOT_BEYOND_ENTRY")
    assert status_of(result, CONFIDENCE_GATE) == (UNKNOWN, "CONFIDENCE_NOT_CURRENT")
    assert result.reasons == (
        RISK_GATE + ":" + FAIL + ":TARGET_NOT_BEYOND_ENTRY",
        CONFIDENCE_GATE + ":" + UNKNOWN + ":CONFIDENCE_NOT_CURRENT")


# --- immutability, stability and adopted numbers -----------------------------


@pytest.mark.parametrize("changes", (
    {"name": "NOT_A_GATE"}, {"status": "MAYBE"}, {"status": "FAIL", "reason": None},
    {"reason": "UNKNOWN"}, {"input_record_ids": ["a"]}, {"input_record_ids": (" ",)},
))
def test_outcome_gates_require_supported_facts(changes):
    values = dict(name=RISK_GATE, status=FAIL, reason="STOP_ON_THE_WRONG_SIDE",
                  input_record_ids=())
    values.update(changes)
    with pytest.raises(RecordError):
        OutcomeGate(**values)


def test_every_reported_gate_name_is_a_supported_one():
    assert tuple(row.name for row in outcome().gates) == OUTCOME_GATES
    assert OutcomeGate(TRIGGER_GATE, PASS).as_dict()["input_record_ids"] == []


def test_composed_outcomes_and_their_gates_are_immutable_and_stable():
    result = outcome()
    with pytest.raises(FrozenInstanceError):
        result.gates[0].__setattr__("status", FAIL)
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("status", READY)
    assert result.to_json() == outcome().to_json()
    payload = json.loads(result.to_json())
    assert payload["outcome_version"] == OUTCOME_VERSION
    assert payload["strategy_id"] == STRATEGY_ID and payload["mode"] == TAPE
    assert payload["crossed_at"] == "2026-07-06T13:50:00Z"
    assert payload["suppression_version"] == POLICY_VERSION
    assert payload["unavailable"] == list(UNDEFINED)


def test_the_module_adopts_no_rule_number_of_its_own():
    source = inspect.getsource(hod_comp_rs_risk_confidence)
    for token in ("0.05", "1.5", "2.5", "0.70", "1.40", "0.35", "0.60", "600",
                  "compression_low - ", "rs_15m"):
        assert token not in source
    assert isinstance(outcome(), HodCompRsOutcome)


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           trigger_rules())


async def test_the_composed_outcome_at_one_recorded_trigger():
    proofs = []
    connection = await db.init_db()
    for direction in ("LONG", "SHORT"):
        frozen = freeze_structure(
            trigger_policy(), direction=direction, frozen_at=EARLY,
            reference_extreme=REFERENCE[direction], compression_high=COMPRESSION[direction][0],
            compression_low=COMPRESSION[direction][1], latest_atr=ATR,
            anchor_bar_id="m73-anchor-minute", structure_number=1,
            input_record_ids=("m73-compression-window", "m73-reference-freeze"))
        assert frozen.boundary == BOUNDARY[direction]
        subject = owner(direction, strategy_version=VERSION)
        subject.reserve_structure(EARLY)
        engine = StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection))
        store = ResearchEventStore(connection)

        crossing_context, _ = eligibility(direction, at=CROSS)
        opening = subject.open_crossing(frozen, crossed_at=CROSS,
                                        record_id="m74-open-" + direction)
        await engine.apply(opening[0], context=crossing_context)
        assert subject.confirm(opening[0]) == StrategyState("ARMED", "CROSSING_OBSERVED")

        context, standing = eligibility(direction, at=TRIGGER)
        evaluation = trigger_request(direction, structure=frozen, eligibility=standing)
        assessment, changes = subject.propose(evaluation, record_id="m74-trigger-" + direction)
        assert assessment.state == StrategyState("ALERT_TRIGGERED")
        entry = await engine.apply(changes[0], context=context)
        assert subject.confirm(changes[0]) == StrategyState("ALERT_TRIGGERED")

        stored = await store.append(changes[0], session=DAY, recorded_at=TRIGGER)
        assert await store.append(changes[0], session=DAY, recorded_at=TRIGGER) == stored

        request = HodCompRsOutcomeRequest(
            assessment=assessment, structural=structural(direction),
            confidence=composed(direction), suppression=suppression_policy(),
            history=history(at=TRIGGER), strategy_version=VERSION,
            definition_reference=DEFINITION)
        result = compose_hod_comp_rs_outcome(request)
        assert result.status == READY and result.reasons == ()
        assert isinstance(result, HodCompRsOutcome)
        assert compose_hod_comp_rs_outcome(request).to_json() == result.to_json()

        # The same composition after the caller records this action is suppressed.
        again = compose_hod_comp_rs_outcome(replace(request, history=history(
            prior("m74-trigger-" + direction, direction=direction, at=TRIGGER), at=TRIGGER)))
        assert again.status == SUPPRESSED
        assert again.suppression_reasons[0] == SUPPRESSION_REASONS[0]

        proofs.append({
            "synthetic_only": True, "direction": direction,
            "structure": frozen.as_dict(), "outcome": result.as_dict(),
            "suppressed_outcome": again.as_dict(), "transition": changes[0].as_dict(),
            "stored_position": entry.position, "stored_fingerprint": stored["fingerprint"],
            "repeated_outcome_identical": True,
        })
    await db.close_db()
    payload = {"evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
               "outcome_version": OUTCOME_VERSION, "runs": proofs}
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    (Path(os.environ["TMPDIR"]) / "m7_4_hod_comp_rs_risk_confidence_proof.json").write_text(
        rendered)
