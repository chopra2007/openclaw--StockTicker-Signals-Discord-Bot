"""M9.1V part 1: the frozen stage-1/stage-2 search catalog and training-set
ranking rule, reproduced exactly from
`M9_1T_PARAMETER_GRID_PREREGISTRATION.md` section 2-3 (build-scope item (e)
of the 2026-09-17 M9.1 inventory).

This module holds pure data and a pure comparison rule: the per-playbook
stage-1 candidate grids (18/4/2/4 configurations), the five stage-2
playbook-combination candidates, the D-107 training/held-out ticker split,
and `rank_training_candidates`, which applies the frozen stage-1/stage-2
tie-break (highest training-set mean profit, then weekly win rate, then
lowest drawdown, then lowest-ID candidate in preregistered table order) to
whatever training-set measurements the caller supplies.

It does not load bars, run a playbook, drive an adapter, evaluate a trade or
read any real training or held-out result. `TrainingMeasurement` is a plain
value the caller must compute elsewhere and supply; no default or synthetic
measurement is produced here. This is scaffolding for the stage-1/2/3 search
run itself, which remains a further M9.1V sub-step. No application ran and
no spend occurred while writing this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Sequence

from .trade_alerts_models import RecordError

# D-107 split, reproduced unchanged from M9_1T_PARAMETER_GRID_PREREGISTRATION.md
# section 1. Fixed tuples, not sets: order carries no ranking meaning here.
TRAINING_TICKERS: tuple[str, ...] = (
    "NVDA", "MSFT", "AAPL", "TSLA", "LLY", "SPY", "QQQ", "XLV", "USO",
)
HELD_OUT_TICKERS: tuple[str, ...] = (
    "GOOGL", "AMZN", "META", "AVGO", "BRK.B", "IWM", "GLD", "VXX",
)

PLAYBOOKS: tuple[str, ...] = (
    "CRVOL_ORB5", "HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP",
)


@dataclass(frozen=True)
class Candidate:
    """One preregistered stage-1 (per-playbook) or stage-2 (combination) candidate.

    `candidate_id` is the composite ID formed by joining each axis's own ID
    in the fixed table order from `M9_1T_PARAMETER_GRID_PREREGISTRATION.md`;
    `settings` maps each D-number axis name to the chosen axis ID for that
    axis. `table_order` is this candidate's position in the fixed
    (never re-sorted) preregistered cross-product order, used only for the
    lowest-ID tie-break.
    """

    candidate_id: str
    settings: tuple[tuple[str, str], ...]
    table_order: int


def _axis_grid(playbook: str, axes: Sequence[tuple[str, tuple[str, ...]]]) -> tuple[Candidate, ...]:
    candidates = []
    for order, combo in enumerate(product(*(values for _name, values in axes))):
        settings = tuple((name, value) for (name, _values), value in zip(axes, combo))
        candidate_id = "|".join(value for _name, value in settings)
        candidates.append(Candidate(candidate_id=candidate_id, settings=settings, table_order=order))
    return tuple(candidates)


# Axis order and IDs reproduced exactly from section 2's tables; the D-number
# key names the owner decision each axis was frozen under.
STAGE1_CANDIDATES: dict[str, tuple[Candidate, ...]] = {
    "CRVOL_ORB5": _axis_grid(
        "CRVOL_ORB5",
        [
            ("D-043", ("OR5", "OR15")),
            ("D-044", ("RVOL_1_5", "RVOL_2_0", "RVOL_2_5")),
            ("D-045", ("ACC_10S_060", "ACC_10S_070", "ACC_30S_070")),
        ],
    ),
    "HOD_COMP_RS": _axis_grid(
        "HOD_COMP_RS",
        [
            ("D-048", ("COMP_ON_060", "COMP_OFF")),
            ("D-049", ("RS_MANDATORY", "RS_REPORT_ONLY")),
        ],
    ),
    "OR_FAILURE_REV": _axis_grid(
        "OR_FAILURE_REV",
        [
            ("D-052", ("CONFIRMED", "FASTER")),
        ],
    ),
    "FIRST_PULLBACK_VWAP": _axis_grid(
        "FIRST_PULLBACK_VWAP",
        [
            ("D-054", ("VWAP_MANDATORY", "VWAP_RELAXED")),
            ("D-055", ("AVWAP_OFF", "AVWAP_ON")),
        ],
    ),
}

STAGE1_GRID_SIZES: dict[str, int] = {
    "CRVOL_ORB5": 18,
    "HOD_COMP_RS": 4,
    "OR_FAILURE_REV": 2,
    "FIRST_PULLBACK_VWAP": 4,
}

# Section 3's five stage-2 combination candidates, in their fixed table order.
STAGE2_CANDIDATES: tuple[Candidate, ...] = tuple(
    Candidate(candidate_id=candidate_id, settings=(("playbooks", playbooks),), table_order=order)
    for order, (candidate_id, playbooks) in enumerate(
        [
            ("SOLO_ORB5", ("CRVOL_ORB5",)),
            ("SOLO_HODCOMP", ("HOD_COMP_RS",)),
            ("SOLO_ORFAIL", ("OR_FAILURE_REV",)),
            ("SOLO_PULLBACK", ("FIRST_PULLBACK_VWAP",)),
            ("ALL_FOUR", PLAYBOOKS),
        ]
    )
)


@dataclass(frozen=True)
class TrainingMeasurement:
    """One candidate's already-computed training-set (nine-ticker) ranking inputs.

    `mean_profit_r` and `weekly_win_rate` rank higher-is-better;
    `drawdown_recovery_weeks` ranks lower-is-better (fewer average winning
    weeks needed to recover the worst drawdown). This module does not compute
    any of the three; the caller supplies them from an already-run training
    evaluation.
    """

    candidate: Candidate
    mean_profit_r: float
    weekly_win_rate: float
    drawdown_recovery_weeks: float


def rank_training_candidates(measurements: Sequence[TrainingMeasurement]) -> TrainingMeasurement:
    """Apply the frozen stage-1/stage-2 tie-break to already-measured training results.

    Highest `mean_profit_r` wins; ties broken by highest `weekly_win_rate`,
    then lowest `drawdown_recovery_weeks`, then the candidate whose
    `table_order` is lowest (the earliest candidate in the preregistered
    axis-cross order). Raises `RecordError` on an empty sequence rather than
    returning a default winner.
    """
    if not measurements:
        raise RecordError("no training measurements to rank")
    return min(
        measurements,
        key=lambda m: (
            -m.mean_profit_r,
            -m.weekly_win_rate,
            m.drawdown_recovery_weeks,
            m.candidate.table_order,
        ),
    )
