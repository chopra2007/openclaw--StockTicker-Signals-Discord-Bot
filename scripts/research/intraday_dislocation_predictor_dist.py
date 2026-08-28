#!/usr/bin/env python3
"""TODO #103 step 3 - the predictor distribution, development dates only.

Everything here is known at 10:00 a.m. Eastern (7:00 a.m. Pacific) on the signal
date. There is no post-entry price, no return after entry, no profit, no target
hit and no strategy ranking in this file. It exists so the "extreme" threshold
can be justified from the shape of the predictor rather than from what made
money.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intraday_dislocation_common import RES_DIR  # noqa: E402


def main():
    p = pd.read_parquet(RES_DIR / "panel-dev.parquet")
    assert p.date.max() <= "2025-11-28", "profit-sealed dates must not be present"
    el = p[p.eligible].copy()

    qs = [0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999]
    out = {
        "scope": "development dates only, 2023-03-28 to 2025-11-28",
        "contains_no_post_entry_information": True,
        "rows": int(len(el)),
        "dates": int(el.date.nunique()),
        "symbols": int(el.symbol.nunique()),
        "window_return_bps": {str(q): float(el.r.quantile(q) * 1e4) for q in qs},
        "market_window_return_bps": {
            str(q): float(el.groupby("date").mkt_r.first().quantile(q) * 1e4) for q in qs},
        "residual_bps": {str(q): float(el.resid.quantile(q) * 1e4) for q in qs},
        "residual_minus_centre_bps": {str(q): float(el.dev.quantile(q) * 1e4) for q in qs},
        "extreme_bar_bps": {str(q): float(el.extreme_bar.quantile(q) * 1e4) for q in qs},
        "risk_unit_bps": {str(q): float(el.risk_unit.quantile(q) * 1e4) for q in qs},
        "alpha_bps": {str(q): float(el.alpha.quantile(q) * 1e4) for q in qs},
        "basket_names_per_date": {str(q): float(el.groupby("date").basket_n.first().quantile(q)) for q in qs},
        "beta": {str(q): float(el.beta.quantile(q)) for q in qs},
        "z": {str(q): float(el.z.quantile(q)) for q in qs},
        "abs_z": {str(q): float(el.z.abs().quantile(q)) for q in qs},
        "trailing_robust_resid_scale_bps": {
            str(q): float(el.resid_scale.quantile(q) * 1e4) for q in qs},
        "trailing_resid_centre_bps": {
            str(q): float(el.resid_centre.quantile(q) * 1e4) for q in qs},
        "window_dollar_volume_usd": {
            str(q): float(el.win_dollar_volume.quantile(q)) for q in qs},
        "prior20_session_dollar_volume_usd": {
            str(q): float(el.prior20_dollar_volume.quantile(q)) for q in qs},
        "pre_entry_minute_dollar_volume_usd": {
            str(q): float(el.pre_entry_minute_dollar_volume.quantile(q)) for q in qs},
        "eligible_names_per_date": {
            str(q): float(el.groupby("date").size().quantile(q)) for q in qs},
    }

    # how often the frozen extreme bar fires, and how many names per side per day
    fires = {}
    for thr in ("frozen",):
        hit = el[el.dev.abs() >= el.extreme_bar]
        per_day_dn = hit[hit.dev < 0].groupby("date").size()
        per_day_up = hit[hit.dev > 0].groupby("date").size()
        fires[str(thr)] = {
            "share_of_rows_pct": float(len(hit) / len(el) * 100),
            "dates_with_at_least_one": int(hit.date.nunique()),
            "mean_down_names_per_date": float(per_day_dn.reindex(
                el.date.unique(), fill_value=0).mean()),
            "mean_up_names_per_date": float(per_day_up.reindex(
                el.date.unique(), fill_value=0).mean()),
            "median_abs_residual_of_hits_bps": float(hit.dev.abs().median() * 1e4),
        }
    out["threshold_firing_rates"] = fires

    # with the "at most two per side per day" cap applied
    cap = {}
    for thr in ("frozen",):
        hit = el[el.dev.abs() >= el.extreme_bar].copy()
        hit["rank_side"] = hit.groupby(["date", hit.dev > 0]).dev.transform(
            lambda s: s.abs().rank(ascending=False, method="first"))
        sel = hit[hit.rank_side <= 2]
        cap[str(thr)] = {
            "selected_rows": int(len(sel)),
            "dates": int(sel.date.nunique()),
            "symbols": int(sel.symbol.nunique()),
            "mean_selected_per_date": float(len(sel) / el.date.nunique()),
            "down_rows": int((sel.dev < 0).sum()),
            "up_rows": int((sel.dev > 0).sum()),
            "median_abs_residual_bps": float(sel.dev.abs().median() * 1e4),
            "median_risk_unit_bps": float(sel.risk_unit.median() * 1e4),
        }
    out["with_two_per_side_cap"] = cap

    path = RES_DIR / "predictor-distribution.json"
    json.dump(out, open(path, "w"), indent=2)
    print(json.dumps({k: out[k] for k in
                      ("rows", "dates", "symbols", "abs_z", "threshold_firing_rates",
                       "with_two_per_side_cap", "risk_unit_bps", "extreme_bar_bps")},
                     indent=2))


if __name__ == "__main__":
    main()
