"""M6.3 supplied risk, targets and confidence contracts for `CRVOL_ORB5`.

Every number below is a synthetic fixture supplied by the caller. A READY
composition proves the offline contract only: it establishes no source coverage,
no adopted `M03B_ORB5_V1` rule, no approved catalog or factor roster, no quality
cutoff, no alert and no permission to act.
"""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import json
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine import db
from consensus_engine.confidence import (
    COMPONENTS, ConfidencePolicy, ConfidenceRequest, ConfidenceTerm, compose_confidence,
)
from consensus_engine.event_store import ResearchEventStore
from consensus_engine.orb5_risk_confidence import (
    CONFIDENCE_GATE, OUTCOME_GATES, OUTCOME_VERSION, Orb5Outcome, Orb5OutcomeRequest,
    OutcomeGate, READY, REJECTED, RISK_GATE, STRATEGY_ID, TRIGGER_GATE, UNAVAILABLE,
    UNDEFINED, compose_orb5_outcome,
)
from consensus_engine.orb5_trigger import (
    FAIL, MODE_VARIANTS, PASS, QUOTE_PROJECTED, TAPE, UNKNOWN, evaluate_orb5_trigger,
    freeze_candidate, trigger_rules,
)
from consensus_engine.state_transitions import StateTransitionEngine, TransitionScope
from consensus_engine.strategy_interface import StrategyContext, StrategyState
from consensus_engine.structural_risk import VARIANTS, select_b_risk_targets
from consensus_engine.trade_alerts_models import (
    FeatureSnapshot, FeatureValue, RecordError, RiskLevel, TargetLevel,
)
from consensus_engine.transition_store import SQLiteTransitionStore
from test_orb5_eligibility import DAY, metadata
from test_orb5_trigger import (
    BOUNDARY, CROSS, PRICES, RANGE, TRIGGER, eligibility, geometry as trigger_geometry,
    grid, minute_close, owner, request as trigger_request, trigger_policy,
)
from test_strategy_interface import session
from test_structural_risk import changed_value


VERSION = "M63_FIXTURE_ONLY_V1"
POLICY_VERSION = "M63_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M63_SUPPLIED_FIXTURE_DEFINITION"
MODE = "SUPPLIED_FIXTURE_SCORE_POINTS"
SCORES = (80.0, 60.0, 40.0)


def terms():
    """One supplied score and one declared factor for each M4.4 component."""
    return tuple(
        ConfidenceTerm(component.lower() + "-" + kind.lower(), component, kind,
                       component.lower() + "-" + kind.lower(), VERSION, MODE)
        for component in COMPONENTS for kind in ("SCORE", "FACTOR")
    )


def confidence_policy(*, strategy_id=STRATEGY_ID, strategy_version=VERSION, weights=(.5, .3, .2)):
    return ConfidencePolicy(strategy_id, strategy_version, POLICY_VERSION, *weights, terms())


def scores_snapshot(scores=SCORES, *, at=TRIGGER, record_id="m63-supplied-scores", missing=None):
    features = tuple(
        FeatureValue(term.feature_name,
                     None if term.name == missing else scores[COMPONENTS.index(term.component)],
                     "SCORE_POINTS", "MISSING_SOURCE" if term.name == missing else None,
                     ("m63-score-input",))
        for term in terms()
    )
    return FeatureSnapshot(record_id=record_id, metadata=metadata(at, data_mode=MODE),
                           evaluated_at=at, feature_version=VERSION, features=features,
                           input_record_ids=("m63-score-input",))


def confidence_request(direction="LONG", *, at=TRIGGER, scores=SCORES, missing=None,
                       supplied_policy=None):
    rules = supplied_policy if supplied_policy is not None else confidence_policy()
    snapshot = scores_snapshot(scores, at=at, missing=missing)
    context = StrategyContext(session(DAY), "SYNTH", "EQUITY", direction, at, (snapshot,))
    return ConfidenceRequest(
        context, rules, tuple((term.name, snapshot.record_id) for term in rules.terms))


def composed(direction="LONG", **changes):
    return compose_confidence(confidence_request(direction, **changes))


def assessment_of(direction="LONG", *, mode=TAPE, at=TRIGGER, **changes):
    return evaluate_orb5_trigger(trigger_request(direction, mode=mode, at=at, **changes))


def request_values(direction="LONG", *, mode=TAPE, at=TRIGGER):
    return dict(assessment=assessment_of(direction, mode=mode, at=at),
                geometry=trigger_geometry(direction, mode=mode, at=at),
                confidence=composed(direction, at=at), strategy_version=VERSION,
                definition_reference=DEFINITION)


def outcome_request(direction="LONG", *, mode=TAPE, at=TRIGGER, **changes):
    values = request_values(direction, mode=mode, at=at)
    values.update(changes)
    return Orb5OutcomeRequest(**values)


def outcome(direction="LONG", **changes):
    return compose_orb5_outcome(outcome_request(direction, **changes))


def status_of(result, name):
    row = result.gate(name)
    return row.status, row.reason


# --- supplied record contracts ----------------------------------------------


@pytest.mark.parametrize("changes", (
    {"assessment": "ALERT_TRIGGERED"}, {"assessment": None}, {"geometry": "READY"},
    {"geometry": None}, {"confidence": "READY"}, {"confidence": None},
    {"strategy_version": ""}, {"strategy_version": " "}, {"strategy_version": "UNKNOWN"},
    {"strategy_version": 1}, {"definition_reference": ""}, {"definition_reference": "UNSPECIFIED"},
    {"definition_reference": None},
))
def test_request_requires_canonical_supplied_parts(changes):
    with pytest.raises(RecordError):
        outcome_request(**changes)


def test_composition_refuses_anything_but_its_own_request():
    for supplied in ("READY", None, outcome_request().assessment):
        with pytest.raises(RecordError):
            compose_orb5_outcome(supplied)


@pytest.mark.parametrize("changes", (
    {"name": "OTHER_GATE"}, {"name": ""}, {"status": "MAYBE"}, {"status": "pass"},
    {"status": FAIL, "reason": None}, {"status": UNKNOWN, "reason": None},
    {"reason": "UNKNOWN"}, {"reason": " "}, {"input_record_ids": ["a"]},
    {"input_record_ids": (" ",)}, {"input_record_ids": (1,)},
))
def test_outcome_gate_requires_supported_supplied_facts(changes):
    values = dict(name=RISK_GATE, status=FAIL, reason="GEOMETRY_STALE_EXTENSION",
                  input_record_ids=("m63-level",))
    values.update(changes)
    with pytest.raises(RecordError):
        OutcomeGate(**values)


def test_every_reported_gate_belongs_to_this_milestone():
    result = outcome()
    assert tuple(row.name for row in result.gates) == OUTCOME_GATES
    assert OUTCOME_GATES == (TRIGGER_GATE, RISK_GATE, CONFIDENCE_GATE)


def test_composed_results_and_gates_are_immutable():
    result = outcome()
    with pytest.raises(FrozenInstanceError):
        result.status = REJECTED
    with pytest.raises(FrozenInstanceError):
        result.gates[0].status = FAIL


def test_the_module_defaults_no_number_of_its_own():
    from consensus_engine import orb5_risk_confidence

    numbers = {name: value for name, value in vars(orb5_risk_confidence).items()
               if not name.startswith("_") and isinstance(value, (int, float))
               and not isinstance(value, bool)}
    assert numbers == {}


# --- the composed READY path ------------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("mode", (TAPE, QUOTE_PROJECTED))
def test_both_arms_compose_the_supplied_stop_targets_and_confidence(direction, mode):
    supplied = outcome_request(direction, mode=mode)
    result = compose_orb5_outcome(supplied)
    assert result.status == READY and result.reasons == ()
    assert all(row.status == PASS for row in result.gates)
    assert result.state == StrategyState("ALERT_TRIGGERED")
    assert result.evaluated_at == TRIGGER
    assert result.candidate == supplied.assessment.candidate
    assert result.risk == supplied.geometry.risk
    assert result.targets == supplied.geometry.targets
    assert result.target_labels == supplied.geometry.target_labels
    assert result.target_input_ids == supplied.geometry.target_input_ids
    assert result.extension_r == supplied.geometry.extension_r
    assert result.confidence == supplied.confidence.confidence
    assert result.strategy_version == VERSION
    assert result.definition_reference == DEFINITION
    assert supplied.geometry.request.variant == MODE_VARIANTS[mode]


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_the_supplied_geometry_and_scores_are_reported_unchanged(direction):
    supplied = outcome_request(direction)
    result = compose_orb5_outcome(supplied)
    sign = 1 if direction == "LONG" else -1
    assert result.risk.entry_reference == PRICES[direction][2]
    assert sign * (result.risk.entry_reference - BOUNDARY[direction]) >= 0
    assert sign * (result.risk.entry_reference - result.risk.hard_stop) > 0
    assert tuple(row.name for row in result.targets) == ("T1", "T2")
    assert all(sign * (row.price - result.risk.entry_reference) > 0 for row in result.targets)
    assert (result.confidence.setup_score, result.confidence.context_score,
            result.confidence.execution_score) == SCORES
    assert result.confidence.final_score == 66
    assert tuple(row.name for row in result.confidence.factors) == (
        "setup-factor", "context-factor", "execution-factor")


def test_the_composition_names_what_no_definition_supplies():
    result = outcome()
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable
    assert set(UNDEFINED) <= set(result.unavailable)
    assert {"SOFT_INVALIDATION_UNDEFINED", "RUNNER_UNDEFINED"} <= set(result.unavailable)


def test_a_single_admitted_target_keeps_t2_reported_as_unavailable():
    supplied = trigger_geometry().request
    catalog = replace(supplied.catalog, levels=supplied.catalog.levels[:1])
    single = select_b_risk_targets(replace(supplied, catalog=catalog))
    assert single.status == "READY" and len(single.targets) == 1
    result = compose_orb5_outcome(outcome_request(geometry=single))
    assert result.status == READY
    assert "T2_UNAVAILABLE" in result.unavailable


@pytest.mark.parametrize("scores,expected", (((0, 0, 0), 0), ((100, 100, 100), 100),
                                             ((1, 1, 1), 1)))
def test_no_quality_cutoff_is_applied_to_the_supplied_confidence(scores, expected):
    result = compose_orb5_outcome(outcome_request(confidence=composed(scores=scores)))
    assert result.status == READY
    assert result.confidence.final_score == expected
    assert "CONFIDENCE_FLOOR_UNDEFINED" in result.unavailable


@pytest.mark.parametrize("weights,expected", (((.5, .3, .2), 66), ((.45, .35, .2), 65),
                                              ((.4, .4, .2), 64)))
def test_the_callers_own_weights_are_preserved(weights, expected):
    supplied = composed(supplied_policy=confidence_policy(weights=weights))
    result = compose_orb5_outcome(outcome_request(confidence=supplied))
    assert result.status == READY and result.confidence.final_score == expected
    assert supplied.request.policy.version == POLICY_VERSION


def test_the_same_supplied_inputs_compose_the_same_record_twice():
    supplied = outcome_request()
    first, second = compose_orb5_outcome(supplied), compose_orb5_outcome(supplied)
    assert first.to_json() == second.to_json()
    rendered = json.loads(first.to_json())
    assert rendered["outcome_version"] == OUTCOME_VERSION
    assert rendered["strategy_id"] == STRATEGY_ID
    assert rendered["status"] == READY and rendered["reasons"] == []
    assert rendered["candidate"]["boundary"] == BOUNDARY["LONG"]
    assert rendered["risk"]["risk_per_share"] == first.risk.risk_per_share
    assert [row["name"] for row in rendered["targets"]] == ["T1", "T2"]
    assert rendered["confidence"]["final_score"] == 66
    assert rendered["definition_reference"] == DEFINITION


# --- the trigger gate -------------------------------------------------------


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_trigger_that_is_not_actionable_carries_no_ready_outcome(direction):
    # Six of ten samples accept, so the supplied acceptance window fails.
    prices = (PRICES["LONG"][2],) * 6 + (PRICES["LONG"][0],) * 4
    assessment = assessment_of(direction, observations=grid(direction, prices=prices))
    assert assessment.state != StrategyState("ALERT_TRIGGERED")
    result = compose_orb5_outcome(outcome_request(direction, assessment=assessment))
    assert result.status == REJECTED
    assert status_of(result, TRIGGER_GATE) == (FAIL, "TRIGGER_NOT_ACTIONABLE_ACCEPTANCE_WINDOW")
    assert result.reasons[0].startswith(TRIGGER_GATE + ":" + FAIL)
    assert result.state == assessment.state


def test_an_unknown_trigger_input_keeps_the_outcome_unavailable():
    assessment = assessment_of(participation=None)
    result = compose_orb5_outcome(outcome_request(assessment=assessment))
    assert result.status == UNAVAILABLE
    assert status_of(result, TRIGGER_GATE) == (UNKNOWN, "TRIGGER_UNKNOWN_PARTICIPATION")
    # The other supplied parts are still reported; unknown never becomes a pass.
    assert result.gate(RISK_GATE).status == PASS and result.gate(CONFIDENCE_GATE).status == PASS


def test_an_invalidated_attempt_is_reported_as_refused():
    inside = minute_close(close=100.5)
    assessment = assessment_of(minute_close=inside)
    assert assessment.state == StrategyState("INVALIDATED")
    result = compose_orb5_outcome(outcome_request(assessment=assessment))
    assert result.status == REJECTED
    assert status_of(result, TRIGGER_GATE) == (FAIL, "TRIGGER_NOT_ACTIONABLE_ATTEMPT_ACTIVE")


def test_the_trigger_gate_keeps_the_frozen_crossing_references():
    result = outcome()
    assert result.gate(TRIGGER_GATE).input_record_ids == (
        "m62-crossing-previous", "m62-crossing-current")


# --- the M4.3 geometry this trigger acted on --------------------------------


@pytest.mark.parametrize("supplied,reason", (
    (dict(mode=QUOTE_PROJECTED), "GEOMETRY_ARM_MISMATCH"),
    (dict(direction="SHORT"), "GEOMETRY_DIRECTION_MISMATCH"),
    (dict(crossed_at=CROSS - timedelta(minutes=1), at=TRIGGER), "GEOMETRY_CROSSING_MISMATCH"),
    (dict(at=TRIGGER + timedelta(seconds=1)), "GEOMETRY_NOT_CURRENT"),
))
def test_foreign_or_stale_geometry_cannot_serve_this_frozen_trigger(supplied, reason):
    result = compose_orb5_outcome(outcome_request(geometry=trigger_geometry(**supplied)))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, reason)
    assert result.risk is None and result.targets == () and result.extension_r is None


def test_geometry_measured_from_another_boundary_cannot_serve_this_trigger():
    supplied = trigger_geometry().request
    moved = select_b_risk_targets(replace(supplied, boundary=changed_value(
        supplied.boundary, 101.01)))
    assert moved.status == "READY"
    result = compose_orb5_outcome(outcome_request(geometry=moved))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, "GEOMETRY_BOUNDARY_MISMATCH")


def test_a_geometry_without_its_boundary_value_is_unknown_not_assumed():
    supplied = trigger_geometry()
    blind = replace(supplied, request=replace(
        supplied.request, boundary=changed_value(supplied.request.boundary, None)))
    result = compose_orb5_outcome(outcome_request(geometry=blind))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, "GEOMETRY_BOUNDARY_MISMATCH")


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_a_refused_geometry_refuses_the_outcome(direction):
    supplied = trigger_geometry(direction, outcome="REJECTED")
    result = compose_orb5_outcome(outcome_request(direction, geometry=supplied))
    assert result.status == REJECTED
    assert status_of(result, RISK_GATE) == (FAIL, "GEOMETRY_ENTRY_BEFORE_BOUNDARY")
    assert result.risk is None and result.targets == ()
    # A complete confidence never repairs refused geometry.
    assert result.gate(CONFIDENCE_GATE).status == PASS and result.confidence is not None


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_an_incomplete_geometry_keeps_the_outcome_unavailable(direction):
    supplied = trigger_geometry(direction, outcome="UNAVAILABLE")
    result = compose_orb5_outcome(outcome_request(direction, geometry=supplied))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, "GEOMETRY_ANCHOR_PATH_INCOMPLETE")


@pytest.mark.parametrize("changes,reason", (
    ({"risk": None}, "GEOMETRY_LEVELS_UNAVAILABLE"),
    ({"targets": ()}, "GEOMETRY_LEVELS_UNAVAILABLE"),
))
def test_a_ready_label_without_levels_is_unknown_not_passing(changes, reason):
    supplied = replace(trigger_geometry(), **changes)
    result = compose_orb5_outcome(outcome_request(geometry=supplied))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (UNKNOWN, reason)


@pytest.mark.parametrize("risk,reason", (
    ((101.01, 100.78, 0.23), "ENTRY_INSIDE_FROZEN_BOUNDARY"),
    ((101.03, 101.28, 0.25), "STOP_ON_THE_WRONG_SIDE"),
))
def test_a_supplied_result_must_be_framed_on_this_frozen_boundary(risk, reason):
    entry, stop, distance = risk
    supplied = replace(trigger_geometry(), risk=RiskLevel(
        entry, stop, distance, "Synthetic fixture geometry only", "m63-fixture"))
    result = compose_orb5_outcome(outcome_request(geometry=supplied))
    assert result.status == REJECTED
    assert status_of(result, RISK_GATE) == (FAIL, reason)
    assert result.risk is None


def test_a_target_that_is_not_beyond_the_entry_refuses_the_outcome():
    supplied = trigger_geometry()
    behind = replace(supplied, targets=(
        supplied.targets[0], TargetLevel("T2", 100.90, 2.5, "m63-fixture")))
    result = compose_orb5_outcome(outcome_request(geometry=behind))
    assert result.status == REJECTED
    assert status_of(result, RISK_GATE) == (FAIL, "TARGET_NOT_BEYOND_ENTRY")


def test_the_risk_gate_keeps_the_supplied_level_references():
    supplied = trigger_geometry()
    result = compose_orb5_outcome(outcome_request(geometry=supplied))
    assert result.gate(RISK_GATE).input_record_ids == tuple(sorted(
        {value for row in supplied.target_input_ids for value in row}))
    assert result.gate(RISK_GATE).input_record_ids != ()


# --- the M4.4 confidence for this instant -----------------------------------


@pytest.mark.parametrize("changes,reason", (
    (dict(supplied_policy=confidence_policy(strategy_id="HOD_COMP_RS")),
     "CONFIDENCE_STRATEGY_MISMATCH"),
    (dict(supplied_policy=confidence_policy(strategy_version="M63_OTHER_VERSION")),
     "CONFIDENCE_VERSION_MISMATCH"),
    (dict(direction="SHORT"), "CONFIDENCE_DIRECTION_MISMATCH"),
    (dict(at=CROSS), "CONFIDENCE_NOT_CURRENT"),
))
def test_confidence_from_another_strategy_direction_or_instant_is_never_used(changes, reason):
    result = compose_orb5_outcome(outcome_request(confidence=composed(**changes)))
    assert result.status == UNAVAILABLE
    assert status_of(result, CONFIDENCE_GATE) == (UNKNOWN, reason)
    assert result.confidence is None
    # The geometry this trigger acted on is still reported.
    assert result.gate(RISK_GATE).status == PASS and result.risk is not None


@pytest.mark.parametrize("name", ("setup-score", "context-score", "execution-score",
                                  "setup-factor", "context-factor", "execution-factor"))
def test_a_missing_score_or_declared_factor_never_becomes_a_composed_confidence(name):
    supplied = composed(missing=name)
    assert supplied.status == "UNAVAILABLE"
    result = compose_orb5_outcome(outcome_request(confidence=supplied))
    assert result.status == UNAVAILABLE
    assert status_of(result, CONFIDENCE_GATE) == (
        UNKNOWN, "CONFIDENCE_" + name + ":MISSING_SOURCE")
    assert result.confidence is None


def test_the_confidence_gate_keeps_its_supplied_snapshot_references():
    result = outcome()
    assert result.gate(CONFIDENCE_GATE).input_record_ids == ("m63-supplied-scores",)


def test_one_unknown_input_and_one_refusal_stay_unavailable():
    result = compose_orb5_outcome(outcome_request(
        geometry=trigger_geometry(outcome="REJECTED"), confidence=composed(at=CROSS)))
    assert result.status == UNAVAILABLE
    assert status_of(result, RISK_GATE) == (FAIL, "GEOMETRY_ENTRY_BEFORE_BOUNDARY")
    assert status_of(result, CONFIDENCE_GATE) == (UNKNOWN, "CONFIDENCE_NOT_CURRENT")
    assert result.reasons == (
        RISK_GATE + ":" + FAIL + ":GEOMETRY_ENTRY_BEFORE_BOUNDARY",
        CONFIDENCE_GATE + ":" + UNKNOWN + ":CONFIDENCE_NOT_CURRENT")


# --- the M4.2 engine, the M5.1 store and the recorded proof ------------------


def scope(direction):
    return TransitionScope(session(DAY), "SYNTH", "EQUITY", direction, STRATEGY_ID, VERSION,
                           trigger_rules())


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
async def test_the_composed_outcome_at_one_recorded_trigger(direction):
    supplied = trigger_geometry(direction)
    context, armed = eligibility(direction, geometry_result=supplied)
    crossing_context, _ = eligibility(direction, at=CROSS)
    frozen = freeze_candidate(trigger_policy(), direction=direction, crossed_at=CROSS,
                              opening_range_high=RANGE[direction][0],
                              opening_range_low=RANGE[direction][1], latest_atr=0.4,
                              anchor_bar_id="m62-anchor-minute", attempt_number=1)
    subject = owner(direction, strategy_version=VERSION)
    opening = subject.open_attempt(frozen, record_id="m63-open-" + direction)

    connection = await db.init_db()
    engine = StateTransitionEngine(scope(direction), SQLiteTransitionStore(connection))
    await engine.apply(opening[0], context=crossing_context)
    subject.confirm(opening[0])

    evaluation = trigger_request(direction, eligibility=armed, geometry=supplied,
                                 candidate=frozen)
    assessment, changes = subject.propose(evaluation, record_id="m63-trigger-" + direction)
    assert assessment.state == StrategyState("ALERT_TRIGGERED")
    entry = await engine.apply(changes[0], context=context)
    assert subject.confirm(changes[0]) == StrategyState("ALERT_TRIGGERED")

    store = ResearchEventStore(connection)
    stored = await store.append(changes[0], session=DAY, recorded_at=TRIGGER)
    assert await store.append(changes[0], session=DAY, recorded_at=TRIGGER) == stored

    scores = composed(direction)
    request = Orb5OutcomeRequest(assessment, supplied, scores, VERSION, DEFINITION)
    result = compose_orb5_outcome(request)
    assert result.status == READY and result.reasons == ()
    assert isinstance(result, Orb5Outcome)

    proof = {
        "synthetic_only": True, "direction": direction,
        "candidate": frozen.as_dict(), "outcome": result.as_dict(),
        "transition": changes[0].as_dict(), "stored_position": entry.position,
        "stored_fingerprint": stored["fingerprint"],
        "repeated_outcome_identical":
            compose_orb5_outcome(request).to_json() == result.to_json(),
    }
    assert proof["repeated_outcome_identical"]
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    Path(f"/tmp/m63-orb5-risk-confidence-{direction.lower()}-proof.json").write_text(rendered)


@pytest.mark.parametrize("mode,variant", ((TAPE, VARIANTS[0]), (QUOTE_PROJECTED, VARIANTS[1])))
def test_each_arm_keeps_its_own_supplied_variant_through_the_composition(mode, variant):
    result = compose_orb5_outcome(outcome_request(mode=mode))
    assert result.status == READY
    assert MODE_VARIANTS[result.candidate.mode] == variant
    other = TAPE if mode == QUOTE_PROJECTED else QUOTE_PROJECTED
    crossed = compose_orb5_outcome(outcome_request(
        mode=mode, geometry=trigger_geometry(mode=other)))
    assert crossed.status == UNAVAILABLE
    assert status_of(crossed, RISK_GATE) == (UNKNOWN, "GEOMETRY_ARM_MISMATCH")
