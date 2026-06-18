"""Fetch the CBOE daily put/call ratios into the Parquet store.

Source: CBOE's public daily market-statistics page
(cboe.com/us/options/market_statistics/daily/?dt=YYYY-MM-DD). The ratios are
embedded in the page's server-rendered Next.js JSON payload under
optionsData.ratios (no auth, no API key). A `dt=` query param requests a
specific trading day, so free history is backfillable to ~2019-10-15; older
dates and non-trading days return no ratios block (silently skipped).

We keep TOTAL / EQUITY / INDEX put-call (and the ETP ratio when present). The
total put/call is the classic contrarian fear gauge; high readings cluster at
market bottoms. All values are same-day, point-in-time (the ratio published for
that trading session), persisted append-only so committed history is never
overwritten (silent-restatement guard).

Stored as series 'CBOE_PUTCALL' with columns: total, equity, index, etp
(all lowercase, PIT).
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pandas as pd
import requests

from . import store

_URL = "https://www.cboe.com/us/options/market_statistics/daily/"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
# CBOE free history floor (probed 2026-06-18: 2019-10-15 returns ratios, 2019-10-01 does not).
_BACKFILL_START = "2019-10-15"

# map CBOE ratio names -> our lowercase columns
_NAME_MAP = {
    "TOTAL PUT/CALL RATIO": "total",
    "EQUITY PUT/CALL RATIO": "equity",
    "INDEX PUT/CALL RATIO": "index",
    "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO": "etp",
}


def _ratios_for_day(dt: str) -> dict | None:
    """Return {total, equity, index, etp} for one trading day, or None if no data.

    dt is 'YYYY-MM-DD'. Parses the ratios array out of the page's __next_f payload.
    """
    resp = requests.get(_URL, params={"dt": dt}, headers=_HEADERS, timeout=30)
    if resp.status_code != 200:
        return None
    body = resp.text
    m = re.search(r'\\"ratios\\":(\[.*?\])\s*,\\"SUM OF ALL PRODUCTS', body)
    if m is None:
        m = re.search(r'"ratios":(\[.*?\])', body)
    if m is None:
        return None
    raw = m.group(1).replace('\\"', '"')
    try:
        arr = json.loads(raw)
    except json.JSONDecodeError:
        return None
    named = {x.get("name"): x.get("value") for x in arr if isinstance(x, dict)}
    out: dict[str, float] = {}
    for cboe_name, col in _NAME_MAP.items():
        v = named.get(cboe_name)
        if v is None:
            continue
        try:
            out[col] = float(v)
        except (TypeError, ValueError):
            continue
    # require at least the total ratio for a row to count
    if "total" not in out:
        return None
    return out


def fetch_putcall_frame(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Download CBOE put/call ratios over [start, end]; return a date-indexed frame.

    Iterates calendar days, skipping weekends and any day the source has no data
    (holidays / pre-history). Each cell is the ratio published for that session.
    """
    start_d = date.fromisoformat(start or _BACKFILL_START)
    end_d = date.fromisoformat(end) if end else date.today()
    rows: dict[pd.Timestamp, dict] = {}
    d = start_d
    while d <= end_d:
        if d.weekday() < 5:  # Mon-Fri only
            r = _ratios_for_day(d.isoformat())
            if r:
                rows[pd.Timestamp(d)] = r
        d += timedelta(days=1)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    # stable column order; only keep columns that actually appeared
    cols = [c for c in ("total", "equity", "index", "etp") if c in out.columns]
    return out[cols]


def fetch_putcall(append_only: bool = True) -> bool:
    """Fetch CBOE put/call ratios into the store as 'CBOE_PUTCALL'.

    First run backfills from the free-history floor (~2019-10-15). On later runs
    (append_only) only NEW trading days after the last stored date are fetched;
    every existing historical row is kept unchanged (silent-restatement guard),
    and a changed overlapping value is warned about but not applied.
    """
    if append_only and store.series_exists("CBOE_PUTCALL"):
        existing = store.read_series("CBOE_PUTCALL")
        last = existing.index.max().date()
        # re-fetch from the day after the last stored date through today
        fresh = fetch_putcall_frame(start=(last + timedelta(days=1)).isoformat())
        if fresh.empty:
            return False
        new_dates = fresh.index.difference(existing.index)
        overlap = fresh.index.intersection(existing.index)
        if len(overlap):
            diff = (fresh.loc[overlap, "total"] - existing.loc[overlap, "total"]).abs()
            n_restated = int((diff > 1e-9).sum())
            if n_restated:
                print(f"  WARNING: {n_restated} historical CBOE_PUTCALL rows differ from the "
                      f"committed snapshot — keeping committed values (restatement guard).")
        if len(new_dates) == 0:
            return False
        merged = pd.concat([existing, fresh.loc[new_dates]]).sort_index()
        store.write_series("CBOE_PUTCALL", merged, source="cboe.com daily market statistics", adjusted=False)
        return True
    fresh = fetch_putcall_frame()
    if fresh.empty:
        return False
    store.write_series("CBOE_PUTCALL", fresh, source="cboe.com daily market statistics", adjusted=False)
    return True


if __name__ == "__main__":
    ok = fetch_putcall()
    print("CBOE_PUTCALL updated" if ok else "CBOE_PUTCALL: no new rows")
