"""M9.1AB: `CRVOL_ORB5` gate coverage on bars, stop/target geometry, and the walk.

Gate coverage (D-104). One-minute bars can honestly drive only the boundary
crossing (`find_orb5_crossing`). Every other trigger gate is recorded OFF and
untested for a bar-only run, never approximated: acceptance (needs 1 Hz samples
inside 10-30 seconds), participation (TAPE intensity needs 15-second prints;
the projected-volume reference needs prior-day bars), last trade beyond the
boundary, and the M6.1 eligibility gates (need quote and status inputs).

Geometry is `STOP_FAR_OR_EDGE_V2` from the frozen candidate: ORL - 0.05*ATR for
a long and ORH + 0.05*ATR for a short, rounded outward to the caller's tick.
An unknown tick gives no geometry. Targets are the fixed `EXIT_FIXED_2R_V2` /
`EXIT_FIXED_3R_V2` prices E +/- kR from the caller's entry and the frozen stop.
The entry price and time are supplied: bars cannot give the D-106 0-30 second
quote-based fill, so the caller states its source and this module never picks
one. A stop that is not strictly adverse gives no geometry.

The walk reads ready bars that start at or after the entry time. A bar touching
the stop is a stop even when it also touches the target; a bar that opens beyond
the stop exits at that open. A target is credited at exactly k R. A missing or
non-ready bar before an exit leaves the trade unresolved with a reason, and no
exit by the session close is unresolved: no overnight fill is invented. R is
gross of cost and slippage, which are recorded OFF here.

M9.1AC adds `build_orb5_trade_record`: crossing, geometry and walk for one
direction and one exit, as one per-trade R record. The record carries the
frozen candidate, the bar gate coverage, the caller's stated entry source and
the D-110 label. The entry must not precede the crossing. A missing candidate,
geometry or exit gives an unresolved record with the reason and no R.

M9.1AE adds `build_orb5_quote_filled_record`: the D-106/D-107 entry for one
trade. The alert time is the frozen crossing; `fill_cost_model.model_fill`
takes the first valid trade print in the 0-30 second window and adds the real
half-spread from the quote at that print, modeled slippage and commission. That
modeled price and the print time become the entry. Only the entry side is
costed: no exit quotes are supplied, so the exit-side spread, slippage and
commission are recorded OFF and untested (D-104), and the walk reads bars that
start at or after the print time. No print or quote in the window gives an
unresolved record with the fill status and no R.

M9.1AF adds `build_orb5_structure_exit_record`: the `EXIT_D090_STRUCTURE_V2`
two-unit 50/50 exit. From a caller-supplied structural level catalog, only levels
ahead of the entry count; any level closer than 1.5R suppresses the trade (the
D-090 <1R veto plus the 1R-1.5R insufficient-room rule); T1 is the nearest level
at or beyond 1.5R and T2 the next distinct level at or beyond 2.5R, or none. An
incomplete catalog is never read as "no obstacle": the trade is unresolved. T1
closes one unit and T2, else the regular-session close, the other; the stop stays
put after T1 and a stop closes every open unit. On bars a stop-and-target bar is
stop first and a gap through the stop exits at the open. The bar-proxy horizon is
the last regular bar's close, and a missing bar or close leaves the trade
unresolved. R is gross of cost: cost and exit quotes stay OFF (D-104).

No data is fetched, no parameter is searched, and no alert or order occurs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any, Sequence

from .fill_cost_model import FillCostPolicy, ModeledFill, model_fill
from .historical_bars import HistoryBatch
from .orb5_research_adapter import find_orb5_crossing
from .or_failure_rev_research_adapter import _READY, _basis_reason
from .orb5_trigger import FrozenCandidate, TriggerPolicy
from .research_bar_access import research_coverage_at
from .trade_alerts_models import Quote, RecordError
from .utils.time_context import as_utc

STOP_BUFFER_ATR_MULTIPLE = Fraction(5, 100)
EXIT_MULTIPLES = {"EXIT_FIXED_2R_V2": 2, "EXIT_FIXED_3R_V2": 3}

BAR_GATES_ON = ("BOUNDARY_CROSSING",)
BAR_GATES_OFF = (
    ("ACCEPTANCE", "NO_1HZ_SAMPLES_FROM_MINUTE_BARS"),
    ("PARTICIPATION", "NO_15S_TAPE_OR_PRIOR_DAY_REFERENCE_FROM_BARS"),
    ("LAST_TRADE_BEYOND_BOUNDARY", "NO_TRADE_PRINTS_FROM_MINUTE_BARS"),
    ("ELIGIBILITY_ARMED", "NO_QUOTE_OR_STATUS_INPUTS_IN_BAR_SOURCE"),
    ("COST_AND_SLIPPAGE", "NO_QUOTE_SPREAD_IN_BAR_SOURCE"),
)


def bar_gate_coverage() -> dict[str, Any]:
    """Which gates run on bars and which are recorded OFF and untested."""
    return {"on": list(BAR_GATES_ON),
            "off": [{"gate": gate, "reason": reason} for gate, reason in BAR_GATES_OFF],
            "label": "OFF_GATES_UNTESTED_D104"}


@dataclass(frozen=True)
class Orb5Geometry:
    direction: str
    entry: float
    stop: float
    risk: float
    targets: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class Orb5GeometryResult:
    geometry: Orb5Geometry | None
    missing_reason: str | None


def _number(value: object, name: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RecordError(f"{name} must be a finite number")
    return Fraction(str(value))


def build_orb5_geometry(
    candidate: FrozenCandidate, *, entry_price: float | None, tick: float | None,
) -> Orb5GeometryResult:
    """Far-edge stop and fixed 2R/3R targets, or why there is no geometry."""
    if not isinstance(candidate, FrozenCandidate):
        raise RecordError("FrozenCandidate is required")
    if tick is None:
        return Orb5GeometryResult(None, "TICK_UNKNOWN")
    if entry_price is None:
        return Orb5GeometryResult(None, "ENTRY_PRICE_UNAVAILABLE")
    step = _number(tick, "tick")
    entry = _number(entry_price, "entry_price")
    if step <= 0 or entry <= 0:
        raise RecordError("tick and entry price must be positive")
    buffer = STOP_BUFFER_ATR_MULTIPLE * _number(candidate.frozen_atr, "frozen_atr")
    if candidate.direction == "LONG":
        raw = _number(candidate.opening_range_low, "low") - buffer
        stop = Fraction(math.floor(raw / step)) * step
        risk = entry - stop
    else:
        raw = _number(candidate.opening_range_high, "high") + buffer
        stop = Fraction(math.ceil(raw / step)) * step
        risk = stop - entry
    if risk <= 0:
        return Orb5GeometryResult(None, "STOP_NOT_ADVERSE_TO_ENTRY")
    sign = 1 if candidate.direction == "LONG" else -1
    targets = tuple((name, float(entry + sign * k * risk)) for name, k in EXIT_MULTIPLES.items())
    return Orb5GeometryResult(
        Orb5Geometry(candidate.direction, float(entry), float(stop), float(risk), targets), None)


@dataclass(frozen=True)
class Orb5WalkResult:
    status: str  # STOP, TARGET or UNRESOLVED
    exit_name: str
    r_multiple: float | None
    exit_time: datetime | None
    reason: str | None
    bars_read: int
    label: dict[str, Any] | None


def walk_orb5_trade(
    geometry: Orb5Geometry, *, exit_name: str, entry_time: datetime,
    symbol: str, minute_history: HistoryBatch | None,
) -> Orb5WalkResult:
    """First stop or fixed-R target touch on bars from the entry time to the close."""
    if not isinstance(geometry, Orb5Geometry):
        raise RecordError("Orb5Geometry is required")
    if exit_name not in EXIT_MULTIPLES:
        raise RecordError("exit must be EXIT_FIXED_2R_V2 or EXIT_FIXED_3R_V2")
    entry_at = as_utc(entry_time)
    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        return Orb5WalkResult("UNRESOLVED", exit_name, None, None, reason, 0, None)
    research = research_coverage_at(minute_history, as_utc(minute_history.request.end))
    label = research.label()
    sign = 1 if geometry.direction == "LONG" else -1
    stop = Fraction(str(geometry.stop))
    risk = Fraction(str(geometry.risk))
    target = Fraction(str(dict(geometry.targets)[exit_name]))
    read = 0
    for item in sorted(research.coverage.intervals, key=lambda row: row.interval.start):
        if item.interval.start < entry_at:
            continue
        bar = item.bar
        if bar is None or item.status not in _READY:
            return Orb5WalkResult("UNRESOLVED", exit_name, None, None,
                                  "COVERAGE_GAP_BEFORE_EXIT", read, label)
        read += 1
        if bar.certified_no_trade or bar.high is None or bar.low is None:
            continue
        adverse = Fraction(str(bar.low if sign > 0 else bar.high))
        favorable = Fraction(str(bar.high if sign > 0 else bar.low))
        if sign * (adverse - stop) <= 0:
            opened = Fraction(str(bar.open)) if bar.open is not None else stop
            fill = opened if sign * (opened - stop) < 0 else stop
            return Orb5WalkResult("STOP", exit_name, float(sign * (fill - Fraction(str(geometry.entry))) / risk),
                                  item.interval.end, None, read, label)
        if sign * (favorable - target) >= 0:
            return Orb5WalkResult("TARGET", exit_name, float(EXIT_MULTIPLES[exit_name]),
                                  item.interval.end, None, read, label)
    return Orb5WalkResult("UNRESOLVED", exit_name, None, None,
                          "NO_EXIT_BY_SESSION_CLOSE", read, label)


@dataclass(frozen=True)
class Orb5TradeRecord:
    """One candidate's per-trade R (gross of cost), or why there is none."""

    status: str  # NO_CANDIDATE, NO_GEOMETRY, STOP, TARGET or UNRESOLVED
    direction: str
    exit_name: str
    r_multiple: float | None
    reason: str | None
    candidate: FrozenCandidate | None
    geometry: Orb5Geometry | None
    walk: Orb5WalkResult | None
    entry_source: str
    gate_coverage: dict[str, Any]
    label: dict[str, Any] | None

    @property
    def resolved(self) -> bool:
        return self.r_multiple is not None


def build_orb5_trade_record(
    *,
    policy: TriggerPolicy,
    direction: str,
    exit_name: str,
    symbol: str,
    instrument_type: str,
    opening_range_minutes: int,
    search_minutes: int,
    latest_atr: float | None,
    tick: float | None,
    entry_price: float | None,
    entry_time: datetime | None,
    entry_source: str,
    minute_history: HistoryBatch | None,
    record_id_prefix: str,
) -> Orb5TradeRecord:
    """Crossing to geometry to walk for one direction and one fixed-R exit."""
    if exit_name not in EXIT_MULTIPLES:
        raise RecordError("exit must be EXIT_FIXED_2R_V2 or EXIT_FIXED_3R_V2")
    if not isinstance(entry_source, str) or not entry_source.strip():
        raise RecordError("entry source must be stated")
    coverage = bar_gate_coverage()

    def record(status, reason, *, candidate=None, geometry=None, walk=None, label=None):
        return Orb5TradeRecord(
            status, direction, exit_name, None if walk is None else walk.r_multiple,
            reason, candidate, geometry, walk, entry_source, coverage, label)

    search = find_orb5_crossing(
        policy=policy, direction=direction, symbol=symbol, instrument_type=instrument_type,
        opening_range_minutes=opening_range_minutes, search_minutes=search_minutes,
        latest_atr=latest_atr, minute_history=minute_history, record_id_prefix=record_id_prefix)
    candidate = search.candidate
    if candidate is None:
        return record("NO_CANDIDATE", search.missing_reason, label=search.label)
    if entry_time is None:
        return record("UNRESOLVED", "ENTRY_TIME_UNAVAILABLE", candidate=candidate, label=search.label)
    if as_utc(entry_time) < as_utc(candidate.crossed_at):
        raise RecordError("entry time must not precede the crossing")
    built = build_orb5_geometry(candidate, entry_price=entry_price, tick=tick)
    if built.geometry is None:
        return record("NO_GEOMETRY", built.missing_reason, candidate=candidate, label=search.label)
    walk = walk_orb5_trade(
        built.geometry, exit_name=exit_name, entry_time=entry_time, symbol=symbol,
        minute_history=minute_history)
    return record(walk.status, walk.reason, candidate=candidate, geometry=built.geometry,
                  walk=walk, label=walk.label or search.label)


QUOTE_FILL_ENTRY_SOURCE = "D106_D107_QUOTE_FILL"
EXIT_SIDE_COST_OFF = ("EXIT_SIDE_COST", "NO_EXIT_QUOTES_SUPPLIED")


@dataclass(frozen=True)
class Orb5QuoteFilledRecord:
    """A trade record whose entry is the D-106/D-107 modeled fill, if there is one."""

    status: str  # the trade record status, or NO_FILL
    reason: str | None
    fill: ModeledFill | None
    record: Orb5TradeRecord
    cost_scope: dict[str, Any]

    @property
    def resolved(self) -> bool:
        return self.record.resolved


def build_orb5_quote_filled_record(
    *,
    policy: TriggerPolicy,
    fill_policy: FillCostPolicy,
    direction: str,
    exit_name: str,
    symbol: str,
    instrument_type: str,
    opening_range_minutes: int,
    search_minutes: int,
    latest_atr: float | None,
    tick: float | None,
    trades: Sequence[Quote],
    quotes: Sequence[Quote],
    minute_history: HistoryBatch | None,
    record_id_prefix: str,
) -> Orb5QuoteFilledRecord:
    """One trade with a 0-30 second quote-based entry fill and entry-side cost."""
    common = dict(
        policy=policy, direction=direction, exit_name=exit_name, symbol=symbol,
        instrument_type=instrument_type, opening_range_minutes=opening_range_minutes,
        search_minutes=search_minutes, latest_atr=latest_atr, tick=tick,
        minute_history=minute_history, record_id_prefix=record_id_prefix)
    scope = {"entry_side_cost": "SPREAD_SLIPPAGE_COMMISSION",
             "off": [{"gate": EXIT_SIDE_COST_OFF[0], "reason": EXIT_SIDE_COST_OFF[1]}],
             "label": "OFF_GATES_UNTESTED_D104"}
    search = find_orb5_crossing(
        policy=policy, direction=direction, symbol=symbol, instrument_type=instrument_type,
        opening_range_minutes=opening_range_minutes, search_minutes=search_minutes,
        latest_atr=latest_atr, minute_history=minute_history, record_id_prefix=record_id_prefix)
    if search.candidate is None:
        record = build_orb5_trade_record(
            **common, entry_price=None, entry_time=None, entry_source=QUOTE_FILL_ENTRY_SOURCE)
        return Orb5QuoteFilledRecord(record.status, record.reason, None, record, scope)
    fill = model_fill(alert_time=search.candidate.crossed_at, direction=direction,
                      trades=trades, quotes=quotes, policy=fill_policy)
    if fill.status != "FILLED":
        record = build_orb5_trade_record(
            **common, entry_price=None, entry_time=None, entry_source=QUOTE_FILL_ENTRY_SOURCE)
        return Orb5QuoteFilledRecord("NO_FILL", fill.status, fill, record, scope)
    record = build_orb5_trade_record(
        **common, entry_price=fill.modeled_price, entry_time=fill.trade_print_time,
        entry_source=QUOTE_FILL_ENTRY_SOURCE)
    return Orb5QuoteFilledRecord(record.status, record.reason, fill, record, scope)


STRUCTURE_EXIT = "EXIT_D090_STRUCTURE_V2"
T1_MIN_R = Fraction(3, 2)
T2_MIN_R = Fraction(5, 2)


@dataclass(frozen=True)
class Orb5Targets:
    status: str  # SELECTED, SUPPRESSED_NEAR_LEVEL, NO_T1 or CATALOG_INCOMPLETE
    t1: float | None
    t2: float | None
    labels: dict[float, tuple[str, ...]]


def select_orb5_structure_targets(
    geometry: Orb5Geometry, levels: Sequence[tuple[str, float]], *, catalog_complete: bool,
) -> Orb5Targets:
    """D-090 T1/T2 from levels ahead of entry; labels merge on equal prices."""
    if not isinstance(geometry, Orb5Geometry):
        raise RecordError("Orb5Geometry is required")
    if not catalog_complete:
        return Orb5Targets("CATALOG_INCOMPLETE", None, None, {})
    sign = 1 if geometry.direction == "LONG" else -1
    entry, risk = Fraction(str(geometry.entry)), Fraction(str(geometry.risk))
    grouped: dict[Fraction, list[str]] = {}
    for name, price in levels:
        if not isinstance(name, str) or not name.strip():
            raise RecordError("level label is required")
        value = _number(price, "level price")
        if sign * (value - entry) > 0:
            grouped.setdefault(value, []).append(name)
    labels = {float(p): tuple(sorted(n)) for p, n in grouped.items()}
    ordered = sorted(grouped, key=lambda p: sign * (p - entry))
    if ordered and sign * (ordered[0] - entry) < T1_MIN_R * risk:
        return Orb5Targets("SUPPRESSED_NEAR_LEVEL", None, None, labels)
    if not ordered:
        return Orb5Targets("NO_T1", None, None, labels)
    t1 = ordered[0]
    t2 = next((p for p in ordered if sign * (p - t1) > 0 and sign * (p - entry) >= T2_MIN_R * risk), None)
    return Orb5Targets("SELECTED", float(t1), None if t2 is None else float(t2), labels)


@dataclass(frozen=True)
class Orb5StructureExitRecord:
    """Two-unit result: per-unit exits, or why the trade has no R."""

    status: str  # NO_CANDIDATE, NO_GEOMETRY, NO_TARGETS, STOP, T1_THEN_STOP, TARGET, HORIZON or UNRESOLVED
    reason: str | None
    r_multiple: float | None
    targets: Orb5Targets | None
    unit_exits: tuple[tuple[str, float, datetime], ...]
    record: Orb5TradeRecord
    cost_scope: dict[str, Any]

    @property
    def resolved(self) -> bool:
        return self.r_multiple is not None


def walk_orb5_structure_exit(
    geometry: Orb5Geometry, targets: Orb5Targets, *, entry_time: datetime,
    symbol: str, minute_history: HistoryBatch | None,
) -> tuple[str, str | None, float | None, tuple[tuple[str, float, datetime], ...], dict[str, Any] | None]:
    """Walk bars: T1 closes unit one, T2 or the session close unit two, stop closes the rest."""
    if targets.status != "SELECTED" or targets.t1 is None:
        raise RecordError("selected targets are required")
    entry_at = as_utc(entry_time)
    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        return "UNRESOLVED", reason, None, (), None
    end = as_utc(minute_history.request.end)
    research = research_coverage_at(minute_history, end)
    label = research.label()
    sign = 1 if geometry.direction == "LONG" else -1
    entry = Fraction(str(geometry.entry))
    stop = Fraction(str(geometry.stop))
    t1 = Fraction(str(targets.t1))
    t2 = None if targets.t2 is None else Fraction(str(targets.t2))
    exits: list[tuple[str, Fraction, datetime]] = []
    last_close: tuple[Fraction, datetime] | None = None

    def finish(status, why):
        if len(exits) < 2:
            return "UNRESOLVED", why, None, tuple((n, float(p), t) for n, p, t in exits), label
        total = sum(sign * (p - entry) for _, p, _ in exits) / (2 * Fraction(str(geometry.risk)))
        return status, None, float(total), tuple((n, float(p), t) for n, p, t in exits), label

    for item in sorted(research.coverage.intervals, key=lambda row: row.interval.start):
        if item.interval.start < entry_at:
            continue
        bar = item.bar
        if bar is None or item.status not in _READY:
            return finish("UNRESOLVED", "COVERAGE_GAP_BEFORE_EXIT")
        if bar.certified_no_trade or bar.high is None or bar.low is None:
            last_close = None
            continue
        if bar.close is not None:
            last_close = (Fraction(str(bar.close)), item.interval.end)
        adverse = Fraction(str(bar.low if sign > 0 else bar.high))
        favorable = Fraction(str(bar.high if sign > 0 else bar.low))
        if sign * (adverse - stop) <= 0:
            opened = Fraction(str(bar.open)) if bar.open is not None else stop
            fill = opened if sign * (opened - stop) < 0 else stop
            while len(exits) < 2:
                exits.append(("STOP", fill, item.interval.end))
            return finish("T1_THEN_STOP" if exits[0][0] == "T1" else "STOP", None)
        if not exits and sign * (favorable - t1) >= 0:
            exits.append(("T1", t1, item.interval.end))
        if exits and len(exits) < 2 and t2 is not None and sign * (favorable - t2) >= 0:
            exits.append(("T2", t2, item.interval.end))
        if len(exits) == 2:
            return finish("TARGET", None)
    if last_close is None or last_close[1] != end:
        return finish("UNRESOLVED", "NO_HORIZON_CLOSE_BAR")
    exits.append(("HORIZON", last_close[0], last_close[1]))
    if len(exits) == 1:
        exits.append(("HORIZON", last_close[0], last_close[1]))
    return finish("HORIZON", None)


def build_orb5_structure_exit_record(
    *,
    policy: TriggerPolicy,
    direction: str,
    symbol: str,
    instrument_type: str,
    opening_range_minutes: int,
    search_minutes: int,
    latest_atr: float | None,
    tick: float | None,
    entry_price: float | None,
    entry_time: datetime | None,
    entry_source: str,
    levels: Sequence[tuple[str, float]],
    catalog_complete: bool,
    minute_history: HistoryBatch | None,
    record_id_prefix: str,
) -> Orb5StructureExitRecord:
    """Crossing, geometry, D-090 targets and the two-unit walk for one trade."""
    if not isinstance(entry_source, str) or not entry_source.strip():
        raise RecordError("entry source must be stated")
    scope = {"cost": "GROSS_OF_COST",
             "off": [{"gate": "COST_AND_SLIPPAGE", "reason": "NO_EXIT_QUOTES_SUPPLIED"}],
             "horizon": "LAST_REGULAR_BAR_CLOSE_PROXY",
             "label": "OFF_GATES_UNTESTED_D104"}
    coverage = bar_gate_coverage()

    def out(status, reason, *, targets=None, units=(), r=None, candidate=None, geometry=None, label=None):
        record = Orb5TradeRecord(
            status if status in ("NO_CANDIDATE", "NO_GEOMETRY") else "UNRESOLVED" if r is None else status,
            direction, STRUCTURE_EXIT, r, reason, candidate, geometry, None, entry_source, coverage, label)
        return Orb5StructureExitRecord(status, reason, r, targets, units, record, scope)

    search = find_orb5_crossing(
        policy=policy, direction=direction, symbol=symbol, instrument_type=instrument_type,
        opening_range_minutes=opening_range_minutes, search_minutes=search_minutes,
        latest_atr=latest_atr, minute_history=minute_history, record_id_prefix=record_id_prefix)
    candidate = search.candidate
    if candidate is None:
        return out("NO_CANDIDATE", search.missing_reason, label=search.label)
    if entry_time is None:
        return out("UNRESOLVED", "ENTRY_TIME_UNAVAILABLE", candidate=candidate, label=search.label)
    if as_utc(entry_time) < as_utc(candidate.crossed_at):
        raise RecordError("entry time must not precede the crossing")
    built = build_orb5_geometry(candidate, entry_price=entry_price, tick=tick)
    if built.geometry is None:
        return out("NO_GEOMETRY", built.missing_reason, candidate=candidate, label=search.label)
    targets = select_orb5_structure_targets(
        built.geometry, levels, catalog_complete=catalog_complete)
    if targets.status != "SELECTED":
        status = "UNRESOLVED" if targets.status == "CATALOG_INCOMPLETE" else "NO_TARGETS"
        return out(status, targets.status, targets=targets, candidate=candidate,
                   geometry=built.geometry, label=search.label)
    status, reason, r, units, label = walk_orb5_structure_exit(
        built.geometry, targets, entry_time=entry_time, symbol=symbol, minute_history=minute_history)
    return out(status, reason, targets=targets, units=units, r=r, candidate=candidate,
               geometry=built.geometry, label=label or search.label)
