"""M9.1H/M9.1I/M9.1J research adapters: `OR_FAILURE_REV` bar-native inputs from real bars.

`OrFailureRevMachine` (`consensus_engine/or_failure_rev.py`) needs a supplied
`Observation` (the tape read used by `LAST_BACK_INSIDE_RANGE`/`DISPLACEMENT_FROM_EDGE`)
and a supplied `MinuteClose` (the mandatory-arm confirmation read used by
`FAILURE_CONFIRMATION`) at each evaluation instant. M9.1H built both of those
bar-native reads from real minute bars, mirroring the M9.1E/F/G precedent
exactly -- reuse the already-adopted structures unchanged, only admit
`PROVISIONAL` through D-110.

M9.1I adds the M8.1 `BreakoutExtreme` (`consensus_engine/or_failure_handoff.py`)
and the M8.2 `FailureBar` (`consensus_engine/or_failure_rev.py`), the two inputs
that both name "the" failure bar: the real minute bar that produced the break's
own furthest traded price since it crossed the opening range. PLAYBOOKS section
5 gives the stronger trigger as "below failure-bar low" for a failed upside
break -- the mirror-image extreme of the very bar whose opposite side set the
breakout extreme -- so both facts are read from the one bar identified here,
never from two different bars.

M9.1J adds `InsideAcceptance` (`consensus_engine/or_failure_rev.py`), the share
of the failure window spent back inside the range that the `INSIDE_ACCEPTANCE`
gate reads. PLAYBOOKS section 13 leaves "the inside-acceptance window" itself
unresolved, and M0.3B is PROPOSED, so this module adopts no window of its own:
the caller supplies `window_start`/`window_end` exactly as it already supplies
every other threshold to `ReversalPolicy`/`HandoffPolicy`, and this adapter only
computes the real bar-native share inside that caller-named window.

M9.1K adds `ReversalStructural` (the `RISK_TARGETS` gate's own reading), under
the frozen M0.3D section 6 rule: the raw stop is the breakout extreme moved
`0.05 * frozen_ATR_1m` further from entry, rounded outward -- up for a short
reversal, down for a long one -- to a caller-supplied price increment. The
target catalog is built from three real-facing levels: the frozen opening-range
midpoint, the selected as-of session VWAP measured here from real minute bars
up to `evaluated_at` (summed `hlc3 * volume` over every ready traded bar since
the session open, admitting `PROVISIONAL` through D-110 exactly like the
M9.1H/I/J reads), and the opposite opening-range edge. T1 is the nearest level
at least 1.5R ahead of entry in the reversal direction; T2 is the nearest
distinct level beyond it at least 2.5R ahead. An unknown price increment or an
unavailable session VWAP leaves its own dependent piece unavailable rather than
approximated, per D-104: an unpriceable stop reports `risk=None` with its own
`missing_reason`; a VWAP-incomplete catalog reports `risk` (when available) with
an empty `targets` tuple, which the existing `RISK_TARGETS` gate already reads
as `GEOMETRY_TARGETS_UNAVAILABLE`. Neither this module nor the gate it feeds
invents a target, moves a level, or picks an R-multiple beyond what M0.3D
names. `entry_reference` and `breakout_extreme_price` are caller-supplied facts
(the M0.3A entry search and the M9.1I extreme are their own separate producers);
this adapter only measures the stop/target geometry those facts imply.

The remaining `OR_FAILURE_REV` input (the quote decision, which needs a real
bid/ask quote stream this project has no source for and so cannot be derived
from bar-only history at all) and the M8.1 handoff chain's own real-data
adapter still need their own producers and stay open build-scope for a later
M9.1 sub-step.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at` without touching the live
`HistoryBatch`/`HistoryCoverage` contract. This module reuses the untouched
`HistoryBatch.coverage_at` for revision selection and interval status exactly
as the live callers of `Observation`/`MinuteClose`/`BreakoutExtreme`/`FailureBar`
already assume; a `PROVISIONAL` interval counts as ready here, where a live
tape/quote feed would never have produced one in the first place.

For the M9.1H pair, the selected bar is the most recently ended real minute
interval at or before `evaluated_at`; that one bar's close stands for both
reads, exactly as a real single 1-minute-arm feed would report the same current
minute for both its tape print and its minute close. For the M9.1I pair, the
selected bar is the one real minute interval -- among every ready interval that
ended strictly after the supplied crossing and at or before `evaluated_at` --
whose own high (a failed upside break) or low (a failed downside break) is the
furthest from the frozen range; that bar's opposite side is the failure-bar
extreme the stronger trigger reads. `record_id` on each produced object names
this module's own `RESEARCH_OR_FAILURE_REV_V1` origin plus the source bar's own
record ID, so it cannot be mistaken for a live tape/quote record; `TAPE` is
still the correct M6.2 arm name for a trade-derived read, so it is reused
unchanged rather than invented.

No data is fetched, no parameter is searched or chosen, and no order, alert or
delivery action occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any

from .historical_bars import HistoryBatch, IntervalCoverage
from .or_failure_handoff import BreakoutExtreme
from .or_failure_rev import FailureBar, InsideAcceptance, ReversalStructural
from .orb5_trigger import TAPE, MinuteClose, Observation
from .research_bar_access import research_coverage_at
from .trade_alerts_models import RecordError, RiskLevel, TargetLevel
from .utils.time_context import as_utc, session_bounds, session_date_at

RESEARCH_OR_FAILURE_REV_ORIGIN = "RESEARCH_OR_FAILURE_REV_V1"
ACCEPTANCE_DEFINITION_REFERENCE = "RESEARCH_OR_FAILURE_REV_ACCEPTANCE_CALLER_SUPPLIED_WINDOW_V1"
STRUCTURAL_DEFINITION_REFERENCE = "RESEARCH_OR_FAILURE_REV_STRUCTURAL_M03D_SECTION6_V1"
_INSTRUMENT_TYPES = ("EQUITY", "ETF")
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")
_BREAK_DIRECTIONS = ("LONG", "SHORT")
_REVERSAL_DIRECTIONS = ("LONG", "SHORT")


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{name} must be explicit")
    return value


def _basis_reason(batch: HistoryBatch | None, symbol: str) -> str | None:
    if batch is None:
        return "MISSING_MINUTE_HISTORY"
    if batch.request.symbol != symbol:
        return "INCOMPATIBLE_SYMBOL"
    if batch.request.interval != "1m":
        return "INCOMPATIBLE_HISTORY_INTERVAL"
    if batch.conventions.price != "USD_PER_SHARE":
        return "INCOMPATIBLE_PRICE_UNIT"
    if batch.conventions.volume != "SHARES":
        return "INCOMPATIBLE_VOLUME_UNIT"
    unknown = ("", "UNKNOWN", "UNSPECIFIED")
    if any(value.strip().upper() in unknown for value in (
            batch.source, batch.conventions.adjustment_basis, batch.conventions.coverage_basis)):
        return "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    return None


def _latest_ready(intervals: tuple[IntervalCoverage, ...], moment: datetime,
                  ) -> IntervalCoverage | None:
    ended = [item for item in intervals if item.interval.end <= moment and item.bar is not None
             and item.status in _READY]
    return max(ended, key=lambda item: item.interval.end) if ended else None


@dataclass(frozen=True)
class OrFailureRevBarInputs:
    """The bar-derived `Observation`/`MinuteClose` pair and their D-110 label.

    `label` is `ResearchCoverage.label()` for the source history; it is `None`
    only when the history was absent or incompatible before any coverage could
    be computed, exactly as the M9.1E precedent's per-side labels.
    """

    last_trade: Observation
    confirmation_close: MinuteClose
    label: dict[str, Any] | None


def build_or_failure_rev_bar_inputs_from_research(
    *,
    record_id_prefix: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
) -> OrFailureRevBarInputs:
    """Derive one instant's tape observation and minute close from real bars.

    Both reads name the same selected bar; a caller comparing this instant's
    `last_trade.price` against `confirmation_close.close` will find them equal,
    exactly as one supplied minute-bar record standing in for both a real tape
    print and a real minute close should.
    """
    prefix = _label(record_id_prefix, "record ID prefix")
    moment = _instant(evaluated_at, "evaluated_at")
    _label(symbol, "symbol")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")

    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE", mode=TAPE,
            observed_at=moment, available_at=moment, price=None, age_seconds=None,
            coverage_known=False, missing_reason=reason)
        close = MinuteClose(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE", bar_end=moment,
            available_at=moment, close=None, final=False, coverage_known=False)
        return OrFailureRevBarInputs(last_trade=observation, confirmation_close=close, label=None)

    research = research_coverage_at(minute_history, moment)
    label = research.label()
    selected = _latest_ready(research.coverage.intervals, moment)
    if selected is None:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE", mode=TAPE,
            observed_at=moment, available_at=moment, price=None, age_seconds=None,
            coverage_known=False, missing_reason="NO_READY_BAR_BEFORE_EVALUATED_AT")
        close = MinuteClose(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE",
            bar_end=moment, available_at=moment, close=None, final=False, coverage_known=False)
        return OrFailureRevBarInputs(last_trade=observation, confirmation_close=close, label=label)

    bar = selected.bar
    if bar.metadata.instrument_type != instrument_type:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{bar.record_id}", mode=TAPE,
            observed_at=bar.end_time, available_at=bar.end_time, price=None, age_seconds=None,
            coverage_known=True, missing_reason="INCOMPATIBLE_INSTRUMENT_TYPE")
        close = MinuteClose(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{bar.record_id}",
            bar_end=bar.end_time, available_at=bar.end_time, close=None, final=False,
            coverage_known=True)
        return OrFailureRevBarInputs(last_trade=observation, confirmation_close=close, label=label)

    age = (moment - bar.end_time).total_seconds()
    if bar.certified_no_trade or bar.close is None:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{bar.record_id}", mode=TAPE,
            observed_at=bar.end_time, available_at=bar.end_time, price=None, age_seconds=age,
            coverage_known=True, missing_reason="NO_TRADE_AT_LATEST_BAR")
        close = MinuteClose(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{bar.record_id}",
            bar_end=bar.end_time, available_at=bar.end_time, close=None, final=False,
            coverage_known=True)
        return OrFailureRevBarInputs(last_trade=observation, confirmation_close=close, label=label)

    observation = Observation(
        record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{bar.record_id}", mode=TAPE,
        observed_at=bar.end_time, available_at=bar.end_time, price=bar.close, age_seconds=age,
        coverage_known=True)
    close = MinuteClose(
        record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{bar.record_id}",
        bar_end=bar.end_time, available_at=bar.end_time, close=bar.close, final=True,
        coverage_known=True)
    return OrFailureRevBarInputs(last_trade=observation, confirmation_close=close, label=label)


def _extreme_bar(intervals: tuple[IntervalCoverage, ...], crossed_at: datetime, moment: datetime,
                 break_direction: str) -> IntervalCoverage | None:
    """The one ready bar since the crossing whose own extreme is furthest out.

    A bar with no usable high/low (a certified no-trade bar) cannot supply an
    extreme and is excluded rather than treated as a zero excursion.
    """
    candidates = [
        item for item in intervals
        if item.interval.end > crossed_at and item.interval.end <= moment
        and item.bar is not None and item.status in _READY
        and item.bar.high is not None and item.bar.low is not None
    ]
    if not candidates:
        return None
    if break_direction == "LONG":
        return max(candidates, key=lambda item: item.bar.high)
    return min(candidates, key=lambda item: item.bar.low)


@dataclass(frozen=True)
class OrFailureRevExtremeInputs:
    """The bar-derived `BreakoutExtreme`/`FailureBar` pair and their D-110 label.

    Both facts name the same identified failure bar: the extreme is one side of
    it, and the failure-bar's opposite side is the stronger-trigger level.
    `label` is `None` only when the history was absent or incompatible before
    any coverage could be computed, exactly as the M9.1H pair's own label.
    """

    breakout_extreme: BreakoutExtreme
    failure_bar: FailureBar
    label: dict[str, Any] | None


def build_or_failure_rev_extreme_inputs_from_research(
    *,
    record_id_prefix: str,
    crossed_at: datetime,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    break_direction: str,
    minute_history: HistoryBatch | None,
) -> OrFailureRevExtremeInputs:
    """Derive the break's own breakout extreme and its failure bar from real bars.

    The failure bar is identified once, from the break's own furthest traded
    price since it crossed the opening range: for a failed upside break the bar
    with the highest high, for a failed downside break the bar with the lowest
    low. That same bar's opposite side is reported as the failure bar's own
    high/low, so a caller reading `failure_bar.extreme(reversal_direction)` finds
    exactly the level PLAYBOOKS section 5 names as the stronger trigger.
    """
    prefix = _label(record_id_prefix, "record ID prefix")
    crossing = _instant(crossed_at, "crossed_at")
    moment = _instant(evaluated_at, "evaluated_at")
    if crossing > moment:
        raise RecordError("the crossing cannot follow the instant this is evaluated at")
    _label(symbol, "symbol")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")
    if break_direction not in _BREAK_DIRECTIONS:
        raise RecordError("break direction must be LONG or SHORT")

    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        extreme = BreakoutExtreme(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE",
            observed_at=moment, available_at=moment, price=None, coverage_known=False)
        bar = FailureBar(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE", bar_end=moment,
            available_at=moment, high=None, low=None, final=False, coverage_known=False)
        return OrFailureRevExtremeInputs(breakout_extreme=extreme, failure_bar=bar, label=None)

    research = research_coverage_at(minute_history, moment)
    label = research.label()
    selected = _extreme_bar(research.coverage.intervals, crossing, moment, break_direction)
    if selected is None:
        extreme = BreakoutExtreme(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE",
            observed_at=moment, available_at=moment, price=None, coverage_known=True)
        bar = FailureBar(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE", bar_end=moment,
            available_at=moment, high=None, low=None, final=False, coverage_known=True)
        return OrFailureRevExtremeInputs(breakout_extreme=extreme, failure_bar=bar, label=label)

    candle = selected.bar
    if candle.metadata.instrument_type != instrument_type:
        extreme = BreakoutExtreme(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{candle.record_id}",
            observed_at=candle.end_time, available_at=candle.end_time, price=None,
            coverage_known=True)
        bar = FailureBar(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{candle.record_id}",
            bar_end=candle.end_time, available_at=candle.end_time, high=None, low=None,
            final=False, coverage_known=True)
        return OrFailureRevExtremeInputs(breakout_extreme=extreme, failure_bar=bar, label=label)

    price = candle.high if break_direction == "LONG" else candle.low
    extreme = BreakoutExtreme(
        record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{candle.record_id}",
        observed_at=candle.end_time, available_at=candle.end_time, price=price,
        coverage_known=True)
    bar = FailureBar(
        record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{candle.record_id}",
        bar_end=candle.end_time, available_at=candle.end_time, high=candle.high, low=candle.low,
        final=True, coverage_known=True)
    return OrFailureRevExtremeInputs(breakout_extreme=extreme, failure_bar=bar, label=label)


def _window_bars(intervals: tuple[IntervalCoverage, ...], window_start: datetime,
                 window_end: datetime, instrument_type: str) -> list[IntervalCoverage]:
    """Every ready, correctly-typed, traded bar wholly inside the caller's window."""
    return [
        item for item in intervals
        if item.interval.start >= window_start and item.interval.end <= window_end
        and item.status in _READY and item.bar is not None
        and item.bar.metadata.instrument_type == instrument_type
        and item.bar.close is not None
    ]


def _covers_window(usable: list[IntervalCoverage], window_start: datetime,
                   window_end: datetime) -> bool:
    """Whether the usable bars tile the window with no gap, wrong type or no-trade hole."""
    if not usable:
        return False
    ordered = sorted(usable, key=lambda item: item.interval.start)
    if ordered[0].interval.start != window_start or ordered[-1].interval.end != window_end:
        return False
    expected = window_start
    for item in ordered:
        if item.interval.start != expected:
            return False
        expected = item.interval.end
    return True


@dataclass(frozen=True)
class OrFailureRevAcceptanceInputs:
    """The bar-derived `InsideAcceptance` share and its D-110 label.

    `label` is `None` only when the history was absent or incompatible before
    any coverage could be computed, exactly as the M9.1H/M9.1I pairs' own label.
    """

    acceptance: InsideAcceptance
    label: dict[str, Any] | None


def build_or_failure_rev_acceptance_from_research(
    *,
    record_id_prefix: str,
    window_start: datetime,
    window_end: datetime,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    opening_range_low: float,
    opening_range_high: float,
    minute_history: HistoryBatch | None,
) -> OrFailureRevAcceptanceInputs:
    """Derive the real share of a caller-named failure window spent back inside the range.

    Neither `window_start` nor `window_end` is adopted here: PLAYBOOKS section 13
    leaves the inside-acceptance window itself unresolved, so the caller supplies
    both exactly as it already supplies every other `ReversalPolicy` threshold.
    This only reads real minute bars over the caller's own named interval; a bar
    whose close does not lie strictly between the supplied range edges counts
    against the share, and a certified no-trade or wrong-type bar inside the
    window breaks `coverage_complete` rather than being read as a covered minute.
    """
    prefix = _label(record_id_prefix, "record ID prefix")
    start = _instant(window_start, "window_start")
    end = _instant(window_end, "window_end")
    moment = _instant(evaluated_at, "evaluated_at")
    if start >= end:
        raise RecordError("the window must have a positive duration")
    _label(symbol, "symbol")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")
    low, high = float(opening_range_low), float(opening_range_high)
    if not low < high:
        raise RecordError("opening_range_low must be below opening_range_high")

    def missing(reason: str) -> OrFailureRevAcceptanceInputs:
        acceptance = InsideAcceptance(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE",
            definition_reference=ACCEPTANCE_DEFINITION_REFERENCE, available_at=moment,
            share=None, coverage_complete=False, missing_reason=reason)
        return OrFailureRevAcceptanceInputs(acceptance=acceptance, label=None)

    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        return missing(reason)

    observed_end = min(end, moment)
    if observed_end <= start:
        return missing("WINDOW_NOT_YET_STARTED")

    research = research_coverage_at(minute_history, observed_end)
    label = research.label()
    usable = _window_bars(research.coverage.intervals, start, observed_end, instrument_type)
    if not usable:
        acceptance = InsideAcceptance(
            record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE",
            definition_reference=ACCEPTANCE_DEFINITION_REFERENCE, available_at=moment,
            share=None, coverage_complete=False, missing_reason="NO_READY_BAR_IN_WINDOW")
        return OrFailureRevAcceptanceInputs(acceptance=acceptance, label=label)

    inside = sum(1 for item in usable if low < item.bar.close < high)
    share = inside / len(usable)
    coverage_complete = end == observed_end and _covers_window(usable, start, end)
    ids = "-".join(sorted(item.bar.record_id for item in usable))
    acceptance = InsideAcceptance(
        record_id=f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-{ids}",
        definition_reference=ACCEPTANCE_DEFINITION_REFERENCE, available_at=moment,
        share=share, coverage_complete=coverage_complete)
    return OrFailureRevAcceptanceInputs(acceptance=acceptance, label=label)


def _price_value(value: object, name: str, *, positive: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    number = Fraction(str(value))
    if number < 0 or (positive and number <= 0):
        raise RecordError(f"{name} must be a supported price")
    return number


def _session_vwap(intervals: tuple[IntervalCoverage, ...], session_start: datetime,
                  moment: datetime, instrument_type: str) -> tuple[Fraction | None, tuple[str, ...]]:
    """The real hlc3*volume-weighted average over every ready traded bar so far.

    Admits `PROVISIONAL` through D-110 exactly like the M9.1H/I/J reads. Returns
    `(None, ())` when no traded bar of the right type has been observed yet.
    """
    bars = [
        item.bar for item in intervals
        if item.interval.start >= session_start and item.interval.end <= moment
        and item.status in _READY and item.bar is not None
        and item.bar.metadata.instrument_type == instrument_type
        and item.bar.close is not None and item.bar.volume
    ]
    if not bars:
        return None, ()
    volume = sum(Fraction(str(bar.volume)) for bar in bars)
    weighted = sum(
        (Fraction(str(bar.high)) + Fraction(str(bar.low)) + Fraction(str(bar.close)))
        / 3 * Fraction(str(bar.volume)) for bar in bars)
    ids = tuple(sorted(bar.record_id for bar in bars))
    return weighted / volume, ids


def _round_outward(raw: Fraction, increment: Fraction, direction: str) -> Fraction:
    ticks = raw / increment
    if direction == "SHORT":
        count = -(-ticks.numerator // ticks.denominator)
    else:
        count = ticks.numerator // ticks.denominator
    return count * increment


@dataclass(frozen=True)
class OrFailureRevStructuralInputs:
    """The bar-derived `ReversalStructural` reading and its D-110 label.

    `label` is `None` only when the history was absent or incompatible before
    any VWAP coverage could be computed, exactly as the M9.1H/I/J pairs' own
    label; the structural reading itself can still stand on a supplied stop
    alone when only the target catalog is affected.
    """

    structural: ReversalStructural
    label: dict[str, Any] | None


def build_or_failure_rev_structural_from_research(
    *,
    record_id_prefix: str,
    direction: str,
    attempt_number: int,
    crossed_at: datetime,
    evaluated_at: datetime,
    available_at: datetime,
    symbol: str,
    instrument_type: str,
    entry_reference: float,
    breakout_extreme_price: float | None,
    frozen_atr: float,
    price_increment: float | None,
    opening_range_low: float,
    opening_range_high: float,
    minute_history: HistoryBatch | None,
) -> OrFailureRevStructuralInputs:
    """Derive the M0.3D section 6 stop/target geometry from real minute bars.

    `entry_reference` and `breakout_extreme_price` are supplied facts from their
    own producers (the M0.3A entry search and the M9.1I extreme); this only
    measures the stop the frozen ATR pad implies and the target catalog the
    real opening-range midpoint, session VWAP and opposite edge admit.
    """
    prefix = _label(record_id_prefix, "record ID prefix")
    if direction not in _REVERSAL_DIRECTIONS:
        raise RecordError("direction must be LONG or SHORT")
    crossing = _instant(crossed_at, "crossed_at")
    moment = _instant(evaluated_at, "evaluated_at")
    available = _instant(available_at, "available_at")
    _label(symbol, "symbol")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")
    entry = _price_value(entry_reference, "entry_reference", positive=True)
    atr = _price_value(frozen_atr, "frozen_atr")
    low = _price_value(opening_range_low, "opening_range_low", positive=True)
    high = _price_value(opening_range_high, "opening_range_high", positive=True)
    if low >= high:
        raise RecordError("opening_range_low must be below opening_range_high")
    sign = 1 if direction == "LONG" else -1

    def missing(reason: str, *, record_ids: tuple[str, ...] = ()) -> OrFailureRevStructuralInputs:
        structural = ReversalStructural(
            definition_reference=STRUCTURAL_DEFINITION_REFERENCE, direction=direction,
            attempt_number=attempt_number, crossed_at=crossing, evaluated_at=moment,
            available_at=available, risk=None, targets=(), missing_reason=reason,
            record_ids=record_ids or (f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-NONE",))
        return OrFailureRevStructuralInputs(structural=structural, label=None)

    if breakout_extreme_price is None:
        return missing("BREAKOUT_EXTREME_UNAVAILABLE")
    extreme = _price_value(breakout_extreme_price, "breakout_extreme_price", positive=True)
    if price_increment is None:
        return missing("PRICE_INCREMENT_UNKNOWN")
    increment = _price_value(price_increment, "price_increment", positive=True)

    raw_stop = extreme - sign * Fraction(1, 20) * atr
    stop = _round_outward(raw_stop, increment, direction)
    risk_per_share = sign * (entry - stop)
    if stop <= 0 or risk_per_share <= 0:
        return missing("INVALID_STOP_GEOMETRY")

    risk = RiskLevel(
        float(entry), float(stop), float(risk_per_share),
        "M0.3D section 6: breakout extreme moved 0.05 frozen ATR further from "
        "entry, rounded outward to the supplied price increment",
        f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-STOP")

    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        structural = ReversalStructural(
            definition_reference=STRUCTURAL_DEFINITION_REFERENCE, direction=direction,
            attempt_number=attempt_number, crossed_at=crossing, evaluated_at=moment,
            available_at=available, risk=risk, targets=(),
            record_ids=(f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-STOP",))
        return OrFailureRevStructuralInputs(structural=structural, label=None)

    session_start = as_utc(session_bounds(session_date_at(moment))[0])
    research = research_coverage_at(minute_history, moment)
    label = research.label()
    vwap, vwap_ids = _session_vwap(research.coverage.intervals, session_start, moment, instrument_type)

    opposite_edge = high if direction == "LONG" else low
    midpoint = (low + high) / 2
    levels = [("MIDPOINT", midpoint, ())]
    if vwap is not None:
        levels.append(("SESSION_VWAP", vwap, vwap_ids))
    levels.append(("OPPOSITE_EDGE", opposite_edge, ()))

    grouped: dict[Fraction, list[tuple[str, tuple[str, ...]]]] = {}
    for name, price, ids in levels:
        if sign * (price - entry) > 0:
            grouped.setdefault(price, []).append((name, ids))
    ordered = sorted(grouped, key=lambda price: sign * (price - entry))
    first = next((p for p in ordered if sign * (p - entry) >= Fraction(3, 2) * risk_per_share), None)
    targets: tuple[TargetLevel, ...] = ()
    if vwap is not None and first is not None:
        second = next((p for p in ordered if sign * (p - first) > 0
                       and sign * (p - entry) >= Fraction(5, 2) * risk_per_share), None)
        prices = (first,) if second is None else (first, second)
        built = []
        for number, price in enumerate(prices, 1):
            built.append(TargetLevel(
                "T" + str(number), float(price), float(sign * (price - entry) / risk_per_share),
                STRUCTURAL_DEFINITION_REFERENCE))
        targets = tuple(built)

    record_ids = (f"{prefix}-{RESEARCH_OR_FAILURE_REV_ORIGIN}-STOP", *vwap_ids)
    structural = ReversalStructural(
        definition_reference=STRUCTURAL_DEFINITION_REFERENCE, direction=direction,
        attempt_number=attempt_number, crossed_at=crossing, evaluated_at=moment,
        available_at=available, risk=risk, targets=targets, record_ids=record_ids)
    return OrFailureRevStructuralInputs(structural=structural, label=label)


__all__ = [
    "ACCEPTANCE_DEFINITION_REFERENCE", "OrFailureRevAcceptanceInputs", "OrFailureRevBarInputs",
    "OrFailureRevExtremeInputs", "OrFailureRevStructuralInputs", "RESEARCH_OR_FAILURE_REV_ORIGIN",
    "STRUCTURAL_DEFINITION_REFERENCE",
    "build_or_failure_rev_acceptance_from_research",
    "build_or_failure_rev_bar_inputs_from_research",
    "build_or_failure_rev_extreme_inputs_from_research",
    "build_or_failure_rev_structural_from_research",
]
