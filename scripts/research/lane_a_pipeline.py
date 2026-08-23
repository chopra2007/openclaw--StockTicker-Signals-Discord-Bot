#!/usr/bin/env python3
"""Lane A pipeline runner -- builds the event table, splits dev/eval, and
(after thresholds are frozen in hypotheses-v1.md) runs the frozen rule once
on the evaluation period. See lane_a_earnings_reaction.py for the data-pull
helpers and module docstring for the full method.

Stages:
  build        -- pull yfinance earnings_dates + Schwab 30m bars for the
                   universe; compute rvol_30m + initial_reaction_pct (cheap,
                   no 5-minute pulls yet); write candidate_events.json and
                   the raw manifest.
  dev-inspect  -- chronological dev/eval split; print DEV-period-only
                   distributions used to freeze thresholds. Does not touch
                   eval numbers.
  eval-run     -- with frozen thresholds (constants below, set after
                   dev-inspect), pull 5-minute windows for qualifying dev +
                   eval candidates and their matched same-ticker controls;
                   compute the primary outcome once; write events_lane_a.csv
                   and the result JSON files.

Read-only against consensus.db. No production writes.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import lane_a_earnings_reaction as lib  # noqa: E402

ET = lib.ET
PT = lib.PT
OUT_DIR = lib.OUT_DIR
CACHE_DIR = lib.CACHE_DIR

WINDOW_START = datetime(2025, 12, 1, tzinfo=ET)

# --------------------------------------------------------------------------
# FROZEN THRESHOLDS -- set from DEV-period-only inspection (see
# hypotheses-v1.md "## Lane A" for the exact numbers and the dev-period
# distribution that produced them). Do not edit after eval-run has been
# executed once; a change here is a new hypothesis version.
# --------------------------------------------------------------------------
RVOL_THRESHOLD = 5.0          # premarket 30m-bar volume vs 20-day trailing MEDIAN
MOVE_FLOOR_PCT = 3.0          # |initial_reaction_pct| floor, 09:00-09:29 ET bar close vs prior daily close
STOP_PCT = 1.5                # frozen stop distance, % adverse from entry, sizing $100 risk
TARGET_MULT = 2.0             # frozen target = STOP_PCT * TARGET_MULT (2R), geometry-neutral, same for both arms
DEV_EVAL_SPLIT_DATE = None    # computed in build/split step, printed for the record

OUTCOME_HORIZONS_MIN = [30, 60]


def stage_build(cap: int) -> None:
    universe = lib.build_universe(cap)
    now = datetime.now(ET)

    raw_manifest: list[dict] = []
    candidates: list[dict] = []

    for i, ticker in enumerate(universe):
        raw_rows = lib.fetch_earnings_dates_cached(ticker)
        for r in raw_rows:
            raw_manifest.append(r)
        if not raw_rows:
            continue

        df_30m = lib.fetch_30m_cached(ticker, WINDOW_START, now)
        if df_30m is None or df_30m.empty:
            for r in raw_rows:
                candidates.append(_excluded_row(ticker, r, "no_30m_price_history"))
            continue
        daily_df = lib.daily_closes_cached(ticker, WINDOW_START, now)

        for r in raw_rows:
            report_ts = datetime.fromisoformat(r["report_ts_et"])
            report_date = report_ts.date()
            if r["reported_eps"] is None:
                candidates.append(_excluded_row(ticker, r, "not_yet_reported"))
                continue
            if r["surprise_pct"] is None:
                candidates.append(_excluded_row(ticker, r, "missing_surprise_pct"))
                continue

            t = report_ts.timetz()
            if t.replace(tzinfo=None) < dtime(9, 30):
                subtype = "BMO"
                entry_day = report_date if report_date in {d for d in df_30m.index.date} else lib.next_trading_day(df_30m, report_date - timedelta(days=1))
            elif t.replace(tzinfo=None) >= dtime(16, 0):
                subtype = "AMC"
                entry_day = lib.next_trading_day(df_30m, report_date)
            else:
                candidates.append(_excluded_row(ticker, r, "intraday_report_not_premarket_observable", subtype="INTRADAY"))
                continue

            if entry_day is None:
                candidates.append(_excluded_row(ticker, r, "no_trading_day_available_after_report", subtype=subtype))
                continue
            if entry_day < lib.SCHWAB_30M_REACH:
                candidates.append(_excluded_row(ticker, r, "before_schwab_30m_reach", subtype=subtype))
                continue

            rvol = lib.rvol_30m(df_30m, entry_day)
            if rvol is None:
                candidates.append(_excluded_row(ticker, r, "insufficient_30m_baseline_or_no_bar", subtype=subtype))
                continue

            pm_bar = lib.premarket_30m_bar(df_30m, entry_day)
            pclose = lib.prior_close(daily_df, entry_day)
            if pm_bar is None or pclose is None or pclose <= 0:
                candidates.append(_excluded_row(ticker, r, "missing_premarket_bar_or_prior_close", subtype=subtype))
                continue

            initial_reaction_pct = (float(pm_bar["Close"]) - pclose) / pclose * 100.0
            eps_dir = "up" if r["surprise_pct"] > 0 else ("down" if r["surprise_pct"] < 0 else None)
            reaction_dir = "up" if initial_reaction_pct > 0 else ("down" if initial_reaction_pct < 0 else None)
            agree = eps_dir is not None and eps_dir == reaction_dir
            trade_direction = eps_dir if agree else None

            candidates.append({
                "ticker": ticker, "subtype": subtype, "report_ts_et": r["report_ts_et"],
                "eps_estimate": r["eps_estimate"], "reported_eps": r["reported_eps"],
                "surprise_pct": r["surprise_pct"], "entry_day": str(entry_day),
                "rvol_30m": round(rvol["rvol"], 3), "rvol_baseline_median_shares": rvol["baseline_median_shares"],
                "prior_close": pclose, "premarket_30m_close": float(pm_bar["Close"]),
                "initial_reaction_pct": round(initial_reaction_pct, 3),
                "eps_direction": eps_dir, "reaction_direction": reaction_dir,
                "direction_agrees": agree, "trade_direction": trade_direction,
                "exclusion_reason": None,
            })
        print(f"[{i+1}/{len(universe)}] {ticker}: {sum(1 for c in candidates if c['ticker']==ticker)} rows so far")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "events_lane_a_raw_manifest.json").write_text(json.dumps(raw_manifest, indent=2, default=str))
    (CACHE_DIR / "candidate_events.json").write_text(json.dumps(candidates, indent=2, default=str))
    print(f"\nwrote {len(raw_manifest)} raw yfinance rows -> events_lane_a_raw_manifest.json")
    print(f"wrote {len(candidates)} classified candidate rows -> cache/candidate_events.json")


def _excluded_row(ticker: str, r: dict, reason: str, subtype: str = "UNKNOWN") -> dict:
    return {
        "ticker": ticker, "subtype": subtype, "report_ts_et": r["report_ts_et"],
        "eps_estimate": r["eps_estimate"], "reported_eps": r["reported_eps"],
        "surprise_pct": r["surprise_pct"], "entry_day": None,
        "rvol_30m": None, "rvol_baseline_median_shares": None,
        "prior_close": None, "premarket_30m_close": None,
        "initial_reaction_pct": None, "eps_direction": None, "reaction_direction": None,
        "direction_agrees": None, "trade_direction": None,
        "exclusion_reason": reason,
    }


def _load_candidates() -> list[dict]:
    return json.loads((CACHE_DIR / "candidate_events.json").read_text())


def _split_date(usable: list[dict]) -> str:
    dates = sorted(c["entry_day"] for c in usable)
    idx = int(len(dates) * 0.6)
    idx = min(max(idx, 0), len(dates) - 1)
    return dates[idx]


def wilson_ci(wins: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return round(max(0.0, lo) * 100.0, 1), round(min(1.0, hi) * 100.0, 1)


def sector_map() -> dict[str, str]:
    try:
        return lib._load_sector_map()
    except Exception as exc:
        print(f"sector map load failed: {exc}")
        return {}


def stage_dev_inspect() -> None:
    candidates = _load_candidates()
    usable = [c for c in candidates if c["exclusion_reason"] is None]
    split_date = _split_date(usable)
    dev = [c for c in usable if c["entry_day"] <= split_date]
    ev = [c for c in usable if c["entry_day"] > split_date]

    print(f"total raw classified rows: {len(candidates)}")
    print(f"usable (reached rvol/reaction stage): {len(usable)}")
    print(f"chronological split date: {split_date}")
    print(f"DEV period: {len(dev)} events, EVAL period: {len(ev)} events (eval NOT inspected below)")

    print("\n--- DEV period distributions (this is what freezes the rule) ---")
    rvols = sorted(c["rvol_30m"] for c in dev)
    reacts = sorted(abs(c["initial_reaction_pct"]) for c in dev)
    agree_n = sum(1 for c in dev if c["direction_agrees"])
    print(f"rvol_30m: n={len(rvols)} median={statistics.median(rvols):.2f} "
          f"p25={rvols[len(rvols)//4]:.2f} p75={rvols[3*len(rvols)//4]:.2f} max={rvols[-1]:.2f}")
    print(f"|initial_reaction_pct|: n={len(reacts)} median={statistics.median(reacts):.2f} "
          f"p25={reacts[len(reacts)//4]:.2f} p75={reacts[3*len(reacts)//4]:.2f} max={reacts[-1]:.2f}")
    print(f"direction_agrees (EPS surprise sign == premarket reaction sign): {agree_n}/{len(dev)} "
          f"= {agree_n/len(dev)*100:.1f}%")

    for rv_thr in (1.2, 1.5, 2.0, 2.5, 3.0):
        for mv_thr in (1.0, 1.5, 2.0, 3.0, 4.0):
            q = [c for c in dev if c["rvol_30m"] >= rv_thr and abs(c["initial_reaction_pct"]) >= mv_thr and c["direction_agrees"]]
            print(f"  RVOL>={rv_thr} & |move|>={mv_thr}% & direction_agrees: {len(q)}/{len(dev)} qualify "
                  f"({len(q)/len(dev)*100:.1f}%)")

    exclusion_counts: dict[str, int] = {}
    for c in candidates:
        if c["exclusion_reason"]:
            exclusion_counts[c["exclusion_reason"]] = exclusion_counts.get(c["exclusion_reason"], 0) + 1
    print("\nexclusion reasons (all periods):")
    for k, v in sorted(exclusion_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")

    (CACHE_DIR / "split_date.json").write_text(json.dumps({"split_date": split_date}))


CSV_FIELDS = [
    "event_id", "ticker", "event_family", "event_subtype", "first_public_timestamp_et",
    "first_public_source", "eps_estimate", "reported_eps", "surprise_pct", "entry_day",
    "direction_implied", "direction_basis", "materiality_class", "rvol_30m",
    "rvol_baseline_median_shares", "initial_reaction_pct", "direction_agrees", "trade_direction",
    "qualifies", "dev_or_eval", "owner_actionable", "entry_ts_et", "entry_price",
    "ticker_ret_30m_pct", "mkt_adj_ret_30m_pct", "sector_adj_ret_30m_pct",
    "ticker_ret_60m_pct", "mkt_adj_ret_60m_pct", "sector_adj_ret_60m_pct",
    "ticker_ret_to_close_pct", "ticker_ret_to_next_open_pct", "ticker_ret_to_next_close_pct",
    "mfe_up_pct", "mfe_up_time_min", "mfe_down_pct", "mfe_down_time_min",
    "target_stop_outcome", "pnl_per_100_risk_dollars", "missing_data_exclusion_reason",
    "duplicate_cluster_id", "sector_etf_used",
]


def flatten_row(cand: dict, outcome: dict | None, pnl: dict | None, dev_or_eval: str, qualifies: bool,
                 sector_etf: str | None) -> dict:
    event_id = f"LANEA-{cand['ticker']}-{cand.get('entry_day') or cand['report_ts_et'][:10]}"
    row = {
        "event_id": event_id, "ticker": cand["ticker"], "event_family": "earnings",
        "event_subtype": cand["subtype"], "first_public_timestamp_et": cand["report_ts_et"],
        "first_public_source": "yfinance Ticker.earnings_dates (cross-validated 97.8% exact-day "
                                "vs SEC EDGAR 8-K Item 2.02, see lane-ac-resolvability.md)",
        "eps_estimate": cand["eps_estimate"], "reported_eps": cand["reported_eps"],
        "surprise_pct": cand["surprise_pct"], "entry_day": cand.get("entry_day"),
        "direction_implied": cand.get("eps_direction") or "unknown",
        "direction_basis": "EPS surprise sign AND premarket reaction sign must agree "
                            "(no point-in-time guidance data available; see builder verdict weakness)",
        "materiality_class": "scheduled_earnings_report", "rvol_30m": cand.get("rvol_30m"),
        "rvol_baseline_median_shares": cand.get("rvol_baseline_median_shares"),
        "initial_reaction_pct": cand.get("initial_reaction_pct"), "direction_agrees": cand.get("direction_agrees"),
        "trade_direction": cand.get("trade_direction"), "qualifies": qualifies, "dev_or_eval": dev_or_eval,
        "missing_data_exclusion_reason": cand.get("exclusion_reason"), "duplicate_cluster_id": event_id,
        "sector_etf_used": sector_etf,
    }
    for f in CSV_FIELDS:
        row.setdefault(f, None)
    if outcome:
        for k, v in outcome.items():
            if k == "_window60":
                continue
            if k in row or k in ("owner_actionable", "entry_ts_et", "entry_price"):
                row[k] = v
    if pnl:
        row["target_stop_outcome"] = pnl["target_stop_outcome"]
        row["pnl_per_100_risk_dollars"] = pnl["pnl_per_100_risk_dollars"]
    return row


def stage_eval_run() -> None:
    candidates = _load_candidates()
    usable = [c for c in candidates if c["exclusion_reason"] is None]
    split_date = json.loads((CACHE_DIR / "split_date.json").read_text())["split_date"] if (CACHE_DIR / "split_date.json").exists() else _split_date(usable)

    def period(entry_day: str) -> str:
        return "dev" if entry_day <= split_date else "eval"

    qualifying = [c for c in usable if c["rvol_30m"] is not None and c["rvol_30m"] >= RVOL_THRESHOLD
                  and abs(c["initial_reaction_pct"]) >= MOVE_FLOOR_PCT and c["direction_agrees"]]
    print(f"usable={len(usable)} qualifying (frozen filter)={len(qualifying)} "
          f"({len(qualifying)/len(usable)*100:.1f}% -- selectivity check)")

    smap = sector_map()
    now = datetime.now(ET)

    csv_rows: list[dict] = []
    outcome_records: list[dict] = []  # for catalyst arm, period-tagged
    control_records: list[dict] = []

    # non-qualifying usable rows still go in the event table (no outcome computed -- not a candidate trade)
    for c in usable:
        if c in qualifying:
            continue
        csv_rows.append(flatten_row(c, None, None, period(c["entry_day"]), False, smap.get(c["ticker"])))
    for c in candidates:
        if c["exclusion_reason"] is not None:
            csv_rows.append(flatten_row(c, None, None, "n/a", False, None))

    tickers_with_qual: dict[str, list[dict]] = {}
    for c in qualifying:
        tickers_with_qual.setdefault(c["ticker"], []).append(c)

    for i, (ticker, events) in enumerate(tickers_with_qual.items()):
        sector_etf = smap.get(ticker)
        daily_df = lib.daily_closes_cached(ticker, WINDOW_START, now)
        for c in events:
            report_ts = datetime.fromisoformat(c["report_ts_et"])
            outcome = compute_entry_and_outcome(ticker, c["entry_day"], report_ts, daily_df, None, sector_etf, None)
            dev_or_eval = period(c["entry_day"])
            pnl = None
            if outcome and outcome.get("exclusion_reason") is None and "_window60" in outcome:
                pnl = pnl_and_target_stop(outcome["_window60"], outcome["entry_price"], c["trade_direction"],
                                           datetime.fromisoformat(outcome["entry_ts_et"]))
                outcome_records.append({**{k: v for k, v in outcome.items() if k != "_window60"}, **pnl,
                                         "ticker": ticker, "entry_day": c["entry_day"],
                                         "trade_direction": c["trade_direction"], "period": dev_or_eval,
                                         "rvol_30m": c["rvol_30m"], "initial_reaction_pct": c["initial_reaction_pct"]})
            csv_rows.append(flatten_row(c, outcome, pnl, dev_or_eval, True, sector_etf))
        print(f"[{i+1}/{len(tickers_with_qual)}] {ticker}: {len(events)} qualifying event(s) priced")

    # controls: same tickers that produced >=1 qualifying event
    for i, (ticker, events) in enumerate(tickers_with_qual.items()):
        df_30m = lib.fetch_30m_cached(ticker, WINDOW_START, now)
        daily_df = lib.daily_closes_cached(ticker, WINDOW_START, now)
        if df_30m is None or daily_df is None:
            continue
        catalyst_days = {date.fromisoformat(c["entry_day"]) for c in events}
        since_ts2 = time.time() - 400 * 86400
        alert_days = lib.ticker_alert_days(ticker, since_ts2)
        ctrl_days = find_control_days(ticker, df_30m, daily_df, catalyst_days, alert_days)
        sector_etf = smap.get(ticker)
        for cd in ctrl_days:
            outcome = compute_entry_and_outcome(ticker, cd["entry_day"], None, daily_df, None, sector_etf, None)
            dev_or_eval = period(cd["entry_day"])
            if outcome and outcome.get("exclusion_reason") is None and "_window60" in outcome:
                pnl = pnl_and_target_stop(outcome["_window60"], outcome["entry_price"], cd["trade_direction"],
                                           datetime.fromisoformat(outcome["entry_ts_et"]))
                control_records.append({**{k: v for k, v in outcome.items() if k != "_window60"}, **pnl,
                                         "ticker": ticker, "entry_day": cd["entry_day"],
                                         "trade_direction": cd["trade_direction"], "period": dev_or_eval,
                                         "rvol_30m": cd["rvol_30m"], "initial_reaction_pct": cd["initial_reaction_pct"]})
        print(f"[{i+1}/{len(tickers_with_qual)}] {ticker}: {len(ctrl_days)} control day(s) found, priced")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "events_lane_a.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in csv_rows:
            w.writerow({k: r.get(k) for k in CSV_FIELDS})
    (OUT_DIR / "lane_a_catalyst_outcomes.json").write_text(json.dumps(outcome_records, indent=2, default=str))
    (OUT_DIR / "lane_a_control_outcomes.json").write_text(json.dumps(control_records, indent=2, default=str))
    (CACHE_DIR / "run_meta.json").write_text(json.dumps({
        "split_date": split_date, "rvol_threshold": RVOL_THRESHOLD, "move_floor_pct": MOVE_FLOOR_PCT,
        "stop_pct": STOP_PCT, "target_mult": TARGET_MULT,
    }, indent=2))
    print(f"\nwrote {len(csv_rows)} rows -> events_lane_a.csv")
    print(f"wrote {len(outcome_records)} catalyst outcomes, {len(control_records)} control outcomes")


# --------------------------------------------------------------------------
# eval-run: pull 5m windows for qualifying candidates + matched controls,
# compute the frozen primary outcome, write final artifacts.
# --------------------------------------------------------------------------
def _first_bar_at_or_after(df_5m, ready_ts_et: datetime):
    if df_5m is None or df_5m.empty:
        return None
    after = df_5m[df_5m.index >= ready_ts_et]
    if after.empty:
        return None
    return after.iloc[0], after.index[0]


def _bar_at_or_before(df_5m, ts_et: datetime):
    if df_5m is None or df_5m.empty:
        return None
    before = df_5m[df_5m.index <= ts_et]
    if before.empty:
        return None
    return before.iloc[-1]


def compute_entry_and_outcome(ticker: str, entry_day_str: str, report_ts_et: datetime | None,
                               daily_df, spy_daily, sector_ticker: str | None, sector_daily) -> dict | None:
    from datetime import date as _date
    entry_day = _date.fromisoformat(entry_day_str)
    win_start = datetime.combine(entry_day - timedelta(days=1), dtime(0, 0), tzinfo=ET)
    win_end = datetime.combine(entry_day + timedelta(days=3), dtime(0, 0), tzinfo=ET)

    df5 = lib.fetch_5m_window_cached(ticker, win_start, win_end)
    if df5 is None or df5.empty:
        return {"exclusion_reason": "no_5m_data_in_window"}

    if report_ts_et is not None:
        total_delay = timedelta(minutes=lib.DETECTION_DELAY_MIN + lib.DELIVERY_DELAY_MIN + lib.OWNER_DELAY_MIN)
        ready_et = report_ts_et + total_delay
        floor_et = datetime.combine(entry_day, dtime(6, 15), tzinfo=PT).astimezone(ET)
        cap_et = datetime.combine(entry_day, dtime(6, 45), tzinfo=PT).astimezone(ET)
        target_ready_et = max(ready_et, floor_et)
        owner_actionable = target_ready_et <= cap_et
    else:
        target_ready_et = datetime.combine(entry_day, dtime(6, 15), tzinfo=PT).astimezone(ET)
        owner_actionable = True

    picked = _first_bar_at_or_after(df5, target_ready_et)
    if picked is None:
        return {"exclusion_reason": "no_tradable_5m_bar_at_or_after_ready_time"}
    entry_bar, entry_ts = picked
    entry_price = float(entry_bar["Close"])

    spy5 = lib.fetch_5m_window_cached("SPY", win_start, win_end)
    sec5 = lib.fetch_5m_window_cached(sector_ticker, win_start, win_end) if sector_ticker else None

    spy_entry_bar = _bar_at_or_before(spy5, entry_ts) if spy5 is not None else None
    sec_entry_bar = _bar_at_or_before(sec5, entry_ts) if sec5 is not None else None

    out: dict = {
        "exclusion_reason": None, "entry_ts_et": entry_ts.isoformat(), "entry_price": entry_price,
        "owner_actionable": owner_actionable,
    }

    window60 = df5[(df5.index >= entry_ts) & (df5.index <= entry_ts + timedelta(minutes=60))]
    if window60.empty:
        out["exclusion_reason"] = "no_bars_in_60min_window"
        return out

    for horizon in OUTCOME_HORIZONS_MIN:
        w = window60[window60.index <= entry_ts + timedelta(minutes=horizon)]
        if w.empty:
            out[f"ticker_ret_{horizon}m_pct"] = None
            out[f"mkt_adj_ret_{horizon}m_pct"] = None
            out[f"sector_adj_ret_{horizon}m_pct"] = None
            continue
        end_price = float(w["Close"].iloc[-1])
        ticker_ret = (end_price - entry_price) / entry_price * 100.0
        out[f"ticker_ret_{horizon}m_pct"] = round(ticker_ret, 3)
        if spy_entry_bar is not None:
            spy_w = spy5[(spy5.index >= entry_ts) & (spy5.index <= entry_ts + timedelta(minutes=horizon))]
            if not spy_w.empty:
                spy_ret = (float(spy_w["Close"].iloc[-1]) - float(spy_entry_bar["Close"])) / float(spy_entry_bar["Close"]) * 100.0
                out[f"mkt_adj_ret_{horizon}m_pct"] = round(ticker_ret - spy_ret, 3)
        if sec_entry_bar is not None:
            sec_w = sec5[(sec5.index >= entry_ts) & (sec5.index <= entry_ts + timedelta(minutes=horizon))]
            if not sec_w.empty:
                sec_ret = (float(sec_w["Close"].iloc[-1]) - float(sec_entry_bar["Close"])) / float(sec_entry_bar["Close"]) * 100.0
                out[f"sector_adj_ret_{horizon}m_pct"] = round(ticker_ret - sec_ret, 3)

    # MFE/MAE within 60 min, direction-neutral here (signed by caller using trade_direction)
    highs = (window60["High"] - entry_price) / entry_price * 100.0
    lows = (window60["Low"] - entry_price) / entry_price * 100.0
    out["mfe_up_pct"] = round(float(highs.max()), 3)
    out["mfe_up_time_min"] = round((window60["High"].idxmax() - entry_ts).total_seconds() / 60.0, 1)
    out["mfe_down_pct"] = round(float(lows.min()), 3)
    out["mfe_down_time_min"] = round((window60["Low"].idxmin() - entry_ts).total_seconds() / 60.0, 1)

    # close / next-open / next-close (ticker return; market-adjustment for
    # these three is reported as a supporting delta in the verdict text,
    # not computed inline here -- SPY's own close/next-close are cheap to
    # pull once at write-time from the same daily cache).
    close_row = daily_df[[d == entry_day for d in daily_df.index.date]] if daily_df is not None else None
    if close_row is not None and not close_row.empty:
        close_px = float(close_row["Close"].iloc[0])
        out["ticker_ret_to_close_pct"] = round((close_px - entry_price) / entry_price * 100.0, 3)
    nxt = lib.next_trading_day_from_daily(daily_df, entry_day) if daily_df is not None else None
    if nxt is not None:
        nrow = daily_df[[d == nxt for d in daily_df.index.date]]
        if not nrow.empty:
            out["ticker_ret_to_next_open_pct"] = round((float(nrow["Open"].iloc[0]) - entry_price) / entry_price * 100.0, 3)
            out["ticker_ret_to_next_close_pct"] = round((float(nrow["Close"].iloc[0]) - entry_price) / entry_price * 100.0, 3)

    out["_window60"] = window60  # consumed by pnl_and_target_stop(), stripped before JSON write
    return out


def pnl_and_target_stop(window60, entry_price: float, direction: str, entry_ts) -> dict:
    """Frozen, geometry-neutral stop/target: STOP_PCT adverse, TARGET_MULT x
    STOP_PCT favorable, same numbers for catalyst and control arms. Walks
    the 5-minute bars in order; a bar whose Low/High touches BOTH levels is
    scored as a stop-first tie (conservative)."""
    sign = 1.0 if direction == "up" else -1.0
    stop_level = entry_price * (1 - sign * STOP_PCT / 100.0)
    target_level = entry_price * (1 + sign * STOP_PCT * TARGET_MULT / 100.0)
    outcome = "neither"
    exit_price = None
    exit_ts = None
    for ts, bar in window60.iterrows():
        lo, hi = float(bar["Low"]), float(bar["High"])
        stop_hit = (lo <= stop_level) if sign > 0 else (hi >= stop_level)
        target_hit = (hi >= target_level) if sign > 0 else (lo <= target_level)
        if stop_hit and target_hit:
            outcome, exit_price, exit_ts = "tie_scored_as_stop", stop_level, ts
            break
        if stop_hit:
            outcome, exit_price, exit_ts = "stop_first", stop_level, ts
            break
        if target_hit:
            outcome, exit_price, exit_ts = "target_first", target_level, ts
            break
    if exit_price is None:
        exit_price = float(window60["Close"].iloc[-1])
        exit_ts = window60.index[-1]

    risk_per_share = entry_price * STOP_PCT / 100.0
    shares = 100.0 / risk_per_share
    pnl_dollars = shares * (exit_price - entry_price) * sign
    return {
        "target_stop_outcome": outcome,
        "exit_price": round(exit_price, 4),
        "minutes_to_exit": round((exit_ts - entry_ts).total_seconds() / 60.0, 1),
        "pnl_per_100_risk_dollars": round(pnl_dollars, 2),
    }


def find_control_days(ticker: str, df_30m, daily_df, catalyst_entry_days: set, alert_days: set) -> list[dict]:
    """Same-ticker, non-report trading days that pass the SAME rvol/move
    selectivity filter as the tested arm (matches on abnormal-volume
    magnitude and initial-move magnitude by construction -- section 11
    design 'same ticker on comparable non-event days'), excluding: any day
    with ANY alert_history entry (not just catalyst-tagged), and any day
    within +/-1 trading day of a Lane A catalyst event for this ticker (to
    keep pre/post-earnings drift out of the 'no identifiable catalyst'
    arm)."""
    from datetime import timedelta as _td
    pm_days = sorted({d for d in df_30m[(df_30m.index.time == lib.PREMARKET_START)].index.date})
    exclude = set()
    for d in catalyst_entry_days:
        for off in (-1, 0, 1):
            exclude.add(d + _td(days=off))
    out = []
    for day in pm_days:
        if day in exclude or str(day) in alert_days:
            continue
        rvol = lib.rvol_30m(df_30m, day)
        if rvol is None or rvol["rvol"] < RVOL_THRESHOLD:
            continue
        pm_bar = lib.premarket_30m_bar(df_30m, day)
        pclose = lib.prior_close(daily_df, day)
        if pm_bar is None or pclose is None or pclose <= 0:
            continue
        reaction_pct = (float(pm_bar["Close"]) - pclose) / pclose * 100.0
        if abs(reaction_pct) < MOVE_FLOOR_PCT:
            continue
        out.append({
            "ticker": ticker, "entry_day": str(day), "rvol_30m": round(rvol["rvol"], 3),
            "initial_reaction_pct": round(reaction_pct, 3),
            "trade_direction": "up" if reaction_pct > 0 else "down",
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["build", "dev-inspect", "eval-run"])
    ap.add_argument("--universe-cap", type=int, default=lib.UNIVERSE_CAP)
    args = ap.parse_args()
    if args.stage == "build":
        stage_build(args.universe_cap)
    elif args.stage == "dev-inspect":
        stage_dev_inspect()
    elif args.stage == "eval-run":
        stage_eval_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
