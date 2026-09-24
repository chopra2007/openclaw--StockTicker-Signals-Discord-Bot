"""M9.1EK closed held-out input for the frozen stage-3 winner.

This offline boundary accepts only the reproduced M9.1EJ stage-3 input and
binds already-resolved, fully costed events from the frozen D-107 held-out
eight.  It does not run the D-108 pass/fail evaluation or release a result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_stage3_input import (
    RUN_VERSION as STAGE3_INPUT_VERSION,
    RetainedStage3InputRun,
    bind_retained_stage3_input,
)
from .search_run_config import HELD_OUT_TICKERS
from .stage2_training_comparison import Stage2TrainingEvent
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EK_RETAINED_STAGE3_HELD_OUT_INPUT_V1"


def _event_dict(event: Stage2TrainingEvent) -> dict[str, object]:
    trade = event.trade
    return {
        "playbook": trade.playbook,
        "candidate_id": trade.candidate_id,
        "ticker": trade.ticker,
        "direction": trade.direction,
        "alerted_at": event.alerted_at.isoformat(),
        "closed_at": trade.closed_at.isoformat(),
        "resolved_r": trade.resolved_r,
        "cost_model_version": trade.cost_model_version,
        "costs_complete": trade.costs_complete,
        "tested_axes": list(trade.tested_axes),
        "input_record_ids": list(trade.input_record_ids),
    }


@dataclass(frozen=True)
class RetainedStage3HeldOutInputRun:
    version: str
    source_version: str
    source_stage3: RetainedStage3InputRun
    selected_candidate_id: str
    selected_playbooks: tuple[str, ...]
    held_out_events: tuple[Stage2TrainingEvent, ...]
    evaluated_tickers: tuple[str, ...] = HELD_OUT_TICKERS
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    input_complete: bool = True
    held_out_bound: bool = True
    d108_evaluation_run: bool = False
    result_shard_released: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source_version": self.source_version,
            "source_stage3": self.source_stage3.as_dict(),
            "selected_candidate_id": self.selected_candidate_id,
            "selected_playbooks": list(self.selected_playbooks),
            "held_out_events": [_event_dict(event) for event in self.held_out_events],
            "evaluated_tickers": list(self.evaluated_tickers),
            "disabled_rules": list(self.disabled_rules),
            "input_complete": self.input_complete,
            "held_out_bound": self.held_out_bound,
            "d108_evaluation_run": self.d108_evaluation_run,
            "result_shard_released": self.result_shard_released,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def bind_retained_stage3_held_out_inputs(
    source: RetainedStage3InputRun,
    *,
    events: Sequence[Stage2TrainingEvent],
    evaluated_tickers: tuple[str, ...],
) -> RetainedStage3HeldOutInputRun:
    """Bind the frozen winner's held-out events without evaluating D-108."""
    if (type(source) is not RetainedStage3InputRun
            or source.version != STAGE3_INPUT_VERSION
            or source.disabled_rules != REQUIRED_DISABLED_RULES
            or source.input_complete is not True
            or any((source.held_out_opened, source.d108_evaluation_run,
                    source.result_shard_released, source.alert_released,
                    source.live_action))):
        raise RecordError("held-out binding requires the accepted closed M9.1EJ input")

    rebuilt = bind_retained_stage3_input(source.source_training)
    if rebuilt != source:
        raise RecordError("stage-3 input does not reproduce from its full training evidence")
    if evaluated_tickers != HELD_OUT_TICKERS:
        raise RecordError("stage 3 must evaluate exactly the frozen held-out eight")

    selected = source.selected_winner
    selected_playbooks = tuple(dict(selected.candidate.settings)["playbooks"])
    stage1_winners = {
        winner.playbook: winner
        for winner in source.source_training.source_input.winners
    }
    bound = tuple(events)
    if not bound or any(type(event) is not Stage2TrainingEvent for event in bound):
        raise RecordError("stage 3 needs strict fully costed held-out events")

    clusters = set()
    for event in bound:
        trade = event.trade
        winner = stage1_winners.get(trade.playbook)
        expected_candidate = (
            winner.measurement.measurement.candidate if winner is not None else None
        )
        if (trade.playbook not in selected_playbooks
                or expected_candidate is None
                or trade.candidate_id != expected_candidate.candidate_id
                or trade.ticker not in HELD_OUT_TICKERS
                or not trade.costs_complete
                or trade.tested_axes != tuple(
                    axis for axis, _value in expected_candidate.settings
                )
                or not trade.input_record_ids
                or event.alerted_at.date() != trade.closed_at.date()):
            raise RecordError("held-out event does not match the frozen stage-3 winner")
        if trade.cluster_key in clusters:
            raise RecordError("stage 3 allows one event per ticker-day-side")
        clusters.add(trade.cluster_key)

    return RetainedStage3HeldOutInputRun(
        RUN_VERSION,
        source.version,
        source,
        selected.candidate.candidate_id,
        selected_playbooks,
        bound,
        evaluated_tickers,
        source.disabled_rules,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage3HeldOutInputRun",
    "bind_retained_stage3_held_out_inputs",
]
