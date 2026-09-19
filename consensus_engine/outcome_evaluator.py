"""Deterministic supplied-bar outcome evaluation for D-090 O-01 (M5.2).

This module evaluates the approved ``BAR_ONLY_ORB5_O1_PROXY`` study.  It does
not fetch data, estimate sub-minute delays, add costs, place orders, or claim
that the supplied history is representative of live provider coverage.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from fractions import Fraction

from .historical_bars import HistoryBatch
from .trade_alerts_models import (
    AlertCandidate, OutcomeRecord, RecordError, TargetOutcome,
)
from .utils.time_context import as_utc, session_bounds


POLICY_VERSION = "BAR_ONLY_ORB5_O1_PROXY_V1"
_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class UnitExit:
    unit: int
    reason: str
    price: float
    at: datetime


@dataclass(frozen=True)
class BarOutcomeEvaluation:
    outcome: OutcomeRecord
    status_reason: str
    entry_at: datetime | None
    actual_risk: float | None
    original_risk: float | None
    same_bar_ambiguous: bool
    ambiguous_sensitivity: str
    unit_exits: tuple[UnitExit, ...]
    resolved_r: float | None
    original_resolved_r: float | None

    def as_dict(self):
        """Retain the complete evaluation beside the canonical outcome fact."""
        return {
            "evaluation_version": "M52_V1", "outcome": self.outcome.as_dict(),
            "status_reason": self.status_reason,
            "entry_at": self.entry_at.isoformat() if self.entry_at else None,
            "actual_risk": self.actual_risk,
            "original_risk": self.original_risk,
            "same_bar_ambiguous": self.same_bar_ambiguous,
            "ambiguous_sensitivity": self.ambiguous_sensitivity,
            "unit_exits": [{"unit": row.unit, "reason": row.reason,
                            "price": row.price, "at": row.at.isoformat()}
                           for row in self.unit_exits],
            "resolved_r": self.resolved_r,
            "original_resolved_r": self.original_resolved_r,
        }


def _unknown(record_id, candidate, evaluated_at, history, reason):
    return BarOutcomeEvaluation(
        OutcomeRecord(
            record_id=record_id, candidate_id=candidate.record_id,
            evaluated_at=evaluated_at, horizon="SESSION_CLOSE",
            coverage_status="UNRESOLVED", policy_version=POLICY_VERSION,
            alert_price=candidate.alert_price, result="UNKNOWN",
            data_quality="UNAVAILABLE",
            input_record_ids=tuple(bar.record_id for bar in history.bars),
        ), reason, None, None, None, False, "NOT_APPLICABLE", (), None, None,
    )


def evaluate_bar_outcome(
    *, record_id: str, candidate: AlertCandidate, history: HistoryBatch,
    reference_time: datetime, evaluated_at: datetime,
) -> BarOutcomeEvaluation:
    """Evaluate one supplied CRVOL_ORB5 candidate through the session close.

    The next observed minute-bar open strictly after ``reference_time`` is the
    modeled entry.  Missing entry observations may wait no more than 60 seconds.
    Bar opens are evaluated before ranges.  A bar that touches both the stop and
    the next target is resolved stop-first and remains explicitly ambiguous.
    """
    reference_time, evaluated_at = as_utc(reference_time), as_utc(evaluated_at)
    if (not isinstance(candidate, AlertCandidate)
            or candidate.strategy_id != "CRVOL_ORB5"
            or candidate.alert_type != "ACTIONABLE"
            or not candidate.mechanically_valid
            or candidate.risk is None or not candidate.targets):
        raise RecordError("O-01 bar outcomes require a valid actionable CRVOL_ORB5 candidate")
    if len(candidate.targets) > 2 or candidate.targets[0].name != "T1" or (
            len(candidate.targets) == 2 and candidate.targets[1].name != "T2"):
        raise RecordError("O-01 bar outcomes support frozen T1 and optional T2 only")
    if history.request.interval != "1m" or history.request.session_scope != "REGULAR":
        raise RecordError("O-01 bar outcomes require regular-session one-minute history")
    if history.request.symbol != candidate.metadata.instrument_id:
        raise RecordError("outcome history symbol conflicts with candidate")
    bounds = session_bounds(date.fromisoformat(candidate.metadata.session))
    if (bounds is None or as_utc(bounds[0]) != history.request.start
            or as_utc(bounds[1]) != history.request.end):
        raise RecordError("O-01 history must cover the alert's full regular session")
    if not candidate.created_at <= reference_time < history.request.end:
        raise RecordError("outcome reference must be inside the candidate session window")
    if evaluated_at < history.request.end:
        raise RecordError("outcome cannot be evaluated before the session horizon")

    coverage = history.coverage_at(evaluated_at)
    observed = [item.bar for item in coverage.intervals
                if item.status == "FINAL" and item.bar is not None]
    entry_window_end = min(as_utc(bounds[0]) + timedelta(minutes=45), history.request.end)
    eligible = [bar for bar in observed
                if reference_time < bar.start_time <= reference_time + _MINUTE
                and bar.start_time < entry_window_end
                and bar.metadata.available_time < entry_window_end]
    if not eligible:
        return _unknown(record_id, candidate, evaluated_at, history, "ENTRY_WINDOW_UNRESOLVED")
    entry_bar = min(eligible, key=lambda bar: (bar.start_time, bar.record_id))
    entry = entry_bar.open
    assert entry is not None
    sign = 1 if candidate.direction == "LONG" else -1
    stop = candidate.risk.hard_stop
    original_entry = candidate.risk.entry_reference
    original_r = candidate.risk.risk_per_share
    actual_r = sign * (entry - stop)
    t1 = candidate.targets[0]
    # Decimal price text is authoritative. Exact comparisons keep the approved
    # 0.35 extension and 1.5R room boundaries inclusive despite float rounding.
    exact_entry = Fraction(str(entry))
    exact_stop = Fraction(str(stop))
    exact_original_entry = Fraction(str(original_entry))
    exact_original_r = Fraction(str(original_r))
    exact_actual_r = sign * (exact_entry - exact_stop)
    extension = sign * (exact_entry - exact_original_entry) / exact_original_r
    room = (sign * (Fraction(str(t1.price)) - exact_entry) / exact_actual_r
            if exact_actual_r > 0 else Fraction(-1))
    complete = coverage.complete
    input_ids = tuple(bar.record_id for bar in history.bars)
    if (actual_r <= 0 or sign * (entry - candidate.trigger_price) < 0
            or extension > Fraction("0.35") or room < Fraction("1.5")):
        outcome = OutcomeRecord(
            record_id=record_id, candidate_id=candidate.record_id,
            evaluated_at=evaluated_at, horizon="SESSION_CLOSE",
            coverage_status="COMPLETE" if complete else "PARTIAL",
            policy_version=POLICY_VERSION, alert_price=candidate.alert_price,
            modeled_entry_price=None, result="UNFILLED", data_quality="VALID" if complete else "INVALID",
            input_record_ids=input_ids,
        )
        return BarOutcomeEvaluation(outcome, "ENTRY_GEOMETRY_INVALID", entry_bar.start_time,
                                    None, None, False, "NOT_APPLICABLE", (), None, None)

    path = [bar for bar in observed if bar.start_time >= entry_bar.start_time]
    favorable = max(sign * (price - entry) for bar in path
                    for price in (bar.open, bar.high, bar.low, bar.close) if price is not None)
    adverse = max(sign * (entry - price) for bar in path
                  for price in (bar.open, bar.high, bar.low, bar.close) if price is not None)
    exits = []
    remaining = [1, 2]
    target_hits = {target.name: None for target in candidate.targets}
    target_times = {}
    stop_hit = False
    stop_at = None
    ambiguous = False
    next_target = 0

    def exit_stop(price, at):
        nonlocal stop_hit, stop_at
        stop_hit, stop_at = True, at
        exits.extend(UnitExit(unit, "STOP", price, at) for unit in remaining)
        remaining.clear()

    for item in coverage.intervals:
        if item.interval.start < entry_bar.start_time:
            continue
        if not remaining:
            break
        if item.status == "NO_TRADE":
            continue
        if item.status != "FINAL":
            # Later prices cannot establish exits for units exposed to this gap.
            break
        bar = item.bar
        assert bar is not None
        assert bar.open is not None and bar.high is not None and bar.low is not None
        open_stops = sign * (bar.open - stop) <= 0
        if open_stops:
            exit_stop(bar.open, bar.start_time)
            break
        while remaining and next_target < len(candidate.targets):
            target = candidate.targets[next_target]
            if sign * (bar.open - target.price) >= 0:
                target_hits[target.name] = True
                target_times[target.name] = bar.start_time
                exits.append(UnitExit(remaining.pop(0), target.name, target.price, bar.start_time))
                next_target += 1
                if not remaining:
                    break
            else:
                break
        if not remaining:
            break
        low_side, high_side = (bar.low, bar.high) if sign == 1 else (bar.high, bar.low)
        range_stops = sign * (low_side - stop) <= 0
        target = candidate.targets[next_target] if next_target < len(candidate.targets) else None
        range_targets = target is not None and sign * (high_side - target.price) >= 0
        if range_stops and range_targets:
            ambiguous = True
            exit_stop(stop, bar.end_time)
            break
        if range_stops:
            exit_stop(stop, bar.end_time)
            break
        while remaining and target is not None and sign * (high_side - target.price) >= 0:
            target_hits[target.name] = True
            target_times[target.name] = bar.end_time
            exits.append(UnitExit(remaining.pop(0), target.name, target.price, bar.end_time))
            next_target += 1
            target = candidate.targets[next_target] if next_target < len(candidate.targets) else None

    if complete and remaining and path and path[-1].end_time == history.request.end:
        last = path[-1]
        assert last.close is not None
        exits.extend(UnitExit(unit, "HORIZON", last.close, history.request.end) for unit in remaining)
        remaining.clear()
    resolved = complete and not remaining
    for target in candidate.targets:
        if target_hits[target.name] is None and resolved:
            target_hits[target.name] = False
    average_exit = sum(item.price for item in exits) / 2 if len(exits) == 2 else None
    resolved_r = (sum(sign * (item.price - entry) for item in exits) / (2 * actual_r)
                  if len(exits) == 2 else None)
    original_resolved_r = (sum(sign * (item.price - original_entry) for item in exits) / (2 * original_r)
                           if len(exits) == 2 else None)
    outcome = OutcomeRecord(
        record_id=record_id, candidate_id=candidate.record_id,
        evaluated_at=evaluated_at, horizon="SESSION_CLOSE",
        coverage_status="COMPLETE" if complete else "PARTIAL",
        policy_version=POLICY_VERSION, alert_price=candidate.alert_price,
        modeled_entry_price=entry, outcome_price=average_exit,
        mfe=favorable, mae=adverse, max_r=favorable / actual_r,
        stop_hit=stop_hit if resolved else (True if stop_hit else None), stop_hit_at=stop_at,
        target_outcomes=tuple(TargetOutcome(target.name, target_hits[target.name],
                                            target_times.get(target.name))
                              for target in candidate.targets),
        result=("AMBIGUOUS" if ambiguous else "RESOLVED") if resolved else "CENSORED",
        data_quality="VALID" if complete else "INVALID", input_record_ids=input_ids,
    )
    return BarOutcomeEvaluation(outcome, "STOP_FIRST_CONSERVATIVE" if ambiguous else
                                ("RESOLVED" if resolved else "PATH_COVERAGE_INCOMPLETE"),
                                entry_bar.start_time, actual_r, original_r, ambiguous,
                                "UNRESOLVED" if ambiguous else "NOT_APPLICABLE",
                                tuple(exits), resolved_r, original_resolved_r)


__all__ = ["POLICY_VERSION", "UnitExit", "BarOutcomeEvaluation", "evaluate_bar_outcome"]
