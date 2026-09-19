"""Shared D-106/D-107 supplied-history outcome evaluator for M9.1C.

`CRVOL_ORB5` already has its own `BAR_ONLY_ORB5_O1_PROXY` evaluator
(`outcome_evaluator.py`), which enters at the next observed bar open and
carries no cost model. `HOD_COMP_RS`, `OR_FAILURE_REV` and
`FIRST_PULLBACK_VWAP` have none. This module is that missing evaluator,
shared across the three because none of them needs playbook-specific
resolution logic once its composed `risk`/`targets` are supplied: entry uses
`fill_cost_model.model_fill` (D-106's fixed 0-30s post-alert window, real
spread, modeled slippage and commission — never the trigger price, never the
most favorable print), and the remaining path is resolved bar-by-bar from
supplied history exactly like the existing O-01 evaluator's stop-first-
conservative rule, generalized from its fixed two units to one unit per
supplied target.

This module derives no eligibility, trigger or structural input from raw
bars; it evaluates one already-composed risk/target outcome. The remaining
per-playbook adapters from raw `core17_bar_loader` bars into each strategy's
`EligibilityRequest`/`TriggerRequest` inputs are separate, larger, unbuilt
work (see ROADMAP M9.1C/M9.1D). The two D-104 gaps (original
availability/finality; point-in-time membership) are unaffected here and stay
recorded gaps with dependent rules off. No data is fetched, no parameter is
searched or chosen from a result, and no live action occurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from .fill_cost_model import FillCostPolicy, ModeledFill, model_fill
from .historical_bars import HistoryBatch
from .trade_alerts_models import (
    OutcomeRecord, Quote, RecordError, RiskLevel, TargetLevel, TargetOutcome,
)
from .utils.time_context import as_utc

POLICY_VERSION = "M91C_SHARED_D106_D107_OUTCOME_V1"
SUPPORTED_STRATEGIES = frozenset({"HOD_COMP_RS", "OR_FAILURE_REV", "FIRST_PULLBACK_VWAP"})
_DIRECTIONS = frozenset({"LONG", "SHORT"})


@dataclass(frozen=True)
class UnitExit:
    unit: int
    target_name: str
    reason: str
    price: float
    at: datetime


@dataclass(frozen=True)
class PlaybookOutcomeEvaluation:
    outcome: OutcomeRecord
    status_reason: str
    fill: ModeledFill
    actual_risk: float | None
    same_bar_ambiguous: bool
    unit_exits: tuple[UnitExit, ...]
    resolved_r: float | None

    def as_dict(self) -> dict:
        return {
            "evaluation_version": POLICY_VERSION,
            "outcome": self.outcome.as_dict(),
            "status_reason": self.status_reason,
            "fill": self.fill.as_dict(),
            "actual_risk": self.actual_risk,
            "same_bar_ambiguous": self.same_bar_ambiguous,
            "unit_exits": [
                {"unit": row.unit, "target_name": row.target_name, "reason": row.reason,
                 "price": row.price, "at": row.at.isoformat()}
                for row in self.unit_exits
            ],
            "resolved_r": self.resolved_r,
        }


def _unfilled(record_id, candidate_id, evaluated_at, fill: ModeledFill,
              input_ids: tuple[str, ...]) -> PlaybookOutcomeEvaluation:
    outcome = OutcomeRecord(
        record_id=record_id, candidate_id=candidate_id, evaluated_at=evaluated_at,
        horizon="SESSION_CLOSE", coverage_status="UNRESOLVED", policy_version=POLICY_VERSION,
        alert_price=None, result="UNKNOWN", data_quality="UNAVAILABLE",
        input_record_ids=input_ids,
    )
    return PlaybookOutcomeEvaluation(outcome, fill.status, fill, None, False, (), None)


def evaluate_playbook_outcome(
    *, record_id: str, candidate_id: str, strategy_id: str, direction: str,
    risk: RiskLevel, targets: tuple[TargetLevel, ...], alert_time: datetime,
    evaluated_at: datetime, trades: Sequence[Quote], quotes: Sequence[Quote],
    policy: FillCostPolicy, history: HistoryBatch,
) -> PlaybookOutcomeEvaluation:
    """Evaluate one supplied risk/target outcome for a D-106/D-107 fill.

    ``targets`` must already be in exit order (its own strategy's composed
    order); unit ``i`` exits at ``targets[i]`` and no unit may exit before an
    earlier-ordered unit. A bar that touches both a live unit's stop and its
    target resolves stop-first and is reported explicitly ambiguous, exactly
    as the existing O-01 evaluator does.
    """
    if strategy_id not in SUPPORTED_STRATEGIES:
        raise RecordError("this shared evaluator supports only HOD_COMP_RS, "
                          "OR_FAILURE_REV or FIRST_PULLBACK_VWAP")
    if direction not in _DIRECTIONS:
        raise RecordError("direction must be LONG or SHORT")
    if not isinstance(risk, RiskLevel):
        raise RecordError("a playbook outcome requires a composed RiskLevel")
    if not isinstance(targets, tuple) or not targets or any(
            not isinstance(target, TargetLevel) for target in targets):
        raise RecordError("a playbook outcome requires a non-empty tuple of TargetLevel")
    if not isinstance(history, HistoryBatch):
        raise RecordError("a playbook outcome requires a HistoryBatch")
    if history.request.interval != "1m" or history.request.session_scope != "REGULAR":
        raise RecordError("playbook outcomes require regular-session one-minute history")
    alert_time, evaluated_at = as_utc(alert_time), as_utc(evaluated_at)
    if evaluated_at < history.request.end:
        raise RecordError("outcome cannot be evaluated before the session horizon")

    fill = model_fill(alert_time=alert_time, direction=direction, trades=trades,
                       quotes=quotes, policy=policy)
    if fill.status != "FILLED":
        return _unfilled(record_id, candidate_id, evaluated_at, fill, fill.input_record_ids)

    sign = 1 if direction == "LONG" else -1
    entry = fill.modeled_price
    assert entry is not None
    actual_risk = sign * (entry - risk.hard_stop)
    coverage = history.coverage_at(evaluated_at)
    input_ids = tuple(bar.record_id for bar in history.bars) + fill.input_record_ids
    if actual_risk <= 0:
        outcome = OutcomeRecord(
            record_id=record_id, candidate_id=candidate_id, evaluated_at=evaluated_at,
            horizon="SESSION_CLOSE",
            coverage_status="COMPLETE" if coverage.complete else "PARTIAL",
            policy_version=POLICY_VERSION, alert_price=None, modeled_entry_price=entry,
            result="UNFILLED", data_quality="VALID" if coverage.complete else "INVALID",
            input_record_ids=input_ids,
        )
        return PlaybookOutcomeEvaluation(outcome, "ENTRY_GEOMETRY_INVALID", fill, actual_risk,
                                         False, (), None)

    observed = [item.bar for item in coverage.intervals
                if item.status == "FINAL" and item.bar is not None]
    path = [bar for bar in observed if bar.end_time > fill.trade_print_time]
    if not path:
        outcome = OutcomeRecord(
            record_id=record_id, candidate_id=candidate_id, evaluated_at=evaluated_at,
            horizon="SESSION_CLOSE", coverage_status="UNRESOLVED", policy_version=POLICY_VERSION,
            alert_price=None, modeled_entry_price=entry, result="UNKNOWN",
            data_quality="UNAVAILABLE", input_record_ids=input_ids,
        )
        return PlaybookOutcomeEvaluation(outcome, "NO_PATH_AFTER_FILL", fill, actual_risk,
                                         False, (), None)

    favorable = max(sign * (price - entry) for bar in path
                    for price in (bar.open, bar.high, bar.low, bar.close) if price is not None)
    adverse = max(sign * (entry - price) for bar in path
                  for price in (bar.open, bar.high, bar.low, bar.close) if price is not None)

    remaining = list(range(1, len(targets) + 1))
    exits: list[UnitExit] = []
    target_hits = {target.name: None for target in targets}
    target_times: dict[str, datetime] = {}
    stop_hit = False
    stop_at = None
    ambiguous = False
    next_target = 0

    def exit_stop(price, at):
        nonlocal stop_hit, stop_at
        stop_hit, stop_at = True, at
        exits.extend(UnitExit(unit, targets[next_target].name if next_target < len(targets)
                              else targets[-1].name, "STOP", price, at) for unit in remaining)
        remaining.clear()

    for item in coverage.intervals:
        if item.interval.end <= fill.trade_print_time:
            continue
        if not remaining:
            break
        if item.status == "NO_TRADE":
            continue
        if item.status != "FINAL":
            break
        bar = item.bar
        assert bar is not None
        assert bar.open is not None and bar.high is not None and bar.low is not None
        if sign * (bar.open - risk.hard_stop) <= 0:
            exit_stop(bar.open, bar.start_time)
            break
        while remaining and next_target < len(targets):
            target = targets[next_target]
            if sign * (bar.open - target.price) >= 0:
                target_hits[target.name] = True
                target_times[target.name] = bar.start_time
                exits.append(UnitExit(remaining.pop(0), target.name, "TARGET", target.price,
                                       bar.start_time))
                next_target += 1
            else:
                break
        if not remaining:
            break
        low_side, high_side = (bar.low, bar.high) if sign == 1 else (bar.high, bar.low)
        range_stops = sign * (low_side - risk.hard_stop) <= 0
        target = targets[next_target] if next_target < len(targets) else None
        range_targets = target is not None and sign * (high_side - target.price) >= 0
        if range_stops and range_targets:
            ambiguous = True
            exit_stop(risk.hard_stop, bar.end_time)
            break
        if range_stops:
            exit_stop(risk.hard_stop, bar.end_time)
            break
        while remaining and target is not None and sign * (high_side - target.price) >= 0:
            target_hits[target.name] = True
            target_times[target.name] = bar.end_time
            exits.append(UnitExit(remaining.pop(0), target.name, "TARGET", target.price,
                                   bar.end_time))
            next_target += 1
            target = targets[next_target] if next_target < len(targets) else None

    complete = coverage.complete
    if complete and remaining and path and path[-1].end_time == history.request.end:
        last = path[-1]
        assert last.close is not None
        exits.extend(UnitExit(unit, targets[-1].name, "HORIZON", last.close,
                              history.request.end) for unit in remaining)
        remaining.clear()
    resolved = complete and not remaining
    for target in targets:
        if target_hits[target.name] is None and resolved:
            target_hits[target.name] = False

    n = len(targets)
    average_exit = (sum(item.price for item in exits) / n) if len(exits) == n else None
    resolved_r = (sum(sign * (item.price - entry) for item in exits) / (n * actual_risk)
                  if len(exits) == n else None)
    outcome = OutcomeRecord(
        record_id=record_id, candidate_id=candidate_id, evaluated_at=evaluated_at,
        horizon="SESSION_CLOSE", coverage_status="COMPLETE" if complete else "PARTIAL",
        policy_version=POLICY_VERSION, alert_price=None, modeled_entry_price=entry,
        outcome_price=average_exit, mfe=favorable, mae=adverse, max_r=favorable / actual_risk,
        stop_hit=stop_hit if resolved else (True if stop_hit else None), stop_hit_at=stop_at,
        target_outcomes=tuple(TargetOutcome(target.name, target_hits[target.name],
                                            target_times.get(target.name))
                              for target in targets),
        result=("AMBIGUOUS" if ambiguous else "RESOLVED") if resolved else "CENSORED",
        data_quality="VALID" if complete else "INVALID", input_record_ids=input_ids,
    )
    return PlaybookOutcomeEvaluation(
        outcome, "STOP_FIRST_CONSERVATIVE" if ambiguous else
        ("RESOLVED" if resolved else "PATH_COVERAGE_INCOMPLETE"),
        fill, actual_risk, ambiguous, tuple(exits), resolved_r,
    )


__all__ = [
    "POLICY_VERSION", "SUPPORTED_STRATEGIES", "UnitExit", "PlaybookOutcomeEvaluation",
    "evaluate_playbook_outcome",
]
