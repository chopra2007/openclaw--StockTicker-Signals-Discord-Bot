"""M9.1EG frozen per-playbook ranking for the retained stage-1 catalog.

This offline boundary ranks every complete first-four playbook catalog with the
preregistered training rule.  It preserves the full input catalog and keeps the
held-out set, result shard, alerts, and live action closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS
from .retained_stage1_measurement_catalog import (
    RUN_VERSION as CATALOG_VERSION,
    RetainedStage1CatalogEntry,
    RetainedStage1MeasurementCatalogRun,
    RetainedStage1PlaybookCatalog,
)
from .retained_stage1_candidate_measurements import RUN_VERSION as MEASUREMENT_RUN_VERSION
from .search_run_config import (
    STAGE1_CANDIDATES,
    TRAINING_TICKERS,
    Candidate,
    TrainingMeasurement,
    rank_training_candidates,
)
from .stage1_training_measurement import (
    POLICY_VERSION as MEASUREMENT_VERSION,
    Stage1TrainingMeasurement,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EG_RETAINED_STAGE1_RANKING_V1"


@dataclass(frozen=True)
class RetainedStage1PlaybookRanking:
    playbook: str
    winner_candidate_id: str
    winner: Stage1TrainingMeasurement
    entries: tuple[RetainedStage1CatalogEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "playbook": self.playbook,
            "winner_candidate_id": self.winner_candidate_id,
            "winner": self.winner.measurement.candidate.candidate_id,
            "entries": [entry.as_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class RetainedStage1RankingRun:
    version: str
    catalog_version: str
    rankings: tuple[RetainedStage1PlaybookRanking, ...]
    training_sessions: tuple[tuple[str, str], ...]
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    ranking_complete: bool = True
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "catalog_version": self.catalog_version,
            "rankings": [ranking.as_dict() for ranking in self.rankings],
            "training_sessions": [
                {"ticker": ticker, "session": session}
                for ticker, session in self.training_sessions
            ],
            "disabled_rules": list(self.disabled_rules),
            "ranking_complete": self.ranking_complete,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _validate_sessions(sessions: tuple[tuple[str, str], ...]) -> None:
    if (type(sessions) is not tuple or not sessions or len(set(sessions)) != len(sessions)
            or any(type(item) is not tuple or len(item) != 2
                   or item[0] not in TRAINING_TICKERS
                   or not isinstance(item[1], str) or not item[1]
                   for item in sessions)):
        raise RecordError("ranking requires unique frozen training sessions")
    try:
        for _ticker, session in sessions:
            date.fromisoformat(session)
    except ValueError as exc:
        raise RecordError("ranking sessions must use ISO dates") from exc
    expected = tuple(sorted(
        sessions, key=lambda item: (TRAINING_TICKERS.index(item[0]), item[1])))
    if sessions != expected or tuple(dict.fromkeys(row[0] for row in sessions)) != TRAINING_TICKERS:
        raise RecordError("ranking must preserve all nine training names in frozen order")


def _validate_entry(
    entry: RetainedStage1CatalogEntry,
    playbook: str,
    candidate: Candidate,
) -> None:
    if (type(entry) is not RetainedStage1CatalogEntry
            or entry.playbook != playbook
            or entry.candidate_id != candidate.candidate_id
            or type(entry.measurement) is not Stage1TrainingMeasurement):
        raise RecordError("ranking catalog entry identity changed")
    row = entry.measurement
    if (row.policy_version != MEASUREMENT_VERSION
            or row.playbook != playbook
            or type(row.measurement) is not TrainingMeasurement
            or type(row.measurement.candidate) is not Candidate
            or row.measurement.candidate != candidate
            or row.evaluated_tickers != TRAINING_TICKERS
            or row.disabled_rules != REQUIRED_DISABLED_RULES
            or type(row.trade_count) is not int or row.trade_count <= 0
            or type(row.week_count) is not int
            or not 0 < row.week_count <= row.trade_count):
        raise RecordError("ranking requires complete frozen measurements")
    values = (
        row.measurement.mean_profit_r,
        row.measurement.weekly_win_rate,
        row.bootstrap_lower_bound,
    )
    if (any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
            or not 0 <= row.measurement.weekly_win_rate <= 1):
        raise RecordError("ranking measurement values are invalid")
    recovery = row.measurement.drawdown_recovery_weeks
    if (type(recovery) not in (int, float) or math.isnan(recovery) or recovery < 0):
        raise RecordError("ranking recovery must be nonnegative or positive infinity")
    counts = (
        entry.outcome_count,
        entry.resolved_outcome_count,
        entry.fully_costed_count,
        entry.unresolved_excluded_count,
        entry.incomplete_cost_excluded_count,
        entry.unfilled_excluded_count,
        entry.no_event_excluded_count,
        entry.unavailable_excluded_count,
    )
    if (any(type(value) is not int or value < 0 for value in counts)
            or entry.outcome_count != entry.resolved_outcome_count + entry.unresolved_excluded_count
            or entry.resolved_outcome_count
            != entry.fully_costed_count + entry.incomplete_cost_excluded_count
            # Catalog counts cover the entire source run, while this row covers
            # one playbook; each of the other playbooks had a nonempty row.
            or entry.fully_costed_count < row.trade_count + len(PLAYBOOKS) - 1):
        raise RecordError("ranking catalog exclusion counts do not match")


def rank_retained_stage1_catalog(
    catalog: RetainedStage1MeasurementCatalogRun,
) -> RetainedStage1RankingRun:
    """Rank each complete playbook catalog without opening any later boundary."""
    if (type(catalog) is not RetainedStage1MeasurementCatalogRun
            or catalog.version != CATALOG_VERSION
            or catalog.measurement_run_version != MEASUREMENT_RUN_VERSION
            or catalog.measurement_version != MEASUREMENT_VERSION
            or catalog.disabled_rules != REQUIRED_DISABLED_RULES
            or catalog.catalog_complete is not True
            or any(flag is not False for flag in (
                catalog.ranking_released, catalog.result_shard_released,
                catalog.held_out_opened, catalog.alert_released, catalog.live_action,
            ))
            or type(catalog.playbooks) is not tuple
            or len(catalog.playbooks) != len(PLAYBOOKS)):
        raise RecordError("ranking requires the complete closed M9.1EF catalog")
    _validate_sessions(catalog.training_sessions)

    rankings = []
    for playbook, group in zip(PLAYBOOKS, catalog.playbooks):
        candidates = STAGE1_CANDIDATES[playbook]
        if (type(group) is not RetainedStage1PlaybookCatalog
                or group.playbook != playbook
                or type(group.entries) is not tuple
                or len(group.entries) != len(candidates)):
            raise RecordError("ranking requires the exact 18/4/2/4 playbook catalog")
        for entry, candidate in zip(group.entries, candidates):
            _validate_entry(entry, playbook, candidate)
        winning_measurement = rank_training_candidates(tuple(
            entry.measurement.measurement for entry in group.entries
        ))
        winning_entry = next(
            entry for entry in group.entries
            if entry.candidate_id == winning_measurement.candidate.candidate_id
        )
        rankings.append(RetainedStage1PlaybookRanking(
            playbook, winning_entry.candidate_id, winning_entry.measurement, group.entries,
        ))

    return RetainedStage1RankingRun(
        RUN_VERSION, CATALOG_VERSION, tuple(rankings),
        catalog.training_sessions, catalog.disabled_rules,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage1PlaybookRanking", "RetainedStage1RankingRun",
    "rank_retained_stage1_catalog",
]
