"""M9.1DV retained first-four owner-input admission contracts."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

from consensus_engine.retained_decision_moments import PLAYBOOKS
from consensus_engine.retained_first_four_evaluator_plan import (
    build_retained_first_four_evaluator_plan,
)
from consensus_engine.retained_first_four_owner_inputs import (
    RUN_VERSION,
    bind_retained_first_four_owner_inputs,
)
from consensus_engine.trade_alerts_models import RecordError
from test_retained_first_two_producers import _input


def _plans():
    return tuple(
        build_retained_first_four_evaluator_plan(_input(playbook))
        for playbook in PLAYBOOKS
    )


def test_retained_unknowns_admit_no_steps_or_parent_records():
    admitted = tuple(bind_retained_first_four_owner_inputs(plan) for plan in _plans())

    assert tuple(row.playbook for row in admitted) == PLAYBOOKS
    assert all(row.version == RUN_VERSION for row in admitted)
    assert {row.status for row in admitted} == {"UNAVAILABLE"}
    assert all(row.steps == () and row.parent_records == () for row in admitted)
    assert all("CONFIDENCE_UNAVAILABLE" in row.missing_required_inputs for row in admitted)
    assert "ENDED_ORB_ATTEMPT_UNAVAILABLE" in admitted[2].missing_required_inputs
    assert "IMPULSE_PULLBACK_PARENT_UNAVAILABLE" in admitted[3].missing_required_inputs


def test_removed_missing_labels_cannot_admit_incomplete_canonical_contents():
    for plan in _plans():
        admitted = bind_retained_first_four_owner_inputs(
            replace(plan, missing_required_inputs=()),
        )
        assert admitted.status == "UNAVAILABLE"
        assert admitted.steps == () and admitted.parent_records == ()
        if plan.playbook in PLAYBOOKS[:2]:
            assert admitted.missing_required_inputs == ("CONFIDENCE_UNAVAILABLE",)
        else:
            assert "EVALUATOR_STEPS_UNAVAILABLE" in admitted.missing_required_inputs


def test_rejects_forged_evaluator_binding_before_admission():
    forged = replace(_plans()[0], evaluator_type="OrFailureRevReplayStrategy")
    with pytest.raises(RecordError, match="binding does not match"):
        bind_retained_first_four_owner_inputs(forged)


def test_recorded_owner_input_admission_is_deterministic():
    rows = tuple(bind_retained_first_four_owner_inputs(plan) for plan in _plans())
    complete = []
    rejected = []
    identity_rejected = []
    for playbook in PLAYBOOKS:
        for direction in ("LONG", "SHORT"):
            plan = _complete_plan(playbook, direction)
            admitted = bind_retained_first_four_owner_inputs(plan)
            assert admitted.status == "READY", admitted.missing_required_inputs
            complete.append(admitted.as_dict())
            rejected.append(_refused(replace(
                plan, retained_source_record_ids=("wrong-source",))).as_dict())
            if playbook == "FIRST_PULLBACK_VWAP":
                step, = plan.steps
                changed = replace(step.measurement, record_id="different-parent-record")
                identity_rejected.append(_refused(
                    replace(plan, steps=(replace(step, measurement=changed),)),
                    "IMPULSE_PARENT_CONTENT_MISMATCH").as_dict())
    for direction in ("LONG", "SHORT"):
        identity_rejected.append(_refused(
            _mixed_step_plan(direction, feature_sources=True),
            "CONFIDENCE_SOURCE_MISMATCH").as_dict())
    full = [row.as_dict() for row in rows] + complete + rejected + identity_rejected
    canonical = json.dumps(full, sort_keys=True, separators=(",", ":")).encode()
    recording = {
        "version": RUN_VERSION,
        "playbooks": list(PLAYBOOKS),
        "owner_input_sha256": hashlib.sha256(canonical).hexdigest(),
        "canonical_bytes": len(canonical),
        "synthetic_complete_inputs": complete,
        "synthetic_wrong_source_rejections": rejected,
        "synthetic_parent_and_mixed_step_rejections": identity_rejected,
        "statuses": {row.playbook: row.status for row in rows},
        "admitted_step_counts": {row.playbook: len(row.steps) for row in rows},
        "admitted_parent_counts": {row.playbook: len(row.parent_records) for row in rows},
        "missing_required_inputs": {
            row.playbook: list(row.missing_required_inputs) for row in rows
        },
        "gap_dependent_rules": "OFF_UNTESTED",
        "owner_constructed": False,
        "exact_sample_released": False,
    }
    rendered = json.dumps(recording, sort_keys=True, indent=2) + "\n"
    output = Path(os.environ["TMPDIR"], "m91dv-retained-first-four-owner-inputs.json")
    output.write_text(rendered)
    assert output.read_text() == rendered
    assert len(rendered.encode()) < 2 * 1024 * 1024


def _complete_plan(playbook, direction="LONG"):
    """Synthetic canonical evidence only; no retained missing fact is filled in."""
    from consensus_engine.confidence import ConfidenceRequest, compose_confidence
    from consensus_engine.strategy_interface import StrategyContext
    from consensus_engine.trade_alerts_models import FeatureSnapshot, FeatureValue
    from test_confidence import MODE, VERSION, policy
    from test_strategy_interface import session

    parents = ()
    if playbook == "CRVOL_ORB5":
        from test_orb5_replay import trigger_step
        step = trigger_step(direction)
        snapshots = tuple(getattr(step.geometry.request, name).snapshot for name in (
            "anchor", "frozen_atr", "price_increment", "boundary", "entry"))
        sources = tuple(sorted({ref for row in snapshots for ref in row.input_record_ids}))
        reference = snapshots[0]
    elif playbook == "HOD_COMP_RS":
        from test_hod_comp_rs_replay import trigger_step
        step = trigger_step(direction)
        sources = step.structural.record_ids
        reference = step.confidence.request.context.features[0]
    elif playbook == "OR_FAILURE_REV":
        from consensus_engine.retained_or_failure_parent_scan import scan_retained_or_failure_parents
        from test_retained_or_failure_parent_scan import _input as parent_input, _coverage
        value = parent_input(direction="SHORT" if direction == "LONG" else "LONG")
        scan = scan_retained_or_failure_parents(value, trade_coverage=_coverage(value))
        step, = scan.reversal_steps
        parents = scan.handoff_requests
        sources = value.source_record_ids
        reference = build_retained_first_four_evaluator_plan(value).offline_inputs[0].measurement
    else:
        from consensus_engine.retained_first_pullback_parent_scan import scan_retained_first_pullback_parents
        from test_retained_first_pullback_parent_scan import _input as parent_input, _evidence
        value = parent_input(direction)
        scan = scan_retained_first_pullback_parents(value, evidence=_evidence(value))
        step, = scan.pullback_steps
        sources = value.source_record_ids
        reference = step.measurement

    at = step.evaluated_at
    meta = replace(reference.metadata, source_time=at, available_time=at,
                   received_time=at, normalized_time=at)
    # All test scores cite the actual supplied step ancestors, not unrelated IDs.
    reference = FeatureSnapshot(
        record_id="synthetic-admission-moment", metadata=meta, evaluated_at=at,
        features=(FeatureValue("SYNTHETIC_BOUNDARY", 1, "BOOLEAN", input_record_ids=sources),),
        feature_version="SYNTHETIC_ADMISSION_V1", input_record_ids=sources,
    )
    if playbook == "FIRST_PULLBACK_VWAP":
        reference = step.measurement
    score_refs = sources
    if playbook == "OR_FAILURE_REV":
        score_refs = step.handoff.candidate.input_record_ids
    elif playbook == "FIRST_PULLBACK_VWAP":
        score_refs = step.measurement.input_record_ids
    rules = policy(strategy_id=playbook)
    scores = FeatureSnapshot(
        record_id="synthetic-admission-scores", metadata=replace(meta, data_mode=MODE),
        evaluated_at=at, feature_version=VERSION, input_record_ids=score_refs,
        features=tuple(FeatureValue(term.feature_name, 50, "SCORE_POINTS", input_record_ids=score_refs)
                       for term in rules.terms),
    )
    context = StrategyContext(session(meta.session), meta.instrument_id, meta.instrument_type,
                              direction, at, (scores,))
    confidence = compose_confidence(ConfidenceRequest(
        context, rules, tuple((term.name, scores.record_id) for term in rules.terms)))
    assert confidence.status == "READY"
    step = replace(step, confidence=confidence)
    base = _plans()[0]
    moment = replace(base.offline_inputs[0], evaluated_at=at, measurement=reference,
                     missing_required_inputs=())
    from consensus_engine.retained_first_four_evaluator_plan import EVALUATORS
    return replace(base, playbook=playbook, evaluator_type=EVALUATORS[playbook],
                   steps=(step,), parent_records=parents, offline_inputs=(moment,),
                   retained_source_record_ids=sources, missing_required_inputs=())


def _refused(plan, reason=None):
    result = bind_retained_first_four_owner_inputs(plan)
    assert result.status == "UNAVAILABLE"
    assert result.steps == result.parent_records == ()
    if reason:
        assert reason in result.missing_required_inputs
    return result


def _mixed_step_plan(direction, *, feature_sources):
    """Two admitted synthetic steps, then mix the later source into the first."""
    from datetime import timedelta
    from consensus_engine.confidence import compose_confidence

    plan = _complete_plan("HOD_COMP_RS", direction)
    first, = plan.steps
    moment, = plan.offline_inputs
    request = first.confidence.request
    scores, = request.context.features
    at = first.evaluated_at + timedelta(minutes=1)
    refs = ("other-retained-step-source",)
    later_scores = replace(
        scores, record_id="later-step-scores", evaluated_at=at, input_record_ids=refs,
        metadata=replace(scores.metadata, source_time=at, available_time=at,
                         received_time=at, normalized_time=at),
        features=tuple(replace(row, input_record_ids=refs) for row in scores.features),
    )
    later_confidence = compose_confidence(replace(
        request, context=replace(request.context, evaluated_at=at, features=(later_scores,)),
        bindings=tuple((name, later_scores.record_id) for name, _ in request.bindings),
    ))
    later = replace(first, evaluated_at=at, confidence=later_confidence,
                    structural=replace(first.structural, evaluated_at=at,
                                       available_at=at, record_ids=refs))
    plan = replace(
        plan, steps=(first, later),
        offline_inputs=(moment, replace(moment, evaluated_at=at, measurement=later_scores)),
        retained_source_record_ids=(*plan.retained_source_record_ids, *refs),
    )
    admitted = bind_retained_first_four_owner_inputs(plan)
    assert admitted.status == "READY", admitted.missing_required_inputs
    mixed_refs = (*scores.input_record_ids, *refs)
    mixed_scores = replace(
        scores, input_record_ids=mixed_refs,
        features=tuple(replace(row, input_record_ids=mixed_refs) for row in scores.features)
        if feature_sources else scores.features,
    )
    mixed_confidence = compose_confidence(replace(
        request, context=replace(request.context, features=(mixed_scores,)),
    ))
    assert mixed_confidence.status == "READY"
    return replace(plan, steps=(replace(first, confidence=mixed_confidence), later))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("feature_sources", (False, True))
def test_confidence_rejects_sources_from_another_admitted_step(direction, feature_sources):
    _refused(_mixed_step_plan(direction, feature_sources=feature_sources),
             "CONFIDENCE_SOURCE_MISMATCH")


@pytest.mark.parametrize("playbook", PLAYBOOKS)
@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
def test_complete_canonical_inputs_are_admitted(playbook, direction):
    plan = _complete_plan(playbook, direction)
    result = bind_retained_first_four_owner_inputs(plan)
    assert result.status == "READY", result.missing_required_inputs
    assert result.steps == plan.steps
    assert result.parent_records == plan.parent_records
    assert result.retained_source_record_ids == plan.retained_source_record_ids
    assert result.missing_required_inputs == ()


@pytest.mark.parametrize("playbook", PLAYBOOKS)
@pytest.mark.parametrize("case", (
    "symbol", "instrument", "session", "direction", "time", "source", "outside_step",
    "mixed_step_source", "term_source", "missing_binding",
    "wrong_binding", "forged_score", "forged_ready", "wrong_strategy", "missing_moment",
    "duplicate_moment", "wrong_step_type", "step_source",
))
def test_confidence_must_belong_to_the_plan_and_step(playbook, case):
    from datetime import timedelta
    from consensus_engine.confidence import compose_confidence
    plan = _complete_plan(playbook)
    step, = plan.steps
    result = step.confidence
    request = result.request
    context = request.context
    if case in ("symbol", "instrument", "direction"):
        key, value = {"symbol": ("symbol", "OTHER"), "instrument": ("instrument_type", "ETF"),
                      "direction": ("direction", "SHORT")}[case]
        request = replace(request, context=replace(context, **{key: value}))
    elif case == "session":
        moment, = plan.offline_inputs
        measurement = replace(moment.measurement, metadata=replace(
            moment.measurement.metadata, session="2026-07-07"))
        plan = replace(plan, offline_inputs=(replace(moment, measurement=measurement),))
    elif case == "time":
        request = replace(request, context=replace(context, evaluated_at=context.evaluated_at + timedelta(seconds=1)))
    elif case in ("source", "outside_step", "mixed_step_source", "term_source", "forged_ready"):
        snapshot, = context.features
        refs = ("unrelated-source",) if case in ("source", "outside_step") else snapshot.input_record_ids
        if case == "outside_step":
            plan = replace(plan, retained_source_record_ids=(*plan.retained_source_record_ids, *refs))
        if case == "mixed_step_source":
            refs = (*snapshot.input_record_ids, "other-retained-step-source")
            plan = replace(
                plan,
                retained_source_record_ids=(
                    *plan.retained_source_record_ids,
                    "other-retained-step-source",
                ),
            )
        if case == "term_source":
            refs = (*snapshot.input_record_ids, "unrelated-source")
            plan = replace(plan, retained_source_record_ids=(*plan.retained_source_record_ids, "unrelated-source"))
        features = tuple(replace(row, input_record_ids=("unrelated-source",) if case == "term_source" else refs,
                                 value=None if case == "forged_ready" else row.value,
                                 missing_reason="ABSENT" if case == "forged_ready" else None)
                         for row in snapshot.features)
        snapshot = replace(snapshot, features=features, input_record_ids=refs)
        request = replace(request, context=replace(context, features=(snapshot,)))
        if case == "forged_ready":
            assert compose_confidence(request).status == "UNAVAILABLE"
    elif case == "missing_binding":
        request = replace(request, bindings=request.bindings[:-1])
    elif case == "wrong_binding":
        request = replace(request, bindings=tuple((name, "absent") for name, _ in request.bindings))
    elif case == "forged_score":
        result = replace(result, confidence=replace(result.confidence, final_score=99))
    elif case == "wrong_strategy":
        other = "HOD_COMP_RS" if playbook == "CRVOL_ORB5" else "CRVOL_ORB5"
        request = replace(request, policy=replace(request.policy, strategy_id=other))
    elif case == "missing_moment":
        plan = replace(plan, offline_inputs=())
    elif case == "duplicate_moment":
        plan = replace(plan, offline_inputs=plan.offline_inputs * 2)
    elif case == "wrong_step_type":
        from types import SimpleNamespace
        _refused(replace(plan, steps=(SimpleNamespace(evaluated_at=step.evaluated_at, confidence=result),)))
        return
    elif case == "step_source":
        plan = replace(plan, retained_source_record_ids=("unrelated-source",))
    if case == "mixed_step_source":
        result = compose_confidence(request)
        assert result.status == "READY"
        _refused(replace(plan, steps=(replace(step, confidence=result),)),
                 "CONFIDENCE_SOURCE_MISMATCH")
        return
    result = replace(result, request=request)
    _refused(replace(plan, steps=(replace(step, confidence=result),)))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("case", (
    "object", "symbol", "instrument", "time", "session", "source", "missing_range",
    "wrong_candidate", "forged_handoff", "extreme", "close", "incomplete", "reordered",
))
def test_reversal_parent_must_match_its_exact_step(direction, case):
    from datetime import timedelta
    plan = _complete_plan("OR_FAILURE_REV", direction)
    parent, = plan.parent_records
    step, = plan.steps
    if case == "object":
        parent = object()
    elif case in ("symbol", "instrument"):
        parent = replace(parent, **({"symbol": "OTHER"} if case == "symbol" else {"instrument_type": "ETF"}))
    elif case == "time":
        parent = replace(parent, evaluated_at=parent.evaluated_at + timedelta(seconds=1))
    elif case in ("session", "source"):
        snapshot = parent.opening_range
        snapshot = (replace(snapshot, metadata=replace(snapshot.metadata, session="2026-07-07"))
                    if case == "session" else replace(snapshot, input_record_ids=("unrelated",)))
        parent = replace(parent, opening_range=snapshot)
    elif case == "missing_range":
        parent = replace(parent, opening_range=None)
    elif case == "wrong_candidate":
        candidate = replace(parent.candidate, attempt_number=parent.candidate.attempt_number + 1)
        parent = replace(parent, attempt=replace(parent.attempt, candidate=candidate))
    elif case == "forged_handoff":
        step = replace(step, handoff=replace(step.handoff, excursion=999))
    elif case == "extreme":
        step = replace(step, breakout_extreme_price=999)
    elif case == "close":
        step = replace(step, confirmation_close=replace(step.confirmation_close, record_id="other-close"))
    elif case == "incomplete":
        parent = replace(parent, breakout_extreme=None)
    elif case == "reordered":
        other = _complete_plan("OR_FAILURE_REV", "SHORT" if direction == "LONG" else "LONG")
        plan = replace(plan, steps=(step, other.steps[0]), parent_records=(other.parent_records[0], parent))
        _refused(plan)
        return
    _refused(replace(plan, steps=(step,), parent_records=(parent,)))


@pytest.mark.parametrize("direction", ("LONG", "SHORT"))
@pytest.mark.parametrize("case", (
    "object", "symbol", "instrument", "session", "time", "future", "source", "version",
    "mode", "unit", "same_metadata_different_content", "record_id_only", "content_only",
    "missing_feature", "missing_value",
    "incomplete", "unordered", "wrong_direction",
))
def test_pullback_requires_complete_matching_impulse_contents(direction, case):
    from copy import copy
    from datetime import timedelta
    plan = _complete_plan("FIRST_PULLBACK_VWAP", direction)
    step, = plan.steps
    snapshot = step.measurement
    if case == "object":
        # Simulate an untrusted deserialized object that bypassed construction.
        step = copy(step)
        object.__setattr__(step, "measurement", object())
        _refused(replace(plan, steps=(step,)))
        return
    if case in ("symbol", "instrument", "session", "mode", "future"):
        key, value = {
            "symbol": ("instrument_id", "OTHER"), "instrument": ("instrument_type", "ETF"),
            "session": ("session", "2026-07-07"), "mode": ("data_mode", "WRONG_MODE"),
            "future": ("available_time", step.evaluated_at + timedelta(seconds=1)),
        }[case]
        snapshot = replace(snapshot, metadata=replace(snapshot.metadata, **{key: value}),
                           evaluated_at=value if case == "future" else snapshot.evaluated_at)
    elif case == "time":
        at = step.evaluated_at - timedelta(seconds=1)
        snapshot = replace(snapshot, evaluated_at=at, metadata=replace(
            snapshot.metadata, source_time=at, received_time=at, available_time=at, normalized_time=at))
    elif case == "source":
        snapshot = replace(snapshot, input_record_ids=("unrelated",))
    elif case == "version":
        snapshot = replace(snapshot, feature_version="WRONG_VERSION")
    elif case == "unit":
        snapshot = replace(snapshot, features=tuple(replace(row, unit="WRONG_UNIT")
                                                   for row in snapshot.features))
    elif case in ("same_metadata_different_content", "record_id_only", "content_only"):
        snapshot = replace(
            snapshot,
            record_id=snapshot.record_id if case == "content_only" else "different-parent-record",
            features=tuple(
                replace(row, value=row.value + 1)
                if row.name == "IMPULSE_VOLUME_V1" and case != "record_id_only" else row
                for row in snapshot.features
            ),
        )
        _refused(replace(plan, steps=(replace(step, measurement=snapshot),)),
                 "IMPULSE_PARENT_CONTENT_MISMATCH")
        return
    elif case == "missing_feature":
        snapshot = replace(snapshot, features=snapshot.features[:-1])
    elif case in ("missing_value", "incomplete", "unordered"):
        name = {"missing_value": "IMPULSE_ORIGIN_V1", "incomplete": "IMPULSE_COMPLETE_V1",
                "unordered": "IMPULSE_EXTREME_AFTER_ORIGIN_V1"}[case]
        snapshot = replace(snapshot, features=tuple(
            replace(row, value=None if case == "missing_value" else 0,
                    missing_reason="ABSENT" if case == "missing_value" else None)
            if row.name == name else row for row in snapshot.features))
    elif case == "wrong_direction":
        other = _complete_plan("FIRST_PULLBACK_VWAP", "SHORT" if direction == "LONG" else "LONG")
        snapshot = other.steps[0].measurement
    _refused(replace(plan, steps=(replace(step, measurement=snapshot),)))


@pytest.mark.parametrize("playbook", PLAYBOOKS[:2])
@pytest.mark.parametrize("case", ("missing_direction", "step_time", "step_source"))
def test_first_two_direction_evidence_must_be_bound_independently(playbook, case):
    from datetime import timedelta
    plan = _complete_plan(playbook)
    step, = plan.steps
    if playbook == "CRVOL_ORB5":
        if case == "missing_direction":
            step = replace(step, preliminary=None, geometry=None)
        else:
            request = step.geometry.request
            if case == "step_time":
                request = replace(request, evaluated_at=request.evaluated_at + timedelta(seconds=1))
            else:
                anchor = replace(request.anchor, snapshot=replace(
                    request.anchor.snapshot, input_record_ids=("unrelated",)))
                request = replace(request, anchor=anchor)
            step = replace(step, geometry=replace(step.geometry, request=request))
    else:
        if case == "missing_direction":
            step = replace(step, structural=None)
        elif case == "step_time":
            step = replace(step, structural=replace(step.structural,
                           evaluated_at=step.evaluated_at + timedelta(seconds=1)))
        else:
            step = replace(step, structural=replace(step.structural, record_ids=("unrelated",)))
    _refused(replace(plan, steps=(step,)))
