"""Build the minute-by-minute move of the 60-name group itself.

Every idea screened so far looks only at the one stock being traded. This file
makes the other 59 available: at each minute it records the MEDIAN half-hour
return across all sixty names. A single name's half-hour return minus that
median is what the name did on its own, with the whole group's move taken out.

The median is used rather than the average so that one name's news cannot move
the yardstick it is being measured against.

Development period only - the sealed bars are dropped before anything is
computed. Writes one parquet to the research-data folder; safe to re-run.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_111_round2_bracket as B
import todo_111_round2_prescreen as P

OUT = Path("/home/openclaw/.openclaw/research-data/todo-111-round2/market-move-equs.parquet")


def build(feed="equs"):
    series = {}
    for sym in B.symbols(feed):
        df = B.load(sym, feed)
        df = df[df["ts"] < P.DEV_END]
        close = df["close"].to_numpy(np.float64)
        ret30 = np.full(len(close), np.nan)
        ret30[30:] = close[30:] / close[:-30] - 1.0
        series[sym] = pd.Series(ret30, index=df["ts"].to_numpy())
        print("loaded", sym, flush=True)
    wide = pd.DataFrame(series)
    market = wide.median(axis=1, skipna=True)
    out = pd.DataFrame({"ts": market.index, "market_ret30": market.to_numpy()})
    out = out.dropna()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print("wrote", OUT, len(out), "minutes")


if __name__ == "__main__":
    t0 = time.time()
    build()
    print("%.0fs" % (time.time() - t0))
