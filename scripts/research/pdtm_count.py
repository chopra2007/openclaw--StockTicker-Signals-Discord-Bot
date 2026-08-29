#!/usr/bin/env python3
"""How often each candidate rule FIRES, at several candidate thresholds.

Counts only.  No return is computed anywhere in this file.  Its whole purpose
is to choose thresholds that can reach the sample-size gates, using an input
property of the data, before any profit number exists.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdtm_methods as M  # noqa: E402
from pdtm_common import DEV_LAST, RES_DIR, build_panel  # noqa: E402
from pdtm_predictors import decision_frame  # noqa: E402


def load(feed="equs"):
    panel = build_panel(feed)
    d = decision_frame(feed)
    z = np.load(RES_DIR / f"ctx-{feed}.npz")
    d._ret, d._mkt = z["ret"], z["mkt"]
    return panel, d


def counts(sig, d):
    if len(sig) == 0:
        return dict(trades=0, dev=0, sealed=0)
    dev = sig[sig.date <= DEV_LAST]
    seal = sig[sig.date > DEV_LAST]
    f = lambda s: dict(trades=len(s), days=int(s.date.nunique()),
                       stocks=int(s.symbol.nunique()),
                       long=int((s.side > 0).sum()), short=int((s.side < 0).sum()))
    return dict(all=f(sig), development=f(dev), sealed=f(seal))


def main():
    panel, d = load()
    print("mkt_or dev percentiles:",
          {k: round(float(np.nanpercentile(d[d.is_dev & d.eligible].mkt_or, k)), 5)
           for k in (10, 25, 50, 75, 90)})
    out = {}
    for rv in (1.25, 1.50, 1.75, 2.00):
        for mt in (0.0010, 0.0020):
            k = f"M1 relvol>={rv} mkt_tol={mt}"
            out[k] = counts(M.m1_signals(d, panel, rv, mt), d)
            print(k, json.dumps(out[k]), flush=True)
    for rv in (1.25, 1.50, 1.75, 2.00):
        k = f"M2 relvol>={rv} mkt_tol=0.002"
        out[k] = counts(M.m2_signals(d, panel, rv, 0.0020), d)
        print(k, json.dumps(out[k]), flush=True)
    for rv in (1.25, 1.50, 1.75):
        for ext in (0.382, 0.618):
            k = f"M3 relvol>={rv} ext={ext}"
            out[k] = counts(M.m3_signals(d, panel, rv, ext, "fib"), d)
            print(k, json.dumps(out[k]), flush=True)
    (RES_DIR / "signal-frequency.json").write_text(json.dumps(out, indent=2))
    print("wrote signal-frequency.json")


if __name__ == "__main__":
    main()
