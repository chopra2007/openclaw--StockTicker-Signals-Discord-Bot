"""M9.1DE frozen M0.3E impulse-parent scan over supplied session records.

The retained reader does not provide finality, original-availability, daily ATR,
minute ATR or VWAP evidence.  Those gaps therefore produce an explicit
unavailable result.  Synthetic contract records may supply the missing numeric
facts to exercise the exact parent-selection boundary; that does not qualify a
retained source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .first_pullback_vwap_replay import PullbackReplayStep
from .historical_bars import HistoryBatch, HistoryRequest
from .impulse_pullback import PullbackPolicy, build_impulse_pullback_snapshot
from .retained_candidate_events import CandidateEventInput
from .search_run_config import TRAINING_TICKERS
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc, session_bounds

RUN_VERSION = "M91DE_RETAINED_FIRST_PULLBACK_PARENT_SCAN_V1"
DEFINITION_REFERENCE = "M03E_FIRST_PULLBACK_VWAP_V1"


@dataclass(frozen=True)
class ImpulseScanEvidence:
    ticker: str
    session: str
    available_at: datetime
    atr_1m: float
    daily_atr: float
    vwap: float
    input_record_ids: tuple[str, ...]
    evidence_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "available_at", as_utc(self.available_at))
        for name in ("atr_1m", "daily_atr", "vwap"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise RecordError(f"{name} must be a positive number")
        if not self.evidence_reference.strip() or self.evidence_reference.upper() == "UNKNOWN":
            raise RecordError("impulse scan evidence needs an explicit reference")


@dataclass(frozen=True)
class RetainedFirstPullbackParentScan:
    version: str
    ticker: str
    session: str
    pullback_steps: tuple[PullbackReplayStep, ...]
    directions: tuple[str, ...]
    impulse_windows: tuple[tuple[datetime, datetime], ...]
    source_record_ids: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]


def _bars_at(value: CandidateEventInput, at: datetime, through: datetime):
    batch = value.history.batch
    bounds = session_bounds(value.session)
    if bounds is None:
        return (), "NO_REGULAR_SESSION"
    opened, _closed = map(as_utc, bounds)
    request = HistoryRequest(value.ticker, opened, through)
    if not set(request.expected_intervals()).issubset(batch.request.expected_intervals()):
        return (), "IMPULSE_WINDOW_NOT_REQUESTED"
    selected = tuple(bar for bar in batch.bars
                     if bar.start_time < request.end and bar.end_time > request.start)
    coverage = HistoryBatch(request, batch.source, batch.conventions, selected).coverage_at(at)
    if coverage.unexpected_record_ids:
        return (), "IMPULSE_WINDOW_CONFLICT"
    if not coverage.complete:
        status = next(row.status for row in coverage.intervals if row.status not in ("FINAL", "NO_TRADE"))
        return (), "IMPULSE_WINDOW_" + status
    if any(row.status == "NO_TRADE" for row in coverage.intervals):
        return (), "IMPULSE_WINDOW_NO_TRADE"
    bars = tuple(row.bar for row in coverage.intervals)
    if any(bar.metadata.revision > 0 for bar in bars):
        return (), "IMPULSE_WINDOW_REVISION_UNAVAILABLE"
    return bars, None


def _first_direction_parent(bars, direction: str, evidence: ImpulseScanEvidence):
    origin = Decimal(str(bars[0].open))
    atr_1m = Decimal(str(evidence.atr_1m))
    minimum = max(Decimal("0.40") * atr_1m,
                  Decimal("0.15") * Decimal(str(evidence.daily_atr)))
    vwap_gap = Decimal("0.25") * atr_1m
    long = direction == "LONG"
    extreme_index = None
    extreme = None
    for index in range(1, len(bars) - 2):
        candidate = Decimal(str(bars[index].high if long else bars[index].low))
        if extreme is None or (candidate > extreme if long else candidate < extreme):
            extreme, extreme_index = candidate, index
        if extreme_index is None:
            continue
        distance = extreme - origin if long else origin - extreme
        beyond_vwap = extreme - Decimal(str(evidence.vwap)) if long else Decimal(str(evidence.vwap)) - extreme
        if distance < minimum or beyond_vwap < vwap_gap:
            continue
        first, second = bars[extreme_index + 1], bars[extreme_index + 2]
        first_extreme = Decimal(str(first.high if long else first.low))
        second_extreme = Decimal(str(second.high if long else second.low))
        stricter_extreme = ((first_extreme > extreme or second_extreme > extreme) if long
                            else (first_extreme < extreme or second_extreme < extreme))
        if stricter_extreme:
            continue
        closes = (Decimal(str(bars[extreme_index].close)), Decimal(str(first.close)), Decimal(str(second.close)))
        if not (closes[0] > closes[1] > closes[2] if long else closes[0] < closes[1] < closes[2]):
            continue
        return extreme_index, extreme_index + 2
    return None


def scan_retained_first_pullback_parents(
    value: CandidateEventInput, *, evidence: tuple[ImpulseScanEvidence, ...] = (),
) -> RetainedFirstPullbackParentScan:
    if not isinstance(value, CandidateEventInput) or value.playbook != "FIRST_PULLBACK_VWAP":
        raise RecordError("FIRST_PULLBACK_VWAP CandidateEventInput is required")
    if value.ticker not in TRAINING_TICKERS or not value.decision_moments:
        raise RecordError("scan requires an isolated training ticker and decision moments")
    records = (*value.history.batch.bars, *value.trades, *value.quotes)
    if any(row.metadata.instrument_id != value.ticker or row.metadata.session != value.session
           for row in records):
        raise RecordError("scan records must match the producer ticker and session")
    kinds = {bar.metadata.instrument_type for bar in value.history.batch.bars}
    if len(kinds) != 1 or next(iter(kinds)) not in ("EQUITY", "ETF"):
        raise RecordError("retained bars need one EQUITY or ETF instrument type")
    bounds = session_bounds(value.session)
    if bounds is None:
        return RetainedFirstPullbackParentScan(
            RUN_VERSION, value.ticker, value.session, (), (), (), value.source_record_ids,
            ("NO_REGULAR_SESSION",))
    opened, closed = map(as_utc, bounds)
    parents = {}
    unavailable = ("ATR_1M_UNAVAILABLE", "DAILY_ATR_UNAVAILABLE", "VWAP_UNAVAILABLE")
    for at in sorted(set(value.decision_moments)):
        fact = next((row for row in evidence if row.ticker == value.ticker
                     and row.session == value.session and row.available_at <= at
                     and set(row.input_record_ids).issubset(value.source_record_ids)), None)
        if fact is None:
            continue
        unavailable = ("CONFIRMED_IMPULSE_UNAVAILABLE",)
        # An origin, a later extreme and two confirmation bars are required.
        # Check only each possible confirmation prefix, as known at this decision.
        through = opened + timedelta(minutes=4)
        while through <= min(at, closed) and len(parents) < 2:
            bars, reason = _bars_at(value, at, through)
            if reason:
                unavailable = (reason,)
                break  # Every longer first-structure prefix needs these same bars.
            for direction in ("LONG", "SHORT"):
                if direction in parents:
                    continue
                selected = _first_direction_parent(bars, direction, fact)
                if selected is None:
                    continue
                _extreme_index, confirmed_index = selected
                started_at = bars[0].start_time
                frozen_at = bars[confirmed_index - 1].start_time
                policy = PullbackPolicy(
                    RUN_VERSION, DEFINITION_REFERENCE, direction, 1, False)
                snapshot = build_impulse_pullback_snapshot(
                    record_id=f"m91de:{value.ticker}:{value.session}:{direction}",
                    evaluated_at=at, symbol=value.ticker,
                    instrument_type=next(iter(kinds)), minute_history=value.history.batch,
                    policy=policy, impulse_started_at=started_at, impulse_frozen_at=frozen_at,
                    atr_1m=fact.atr_1m, vwap=fact.vwap,
                )
                parents[direction] = (PullbackReplayStep(at, snapshot, fact.atr_1m, 1),
                                      (started_at, frozen_at))
            through += timedelta(minutes=1)
    directions = tuple(direction for direction in ("LONG", "SHORT") if direction in parents)
    return RetainedFirstPullbackParentScan(
        RUN_VERSION, value.ticker, value.session,
        tuple(parents[direction][0] for direction in directions), directions,
        tuple(parents[direction][1] for direction in directions), value.source_record_ids,
        () if parents else unavailable)


__all__ = [
    "DEFINITION_REFERENCE", "RUN_VERSION", "ImpulseScanEvidence",
    "RetainedFirstPullbackParentScan", "scan_retained_first_pullback_parents",
]
