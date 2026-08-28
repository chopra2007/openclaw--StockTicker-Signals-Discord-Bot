#!/usr/bin/env python3
"""TODO #103 step 2 - build the signal panel from the local minute bars.

One row per symbol-date with every field that exists BEFORE the entry price
prints. No outcome, no profit, no post-entry price is computed here.

The design is the one in design-reconciliation.md and frozen-policy.md.
Local parquet only. No network.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intraday_dislocation_common import RES_DIR  # noqa: E402

WIN_LO, WIN_HI = 570, 599       # 09:30-09:59 Eastern = 6:30-6:59 a.m. Pacific
ANCHOR_START = (570, 571, 572)  # first three window bars
ANCHOR_END = (597, 598, 599)    # last three window bars
MIN_WINDOW_BARS = 25            # of 30
TRAILING_WINDOW = 60
TRAILING_MIN = 40
RETURN_CAP = 0.03               # trailing window returns capped for the beta fit
ROBUST_K = 1.4826
SCALE_FLOOR = 0.0010            # 10 bps
EXTREME_FLOOR = 0.0050          # 50 bps
LIQ_LOOKBACK = 20
MIN_PRICE = 10.0
MIN_PRIOR_DOLLAR_VOLUME = 20e6  # on this feed; ~$100m consolidated
MIN_WINDOW_DOLLAR_VOLUME = 1e6   # ~$5m consolidated at this feed's ~20% coverage
MIN_OTHER_ELIGIBLE = 25   # of a 60-name universe; see design-reconciliation.md
ENTRY_DIRECT = 601              # 10:01 Eastern = 7:01 a.m. Pacific
HOLD_PRIMARY = 30
DEV_LAST = "2025-11-28"


def robust_scale(x):
    med = np.nanmedian(x)
    return ROBUST_K * np.nanmedian(np.abs(x - med))


def build(bars_path, dev_only=True):
    b = pd.read_parquet(bars_path)
    b["symbol"] = b.symbol.astype(str)
    b = b.drop_duplicates(["date", "symbol", "minute"], keep="first")
    if dev_only:
        b = b[b.date <= DEV_LAST]

    w = b[(b.minute >= WIN_LO) & (b.minute <= WIN_HI)].copy()
    w["dollar"] = w.close * w.volume
    g = w.groupby(["date", "symbol"], observed=True)
    p = g.agg(bars=("minute", "size"),
              win_high=("high", "max"),
              win_low=("low", "min"),
              win_dollar_volume=("dollar", "sum")).reset_index()

    # the two three-bar price anchors
    piv = w.pivot_table(index=["date", "symbol"], columns="minute",
                        values="close", observed=True)
    for m in set(ANCHOR_START) | set(ANCHOR_END):
        if m not in piv.columns:
            piv[m] = np.nan
    anchors = pd.DataFrame({
        "p0": piv[list(ANCHOR_START)].median(axis=1, skipna=False),
        "p1": piv[list(ANCHOR_END)].median(axis=1, skipna=False),
    }).reset_index()
    p = p.merge(anchors, on=["date", "symbol"], how="left")

    # last completed minute before entry, for the capacity cap
    pre = b[b.minute == ENTRY_DIRECT - 1][["date", "symbol", "close", "volume"]].copy()
    pre["pre_entry_minute_dollar_volume"] = pre.close * pre.volume
    p = p.merge(pre[["date", "symbol", "pre_entry_minute_dollar_volume"]],
                on=["date", "symbol"], how="left")

    # per-session liquidity, from completed prior sessions only
    daily = pd.read_parquet(RES_DIR / "daily-equs.parquet").sort_values(["symbol", "date"])
    daily["prior20_dollar_volume"] = (
        daily.groupby("symbol").session_dollar_volume
        .transform(lambda s: s.shift(1).rolling(LIQ_LOOKBACK, min_periods=LIQ_LOOKBACK).median()))
    p = p.merge(daily[["date", "symbol", "prior20_dollar_volume"]],
                on=["date", "symbol"], how="left")
    p = p.sort_values(["symbol", "date"]).reset_index(drop=True)
    def prior_valid_median(s):
        v = s.dropna()
        if v.empty:
            return pd.Series(np.nan, index=s.index)
        return (v.shift(1).rolling(LIQ_LOOKBACK, min_periods=LIQ_LOOKBACK)
                .median().reindex(s.index))

    p["prior20_median_price"] = p.groupby("symbol").p1.transform(prior_valid_median)
    p["prior20_dollar_volume"] = p.groupby("symbol").prior20_dollar_volume.transform(
        lambda s: s.ffill(limit=5))

    p["window_ok"] = (
        (p.bars >= MIN_WINDOW_BARS) & p.p0.notna() & p.p1.notna()
        & (p.p0 > 0) & (p.p1 > 0) & (p.win_high > p.win_low)
    )
    p["r"] = np.where(p.window_ok, np.log(p.p1 / p.p0), np.nan)

    p["liquid"] = (
        (p.prior20_median_price >= MIN_PRICE)
        & (p.prior20_dollar_volume >= MIN_PRIOR_DOLLAR_VOLUME)
        & (p.win_dollar_volume >= MIN_WINDOW_DOLLAR_VOLUME)
    )
    p["basket_member"] = p.window_ok & p.liquid

    # leave-one-out market move: the MEDIAN window return of every OTHER member
    def loo_median(day):
        vals = day.r.to_numpy()
        n = len(vals)
        out = np.full(n, np.nan)
        for i in range(n):
            other = np.delete(vals, i)
            out[i] = np.median(other) if len(other) else np.nan
        return pd.Series(out, index=day.index)

    p["mkt_r"] = np.nan
    members = p[p.basket_member]
    breadth = members.groupby("date").size().rename("basket_n")
    for date, day in members.groupby("date"):
        p.loc[day.index, "mkt_r"] = loo_median(day).to_numpy()
    p = p.merge(breadth, on="date", how="left")
    p["basket_n"] = p.basket_n.fillna(0)

    # trailing straight-line fit of the stock's window return on its market move.
    # Every trailing statistic uses the last N VALID prior sessions for that
    # stock, never the last N calendar rows, so a day the stock was not in the
    # basket cannot silently shorten the history.
    def rolling_valid(series, fn, window=TRAILING_WINDOW, minp=TRAILING_MIN):
        valid = series.dropna()
        if valid.empty:
            return pd.Series(np.nan, index=series.index)
        out = fn(valid.rolling(window, min_periods=minp)).shift(1)
        return out.reindex(series.index)

    def per_symbol(x):
        x = x.sort_values("date").copy()
        ok = x.basket_member & x.r.notna() & x.mkt_r.notna()
        r = x.r.where(ok).clip(-RETURN_CAP, RETURN_CAP)
        m = x.mkt_r.where(ok).clip(-RETURN_CAP, RETURN_CAP)
        pair = pd.concat([r.rename("r"), m.rename("m")], axis=1).dropna()
        if len(pair) >= TRAILING_MIN:
            roll = dict(window=TRAILING_WINDOW, min_periods=TRAILING_MIN)
            rr = pair.r.rolling(**roll).mean().shift(1)
            mm = pair.m.rolling(**roll).mean().shift(1)
            cov = pair.r.rolling(**roll).cov(pair.m).shift(1)
            var = pair.m.rolling(**roll).var().shift(1)
            beta = (cov / var).clip(-1.0, 3.0)
            x["beta"] = beta.reindex(x.index)
            x["alpha"] = (rr - beta * mm).reindex(x.index)
        else:
            x["beta"] = np.nan
            x["alpha"] = np.nan
        x["resid"] = x.r - (x.alpha + x.beta * x.mkt_r)
        res = x.resid.where(ok)
        x["resid_centre"] = rolling_valid(res, lambda rl: rl.median())
        x["resid_scale"] = rolling_valid(res, lambda rl: rl.apply(robust_scale, raw=True))
        x["resid_scale"] = x.resid_scale.clip(lower=SCALE_FLOOR)
        # one risk unit: the stock's own normal move over the frozen holding
        # window, measured at the same clock minutes on prior sessions
        x["risk_unit"] = rolling_valid(x.hold_ret,
                                       lambda rl: rl.apply(robust_scale, raw=True))
        return x

    # trailing 30-minute open-to-open move at the frozen clock minutes
    o_entry = b[b.minute == ENTRY_DIRECT][["date", "symbol", "open"]].rename(
        columns={"open": "o_entry"})
    o_exit = b[b.minute == ENTRY_DIRECT + HOLD_PRIMARY][["date", "symbol", "open"]].rename(
        columns={"open": "o_exit"})
    p = p.merge(o_entry, on=["date", "symbol"], how="left").merge(
        o_exit, on=["date", "symbol"], how="left")
    p["hold_ret"] = np.log(p.o_exit / p.o_entry)

    p = p.groupby("symbol", group_keys=False)[p.columns.tolist()].apply(per_symbol)
    p["risk_unit"] = p.risk_unit.clip(lower=0.0035)
    p["dev"] = p.resid - p.resid_centre
    p["extreme_bar"] = np.maximum(EXTREME_FLOOR, 2.0 * p.resid_scale)
    p["z"] = p.dev / p.resid_scale

    p["eligible"] = (
        p.basket_member & p.beta.notna() & p.resid_scale.notna()
        & p.resid_centre.notna() & p.risk_unit.notna()
        & (p.basket_n - 1 >= MIN_OTHER_ELIGIBLE)
        & p.pre_entry_minute_dollar_volume.notna()
        & (p.pre_entry_minute_dollar_volume > 0)
    )
    p["extreme_down"] = p.eligible & (p.dev <= -p.extreme_bar)
    p["extreme_up"] = p.eligible & (p.dev >= p.extreme_bar)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-dates", action="store_true",
                    help="include the profit-sealed dates (authorised runs only)")
    ap.add_argument("--bars", default=str(RES_DIR / "bars-equs.parquet"))
    ap.add_argument("--out", default=str(RES_DIR / "panel-dev.parquet"))
    a = ap.parse_args()

    p = build(a.bars, dev_only=not a.all_dates)
    p.to_parquet(a.out, index=False)
    el = p[p.eligible]
    print(json.dumps({
        "rows": int(len(p)),
        "eligible_rows": int(len(el)),
        "dates": int(p.date.nunique()),
        "eligible_dates": int(el.date.nunique()),
        "symbols": int(el.symbol.nunique()),
        "extreme_down": int(p.extreme_down.sum()),
        "extreme_up": int(p.extreme_up.sum()),
        "mean_extreme_down_per_date": float(p.extreme_down.sum() / el.date.nunique()),
        "mean_extreme_up_per_date": float(p.extreme_up.sum() / el.date.nunique()),
        "median_risk_unit_bps": float(el.risk_unit.median() * 1e4),
        "first_date": p.date.min(),
        "last_date": p.date.max(),
    }, indent=2))


if __name__ == "__main__":
    main()
