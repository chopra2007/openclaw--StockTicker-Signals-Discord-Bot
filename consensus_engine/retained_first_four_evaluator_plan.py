"""M9.1DT fail-closed plans for the four retained strategy evaluators.

The plan binds the accepted retained input records to the canonical replay-step
types used by each first-four evaluator.  It also keeps parent records attached
for the two strategies that require them.  A plan is not runnable while any
mandatory input is missing; no unknown is replaced with a favorable value.
"""

from __future__ import annotations

from dataclasses import dataclass

from .retained_candidate_events import CandidateEventInput
from .retained_first_two_producers import build_retained_first_two_request
from .retained_offline_producer_inputs import RetainedOfflineProducerMoment
from .retained_remaining_producers import build_retained_remaining_request
from .trade_alerts_models import RecordError

RUN_VERSION = "M91DT_RETAINED_FIRST_FOUR_EVALUATOR_PLAN_V1"
EVALUATORS = {
    "CRVOL_ORB5": "Orb5ReplayStrategy",
    "HOD_COMP_RS": "HodCompRsReplayStrategy",
    "OR_FAILURE_REV": "OrFailureRevReplayStrategy",
    "FIRST_PULLBACK_VWAP": "FirstPullbackVwapReplayStrategy",
}


@dataclass(frozen=True)
class RetainedFirstFourEvaluatorPlan:
    """Exact accepted inputs and blockers for one canonical evaluator."""

    version: str
    playbook: str
    evaluator_type: str
    steps: tuple[object, ...]
    parent_records: tuple[object, ...]
    offline_inputs: tuple[RetainedOfflineProducerMoment, ...]
    retained_source_record_ids: tuple[str, ...]
    missing_required_inputs: tuple[str, ...]

    @property
    def runnable(self) -> bool:
        return bool(self.steps) and not self.missing_required_inputs

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "playbook": self.playbook,
            "evaluator_type": self.evaluator_type,
            "step_types": [type(row).__name__ for row in self.steps],
            "parent_record_types": [type(row).__name__ for row in self.parent_records],
            "offline_inputs": [row.as_dict() for row in self.offline_inputs],
            "retained_source_record_ids": list(self.retained_source_record_ids),
            "missing_required_inputs": list(self.missing_required_inputs),
            "runnable": self.runnable,
        }


def build_retained_first_four_evaluator_plan(
    value: CandidateEventInput,
) -> RetainedFirstFourEvaluatorPlan:
    """Bind one isolated retained session to its canonical evaluator inputs."""
    if not isinstance(value, CandidateEventInput):
        raise RecordError("evaluator plan input must be CandidateEventInput")
    if value.playbook not in EVALUATORS:
        raise RecordError("evaluator plan supports exactly the frozen first four playbooks")

    if value.playbook in ("CRVOL_ORB5", "HOD_COMP_RS"):
        request = build_retained_first_two_request(value)
        steps = request.steps
        parents: tuple[object, ...] = ()
    else:
        request = build_retained_remaining_request(value)
        steps = request.reversal_steps if value.playbook == "OR_FAILURE_REV" else request.pullback_steps
        parents = request.handoff_requests if value.playbook == "OR_FAILURE_REV" else ()

    missing = list(request.missing_required_inputs)
    if not value.trades:
        missing.append("RETAINED_TRADES_UNAVAILABLE")
    if not value.quotes:
        missing.append("RETAINED_QUOTES_UNAVAILABLE")
    return RetainedFirstFourEvaluatorPlan(
        RUN_VERSION,
        value.playbook,
        EVALUATORS[value.playbook],
        tuple(steps),
        tuple(parents),
        request.offline_inputs,
        request.retained_source_record_ids,
        tuple(dict.fromkeys(missing)),
    )


__all__ = [
    "EVALUATORS", "RUN_VERSION", "RetainedFirstFourEvaluatorPlan",
    "build_retained_first_four_evaluator_plan",
]
