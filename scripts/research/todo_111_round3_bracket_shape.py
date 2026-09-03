"""TODO #111 - does an even-sized target and stop win more than a two-to-one one?

The owner asked, on 2026-09-03, to test +0.5% against -0.5% instead of the
frozen +1.0% against -0.5%. This file re-measures the same entry rules with the
only thing changed being the shape of the bracket.

Two numbers matter and they pull in opposite directions:

  - the WIN RATE goes up, mechanically, because the target is now as close as
    the stop instead of twice as far;
  - the MONEY NEEDED goes up with it, because each win pays 0.5% instead of
    1.0% while each loss still costs 0.5%.

At +1.0/-0.5 a rule needs 60 wins in 100 to average +0.40% a trade. At
+0.5/-0.5 the same +0.40% a trade needs 90 wins in 100. Both figures are
printed so the comparison is like for like rather than a bigger-looking
percentage.

Development period only. Returns are gross.
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
SHAPES = [(1.0, 0.5), (0.5, 0.5)]
PICK = ["baseline-1130-no-trigger", "baseline-1100-no-trigger",
        "orb15-break", "overnight-break", "trend-day-continuation"]

_real_simulate = B.simulate


def needed_win_rate(target, stop, avg_wanted=0.40):
    """The win rate at which this bracket averages avg_wanted a trade."""
    return (avg_wanted + stop) / (target + stop) * 100.0


def main():
    feed = sys.argv[1] if len(sys.argv) > 1 else "equs"
    results = []
    for target, stop in SHAPES:
        B.simulate = (lambda df, idx, dirn, t=target, s=stop:
                      _real_simulate(df, idx, dirn, target_pct=t, stop_pct=s))
        for name in PICK:
            t0 = time.time()
            r = R.screen(name, R.FAMILIES[name], feed)
            r["targetPct"] = target
            r["stopPct"] = stop
            r["winRateNeededForPlus040"] = round(needed_win_rate(target, stop), 2)
            r["seconds"] = round(time.time() - t0, 1)
            results.append(r)
            print("+%.1f/-%.1f  %-26s %7d trades  target-first %5.2f%%  "
                  "avg %+.4f%%  (needs %5.2f%%)"
                  % (target, stop, name, r["tradeCount"], r["winRatePct"],
                     r["avgReturnPct"], r["winRateNeededForPlus040"]), flush=True)
    B.simulate = _real_simulate
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("todo-111-round3-bracket-shape-%s.json" % feed)
    path.write_text(json.dumps(results, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
