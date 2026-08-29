#!/usr/bin/env python3
"""Extract EVERY minute bar (extended hours included) for both local feeds.

TODO #105. The TODO #104 extraction kept only 09:30-15:59 Eastern; the
overnight-range and prior-session methods need the pre- and post-market
minutes too, so this re-reads the raw DBN files with no minute filter.

Writes into .omc/research/professional-day-trader-methods/:
  bars-equs-allmin.parquet    one row per symbol-date-minute, EQUS.MINI
  bars-pillar-allmin.parquet  same for XNYS.PILLAR (independent check)

`date`/`minute` are Eastern session date and Eastern minute-of-day, matching
the TODO #103/#104 convention.  No network.  No spend.
"""

import sys
from array import array
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intraday_dislocation_common import (  # noqa: E402
    EQUS_BRK_FILE,
    EQUS_FILE,
    PILLAR_FILE,
    PRICE_SCALE,
    EtClock,
    canonical,
    day_to_date_str,
    open_store,
    symbol_map,
)

RES_DIR = Path(__file__).resolve().parents[2] / ".omc/research/professional-day-trader-methods"


def scan(paths, label):
    clock = EtClock()
    cols = {k: array("q") for k in ("open", "high", "low", "close", "volume")}
    a_date, a_sym, a_min = array("i"), array("i"), array("h")
    sym_ids = {}
    scanned = 0

    for path in paths:
        inst2sym = {i: canonical(s) for i, s in symbol_map(path).items()}
        for rec in open_store(path):
            scanned += 1
            day, sec = clock.date_and_sec(rec.ts_event)
            sym = inst2sym.get(rec.instrument_id)
            if sym is None:
                continue
            a_date.append(int(day))
            a_sym.append(sym_ids.setdefault(sym, len(sym_ids)))
            a_min.append(int(sec) // 60)
            cols["open"].append(rec.open)
            cols["high"].append(rec.high)
            cols["low"].append(rec.low)
            cols["close"].append(rec.close)
            cols["volume"].append(rec.volume)
        print(f"  {label}: {path.name} done, scanned={scanned:,}", flush=True)

    id2sym = {v: k for k, v in sym_ids.items()}
    days = np.frombuffer(a_date, dtype=np.int32)
    day_str = {int(d): day_to_date_str(int(d)) for d in np.unique(days)}
    df = pd.DataFrame(
        {
            "date": pd.Categorical([day_str[int(d)] for d in days]),
            "symbol": pd.Categorical(
                [id2sym[i] for i in np.frombuffer(a_sym, dtype=np.int32)]
            ),
            "minute": np.frombuffer(a_min, dtype=np.int16),
            "open": np.frombuffer(cols["open"], dtype=np.int64) * PRICE_SCALE,
            "high": np.frombuffer(cols["high"], dtype=np.int64) * PRICE_SCALE,
            "low": np.frombuffer(cols["low"], dtype=np.int64) * PRICE_SCALE,
            "close": np.frombuffer(cols["close"], dtype=np.int64) * PRICE_SCALE,
            "volume": np.frombuffer(cols["volume"], dtype=np.int64),
        }
    )
    df = df.sort_values(["date", "symbol", "minute"], ignore_index=True)
    print(f"  {label}: kept {len(df):,} bars, {df.symbol.nunique()} symbols", flush=True)
    return df


def main():
    RES_DIR.mkdir(parents=True, exist_ok=True)
    equs = scan([EQUS_FILE, EQUS_BRK_FILE], "equs")
    equs.to_parquet(RES_DIR / "bars-equs-allmin.parquet", index=False)
    del equs
    pillar = scan([PILLAR_FILE], "pillar")
    pillar.to_parquet(RES_DIR / "bars-pillar-allmin.parquet", index=False)
    print("done", flush=True)


if __name__ == "__main__":
    main()
