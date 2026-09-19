"""M9.1Y research adapter: `CRVOL_ORB5` bar-native inputs from real minute bars.

`Orb5TriggerMachine` (`consensus_engine/orb5_trigger.py`) reads supplied tape
`Observation` rows on a fixed grid, one frozen opening range, and a
`TapeIntensity`. This module builds the reads that one-minute bars can honestly
supply and reports the rest as explicit gaps (D-104), never as a proxy:

- `build_orb5_bar_observations`: one TAPE `Observation` per requested grid
  instant. Each carries the close of the latest ready bar that ended at or
  before that instant, with its true age (instant minus bar end). Bars cannot
  show what traded inside a minute, so a fine grid reuses the same close and the
  age grows honestly; the trigger policy's own maximum age then makes older
  samples STALE rather than this module inventing intra-minute prices.
- `opening_range_from_bars`: the opening-range high/low over the first
  `minutes` regular minutes, only when every one of those minutes has a ready
  bar with a high and low. A missing or no-trade minute gives an unavailable
  range with a reason, not a range over the remaining bars.
- `bar_tape_intensity`: always unavailable. The tape-intensity definition needs
  15-second tape prints this project has no source for.

Basis checks (price/volume units, unknown source or venue basis, instrument
type) reuse `or_failure_rev_research_adapter` unchanged, so a batch whose
volume units are UNKNOWN is refused. The loader labels every ticker `ETF`; a
stock session therefore reports INCOMPATIBLE_INSTRUMENT_TYPE when the caller
names it `EQUITY` until that label is corrected in its own step. PROVISIONAL
bars are admitted through D-110 and every output carries its label.

No data is fetched, no parameter is searched or chosen, and no order, alert or
delivery action occurs here.

M9.1AA part 1 adds `find_orb5_crossing`: it walks the bar-native observations
after the opening range, tests each consecutive pair against the buffered
boundary and freezes the first fresh crossing as a `FrozenCandidate`. It stops
there. Eligibility, participation, geometry, fills and per-trade R are not
driven here. The ATR is supplied by the caller (bars of one session cannot give
it); a missing ATR, opening range or basis gives no candidate and a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .historical_bars import HistoryBatch
from .or_failure_rev_research_adapter import (
    _INSTRUMENT_TYPES, _READY, _basis_reason, _instant, _label, _latest_ready,
)
from .orb5_trigger import (
    CROSSED, TAPE, FrozenCandidate, Observation, TapeIntensity, TriggerPolicy,
    candidate_boundary, evaluate_crossing, freeze_candidate,
)
from .research_bar_access import research_coverage_at
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc, session_bounds

RESEARCH_ORB5_ORIGIN = "RESEARCH_ORB5_V1"
INTENSITY_GAP_REFERENCE = "RESEARCH_ORB5_TAPE_INTENSITY_UNAVAILABLE_V1"


@dataclass(frozen=True)
class Orb5OpeningRange:
    """The bar-native opening range, or why it is unavailable."""

    high: float | None
    low: float | None
    minutes: int
    bar_record_ids: tuple[str, ...]
    missing_reason: str | None
    label: dict[str, Any] | None

    @property
    def available(self) -> bool:
        return self.high is not None and self.low is not None


def _unavailable(reason: str, minutes: int, label: dict[str, Any] | None) -> Orb5OpeningRange:
    return Orb5OpeningRange(None, None, minutes, (), reason, label)


def opening_range_from_bars(
    *, symbol: str, instrument_type: str, minutes: int, minute_history: HistoryBatch | None,
) -> Orb5OpeningRange:
    """High/low over the first `minutes` regular minutes; all must be ready bars."""
    _label(symbol, "symbol")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")
    if type(minutes) is not int or minutes < 1:
        raise RecordError("opening range minutes must be a positive whole number")
    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        return _unavailable(reason, minutes, None)
    opened, closed = map(as_utc, _session_of(minute_history))
    range_end = opened + timedelta(minutes=minutes)
    if range_end > closed:
        raise RecordError("opening range cannot extend past the session close")
    research = research_coverage_at(minute_history, range_end)
    label = research.label()
    window = [item for item in research.coverage.intervals
              if item.interval.start >= opened and item.interval.end <= range_end]
    if len(window) != minutes:
        return _unavailable("OPENING_RANGE_INTERVALS_INCOMPLETE", minutes, label)
    bars = []
    for item in sorted(window, key=lambda row: row.interval.start):
        bar = item.bar
        if bar is None or item.status not in _READY:
            return _unavailable("OPENING_RANGE_BAR_NOT_READY", minutes, label)
        if bar.certified_no_trade or bar.high is None or bar.low is None:
            return _unavailable("OPENING_RANGE_MINUTE_HAS_NO_TRADE", minutes, label)
        if bar.metadata.instrument_type != instrument_type:
            return _unavailable("INCOMPATIBLE_INSTRUMENT_TYPE", minutes, label)
        bars.append(bar)
    return Orb5OpeningRange(max(bar.high for bar in bars), min(bar.low for bar in bars),
                            minutes, tuple(bar.record_id for bar in bars), None, label)


def _session_of(batch: HistoryBatch) -> tuple[datetime, datetime]:
    return batch.request.start, batch.request.end


def build_orb5_bar_observations(
    *,
    record_id_prefix: str,
    instants: tuple[datetime, ...],
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
) -> tuple[tuple[Observation, ...], dict[str, Any] | None]:
    """One TAPE observation per instant from the latest ready bar, plus the D-110 label."""
    prefix = _label(record_id_prefix, "record ID prefix")
    _label(symbol, "symbol")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")
    if not isinstance(instants, tuple) or not instants:
        raise RecordError("instants must be a non-empty tuple")
    moments = tuple(_instant(item, "instant") for item in instants)
    if len(set(moments)) != len(moments):
        raise RecordError("instants must be unique")

    reason = _basis_reason(minute_history, symbol)
    label = None
    research = None
    if reason is None:
        research = research_coverage_at(minute_history, max(moments))
        label = research.label()
    rows = []
    for index, moment in enumerate(moments):
        record = f"{prefix}-{RESEARCH_ORB5_ORIGIN}-{index}"
        missing = reason
        bar = None
        if missing is None:
            selected = _latest_ready(research.coverage.intervals, moment)
            if selected is None:
                missing = "NO_READY_BAR_BEFORE_INSTANT"
            else:
                bar = selected.bar
                if bar.metadata.instrument_type != instrument_type:
                    missing = "INCOMPATIBLE_INSTRUMENT_TYPE"
                elif bar.certified_no_trade or bar.close is None:
                    missing = "NO_TRADE_AT_LATEST_BAR"
        if missing is not None:
            rows.append(Observation(
                record_id=record, mode=TAPE, observed_at=moment, available_at=moment,
                price=None, age_seconds=None if bar is None else (moment - bar.end_time).total_seconds(),
                coverage_known=reason is None and bar is not None, missing_reason=missing))
            continue
        rows.append(Observation(
            record_id=f"{record}-{bar.record_id}", mode=TAPE, observed_at=moment,
            available_at=moment, price=bar.close,
            age_seconds=(moment - bar.end_time).total_seconds(), coverage_known=True))
    return tuple(rows), label


def bar_tape_intensity() -> TapeIntensity:
    """Tape intensity needs 15-second tape prints; bars cannot supply it."""
    return TapeIntensity(
        definition_reference=INTENSITY_GAP_REFERENCE, ratio=None, coverage_complete=False,
        missing_reason="NO_15S_TAPE_FROM_MINUTE_BARS")


@dataclass(frozen=True)
class Orb5CrossingSearch:
    """The first frozen crossing in a search window, or why there is none."""

    candidate: FrozenCandidate | None
    missing_reason: str | None
    opening_range: Orb5OpeningRange | None
    instants_examined: int
    label: dict[str, Any] | None


def find_orb5_crossing(
    *,
    policy: TriggerPolicy,
    direction: str,
    symbol: str,
    instrument_type: str,
    opening_range_minutes: int,
    search_minutes: int,
    latest_atr: float | None,
    minute_history: HistoryBatch | None,
    record_id_prefix: str,
    attempt_number: int = 1,
) -> Orb5CrossingSearch:
    """Freeze the first fresh boundary crossing after the opening range, if any."""
    if not isinstance(policy, TriggerPolicy):
        raise RecordError("TriggerPolicy is required")
    if direction not in ("LONG", "SHORT"):
        raise RecordError("direction must be LONG or SHORT")
    if type(search_minutes) is not int or search_minutes < 1:
        raise RecordError("search minutes must be a positive whole number")
    opening = opening_range_from_bars(
        symbol=symbol, instrument_type=instrument_type, minutes=opening_range_minutes,
        minute_history=minute_history)
    if not opening.available:
        return Orb5CrossingSearch(None, opening.missing_reason, opening, 0, opening.label)
    if latest_atr is None:
        return Orb5CrossingSearch(None, "ATR_UNAVAILABLE", opening, 0, opening.label)
    opened, closed = map(as_utc, _session_of(minute_history))
    start = opened + timedelta(minutes=opening_range_minutes)
    end = min(start + timedelta(minutes=search_minutes), closed)
    step = timedelta(seconds=policy.sample_interval_seconds)
    instants = []
    moment = start
    while moment <= end:
        instants.append(moment)
        moment += step
    rows, label = build_orb5_bar_observations(
        record_id_prefix=record_id_prefix, instants=tuple(instants), symbol=symbol,
        instrument_type=instrument_type, minute_history=minute_history)
    _, boundary = candidate_boundary(
        policy, direction, opening_range_high=opening.high,
        opening_range_low=opening.low, latest_atr=latest_atr)
    for previous, current in zip(rows, rows[1:]):
        result = evaluate_crossing(
            policy, direction, boundary=boundary, previous=previous, current=current)
        if result.status == CROSSED:
            candidate = freeze_candidate(
                policy, direction=direction, crossed_at=current.observed_at,
                opening_range_high=opening.high, opening_range_low=opening.low,
                latest_atr=latest_atr, anchor_bar_id=current.record_id,
                attempt_number=attempt_number, input_record_ids=result.input_record_ids)
            return Orb5CrossingSearch(candidate, None, opening, len(rows), label)
    return Orb5CrossingSearch(None, "NO_FRESH_CROSSING_IN_SEARCH_WINDOW", opening,
                              len(rows), label)
