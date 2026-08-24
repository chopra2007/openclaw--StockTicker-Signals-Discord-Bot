#!/usr/bin/env python3
"""Independent Phase-4 audit recompute for TODO #93 (opening-auction pressure response).

Reads ONLY the raw local DBN files plus the builder's output artifacts.
No network, no Databento client, no API key. Written from the frozen spec,
without reading the builder's code.

Internal clock comments are Eastern (exchange time). Owner-facing prose is Pacific.
"""
import json, sys, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import databento as db

ET = ZoneInfo("America/New_York")
RAW = "/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/"
GATE = "/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-pressure-response/"
IMB = RAW + "xnys-pillar_imbalance_60-symbols_2023-01-01_2026-08-22.dbn.zst"
BARS = RAW + "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst"
BARS_BRK = RAW + "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"
SEED = 20260824
DEV_MAX = "2025-11-28"          # dates after this are SEALED
NS = 1_000_000_000
MINUTES = [570, 574, 575, 579, 605, 609, 635, 639, 959]   # ET minutes-from-midnight
SNAPS = [("0915", 9*3600+15*60), ("0920", 9*3600+20*60), ("0925", 9*3600+25*60),
         ("0929_30", 9*3600+29*60+30), ("0930", 9*3600+30*60)]
TRAIL_BACK = 135                 # trading days of history to pull for trailing windows

def log(*a): print(*a, flush=True)

# ---------------------------------------------------------------- setup
panel = pd.read_parquet(GATE + "dev-panel.parquet")
events = pd.read_parquet(GATE + "internal-events.parquet")
assert panel["date"].max() <= DEV_MAX and events["date"].max() <= DEV_MAX

dates = sorted(panel["date"].unique())
didx = {d: i for i, d in enumerate(dates)}
# UTC-ns start of each Eastern calendar day, for date bucketing + time-of-day
day_start = np.array([int(dt.datetime(int(d[:4]), int(d[5:7]), int(d[8:]), 0, 0,
                                      tzinfo=ET).timestamp() * 1e9) for d in dates], dtype=np.int64)
day_end = day_start + np.int64(24*3600*int(1e9))

rng = np.random.default_rng(SEED)
sample = events.iloc[np.sort(rng.choice(len(events), 50, replace=False))].copy().reset_index(drop=True)
log("sampled 50 events;", sample["symbol"].nunique(), "distinct symbols,",
    sample["date"].min(), "->", sample["date"].max())

# symbol -> instrument id, resolved from each file's OWN mappings
def mappings(path):
    st = db.DBNStore.from_file(path)
    return {k: int(v[0]["symbol"]) for k, v in st.metadata.mappings.items() if v}
imb_map = mappings(IMB)
bar_map = mappings(BARS); bar_map.update(mappings(BARS_BRK))
def xnys_sym(s): return "BRK B" if s == "BRK.B" else s

syms = sorted(sample["symbol"].unique())
imb_ids = {s: imb_map[xnys_sym(s)] for s in syms}
bar_ids = {s: bar_map[s] for s in syms}
need_bars_brk = "BRK.B" in syms

# needed (instrument, date-index) pairs
def pack(i, d): return np.int64(i) * 100000 + np.int64(d)
imb_need, bar_need = set(), set()
for _, r in sample.iterrows():
    di = didx[r["date"]]
    lo = max(0, di - TRAIL_BACK)
    for d in range(lo, di + 1):
        imb_need.add(pack(imb_ids[r["symbol"]], d))
        bar_need.add(pack(bar_ids[r["symbol"]], d))
imb_need_a = np.array(sorted(imb_need), dtype=np.int64)
bar_need_a = np.array(sorted(bar_need), dtype=np.int64)
imb_inst_a = np.array(sorted({v for v in imb_ids.values()}), dtype=np.uint32)
bar_inst_a = np.array(sorted({v for v in bar_ids.values()}), dtype=np.uint32)
log(f"need {len(imb_need_a)} (instrument,date) imbalance pairs, {len(bar_need_a)} bar pairs")

def bucket(ts, inst, need, insts):
    """-> (keep_mask, date_index, seconds_into_the_Eastern_day)"""
    m = np.isin(inst, insts)
    idx = np.searchsorted(day_start, ts, side="right") - 1
    idx = np.clip(idx, 0, len(day_start) - 1)
    m &= (idx >= 0) & (ts >= day_start[idx]) & (ts < day_end[idx])
    key = pack(inst.astype(np.int64), idx.astype(np.int64))
    m &= np.isin(key, need)
    return m, idx, (ts - day_start[idx])          # nanoseconds into the Eastern day

# ---------------------------------------------------------------- imbalance pass
log("scanning imbalance file ...")
cols = {k: [] for k in ("inst", "di", "tod", "ts", "pq", "tiq", "at", "side")}
n = 0
for chunk in db.DBNStore.from_file(IMB).to_ndarray(count=1_000_000):
    n += len(chunk)
    ts = chunk["ts_recv"].astype(np.int64)
    m, idx, tod = bucket(ts, chunk["instrument_id"], imb_need_a, imb_inst_a)
    at = chunk["auction_type"]
    # opening window 09:14:00-09:30:00 ET, closing window from 15:45 ET
    m &= (((at == b"M") & (tod >= NS*(8*3600+30*60)) & (tod <= NS*(9*3600+30*60))) |
          ((at == b"C") & (tod >= NS*(15*3600+45*60))))
    if not m.any():
        continue
    c = chunk[m]
    cols["inst"].append(c["instrument_id"]); cols["di"].append(idx[m]); cols["tod"].append(tod[m])
    cols["ts"].append(ts[m]); cols["pq"].append(c["paired_qty"]); cols["tiq"].append(c["total_imbalance_qty"])
    cols["at"].append(c["auction_type"]); cols["side"].append(c["side"])
imbdf = pd.DataFrame({k: np.concatenate(v) for k, v in cols.items()})
log(f"  scanned {n} imbalance records, kept {len(imbdf)}")

# ---------------------------------------------------------------- bars pass
log("scanning bar files ...")
bcols = {k: [] for k in ("inst", "di", "minute", "open", "close", "volume")}
mins = np.array(MINUTES)
for path in ([BARS] + ([BARS_BRK] if need_bars_brk else [])):
    n = 0
    for chunk in db.DBNStore.from_file(path).to_ndarray(count=1_000_000):
        n += len(chunk)
        ts = chunk["ts_event"].astype(np.int64)     # bars stamped at bar START
        m, idx, tod = bucket(ts, chunk["instrument_id"], bar_need_a, bar_inst_a)
        minute = tod // (60*NS)
        m &= np.isin(minute, mins)
        if not m.any():
            continue
        c = chunk[m]
        bcols["inst"].append(c["instrument_id"]); bcols["di"].append(idx[m]); bcols["minute"].append(minute[m])
        bcols["open"].append(c["open"].astype(np.float64) * 1e-9)
        bcols["close"].append(c["close"].astype(np.float64) * 1e-9)
        bcols["volume"].append(c["volume"].astype(np.float64))
    log(f"  {path.split('/')[-1]}: scanned {n}")
bardf = pd.DataFrame({k: np.concatenate(v) for k, v in bcols.items()})
log(f"  kept {len(bardf)} bars")

# ---------------------------------------------------------------- lookups
imbdf["key"] = pack(imbdf["inst"].astype(np.int64), imbdf["di"].astype(np.int64))
bardf["key"] = pack(bardf["inst"].astype(np.int64), bardf["di"].astype(np.int64))
bar_lu = {(int(k), int(mi)): (o, c, v) for k, mi, o, c, v in
          zip(bardf["key"], bardf["minute"], bardf["open"], bardf["close"], bardf["volume"])}
imb_by_key = {k: g for k, g in imbdf.groupby("key", sort=False)}

def snap(inst, di, cutoff_sec):
    """latest opening ('M') message with ts_recv at or before the cutoff"""
    g = imb_by_key.get(int(pack(inst, di)))
    if g is None: return None
    g = g[(g["at"] == b"M") & (g["tod"] <= NS*cutoff_sec)]
    if len(g) == 0: return None
    r = g.loc[g["ts"].idxmax()]
    if r["pq"] == 0: return dict(p=np.nan, ts=int(r["ts"]), pq=float(r["pq"]))
    s = 1.0 if r["side"] == b"B" else (-1.0 if r["side"] == b"A" else np.nan)
    return dict(p=s * float(r["tiq"]) / float(r["pq"]), ts=int(r["ts"]), pq=float(r["pq"]))

def closing_pressure(inst, di):
    g = imb_by_key.get(int(pack(inst, di)))
    if g is None: return np.nan
    g = g[g["at"] == b"C"]
    if len(g) == 0: return np.nan
    r = g.loc[g["ts"].idxmax()]
    if r["pq"] == 0: return np.nan
    s = 1.0 if r["side"] == b"B" else (-1.0 if r["side"] == b"A" else np.nan)
    return s * float(r["tiq"]) / float(r["pq"])

def bar(inst, di, minute, field):
    v = bar_lu.get((int(pack(inst, di)), int(minute)))
    if v is None: return np.nan
    return {"open": v[0], "close": v[1], "volume": v[2]}[field]

# ---------------------------------------------------------------- recompute
rows = []
for _, r in sample.iterrows():
    sym, d = r["symbol"], r["date"]
    di, ii, bi = didx[d], imb_ids[sym], bar_ids[sym]
    pdi = didx[r["prior_session_date"]]
    rec = {"date": d, "symbol": sym, "rule_ids": r["rule_ids"], "lane": r["lane"]}
    rec["b_xnys_inst"] = r["xnys_inst"]; rec["m_xnys_inst"] = ii
    ps = {}
    for name, cut in SNAPS:
        s = snap(ii, di, cut)
        ps[name] = np.nan if s is None else s["p"]
        rec[f"m_p_{name}"] = ps[name]
        rec[f"b_p_{name}"] = r[f"p_{name}"]
        rec[f"m_ts_{name}"] = np.nan if s is None else s["ts"]
        rec[f"b_ts_{name}"] = r[f"ts_{name}"]
        rec[f"m_pq_{name}"] = np.nan if s is None else s["pq"]
        rec[f"b_pq_{name}"] = r[f"pq_{name}"]
    rec["m_prior_closing_pressure"] = closing_pressure(ii, pdi)
    rec["b_prior_closing_pressure"] = r["prior_closing_pressure"]
    op = bar(bi, di, 570, "open"); pc = bar(bi, pdi, 959, "close")
    rec["m_opening_price"] = op; rec["b_opening_price"] = r["opening_price"]
    rec["m_prior_close"] = pc;  rec["b_prior_close"] = r["prior_close"]
    rec["m_opening_gap"] = (op - pc) / pc
    rec["b_opening_gap"] = r["opening_gap"]
    c574 = bar(bi, di, 574, "close")
    rec["m_first_five_return"] = (c574 - op) / op
    rec["b_first_five_return"] = r["first_five_return"]
    lane = r["lane"]
    em, xm = (579, 639) if lane == "a" else (575, 635)
    ep = bar(bi, di, em, "close"); ev = bar(bi, di, em, "volume"); xp = bar(bi, di, xm, "close")
    rec["m_entry_price"] = ep; rec["b_entry_price"] = r["entry_a"] if lane == "a" else r["entry_b"]
    rec["m_entry_volume"] = ev; rec["b_entry_volume"] = r["entry_vol_a"] if lane == "a" else r["entry_vol_b"]
    rec["m_exit_price"] = xp;  rec["b_exit_price"] = r["exit_a"] if lane == "a" else r["exit_b"]
    rec["m_raw_return"] = xp / ep - 1
    rec["b_raw_return"] = r["ret_a"] if lane == "a" else r["ret_b"]

    # trailing thresholds from my own raw values over the last 60 VALID sessions before d
    hist_p, hist_pq, hist_gap, hist_cp = [], [], [], []
    for k in range(di - 1, max(-1, di - TRAIL_BACK) - 1, -1):
        if len(hist_p) >= 60 and len(hist_gap) >= 60 and len(hist_cp) >= 60: break
        s930 = snap(ii, k, 9*3600+30*60)
        if s930 is not None and np.isfinite(s930["p"]):
            if len(hist_p) < 60: hist_p.append(abs(s930["p"])); hist_pq.append(s930["pq"])
        o = bar(bi, k, 570, "open"); c = bar(bi, k - 1, 959, "close") if k >= 1 else np.nan
        if np.isfinite(o) and np.isfinite(c) and len(hist_gap) < 60: hist_gap.append(abs((o - c) / c))
        cp = closing_pressure(ii, k - 1) if k >= 1 else np.nan
        if np.isfinite(cp) and len(hist_cp) < 60: hist_cp.append(abs(cp))
    def pct(x, q, mn=20):
        return np.percentile(x, q) if len(x) >= mn else np.nan
    thr_p = pct(hist_p, 90); thr_g = pct(hist_gap, 75); thr_c = pct(hist_cp, 90)
    med_pq = np.median(hist_pq) if len(hist_pq) >= 20 else np.nan
    rec["m_pressure_pctl"] = thr_p; rec["b_pressure_pctl"] = r["pressure_pctl"]
    rec["m_gap_pctl"] = thr_g; rec["b_gap_pctl"] = r["gap_pctl"]
    rec["m_closing_pressure_pctl"] = thr_c; rec["b_closing_pressure_pctl"] = r["closing_pressure_pctl"]
    rec["m_paired_median"] = med_pq; rec["b_paired_median"] = r["paired_median"]

    # rule replay from my own numbers
    p930 = ps["0930"]; s930 = np.sign(p930)
    pre = [ps[n] for n, _ in SNAPS[:-1]]
    allp = [ps[n] for n, _ in SNAPS]
    maxpre = max(pre, key=lambda x: abs(x)) if all(np.isfinite(pre)) else np.nan
    persistence = np.mean([np.sign(x) == s930 for x in allp]) if all(np.isfinite(allp)) else np.nan
    persistent = bool(persistence >= 0.80 and np.sign(ps["0929_30"]) == s930 and np.sign(ps["0930"]) == s930)
    canc = (abs(maxpre) - abs(p930)) / abs(maxpre) if np.isfinite(maxpre) and maxpre != 0 else np.nan
    eps = np.sign(maxpre)
    late_flip = bool(s930 != eps)
    gap = rec["m_opening_gap"]; f5 = rec["m_first_five_return"]
    pe = abs(p930) >= thr_p; mpe = abs(maxpre) >= thr_p
    cpe = abs(rec["m_prior_closing_pressure"]) >= thr_c
    lg = abs(gap) >= thr_g
    same = np.sign(rec["m_prior_closing_pressure"]) == s930
    cal = r["calendar_group"]
    fired = {}
    if pe and persistent and s930*gap <= 0 and s930*f5 <= 0: fired["A1"] = -s930
    if mpe and (canc >= 0.50 or late_flip) and eps*gap > 0 and -eps*f5 > 0: fired["A2"] = -eps
    if pe and persistent and s930*gap > 0 and s930*f5 > 0: fired["A3"] = s930
    if cpe and pe and same and s930*gap > 0: fired["B1"] = s930
    if cpe and pe and (not same) and s930*gap > 0: fired["B2"] = s930
    if cal in ("month_end", "quarter_end") and pe and lg and s930*gap > 0: fired["B3"] = -s930
    lane_allowed = {k: v for k, v in fired.items()
                    if (k[0] == "A" and r["lane_a_eligible"]) or (k[0] == "B" and r["lane_b_eligible"])}
    rec["m_rule_ids"] = ",".join(sorted(lane_allowed))
    dv = set(lane_allowed.values())
    rec["m_direction"] = list(dv)[0] if len(dv) == 1 else np.nan
    rec["b_direction"] = r["direction"]
    rec["m_persistence"] = persistence; rec["b_persistence"] = r["persistence"]
    rec["m_cancellation"] = canc; rec["b_cancellation"] = r["cancellation"]
    rows.append(rec)

out = pd.DataFrame(rows)

# ---------------------------------------------------------------- comparison
def cmp_num(name, tol):
    m = out["m_" + name].astype(float); b = out["b_" + name].astype(float)
    diff = (m - b).abs()
    both_nan = m.isna() & b.isna()
    out["diff_" + name] = diff
    out["match_" + name] = (diff <= tol) | both_nan
FIELDS = ([(f"p_{n}", 1e-9) for n, _ in SNAPS] + [(f"ts_{n}", 0) for n, _ in SNAPS] +
          [(f"pq_{n}", 0) for n, _ in SNAPS] +
          [("prior_closing_pressure", 1e-9), ("opening_price", 1e-9), ("prior_close", 1e-9),
           ("opening_gap", 1e-9), ("first_five_return", 1e-9), ("entry_price", 1e-9),
           ("entry_volume", 0), ("exit_price", 1e-9), ("raw_return", 1e-9),
           ("pressure_pctl", 1e-6), ("gap_pctl", 1e-6), ("closing_pressure_pctl", 1e-6),
           ("paired_median", 1e-6), ("persistence", 1e-9), ("cancellation", 1e-9),
           ("direction", 0), ("xnys_inst", 0)])
for f, t in FIELDS: cmp_num(f, t)
out["match_rule_ids"] = out["m_rule_ids"] == out["rule_ids"]

out.to_csv(GATE + "audit-event-checks.csv", index=False)
log("\nwrote audit-event-checks.csv")
summary = {}
for f, _ in FIELDS + [("rule_ids", 0)]:
    c = int((~out["match_" + f]).sum())
    summary[f] = c
    if c: log(f"  MISMATCH {f}: {c}/50")
log("fields with zero mismatches:", sum(1 for v in summary.values() if v == 0), "of", len(summary))
json.dump(summary, open(GATE + "audit-field-mismatch-counts.json", "w"), indent=1)
