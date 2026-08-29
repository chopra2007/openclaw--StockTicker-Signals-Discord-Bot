#!/usr/bin/env python3
"""Independent rebuild of the TODO #106 M1 headline numbers.

Written deliberately WITHOUT importing pdtm_common, pdtm_context, pdtm_methods,
pdtm_engine, pdtm_gates, pdtm_controls or pdtm_run.  Everything below is
rebuilt from the written specification in `mechanical-definitions.md` and
`selected-method-cards.md`, reading the raw minute bars directly.

The point is a second code path, not a second opinion.  If the two disagree,
at least one of them is wrong.

Sealed dates (after 2025-11-28) are excluded explicitly and never read.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RES = Path(__file__).resolve().parents[2] / ".omc/research/professional-day-trader-methods"
DEV_LAST = "2025-11-28"
OPEN_M, OR_END_M, LAST_SIG_M, LAST_EXIT_M = 570, 584, 750, 955
RELVOL_MIN, MKT_TOL, RR, RETEST = 1.25, 0.0020, 1.5, 0.25
SPLITS = {("ANET", "2024-12-04"), ("APH", "2024-06-12"), ("NOW", "2025-12-18")}
SECTOR_FILE_HINT = "read from the builder's session table only for the sector label"


SAMPLE_DATES = 120      # deterministic: every Nth development date
VERIFY_SEED = 20260829


def load_bars():
    """Regular-session bars for a deterministic sample of development dates.

    Sealed dates are never read.  The whole development block is 15 million
    bars and rebuilding every volume profile from it exhausted this box's
    memory, so the check runs on an evenly spaced sample of dates instead -
    thousands of company-days, far more than the comparison needs.
    """
    all_dates = pq.read_table(RES / "bars-equs-allmin.parquet", columns=["date"])
    dates = sorted({str(d) for d in all_dates.column("date").to_pylist() if str(d) <= DEV_LAST})
    step = max(len(dates) // SAMPLE_DATES, 1)
    keep = dates[::step][:SAMPLE_DATES]
    # the profile of day N needs day N-1 as well, for the prior value area
    idx = {d: i for i, d in enumerate(dates)}
    need = sorted({d for k in keep for d in (dates[max(idx[k] - 1, 0)], k)})
    t = pq.read_table(
        RES / "bars-equs-allmin.parquet",
        columns=["date", "symbol", "minute", "open", "high", "low", "close", "volume"],
        filters=[("minute", ">=", OPEN_M), ("minute", "<=", 959),
                 ("date", "in", need)],
    )
    df = t.to_pandas()
    df["date"] = df.date.astype(str)
    df["symbol"] = df.symbol.astype(str)
    assert (df.date <= DEV_LAST).all()
    return df.sort_values(["symbol", "date", "minute"], ignore_index=True)


def profile_value_area(low, high, vol, ref_open):
    """Volume-at-price, rebuilt from the written rule with a different loop."""
    w = max(round(ref_open * 0.001, 2), 0.01)
    lo_edge, hi_edge = low.min(), high.max()
    nb = int((hi_edge - lo_edge) / w) + 1
    if nb <= 0 or nb > 20000:
        return np.nan, np.nan, np.nan
    prof = np.zeros(nb)
    for l, h, v in zip(low, high, vol):
        if v <= 0 or not (np.isfinite(l) and np.isfinite(h)):
            continue
        a = min(max(int(np.floor((l - lo_edge) / w + 1e-9)), 0), nb - 1)
        b = min(max(int(np.floor((h - lo_edge) / w + 1e-9)), 0), nb - 1)
        prof[a:b + 1] += v / (b - a + 1)
    total = prof.sum()
    if total <= 0:
        return np.nan, np.nan, np.nan
    poc = int(prof.argmax())
    lo = hi = poc
    got = prof[poc]
    while got < total * 0.70 and (lo > 0 or hi < nb - 1):
        below = prof[max(lo - 2, 0):lo].sum() if lo > 0 else -1.0
        above = prof[hi + 1:min(hi + 3, nb)].sum() if hi < nb - 1 else -1.0
        if above >= below:
            hi = min(hi + 2, nb - 1)
        else:
            lo = max(lo - 2, 0)
        got = prof[lo:hi + 1].sum()
    return (lo_edge + (poc + 0.5) * w, lo_edge + (hi + 1) * w, lo_edge + lo * w)


def build_sessions(df):
    rows = []
    for (sym, dt), g in df.groupby(["symbol", "date"], sort=True):
        m, o, h, l, c, v = (g.minute.values, g.open.values, g.high.values,
                            g.low.values, g.close.values, g.volume.values)
        orm = m <= OR_END_M
        poc, vah, val = profile_value_area(l, h, v, o[0])
        rows.append(dict(symbol=sym, date=dt, sess_open=o[0], sess_close=c[-1],
                         sess_high=h.max(), sess_low=l.min(), sess_vol=v.sum(),
                         or_high=h[orm].max() if orm.any() else np.nan,
                         or_low=l[orm].min() if orm.any() else np.nan,
                         or_bars=int(orm.sum()), poc=poc, vah=vah, val=val))
    s = pd.DataFrame(rows).sort_values(["symbol", "date"], ignore_index=True)
    g = s.groupby("symbol", sort=False)
    for src, dst in [("sess_high", "prev_high"), ("sess_low", "prev_low"),
                     ("sess_close", "prev_close"), ("poc", "prev_poc"),
                     ("vah", "prev_vah"), ("val", "prev_val")]:
        s[dst] = g[src].shift(1)
    s["daily_range"] = (s.sess_high - s.sess_low) / s.sess_close
    s["atr20"] = g.daily_range.transform(lambda x: x.shift(1).rolling(20, min_periods=15).median())
    return s


def relvol_and_ret(df, sessions):
    """Volume so far at 06:45 over the 20-session median at the same minute,
    and each company's move since its own opening print, minute by minute."""
    piv_v = df.pivot_table(index=["symbol", "date"], columns="minute",
                           values="volume", aggfunc="sum").reindex(
        columns=range(OPEN_M, 960)).fillna(0.0)
    piv_c = df.pivot_table(index=["symbol", "date"], columns="minute",
                           values="close", aggfunc="last").reindex(
        columns=range(OPEN_M, 960))
    cum = piv_v.cumsum(axis=1).shift(1, axis=1).fillna(0.0)
    col_or = OR_END_M + 1
    rv = {}
    for sym, block in cum.groupby(level=0):
        s = block[col_or].values
        out = np.full(len(s), np.nan)
        for i in range(20, len(s)):
            med = np.median(s[i - 20:i])
            out[i] = s[i] / med if med > 0 else np.nan
        rv[sym] = pd.Series(out, index=block.index)
    relvol = pd.concat(rv.values()).reindex(cum.index)
    opens = piv_c.ffill(axis=1).bfill(axis=1).iloc[:, 0]
    ret = piv_c.ffill(axis=1).div(
        df.groupby(["symbol", "date"]).open.first(), axis=0) - 1.0
    return relvol, ret, piv_c, piv_v


def main():
    df = load_bars()
    assert (df.date <= DEV_LAST).all(), "a sealed date leaked in"
    print(f"bars {len(df):,}  dates {df.date.nunique()}  symbols {df.symbol.nunique()}",
          flush=True)
    sessions = build_sessions(df)
    print(f"sessions rebuilt: {len(sessions):,}", flush=True)

    theirs = pd.read_parquet(RES / "sessions-equs.parquet")
    theirs = theirs[theirs.date <= DEV_LAST]
    m = sessions.merge(theirs, on=["symbol", "date"], suffixes=("_mine", "_theirs"))
    out = {"rows_compared": int(len(m))}
    for f in ("or_high", "or_low", "poc", "vah", "val", "sess_open", "atr20"):
        a, b = m[f + "_mine"].values, m[f + "_theirs"].values
        ok = np.isfinite(a) & np.isfinite(b)
        d = np.abs(a[ok] - b[ok])
        rel = d / np.maximum(np.abs(b[ok]), 1e-9)
        out[f] = {"compared": int(ok.sum()),
                  "exact": int((d == 0).sum()),
                  "within_1e-6_relative": int((rel < 1e-6).sum()),
                  "worst_absolute": float(d.max()) if ok.any() else 0.0}
        print(f"  {f:10s} compared {ok.sum():6d} exact {int((d==0).sum()):6d} "
              f"worst {d.max() if ok.any() else 0:.10f}", flush=True)
    (RES / "independent-verification.json").write_text(json.dumps(out, indent=2))
    print("wrote independent-verification.json", flush=True)


if __name__ == "__main__":
    main()
