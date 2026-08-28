#!/usr/bin/env python3
"""TODO #103 step 1 - reproduce the local data facts and build the bar panel.

Reads the local DBN files directly. Writes:
  - <res>/bars-equs.parquet         one row per symbol-date-minute (kept minutes)
  - <res>/daily-equs.parquet        one row per symbol-date (whole-session volume)
  - <res>/current-state.json        reproduced file, symbol and coverage facts

No network. No API key. No spend.
"""

import hashlib
import json
import sys
from array import array
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intraday_dislocation_common import (  # noqa: E402
    EQUS_BRK_FILE,
    EQUS_FILE,
    KEEP_MINUTES,
    MIN_OPEN,
    MIN_RTH_LAST,
    PILLAR_FILE,
    PRICE_SCALE,
    RES_DIR,
    EtClock,
    canonical,
    day_to_date_str,
    open_store,
    symbol_map,
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(paths, keep_minutes, label):
    """One streaming pass per file. Keeps chosen minutes; totals whole-session volume."""
    clock = EtClock()
    cols = {k: array("q") for k in ("open", "high", "low", "close", "volume")}
    a_date, a_sym, a_min = array("i"), array("i"), array("h")
    sym_ids = {}
    daily = defaultdict(lambda: [0, 0.0, 0])  # volume, dollar volume, bar count
    scanned = 0
    per_file = {}

    for path in paths:
        inst2sym = {i: canonical(s) for i, s in symbol_map(path).items()}
        n = 0
        for rec in open_store(path):
            n += 1
            day, sec = clock.date_and_sec(rec.ts_event)
            minute = int(sec) // 60
            sym = inst2sym.get(rec.instrument_id)
            if sym is None:
                continue
            sid = sym_ids.setdefault(sym, len(sym_ids))
            if MIN_OPEN <= minute <= MIN_RTH_LAST:
                d = daily[(int(day), sid)]
                d[0] += rec.volume
                d[1] += rec.close * PRICE_SCALE * rec.volume
                d[2] += 1
            if minute not in keep_minutes:
                continue
            a_date.append(int(day))
            a_sym.append(sid)
            a_min.append(minute)
            cols["open"].append(rec.open)
            cols["high"].append(rec.high)
            cols["low"].append(rec.low)
            cols["close"].append(rec.close)
            cols["volume"].append(rec.volume)
            if n % 10_000_000 == 0:
                print(f"  {label} {path.name} {n:,}...", file=sys.stderr, flush=True)
        per_file[path.name] = n
        scanned += n
        print(f"  {label} {path.name}: {n:,} records", file=sys.stderr, flush=True)

    id2sym = {v: k for k, v in sym_ids.items()}
    names = [id2sym[i] for i in range(len(id2sym))]
    bars = pd.DataFrame({
        "date": [day_to_date_str(d) for d in a_date],
        "symbol": pd.Categorical.from_codes(np.frombuffer(a_sym, dtype=np.int32), names),
        "minute": np.frombuffer(a_min, dtype=np.int16),
        "open": np.frombuffer(cols["open"], dtype=np.int64) * PRICE_SCALE,
        "high": np.frombuffer(cols["high"], dtype=np.int64) * PRICE_SCALE,
        "low": np.frombuffer(cols["low"], dtype=np.int64) * PRICE_SCALE,
        "close": np.frombuffer(cols["close"], dtype=np.int64) * PRICE_SCALE,
        "volume": np.frombuffer(cols["volume"], dtype=np.int64),
    })
    drows = [
        {"date": day_to_date_str(d), "symbol": id2sym[s],
         "session_volume": v, "session_dollar_volume": dv, "session_bars": nb}
        for (d, s), (v, dv, nb) in daily.items()
    ]
    dfd = pd.DataFrame(drows).sort_values(["date", "symbol"]).reset_index(drop=True)
    return bars, dfd, {"records_scanned": scanned, "per_file": per_file,
                       "bars_kept": int(len(bars)), "symbols": sorted(names)}


def main():
    RES_DIR.mkdir(parents=True, exist_ok=True)
    do_pillar = "--with-pillar" in sys.argv

    files = {}
    for p in (EQUS_FILE, EQUS_BRK_FILE, PILLAR_FILE):
        files[p.name] = {"path": str(p), "size_bytes": p.stat().st_size,
                         "sha256": sha256_of(p)}
        print(f"  hashed {p.name}", file=sys.stderr, flush=True)

    bars, daily, meta = scan([EQUS_FILE, EQUS_BRK_FILE], KEEP_MINUTES, "equs")
    bars.to_parquet(RES_DIR / "bars-equs.parquet", index=False)
    daily.to_parquet(RES_DIR / "daily-equs.parquet", index=False)

    dates = sorted(bars["date"].unique())
    # coverage: how many of the 60 names have an opening bar on each date
    opens = bars[bars["minute"] == MIN_OPEN]
    per_date = opens.groupby("date", observed=True)["symbol"].nunique()
    per_symbol = opens.groupby("symbol", observed=True)["date"].nunique()

    state = {
        "created_utc": pd.Timestamp.utcnow().isoformat(),
        "purpose": "TODO #103 intraday dislocation - reproduced data facts",
        "network_used": False,
        "new_data_spend_usd": 0.0,
        "files": files,
        "equs": meta,
        "date_coverage": {
            "n_dates_with_open_bar": int(len(per_date)),
            "first_date": dates[0],
            "last_date": dates[-1],
            "median_symbols_per_date": float(per_date.median()),
            "min_symbols_per_date": int(per_date.min()),
            "dates_with_fewer_than_50_symbols": int((per_date < 50).sum()),
        },
        "symbol_coverage": {
            "n_symbols": int(per_symbol.shape[0]),
            "min_dates_per_symbol": int(per_symbol.min()),
            "max_dates_per_symbol": int(per_symbol.max()),
            "symbols_missing_dates": {
                s: int(int(len(per_date)) - int(v))
                for s, v in per_symbol.items() if int(v) < int(len(per_date))
            },
        },
        "market_proxy": {
            "spy_present": bool("SPY" in meta["symbols"]),
            "sector_etf_present": False,
            "note": ("No index or sector ETF exists in these files. The market "
                     "move is therefore the equal-weighted average of the same "
                     "60 names over the same minutes, which uses no future "
                     "information."),
        },
    }
    if do_pillar:
        pbars, _pdaily, pmeta = scan([PILLAR_FILE], KEEP_MINUTES, "pillar")
        pbars.to_parquet(RES_DIR / "bars-pillar.parquet", index=False)
        state["pillar"] = pmeta

    with open(RES_DIR / "current-state.json", "w") as fh:
        json.dump(state, fh, indent=2)
    print(json.dumps({k: state[k] for k in
                      ("date_coverage", "symbol_coverage", "market_proxy")}, indent=2))


if __name__ == "__main__":
    main()
