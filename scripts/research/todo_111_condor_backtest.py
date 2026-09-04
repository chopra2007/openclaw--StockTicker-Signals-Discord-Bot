"""TODO #111 iron condor — run the frozen exit gate over the downloaded minutes.

Reads the leg files bought by todo_111_condor_pull.py, applies the frozen rule
(sell at bid, buy at ask; first touch of +20% or -20%; 14-trading-day cap) and
writes every number to a JSON file. Nothing here is typed by hand.
"""
from __future__ import annotations
import json, sys
from collections import defaultdict
from datetime import time
from zoneinfo import ZoneInfo

import databento as db

RD = "/home/openclaw/.openclaw/research-data/todo-111-condor"
NY = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)
TARGET, STOP = 0.20, -0.20
MAX_SPREAD_FRACTION = 0.25


def minutes(path, symbols):
    """ts (exchange time) -> {symbol: (bid, ask)}, regular session only."""
    df = db.DBNStore.from_file(path).to_df()
    want = set(symbols)
    book = defaultdict(dict)
    for ts, sym, b, a in zip(df.index, df["symbol"], df["bid_px_00"], df["ask_px_00"]):
        if sym not in want or float(a) <= 0:
            continue
        local = ts.astimezone(NY)
        if OPEN <= local.time() <= CLOSE:
            book[local][sym] = (float(b), float(a))
    return book


def structures(legs):
    s = legs["symbols"]
    return {
        "condor": ([s["short_put"], s["short_call"]], [s["long_put"], s["long_call"]]),
        "put_spread": ([s["short_put"]], [s["long_put"]]),
        "call_spread": ([s["short_call"]], [s["long_call"]]),
    }


def credit(book_min, shorts, longs):
    """What is collected on the way in: sell shorts at bid, buy longs at ask."""
    return sum(book_min[s][0] for s in shorts) - sum(book_min[s][1] for s in longs)


def cost_to_close(book_min, shorts, longs):
    """What it costs to get out: buy shorts back at ask, sell longs at bid."""
    return sum(book_min[s][1] for s in shorts) - sum(book_min[s][0] for s in longs)


def run_one(trade):
    legs = trade["legs"]
    entry_day = trade["entry_day"]
    syms = list(legs["symbols"].values())
    book = minutes(trade["legs_file"], syms)
    stamps = sorted(book)
    entry = next((t for t in stamps if str(t.date()) == entry_day
                  and t.hour == 10 and t.minute == 0), None)
    if entry is None or len(book[entry]) < 4:
        return {"skipped": "entry minute incomplete"}
    # frozen liquidity check on the two short legs
    for name in ("short_put", "short_call"):
        b, a = book[entry][legs["symbols"][name]]
        if b <= 0 or a <= 0 or (a - b) / ((a + b) / 2) > MAX_SPREAD_FRACTION:
            return {"skipped": f"{name} quote too wide at entry"}
    complete = [t for t in stamps if t > entry and len(book[t]) == 4]
    out = {"entry_ts": str(entry),
           "session_minutes": len([t for t in stamps if t > entry]),
           "complete_minutes": len(complete)}
    for name, (shorts, longs) in structures(legs).items():
        c = credit(book[entry], shorts, longs)
        if c <= 0:
            out[name] = {"skipped": "credit is zero or negative"}
            continue
        res = {"credit": c, "exit_reason": "held to the 14-day cap"}
        for t in complete:
            r = (c - cost_to_close(book[t], shorts, longs)) / c
            if r >= TARGET or r <= STOP:
                res.update(exit_ts=str(t), ret=r,
                           exit_reason="target touched" if r >= TARGET else "stop touched")
                break
        else:
            if complete:
                t = complete[-1]
                res.update(exit_ts=str(t),
                           ret=(c - cost_to_close(book[t], shorts, longs)) / c)
            else:
                res = {"skipped": "no complete minute after entry"}
        out[name] = res
    return out


def summarise(rows, name):
    rets = [r[name]["ret"] for r in rows if name in r and "ret" in r[name]]
    if not rets:
        return {"trades": 0}
    wins = [x for x in rets if x > 0]
    return {"trades": len(rets), "wins": len(wins),
            "win_rate": len(wins) / len(rets),
            "avg_return": sum(rets) / len(rets),
            "worst": min(rets), "best": max(rets)}


if __name__ == "__main__":
    period = sys.argv[1]
    trades = json.load(open(f"{RD}/{period}_trades.json"))
    rows, skips = [], defaultdict(int)
    for t in trades:
        if "legs_file" not in t:
            skips[t.get("skipped", "no legs")] += 1
            continue
        r = run_one(t)
        r["signal_date"] = t["signal_date"]
        r["entry_day"] = t["entry_day"]
        if "skipped" in r:
            skips[r["skipped"]] += 1
            continue
        r["legs"] = t["legs"]
        rows.append(r)
    total_min = sum(r["session_minutes"] for r in rows)
    complete = sum(r["complete_minutes"] for r in rows)
    result = {"period": period, "entries_considered": len(trades),
              "trades_with_data": len(rows), "skips": dict(skips),
              "missing_minute_rate": 1 - complete / total_min if total_min else None,
              "condor": summarise(rows, "condor"),
              "put_spread": summarise(rows, "put_spread"),
              "call_spread": summarise(rows, "call_spread")}
    json.dump({"summary": result, "trades": rows},
              open(f"{RD}/{period}_result.json", "w"), indent=1, default=str)
    print(json.dumps(result, indent=1))
