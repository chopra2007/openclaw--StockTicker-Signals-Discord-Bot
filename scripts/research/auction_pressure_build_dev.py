#!/usr/bin/env python3
"""TODO #93 Phase 1 — build the immutable development panel.

Streams the local DBN files once each, then builds one row per ticker-date
with the five opening-pressure snapshots, the prior session's closing
pressure, the frozen price fields, the frozen features, entry/exit prices,
exclusion reasons, and the development-fold number.

Local files only. No network, no API key, no paid request.
The evaluation dates are filtered out before any feature or outcome is
computed, so no evaluation result can exist in this phase.
"""

import argparse
import json
import sys
from array import array
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auction_pressure_common import (  # noqa: E402
    BASE_COST,
    DEV_FRACTION,
    EQUS_BRK_FILE,
    EQUS_FILE,
    EXTREME_PCTL,
    FOLDS,
    GATE_DIR,
    IMBALANCE_FILE,
    LARGE_GAP_PCTL,
    MIN_BASKET_BREADTH,
    MIN_ENTRY_A,
    MIN_ENTRY_B,
    MIN_ENTRY_VOLUME,
    MIN_EXIT30_A,
    MIN_EXIT30_B,
    MIN_EXIT_A,
    MIN_EXIT_B,
    MIN_FIRST_FIVE,
    MIN_OPEN,
    MIN_PRIOR_CLOSE,
    NEEDED_MINUTES,
    PERSISTENCE_MIN,
    PRICE_SCALE,
    PRIOR_DIR,
    SEED,
    SNAPSHOT_CUTOFFS_ET,
    SNAPSHOT_ORDER,
    TRAILING_MIN,
    TRAILING_WINDOW,
    EtClock,
    canonical,
    day_to_date_str,
    open_store,
    side_sign,
    symbol_map,
)

RAW_IMB = GATE_DIR / "raw-imbalance-snapshots.parquet"
RAW_BARS = GATE_DIR / "raw-bars.parquet"
RAW_META = GATE_DIR / "raw-extract-meta.json"

TS_COLS = [f"ts_{n}" for n in SNAPSHOT_ORDER] + ["ts_close_auction"]
CUTS = [SNAPSHOT_CUTOFFS_ET[k] for k in SNAPSHOT_ORDER]


def update_snapshots(slots, ts, sec, val):
    """Keep, for each frozen cutoff, the latest message received at or before it."""
    for i, cut in enumerate(CUTS):
        if sec <= cut and (slots[i] is None or ts > slots[i][0]):
            slots[i] = val
    return slots


def fold_of_index(i):
    """0 = first training block only, 1-4 = walk-forward validation block."""
    for k, (_, _, vlo, vhi) in enumerate(FOLDS, start=1):
        if vlo <= i < vhi:
            return k
    return 0


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def extract_imbalance():
    """One streaming pass: five opening snapshots + the last closing message."""
    clock = EtClock()
    inst2sym = {i: canonical(s) for i, s in symbol_map(IMBALANCE_FILE).items()}
    last_cut = CUTS[-1]

    snaps, closes, halt_pairs, m_days = {}, {}, set(), set()
    n = 0
    out_of_order = 0
    prev_ts = 0

    for rec in open_store(IMBALANCE_FILE):
        n += 1
        ts = rec.ts_recv
        if ts < prev_ts:
            out_of_order += 1
        prev_ts = ts
        at = rec.auction_type
        if at == "M":
            day, sec = clock.date_and_sec(ts)
            m_days.add(day)
            if sec > last_cut:
                continue
            key = (day, rec.instrument_id)
            e = snaps.get(key)
            if e is None:
                e = snaps[key] = [None] * 5
            update_snapshots(e, ts, sec, (ts, rec.total_imbalance_qty,
                                          rec.paired_qty, str(rec.side)))
        elif at == "C":
            day, _ = clock.date_and_sec(ts)
            key = (day, rec.instrument_id)
            cur = closes.get(key)
            if cur is None or ts > cur[0]:
                closes[key] = (ts, rec.total_imbalance_qty, rec.paired_qty, str(rec.side))
        elif at == "H":
            day, _ = clock.date_and_sec(ts)
            halt_pairs.add((day_to_date_str(day), int(rec.instrument_id)))
        if n % 5_000_000 == 0:
            print(f"  imbalance {n:,} records...", file=sys.stderr, flush=True)

    print(f"  imbalance total {n:,}; out-of-order ts_recv {out_of_order}", file=sys.stderr)

    rows = []
    for day, inst in set(snaps) | set(closes):
        sym = inst2sym.get(inst)
        if sym is None:
            continue
        row = {"date": day_to_date_str(day), "symbol": sym, "xnys_inst": int(inst)}
        e = snaps.get((day, inst), [None] * 5)
        for i, name in enumerate(SNAPSHOT_ORDER):
            v = e[i]
            if v is None:
                row[f"ts_{name}"] = None
                row[f"p_{name}"] = np.nan
                row[f"pq_{name}"] = np.nan
            else:
                ts, tiq, pq, side = v
                sgn = side_sign(side)
                row[f"ts_{name}"] = int(ts)
                row[f"p_{name}"] = (sgn * tiq / pq) if (pq and sgn != 0) else np.nan
                row[f"pq_{name}"] = float(pq) if pq else np.nan
        c = closes.get((day, inst))
        if c is None:
            row["ts_close_auction"] = None
            row["closing_pressure"] = np.nan
        else:
            ts, tiq, pq, side = c
            sgn = side_sign(side)
            row["ts_close_auction"] = int(ts)
            row["closing_pressure"] = (sgn * tiq / pq) if (pq and sgn != 0) else np.nan
        rows.append(row)

    df = pd.DataFrame(rows)
    for c in TS_COLS:
        df[c] = df[c].astype("Int64")
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    meta = {
        "imbalance_records": n,
        "out_of_order_ts_recv": out_of_order,
        "m_trading_dates": sorted(day_to_date_str(d) for d in m_days),
        "halted_pairs": sorted([list(p) for p in halt_pairs]),
    }
    return df, meta


def extract_bars():
    """One streaming pass per EQUS file, keeping only the minutes this plan uses."""
    clock = EtClock()
    cols = {k: array("q") for k in ("open", "high", "low", "close", "volume")}
    a_date, a_sym, a_min = array("i"), array("i"), array("h")
    sym_ids = {}
    total = 0

    for path in (EQUS_FILE, EQUS_BRK_FILE):
        inst2sym = {i: canonical(s) for i, s in symbol_map(path).items()}
        n = 0
        for rec in open_store(path):
            n += 1
            day, sec = clock.date_and_sec(rec.ts_event)
            minute = int(sec) // 60
            if minute not in NEEDED_MINUTES:
                continue
            sym = inst2sym.get(rec.instrument_id)
            if sym is None:
                continue
            sid = sym_ids.setdefault(sym, len(sym_ids))
            a_date.append(int(day))
            a_sym.append(sid)
            a_min.append(minute)
            cols["open"].append(rec.open)
            cols["high"].append(rec.high)
            cols["low"].append(rec.low)
            cols["close"].append(rec.close)
            cols["volume"].append(rec.volume)
            if n % 5_000_000 == 0:
                print(f"  bars {path.name} {n:,} records...", file=sys.stderr, flush=True)
        total += n
        print(f"  {path.name}: {n:,} records", file=sys.stderr)

    id2sym = {v: k for k, v in sym_ids.items()}
    sym_arr = np.frombuffer(a_sym, dtype=np.int32)
    df = pd.DataFrame({
        "date": [day_to_date_str(d) for d in a_date],
        "symbol": pd.Categorical.from_codes(sym_arr, [id2sym[i] for i in range(len(id2sym))]),
        "minute": np.frombuffer(a_min, dtype=np.int16),
        "open": np.frombuffer(cols["open"], dtype=np.int64) * PRICE_SCALE,
        "high": np.frombuffer(cols["high"], dtype=np.int64) * PRICE_SCALE,
        "low": np.frombuffer(cols["low"], dtype=np.int64) * PRICE_SCALE,
        "close": np.frombuffer(cols["close"], dtype=np.int64) * PRICE_SCALE,
        "volume": np.frombuffer(cols["volume"], dtype=np.int64),
    })
    return df, {"equs_records_scanned": total, "bars_kept": int(len(df))}


# --------------------------------------------------------------------------
# trailing statistics over VALID prior sessions only
# --------------------------------------------------------------------------
def trailing(series, how, q=0.0):
    valid = series.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=series.index)
    roll = valid.shift(1).rolling(TRAILING_WINDOW, min_periods=TRAILING_MIN)
    out = roll.quantile(q) if how == "quantile" else roll.median()
    return out.reindex(series.index)


def trailing_beta(y, x):
    both = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    if len(both) < TRAILING_MIN + 1:
        return pd.Series(np.nan, index=y.index)
    ys, xs = both["y"].shift(1), both["x"].shift(1)
    cov = ys.rolling(TRAILING_WINDOW, min_periods=TRAILING_MIN).cov(xs)
    var = xs.rolling(TRAILING_WINDOW, min_periods=TRAILING_MIN).var()
    return (cov / var.replace(0.0, np.nan)).reindex(y.index)


def build_calendar(meta):
    calendar = meta["m_trading_dates"]
    n_dates = len(calendar)
    n_dev = int(round(n_dates * DEV_FRACTION))
    dev_dates = calendar[:n_dev]
    cal = pd.Series(calendar)
    last_of_month = set(cal.groupby(cal.str.slice(0, 7)).last())
    quarter_ends = {d for d in last_of_month if d[5:7] in ("03", "06", "09", "12")}
    return calendar, dev_dates, last_of_month, quarter_ends


# --------------------------------------------------------------------------
# panel
# --------------------------------------------------------------------------
def build_panel(imb, bars, meta, which="dev"):
    prior = json.load(open(PRIOR_DIR / "phase1-gate.json"))
    degraded_xnys = set(prior["degraded_dates_xnys"])
    degraded_equs = set(prior["degraded_dates_equs"])
    raw1b = json.load(open(PRIOR_DIR / "phase1b-raw-analysis.json"))
    halted_pairs = {(d, int(i)) for d, i in raw1b["imbalance"]["halted_pairs"]}

    calendar, dev_dates, last_of_month, quarter_ends = build_calendar(meta)
    split_date = dev_dates[-1]
    keep = set(dev_dates) if which == "dev" else set(calendar[len(dev_dates):])
    # the prior session of the first kept date is needed for the overnight join
    first_kept_idx = calendar.index(min(keep))
    price_keep = set(calendar[max(0, first_kept_idx - 1):]) & set(calendar[: calendar.index(max(keep)) + 1])

    date_index = {d: i for i, d in enumerate(calendar)}
    prior_date = {d: (calendar[i - 1] if i > 0 else None) for d, i in date_index.items()}

    def cal_group(d):
        if d in quarter_ends:
            return "quarter_end"
        if d in last_of_month:
            return "month_end"
        return "ordinary"

    imb = imb[imb["date"].isin(price_keep)].copy()
    bars = bars[bars["date"].isin(price_keep)].copy()
    bars["symbol"] = bars["symbol"].astype(str)
    bars = bars.drop_duplicates(["date", "symbol", "minute"], keep="last")

    wanted = {
        MIN_OPEN: ["open"],
        MIN_FIRST_FIVE: ["close"],
        MIN_ENTRY_B: ["close", "volume"],
        MIN_ENTRY_A: ["close", "volume"],
        MIN_EXIT30_B: ["close"],
        MIN_EXIT30_A: ["close"],
        MIN_EXIT_B: ["close"],
        MIN_EXIT_A: ["close"],
        MIN_PRIOR_CLOSE: ["close"],
    }
    px = {}
    for minute, want in wanted.items():
        sub = bars[bars["minute"] == minute].set_index(["date", "symbol"])
        for c in want:
            px[f"{c}_{minute}"] = sub[c]
    px = pd.DataFrame(px)

    def extremes(lo, hi):
        w = bars[(bars["minute"] > lo) & (bars["minute"] <= hi)]
        g = w.groupby(["date", "symbol"], observed=True)
        return g["high"].max(), g["low"].min()

    hi_a, lo_a = extremes(MIN_ENTRY_A, MIN_EXIT_A)
    hi_b, lo_b = extremes(MIN_ENTRY_B, MIN_EXIT_B)

    df = imb.reset_index(drop=True)
    df["prior_session_date"] = df["date"].map(prior_date)
    df["calendar_group"] = df["date"].map(cal_group)

    idx = pd.MultiIndex.from_arrays([df["date"], df["symbol"]])
    for col in px.columns:
        df[col] = px[col].reindex(idx).to_numpy()
    df["hi_a"] = hi_a.reindex(idx).to_numpy()
    df["lo_a"] = lo_a.reindex(idx).to_numpy()
    df["hi_b"] = hi_b.reindex(idx).to_numpy()
    df["lo_b"] = lo_b.reindex(idx).to_numpy()

    key = df.set_index(["symbol", "date"])
    prior_idx = pd.MultiIndex.from_arrays([df["symbol"], df["prior_session_date"]])
    df["prior_closing_pressure"] = key["closing_pressure"].reindex(prior_idx).to_numpy()
    df["ts_prior_close_auction"] = pd.array(
        key["ts_close_auction"].reindex(prior_idx).to_numpy(), dtype="Int64"
    )
    prior_px_idx = pd.MultiIndex.from_arrays([df["prior_session_date"], df["symbol"]])
    df["prior_close"] = px[f"close_{MIN_PRIOR_CLOSE}"].reindex(prior_px_idx).to_numpy()

    df["xnys_degraded"] = df["date"].isin(degraded_xnys)
    df["xnys_degraded_prior"] = df["prior_session_date"].isin(degraded_xnys)
    df["equs_degraded"] = df["date"].isin(degraded_equs)
    df["equs_degraded_prior"] = df["prior_session_date"].isin(degraded_equs)
    df["halted"] = [(d, int(i)) in halted_pairs for d, i in zip(df["date"], df["xnys_inst"])]

    bad_imb = df["xnys_degraded"] | df["halted"]
    for name in SNAPSHOT_ORDER:
        df.loc[bad_imb, [f"p_{name}", f"pq_{name}"]] = np.nan
    df.loc[df["xnys_degraded_prior"] | df["halted"], "prior_closing_pressure"] = np.nan
    price_cols = list(px.columns) + ["hi_a", "lo_a", "hi_b", "lo_b"]
    df.loc[df["equs_degraded"] | df["halted"], price_cols] = np.nan
    df.loc[df["equs_degraded_prior"] | df["halted"], "prior_close"] = np.nan

    # ---- frozen features ----
    p = {n: df[f"p_{n}"] for n in SNAPSHOT_ORDER}
    df["signed_pressure"] = p["0930"]
    df["paired_qty_0930"] = df["pq_0930"]

    sign930 = np.sign(p["0930"])
    any_missing = pd.concat([p[n].isna() for n in SNAPSHOT_ORDER], axis=1).any(axis=1)
    df["any_snapshot_missing"] = any_missing
    match = pd.concat([(np.sign(p[n]) == sign930) for n in SNAPSHOT_ORDER], axis=1)
    df["persistence"] = (match.sum(axis=1) / 5.0).where(~any_missing)
    late_same = (np.sign(p["0925"]) == sign930) & (np.sign(p["0929_30"]) == sign930)
    df["persistent"] = (df["persistence"] >= PERSISTENCE_MIN) & late_same & ~any_missing

    flips = sum(
        (np.sign(p[SNAPSHOT_ORDER[i]]) != np.sign(p[SNAPSHOT_ORDER[i + 1]])).astype(float)
        for i in range(4)
    )
    df["flip_count"] = flips.where(~any_missing)
    df["growth"] = (p["0930"].abs() - p["0915"].abs()).where(~any_missing)

    pre = pd.concat([p[n].abs().rename(n) for n in SNAPSHOT_ORDER[:4]], axis=1)
    max_pre = pre.max(axis=1)
    which_max = pre.dropna(how="all").idxmax(axis=1).reindex(pre.index)
    earlier_vals = pd.Series(np.nan, index=df.index)
    for name in SNAPSHOT_ORDER[:4]:
        sel = which_max == name
        earlier_vals[sel] = p[name][sel]
    df["earlier_pressure_sign"] = np.sign(earlier_vals)
    df["max_pre_pressure"] = max_pre
    canc = np.where(max_pre > 0, (max_pre - p["0930"].abs()) / max_pre.replace(0, np.nan), 0.0)
    df["cancellation"] = pd.Series(canc, index=df.index).where(~any_missing)
    df["late_flip"] = (sign930 != df["earlier_pressure_sign"]) & ~any_missing

    df["opening_price"] = df[f"open_{MIN_OPEN}"]
    df["opening_gap"] = (df["opening_price"] - df["prior_close"]) / df["prior_close"]
    df["first_five_return"] = (df[f"close_{MIN_FIRST_FIVE}"] - df["opening_price"]) / df["opening_price"]

    df["entry_a"] = df[f"close_{MIN_ENTRY_A}"]
    df["entry_vol_a"] = df[f"volume_{MIN_ENTRY_A}"]
    df["exit_a"] = df[f"close_{MIN_EXIT_A}"]
    df["exit30_a"] = df[f"close_{MIN_EXIT30_A}"]
    df["entry_b"] = df[f"close_{MIN_ENTRY_B}"]
    df["entry_vol_b"] = df[f"volume_{MIN_ENTRY_B}"]
    df["exit_b"] = df[f"close_{MIN_EXIT_B}"]
    df["exit30_b"] = df[f"close_{MIN_EXIT30_B}"]
    for lane in ("a", "b"):
        df[f"ret_{lane}"] = (df[f"exit_{lane}"] - df[f"entry_{lane}"]) / df[f"entry_{lane}"]
        df[f"ret30_{lane}"] = (df[f"exit30_{lane}"] - df[f"entry_{lane}"]) / df[f"entry_{lane}"]
        df[f"up_{lane}"] = df[f"hi_{lane}"] / df[f"entry_{lane}"] - 1.0
        df[f"dn_{lane}"] = df[f"lo_{lane}"] / df[f"entry_{lane}"] - 1.0

    for lane in ("a", "b"):
        r = df[f"ret_{lane}"]
        g = r.groupby(df["date"])
        tot, cnt = g.transform("sum"), g.transform("count")
        n_other = cnt - r.notna().astype(int)
        basket = (tot - r.fillna(0.0)) / n_other.replace(0, np.nan)
        df[f"basket_{lane}"] = basket.where(n_other >= MIN_BASKET_BREADTH)
        df[f"basket_n_{lane}"] = n_other

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    parts = []
    for _, g in df.groupby("symbol", sort=False):
        g = g.copy()
        g["pressure_pctl"] = trailing(g["signed_pressure"].abs(), "quantile", EXTREME_PCTL)
        g["closing_pressure_pctl"] = trailing(
            g["closing_pressure"].abs().shift(1), "quantile", EXTREME_PCTL
        )
        g["paired_median"] = trailing(g["paired_qty_0930"], "median")
        g["gap_pctl"] = trailing(g["opening_gap"].abs(), "quantile", LARGE_GAP_PCTL)
        for lane in ("a", "b"):
            g[f"beta_{lane}"] = trailing_beta(g[f"ret_{lane}"], g[f"basket_{lane}"])
        parts.append(g)
    df = pd.concat(parts).sort_values(["date", "symbol"]).reset_index(drop=True)

    df["pressure_extreme"] = df["signed_pressure"].abs() >= df["pressure_pctl"]
    df["max_pre_extreme"] = df["max_pre_pressure"] >= df["pressure_pctl"]
    df["closing_pressure_extreme"] = df["prior_closing_pressure"].abs() >= df["closing_pressure_pctl"]
    df["paired_size"] = df["paired_qty_0930"] / df["paired_median"]
    df["large_gap"] = df["opening_gap"].abs() >= df["gap_pctl"]

    for lane in ("a", "b"):
        df[f"adj_{lane}"] = df[f"ret_{lane}"] - df[f"beta_{lane}"] * df[f"basket_{lane}"]
        df[f"adj30_{lane}"] = df[f"ret30_{lane}"] - df[f"beta_{lane}"] * df[f"basket_{lane}"]

    def lane_exclusion(lane):
        reasons = pd.Series("", index=df.index, dtype=object)

        def add(mask, why):
            m = mask.fillna(True) if mask.dtype == object else mask
            reasons[m.astype(bool) & (reasons == "")] = why

        add(df["halted"], "halted_ticker_day")
        if lane == "a":
            add(df["any_snapshot_missing"], "missing_opening_snapshot")
        else:
            add(df["signed_pressure"].isna(), "missing_0930_snapshot")
            add(df["prior_closing_pressure"].isna(), "missing_prior_closing_pressure")
        add(df["prior_close"].isna(), "missing_prior_close_price")
        add(df["opening_price"].isna(), "missing_opening_price")
        if lane == "a":
            add(df[f"close_{MIN_FIRST_FIVE}"].isna(), "missing_first_five_bar")
        add(df[f"entry_{lane}"].isna(), "missing_entry_bar")
        add(df[f"exit_{lane}"].isna(), "missing_exit_bar")
        add(df[f"entry_vol_{lane}"].fillna(0) <= MIN_ENTRY_VOLUME, "entry_volume_not_fillable")
        add(df[f"basket_{lane}"].isna(), "insufficient_basket_breadth")
        add(df[f"beta_{lane}"].isna(), "insufficient_trailing_beta_history")
        add(df["pressure_pctl"].isna(), "insufficient_trailing_pressure_history")
        add(df["gap_pctl"].isna(), "insufficient_trailing_gap_history")
        if lane == "b":
            add(df["closing_pressure_pctl"].isna(),
                "insufficient_trailing_closing_pressure_history")
        return reasons

    for lane in ("a", "b"):
        df[f"lane_{lane}_exclusion"] = lane_exclusion(lane)
        df[f"lane_{lane}_eligible"] = df[f"lane_{lane}_exclusion"] == ""

    dev_pos = {d: i for i, d in enumerate(dev_dates)}

    def fold_of(d):
        i = dev_pos.get(d)
        return -1 if i is None else fold_of_index(i)

    df["fold"] = df["date"].map(fold_of)
    df["base_cost"] = BASE_COST
    df["seed"] = SEED
    df = df[df["date"].isin(keep)].reset_index(drop=True)

    info = {
        "calendar_dates": len(calendar),
        "development_dates": len(dev_dates),
        "split_date": split_date,
        "evaluation_dates": len(calendar) - len(dev_dates),
        "month_end_dates": len(last_of_month),
        "quarter_end_dates": len(quarter_ends),
        "which": which,
    }
    return df, info


def load_or_extract(reuse):
    GATE_DIR.mkdir(parents=True, exist_ok=True)
    if reuse and RAW_IMB.exists() and RAW_BARS.exists() and RAW_META.exists():
        print("reusing cached extracts", file=sys.stderr)
        return pd.read_parquet(RAW_IMB), pd.read_parquet(RAW_BARS), json.load(open(RAW_META))
    print("PASS 1/2 imbalance file", file=sys.stderr, flush=True)
    imb, meta_i = extract_imbalance()
    imb.to_parquet(RAW_IMB, index=False)
    print("PASS 2/2 EQUS one-minute bars", file=sys.stderr, flush=True)
    bars, meta_b = extract_bars()
    bars.to_parquet(RAW_BARS, index=False)
    meta = {**meta_i, **meta_b}
    json.dump(meta, open(RAW_META, "w"), indent=2)
    return imb, bars, meta


def write_data_dictionary(df):
    doc = {
        "date": "trading date, Eastern calendar date of the auction (owner-facing times are Pacific)",
        "symbol": "ticker, canonical form (BRK.B for both venues)",
        "p_0915..p_0930": "signed opening pressure at each frozen snapshot = sign(side) * total_imbalance_qty / paired_qty",
        "ts_0915..ts_0930": "ts_recv in UTC nanoseconds of the message each snapshot came from",
        "closing_pressure": "signed pressure of this date's last closing-auction message",
        "prior_closing_pressure": "closing_pressure of the immediately preceding trading session",
        "signed_pressure": "p_0930, the 6:30 a.m. Pacific opening pressure",
        "persistence": "share of the five snapshots whose sign matches the 6:30 sign",
        "persistent": "persistence >= 0.80 and no sign flip after 6:25 a.m. Pacific",
        "flip_count": "sign changes across consecutive snapshots",
        "growth": "|p_0930| - |p_0915|",
        "cancellation": "(largest |pressure| before 6:30 - |p_0930|) / largest |pressure| before 6:30",
        "earlier_pressure_sign": "sign of the largest |pressure| snapshot before 6:30",
        "late_flip": "the 6:30 sign differs from earlier_pressure_sign",
        "paired_size": "6:30 paired_qty divided by its trailing 60-session median",
        "prior_close": "close of the one-minute bar ending 1:00 p.m. Pacific on the prior session",
        "opening_price": "open of the one-minute bar beginning 6:30 a.m. Pacific",
        "opening_gap": "(opening_price - prior_close) / prior_close",
        "first_five_return": "(close of the bar ending 6:35 - opening_price) / opening_price",
        "large_gap": "|opening_gap| >= its trailing 75th percentile",
        "pressure_extreme": "|signed_pressure| >= its trailing 90th percentile",
        "max_pre_extreme": "largest |pressure| before 6:30 >= the same trailing 90th percentile",
        "closing_pressure_extreme": "|prior_closing_pressure| >= its trailing 90th percentile",
        "calendar_group": "ordinary / month_end / quarter_end, computed from the trading calendar",
        "entry_a / exit_a": "lane A entry = close of the bar ending 6:40 Pacific; exit = 60 minutes later",
        "entry_b / exit_b": "lane B entry = close of the bar ending 6:36 Pacific; exit = 60 minutes later",
        "ret_a / ret_b": "raw entry-to-exit return",
        "basket_a / basket_b": "equal-weighted same-window return of the other available names",
        "beta_a / beta_b": "trailing 60-session OLS slope of the ticker's window return on that basket",
        "adj_a / adj_b": "ret - beta * basket, the market-adjusted return before costs",
        "adj30_a / adj30_b": "same, using the 30-minute exit (diagnostic only)",
        "up_a / dn_a": "largest up and down move between entry and exit (diagnostic only)",
        "lane_a_eligible / lane_b_eligible": "all required inputs present and the entry minute fillable",
        "lane_a_exclusion / lane_b_exclusion": "first reason the row is not eligible; empty when eligible",
        "fold": "0 = first training block only, 1-4 = walk-forward validation block, -1 = not development",
        "base_cost": "round-trip trading cost used for the primary result (15 basis points)",
    }
    doc["_columns_present"] = sorted(df.columns.tolist())
    json.dump(doc, open(GATE_DIR / "data-dictionary.json", "w"), indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-raw", action="store_true")
    args = ap.parse_args()

    imb, bars, meta = load_or_extract(args.reuse_raw)
    print("building development panel", file=sys.stderr, flush=True)
    dev, info = build_panel(imb, bars, meta, which="dev")

    dev.to_parquet(GATE_DIR / "dev-panel.parquet", index=False)
    dev.head(200).to_csv(GATE_DIR / "dev-panel-sample.csv", index=False)
    write_data_dictionary(dev)

    gate = {
        "phase": "phase1",
        "seed": SEED,
        "rows_development": int(len(dev)),
        "distinct_symbols": int(dev["symbol"].nunique()),
        "distinct_dates": int(dev["date"].nunique()),
        "max_date_in_panel": str(dev["date"].max()),
        "lane_a_eligible": int(dev["lane_a_eligible"].sum()),
        "lane_b_eligible": int(dev["lane_b_eligible"].sum()),
        "lane_a_exclusions": {k: int(v) for k, v in dev["lane_a_exclusion"].value_counts().items()},
        "lane_b_exclusions": {k: int(v) for k, v in dev["lane_b_exclusion"].value_counts().items()},
        "extract_meta": {k: v for k, v in meta.items()
                         if k not in ("m_trading_dates", "halted_pairs")},
        "calendar": info,
        "evaluation_rows_written": 0,
        "clock_pacific": {
            "snapshots": ["06:15", "06:20", "06:25", "06:29:30", "06:30"],
            "lane_a_signal": "06:35", "lane_a_entry_bar_ends": "06:40",
            "lane_b_signal": "06:31", "lane_b_entry_bar_ends": "06:36",
            "exit_minutes_after_entry": 60,
        },
    }
    gate["gate_pass"] = bool(
        info["development_dates"] == 730
        and info["split_date"] == "2025-11-28"
        and gate["max_date_in_panel"] <= "2025-11-28"
        and gate["rows_development"] > 0
    )
    json.dump(gate, open(GATE_DIR / "phase1-gate.json", "w"), indent=2)
    print(json.dumps({k: v for k, v in gate.items() if k != "extract_meta"}, indent=2))


if __name__ == "__main__":
    main()
