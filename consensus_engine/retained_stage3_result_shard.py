"""M9.1EM closed offline result shard for the frozen D-108 record.

This boundary publishes the already-complete M9.1EL record without rerunning
the evaluation.  The shard remains offline: alert and live release stay closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .d108_evaluator import POLICY_VERSION as D108_POLICY_VERSION
from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_stage3_d108_evaluation import (
    RUN_VERSION as D108_RUN_VERSION,
    RetainedStage3D108EvaluationRun,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EM_RETAINED_STAGE3_RESULT_SHARD_V1"


def _fingerprint(source: RetainedStage3D108EvaluationRun) -> str:
    canonical = json.dumps(
        source.as_dict(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class RetainedStage3ResultShard:
    version: str
    evaluation_version: str
    d108_policy_version: str
    source_evaluation: RetainedStage3D108EvaluationRun
    frozen_evaluation_sha256: str
    selected_candidate_id: str
    d108_passed: bool
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    offline_result_complete: bool = True
    result_shard_released: bool = True
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "evaluation_version": self.evaluation_version,
            "d108_policy_version": self.d108_policy_version,
            "source_evaluation": self.source_evaluation.as_dict(),
            "frozen_evaluation_sha256": self.frozen_evaluation_sha256,
            "selected_candidate_id": self.selected_candidate_id,
            "d108_passed": self.d108_passed,
            "disabled_rules": list(self.disabled_rules),
            "offline_result_complete": self.offline_result_complete,
            "result_shard_released": self.result_shard_released,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def publish_retained_stage3_result_shard(
    source: RetainedStage3D108EvaluationRun,
    *,
    frozen_evaluation_sha256: str,
) -> RetainedStage3ResultShard:
    """Publish only the independently frozen, closed M9.1EL result record."""
    if (type(source) is not RetainedStage3D108EvaluationRun
            or source.version != D108_RUN_VERSION
            or source.d108_policy_version != D108_POLICY_VERSION
            or source.disabled_rules != REQUIRED_DISABLED_RULES
            or source.evaluation_complete is not True
            or source.d108_evaluation_run is not True
            or any((source.result_shard_released, source.alert_released,
                    source.live_action))):
        raise RecordError("result shard requires the accepted closed M9.1EL record")

    evaluation = source.evaluation
    held_out = source.source_held_out
    if (evaluation.policy_version != D108_POLICY_VERSION
            or evaluation.candidate_id != held_out.selected_candidate_id
            or evaluation.trade_count != len(held_out.held_out_events)):
        raise RecordError("frozen D-108 result is incomplete")
    if (type(frozen_evaluation_sha256) is not str
            or _fingerprint(source) != frozen_evaluation_sha256):
        raise RecordError("D-108 record differs from its independently frozen fingerprint")

    return RetainedStage3ResultShard(
        RUN_VERSION,
        source.version,
        evaluation.policy_version,
        source,
        frozen_evaluation_sha256,
        evaluation.candidate_id,
        evaluation.passed,
        source.disabled_rules,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage3ResultShard",
    "publish_retained_stage3_result_shard",
]
