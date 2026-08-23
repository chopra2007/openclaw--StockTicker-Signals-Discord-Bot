#!/usr/bin/env python3
"""Lane B (material company-news reaction) — frozen eval-period test.

Runs the frozen rule from `.omc/research/event-reaction-short-duration/
hypotheses-v1.md` ("## Lane B") ONCE against the untouched eval period
(events_lane_b.csv rows with period=="eval"). Do not edit this script to
chase a better number -- a corrected rule is a new version per plan section 8.

Read-only against consensus.db (not touched at all here -- only Schwab price
history is pulled, no DB access). Bounded Schwab calls: 1 pull per {ticker,
SPY, sector ETF} used, ~9 total. No secrets printed.

Usage: python3 scripts/research/lane_b_eval_test.py
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")

OUT_DIR = ROOT / ".omc" / "research" / "event-reaction-short-duration"
EVENTS_CSV = OUT_DIR / "events_lane_b.csv"

TICKERS = ["AAPL", "MRNA", "ROKU", "GME"]
SECTOR_ETF = {"AAPL": "XLK", "MRNA": "XLV", "ROKU": "XLC", "GME": "XLY"}
ALL_SYMBOLS = sorted(set(TICKERS) | {"SPY"} | set(SECTOR_ETF.values()))

# Frozen outcome parameters (hypotheses-v1.md ## Lane B section 7).
STOP_PCT = 0.015
RISK_DOLLARS = 100.0
ENTRY_MAX_WAIT_HOURS = 4

PULL_START = datetime(2026, 5, 20, tzinfo=ET)  # buffer before window for prior-5-day baselines
PULL_END = datetime(2026, 8, 23, tzinfo=ET)


def load_events() -> list[dict]:
    with open(EVENTS_CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["period"] == "eval"]


def pull_5m(symbol: str):
    print(f"[price] {symbol} 5m extended-hours ...", file=sys.stderr)
    df = schwab_client.get_price_history(
        symbol, interval="5m", start=PULL_START, end=PULL_END, extended_hours=True,
    )
    return df


def pull_daily(symbol: str):
    print(f"[price] {symbol} 1d ...", file=sys.stderr)
    df = schwab_client.get_price_history(
        symbol, interval="1d", start=PULL_START, end=PULL_END, extended_hours=False,
    )
    return df


def bar_at_or_after(df, ts: datetime, max_wait_hours: float = ENTRY_MAX_WAIT_HOURS):
    """First bar with index >= ts, within max_wait_hours. Returns (timestamp, row) or None."""
    if df is None or df.empty:
        return None
    window = df[(df.index >= ts) & (df.index <= ts + timedelta(hours=max_wait_hours))]
    if window.empty:
        return None
    return window.index[0], window.iloc[0]


def bar_at_or_before(df, ts: datetime, max_wait_hours: float = ENTRY_MAX_WAIT_HOURS):
    if df is None or df.empty:
        return None
    window = df[(df.index <= ts) & (df.index >= ts - timedelta(hours=max_wait_hours))]
    if window.empty:
        return None
    return window.index[-1], window.iloc[-1]


def path_slice(df, start_ts: datetime, end_ts: datetime):
    if df is None or df.empty:
        return None
    win = df[(df.index >= start_ts) & (df.index <= end_ts)]
    return win if not win.empty else None


def compute_outcome(ticker_df, spy_df, sector_df, entry_ts: datetime, direction: str) -> dict | None:
    """Returns the full outcome dict for one (event or control) observation,
    or None if price data is insufficient (caller records the exclusion)."""
    entry = bar_at_or_after(ticker_df, entry_ts)
    if entry is None:
        return {"excluded_reason": "no_tradable_entry_window"}
    entry_bar_ts, entry_bar = entry
    entry_price = float(entry_bar["Close"])

    spy_entry = bar_at_or_after(spy_df, entry_ts)
    sector_entry = bar_at_or_after(sector_df, entry_ts)
    if spy_entry is None or sector_entry is None:
        return {"excluded_reason": "no_market_or_sector_reference_at_entry"}
    spy_entry_price = float(spy_entry[1]["Close"])
    sector_entry_price = float(sector_entry[1]["Close"])

    out = {
        "entry_ts_et": entry_bar_ts.isoformat(),
        "entry_price": round(entry_price, 4),
        "spy_entry_price": round(spy_entry_price, 4),
        "sector_entry_price": round(sector_entry_price, 4),
    }

    sign = 1.0 if direction == "bullish" else -1.0

    def adjusted_return_at(minutes: int) -> dict | None:
        target = entry_bar_ts + timedelta(minutes=minutes)
        t_bar = bar_at_or_after(ticker_df, target, max_wait_hours=2)
        s_bar = bar_at_or_after(spy_df, target, max_wait_hours=2)
        e_bar = bar_at_or_after(sector_df, target, max_wait_hours=2)
        if t_bar is None or s_bar is None or e_bar is None:
            return None
        t_ret = float(t_bar[1]["Close"]) / entry_price - 1.0
        s_ret = float(s_bar[1]["Close"]) / spy_entry_price - 1.0
        e_ret = float(e_bar[1]["Close"]) / sector_entry_price - 1.0
        raw_adj = t_ret - (s_ret + e_ret) / 2.0
        return {
            "ticker_return": round(t_ret, 5),
            "market_sector_adjusted_return": round(raw_adj, 5),
            "signed_adjusted_return": round(raw_adj * sign, 5),
        }

    for label, mins in [("30min", 30), ("60min", 60)]:
        r = adjusted_return_at(mins)
        out[f"return_{label}"] = r

    # Close of entry day, next open, next close -- own-clock windows (each
    # leg's own session boundary, same rule applied to ticker/SPY/sector).
    entry_day = entry_bar_ts.date()
    day_bars_t = ticker_df[ticker_df.index.date == entry_day]
    close_bar_t = day_bars_t.iloc[-1] if not day_bars_t.empty else None
    if close_bar_t is not None:
        close_ts = day_bars_t.index[-1]
        s_close = bar_at_or_before(spy_df, close_ts, max_wait_hours=2)
        e_close = bar_at_or_before(sector_df, close_ts, max_wait_hours=2)
        if s_close is not None and e_close is not None:
            t_ret = float(close_bar_t["Close"]) / entry_price - 1.0
            s_ret = float(s_close[1]["Close"]) / spy_entry_price - 1.0
            e_ret = float(e_close[1]["Close"]) / sector_entry_price - 1.0
            raw_adj = t_ret - (s_ret + e_ret) / 2.0
            out["return_close"] = {"ticker_return": round(t_ret, 5),
                                    "market_sector_adjusted_return": round(raw_adj, 5),
                                    "signed_adjusted_return": round(raw_adj * sign, 5)}
        else:
            out["return_close"] = None
    else:
        out["return_close"] = None

    next_day_bars_t = ticker_df[ticker_df.index.date > entry_day]
    if not next_day_bars_t.empty:
        nd = next_day_bars_t.index[0].date()
        nd_bars = ticker_df[ticker_df.index.date == nd]
        open_ts, open_bar = nd_bars.index[0], nd_bars.iloc[0]
        close_ts2, close_bar2 = nd_bars.index[-1], nd_bars.iloc[-1]
        for label, ts_ref, bar_ref in [("next_open", open_ts, open_bar), ("next_close", close_ts2, close_bar2)]:
            s_b = bar_at_or_before(spy_df, ts_ref, max_wait_hours=2)
            e_b = bar_at_or_before(sector_df, ts_ref, max_wait_hours=2)
            if s_b is not None and e_b is not None:
                t_ret = float(bar_ref["Close"]) / entry_price - 1.0
                s_ret = float(s_b[1]["Close"]) / spy_entry_price - 1.0
                e_ret = float(e_b[1]["Close"]) / sector_entry_price - 1.0
                raw_adj = t_ret - (s_ret + e_ret) / 2.0
                out[f"return_{label}"] = {"ticker_return": round(t_ret, 5),
                                           "market_sector_adjusted_return": round(raw_adj, 5),
                                           "signed_adjusted_return": round(raw_adj * sign, 5)}
            else:
                out[f"return_{label}"] = None
    else:
        out["return_next_open"] = None
        out["return_next_close"] = None

    # Stop check + $ per $100 risk, over [entry, entry+60min], via intrabar
    # Low/High (a stop-fill check, distinct from Phase A's banned
    # intrabar-entry-trigger pattern -- see hypotheses-v1.md section 7).
    horizon = entry_bar_ts + timedelta(minutes=60)
    path = path_slice(ticker_df, entry_bar_ts, horizon)
    stop_price = entry_price * (1 - STOP_PCT) if direction == "bullish" else entry_price * (1 + STOP_PCT)
    shares = RISK_DOLLARS / (entry_price * STOP_PCT)
    stopped_out = False
    stop_ts = None
    mfe = 0.0
    mae = 0.0
    mfe_ts = None
    mae_ts = None
    pnl_dollars = None
    if path is not None:
        for ts, bar in path.iterrows():
            high, low = float(bar["High"]), float(bar["Low"])
            if direction == "bullish":
                fav = high - entry_price
                adv = entry_price - low
            else:
                fav = entry_price - low
                adv = high - entry_price
            if fav > mfe:
                mfe, mfe_ts = fav, ts
            if adv > mae:
                mae, mae_ts = adv, ts
            if not stopped_out:
                hit = (low <= stop_price) if direction == "bullish" else (high >= stop_price)
                if hit:
                    stopped_out = True
                    stop_ts = ts
        if stopped_out:
            pnl_dollars = -RISK_DOLLARS
        else:
            end_price = float(path["Close"].iloc[-1])
            move = (end_price - entry_price) if direction == "bullish" else (entry_price - end_price)
            pnl_dollars = shares * move
    out["stop_pct"] = STOP_PCT
    out["stopped_out_before_60min"] = stopped_out
    out["stop_ts_et"] = stop_ts.isoformat() if stop_ts else None
    out["pnl_dollars_per_100_risk"] = round(pnl_dollars, 2) if pnl_dollars is not None else None
    out["max_favorable_move_dollars"] = round(mfe, 4)
    out["max_favorable_move_ts_et"] = mfe_ts.isoformat() if mfe_ts else None
    out["max_adverse_move_dollars"] = round(mae, 4)
    out["max_adverse_move_ts_et"] = mae_ts.isoformat() if mae_ts else None
    return out


def trailing_5day_vol_and_dollarvol(daily_df, before_date) -> dict | None:
    if daily_df is None or daily_df.empty:
        return None
    prior = daily_df[daily_df.index.date < before_date]
    if len(prior) < 5:
        return None
    last5 = prior.iloc[-5:]
    closes = last5["Close"].astype(float).values
    rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes))]
    vol = statistics.pstdev(rets) if len(rets) > 1 else None
    dollar_vol = float((last5["Close"].astype(float) * last5["Volume"].astype(float)).mean())
    return {"trailing5_realized_vol": round(vol, 5) if vol is not None else None,
            "trailing5_avg_dollar_volume": round(dollar_vol, 0)}


def two_prop_z(x1, n1, x2, n2):
    if n1 < 10 or n2 < 10:
        return None
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = (p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) ** 0.5
    if se == 0:
        return None
    z = (p1 - p2) / se
    return {"p1": round(p1, 4), "p2": round(p2, 4), "z": round(z, 3)}


def mean_ci95(values: list[float]) -> dict | None:
    n = len(values)
    if n < 2:
        return {"n": n, "mean": (values[0] if n == 1 else None), "ci95": None}
    m = statistics.mean(values)
    sd = statistics.stdev(values)
    se = sd / (n ** 0.5)
    return {"n": n, "mean": round(m, 5), "sd": round(sd, 5),
            "ci95_lo": round(m - 1.96 * se, 5), "ci95_hi": round(m + 1.96 * se, 5)}


def main() -> int:
    events = load_events()
    print(f"loaded {len(events)} eval-period Lane B events from {EVENTS_CSV}", file=sys.stderr)
    by_ticker_count = {}
    for e in events:
        by_ticker_count[e["ticker"]] = by_ticker_count.get(e["ticker"], 0) + 1
    print(f"eval events by ticker: {by_ticker_count}", file=sys.stderr)

    price_5m = {s: pull_5m(s) for s in ALL_SYMBOLS}
    price_1d = {s: pull_daily(s) for s in ALL_SYMBOLS}

    event_days_by_ticker: dict[str, set] = {t: set() for t in TICKERS}
    for e in events:
        event_days_by_ticker[e["ticker"]].add(e["trading_day_et"])

    median_entry_clock: dict[str, tuple] = {}
    for t in TICKERS:
        t_events = [e for e in events if e["ticker"] == t]
        if not t_events:
            continue
        clocks = sorted(
            (datetime.fromisoformat(e["entry_ts_et"]).hour, datetime.fromisoformat(e["entry_ts_et"]).minute)
            for e in t_events
        )
        median_entry_clock[t] = clocks[len(clocks) // 2]

    # --- Event-arm outcomes ---
    event_results = []
    for e in events:
        ticker = e["ticker"]
        sector = SECTOR_ETF[ticker]
        entry_ts = datetime.fromisoformat(e["entry_ts_et"])
        outcome = compute_outcome(price_5m[ticker], price_5m["SPY"], price_5m[sector],
                                   entry_ts, e["direction_implied"])
        bal = trailing_5day_vol_and_dollarvol(price_1d[ticker], entry_ts.date())
        event_results.append({**e, "outcome": outcome, "balance_inputs": bal})

    # --- Control-arm outcomes: same ticker, non-event days, ticker's own
    # median event entry clock-time-of-day. ---
    control_results = []
    for t in TICKERS:
        if t not in median_entry_clock or price_1d[t] is None:
            continue
        hh, mm = median_entry_clock[t]
        all_days = sorted({d.date() for d in price_1d[t].index})
        eval_days = [d for d in all_days if "2026-07-01" <= d.isoformat() <= "2026-08-22"]
        control_days = [d for d in eval_days if d.isoformat() not in event_days_by_ticker[t]]
        sector = SECTOR_ETF[t]
        for i, d in enumerate(sorted(control_days)):
            entry_ts = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ET)
            # A control day has no real news claim, so there is no genuine
            # direction to sign against. Alternating bullish/bearish
            # deterministically (not randomly) gives a neutral ~50/50 "guessed
            # a direction with no information" baseline instead of always
            # scoring "long" -- which would silently import the market's
            # average upward drift into the control arm and bias the
            # event-vs-control comparison. This keeps "success = signed
            # adjusted return > 0" an apples-to-apples definition in both arms.
            assumed_direction = "bullish" if i % 2 == 0 else "bearish"
            outcome = compute_outcome(price_5m[t], price_5m["SPY"], price_5m[sector], entry_ts, assumed_direction)
            bal = trailing_5day_vol_and_dollarvol(price_1d[t], d)
            control_results.append({"ticker": t, "trading_day_et": d.isoformat(),
                                     "entry_ts_et": entry_ts.isoformat(),
                                     "assumed_direction_for_neutral_baseline": assumed_direction,
                                     "outcome": outcome, "balance_inputs": bal})

    # --- Balance check ---
    balance_by_ticker = {}
    for t in TICKERS:
        ev_bal = [r["balance_inputs"] for r in event_results if r["ticker"] == t and r["balance_inputs"]]
        ct_bal = [r["balance_inputs"] for r in control_results if r["ticker"] == t and r["balance_inputs"]]
        def med(lst, key):
            vals = [x[key] for x in lst if x.get(key) is not None]
            return statistics.median(vals) if vals else None
        balance_by_ticker[t] = {
            "n_event_days": len(ev_bal), "n_control_days": len(ct_bal),
            "event_median_trailing5_vol": med(ev_bal, "trailing5_realized_vol"),
            "control_median_trailing5_vol": med(ct_bal, "trailing5_realized_vol"),
            "event_median_trailing5_dollar_vol": med(ev_bal, "trailing5_avg_dollar_volume"),
            "control_median_trailing5_dollar_vol": med(ct_bal, "trailing5_avg_dollar_volume"),
        }

    # --- Usable-sample filtering + summary stats ---
    usable_events = [r for r in event_results
                      if r["outcome"] and "excluded_reason" not in r["outcome"]
                      and r["outcome"].get("return_60min")]
    excluded_events = [r for r in event_results if r not in usable_events]
    usable_controls = [r for r in control_results
                        if r["outcome"] and "excluded_reason" not in r["outcome"]
                        and r["outcome"].get("return_60min")]

    def signed_60(r):
        return r["outcome"]["return_60min"]["signed_adjusted_return"]

    event_signed_60 = [signed_60(r) for r in usable_events]
    # Controls: also "signed" now, against the deterministic alternating
    # bullish/bearish baseline direction assigned above (a genuine no-
    # information 50/50 guess), so "success" is defined identically in both
    # arms -- not a real-direction vs. no-direction mismatch.
    control_signed_60 = [signed_60(r) for r in usable_controls]

    event_success = sum(1 for v in event_signed_60 if v > 0)
    control_success = sum(1 for v in control_signed_60 if v > 0)

    event_pnl = [r["outcome"]["pnl_dollars_per_100_risk"] for r in usable_events
                 if r["outcome"].get("pnl_dollars_per_100_risk") is not None]
    control_pnl = [r["outcome"]["pnl_dollars_per_100_risk"] for r in usable_controls
                   if r["outcome"].get("pnl_dollars_per_100_risk") is not None]

    # Robustness: drop the single largest-|effect| event, recompute mean signed return.
    robustness = None
    if len(event_signed_60) >= 2:
        idx_max = max(range(len(event_signed_60)), key=lambda i: abs(event_signed_60[i]))
        trimmed = event_signed_60[:idx_max] + event_signed_60[idx_max + 1:]
        robustness = {
            "dropped_event_id": usable_events[idx_max]["event_id"],
            "dropped_signed_return": event_signed_60[idx_max],
            "mean_with_all": round(statistics.mean(event_signed_60), 5),
            "mean_after_drop": round(statistics.mean(trimmed), 5) if trimmed else None,
        }

    result = {
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "hypothesis_version": "hypotheses-v1.md ## Lane B",
        "eval_events_loaded": len(events),
        "eval_events_by_ticker": by_ticker_count,
        "usable_events": len(usable_events),
        "excluded_events": len(excluded_events),
        "excluded_events_reasons": {
            r["event_id"]: r["outcome"].get("excluded_reason") if r["outcome"] else "no_outcome_computed"
            for r in excluded_events
        },
        "usable_controls": len(usable_controls),
        "control_days_by_ticker": {t: len([c for c in control_results if c["ticker"] == t]) for t in TICKERS},
        "median_entry_clock_et_by_ticker": {t: f"{h:02d}:{m:02d}" for t, (h, m) in median_entry_clock.items()},
        "balance_check": balance_by_ticker,
        "primary_outcome": {
            "event_arm": {
                "n": len(event_signed_60),
                "success_rate_signed_adjusted_return_gt_0": {
                    "successes": event_success, "n": len(event_signed_60),
                    "rate": round(event_success / len(event_signed_60), 4) if event_signed_60 else None,
                },
                "signed_adjusted_return_60min": mean_ci95(event_signed_60),
                "pnl_per_100_risk": mean_ci95(event_pnl),
            },
            "control_arm": {
                "n": len(control_signed_60),
                "note": "direction assigned by deterministic bullish/bearish alternation "
                        "per control day (no real news claim exists) -- a neutral "
                        "50/50 guess baseline, not the market's average drift",
                "success_rate_signed_adjusted_return_gt_0": {
                    "successes": control_success, "n": len(control_signed_60),
                    "rate": round(control_success / len(control_signed_60), 4) if control_signed_60 else None,
                },
                "signed_adjusted_return_60min": mean_ci95(control_signed_60),
                "pnl_per_100_risk": mean_ci95(control_pnl),
            },
            "two_proportion_z_event_vs_control": two_prop_z(
                event_success, len(event_signed_60), control_success, len(control_signed_60)),
        },
        "robustness_drop_largest_event": robustness,
        "owner_actionable_window_events": sum(1 for r in usable_events if r["owner_actionable_window"] == "True"),
        "event_level_detail": event_results,
        "control_level_detail": control_results,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "lane_b_eval_results.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"wrote eval results to {out_path}", file=sys.stderr)

    print(json.dumps({k: v for k, v in result.items()
                       if k not in ("event_level_detail", "control_level_detail")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
