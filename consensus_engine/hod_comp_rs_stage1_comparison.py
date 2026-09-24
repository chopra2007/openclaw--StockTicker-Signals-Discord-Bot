"""M9.1CR: compare the four frozen HOD-compression stage-1 candidates.

The four candidate runners already own strategy replay and measurement. This
module accepts their completed results, checks matching retained training
coverage and disabled-rule labels, and applies the frozen stage-1 ranking rule.
Missing or incomparable measurements never produce a winner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .hod_comp_rs_compression_off_report_only_stage1_run import (
    RUN_VERSION as COMPRESSION_OFF_REPORT_ONLY_RUN_VERSION,
)
from .hod_comp_rs_compression_off_stage1_run import (
    RUN_VERSION as COMPRESSION_OFF_RUN_VERSION,
)
from .hod_comp_rs_report_only_stage1_run import RUN_VERSION as REPORT_ONLY_RUN_VERSION
from .hod_comp_rs_stage1_run import (
    RUN_VERSION as DEFAULT_RUN_VERSION,
    HodCompRsStage1Run,
)
from .search_run_config import STAGE1_CANDIDATES, TrainingMeasurement, rank_training_candidates
from .stage1_training_measurement import Stage1TrainingMeasurement
from .trade_alerts_models import RecordError

COMPARISON_VERSION = "M91CR_HOD_COMP_RS_STAGE1_COMPARISON_V1"
PLAYBOOK = "HOD_COMP_RS"
_CANDIDATES = STAGE1_CANDIDATES[PLAYBOOK]
_RUN_VERSIONS = {
    _CANDIDATES[0].candidate_id: DEFAULT_RUN_VERSION,
    _CANDIDATES[1].candidate_id: REPORT_ONLY_RUN_VERSION,
    _CANDIDATES[2].candidate_id: COMPRESSION_OFF_RUN_VERSION,
    _CANDIDATES[3].candidate_id: COMPRESSION_OFF_REPORT_ONLY_RUN_VERSION,
}


@dataclass(frozen=True)
class HodCompRsStage1Comparison:
    version: str
    status: str
    runs: tuple[HodCompRsStage1Run, ...]
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


def compare_hod_comp_rs_stage1(
    runs: Sequence[HodCompRsStage1Run],
) -> HodCompRsStage1Comparison:
    """Validate and rank one accepted run for each frozen candidate."""
    if len(runs) != len(_CANDIDATES):
        raise RecordError("all four frozen HOD-compression candidate runs are required")
    by_candidate: dict[str, HodCompRsStage1Run] = {}
    for run in runs:
        if not isinstance(run, HodCompRsStage1Run):
            raise RecordError("runs must be HodCompRsStage1Run records")
        if run.candidate_id not in _RUN_VERSIONS:
            raise RecordError("run candidate is not in the frozen HOD-compression grid")
        if run.candidate_id in by_candidate:
            raise RecordError("duplicate HOD-compression candidate run")
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
                raise RecordError("measurement does not belong to the frozen HOD-compression grid")
            if row.measurement.candidate.candidate_id != run.candidate_id:
                raise RecordError("measurement candidate does not match its run")
            if row.disabled_rules != reference_disabled:
                blockers.append(
                    f"{row.measurement.candidate.candidate_id}:DISABLED_RULE_LABELS_MISMATCH")
    if blockers:
        return HodCompRsStage1Comparison(
            COMPARISON_VERSION, "NOT_RANKABLE", canonical, (), None,
            tuple(dict.fromkeys(blockers)),
        )

    ranked = tuple(sorted(measured, key=_ranking_key))
    winning_measurement: TrainingMeasurement = rank_training_candidates(
        tuple(row.measurement for row in measured))
    winner = next(row for row in ranked if row.measurement == winning_measurement)
    return HodCompRsStage1Comparison(
        COMPARISON_VERSION, "RANKED", canonical, ranked, winner, (),
    )


__all__ = [
    "COMPARISON_VERSION", "HodCompRsStage1Comparison", "PLAYBOOK",
    "compare_hod_comp_rs_stage1",
]
