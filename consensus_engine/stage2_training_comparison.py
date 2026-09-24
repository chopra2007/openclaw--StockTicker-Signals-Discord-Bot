"""M9.1CT: connect the four stage-1 winners to the frozen stage-2 boundary.

The caller supplies one accepted winner for each first-four playbook together
with that winner's resolved, fully costed training events.  This module builds
the four solo candidates and ``ALL_FOUR``, applies D-106's one-event-per-
ticker-day-side rule to the combined stream, and uses the frozen training
ranking rule.  It reads no files and never opens a held-out name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Sequence

from .d108_evaluator import TradeResult, evaluate_d108
from .search_run_config import (
    PLAYBOOKS,
    STAGE1_CANDIDATES,
    STAGE2_CANDIDATES,
    TRAINING_TICKERS,
    Candidate,
    TrainingMeasurement,
    rank_training_candidates,
)
from .stage1_training_measurement import (
    POLICY_VERSION,
    ResolvedTrainingTrade,
    Stage1TrainingMeasurement,
)
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc

COMPARISON_VERSION = "M91CT_STAGE2_TRAINING_COMPARISON_V1"
_PLAYBOOK_ORDER = {playbook: order for order, playbook in enumerate(PLAYBOOKS)}


@dataclass(frozen=True)
class Stage2TrainingEvent:
    """One winner trade plus its point-in-time alert timestamp."""

    trade: ResolvedTrainingTrade
    alerted_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.trade, ResolvedTrainingTrade):
            raise RecordError("stage-2 events must contain ResolvedTrainingTrade records")
        alerted_at = as_utc(self.alerted_at)
        if alerted_at > self.trade.closed_at:
            raise RecordError("stage-2 alert time cannot be after the trade close")
        object.__setattr__(self, "alerted_at", alerted_at)


@dataclass(frozen=True)
class AcceptedStage1Winner:
    playbook: str
    measurement: Stage1TrainingMeasurement
    candidate_measurements: tuple[Stage1TrainingMeasurement, ...]
    events: tuple[Stage2TrainingEvent, ...]


@dataclass(frozen=True)
class Stage2CandidateMeasurement:
    candidate: Candidate
    measurement: TrainingMeasurement
    bootstrap_lower_bound: float
    trade_count: int
    week_count: int
    events: tuple[Stage2TrainingEvent, ...]
    disabled_rules_by_playbook: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class Stage2TrainingComparison:
    version: str
    status: str
    winners: tuple[AcceptedStage1Winner, ...]
    measured: tuple[Stage2CandidateMeasurement, ...]
    ranked: tuple[Stage2CandidateMeasurement, ...]
    winner: Stage2CandidateMeasurement | None
    blockers: tuple[str, ...]


def _validate_winners(
    winners: Sequence[AcceptedStage1Winner],
) -> tuple[AcceptedStage1Winner, ...]:
    if len(winners) != len(PLAYBOOKS):
        raise RecordError("one accepted stage-1 winner is required for each first-four playbook")
    by_playbook: dict[str, AcceptedStage1Winner] = {}
    for winner in winners:
        if not isinstance(winner, AcceptedStage1Winner):
            raise RecordError("winners must be AcceptedStage1Winner records")
        if winner.playbook not in PLAYBOOKS or winner.playbook in by_playbook:
            raise RecordError("stage-1 winners must name each frozen playbook exactly once")
        row = winner.measurement
        if (not isinstance(row, Stage1TrainingMeasurement)
                or row.policy_version != POLICY_VERSION
                or row.playbook != winner.playbook):
            raise RecordError("stage-1 winner measurement does not match its playbook")
        if row.evaluated_tickers != TRAINING_TICKERS:
            raise RecordError("stage-2 inputs must retain the complete training-nine scope")
        frozen = STAGE1_CANDIDATES[winner.playbook]
        if row.measurement.candidate not in frozen:
            raise RecordError("stage-1 winner is not in its frozen candidate catalog")
        if len(winner.candidate_measurements) != len(frozen):
            raise RecordError("stage-1 winner needs every frozen candidate measurement")
        measurements_by_candidate = {}
        for candidate_row in winner.candidate_measurements:
            if (not isinstance(candidate_row, Stage1TrainingMeasurement)
                    or candidate_row.policy_version != POLICY_VERSION
                    or candidate_row.playbook != winner.playbook
                    or candidate_row.evaluated_tickers != TRAINING_TICKERS
                    or candidate_row.measurement.candidate not in frozen):
                raise RecordError("stage-1 candidate measurement does not match its frozen grid")
            candidate = candidate_row.measurement.candidate
            if candidate in measurements_by_candidate:
                raise RecordError("duplicate stage-1 candidate measurement")
            measurements_by_candidate[candidate] = candidate_row
        if set(measurements_by_candidate) != set(frozen):
            raise RecordError("stage-1 candidate measurements must cover the frozen grid")
        selected = rank_training_candidates(tuple(
            measurements_by_candidate[candidate].measurement for candidate in frozen))
        if (selected != row.measurement
                or measurements_by_candidate[selected.candidate] != row):
            raise RecordError("supplied stage-1 winner does not win the frozen ranking")
        if any(candidate_row.disabled_rules != row.disabled_rules
               for candidate_row in measurements_by_candidate.values()):
            raise RecordError("stage-1 candidate disabled-rule labels do not match")
        if not winner.events:
            raise RecordError("an accepted stage-1 winner needs resolved training events")
        clusters = set()
        for event in winner.events:
            if not isinstance(event, Stage2TrainingEvent):
                raise RecordError("winner events must be Stage2TrainingEvent records")
            trade = event.trade
            if (trade.playbook != winner.playbook
                    or trade.candidate_id != row.measurement.candidate.candidate_id):
                raise RecordError("stage-2 event does not belong to its stage-1 winner")
            if trade.ticker not in TRAINING_TICKERS:
                raise RecordError("held-out or unknown ticker cannot enter stage 2")
            if not trade.costs_complete:
                raise RecordError("stage-2 R must include every required cost")
            if trade.cluster_key in clusters:
                raise RecordError("a stage-1 winner cannot repeat a ticker-day-side event")
            clusters.add(trade.cluster_key)
        by_playbook[winner.playbook] = winner
    return tuple(by_playbook[playbook] for playbook in PLAYBOOKS)


def _cluster_all_four(
    winners: tuple[AcceptedStage1Winner, ...],
) -> tuple[Stage2TrainingEvent, ...]:
    """Keep the earliest alert in each D-106 ticker-day-side cluster.

    Equal alert times use frozen playbook table order, so the choice does not
    inspect a trade's return or close time.
    """
    chosen: dict[tuple[str, date, str], Stage2TrainingEvent] = {}
    for winner in winners:
        for event in winner.events:
            key = event.trade.cluster_key
            current = chosen.get(key)
            event_key = (event.alerted_at, _PLAYBOOK_ORDER[event.trade.playbook])
            if current is None or event_key < (
                current.alerted_at, _PLAYBOOK_ORDER[current.trade.playbook]
            ):
                chosen[key] = event
    return tuple(sorted(
        chosen.values(),
        key=lambda event: (
            event.alerted_at, event.trade.ticker, event.trade.direction,
            _PLAYBOOK_ORDER[event.trade.playbook], event.trade.input_record_ids,
        ),
    ))


def _measure(
    candidate: Candidate,
    events: tuple[Stage2TrainingEvent, ...],
    winners: tuple[AcceptedStage1Winner, ...],
) -> Stage2CandidateMeasurement:
    detail = evaluate_d108(
        candidate.candidate_id,
        tuple(TradeResult(event.trade.resolved_r, event.trade.closed_at) for event in events),
    )
    recovery = detail.survivability.weeks_to_recover
    measured = TrainingMeasurement(
        candidate=candidate,
        mean_profit_r=detail.profit.mean_r,
        weekly_win_rate=detail.consistency.winning_week_fraction,
        drawdown_recovery_weeks=float("inf") if recovery is None else recovery,
    )
    included = dict(candidate.settings)["playbooks"]
    disabled = tuple(
        (winner.playbook, winner.measurement.disabled_rules)
        for winner in winners if winner.playbook in included
    )
    return Stage2CandidateMeasurement(
        candidate, measured, detail.profit.primary.lower_bound,
        detail.trade_count, detail.consistency.week_count, events, disabled,
    )


def compare_stage2_training(
    winners: Sequence[AcceptedStage1Winner],
) -> Stage2TrainingComparison:
    """Build, measure and rank the five frozen stage-2 candidates."""
    canonical = _validate_winners(winners)
    by_playbook = {winner.playbook: winner for winner in canonical}
    measured = []
    for candidate in STAGE2_CANDIDATES:
        included = dict(candidate.settings)["playbooks"]
        if candidate.candidate_id == "ALL_FOUR":
            events = _cluster_all_four(canonical)
        else:
            events = by_playbook[included[0]].events
        measured.append(_measure(candidate, events, canonical))
    rows = tuple(measured)
    ranked = tuple(sorted(rows, key=lambda row: (
        -row.measurement.mean_profit_r,
        -row.measurement.weekly_win_rate,
        row.measurement.drawdown_recovery_weeks,
        row.candidate.table_order,
    )))
    winning_measurement = rank_training_candidates(tuple(row.measurement for row in rows))
    winner = next(row for row in ranked if row.measurement == winning_measurement)
    return Stage2TrainingComparison(
        COMPARISON_VERSION, "RANKED", canonical, rows, ranked, winner, (),
    )


__all__ = [
    "AcceptedStage1Winner", "COMPARISON_VERSION", "Stage2CandidateMeasurement",
    "Stage2TrainingComparison", "Stage2TrainingEvent", "compare_stage2_training",
]
