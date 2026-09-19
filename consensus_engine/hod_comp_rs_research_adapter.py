"""M9.1E research adapter: `HOD_COMP_RS` RS/benchmark lookback from real bars.

This is the first of the `HOD_COMP_RS` adapters M9.1E build-scope names. It is
deliberately narrow: `RsTrendPolicy` (`consensus_engine/rs_trend_eligibility.py`)
binds nine `REQUIRED_ROLES` before eligibility can be assessed, and only two of
them -- `RS` and `RS_WARMUP_COMPLETE` -- are computed purely from minute price
bars. The remaining seven (`MEDIAN_DOLLAR_VOLUME`, `RVOL`, `OPEN_RETURN`,
`DAILY_ATR_PCT`, `SESSION_VWAP`, `REFERENCE_EXTREME_COMPLETE`,
`COMPRESSION_COMPLETE`) and the two quote-derived gates (`QUOTE_ACTIONABLE`,
`SPREAD_BPS`) need their own real-bar or real-quote adapters, which do not fit
in the same session; they remain open build-scope for a later M9.1E sub-step.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at` without touching the live
`HistoryBatch`/`HistoryCoverage` contract. This module reuses the untouched
`HistoryBatch.coverage_at` for revision selection and interval status exactly
as `rs_trend_eligibility.build_rs_trend_snapshot` does, but a `PROVISIONAL`
interval counts as ready here, where the live function stops at `FINAL`/
`NO_TRADE`. `research_coverage_at` supplies the exact D-110 label and the
final/no-trade/provisional/excluded counts this module attaches to its result;
it performs no window selection of its own.

The produced `FeatureSnapshot` uses its own `RESEARCH_RS_FEATURE_VERSION` and
`RESEARCH_RS_DATA_MODE`, distinct from `rs_trend_eligibility.RS_FEATURE_VERSION`/
`RS_DATA_MODE`, so a live `RsTrendPolicy` binding cannot match it by accident;
only a policy that names these research identifiers explicitly can bind to it.

No data is fetched, no parameter is searched or chosen, and no order, alert or
delivery action occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .historical_bars import HistoryBatch
from .research_bar_access import research_coverage_at
from .rs_trend_eligibility import RS_BARS_NAME, RS_NAME, RS_WARMUP_NAME, RsWindowPolicy
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at

RESEARCH_RS_FEATURE_VERSION = "M91E_HOD_COMP_RS_RESEARCH_RS_V1"
RESEARCH_RS_DATA_MODE = "RESEARCH_BAR_RS_TREND_V1"
RESEARCH_STOCK_RETURN_NAME = "RESEARCH_" + "STOCK_RETURN_LOOKBACK_V1"
RESEARCH_BENCHMARK_RETURN_NAME = "RESEARCH_" + "BENCHMARK_RETURN_LOOKBACK_V1"

_INSTRUMENT_TYPES = ("EQUITY", "ETF")
_UNKNOWN = ("", "UNKNOWN", "UNSPECIFIED")
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")


def _instant(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError(f"{name} must be a timestamp")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError(f"{name} must include a timezone") from exc


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
    if any(value.strip().upper() in _UNKNOWN for value in (
            batch.source, batch.conventions.adjustment_basis, batch.conventions.coverage_basis)):
        return "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    return None


def _unexpected_over(batch: HistoryBatch, coverage, items) -> bool:
    unexpected = set(coverage.unexpected_record_ids)
    return any(bar.record_id in unexpected
               and any(bar.start_time < item.interval.end and bar.end_time > item.interval.start
                       for item in items)
               for bar in batch.bars)


def _ids(items) -> tuple[str, ...]:
    return tuple(sorted({item.bar.record_id for item in items if item.bar is not None}))


def _contiguous(items) -> bool:
    return all(later.interval.start == earlier.interval.end
               for earlier, later in zip(items, items[1:]))


def _lookback_return(batch: HistoryBatch, coverage, moment: datetime, opened: datetime,
                     closed: datetime, day: str, policy: RsWindowPolicy,
                     instrument_type: str | None):
    """The `_lookback_return` window, with `PROVISIONAL` admitted as ready.

    Mirrors `rs_trend_eligibility._lookback_return` exactly except for which
    interval statuses count as ready; see the module docstring for why.
    """
    ended = [item for item in coverage.intervals
             if item.interval.session == day and item.interval.start >= opened
             and item.interval.end <= min(moment, closed)]
    selected = ended[-policy.required_bars:]
    ids = _ids(selected)
    if len(selected) != policy.required_bars or not _contiguous(selected):
        return None, "INCOMPLETE_RS_WINDOW", ids
    blocking = [item.status for item in selected if item.status not in _READY]
    if blocking:
        return None, "RS_WINDOW_" + blocking[0], ids
    if _unexpected_over(batch, coverage, selected):
        return None, "UNEXPECTED_OVERLAPPING_RECORD", ids
    bars = [item.bar for item in selected]
    if any(bar.certified_no_trade for bar in bars):
        return None, "NO_TRADED_RS_INTERVAL", ids
    types = {bar.metadata.instrument_type for bar in bars}
    if len(types) != 1 or (instrument_type is not None and types != {instrument_type}):
        return None, "INCOMPATIBLE_INSTRUMENT_TYPE", ids
    base = bars[0].open if policy.return_basis == "FIRST_BAR_OPEN" else bars[0].close
    start = Decimal(str(base))
    return (Decimal(str(bars[-1].close)) - start) / start, None, ids


def _value(name: str, value: Decimal | int | None, unit: str, reason: str | None,
           ids: tuple[str, ...]) -> FeatureValue:
    return FeatureValue(name, float(value) if value is not None else None, unit, reason, ids)


@dataclass(frozen=True)
class RsTrendResearchSnapshot:
    """The research RS/benchmark snapshot plus the D-110 label for each side.

    `stock_label`/`benchmark_label` are `ResearchCoverage.label()` results,
    naming decision D-110, the finality gap and the final/no-trade/provisional/
    excluded interval counts feeding that side's return, per D-110 condition 2.
    A `None` label means that side's history was absent or incompatible before
    any coverage could be computed.
    """

    snapshot: FeatureSnapshot
    stock_label: dict[str, Any] | None
    benchmark_label: dict[str, Any] | None


def build_rs_trend_snapshot_from_research(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
    benchmark_history: HistoryBatch | None,
    policy: RsWindowPolicy,
) -> RsTrendResearchSnapshot:
    """Measure the stock/benchmark lookback return over real, `PROVISIONAL`-usable bars.

    Reuses `rs_trend_eligibility`'s own lookback/window contract unchanged
    except for admitting `PROVISIONAL` intervals; every other refusal reason
    (`INCOMPLETE_RS_WINDOW`, `NO_TRADED_RS_INTERVAL`, `INCOMPATIBLE_*`, ...)
    behaves exactly as the live function's.
    """
    moment = _instant(evaluated_at, "evaluated_at")
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("RS symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("RS instrument type must be EQUITY or ETF")
    if not isinstance(policy, RsWindowPolicy):
        raise RecordError("policy must be RsWindowPolicy")
    if policy.benchmark_symbol == symbol:
        raise RecordError("the benchmark must differ from the measured symbol")

    day = session_date_at(moment)
    bounds = session_bounds(day)
    session = day.isoformat()
    stock_label = benchmark_label = None
    if bounds is None:
        warm = False
        stock = benchmark = (None, "NO_REGULAR_SESSION", ())
    else:
        opened, closed = map(as_utc, bounds)
        elapsed = (min(moment, closed) - opened) // timedelta(minutes=1)
        warm = elapsed >= policy.required_bars
        measured = []
        labels = []
        for batch, wanted, kind in (
            (minute_history, symbol, instrument_type),
            (benchmark_history, policy.benchmark_symbol, None),
        ):
            reason = _basis_reason(batch, wanted)
            if reason is not None:
                measured.append((None, reason, ()))
                labels.append(None)
                continue
            research = research_coverage_at(batch, moment)
            labels.append(research.label())
            if not warm:
                measured.append((None, "RS_WARMUP_INCOMPLETE", ()))
            else:
                measured.append(_lookback_return(batch, batch.coverage_at(moment), moment,
                                                 opened, closed, session, policy, kind))
        stock, benchmark = measured
        stock_label, benchmark_label = labels
        benchmark = (benchmark[0],
                     None if benchmark[1] is None else "BENCHMARK_" + benchmark[1],
                     benchmark[2])

    features = [_value(RESEARCH_STOCK_RETURN_NAME, stock[0], "RATIO", stock[1], stock[2]),
                _value(RESEARCH_BENCHMARK_RETURN_NAME, benchmark[0], "RATIO",
                      benchmark[1], benchmark[2])]
    ids = tuple(sorted(set(stock[2]) | set(benchmark[2])))
    if stock[0] is None or benchmark[0] is None:
        features.append(_value(RS_NAME, None, "RATIO", stock[1] or benchmark[1], ids))
    else:
        features.append(_value(RS_NAME, stock[0] - benchmark[0], "RATIO", None, ids))
    features += [_value(RS_BARS_NAME, policy.lookback_bars, "COUNT", None, ()),
                 _value(RS_WARMUP_NAME, int(warm), "BOOLEAN", None, ())]

    metadata = SourceMetadata(
        instrument_id=symbol, instrument_type=instrument_type, source="DERIVED_M91E",
        source_time=moment, received_time=moment, available_time=moment,
        normalized_time=moment, session=session, data_mode=RESEARCH_RS_DATA_MODE,
        quality="VALID",
    )
    snapshot = FeatureSnapshot(
        record_id=record_id, metadata=metadata, evaluated_at=moment,
        features=tuple(features), feature_version=RESEARCH_RS_FEATURE_VERSION,
        input_record_ids=ids,
    )
    return RsTrendResearchSnapshot(snapshot=snapshot, stock_label=stock_label,
                                   benchmark_label=benchmark_label)


__all__ = [
    "RESEARCH_BENCHMARK_RETURN_NAME", "RESEARCH_RS_DATA_MODE", "RESEARCH_RS_FEATURE_VERSION",
    "RESEARCH_STOCK_RETURN_NAME", "RsTrendResearchSnapshot",
    "build_rs_trend_snapshot_from_research",
]
