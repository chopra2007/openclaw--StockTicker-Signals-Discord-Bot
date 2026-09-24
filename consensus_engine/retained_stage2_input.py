"""M9.1EH retained stage-1 winners at the stage-2 input boundary.

This offline boundary binds each accepted retained stage-1 winner to its exact
fully costed training events.  It preserves the complete ranking catalog and
does not rank stage 2, open held-out names, or release any result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS
from .retained_stage1_candidate_measurements import RUN_VERSION as MEASUREMENT_RUN_VERSION
from .retained_stage1_measurement_catalog import (
    RUN_VERSION as CATALOG_VERSION,
    RetainedStage1MeasurementCatalogRun,
    RetainedStage1PlaybookCatalog,
)
from .retained_stage1_ranking import (
    RUN_VERSION as RANKING_VERSION,
    RetainedStage1PlaybookRanking,
    RetainedStage1RankingRun,
    rank_retained_stage1_catalog,
)
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS
from .stage1_training_measurement import (
    POLICY_VERSION as MEASUREMENT_VERSION,
    measure_stage1_candidate,
)
from .stage2_training_comparison import AcceptedStage1Winner, Stage2TrainingEvent
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EH_RETAINED_STAGE2_INPUT_V1"


@dataclass(frozen=True)
class RetainedStage2InputRun:
    version: str
    ranking_version: str
    source_ranking: RetainedStage1RankingRun
    winners: tuple[AcceptedStage1Winner, ...]
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    input_complete: bool = True
    stage2_ranking_released: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "ranking_version": self.ranking_version,
            "source_ranking": self.source_ranking.as_dict(),
            "winners": [
                {
                    "playbook": winner.playbook,
                    "winner_candidate_id": winner.measurement.measurement.candidate.candidate_id,
                    "candidate_measurement_count": len(winner.candidate_measurements),
                    "events": [
                        {
                            "ticker": event.trade.ticker,
                            "direction": event.trade.direction,
                            "alerted_at": event.alerted_at.isoformat(),
                            "closed_at": event.trade.closed_at.isoformat(),
                            "resolved_r": event.trade.resolved_r,
                            "cost_model_version": event.trade.cost_model_version,
                            "costs_complete": event.trade.costs_complete,
                            "tested_axes": list(event.trade.tested_axes),
                            "input_record_ids": list(event.trade.input_record_ids),
                        }
                        for event in winner.events
                    ],
                }
                for winner in self.winners
            ],
            "disabled_rules": list(self.disabled_rules),
            "input_complete": self.input_complete,
            "stage2_ranking_released": self.stage2_ranking_released,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _validate_ranking(ranking: RetainedStage1RankingRun) -> None:
    if (type(ranking) is not RetainedStage1RankingRun
            or ranking.version != RANKING_VERSION
            or ranking.catalog_version != CATALOG_VERSION
            or ranking.disabled_rules != REQUIRED_DISABLED_RULES
            or ranking.ranking_complete is not True
            or any((ranking.result_shard_released, ranking.held_out_opened,
                    ranking.alert_released, ranking.live_action))
            or type(ranking.rankings) is not tuple
            or len(ranking.rankings) != len(PLAYBOOKS)):
        raise RecordError("stage-2 input requires the accepted closed M9.1EG ranking")
    catalog = RetainedStage1MeasurementCatalogRun(
        CATALOG_VERSION,
        MEASUREMENT_RUN_VERSION,
        MEASUREMENT_VERSION,
        tuple(
            RetainedStage1PlaybookCatalog(row.playbook, row.entries)
            for row in ranking.rankings
        ),
        ranking.training_sessions,
        ranking.disabled_rules,
    )
    if rank_retained_stage1_catalog(catalog) != ranking:
        raise RecordError("stage-2 input ranking does not reproduce from its full catalog")


def _bind_winner(
    ranking_row: RetainedStage1PlaybookRanking,
    supplied_events: Sequence[Stage2TrainingEvent],
    training_sessions: tuple[tuple[str, str], ...],
) -> AcceptedStage1Winner:
    playbook = ranking_row.playbook
    events = tuple(supplied_events)
    if not events or any(type(event) is not Stage2TrainingEvent for event in events):
        raise RecordError("each retained stage-1 winner needs strict training events")
    candidate = ranking_row.winner.measurement.candidate
    expected_axes = tuple(axis for axis, _value in candidate.settings)
    session_set = set(training_sessions)
    clusters = set()
    for event in events:
        trade = event.trade
        if (trade.playbook != playbook
                or trade.candidate_id != ranking_row.winner_candidate_id
                or trade.ticker not in TRAINING_TICKERS
                or (trade.ticker, trade.closed_at.date().isoformat()) not in session_set
                or event.alerted_at.date() != trade.closed_at.date()
                or not trade.costs_complete
                or trade.tested_axes != expected_axes
                or not trade.input_record_ids):
            raise RecordError("stage-2 event does not match its complete-cost retained winner")
        if trade.cluster_key in clusters:
            raise RecordError("a retained winner cannot repeat a ticker-day-side event")
        clusters.add(trade.cluster_key)
    measured = measure_stage1_candidate(
        playbook=playbook,
        candidate=candidate,
        trades=tuple(event.trade for event in events),
        evaluated_tickers=TRAINING_TICKERS,
        disabled_rules=REQUIRED_DISABLED_RULES,
    )
    if measured != ranking_row.winner:
        raise RecordError("retained winner events do not reproduce its frozen measurement")
    return AcceptedStage1Winner(
        playbook,
        ranking_row.winner,
        tuple(entry.measurement for entry in ranking_row.entries),
        events,
    )


def bind_retained_stage2_inputs(
    ranking: RetainedStage1RankingRun,
    *,
    events_by_playbook: Mapping[str, Sequence[Stage2TrainingEvent]],
) -> RetainedStage2InputRun:
    """Bind exact winner events without performing the stage-2 comparison."""
    _validate_ranking(ranking)
    if not isinstance(events_by_playbook, Mapping) or tuple(events_by_playbook) != PLAYBOOKS:
        raise RecordError("stage-2 input events must name the first four in frozen order")
    winners = tuple(
        _bind_winner(row, events_by_playbook[row.playbook], ranking.training_sessions)
        for row in ranking.rankings
    )
    return RetainedStage2InputRun(
        RUN_VERSION, ranking.version, ranking, winners, ranking.disabled_rules,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage2InputRun", "bind_retained_stage2_inputs",
]
