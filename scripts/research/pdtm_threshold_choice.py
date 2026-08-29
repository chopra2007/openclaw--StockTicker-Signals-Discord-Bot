#!/usr/bin/env python3
"""Re-derive the participation threshold from DEVELOPMENT counts only.

The first pass at this (`signal-frequency.json`) tabulated sealed-period counts
as well, and the clean-room reviewer was right to call that a touch of the
sealed block — sample sizes, never outcomes, but still a measurement taken
inside it.

This file redoes the same decision using development counts alone, projecting
the sealed sample as development x (182 / 672).  If the projection picks the
same threshold, the choice stands on development evidence by itself.  Both
files are kept; neither is deleted.
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdtm_methods as M  # noqa: E402
from pdtm_common import DEV_LAST, RES_DIR  # noqa: E402
from pdtm_count import load  # noqa: E402

DEV_DAYS, SEALED_DAYS = 672, 182
SEALED_GATE_TRADES, SEALED_GATE_DAYS, SEALED_GATE_STOCKS = 100, 50, 20
DEV_GATE_TRADES, DEV_GATE_DAYS, DEV_GATE_STOCKS = 300, 100, 30


def dev_only(sig):
    if len(sig) == 0:
        return dict(trades=0, days=0, stocks=0)
    s = sig[sig.date <= DEV_LAST]
    return dict(trades=int(len(s)), days=int(s.date.nunique()),
                stocks=int(s.symbol.nunique()))


def main():
    panel, d = load()
    scale = SEALED_DAYS / DEV_DAYS
    out = {
        "rule": ("choose the HIGHEST relative-volume threshold whose DEVELOPMENT counts "
                 "clear the development gates and whose projected sealed counts "
                 "(development x 182/672) clear the sealed gates. Highest, not lowest: "
                 "the sources say to trade stocks that are unusually busy, so the "
                 "closest provable version of their claim is the strictest filter that "
                 "still leaves enough trades to prove anything. The threshold is held "
                 "identical across methods, so the tightest method binds it."),
        "projection_factor": scale,
        "gates": {"development": [DEV_GATE_TRADES, DEV_GATE_DAYS, DEV_GATE_STOCKS],
                  "sealed": [SEALED_GATE_TRADES, SEALED_GATE_DAYS, SEALED_GATE_STOCKS]},
        "candidates": {},
    }
    for rv in (1.00, 1.10, 1.25, 1.50, 1.75, 2.00):
        row = {}
        for name, fn in (("M1", lambda: M.m1_signals(d, panel, rv, 0.0020)),
                         ("M2", lambda: M.m2_signals(d, panel, rv, 0.0020))):
            c = dev_only(fn())
            c["projected_sealed_trades"] = round(c["trades"] * scale, 1)
            c["projected_sealed_days"] = round(c["days"] * scale, 1)
            c["development_gates_met"] = bool(
                c["trades"] >= DEV_GATE_TRADES and c["days"] >= DEV_GATE_DAYS
                and c["stocks"] >= DEV_GATE_STOCKS)
            c["projected_sealed_gates_met"] = bool(
                c["projected_sealed_trades"] >= SEALED_GATE_TRADES
                and c["projected_sealed_days"] >= SEALED_GATE_DAYS
                and c["stocks"] >= SEALED_GATE_STOCKS)
            row[name] = c
        out["candidates"][f"{rv:.2f}"] = row
        print(f"relvol {rv:.2f}: " + json.dumps(row), flush=True)

    ok = [rv for rv, r in out["candidates"].items()
          if all(v["development_gates_met"] and v["projected_sealed_gates_met"]
                 for v in r.values())]
    out["thresholds_that_work_on_development_evidence_alone"] = ok
    out["chosen"] = max(ok, key=float) if ok else None
    out["note"] = ("The chosen value is the HIGHEST that works. It is still weaker than "
                   "the ~1.75 the practitioner sources imply by 'in play'; M1 cannot "
                   "reach the sample gates at 1.75 (189 development trades against a "
                   "300 gate). See clean-room-review.md question 6.")
    out["disclosure"] = (
        "An earlier count file, signal-frequency.json, tabulated SEALED-period trade "
        "counts (never outcomes) for several settings. That was a real, if mild, touch "
        "of the sealed block. This file redoes the decision from development counts "
        "alone. The peek is disclosed rather than acted on: at the chosen 1.25 the "
        "earlier count showed M1's ACTUAL sealed trades at 91 against a 100 gate, while "
        "the development projection here is 106. The threshold has NOT been lowered to "
        "fix that. If M1 reaches the sealed period and falls short on sample, that is "
        "reported as a failed gate.")
    (RES_DIR / "threshold-choice-development-only.json").write_text(json.dumps(out, indent=2))
    print("chosen on development evidence alone:", out["chosen"])


if __name__ == "__main__":
    main()
