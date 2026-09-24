"""M9.1EL one-shot D-108 evaluation of the frozen retained held-out input.

This offline boundary reproduces the complete M9.1EK input before converting
its already-resolved, fully costed events to the frozen D-108 measurement.  It
does not release a result shard, send an alert, or act live.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .d108_evaluator import (
    POLICY_VERSION as D108_POLICY_VERSION,
    D108Evaluation,
    TradeResult,
    evaluate_d108,
)
from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_stage3_held_out_input import (
    RUN_VERSION as HELD_OUT_INPUT_VERSION,
    RetainedStage3HeldOutInputRun,
    bind_retained_stage3_held_out_inputs,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EL_RETAINED_STAGE3_D108_EVALUATION_V1"


@dataclass(frozen=True)
class RetainedStage3D108EvaluationRun:
    version: str
    input_version: str
    d108_policy_version: str
    source_held_out: RetainedStage3HeldOutInputRun
    evaluation: D108Evaluation
    frozen_input_sha256: str
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    evaluation_complete: bool = True
    d108_evaluation_run: bool = True
    result_shard_released: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "input_version": self.input_version,
            "d108_policy_version": self.d108_policy_version,
            "source_held_out": self.source_held_out.as_dict(),
            "evaluation": self.evaluation.as_dict(),
            "frozen_input_sha256": self.frozen_input_sha256,
            "disabled_rules": list(self.disabled_rules),
            "evaluation_complete": self.evaluation_complete,
            "d108_evaluation_run": self.d108_evaluation_run,
            "result_shard_released": self.result_shard_released,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def run_retained_stage3_d108_evaluation(
    source: RetainedStage3HeldOutInputRun,
    *,
    frozen_input_sha256: str,
) -> RetainedStage3D108EvaluationRun:
    """Check the independently frozen input fingerprint, then evaluate once.

    The caller must retain the SHA256 of the accepted M9.1EK ``as_dict()``
    before handing the input to this boundary: sorted, compact JSON with
    ensure_ascii=True and allow_nan=False, encoded as UTF-8. Computing that
    expected fingerprint from the input under evaluation defeats the check.
    This binds supplied evidence; it does not establish market-source truth.
    """
    if (type(source) is not RetainedStage3HeldOutInputRun
            or source.version != HELD_OUT_INPUT_VERSION
            or source.disabled_rules != REQUIRED_DISABLED_RULES
            or source.input_complete is not True
            or source.held_out_bound is not True
            or any((source.d108_evaluation_run, source.result_shard_released,
                    source.alert_released, source.live_action))):
        raise RecordError("D-108 requires the accepted closed M9.1EK held-out input")

    canonical = json.dumps(
        source.as_dict(), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")
    if (type(frozen_input_sha256) is not str
            or hashlib.sha256(canonical).hexdigest() != frozen_input_sha256):
        raise RecordError("held-out input differs from its independently frozen fingerprint")

    rebuilt = bind_retained_stage3_held_out_inputs(
        source.source_stage3,
        events=source.held_out_events,
        evaluated_tickers=source.evaluated_tickers,
    )
    if rebuilt != source:
        raise RecordError("held-out input does not reproduce from its full frozen evidence")

    rows = tuple(
        TradeResult(event.trade.resolved_r, event.trade.closed_at)
        for event in source.held_out_events
    )
    evaluation = evaluate_d108(source.selected_candidate_id, rows)
    if (evaluation.policy_version != D108_POLICY_VERSION
            or evaluation.candidate_id != source.selected_candidate_id
            or evaluation.trade_count != len(source.held_out_events)):
        raise RecordError("frozen D-108 evaluation is incomplete")

    return RetainedStage3D108EvaluationRun(
        RUN_VERSION,
        source.version,
        evaluation.policy_version,
        source,
        evaluation,
        frozen_input_sha256,
        source.disabled_rules,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage3D108EvaluationRun",
    "run_retained_stage3_d108_evaluation",
]
