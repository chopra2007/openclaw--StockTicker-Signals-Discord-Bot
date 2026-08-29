#!/usr/bin/env python3
"""Development-period input distributions for TODO #106.

These are the ONLY numbers allowed to set a threshold.  Nothing here touches a
return earned after an entry: every field is a property of the market state at
06:45 Pacific, the first legal decision minute.

Writes predictor-distributions.json.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdtm_common import DEV_LAST, MIN_OPEN, OR_KNOWN, RES_DIR  # noqa: E402

COL_OR = OR_KNOWN - MIN_OPEN          # 15 -> 06:45 Pacific


def decision_frame(feed="equs", col=COL_OR):
    """One row per company-day, holding every context field as it stood at the
    decision minute.  Development rows are flagged; no sealed row is used to
    choose anything."""
    sess = pd.read_parquet(RES_DIR / f"sessions-{feed}.parquet")
    z = np.load(RES_DIR / f"ctx-{feed}.npz")
    d = sess.copy()
    d["is_dev"] = d.date <= DEV_LAST
    d["relvol_or"] = z["relvol"][:, col]
    d["ret_or"] = z["ret"][:, col]
    d["mkt_or"] = z["mkt"][:, col]
    d["sec_or"] = z["sec"][:, col]
    d["peers"] = z["peers"][:, col]
    d["rs_mkt"] = d.ret_or - d.mkt_or
    d["rs_sec"] = d.ret_or - d.sec_or
    d["or_width"] = (d.or_high - d.or_low) / d.sess_open
    d["or_width_vs_atr"] = d.or_width / d.atr20
    d["gap"] = d.sess_open / d.prev_close - 1.0
    # where the opening range sits against yesterday's agreed value
    d["above_prev_vah"] = d.or_high > d.prev_vah
    d["below_prev_val"] = d.or_low < d.prev_val
    d["inside_prev_va"] = (~d.above_prev_vah) & (~d.below_prev_val)
    # room from the opening-range edge to the next opposing prior level
    d["room_up"] = (d.prev_high - d.or_high) / d.sess_open
    d["room_down"] = (d.or_low - d.prev_low) / d.sess_open
    # SEC Rule 201: if a stock trades 10% below its prior close, short selling
    # in it is restricted for the rest of that day AND the next.  A short taken
    # on such a day could not simply hit the bid.  Nothing here blocks the
    # trade; it is counted and reported, because the rule binds precisely on the
    # violent days a short-side method wants to trade.
    trig = (d.sess_low <= 0.90 * d.prev_close).fillna(False)
    d["rule201_triggered_today"] = trig.values
    d["rule201_restricted"] = (
        trig | d.groupby("symbol", sort=False)["rule201_triggered_today"].shift(1).fillna(False)
    ).values

    d["eligible"] = (
        np.isfinite(d.relvol_or) & np.isfinite(d.atr20) & np.isfinite(d.prev_vah)
        & np.isfinite(d.or_high) & np.isfinite(d.or_low) & (~d.is_split)
        # liveness must be judged on information available at 06:45.  Using the
        # whole session's bar count would be look-ahead: it would quietly drop
        # days that turned quiet in the afternoon, which nobody knew at 06:45.
        & (d.or_bars >= 12) & (d.or_width > 0) & (d.peers >= 2)
    )
    return d


def main():
    d = decision_frame()
    dev = d[d.is_dev & d.eligible]
    q = [1, 5, 10, 25, 50, 75, 80, 90, 95, 99]
    fields = ["relvol_or", "or_width", "or_width_vs_atr", "gap", "rs_mkt",
              "rs_sec", "room_up", "room_down", "atr20", "adv20"]
    out = {
        "feed": "equs",
        "decision_minute_pacific": "06:45",
        "development_last_date": DEV_LAST,
        "rows_total": int(len(d)),
        "rows_development": int((d.is_dev).sum()),
        "rows_development_eligible": int(len(dev)),
        "eligible_share_of_development": float(len(dev) / max((d.is_dev).sum(), 1)),
        "location_mix_development": {
            "opening_range_above_prior_value_area": float(dev.above_prev_vah.mean()),
            "opening_range_below_prior_value_area": float(dev.below_prev_val.mean()),
            "opening_range_inside_prior_value_area": float(dev.inside_prev_va.mean()),
        },
        "percentiles": {f: {str(k): float(np.nanpercentile(dev[f], k)) for k in q}
                        for f in fields},
        "note": ("Every figure is a property of the market state at 06:45 Pacific. "
                 "No return earned after an entry was used to produce any of them."),
    }
    p = RES_DIR / "predictor-distributions.json"
    p.write_text(json.dumps(out, indent=2))
    print(json.dumps(out["percentiles"]["relvol_or"], indent=1))
    print("eligible dev rows:", out["rows_development_eligible"])
    print("location mix:", out["location_mix_development"])
    print("wrote", p)


if __name__ == "__main__":
    main()
