"""Fetch a broad-US market-breadth advance/decline feed into the Parquet store.

Source: thetrading.tools advance-decline JSON (free, ~5,600 broad-US issues, daily
to 2010-01-04). This is a VALIDATED breadth SUBSTITUTE for Fosback's NYSE-only ABI,
NOT the literal NYSE count — flagged as `broad_us_abi_proxy` (it includes illiquid
micro-caps we cannot liquidity-filter without per-stock data; a documented caveat).

ABI is a SELF-NORMALIZING ratio so the growing-universe artifact does not leak into
the level (verified: yearly-median ABI is roughly stationary 0.21-0.32 while the issue
count doubles 2,407 -> 5,453). We RECOMPUTE total = adv+dec+unch and abi = |adv-dec|/total
in the fetcher rather than trusting external fields, and persist append-only so historical
rows are never overwritten (silent-restatement guard).

Stored as series 'ABINYSE' with columns: adv, dec, unch, total, abi  (all same-day, PIT).
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np
import pandas as pd

from . import store

_URL = "https://www.thetrading.tools/data/market_breadth/ad_line.json"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Referer": "https://www.thetrading.tools/advance-decline-line",
}


def fetch_breadth_frame() -> pd.DataFrame:
    """Download the feed; return a date-indexed frame with adv/dec/unch/total/abi.

    total and abi are recomputed locally (never trust the external aggregate).
    """
    req = urllib.request.Request(_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    rows = data if isinstance(data, list) else (
        data.get("data") or next((v for v in data.values() if isinstance(v, list)), None))
    if not rows:
        raise RuntimeError("thetrading.tools breadth feed returned no rows")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    adv = df["advancing"].astype(float)
    dec = df["declining"].astype(float)
    unch = df["unchanged"].astype(float)
    total = adv + dec + unch
    abi = (adv - dec).abs() / total.replace(0.0, np.nan)
    out = pd.DataFrame({"adv": adv, "dec": dec, "unch": unch, "total": total, "abi": abi})
    out = out[(out["total"] > 0) & np.isfinite(out["abi"])]
    return out


def fetch_breadth(append_only: bool = True) -> bool:
    """Fetch the breadth feed into the store as 'ABINYSE'.

    append_only: if a snapshot already exists, KEEP every existing historical row
    unchanged and only add genuinely new dates (silent-restatement guard). A changed
    historical row is logged but the committed value is preserved.
    """
    fresh = fetch_breadth_frame()
    if fresh is None or fresh.empty:
        return False
    if append_only and store.series_exists("ABINYSE"):
        existing = store.read_series("ABINYSE")
        new_dates = fresh.index.difference(existing.index)
        # detect (but do not apply) any restatement of overlapping historical rows
        overlap = fresh.index.intersection(existing.index)
        if len(overlap):
            diff = (fresh.loc[overlap, "abi"] - existing.loc[overlap, "abi"]).abs()
            n_restated = int((diff > 1e-9).sum())
            if n_restated:
                print(f"  WARNING: {n_restated} historical ABINYSE rows differ from the "
                      f"committed snapshot — keeping committed values (restatement guard).")
        merged = pd.concat([existing, fresh.loc[new_dates]]).sort_index()
        store.write_series("ABINYSE", merged, source="thetrading.tools", adjusted=False)
    else:
        store.write_series("ABINYSE", fresh, source="thetrading.tools", adjusted=False)
    return True
