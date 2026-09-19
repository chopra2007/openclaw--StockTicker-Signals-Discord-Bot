"""M9.1W part 1: group loaded `core17-1y` minute records into per-ticker,
per-session bar sets for the stage-1 search run.

Pure and offline. It takes already-converted `DatabentoMinuteRecord` values
(from `core17_bar_loader.iter_ohlcv_1m_records`), keeps only the requested
tickers, and returns one time-ordered bar tuple per (ticker, session). It
fails closed: a duplicate bar for the same ticker and minute raises. Sessions
where any kept bar carries a DEGRADED provider condition are not returned as
usable; they are listed in `degraded_sessions` so a dependent rule stays off
and labelled untested (D-104) instead of running on a proxy. It computes no
signal, return or parameter figure, drives no adapter and reads no result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .databento_minute_bars import DatabentoMinuteRecord
from .historical_bars import HistoryBatch, HistoryConventions, HistoryRequest
from .trade_alerts_models import Bar, RecordError
from .utils.time_context import as_utc, session_bounds


@dataclass(frozen=True)
class SessionBars:
    """Grouped bars: usable sessions and the sessions held back as degraded."""

    sessions: tuple[tuple[tuple[str, str], tuple[Bar, ...]], ...]
    degraded_sessions: tuple[tuple[str, str], ...]
    ignored_ticker_count: int

    def bars_for(self, ticker: str, session: str) -> tuple[Bar, ...]:
        for key, bars in self.sessions:
            if key == (ticker, session):
                return bars
        raise RecordError(f"no usable bars for {ticker} on {session}")


def group_session_bars(
    records: Iterable[DatabentoMinuteRecord], tickers: Iterable[str]
) -> SessionBars:
    wanted = tuple(tickers)
    if not wanted or len(set(wanted)) != len(wanted):
        raise RecordError("tickers must be a non-empty list without duplicates")
    wanted_set = set(wanted)
    grouped: dict[tuple[str, str], dict[object, DatabentoMinuteRecord]] = {}
    ignored = 0
    for record in records:
        if not isinstance(record, DatabentoMinuteRecord):
            raise RecordError("records must be DatabentoMinuteRecord")
        ticker = record.bar.metadata.instrument_id
        if ticker not in wanted_set:
            ignored += 1
            continue
        key = (ticker, record.bar.metadata.session)
        minutes = grouped.setdefault(key, {})
        if record.bar.start_time in minutes:
            raise RecordError(f"duplicate bar for {ticker} at {record.bar.start_time.isoformat()}")
        minutes[record.bar.start_time] = record
    usable: list[tuple[tuple[str, str], tuple[Bar, ...]]] = []
    degraded: list[tuple[str, str]] = []
    for key in sorted(grouped):
        ordered = [grouped[key][start] for start in sorted(grouped[key])]
        if any(item.provider_condition != "AVAILABLE" for item in ordered):
            degraded.append(key)
            continue
        usable.append((key, tuple(item.bar for item in ordered)))
    return SessionBars(tuple(usable), tuple(degraded), ignored)


def history_batch_for(
    grouped: SessionBars, ticker: str, session: str, conventions: HistoryConventions
) -> HistoryBatch:
    """M9.1X part 1: wrap one grouped (ticker, session) as a `HistoryBatch`.

    The research adapters read a `HistoryBatch`, so this is the bridge from
    `group_session_bars` output to their input. The request covers that
    session's regular hours. `conventions` is supplied by the caller from a
    dated evidence reference and is never defaulted or filled in here: the
    loader labels volume units unknown, so a caller that cannot name them
    passes UNKNOWN and the adapters refuse the batch (D-104) rather than run
    on a guess. A degraded or absent session raises via `bars_for`.
    """
    if not isinstance(conventions, HistoryConventions):
        raise RecordError("conventions must be HistoryConventions")
    bars = grouped.bars_for(ticker, session)
    sources = {bar.metadata.source for bar in bars}
    if len(sources) != 1:
        raise RecordError("a session batch needs exactly one source dataset")
    try:
        bounds = session_bounds(date.fromisoformat(session))
    except ValueError as exc:
        raise RecordError("session must be an ISO date") from exc
    if bounds is None:
        raise RecordError(f"{session} is not a regular trading session")
    opened, closed = map(as_utc, bounds)
    request = HistoryRequest(symbol=ticker, start=opened, end=closed)
    return HistoryBatch(request, sources.pop(), conventions, bars)
