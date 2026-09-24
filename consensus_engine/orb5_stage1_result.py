"""M9.1CV: strict retained stage-1 results for the frozen ORB5 grid.

The bar-only ORB5 grid is gross of costs and cannot test the D-044/D-045
axes.  This boundary therefore accepts only caller-supplied, resolved events
whose records already prove all three frozen axes and every required cost.  It
keeps each event's alert time for the later D-106 stage-2 clustering rule,
requires explicit coverage of the training nine, and never reads held-out
names or fills a missing field.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from .search_run_config import (
    STAGE1_CANDIDATES,
    TRAINING_TICKERS,
    Candidate,
    TrainingMeasurement,
    rank_training_candidates,
)
from .stage1_training_measurement import (
    ResolvedTrainingTrade,
    Stage1TrainingMeasurement,
    measure_stage1_candidate,
)
from .stage2_training_comparison import AcceptedStage1Winner, Stage2TrainingEvent
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

RUN_VERSION = "M91CV_ORB5_STAGE1_RESULT_V1"
COMPARISON_VERSION = "M91CV_ORB5_STAGE1_COMPARISON_V1"
PLAYBOOK = "CRVOL_ORB5"
_CANDIDATES = STAGE1_CANDIDATES[PLAYBOOK]
# This supplied record shape cannot prove these fields. Every listed dependent
# rule is OFF and untested, including when there are no resolved events.
REQUIRED_DISABLED_RULES = (
    "ORIGINAL_AVAILABILITY_GAP", "CORRECTIONS_FINALITY_GAP",
    "POINT_IN_TIME_MEMBERSHIP_GAP",
)
_PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class Orb5Stage1Event:
    """One fully costed ORB5 result with its original alert time and session."""

    session: str
    alerted_at: datetime
    trade: ResolvedTrainingTrade

    def __post_init__(self) -> None:
        try:
            date.fromisoformat(self.session)
        except (TypeError, ValueError) as exc:
            raise RecordError("ORB5 event session must be an ISO date") from exc
        if not isinstance(self.trade, ResolvedTrainingTrade):
            raise RecordError("ORB5 events must contain ResolvedTrainingTrade records")
        alerted_at = as_utc(self.alerted_at)
        if (self.session != alerted_at.astimezone(_PACIFIC).date().isoformat()
                or self.session != self.trade.closed_at.astimezone(_PACIFIC).date().isoformat()):
            raise RecordError("ORB5 session must match the alert and trade close Pacific dates")
        if alerted_at > self.trade.closed_at:
            raise RecordError("ORB5 alert time cannot be after the trade close")
        object.__setattr__(self, "alerted_at", alerted_at)

    def stage2_event(self) -> Stage2TrainingEvent:
        return Stage2TrainingEvent(self.trade, self.alerted_at)


@dataclass(frozen=True)
class Orb5CandidateStage1Run:
    version: str
    candidate_id: str
    measurement: Stage1TrainingMeasurement | None
    events: tuple[Orb5Stage1Event, ...]
    evaluated_sessions: tuple[tuple[str, str], ...]
    exclusions: tuple[str, ...]
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES


@dataclass(frozen=True)
class Orb5Stage1Comparison:
    version: str
    status: str
    runs: tuple[Orb5CandidateStage1Run, ...]
    ranked: tuple[Stage1TrainingMeasurement, ...]
    winner: Stage1TrainingMeasurement | None
    accepted_winner: AcceptedStage1Winner | None
    blockers: tuple[str, ...]


def _frozen_candidate(candidate: Candidate) -> Candidate:
    if not isinstance(candidate, Candidate) or candidate not in _CANDIDATES:
        raise RecordError("candidate must be in the frozen CRVOL_ORB5 grid")
    return candidate


def run_orb5_candidate_stage1(
    *, candidate: Candidate, events: Sequence[Orb5Stage1Event],
    evaluated_sessions: Sequence[tuple[str, str]],
    disabled_rules: tuple[str, ...] = REQUIRED_DISABLED_RULES,
    exclusions: tuple[str, ...] = (),
) -> Orb5CandidateStage1Run:
    """Build one strict candidate measurement from supplied retained results."""
    frozen = _frozen_candidate(candidate)
    if (not isinstance(disabled_rules, tuple)
            or any(not isinstance(rule, str) or not rule.strip() for rule in disabled_rules)
            or len(set(disabled_rules)) != len(disabled_rules)
            or not set(REQUIRED_DISABLED_RULES).issubset(disabled_rules)):
        raise RecordError("required D-104 gap rules must remain OFF and untested")
    if set(disabled_rules).intersection(name for name, _value in frozen.settings):
        raise RecordError("a frozen candidate axis cannot be disabled")
    sessions: set[tuple[str, str]] = set()
    for row in evaluated_sessions:
        if (not isinstance(row, tuple) or len(row) != 2
                or row[0] not in TRAINING_TICKERS):
            raise RecordError("evaluated sessions must name frozen training tickers")
        try:
            date.fromisoformat(row[1])
        except (TypeError, ValueError) as exc:
            raise RecordError("evaluated session must use an ISO date") from exc
        if row in sessions:
            raise RecordError("duplicate evaluated ORB5 session")
        sessions.add(row)
    if {ticker for ticker, _session in sessions} != set(TRAINING_TICKERS):
        raise RecordError("ORB5 stage 1 must cover all nine frozen training names")
    if (not isinstance(exclusions, tuple)
            or any(not isinstance(reason, str) or not reason.strip() for reason in exclusions)):
        raise RecordError("exclusions must be explicit strings")

    axes = tuple(name for name, _value in frozen.settings)
    preserved: list[Orb5Stage1Event] = []
    event_keys: set[tuple[str, str, str]] = set()
    for event in events:
        if not isinstance(event, Orb5Stage1Event):
            raise RecordError("events must be Orb5Stage1Event records")
        trade = event.trade
        if (trade.playbook != PLAYBOOK or trade.candidate_id != frozen.candidate_id
                or trade.ticker not in TRAINING_TICKERS):
            raise RecordError("ORB5 event does not belong to the frozen candidate")
        if (trade.ticker, event.session) not in sessions:
            raise RecordError("ORB5 event does not match an evaluated training session")
        if not trade.costs_complete:
            raise RecordError("ORB5 resolved R must include every required cost")
        if trade.tested_axes != axes:
            raise RecordError("ORB5 event must prove all three frozen candidate axes")
        key = (trade.ticker, event.session, trade.direction)
        if key in event_keys:
            raise RecordError("ORB5 stage 1 allows one event per ticker-session-side")
        event_keys.add(key)
        preserved.append(event)

    measurement = None
    if preserved:
        measurement = measure_stage1_candidate(
            playbook=PLAYBOOK, candidate=frozen,
            trades=tuple(event.trade for event in preserved),
            evaluated_tickers=TRAINING_TICKERS, disabled_rules=disabled_rules,
        )
    return Orb5CandidateStage1Run(
        RUN_VERSION, frozen.candidate_id, measurement, tuple(preserved),
        tuple(sorted(sessions)), exclusions, disabled_rules,
    )


def _ranking_key(row: Stage1TrainingMeasurement) -> tuple[float, float, float, int]:
    measured = row.measurement
    return (-measured.mean_profit_r, -measured.weekly_win_rate,
            measured.drawdown_recovery_weeks, measured.candidate.table_order)


def compare_orb5_stage1(runs: Sequence[Orb5CandidateStage1Run]) -> Orb5Stage1Comparison:
    """Validate, rank and preserve all 18 frozen ORB5 candidate results."""
    if len(runs) != len(_CANDIDATES):
        raise RecordError("all 18 frozen CRVOL_ORB5 candidate runs are required")
    by_candidate: dict[str, Orb5CandidateStage1Run] = {}
    for run in runs:
        if not isinstance(run, Orb5CandidateStage1Run):
            raise RecordError("runs must be Orb5CandidateStage1Run records")
        if run.version != RUN_VERSION:
            raise RecordError("ORB5 candidate run version is not accepted")
        if run.candidate_id not in {row.candidate_id for row in _CANDIDATES}:
            raise RecordError("run candidate is not in the frozen CRVOL_ORB5 grid")
        if run.candidate_id in by_candidate:
            raise RecordError("duplicate CRVOL_ORB5 candidate run")
        by_candidate[run.candidate_id] = run
    canonical = tuple(by_candidate[row.candidate_id] for row in _CANDIDATES)

    blockers: list[str] = []
    reference_sessions = canonical[0].evaluated_sessions
    measured: list[Stage1TrainingMeasurement] = []
    reference_disabled: tuple[str, ...] | None = None
    for candidate, run in zip(_CANDIDATES, canonical):
        if run.evaluated_sessions != reference_sessions:
            blockers.append(f"{run.candidate_id}:EVALUATED_SESSION_COVERAGE_MISMATCH")
        # Runs are public records, so construction by the runner is not proof.
        # Reapply its input checks and recompute every stored measurement field.
        try:
            rebuilt = run_orb5_candidate_stage1(
                candidate=candidate, events=run.events,
                evaluated_sessions=run.evaluated_sessions,
                disabled_rules=run.disabled_rules, exclusions=run.exclusions,
            )
        except RecordError as exc:
            blockers.append(f"{run.candidate_id}:INVALID_RUN:{exc}")
            continue
        row = run.measurement
        if row != rebuilt.measurement:
            blockers.append(f"{run.candidate_id}:MEASUREMENT_EVENTS_MISMATCH")
            continue
        if row is None:
            blockers.append(f"{run.candidate_id}:MEASUREMENT_UNAVAILABLE")
            continue
        if (row.playbook != PLAYBOOK or row.measurement.candidate != candidate
                or row.measurement.candidate.candidate_id != run.candidate_id):
            raise RecordError("ORB5 measurement does not match its frozen candidate run")
        if reference_disabled is None:
            reference_disabled = row.disabled_rules
        elif row.disabled_rules != reference_disabled:
            blockers.append(f"{run.candidate_id}:DISABLED_RULE_LABELS_MISMATCH")
        measured.append(row)
    if blockers:
        return Orb5Stage1Comparison(
            COMPARISON_VERSION, "NOT_RANKABLE", canonical, (), None, None,
            tuple(dict.fromkeys(blockers)),
        )

    ranked = tuple(sorted(measured, key=_ranking_key))
    winning: TrainingMeasurement = rank_training_candidates(
        tuple(row.measurement for row in measured))
    winner = next(row for row in ranked if row.measurement == winning)
    winning_run = canonical[winner.measurement.candidate.table_order]
    accepted = AcceptedStage1Winner(
        PLAYBOOK, winner, tuple(measured),
        tuple(event.stage2_event() for event in winning_run.events),
    )
    return Orb5Stage1Comparison(
        COMPARISON_VERSION, "RANKED", canonical, ranked, winner, accepted, (),
    )


__all__ = [
    "COMPARISON_VERSION", "Orb5CandidateStage1Run", "Orb5Stage1Comparison",
    "Orb5Stage1Event", "PLAYBOOK", "RUN_VERSION", "REQUIRED_DISABLED_RULES",
    "compare_orb5_stage1",
    "run_orb5_candidate_stage1",
]
