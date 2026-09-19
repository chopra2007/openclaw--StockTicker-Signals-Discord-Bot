"""Supplied candidate consistency, not eligibility, deduplication or delivery."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.candidate_assembly import (
    ASSEMBLY_VERSION, assemble_candidate, assemble_suppression, candidate_is_expired,
)
from consensus_engine.confidence import compose_confidence
from consensus_engine.opening_range_features import build_opening_range_snapshot
from consensus_engine.strategy_interface import StrategyState
from consensus_engine.trade_alerts_config import STRATEGY_IDS, TradeAlertsConfig
from consensus_engine.trade_alerts_models import (
    AlertCandidate, Bar, ConfluenceLink, FeatureSnapshot, OptionRecommendation,
    RecordError, RiskLevel, SessionRecord, SuppressionEvent, TargetLevel,
)
from test_confidence import MODE, VERSION, policy, request, with_value
from test_opening_range_features import history
from test_strategy_interface import START, metadata


def facts(direction="LONG", alert_type="ACTIONABLE", supplied=None, **changes):
    supplied = supplied or request(direction=direction)
    context = supplied.context
    sign = 1 if context.direction == "LONG" else -1
    fields = dict(
        context=context, confidence_result=compose_confidence(supplied),
        record_id="m45-" + direction + "-" + alert_type,
        metadata=metadata(context.evaluated_at, data_mode=MODE),
        strategy_id=supplied.policy.strategy_id, strategy_version=supplied.policy.strategy_version,
        alert_type=alert_type, state=StrategyState("ALERT_TRIGGERED", "FIXTURE_ONLY"),
        structure_id="M45_FIXTURE_STRUCTURE", trigger_price=100, alert_price=100,
        risk=RiskLevel(100, 100 - sign, 1, "Supplied geometry only", "FIXTURE_LEVEL"),
        targets=(TargetLevel("T1", 100 + 2 * sign, 2, "FIXTURE_LEVEL"),),
        feature_snapshot_id=context.features[0].record_id,
        input_record_ids=tuple(row.record_id for row in context.features),
        expires_at=context.evaluated_at + timedelta(seconds=1), mechanically_valid=True,
        data_quality="VALID", strategy_lifecycle="DEVELOPMENT", evidence_stage="IMPLEMENTED",
        human_checks=("Review supplied structure",), soft_invalidation="Supplied review reason",
    )
    fields.update(changes)
    return fields


def suppression(context, candidate=None, **changes):
    fields = dict(context=context, record_id="m45-suppression", metadata=metadata(context.evaluated_at),
                  strategy_id="CRVOL_ORB5", strategy_version=VERSION, reason="SUPPLIED_REASON",
                  input_record_ids=(candidate.record_id,) if candidate else (), candidate=candidate)
    fields.update(changes)
    return assemble_suppression(**fields)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("alert_type", ("HEADS_UP", "ACTIONABLE"))
def test_both_types_and_directions_preserve_supplied_facts(direction, alert_type):
    inputs = facts(direction, alert_type)
    result = assemble_candidate(**inputs)
    row = result.candidate
    assert result.status == "READY" and result.reasons == ()
    assert AlertCandidate.from_json(row.to_json()) == row
    for name in ("record_id", "metadata", "strategy_id", "strategy_version", "alert_type",
                 "structure_id", "trigger_price", "alert_price", "risk", "targets",
                 "feature_snapshot_id", "input_record_ids", "expires_at", "mechanically_valid",
                 "data_quality", "strategy_lifecycle", "evidence_stage", "human_checks", "soft_invalidation"):
        assert getattr(row, name) == inputs[name]
    assert row.direction == direction and row.created_at == inputs["context"].evaluated_at
    assert row.setup_substate == "FIXTURE_ONLY" and row.delivery_status == "PENDING"
    assert row.confidence == inputs["confidence_result"].confidence
    assert (row.session_record_id, row.config_version, row.config_hash) == (
        inputs["context"].session.record_id, inputs["context"].session.config_version,
        inputs["context"].session.config_hash)
    assert result.confidence_result == inputs["confidence_result"]


@pytest.mark.parametrize("strategy_id", STRATEGY_IDS)
def test_all_existing_strategy_ids_use_supplied_versions_without_activation(strategy_id):
    supplied = request(supplied_policy=policy(strategy_id=strategy_id))
    result = assemble_candidate(**facts(supplied=supplied))
    assert result.candidate.strategy_id == strategy_id
    settings = json.loads(result.context.session.config_json)
    assert not settings["evaluation_enabled"]
    assert not settings["alerts"]["delivery_enabled"]
    assert all(not row["enabled"] for row in settings["strategies"].values())


def test_heads_up_can_preserve_unknown_action_prices_and_nonvalid_candidate():
    result = assemble_candidate(**facts(alert_type="HEADS_UP", trigger_price=None, alert_price=None,
                                       risk=None, targets=(), mechanically_valid=False,
                                       state=StrategyState("SETUP_FORMING")))
    assert result.candidate.alert_type == "HEADS_UP"
    assert result.candidate.risk is None and result.candidate.targets == ()
    assert result.candidate.trigger_price is None and not result.candidate.mechanically_valid


@pytest.mark.parametrize("field,value", (("trigger_price", None), ("alert_price", None),
                                       ("risk", None), ("targets", ())))
def test_missing_valid_actionable_facts_cannot_produce_a_candidate(field, value):
    result = assemble_candidate(**facts(**{field: value}))
    assert result.status == "UNAVAILABLE" and result.candidate is None
    assert result.reasons == ("ACTIONABLE_FACTS_UNAVAILABLE",)


@pytest.mark.parametrize("missing", ("absent_result", "missing_score", "missing_factor", "missing_feature"))
def test_missing_confidence_or_primary_feature_never_becomes_zero(missing):
    inputs = facts()
    expected = "CONFIDENCE_UNAVAILABLE"
    if missing == "absent_result":
        inputs["confidence_result"] = None
    elif missing == "missing_feature":
        inputs["feature_snapshot_id"] = "absent-feature"
        expected = "FEATURE_SNAPSHOT_UNAVAILABLE"
    else:
        name = "context-score" if missing == "missing_score" else "context-factor"
        inputs = facts(supplied=with_value(request(), name, None))
    result = assemble_candidate(**inputs)
    assert result.candidate is None and result.reasons == (expected,)
    assert result.as_dict()["context"]["symbol"] == "SYNTH"
    assert json.loads(result.to_json())["candidate"] is None
    saved = suppression(result.context, reason=expected)
    assert saved.candidate_id is None and saved.reason == expected
    assert SuppressionEvent.from_json(saved.to_json()) == saved


def test_known_zero_confidence_is_preserved_without_a_cutoff():
    result = assemble_candidate(**facts(supplied=request((0, 0, 0))))
    assert result.status == "READY" and result.candidate.confidence.final_score == 0


@pytest.mark.parametrize("field,value", (("instrument_id", "OTHER"), ("instrument_type", "ETF"),
                                       ("session", "2026-07-07"),
                                       ("source_time", START + timedelta(seconds=1)),
                                       ("normalized_time", START + timedelta(seconds=1))))
def test_candidate_metadata_identity_and_time_must_match_context(field, value):
    with pytest.raises(RecordError):
        assemble_candidate(**facts(metadata=replace(metadata(data_mode=MODE), **{field: value})))


def test_future_candidate_availability_is_rejected():
    with pytest.raises(RecordError):
        assemble_candidate(**facts(metadata=metadata(START + timedelta(seconds=1), data_mode=MODE)))


@pytest.mark.parametrize("case", ("direction", "strategy", "version", "context_time", "context_feature",
                                "context_session", "altered_score", "altered_status", "altered_reasons"))
def test_confidence_must_match_full_context_identity_and_original_calculation(case):
    inputs = facts()
    result = inputs["confidence_result"]
    if case == "direction":
        inputs["confidence_result"] = compose_confidence(request(direction="SHORT"))
    elif case == "strategy":
        inputs["strategy_id"] = "HOD_COMP_RS"
    elif case == "version":
        inputs["strategy_version"] = "OTHER_V1"
    elif case == "context_time":
        inputs["context"] = replace(inputs["context"], evaluated_at=START + timedelta(microseconds=1))
    elif case == "context_feature":
        snap = inputs["context"].features[0]
        inputs["context"] = replace(inputs["context"], features=(replace(snap, feature_version="OTHER"),))
    elif case == "context_session":
        inputs["context"] = replace(inputs["context"], session=replace(inputs["context"].session, record_id="other"))
    elif case == "altered_score":
        inputs["confidence_result"] = replace(result, confidence=replace(result.confidence, final_score=99))
    elif case == "altered_status":
        inputs["confidence_result"] = replace(result, status="UNAVAILABLE")
    else:
        inputs["confidence_result"] = replace(result, reasons=("invented",))
    with pytest.raises(RecordError):
        assemble_candidate(**inputs)


def test_saved_strategy_version_cannot_be_overridden():
    inputs = facts()
    old = inputs["context"].session
    settings = json.loads(old.config_json)
    settings["strategies"]["CRVOL_ORB5"]["strategy_version"] = "OTHER_V1"
    saved = SessionRecord.from_config(record_id=old.record_id, session=old.session,
                                      started_at=old.started_at, config=TradeAlertsConfig(settings))
    with pytest.raises(RecordError):
        assemble_candidate(**{**inputs, "context": replace(inputs["context"], session=saved)})


@pytest.mark.parametrize("refs", ((), ("absent",), ("UNKNOWN",), ("m44-supplied-scores", "m44-supplied-scores"),
                                  ["m44-supplied-scores"]))
def test_missing_duplicate_unknown_and_unattributed_feature_links_fail(refs):
    with pytest.raises(RecordError):
        assemble_candidate(**facts(input_record_ids=refs))


def test_primary_feature_and_all_confidence_snapshot_links_are_required():
    supplied = request()
    score = supplied.context.features[0]
    primary = replace(score, record_id="separate-primary")
    supplied = replace(supplied, context=replace(supplied.context, features=(score, primary)))
    with pytest.raises(RecordError):
        assemble_candidate(**facts(supplied=supplied, feature_snapshot_id=primary.record_id,
                                   input_record_ids=(primary.record_id,)))
    other = replace(primary, metadata=replace(primary.metadata, instrument_id="OTHER"))
    supplied = replace(supplied, context=replace(supplied.context, features=(score, other)))
    with pytest.raises(RecordError):
        assemble_candidate(**facts(supplied=supplied, feature_snapshot_id=other.record_id))


@pytest.mark.parametrize("alert_type", ("HEADS_UP", "ACTIONABLE"))
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("wrong", ("stop", "target_side", "target_multiple", "duplicate_target"))
def test_supplied_geometry_must_agree_for_both_alert_types(alert_type, direction, wrong):
    inputs = facts(direction, alert_type)
    sign = 1 if direction == "LONG" else -1
    if wrong == "stop":
        inputs["risk"] = RiskLevel(100, 100 + sign, 1, "fixture", "fixture")
    elif wrong == "target_side":
        inputs["targets"] = (TargetLevel("T1", 100 - 2 * sign, 2, "fixture"),)
    elif wrong == "target_multiple":
        inputs["targets"] = (replace(inputs["targets"][0], r_multiple=3),)
    else:
        inputs["targets"] *= 2
    with pytest.raises(RecordError):
        assemble_candidate(**inputs)


@pytest.mark.parametrize("quality", ("STALE", "UNAVAILABLE", "INVALID", "UNKNOWN"))
def test_unusable_supplied_data_cannot_be_labeled_valid_actionable(quality):
    result = assemble_candidate(**facts(data_quality=quality, metadata=metadata(data_mode=MODE, quality=quality)))
    assert result.candidate is None and result.reasons == ("ACTIONABLE_DATA_UNAVAILABLE",)
    with pytest.raises(RecordError):
        assemble_candidate(**facts(metadata=metadata(data_mode=MODE, quality=quality)))


def test_explicit_proxy_facts_remain_labeled_and_do_not_select_a_new_rule():
    result = assemble_candidate(**facts(data_quality="DEGRADED_PROXY",
                                       metadata=metadata(data_mode="SUPPLIED_PROXY", quality="DEGRADED_PROXY")))
    assert result.candidate.metadata.data_mode == "SUPPLIED_PROXY"
    assert result.candidate.data_quality == "DEGRADED_PROXY"


@pytest.mark.parametrize("source_changes", ({"source": "UNKNOWN"}, {"source_time": None},
                                          {"data_mode": "UNSPECIFIED"}))
def test_unknown_candidate_source_facts_cannot_supply_valid_actionable(source_changes):
    result = assemble_candidate(**facts(metadata=replace(metadata(data_mode=MODE), **source_changes)))
    assert result.candidate is None and result.reasons == ("ACTIONABLE_DATA_UNAVAILABLE",)


def test_missing_or_degraded_primary_feature_quality_cannot_be_hidden_by_scores():
    supplied = request()
    score = supplied.context.features[0]
    for quality in ("STALE", "UNKNOWN", "DEGRADED_PROXY"):
        primary = replace(score, record_id="primary", metadata=replace(score.metadata, quality=quality))
        current = replace(supplied, context=replace(supplied.context, features=(score, primary)))
        inputs = facts(supplied=current, feature_snapshot_id=primary.record_id)
        if quality == "DEGRADED_PROXY":
            with pytest.raises(RecordError):
                assemble_candidate(**inputs)
            result = assemble_candidate(**{**inputs, "data_quality": quality,
                                           "metadata": metadata(data_mode=MODE, quality=quality)})
            assert result.candidate.data_quality == quality
        else:
            result = assemble_candidate(**inputs)
            assert result.candidate is None and result.reasons == ("ACTIONABLE_DATA_UNAVAILABLE",)


@pytest.mark.parametrize("delta,expired", ((-1, False), (0, True), (1, True)))
def test_exact_supplied_expiry_boundary_is_read_only(delta, expired):
    row = assemble_candidate(**facts()).candidate
    original = row.to_json()
    assert candidate_is_expired(row, at=row.expires_at + timedelta(microseconds=delta)) is expired
    assert row.to_json() == original and row.setup_state == "ALERT_TRIGGERED"


def test_expiry_requires_explicit_aware_instants_after_creation():
    row = assemble_candidate(**facts()).candidate
    for at in (START - timedelta(microseconds=1), START.replace(tzinfo=None), None):
        with pytest.raises(ValueError):
            candidate_is_expired(row, at=at)
    for at in (START, START - timedelta(microseconds=1), START.replace(tzinfo=None)):
        with pytest.raises(RecordError):
            assemble_candidate(**facts(expires_at=at))


def test_confluence_preserves_every_component_and_never_changes_primary_or_scores():
    linked = assemble_candidate(**facts(record_id="linked", supplied=request(
        supplied_policy=policy(strategy_id="HOD_COMP_RS")))).candidate
    unlinked = assemble_candidate(**facts(direction="SHORT", record_id="unlinked")).candidate
    inputs = facts(confluence=(ConfluenceLink(linked.strategy_id, linked.record_id),),
                   component_candidates=(unlinked, linked))
    result = assemble_candidate(**inputs)
    assert result.component_candidates == (unlinked, linked)
    assert result.candidate.strategy_id == "CRVOL_ORB5"
    assert result.candidate.confidence.final_score == 66
    assert result.candidate.confluence == inputs["confluence"]
    assert [row["record_id"] for row in result.as_dict()["component_candidates"]] == ["unlinked", "linked"]


@pytest.mark.parametrize("case", ("missing", "wrong_strategy", "opposite", "duplicate_link", "duplicate_component",
                                "self", "future", "wrong_config", "wrong_session", "wrong_symbol", "wrong_type"))
def test_confluence_requires_exact_available_component_identity(case):
    row = assemble_candidate(**facts(record_id="component")).candidate
    link = ConfluenceLink(row.strategy_id, row.record_id)
    inputs = facts(component_candidates=(row,), confluence=(link,))
    if case == "missing":
        inputs["component_candidates"] = ()
    elif case == "wrong_strategy":
        inputs["confluence"] = (ConfluenceLink("HOD_COMP_RS", row.record_id),)
    elif case == "opposite":
        inputs["component_candidates"] = (assemble_candidate(**facts("SHORT", record_id="component")).candidate,)
    elif case == "duplicate_link":
        inputs["confluence"] *= 2
    elif case == "duplicate_component":
        inputs["component_candidates"] *= 2
    elif case == "self":
        inputs["record_id"] = row.record_id
    elif case == "future":
        inputs["component_candidates"] = (replace(row, created_at=START + timedelta(microseconds=1)),)
    elif case == "wrong_config":
        inputs["component_candidates"] = (replace(row, config_hash="0" * 64),)
    elif case == "wrong_session":
        inputs["component_candidates"] = (replace(row, session_record_id="other-session"),)
    else:
        field, value = ("instrument_id", "OTHER") if case == "wrong_symbol" else ("instrument_type", "ETF")
        inputs["component_candidates"] = (replace(row, metadata=replace(row.metadata, **{field: value})),)
    with pytest.raises(RecordError):
        assemble_candidate(**inputs)


@pytest.mark.parametrize("case", ("direction", "strategy", "version", "configuration", "before_creation",
                                "unknown_reason", "unattributed", "reused_id"))
def test_suppression_is_linked_to_exact_candidate_without_inventing_a_reason(case):
    inputs = facts()
    row = assemble_candidate(**inputs).candidate
    context = inputs["context"]
    changes = {}
    if case == "direction":
        context = replace(context, direction="SHORT")
    elif case == "strategy":
        changes["strategy_id"] = "HOD_COMP_RS"
    elif case == "version":
        changes["strategy_version"] = "OTHER_V1"
    elif case == "configuration":
        row = replace(row, config_hash="0" * 64)
    elif case == "before_creation":
        context = replace(context, evaluated_at=START - timedelta(seconds=1), features=())
    elif case == "unknown_reason":
        changes["reason"] = "UNKNOWN"
    elif case == "unattributed":
        changes["input_record_ids"] = ("absent",)
    else:
        changes["record_id"] = row.record_id
    with pytest.raises(RecordError):
        suppression(context, row, **changes)


def test_full_assembly_is_immutable_and_repeated_inputs_produce_identical_bytes():
    inputs = facts()
    result = assemble_candidate(**inputs)
    original = result.to_json()
    with pytest.raises(FrozenInstanceError):
        result.candidate.structure_id = "changed"
    detached = result.as_dict()
    detached["candidate"]["risk"]["hard_stop"] = 1
    detached["confidence_result"]["request"]["policy"]["setup_weight"] = 1
    assert result.to_json() == original == assemble_candidate(**inputs).to_json()
    assert json.loads(original)["assembly_version"] == ASSEMBLY_VERSION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_supplied_features_confidence_candidate_suppression_recording_end_to_end(direction):
    source = history(changed=lambda bars: [Bar.from_json(row.to_json()) for row in bars])
    opening = build_opening_range_snapshot(record_id="m45-opening", evaluated_at=START,
                                           symbol="SYNTH", instrument_type="EQUITY", minute_history=source)
    opening = FeatureSnapshot.from_json(opening.to_json())
    assert {row.name: row.value for row in opening.features}["OPENING_RANGE_WIDTH_5M_V1"] == 10
    supplied = request(direction=direction, parents=(opening.record_id,))
    supplied = replace(supplied, context=replace(supplied.context, features=(*supplied.context.features, opening)))
    # Normalization of scores, geometry, state and one-second expiry are supplied
    # fixtures only. The opening calculation, composition and assembly are real.
    heads = assemble_candidate(**facts(direction, "HEADS_UP", supplied,
                                       state=StrategyState("SETUP_FORMING")))
    component = assemble_candidate(**facts(direction, "HEADS_UP", supplied, record_id="m45-component"))
    action_inputs = facts(direction, "ACTIONABLE", supplied,
                         component_candidates=(component.candidate,),
                         confluence=(ConfluenceLink(component.candidate.strategy_id, component.candidate.record_id),))
    action = assemble_candidate(**action_inputs)
    original = (heads.to_json(), action.to_json(), component.to_json())
    for result in (heads, action):
        row = result.candidate
        assert AlertCandidate.from_json(row.to_json()) == row
        assert row.confidence.final_score == 66 and row.risk.risk_per_share == 1
        assert row.targets[0].r_multiple == 2 and row.direction == direction
    instant = action.candidate.expires_at
    expired = [candidate_is_expired(action.candidate, at=instant + timedelta(microseconds=delta))
               for delta in (-1, 0, 1)]
    assert expired == [False, True, True]
    later_context = replace(supplied.context, evaluated_at=instant, features=())
    saved = suppression(later_context, action.candidate, reason="FIXTURE_EXPLICIT_EXPIRY",
                        input_record_ids=(action.candidate.record_id, opening.record_id))
    assert saved.occurred_at == instant and saved.candidate_id == action.candidate.record_id
    assert SuppressionEvent.from_json(saved.to_json()) == saved
    missing_request = replace(supplied, bindings=supplied.bindings[:-1])
    missing = assemble_candidate(**facts(direction, supplied=missing_request))
    assert missing.candidate is None and missing.reasons == ("CONFIDENCE_UNAVAILABLE",)
    no_candidate = suppression(missing.context, reason="FIXTURE_MISSING_CONFIDENCE")
    assert no_candidate.candidate_id is None
    score = supplied.context.features[0]
    revised = replace(score, record_id="m45-revised-score", evaluated_at=instant,
                      metadata=metadata(instant, data_mode=MODE, revision=1),
                      features=tuple(replace(row, value=100) for row in score.features))
    revised_request = replace(supplied, context=replace(supplied.context, evaluated_at=instant,
                                                       features=(revised, opening)),
                              bindings=tuple((name, revised.record_id) for name, _ in supplied.bindings))
    newer = assemble_candidate(**facts(direction, supplied=revised_request, record_id="m45-new-candidate"))
    assert newer.candidate.confidence.final_score == 100
    options = OptionRecommendation(record_id="m45-options", candidate_id=action.candidate.record_id,
                                   ranked_at=instant, status="UNAVAILABLE", reasons=("FIXTURE_OUTAGE",),
                                   policy_version=VERSION)
    assert OptionRecommendation.from_json(options.to_json()) == options
    assert (heads.to_json(), action.to_json(), component.to_json()) == original
    assert assemble_candidate(**action_inputs).to_json() == action.to_json()
    proof = {"synthetic_only": True, "direction": direction, "source_bars": len(source.bars),
             "source_sha256": hashlib.sha256("".join(row.to_json() for row in source.bars).encode()).hexdigest(),
             "opening": opening.as_dict(), "heads_up": heads.candidate.as_dict(),
             "actionable_assembly": action.as_dict(), "expiry_before_at_after": expired,
             "suppression": saved.as_dict(), "candidate_less_suppression": no_candidate.as_dict(),
             "missing_reasons": missing.reasons, "later_confidence": newer.candidate.confidence.final_score,
             "option_result": options.as_dict(), "original_records_unchanged": True,
             "repeated_assembly_identical": True}
    rendered = json.dumps(proof, sort_keys=True, separators=(",", ":"))
    assert len(rendered.encode()) < 100000
    Path(f"/tmp/m45-candidate-assembly-{direction.lower()}-proof.json").write_text(rendered)
