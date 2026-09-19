"""M9.1L research adapter: the M8.1 handoff chain's own real-data opening range.

`OrFailureHandoffMachine`'s `RANGE_GATE` (`consensus_engine/or_failure_handoff.py`)
needs a supplied M3.6 `FeatureSnapshot`
(`opening_range_features.build_opening_range_snapshot`) whose `feature_version`
matches `OPENING_RANGE_VERSION` (`opening_range_features.FEATURE_VERSION`)
exactly. The existing M9.1H/M9.1I bar-derived `MinuteClose`/`BreakoutExtreme`
reads (`or_failure_rev_research_adapter.build_or_failure_rev_bar_inputs_from_research`'s
`confirmation_close` and `build_or_failure_rev_extreme_inputs_from_research`'s
`breakout_extreme`) already reuse unchanged as the handoff's own `minute_close`/
`breakout_extreme` inputs -- both read "the real minute bar at or before
`evaluated_at`", exactly what `HandoffRequest.minute_close` and
`.breakout_extreme` need. So the one missing piece before the handoff's own
`HandoffRequest` can be built entirely from real bars is its opening range:
`build_opening_range_snapshot` only admits `FINAL`/`NO_TRADE` bars, and M9.1D's
finding that Databento history is permanently `PROVISIONAL` for this project
means it can never complete from that path.

This mirrors the M9.1D research-bar-accessor precedent M9.1E-K already used:
reuse `opening_range_features.build_opening_range_snapshot`'s own value/version
definitions and revision-selection/conflict logic unchanged, only replace its
`HistoryBatch.coverage_at` call with `research_bar_access.research_coverage_at`'s
D-110 `PROVISIONAL`-admitting view. The produced `FeatureSnapshot.feature_version`
stays exactly `opening_range_features.FEATURE_VERSION`, since this computes the
identical D-090 five-minute high/low/mid/width definition from the identical
selection logic -- only the finality admission differs -- so
`OrFailureHandoffMachine`'s `RANGE_GATE` version check can bind to it directly.
The research provenance is carried in `metadata.data_mode`
(`RESEARCH_BAR_OPENING_RANGE_V1`, distinct from the live
`SUPPLIED_BAR_OPENING_RANGE`) and the returned D-110 label, not by inventing a
second feature version.

Combined with the existing M9.1H/M9.1I reads, a `HandoffRequest` can now be
built entirely from real bars; only the caller-supplied `TriggerAssessment`/
`HandoffPolicy` -- the M6.2 attempt record and the caller's own
unresolved-rule policy -- remain outside this module's scope, exactly as they
already are for a live caller.

D-110 permits offline research to read `PROVISIONAL` (finality-unknown) bars
through `research_bar_access.research_coverage_at` without touching the live
`HistoryBatch`/`HistoryCoverage` contract. No data is fetched, no parameter is
searched or chosen, and no order, alert or delivery action occurs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from .historical_bars import HistoryBatch, HistoryRequest
from .opening_range_features import FEATURE_VERSION as OPENING_RANGE_VERSION
from .research_bar_access import research_coverage_at
from .trade_alerts_models import FeatureSnapshot, FeatureValue, RecordError, SourceMetadata
from .utils.time_context import as_utc, session_bounds, session_date_at

RESEARCH_OR_FAILURE_HANDOFF_DATA_MODE = "RESEARCH_BAR_OPENING_RANGE_V1"
_INSTRUMENT_TYPES = {"EQUITY", "ETF"}
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}
_READY = ("FINAL", "NO_TRADE", "PROVISIONAL")
_VALUE_SPECS = (
    ("OPENING_RANGE_HIGH_5M_V1", "USD_PER_SHARE"),
    ("OPENING_RANGE_LOW_5M_V1", "USD_PER_SHARE"),
    ("OPENING_RANGE_MID_5M_V1", "USD_PER_SHARE"),
    ("OPENING_RANGE_WIDTH_5M_V1", "USD_PER_SHARE"),
)
_COMPLETE_NAME = "OPENING_RANGE_COMPLETE_5M_V1"


def _missing_features(reason: str, ids: tuple[str, ...]) -> tuple[FeatureValue, ...]:
    values = tuple(FeatureValue(name, None, unit, reason, ids) for name, unit in _VALUE_SPECS)
    return (*values, FeatureValue(_COMPLETE_NAME, 0.0, "BOOLEAN", None, ids))


@dataclass(frozen=True)
class OrFailureHandoffOpeningRangeResult:
    """The bar-derived M3.6 opening-range `FeatureSnapshot` and its D-110 label.

    `label` is `None` only when the session/history was absent or incompatible
    before any coverage could be computed, exactly as the M9.1H/I/J/K pairs'
    own label.
    """

    snapshot: FeatureSnapshot
    label: dict[str, Any] | None


def build_or_failure_handoff_opening_range_from_research(
    *,
    record_id: str,
    evaluated_at: datetime,
    symbol: str,
    instrument_type: str,
    minute_history: HistoryBatch | None,
) -> OrFailureHandoffOpeningRangeResult:
    """Build the M8.1 handoff's own opening-range `FeatureSnapshot` from real bars.

    Reuses `opening_range_features.build_opening_range_snapshot`'s exact
    five-minute high/low/mid/width definition and `FEATURE_VERSION` unchanged;
    only the finality admission differs, through D-110's
    `research_bar_access.research_coverage_at`.
    """
    moment = as_utc(evaluated_at)
    if not isinstance(symbol, str) or not symbol.strip():
        raise RecordError("opening range symbol is required")
    if instrument_type not in _INSTRUMENT_TYPES:
        raise RecordError("opening range instrument type must be EQUITY or ETF")

    day = session_date_at(moment)
    bounds = session_bounds(day)
    reason: str | None = None
    ids: tuple[str, ...] = ()
    selected: tuple = ()
    label: dict[str, Any] | None = None

    if bounds is None:
        reason = "NO_REGULAR_SESSION"
    elif minute_history is None:
        reason = "MISSING_MINUTE_HISTORY"
    elif minute_history.request.symbol != symbol:
        reason = "INCOMPATIBLE_SYMBOL"
    elif minute_history.request.interval != "1m":
        reason = "INCOMPATIBLE_HISTORY_INTERVAL"
    elif minute_history.conventions.price != "USD_PER_SHARE":
        reason = "INCOMPATIBLE_PRICE_UNIT"
    elif minute_history.conventions.volume != "SHARES":
        reason = "INCOMPATIBLE_VOLUME_UNIT"
    elif any(
        value.strip().upper() in _UNKNOWN
        for value in (
            minute_history.source,
            minute_history.conventions.adjustment_basis,
            minute_history.conventions.coverage_basis,
        )
    ):
        reason = "UNKNOWN_SOURCE_OR_VENUE_BASIS"
    else:
        opened = as_utc(bounds[0])
        request = HistoryRequest(symbol, opened, opened + timedelta(minutes=5))
        requested = set(minute_history.request.expected_intervals())
        opening_intervals = request.expected_intervals()
        if any(interval not in requested for interval in opening_intervals):
            reason = "OPENING_RANGE_NOT_REQUESTED"
        else:
            overlapping = tuple(
                bar
                for bar in minute_history.bars
                if bar.start_time < request.end and bar.end_time > request.start
            )
            opening_history = HistoryBatch(
                request, minute_history.source, minute_history.conventions, overlapping
            )
            research = research_coverage_at(opening_history, moment)
            label = research.label()
            coverage = research.coverage
            ids = tuple(
                sorted(
                    {item.bar.record_id for item in coverage.intervals if item.bar is not None}
                    | set(coverage.unexpected_record_ids)
                )
            )
            statuses = [item.status for item in coverage.intervals]
            if coverage.unexpected_record_ids:
                reason = "UNEXPECTED_OVERLAPPING_RECORD"
            elif any(status not in _READY for status in statuses):
                reason = "OPENING_RANGE_" + next(
                    status for status in statuses if status not in _READY
                )
            else:
                selected = tuple(item.bar for item in coverage.intervals if item.bar is not None)
                types = {bar.metadata.instrument_type for bar in selected}
                if types != {instrument_type}:
                    reason = "INCOMPATIBLE_INSTRUMENT_TYPE"
                elif not any(not bar.certified_no_trade for bar in selected):
                    reason = "NO_TRADED_OPENING_RANGE_INTERVAL"

    metadata = SourceMetadata(
        instrument_id=symbol,
        instrument_type=instrument_type,
        source="DERIVED_M91L_RESEARCH",
        source_time=moment,
        received_time=moment,
        available_time=moment,
        normalized_time=moment,
        session=day.isoformat(),
        data_mode=RESEARCH_OR_FAILURE_HANDOFF_DATA_MODE,
        quality="VALID",
    )
    if reason is not None:
        features = _missing_features(reason, ids)
    else:
        traded = tuple(bar for bar in selected if not bar.certified_no_trade)
        high = max(Decimal(str(bar.high)) for bar in traded)
        low = min(Decimal(str(bar.low)) for bar in traded)
        values = (high, low, (high + low) / Decimal(2), high - low)
        features = tuple(
            FeatureValue(name, float(value), unit, None, ids)
            for (name, unit), value in zip(_VALUE_SPECS, values)
        ) + (FeatureValue(_COMPLETE_NAME, 1.0, "BOOLEAN", None, ids),)
    snapshot = FeatureSnapshot(
        record_id=record_id,
        metadata=metadata,
        evaluated_at=moment,
        features=features,
        feature_version=OPENING_RANGE_VERSION,
        input_record_ids=ids,
    )
    return OrFailureHandoffOpeningRangeResult(snapshot=snapshot, label=label)


__all__ = [
    "OrFailureHandoffOpeningRangeResult",
    "RESEARCH_OR_FAILURE_HANDOFF_DATA_MODE",
    "build_or_failure_handoff_opening_range_from_research",
]
