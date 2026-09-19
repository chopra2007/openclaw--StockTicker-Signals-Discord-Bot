"""M9.1AN: read retained `core17-1y` files into `Orb5Session` records.

`load_retained_training_sessions` opens each named retained monthly file with
`core17_bar_loader.open_core17_ohlcv_1m_file` (which checks the file's sha256
against its manifest first), groups the records for the tickers in `pairs`, and
hands the result to `build_training_sessions`. The caller names every file, so a
prior-session day that lives in an unnamed file is simply not loaded and its
prior-session family stays `UNKNOWN` (D-104). Nothing is filled in, no entry is
set, and no search is run. Reading the real files happens only when the caller
runs this outside the protected launcher; the offline contract uses a fake
opener. No provider is called and no result is produced.
"""

from __future__ import annotations

from itertools import chain
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping

from .core17_bar_loader import open_core17_ohlcv_1m_file
from .databento_minute_bars import DatabentoMinuteRecord
from .historical_bars import HistoryConventions
from .orb5_training_sessions import TrainingSessions, build_training_sessions
from .search_run_bars import group_session_bars
from .trade_alerts_models import RecordError

Opener = Callable[[Path, str], Iterator[DatabentoMinuteRecord]]


def load_retained_training_sessions(
    job_dir: Path, filenames: Iterable[str], *, pairs: Iterable[tuple[str, str]],
    conventions: HistoryConventions, instrument_type: str,
    evaluation_minutes_after_open: int,
    atr_by_pair: Mapping[tuple[str, str], float] | None = None,
    tick_by_ticker: Mapping[str, float] | None = None,
    opener: Opener = open_core17_ohlcv_1m_file,
) -> TrainingSessions:
    names = tuple(filenames)
    if not names or len(set(names)) != len(names):
        raise RecordError("filenames must be a non-empty list without duplicates")
    pair_list = tuple(pairs)
    tickers = tuple(dict.fromkeys(ticker for ticker, _ in pair_list))
    if not tickers:
        raise RecordError("pairs must not be empty")
    records = chain.from_iterable(opener(Path(job_dir), name) for name in names)
    grouped = group_session_bars(records, tickers)
    return build_training_sessions(
        grouped, pairs=pair_list, conventions=conventions, instrument_type=instrument_type,
        evaluation_minutes_after_open=evaluation_minutes_after_open,
        atr_by_pair=atr_by_pair, tick_by_ticker=tick_by_ticker)


__all__ = ["load_retained_training_sessions"]
