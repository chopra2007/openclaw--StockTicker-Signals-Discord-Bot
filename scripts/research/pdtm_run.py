#!/usr/bin/env python3
"""Run the frozen methods and write every number the report needs.

    python3 pdtm_run.py development     # the 672 development days
    python3 pdtm_run.py sealed M2       # ONE named method, the 182 sealed days

The sealed run refuses to start unless a method is named and
`frozen-policy.sha256` exists, so the sealed block cannot be opened casually or
opened for more than one method.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdtm_controls as CT  # noqa: E402
import pdtm_engine as E  # noqa: E402
import pdtm_gates as G  # noqa: E402
import pdtm_methods as M  # noqa: E402
from pdtm_common import DEV_LAST, RES_DIR, build_panel  # noqa: E402
from pdtm_predictors import decision_frame  # noqa: E402

RELVOL_MIN = 1.25          # frozen: see threshold-choice-development-only.json
MKT_TOL = 0.0020           # frozen
EXT_FRAC = 0.382           # frozen for M3
COST_NORMAL, COST_HARSH = 20.0, 40.0
# Entries before 07:00 Pacific are charged the harsh rate as the PRIMARY cost.
# Spreads are widest in the first half hour; nobody in this research could read
# a source that measures by how much, so doubling is the conservative answer
# rather than inventing a figure.  Frozen before results.
COST_OPEN_30 = COST_HARSH
# M3 never reaches the sealed period.  At roughly six or seven signals a day it
# breaks the owner's own ceiling of four setups, so a pass could not be acted
# on.  Decided before any M3 return was computed.
SEALED_ELIGIBLE = ("M1", "M2")
YEARS_DEV = 672 / 252.0
YEARS_SEALED = 182 / 252.0


def load(feed="equs"):
    panel = build_panel(feed)
    d = decision_frame(feed)
    z = np.load(RES_DIR / f"ctx-{feed}.npz")
    object.__setattr__(d, "_ret", z["ret"])
    object.__setattr__(d, "_mkt", z["mkt"])
    return panel, d


BUILDERS = {
    "M1": lambda d, p: M.m1_signals(d, p, RELVOL_MIN, MKT_TOL),
    "M2": lambda d, p: M.m2_signals(d, p, RELVOL_MIN, MKT_TOL),
    "M3-fib": lambda d, p: M.m3_signals(d, p, RELVOL_MIN, EXT_FRAC, "fib"),
    "M3-mid": lambda d, p: M.m3_signals(d, p, RELVOL_MIN, EXT_FRAC, "mid"),
    "M3-even": lambda d, p: M.m3_signals(d, p, RELVOL_MIN, EXT_FRAC, "even"),
    "M1-control": lambda d, p: CT.m1_control_signals(d, p, RELVOL_MIN),
    "M2-control": lambda d, p: CT.m2_control_signals(d, p, RELVOL_MIN),
}


def build_all(d, panel, only=None):
    """Build only what is asked for.  Building all seven every time turned a
    seven-method run into forty-nine signal builds."""
    names = [only] if only else list(BUILDERS)
    return {n: BUILDERS[n](d, panel) for n in names}


def window(sig, phase):
    if len(sig) == 0:
        return sig
    return sig[sig.date <= DEV_LAST] if phase == "development" else sig[sig.date > DEV_LAST]


def evaluate(name, sig, panel, phase, years, gates, d=None):
    if len(sig) == 0:
        return {"label": name, "trades": 0, "note": "no signals"}
    sim = lambda s, c, **kw: E.one_position_per_symbol(
        E.simulate(panel, s, c, open_cost_bps=COST_OPEN_30, **kw))
    base = sim(sig, COST_NORMAL)
    if len(base) == 0:
        return {"label": name, "trades": 0, "note": "no completed trades"}
    out = G.summarise(base, name, years)

    # the drift benchmark: same direction, same minute, same geometry, chosen by
    # nothing.  This is what separates an edge from three rising years.
    # Controls do not need one: they exist to be beaten, not to be gated.
    if d is not None and not name.endswith("-control"):
        drift = CT.drift_benchmark(panel, d, sig, E.simulate, COST_NORMAL,
                                   open_cost_bps=COST_OPEN_30)
        if len(drift):
            out["edge_over_drift"] = CT.edge_over_drift(base.net.values, drift.net.values)

    if d is not None:
        restricted = set(map(tuple, d[d.rule201_restricted][["symbol", "date"]].values))
        shorts = base[base.side < 0]
        n_bad = sum(1 for s, dt in shorts[["symbol", "date"]].values
                    if (s, dt) in restricted)
        out["rule201"] = {
            "short_trades": int(len(shorts)),
            "short_trades_on_a_restricted_day": int(n_bad),
            "share": float(n_bad / max(len(shorts), 1)),
            "note": ("SEC Rule 201 restricts short selling for the rest of a day, and "
                     "the next day, once a stock trades 10% below its prior close. "
                     "These trades are counted, not removed."),
        }

    out["gates"] = G.check(out, gates)

    harsh = sim(sig, COST_HARSH)
    zero = sim(sig, 0.0)
    delayed = sim(sig, COST_NORMAL, entry_delay=1)
    out["stress"] = {
        "harsh_cost_mean_net": float(harsh.net.mean()),
        "zero_cost_mean_gross": float(zero.gross.mean()),
        "delayed_entry_mean_net": float(delayed.net.mean()),
        "delayed_entry_trades": int(len(delayed)),
    }

    flipped = sim(CT.flip_sides(sig), COST_NORMAL)
    key = ["symbol", "date", "confirm_min"]
    a = base.set_index(key).net
    b = flipped.set_index(key).net
    common = a.index.intersection(b.index)
    if len(common) > 20:
        out["placebo"] = CT.placebo_distribution(a.loc[common].values, b.loc[common].values)
        out["placebo"]["paired_signals"] = int(len(common))

    for col, tag in (("side", "by_direction"), ("sector", "by_sector"),
                     ("symbol", "by_stock")):
        g = base.groupby(col).net.agg(["count", "mean"])
        out[tag] = {str(k): [int(v["count"]), float(v["mean"])] for k, v in g.iterrows()}
    blk = base.assign(block=(base.entry_min // 30)).groupby("block").net.agg(["count", "mean"])
    out["by_time_block"] = {str(k): [int(v["count"]), float(v["mean"])] for k, v in blk.iterrows()}
    mon = base.assign(m=pd.to_datetime(base.date).dt.strftime("%Y-%m")).groupby("m").net.agg(["count", "mean"])
    out["by_month"] = {str(k): [int(v["count"]), float(v["mean"])] for k, v in mon.iterrows()}
    out["exposure"] = {
        "median_minutes_held": float(base.bars_held.median()),
        "mean_minutes_held": float(base.bars_held.mean()),
        "signals_before_overlap_filter": int(len(sig)),
        "trades_after_overlap_filter": int(len(base)),
    }
    return out


def independent_check(name, sig_equs, base_equs):
    """Rebuild the same signals on the second, independent feed and compare."""
    panel_p, d_p = load("pillar")
    sigs = build_all(d_p, panel_p, name)
    sp = sigs.get(name)
    if sp is None or len(sp) == 0:
        return {"note": "no signals on the independent feed"}
    key = ["symbol", "date"]
    a = set(map(tuple, base_equs[key].values))
    b = set(map(tuple, sp[key].values))
    trades_p = E.one_position_per_symbol(
        E.simulate(panel_p, sp, COST_NORMAL, open_cost_bps=COST_OPEN_30))
    return {
        "feed": "XNYS.PILLAR",
        "signals_on_this_feed": int(len(sp)),
        "company_days_shared_with_main_feed": int(len(a & b)),
        "coverage_of_main_feed_trades": float(len(a & b) / max(len(a), 1)),
        "completed_paths": int(len(trades_p)),
        "mean_net": float(trades_p.net.mean()),
        "mean_gross": float(trades_p.gross.mean()),
        "win_rate": float((trades_p.net > 0).mean()),
        "profit_factor": G.profit_factor(trades_p.net.values),
    }


def main():
    phase = sys.argv[1]
    only = sys.argv[2] if len(sys.argv) > 2 else None
    if phase == "sealed":
        if not only:
            sys.exit("the sealed period may only be opened for ONE named method")
        if only not in SEALED_ELIGIBLE:
            sys.exit(f"{only} is development-only; sealed-eligible: {SEALED_ELIGIBLE}")
        if not (RES_DIR / "frozen-policy.sha256").exists():
            sys.exit("refusing to open sealed data before the policy is frozen")
    gates = G.GATES_DEV if phase == "development" else G.GATES_SEALED
    years = YEARS_DEV if phase == "development" else YEARS_SEALED

    panel, d = load("equs")
    sigs = build_all(d, panel, only)
    results = {}
    for name, sig in sigs.items():
        if only and name != only:
            continue
        w = window(sig, phase)
        print(f"{name}: {len(w)} signals in {phase}", flush=True)
        results[name] = evaluate(name, w, panel, phase, years, gates, d)

    if only and phase == "development":
        w = window(sigs[only], phase)
        E.one_position_per_symbol(
            E.simulate(panel, w, COST_NORMAL, open_cost_bps=COST_OPEN_30)
        ).to_parquet(RES_DIR / f"trades-development-{only}.parquet", index=False)

    if only and phase == "sealed":
        w = window(sigs[only], phase)
        base = E.one_position_per_symbol(
            E.simulate(panel, w, COST_NORMAL, open_cost_bps=COST_OPEN_30))
        results[only]["independent_feed"] = independent_check(only, w, base)
        base.to_parquet(RES_DIR / f"trades-{phase}-{only}.parquet", index=False)

    out = RES_DIR / (f"{phase}-results.json" if not only else f"{phase}-results-{only}.json")
    out.write_text(json.dumps(results, indent=2, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
