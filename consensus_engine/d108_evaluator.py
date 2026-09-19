"""D-108 success-bar evaluator (M9.1U), frozen before any search result is read.

`DECISIONS_AND_OPEN_QUESTIONS.md` section 57 (D-108) defines a combination as
passing only if all three hold on the **held-out eight** weeks:

1. Profit — highest mean profit per trade after all costs, and the lower
   bound of its bootstrap confidence interval is above zero.
2. Consistency — at least 60% winning weeks.
3. Survivability — worst peak-to-trough loss recoverable within about six
   average winning weeks. Worst losing streak is reported, not pass/fail.

This module implements only that measurement. It has no clock, provider,
database or search loop of its own: the caller supplies one already-resolved
sequence of per-trade R multiples with their close times (each trade's
``resolved_r`` already reflects the D-106/D-107 modeled fill and cost, from
``playbook_outcome_evaluator``/``outcome_evaluator``), and this module
computes the three D-108 measures over them. It does not run the stage-1/
stage-2 training search (`M9_1T_PARAMETER_GRID_PREREGISTRATION.md` section 3),
choose a configuration, fetch data, or read any held-out result on its own;
the caller decides when the held-out eight may be read. No application ran
and no spend occurred while writing this module.

The bootstrap reuses this project's existing dependence-aware convention
(`M0_3B_DEFINITION_PACKET.md` section 5): a circular moving-block resample
over ordered calendar weeks (blocks of consecutive weeks rather than
sessions, since D-108's own unit is the week), 10,000 draws, block length
`L=10` primary with `L=5`/`L=20` sensitivities, a frozen NumPy
`Generator(PCG64(seed))` derived from a canonical-JSON SHA256 hash, and the
same nearest-rank quantile rule. This is a single frozen measurement, not one
of the 72 multi-arm family comparisons, so no Bonferroni-style family
allocation applies here; the one-sided bound is the ordinary `q=0.05` (95%)
lower bound.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

import numpy as np

from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

POLICY_VERSION = "D108_SUCCESS_BAR_V1"
WINNING_WEEK_FRACTION_REQUIRED = 0.60
DRAWDOWN_RECOVERY_WINNING_WEEKS = 6.0
PRIMARY_BLOCK_LENGTH = 10
SENSITIVITY_BLOCK_LENGTHS = (5, 20)
RESAMPLES = 10_000
LOWER_BOUND_Q = 0.05


@dataclass(frozen=True)
class TradeResult:
    """One already-resolved trade: its D-106/D-107 modeled R and close time."""

    resolved_r: float
    closed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.resolved_r, (int, float)) or not math.isfinite(self.resolved_r):
            raise RecordError("resolved_r must be a finite number")
        object.__setattr__(self, "closed_at", as_utc(self.closed_at))

    @property
    def week(self) -> date:
        iso = self.closed_at.isocalendar()
        return date.fromisocalendar(iso.year, iso.week, 1)


@dataclass(frozen=True)
class WeeklyBlockBootstrap:
    block_length: int
    seed: int
    seed_hash: str
    resamples: int
    lower_bound: float
    passed: bool

    def as_dict(self) -> dict:
        return {
            "block_length": self.block_length, "seed": self.seed, "seed_hash": self.seed_hash,
            "resamples": self.resamples, "lower_bound": self.lower_bound, "passed": self.passed,
        }


@dataclass(frozen=True)
class ProfitCheck:
    trade_count: int
    mean_r: float
    primary: WeeklyBlockBootstrap
    sensitivities: tuple[WeeklyBlockBootstrap, ...]
    review_required: bool
    passed: bool

    def as_dict(self) -> dict:
        return {
            "trade_count": self.trade_count, "mean_r": self.mean_r,
            "primary": self.primary.as_dict(),
            "sensitivities": [item.as_dict() for item in self.sensitivities],
            "review_required": self.review_required, "passed": self.passed,
        }


@dataclass(frozen=True)
class ConsistencyCheck:
    week_count: int
    winning_week_count: int
    winning_week_fraction: float
    passed: bool

    def as_dict(self) -> dict:
        return {
            "week_count": self.week_count, "winning_week_count": self.winning_week_count,
            "winning_week_fraction": self.winning_week_fraction, "passed": self.passed,
        }


@dataclass(frozen=True)
class SurvivabilityCheck:
    worst_drawdown_r: float
    average_winning_week_r: float | None
    weeks_to_recover: float | None
    passed: bool
    reason: str
    worst_losing_streak: int

    def as_dict(self) -> dict:
        return {
            "worst_drawdown_r": self.worst_drawdown_r,
            "average_winning_week_r": self.average_winning_week_r,
            "weeks_to_recover": self.weeks_to_recover, "passed": self.passed,
            "reason": self.reason, "worst_losing_streak": self.worst_losing_streak,
        }


@dataclass(frozen=True)
class D108Evaluation:
    policy_version: str
    candidate_id: str
    trade_count: int
    profit: ProfitCheck
    consistency: ConsistencyCheck
    survivability: SurvivabilityCheck
    passed: bool

    def as_dict(self) -> dict:
        return {
            "policy_version": self.policy_version, "candidate_id": self.candidate_id,
            "trade_count": self.trade_count, "profit": self.profit.as_dict(),
            "consistency": self.consistency.as_dict(),
            "survivability": self.survivability.as_dict(), "passed": self.passed,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _seed_for(candidate_id: str, week_count: int, block_length: int, resamples: int) -> tuple[int, str]:
    payload = {
        "candidate_id": candidate_id, "metric": "d108_mean_r_over_sampled_weeks",
        "week_count": week_count, "block_length": block_length, "resamples": resamples,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return int(digest[:16], 16), digest


def _nearest_rank_quantile(sorted_values: np.ndarray, q: float) -> float:
    n = sorted_values.size
    idx = min(max(math.ceil(q * n) - 1, 0), n - 1)
    return float(sorted_values[idx])


def _weekly_r(trades: Sequence[TradeResult]) -> dict[date, float]:
    weekly: dict[date, float] = {}
    for trade in trades:
        weekly[trade.week] = weekly.get(trade.week, 0.0) + trade.resolved_r
    return weekly


def _circular_block_bootstrap_mean_r(
    trades_by_week: Sequence[tuple[date, tuple[float, ...]]], block_length: int,
    resamples: int, seed: int,
) -> np.ndarray:
    """Circular moving-block resample over ordered weeks (M0_3B section 5),
    computing the requested statistic (mean R) across every appended trade
    row, never averaging week means."""
    n = len(trades_by_week)
    if n == 0:
        return np.empty(0, dtype=float)
    rng = np.random.Generator(np.random.PCG64(seed))
    n_blocks = math.ceil(n / block_length)
    starts = rng.integers(0, n, size=(resamples, n_blocks))
    stats = np.empty(resamples, dtype=float)
    for row in range(resamples):
        week_indexes: list[int] = []
        for start in starts[row]:
            week_indexes.extend(int(start + offset) % n for offset in range(block_length))
        week_indexes = week_indexes[:n]
        total, count = 0.0, 0
        for idx in week_indexes:
            values = trades_by_week[idx][1]
            total += sum(values)
            count += len(values)
        stats[row] = total / count if count else float("nan")
    return stats


def evaluate_d108(
    candidate_id: str, trades: Sequence[TradeResult],
    *, resamples: int = RESAMPLES, primary_block_length: int = PRIMARY_BLOCK_LENGTH,
    sensitivity_block_lengths: Sequence[int] = SENSITIVITY_BLOCK_LENGTHS,
) -> D108Evaluation:
    """Evaluate the frozen D-108 bar over one already-resolved held-out trade
    sequence for one candidate configuration. Raises if the sequence is empty
    or any input is malformed; a strategy/combination with zero trades on the
    held-out eight has no D-108 result, not a silent pass or fail."""
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise RecordError("candidate_id must be explicit")
    if not trades:
        raise RecordError("D-108 requires at least one held-out trade to evaluate")
    ordered = sorted(trades, key=lambda item: item.closed_at)

    weekly = _weekly_r(ordered)
    weeks_sorted = sorted(weekly)
    trades_by_week: list[tuple[date, tuple[float, ...]]] = []
    for week in weeks_sorted:
        values = tuple(item.resolved_r for item in ordered if item.week == week)
        trades_by_week.append((week, values))

    trade_count = len(ordered)
    mean_r = sum(item.resolved_r for item in ordered) / trade_count

    def _bound(block_length: int) -> WeeklyBlockBootstrap:
        seed, seed_hash = _seed_for(candidate_id, len(trades_by_week), block_length, resamples)
        stats = _circular_block_bootstrap_mean_r(trades_by_week, block_length, resamples, seed)
        lower = _nearest_rank_quantile(np.sort(stats), LOWER_BOUND_Q)
        return WeeklyBlockBootstrap(block_length, seed, seed_hash, resamples, lower, lower > 0.0)

    primary = _bound(primary_block_length)
    sensitivities = tuple(_bound(length) for length in sensitivity_block_lengths)
    review_required = any(item.passed != primary.passed for item in sensitivities)
    profit = ProfitCheck(trade_count, mean_r, primary, sensitivities, review_required,
                         passed=primary.passed and not review_required)

    winning_weeks = [week for week, values in trades_by_week if sum(values) > 0]
    week_count = len(trades_by_week)
    winning_week_fraction = len(winning_weeks) / week_count if week_count else 0.0
    consistency = ConsistencyCheck(week_count, len(winning_weeks), winning_week_fraction,
                                   winning_week_fraction >= WINNING_WEEK_FRACTION_REQUIRED)

    cumulative = 0.0
    peak = 0.0
    worst_drawdown = 0.0
    current_streak = 0
    worst_streak = 0
    for item in ordered:
        cumulative += item.resolved_r
        peak = max(peak, cumulative)
        worst_drawdown = max(worst_drawdown, peak - cumulative)
        if item.resolved_r < 0:
            current_streak += 1
            worst_streak = max(worst_streak, current_streak)
        else:
            current_streak = 0

    winning_week_values = [sum(values) for _, values in trades_by_week if sum(values) > 0]
    if winning_week_values:
        average_winning_week_r = sum(winning_week_values) / len(winning_week_values)
    else:
        average_winning_week_r = None

    if worst_drawdown <= 0.0:
        weeks_to_recover: float | None = 0.0
        survivability_passed = True
        reason = "no drawdown observed"
    elif average_winning_week_r is None or average_winning_week_r <= 0.0:
        weeks_to_recover = None
        survivability_passed = False
        reason = "no winning week to size a recovery rate from"
    else:
        weeks_to_recover = worst_drawdown / average_winning_week_r
        survivability_passed = weeks_to_recover <= DRAWDOWN_RECOVERY_WINNING_WEEKS
        reason = ("recoverable within about six average winning weeks" if survivability_passed
                  else "worst drawdown exceeds about six average winning weeks to recover")

    survivability = SurvivabilityCheck(worst_drawdown, average_winning_week_r, weeks_to_recover,
                                       survivability_passed, reason, worst_streak)

    passed = profit.passed and consistency.passed and survivability.passed
    return D108Evaluation(POLICY_VERSION, candidate_id, trade_count, profit, consistency,
                          survivability, passed)


__all__ = [
    "POLICY_VERSION", "WINNING_WEEK_FRACTION_REQUIRED", "DRAWDOWN_RECOVERY_WINNING_WEEKS",
    "PRIMARY_BLOCK_LENGTH", "SENSITIVITY_BLOCK_LENGTHS", "RESAMPLES", "LOWER_BOUND_Q",
    "TradeResult", "WeeklyBlockBootstrap", "ProfitCheck", "ConsistencyCheck",
    "SurvivabilityCheck", "D108Evaluation", "evaluate_d108",
]
