"""M9.1N/M9.1P/M9.1Q research adapters: `FIRST_PULLBACK_VWAP`'s bar-native inputs.

`FIRST_PULLBACK_VWAP`'s `PullbackRequest.relative_strength`
(`first_pullback_vwap.RelativeStrength`) needs one directional reading: the
stock's lookback return against its benchmark's, already oriented so
`_relative_strength` can compare it to the caller's own minimum with a single
sign flip. `rs_trend_eligibility.RsWindowPolicy` already names that exact
stock-return-minus-benchmark-return computation with no adopted number of its
own -- "Nothing here adopts a number", per its own docstring -- and M9.1E's
`hod_comp_rs_research_adapter.build_rs_trend_snapshot_from_research` already
computes it from real, `PROVISIONAL`-admissible bars for `HOD_COMP_RS`. That
computation is playbook-neutral: it is entirely the caller's own supplied
`RsWindowPolicy` (lookback, benchmark, return basis) applied to two supplied
`HistoryBatch`es, so this module reuses it unchanged rather than duplicating
it, and adds no new rule, number or convention of its own.

This was the first `FIRST_PULLBACK_VWAP` sub-step after M9.1M's impulse/
pullback measurement; M9.1P adds the next two: the last-trade `Observation`
(`orb5_trigger.Observation`, the `PRICE_VS_VWAP`/`REVERSAL_BAR_BREAK` tape
read) and the VWAP context (`first_pullback_vwap.VwapContext`), both from real
minute bars, mirroring the M9.1H `OrFailureRevBarInputs` tape-read precedent
and the M9.1G/M9.1K cumulative session-VWAP precedent respectively.

`build_last_trade_from_research` reuses the exact M9.1H basis/selection
pattern (latest ready bar at or before `evaluated_at`, `PROVISIONAL` admitted
through D-110), producing only the `Observation` half of that pair -- this
playbook has no `MinuteClose`-shaped input, so the `MinuteClose` half is not
reproduced. The observation always carries `mode=TAPE`; a caller whose own
`PullbackVwapPolicy.mode` differs (`QUOTE_PROJECTED`) needs a different
producer this module does not build.

`build_vwap_context_from_research` computes the real, volume-weighted
`hlc3`-average VWAP level from every ready traded bar since the regular
session opened through `evaluated_at`, the exact computation
`or_failure_rev_research_adapter._session_vwap` already uses for
`OR_FAILURE_REV`'s own structural target catalog (M9.1K), admitting
`PROVISIONAL` through D-110. PLAYBOOKS section 6 leaves the VWAP slope
convention and the cross-count convention themselves unresolved --
`first_pullback_vwap.py`'s own `UNDEFINED` tuple already names
`VWAP_SLOPE_CONVENTION_UNDEFINED` for exactly this gap -- so no slope or cross
count is computed here; per D-104 this is a recorded gap, not an
approximation, and the produced `VwapContext` always reports `slope=None`,
`crosses=None` and that reason whenever a level is otherwise available. This
still lets `PRICE_VS_VWAP` (`_vwap_side`) evaluate genuinely from a real level
while `VWAP_SLOPE`/`VWAP_CROSSES` stay `UNKNOWN` by name, exactly as
`VwapContext.__post_init__`'s own contract allows a partially known context to
report.

M9.1Q adds the first piece of the structural stop/target
(`first_pullback_vwap.PullbackStructural`): the raw stop, under PLAYBOOKS
section 6 -- `pullback_low - 0.05 * frozen_ATR_1m` for a long continuation,
`pullback_high + 0.05 * frozen_ATR_1m` for a short one -- rounded outward to
the caller's own supplied price increment. `entry_reference` and
`pullback_extreme_price` are caller-supplied facts from their own producers
(the M0.3A entry search and the M8.3 measurement this playbook already reads
unchanged), exactly like `OR_FAILURE_REV`'s `entry_reference`/
`breakout_extreme_price` in `build_or_failure_rev_structural_from_research`
(M9.1K); this reuses that same `extreme -/+ 0.05*ATR` arithmetic and outward-
rounding, reproduced here rather than imported since it is private there. The
target catalog PLAYBOOKS section 6 and the M0.3E packet section 7 describe
(the frozen impulse extreme, regular-session HOD/LOD, prior-day OHLC and
whole/half-dollar levels) needed its own real-bar producer and stayed open
build-scope through M9.1Q, so `targets` was always `()` there; an unpriceable
stop reports `risk=None` with its own `missing_reason` per D-104, never an
approximated number.

M9.1R adds that target catalog, under the exact M0.3E section 7 rule: the
frozen impulse extreme is a caller-supplied fact (the M8.3 measurement, like
`pullback_extreme_price`); regular-session HOD/LOD and prior-day high/low/close
are read here from real minute bars, admitting `PROVISIONAL` through D-110
exactly like `_session_vwap`'s own read for `OR_FAILURE_REV`'s M9.1K catalog;
and known whole-dollar/half-dollar levels strictly between entry and the
furthest of those real levels are generated arithmetically. Keep only levels
ahead in the trade direction, merge exact prices while retaining every label,
and sort by directional distance. T1 is the nearest level at least 1.5R away;
T2 is the nearest distinct later level from 2.5R through 4R. No T1 leaves
`targets=()`, which the existing `RISK_TARGETS` gate already reads as
`GEOMETRY_TARGETS_UNAVAILABLE`, exactly the M9.1K precedent for its own absent
VWAP/T1 case -- this module does not distinguish "known absence" from
"incomplete inputs" beyond that existing reading. The session HOD/LOD and
prior-day OHLC are each computed only when their own real bar window is fully
covered (every expected minute either the current session's read-so-far
window or the entire prior regular session, per `_READY` status); an
incomplete window leaves that source unavailable and, per D-104, the whole
target catalog stays `()` rather than mixing a partial level set silently.

The remaining `FIRST_PULLBACK_VWAP` inputs (the quote decision, which needs a
real bid/ask quote stream this project has no source for and so cannot be
derived at all; and the M4.4 confidence) still need their own producers and
stay open build-scope for a further M9.1 sub-step; `first_pullback_vwap.py`,
`impulse_pullback_research_adapter.py`, `hod_comp_rs_research_adapter.py` and
`or_failure_rev_research_adapter.py` are all untouched.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at`; this module inherits that
admission from the reused M9.1E computation and, for M9.1P's own two
functions, calls `research_coverage_at` directly, without touching the live
`HistoryBatch`/`HistoryCoverage` contract itself. No data is fetched, no
parameter is searched or chosen, and no order, alert or delivery action occurs
here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any

from .first_pullback_vwap import PullbackStructural, RelativeStrength, VwapContext
from .historical_bars import HistoryBatch, IntervalCoverage
from .hod_comp_rs_research_adapter import (
    RS_NAME, build_rs_trend_snapshot_from_research,
)
from .orb5_trigger import TAPE, Observation
from .research_bar_access import research_coverage_at
from .rs_trend_eligibility import RsWindowPolicy
from .trade_alerts_models import RecordError, RiskLevel, TargetLevel
from .utils.time_context import as_utc, session_bounds, session_date_at, session_dates

RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE = "M91N_FIRST_PULLBACK_VWAP_RESEARCH_RS_V1"
RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN = "M91P_FIRST_PULLBACK_VWAP_RESEARCH_LAST_TRADE_V1"
RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE = (
    "M91P_FIRST_PULLBACK_VWAP_RESEARCH_CONTEXT_V1")
RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE = (
    "M91Q_FIRST_PULLBACK_VWAP_RESEARCH_STOP_PLAYBOOKS_SEC6_V1")
RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN = "M91Q_FIRST_PULLBACK_VWAP_RESEARCH_STRUCTURAL_V1"
RESEARCH_FIRST_PULLBACK_VWAP_TARGET_DEFINITION_REFERENCE = (
    "M91R_FIRST_PULLBACK_VWAP_RESEARCH_TARGETS_M03E_SEC7_V1")
VWAP_SLOPE_CONVENTION_UNDEFINED = "VWAP_SLOPE_CONVENTION_UNDEFINED"
_INSTRUMENT_TYPES = ("EQUITY", "ETF")
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")
_DIRECTIONS = ("LONG", "SHORT")


def build_relative_strength_from_research(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
    benchmark_history: HistoryBatch | None,
    policy: RsWindowPolicy,
) -> RelativeStrength:
    """The stock-vs-benchmark lookback return, over real bars, as a `RelativeStrength`.

    Reuses `build_rs_trend_snapshot_from_research`'s exact `RS_LOOKBACK_V1`
    value and reasons unchanged; only the result shape differs, matching
    `first_pullback_vwap.RelativeStrength` instead of a `FeatureSnapshot`.
    `coverage_complete` is true exactly when both the stock's and the
    benchmark's own bar coverage were computed at all (a compatible history was
    supplied and a regular session existed), independent of whether the RS
    value itself could be measured yet (for example, before warm-up); a value
    that could not be measured always carries its own named reason instead.
    """
    moment = as_utc(evaluated_at)
    if not isinstance(record_id, str) or not record_id.strip():
        raise RecordError("relative-strength record_id is required")
    result = build_rs_trend_snapshot_from_research(
        record_id=record_id, evaluated_at=moment, symbol=symbol,
        instrument_type=instrument_type, minute_history=minute_history,
        benchmark_history=benchmark_history, policy=policy,
    )
    rs = next(row for row in result.snapshot.features if row.name == RS_NAME)
    complete = result.stock_label is not None and result.benchmark_label is not None
    if not complete:
        return RelativeStrength(
            record_id=record_id,
            definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE,
            available_at=moment, coverage_complete=False, value=None,
            missing_reason=rs.missing_reason or "RELATIVE_STRENGTH_COVERAGE_INCOMPLETE",
        )
    if rs.value is None:
        return RelativeStrength(
            record_id=record_id,
            definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE,
            available_at=moment, coverage_complete=True, value=None,
            missing_reason=rs.missing_reason,
        )
    return RelativeStrength(
        record_id=record_id,
        definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE,
        available_at=moment, coverage_complete=True, value=rs.value,
    )


def _basis_reason(batch: HistoryBatch | None, symbol: str) -> str | None:
    """Exactly the M9.1H/K basis check, reproduced for this module's own bars."""
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
    """Exactly the M9.1H selection: the newest ready, traded bar at or before `moment`."""
    ended = [item for item in intervals if item.interval.end <= moment and item.bar is not None
             and item.status in _READY]
    return max(ended, key=lambda item: item.interval.end) if ended else None


@dataclass(frozen=True)
class FirstPullbackVwapLastTradeInputs:
    """The bar-derived last-trade `Observation` and its D-110 label.

    `label` is `None` only when the history was absent or incompatible before
    any coverage could be computed, exactly as the M9.1H pair's own label.
    """

    last_trade: Observation
    label: dict[str, Any] | None


def build_last_trade_from_research(
    *,
    record_id_prefix: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
) -> FirstPullbackVwapLastTradeInputs:
    """The newest real minute-bar close at or before `evaluated_at`, as a tape `Observation`.

    Reuses the M9.1H `OrFailureRevBarInputs` tape-read pattern unchanged, minus
    its `MinuteClose` half, which `FIRST_PULLBACK_VWAP` does not need. The
    observation always carries `mode=TAPE`: a caller whose own policy arm is
    `QUOTE_PROJECTED` needs a different producer this module does not build.
    """
    prefix = record_id_prefix
    if not isinstance(prefix, str) or not prefix.strip():
        raise RecordError("record ID prefix is required")
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")

    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN}-NONE",
            mode=TAPE, observed_at=moment, available_at=moment, price=None, age_seconds=None,
            coverage_known=False, missing_reason=reason)
        return FirstPullbackVwapLastTradeInputs(last_trade=observation, label=None)

    research = research_coverage_at(minute_history, moment)
    label = research.label()
    selected = _latest_ready(research.coverage.intervals, moment)
    if selected is None:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN}-NONE",
            mode=TAPE, observed_at=moment, available_at=moment, price=None, age_seconds=None,
            coverage_known=False, missing_reason="NO_READY_BAR_BEFORE_EVALUATED_AT")
        return FirstPullbackVwapLastTradeInputs(last_trade=observation, label=label)

    bar = selected.bar
    if bar.metadata.instrument_type != instrument_type:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN}-"
                      f"{bar.record_id}",
            mode=TAPE, observed_at=bar.end_time, available_at=bar.end_time, price=None,
            age_seconds=None, coverage_known=True, missing_reason="INCOMPATIBLE_INSTRUMENT_TYPE")
        return FirstPullbackVwapLastTradeInputs(last_trade=observation, label=label)

    age = (moment - bar.end_time).total_seconds()
    if bar.certified_no_trade or bar.close is None:
        observation = Observation(
            record_id=f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN}-"
                      f"{bar.record_id}",
            mode=TAPE, observed_at=bar.end_time, available_at=bar.end_time, price=None,
            age_seconds=age, coverage_known=True, missing_reason="NO_TRADE_AT_LATEST_BAR")
        return FirstPullbackVwapLastTradeInputs(last_trade=observation, label=label)

    observation = Observation(
        record_id=f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN}-{bar.record_id}",
        mode=TAPE, observed_at=bar.end_time, available_at=bar.end_time, price=bar.close,
        age_seconds=age, coverage_known=True)
    return FirstPullbackVwapLastTradeInputs(last_trade=observation, label=label)


def _session_vwap(intervals: tuple[IntervalCoverage, ...], session_start: datetime,
                  moment: datetime, instrument_type: str) -> tuple[Fraction | None, tuple[str, ...]]:
    """Exactly the M9.1K `_session_vwap` computation, reproduced for this module.

    The real `hlc3`-weighted average over every ready traded bar from the
    regular session open through `moment`. Admits `PROVISIONAL` through D-110.
    Returns `(None, ())` when no traded bar of the right type has printed yet.
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


@dataclass(frozen=True)
class FirstPullbackVwapContextInputs:
    """The bar-derived `VwapContext` and its D-110 label.

    `label` is `None` only when the history was absent or incompatible before
    any coverage could be computed, exactly as the other M9.1 pairs' own label.
    """

    context: VwapContext
    label: dict[str, Any] | None


def build_vwap_context_from_research(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
) -> FirstPullbackVwapContextInputs:
    """The real session VWAP level as a `VwapContext`; slope and crosses stay a named gap.

    `level` is the real, `hlc3`-weighted VWAP over every ready traded bar since
    the regular session opened, admitting `PROVISIONAL` through D-110, exactly
    the M9.1K `_session_vwap` computation. `slope` and `crosses` are never
    computed here: PLAYBOOKS section 6 leaves both conventions unresolved
    (`first_pullback_vwap.py`'s own `UNDEFINED` tuple already names
    `VWAP_SLOPE_CONVENTION_UNDEFINED`), so per D-104 this is a recorded gap with
    its own dependent gates (`VWAP_SLOPE`, `VWAP_CROSSES`) left `UNKNOWN`, not
    an approximated number.
    """
    if not isinstance(record_id, str) or not record_id.strip():
        raise RecordError("VWAP context record_id is required")
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("instrument type must be EQUITY or ETF")

    reason = _basis_reason(minute_history, symbol)
    if reason is not None:
        context = VwapContext(
            record_id=record_id,
            definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE,
            available_at=moment, coverage_complete=False, level=None, slope=None, crosses=None,
            missing_reason=reason)
        return FirstPullbackVwapContextInputs(context=context, label=None)

    research = research_coverage_at(minute_history, moment)
    label = research.label()
    bounds = session_bounds(session_date_at(moment))
    if bounds is None:
        context = VwapContext(
            record_id=record_id,
            definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE,
            available_at=moment, coverage_complete=False, level=None, slope=None, crosses=None,
            missing_reason="NO_REGULAR_SESSION")
        return FirstPullbackVwapContextInputs(context=context, label=label)

    session_start = as_utc(bounds[0])
    level, _ids = _session_vwap(research.coverage.intervals, session_start, moment,
                                instrument_type)
    if level is None:
        context = VwapContext(
            record_id=record_id,
            definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE,
            available_at=moment, coverage_complete=True, level=None, slope=None, crosses=None,
            missing_reason="NO_TRADED_SESSION_BAR_YET")
        return FirstPullbackVwapContextInputs(context=context, label=label)

    context = VwapContext(
        record_id=record_id,
        definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE,
        available_at=moment, coverage_complete=True, level=float(level), slope=None, crosses=None,
        missing_reason=VWAP_SLOPE_CONVENTION_UNDEFINED)
    return FirstPullbackVwapContextInputs(context=context, label=label)


def _price_value(value: object, name: str, *, positive: bool = False) -> Fraction:
    """Exactly the M9.1K `_price_value` check, reproduced for this module's own bars."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{name} must be a number")
    number = Fraction(str(value))
    if number < 0 or (positive and number <= 0):
        raise RecordError(f"{name} must be a supported price")
    return number


def _round_outward(raw: Fraction, increment: Fraction, direction: str) -> Fraction:
    """Exactly the M9.1K `_round_outward` rounding, reproduced for this module."""
    ticks = raw / increment
    if direction == "SHORT":
        count = -(-ticks.numerator // ticks.denominator)
    else:
        count = ticks.numerator // ticks.denominator
    return count * increment


def _session_extremes(intervals: tuple[IntervalCoverage, ...], session_start: datetime,
                      moment: datetime, instrument_type: str,
                      ) -> tuple[Fraction | None, Fraction | None, tuple[str, ...]]:
    """The real regular-session high/low over every ready traded bar so far.

    The same window and admission the M9.1P `_session_vwap` read uses;
    returns `(None, None, ())` when no traded bar of the right type has
    printed yet.
    """
    bars = [
        item.bar for item in intervals
        if item.interval.start >= session_start and item.interval.end <= moment
        and item.status in _READY and item.bar is not None
        and item.bar.metadata.instrument_type == instrument_type
        and item.bar.close is not None and item.bar.volume
    ]
    if not bars:
        return None, None, ()
    high = max(Fraction(str(bar.high)) for bar in bars)
    low = min(Fraction(str(bar.low)) for bar in bars)
    ids = tuple(sorted(bar.record_id for bar in bars))
    return high, low, ids


def _prior_trading_day(day):
    """The most recent trading day strictly before `day`, or `None` if unknown."""
    candidates = session_dates(day - timedelta(days=10), day - timedelta(days=1))
    return candidates[-1] if candidates else None


def _prior_day_ohlc(intervals: tuple[IntervalCoverage, ...], prior_day,
                    instrument_type: str,
                    ) -> tuple[Fraction | None, Fraction | None, Fraction | None, tuple[str, ...]]:
    """The prior regular session's real high/low/close, only when fully covered.

    An incomplete prior-session window (a gap, or any non-ready interval)
    reports every value as unavailable rather than an approximation from a
    partial session, per D-104.
    """
    bounds = session_bounds(prior_day)
    if bounds is None:
        return None, None, None, ()
    start, end = as_utc(bounds[0]), as_utc(bounds[1])
    session = prior_day.isoformat()
    window = sorted(
        (item for item in intervals
         if item.interval.session == session
         and item.interval.start >= start and item.interval.end <= end),
        key=lambda item: item.interval.start)
    if (not window or window[0].interval.start != start or window[-1].interval.end != end
            or any(item.status not in _READY for item in window)):
        return None, None, None, ()
    traded = [item.bar for item in window if item.bar is not None
              and item.bar.metadata.instrument_type == instrument_type
              and item.bar.close is not None and item.bar.volume]
    if not traded:
        return None, None, None, ()
    high = max(Fraction(str(bar.high)) for bar in traded)
    low = min(Fraction(str(bar.low)) for bar in traded)
    close = Fraction(str(traded[-1].close))
    ids = tuple(sorted(bar.record_id for bar in traded))
    return high, low, close, ids


def _dollar_half_levels(entry: Fraction, furthest: Fraction, direction: str) -> list[Fraction]:
    """Whole-dollar and half-dollar prices strictly between entry and `furthest`."""
    half = Fraction(1, 2)
    lower, upper = (entry, furthest) if direction == "LONG" else (furthest, entry)
    if lower >= upper:
        return []
    start = (lower // half + 1) * half
    levels = []
    level = start
    while level < upper:
        levels.append(level)
        level += half
    return levels


def _build_target_catalog(
    entry: Fraction, risk_per_share: Fraction, direction: str, sign: int,
    candidates: list[tuple[str, Fraction, tuple[str, ...]]],
) -> tuple[tuple[TargetLevel, ...], tuple[str, ...]]:
    """The M0.3E section 7 T1/T2 catalog from real levels ahead of entry.

    Keep only levels ahead in the trade direction, merge exact prices while
    retaining every label, and sort by directional distance. T1 is the
    nearest level at least 1.5R away; T2 is the nearest distinct later level
    from 2.5R through 4R. No qualifying T1 leaves an empty catalog, which the
    existing `RISK_TARGETS` gate already reads as `GEOMETRY_TARGETS_UNAVAILABLE`,
    exactly the M9.1K precedent for its own absent-VWAP/no-T1 case.
    """
    ahead = [(name, price, ids) for name, price, ids in candidates if sign * (price - entry) > 0]
    if not ahead:
        return (), ()
    furthest = max(price for _, price, _ in ahead)
    grouped: dict[Fraction, list[tuple[str, tuple[str, ...]]]] = {}
    for name, price, ids in ahead:
        grouped.setdefault(price, []).append((name, ids))
    for level in _dollar_half_levels(entry, furthest, direction):
        grouped.setdefault(level, []).append(("WHOLE_HALF_DOLLAR", ()))
    ordered = sorted(grouped, key=lambda price: sign * (price - entry))
    first = next((p for p in ordered if sign * (p - entry) >= Fraction(3, 2) * risk_per_share), None)
    if first is None:
        return (), ()
    second = next(
        (p for p in ordered if sign * (p - first) > 0
         and Fraction(5, 2) * risk_per_share <= sign * (p - entry) <= 4 * risk_per_share),
        None)
    prices = (first,) if second is None else (first, second)
    built = []
    source_ids: list[str] = []
    for number, price in enumerate(prices, 1):
        names = sorted({name for name, _ in grouped[price]})
        for _, ids in grouped[price]:
            source_ids.extend(ids)
        built.append(TargetLevel(
            "T" + str(number), float(price), float(sign * (price - entry) / risk_per_share),
            f"{RESEARCH_FIRST_PULLBACK_VWAP_TARGET_DEFINITION_REFERENCE}:{'+'.join(names)}"))
    return tuple(built), tuple(sorted(set(source_ids)))


@dataclass(frozen=True)
class FirstPullbackVwapStructuralInputs:
    """The bar-derived `PullbackStructural` reading and its D-110 label.

    `label` is `None` only when no target-catalog input was supplied, or the
    supplied minute history was absent or incompatible before any coverage
    could be computed, exactly the other M9.1 pairs' own label.
    """

    structural: PullbackStructural
    label: dict[str, Any] | None


def build_pullback_structural_from_research(
    *,
    record_id_prefix: str,
    direction: str,
    impulse_frozen_at: datetime,
    evaluated_at: datetime,
    available_at: datetime,
    entry_reference: float,
    pullback_extreme_price: float | None,
    frozen_atr: float,
    price_increment: float | None,
    symbol: str | None = None,
    instrument_type: str | None = None,
    impulse_extreme_price: float | None = None,
    minute_history: HistoryBatch | None = None,
) -> FirstPullbackVwapStructuralInputs:
    """Derive the PLAYBOOKS section 6/M0.3E section 7 stop and target catalog.

    `entry_reference` and `pullback_extreme_price` are supplied facts from
    their own producers (the M0.3A entry search and the M8.3 measurement);
    this only measures the stop those facts and the supplied price increment
    imply, reusing the M9.1K `extreme -/+ 0.05*ATR` arithmetic unchanged.

    The target catalog (M9.1R) additionally needs `symbol`, `instrument_type`,
    `impulse_extreme_price` (another M8.3-measurement fact) and
    `minute_history`; when any of those is omitted, `targets` stays `()`
    exactly as it did before M9.1R. Regular-session HOD/LOD and the prior
    session's high/low/close are read from `minute_history`, admitting
    `PROVISIONAL` through D-110; an incomplete window for either leaves
    `targets` at `()` rather than a partial catalog, per D-104.
    """
    prefix = record_id_prefix
    if not isinstance(prefix, str) or not prefix.strip():
        raise RecordError("record ID prefix is required")
    if direction not in _DIRECTIONS:
        raise RecordError("direction must be LONG or SHORT")
    frozen = as_utc(impulse_frozen_at)
    moment = as_utc(evaluated_at)
    available = as_utc(available_at)
    entry = _price_value(entry_reference, "entry_reference", positive=True)
    atr = _price_value(frozen_atr, "frozen_atr")
    sign = 1 if direction == "LONG" else -1

    def missing(reason: str) -> FirstPullbackVwapStructuralInputs:
        structural = PullbackStructural(
            definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE,
            direction=direction, impulse_frozen_at=frozen, evaluated_at=moment,
            available_at=available, risk=None, targets=(), missing_reason=reason,
            record_ids=(f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN}-NONE",))
        return FirstPullbackVwapStructuralInputs(structural=structural, label=None)

    if pullback_extreme_price is None:
        return missing("PULLBACK_EXTREME_UNAVAILABLE")
    extreme = _price_value(pullback_extreme_price, "pullback_extreme_price", positive=True)
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
        "PLAYBOOKS section 6: pullback extreme moved 0.05 frozen ATR further "
        "from entry, rounded outward to the supplied price increment",
        f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN}-STOP")
    stop_id = f"{prefix}-{RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN}-STOP"

    targets: tuple[TargetLevel, ...] = ()
    target_ids: tuple[str, ...] = ()
    label: dict[str, Any] | None = None
    have_target_inputs = (
        symbol is not None and instrument_type is not None
        and impulse_extreme_price is not None and minute_history is not None)
    if have_target_inputs:
        if instrument_type not in _INSTRUMENT_TYPES:
            raise RecordError("instrument type must be EQUITY or ETF")
        reason = _basis_reason(minute_history, symbol)
        if reason is None:
            research = research_coverage_at(minute_history, moment)
            label = research.label()
            bounds = session_bounds(session_date_at(moment))
            if bounds is not None:
                session_start = as_utc(bounds[0])
                session_high, session_low, session_ids = _session_extremes(
                    research.coverage.intervals, session_start, moment, instrument_type)
                prior_day = _prior_trading_day(session_date_at(moment))
                prior_high = prior_low = prior_close = None
                prior_ids: tuple[str, ...] = ()
                if prior_day is not None:
                    prior_high, prior_low, prior_close, prior_ids = _prior_day_ohlc(
                        research.coverage.intervals, prior_day, instrument_type)
                if (session_high is not None and session_low is not None
                        and prior_high is not None and prior_low is not None
                        and prior_close is not None):
                    impulse_extreme = _price_value(
                        impulse_extreme_price, "impulse_extreme_price", positive=True)
                    candidates = [
                        ("IMPULSE_EXTREME", impulse_extreme, ()),
                        ("SESSION_HIGH", session_high, session_ids),
                        ("SESSION_LOW", session_low, session_ids),
                        ("PRIOR_DAY_HIGH", prior_high, prior_ids),
                        ("PRIOR_DAY_LOW", prior_low, prior_ids),
                        ("PRIOR_DAY_CLOSE", prior_close, prior_ids),
                    ]
                    targets, target_ids = _build_target_catalog(
                        entry, risk_per_share, direction, sign, candidates)

    record_ids = (stop_id, *target_ids)
    structural = PullbackStructural(
        definition_reference=RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE,
        direction=direction, impulse_frozen_at=frozen, evaluated_at=moment,
        available_at=available, risk=risk, targets=targets, record_ids=record_ids)
    return FirstPullbackVwapStructuralInputs(structural=structural, label=label)


__all__ = [
    "RESEARCH_FIRST_PULLBACK_VWAP_RS_DEFINITION_REFERENCE",
    "RESEARCH_FIRST_PULLBACK_VWAP_LAST_TRADE_ORIGIN",
    "RESEARCH_FIRST_PULLBACK_VWAP_CONTEXT_DEFINITION_REFERENCE",
    "RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_DEFINITION_REFERENCE",
    "RESEARCH_FIRST_PULLBACK_VWAP_STRUCTURAL_ORIGIN",
    "RESEARCH_FIRST_PULLBACK_VWAP_TARGET_DEFINITION_REFERENCE",
    "VWAP_SLOPE_CONVENTION_UNDEFINED",
    "FirstPullbackVwapLastTradeInputs",
    "FirstPullbackVwapContextInputs",
    "FirstPullbackVwapStructuralInputs",
    "build_relative_strength_from_research",
    "build_last_trade_from_research",
    "build_vwap_context_from_research",
    "build_pullback_structural_from_research",
]
