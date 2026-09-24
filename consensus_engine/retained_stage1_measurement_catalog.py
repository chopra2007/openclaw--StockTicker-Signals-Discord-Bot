"""M9.1EF complete retained stage-1 measurement catalog.

This boundary accepts one M9.1EE measurement run for every frozen candidate,
requires the exact 18/4/2/4 catalog and one shared training-session plan, and
keeps the measurements in preregistered order.  It does not rank candidates,
open held-out names, release a result shard, send an alert, or act live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Mapping

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS
from .retained_stage1_candidate_groups import (
    RUN_VERSION as GROUP_VERSION,
    SessionKey,
)
from .retained_stage1_candidate_measurements import (
    RUN_VERSION as MEASUREMENT_RUN_VERSION,
    RetainedStage1CandidateMeasurementRun,
)
from .search_run_config import (
    STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate, TrainingMeasurement,
)
from .stage1_training_measurement import (
    POLICY_VERSION as MEASUREMENT_VERSION,
    Stage1TrainingMeasurement,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EF_RETAINED_STAGE1_MEASUREMENT_CATALOG_V1"
CandidateKey = tuple[str, str]


@dataclass(frozen=True)
class RetainedStage1CatalogEntry:
    playbook: str
    candidate_id: str
    measurement: Stage1TrainingMeasurement
    outcome_count: int
    resolved_outcome_count: int
    fully_costed_count: int
    unresolved_excluded_count: int
    incomplete_cost_excluded_count: int
    unfilled_excluded_count: int
    no_event_excluded_count: int
    unavailable_excluded_count: int

    def as_dict(self) -> dict[str, object]:
        row = self.measurement
        return {
            "playbook": self.playbook,
            "candidate_id": self.candidate_id,
            "measurement": {
                "mean_profit_r": row.measurement.mean_profit_r,
                "weekly_win_rate": row.measurement.weekly_win_rate,
                "drawdown_recovery_weeks": row.measurement.drawdown_recovery_weeks,
                "bootstrap_lower_bound": row.bootstrap_lower_bound,
                "trade_count": row.trade_count,
                "week_count": row.week_count,
                "evaluated_tickers": list(row.evaluated_tickers),
                "disabled_rules": list(row.disabled_rules),
            },
            "outcome_count": self.outcome_count,
            "resolved_outcome_count": self.resolved_outcome_count,
            "fully_costed_count": self.fully_costed_count,
            "unresolved_excluded_count": self.unresolved_excluded_count,
            "incomplete_cost_excluded_count": self.incomplete_cost_excluded_count,
            "unfilled_excluded_count": self.unfilled_excluded_count,
            "no_event_excluded_count": self.no_event_excluded_count,
            "unavailable_excluded_count": self.unavailable_excluded_count,
        }


@dataclass(frozen=True)
class RetainedStage1PlaybookCatalog:
    playbook: str
    entries: tuple[RetainedStage1CatalogEntry, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "playbook": self.playbook,
            "entries": [entry.as_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class RetainedStage1MeasurementCatalogRun:
    version: str
    measurement_run_version: str
    measurement_version: str
    playbooks: tuple[RetainedStage1PlaybookCatalog, ...]
    training_sessions: tuple[SessionKey, ...]
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    catalog_complete: bool = True
    ranking_released: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "measurement_run_version": self.measurement_run_version,
            "measurement_version": self.measurement_version,
            "playbooks": [row.as_dict() for row in self.playbooks],
            "training_sessions": [
                {"ticker": ticker, "session": session}
                for ticker, session in self.training_sessions
            ],
            "disabled_rules": list(self.disabled_rules),
            "catalog_complete": self.catalog_complete,
            "ranking_released": self.ranking_released,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _catalog_keys() -> tuple[CandidateKey, ...]:
    return tuple(
        (playbook, candidate.candidate_id)
        for playbook in PLAYBOOKS
        for candidate in STAGE1_CANDIDATES[playbook]
    )


def _validate_sessions(plan: tuple[SessionKey, ...]) -> None:
    if (not plan or len(set(plan)) != len(plan)
            or any(type(item) is not tuple or len(item) != 2
                   or item[0] not in TRAINING_TICKERS
                   or not isinstance(item[1], str) or not item[1]
                   for item in plan)):
        raise RecordError("catalog requires unique frozen training sessions")
    try:
        for _ticker, session in plan:
            date.fromisoformat(session)
    except ValueError as exc:
        raise RecordError("catalog sessions must use ISO dates") from exc
    if plan != tuple(sorted(
            plan, key=lambda item: (TRAINING_TICKERS.index(item[0]), item[1]))):
        raise RecordError("catalog sessions must keep frozen ticker and date order")
    if tuple(dict.fromkeys(ticker for ticker, _session in plan)) != TRAINING_TICKERS:
        raise RecordError("catalog coverage must preserve all nine training names in order")


def _validate_source(run: RetainedStage1CandidateMeasurementRun) -> None:
    if (type(run) is not RetainedStage1CandidateMeasurementRun
            or run.version != MEASUREMENT_RUN_VERSION
            or run.group_version != GROUP_VERSION
            or run.measurement_version != MEASUREMENT_VERSION):
        raise RecordError("catalog requires accepted M9.1EE measurement runs")
    if (run.disabled_rules != REQUIRED_DISABLED_RULES
            or any((run.ranking_released, run.result_shard_released,
                    run.held_out_opened, run.alert_released, run.live_action))):
        raise RecordError("source-gap rules or release boundaries changed")
    counts = (
        run.outcome_count, run.resolved_outcome_count, run.fully_costed_count,
        run.unresolved_excluded_count, run.incomplete_cost_excluded_count,
        run.unfilled_excluded_count, run.no_event_excluded_count,
        run.unavailable_excluded_count,
    )
    if (any(type(value) is not int or value < 0 for value in counts)
            or run.outcome_count != run.resolved_outcome_count + run.unresolved_excluded_count
            or run.resolved_outcome_count
            != run.fully_costed_count + run.incomplete_cost_excluded_count):
        raise RecordError("measurement-run counts do not match")
    _validate_sessions(run.training_sessions)
    if (type(run.measurements) is not tuple
            or len(run.measurements) != len(PLAYBOOKS)):
        raise RecordError("measurement run must keep one first-four row in order")
    for playbook, row in zip(PLAYBOOKS, run.measurements):
        if (type(row) is not Stage1TrainingMeasurement
                or row.policy_version != MEASUREMENT_VERSION
                or row.playbook != playbook
                or type(row.measurement) is not TrainingMeasurement
                or type(row.measurement.candidate) is not Candidate
                or row.measurement.candidate not in STAGE1_CANDIDATES[playbook]
                or row.evaluated_tickers != TRAINING_TICKERS
                or row.disabled_rules != REQUIRED_DISABLED_RULES
                or type(row.trade_count) is not int or row.trade_count <= 0
                or type(row.week_count) is not int
                or not 0 < row.week_count <= row.trade_count):
            raise RecordError("measurement row is outside the complete frozen boundary")
        values = (row.measurement.mean_profit_r, row.measurement.weekly_win_rate,
                  row.bootstrap_lower_bound)
        if (any(type(value) not in (int, float) or not math.isfinite(value)
                for value in values)
                or not 0 <= row.measurement.weekly_win_rate <= 1):
            raise RecordError("measurement profit, win rate and bootstrap bound must be valid finite numbers")
        recovery = row.measurement.drawdown_recovery_weeks
        # The producer uses positive infinity when recovery is unavailable.
        if (type(recovery) not in (int, float) or math.isnan(recovery)
                or recovery < 0):
            raise RecordError("measurement recovery must be nonnegative or positive infinity")
    if run.fully_costed_count != sum(row.trade_count for row in run.measurements):
        raise RecordError("fully costed count does not match measured trades")


def assemble_retained_stage1_measurement_catalog(
    runs: Mapping[CandidateKey, RetainedStage1CandidateMeasurementRun],
) -> RetainedStage1MeasurementCatalogRun:
    """Assemble the full frozen catalog without ranking or releasing it."""
    keys = _catalog_keys()
    if not isinstance(runs, Mapping) or tuple(runs) != keys:
        raise RecordError("catalog needs the exact frozen 18/4/2/4 candidate order")

    reference_sessions: tuple[SessionKey, ...] | None = None
    playbook_entries: dict[str, list[RetainedStage1CatalogEntry]] = {
        playbook: [] for playbook in PLAYBOOKS
    }
    for playbook, candidate_id in keys:
        run = runs[(playbook, candidate_id)]
        _validate_source(run)
        if reference_sessions is None:
            reference_sessions = run.training_sessions
        elif run.training_sessions != reference_sessions:
            raise RecordError("every frozen candidate needs exact matching training coverage")
        measurement = next(row for row in run.measurements if row.playbook == playbook)
        if measurement.measurement.candidate.candidate_id != candidate_id:
            raise RecordError("catalog key does not match its measured frozen candidate")
        playbook_entries[playbook].append(RetainedStage1CatalogEntry(
            playbook, candidate_id, measurement,
            run.outcome_count, run.resolved_outcome_count, run.fully_costed_count,
            run.unresolved_excluded_count, run.incomplete_cost_excluded_count,
            run.unfilled_excluded_count, run.no_event_excluded_count,
            run.unavailable_excluded_count,
        ))

    assert reference_sessions is not None
    catalog = tuple(
        RetainedStage1PlaybookCatalog(playbook, tuple(playbook_entries[playbook]))
        for playbook in PLAYBOOKS
    )
    return RetainedStage1MeasurementCatalogRun(
        RUN_VERSION, MEASUREMENT_RUN_VERSION, MEASUREMENT_VERSION,
        catalog, reference_sessions,
    )


__all__ = [
    "RUN_VERSION", "CandidateKey", "RetainedStage1CatalogEntry",
    "RetainedStage1PlaybookCatalog", "RetainedStage1MeasurementCatalogRun",
    "assemble_retained_stage1_measurement_catalog",
]
