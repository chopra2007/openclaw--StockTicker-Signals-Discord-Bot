#!/usr/bin/env python3
"""TODO #103 - why the family failed. Development dates only; no new rule.

The six frozen rules all use a target and a stop, so their result mixes the
mechanism with the bracket shape. This strips the bracket away and asks the
plainest possible question: after an extreme move, which way does the price
actually go next, before any exit rule and before any cost?

This is a diagnostic for the rejection report. It is not a seventh test, it is
never run on the profit-sealed dates, and nothing may be promoted from it.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intraday_dislocation_common import RES_DIR  # noqa: E402

ENTRY, HOLD = 601, 30


def main():
    panel = pd.read_parquet(RES_DIR / "panel-dev.parquet")
    bars = pd.read_parquet(RES_DIR / "bars-equs.parquet")
    bars["symbol"] = bars.symbol.astype(str)
    bars = bars[bars.date.isin(set(panel.date.unique()))]

    o = {}
    for m in (ENTRY, ENTRY + HOLD):
        o[m] = (bars[bars.minute == m][["date", "symbol", "open", "volume"]]
                .rename(columns={"open": f"o{m}", "volume": f"v{m}"}))
    p = panel.merge(o[ENTRY], on=["date", "symbol"], how="left").merge(
        o[ENTRY + HOLD], on=["date", "symbol"], how="left")
    p = p[p.eligible & p[f"o{ENTRY}"].notna() & p[f"o{ENTRY+HOLD}"].notna()
          & (p[f"v{ENTRY}"] > 0) & (p[f"v{ENTRY+HOLD}"] > 0)].copy()
    p["fwd"] = np.log(p[f"o{ENTRY+HOLD}"] / p[f"o{ENTRY}"])

    # the same market removal, applied to the forward window
    fwd_mkt = p.groupby("date").fwd.transform(
        lambda s: (s.sum() - s) / max(len(s) - 1, 1))
    p["fwd_resid"] = p.fwd - p.beta * fwd_mkt

    def stats(sub, label):
        if sub.empty:
            return {"group": label, "n": 0}
        return {
            "group": label,
            "n": int(len(sub)),
            "raw_forward_move_bps": float(sub.fwd.mean() * 1e4),
            "market_removed_forward_move_bps": float(sub.fwd_resid.mean() * 1e4),
            "market_removed_median_bps": float(sub.fwd_resid.median() * 1e4),
            "std_bps": float(sub.fwd_resid.std() * 1e4),
            "standard_error_bps": float(sub.fwd_resid.std() / np.sqrt(len(sub)) * 1e4),
            "share_moving_further_pct": float(
                (np.sign(sub.fwd_resid) == np.sign(sub.dev)).mean() * 100),
        }

    top = p[p.dev.abs() >= p.extreme_bar].copy()
    top["rank"] = top.groupby(["date", top.dev > 0]).dev.transform(
        lambda s: s.abs().rank(ascending=False, method="first"))
    sel = top[top["rank"] <= 2]

    out = {
        "scope": "development dates only",
        "question": ("after an extreme move, what does the market-adjusted price "
                     "do over the next 30 minutes, with no target, no stop and "
                     "no cost?"),
        "groups": [
            stats(sel[sel.dev < 0], "selected extreme DOWN movers"),
            stats(sel[sel.dev > 0], "selected extreme UP movers"),
            stats(p[p.dev.abs() < p.extreme_bar], "all non-extreme stocks"),
            stats(p, "every eligible stock"),
        ],
        "cost_context_bps": {
            "normal_round_trip": 20.0,
            "median_feed_disagreement_on_a_30_minute_move": 9.95,
            "gross_edge_needed_to_be_distinguishable": 40.0,
        },
    }
    # is there any reversal at all in the dislocation itself?
    # One yardstick for both sides: the share of the original dislocation given
    # back over the next 30 minutes. Positive = it came back. Negative = it kept
    # going. Same sentence shape for the up side and the down side.
    def given_back(sub):
        if sub.empty:
            return float("nan")
        frac = -np.sign(sub.dev) * sub.fwd_resid / sub.dev.abs()
        return float(frac.median() * 100)

    out["percent_of_the_move_given_back_next_30_minutes"] = {
        "note": ("positive means the move partly came back; negative means it "
                 "kept going. Same formula for both sides."),
        "after_an_extreme_down_move": given_back(sel[sel.dev < 0]),
        "after_an_extreme_up_move": given_back(sel[sel.dev > 0]),
        "non_extreme_stocks": given_back(p[p.dev.abs() < p.extreme_bar]),
    }
    Path(RES_DIR / "why-it-failed.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
