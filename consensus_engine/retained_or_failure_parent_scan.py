"""M9.1DD retained parent scan for the frozen OR-failure research arm.

The scan uses only one isolated training session's retained minute bars and
trades.  It applies the frozen M0.3D five-minute range, 0.05-ATR crossing
buffer, 0.10-ATR meaningful excursion and 180-second reacceptance deadline.
Every selected parent is represented by the existing canonical handoff and
reversal-step records.  Missing coverage produces an explicit unavailable
reason; no parent is invented.

This is offline research construction only.  It does not calculate a fill,
return, confidence result or supervised package.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .or_failure_handoff import (
    BreakoutExtreme,
    HandoffPolicy,
    HandoffRequest,
    evaluate_or_failure_handoff,
)
from .historical_bars import HistoryBatch, HistoryRequest
from .opening_range_features import build_opening_range_snapshot
from .search_run_config import TRAINING_TICKERS
from .or_failure_rev_replay import OrFailureRevReplayStep
from .orb5_trigger import (
    TAPE,
    FrozenCandidate,
    MinuteClose,
    TriggerPolicy,
    TriggerRequest,
    evaluate_orb5_trigger,
)
from .retained_candidate_events import CandidateEventInput
from .trade_alerts_models import Quote, RecordError
from .utils.time_context import as_utc, session_bounds

RUN_VERSION = "M91DD_RETAINED_OR_FAILURE_PARENT_SCAN_V2"
DEFINITION_REFERENCE = "M03D_OR_FAILURE_REV_V1"


@dataclass(frozen=True)
class RetainedOrFailureParentScan:
    version: str
    ticker: str
    session: str
    handoff_requests: tuple[HandoffRequest, ...]
    reversal_steps: tuple[OrFailureRevReplayStep, ...]
    source_record_ids: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]


@dataclass(frozen=True)
class TradeCoverage:
    """Supplied interval evidence; never inferred from the presence of trades.

    Retained readers currently supply no such evidence. Synthetic tests may
    supply it to exercise the contract, without qualifying a retained source.
    """

    ticker: str
    session: str
    source: str
    start: datetime
    end: datetime
    available_at: datetime
    input_record_ids: tuple[str, ...]
    complete: bool
    halted: bool | None
    evidence_reference: str

    def __post_init__(self) -> None:
        for name in ("start", "end", "available_at"):
            object.__setattr__(self, name, as_utc(getattr(self, name)))
        if self.start > self.end or self.available_at < self.end:
            raise RecordError("trade coverage times are inconsistent")
        if type(self.complete) is not bool or (self.halted is not None and type(self.halted) is not bool):
            raise RecordError("trade coverage flags must be bool or unknown halt")
        if not self.evidence_reference.strip() or self.evidence_reference.upper() == "UNKNOWN":
            raise RecordError("trade coverage needs an evidence reference")


def _covered_bars(value, start, end, at):
    batch = value.history.batch
    requested = HistoryRequest(value.ticker, start, end)
    if not set(requested.expected_intervals()).issubset(batch.request.expected_intervals()):
        return (), "NOT_REQUESTED"
    overlapping = tuple(bar for bar in batch.bars if bar.start_time < end and bar.end_time > start)
    coverage = HistoryBatch(requested, batch.source, batch.conventions, overlapping).coverage_at(at)
    if not coverage.complete:
        reason = ("UNEXPECTED_RECORD" if coverage.unexpected_record_ids else
                  next(row.status for row in coverage.intervals if row.status not in ("FINAL", "NO_TRADE")))
        return (), reason
    if any(bar.metadata.revision > 0 for bar in coverage.final_bars):
        return (), "REVISION_UNAVAILABLE"
    return coverage.final_bars, None


def _atr_at(value, at):
    end = at.replace(second=0, microsecond=0)
    bars, reason = _covered_bars(value, end - timedelta(minutes=21), end, at)
    if reason or len(bars) != 21 or any(bar.certified_no_trade for bar in bars):
        return None, ()
    previous = Decimal(str(bars[0].close))
    ranges = []
    for bar in bars[1:]:
        high, low = Decimal(str(bar.high)), Decimal(str(bar.low))
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
        previous = Decimal(str(bar.close))
    return sum(ranges, Decimal(0)) / Decimal(20), tuple(bar.record_id for bar in bars)


def _trade_reason(row: Quote, at: datetime) -> str | None:
    if row.metadata.quality != "VALID" or row.status != "VALID" or row.metadata.revision:
        return "TRADE_SOURCE_QUALITY_UNAVAILABLE"
    if row.delayed is not False:
        return "TRADE_DELAY_STATUS_UNAVAILABLE"
    if row.trade_time is None or row.last is None or row.last <= 0:
        return "TRADE_VALUE_UNAVAILABLE"
    if row.metadata.source_time != row.trade_time or row.metadata.available_time > at:
        return "TRADE_NOT_AVAILABLE_AT_OBSERVATION"
    if not 0 <= (at - row.trade_time).total_seconds() <= 3:
        return "TRADE_FRESHNESS_UNAVAILABLE"
    return None


def _tape_covered(value, evidence, start, end, at, ids):
    return any(
        row.ticker == value.ticker and row.session == value.session
        and row.source == value.history.batch.source
        and row.start <= start and row.end >= end and row.available_at <= at
        and row.complete and row.halted is False
        and set(ids).issubset(row.input_record_ids)
        and set(row.input_record_ids).issubset(value.source_record_ids)
        for row in evidence
    )


def scan_retained_or_failure_parents(
    value: CandidateEventInput, *, trade_coverage: tuple[TradeCoverage, ...] = (),
) -> RetainedOrFailureParentScan:
    """Freeze each direction's first crossing; admit only evidenced parents."""
    if not isinstance(value, CandidateEventInput) or value.playbook != "OR_FAILURE_REV":
        raise RecordError("OR_FAILURE_REV CandidateEventInput is required")
    if value.ticker not in TRAINING_TICKERS or not value.decision_moments:
        raise RecordError("scan requires an isolated training ticker and decision moments")
    bars = value.history.batch.bars
    kinds = {bar.metadata.instrument_type for bar in bars}
    if kinds and (len(kinds) != 1 or next(iter(kinds)) not in ("EQUITY", "ETF")):
        raise RecordError("retained bars need one EQUITY or ETF instrument type")
    instrument_type = next(iter(kinds)) if kinds else "EQUITY"
    records = (*bars, *value.trades, *value.quotes)
    if any(row.metadata.instrument_id != value.ticker or row.metadata.session != value.session
           or row.metadata.source != value.history.batch.source
           or row.metadata.instrument_type != instrument_type for row in records):
        raise RecordError("retained records must match the producer ticker, session and source")
    ids = tuple(row.record_id for row in records)
    if len(set(ids)) != len(ids) or not set(ids).issubset(value.source_record_ids):
        raise RecordError("retained source record identities must be unique and preserved")
    try:
        bounds = session_bounds(datetime.fromisoformat(value.session).date())
    except ValueError as exc:
        raise RecordError("retained session must be an ISO date") from exc
    if bounds is None:
        raise RecordError("retained session must be a regular trading session")
    opened = as_utc(bounds[0])
    setup_start, setup_end = opened + timedelta(minutes=5), opened + timedelta(minutes=45)
    latest_evaluation = max(value.decision_moments)

    def unavailable(reason):
        return RetainedOrFailureParentScan(
            RUN_VERSION, value.ticker, value.session, (), (), value.source_record_ids, (reason,))

    opening, reason = _covered_bars(value, opened, setup_start, latest_evaluation)
    if reason:
        return unavailable("OPENING_RANGE_" + reason)
    traded_opening = [bar for bar in opening if not bar.certified_no_trade]
    if not traded_opening:
        return unavailable("OPENING_RANGE_NO_TRADED_BARS")
    range_high = max(Decimal(str(bar.high)) for bar in traded_opening)
    range_low = min(Decimal(str(bar.low)) for bar in traded_opening)
    # Do not filter bad rows and accidentally join observations across a gap.
    trades = tuple(sorted(value.trades, key=lambda row: (row.metadata.available_time, row.record_id)))
    if len(trades) < 2:
        return unavailable("RETAINED_TRADES_UNAVAILABLE")

    handoffs: list[HandoffRequest] = []
    steps: list[OrFailureRevReplayStep] = []
    reasons: list[str] = []
    used_directions: set[str] = set()
    for previous, current in zip(trades, trades[1:]):
        crossed_at = current.metadata.available_time
        if not (setup_start <= crossed_at < setup_end) or crossed_at > latest_evaluation:
            continue
        reason = _trade_reason(previous, previous.metadata.available_time) or _trade_reason(current, crossed_at)
        if reason:
            return unavailable(reason)
        if not _tape_covered(value, trade_coverage, previous.trade_time, current.trade_time,
                             crossed_at, (previous.record_id, current.record_id)):
            return unavailable("TRADE_COVERAGE_OR_HALT_UNAVAILABLE")
        opening_at_cross, reason = _covered_bars(value, opened, setup_start, crossed_at)
        if reason or opening_at_cross != opening:
            return unavailable("OPENING_RANGE_NOT_AVAILABLE_AT_CROSSING")
        atr, atr_ids = _atr_at(value, crossed_at)
        if atr is None or atr <= 0:
            return unavailable("ATR_1M_20_SMA_UNAVAILABLE")
        buffer = max(Decimal("0.01"), Decimal("0.05") * atr)
        candidates = (
            ("LONG", range_high + buffer,
             Decimal(str(previous.last)) < range_high + buffer <= Decimal(str(current.last))),
            ("SHORT", range_low - buffer,
             Decimal(str(previous.last)) > range_low - buffer >= Decimal(str(current.last))),
        )
        for break_direction, boundary, crossed in candidates:
            if not crossed or break_direction in used_directions:
                continue
            # Consume the first crossing even if it fails. Never restart its timer.
            used_directions.add(break_direction)
            deadline = crossed_at + timedelta(seconds=180)
            reaccepted = None
            for end in sorted({bar.end_time for bar in bars
                               if crossed_at < bar.end_time <= deadline and bar.end_time < setup_end}):
                arrivals = sorted({max(end, bar.metadata.available_time) for bar in bars
                                   if bar.end_time == end and bar.metadata.available_time <= deadline
                                   and bar.metadata.available_time < setup_end
                                   and max(end, bar.metadata.available_time) <= latest_evaluation})
                for at in arrivals:
                    covered, reason = _covered_bars(
                        value, crossed_at.replace(second=0, microsecond=0), end, at)
                    if reason:
                        return unavailable("REACCEPTANCE_" + reason)
                    bar = covered[-1]
                    if not bar.certified_no_trade and range_low < Decimal(str(bar.close)) < range_high:
                        reaccepted, evaluated_at = bar, at
                        break
                if reaccepted is not None:
                    break
            if reaccepted is None:
                reasons.append("FIRST_CROSSING_REACCEPTANCE_UNAVAILABLE")
                continue
            path_trades = [row for row in trades
                           if crossed_at <= row.metadata.available_time <= evaluated_at]
            for row in path_trades:
                reason = _trade_reason(row, row.metadata.available_time)
                if reason:
                    return unavailable(reason)
            if not _tape_covered(value, trade_coverage, previous.trade_time, evaluated_at,
                                 evaluated_at, tuple(row.record_id for row in path_trades)):
                return unavailable("TRADE_COVERAGE_OR_HALT_UNAVAILABLE")
            prices = [Decimal(str(row.last)) for row in path_trades]
            extreme = max(prices) if break_direction == "LONG" else min(prices)
            meaningful = (extreme >= range_high + Decimal("0.10") * atr and extreme > boundary
                          if break_direction == "LONG" else
                          extreme <= range_low - Decimal("0.10") * atr and extreme < boundary)
            if not meaningful:
                reasons.append("FIRST_CROSSING_EXCURSION_INSUFFICIENT")
                continue
            candidate = FrozenCandidate(
                crossed_at=crossed_at, direction=break_direction, mode=TAPE,
                attempt_number=1, opening_range_high=float(range_high),
                opening_range_low=float(range_low), frozen_atr=float(atr),
                buffer=float(buffer), boundary=float(boundary),
                anchor_bar_id=opening[-1].record_id,
                input_record_ids=(previous.record_id, current.record_id, *atr_ids),
            )
            trigger_policy = TriggerPolicy(
                RUN_VERSION, DEFINITION_REFERENCE, TAPE, 0.01, 0.05,
                10, 180, 10, 7, 1, 3.0, 0.0, 0, 2, 600.0,
            )
            close = MinuteClose(
                reaccepted.record_id, reaccepted.end_time, reaccepted.metadata.available_time,
                reaccepted.close, reaccepted.is_final, True,
            )
            attempt = evaluate_orb5_trigger(TriggerRequest(
                candidate, trigger_policy, evaluated_at, minute_close=close,
            ))
            opening_range = build_opening_range_snapshot(
                record_id=f"{RUN_VERSION}:{value.ticker}:{value.session}:OPENING_RANGE",
                evaluated_at=crossed_at, symbol=value.ticker,
                instrument_type=instrument_type, minute_history=value.history.batch,
            )
            extreme_row = max(path_trades, key=lambda row: row.last) if break_direction == "LONG" \
                else min(path_trades, key=lambda row: row.last)
            breakout = BreakoutExtreme(
                extreme_row.record_id, extreme_row.trade_time,
                extreme_row.metadata.available_time, float(extreme), True,
            )
            request = HandoffRequest(
                value.ticker, instrument_type, attempt,
                HandoffPolicy(RUN_VERSION, DEFINITION_REFERENCE, 0.10, 180, True),
                evaluated_at, opening_range, breakout, close, False,
            )
            assessment = evaluate_or_failure_handoff(request)
            if assessment.state.substate != "FAILURE_FORMING":
                return unavailable("CANONICAL_HANDOFF_UNAVAILABLE")
            handoffs.append(request)
            steps.append(OrFailureRevReplayStep(
                evaluated_at, assessment, float(extreme), confirmation_close=close,
            ))

    if not handoffs and not reasons:
        reasons.append("NO_COMPLETE_M03D_ENDED_ORB_PARENT")
    return RetainedOrFailureParentScan(
        RUN_VERSION, value.ticker, value.session, tuple(handoffs), tuple(steps),
        value.source_record_ids, tuple(dict.fromkeys(reasons)),
    )


__all__ = [
    "DEFINITION_REFERENCE", "RUN_VERSION", "RetainedOrFailureParentScan", "TradeCoverage",
    "scan_retained_or_failure_parents",
]
