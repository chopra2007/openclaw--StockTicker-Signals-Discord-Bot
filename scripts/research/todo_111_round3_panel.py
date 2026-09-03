"""TODO #111 round 3 - the cross-sectional mechanism.

Every family screened so far, in round 2 and round 3, decides one stock's trade
by looking at that one stock. This file is the exception the owner asked for:
it looks at all sixty names at the same moment and trades a name because of
where it SITS AMONG THE OTHERS, not because of anything on its own chart.

At 11:00 New York each session, every name's move since its own open is
measured and the sixty are put in order. The six that have gone up the most and
the six that have gone down the most are the extremes.

  momentum: buy the six strongest, short the six weakest
  reversal: the mirror - short the six strongest, buy the six weakest

Both are run because the point is to find out whether the ranking carries any
information at all; if it does, one of the two must move away from the middle.

Development period only. Entry is the open of the bar AFTER the 11:00 signal
bar, exits come from the frozen bracket engine, returns are GROSS.
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_111_round2_bracket as B
import todo_111_round3_prescreen as R

OUT = Path("/home/openclaw/.openclaw/workspace/.omc/research")
N_EXTREME = 6


def signals(df):
    """One row a session: the session date, the bar index at 11:00, and how far
    the name has moved since its own open."""
    m = df["min"].to_numpy()
    at_mid = (m >= R.MID_MIN - 2) & (m <= R.MID_MIN)
    ok = at_mid & (df["ts"] < R.LAST_SIGNAL).to_numpy()
    idx = R._first_per_day(ok, df["day"].to_numpy())
    if len(idx) == 0:
        return []
    op = R._per_day(df, (m >= R.OPEN_MIN) & (m < R.OPEN_MIN + 5), "open", "first")
    px = df["close"].to_numpy(np.float64)
    dates = df["date"].to_numpy()
    out = []
    for i in idx:
        o = op[i]
        if not np.isfinite(o) or o <= 0:
            continue
        out.append((dates[i], int(i), float(px[i] / o - 1.0)))
    return out


def build(feed="equs"):
    """Collect every name's 11:00 standing, keyed by session date."""
    per_date = defaultdict(list)
    frames = {}
    for sym in B.symbols(feed):
        df = R.frame(sym, feed)
        if df is None:
            continue
        frames[sym] = df
        for date, i, ret in signals(df):
            per_date[date].append((sym, i, ret))
        print("loaded", sym, flush=True)
    return frames, per_date


def pick(per_date, reverse=False):
    """Which name trades which way, on each session."""
    chosen = defaultdict(list)
    for date, rows in per_date.items():
        if len(rows) < 3 * N_EXTREME:
            continue                       # too few names reporting to rank
        rows.sort(key=lambda r: r[2])
        weak, strong = rows[:N_EXTREME], rows[-N_EXTREME:]
        up, dn = (weak, strong) if reverse else (strong, weak)
        for sym, i, _ in up:
            chosen[sym].append((i, 1.0))
        for sym, i, _ in dn:
            chosen[sym].append((i, -1.0))
    return chosen


def run(name, frames, chosen, feed):
    parts = []
    for sym, picks in chosen.items():
        picks.sort()
        idx = np.array([p[0] for p in picks])
        dirn = np.array([p[1] for p in picks])
        tr = B.simulate(frames[sym], idx, dirn)
        tr["symbol"] = sym
        parts.append(tr)
    allt = pd.concat(parts, ignore_index=True)
    out = {"family": name, "feed": feed, "period": "development",
           "devEnd": str(R.DEV_END.date()), "costBasis": "gross_no_costs",
           "exitPriceResolution": "one_minute", "extremesPerSide": N_EXTREME}
    out.update(B.summarise(allt))
    longs, shorts = allt[allt["direction"] > 0], allt[allt["direction"] < 0]
    out["long"] = B.summarise(longs) if len(longs) else None
    out["short"] = B.summarise(shorts) if len(shorts) else None
    return out


def main():
    feed = sys.argv[1] if len(sys.argv) > 1 else "equs"
    t0 = time.time()
    frames, per_date = build(feed)
    results = []
    for name, rev in [("panel-rank-momentum", False), ("panel-rank-reversal", True)]:
        r = run(name, frames, pick(per_date, rev), feed)
        r["seconds"] = round(time.time() - t0, 1)
        results.append(r)
        print("%-22s %7d trades  target-first %5.2f%%  avg %+.4f%%"
              % (name, r["tradeCount"], r["winRatePct"], r["avgReturnPct"]),
              flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("todo-111-round3-panel-%s.json" % feed)
    path.write_text(json.dumps(results, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
