"""Fetch true NYSE breadth WITH up/down VOLUME into the Parquet store.

Source: TradingView's public stock-screener scan endpoint
(scanner.tradingview.com/america/scan). We filter to NYSE-listed common stocks
(type=stock, which excludes the 431 ETFs and 187 depository receipts on the
exchange) and split on the day's price change to get advancing / declining /
unchanged ISSUE counts plus the SUM of each group's share VOLUME. The volume
split is the field our existing ABINYSE feed lacks; it is what enables a future
Lowry 90/90 up-volume / down-volume rule.

No auth, no API key. This source only exposes the LATEST settled session, so
this feed is FORWARD-COLLECTION: each daily after-close run appends exactly one
row dated for the just-closed trading day. No historical backfill is possible.

All values are same-day, point-in-time (the session's closing breadth). Persisted
append-only so committed history is never overwritten (silent-restatement guard).

Stored as series 'NYSE_BREADTH' with columns: adv_issues, dec_issues,
unch_issues, adv_volume, dec_volume (all lowercase, PIT).
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import requests

from . import store

_URL = "https://scanner.tradingview.com/america/scan"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "text/plain;charset=UTF-8",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}
_BASE_FILTER = [
    {"left": "exchange", "operation": "equal", "right": "NYSE"},
    {"left": "type", "operation": "equal", "right": "stock"},
]


def _scan(change_op: str, change_val: float) -> tuple[int, float]:
    """Return (issue_count, summed_volume) for NYSE stocks matching a change condition."""
    payload = {
        "filter": _BASE_FILTER + [{"left": "change", "operation": change_op, "right": change_val}],
        "columns": ["volume"],
        "range": [0, 5000],
    }
    resp = requests.post(_URL, headers=_HEADERS, data=json.dumps(payload), timeout=40)
    resp.raise_for_status()
    j = resp.json()
    count = int(j.get("totalCount") or 0)
    rows = j.get("data") or []
    vol = sum(r["d"][0] for r in rows if r.get("d") and r["d"][0] is not None)
    return count, float(vol)


def fetch_nyse_breadth_frame() -> pd.DataFrame:
    """Scan the latest NYSE session; return a single-row date-indexed frame.

    Row is dated today (the just-closed session). Columns: adv_issues, dec_issues,
    unch_issues, adv_volume, dec_volume.
    """
    adv_n, adv_vol = _scan("greater", 0)
    dec_n, dec_vol = _scan("less", 0)
    unch_n, _ = _scan("equal", 0)
    if adv_n == 0 and dec_n == 0:
        raise RuntimeError("TradingView NYSE scan returned no advancing or declining issues")
    idx = pd.DatetimeIndex([pd.Timestamp(date.today())])
    return pd.DataFrame(
        {
            "adv_issues": [adv_n],
            "dec_issues": [dec_n],
            "unch_issues": [unch_n],
            "adv_volume": [adv_vol],
            "dec_volume": [dec_vol],
        },
        index=idx,
    )


def fetch_nyse_breadth(append_only: bool = True) -> bool:
    """Fetch the latest NYSE breadth+volume row into the store as 'NYSE_BREADTH'.

    Forward-collection: appends one row per trading day. Re-running on the same
    day is a no-op (the date already exists). append_only keeps every committed
    historical row unchanged and only adds genuinely new dates (restatement guard).
    """
    fresh = fetch_nyse_breadth_frame()
    if fresh is None or fresh.empty:
        return False
    if append_only and store.series_exists("NYSE_BREADTH"):
        existing = store.read_series("NYSE_BREADTH")
        new_dates = fresh.index.difference(existing.index)
        overlap = fresh.index.intersection(existing.index)
        if len(overlap):
            diff = (fresh.loc[overlap, "adv_issues"] - existing.loc[overlap, "adv_issues"]).abs()
            n_restated = int((diff > 0).sum())
            if n_restated:
                print(f"  WARNING: {n_restated} historical NYSE_BREADTH rows differ from the "
                      f"committed snapshot — keeping committed values (restatement guard).")
        if len(new_dates) == 0:
            return False
        merged = pd.concat([existing, fresh.loc[new_dates]]).sort_index()
        store.write_series("NYSE_BREADTH", merged, source="tradingview.com scanner", adjusted=False)
        return True
    store.write_series("NYSE_BREADTH", fresh, source="tradingview.com scanner", adjusted=False)
    return True


if __name__ == "__main__":
    ok = fetch_nyse_breadth()
    print("NYSE_BREADTH updated" if ok else "NYSE_BREADTH: no new row")
