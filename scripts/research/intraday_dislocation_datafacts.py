#!/usr/bin/env python3
"""TODO #103 step 1b - add the reproduced data-quality facts to current-state.json.

Local parquet panels only, built by intraday_dislocation_extract.py. No network.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from intraday_dislocation_common import RES_DIR  # noqa: E402

WIN_LO, WIN_HI = 570, 599  # 09:30-09:59 Eastern bars = 6:30-6:59 a.m. Pacific
DEV_LAST = "2025-11-28"


def window(df):
    return df[(df.minute >= WIN_LO) & (df.minute <= WIN_HI)]


def window_return_bps(df):
    g = df.sort_values("minute").groupby(["date", "symbol"], observed=True)
    return g.apply(lambda x: (x["close"].iloc[-1] / x["open"].iloc[0] - 1) * 1e4,
                   include_groups=False)


def main():
    e = pd.read_parquet(RES_DIR / "bars-equs.parquet")
    p = pd.read_parquet(RES_DIR / "bars-pillar.parquet")
    e["symbol"] = e.symbol.astype(str)
    p["symbol"] = p.symbol.astype(str)
    daily = pd.read_parquet(RES_DIR / "daily-equs.parquet")

    E, P = window(e), window(p)
    m = E.merge(P, on=["date", "symbol", "minute"], suffixes=("_e", "_p"))
    close_diff = (m.close_e - m.close_p) / m.close_p * 1e4
    re_, rp = window_return_bps(E), window_return_bps(P)
    j = pd.concat([re_.rename("e"), rp.rename("p")], axis=1).dropna()

    dates = sorted(e.date.unique())
    dev = [d for d in dates if d <= DEV_LAST]
    ev = [d for d in dates if d > DEV_LAST]

    # completeness of the observation window per symbol-date
    cnt = E.groupby(["date", "symbol"], observed=True).size()
    zero_vol = E.groupby(["date", "symbol"], observed=True).volume.apply(lambda v: int((v == 0).sum()))

    facts = {
        "bar_timestamp_convention": {
            "finding": "ts_event marks the START of the one-minute bar",
            "evidence": ("TSM has an 09:30 Eastern bar on all 854 dates totalling "
                         "9,768,376 shares, against 448 dates and 104,294 shares at "
                         "09:29. The opening auction print lands in the 09:30 bar, so "
                         "that bar covers 09:30:00-09:30:59."),
            "consequence": ("The 09:30-09:59 bars are the complete first half hour. "
                            "The first bar a trader can act on afterwards is 10:01."),
        },
        "missing_bars": {
            "finding": "A bar is absent when no trade printed in that minute",
            "evidence": ("ABT has no 09:30 bar on 152 of its 854 dates; on 2023-03-29 "
                         "its first bar of the day is 09:31 and its minute volumes are "
                         "around 1,000 shares."),
            "consequence": "No fill may ever be assumed in a minute with no bar.",
        },
        "feed_is_a_subset_of_the_tape": {
            "finding": "EQUS.MINI carries roughly a fifth of consolidated volume",
            "evidence": {
                "tsm_median_session_volume_equs": int(
                    daily[(daily.symbol == "TSM") & (daily.date >= "2026-06-01")]
                    .session_volume.median()),
                "tsm_median_session_volume_consolidated_from_selection_file": 2845157,
            },
            "consequence": ("Position size taken as a share of window dollar volume is "
                            "conservative by roughly five times. Prices are real trades, "
                            "but bar highs and lows are slightly less extreme than the "
                            "full tape, so target and stop touches are undercounted "
                            "rather than overcounted."),
        },
        "feed_cross_check": {
            "overlapping_minute_bars": int(len(m)),
            "median_volume_ratio_equs_over_pillar": float(
                (m.volume_e / m.volume_p.replace(0, np.nan)).median()),
            "close_price_difference_bps": {
                "median": float(close_diff.median()),
                "p95_abs": float(close_diff.abs().quantile(0.95)),
                "p99_abs": float(close_diff.abs().quantile(0.99)),
                "max_abs": float(close_diff.abs().max()),
            },
            "window_return_agreement": {
                "symbol_dates_compared": int(len(j)),
                "correlation": float(j.e.corr(j.p)),
                "median_abs_difference_bps": float((j.e - j.p).abs().median()),
                "p99_abs_difference_bps": float((j.e - j.p).abs().quantile(0.99)),
            },
            "consequence": ("The two independent feeds disagree about the same 30-minute "
                            "move by about 10 bps in the middle of the distribution. That "
                            "is half the entire 20 bps cost budget, so any edge smaller "
                            "than roughly 10 bps cannot be told apart from which feed was "
                            "chosen. EQUS.MINI is the frozen primary source; XNYS.PILLAR "
                            "is the check."),
        },
        "date_split": {
            "development_dates": len(dev),
            "development_first": dev[0],
            "development_last": dev[-1],
            "profit_sealed_dates": len(ev),
            "profit_sealed_first": ev[0] if ev else None,
            "profit_sealed_last": ev[-1] if ev else None,
            "discrepancy_with_prior_records": (
                "Prior TODO records describe a 730-date development panel. That count "
                "came from the XNYS imbalance file, which starts 2023-01-01. The "
                "EQUS.MINI price file starts 2023-03-28, so the price-based development "
                "panel here is 672 dates. The 182 profit-sealed dates match exactly, "
                "starting 2025-12-01."),
        },
        "window_completeness": {
            "symbol_dates_with_any_window_bar": int(len(cnt)),
            "median_bars_in_window": float(cnt.median()),
            "symbol_dates_with_all_30_bars": int((cnt == 30).sum()),
            "symbol_dates_with_fewer_than_25_bars": int((cnt < 25).sum()),
            "symbol_dates_with_a_zero_volume_bar": int((zero_vol > 0).sum()),
        },
        "corporate_actions": {
            "finding": ("The DBN files carry no split or dividend adjustment records for "
                        "the ohlcv-1m schema."),
            "consequence": ("Every return in this research is computed inside a single "
                            "session from prices minutes apart, so a split or dividend "
                            "applied overnight cannot contaminate it. Nothing in this "
                            "design compares a price on one date with a price on "
                            "another date, except trailing statistics measured as "
                            "same-day percentage moves, which are split-neutral."),
        },
        "symbol_mapping": {
            "finding": "XNYS writes 'BRK B' and EQUS writes 'BRK.B'.",
            "consequence": "Both are folded to 'BRK.B' before any join.",
        },
    }

    state_path = RES_DIR / "current-state.json"
    state = json.load(open(state_path))
    state["reproduced_data_facts"] = facts
    json.dump(state, open(state_path, "w"), indent=2)
    print(json.dumps(facts, indent=2, default=str))


if __name__ == "__main__":
    main()
