#!/usr/bin/env python3
"""TODO #103 - independent verification, written to NOT import the builder.

This script deliberately imports nothing from intraday_dislocation_engine,
intraday_dislocation_panel or intraday_dislocation_gates. It reads the raw DBN
records itself, rebuilds predictors and complete minute-by-minute trade paths
with its own code, and compares against the builder's saved trades.

Usage:
  intraday_dislocation_verify.py --trades <parquet> --policy <json> --n 100
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import databento as db

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
SCALE = 1e-9
DATA = Path("/home/openclaw/.openclaw/research-data/databento/opening-auctions/"
            "selected60_2023-01_to_2026-08")
FILES = [DATA / "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst",
         DATA / "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"]


def et_minute_and_date(ts_ns, cache={}):
    day = ts_ns // 86_400_000_000_000
    off = cache.get(day)
    if off is None:
        off = int(datetime.fromtimestamp(ts_ns / 1e9, tz=UTC)
                  .astimezone(ET).utcoffset().total_seconds()) * 1_000_000_000
        cache[day] = off
    loc = ts_ns + off
    d = loc // 86_400_000_000_000
    return (datetime.utcfromtimestamp(d * 86_400).strftime("%Y-%m-%d"),
            int((loc % 86_400_000_000_000) / 1e9) // 60)


def load_raw(wanted_keys, lo_min, hi_min):
    """Read the raw DBN files and keep only the symbol-dates asked for."""
    out = defaultdict(dict)
    for path in FILES:
        store = db.DBNStore.from_file(str(path))
        inst2sym = {}
        for sym, ivs in store.metadata.mappings.items():
            for iv in ivs:
                inst2sym[int(iv["symbol"])] = sym.replace(" ", ".").upper()
        for rec in store:
            d, m = et_minute_and_date(rec.ts_event)
            if m < lo_min or m > hi_min:
                continue
            s = inst2sym.get(rec.instrument_id)
            if s is None:
                continue
            k = (d, s)
            if k not in wanted_keys:
                continue
            out[k][m] = (rec.open * SCALE, rec.high * SCALE, rec.low * SCALE,
                         rec.close * SCALE, rec.volume)
    return out


def replay(day, side, entry_minute, stop_px, target_px, hold, search):
    """A second, independently written implementation of the frozen fill rules."""
    for m in range(entry_minute + 1, entry_minute + hold):
        if m not in day:
            continue
        o, h, lo, c, v = day[m]
        if v <= 0:
            continue
        if side > 0:
            if o <= stop_px:
                return o, m, "stop_gap"
            if o >= target_px:
                return o, m, "target_gap"
            if lo <= stop_px:
                return stop_px, m, "stop"
            if h >= target_px:
                return target_px, m, "target"
        else:
            if o >= stop_px:
                return o, m, "stop_gap"
            if o <= target_px:
                return o, m, "target_gap"
            if h >= stop_px:
                return stop_px, m, "stop"
            if lo <= target_px:
                return target_px, m, "target"
    for m in range(entry_minute + hold, entry_minute + hold + search + 1):
        if m in day and day[m][4] > 0:
            return day[m][0], m, "time"
    return None


def verify_predictors(panel_path, policy, n, seed):
    """Rebuild P0, P1, the window move, the window high/low and the window dollar
    volume for n randomly chosen SIGNAL candidates, straight from raw DBN."""
    p = pd.read_parquet(panel_path)
    el = p[p.eligible]
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(el), size=min(n, len(el)), replace=False)
    s = el.iloc[idx]
    keys = set(zip(s.date, s.symbol))
    raw = load_raw(keys, policy["window_lo"], policy["window_hi"])

    out = []
    for r in s.itertuples():
        day = raw.get((r.date, r.symbol), {})
        closes = {m: day[m][3] for m in day}
        try:
            p0 = float(np.median([closes[m] for m in policy["anchor_start"]]))
            p1 = float(np.median([closes[m] for m in policy["anchor_end"]]))
        except KeyError:
            out.append({"date": r.date, "symbol": r.symbol, "ok": False,
                        "note": "verifier could not find the anchor bars"})
            continue
        hi = max(v[1] for v in day.values())
        lo = min(v[2] for v in day.values())
        dol = sum(v[3] * v[4] for v in day.values())
        rr = float(np.log(p1 / p0))
        out.append({
            "date": r.date, "symbol": r.symbol,
            "p0_matches": bool(abs(p0 - r.p0) < 1e-9),
            "p1_matches": bool(abs(p1 - r.p1) < 1e-9),
            "r_matches": bool(abs(rr - r.r) < 1e-9),
            "high_matches": bool(abs(hi - r.win_high) < 1e-9),
            "low_matches": bool(abs(lo - r.win_low) < 1e-9),
            "dollar_volume_matches": bool(abs(dol - r.win_dollar_volume) < 1.0),
            "bars_matches": bool(len(day) == r.bars),
            "ok": True,
        })
    df = pd.DataFrame(out)
    cols = [c for c in df.columns if c.endswith("_matches")]
    return {
        "checked": int(len(df)),
        "all_fields_match": int(df[cols].all(axis=1).sum()) if cols else 0,
        "per_field": {c: int(df[c].sum()) for c in cols},
        "failures": df[~df[cols].all(axis=1)].to_dict("records") if cols else [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=99991)
    ap.add_argument("--out", required=True)
    ap.add_argument("--panel", default=None)
    ap.add_argument("--n-predictors", type=int, default=100)
    a = ap.parse_args()

    policy = json.loads(Path(a.policy).read_text())
    t = pd.read_parquet(a.trades)
    t = t[~t.unresolvable.fillna(False)]
    rng = np.random.default_rng(a.seed)
    idx = rng.choice(len(t), size=min(a.n, len(t)), replace=False)
    sample = t.iloc[idx].copy()

    keys = set(zip(sample.date, sample.symbol))
    hi = int(sample.entry_minute.max()) + policy["hold_minutes"] + 20
    raw = load_raw(keys, 570, hi)

    rows = []
    for r in sample.itertuples():
        day = raw.get((r.date, r.symbol), {})
        ebar = day.get(int(r.entry_minute))
        entry_ok = ebar is not None and abs(ebar[0] - r.entry_px) < 1e-6
        res = replay(day, int(r.side), int(r.entry_minute), float(r.stop_px),
                     float(r.target_px), policy["hold_minutes"],
                     policy["time_exit_search_minutes"])
        if res is None:
            rows.append({"rule": r.rule, "date": r.date, "symbol": r.symbol,
                         "entry_matches": entry_ok, "exit_matches": False,
                         "note": "verifier found no exit"})
            continue
        px, m, kind = res
        gross = int(r.side) * (px / float(r.entry_px) - 1.0) * 1e4
        rows.append({
            "rule": r.rule, "date": r.date, "symbol": r.symbol,
            "entry_matches": bool(entry_ok),
            "exit_price_matches": bool(abs(px - r.exit_px) < 1e-6),
            "exit_minute_matches": bool(m == r.exit_minute),
            "exit_kind_matches": bool(kind == r.exit_kind),
            "gross_bps_builder": float(r.gross_bps),
            "gross_bps_verifier": float(gross),
            "gross_matches": bool(abs(gross - float(r.gross_bps)) < 0.01),
        })
    df = pd.DataFrame(rows)
    summary = {
        "predictors": (verify_predictors(a.panel, policy, a.n_predictors, a.seed)
                       if a.panel else {"skipped": True}),
        "checked": int(len(df)),
        "entry_matches": int(df.entry_matches.sum()),
        "exit_price_matches": int(df.get("exit_price_matches", pd.Series(dtype=bool)).sum()),
        "exit_minute_matches": int(df.get("exit_minute_matches", pd.Series(dtype=bool)).sum()),
        "exit_kind_matches": int(df.get("exit_kind_matches", pd.Series(dtype=bool)).sum()),
        "gross_matches": int(df.get("gross_matches", pd.Series(dtype=bool)).sum()),
        "mismatches": df[~df.get("gross_matches", pd.Series([True] * len(df)))
                         .fillna(False)].to_dict("records"),
    }
    Path(a.out).write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "mismatches"}, indent=2))
    print("mismatches:", len(summary["mismatches"]))


if __name__ == "__main__":
    main()
