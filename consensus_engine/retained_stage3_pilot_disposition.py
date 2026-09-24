"""M9.1EN parent engineering-pilot disposition from the closed result shard.

This boundary records the exact offline D-108 result without treating it as
promotion, alert, or live evidence.  Every source-gap dependent rule stays off.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_stage3_result_shard import (
    RUN_VERSION as RESULT_SHARD_VERSION,
    RetainedStage3ResultShard,
    publish_retained_stage3_result_shard,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EN_RETAINED_STAGE3_PILOT_DISPOSITION_V1"
DISPOSITION = "ENGINEERING_PILOT_ONLY"


def _fingerprint(source: RetainedStage3ResultShard) -> str:
    canonical = json.dumps(
        source.as_dict(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class RetainedStage3PilotDisposition:
    version: str
    result_shard_version: str
    source_result_shard: RetainedStage3ResultShard
    frozen_result_shard_sha256: str
    selected_candidate_id: str
    d108_passed: bool
    disposition: str = DISPOSITION
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    gap_dependent_rules: str = "OFF_UNTESTED"
    engineering_pilot_complete: bool = True
    promotion_released: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "result_shard_version": self.result_shard_version,
            "source_result_shard": self.source_result_shard.as_dict(),
            "frozen_result_shard_sha256": self.frozen_result_shard_sha256,
            "selected_candidate_id": self.selected_candidate_id,
            "d108_passed": self.d108_passed,
            "disposition": self.disposition,
            "disabled_rules": list(self.disabled_rules),
            "gap_dependent_rules": self.gap_dependent_rules,
            "engineering_pilot_complete": self.engineering_pilot_complete,
            "promotion_released": self.promotion_released,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def publish_retained_stage3_pilot_disposition(
    source: RetainedStage3ResultShard,
    *,
    frozen_result_shard_sha256: str,
) -> RetainedStage3PilotDisposition:
    """Close the parent engineering pilot around the exact accepted shard."""
    if (type(source) is not RetainedStage3ResultShard
            or source.version != RESULT_SHARD_VERSION
            or source.disabled_rules != REQUIRED_DISABLED_RULES
            or source.offline_result_complete is not True
            or source.result_shard_released is not True
            or any((source.alert_released, source.live_action))):
        raise RecordError("pilot disposition requires the accepted closed M9.1EM shard")

    rebuilt = publish_retained_stage3_result_shard(
        source.source_evaluation,
        frozen_evaluation_sha256=source.frozen_evaluation_sha256,
    )
    if rebuilt != source:
        raise RecordError("result shard does not reproduce from its frozen evaluation")
    if (type(frozen_result_shard_sha256) is not str
            or _fingerprint(source) != frozen_result_shard_sha256):
        raise RecordError("result shard differs from its independently frozen fingerprint")

    return RetainedStage3PilotDisposition(
        RUN_VERSION,
        source.version,
        source,
        frozen_result_shard_sha256,
        source.selected_candidate_id,
        source.d108_passed,
        disabled_rules=source.disabled_rules,
    )


__all__ = [
    "DISPOSITION", "RUN_VERSION", "RetainedStage3PilotDisposition",
    "publish_retained_stage3_pilot_disposition",
]
