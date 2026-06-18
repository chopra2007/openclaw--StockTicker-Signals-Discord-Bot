"""Fetch the volatility-index complex (^VIX etc.) into the Parquet store.

Stored under the CLEAN name (VIX, not ^VIX). Indices may carry zero/NaN volume —
we keep whatever columns yfinance returns, lowercased. auto_adjust=True is harmless
for indices (no splits/dividends).
"""
from __future__ import annotations

import time

import yfinance as yf

from ..config import get
from . import store

_START = "1990-01-01"
_RETRY_BACKOFF_S = 3.0


def _flatten(df):
    if df.columns.nlevels > 1:
        df = df.copy()
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
    return df


def fetch_vol_series(symbol: str):
    """Download one vol-index symbol (e.g. ^VIX), flatten, drop all-NaN rows. Retries once."""
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


def fetch_all_vol() -> dict[str, bool]:
    """Fetch every vol index in config data.vol_indices (name -> ^SYMBOL) into the store.

    Stores under the clean name. Returns {name: True/False} success map.
    """
    vol_indices = get("data.vol_indices", {})
    results: dict[str, bool] = {}
    for name, symbol in vol_indices.items():
        df = fetch_vol_series(symbol)
        if df is None:
            results[name] = False
            continue
        store.write_series(name, df, source="yfinance", adjusted=True)
        results[name] = True
    return results
