"""Offline historical-bar requests, normalization and available-time coverage.

There is no provider fallback, clock read, storage or runtime activation here.
Source conventions and original observation times require independent evidence.
Supplying synthetic context proves only the interface, never provider coverage.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from consensus_engine.scanners.schwab_normalization import normalize_schwab_bar
from consensus_engine.trade_alerts_models import Bar, RecordError, SourceMetadata
from consensus_engine.utils.time_context import as_utc, premarket_bounds, session_bounds, session_dates


_PACIFIC = ZoneInfo("America/Los_Angeles")
_MINUTE = timedelta(minutes=1)
_UNKNOWN = {"", "UNKNOWN", "UNSPECIFIED"}


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise RecordError("history times must be timezone-aware datetimes")
    try:
        return as_utc(value)
    except ValueError as exc:
        raise RecordError("history times must include a timezone") from exc


@dataclass(frozen=True, order=True)
class BarInterval:
    session: str
    start: datetime
    end: datetime

    def as_dict(self) -> dict[str, str]:
        return {"session": self.session, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class HistoryRequest:
    """Requested [start, end) coverage, independent of what a provider returns.

    Daily means one regular-session bar, never a calendar-day aggregate.
    Premarket begins at an explicit Pacific clock time, with no default.
    Only scheduled bars intersecting the request are expected; closed hours are
    excluded. Minute edges align to whole minutes. An intersecting daily bar
    must be requested in full, including on an early close.
    """

    symbol: str
    start: datetime
    end: datetime
    interval: str = "1m"
    session_scope: str = "REGULAR"
    premarket_start: time | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise RecordError("history symbol is required")
        object.__setattr__(self, "start", _instant(self.start))
        object.__setattr__(self, "end", _instant(self.end))
        if self.start >= self.end:
            raise RecordError("history start must precede end")
        if self.interval not in ("1m", "1d"):
            raise RecordError("history interval must be 1m or 1d")
        if self.session_scope not in ("REGULAR", "PREMARKET", "PREMARKET_AND_REGULAR"):
            raise RecordError("history session scope is unsupported")
        if self.interval == "1d" and self.session_scope != "REGULAR":
            raise RecordError("daily history requires regular-session coverage")
        if self.session_scope != "REGULAR" and self.premarket_start is None:
            raise RecordError("premarket history requires an explicit Pacific start")
        if self.premarket_start is not None:
            if (not isinstance(self.premarket_start, time) or self.premarket_start.tzinfo is not None
                    or self.premarket_start.second or self.premarket_start.microsecond):
                raise RecordError("premarket start must be a whole-minute Pacific clock time")
        if self.interval == "1m" and any(t.second or t.microsecond for t in (self.start, self.end)):
            raise RecordError("minute history requires whole-minute request edges")
        self.expected_intervals()

    def expected_intervals(self) -> tuple[BarInterval, ...]:
        intervals = []
        first = self.start.astimezone(_PACIFIC).date()
        last = self.end.astimezone(_PACIFIC).date()
        for day in session_dates(first, last):
            regular = session_bounds(day)
            assert regular is not None
            opened, closed = map(as_utc, regular)
            spans = []
            if self.session_scope != "REGULAR":
                spans.append(premarket_bounds(day, self.premarket_start))
            if self.session_scope != "PREMARKET":
                spans.append((opened, closed))
            for start, end in spans:
                if self.interval == "1d":
                    if start < self.end and end > self.start:
                        if start < self.start or end > self.end:
                            raise RecordError("daily history request must contain the whole regular session")
                        intervals.append(BarInterval(day.isoformat(), start, end))
                else:
                    cursor, stop = max(start, self.start), min(end, self.end)
                    while cursor < stop:
                        intervals.append(BarInterval(day.isoformat(), cursor, cursor + _MINUTE))
                        cursor += _MINUTE
        return tuple(intervals)

    def provider_kwargs(self) -> dict[str, Any]:
        """Arguments for schwab_client.get_price_history_payload, without I/O."""
        return {"symbol": self.symbol, "start": self.start, "end": self.end,
                "interval": self.interval, "extended_hours": self.session_scope != "REGULAR"}

    def as_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "start": self.start.isoformat(), "end": self.end.isoformat(),
                "interval": self.interval, "session_scope": self.session_scope,
                "premarket_start": self.premarket_start.isoformat() if self.premarket_start else None}


@dataclass(frozen=True)
class HistoryConventions:
    """Source facts supplied from a dated evidence reference, not inferred here.

    EXPLICIT means an independently mapped interval; it makes no start/end-stamp
    claim. UNKNOWN preserves normalized values but prevents complete coverage.
    coverage_basis identifies venue/trade eligibility, not just a provider name.
    """

    timestamp: str = "UNKNOWN"
    session: str = "UNKNOWN"
    adjustment_basis: str = "UNKNOWN"
    price: str = "UNKNOWN"
    volume: str = "UNKNOWN"
    coverage_basis: str = "UNKNOWN"
    finality: str = "UNKNOWN"
    publication: str = "UNKNOWN"
    evidence_reference: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp not in ("UNKNOWN", "START", "END", "EXPLICIT"):
            raise RecordError("history timestamp convention is unsupported")
        if self.session not in ("UNKNOWN", "REGULAR", "PREMARKET", "PREMARKET_AND_REGULAR", "CALENDAR_DAY"):
            raise RecordError("history source session convention is unsupported")
        for name in ("adjustment_basis", "price", "volume", "coverage_basis", "finality", "publication"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise RecordError("history convention labels must be nonempty strings")
        if self.evidence_reference is not None and (
                not isinstance(self.evidence_reference, str) or not self.evidence_reference.strip()):
            raise RecordError("history evidence reference must be a nonempty string or null")

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class SchwabBarContext:
    """Per-row original facts; the raw candle alone cannot supply these times."""

    record_id: str
    metadata: SourceMetadata
    start: datetime
    end: datetime
    is_final: bool = False


@dataclass(frozen=True)
class IntervalCoverage:
    interval: BarInterval
    status: str
    bar: Bar | None = None
    duplicate_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"interval": self.interval.as_dict(), "status": self.status,
                "bar": self.bar.as_dict() if self.bar else None, "duplicate_count": self.duplicate_count}


@dataclass(frozen=True)
class HistoryCoverage:
    evaluated_at: datetime
    intervals: tuple[IntervalCoverage, ...]
    unexpected_record_ids: tuple[str, ...]
    outside_scope_record_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """All requested intervals covered; does not imply a strategy is ready."""
        return bool(self.intervals) and not self.unexpected_record_ids and all(
            item.status in ("FINAL", "NO_TRADE") for item in self.intervals)

    @property
    def final_bars(self) -> tuple[Bar, ...]:
        return tuple(item.bar for item in self.intervals
                     if item.status in ("FINAL", "NO_TRADE") and item.bar is not None)

    def as_dict(self) -> dict[str, Any]:
        return {"evaluated_at": self.evaluated_at.isoformat(), "complete": self.complete,
                "intervals": [item.as_dict() for item in self.intervals],
                "unexpected_record_ids": list(self.unexpected_record_ids),
                "outside_scope_record_ids": list(self.outside_scope_record_ids)}


@dataclass(frozen=True)
class HistoryBatch:
    request: HistoryRequest
    source: str
    conventions: HistoryConventions
    bars: tuple[Bar, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, HistoryRequest) or not isinstance(self.conventions, HistoryConventions):
            raise RecordError("history requires a request and source conventions")
        if not isinstance(self.source, str) or not self.source.strip():
            raise RecordError("history source is required")
        if not isinstance(self.bars, tuple) or any(not isinstance(bar, Bar) for bar in self.bars):
            raise RecordError("history bars must be a tuple of canonical Bar records")
        identities = {}
        for bar in self.bars:
            if bar.metadata.source != self.source or bar.metadata.instrument_id != self.request.symbol:
                raise RecordError("history record source or symbol contradicts its batch")
            if bar.metadata.instrument_type == "OPTION":
                raise RecordError("historical stock bars cannot identify an option")
            if bar.metadata.source_time is not None and bar.metadata.source_time > bar.metadata.available_time:
                raise RecordError("history source time cannot follow availability")
            payload = bar.to_json()
            if bar.record_id in identities and identities[bar.record_id] != payload:
                raise RecordError("history record identity cannot be reused for different facts")
            identities[bar.record_id] = payload

    def _conventions_known(self) -> bool:
        c = self.conventions
        allowed_sessions = {self.request.session_scope}
        if self.request.interval == "1m":
            allowed_sessions.add("PREMARKET_AND_REGULAR")
        return (self.source.strip().upper() not in _UNKNOWN
                and c.timestamp != "UNKNOWN" and c.session in allowed_sessions
                and c.evidence_reference is not None
                and c.evidence_reference.strip().upper() not in _UNKNOWN
                and all(value.strip().upper() not in _UNKNOWN for value in
                        (c.adjustment_basis, c.price, c.volume, c.coverage_basis, c.finality, c.publication)))

    def coverage_at(self, evaluated_at: datetime) -> HistoryCoverage:
        """Select only revisions actually available at this instant.

        Missing intervals stay missing, with no invented zero volume or prices.
        A later provisional/invalid revision blocks the interval; an old final
        revision is not silently substituted. Equal-revision conflicts block it.
        Exact redeliveries count once. Future revisions cannot affect this view.
        """
        moment = _instant(evaluated_at)
        expected = self.request.expected_intervals()
        grouped: dict[BarInterval, list[Bar]] = {interval: [] for interval in expected}
        ends = [interval.end for interval in expected]
        unexpected = []
        outside_scope = []
        for bar in self.bars:
            if bar.metadata.available_time > moment:
                continue
            key = BarInterval(bar.metadata.session, bar.start_time, bar.end_time)
            if key in grouped:
                grouped[key].append(bar)
            else:
                # Providers may include the exclusive end or other session hours.
                # Preserve those records without claiming they fill a requested slot.
                next_interval = bisect_right(ends, bar.start_time)
                if next_interval == len(expected) or expected[next_interval].start >= bar.end_time:
                    outside_scope.append(bar.record_id)
                else:
                    unexpected.append(bar.record_id)
        results = []
        for interval, observed in grouped.items():
            if interval.end > moment:
                results.append(IntervalCoverage(interval, "NOT_ENDED"))
                continue
            if not observed:
                results.append(IntervalCoverage(interval, "MISSING"))
                continue
            revision = max(bar.metadata.revision for bar in observed)
            latest = [bar for bar in observed if bar.metadata.revision == revision]
            # Re-fetch/normalization times do not create a new market fact. Keep
            # original copies in the archive and select the earliest availability.
            # Source time, values, quality and source conventions must still agree.
            facts = []
            for bar in latest:
                fact = bar.as_dict()
                fact.pop("record_id")
                for name in ("received_time", "available_time", "normalized_time"):
                    fact["metadata"].pop(name)
                facts.append(fact)
            if any(fact != facts[0] for fact in facts[1:]):
                results.append(IntervalCoverage(interval, "CONFLICT"))
                continue
            bar = min(latest, key=lambda value: (
                value.metadata.available_time, value.metadata.received_time,
                value.metadata.normalized_time, value.record_id))
            c = self.conventions
            if not bar.is_final:
                status = "PROVISIONAL"
            elif bar.metadata.quality != "VALID":
                status = "QUALITY_" + bar.metadata.quality
            elif not self._conventions_known():
                status = "UNKNOWN_CONVENTIONS"
            elif (bar.adjustment_basis, bar.price_convention, bar.volume_convention) != (
                    c.adjustment_basis, c.price, c.volume):
                status = "INCOMPATIBLE_CONVENTIONS"
            elif ((c.timestamp == "START" and bar.metadata.source_time != bar.start_time)
                  or (c.timestamp == "END" and bar.metadata.source_time != bar.end_time)):
                status = "INCOMPATIBLE_TIMESTAMP"
            else:
                status = "NO_TRADE" if bar.certified_no_trade else "FINAL"
            results.append(IntervalCoverage(interval, status, bar, len(latest) - 1))
        # Mixed data modes are separate studies, even when each interval is valid.
        modes = {item.bar.metadata.data_mode for item in results if item.bar is not None}
        if len(modes) > 1 or any(mode.strip().upper() in _UNKNOWN for mode in modes):
            results = [IntervalCoverage(item.interval, "INCOMPATIBLE_MODE", item.bar, item.duplicate_count)
                       if item.status in ("FINAL", "NO_TRADE") else item for item in results]
        return HistoryCoverage(moment, tuple(results), tuple(sorted(unexpected)), tuple(sorted(outside_scope)))

    def as_dict(self) -> dict[str, Any]:
        """Detached archive view retains every supplied revision in input order."""
        return {"interface_version": "M22_V1", "request": self.request.as_dict(), "source": self.source,
                "conventions": self.conventions.as_dict(), "bars": [bar.as_dict() for bar in self.bars]}


def normalize_schwab_history(
    response: Mapping[str, Any], *, request: HistoryRequest,
    contexts: tuple[SchwabBarContext, ...], conventions: HistoryConventions,
) -> HistoryBatch:
    """Map a raw response before table conversion, preserving one context per row.

    Unknown start/end/publication semantics must stay unknown or be mapped from
    independent evidence. This function does not derive them from candle time.
    Empty responses produce missing coverage, never certified no-trade bars.
    Provider failures propagate from the request path; there is no silent fallback.
    """
    if not isinstance(response, Mapping):
        raise RecordError("historical response must be an object")
    if not isinstance(request, HistoryRequest) or not isinstance(conventions, HistoryConventions):
        raise RecordError("history requires a request and source conventions")
    # This is the same symbol spelling used by the existing authenticated client.
    from consensus_engine.scanners.schwab_client import to_schwab_symbol

    raw_symbol = response.get("symbol")
    if raw_symbol != to_schwab_symbol(request.symbol):
        raise RecordError("historical response symbol must match the requested symbol")
    candles = response.get("candles")
    if not isinstance(candles, list):
        raise RecordError("historical response requires a candles list")
    if "empty" in response and (type(response["empty"]) is not bool or response["empty"] != (not candles)):
        raise RecordError("historical response empty flag contradicts its candles")
    if not isinstance(contexts, tuple) or len(contexts) != len(candles):
        raise RecordError("historical response requires one original context per candle")
    bars = []
    for candle, context in zip(candles, contexts):
        if not isinstance(context, SchwabBarContext):
            raise RecordError("historical context must be SchwabBarContext")
        bars.append(normalize_schwab_bar(
            candle, record_id=context.record_id, metadata=context.metadata,
            raw_symbol=request.symbol, start_time=context.start, end_time=context.end,
            is_final=context.is_final, adjustment_basis=conventions.adjustment_basis,
            price_convention=conventions.price, volume_convention=conventions.volume,
        ))
    return HistoryBatch(request, "SCHWAB", conventions, tuple(bars))
