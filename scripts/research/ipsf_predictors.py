#!/usr/bin/env python3
"""Predictor distributions for all three methods — development dates only.

Everything written here is knowable BEFORE a trade is entered.  There is no
post-entry return, profit, target, stop outcome, or method ranking in the
output.  The point is to choose selection thresholds honestly: from how the
predictors are shaped, never from what they earned.

Writes <res>/predictor-distributions.json and the Method 1 signal panel
<res>/panel-m1-dev.parquet (predictor columns only).
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ipsf_common import METHOD1_BLOCKS, RES_DIR, SEALED_DATES  # noqa: E402
from ipsf_daily import (  # noqa: E402
    as_of_liquid_daily,
    load_daily_panel,
    load_spy,
)

LOOKBACK = 20
MIN_BARS_IN_BLOCK = 20
MIN_STOCKS_IN_BLOCK = 20
SCALE_FLOOR = 0.0005  # 5 bps


def dev_dates(all_dates):
    return list(all_dates[: len(all_dates) - SEALED_DATES])


def method1_panel(blocks: pd.DataFrame, dates_keep: set) -> pd.DataFrame:
    """Signal-side panel for Method 1.  No entry, exit or profit columns."""
    b = blocks[blocks["block"].isin(METHOD1_BLOCKS)].copy()
    b = b[b["n_bars"] >= MIN_BARS_IN_BLOCK]
    b["blockret"] = b["last_px"] / b["first_px"] - 1.0
    b["range_frac"] = (b["high"] - b["low"]) / b["first_px"]

    # leave-one-stock-out cross-sectional mean of the same date-block
    g = b.groupby(["date", "block"], sort=False)["blockret"]
    n = g.transform("size")
    tot = g.transform("sum")
    b["n_in_block"] = n
    b = b[b["n_in_block"] >= MIN_STOCKS_IN_BLOCK].copy()
    n = b["n_in_block"]
    tot = b.groupby(["date", "block"], sort=False)["blockret"].transform("sum")
    b["mkt"] = (tot - b["blockret"]) / (n - 1)
    b["mar"] = b["blockret"] - b["mkt"]

    b = b.sort_values(["symbol", "block", "date"], ignore_index=True)
    grp_id = b.groupby(["symbol", "block"], sort=False).ngroup().to_numpy()

    mar = b["mar"].to_numpy(dtype=float)
    rng = b["range_frac"].to_numpy(dtype=float)
    dv = b["dollar_volume"].to_numpy(dtype=float)
    n = len(b)
    pred = np.full(n, np.nan)
    mad = np.full(n, np.nan)
    risk = np.full(n, np.nan)
    pdv = np.full(n, np.nan)

    # one pass per (symbol, block) series; every window is the PRIOR 20 rows
    starts = np.flatnonzero(np.r_[True, grp_id[1:] != grp_id[:-1]])
    ends = np.r_[starts[1:], n]
    for s0, s1 in zip(starts, ends):
        m = mar[s0:s1]
        r = rng[s0:s1]
        v = dv[s0:s1]
        for i in range(LOOKBACK, s1 - s0):
            w = m[i - LOOKBACK:i]
            med = np.median(w)
            pred[s0 + i] = med
            mad[s0 + i] = np.median(np.abs(w - med))
            risk[s0 + i] = np.median(r[i - LOOKBACK:i])
            pdv[s0 + i] = np.median(v[i - LOOKBACK:i])

    b["pred"] = pred
    b["mad"] = mad
    b["scale"] = np.maximum(1.4826 * mad, SCALE_FLOOR)
    b["score"] = b["pred"] / b["scale"]
    b["risk_unit"] = risk
    b["prior20_block_dollar_volume"] = pdv

    b = b[b["date"].isin(dates_keep)]
    keep = ["date", "symbol", "block", "n_in_block", "pred", "scale", "score",
            "mad", "risk_unit", "prior20_block_dollar_volume", "n_bars", "mkt"]
    return b[keep].dropna(subset=["pred", "score", "risk_unit"]).reset_index(drop=True)


def _rolling_mad(a: np.ndarray) -> np.ndarray:
    """Median absolute deviation of the PRIOR 20 values, aligned to each row."""
    out = np.full(len(a), np.nan)
    for i in range(LOOKBACK, len(a)):
        w = a[i - LOOKBACK:i]
        out[i] = np.median(np.abs(w - np.median(w)))
    return out


def q(s, ps=(0.5, 0.9, 0.95, 0.99, 0.995, 0.999)):
    return {f"p{int(p * 1000) / 10}": float(np.nanquantile(s, p)) for p in ps}


def main():
    RES_DIR.mkdir(parents=True, exist_ok=True)
    doc = {"note": "Development dates only. No post-entry return, profit, "
                   "target, stop outcome or method ranking appears here. "
                   "These distributions are what the selection thresholds "
                   "were chosen from."}

    # ---------------- Method 1 ----------------
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ipsf_daily import EARLY_CLOSE_DATES, as_of_liquid_minute  # noqa
    from ipsf_run import minute_sessions  # noqa

    blocks = pd.read_parquet(RES_DIR / "blocks-equs.parquet")
    all_dates = sorted(blocks["date"].unique())
    keep = set(d for d in dev_dates(all_dates) if d not in EARLY_CLOSE_DATES)
    m1 = method1_panel(blocks, keep)
    del blocks
    liq = as_of_liquid_minute(minute_sessions("equs"))
    liq = liq[liq["liquid"]]
    m1 = m1.merge(liq[["date", "symbol", "prior20_median_dollar_volume"]],
                  on=["date", "symbol"], how="inner")
    m1.to_parquet(RES_DIR / "panel-m1-dev.parquet", index=False)

    absscore = m1["score"].abs()
    per_day_counts = {}
    for t in (0.75, 1.0, 1.25, 1.5, 2.0):
        sel = m1[absscore >= t]
        top1 = sel.sort_values(["date", "block", "score"],
                               key=lambda c: c.abs() if c.name == "score" else c,
                               ascending=[True, True, False]
                               ).groupby(["date", "block"]).head(1)
        per_day = top1.groupby("date").size()
        capped = per_day.clip(upper=4)
        per_day_counts[str(t)] = {
            "eligible_rows": int(len(sel)),
            "one_per_block": int(len(top1)),
            "after_the_four_a_day_cap": int(capped.sum()),
            "dates_with_any": int(per_day.size),
            "mean_per_date": float(capped.reindex(sorted(keep)).fillna(0).mean()),
        }
    doc["method1"] = {
        "rows_after_as_of_liquidity": int(len(m1)),
        "dates": int(m1["date"].nunique()),
        "symbols": int(m1["symbol"].nunique()),
        "blocks": sorted(int(x) for x in m1["block"].unique()),
        "abs_score_quantiles": q(absscore),
        "pred_bps_quantiles": q(m1["pred"].abs() * 1e4),
        "scale_bps_quantiles": q(m1["scale"] * 1e4),
        "risk_unit_bps_quantiles": q(m1["risk_unit"] * 1e4),
        "stop_frac_bps_quantiles": q(
            np.clip(m1["risk_unit"] * 1.25, 0.0030, 0.0150) * 1e4),
        "candidates_by_threshold": per_day_counts,
        "chosen_threshold": 1.0,
        "why": "the frozen tail gives about two to four candidates a day across "
               "eleven blocks, which is what the four-a-day cap can absorb",
    }
    del m1

    # ---------------- Methods 2 and 3 ----------------
    daily = load_daily_panel()
    spy = load_spy()
    liq = as_of_liquid_daily(daily)
    d = daily[(daily["date"] >= "2015-01-02") & (daily["date"] <= "2025-11-28")]
    d = d[~d["date"].isin(EARLY_CLOSE_DATES)].copy()
    d = d.merge(spy.rename(columns={"ret": "spy_ret"})[["date", "spy_ret"]],
                on="date", how="left")
    d["x"] = d["ret"] - d["spy_ret"]
    d = d.merge(liq, on=["date", "symbol"], how="left")
    elig = d[d["liquid"].fillna(False)]

    n_dates = int(elig["date"].nunique())
    doc["method2"] = {
        "window": ["2015-01-02", "2025-11-28"],
        "rows": int(len(d)),
        "eligible_rows_after_as_of_liquidity": int(len(elig)),
        "dates": n_dates,
        "symbols": int(elig["symbol"].nunique()),
        "abs_market_adjusted_move_pct_quantiles": q(elig["x"].abs() * 100),
        "abnormal_volume_quantiles": {
            f"p{p}": float(np.nanquantile(elig["v"].dropna(), p / 100))
            for p in (1, 5, 25, 50, 75, 90, 95, 99)},
        "atr20_pct_quantiles": q(elig["atr20"].dropna() * 100),
        "stop_frac_pct_quantiles": q(
            np.clip(1.5 * elig["atr20"].dropna() * np.sqrt(5), 0.02, 0.08) * 100),
        "signals_by_rule": {},
    }
    for move in (0.02, 0.03, 0.04):
        for vt in (0.5, 1.0, 1.5):
            sel = elig[(elig["x"].abs() >= move) & (elig["v"] >= vt)]
            per_day = sel.groupby("date").size().clip(upper=4)
            doc["method2"]["signals_by_rule"][f"move>={move:.0%},vol>={vt}"] = {
                "signals": int(len(sel)),
                "after_the_four_a_day_cap": int(per_day.sum()),
                "dates_with_any": int(per_day.size),
                "distinct_stocks": int(sel["symbol"].nunique()),
                "shorts_allowed_share": float(
                    sel["shortable_proxy"].fillna(False).mean()) if len(sel) else None,
            }
    doc["method2"]["chosen"] = {"move_floor": 0.03, "volume_threshold": 1.0,
                                "direction": "against the move (reversal)"}

    # Method 3: how many pairs and cycles the frozen rule can even form
    import yaml
    groups = yaml.safe_load(open(
        "/home/openclaw/.openclaw/workspace/consensus_engine/data/"
        "peer_groups.yaml"))["groups"]
    have = set(elig["symbol"].unique())
    usable = {g: [s for s in v["members"] if s in have]
              for g, v in groups.items()}
    usable = {g: m for g, m in usable.items() if len(m) >= 2}
    doc["method3"] = {
        "window": ["2015-01-02", "2025-11-28"],
        "groups_with_two_or_more_eligible_members": len(usable),
        "distinct_stocks": len(set(s for m in usable.values() for s in m)),
        "candidate_pairs": int(sum(len(m) * (len(m) - 1) / 2
                                   for m in usable.values())),
        "members_by_group": {g: len(m) for g, m in sorted(usable.items())},
        "formation_and_trading_cycles_available": int(
            max(0, (n_dates - 120) // 60)),
        "pairs_kept_per_cycle": 10,
    }

    out = RES_DIR / "predictor-distributions.json"
    out.write_text(json.dumps(doc, indent=2, default=str) + "\n")
    print(json.dumps({k: v for k, v in doc.items() if k != "note"},
                     indent=2, default=str)[:6000])
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
