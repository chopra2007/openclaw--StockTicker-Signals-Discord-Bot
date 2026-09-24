"""M9.1ED strict grouping before retained stage-1 measurement.

Fully costed result rows are grouped by their frozen playbook candidate only
after the caller proves the exact retained training-session coverage for every
group.  Exclusion counts remain visible.  This boundary does not measure or
rank a candidate, release a result shard, inspect held-out names, send an alert,
or perform a live action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .orb5_stage1_result import REQUIRED_DISABLED_RULES
from .retained_decision_moments import PLAYBOOKS
from .retained_first_four_stage1_result import (
    RUN_VERSION as STAGE1_RESULT_VERSION,
    RetainedFirstFourStage1ResultRun,
)
from .search_run_config import STAGE1_CANDIDATES, TRAINING_TICKERS, Candidate
from .stage1_training_measurement import ResolvedTrainingTrade
from .trade_alerts_models import RecordError

RUN_VERSION = "M91ED_RETAINED_STAGE1_CANDIDATE_GROUPS_V1"
SessionKey = tuple[str, str]
CandidateKey = tuple[str, str]


@dataclass(frozen=True)
class RetainedStage1CandidateGroup:
    playbook: str
    candidate_id: str
    sessions: tuple[SessionKey, ...]
    rows: tuple[ResolvedTrainingTrade, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "playbook": self.playbook,
            "candidate_id": self.candidate_id,
            "sessions": [
                {"ticker": ticker, "session": session}
                for ticker, session in self.sessions
            ],
            "rows": [
                {
                    "ticker": row.ticker,
                    "direction": row.direction,
                    "closed_at": row.closed_at.isoformat(),
                    "resolved_r": row.resolved_r,
                    "cost_model_version": row.cost_model_version,
                    "costs_complete": row.costs_complete,
                    "tested_axes": list(row.tested_axes),
                    "input_record_ids": list(row.input_record_ids),
                }
                for row in self.rows
            ],
        }


@dataclass(frozen=True)
class RetainedStage1CandidateGroupRun:
    version: str
    stage1_result_version: str
    groups: tuple[RetainedStage1CandidateGroup, ...]
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
    coverage_complete: bool = True
    measurement_released: bool = False
    ranking_released: bool = False
    result_shard_released: bool = False
    held_out_opened: bool = False
    alert_released: bool = False
    live_action: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "stage1_result_version": self.stage1_result_version,
            "groups": [group.as_dict() for group in self.groups],
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
            "coverage_complete": self.coverage_complete,
            "measurement_released": self.measurement_released,
            "ranking_released": self.ranking_released,
            "result_shard_released": self.result_shard_released,
            "held_out_opened": self.held_out_opened,
            "alert_released": self.alert_released,
            "live_action": self.live_action,
        }


def _validate_result_run(run: RetainedFirstFourStage1ResultRun) -> None:
    if (type(run) is not RetainedFirstFourStage1ResultRun
            or run.version != STAGE1_RESULT_VERSION):
        raise RecordError("candidate grouping requires the accepted stage-1 result run")
    if any((run.result_shard_released, run.held_out_opened,
            run.alert_released, run.live_action)):
        raise RecordError("stage-1 result run opened a later release boundary")
    counts = (
        run.outcome_count, run.resolved_outcome_count, run.fully_costed_count,
        run.unresolved_excluded_count, run.incomplete_cost_excluded_count,
        run.unfilled_excluded_count, run.no_event_excluded_count,
        run.unavailable_excluded_count,
    )
    if any(type(value) is not int or value < 0 for value in counts):
        raise RecordError("stage-1 result counts must be non-negative integers")
    if (run.outcome_count != run.resolved_outcome_count + run.unresolved_excluded_count
            or run.resolved_outcome_count
            != run.fully_costed_count + run.incomplete_cost_excluded_count
            or run.fully_costed_count != len(run.rows)
            or run.disabled_rules != REQUIRED_DISABLED_RULES):
        raise RecordError("stage-1 result counts or disabled rules do not match")


def _validate_candidates(candidates: Mapping[str, Candidate]) -> tuple[CandidateKey, ...]:
    if not isinstance(candidates, Mapping) or tuple(candidates) != PLAYBOOKS:
        raise RecordError("candidate groups must name the first four in order")
    keys = []
    for playbook, candidate in candidates.items():
        if type(candidate) is not Candidate or candidate not in STAGE1_CANDIDATES[playbook]:
            raise RecordError("candidate group is outside the frozen stage-1 catalog")
        keys.append((playbook, candidate.candidate_id))
    return tuple(keys)


def _validate_sessions(sessions: Sequence[SessionKey]) -> tuple[SessionKey, ...]:
    plan = tuple(sessions)
    if (not plan or len(set(plan)) != len(plan)
            or any(type(item) is not tuple or len(item) != 2
                   or not all(isinstance(value, str) and value for value in item)
                   for item in plan)
            or {ticker for ticker, _session in plan} != set(TRAINING_TICKERS)):
        raise RecordError("training coverage needs unique sessions across all nine frozen names")
    if plan != tuple(sorted(plan, key=lambda item: (TRAINING_TICKERS.index(item[0]), item[1]))):
        raise RecordError("training sessions must use frozen ticker and session order")
    return plan


def group_retained_stage1_results(
    run: RetainedFirstFourStage1ResultRun,
    *,
    candidates: Mapping[str, Candidate],
    training_sessions: Sequence[SessionKey],
    evaluated_sessions: Mapping[CandidateKey, Sequence[SessionKey]],
) -> RetainedStage1CandidateGroupRun:
    """Group strict result rows after exact training coverage is proven."""
    _validate_result_run(run)
    keys = _validate_candidates(candidates)
    plan = _validate_sessions(training_sessions)
    if not isinstance(evaluated_sessions, Mapping) or tuple(evaluated_sessions) != keys:
        raise RecordError("coverage must name each frozen candidate in order")
    for key in keys:
        if tuple(evaluated_sessions[key]) != plan:
            raise RecordError("every candidate needs exact complete training-session coverage")

    grouped: dict[CandidateKey, list[ResolvedTrainingTrade]] = {key: [] for key in keys}
    expected_axes = {
        key: tuple(axis for axis, _value in candidates[key[0]].settings)
        for key in keys
    }
    plan_set = set(plan)
    for row in run.rows:
        if type(row) is not ResolvedTrainingTrade:
            raise RecordError("candidate groups require strict resolved training rows")
        key = (row.playbook, row.candidate_id)
        if key not in grouped:
            raise RecordError("result row does not match a frozen candidate")
        session_key = (row.ticker, row.closed_at.date().isoformat())
        if session_key not in plan_set:
            raise RecordError("result row is outside the exact training-session coverage")
        if not row.costs_complete or row.tested_axes != expected_axes[key]:
            raise RecordError("result row is not fully costed with every candidate axis tested")
        grouped[key].append(row)

    groups = tuple(
        RetainedStage1CandidateGroup(
            playbook, candidate_id, plan, tuple(grouped[(playbook, candidate_id)]),
        )
        for playbook, candidate_id in keys
    )
    return RetainedStage1CandidateGroupRun(
        RUN_VERSION,
        run.version,
        groups,
        plan,
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
    "RUN_VERSION", "CandidateKey", "SessionKey", "RetainedStage1CandidateGroup",
    "RetainedStage1CandidateGroupRun", "group_retained_stage1_results",
]
