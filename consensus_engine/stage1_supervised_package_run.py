"""M9.1CX: bounded offline connection from stage-1 results to their package.

The supervised caller supplies completed training-nine candidate results and
the original alert-time records for each non-ORB5 winner.  This module runs
only the accepted comparison functions, binds the winning events to those
results, and writes the immutable M9.1CW package.  It reads no market data and
does not start stage 2 or stage 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from .first_pullback_stage1_comparison import compare_first_pullback_stage1
from .first_pullback_vwap_stage1_run import FirstPullbackStage1Run
from .hod_comp_rs_stage1_comparison import compare_hod_comp_rs_stage1
from .hod_comp_rs_stage1_run import HodCompRsStage1Run
from .or_failure_stage1_comparison import compare_or_failure_stage1
from .or_failure_stage1_run import OrFailureStage1Run
from .orb5_stage1_result import (
    REQUIRED_DISABLED_RULES,
    Orb5CandidateStage1Run,
    compare_orb5_stage1,
)
from .search_run_config import PLAYBOOKS, TRAINING_TICKERS
from .stage1_result_package import (
    Stage1ResultPackage,
    build_stage1_result_package,
    read_stage1_result_package,
    write_stage1_result_package,
)
from .stage2_training_comparison import AcceptedStage1Winner, Stage2TrainingEvent
from .trade_alerts_models import RecordError

RUN_VERSION = "M91CX_SUPERVISED_STAGE1_PACKAGE_RUN_V1"
_EVENT_PLAYBOOKS = PLAYBOOKS[1:]


def _validate_run_scope(playbook: str, runs: Sequence[object]) -> None:
    for run in runs:
        candidate_id = getattr(run, "candidate_id", None)
        for trade in getattr(run, "resolved", ()):
            if (trade.playbook != playbook or trade.candidate_id != candidate_id
                    or trade.ticker not in TRAINING_TICKERS):
                raise RecordError(
                    f"{playbook} result contains a held-out or mismatched trade")


def _accepted_winner(
    playbook: str, comparison: object, events: Sequence[Stage2TrainingEvent],
) -> AcceptedStage1Winner:
    winner = getattr(comparison, "winner", None)
    blockers = getattr(comparison, "blockers", ())
    if getattr(comparison, "status", None) != "RANKED" or winner is None or blockers:
        raise RecordError(f"{playbook} stage-1 comparison is not accepted")
    frozen_events = tuple(events)
    if not frozen_events or any(not isinstance(row, Stage2TrainingEvent)
                                for row in frozen_events):
        raise RecordError(f"{playbook} needs original alert-time winner events")
    runs = comparison.runs
    winning_run = next(
        row for row in runs
        if row.candidate_id == winner.measurement.candidate.candidate_id
    )
    if tuple(event.trade for event in frozen_events) != tuple(winning_run.resolved):
        raise RecordError(f"{playbook} alert-time events do not match its winning result")
    measurements = tuple(row.measurement for row in runs)
    if any(row is None for row in measurements):
        raise RecordError(f"{playbook} candidate measurements are incomplete")
    return AcceptedStage1Winner(playbook, winner, measurements, frozen_events)


def run_supervised_stage1_package(
    *,
    output_path: Path,
    orb5_runs: Sequence[Orb5CandidateStage1Run],
    hod_comp_rs_runs: Sequence[HodCompRsStage1Run],
    or_failure_runs: Sequence[OrFailureStage1Run],
    first_pullback_runs: Sequence[FirstPullbackStage1Run],
    winner_events: Mapping[str, Sequence[Stage2TrainingEvent]],
) -> Stage1ResultPackage:
    """Validate supplied stage-1 results and durably write their package."""
    if (not isinstance(winner_events, Mapping)
            or set(winner_events) != set(_EVENT_PLAYBOOKS)):
        raise RecordError(
            "winner events must name exactly the three non-ORB5 playbooks")

    _validate_run_scope(PLAYBOOKS[1], hod_comp_rs_runs)
    _validate_run_scope(PLAYBOOKS[2], or_failure_runs)
    _validate_run_scope(PLAYBOOKS[3], first_pullback_runs)

    comparisons = (
        compare_orb5_stage1(orb5_runs),
        compare_hod_comp_rs_stage1(hod_comp_rs_runs),
        compare_or_failure_stage1(or_failure_runs),
        compare_first_pullback_stage1(first_pullback_runs),
    )
    orb5_winner = comparisons[0].accepted_winner
    if orb5_winner is None:
        raise RecordError("CRVOL_ORB5 stage-1 comparison is not accepted")
    winners = (orb5_winner,) + tuple(
        _accepted_winner(playbook, comparison, winner_events[playbook])
        for playbook, comparison in zip(_EVENT_PLAYBOOKS, comparisons[1:])
    )
    for winner in winners:
        for measurement in winner.candidate_measurements:
            if not set(REQUIRED_DISABLED_RULES).issubset(measurement.disabled_rules):
                raise RecordError(
                    f"{winner.playbook} must keep every D-104 dependent rule OFF and untested")

    package = build_stage1_result_package(comparisons, winners)
    write_stage1_result_package(Path(output_path), package)
    reopened = read_stage1_result_package(Path(output_path))
    if reopened != package:
        raise RecordError("written stage-1 package does not reopen identically")
    return reopened


__all__ = ["RUN_VERSION", "run_supervised_stage1_package"]
