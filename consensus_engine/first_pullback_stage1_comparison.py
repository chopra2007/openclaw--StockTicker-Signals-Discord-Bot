"""M9.1CO: compare the four frozen first-pullback stage-1 candidates.

The four candidate runners already own strategy replay and measurement.  This
module accepts their completed results, checks that they cover the same retained
training sessions under the same disabled-rule labels, and applies the frozen
stage-1 ranking rule.  Missing measurements and mismatched coverage stay visible
as blockers; they never produce a winner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .first_pullback_vwap_avwap_stage1_run import RUN_VERSION as AVWAP_RUN_VERSION
from .first_pullback_vwap_relaxed_avwap_stage1_run import (
    RUN_VERSION as RELAXED_AVWAP_RUN_VERSION,
)
from .first_pullback_vwap_relaxed_stage1_run import RUN_VERSION as RELAXED_RUN_VERSION
from .first_pullback_vwap_stage1_run import (
    RUN_VERSION as DEFAULT_RUN_VERSION,
    FirstPullbackStage1Run,
)
from .search_run_config import (
    STAGE1_CANDIDATES,
    TrainingMeasurement,
    rank_training_candidates,
)
from .stage1_training_measurement import Stage1TrainingMeasurement
from .trade_alerts_models import RecordError

COMPARISON_VERSION = "M91CO_FIRST_PULLBACK_STAGE1_COMPARISON_V1"
PLAYBOOK = "FIRST_PULLBACK_VWAP"
_CANDIDATES = STAGE1_CANDIDATES[PLAYBOOK]
_RUN_VERSIONS = {
    _CANDIDATES[0].candidate_id: DEFAULT_RUN_VERSION,
    _CANDIDATES[1].candidate_id: AVWAP_RUN_VERSION,
    _CANDIDATES[2].candidate_id: RELAXED_RUN_VERSION,
    _CANDIDATES[3].candidate_id: RELAXED_AVWAP_RUN_VERSION,
}


@dataclass(frozen=True)
class FirstPullbackStage1Comparison:
    version: str
    status: str
    runs: tuple[FirstPullbackStage1Run, ...]
    ranked: tuple[Stage1TrainingMeasurement, ...]
    winner: Stage1TrainingMeasurement | None
    blockers: tuple[str, ...]


def _ranking_key(row: Stage1TrainingMeasurement) -> tuple[float, float, float, int]:
    measured = row.measurement
    return (
        -measured.mean_profit_r,
        -measured.weekly_win_rate,
        measured.drawdown_recovery_weeks,
        measured.candidate.table_order,
    )


def compare_first_pullback_stage1(
    runs: Sequence[FirstPullbackStage1Run],
) -> FirstPullbackStage1Comparison:
    """Validate and rank one accepted run for each frozen candidate."""
    if len(runs) != len(_CANDIDATES):
        raise RecordError("all four frozen first-pullback candidate runs are required")
    by_candidate: dict[str, FirstPullbackStage1Run] = {}
    for run in runs:
        if not isinstance(run, FirstPullbackStage1Run):
            raise RecordError("runs must be FirstPullbackStage1Run records")
        if run.candidate_id not in _RUN_VERSIONS:
            raise RecordError("run candidate is not in the frozen first-pullback grid")
        if run.candidate_id in by_candidate:
            raise RecordError("duplicate first-pullback candidate run")
        if run.version != _RUN_VERSIONS[run.candidate_id]:
            raise RecordError("candidate run version does not match its accepted runner")
        by_candidate[run.candidate_id] = run
    canonical = tuple(by_candidate[candidate.candidate_id] for candidate in _CANDIDATES)

    blockers: list[str] = []
    reference_sessions = canonical[0].evaluated_sessions
    for run in canonical:
        if run.evaluated_sessions != reference_sessions:
            blockers.append(f"{run.candidate_id}:EVALUATED_SESSION_COVERAGE_MISMATCH")
        if run.measurement is None:
            blockers.append(f"{run.candidate_id}:MEASUREMENT_UNAVAILABLE")
    measured = tuple(run.measurement for run in canonical if run.measurement is not None)
    if measured:
        reference_disabled = measured[0].disabled_rules
        for run in canonical:
            row = run.measurement
            if row is None:
                continue
            if row.playbook != PLAYBOOK or row.measurement.candidate not in _CANDIDATES:
                raise RecordError("measurement does not belong to the frozen first-pullback grid")
            if row.measurement.candidate.candidate_id != run.candidate_id:
                raise RecordError("measurement candidate does not match its run")
            if row.disabled_rules != reference_disabled:
                blockers.append(
                    f"{row.measurement.candidate.candidate_id}:DISABLED_RULE_LABELS_MISMATCH")
    if blockers:
        return FirstPullbackStage1Comparison(
            COMPARISON_VERSION, "NOT_RANKABLE", canonical, (), None,
            tuple(dict.fromkeys(blockers)),
        )

    ranked = tuple(sorted(measured, key=_ranking_key))
    winning_measurement: TrainingMeasurement = rank_training_candidates(
        tuple(row.measurement for row in measured))
    winner = next(row for row in ranked if row.measurement == winning_measurement)
    return FirstPullbackStage1Comparison(
        COMPARISON_VERSION, "RANKED", canonical, ranked, winner, (),
    )


__all__ = [
    "COMPARISON_VERSION", "FirstPullbackStage1Comparison", "PLAYBOOK",
    "compare_first_pullback_stage1",
]
