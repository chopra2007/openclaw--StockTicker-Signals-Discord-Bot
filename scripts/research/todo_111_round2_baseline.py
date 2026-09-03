"""The unconditional baseline: how often does a +1.0% target get touched before
a -0.5% stop when the entry minute is chosen for no reason at all?

This is the number every candidate rule has to beat. Theory says a driftless
stock hits the far level first about 33 times in 100 (0.5 / 1.5). The owner's
bar is 60 in 100, so a rule has to be nearly twice as accurate as chance.

Entries are taken on a fixed clock stride through the regular session only
(09:30-15:59 New York), long and short at every sampled minute, on both feeds.
Every result here is GROSS - no commission, spread or slippage.

Writes JSON to .omc/research/todo-111-round2-baseline-<feed>.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_111_round2_bracket as B

OUT = Path("/home/openclaw/.openclaw/workspace/.omc/research")

# One sampled entry every 60 minutes of the regular session: about 6 or 7 a day
# per symbol, which is plenty of independent starts without pretending that
# overlapping minute-by-minute entries are separate trades.
STRIDE_MINUTES = 60


def session_signals(df):
    """Indices of regular-session bars on the sampling stride."""
    ny = df["ts"].dt.tz_convert("America/New_York")
    mins = ny.dt.hour * 60 + ny.dt.minute
    regular = (mins >= 9 * 60 + 30) & (mins <= 15 * 60 + 59)
    on_stride = ((mins - (9 * 60 + 30)) % STRIDE_MINUTES) == 0
    return np.flatnonzero((regular & on_stride).to_numpy())


def run(feed):
    per_symbol = {}
    frames = []
    for k, sym in enumerate(B.symbols(feed)):
        t0 = time.time()
        df = B.load(sym, feed)
        si = session_signals(df)
        parts = []
        for dirn in (1, -1):
            tr = B.simulate(df, si, np.full(len(si), dirn))
            tr["symbol"] = sym
            parts.append(tr)
        both = pd.concat(parts, ignore_index=True)
        frames.append(both)
        per_symbol[sym] = {
            "long": B.summarise(parts[0]),
            "short": B.summarise(parts[1]),
        }
        print("%s %2d/60 %-6s %d trades %.1fs"
              % (feed, k + 1, sym, len(both), time.time() - t0), flush=True)

    allt = pd.concat(frames, ignore_index=True)
    longs = allt[allt["direction"] > 0]
    shorts = allt[allt["direction"] < 0]
    report = {
        "feed": feed,
        "strideMinutes": STRIDE_MINUTES,
        "costBasis": "gross_no_costs",
        "exitPriceResolution": "one_minute",
        "target_pct": B.TARGET_PCT,
        "stop_pct": B.STOP_PCT,
        "all": B.summarise(allt),
        "long": B.summarise(longs),
        "short": B.summarise(shorts),
        "perSymbol": per_symbol,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("todo-111-round2-baseline-%s.json" % feed)
    path.write_text(json.dumps(report, indent=2))
    print("wrote", path, flush=True)
    for name in ("all", "long", "short"):
        s = report[name]
        print("  %-5s %7d trades  target-first %5.2f%%  avg %+.4f%%"
              % (name, s["tradeCount"], s["winRatePct"], s["avgReturnPct"]),
              flush=True)


if __name__ == "__main__":
    for feed in (sys.argv[1:] or ["equs", "xnys"]):
        run(feed)
