"""Durable Parquet store + point-in-time panel assembly.

Shared interface contract for the whole project. Series are stored date-indexed
and adjusted-only; the backtest reads the store, never live yfinance, so an
outage can't corrupt or block a run and results are reproducible.

Series naming (fixed contract):
  ETFs       -> columns: open, high, low, close, volume   (adjusted)
  Vol indices-> columns: open, high, low, close[, volume] (^VIX etc.)
  FRED       -> column:  value                             (e.g. BAA10Y)

load_panel(names) returns one wide frame, columns "{name}_{field}", indexed by
the sorted union of all dates, forward-filled across small (holiday) gaps only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from ..config import get, project_root


def store_dir() -> Path:
    d = project_root() / get("data.store_dir", "data/store")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parquet_path(name: str) -> Path:
    return store_dir() / f"{name}.parquet"


def _provenance_path(name: str) -> Path:
    return store_dir() / f"{name}.provenance.json"


def series_exists(name: str) -> bool:
    return _parquet_path(name).exists()


def write_series(name: str, df: pd.DataFrame, source: str, adjusted: bool) -> None:
    """Persist a date-indexed series + provenance sidecar.

    df must have a DatetimeIndex (named or coerced to 'date') and lowercase columns.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df.index.name = "date"
    # normalise to tz-naive dates (calendar alignment, no intraday)
    df.index = df.index.tz_localize(None) if df.index.tz is not None else df.index
    df.columns = [str(c).lower() for c in df.columns]
    df.to_parquet(_parquet_path(name))
    prov = {
        "name": name,
        "source": source,
        "adjusted": bool(adjusted),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(df)),
        "start": str(df.index.min().date()) if len(df) else None,
        "end": str(df.index.max().date()) if len(df) else None,
        "columns": list(df.columns),
    }
    _provenance_path(name).write_text(json.dumps(prov, indent=2))


def read_series(name: str) -> pd.DataFrame:
    p = _parquet_path(name)
    if not p.exists():
        raise FileNotFoundError(f"series '{name}' not in store ({p}); run `python -m src.run_update`")
    df = pd.read_parquet(p)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    return df.sort_index()


def provenance(name: str) -> dict:
    p = _provenance_path(name)
    return json.loads(p.read_text()) if p.exists() else {}


def load_panel(
    names: Iterable[str],
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Assemble a wide point-in-time panel.

    - reference index = sorted union of every series' dates (NYSE trading days);
    - each series reindexed onto it and forward-filled across SMALL gaps only
      (limit = data.holiday_ffill_max_gap_days) — never across long gaps, never
      backfilled, so leading NaN (series not yet started) stays missing.
    Columns are prefixed "{name}_". No look-ahead is introduced: ffill only ever
    carries a PAST observation forward, never a future one.
    """
    names = list(names)
    frames: dict[str, pd.DataFrame] = {}
    idx: pd.DatetimeIndex | None = None
    for n in names:
        df = read_series(n).add_prefix(f"{n}_")
        frames[n] = df
        idx = df.index if idx is None else idx.union(df.index)
    if idx is None:
        return pd.DataFrame()
    idx = idx.sort_values()
    max_gap = int(get("data.holiday_ffill_max_gap_days", 4))
    out = pd.DataFrame(index=idx)
    for n, df in frames.items():
        out = out.join(df.reindex(idx).ffill(limit=max_gap))
    if start:
        out = out[out.index >= pd.Timestamp(start)]
    if end:
        out = out[out.index <= pd.Timestamp(end)]
    out.index.name = "date"
    return out
