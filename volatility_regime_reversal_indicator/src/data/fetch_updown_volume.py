"""Fetch the historical NYSE advance/decline VOLUME archive into the Parquet store.

Source: unicorn.us.com's free advance/decline archive (Carl Futia's mirror of the
classic NYSE breadth tape). Five plain-CSV files, no header, 'YYYYMMDD, value' rows,
requiring a browser User-Agent:
  NYSE_advv.csv  -> advancing volume   (shares)
  NYSE_declv.csv -> declining volume   (shares)
  NYSE_unchv.csv -> unchanged volume   (shares)
  NYSE_advn.csv  -> advancing ISSUE count
  NYSE_decln.csv -> declining ISSUE count

History runs 1965-03-01 onward. The archive STOPPED updating on 2020-02-10: every
row dated after that is an all-zeros placeholder, not a real session. We HARD-DROP
those zero-volume padding rows (truncate at the last real day, 2020-02-10) so the
store never contains fake zero-volume sessions. The five series are inner-joined on
the date index so every stored row has all five fields present (point-in-time: each
row is one settled NYSE session's own-day breadth, no look-ahead).

This is the HISTORICAL BACKFILL companion to the forward-collected 'NYSE_BREADTH'
feed (fetch_nyse_breadth.py): same volume-split fields, but covering 1965-2020 that
the live TradingView scan cannot reach. Raw daily values only — no features or
percentiles are computed here.

Stored as series 'NYSE_UDVOL' with columns: adv_volume, dec_volume, unch_volume,
adv_issues, dec_issues  (all lowercase, same-day, PIT). Persisted append-only so
committed history is never overwritten (silent-restatement guard).
"""
from __future__ import annotations

import io
import urllib.request

import pandas as pd

from . import store

_BASE = "http://unicorn.us.com/advdec/"
_FILES = {
    "adv_volume": "NYSE_advv.csv",
    "dec_volume": "NYSE_declv.csv",
    "unch_volume": "NYSE_unchv.csv",
    "adv_issues": "NYSE_advn.csv",
    "dec_issues": "NYSE_decln.csv",
}
# The archive froze here; later rows are all-zero padding and are dropped.
_LAST_REAL_DAY = pd.Timestamp("2020-02-10")
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
}


def _fetch_one(filename: str, colname: str) -> pd.Series:
    """Download one 'YYYYMMDD, value' CSV; return a date-indexed float Series."""
    req = urllib.request.Request(_BASE + filename, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    df = pd.read_csv(
        io.StringIO(raw),
        header=None,
        names=["date", colname],
        skipinitialspace=True,
    )
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    s = df.set_index("date")[colname].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def fetch_updown_volume_frame() -> pd.DataFrame:
    """Download all five series; inner-join on date; drop the zero padding tail.

    Inner join keeps only dates present in every series so each stored row is
    complete. Rows after 2020-02-10 (all-zeros placeholders) are truncated.
    """
    series = {col: _fetch_one(fn, col) for col, fn in _FILES.items()}
    out = pd.concat(series.values(), axis=1, join="inner")
    out.columns = list(_FILES.keys())
    out = out.sort_index()
    # Hard limit: drop the zero-volume padding tail that begins after the freeze.
    out = out[out.index <= _LAST_REAL_DAY]
    # Defensive: any all-zero volume row inside the kept range is not a real session.
    vol_cols = ["adv_volume", "dec_volume", "unch_volume"]
    out = out[out[vol_cols].sum(axis=1) > 0]
    return out


def fetch_updown_volume(append_only: bool = True) -> bool:
    """Fetch the up/down volume archive into the store as 'NYSE_UDVOL'.

    append_only: if a snapshot already exists, KEEP every existing historical row
    unchanged and only add genuinely new dates (silent-restatement guard). A changed
    historical row is logged but the committed value is preserved.
    """
    fresh = fetch_updown_volume_frame()
    if fresh is None or fresh.empty:
        return False
    if append_only and store.series_exists("NYSE_UDVOL"):
        existing = store.read_series("NYSE_UDVOL")
        new_dates = fresh.index.difference(existing.index)
        overlap = fresh.index.intersection(existing.index)
        if len(overlap):
            diff = (fresh.loc[overlap, "dec_volume"] - existing.loc[overlap, "dec_volume"]).abs()
            n_restated = int((diff > 0).sum())
            if n_restated:
                print(f"  WARNING: {n_restated} historical NYSE_UDVOL rows differ from the "
                      f"committed snapshot — keeping committed values (restatement guard).")
        if len(new_dates) == 0:
            return False
        merged = pd.concat([existing, fresh.loc[new_dates]]).sort_index()
        store.write_series("NYSE_UDVOL", merged, source="unicorn.us.com/advdec", adjusted=False)
        return True
    store.write_series("NYSE_UDVOL", fresh, source="unicorn.us.com/advdec", adjusted=False)
    return True


if __name__ == "__main__":
    ok = fetch_updown_volume()
    print("NYSE_UDVOL updated" if ok else "NYSE_UDVOL: no new rows")
