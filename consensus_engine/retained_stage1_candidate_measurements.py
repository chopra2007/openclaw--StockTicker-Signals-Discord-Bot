"""M9.1EE strict measurement of complete retained candidate groups.

Only non-empty M9.1ED groups with exact frozen training coverage may reach the
existing stage-1 measurement function.  Exclusions and source-gap OFF labels
remain visible.  This boundary does not rank candidates, open held-out names,
release a result shard, send an alert, or perform a live action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS
from .retained_stage1_candidate_groups import (
    RUN_VERSION as GROUP_VERSION,
    RetainedStage1CandidateGroup,
    RetainedStage1CandidateGroupRun,
    SessionKey,
)
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import (
    POLICY_VERSION as MEASUREMENT_VERSION,
    Stage1TrainingMeasurement,
    measure_stage1_candidate,
)
from .trade_alerts_models import RecordError

RUN_VERSION = "M91EE_RETAINED_STAGE1_CANDIDATE_MEASUREMENTS_V1"


@dataclass(frozen=True)
class RetainedStage1CandidateMeasurementRun:
    version: str
    group_version: str
    measurement_version: str
    measurements: tuple[Stage1TrainingMeasurement, ...]
    training_sessions: tuple[SessionKey, ...]
    outcome_count: int
    resolved_outcome_count: int
    fully_costed_count: int
    unresolved_excluded_count: int
    incomplete_cost_excluded_count: int
    unfilled_excluded_count: int
    no_event_excluded_count: int
    unavailable_excluded_count: int
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES
    ranking_released: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "group_version": self.group_version,
            "measurement_version": self.measurement_version,
            "measurements": [
                {
                    "playbook": row.playbook,
                    "candidate_id": row.measurement.candidate.candidate_id,
                    "mean_profit_r": row.measurement.mean_profit_r,
                    "weekly_win_rate": row.measurement.weekly_win_rate,
                    "drawdown_recovery_weeks": row.measurement.drawdown_recovery_weeks,
                    "bootstrap_lower_bound": row.bootstrap_lower_bound,
                    "trade_count": row.trade_count,
                    "week_count": row.week_count,
                    "evaluated_tickers": list(row.evaluated_tickers),
                    "disabled_rules": list(row.disabled_rules),
                }
                for row in self.measurements
            ],
            "training_sessions": [
                {"ticker": ticker, "session": session}
                for ticker, session in self.training_sessions
            ],
            "outcome_count": self.outcome_count,
            "resolved_outcome_count": self.resolved_outcome_count,
            "fully_costed_count": self.fully_costed_count,
            "unresolved_excluded_count": self.unresolved_excluded_count,
            "incomplete_cost_excluded_count": self.incomplete_cost_excluded_count,
            "unfilled_excluded_count": self.unfilled_excluded_count,
            "no_event_excluded_count": self.no_event_excluded_count,
            "unavailable_excluded_count": self.unavailable_excluded_count,
            "disabled_rules": list(self.disabled_rules),
            "ranking_released": self.ranking_released,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _validate_groups(
    run: RetainedStage1CandidateGroupRun,
    candidates: Mapping[str, Candidate],
) -> None:
    if type(run) is not RetainedStage1CandidateGroupRun or run.version != GROUP_VERSION:
        raise RecordError("measurement requires the accepted candidate-group run")
    if (not run.coverage_complete or run.measurement_released
            or any((run.ranking_released, run.result_shard_released,
                    run.held_out_opened, run.alert_released, run.live_action))):
        raise RecordError("candidate groups opened or failed an earlier boundary")
    if run.disabled_rules != REQUIRED_DISABLED_RULES:
        raise RecordError("source-gap dependent rules must remain OFF and untested")
    counts = (
        run.outcome_count, run.resolved_outcome_count, run.fully_costed_count,
        run.unresolved_excluded_count, run.incomplete_cost_excluded_count,
        run.unfilled_excluded_count, run.no_event_excluded_count,
        run.unavailable_excluded_count,
    )
    if any(type(group) is not RetainedStage1CandidateGroup for group in run.groups):
        raise RecordError("measurement requires strict candidate groups")
    if (any(type(value) is not int or value < 0 for value in counts)
            or run.outcome_count != run.resolved_outcome_count + run.unresolved_excluded_count
            or run.resolved_outcome_count
            != run.fully_costed_count + run.incomplete_cost_excluded_count
            or run.fully_costed_count != sum(len(group.rows) for group in run.groups)):
        raise RecordError("candidate-group counts do not match")
    if not isinstance(candidates, Mapping) or tuple(candidates) != PLAYBOOKS:
        raise RecordError("measurements must name the first four in order")
    if len(run.groups) != len(PLAYBOOKS):
        raise RecordError("measurement requires one complete group per first-four playbook")
    expected = []
    for playbook, candidate in candidates.items():
        if type(candidate) is not Candidate or candidate not in STAGE1_CANDIDATES[playbook]:
            raise RecordError("measurement candidate is outside the frozen catalog")
        expected.append((playbook, candidate.candidate_id))
    if tuple((group.playbook, group.candidate_id) for group in run.groups) != tuple(expected):
        raise RecordError("candidate groups do not match the frozen measurement candidates")
    plan = run.training_sessions
    if (not plan or len(set(plan)) != len(plan)
            or any(type(item) is not tuple or len(item) != 2
                   or item[0] not in TRAINING_TICKERS
                   or not isinstance(item[1], str) or not item[1]
                   for item in plan)):
        raise RecordError("measurement requires unique frozen training sessions")
    try:
        for _ticker, session in plan:
            date.fromisoformat(session)
    except (TypeError, ValueError) as exc:
        raise RecordError("measurement sessions must use ISO dates") from exc
    if plan != tuple(sorted(
            plan, key=lambda item: (TRAINING_TICKERS.index(item[0]), item[1]))):
        raise RecordError("measurement sessions must keep frozen ticker and date order")
    if any(group.sessions != run.training_sessions for group in run.groups):
        raise RecordError("candidate groups must preserve one exact training-session plan")
    if tuple(dict.fromkeys(ticker for ticker, _session in run.training_sessions)) != TRAINING_TICKERS:
        raise RecordError("measurement coverage must preserve all nine training names in order")
    if any(not group.rows for group in run.groups):
        raise RecordError("empty candidate groups cannot be measured")
    plan_set = set(plan)
    if any((row.ticker, row.closed_at.date().isoformat()) not in plan_set
           for group in run.groups for row in group.rows):
        raise RecordError("measurement row is outside the complete training-session plan")


def measure_retained_stage1_groups(
    run: RetainedStage1CandidateGroupRun,
    *,
    candidates: Mapping[str, Candidate],
) -> RetainedStage1CandidateMeasurementRun:
    """Measure every complete group without ranking or releasing results."""
    _validate_groups(run, candidates)
    measurements = tuple(
        measure_stage1_candidate(
            playbook=group.playbook,
            candidate=candidates[group.playbook],
            trades=group.rows,
            evaluated_tickers=TRAINING_TICKERS,
            disabled_rules=run.disabled_rules,
        )
        for group in run.groups
    )
    return RetainedStage1CandidateMeasurementRun(
        RUN_VERSION,
        run.version,
        MEASUREMENT_VERSION,
        measurements,
        run.training_sessions,
        run.outcome_count,
        run.resolved_outcome_count,
        run.fully_costed_count,
        run.unresolved_excluded_count,
        run.incomplete_cost_excluded_count,
        run.unfilled_excluded_count,
        run.no_event_excluded_count,
        run.unavailable_excluded_count,
    )


__all__ = [
    "RUN_VERSION", "RetainedStage1CandidateMeasurementRun",
    "measure_retained_stage1_groups",
]
