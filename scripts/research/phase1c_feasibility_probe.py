#!/usr/bin/env python3
"""
Phase 1c: feasibility probe (development period only, arithmetic kill) for
TODO #93 opening-auction-imbalance research.

Streams the DBN files (never .to_df() on a full store). Writes
phase1c-decile-table.csv, phase1c-feasibility-probe.md, phase1c-gate.json
to the gate directory.
"""

import csv
import json
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import databento as db

DATA_DIR = Path("/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08")
GATE_DIR = Path("/home/openclaw/.openclaw/workspace/.omc/research/opening-auction-imbalance")

IMBALANCE_FILE = DATA_DIR / "xnys-pillar_imbalance_60-symbols_2023-01-01_2026-08-22.dbn.zst"
EQUS_OHLCV_FILE = DATA_DIR / "equs-mini_ohlcv-1m_60-symbols_2023-03-28_2026-08-22.dbn.zst"
EQUS_BRK_FILE = DATA_DIR / "equs-mini_ohlcv-1m_BRK.B_2023-03-28_2026-08-22.dbn.zst"

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

HOLDING_PERIOD_MINUTES = 60  # frozen; must match Phase 2
BETA_TRAILING_WINDOW_DAYS = 60  # trading days, strictly before event date
BETA_MIN_WINDOW_DAYS = 20  # minimum valid trailing days required to trust a beta estimate
MIN_BASKET_BREADTH = 10  # minimum other-ticker returns required to trust r_basket that day
MIDDLE_DECILES_LOW = 5
MIDDLE_DECILES_HIGH = 6
SPREAD_THRESHOLD_BPS = 15.0
FILLABLE_SHARE_THRESHOLD = 0.60
FILLABLE_VOLUME_MIN = 500


def ns_to_et(ns: int):
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).astimezone(ET)


def load_gates():
    with open(GATE_DIR / "phase1b-gate.json") as f:
        gate1b = json.load(f)
    with open(GATE_DIR / "phase1-gate.json") as f:
        gate1 = json.load(f)
    with open(GATE_DIR / "phase1b-raw-analysis.json") as f:
        raw1b = json.load(f)
    halted_pairs = set(tuple(p) for p in raw1b["imbalance"]["halted_pairs"])
    degraded_xnys = set(gate1["degraded_dates_xnys"])
    degraded_equs = set(gate1["degraded_dates_equs"])
    all_insts = set(int(k) for k in raw1b["imbalance"]["inst_map"].keys())
    return gate1b, halted_pairs, degraded_xnys, degraded_equs, all_insts


def pass_imbalance(halted_pairs, degraded_xnys):
    """
    One streaming pass over the imbalance file.
    Returns:
      last_m: dict (date_str, inst_id) -> (total_imbalance_qty, paired_qty, side)
        for the LAST 'M' record of that ticker-day (the final pre-print snapshot),
        excluding halted pairs and XNYS-degraded dates.
      all_m_dates: sorted set of all trading dates with any 'M' record (full range,
        used only to freeze split_date -- NOT pre-filtered by degraded/halt, since
        split_date must reflect the calendar the data actually covers).
    """
    print("PASS 1/3: imbalance file (full stream)...", file=sys.stderr)
    store = db.DBNStore.from_file(str(IMBALANCE_FILE))

    last_m_raw = {}  # (date, inst) -> (ts_recv, total_imbalance_qty, paired_qty, side)
    all_m_dates = set()
    n = 0
    for rec in store:
        n += 1
        if getattr(rec, "auction_type", None) != "M":
            continue
        ts_recv_raw = getattr(rec, "ts_recv")
        dt_et = ns_to_et(ts_recv_raw)
        date_str = dt_et.strftime("%Y-%m-%d")
        all_m_dates.add(date_str)
        inst_id = getattr(rec, "instrument_id")
        key = (date_str, inst_id)
        prev = last_m_raw.get(key)
        if prev is None or ts_recv_raw > prev[0]:
            last_m_raw[key] = (
                ts_recv_raw,
                getattr(rec, "total_imbalance_qty"),
                getattr(rec, "paired_qty"),
                str(getattr(rec, "side")),
            )
        if n % 10_000_000 == 0:
            print(f"  imbalance: {n:,} records...", file=sys.stderr)
    print(f"  imbalance total: {n:,} records, {len(all_m_dates)} trading dates, "
          f"{len(last_m_raw)} ticker-days", file=sys.stderr)

    last_m = {}
    for (date_str, inst_id), (_, tiq, pq, side) in last_m_raw.items():
        if (date_str, inst_id) in halted_pairs:
            continue
        if date_str in degraded_xnys:
            continue
        if not pq or pq == 0:
            continue
        if side not in ("Side.BID", "Side.ASK", "B", "A"):
            continue
        sign = 1.0 if side in ("Side.BID", "B") else -1.0
        signed_ratio = sign * (tiq / pq)
        last_m[(date_str, inst_id)] = signed_ratio

    return last_m, all_m_dates


def pass_equs_ohlcv(halted_pairs):
    """
    Stream both EQUS ohlcv files. Collect the 09:34 bar (close, volume) and the
    10:34 bar (close) for every (date, inst) pair, system-wide (needed both as
    event days and as history inside other events' trailing beta windows).
    """
    print("PASS 2/3: EQUS ohlcv-1m (60-symbol file)...", file=sys.stderr)
    bars0934 = {}  # (date, inst) -> (close, volume)
    bars1034 = {}  # (date, inst) -> close

    for filepath, label in [(EQUS_OHLCV_FILE, "equs-60"), (EQUS_BRK_FILE, "equs-brk")]:
        store = db.DBNStore.from_file(str(filepath))
        n = 0
        for rec in store:
            n += 1
            ts_event_raw = getattr(rec, "ts_event")
            dt_et = ns_to_et(ts_event_raw)
            if dt_et.hour == 9 and dt_et.minute == 34:
                date_str = dt_et.strftime("%Y-%m-%d")
                inst_id = getattr(rec, "instrument_id")
                key = (date_str, inst_id)
                if key not in halted_pairs:
                    bars0934[key] = (getattr(rec, "close"), getattr(rec, "volume"))
            elif dt_et.hour == 10 and dt_et.minute == 34:
                date_str = dt_et.strftime("%Y-%m-%d")
                inst_id = getattr(rec, "instrument_id")
                key = (date_str, inst_id)
                if key not in halted_pairs:
                    bars1034[key] = getattr(rec, "close")
            if n % 10_000_000 == 0:
                print(f"  {label}: {n:,} records...", file=sys.stderr)
        print(f"  {label} total: {n:,} records", file=sys.stderr)

    return bars0934, bars1034


def build_daily_returns(bars0934, bars1034, degraded_equs, all_insts):
    """
    daily_window_return[(date, inst)] = (close_1034 - close_0934) / close_0934
    Only for dates not EQUS-degraded, and only where both bars exist.
    Also returns fillable[(date,inst)] = bool (volume>500 on 09:34 bar).
    """
    ret = {}
    fillable = {}
    for key, (close0934, vol0934) in bars0934.items():
        date_str, inst_id = key
        if date_str in degraded_equs:
            continue
        if inst_id not in all_insts:
            continue
        close1034 = bars1034.get(key)
        if close1034 is None or not close0934:
            continue
        ret[key] = (close1034 - close0934) / close0934
        fillable[key] = vol0934 is not None and vol0934 > FILLABLE_VOLUME_MIN
    return ret, fillable


def build_basket_returns(daily_ret, all_insts):
    """
    r_basket[date][inst] = equal-weighted mean daily_window_return of the OTHER
    59 tickers on that date (excludes `inst` itself). Also returns basket_n[date][inst]
    = number of other tickers contributing.
    """
    by_date = defaultdict(dict)  # date -> {inst: ret}
    for (date_str, inst_id), r in daily_ret.items():
        by_date[date_str][inst_id] = r

    basket = {}  # (date, inst) -> (mean_other_ret, n_other)
    for date_str, inst_rets in by_date.items():
        total = sum(inst_rets.values())
        n_total = len(inst_rets)
        for inst_id, r in inst_rets.items():
            n_other = n_total - 1
            if n_other <= 0:
                continue
            mean_other = (total - r) / n_other
            basket[(date_str, inst_id)] = (mean_other, n_other)
    return basket


def estimate_beta(inst_id, event_date, sorted_dates, daily_ret, basket):
    """
    OLS beta of inst_id's daily_window_return on r_basket, over up to
    BETA_TRAILING_WINDOW_DAYS trading days strictly before event_date, using only
    days where both inst_id's return and its basket return (with sufficient
    breadth) are available.
    """
    idx = sorted_dates.index(event_date)
    xs = []
    ys = []
    i = idx - 1
    while i >= 0 and len(xs) < BETA_TRAILING_WINDOW_DAYS:
        d = sorted_dates[i]
        key = (d, inst_id)
        r_i = daily_ret.get(key)
        b = basket.get(key)
        if r_i is not None and b is not None and b[1] >= MIN_BASKET_BREADTH:
            ys.append(r_i)
            xs.append(b[0])
        i -= 1
    if len(xs) < BETA_MIN_WINDOW_DAYS:
        return None
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    if var_x == 0:
        return None
    return cov / var_x


def main():
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    gate1b, halted_pairs, degraded_xnys, degraded_equs, all_insts = load_gates()

    last_m, all_m_dates = pass_imbalance(halted_pairs, degraded_xnys)

    bars0934, bars1034 = pass_equs_ohlcv(halted_pairs)

    print("PASS 3/3: building return series, deciles, beta...", file=sys.stderr)
    daily_ret, fillable = build_daily_returns(bars0934, bars1034, degraded_equs, all_insts)
    basket = build_basket_returns(daily_ret, all_insts)

    # split_date: earliest ~80% of trading dates (by date count) across the FULL
    # imbalance-file date range = development; remaining ~20% = evaluation.
    sorted_dates = sorted(all_m_dates)
    n_dates = len(sorted_dates)
    n_dev = int(round(n_dates * 0.8))
    dev_dates = sorted_dates[:n_dev]
    split_date = dev_dates[-1]
    dev_date_set = set(dev_dates)

    # Build candidate events: (date, inst) with a valid signed ratio (last_m) AND
    # a valid daily_window_return (price data present, not EQUS-degraded).
    events = []
    for (date_str, inst_id), signed_ratio in last_m.items():
        if date_str not in dev_date_set:
            continue
        key = (date_str, inst_id)
        r_i = daily_ret.get(key)
        if r_i is None:
            continue
        b = basket.get(key)
        if b is None or b[1] < MIN_BASKET_BREADTH:
            continue
        beta_i = estimate_beta(inst_id, date_str, sorted_dates, daily_ret, basket)
        if beta_i is None:
            continue
        r_basket_event = b[0]
        adj_return_bps = (r_i - beta_i * r_basket_event) * 10000.0
        events.append({
            "date": date_str,
            "inst": inst_id,
            "signed_ratio": signed_ratio,
            "adj_return_bps": adj_return_bps,
            "fillable": fillable.get(key, False),
        })

    print(f"  {len(events)} decile-eligible development-period events", file=sys.stderr)

    events.sort(key=lambda e: e["signed_ratio"])
    n_events = len(events)
    decile_rows = []
    decile_means = {}
    for d in range(1, 11):
        lo = int((d - 1) * n_events / 10)
        hi = int(d * n_events / 10) if d < 10 else n_events
        chunk = events[lo:hi]
        n_chunk = len(chunk)
        if n_chunk == 0:
            mean_ratio = None
            mean_ret = None
        else:
            mean_ratio = sum(e["signed_ratio"] for e in chunk) / n_chunk
            mean_ret = sum(e["adj_return_bps"] for e in chunk) / n_chunk
        decile_rows.append({
            "decile": d,
            "mean_signed_ratio": mean_ratio,
            "mean_adjusted_return_bps": mean_ret,
            "n": n_chunk,
        })
        decile_means[d] = (mean_ret, chunk)

    top_mean = decile_means[10][0]
    bottom_mean = decile_means[1][0]
    middle_chunk = decile_means[MIDDLE_DECILES_LOW][1] + decile_means[MIDDLE_DECILES_HIGH][1]
    middle_mean = (sum(e["adj_return_bps"] for e in middle_chunk) / len(middle_chunk)
                   if middle_chunk else None)

    decile_spread_bps_top = (top_mean - middle_mean) if (top_mean is not None and middle_mean is not None) else None
    decile_spread_bps_bottom = (bottom_mean - middle_mean) if (bottom_mean is not None and middle_mean is not None) else None

    fillable_count = sum(1 for e in events if e["fillable"])
    fillable_entry_share = (fillable_count / n_events) if n_events else 0.0

    spread_condition = (
        (decile_spread_bps_top is not None and decile_spread_bps_top >= SPREAD_THRESHOLD_BPS) or
        (decile_spread_bps_bottom is not None and decile_spread_bps_bottom <= -SPREAD_THRESHOLD_BPS)
    )
    fillability_condition = fillable_entry_share >= FILLABLE_SHARE_THRESHOLD
    proceed = bool(spread_condition and fillability_condition)

    # --- write CSV ---
    csv_path = GATE_DIR / "phase1c-decile-table.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["decile", "mean_signed_ratio", "mean_adjusted_return_bps", "n"])
        for row in decile_rows:
            w.writerow([row["decile"], row["mean_signed_ratio"], row["mean_adjusted_return_bps"], row["n"]])

    # --- write markdown ---
    md_path = GATE_DIR / "phase1c-feasibility-probe.md"
    lines = []
    lines.append("# Phase 1c — Feasibility Probe (development period only, arithmetic kill)\n")
    lines.append(f"split_date = {split_date} (development = dates <= split_date, "
                 f"{len(dev_dates)} of {n_dates} total trading dates; evaluation = dates after)\n")
    lines.append(f"holding_period_minutes = {HOLDING_PERIOD_MINUTES} (frozen, matches Phase 2)\n")
    lines.append(f"decile-eligible development-period events: n = {n_events}\n")
    lines.append("\n## Threshold check 1 — decile spread vs middle-decile (5/6) baseline\n")
    lines.append(f"- Top decile (10, largest buy imbalance) mean adjusted return: "
                 f"{top_mean:.4f} bps (n={decile_means[10][1].__len__()})\n" if top_mean is not None else "- Top decile: no data\n")
    lines.append(f"- Bottom decile (1, largest sell imbalance) mean adjusted return: "
                 f"{bottom_mean:.4f} bps (n={decile_means[1][1].__len__()})\n" if bottom_mean is not None else "- Bottom decile: no data\n")
    lines.append(f"- Middle deciles (5+6, pooled) mean adjusted return: "
                 f"{middle_mean:.4f} bps (n={len(middle_chunk)})\n" if middle_mean is not None else "- Middle deciles: no data\n")
    lines.append(f"- decile_spread_bps_top = top - middle = {decile_spread_bps_top:.4f} bps "
                 f"(threshold: >= +{SPREAD_THRESHOLD_BPS}) -> "
                 f"{'PASS' if decile_spread_bps_top is not None and decile_spread_bps_top >= SPREAD_THRESHOLD_BPS else 'FAIL'}\n")
    lines.append(f"- decile_spread_bps_bottom = bottom - middle = {decile_spread_bps_bottom:.4f} bps "
                 f"(threshold: <= -{SPREAD_THRESHOLD_BPS}) -> "
                 f"{'PASS' if decile_spread_bps_bottom is not None and decile_spread_bps_bottom <= -SPREAD_THRESHOLD_BPS else 'FAIL'}\n")
    lines.append(f"- Spread condition (either leg passes): {'PASS' if spread_condition else 'FAIL'}\n")
    lines.append("\n## Threshold check 2 — fillable entry coverage\n")
    lines.append(f"- fillable_entry_share = {fillable_entry_share:.4f} "
                 f"({fillable_count} / {n_events} development-period decile-eligible ticker-days "
                 f"with >500 shares on the 09:34-09:35 EQUS bar)\n")
    lines.append(f"- Threshold: >= {FILLABLE_SHARE_THRESHOLD} -> "
                 f"{'PASS' if fillability_condition else 'FAIL'}\n")
    lines.append(f"\n## Overall\n")
    lines.append(f"- proceed = spread_condition AND fillability_condition = {proceed}\n")
    lines.append(f"\n## Method notes (not opinion, just what was computed)\n")
    lines.append("- Feature = signed imbalance ratio = total_imbalance_qty / paired_qty, "
                 "sign +1 for side=BID (buy imbalance), -1 for side=ASK (sell imbalance), "
                 "taken from the LAST 'M' record per ticker-day (final pre-print snapshot).\n")
    lines.append("- beta_i: OLS slope of daily entry(09:35 ET)->exit(10:35 ET) window return on "
                 f"the equal-weighted other-59-ticker basket return of the same window, over up to "
                 f"{BETA_TRAILING_WINDOW_DAYS} trading days strictly before the event date "
                 f"(minimum {BETA_MIN_WINDOW_DAYS} valid days required; event dropped otherwise).\n")
    lines.append(f"- r_basket requires at least {MIN_BASKET_BREADTH} of the other 59 tickers to have "
                 "a valid same-day window return; event dropped otherwise.\n")
    lines.append("- Exclusions applied: 22 halted (date, instrument) pairs (Phase 1b); "
                 "XNYS-degraded dates excluded from the imbalance feature only; EQUS-degraded dates "
                 "excluded from price/return computation only (each per-date, per-source, not global).\n")
    with open(md_path, "w") as f:
        f.writelines(lines)

    # --- write gate json ---
    gate = {
        "gate_pass": True,
        "proceed": proceed,
        "split_date": split_date,
        "decile_spread_bps_top": round(decile_spread_bps_top, 6) if decile_spread_bps_top is not None else None,
        "decile_spread_bps_bottom": round(decile_spread_bps_bottom, 6) if decile_spread_bps_bottom is not None else None,
        "fillable_entry_share": round(fillable_entry_share, 6),
    }
    with open(GATE_DIR / "phase1c-gate.json", "w") as f:
        json.dump(gate, f, indent=2)

    print(json.dumps(gate, indent=2))
    print("\nDecile table:")
    for row in decile_rows:
        print(row)


if __name__ == "__main__":
    main()
