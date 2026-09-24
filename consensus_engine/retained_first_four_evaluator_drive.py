"""M9.1DX drive admitted first-four owners through their exact contexts.

The plan remains the source of every evaluation context.  Proposed transitions
must be acknowledged unchanged by the supplied recording boundary before the
canonical owner is allowed to advance.  This module reads no clock or outside
source and releases no sample, candidate, alert, or live action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .retained_first_four_evaluator_owner import (
    RetainedFirstFourOwnerConfig,
    construct_retained_first_four_evaluator_owner,
)
from .retained_first_four_evaluator_plan import RetainedFirstFourEvaluatorPlan
from .retained_first_four_owner_inputs import bind_retained_first_four_owner_inputs
from .strategy_interface import StrategyContext, StrategyState
from .trade_alerts_models import RecordError, StrategyStateTransition

RUN_VERSION = "M91DX_RETAINED_FIRST_FOUR_EVALUATOR_DRIVE_V1"


class TransitionRecorder(Protocol):
    """Recording boundary that returns the exact transitions it saved."""

    def record(
        self,
        context: StrategyContext,
        transitions: tuple[StrategyStateTransition, ...],
    ) -> tuple[StrategyStateTransition, ...]: ...


@dataclass(frozen=True)
class RetainedFirstFourDriveResult:
    version: str
    playbook: str
    status: str
    evaluated_step_count: int
    proposed_transition_count: int
    acknowledged_transition_count: int
    final_state: StrategyState | None
    retained_source_record_ids: tuple[str, ...]
    missing_required_inputs: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "playbook": self.playbook,
            "status": self.status,
            "evaluated_step_count": self.evaluated_step_count,
            "proposed_transition_count": self.proposed_transition_count,
            "acknowledged_transition_count": self.acknowledged_transition_count,
            "final_state": None if self.final_state is None else self.final_state.__dict__,
            "retained_source_record_ids": list(self.retained_source_record_ids),
            "missing_required_inputs": list(self.missing_required_inputs),
        }


def _contexts(plan: RetainedFirstFourEvaluatorPlan) -> tuple[StrategyContext, ...]:
    contexts = tuple(
        getattr(getattr(step, "confidence", None), "request", None).context
        for step in plan.steps
        if getattr(getattr(step, "confidence", None), "request", None) is not None
    )
    if (len(contexts) != len(plan.steps)
            or any(type(context) is not StrategyContext for context in contexts)
            or any(context.evaluated_at != step.evaluated_at
                   for context, step in zip(contexts, plan.steps))):
        raise RecordError("evaluator drive requires every exact admitted step context")
    return contexts


def _discard_unrecorded(owner: object) -> None:
    """Prevent a later update from confirming a transition that was not saved."""
    pending = getattr(owner, "_pending", None)
    if not isinstance(pending, tuple):
        raise RecordError("canonical owner does not expose pending transitions")
    owner._pending = ()


def drive_retained_first_four_evaluator_owner(
    owner: object,
    plan: RetainedFirstFourEvaluatorPlan,
    recorder: TransitionRecorder,
) -> RetainedFirstFourDriveResult:
    """Evaluate admitted steps and advance only after exact recording acknowledgment."""
    if not callable(getattr(recorder, "record", None)):
        raise RecordError("evaluator drive requires a transition recorder")
    admitted = bind_retained_first_four_owner_inputs(plan)
    if admitted.status != "READY" or admitted.steps != plan.steps:
        raise RecordError("evaluator drive requires admitted complete inputs")
    if type(owner).__name__ != plan.evaluator_type:
        raise RecordError("evaluator drive owner does not match the admitted plan")
    contexts = _contexts(plan)
    proposed = acknowledged = 0
    for context in contexts:
        transitions = owner.update(context)
        if (not isinstance(transitions, tuple)
                or any(type(row) is not StrategyStateTransition for row in transitions)):
            raise RecordError("canonical owner returned invalid transitions")
        proposed += len(transitions)
        if transitions:
            try:
                saved = recorder.record(context, transitions)
            except Exception:
                _discard_unrecorded(owner)
                raise
            if saved != transitions:
                _discard_unrecorded(owner)
                raise RecordError("recording did not acknowledge the exact proposed transitions")
            acknowledged += len(saved)
            owner.confirm_recorded()
    return RetainedFirstFourDriveResult(
        RUN_VERSION,
        plan.playbook,
        "EVALUATED",
        len(contexts),
        proposed,
        acknowledged,
        owner.current_state(),
        admitted.retained_source_record_ids,
        (),
    )


def execute_retained_first_four_evaluator_drive(
    plan: RetainedFirstFourEvaluatorPlan,
    config: RetainedFirstFourOwnerConfig | None,
    recorder: TransitionRecorder | None,
) -> RetainedFirstFourDriveResult:
    """Keep incomplete retained plans off; otherwise construct and drive their owner."""
    admitted = bind_retained_first_four_owner_inputs(plan)
    if admitted.status != "READY":
        return RetainedFirstFourDriveResult(
            RUN_VERSION,
            plan.playbook,
            "UNAVAILABLE",
            0,
            0,
            0,
            None,
            admitted.retained_source_record_ids,
            admitted.missing_required_inputs,
        )
    if config is None or recorder is None:
        raise RecordError("complete evaluator drive requires owner config and recorder")
    owner = construct_retained_first_four_evaluator_owner(plan, config)
    return drive_retained_first_four_evaluator_owner(owner, plan, recorder)


__all__ = [
    "RUN_VERSION",
    "RetainedFirstFourDriveResult",
    "TransitionRecorder",
    "drive_retained_first_four_evaluator_owner",
    "execute_retained_first_four_evaluator_drive",
]
