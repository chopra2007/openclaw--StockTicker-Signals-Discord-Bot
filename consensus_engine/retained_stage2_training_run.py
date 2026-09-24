"""M9.1EI retained five-candidate stage-2 training comparison.

This offline boundary accepts only the closed M9.1EH winner input, reproduces
that input from its complete stage-1 catalog and events, then runs the frozen
five-candidate training comparison.  It does not open held-out names or
release a result shard, alert, or live action.
"""

from __future__ import annotations

from dataclasses import dataclass

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS
from .retained_stage2_input import (
    RUN_VERSION as INPUT_VERSION,
    RetainedStage2InputRun,
    bind_retained_stage2_inputs,
)
from .search_run_config import STAGE2_CANDIDATES
from .stage2_training_comparison import (
    COMPARISON_VERSION,
    Stage2CandidateMeasurement,
    Stage2TrainingComparison,
    compare_stage2_training,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EI_RETAINED_STAGE2_TRAINING_V1"


def _measurement_dict(row: Stage2CandidateMeasurement) -> dict[str, object]:
    measured = row.measurement
    return {
        "candidate_id": row.candidate.candidate_id,
        "playbooks": list(dict(row.candidate.settings)["playbooks"]),
        "mean_profit_r": measured.mean_profit_r,
        "weekly_win_rate": measured.weekly_win_rate,
        "drawdown_recovery_weeks": measured.drawdown_recovery_weeks,
        "bootstrap_lower_bound": row.bootstrap_lower_bound,
        "trade_count": row.trade_count,
        "week_count": row.week_count,
        "disabled_rules_by_playbook": [
            {"playbook": playbook, "rules": list(rules)}
            for playbook, rules in row.disabled_rules_by_playbook
        ],
        "events": [
            {
                "playbook": event.trade.playbook,
                "ticker": event.trade.ticker,
                "direction": event.trade.direction,
                "alerted_at": event.alerted_at.isoformat(),
                "closed_at": event.trade.closed_at.isoformat(),
                "input_record_ids": list(event.trade.input_record_ids),
            }
            for event in row.events
        ],
    }


@dataclass(frozen=True)
class RetainedStage2TrainingRun:
    version: str
    input_version: str
    comparison_version: str
    source_input: RetainedStage2InputRun
    comparison: Stage2TrainingComparison
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    comparison_complete: bool = True
    held_out_opened: bool = False
    result_shard_released: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "input_version": self.input_version,
            "comparison_version": self.comparison_version,
            "source_input": self.source_input.as_dict(),
            "measured": [_measurement_dict(row) for row in self.comparison.measured],
            "ranked_candidate_ids": [
                row.candidate.candidate_id for row in self.comparison.ranked
            ],
            "winner_candidate_id": self.comparison.winner.candidate.candidate_id,
            "disabled_rules": list(self.disabled_rules),
            "comparison_complete": self.comparison_complete,
            "held_out_opened": self.held_out_opened,
            "result_shard_released": self.result_shard_released,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def run_retained_stage2_training(
    source: RetainedStage2InputRun,
) -> RetainedStage2TrainingRun:
    """Reproduce the closed retained input and rank its five candidates."""
    if (type(source) is not RetainedStage2InputRun
            or source.version != INPUT_VERSION
            or source.disabled_rules != REQUIRED_DISABLED_RULES
            or source.input_complete is not True
            or any((source.stage2_ranking_released, source.result_shard_released,
                    source.held_out_opened, source.alert_released, source.live_action))
            or type(source.winners) is not tuple
            or tuple(winner.playbook for winner in source.winners) != PLAYBOOKS):
        raise RecordError("stage-2 training requires the accepted closed M9.1EH input")

    rebuilt = bind_retained_stage2_inputs(
        source.source_ranking,
        events_by_playbook={winner.playbook: winner.events for winner in source.winners},
    )
    if rebuilt != source:
        raise RecordError("stage-2 input does not reproduce from its full catalog and events")

    comparison = compare_stage2_training(source.winners)
    if (comparison.version != COMPARISON_VERSION
            or comparison.status != "RANKED"
            or comparison.blockers
            or tuple(row.candidate for row in comparison.measured) != STAGE2_CANDIDATES
            or comparison.winner is None):
        raise RecordError("frozen five-candidate stage-2 comparison is incomplete")
    return RetainedStage2TrainingRun(
        RUN_VERSION,
        source.version,
        comparison.version,
        source,
        comparison,
        source.disabled_rules,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage2TrainingRun", "run_retained_stage2_training",
]
