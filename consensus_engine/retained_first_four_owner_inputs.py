"""M9.1DV admission gate for retained first-four evaluator owners.

Only complete canonical confidence and parent evidence may cross this boundary.
The retained packet currently lacks those facts, so its plans remain unavailable.
This module does not construct or advance a strategy owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from .confidence import ConfidenceRequest, ConfidenceResult, compose_confidence
from .first_pullback_vwap_replay import PullbackReplayStep
from .hod_comp_rs_replay import HodCompRsReplayStep
from .impulse_pullback import (
    DATA_MODE as IMPULSE_MODE, FEATURE_VERSION as IMPULSE_VERSION, FEATURE_NAMES,
    IMPULSE_COMPLETE_NAME, IMPULSE_ORDERED_NAME, PULLBACK_COMPLETE_NAME,
    IMPULSE_SPECS, PULLBACK_SPECS, VWAP_SPECS,
)
from .orb5_replay import Orb5ReplayStep
from .or_failure_handoff import HandoffRequest, evaluate_or_failure_handoff
from .or_failure_rev_replay import OrFailureRevReplayStep
from .retained_offline_producer_inputs import RetainedOfflineProducerMoment
from .retained_first_four_evaluator_plan import (
    EVALUATORS,
    RetainedFirstFourEvaluatorPlan,
)
from .trade_alerts_models import FeatureSnapshot, RecordError
from .utils.time_context import session_date_at

RUN_VERSION = "M91DV_RETAINED_FIRST_FOUR_OWNER_INPUTS_V1"


@dataclass(frozen=True)
class RetainedFirstFourOwnerInputs:
    """The admitted owner inputs, or the exact reasons admission stopped."""

    version: str
    playbook: str
    evaluator_type: str
    status: str
    steps: tuple[object, ...]
    parent_records: tuple[object, ...]
    retained_source_record_ids: tuple[str, ...]
    missing_required_inputs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "playbook": self.playbook,
            "evaluator_type": self.evaluator_type,
            "status": self.status,
            "step_types": [type(row).__name__ for row in self.steps],
            "parent_record_types": [type(row).__name__ for row in self.parent_records],
            "retained_source_record_ids": list(self.retained_source_record_ids),
            "missing_required_inputs": list(self.missing_required_inputs),
        }


STEP_TYPES = {
    "CRVOL_ORB5": Orb5ReplayStep,
    "HOD_COMP_RS": HodCompRsReplayStep,
    "OR_FAILURE_REV": OrFailureRevReplayStep,
    "FIRST_PULLBACK_VWAP": PullbackReplayStep,
}


def _moment(plan, step):
    matches = [row for row in plan.offline_inputs
               if type(row) is RetainedOfflineProducerMoment
               and row.evaluated_at == step.evaluated_at]
    return matches[0] if len(matches) == 1 else None


def _snapshot_matches(snapshot, reference, at, sources, *, current=True):
    if type(snapshot) is not FeatureSnapshot or type(reference) is not FeatureSnapshot:
        return False
    meta = snapshot.metadata
    expected = reference.metadata
    return (
        (meta.instrument_id, meta.instrument_type, meta.session)
        == (expected.instrument_id, expected.instrument_type, expected.session)
        and (snapshot.evaluated_at == at if current else snapshot.evaluated_at <= at)
        and meta.source_time is not None
        and meta.source_time <= meta.available_time <= at
        and meta.quality in ("VALID", "DEGRADED_PROXY")
        and bool(snapshot.input_record_ids)
        and set(snapshot.input_record_ids).issubset(sources)
        and all(set(row.input_record_ids).issubset(snapshot.input_record_ids)
                for row in snapshot.features)
    )


def _direction(step):
    # Read direction from independent step evidence, never from its confidence.
    if type(step) is Orb5ReplayStep:
        result = step.geometry or step.preliminary
        return result.request.direction if result is not None else None
    if type(step) is HodCompRsReplayStep:
        return step.structural.direction if step.structural is not None else None
    if type(step) is OrFailureRevReplayStep:
        return step.handoff.direction
    if type(step) is PullbackReplayStep and type(step.measurement) is FeatureSnapshot:
        values = {row.name: row.value for row in step.measurement.features}
        origin, extreme = values.get("IMPULSE_ORIGIN_V1"), values.get("IMPULSE_EXTREME_V1")
        if origin is not None and extreme is not None and origin != extreme:
            return "LONG" if extreme > origin else "SHORT"
    return None


def _step_source_ids(step, reference, sources):
    """Return the independently bound step ancestors, or an empty set on mismatch."""
    at = step.evaluated_at
    if type(step) is Orb5ReplayStep:
        results = [row for row in (step.preliminary, step.geometry) if row is not None]
        ids = set()
        for result in results:
            request = result.request
            if request.evaluated_at != at or request.direction != _direction(step):
                return set()
            for name in ("anchor", "frozen_atr", "price_increment", "boundary", "entry"):
                snapshot = getattr(request, name).snapshot
                if not _snapshot_matches(snapshot, reference, at, sources, current=False):
                    return set()
                ids.update(snapshot.input_record_ids)
        return ids
    if type(step) is HodCompRsReplayStep:
        row = step.structural
        if row is None or row.evaluated_at != at or row.available_at > at:
            return set()
        return set(row.record_ids) if set(row.record_ids).issubset(sources) else set()
    if type(step) is OrFailureRevReplayStep:
        return set(step.handoff.candidate.input_record_ids)
    return set(step.measurement.input_record_ids)


def _confidence_gaps(plan: RetainedFirstFourEvaluatorPlan) -> tuple[str, ...]:
    if not plan.steps:
        return ("EVALUATOR_STEPS_UNAVAILABLE",)
    for step in plan.steps:
        if type(step) is not STEP_TYPES[plan.playbook]:
            return ("EVALUATOR_STEP_TYPE_MISMATCH",)
        confidence = step.confidence
        if type(confidence) is not ConfidenceResult:
            return ("CONFIDENCE_UNAVAILABLE",)
        request = confidence.request
        if type(request) is not ConfidenceRequest:
            return ("CONFIDENCE_REQUEST_TYPE_MISMATCH",)
        if confidence.status != "READY" or confidence.confidence is None:
            return ("CONFIDENCE_INCOMPLETE",)
        if request.policy.strategy_id != plan.playbook:
            return ("CONFIDENCE_IDENTITY_MISMATCH",)
        context = request.context
        if context.evaluated_at != step.evaluated_at:
            return ("CONFIDENCE_TIME_MISMATCH",)
        declared = {term.name for term in request.policy.terms}
        if {name for name, _record_id in request.bindings} != declared:
            return ("CONFIDENCE_BINDINGS_INCOMPLETE",)
        moment = _moment(plan, step)
        if moment is None:
            return ("OWNER_INPUT_MOMENT_MISMATCH",)
        reference = moment.measurement
        sources = set(plan.retained_source_record_ids)
        if not _snapshot_matches(reference, reference, step.evaluated_at, sources):
            return ("OWNER_INPUT_SOURCE_MISMATCH",)
        meta = reference.metadata
        if (context.symbol, context.instrument_type, context.session.session) != (
                meta.instrument_id, meta.instrument_type, meta.session):
            return ("CONFIDENCE_IDENTITY_MISMATCH",)
        if context.direction != _direction(step):
            return ("CONFIDENCE_DIRECTION_MISMATCH",)
        step_sources = _step_source_ids(step, reference, sources)
        if not step_sources or not step_sources.issubset(sources):
            return ("EVALUATOR_STEP_SOURCE_MISMATCH",)
        snapshots = {row.record_id: row for row in context.features}
        terms = {term.name: term for term in request.policy.terms}
        for name, record_id in request.bindings:
            snapshot = snapshots.get(record_id)
            # Plan-wide membership alone can admit evidence from another step.
            if (not _snapshot_matches(snapshot, reference, step.evaluated_at, sources)
                    or not set(snapshot.input_record_ids).issubset(step_sources)):
                return ("CONFIDENCE_SOURCE_MISMATCH",)
            feature = next((row for row in snapshot.features
                            if row.name == terms[name].feature_name), None)
            if (feature is None or not feature.input_record_ids
                    or not set(feature.input_record_ids).issubset(step_sources)):
                return ("CONFIDENCE_SOURCE_MISMATCH",)
        if compose_confidence(request) != confidence:
            return ("CONFIDENCE_CONTENT_MISMATCH",)
    return ()


def _parent_gaps(plan: RetainedFirstFourEvaluatorPlan) -> tuple[str, ...]:
    sources = set(plan.retained_source_record_ids)
    if plan.playbook == "OR_FAILURE_REV":
        if not plan.parent_records:
            return ("ENDED_ORB_ATTEMPT_UNAVAILABLE",)
        if len(plan.parent_records) != len(plan.steps):
            return ("COMPLETE_PARENT_EVIDENCE_UNAVAILABLE",)
        for parent, step in zip(plan.parent_records, plan.steps):
            if type(parent) is not HandoffRequest or type(step) is not OrFailureRevReplayStep:
                return ("OR_PARENT_TYPE_MISMATCH",)
            moment = _moment(plan, step)
            if moment is None:
                return ("OR_PARENT_MOMENT_MISMATCH",)
            meta = moment.measurement.metadata
            if (parent.symbol, parent.instrument_type) != (meta.instrument_id, meta.instrument_type):
                return ("OR_PARENT_IDENTITY_MISMATCH",)
            candidate = parent.candidate
            if (parent.evaluated_at != step.evaluated_at
                    or session_date_at(candidate.crossed_at).isoformat() != meta.session
                    or not candidate.crossed_at <= parent.attempt.evaluated_at <= step.evaluated_at):
                return ("OR_PARENT_TIME_MISMATCH",)
            if not _snapshot_matches(parent.opening_range, moment.measurement,
                                     step.evaluated_at, sources, current=False):
                return ("OR_PARENT_SOURCE_MISMATCH",)
            ids = {candidate.anchor_bar_id, *candidate.input_record_ids}
            ids.update(ref for gate in parent.attempt.gates for ref in gate.input_record_ids)
            if parent.breakout_extreme is None or parent.minute_close is None:
                return ("COMPLETE_PARENT_EVIDENCE_UNAVAILABLE",)
            ids.update((parent.breakout_extreme.record_id, parent.minute_close.record_id))
            if not ids.issubset(sources):
                return ("OR_PARENT_SOURCE_MISMATCH",)
            rebuilt = evaluate_or_failure_handoff(parent)
            if (rebuilt != step.handoff or any(gate.status != "PASS" for gate in rebuilt.gates)
                    or step.breakout_extreme_price != parent.breakout_extreme.price
                    or step.confirmation_close != parent.minute_close):
                return ("OR_PARENT_STEP_MISMATCH",)
    elif plan.playbook == "FIRST_PULLBACK_VWAP":
        if not plan.steps:
            return ("IMPULSE_PULLBACK_PARENT_UNAVAILABLE",)
        if plan.parent_records:
            return ("UNEXPECTED_PARENT_RECORDS",)
        for step in plan.steps:
            if type(step) is not PullbackReplayStep:
                return ("IMPULSE_PARENT_TYPE_MISMATCH",)
            moment = _moment(plan, step)
            if moment is None or not _snapshot_matches(
                    step.measurement, moment.measurement, step.evaluated_at, sources):
                return ("IMPULSE_PARENT_IDENTITY_TIME_SOURCE_MISMATCH",)
            if step.measurement != moment.measurement:
                # Metadata matching above does not establish record/content identity.
                return ("IMPULSE_PARENT_CONTENT_MISMATCH",)
            snapshot = step.measurement
            values = {row.name: row for row in snapshot.features}
            units = dict((*IMPULSE_SPECS, *PULLBACK_SPECS, *VWAP_SPECS,
                          ("IMPULSE_VOLUME_V1", "SHARES"), ("PULLBACK_VOLUME_V1", "SHARES"),
                          (IMPULSE_COMPLETE_NAME, "BOOLEAN"), (IMPULSE_ORDERED_NAME, "BOOLEAN"),
                          (PULLBACK_COMPLETE_NAME, "BOOLEAN"), ("PULLBACK_DEPTH_V1", "USD_PER_SHARE"),
                          ("PULLBACK_RETRACEMENT_V1", "RATIO"), ("PULLBACK_VOLUME_RATIO_V1", "RATIO"),
                          ("IMPULSE_DISTANCE_ATR_V1", "RATIO")))
            if (snapshot.feature_version != IMPULSE_VERSION or snapshot.metadata.data_mode != IMPULSE_MODE
                    or snapshot.metadata.source != "DERIVED_M83"
                    or any(row.unit != units.get(row.name) for row in snapshot.features)
                    or set(values) != set(FEATURE_NAMES)
                    or any(row.value is None or row.missing_reason is not None
                           or not row.input_record_ids for row in values.values())
                    or any(values[name].value != 1 for name in (
                        IMPULSE_COMPLETE_NAME, IMPULSE_ORDERED_NAME, PULLBACK_COMPLETE_NAME))
                    or _direction(step) is None):
                return ("IMPULSE_PULLBACK_PARENT_UNAVAILABLE",)
    elif plan.parent_records:
        return ("UNEXPECTED_PARENT_RECORDS",)
    return ()


def bind_retained_first_four_owner_inputs(
    plan: RetainedFirstFourEvaluatorPlan,
) -> RetainedFirstFourOwnerInputs:
    """Admit complete inputs and keep every incomplete plan fail closed."""
    if not isinstance(plan, RetainedFirstFourEvaluatorPlan):
        raise RecordError("owner-input admission requires a retained evaluator plan")
    if plan.playbook not in EVALUATORS or plan.evaluator_type != EVALUATORS[plan.playbook]:
        raise RecordError("evaluator plan binding does not match the frozen first four")
    if not plan.retained_source_record_ids:
        raise RecordError("owner-input admission requires retained source identities")

    missing = tuple(dict.fromkeys(
        (*plan.missing_required_inputs, *_confidence_gaps(plan), *_parent_gaps(plan))
    ))
    admitted = not missing
    return RetainedFirstFourOwnerInputs(
        RUN_VERSION,
        plan.playbook,
        plan.evaluator_type,
        "READY" if admitted else "UNAVAILABLE",
        plan.steps if admitted else (),
        plan.parent_records if admitted else (),
        plan.retained_source_record_ids,
        missing,
    )


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourOwnerInputs",
    "bind_retained_first_four_owner_inputs",
]
