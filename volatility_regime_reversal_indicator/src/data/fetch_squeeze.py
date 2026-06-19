"""Fetch the free SqueezeMetrics dealer-gamma + dark-pool daily CSV into the store.

Source: squeezemetrics.com/monitor/static/DIX.csv (free, no auth, ~3,806 daily rows
to 2011-05-02). Columns are date,price,dix,gex. We ignore `price` (we already store
SPY) and keep the two signal columns:

  dix -- Dark Index, a 0-1 ratio estimating the share of off-exchange (dark-pool)
         volume that is buying. HIGH dix = more hidden buying (supportive); LOW dix
         clusters near tops/pullbacks.
  gex -- Gamma Exposure, dealers' aggregate gamma in dollars (CAN BE NEGATIVE).
         POSITIVE gex = dealers dampen moves (mean-reverting, calm); NEGATIVE gex =
         dealers amplify moves (trend, fragile) and clusters near volatile bottoms.

These are RAW daily values exactly as published — no percentiles, no z-scores, no
features computed here (that is a later build step, deliberately kept out so the
stored series stays a faithful PIT record of what the source said that day).

Point-in-time discipline: each row is the value published for that trading session,
stored same-day, append-only so committed history is never overwritten. SqueezeMetrics
serves a single full-history CSV, so on later runs we re-download the whole file but
only ADD genuinely new dates; any overlapping historical row that differs from the
committed snapshot is warned about and NOT applied (silent-restatement guard). This
keeps backtests reproducible and look-ahead-free — a revised vendor value can never
silently rewrite a date the backtest already saw.

Stored as series 'SQZ' with columns: dix, gex (all lowercase, PIT).
"""
from __future__ import annotations

import csv
import io
import urllib.request

import numpy as np
import pandas as pd

from . import store

_URL = "https://squeezemetrics.com/monitor/static/DIX.csv"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Accept": "text/csv,text/plain,*/*",
}


def fetch_squeeze_frame() -> pd.DataFrame:
    """Download the DIX.csv feed; return a date-indexed frame with dix, gex.

    The `price` column is dropped (SPY is already stored). Rows with a missing or
    non-numeric dix/gex are skipped so the stored series carries only real values.
    """
    req = urllib.request.Request(_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise RuntimeError("SqueezeMetrics DIX.csv returned no rows")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    dix = pd.to_numeric(df["dix"], errors="coerce")
    gex = pd.to_numeric(df["gex"], errors="coerce")
    out = pd.DataFrame({"dix": dix, "gex": gex})
    # keep only rows where BOTH signals are finite (gex may be negative — that's valid)
    out = out[np.isfinite(out["dix"]) & np.isfinite(out["gex"])]
    return out


def fetch_squeeze(append_only: bool = True) -> bool:
    """Fetch the SqueezeMetrics feed into the store as 'SQZ'.

    First run populates from inception (2011-05-02). On later runs (append_only) the
    full CSV is re-downloaded but only genuinely NEW dates are added; every existing
    historical row is kept unchanged (silent-restatement guard) and a changed
    overlapping value is warned about but not applied.
    """
    fresh = fetch_squeeze_frame()
    if fresh is None or fresh.empty:
        return False
    if append_only and store.series_exists("SQZ"):
        existing = store.read_series("SQZ")
        new_dates = fresh.index.difference(existing.index)
        # detect (but do not apply) any restatement of overlapping historical rows
        overlap = fresh.index.intersection(existing.index)
        if len(overlap):
            diff = (fresh.loc[overlap, "dix"] - existing.loc[overlap, "dix"]).abs()
            n_restated = int((diff > 1e-9).sum())
            if n_restated:
                print(f"  WARNING: {n_restated} historical SQZ rows differ from the "
                      f"committed snapshot — keeping committed values (restatement guard).")
        if len(new_dates) == 0:
            return False
        merged = pd.concat([existing, fresh.loc[new_dates]]).sort_index()
        store.write_series("SQZ", merged, source="squeezemetrics.com DIX.csv", adjusted=False)
    else:
        store.write_series("SQZ", fresh, source="squeezemetrics.com DIX.csv", adjusted=False)
    return True


if __name__ == "__main__":
    ok = fetch_squeeze()
    print("SQZ updated" if ok else "SQZ: no new rows")
