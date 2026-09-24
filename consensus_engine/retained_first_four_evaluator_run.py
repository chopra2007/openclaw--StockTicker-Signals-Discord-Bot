"""M9.1DU fail-closed execution of retained first-four evaluator plans.

The retained plans currently contain genuine missing mandatory inputs.  This
boundary records that execution attempt without constructing or advancing a
strategy owner.  It also checks the plan contents instead of trusting a caller
that removes a missing-input label.
"""

from __future__ import annotations

from dataclasses import dataclass

from .retained_first_four_evaluator_plan import (
    EVALUATORS,
    RetainedFirstFourEvaluatorPlan,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91DU_RETAINED_FIRST_FOUR_EVALUATOR_RUN_V1"


@dataclass(frozen=True)
class RetainedFirstFourEvaluatorResult:
    """One immutable fail-closed result for a retained evaluator plan."""

    version: str
    playbook: str
    evaluator_type: str
    status: str
    reason: str
    planned_step_count: int
    evaluated_step_count: int
    transition_count: int
    retained_source_record_ids: tuple[str, ...]
    missing_required_inputs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "playbook": self.playbook,
            "evaluator_type": self.evaluator_type,
            "status": self.status,
            "reason": self.reason,
            "planned_step_count": self.planned_step_count,
            "evaluated_step_count": self.evaluated_step_count,
            "transition_count": self.transition_count,
            "retained_source_record_ids": list(self.retained_source_record_ids),
            "missing_required_inputs": list(self.missing_required_inputs),
        }


def _content_gaps(plan: RetainedFirstFourEvaluatorPlan) -> tuple[str, ...]:
    """Find mandatory gaps directly in the canonical records on the plan."""
    missing: list[str] = []
    if not plan.steps:
        missing.append("EVALUATOR_STEPS_UNAVAILABLE")
    elif any(getattr(step, "confidence", None) is None for step in plan.steps):
        missing.append("CONFIDENCE_UNAVAILABLE")

    if plan.playbook == "OR_FAILURE_REV":
        if not plan.parent_records:
            missing.append("ENDED_ORB_ATTEMPT_UNAVAILABLE")
        elif len(plan.parent_records) != len(plan.steps):
            missing.append("COMPLETE_PARENT_EVIDENCE_UNAVAILABLE")
    elif plan.playbook == "FIRST_PULLBACK_VWAP":
        if not plan.steps or any(getattr(step, "measurement", None) is None for step in plan.steps):
            missing.append("IMPULSE_PULLBACK_PARENT_UNAVAILABLE")
    return tuple(missing)


def execute_retained_first_four_evaluator_plan(
    plan: RetainedFirstFourEvaluatorPlan,
) -> RetainedFirstFourEvaluatorResult:
    """Attempt one plan and stop before evaluation when any input is unknown."""
    if not isinstance(plan, RetainedFirstFourEvaluatorPlan):
        raise RecordError("evaluator execution requires a retained evaluator plan")
    if plan.playbook not in EVALUATORS or plan.evaluator_type != EVALUATORS[plan.playbook]:
        raise RecordError("evaluator plan binding does not match the frozen first four")
    if not plan.retained_source_record_ids:
        raise RecordError("evaluator plan must retain source record identities")

    missing = tuple(dict.fromkeys((*plan.missing_required_inputs, *_content_gaps(plan))))
    if not missing:
        raise RecordError(
            "complete retained evaluator execution is unavailable without a canonical owner"
        )
    return RetainedFirstFourEvaluatorResult(
        RUN_VERSION,
        plan.playbook,
        plan.evaluator_type,
        "UNAVAILABLE",
        "|".join(missing),
        len(plan.steps),
        0,
        0,
        plan.retained_source_record_ids,
        missing,
    )


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourEvaluatorResult",
    "execute_retained_first_four_evaluator_plan",
]
