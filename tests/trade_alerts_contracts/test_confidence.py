"""Supplied score arithmetic and attribution only; no trading scoring policy."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.confidence import (
    COMPONENTS, COMPOSITION_VERSION, ConfidencePolicy, ConfidenceRequest,
    ConfidenceTerm, compose_confidence,
)
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.strategy_interface import StrategyContext
from consensus_engine.trade_alerts_config import STRATEGY_IDS, TradeAlertsConfig
from consensus_engine.trade_alerts_models import (
    AlertCandidate, Bar, ConfidenceBreakdown, ConfidenceComponent, FeatureSnapshot,
    FeatureValue, OptionRecommendation, RecordError, RiskLevel, SessionRecord, TargetLevel,
)
from test_opening_range_features import history
from test_strategy_interface import START, metadata, session


VERSION = "M44_FIXTURE_ONLY_V1"
MODE = "SUPPLIED_FIXTURE_SCORE_POINTS"


def policy(weights=(.5, .3, .2), strategy_id="CRVOL_ORB5"):
    terms = tuple(
        ConfidenceTerm(component.lower() + "-" + kind.lower(), component, kind,
                       component.lower() + "-" + kind.lower(), VERSION, MODE)
        for component in COMPONENTS for kind in ("SCORE", "FACTOR")
    )
    return ConfidencePolicy(strategy_id, VERSION, VERSION, *weights, terms)


def request(scores=(80, 60, 40), *, direction="LONG", supplied_policy=None,
            parents=("synthetic-input",)):
    rules = supplied_policy or policy()
    features = tuple(
        FeatureValue(term.feature_name, scores[COMPONENTS.index(term.component)],
                     "SCORE_POINTS", input_record_ids=parents)
        for term in rules.terms
    )
    snapshot = FeatureSnapshot(
        record_id="m44-supplied-scores", metadata=metadata(data_mode=MODE),
        evaluated_at=START, feature_version=VERSION, features=features,
        input_record_ids=parents,
    )
    context = StrategyContext(session(), "SYNTH", "EQUITY", direction, START,
                              (FeatureSnapshot.from_json(snapshot.to_json()),))
    return ConfidenceRequest(context, rules, tuple((term.name, snapshot.record_id) for term in rules.terms))


def with_snapshot(supplied, snapshot):
    return replace(supplied, context=replace(supplied.context, features=(snapshot,)))


def with_value(supplied, name, value, **changes):
    snapshot = supplied.context.features[0]
    features = tuple(
        replace(f, value=value, missing_reason="MISSING_SOURCE" if value is None else None, **changes)
        if f.name == name else f for f in snapshot.features
    )
    return with_snapshot(supplied, replace(snapshot, features=features))


def candidate(supplied, result, alert_type="ACTIONABLE"):
    direction = supplied.context.direction
    sign = 1 if direction == "LONG" else -1
    saved = supplied.context.session
    return AlertCandidate(
        record_id="m44-" + direction + "-" + alert_type, metadata=metadata(data_mode=MODE),
        strategy_id=supplied.policy.strategy_id, strategy_version=supplied.policy.strategy_version,
        direction=direction, alert_type=alert_type, setup_state="ALERT_TRIGGERED",
        strategy_lifecycle="DEVELOPMENT", evidence_stage="IMPLEMENTED", delivery_status="PENDING",
        structure_id="M44_FIXTURE_STRUCTURE", trigger_price=100, alert_price=100,
        risk=RiskLevel(100, 100 - sign, 1, "Fixture geometry only", VERSION),
        targets=(TargetLevel("T1", 100 + 2 * sign, 2, VERSION),),
        confidence=result.confidence, input_record_ids=tuple(f.record_id for f in supplied.context.features),
        feature_snapshot_id=supplied.context.features[0].record_id,
        session_record_id=saved.record_id, config_version=saved.config_version,
        config_hash=saved.config_hash, created_at=START, expires_at=START + timedelta(seconds=1),
        data_quality="VALID", mechanically_valid=True,
    )


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("weights,expected", (((.5, .3, .2), 66), ((.45, .35, .2), 65),
                                             ((.4, .4, .2), 64), ((.45, .3, .25), 64)))
def test_hand_worked_supplied_weight_arithmetic(direction, weights, expected):
    supplied = request(direction=direction, supplied_policy=policy(weights))
    result = compose_confidence(supplied)
    assert result.status == "READY" and result.reasons == ()
    assert result.confidence == ConfidenceBreakdown(
        80, 60, 40, expected, tuple(ConfidenceComponent(name + "-factor", score, VERSION)
                                  for name, score in (("setup", 80), ("context", 60), ("execution", 40))))
    assert result.request == supplied


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_each_playbook_preserves_its_explicit_current_weights(strategy_id):
    weights = {"INDEX_OPEN_DRIVE_BREADTH": (.45, .35, .2),
               "CAT_FIRST_CONSOL": (.4, .4, .2), "VP_ACCEPT_LVN": (.45, .3, .25)}.get(
                   strategy_id, (.5, .3, .2))
    supplied = request(supplied_policy=policy(weights, strategy_id))
    result = compose_confidence(supplied)
    assert result.status == "READY"
    assert (result.request.policy.setup_weight, result.request.policy.context_weight,
            result.request.policy.execution_weight) == weights
    assert result.request.policy.strategy_id == strategy_id
    assert result.request.policy.version == VERSION  # synthetic factors, never an adopted policy


@pytest.mark.parametrize("scores,expected", (((0, 0, 0), 0), ((100, 100, 100), 100),
                                          ((.1, .2, .3), .17), ((80.000000002, 60, 40), 66.000000001)))
def test_zero_endpoints_and_unrounded_decimal_weighting(scores, expected):
    result = compose_confidence(request(scores))
    assert result.status == "READY" and result.confidence.final_score == expected
    assert (result.confidence.setup_score, result.confidence.context_score,
            result.confidence.execution_score) == scores


@pytest.mark.parametrize("name", ("setup-score", "context-score", "execution-score",
                                  "setup-factor", "context-factor", "execution-factor"))
def test_unknown_scores_and_declared_factors_never_become_zero_or_get_dropped(name):
    supplied = with_value(request(), name, None)
    result = compose_confidence(supplied)
    assert result.status == "UNAVAILABLE" and result.confidence is None
    assert result.reasons == (name + ":MISSING_SOURCE",)
    assert result.as_dict()["request"]["context"]["features"][0]["features"] == supplied.context.features[0].as_dict()["features"]


def test_missing_binding_snapshot_or_feature_cannot_hide_a_required_factor():
    supplied = request()
    missing_binding = replace(supplied, bindings=supplied.bindings[:-1])
    wrong_id = replace(supplied, bindings=(*supplied.bindings[:-1], ("execution-factor", "absent")))
    snapshot = supplied.context.features[0]
    missing_feature = with_snapshot(supplied, replace(snapshot, features=snapshot.features[:-1]))
    for value, reason in ((missing_binding, "SNAPSHOT_UNAVAILABLE"), (wrong_id, "SNAPSHOT_UNAVAILABLE"),
                          (missing_feature, "FEATURE_UNAVAILABLE")):
        result = compose_confidence(value)
        assert result.confidence is None
        assert result.reasons == ("execution-factor:" + reason,)


def test_zero_weight_still_requires_score_and_factor_without_renormalizing():
    supplied = request(supplied_policy=policy((1, 0, 0)))
    assert compose_confidence(supplied).confidence.final_score == 80
    for name in ("execution-score", "context-factor"):
        result = compose_confidence(with_value(supplied, name, None))
        assert result.status == "UNAVAILABLE" and result.confidence is None
    assert supplied.policy.execution_weight == 0


def test_signed_factor_contributions_are_preserved_without_inventing_normalization():
    supplied = with_value(request(), "context-factor", -3.25)
    result = compose_confidence(supplied)
    assert result.confidence.context_score == 60 and result.confidence.final_score == 66
    assert result.confidence.factors[1] == ConfidenceComponent("context-factor", -3.25, VERSION)


def test_multiple_factors_keep_separate_versions_bindings_and_component_membership():
    supplied = request()
    term = ConfidenceTerm("setup-penalty", "SETUP", "FACTOR", "penalty", "FIXTURE_PENALTY_V2", MODE)
    extra = replace(supplied.context.features[0], record_id="penalty-snapshot",
                    feature_version=term.definition_version,
                    features=(FeatureValue("penalty", -5, "SCORE_POINTS",
                                           input_record_ids=("synthetic-input",)),))
    supplied = replace(supplied, policy=replace(supplied.policy, terms=(*supplied.policy.terms, term)),
                       context=replace(supplied.context, features=(*supplied.context.features, extra)),
                       bindings=(*supplied.bindings, (term.name, extra.record_id)))
    result = compose_confidence(supplied)
    assert result.confidence.final_score == 66 and len(result.confidence.factors) == 4
    assert result.confidence.factors[-1] == ConfidenceComponent("setup-penalty", -5, "FIXTURE_PENALTY_V2")
    assert result.request.policy.terms[-1].component == "SETUP"
    reordered = replace(supplied, context=replace(supplied.context, features=tuple(reversed(supplied.context.features))),
                        bindings=tuple(reversed(supplied.bindings)))
    assert compose_confidence(reordered).confidence == result.confidence


@pytest.mark.parametrize("value", (-.000000001, 100.000000001))
def test_out_of_bounds_scores_are_unavailable_not_clamped_into_valid_inputs(value):
    result = compose_confidence(with_value(request(), "setup-score", value))
    assert result.confidence is None and result.reasons == ("setup-score:SCORE_OUT_OF_RANGE",)


@pytest.mark.parametrize("name", ("setup-score", "context-factor"))
@pytest.mark.parametrize("unit", ("RATIO", "USD_PER_SHARE"))
def test_wrong_units_cannot_supply_scores_or_factor_contributions(name, unit):
    result = compose_confidence(with_value(request(), name, 50, unit=unit))
    assert result.confidence is None and result.reasons == (name + ":WRONG_UNIT",)


@pytest.mark.parametrize("changes,reason", (
    ({"instrument_id": "OTHER"}, "IDENTITY_MISMATCH"),
    ({"instrument_type": "ETF"}, "IDENTITY_MISMATCH"),
    ({"source": "UNKNOWN"}, "SOURCE_UNAVAILABLE"),
    ({"source_time": None}, "SOURCE_UNAVAILABLE"),
    ({"data_mode": "OTHER_MODE"}, "MODE_MISMATCH"),
    ({"quality": "STALE"}, "QUALITY_UNAVAILABLE"),
    ({"quality": "INVALID"}, "QUALITY_UNAVAILABLE"),
    ({"quality": "UNKNOWN"}, "QUALITY_UNAVAILABLE"),
))
def test_wrong_identity_source_mode_and_quality_cannot_pass(changes, reason):
    supplied = request()
    snapshot = supplied.context.features[0]
    result = compose_confidence(with_snapshot(supplied, replace(snapshot, metadata=replace(snapshot.metadata, **changes))))
    assert result.confidence is None and result.status == "UNAVAILABLE"
    assert result.reasons == tuple(term.name + ":" + reason for term in supplied.policy.terms)


def test_explicit_proxy_mode_and_quality_survive_in_complete_attribution():
    supplied = request()
    snapshot = supplied.context.features[0]
    rules = replace(supplied.policy, terms=tuple(replace(t, data_mode="FIXTURE_PROXY") for t in supplied.policy.terms))
    supplied = with_snapshot(replace(supplied, policy=rules), replace(snapshot, metadata=replace(
        snapshot.metadata, data_mode="FIXTURE_PROXY", quality="DEGRADED_PROXY")))
    result = compose_confidence(supplied)
    assert result.status == "READY"
    assert result.request.context.features[0].metadata.quality == "DEGRADED_PROXY"
    assert result.request.context.features[0].metadata.data_mode == "FIXTURE_PROXY"


def test_wrong_feature_definition_and_old_calculation_stay_unavailable():
    supplied = request()
    snapshot = supplied.context.features[0]
    wrong = with_snapshot(supplied, replace(snapshot, feature_version="OTHER_V1"))
    old = with_snapshot(supplied, replace(snapshot, evaluated_at=START - timedelta(seconds=1),
                                         metadata=metadata(START - timedelta(seconds=1), data_mode=MODE)))
    for value, reason in ((wrong, "DEFINITION_MISMATCH"), (old, "NOT_CURRENT_EVALUATION")):
        result = compose_confidence(value)
        assert result.confidence is None
        assert result.reasons == tuple(t.name + ":" + reason for t in supplied.policy.terms)


def test_missing_or_unlinked_ancestry_cannot_lose_factor_source_attribution():
    supplied = request()
    missing = with_value(supplied, "setup-factor", 80, input_record_ids=())
    unknown = with_value(supplied, "setup-factor", 80, input_record_ids=("UNKNOWN",))
    mismatch = with_value(supplied, "setup-factor", 80, input_record_ids=("absent-parent",))
    for value, reason in ((missing, "INPUT_REFERENCES_UNAVAILABLE"), (unknown, "INPUT_REFERENCES_UNAVAILABLE"),
                          (mismatch, "INPUT_REFERENCES_MISMATCH")):
        assert compose_confidence(value).reasons == ("setup-factor:" + reason,)


@pytest.mark.parametrize("case", ("future_available", "future_evaluation", "future_source", "wrong_session", "duplicate_id"))
def test_existing_context_rejects_future_misattributed_and_conflicting_records(case):
    supplied = request()
    snapshot = supplied.context.features[0]
    later = START + timedelta(seconds=1)
    with pytest.raises(RecordError):
        if case == "future_available":
            with_snapshot(supplied, replace(snapshot, metadata=metadata(later, data_mode=MODE), evaluated_at=later))
        elif case == "future_evaluation":
            with_snapshot(supplied, replace(snapshot, evaluated_at=later))
        elif case == "future_source":
            with_snapshot(supplied, replace(snapshot, metadata=replace(snapshot.metadata, source_time=later)))
        elif case == "wrong_session":
            with_snapshot(supplied, replace(snapshot, metadata=replace(snapshot.metadata, session="2026-07-07")))
        else:
            replace(supplied.context, features=(snapshot, snapshot))


@pytest.mark.parametrize("weights", ((.5, .3, .1), (.5, .3, .200000000001), (50, 30, 20),
                                    (-.1, .6, .5), (True, 0, 0), (float("nan"), .3, .2),
                                    (float("inf"), .3, .2), (None, .3, .2)))
def test_invalid_weights_fail_without_rescaling_or_defaulting(weights):
    with pytest.raises(RecordError):
        policy(weights)


def test_policy_and_binding_contract_errors_are_explicit():
    supplied = request()
    rules = supplied.policy
    bad_policies = (
        {"version": "UNKNOWN"}, {"strategy_version": ""}, {"strategy_id": "UNKNOWN"},
        {"terms": ()}, {"terms": list(rules.terms)}, {"terms": (*rules.terms, rules.terms[0])},
        {"terms": tuple(t for t in rules.terms if t.name != "context-factor")},
    )
    for changes in bad_policies:
        with pytest.raises(RecordError):
            replace(rules, **changes)
    for bindings in (list(supplied.bindings), (*supplied.bindings, supplied.bindings[0]),
                     (("unlisted", "snapshot"),), (("setup-score", ""),), (("setup-score",),)):
        with pytest.raises(RecordError):
            replace(supplied, bindings=bindings)
    for changes in ({"definition_version": " unspecified "}, {"data_mode": "unknown"},
                    {"component": "OTHER"}, {"kind": "OPTIONAL"}, {"feature_name": ""}):
        with pytest.raises(RecordError):
            replace(rules.terms[0], **changes)
    with pytest.raises(RecordError):
        compose_confidence(None)


@pytest.mark.parametrize("value", (True, float("nan"), float("inf")))
def test_canonical_values_reject_non_numeric_or_nonfinite_contributions(value):
    with pytest.raises(RecordError):
        with_value(request(), "execution-factor", value)


def test_fixed_configuration_and_version_are_attributed_without_activation():
    supplied = request()
    settings = json.loads(supplied.context.session.config_json)
    assert settings["evaluation_enabled"] is False
    assert all(not s["enabled"] for s in settings["strategies"].values())
    settings["strategies"]["CRVOL_ORB5"]["strategy_version"] = VERSION
    saved = SessionRecord.from_config(record_id="configured-session", session="2026-07-06",
                                      started_at=supplied.context.session.started_at,
                                      config=TradeAlertsConfig(settings))
    configured = replace(supplied, context=replace(supplied.context, session=saved))
    result = compose_confidence(configured)
    assert result.status == "READY" and result.request.context.session == saved
    settings["config_version"] = "LATER_CONFIG"
    assert result.request.context.session.config_version != "LATER_CONFIG"
    with pytest.raises(RecordError):
        replace(configured, policy=replace(configured.policy, strategy_version="OTHER_V1"))


def test_full_result_and_canonical_factors_are_immutable_with_detached_exports():
    supplied = request()
    result = compose_confidence(supplied)
    original = result.to_json()
    with pytest.raises(FrozenInstanceError):
        result.confidence.factors[0].value = 99
    with pytest.raises(FrozenInstanceError):
        result.request.policy.setup_weight = 1
    with pytest.raises(FrozenInstanceError):
        result.request.context.features[0].features[0].value = 99
    detached = result.as_dict()
    detached["request"]["bindings"][0][1] = "changed"
    detached["request"]["policy"]["terms"][0]["definition_version"] = "changed"
    detached["confidence"]["factors"][0]["value"] = 99
    assert result.to_json() == original == compose_confidence(supplied).to_json()
    assert json.loads(original)["composition_version"] == COMPOSITION_VERSION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_supplied_features_composition_candidate_recording_end_to_end(direction):
    # Real shared calculation over supplied Bars; score normalization and geometry
    # remain explicitly test-only facts, not a playbook or a profitability result.
    source = history(changed=lambda bars: [Bar.from_json(b.to_json()) for b in bars])
    opening = build_opening_range_snapshot(record_id="m44-opening", evaluated_at=START,
                                           symbol="SYNTH", instrument_type="EQUITY", minute_history=source)
    opening = FeatureSnapshot.from_json(opening.to_json())
    assert {f.name: f.value for f in opening.features}["OPENING_RANGE_WIDTH_5M_V1"] == 10
    supplied = request(direction=direction, parents=(opening.record_id,))
    supplied = replace(supplied, context=replace(supplied.context, features=(*supplied.context.features, opening)))
    result = compose_confidence(supplied)
    assert result.status == "READY" and result.confidence.final_score == 66
    candidates = tuple(candidate(supplied, result, kind) for kind in ("HEADS_UP", "ACTIONABLE"))
    for row in candidates:
        assert AlertCandidate.from_json(row.to_json()) == row
        assert row.confidence == result.confidence
        assert row.config_hash == supplied.context.session.config_hash
        assert row.strategy_version == VERSION and row.direction == direction
    frozen_candidates = tuple(c.to_json() for c in candidates)
    missing = replace(supplied, bindings=tuple(b for b in supplied.bindings if b[0] != "context-factor"))
    missing_result = compose_confidence(missing)
    assert missing_result.status == "UNAVAILABLE" and missing_result.confidence is None
    with pytest.raises(RecordError):
        candidate(missing, missing_result)
    # A later revised score changes only the new calculation, never saved facts.
    later = START + timedelta(seconds=1)
    score_snapshot = supplied.context.features[0]
    revised = replace(score_snapshot, record_id="m44-revised-scores", evaluated_at=later,
                      metadata=metadata(later, data_mode=MODE, revision=1),
                      features=tuple(replace(f, value=100) for f in score_snapshot.features))
    next_request = replace(supplied, context=replace(supplied.context, evaluated_at=later,
                                                   features=(revised, opening)),
                           bindings=tuple((name, revised.record_id) for name, _ in supplied.bindings))
    later_result = compose_confidence(next_request)
    assert later_result.confidence.final_score == 100
    unavailable_option = OptionRecommendation(record_id="m44-option-unavailable-" + direction,
                                              candidate_id=candidates[1].record_id,
                                              ranked_at=later, status="UNAVAILABLE",
                                              reasons=("SYNTHETIC_OPTIONS_OUTAGE",),
                                              policy_version=VERSION)
    assert OptionRecommendation.from_json(unavailable_option.to_json()) == unavailable_option
    assert tuple(c.to_json() for c in candidates) == frozen_candidates
    assert compose_confidence(supplied).to_json() == result.to_json()
    proof = {
        "synthetic_only": True, "direction": direction,
        "source_bars": len(source.bars), "opening": opening.as_dict(),
        "source_sha256": hashlib.sha256("".join(b.to_json() for b in source.bars).encode()).hexdigest(),
        "result": result.as_dict(), "candidates": [c.as_dict() for c in candidates],
        "missing_factor_reasons": missing_result.reasons, "missing_confidence": missing_result.confidence,
        "later_score": later_result.confidence.final_score,
        "option_result": unavailable_option.as_dict(), "original_candidates_unchanged": True,
    }
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    Path(f"/tmp/m44-confidence-{direction.lower()}-proof.json").write_text(rendered)
