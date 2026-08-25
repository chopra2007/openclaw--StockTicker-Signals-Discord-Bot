#!/usr/bin/env python3
"""Independent reproduction of the put-flow morning shortlist research.
Written from scratch by an independent verifier. Does NOT import the
builder's scripts.
"""
import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

WS = Path("/home/openclaw/.openclaw/workspace")
DB = WS / "consensus.db"
BARS_DIR = WS / "data" / "put_flow_bars"
RESEARCH_DIR = WS / ".omc" / "research" / "extreme-put-flow-morning-shortlist"

ETF_TICKERS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "SOXX", "SMH", "TQQQ", "SQQQ", "SOXL", "SOXS",
    "GLD", "SLV", "TLT", "USO", "ARKK", "VOO", "RSP", "IGV", "XLE", "XLF",
    "XLK", "XLV", "VGT", "SCHD", "KORU", "EWY",
})

# ---------- Step 1: pull rows from DB ----------

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT o.*, f.vol_oi_ratio, f.volume, f.premium_usd
    FROM options_flow_outcomes o
    JOIN options_flow f ON f.id = o.flow_id
""").fetchall()
rows = [dict(r) for r in rows]
print(f"raw joined rows: {len(rows)}")

usable = []
for r in rows:
    c0, c5, b0, b5 = r["close_0d"], r["close_5d"], r["bench_close_0d"], r["bench_close_5d"]
    if c0 is None or c5 is None or b0 is None or b5 is None:
        continue
    if c0 <= 0 or c5 <= 0 or b0 <= 0 or b5 <= 0:
        continue
    adj5 = (c5 / c0 - 1) - (b5 / b0 - 1)
    r["adj_5d"] = adj5
    usable.append(r)

single_stock = [r for r in usable if r["ticker"] not in ETF_TICKERS]
print(f"usable rows (non-ETF): {len(single_stock)}")

# cluster to one row per (ticker, market_date, side), highest vol_oi_ratio
best = {}
for r in single_stock:
    k = (r["ticker"], r["market_date"], r["side"].upper())
    voi = r.get("vol_oi_ratio") or 0
    if k not in best or voi > (best[k].get("vol_oi_ratio") or 0):
        best[k] = r
events = list(best.values())
print(f"clustered single-stock events: {len(events)} (expect 2680)")

put_extreme = [e for e in events if e["side"].upper() == "PUT" and (e.get("vol_oi_ratio") or 0) >= 50]
n_put = len(put_extreme)
pos = sum(1 for e in put_extreme if e["adj_5d"] > 0)
pct_pos = 100.0 * pos / n_put if n_put else 0.0
print(f"PUT + vol_oi>=50 events: {n_put} (expect 349), pct positive adj-5d: {pct_pos:.1f}% (expect 33.5%)")

step1 = {
    "clustered_events": len(events),
    "put_extreme_n": n_put,
    "put_extreme_pct_positive": pct_pos,
}

# ---------- Step 2: frozen candidate list ----------

cand_pool = [
    e for e in events
    if e["side"].upper() == "PUT"
    and (e.get("vol_oi_ratio") or 0) >= 50
    and (e.get("volume") or 0) >= 500
    and (e.get("premium_usd") or 0) >= 250000
]
print(f"candidate pool (pre-day-cap): {len(cand_pool)}")

# one event per (ticker, market_date): highest vol_oi_ratio, tie-break asc ticker/contract_symbol/flow_id
by_ticker_date = {}
for e in cand_pool:
    k = (e["ticker"], e["market_date"])
    if k not in by_ticker_date:
        by_ticker_date[k] = e
    else:
        cur = by_ticker_date[k]
        cur_key = (-(cur.get("vol_oi_ratio") or 0), cur["ticker"], cur.get("contract_symbol") or "", cur["flow_id"])
        new_key = (-(e.get("vol_oi_ratio") or 0), e["ticker"], e.get("contract_symbol") or "", e["flow_id"])
        if new_key < cur_key:
            by_ticker_date[k] = e

per_date = defaultdict(list)
for e in by_ticker_date.values():
    per_date[e["market_date"]].append(e)

candidates = []
for md, lst in per_date.items():
    lst.sort(key=lambda e: (-(e.get("vol_oi_ratio") or 0), e["ticker"], e.get("contract_symbol") or "", e["flow_id"]))
    kept = lst[:4]
    for rank, e in enumerate(kept, start=1):
        e2 = dict(e)
        e2["rank"] = rank
        candidates.append(e2)

candidates.sort(key=lambda e: (e["market_date"], e["rank"]))
n_signal_dates = len(set(e["market_date"] for e in candidates))
n_stocks = len(set(e["ticker"] for e in candidates))
print(f"candidates: {len(candidates)} (expect 188), signal dates: {n_signal_dates} (expect 53), distinct stocks: {n_stocks} (expect 88)")

step2 = {
    "candidates_n": len(candidates),
    "signal_dates": n_signal_dates,
    "distinct_stocks": n_stocks,
}

# compare row-for-row against frozen-candidates.csv
import csv
frozen_rows = []
with open(RESEARCH_DIR / "frozen-candidates.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        frozen_rows.append(row)

my_by_key = {}
for e in candidates:
    key = (e["market_date"], e["rank"])
    my_by_key[key] = e

diffs = []
if len(frozen_rows) != len(candidates):
    diffs.append(f"row count differs: mine={len(candidates)} frozen={len(frozen_rows)}")

for frow in frozen_rows:
    key = (frow["market_date"], int(frow["rank"]))
    mine = my_by_key.get(key)
    if mine is None:
        diffs.append(f"missing in mine: {key}")
        continue
    if mine["ticker"] != frow["ticker"] or (mine.get("contract_symbol") or "") != frow["contract_symbol"] or str(mine["flow_id"]) != frow["flow_id"]:
        diffs.append(f"mismatch at {key}: mine=({mine['ticker']},{mine.get('contract_symbol')},{mine['flow_id']}) frozen=({frow['ticker']},{frow['contract_symbol']},{frow['flow_id']})")

my_keys = set(my_by_key.keys())
frozen_keys = set((r["market_date"], int(r["rank"])) for r in frozen_rows)
extra = my_keys - frozen_keys
if extra:
    diffs.append(f"extra rows in mine not in frozen: {sorted(extra)[:10]}")

print(f"candidate list diffs vs frozen-candidates.csv: {len(diffs)}")
for d in diffs[:20]:
    print("  DIFF:", d)

# ---------- Step 3: exact entry pricing ----------

def load_bars(ticker):
    p5 = BARS_DIR / f"{ticker}.bars5m.json"
    pd = BARS_DIR / f"{ticker}.daily.json"
    bars5 = json.load(open(p5)) if p5.exists() else None
    daily = json.load(open(pd)) if pd.exists() else None
    return bars5, daily

spy_bars5, spy_daily = load_bars("SPY")

calendar = sorted(d for d, bars in spy_bars5.items() if any(t >= "09:35" for t in bars.keys()))
print(f"trading calendar length: {len(calendar)}")

def price_at_935(bars_for_day):
    times = sorted(t for t in bars_for_day.keys() if t >= "09:35")
    if not times:
        return None
    return bars_for_day[times[0]]

def next_n_sessions(date, n):
    idx = calendar.index(date)
    j = idx + n
    if j >= len(calendar):
        return None
    return calendar[j]

def entry_date_for(market_date):
    for d in calendar:
        if d > market_date:
            return d
    return None

# hard-to-borrow screen + pricing
bars_cache = {}

def get_bars(ticker):
    if ticker not in bars_cache:
        bars_cache[ticker] = load_bars(ticker)
    return bars_cache[ticker]

dropped_htb = []
priced = []
unpriceable = []

for c in candidates:
    ticker = c["ticker"]
    md = c["market_date"]
    bars5, daily = get_bars(ticker)
    if daily is None or bars5 is None:
        unpriceable.append((c, "no data files"))
        continue

    # HTB screen using only dates <= market_date
    dates_le = sorted(d for d in daily.keys() if d <= md)
    if not dates_le:
        unpriceable.append((c, "no daily history <= market_date"))
        continue
    latest_close = daily[dates_le[-1]][0]
    if latest_close < 5.0:
        dropped_htb.append((c, "price_under_5", latest_close))
        continue
    last20 = dates_le[-20:]
    dollar_vols = [daily[d][0] * daily[d][1] for d in last20]
    med_dv = statistics.median(dollar_vols)
    if med_dv < 50_000_000:
        dropped_htb.append((c, "thin_dollar_volume", med_dv))
        continue

    entry_date = entry_date_for(md)
    if entry_date is None:
        unpriceable.append((c, "no entry date"))
        continue
    exit_date = next_n_sessions(entry_date, 4)
    if exit_date is None:
        unpriceable.append((c, "no exit date"))
        continue

    if entry_date not in bars5 or exit_date not in bars5 or entry_date not in spy_bars5 or exit_date not in spy_bars5:
        unpriceable.append((c, "missing bar day"))
        continue

    stock_entry = price_at_935(bars5[entry_date])
    stock_exit = price_at_935(bars5[exit_date])
    spy_entry = price_at_935(spy_bars5[entry_date])
    spy_exit = price_at_935(spy_bars5[exit_date])

    if None in (stock_entry, stock_exit, spy_entry, spy_exit):
        unpriceable.append((c, "missing 09:35+ bar"))
        continue

    stock_ret = stock_exit / stock_entry - 1
    spy_ret = spy_exit / spy_entry - 1
    pair_net = spy_ret - stock_ret - 0.0025
    short_only_net = -stock_ret - 0.0025

    priced.append({
        **c,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "stock_entry_px": stock_entry,
        "stock_exit_px": stock_exit,
        "spy_entry_px": spy_entry,
        "spy_exit_px": spy_exit,
        "stock_ret": stock_ret,
        "spy_ret": spy_ret,
        "pair_net": pair_net,
        "short_only_net": short_only_net,
    })

print(f"dropped by HTB screen: {len(dropped_htb)} (expect 7)")
reason_counts = defaultdict(int)
for c, reason, val in dropped_htb:
    reason_counts[reason] += 1
print(f"  reasons: {dict(reason_counts)}")
print(f"priced trades: {len(priced)} (expect 181)")
print(f"unpriceable: {len(unpriceable)} (expect 0)")
for c, reason in unpriceable:
    print("  UNPRICEABLE:", c["ticker"], c["market_date"], reason)

step3_screen = {
    "dropped_htb": len(dropped_htb),
    "dropped_reasons": dict(reason_counts),
    "priced": len(priced),
    "unpriceable": len(unpriceable),
}

# ---------- stats helpers ----------

def wilson_lower(wins, n, z=1.959963984540054):
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (center - margin) / denom

def profit_factor(vals):
    pos = sum(v for v in vals if v > 0)
    neg = sum(v for v in vals if v < 0)
    if neg == 0:
        return float("inf")
    return pos / abs(neg)

def top_stock_share(trades, key):
    # gross profit share of the single stock with the largest total positive profit
    by_ticker = defaultdict(float)
    for t in trades:
        v = t[key]
        if v > 0:
            by_ticker[t["ticker"]] += v
    total_pos = sum(v for v in (t[key] for t in trades) if v > 0)
    if not by_ticker or total_pos == 0:
        return 0.0, None
    top_ticker = max(by_ticker, key=by_ticker.get)
    return 100.0 * by_ticker[top_ticker] / total_pos, top_ticker

def bootstrap_ci(trades, key, seed, n_boot=10000):
    rng = random.Random(seed)
    dates = sorted(set(t["market_date"] for t in trades))
    by_date = defaultdict(list)
    for t in trades:
        by_date[t["market_date"]].append(t[key])
    means = []
    for _ in range(n_boot):
        sample_dates = [rng.choice(dates) for _ in dates]
        vals = []
        for d in sample_dates:
            vals.extend(by_date[d])
        if vals:
            means.append(statistics.mean(vals))
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means))]
    return lo, hi

def summarize(trades, key, seed):
    vals = [t[key] for t in trades]
    n = len(vals)
    dates = sorted(set(t["market_date"] for t in trades))
    stocks = set(t["ticker"] for t in trades)
    avg = statistics.mean(vals) * 100
    med = statistics.median(vals) * 100
    wins = sum(1 for v in vals if v > 0)
    win_rate = 100.0 * wins / n
    wl = 100.0 * wilson_lower(wins, n)
    pf = profit_factor(vals)
    top_share, top_ticker = top_stock_share(trades, key)

    mid = len(dates) // 2
    early_dates = set(dates[:mid]) if len(dates) % 2 == 0 else set(dates[:mid + 1])
    late_dates = set(dates) - early_dates
    # actually need explicit half split matching len//2 boundary; recompute cleanly
    half = len(dates) // 2
    # builder split: first half vs second half by date, so let's just do straightforward split index
    early_dates = set(dates[:len(dates) - (len(dates) // 2 if len(dates) % 2 == 0 else len(dates)//2)]) if False else None

    return {
        "n": n, "dates": len(dates), "stocks": len(stocks),
        "avg_pct": avg, "median_pct": med, "win_rate_pct": win_rate, "wins": wins,
        "wilson_lower_pct": wl, "profit_factor": pf,
        "top_stock_share_pct": top_share, "top_stock": top_ticker,
    }

def half_split(trades, key):
    dates = sorted(set(t["market_date"] for t in trades))
    n = len(dates)
    half = n // 2
    early_set = set(dates[:half])
    late_set = set(dates[half:])
    early_trades = [t for t in trades if t["market_date"] in early_set]
    late_trades = [t for t in trades if t["market_date"] in late_set]

    def stat(ts):
        vals = [t[key] for t in ts]
        return {
            "trades": len(ts),
            "avg_pct": statistics.mean(vals) * 100 if vals else None,
            "win_rate_pct": 100.0 * sum(1 for v in vals if v > 0) / len(vals) if vals else None,
            "dates": len(set(t["market_date"] for t in ts)),
        }
    return {"early": stat(early_trades), "late": stat(late_trades)}

SEED = 20260824
pair_summary = summarize(priced, "pair_net", SEED)
short_summary = summarize(priced, "short_only_net", SEED)
pair_halves = half_split(priced, "pair_net")
short_halves = half_split(priced, "short_only_net")
pair_boot_lo, pair_boot_hi = bootstrap_ci(priced, "pair_net", SEED)
short_boot_lo, short_boot_hi = bootstrap_ci(priced, "short_only_net", SEED)

print("\n=== PAIR NET ===")
print(pair_summary)
print("halves:", pair_halves)
print(f"bootstrap 95% (seed={SEED}): [{pair_boot_lo*100:.3f}%, {pair_boot_hi*100:.3f}%]  low>0: {pair_boot_lo>0}")

print("\n=== SHORT ONLY NET ===")
print(short_summary)
print("halves:", short_halves)
print(f"bootstrap 95% (seed={SEED}): [{short_boot_lo*100:.3f}%, {short_boot_hi*100:.3f}%]  low>0: {short_boot_lo>0}")

# ---------- Step 4: compare to builder's json ----------

with open(RESEARCH_DIR / "exact-entry-results.json") as f:
    builder = json.load(f)

comparisons = []
def cmp(label, mine, theirs, tol=0.05):
    if theirs is None:
        return
    diff = mine - theirs
    ok = abs(diff) <= tol
    comparisons.append((label, mine, theirs, diff, ok))

bp = builder["pair_trade"]
cmp("pair.trades", pair_summary["n"], bp["trades"], tol=0)
cmp("pair.signal_dates", pair_summary["dates"], bp["signal_dates"], tol=0)
cmp("pair.distinct_stocks", pair_summary["stocks"], bp["distinct_stocks"], tol=0)
cmp("pair.avg_pct", pair_summary["avg_pct"], bp["avg_pct"])
cmp("pair.median_pct", pair_summary["median_pct"], bp["median_pct"])
cmp("pair.win_rate_pct", pair_summary["win_rate_pct"], bp["win_rate_pct"])
cmp("pair.wins", pair_summary["wins"], bp["wins"], tol=0)
cmp("pair.wilson_lower_pct", pair_summary["wilson_lower_pct"], bp["win_rate_lower_95_pct"])
cmp("pair.profit_factor", pair_summary["profit_factor"], bp["profit_factor"])
cmp("pair.top_stock_share_pct", pair_summary["top_stock_share_pct"], bp["top_stock_profit_share_pct"])
cmp("pair.early.avg_pct", pair_halves["early"]["avg_pct"], bp["halves"]["early"]["avg_pct"])
cmp("pair.late.avg_pct", pair_halves["late"]["avg_pct"], bp["halves"]["late"]["avg_pct"])

bu = builder["unhedged_short"]
cmp("short.avg_pct", short_summary["avg_pct"], bu["avg_pct"])
cmp("short.win_rate_pct", short_summary["win_rate_pct"], bu["win_rate_pct"])
cmp("short.wilson_lower_pct", short_summary["wilson_lower_pct"], bu["win_rate_lower_95_pct"])
cmp("short.profit_factor", short_summary["profit_factor"], bu["profit_factor"])
cmp("short.top_stock_share_pct", short_summary["top_stock_share_pct"], bu["top_stock_profit_share_pct"])

print("\n=== COMPARISON TO BUILDER'S exact-entry-results.json ===")
for label, mine, theirs, diff, ok in comparisons:
    status = "OK" if ok else "MISMATCH"
    print(f"  {label}: mine={mine} theirs={theirs} diff={diff} [{status}]")

# candidate top stock ticker check
print(f"\npair.top_stock: mine={pair_summary['top_stock']} theirs={bp['top_stock']}")
print(f"short.top_stock: mine={short_summary['top_stock']} theirs={bu['top_stock']}")

# ---------- Step 5: spot check 12 random trades ----------

SPOT_SEED = 777
rng = random.Random(SPOT_SEED)
sample = rng.sample(priced, 12)

builder_trades = {}
with open(RESEARCH_DIR / "exact-entry-trades.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        key = (row["market_date"], row["ticker"], row["contract_symbol"])
        builder_trades[key] = row

spot_results = []
print(f"\n=== SPOT CHECK (seed={SPOT_SEED}) ===")
for t in sample:
    key = (t["market_date"], t["ticker"], t["contract_symbol"])
    b = builder_trades.get(key)
    hand_pair = float(b["spy_ret"]) - float(b["stock_ret"]) - 0.0025 if b else None
    match = None
    if b:
        match = (
            abs(t["stock_entry_px"] - float(b["stock_entry_px"])) < 1e-6 and
            abs(t["stock_exit_px"] - float(b["stock_exit_px"])) < 1e-6 and
            abs(t["spy_entry_px"] - float(b["spy_entry_px"])) < 1e-6 and
            abs(t["spy_exit_px"] - float(b["spy_exit_px"])) < 1e-6 and
            abs(t["pair_net"] - float(b["pair_net"])) < 1e-9
        )
    print(f"{t['market_date']} {t['ticker']}: entry={t['entry_date']} exit={t['exit_date']}")
    print(f"  stock_entry={t['stock_entry_px']} stock_exit={t['stock_exit_px']} spy_entry={t['spy_entry_px']} spy_exit={t['spy_exit_px']}")
    print(f"  my pair_net={t['pair_net']:.6f}  builder pair_net={b['pair_net'] if b else 'MISSING ROW'}  match={match}")
    spot_results.append({
        "market_date": t["market_date"], "ticker": t["ticker"],
        "entry_date": t["entry_date"], "exit_date": t["exit_date"],
        "stock_entry_px": t["stock_entry_px"], "stock_exit_px": t["stock_exit_px"],
        "spy_entry_px": t["spy_entry_px"], "spy_exit_px": t["spy_exit_px"],
        "my_pair_net": t["pair_net"], "builder_pair_net": float(b["pair_net"]) if b else None,
        "match": match,
    })

# ---------- Step 6: error checks ----------

print("\n=== STEP 6 CHECKS ===")
lookahead = [t for t in priced if t["entry_date"] <= t["market_date"]]
print(f"a) entry_date <= market_date (look-ahead): {len(lookahead)}")

bad_exit_gap = []
for t in priced:
    idx_entry = calendar.index(t["entry_date"])
    idx_exit = calendar.index(t["exit_date"])
    if idx_exit - idx_entry != 4:
        bad_exit_gap.append(t)
print(f"b) exit not exactly 4 sessions after entry: {len(bad_exit_gap)}")

not_in_cal = [t for t in priced if t["entry_date"] not in calendar or t["exit_date"] not in calendar]
print(f"c) entry/exit date not in SPY calendar: {len(not_in_cal)}")

print(f"d) cost is subtracted (0.0025 subtracted, not added): pair_net formula = spy_ret - stock_ret - 0.0025 -> yes, subtracted")

direction_check = []
for t in sample[:3]:
    fell_more = t["stock_ret"] < t["spy_ret"]
    positive_pair = t["pair_net"] > 0
    direction_check.append((t["ticker"], t["market_date"], t["stock_ret"], t["spy_ret"], t["pair_net"], fell_more, positive_pair, fell_more == positive_pair))
print("e) direction check on 3 trades (stock fell more than SPY -> pair_net positive):")
for row in direction_check:
    print("  ", row)

cols_used_for_selection = ["side", "vol_oi_ratio", "volume", "premium_usd", "ticker", "market_date", "contract_symbol", "flow_id"]
print(f"f) columns used in candidate SELECTION: {cols_used_for_selection}")
print("   All of these come from the options_flow row itself (the flow event), known at moment of detection on market_date. None are forward-looking (outcomes table's close_5d etc. are NOT used in selection).")

dupe_check = defaultdict(int)
for c in candidates:
    dupe_check[(c["ticker"], c["market_date"])] += 1
dupes = {k: v for k, v in dupe_check.items() if v > 1}
print(f"g) duplicate (ticker, market_date) pairs in candidate list: {len(dupes)}")

# ---------- write outputs ----------

out = {
    "step1": step1,
    "step2": step2,
    "step2_diffs_vs_frozen_csv": diffs,
    "step3_screen": step3_screen,
    "pair_summary": pair_summary,
    "short_summary": short_summary,
    "pair_halves": pair_halves,
    "short_halves": short_halves,
    "bootstrap": {
        "seed": SEED,
        "pair_low_pct": pair_boot_lo * 100,
        "pair_high_pct": pair_boot_hi * 100,
        "pair_low_above_zero": pair_boot_lo > 0,
        "short_low_pct": short_boot_lo * 100,
        "short_high_pct": short_boot_hi * 100,
        "short_low_above_zero": short_boot_lo > 0,
    },
    "comparisons": [
        {"label": l, "mine": m, "theirs": t, "diff": d, "ok": ok} for l, m, t, d, ok in comparisons
    ],
    "spot_check": {"seed": SPOT_SEED, "trades": spot_results},
    "step6": {
        "lookahead_count": len(lookahead),
        "bad_exit_gap_count": len(bad_exit_gap),
        "not_in_calendar_count": len(not_in_cal),
        "direction_check": direction_check,
        "duplicate_ticker_date_pairs": len(dupes),
        "columns_used_for_selection": cols_used_for_selection,
    },
}

with open(RESEARCH_DIR / "independent-verification.json", "w") as f:
    json.dump(out, f, indent=2, default=str)

print("\nDone. Wrote independent-verification.json")
