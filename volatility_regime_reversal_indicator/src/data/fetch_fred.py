"""Fetch FRED daily macro series (BAA10Y credit spread) into the Parquet store.

BAA10Y = Moody's Baa corporate yield minus 10y Treasury, daily back to 1986, free.
Uses the FRED REST observations endpoint. Missing days are marked "." by FRED and
skipped. Stored as a single-column ('value') date-indexed frame.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

import pandas as pd

from . import store

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_START = "1986-01-01"


def fetch_fred_series(series_id: str, observation_start: str = _DEFAULT_START) -> pd.DataFrame:
    """GET a FRED series' full daily history; return a date-indexed single-column 'value' frame.

    Rows with the FRED missing marker (".") are dropped; value -> float, date -> datetime.
    """
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY not set in environment")
    query = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": observation_start,
    })
    url = f"{_FRED_URL}?{query}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    rows = []
    for obs in data.get("observations", []):
        value = obs.get("value")
        if value == ".":
            continue
        rows.append({"date": obs.get("date"), "value": float(value)})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df


def fetch_baa10y() -> bool:
    """Fetch BAA10Y full history into the store. Returns True on success."""
    df = fetch_fred_series("BAA10Y", observation_start=_DEFAULT_START)
    if df is None or df.empty:
        return False
    store.write_series("BAA10Y", df, source="FRED", adjusted=False)
    return True
