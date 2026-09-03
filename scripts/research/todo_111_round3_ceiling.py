"""TODO #111 round 3 - the ceiling test.

Seven mechanisms have now been measured and every one of them landed on the
baseline. This file asks a different question, and it is the one that decides
whether more mechanisms are worth building:

    Forget triggers. If we simply LOOK UP which stocks, in which hour of the
    day, in which direction, reached the target first most often in the past,
    and then trade exactly those - does it keep working afterwards?

That is the friendliest possible test. It cannot be beaten by any trigger,
because it is allowed to cherry-pick with hindsight. It is run in two halves:

    half A  - everything before 2024-05-01, used to pick the winners
    half B  - 2024-05-01 to the edge of the seal, used to see if they held

If the cherry-picked winners fall back to the baseline in half B, then the
information needed to reach 60 in 100 is not in this data at all, and no
further trigger built from it can get there. If they hold up, the picking rule
itself is a candidate.

Development period only. Entry is the open of the bar AFTER the signal bar,
exits come from the frozen bracket engine, returns are GROSS.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_111_round2_bracket as B
import todo_111_round3_prescreen as R

OUT = Path("/home/openclaw/.openclaw/workspace/.omc/research")

SPLIT = pd.Timestamp("2024-05-01", tz="UTC")
HOURS = [10, 11, 12, 13, 14, 15]      # New York hours, entry at :05 past
MIN_TRADES_A = 120                    # a cell needs a real history to be picked
TOP_CELLS = 20


def trades_for(sym, feed):
    """Every hourly entry this name offers, both directions, tagged with the
    half it belongs to and the hour it was taken in."""
    df = R.frame(sym, feed)
    if df is None:
        return None
    m = df["min"].to_numpy()
    ok = np.isin(m // 60, HOURS) & (m % 60 == 5)
    ok &= (df["ts"] < R.LAST_SIGNAL).to_numpy()
    idx = np.flatnonzero(ok)
    if len(idx) == 0:
        return None
    parts = []
    for dirn in (1.0, -1.0):
        tr = B.simulate(df, idx, np.full(len(idx), dirn))
        tr["hour"] = pd.DatetimeIndex(tr["entry_ts"]).tz_convert(
            "America/New_York").hour
        tr["direction"] = dirn
        parts.append(tr)
    out = pd.concat(parts, ignore_index=True)
    out["symbol"] = sym
    out["half"] = np.where(
        pd.DatetimeIndex(out["entry_ts"]) < SPLIT, "A", "B")
    return out


def main():
    feed = sys.argv[1] if len(sys.argv) > 1 else "equs"
    t0 = time.time()
    parts = []
    for sym in B.symbols(feed):
        tr = trades_for(sym, feed)
        if tr is not None:
            parts.append(tr)
        print("done", sym, flush=True)
    allt = pd.concat(parts, ignore_index=True)
    allt["win"] = allt["outcome"] == "target"

    a = allt[allt["half"] == "A"]
    b = allt[allt["half"] == "B"]
    key = ["symbol", "hour", "direction"]
    ga = a.groupby(key)["win"].agg(["mean", "count"])
    ga = ga[ga["count"] >= MIN_TRADES_A].sort_values("mean", ascending=False)
    picked = ga.head(TOP_CELLS)

    sel = b.set_index(key).index.isin(picked.index)
    chosen = b[sel]

    res = {
        "test": "ceiling-cherry-picked-cells",
        "feed": feed, "period": "development", "costBasis": "gross_no_costs",
        "exitPriceResolution": "one_minute",
        "splitDate": str(SPLIT.date()),
        "cellDefinition": "symbol x New York hour x direction",
        "cellsConsidered": int(len(ga)),
        "cellsPicked": int(len(picked)),
        "minTradesToBePicked": MIN_TRADES_A,
        "halfA": {"allCells": B.summarise(a),
                  "pickedCellsInA": float(picked["mean"].mean() * 100.0)},
        "halfB": {"allCells": B.summarise(b),
                  "pickedCells": B.summarise(chosen)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("todo-111-round3-ceiling-%s.json" % feed)
    path.write_text(json.dumps(res, indent=2))
    print("\nhalf A, every cell        %7d trades  target-first %5.2f%%"
          % (res["halfA"]["allCells"]["tradeCount"],
             res["halfA"]["allCells"]["winRatePct"]))
    print("half A, the 20 picked                     target-first %5.2f%%"
          % res["halfA"]["pickedCellsInA"])
    print("half B, every cell        %7d trades  target-first %5.2f%%"
          % (res["halfB"]["allCells"]["tradeCount"],
             res["halfB"]["allCells"]["winRatePct"]))
    print("half B, the 20 picked     %7d trades  target-first %5.2f%%  avg %+.4f%%"
          % (res["halfB"]["pickedCells"]["tradeCount"],
             res["halfB"]["pickedCells"]["winRatePct"],
             res["halfB"]["pickedCells"]["avgReturnPct"]))
    print("wrote", path, "(%.0fs)" % (time.time() - t0))


if __name__ == "__main__":
    main()
