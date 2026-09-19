"""M9.1AM: `Orb5Session` records for real training ticker-days from grouped bars.

`build_training_sessions` walks the requested (ticker, session) pairs over the
output of `search_run_bars.group_session_bars`. For each pair it wraps that
day's bars (and the previous regular session's bars, when they were loaded and
usable) as `HistoryBatch` values and calls `build_orb5_session`. Nothing is
filled in (D-104):

- A pair with no usable bars, or a degraded session, is listed in `skipped`
  with its reason and no session is built for it.
- Daily history is not in the retained minute files, so it is not derived from
  minutes; the families that need it stay `UNKNOWN` and the catalog incomplete.
- ATR and tick come only from the caller's mappings; a missing one stays None.
- No entry price or time is set, because the D-106 quote fill does not exist.
  A session built here therefore resolves no trade until that fill is wired.

The evaluation time is the session open plus a caller-stated number of minutes,
never earlier than the longer opening range. Pure and offline: no file is read,
no provider is called, and no signal, trade or result is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Mapping

from .historical_bars import HistoryConventions
from .orb5_grid_run import DIRECTIONS, Orb5Session
from .orb5_session_builder import OPENING_RANGE_MINUTES, build_orb5_session
from .search_run_bars import SessionBars, history_batch_for
from .trade_alerts_models import RecordError
from .utils.time_context import as_utc, session_bounds, session_dates

ENTRY_SOURCE = "NONE_D106_QUOTE_FILL_NOT_BUILT"
PRIOR_LOOKBACK_DAYS = 10


@dataclass(frozen=True)
class TrainingSessions:
    sessions: tuple[Orb5Session, ...]
    skipped: tuple[tuple[str, str, str], ...]  # (ticker, session, reason)
    without_prior_session: tuple[tuple[str, str], ...]


def _prior_session(session: str) -> str | None:
    day = date.fromisoformat(session)
    earlier = session_dates(day - timedelta(days=PRIOR_LOOKBACK_DAYS), day - timedelta(days=1))
    return earlier[-1].isoformat() if earlier else None


def build_training_sessions(
    grouped: SessionBars, *, pairs: Iterable[tuple[str, str]],
    conventions: HistoryConventions, instrument_type: str,
    evaluation_minutes_after_open: int,
    atr_by_pair: Mapping[tuple[str, str], float] | None = None,
    tick_by_ticker: Mapping[str, float] | None = None,
) -> TrainingSessions:
    if not isinstance(evaluation_minutes_after_open, int) or isinstance(
            evaluation_minutes_after_open, bool) or \
            evaluation_minutes_after_open < max(OPENING_RANGE_MINUTES):
        raise RecordError("evaluation must come after the longest opening range")
    atr_by_pair = atr_by_pair or {}
    tick_by_ticker = tick_by_ticker or {}
    built: list[Orb5Session] = []
    skipped: list[tuple[str, str, str]] = []
    no_prior: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    degraded = set(grouped.degraded_sessions)
    for ticker, session in pairs:
        if (ticker, session) in seen:
            raise RecordError(f"duplicate pair {ticker} {session}")
        seen.add((ticker, session))
        if (ticker, session) in degraded:
            skipped.append((ticker, session, "DEGRADED_SESSION"))
            continue
        try:
            minute = history_batch_for(grouped, ticker, session, conventions)
        except RecordError:
            skipped.append((ticker, session, "NO_USABLE_BARS"))
            continue
        prior = None
        prior_session = _prior_session(session)
        if prior_session is not None:
            try:
                prior = history_batch_for(grouped, ticker, prior_session, conventions)
            except RecordError:
                prior = None
        if prior is None:
            no_prior.append((ticker, session))
        bounds = session_bounds(date.fromisoformat(session))
        opened = as_utc(bounds[0])
        built.append(build_orb5_session(
            ticker=ticker, instrument_type=instrument_type,
            evaluated_at=opened + timedelta(minutes=evaluation_minutes_after_open),
            minute_history=minute, daily_history=None, prior_minute_history=prior,
            latest_atr=atr_by_pair.get((ticker, session)),
            tick=tick_by_ticker.get(ticker),
            entry_price={d: None for d in DIRECTIONS},
            entry_time={d: None for d in DIRECTIONS}, entry_source=ENTRY_SOURCE))
    return TrainingSessions(tuple(built), tuple(skipped), tuple(no_prior))


__all__ = ["ENTRY_SOURCE", "TrainingSessions", "build_training_sessions"]
