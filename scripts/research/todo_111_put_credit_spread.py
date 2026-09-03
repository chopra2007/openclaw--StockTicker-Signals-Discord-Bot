#!/usr/bin/env python3
"""TODO #111 candidate 1 — short OTM put credit spread, held to expiration.

Implements the frozen rule in
`.omc/research/todo-111-proven-trading-edge/frozen-rule-candidate-1.md`
end to end: snapshot dates -> universe -> option chains -> underlying
settlement prices -> trades -> development-period result.

Option data comes from the DoltHub `post-no-preference/options` database. The
public HTTP SQL endpoint turned out to be too slow and too flaky for the ~5000
queries this needs (range queries hit the server's 55s deadline every time), so
the repository is cloned locally once with the `dolt` CLI and queried from disk:

    mkdir -p /home/openclaw/.openclaw/research-data/todo-111/dolt
    cd /home/openclaw/.openclaw/research-data/todo-111/dolt && dolt clone post-no-preference/options

Stages (run in order, each is idempotent and caches to disk):
    python3 todo_111_put_credit_spread.py dates
    python3 todo_111_put_credit_spread.py universe
    python3 todo_111_put_credit_spread.py chains
    python3 todo_111_put_credit_spread.py prices
    python3 todo_111_put_credit_spread.py trades
"""
import csv
import datetime as dt
import io
import json
import os
import statistics
import subprocess
import sys

OUT = "/home/openclaw/.openclaw/workspace/.omc/research/todo-111-proven-trading-edge"
DATA = "/home/openclaw/.openclaw/research-data/todo-111"
DOLT_DIR = os.path.join(DATA, "dolt", "options")
DATES_JSON = os.path.join(DATA, "snapshot-dates.json")
FIRST_SNAPSHOT_ROWS = os.path.join(DATA, "first-snapshot-puts.csv")
CHAINS_CSV = os.path.join(DATA, "dev-universe-puts.csv")
PRICE_DIR = os.path.join(DATA, "prices")

FIRST = "2019-02-09"          # first date in the table, confirmed from the data
LAST = "2026-09-01"
DEV_START = "2019-02-11"
DEV_END = "2022-12-31"

UNIVERSE_SIZE = 60
DTE_LO, DTE_HI, DTE_TARGET = 25, 45, 35
SHORT_DELTA_TARGET = -0.20
SHORT_DELTA_LO, SHORT_DELTA_HI = -0.30, -0.12
MIN_SHORT_BID = 0.10

# Per spread: 2 legs x $0.65 commission = $1.30 each way.
# Per spread: 2 legs x 100 shares x $0.01 slippage = $2.00 each way.
OPEN_COST = 1.30 + 2.00
CLOSE_COST = 1.30 + 2.00


def d(s):
    return dt.date.fromisoformat(s)


def sql_csv(query, out_path=None):
    """Run one SQL query against the local clone, returning a list of dicts."""
    cmd = ["dolt", "sql", "-r", "csv", "-q", query]
    proc = subprocess.run(cmd, cwd=DOLT_DIR, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("dolt sql failed: %s" % proc.stderr[-2000:])
    if out_path:
        with open(out_path, "w") as f:
            f.write(proc.stdout)
    return list(csv.DictReader(io.StringIO(proc.stdout)))


# ------------------------------------------------------------ stage: dates
def stage_dates():
    rows = sql_csv("select distinct date from option_chain where date>='%s' and date<='%s' "
                   "order by date" % (FIRST, LAST))
    dates = [r["date"] for r in rows]
    with open(DATES_JSON, "w") as f:
        json.dump(dates, f, indent=1)
    print("snapshot dates: %d (%s .. %s)" % (len(dates), dates[0], dates[-1]))
    return dates


def load_dates():
    with open(DATES_JSON) as f:
        return json.load(f)


# --------------------------------------------------------- stage: universe
def stage_universe():
    """The 60 tightest names, measured on the first snapshot in the data."""
    rows = sql_csv("select act_symbol,expiration,strike,bid,ask,delta from option_chain "
                   "where date='%s' and call_put='Put'" % FIRST, out_path=FIRST_SNAPSHOT_ROWS)
    print("put rows on %s: %d" % (FIRST, len(rows)), flush=True)

    best = {}
    for r in rows:
        try:
            delta = float(r["delta"]); bid = float(r["bid"]); ask = float(r["ask"])
        except (TypeError, ValueError):
            continue
        mid = (bid + ask) / 2.0
        if mid <= 0:
            continue              # no quote at all -> tightness is not measurable
        width = (ask - bid) / mid
        key = (abs(delta + 0.50), r["expiration"], float(r["strike"]))
        cur = best.get(r["act_symbol"])
        if cur is None or key < cur[0]:
            best[r["act_symbol"]] = (key, {
                "symbol": r["act_symbol"], "expiration": r["expiration"],
                "strike": float(r["strike"]), "delta": delta,
                "bid": bid, "ask": ask, "relativeWidth": width})

    cands = [v[1] for v in best.values()]
    cands.sort(key=lambda c: (c["relativeWidth"], c["symbol"]))
    universe = cands[:UNIVERSE_SIZE]
    payload = {"measuredOnSnapshot": FIRST,
               "symbolsWithMeasurableWidth": len(cands),
               "universeSize": len(universe),
               "universe": universe}
    with open(os.path.join(OUT, "universe.json"), "w") as f:
        json.dump(payload, f, indent=1)
    print("universe: %d symbols, relative width %.4f .. %.4f"
          % (len(universe), universe[0]["relativeWidth"], universe[-1]["relativeWidth"]))
    return [u["symbol"] for u in universe]


def universe_symbols():
    with open(os.path.join(OUT, "universe.json")) as f:
        return [u["symbol"] for u in json.load(f)["universe"]]


# ----------------------------------------------------------- stage: chains
def month_starts(a, b):
    cur = d(a).replace(day=1)
    stop = d(b)
    while cur <= stop:
        nxt = (cur.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
        yield cur.isoformat(), (nxt - dt.timedelta(days=1)).isoformat()
        cur = nxt


def stage_chains():
    """Every put quote for the universe over the development window.

    Pulled a month at a time and filtered to the universe in Python. Adding
    `act_symbol in (...60 symbols...)` to the SQL makes Dolt abandon the
    primary-key range scan and read the whole 8 GB table (over an hour, never
    finished); the same query with only the date range answers in ~2.5s.
    """
    keep = set(universe_symbols())
    cols = ["date", "act_symbol", "expiration", "strike", "bid", "ask", "delta"]
    total = 0
    dates = set()
    with open(CHAINS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for a, b in month_starts(DEV_START, DEV_END):
            lo = max(a, DEV_START)
            hi = min(b, DEV_END)
            rows = sql_csv("select date,act_symbol,expiration,strike,bid,ask,delta "
                           "from option_chain where call_put='Put' "
                           "and date>='%s' and date<='%s'" % (lo, hi))
            hit = [r for r in rows if r["act_symbol"] in keep]
            for r in hit:
                w.writerow(r)
                dates.add(r["date"])
            total += len(hit)
            print("  %s: %d rows scanned, %d kept (total %d)"
                  % (lo[:7], len(rows), len(hit), total), flush=True)
    with open(DATES_JSON, "w") as f:
        json.dump(sorted(dates), f, indent=1)
    print("development put rows: %d over %d snapshot dates" % (total, len(dates)))


def load_chains():
    with open(CHAINS_CSV) as f:
        return list(csv.DictReader(f))


# ----------------------------------------------------------- stage: prices
def yf_symbol(sym):
    return sym.replace(".", "-")


def stage_prices():
    """Raw (split-unadjusted) daily closes per symbol, rebuilt from yfinance."""
    import pandas as pd
    import yfinance as yf

    os.makedirs(PRICE_DIR, exist_ok=True)
    for sym in universe_symbols():
        path = os.path.join(PRICE_DIR, "%s.json" % sym)
        if os.path.exists(path):
            continue
        t = yf.Ticker(yf_symbol(sym))
        try:
            h = t.history(start="2019-01-01", end="2027-01-01", auto_adjust=False)
            splits = t.splits
        except Exception as exc:
            print("  %s: yfinance error %s" % (sym, exc), flush=True)
            h, splits = pd.DataFrame(), pd.Series(dtype=float)
        raw = {}
        sp = []
        if len(splits):
            sp = [(k.date().isoformat(), float(v)) for k, v in splits.items() if float(v) > 0]
        if len(h):
            for ts, row in h.iterrows():
                day = ts.date().isoformat()
                factor = 1.0
                for sd, ratio in sp:
                    if sd > day:          # split takes effect after this bar
                        factor *= ratio
                raw[day] = float(row["Close"]) * factor
        with open(path, "w") as f:
            json.dump({"symbol": sym, "rawClose": raw, "splits": dict(sp)}, f)
        print("  %s: %d bars, %d splits" % (sym, len(raw), len(sp)), flush=True)


# Tickers Yahoo has since reassigned to an unrelated listing. "FB" now returns a
# security whose first bar is 2025-06-26; Facebook's own 2019-2022 history only
# lives under META. The frozen rule charges a renamed name maximum loss rather
# than substituting the new symbol, so FB's price series is discarded outright —
# this guard makes that explicit instead of relying on the date ranges missing.
RECYCLED_TICKERS = {"FB"}


def load_prices(symbols):
    out = {}
    for s in symbols:
        p = os.path.join(PRICE_DIR, "%s.json" % s)
        if s in RECYCLED_TICKERS or not os.path.exists(p):
            out[s] = {}
            continue
        out[s] = json.load(open(p))["rawClose"]
    return out


def settlement_close(prices_for_symbol, expiration):
    """Close on the expiration date, else the last trading day within 5 days."""
    if not prices_for_symbol:
        return None
    exp = d(expiration)
    for back in range(0, 6):
        key = (exp - dt.timedelta(days=back)).isoformat()
        if key in prices_for_symbol:
            return prices_for_symbol[key]
    return None


# ------------------------------------------------------- validation (step 4)
def stage_validate(n=30):
    """Delta -0.50 strike vs reconstructed raw close, on random symbol-dates."""
    import random
    rows = load_chains()
    prices = load_prices(universe_symbols())
    by = {}
    for r in rows:
        by.setdefault((r["act_symbol"], r["date"]), []).append(r)
    keys = sorted(by)
    random.Random(111).shuffle(keys)
    checked, fails = [], []
    for sym, date in keys:
        if len(checked) >= n:
            break
        close = prices.get(sym, {}).get(date)
        if close is None:                     # snapshots are stamped on non-trading days too
            for back in range(1, 5):
                close = prices.get(sym, {}).get((d(date) - dt.timedelta(days=back)).isoformat())
                if close is not None:
                    break
        if close is None:
            continue
        best = None
        for r in by[(sym, date)]:
            try:
                delta = float(r["delta"]); strike = float(r["strike"])
            except ValueError:
                continue
            k = abs(delta + 0.50)
            if best is None or k < best[0]:
                best = (k, strike)
        if best is None or best[0] > 0.05:
            continue
        err = abs(best[1] - close) / close
        rec = {"symbol": sym, "date": date, "atmStrike": best[1],
               "reconstructedRawClose": round(close, 4), "errorPct": round(100 * err, 3)}
        checked.append(rec)
        if err > 0.03:
            fails.append(rec)
    print(json.dumps({"checked": len(checked), "failedOver3Pct": len(fails),
                      "worst": max(checked, key=lambda c: c["errorPct"]) if checked else None,
                      "failures": fails}, indent=1))
    with open(os.path.join(OUT, "price-validation.json"), "w") as f:
        json.dump({"checked": checked, "failedOver3Pct": fails}, f, indent=1)
    return checked, fails


# ----------------------------------------------------------- stage: trades
def pick_trade(date, sym, rows):
    """Apply the frozen entry rule to one symbol's put chain on one date."""
    puts, seen = [], set()
    for r in rows:
        k = (r["expiration"], r["strike"])
        if k in seen:
            continue
        seen.add(k)
        try:
            puts.append({"expiration": r["expiration"], "strike": float(r["strike"]),
                         "bid": float(r["bid"]), "ask": float(r["ask"]),
                         "delta": float(r["delta"])})
        except (TypeError, ValueError):
            continue
    if not puts:
        return None

    entry = d(date)
    exps = {}
    for p in puts:
        exps.setdefault(p["expiration"], []).append(p)
    cand = [(e, (d(e) - entry).days) for e in exps]
    cand = [(e, n) for e, n in cand if DTE_LO <= n <= DTE_HI]
    if not cand:
        return None
    # closest to 35 days; a tie goes to the shorter dated expiration
    exp, dte = min(cand, key=lambda x: (abs(x[1] - DTE_TARGET), x[1]))
    chain = exps[exp]

    shorts = [p for p in chain if SHORT_DELTA_LO <= p["delta"] <= SHORT_DELTA_HI]
    if not shorts:
        return None
    # closest to -0.20; a tie goes to the higher strike
    short = min(shorts, key=lambda p: (abs(p["delta"] - SHORT_DELTA_TARGET), -p["strike"]))
    if not (short["bid"] > 0 and short["ask"] > 0 and short["bid"] >= MIN_SHORT_BID):
        return None

    lowers = [p for p in chain if p["strike"] < short["strike"] and p["bid"] > 0 and p["ask"] > 0]
    if not lowers:
        return None
    long_ = max(lowers, key=lambda p: p["strike"])

    credit = (short["bid"] - long_["ask"]) * 100.0 - OPEN_COST
    if credit <= 0:
        return None
    return {"symbol": sym, "entryDate": date, "expiration": exp, "dte": dte,
            "shortStrike": short["strike"], "longStrike": long_["strike"],
            "shortBid": short["bid"], "longAsk": long_["ask"],
            "entryDelta": short["delta"], "creditNet": round(credit, 4)}


def stage_trades():
    symbols = universe_symbols()
    prices = load_prices(symbols)
    by = {}
    for r in load_chains():
        by.setdefault((r["date"], r["act_symbol"]), []).append(r)

    trades = []
    for (date, sym) in sorted(by):
        if not (DEV_START <= date <= DEV_END):
            continue
        t = pick_trade(date, sym, by[(date, sym)])
        if not t:
            continue
        width = t["shortStrike"] - t["longStrike"]
        close = settlement_close(prices.get(sym, {}), t["expiration"])
        if close is None:
            settle = width                    # maximum loss, never dropped
            t["missingPrice"] = True
        else:
            settle = min(max(t["shortStrike"] - close, 0.0), width)
            t["missingPrice"] = False
        paid = settle * 100.0 + CLOSE_COST
        t["settlementClose"] = None if close is None else round(close, 4)
        t["settlementValue"] = round(settle, 4)
        t["paidToCloseNet"] = round(paid, 4)
        t["returnPct"] = round((t["creditNet"] - paid) / t["creditNet"] * 100.0, 4)
        t["netProfitUsd"] = round(t["creditNet"] - paid, 4)
        trades.append(t)

    rets = [t["returnPct"] for t in trades]
    res = {
        "instrument": "options",
        "period": "%s..%s" % (DEV_START, DEV_END),
        "tradeCount": len(trades),
        "avgReturnPctAfterCosts": round(statistics.mean(rets), 4) if rets else None,
        "winRatePct": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 4) if rets else None,
        "medianReturnPct": round(statistics.median(rets), 4) if rets else None,
        "worstReturnPct": round(min(rets), 4) if rets else None,
        "bestReturnPct": round(max(rets), 4) if rets else None,
        "totalCreditCollectedUsd": round(sum(t["creditNet"] for t in trades), 2),
        "totalNetProfitUsd": round(sum(t["netProfitUsd"] for t in trades), 2),
        "tradesChargedMaxLossForMissingPrice": sum(1 for t in trades if t["missingPrice"]),
        "distinctSymbols": len({t["symbol"] for t in trades}),
    }
    with open(os.path.join(OUT, "development-result.json"), "w") as f:
        json.dump(res, f, indent=1)

    cols = ["symbol", "entryDate", "expiration", "shortStrike", "longStrike", "shortBid",
            "longAsk", "entryDelta", "creditNet", "settlementClose", "settlementValue",
            "paidToCloseNet", "returnPct"]
    with open(os.path.join(OUT, "trades-development.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for t in sorted(trades, key=lambda x: (x["entryDate"], x["symbol"])):
            w.writerow(t)
    print(json.dumps(res, indent=1))
    return res


STAGES = {"dates": stage_dates, "universe": stage_universe, "chains": stage_chains,
          "prices": stage_prices, "validate": stage_validate, "trades": stage_trades}

if __name__ == "__main__":
    STAGES[sys.argv[1]]()
