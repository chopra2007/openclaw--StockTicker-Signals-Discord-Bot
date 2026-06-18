"""Fetch the ETF price universe (adjusted OHLCV) into the Parquet store.

yfinance with auto_adjust=True returns a single split/dividend-adjusted OHLCV
frame whose columns are a MultiIndex (field, ticker). We flatten to single-level
lowercase columns (open, high, low, close, volume) and persist via store.write_series.
"""
from __future__ import annotations

import time

import yfinance as yf

from ..config import get
from . import store

_START = "1990-01-01"
_RETRY_BACKOFF_S = 3.0


def _flatten(df):
    """Collapse yfinance's MultiIndex (field, ticker) to lowercase single-level columns."""
    if df.columns.nlevels > 1:
        df = df.copy()
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
    return df


def fetch_price_series(symbol: str):
    """Download one symbol, flatten, drop all-NaN rows. Retries once on empty."""
    for attempt in range(2):
        df = yf.download(symbol, start=_START, auto_adjust=True, progress=False)
        if df is not None and not df.empty:
            df = _flatten(df)
            df = df.dropna(how="all")
            if not df.empty:
                return df
        if attempt == 0:
            time.sleep(_RETRY_BACKOFF_S)
    return None


def fetch_all_prices() -> dict[str, bool]:
    """Fetch every ETF in config data.etfs into the store.

    Returns {name: True/False} success map.
    """
    etfs = get("data.etfs", [])
    results: dict[str, bool] = {}
    for name in etfs:
        df = fetch_price_series(name)
        if df is None:
            results[name] = False
            continue
        store.write_series(name, df, source="yfinance", adjusted=True)
        results[name] = True
    return results
