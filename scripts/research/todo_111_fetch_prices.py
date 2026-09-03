"""Cache daily adjusted closes for the TODO #111 candidate-3 universe.

One JSON file per symbol under research-data/todo-111/prices-adj/. A symbol with
no data at all still gets a file (empty series) so it is never re-fetched and is
counted honestly downstream.
"""
import json
import os
import sys
import time

import yfinance as yf

CACHE = "/home/openclaw/.openclaw/research-data/todo-111/prices-adj"


def cache_path(sym):
    return os.path.join(CACHE, sym.replace("/", "_") + ".json")


def yahoo_symbol(sym):
    return sym.replace(".", "-")


def store(sym, series, alias):
    with open(cache_path(sym), "w") as f:
        json.dump({"symbol": sym, "yahooSymbol": alias, "adjClose": series}, f)


def fetch_batch(syms):
    alias = {yahoo_symbol(s): s for s in syms}
    df = yf.download(list(alias), period="max", auto_adjust=False,
                     group_by="ticker", threads=True, progress=False,
                     actions=False)
    out = {}
    for ys, orig in alias.items():
        try:
            sub = df[ys]["Adj Close"] if len(alias) > 1 else df["Adj Close"]
        except Exception:
            out[orig] = ({}, ys)
            continue
        sub = sub.dropna()
        out[orig] = ({d.strftime("%Y-%m-%d"): float(v) for d, v in sub.items()}, ys)
    return out


def main(path):
    os.makedirs(CACHE, exist_ok=True)
    syms = [s.strip() for s in open(path) if s.strip()]
    todo = [s for s in syms if not os.path.exists(cache_path(s))]
    print("universe %d, to fetch %d" % (len(syms), len(todo)), flush=True)
    step = 40
    for i in range(0, len(todo), step):
        batch = todo[i:i + step]
        try:
            got = fetch_batch(batch)
        except Exception as exc:
            print("batch failed %s: %s" % (batch[0], exc), flush=True)
            time.sleep(5)
            continue
        empty = 0
        for sym, (series, ys) in got.items():
            store(sym, series, ys)
            if not series:
                empty += 1
        print("%d/%d done, %d empty in batch" % (i + len(batch), len(todo), empty),
              flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main(sys.argv[1])
