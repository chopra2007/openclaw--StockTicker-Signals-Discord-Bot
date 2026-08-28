#!/usr/bin/env python3
"""Inventory and fingerprint every data source used by TODO #104.

Writes <res>/current-state.json.  No network. No spend.
"""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from intraday_dislocation_common import (  # noqa: E402
    DATA_DIR,
    EQUS_BRK_FILE,
    EQUS_FILE,
    PILLAR_FILE,
)
from ipsf_common import MIN_OPEN, MIN_RTH_LAST, RES_DIR, SEALED_DATES  # noqa: E402

DAILY_DIR = Path("/home/openclaw/.openclaw/workspace/data/mmhl_daily")
UNIVERSE_FILE = DATA_DIR / "universe-selection" / (
    "xnys-pillar_ohlcv-1d_ALL-SYMBOLS_2023-01-01_2026-08-22.dbn.zst"
)


def sha256_of(path: Path, cap_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
            read += len(chunk)
            if cap_bytes and read >= cap_bytes:
                break
    return h.hexdigest()


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd="/home/openclaw/.openclaw/workspace",
    ).stdout.strip()


def minute_facts(path: Path, label: str) -> dict:
    """Streams one row group at a time; the whole panel never sits in memory."""
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(path)
    parts = []
    rows = 0
    zero_vol = 0
    mn, mx = 10 ** 9, -10 ** 9
    for i in range(pf.num_row_groups):
        t = pf.read_row_group(i, columns=["date", "symbol", "minute", "volume"])
        c = t.to_pandas()
        rows += len(c)
        zero_vol += int((c["volume"] <= 0).sum())
        mn = min(mn, int(c["minute"].min()))
        mx = max(mx, int(c["minute"].max()))
        parts.append(c.groupby([c["date"].astype(str), c["symbol"].astype(str)],
                               observed=True).size().rename("n"))
        del t, c
    counts = pd.concat(parts).groupby(level=[0, 1]).sum()
    counts.index.names = ["date", "symbol"]
    df = counts.reset_index()
    dates = np.sort(df["date"].unique())
    per_date = df.groupby("date")["symbol"].nunique()
    per_sym = df.groupby("symbol")["date"].nunique()
    minutes_per_symdate = df["n"]
    return {
        "parquet": str(path),
        "rows": int(rows),
        "symbols": int(df["symbol"].nunique()),
        "first_date": str(dates[0]),
        "last_date": str(dates[-1]),
        "n_dates": int(len(dates)),
        "minute_range": [mn, mx],
        "median_symbols_per_date": float(per_date.median()),
        "min_symbols_per_date": int(per_date.min()),
        "min_dates_per_symbol": int(per_sym.min()),
        "max_dates_per_symbol": int(per_sym.max()),
        "median_minutes_per_symbol_date": float(minutes_per_symdate.median()),
        "symbol_dates_with_all_390_minutes": int((minutes_per_symdate == 390).sum()),
        "symbol_dates": int(len(minutes_per_symdate)),
        "zero_volume_bars": int(zero_vol),
        "contains_bid_ask": False,
        "content": "trade bars (open/high/low/close/volume), no quotes, no queue",
        "label": label,
        "_dates": [str(d) for d in dates],
    }


def daily_facts() -> dict:
    files = sorted(DAILY_DIR.glob("*.json"))
    n_dates, first, last, rows = [], [], [], 0
    for f in files:
        d = json.loads(f.read_text())
        ks = sorted(d)
        if not ks:
            continue
        n_dates.append(len(ks))
        first.append(ks[0])
        last.append(ks[-1])
        rows += len(ks)
    return {
        "dir": str(DAILY_DIR),
        "n_symbol_files": len(files),
        "rows": rows,
        "earliest_date_any_symbol": min(first),
        "latest_date_any_symbol": max(last),
        "median_dates_per_symbol": float(np.median(n_dates)),
        "fields": ["open", "high", "low", "close", "volume"],
        "contains_bid_ask": False,
        "dir_sha256": hashlib.sha256(
            b"".join(
                (f.name + sha256_of(f)).encode() for f in files
            )
        ).hexdigest(),
    }


def adjustment_proof(daily: dict) -> dict:
    """Prove whether the daily cache is split-adjusted, using a known split.

    NVDA split 10-for-1 on 2024-06-10.  If the cache is adjusted, the price on
    2024-06-07 is about a tenth of the unadjusted quote of roughly $1200.
    """
    out = {}
    for tic, split_date, ratio in [("NVDA", "2024-06-10", 10)]:
        p = DAILY_DIR / f"{tic}.json"
        if not p.exists():
            out[tic] = "symbol not present"
            continue
        d = json.loads(p.read_text())
        ks = sorted(d)
        try:
            i = ks.index(split_date)
        except ValueError:
            out[tic] = f"{split_date} not in cache"
            continue
        before, after = d[ks[i - 1]][3], d[ks[i]][3]
        out[tic] = {
            "split_date": split_date,
            "declared_ratio": ratio,
            "close_day_before": before,
            "close_on_split_day": after,
            "ratio_before_over_after": round(before / after, 3),
            "verdict": ("SPLIT-ADJUSTED (no jump across the split)"
                        if 0.5 < before / after < 2
                        else "RAW / UNADJUSTED (price jumps at the split)"),
        }
    return out


def main():
    RES_DIR.mkdir(parents=True, exist_ok=True)
    equs = minute_facts(RES_DIR / "bars-equs-full.parquet", "EQUS.MINI consolidated")
    equs_dates = equs.pop("_dates")
    pillar = minute_facts(RES_DIR / "bars-pillar-full.parquet", "XNYS.PILLAR primary")
    pillar.pop("_dates", None)

    # Feed agreement, whole session, on 40 evenly spaced dates (memory-lean).
    import pyarrow.dataset as ds

    all_dates = sorted(equs_dates)
    sample_dates = [all_dates[i] for i in
                    np.linspace(0, len(all_dates) - 1, 40).astype(int)]
    de = ds.dataset(RES_DIR / "bars-equs-full.parquet")
    dp = ds.dataset(RES_DIR / "bars-pillar-full.parquet")
    cols = ["date", "symbol", "minute", "close", "volume"]
    a = de.to_table(columns=cols,
                    filter=ds.field("date").isin(sample_dates)).to_pandas()
    b = dp.to_table(columns=cols,
                    filter=ds.field("date").isin(sample_dates)).to_pandas()
    for f in (a, b):
        f["symbol"] = f["symbol"].astype(str)
        f["date"] = f["date"].astype(str)
    m = a.merge(b, on=["date", "symbol", "minute"], suffixes=("_e", "_p"))
    bps = (m["close_e"] / m["close_p"] - 1.0).abs() * 1e4
    cross = {
        "sample_dates": len(sample_dates),
        "overlapping_minute_bars": int(len(m)),
        "median_volume_ratio_equs_over_pillar": float(
            (m["volume_e"] / m["volume_p"].replace(0, np.nan)).median()),
        "close_diff_bps_median": float(bps.median()),
        "close_diff_bps_p95": float(bps.quantile(0.95)),
        "close_diff_bps_p99": float(bps.quantile(0.99)),
        "note": "Trade prices from two independent feeds for the same minute. "
                "The gap between them is the floor on how precisely any "
                "historical fill can be known.",
    }
    del a, b, m, bps

    dates = all_dates
    dev_dates = dates[: len(dates) - SEALED_DATES]
    sealed = dates[len(dates) - SEALED_DATES:]

    daily = daily_facts()

    doc = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "TODO #104 immediate profitable share feature - data inventory",
        "network_used": False,
        "new_data_spend_usd": 0.0,
        "git_head": git_head(),
        "raw_files": {
            p.name: {"path": str(p), "size_bytes": p.stat().st_size,
                     "sha256": sha256_of(p)}
            for p in [EQUS_FILE, EQUS_BRK_FILE, PILLAR_FILE]
        },
        "universe_selection_file": {
            "path": str(UNIVERSE_FILE),
            "exists": UNIVERSE_FILE.exists(),
            "size_bytes": UNIVERSE_FILE.stat().st_size if UNIVERSE_FILE.exists() else None,
            "sha256": sha256_of(UNIVERSE_FILE) if UNIVERSE_FILE.exists() else None,
            "role": "daily bars for ALL XNYS symbols; used only to build the "
                    "as-of-date liquidity check and the independent daily record",
        },
        "minute_panels": {"equs": equs, "pillar": pillar, "cross_check": cross},
        "daily_cache": daily,
        "daily_adjustment_proof": adjustment_proof(daily),
        "regular_session_minutes": [MIN_OPEN, MIN_RTH_LAST],
        "date_split": {
            "rule": "chronological; the last 182 dates stay sealed",
            "development_dates": len(dev_dates),
            "development_first": dev_dates[0],
            "development_last": dev_dates[-1],
            "sealed_dates": len(sealed),
            "sealed_first": sealed[0],
            "sealed_last": sealed[-1],
        },
        "known_limits": [
            "The 60 stocks were chosen with liquidity facts ending August 2026 and "
            "applied backwards. Every result on that fixed list is conditional on it. "
            "An as-of-date liquidity check is applied on top and reported separately. "
            "Neither recreates stocks absent from the collection.",
            "Minute files carry trades only. There is no historical bid, ask, or "
            "order-queue position anywhere in this data.",
            "A minute with no trade has no bar. No fill may be assumed there.",
            "EQUS.MINI is a subset of the whole tape, so any dollar-volume "
            "capacity limit computed from it is conservative.",
            "No index fund or sector fund exists in the minute files, so the "
            "market move must be built from the 60 stocks themselves.",
            "Historical short-share availability is unknown for every past date.",
        ],
    }
    out = RES_DIR / "current-state.json"
    out.write_text(json.dumps(doc, indent=2, default=str) + "\n")
    print(f"wrote {out}")
    print(json.dumps({k: doc[k] for k in ("date_split", "daily_adjustment_proof")},
                     indent=2))


if __name__ == "__main__":
    main()
