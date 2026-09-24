"""M9.1CD: one offline stage-1 training measurement contract.

The frozen M9.1T search ranks each first-four playbook candidate on the nine
D-107 training names.  This module turns already-resolved, fully costed trade
rows into the three stored ranking values.  It uses the existing D-108 math,
but does not apply the held-out pass/fail bar.

It reads no files and runs no strategy.  The caller must prove that all nine
training names were evaluated, every candidate axis was actually tested, and
each supplied R value includes all required costs.  A held-out name, an OFF
candidate axis, or an incomplete cost row is refused rather than approximated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Sequence

from .d108_evaluator import D108Evaluation, TradeResult, evaluate_d108
from .search_run_config import (
    STAGE1_CANDIDATES,
    TRAINING_TICKERS,
    Candidate,
    TrainingMeasurement,
)
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

POLICY_VERSION = "M91CD_STAGE1_TRAINING_MEASUREMENT_V1"
_DIRECTIONS = frozenset({"LONG", "SHORT"})


@dataclass(frozen=True)
class ResolvedTrainingTrade:
    """One resolved stage-1 trade after every required execution cost."""

    playbook: str
    candidate_id: str
    ticker: str
    direction: str
    closed_at: datetime
    resolved_r: float
    cost_model_version: str
    costs_complete: bool
    tested_axes: tuple[str, ...]
    input_record_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.direction not in _DIRECTIONS:
            raise RecordError("direction must be LONG or SHORT")
        if not isinstance(self.resolved_r, (int, float)) or not math.isfinite(self.resolved_r):
            raise RecordError("resolved_r must be finite")
        if not isinstance(self.cost_model_version, str) or not self.cost_model_version.strip():
            raise RecordError("cost model version must be explicit")
        if not isinstance(self.input_record_ids, tuple) or not self.input_record_ids:
            raise RecordError("a training trade needs input record IDs")
        object.__setattr__(self, "closed_at", as_utc(self.closed_at))

    @property
    def cluster_key(self) -> tuple[str, date, str]:
        return self.ticker, self.closed_at.date(), self.direction


@dataclass(frozen=True)
class Stage1TrainingMeasurement:
    policy_version: str
    playbook: str
    measurement: TrainingMeasurement
    bootstrap_lower_bound: float
    trade_count: int
    week_count: int
    evaluated_tickers: tuple[str, ...]
    disabled_rules: tuple[str, ...]


def _frozen_candidate(playbook: str, candidate: Candidate) -> Candidate:
    if playbook not in STAGE1_CANDIDATES:
        raise RecordError("playbook must be one of the frozen first four")
    if not isinstance(candidate, Candidate):
        raise RecordError("candidate must be a frozen Candidate")
    matches = tuple(row for row in STAGE1_CANDIDATES[playbook]
                    if row.candidate_id == candidate.candidate_id)
    if len(matches) != 1 or matches[0] != candidate:
        raise RecordError("candidate does not match the frozen stage-1 catalog")
    return matches[0]


def measure_stage1_candidate(
    *, playbook: str, candidate: Candidate,
    trades: Sequence[ResolvedTrainingTrade],
    evaluated_tickers: tuple[str, ...],
    disabled_rules: tuple[str, ...] = (),
) -> Stage1TrainingMeasurement:
    """Measure one frozen candidate on the complete D-107 training split.

    `disabled_rules` records D-104 gaps that do not alter this candidate's
    measured axes or its fully costed trade R.  Disabled rules must not name
    any frozen candidate axis, even when every trade claims it was tested.
    """
    frozen = _frozen_candidate(playbook, candidate)
    if evaluated_tickers != TRAINING_TICKERS:
        raise RecordError("stage 1 must evaluate exactly the nine frozen training names")
    if not trades:
        raise RecordError("stage 1 needs at least one resolved training trade")
    if (not isinstance(disabled_rules, tuple)
            or any(not isinstance(item, str) or not item.strip() for item in disabled_rules)
            or len(set(disabled_rules)) != len(disabled_rules)):
        raise RecordError("disabled rules must be a unique tuple of explicit names")

    expected_axes = tuple(name for name, _value in frozen.settings)
    if set(disabled_rules).intersection(expected_axes):
        raise RecordError("a frozen candidate axis cannot be disabled")
    clusters: set[tuple[str, date, str]] = set()
    d108_rows: list[TradeResult] = []
    for trade in trades:
        if not isinstance(trade, ResolvedTrainingTrade):
            raise RecordError("trades must be ResolvedTrainingTrade records")
        if trade.playbook != playbook or trade.candidate_id != frozen.candidate_id:
            raise RecordError("trade does not belong to the measured candidate")
        if trade.ticker not in TRAINING_TICKERS:
            raise RecordError("held-out or unknown ticker cannot enter stage 1")
        if not trade.costs_complete:
            raise RecordError("training R must include every required cost")
        if trade.tested_axes != expected_axes:
            raise RecordError("every frozen candidate axis must be tested")
        if trade.cluster_key in clusters:
            raise RecordError("stage 1 allows one event per ticker-day-side")
        clusters.add(trade.cluster_key)
        d108_rows.append(TradeResult(trade.resolved_r, trade.closed_at))

    detail: D108Evaluation = evaluate_d108(frozen.candidate_id, d108_rows)
    recovery = detail.survivability.weeks_to_recover
    measurement = TrainingMeasurement(
        candidate=frozen,
        mean_profit_r=detail.profit.mean_r,
        weekly_win_rate=detail.consistency.winning_week_fraction,
        drawdown_recovery_weeks=math.inf if recovery is None else recovery,
    )
    return Stage1TrainingMeasurement(
        POLICY_VERSION, playbook, measurement, detail.profit.primary.lower_bound,
        detail.trade_count, detail.consistency.week_count, evaluated_tickers,
        disabled_rules,
    )


__all__ = [
    "POLICY_VERSION", "ResolvedTrainingTrade", "Stage1TrainingMeasurement",
    "measure_stage1_candidate",
]
