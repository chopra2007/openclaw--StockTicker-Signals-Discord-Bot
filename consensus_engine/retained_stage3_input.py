"""M9.1EJ closed stage-3 input from the retained stage-2 winner.

This offline boundary accepts only the reproduced M9.1EI training comparison
and binds its frozen winner to the next boundary.  It preserves the complete
stage-1 and stage-2 evidence without opening held-out names or running D-108.
"""

from __future__ import annotations

from dataclasses import dataclass

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_stage2_training_run import (
    RUN_VERSION as TRAINING_VERSION,
    RetainedStage2TrainingRun,
    run_retained_stage2_training,
)
from .stage2_training_comparison import Stage2CandidateMeasurement
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EJ_RETAINED_STAGE3_INPUT_V1"


@dataclass(frozen=True)
class RetainedStage3InputRun:
    version: str
    training_version: str
    source_training: RetainedStage2TrainingRun
    selected_winner: Stage2CandidateMeasurement
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    input_complete: bool = True
    held_out_opened: bool = False
    d108_evaluation_run: bool = False
    result_shard_released: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        winner = self.selected_winner
        return {
            "version": self.version,
            "training_version": self.training_version,
            "source_training": self.source_training.as_dict(),
            "selected_winner": {
                "candidate_id": winner.candidate.candidate_id,
                "playbooks": list(dict(winner.candidate.settings)["playbooks"]),
                "mean_profit_r": winner.measurement.mean_profit_r,
                "weekly_win_rate": winner.measurement.weekly_win_rate,
                "drawdown_recovery_weeks": winner.measurement.drawdown_recovery_weeks,
                "bootstrap_lower_bound": winner.bootstrap_lower_bound,
                "trade_count": winner.trade_count,
                "week_count": winner.week_count,
                "event_input_record_ids": [
                    list(event.trade.input_record_ids) for event in winner.events
                ],
            },
            "disabled_rules": list(self.disabled_rules),
            "input_complete": self.input_complete,
            "held_out_opened": self.held_out_opened,
            "d108_evaluation_run": self.d108_evaluation_run,
            "result_shard_released": self.result_shard_released,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def bind_retained_stage3_input(
    source: RetainedStage2TrainingRun,
) -> RetainedStage3InputRun:
    """Bind the reproduced stage-2 winner without reading held-out data."""
    if (type(source) is not RetainedStage2TrainingRun
            or source.version != TRAINING_VERSION
            or source.disabled_rules != REQUIRED_DISABLED_RULES
            or source.comparison_complete is not True
            or any((source.held_out_opened, source.result_shard_released,
                    source.alert_released, source.live_action))):
        raise RecordError("stage-3 input requires the accepted closed M9.1EI training run")

    rebuilt = run_retained_stage2_training(source.source_input)
    if rebuilt != source:
        raise RecordError("stage-2 training evidence does not reproduce from its full input")
    winner = rebuilt.comparison.winner
    if winner is None or winner not in rebuilt.comparison.measured:
        raise RecordError("stage-2 training winner is missing from the frozen comparison")

    return RetainedStage3InputRun(
        RUN_VERSION,
        source.version,
        source,
        winner,
        source.disabled_rules,
    )


__all__ = ["RUN_VERSION", "RetainedStage3InputRun", "bind_retained_stage3_input"]
