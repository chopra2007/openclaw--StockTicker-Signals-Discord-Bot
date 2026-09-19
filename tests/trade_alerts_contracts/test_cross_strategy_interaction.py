"""M8.5 supplied-input cross-strategy facts; no merge rule is adopted."""

from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.cross_strategy_interaction import (
    ACCEPTED, BOTH_REGIONS, DECLARED_TRANSITION, EITHER_REGION, FAIL,
    INTERACTION_VERSION, OPPOSITE_DIRECTION_CONFLICT, OPPOSITE_DIRECTION_SEQUENTIAL,
    REFUSED, SAME_DIRECTION_SEPARATE, SAME_DIRECTION_UNKNOWN, SAME_THESIS_OVERLAP,
    UNDEFINED, InteractionPolicy, InteractionRequest, SymbolAtr, DeclaredTransition,
    report_cross_strategy_interaction,
)
from consensus_engine.or_failure_handoff import evaluate_or_failure_handoff
from consensus_engine.trade_alerts_models import (
    AlertCandidate, Bar, Quote, FeatureSnapshot, FeatureValue, ConfidenceBreakdown, RecordError, RiskLevel, TargetLevel,
)
from test_or_failure_handoff import ENDED_AT, request as handoff_request, reacceptance
from test_strategy_interface import metadata, session
from consensus_engine.or_failure_rev import HANDOFF_GATE, evaluate_or_failure_rev
from consensus_engine.strategy_interface import StrategyState
from test_or_failure_rev import request as reversal_request
from consensus_engine.orb5_trigger import evaluate_orb5_trigger
from test_orb5_trigger import request as orb_request


VERSION = "M85_SUPPLIED_FIXTURE_POLICY_V1"
DEFINITION = "M85_SUPPLIED_FIXTURE_DEFINITION"
EVALUATED = ENDED_AT + timedelta(minutes=10)


def policy(**changes):
    values = dict(version=VERSION, definition_reference=DEFINITION,
                  merge_window_seconds=180, region_atr_multiple=0.25,
                  region_rule=BOTH_REGIONS)
    values.update(changes)
    return InteractionPolicy(**values)


def candidate(record_id, strategy_id="CRVOL_ORB5", direction="LONG", *,
              created=ENDED_AT - timedelta(seconds=10), expires=None, trigger=100.0,
              stop=None, score=70.0, symbol="SYNTH"):
    sign = 1 if direction == "LONG" else -1
    stop = trigger - sign if stop is None else stop
    expires = expires or created + timedelta(minutes=5)
    return AlertCandidate(
        record_id=record_id,
        metadata=metadata(created, instrument_id=symbol),
        strategy_id=strategy_id,
        strategy_version="SUPPLIED_STRATEGY_V1",
        direction=direction,
        alert_type="ACTIONABLE",
        setup_state="ALERT_TRIGGERED",
        setup_substate="SUPPLIED_FIXTURE",
        strategy_lifecycle="DEVELOPMENT",
        evidence_stage="IMPLEMENTED",
        delivery_status="PENDING",
        structure_id="structure-" + record_id,
        trigger_price=trigger,
        alert_price=trigger,
        risk=RiskLevel(trigger, stop, abs(trigger - stop), "supplied", "SUPPLIED"),
        targets=(TargetLevel("T1", trigger + sign * 2, 2 / abs(trigger - stop),
                             "SUPPLIED"),),
        confidence=ConfidenceBreakdown(score, score, score, score),
        human_checks=("Review supplied interaction",),
        input_record_ids=("input-" + record_id,),
        feature_snapshot_id="feature-" + record_id,
        session_record_id="session-2026-07-06",
        config_version="SUPPLIED_CONFIG_V1",
        config_hash="0" * 64,
        created_at=created,
        expires_at=expires,
        data_quality="VALID",
        mechanically_valid=True,
    )


def atr(**changes):
    values = dict(record_id="m85-atr", symbol="SYNTH",
                  definition_reference="SUPPLIED_MINUTE_ATR",
                  available_at=ENDED_AT - timedelta(minutes=1), value=4.0)
    values.update(changes)
    return SymbolAtr(**values)


def report(*candidates, supplied_policy=None, atrs=None, transitions=()):
    return report_cross_strategy_interaction(InteractionRequest(
        evaluated_at=EVALUATED,
        policy=supplied_policy or policy(),
        candidates=tuple(candidates),
        atrs=(atr(),) if atrs is None else atrs,
        transitions=transitions,
    ))


def supplied_bar(record_id, at, close, *, high=None, low=None):
    return Bar(record_id=record_id, metadata=metadata(at),
               start_time=at - timedelta(minutes=1), end_time=at, is_final=True,
               open=close, high=close if high is None else high,
               low=close if low is None else low, close=close, volume=10,
               adjustment_basis="RAW", price_convention="TRADE", volume_convention="SHARES")


def supplied_trade(record_id, at, price):
    return Quote(record_id=record_id, metadata=metadata(at), quote_time=at,
                 trade_time=at, last=price, status="VALID", delayed=False)


def supplied_measurements(record_id, at, values):
    return FeatureSnapshot(record_id=record_id, metadata=metadata(at), evaluated_at=at,
                           feature_version="M85_SUPPLIED_SOURCE_V1",
                           features=tuple(FeatureValue(name, value, "SUPPLIED")
                                          for name, value in values.items()))


def transition_fixture(direction="LONG", kind="handoff", *, evaluation_identity=None,
                       release_originals=False):
    # Canonical sources are supplied first. Their IDs, times and values feed the
    # real evaluators; the recorded sources are those same immutable objects.
    handoff_input = handoff_request(direction)
    frozen = handoff_input.candidate
    previous = supplied_trade("m85-crossing-previous", frozen.crossed_at,
                              frozen.boundary - (0.01 if direction == "LONG" else -0.01))
    current = supplied_trade("m85-crossing-current", frozen.crossed_at, frozen.boundary)
    anchor = supplied_bar("m85-anchor", frozen.crossed_at, frozen.boundary)
    frozen = replace(frozen, boundary=current.last, anchor_bar_id=anchor.record_id,
                     input_record_ids=(previous.record_id, current.record_id))
    ended_close = supplied_bar("m85-attempt-close", ENDED_AT,
                              handoff_input.minute_close.close)
    attempt_input = orb_request(direction)
    attempt_input = replace(attempt_input, candidate=frozen,
                            minute_close=replace(handoff_input.minute_close,
                                                 record_id=ended_close.record_id,
                                                 bar_end=ended_close.end_time,
                                                 available_at=ended_close.metadata.available_time,
                                                 close=ended_close.close))
    observation_sources = tuple(supplied_trade(
        item.record_id, item.observed_at, item.price) for item in attempt_input.observations)
    last_trade_source = supplied_trade(
        attempt_input.last_trade.record_id, attempt_input.last_trade.observed_at,
        attempt_input.last_trade.price)
    attempt = evaluate_orb5_trigger(attempt_input)
    extreme = supplied_trade("m85-extreme", handoff_input.breakout_extreme.observed_at,
                             handoff_input.breakout_extreme.price)
    inside = supplied_bar("m85-reacceptance", ENDED_AT, handoff_input.minute_close.close)
    if evaluation_identity is not None:
        opening = handoff_input.opening_range
        opening = replace(opening, metadata=replace(opening.metadata, **evaluation_identity))
        handoff_input = replace(handoff_input, opening_range=opening,
                                symbol=opening.metadata.instrument_id)
    handoff_input = replace(handoff_input, attempt=attempt,
                            breakout_extreme=replace(handoff_input.breakout_extreme,
                                record_id=extreme.record_id, price=extreme.last,
                                observed_at=extreme.trade_time,
                                available_at=extreme.metadata.available_time),
                            minute_close=replace(handoff_input.minute_close,
                                record_id=inside.record_id, close=inside.close,
                                bar_end=inside.end_time, available_at=inside.metadata.available_time))
    evidence = evaluate_or_failure_handoff(handoff_input)
    inputs = [anchor, previous, current, ended_close, handoff_input.opening_range,
              extreme, inside, *observation_sources, last_trade_source]
    if kind == "reversal":
        reversal_input = reversal_request(direction, handoff=evidence)
        last = supplied_trade("m85-reversal-last", ENDED_AT, reversal_input.last_trade.price)
        confirmation = supplied_bar("m85-reversal-close", ENDED_AT,
                                    reversal_input.confirmation_close.close)
        acceptance = supplied_measurements("m85-acceptance", ENDED_AT,
                                           {"INSIDE_SHARE": reversal_input.acceptance.share})
        risk = reversal_input.structural.risk
        risk_source = supplied_measurements("m85-structural-risk", ENDED_AT,
            {"ENTRY": risk.entry_reference, "STOP": risk.hard_stop,
             "RISK_PER_SHARE": risk.risk_per_share})
        targets_source = supplied_measurements("m85-structural-targets", ENDED_AT,
            {name: value for number, target in enumerate(reversal_input.structural.targets)
             for name, value in ((f"PRICE_{number}", target.price), (f"R_{number}", target.r_multiple))})
        risk_values = {item.name: item.value for item in risk_source.features}
        target_values = {item.name: item.value for item in targets_source.features}
        structural = replace(reversal_input.structural,
            risk=replace(risk, entry_reference=risk_values["ENTRY"], hard_stop=risk_values["STOP"],
                         risk_per_share=risk_values["RISK_PER_SHARE"]),
            targets=tuple(replace(target, price=target_values[f"PRICE_{number}"],
                                  r_multiple=target_values[f"R_{number}"])
                          for number, target in enumerate(reversal_input.structural.targets)),
            record_ids=(risk_source.record_id, targets_source.record_id))
        reversal_input = replace(reversal_input,
            last_trade=replace(reversal_input.last_trade, record_id=last.record_id, price=last.last,
                               observed_at=last.trade_time, available_at=last.metadata.available_time),
            confirmation_close=replace(reversal_input.confirmation_close,
                record_id=confirmation.record_id, close=confirmation.close,
                bar_end=confirmation.end_time, available_at=confirmation.metadata.available_time),
            acceptance=replace(reversal_input.acceptance, record_id=acceptance.record_id,
                               share=acceptance.features[0].value,
                               available_at=acceptance.metadata.available_time), structural=structural)
        evidence = evaluate_or_failure_rev(reversal_input)
        inputs.extend((last, confirmation, acceptance, risk_source, targets_source,
                       reversal_input.quote.quote, *reversal_input.confidence.request.context.features))
    ids = (frozen.anchor_bar_id, *frozen.input_record_ids)
    orb = replace(candidate("orb", direction=direction,
                            created=ENDED_AT - timedelta(seconds=1), trigger=frozen.boundary),
                  structure_id="original-orb-setup", input_record_ids=ids)
    reversal = replace(candidate("reversal", "OR_FAILURE_REV", evidence.direction,
                                 created=ENDED_AT + timedelta(seconds=1)),
                       structure_id=orb.structure_id, input_record_ids=(orb.record_id, *ids))
    declared = DeclaredTransition("transition", orb.record_id,
                                  reversal.record_id, evidence, session(), tuple(inputs))
    if release_originals:
        if kind != "reversal":
            raise AssertionError("original release requests require reversal evidence")
        from consensus_engine.options_portfolio import ReversalReleaseEvidence
        release = ReversalReleaseEvidence(
            declared.record_id, orb.record_id, reversal.record_id,
            attempt_input, handoff_input, reversal_input, declared.session,
            declared.supporting_records)
        return orb, reversal, declared, release
    return orb, reversal, declared


def test_policy_and_input_records_are_explicit_immutable_and_round_trip_cleanly():
    supplied = policy()
    assert supplied.as_dict() == {
        "version": VERSION, "definition_reference": DEFINITION,
        "merge_window_seconds": 180, "region_atr_multiple": 0.25,
        "region_rule": BOTH_REGIONS,
    }
    with pytest.raises(FrozenInstanceError):
        supplied.merge_window_seconds = 3
    for changes in (
        {"version": "UNKNOWN"}, {"merge_window_seconds": -1},
        {"region_atr_multiple": 0}, {"region_rule": "INVENTED"},
    ):
        with pytest.raises(RecordError):
            policy(**changes)
    with pytest.raises(RecordError):
        atr(value=None)
    missing = atr(value=None, missing_reason="SUPPLIED_ATR_MISSING")
    assert missing.as_dict()["missing_reason"] == "SUPPLIED_ATR_MISSING"


def test_every_same_symbol_pair_and_candidate_survives_in_stable_order():
    rows = (
        candidate("c", "FIRST_PULLBACK_VWAP"),
        candidate("a", "CRVOL_ORB5"),
        candidate("other", "HOD_COMP_RS", symbol="OTHER"),
        candidate("b", "OR_FAILURE_REV"),
    )
    first = report(*rows)
    second = report(*reversed(rows))
    assert tuple(row.record_id for row in first.candidates) == ("a", "b", "c", "other")
    assert [(row.first_candidate_id, row.second_candidate_id) for row in first.pairs] == [
        ("a", "b"), ("a", "c"), ("b", "c")]
    assert first.to_json() == second.to_json()
    assert json.loads(first.to_json())["interaction_version"] == INTERACTION_VERSION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_same_direction_exact_time_and_price_boundaries_overlap(direction):
    first = candidate("a", direction=direction, created=ENDED_AT - timedelta(seconds=180),
                      trigger=100.0, stop=99.0 if direction == "LONG" else 101.0)
    second = candidate("b", "HOD_COMP_RS", direction, created=ENDED_AT,
                       trigger=101.0, stop=100.0 if direction == "LONG" else 102.0)
    found = report(first, second).pair("a", "b")
    assert found.relation == SAME_THESIS_OVERLAP
    assert found.lifetimes_overlap
    assert (found.seconds_apart, found.trigger_distance_atr,
            found.stop_distance_atr) == (180.0, 0.25, 0.25)
    assert all(row.status == "PASS" for row in found.gates)


@pytest.mark.parametrize("case", ("time", "trigger", "stop", "lifetime"))
def test_same_direction_separates_when_a_supplied_boundary_fails(case):
    first = candidate("a", expires=ENDED_AT + timedelta(minutes=5))
    values = dict(created=ENDED_AT, trigger=100.5, stop=99.5)
    if case == "time":
        values["created"] = ENDED_AT + timedelta(seconds=181)
    elif case == "trigger":
        values["trigger"] = 101.01
        values["stop"] = 100.01
    elif case == "stop":
        values["stop"] = 100.01
    elif case == "lifetime":
        first = candidate("a", expires=ENDED_AT - timedelta(seconds=1))
    found = report(first, candidate("b", "HOD_COMP_RS", **values)).pair("a", "b")
    assert found.relation == SAME_DIRECTION_SEPARATE


def test_region_rule_and_missing_atr_stay_visible_without_guessing():
    first = candidate("a", trigger=100, stop=99)
    # Keep valid long risk while only the trigger lies inside the supplied region.
    second = candidate("b", "FIRST_PULLBACK_VWAP", trigger=100.5, stop=97.5)
    both = report(first, second).pair("a", "b")
    either = report(first, second, supplied_policy=policy(region_rule=EITHER_REGION)).pair("a", "b")
    unknown = report(first, second, atrs=(atr(value=None, missing_reason="NO_POINT_IN_TIME_ATR"),)).pair("a", "b")
    assert both.trigger_distance_atr == 0.125
    assert both.stop_distance_atr == 0.375
    assert both.gate("TRIGGER_REGION").status == "PASS"
    assert both.gate("STOP_REGION").status == FAIL
    assert both.relation == SAME_DIRECTION_SEPARATE and both.gate("PRICE_REGION").status == FAIL
    assert either.relation == SAME_THESIS_OVERLAP and either.gate("PRICE_REGION").status == "PASS"
    assert unknown.relation == SAME_DIRECTION_UNKNOWN
    assert unknown.gate("TRIGGER_REGION").reason == "NO_POINT_IN_TIME_ATR"
    assert unknown.gate("STOP_REGION").reason == "NO_POINT_IN_TIME_ATR"


def test_opposite_directions_report_conflict_sequence_confidence_and_equal_tie():
    long = candidate("a", score=80)
    short = candidate("b", "OR_FAILURE_REV", "SHORT", score=60)
    conflict = report(long, short).pair("a", "b")
    assert conflict.relation == OPPOSITE_DIRECTION_CONFLICT
    assert conflict.higher_confidence_candidate_id == "a" and not conflict.equal_confidence
    tied = report(long, replace(short, confidence=ConfidenceBreakdown(80, 80, 80, 80))).pair("a", "b")
    assert tied.equal_confidence and tied.higher_confidence_candidate_id is None
    later = candidate("c", "OR_FAILURE_REV", "SHORT", created=long.expires_at)
    assert report(long, later).pair("a", "c").relation == OPPOSITE_DIRECTION_SEQUENTIAL


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("kind", ("handoff", "reversal"))
def test_real_assessment_backs_only_its_original_declared_transition(direction, kind):
    orb, reversal, declared = transition_fixture(direction, kind)
    found = report(orb, reversal, transitions=(declared,))
    assert found.transitions[0].status == ACCEPTED
    assert found.pair("orb", "reversal").relation == DECLARED_TRANSITION
    recorded = found.as_dict()["transitions"][0]
    assert recorded["evidence"] == declared.evidence.as_dict()
    assert recorded["session"] == declared.session.as_dict()
    assert recorded["supporting_records"] == [item.as_dict() for item in sorted(
        declared.supporting_records, key=lambda item: item.record_id)]
    unsupported = replace(declared, from_candidate_id="reversal", to_candidate_id="orb")
    refused = report(orb, reversal, transitions=(unsupported,))
    assert refused.transitions[0].reason == "TRANSITION_PAIR_NOT_SUPPORTED"


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("kind", ("handoff", "reversal"))
@pytest.mark.parametrize("case,reason", (
    ("missing", "TRANSITION_EVIDENCE_IDENTITY_UNAVAILABLE"),
    ("missing_session", "TRANSITION_EVIDENCE_IDENTITY_UNAVAILABLE"),
    ("stock", "TRANSITION_EVIDENCE_SYMBOL_MISMATCH"),
    ("record_stock", "TRANSITION_EVIDENCE_SYMBOL_MISMATCH"),
    ("session", "TRANSITION_EVIDENCE_SESSION_MISMATCH"),
    ("record_session", "TRANSITION_EVIDENCE_SESSION_MISMATCH"),
    ("setup", "TRANSITION_EVIDENCE_SETUP_MISMATCH"),
    ("inputs", "TRANSITION_EVIDENCE_SETUP_MISMATCH"),
    ("original_link", "TRANSITION_EVIDENCE_SETUP_MISMATCH"),
    ("closed", "TRANSITION_EVIDENCE_NOT_HANDED_OVER"),
    ("break_direction", "TRANSITION_BREAK_DIRECTION_MISMATCH"),
    ("target_direction", "TRANSITION_REVERSAL_DIRECTION_MISMATCH"),
    ("source_late", "TRANSITION_ORDER_MISMATCH"),
    ("target_early", "TRANSITION_ORDER_MISMATCH"),
    ("input_late", "TRANSITION_ORDER_MISMATCH"),
    ("crossing_late", "TRANSITION_ORDER_MISMATCH"),
))
def test_unrelated_refused_and_out_of_order_assessments_cannot_declare_transition(direction, kind, case, reason):
    orb, reversal, declared = transition_fixture(direction, kind)
    if case == "missing":
        declared = replace(declared, supporting_records=())
    elif case == "missing_session":
        declared = replace(declared, session=None)
    elif case == "stock":
        orb = replace(orb, metadata=replace(orb.metadata, instrument_id="OTHER"))
        reversal = replace(reversal, metadata=replace(reversal.metadata, instrument_id="OTHER"))
    elif case in ("record_stock", "record_session", "input_late"):
        item, *rest = declared.supporting_records
        changes = ({"instrument_id": "OTHER"} if case == "record_stock" else
                   {"session": "2026-07-07"} if case == "record_session" else
                   {"available_time": ENDED_AT})
        declared = replace(declared, supporting_records=(replace(item, metadata=replace(
            item.metadata, **changes)), *rest))
    elif case == "session":
        orb = replace(orb, session_record_id="unrelated-session")
        reversal = replace(reversal, session_record_id="unrelated-session")
    elif case == "setup":
        reversal = replace(reversal, structure_id="unrelated-setup")
    elif case == "inputs":
        orb = replace(orb, input_record_ids=("unrelated-input",))
    elif case == "original_link":
        reversal = replace(reversal, input_record_ids=orb.input_record_ids)
    elif case == "closed":
        declared = replace(declared, evidence=replace(declared.evidence, state=StrategyState("INVALIDATED")))
    elif case == "break_direction":
        valid = candidate("valid", direction=reversal.direction, trigger=orb.trigger_price)
        orb = replace(orb, direction=reversal.direction, risk=valid.risk, targets=valid.targets)
    elif case == "target_direction":
        valid = candidate("valid", direction=orb.direction, trigger=reversal.trigger_price)
        reversal = replace(reversal, direction=orb.direction, risk=valid.risk, targets=valid.targets)
    elif case == "source_late":
        orb = replace(orb, created_at=ENDED_AT + timedelta(microseconds=1))
    elif case == "target_early":
        reversal = replace(reversal, created_at=ENDED_AT - timedelta(microseconds=1),
                           metadata=metadata(ENDED_AT - timedelta(microseconds=1)))
    elif case == "crossing_late":
        declared = replace(declared, evidence=replace(declared.evidence, candidate=replace(
            declared.evidence.candidate, crossed_at=ENDED_AT)))
    found = report(orb, reversal, transitions=(declared,))
    assert found.transitions[0].status == REFUSED
    assert found.transitions[0].reason == reason
    assert found.pair("orb", "reversal").relation != DECLARED_TRANSITION


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("case,status,reason", (
    ("stale", "UNKNOWN", "HANDOFF_NOT_CURRENT"),
    ("missing_input", "UNKNOWN", "HANDOFF_UNKNOWN_OPENING_RANGE_AGREEMENT"),
    ("not_forming", "FAIL", "HANDOFF_NOT_FAILURE_FORMING_REACCEPTANCE_INSIDE"),
))
def test_real_reversal_evaluator_refuses_failed_or_unknown_failure_handoff(direction, case, status, reason):
    orb, reversal, declared = transition_fixture(direction, "reversal")
    if case == "stale":
        # The real completed handoff is older than the reversal evaluation.
        request = reversal_request(direction, at=ENDED_AT + timedelta(minutes=1),
                                   handoff=evaluate_or_failure_handoff(handoff_request(direction)))
        reversal = replace(reversal, created_at=ENDED_AT + timedelta(minutes=1, seconds=1))
    elif case == "missing_input":
        request = reversal_request(direction, handoff=evaluate_or_failure_handoff(
            handoff_request(direction, opening_range=None)))
    else:
        request = reversal_request(direction, handoff=evaluate_or_failure_handoff(
            handoff_request(direction, minute_close=reacceptance(
                direction, close=declared.evidence.candidate.boundary))))
    evidence = evaluate_or_failure_rev(request)
    assert evidence.gate(HANDOFF_GATE).status == status
    assert evidence.gate(HANDOFF_GATE).reason == reason
    assert evidence.state == StrategyState("SETUP_FORMING", "FAILURE_FORMING")
    declared = replace(declared, evidence=evidence)
    found = report(orb, reversal, transitions=(declared,))
    assert found.transitions[0].status == REFUSED
    assert found.transitions[0].reason == "TRANSITION_EVIDENCE_NOT_HANDED_OVER"
    assert found.pair("orb", "reversal").relation == OPPOSITE_DIRECTION_CONFLICT
    assert found.as_dict()["transitions"][0]["evidence"] == evidence.as_dict()


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("kind", ("handoff", "reversal"))
@pytest.mark.parametrize("identity,reason", (
    ({"instrument_id": "OTHER"}, "TRANSITION_EVIDENCE_SYMBOL_MISMATCH"),
    ({"session": "2026-07-07"}, "TRANSITION_EVIDENCE_SESSION_MISMATCH"),
))
def test_real_evaluation_source_identity_cannot_borrow_original_setup(direction, kind, identity, reason):
    orb, reversal, declared = transition_fixture(direction, kind, evaluation_identity=identity)
    assert (declared.evidence.state.state == "SETUP_FORMING" if kind == "handoff"
            else declared.evidence.gate(HANDOFF_GATE).status == "PASS")
    found = report(orb, reversal, transitions=(declared,))
    assert found.transitions[0].reason == reason
    assert found.transitions[0].status == REFUSED
    assert found.pair("orb", "reversal").relation == OPPOSITE_DIRECTION_CONFLICT


@pytest.mark.parametrize("kind", ("handoff", "reversal"))
def test_all_actual_evaluation_inputs_are_required_and_later_inputs_use_evaluation_time(kind):
    orb, reversal, declared = transition_fixture(kind=kind)
    original_ids = {declared.evidence.candidate.anchor_bar_id,
                    *declared.evidence.candidate.input_record_ids}
    required = {value for gate in declared.evidence.gates for value in gate.input_record_ids}
    if kind == "reversal":
        required.update(declared.evidence.structural_input_ids)
    sources = {item.record_id: item for item in declared.supporting_records}
    assert required <= sources.keys()
    later = {record_id for record_id in required if sources[record_id].metadata.available_time
             > declared.evidence.candidate.crossed_at}
    assert later
    assert report(orb, reversal, transitions=(declared,)).transitions[0].status == ACCEPTED
    for record_id in required - original_ids:
        missing = replace(declared, supporting_records=tuple(
            item for item in declared.supporting_records if item.record_id != record_id))
        assert report(orb, reversal, transitions=(missing,)).transitions[0].reason == "TRANSITION_EVIDENCE_IDENTITY_UNAVAILABLE"
    record_id = sorted(later)[0]
    source = sources[record_id]
    too_late = replace(source, metadata=replace(source.metadata,
        available_time=declared.evidence.evaluated_at + timedelta(microseconds=1)))
    refused = replace(declared, supporting_records=tuple(
        too_late if item.record_id == record_id else item for item in declared.supporting_records))
    assert report(orb, reversal, transitions=(refused,)).transitions[0].reason == "TRANSITION_ORDER_MISMATCH"


def test_first_four_playbook_relationships_and_open_decisions_are_labels_only():
    rows = (
        candidate("a", "CRVOL_ORB5"), candidate("b", "OR_FAILURE_REV"),
        candidate("c", "HOD_COMP_RS"), candidate("d", "FIRST_PULLBACK_VWAP"),
    )
    result = report(*rows)
    assert result.pair("a", "b").playbook_relationship == "ORB_TO_OR_FAILURE"
    assert result.pair("a", "c").playbook_relationship is None
    assert result.pair("c", "d").playbook_relationship is None
    assert result.unavailable == UNDEFINED
    assert result.candidates == tuple(sorted(rows, key=lambda row: row.record_id))


@pytest.mark.parametrize("case", ("duplicate_candidate", "mixed_session", "future_candidate",
                                  "duplicate_atr", "unknown_transition_candidate",
                                  "future_transition_evidence"))
def test_conflicting_or_future_supplied_records_are_refused(case):
    first = candidate("a")
    second = candidate("b", "OR_FAILURE_REV", "SHORT")
    values = dict(evaluated_at=EVALUATED, policy=policy(), candidates=(first, second),
                  atrs=(atr(),), transitions=())
    if case == "duplicate_candidate":
        values["candidates"] = (first, first)
    elif case == "mixed_session":
        values["candidates"] = (first, replace(second, session_record_id="other-session"))
    elif case == "future_candidate":
        values["candidates"] = (first, candidate("future", created=EVALUATED + timedelta(seconds=1)))
    elif case == "duplicate_atr":
        values["atrs"] = (atr(), atr(record_id="other-atr"))
    else:
        evidence = evaluate_or_failure_handoff(handoff_request("LONG"))
        if case == "future_transition_evidence":
            evidence = replace(evidence, evaluated_at=EVALUATED + timedelta(seconds=1))
        target = "absent" if case == "unknown_transition_candidate" else "b"
        values["transitions"] = (DeclaredTransition("transition", "a", target, evidence),)
    with pytest.raises(RecordError):
        InteractionRequest(**values)


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("kind", ("handoff", "reversal"))
def test_recording_is_deterministic_and_retains_every_component_candidate(direction, kind):
    orb, reversal, transition = transition_fixture(direction, kind)
    rows = (orb, reversal, candidate("hod", "HOD_COMP_RS", "LONG", score=65),
            candidate("pullback", "FIRST_PULLBACK_VWAP", "LONG", score=65))
    result = report(*rows, transitions=(transition,))
    assert result.transitions[0].status == ACCEPTED
    assert result.candidates == tuple(sorted(rows, key=lambda item: item.record_id))
    first = result.to_json()
    shuffled = replace(transition, supporting_records=tuple(reversed(transition.supporting_records)))
    second = report(*reversed(rows), transitions=(shuffled,)).to_json()
    assert first == second
    payload = {
        "evidence": "SYNTHETIC_SOFTWARE_PROOF_ONLY",
        "interaction_version": INTERACTION_VERSION,
        "report": json.loads(first),
        "report_sha256": hashlib.sha256(first.encode()).hexdigest(),
        "component_candidate_ids": sorted(row.record_id for row in rows),
        "all_components_retained": True,
    }
    rendered = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    assert len(rendered.encode()) < 100_000
    filename = ("m8_5_cross_strategy_interaction_proof.json"
                if (kind, direction) == ("handoff", "LONG") else
                f"m8_5_cross_strategy_interaction_{kind}_{direction.lower()}_proof.json")
    (Path(os.environ["TMPDIR"]) / filename).write_text(rendered)
