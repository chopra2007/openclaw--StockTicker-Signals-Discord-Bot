"""M9.1AY: retained minute bars -> per ticker-day `HistoryBatch` values for playbooks #2-4.

The `HOD_COMP_RS`, `OR_FAILURE_REV` and `FIRST_PULLBACK_VWAP` research adapters each
take one supplied `HistoryBatch` and a decision moment. This builder groups the
retained records for the named (ticker, session) pairs and wraps each session, plus
the prior session when it was loaded, as a batch. It chooses no decision moment and
sets no entry. A degraded or absent session is skipped with a reason, and a missing
prior session is listed rather than filled (D-104). `atr_1m` is not produced here: no
derivation from the same bars without a proxy has been shown, so it stays unset.
Nothing is read from a provider and no result is produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .core17_bar_loader import open_core17_ohlcv_1m_file
from .databento_minute_bars import DatabentoMinuteRecord
from .historical_bars import HistoryBatch, HistoryConventions
from .orb5_training_sessions import _prior_session
from .search_run_bars import SessionBars, group_session_bars, history_batch_for
from .trade_alerts_models import RecordError

Opener = Callable[[Path, str], Iterator[DatabentoMinuteRecord]]


@dataclass(frozen=True)
class SessionHistory:
    ticker: str
    session: str
    batch: HistoryBatch
    prior_batch: HistoryBatch | None


@dataclass(frozen=True)
class RetainedHistoryBatches:
    histories: tuple[SessionHistory, ...]
    skipped: tuple[tuple[str, str, str], ...]  # (ticker, session, reason)
    without_prior_session: tuple[tuple[str, str], ...]


def build_history_batches(
    grouped: SessionBars, *, pairs: Iterable[tuple[str, str]], conventions: HistoryConventions,
) -> RetainedHistoryBatches:
    built: list[SessionHistory] = []
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
            batch = history_batch_for(grouped, ticker, session, conventions)
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
        built.append(SessionHistory(ticker, session, batch, prior))
    return RetainedHistoryBatches(tuple(built), tuple(skipped), tuple(no_prior))


def load_retained_history_batches(
    job_dir: Path, filenames: Iterable[str], *, pairs: Iterable[tuple[str, str]],
    conventions: HistoryConventions, opener: Opener = open_core17_ohlcv_1m_file,
) -> RetainedHistoryBatches:
    names = tuple(filenames)
    if not names or len(set(names)) != len(names):
        raise RecordError("filenames must be a non-empty list without duplicates")
    pair_list = tuple(pairs)
    tickers = tuple(dict.fromkeys(ticker for ticker, _ in pair_list))
    if not tickers:
        raise RecordError("pairs must not be empty")
    records = chain.from_iterable(opener(Path(job_dir), name) for name in names)
    grouped = group_session_bars(records, tickers)
    return build_history_batches(grouped, pairs=pair_list, conventions=conventions)


__all__ = ["RetainedHistoryBatches", "SessionHistory", "build_history_batches",
           "load_retained_history_batches"]
