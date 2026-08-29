#!/usr/bin/env python3
"""Shared data layer for TODO #106 (professional day-trader methods).

Loads the local minute files into dense (symbol-date x minute) matrices and
derives every context field the frozen methods are allowed to use.

Everything here is point-in-time by construction: a value stamped at minute `t`
uses only bars that had already CLOSED at `t`.  Nothing in this file reads a
profit number.

No network.  No spend.  Read-only with respect to production code.
"""

from pathlib import Path

import numpy as np
import pandas as pd

RES_DIR = Path(__file__).resolve().parents[2] / ".omc/research/professional-day-trader-methods"

# ---------------------------------------------------------------- clocks ----
# Minute-of-day, US/Eastern.  Pacific is Eastern minus 180.
MIN_OPEN = 9 * 60 + 30       # 09:30 ET = 06:30 PT, first regular bar
MIN_LAST = 15 * 60 + 59      # 15:59 ET = 12:59 PT, last regular bar
N_MIN = MIN_LAST - MIN_OPEN + 1                      # 390
OR_LAST = MIN_OPEN + 14      # 09:44 ET, last bar of the 15-minute opening range
OR_KNOWN = OR_LAST + 1       # 09:45 ET = 06:45 PT, earliest minute the range exists

def pt(minute_et: int) -> str:
    """Eastern minute-of-day -> Pacific clock string, for anything a human reads."""
    m = minute_et - 180
    return f"{m // 60:02d}:{m % 60:02d}"

# ------------------------------------------------------------ date split ----
# Reused unchanged from TODO #104, whose sealed block was never opened
# (see .omc/research/immediate-profitable-share-feature/FINAL-VERDICT.md).
DEV_LAST = "2025-11-28"
SEALED_FIRST = "2025-12-01"

# ------------------------------------------------------ corporate actions ----
# Share splits inside the sample, found as |overnight gap| > 25% whose ratio is
# a round number, and confirmed against the ratio itself.  Prices in the raw
# Databento files are NOT split-adjusted, so the split session is dropped for
# that symbol: its prior-session references are on the pre-split scale.
SPLITS = {
    ("ANET", "2024-12-04"),   # 4-for-1
    ("APH", "2024-06-12"),    # 2-for-1
    ("NOW", "2025-12-18"),    # 5-for-1
}

# -------------------------------------------------------------- sectors -----
# Sector labels for the 60-name universe.  These are CURRENT labels applied
# backwards; this is not a point-in-time security master and is recorded as a
# limitation everywhere it is used.  GEV is a 2024 spin-off from GE and only
# has history from its own listing date.
SECTOR = {
    "TSM": "Technology", "ORCL": "Technology", "CRM": "Technology",
    "DELL": "Technology", "IBM": "Technology", "NOW": "Technology",
    "GLW": "Technology", "COHR": "Technology", "ANET": "Technology",
    "VRT": "Technology", "APH": "Technology", "ACN": "Technology",
    "SNOW": "Technology", "CIEN": "Technology",
    "JPM": "Financials", "V": "Financials", "GS": "Financials",
    "BAC": "Financials", "MA": "Financials", "C": "Financials",
    "MS": "Financials", "WFC": "Financials", "AXP": "Financials",
    "SCHW": "Financials", "SPGI": "Financials", "BRK.B": "Financials",
    "LLY": "Healthcare", "UNH": "Healthcare", "JNJ": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "TMO": "Healthcare",
    "ABT": "Healthcare", "PFE": "Healthcare", "DHR": "Healthcare",
    "MCK": "Healthcare",
    "CAT": "Industrials", "GEV": "Industrials", "GE": "Industrials",
    "BE": "Industrials", "BA": "Industrials", "RTX": "Industrials",
    "ETN": "Industrials", "UBER": "Industrials",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy",
    "KO": "Staples", "PG": "Staples", "PM": "Staples",
    "MCD": "Discretionary", "HD": "Discretionary", "TJX": "Discretionary",
    "VZ": "Communications", "T": "Communications", "DIS": "Communications",
    "NEE": "Utilities",
    "SHW": "Materials", "NEM": "Materials",
    "WELL": "RealEstate",
}


# ------------------------------------------------------------ dense panel ----
class Panel:
    """Dense minute matrices for one feed.

    Rows are symbol-dates (`idx`), columns are the 390 regular-session minutes.
    A missing minute is NaN in the price fields and 0 in volume.
    """

    __slots__ = ("idx", "o", "h", "l", "c", "v", "feed", "_row_of")

    def __init__(self, idx, o, h, l, c, v, feed):
        self.idx, self.o, self.h, self.l, self.c, self.v, self.feed = idx, o, h, l, c, v, feed
        self._row_of = {(s, d): i for i, (s, d) in enumerate(zip(idx.symbol.values, idx.date.values))}

    def row_of(self, symbol, date):
        return self._row_of.get((symbol, date))

    def __len__(self):
        return len(self.idx)


def _cache_paths(feed):
    return (RES_DIR / f"panel-{feed}-idx.parquet",
            RES_DIR / f"panel-{feed}-mat.npz")


def build_panel(feed="equs", rebuild=False) -> Panel:
    """Build (or load) the dense matrices for `feed` in {'equs','pillar'}.

    Written column by column: this box has ~3 GB free, so the 20-million-row
    source is never materialised as one wide frame.
    """
    import pyarrow.parquet as pq

    idx_p, mat_p = _cache_paths(feed)
    if idx_p.exists() and mat_p.exists() and not rebuild:
        idx = pd.read_parquet(idx_p)
        z = np.load(mat_p)
        return Panel(idx, z["o"], z["h"], z["l"], z["c"], z["v"], feed)

    src = str(RES_DIR / f"bars-{feed}-allmin.parquet")

    key_tab = pq.read_table(src, columns=["date", "symbol", "minute"])
    minute = key_tab.column("minute").to_numpy().astype(np.int32)
    keep = (minute >= MIN_OPEN) & (minute <= MIN_LAST)
    col = (minute[keep] - MIN_OPEN).astype(np.int32)
    del minute

    dcat = key_tab.column("date").combine_chunks()
    if not hasattr(dcat, "dictionary"):
        dcat = dcat.dictionary_encode()
    dates = np.array(dcat.dictionary.to_pylist())
    dcode = dcat.indices.to_numpy().astype(np.int32)[keep]
    scat = key_tab.column("symbol").combine_chunks()
    if not hasattr(scat, "dictionary"):
        scat = scat.dictionary_encode()
    syms = np.array(scat.dictionary.to_pylist())
    scode = scat.indices.to_numpy().astype(np.int32)[keep]
    del key_tab, dcat, scat

    pair = scode.astype(np.int64) * len(dates) + dcode
    uniq, row = np.unique(pair, return_inverse=True)
    row = row.astype(np.int32)
    idx = pd.DataFrame({"symbol": syms[(uniq // len(dates)).astype(int)],
                        "date": dates[(uniq % len(dates)).astype(int)]})
    del pair, dcode, scode, uniq

    n = len(idx)
    out = {}
    for field, name in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
        vals = pq.read_table(src, columns=[name]).column(name).to_numpy()[keep]
        m = np.full((n, N_MIN), np.nan, dtype=np.float32)
        m[row, col] = vals.astype(np.float32)
        out[field] = m
        del vals
    vals = pq.read_table(src, columns=["volume"]).column("volume").to_numpy()[keep]
    m = np.zeros((n, N_MIN), dtype=np.float32)
    m[row, col] = vals.astype(np.float32)
    out["v"] = m
    del vals, row, col, keep

    order = np.lexsort((idx.date.values, idx.symbol.values))
    idx = idx.iloc[order].reset_index(drop=True)
    for k in list(out):
        out[k] = np.ascontiguousarray(out[k][order])

    idx.to_parquet(idx_p, index=False)
    np.savez(mat_p, **out)
    return Panel(idx, out["o"], out["h"], out["l"], out["c"], out["v"], feed)


# ------------------------------------------------------- derived context ----
def session_frame(p: Panel) -> pd.DataFrame:
    """One row per symbol-date with the session-level facts, plus the previous
    session's facts joined on (symbol, previous date for that symbol)."""
    d = p.idx.copy()
    o, h, l, c, v = p.o, p.h, p.l, p.c, p.v
    d["n_bars"] = np.isfinite(c).sum(1)
    d["sess_open"] = _first_valid(o)
    d["sess_close"] = _last_valid(c)
    d["sess_high"] = np.nanmax(h, axis=1)
    d["sess_low"] = np.nanmin(l, axis=1)
    d["sess_vol"] = v.sum(1)
    d["or_high"] = np.nanmax(h[:, : OR_LAST - MIN_OPEN + 1], axis=1)
    d["or_low"] = np.nanmin(l[:, : OR_LAST - MIN_OPEN + 1], axis=1)
    d["or_vol"] = v[:, : OR_LAST - MIN_OPEN + 1].sum(1)
    # how many of the opening range's 15 minutes actually traded.  This is the
    # liveness check a rule may use, because it is known at 06:45.  The whole
    # session's bar count is NOT: at 06:45 nobody knows how the afternoon goes.
    d["or_bars"] = np.isfinite(c[:, : OR_LAST - MIN_OPEN + 1]).sum(1)
    d["is_split"] = [(s, dt) in SPLITS for s, dt in zip(d.symbol, d.date)]
    d["sector"] = d.symbol.map(SECTOR)

    d = d.sort_values(["symbol", "date"], ignore_index=True)
    g = d.groupby("symbol", sort=False)
    for src, dst in [("sess_high", "prev_high"), ("sess_low", "prev_low"),
                     ("sess_close", "prev_close"), ("sess_vol", "prev_vol"),
                     ("date", "prev_date")]:
        d[dst] = g[src].shift(1)
    # 20-session median dollar volume, known before today (shifted by one)
    d["dollar_vol"] = d.sess_vol * d.sess_close
    d["adv20"] = g.dollar_vol.transform(
        lambda s: s.shift(1).rolling(20, min_periods=15).median())
    d["atr20"] = g.apply(
        lambda x: ((x.sess_high - x.sess_low) / x.sess_close).shift(1)
        .rolling(20, min_periods=15).median(), include_groups=False).reset_index(level=0, drop=True)
    return d


def _first_valid(m):
    out = np.full(m.shape[0], np.nan, dtype=np.float64)
    ok = np.isfinite(m)
    any_ok = ok.any(1)
    first = ok.argmax(1)
    out[any_ok] = m[np.arange(m.shape[0])[any_ok], first[any_ok]]
    return out


def _last_valid(m):
    rev = m[:, ::-1]
    out = _first_valid(rev)
    return out


def ffill_close(p: Panel) -> np.ndarray:
    """Close price carried forward across missing minutes, float32.

    Used only for context fields (composites, relative strength).  It is never
    used as a fill price: a trade may only be filled on a minute that has a
    real bar.
    """
    c = p.c.copy()
    n, k = c.shape
    idx = np.where(np.isfinite(c), np.arange(k)[None, :], -1)
    np.maximum.accumulate(idx, axis=1, out=idx)
    valid = idx >= 0
    rows = np.arange(n)[:, None]
    out = np.where(valid, c[rows, np.clip(idx, 0, k - 1)], np.nan)
    return out.astype(np.float32)
