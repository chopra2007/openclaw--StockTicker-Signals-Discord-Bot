"""M9.1AD: the 18-candidate `CRVOL_ORB5` grid run over supplied training sessions.

On minute bars only the opening-range axis (D-043, `OR5`/`OR15`) can change a
result. The participation axis (D-044) and the acceptance axis (D-045) drive
gates that `orb5_trade_walk.BAR_GATES_OFF` records OFF and untested (D-104), so
all nine candidates that share an opening range run the identical bar rule and
get identical records. Each candidate's tally says which axes were not tested.
The rule is run once per opening range and shared; nothing is approximated.

M9.1AG lets the run use `EXIT_D090_STRUCTURE_V2`: each session carries its
caller-supplied level catalog and completeness flag, and a trade closes when its
last unit closes. No catalog producer exists yet, so no real run is possible.

The tally is gross of cost (cost and slippage are OFF), so it is not the
after-cost mean profit that the frozen stage-1 ranking needs. No
`TrainingMeasurement` is built and nothing is ranked: `ranking_blockers` names
why. This module reads only the sessions the caller supplies, fetches nothing,
and no alert or order occurs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Sequence

from .historical_bars import HistoryBatch
from .orb5_trade_walk import (
    EXIT_MULTIPLES, STRUCTURE_EXIT, Orb5StructureExitRecord, Orb5TradeRecord,
    build_orb5_structure_exit_record, build_orb5_trade_record,
)
from .orb5_trigger import TriggerPolicy
from .search_run_config import STAGE1_CANDIDATES, Candidate
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

DIRECTIONS = ("LONG", "SHORT")
_OR_MINUTES = {"OR5": 5, "OR15": 15}
AXES_NOT_TESTED = (
    ("D-044", "PARTICIPATION_GATE_OFF_ON_BARS"),
    ("D-045", "ACCEPTANCE_GATE_OFF_ON_BARS"),
)
RANKING_BLOCKERS = (
    "COST_AND_SLIPPAGE_OFF_SO_R_IS_GROSS_NOT_AFTER_COST",
    "D044_D045_AXES_UNTESTED_SO_CANDIDATES_SHARING_AN_OPENING_RANGE_TIE",
    "ENTRY_FILL_IS_CALLER_SUPPLIED_NOT_THE_D106_QUOTE_FILL",
)


@dataclass(frozen=True)
class Orb5Session:
    """One training ticker-day: its bars and the caller's ATR, tick and entry."""

    ticker: str
    session_date: date
    instrument_type: str
    latest_atr: float | None
    tick: float | None
    entry_price: dict[str, float | None]  # by direction
    entry_time: dict[str, datetime | None]  # by direction
    entry_source: str
    minute_history: HistoryBatch | None
    # Read only by EXIT_D090_STRUCTURE_V2. An unstated catalog is incomplete, never "no obstacle".
    levels: tuple[tuple[str, float], ...] = ()
    catalog_complete: bool = False
    # M9.1AL: per (direction, opening-range minutes); a present key wins over `levels`,
    # because the measured-move level depends on both.
    catalogs: dict[tuple[str, int], tuple[tuple[tuple[str, float], ...], bool]] = field(
        default_factory=dict)


@dataclass(frozen=True)
class Orb5CandidateTally:
    candidate_id: str
    table_order: int
    opening_range_minutes: int
    exit_name: str
    trades: int
    unresolved: int
    mean_gross_r: float | None
    weekly_gross_win_rate: float | None
    weeks: int
    axes_not_tested: tuple[tuple[str, str], ...]
    records: tuple[Orb5TradeRecord | Orb5StructureExitRecord, ...]


@dataclass(frozen=True)
class Orb5GridRun:
    exit_name: str
    tallies: tuple[Orb5CandidateTally, ...]
    identical_groups: tuple[tuple[str, ...], ...]
    ranking_status: str
    ranking_blockers: tuple[str, ...]


def _opening_range(candidate: Candidate) -> int:
    chosen = dict(candidate.settings)["D-043"]
    return _OR_MINUTES[chosen]


def _exit_time(record: Orb5TradeRecord | Orb5StructureExitRecord) -> datetime:
    """The trade is closed when its last unit closes."""
    if isinstance(record, Orb5StructureExitRecord):
        return max(as_utc(t) for _, _, t in record.unit_exits)
    return record.walk.exit_time


def _tally(candidate: Candidate, exit_name: str, records: tuple) -> Orb5CandidateTally:
    resolved = [r for r in records if r.resolved]
    weekly: dict[date, float] = {}
    for r in resolved:
        iso = as_utc(_exit_time(r)).isocalendar()
        week = date.fromisocalendar(iso.year, iso.week, 1)
        weekly[week] = weekly.get(week, 0.0) + r.r_multiple
    return Orb5CandidateTally(
        candidate.candidate_id, candidate.table_order, _opening_range(candidate), exit_name,
        len(resolved), len(records) - len(resolved),
        sum(r.r_multiple for r in resolved) / len(resolved) if resolved else None,
        sum(1 for v in weekly.values() if v > 0) / len(weekly) if weekly else None,
        len(weekly), AXES_NOT_TESTED, records)


def run_orb5_grid(
    *, policy: TriggerPolicy, exit_name: str, sessions: Sequence[Orb5Session],
    search_minutes: int, record_id_prefix: str,
) -> Orb5GridRun:
    """Every stage-1 `CRVOL_ORB5` candidate over the supplied sessions, both directions."""
    if exit_name != STRUCTURE_EXIT and exit_name not in EXIT_MULTIPLES:
        raise RecordError("exit must be EXIT_FIXED_2R_V2, EXIT_FIXED_3R_V2 or EXIT_D090_STRUCTURE_V2")
    if not sessions:
        raise RecordError("no sessions supplied")
    candidates = STAGE1_CANDIDATES["CRVOL_ORB5"]
    by_range: dict[int, tuple] = {}
    for minutes in sorted({_opening_range(c) for c in candidates}):
        built = []
        for session in sessions:
            for direction in DIRECTIONS:
                common = dict(
                    policy=policy, direction=direction,
                    symbol=session.ticker, instrument_type=session.instrument_type,
                    opening_range_minutes=minutes, search_minutes=search_minutes,
                    latest_atr=session.latest_atr, tick=session.tick,
                    entry_price=session.entry_price.get(direction),
                    entry_time=session.entry_time.get(direction),
                    entry_source=session.entry_source, minute_history=session.minute_history,
                    record_id_prefix=f"{record_id_prefix}:{session.ticker}:{session.session_date}:{minutes}")
                if exit_name == STRUCTURE_EXIT:
                    levels, complete = session.catalogs.get(
                        (direction, minutes), (session.levels, session.catalog_complete))
                    built.append(build_orb5_structure_exit_record(
                        **common, levels=levels, catalog_complete=complete))
                else:
                    built.append(build_orb5_trade_record(**common, exit_name=exit_name))
        by_range[minutes] = tuple(built)
    tallies = tuple(_tally(c, exit_name, by_range[_opening_range(c)]) for c in candidates)
    groups: dict[int, list[str]] = {}
    for t in tallies:
        groups.setdefault(t.opening_range_minutes, []).append(t.candidate_id)
    return Orb5GridRun(exit_name, tallies, tuple(tuple(v) for v in groups.values()),
                       "NOT_RANKABLE", RANKING_BLOCKERS)
