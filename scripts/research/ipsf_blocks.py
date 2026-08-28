#!/usr/bin/env python3
"""Build the 30-minute block summary table from the minute bars.

One row per (date, symbol, block): the first traded price, the last traded
price, the block high and low, the dollar volume, and how many minutes carried
a trade.  This is the shared base for Method 1's predictor and, later, its
trades.

Writes <res>/blocks-<feed>.parquet.  No network. No spend.
"""

import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ipsf_common import BLOCK_STARTS, MIN_OPEN, RES_DIR  # noqa: E402


def build(feed: str) -> pd.DataFrame:
    src = RES_DIR / f"bars-{feed}-full.parquet"
    pf = pq.ParquetFile(src)
    out = []
    for i in range(pf.num_row_groups):
        c = pf.read_row_group(i).to_pandas()
        c["date"] = c["date"].astype(str)
        c["symbol"] = c["symbol"].astype(str)
        c["block"] = MIN_OPEN + ((c["minute"] - MIN_OPEN) // 30) * 30
        c = c.sort_values(["date", "symbol", "block", "minute"])
        g = c.groupby(["date", "symbol", "block"], sort=False)
        part = g.agg(
            first_minute=("minute", "first"),
            last_minute=("minute", "last"),
            first_px=("open", "first"),
            last_px=("close", "last"),
            high=("high", "max"),
            low=("low", "min"),
            volume=("volume", "sum"),
            n_bars=("minute", "size"),
        ).reset_index()
        part["dollar_volume"] = part["volume"] * (part["high"] + part["low"]) / 2.0
        out.append(part)
        del c, g, part
    df = pd.concat(out, ignore_index=True)
    # a row group boundary can split one (date, symbol, block); re-merge those
    dup = df.duplicated(["date", "symbol", "block"], keep=False)
    if dup.any():
        fixed = (
            df[dup]
            .sort_values(["date", "symbol", "block", "first_minute"])
            .groupby(["date", "symbol", "block"], as_index=False)
            .agg(
                first_minute=("first_minute", "first"),
                last_minute=("last_minute", "last"),
                first_px=("first_px", "first"),
                last_px=("last_px", "last"),
                high=("high", "max"),
                low=("low", "min"),
                volume=("volume", "sum"),
                n_bars=("n_bars", "sum"),
                dollar_volume=("dollar_volume", "sum"),
            )
        )
        df = pd.concat([df[~dup], fixed], ignore_index=True)
    df = df.sort_values(["date", "symbol", "block"], ignore_index=True)
    df["block"] = df["block"].astype("int16")
    return df


def main():
    for feed in ("equs", "pillar"):
        df = build(feed)
        dst = RES_DIR / f"blocks-{feed}.parquet"
        df.to_parquet(dst, index=False)
        print(f"{feed}: {len(df):,} block rows, {df.date.nunique()} dates, "
              f"{df.symbol.nunique()} symbols, blocks {sorted(df.block.unique())}")
        print(f"  wrote {dst}")
        del df


if __name__ == "__main__":
    main()
