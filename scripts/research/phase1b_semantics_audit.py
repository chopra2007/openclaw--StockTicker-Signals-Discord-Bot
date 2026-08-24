#!/usr/bin/env python3
"""
Phase 1b: Upstream semantics audit for opening-auction imbalance research.
Streams the DBN files (never .to_df() on the full store) and writes
data-capability-audit.json to the gate directory.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import databento as db

DATA_DIR = Path("/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08")
OUT_DIR = Path("/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-imbalance")

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

IMBALANCE_FILE = DATA_DIR / "xnys-pillar_imbalance_60-symbols_2023-01-01_2026-08-22.dbn.zst"
XNYS_OHLCV_FILE = DATA_DIR / "xnys-pillar_ohlcv-1m_60-symbols_2023-01-01_2026-08-22.dbn.zst"
EQUS_OHLCV_FILE = DATA_DIR / "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst"
EQUS_BRK_FILE = DATA_DIR / "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"


def ns_to_utc_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC)


def build_instrument_symbol_map(store) -> dict:
    """instrument_id (int, as it appears in records) -> symbol, from metadata.mappings."""
    mapping = {}
    md = store.metadata
    for symbol, intervals in md.mappings.items():
        for iv in intervals:
            try:
                iid = int(iv["symbol"])
            except (KeyError, TypeError, ValueError):
                continue
            mapping[iid] = symbol
    return mapping


def bucket_5min_et(dt_et: datetime) -> str:
    """Floor a tz-aware ET datetime to a 5-minute bucket label HH:MM."""
    minute = (dt_et.minute // 5) * 5
    return f"{dt_et.hour:02d}:{minute:02d}"


# ---------------------------------------------------------------------------
# PASS 1: imbalance file
# ---------------------------------------------------------------------------

def pass_imbalance():
    print("PASS 1: imbalance file (full stream)...", file=sys.stderr)
    store = db.DBNStore.from_file(str(IMBALANCE_FILE))
    inst_map = build_instrument_symbol_map(store)

    auction_type_counts = defaultdict(int)
    auction_time_raw_per_type = defaultdict(set)  # type -> set of raw auction_time ints (small, constant per type)

    # Timezone-encoding transition detection: per calendar date (ET, derived from ts_recv),
    # record the delta in hours between auction_time (raw ns, interpreted naively as UTC)
    # and ts_recv (raw ns, genuine UTC), for type=='M' records only. Sample first record/date.
    date_delta_sample = {}  # date_str -> delta_hours (from first M record seen that date)

    # Field population clock (type M only), 5-min ET buckets 08:00-09:35
    target_fields = [
        "total_imbalance_qty", "paired_qty", "side", "ind_match_price",
        "auct_interest_clr_price", "upper_collar", "market_imbalance_qty",
    ]
    bucket_total = defaultdict(int)
    bucket_populated = {f: defaultdict(int) for f in target_fields}
    # earliest bucket where each field first shows any population
    field_first_bucket = {f: None for f in target_fields}

    # Halted (date, instrument_id) pairs for type H
    halted_pairs = set()

    # Order-entry cutoff: per (date, instrument_id) for M-type records, track last ts_recv time-of-day ET
    last_m_time_per_tickerday = {}  # (date_str, instrument_id) -> "HH:MM:SS.ffffff" ET of last M record

    n = 0
    for rec in store:
        n += 1
        atype = getattr(rec, "auction_type", None)
        auction_type_counts[atype] += 1
        auction_time_raw = getattr(rec, "auction_time")
        if len(auction_time_raw_per_type[atype]) < 20:
            auction_time_raw_per_type[atype].add(auction_time_raw)

        ts_recv_raw = getattr(rec, "ts_recv")
        ts_recv_dt_utc = ns_to_utc_dt(ts_recv_raw)
        ts_recv_dt_et = ts_recv_dt_utc.astimezone(ET)
        date_str = ts_recv_dt_et.strftime("%Y-%m-%d")

        if atype == "M":
            if date_str not in date_delta_sample:
                auction_time_dt_naive_as_utc = ns_to_utc_dt(auction_time_raw)
                delta_hours = (ts_recv_dt_utc - auction_time_dt_naive_as_utc).total_seconds() / 3600.0
                date_delta_sample[date_str] = round(delta_hours, 3)

            inst_id = getattr(rec, "instrument_id")
            tkey = (date_str, inst_id)
            hms = ts_recv_dt_et.strftime("%H:%M:%S.%f")
            prev = last_m_time_per_tickerday.get(tkey)
            if prev is None or hms > prev:
                last_m_time_per_tickerday[tkey] = hms

            # 5-min bucket population clock, window 08:00-09:35 ET
            if (ts_recv_dt_et.hour == 8) or (ts_recv_dt_et.hour == 9 and ts_recv_dt_et.minute <= 34) or \
               (ts_recv_dt_et.hour == 9 and ts_recv_dt_et.minute == 35 and ts_recv_dt_et.second == 0):
                b = bucket_5min_et(ts_recv_dt_et)
                bucket_total[b] += 1
                for f in target_fields:
                    val = getattr(rec, f, None)
                    populated = False
                    if f == "side":
                        # Side enum; 'N' == none/not set
                        populated = (str(val) not in ("N", "Side.NONE", "None", ""))
                    else:
                        try:
                            populated = (val is not None and int(val) != 0)
                        except (TypeError, ValueError):
                            populated = bool(val)
                    if populated:
                        bucket_populated[f][b] += 1
                        if field_first_bucket[f] is None or b < field_first_bucket[f]:
                            field_first_bucket[f] = b
        elif atype == "H":
            inst_id = getattr(rec, "instrument_id")
            halted_pairs.add((date_str, inst_id))

        if n % 5_000_000 == 0:
            print(f"  imbalance: {n:,} records processed...", file=sys.stderr)

    print(f"  imbalance total: {n:,} records", file=sys.stderr)

    return {
        "inst_map": inst_map,
        "auction_type_counts": dict(auction_type_counts),
        "auction_time_raw_by_type": {t: sorted(v) for t, v in auction_time_raw_per_type.items()},
        "date_delta_sample": date_delta_sample,
        "bucket_total": dict(bucket_total),
        "bucket_populated": {f: dict(v) for f, v in bucket_populated.items()},
        "field_first_bucket": field_first_bucket,
        "halted_pairs": sorted(list(halted_pairs)),
        "last_m_time_per_tickerday": {f"{d}|{i}": t for (d, i), t in last_m_time_per_tickerday.items()},
        "total_records": n,
    }


# ---------------------------------------------------------------------------
# PASS 2: OHLCV premarket fill-coverage census (xnys + equs)
# ---------------------------------------------------------------------------

def pass_ohlcv(filepath: Path, label: str, is_equs: bool = False):
    print(f"PASS: {label} premarket census...", file=sys.stderr)
    store = db.DBNStore.from_file(str(filepath))

    # bucket by 1-min ET time-of-day string HH:MM, 09:00-09:40
    bar_count = defaultdict(int)
    bar_vol_gt500 = defaultdict(int)
    all_tickerdays = set()
    has_0930_bar = set()
    n = 0
    n_window = 0
    for rec in store:
        n += 1
        ts_event_raw = getattr(rec, "ts_event")
        dt_utc = ns_to_utc_dt(ts_event_raw)
        dt_et = dt_utc.astimezone(ET)
        inst_id = getattr(rec, "instrument_id")
        tkey = (dt_et.strftime("%Y-%m-%d"), inst_id)
        all_tickerdays.add(tkey)
        if dt_et.hour == 9 and dt_et.minute == 30:
            has_0930_bar.add(tkey)
        if dt_et.hour == 9 and 0 <= dt_et.minute <= 40:
            key = f"{dt_et.hour:02d}:{dt_et.minute:02d}"
            bar_count[key] += 1
            vol = getattr(rec, "volume", 0)
            if vol and vol > 500:
                bar_vol_gt500[key] += 1
            n_window += 1
        if n % 5_000_000 == 0:
            print(f"  {label}: {n:,} records processed...", file=sys.stderr)

    print(f"  {label} total: {n:,} records, {n_window:,} in 09:00-09:40 ET window", file=sys.stderr)
    total_td = len(all_tickerdays)
    present_td = len(has_0930_bar)
    missing_share = round(1 - (present_td / total_td), 4) if total_td else None
    return {
        "bar_count": dict(bar_count), "bar_vol_gt500": dict(bar_vol_gt500), "total_records": n,
        "total_ticker_days": total_td, "ticker_days_with_0930_bar": present_td,
        "ticker_days_missing_0930_bar_share": missing_share,
    }


# ---------------------------------------------------------------------------
# instrument-id mapping cross-check (item 6)
# ---------------------------------------------------------------------------

def cross_dataset_id_check():
    print("Cross-dataset instrument-ID check...", file=sys.stderr)
    xnys_store = db.DBNStore.from_file(str(XNYS_OHLCV_FILE))
    equs_store = db.DBNStore.from_file(str(EQUS_OHLCV_FILE))
    xnys_map = xnys_store.metadata.mappings
    equs_map = equs_store.metadata.mappings

    common_symbols = sorted(set(xnys_map.keys()) & set(equs_map.keys()))
    n_multi_interval = {"xnys": 0, "equs": 0}
    n_id_mismatch = 0
    sample_rows = []
    for sym in common_symbols:
        xiv = xnys_map[sym]
        eiv = equs_map[sym]
        if len(xiv) > 1:
            n_multi_interval["xnys"] += 1
        if len(eiv) > 1:
            n_multi_interval["equs"] += 1
        x_id = xiv[0]["symbol"] if xiv else None
        e_id = eiv[0]["symbol"] if eiv else None
        if x_id != e_id:
            n_id_mismatch += 1
        if len(sample_rows) < 8:
            sample_rows.append({"symbol": sym, "xnys_instrument_id": x_id, "equs_instrument_id": e_id,
                                 "xnys_intervals": len(xiv), "equs_intervals": len(eiv)})

    return {
        "common_symbols_count": len(common_symbols),
        "symbols_with_multiple_xnys_intervals": n_multi_interval["xnys"],
        "symbols_with_multiple_equs_intervals": n_multi_interval["equs"],
        "symbols_where_xnys_id_differs_from_equs_id": n_id_mismatch,
        "sample_rows": sample_rows,
    }


def main():
    result = {}
    result["imbalance"] = pass_imbalance()
    result["xnys_ohlcv_premarket"] = pass_ohlcv(XNYS_OHLCV_FILE, "xnys-ohlcv")
    result["equs_ohlcv_premarket"] = pass_ohlcv(EQUS_OHLCV_FILE, "equs-ohlcv")
    result["cross_dataset_id_check"] = cross_dataset_id_check()

    out_file = OUT_DIR / "phase1b-raw-analysis.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nWritten: {out_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
