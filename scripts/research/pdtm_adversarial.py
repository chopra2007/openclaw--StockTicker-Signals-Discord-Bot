#!/usr/bin/env python3
"""The objections that could overturn the TODO #106 NO PASS, measured.

Development dates only.  The sealed block is never touched.

Three objections are tested:
  1. The target is too small for the cost.  M1's median hold is three minutes
     and half its trades reach their target and still lose.  Would a bigger
     target, or holding to the close, find the edge?
  2. The participation filter is too weak.  The sources say "unusually busy";
     the run used "at least normally busy".  Does the per-trade edge strengthen
     as the filter tightens, the way the sources predict?
  3. The room veto throws away 86% of setups.  Does it throw away the winners?
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdtm_engine as E  # noqa: E402
import pdtm_methods as M  # noqa: E402
from pdtm_common import DEV_LAST, RES_DIR  # noqa: E402
from pdtm_run import COST_NORMAL, COST_OPEN_30, EXT_FRAC, MKT_TOL, load  # noqa: E402


def score(panel, sig, label):
    sig = sig[sig.date <= DEV_LAST] if len(sig) else sig
    if len(sig) == 0:
        return {"label": label, "trades": 0}
    t = E.one_position_per_symbol(
        E.simulate(panel, sig, COST_NORMAL, open_cost_bps=COST_OPEN_30))
    if len(t) == 0:
        return {"label": label, "trades": 0}
    return {"label": label, "trades": int(len(t)),
            "gross_bps": round(float(t.gross.mean()) * 1e4, 2),
            "net_bps": round(float(t.net.mean()) * 1e4, 2),
            "win_rate": round(float((t.net > 0).mean()), 3),
            "median_minutes_held": float(t.bars_held.median()),
            "reached_target": int((t.exit_reason == "target").sum())}


def main():
    panel, d = load("equs")
    out = {}

    print("1. Is the target too small for the cost?", flush=True)
    for rr in (1.5, 3.0, 6.0, 20.0):
        s = M.m1_signals(d, panel, 1.25, MKT_TOL, reward_risk=rr)
        r = score(panel, s, f"M1 target {rr}x risk")
        out[f"target_{rr}"] = r
        print("  ", json.dumps(r), flush=True)

    print("2. Does the edge strengthen as the participation filter tightens?", flush=True)
    for rv in (1.25, 1.75, 2.50):
        s = M.m1_signals(d, panel, rv, MKT_TOL)
        r = score(panel, s, f"M1 relative volume {rv}")
        out[f"relvol_{rv}"] = r
        print("  ", json.dumps(r), flush=True)

    print("3. Does the room veto throw away the winners?", flush=True)
    for dis, lab in ((("room",), "no room veto"), ((), "as frozen")):
        s = M.m1_signals(d, panel, 1.25, MKT_TOL, disable=dis)
        r = score(panel, s, f"M1 {lab}")
        out[f"veto_{lab.replace(' ', '_')}"] = r
        print("  ", json.dumps(r), flush=True)

    (RES_DIR / "adversarial-tests.json").write_text(json.dumps(out, indent=2))
    print("wrote adversarial-tests.json", flush=True)


if __name__ == "__main__":
    main()
