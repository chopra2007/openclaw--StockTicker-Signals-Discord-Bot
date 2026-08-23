#!/usr/bin/env python3
"""Phase A test for H5 — catalyst + confirming unusual options flow.

Pre-registered hypothesis (do not edit without bumping the version --
see .omc/research/short-duration-scanner-phaseA/hypotheses-v1.md):

  Setup: a same-morning news catalyst (H1's candidate universe) on a ticker
  that ALSO shows a live unusual-options-flow detection in the same
  direction, using the production options-flow gate exactly as configured
  (config/consensus.yaml options_flow: min_vol_oi=20, min_volume=500,
  min_premium_usd=250000, max_staleness_min=60, nearest_expirations=2).
  Entry trigger: underlying breaks a technical level (VWAP, or the
  premarket/prior-session high or low) in the flow-implied direction within
  the flow detection's staleness window (max_staleness_min after detection).
  Claim: catalyst + confirming flow together outperform catalyst ALONE
  (H1's catalyst-only baseline) over the next 30-60 minutes -- not a random
  baseline. The comparison group is H1's catalyst_results, reused directly
  so both hypotheses test the same candidate universe.

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine import config as cfg  # noqa: E402
from consensus_engine.utils.prices import fetch_history  # noqa: E402
from scripts.research.phase_a_h1_gap_continuation import (  # noqa: E402
    ET,
    LOOKBACK_DAYS as H1_LOOKBACK_DAYS,
    GAP_FLOOR_PCT,
    daily_prior_close,
    evaluate_candidate,
    load_catalyst_candidates,
    minute_bars,
)

PACIFIC = ZoneInfo("America/Los_Angeles")
DB_PATH = ROOT / "consensus.db"
# options_flow only has rows from 2026-06-01 onward (per task brief) -- H5's
# real bound is whichever is more restrictive: this floor, or H1's own
# 40-day minute-bar lookback (LOOKBACK_DAYS below, shared with H1 so both
# hypotheses draw from the identical catalyst-candidate universe).
FLOW_TABLE_FLOOR = datetime(2026, 6, 1, tzinfo=ET)
LOOKBACK_DAYS = H1_LOOKBACK_DAYS
MIN_SAMPLE_FLOOR = 20

# Read the live production gate -- "exactly as configured" means re-reading
# config/consensus.yaml, not hardcoding the numbers quoted in the task brief,
# so a future config change is reflected automatically and this script can't
# silently drift from what's actually running.
MIN_VOL_OI = float(cfg.get("options_flow.min_vol_oi", 20.0))
MIN_VOLUME = int(cfg.get("options_flow.min_volume", 500))
MIN_PREMIUM_USD = float(cfg.get("options_flow.min_premium_usd", 250000.0))
MAX_STALENESS_MIN = int(cfg.get("options_flow.max_staleness_min", 60))
NEAREST_EXPIRATIONS = int(cfg.get("options_flow.nearest_expirations", 2))
SIDE_LABELS_LIVE = bool(cfg.get("options_flow.side_labels_live", False))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def flow_direction(row: sqlite3.Row) -> str:
    """CALL=bullish / PUT=bearish -- the direction definition this repo's
    OWN graded evidence for options_flow actually used (config/consensus.yaml
    options_flow comment block: the min_vol_oi=20 threshold was calibrated by
    grading "CALL vs PUT" against forward SPY-relative return, not buy/sell
    side). It's also the only direction signal available across the WHOLE
    options_flow history (2026-06-01+); the newer BUY/SELL side_labels_live
    refinement only exists from 2026-08-09 (options_flow.side_collect ship
    date) onward and is explicitly marked in config.yaml as "NOT been graded
    against outcomes yet" -- so it is not "the existing production gate" in
    the sense the graded threshold means. See side_confirmation() below for
    how the newer signal is still surfaced, as a secondary/exploratory check,
    not the primary match rule."""
    return "BULLISH" if row["side"] == "CALL" else "BEARISH"


def side_confirmation(row: sqlite3.Row, primary_direction: str) -> str | None:
    """Secondary, exploratory cross-check against the newer BUY/SELL
    side_labels_live signal (see flow_direction docstring for why it is not
    the primary rule). Returns 'agrees' / 'disagrees' / None (side unknown
    for this row -- expected for the large majority of the table, since
    side_collect only started 2026-08-09)."""
    flow_side = row["flow_side"] or ""
    if flow_side in ("", "AMBIGUOUS"):
        return None
    derived = "BULLISH" if (row["side"] == "CALL") == (flow_side == "BUY") else "BEARISH"
    return "agrees" if derived == primary_direction else "disagrees"


def find_flow_match(conn: sqlite3.Connection, ticker: str, day, direction: str) -> dict | None:
    """Earliest options_flow row on `day` that clears the live production
    gate (re-applied here rather than trusted from history -- min_vol_oi was
    raised 10->20 partway through the table's history, 2026-07-09, so an old
    row that only cleared the old bar must not count) AND whose derived
    direction matches the catalyst direction ('long'->BULLISH,
    'short'->BEARISH). One flow signal per ticker/day/direction, earliest
    wins -- mirrors H1's MIN(alerted_at) dedup (plan Section 8.6, "one
    setup, one sample")."""
    day_start = datetime(day.year, day.month, day.day, tzinfo=ET)
    day_end = day_start + timedelta(days=1)
    want = "BULLISH" if direction == "long" else "BEARISH"
    rows = conn.execute(
        """SELECT * FROM options_flow
           WHERE ticker=? AND detected_at>=? AND detected_at<?
             AND vol_oi_ratio>=? AND volume>=? AND premium_usd>=?
           ORDER BY detected_at ASC""",
        (ticker, day_start.timestamp(), day_end.timestamp(),
         MIN_VOL_OI, MIN_VOLUME, MIN_PREMIUM_USD),
    ).fetchall()
    for r in rows:
        if flow_direction(r) == want:
            match = dict(r)
            match["side_confirmation"] = side_confirmation(r, want)
            return match
    return None


def prior_session_high_low(ticker: str, day) -> tuple[float, float] | None:
    """Prior regular-session day's High/Low from the daily series -- same
    source discipline as H1's daily_prior_close (never derive this from
    same-day intraday data)."""
    start = datetime(day.year, day.month, day.day, tzinfo=ET) - timedelta(days=10)
    end = datetime(day.year, day.month, day.day, tzinfo=ET) + timedelta(days=1)
    try:
        df = fetch_history(ticker, start=start, end=end, interval="1d")
    except Exception as exc:
        print(f"  [{ticker} {day}] prior daily history failed: {type(exc).__name__}: {exc}")
        return None
    if df is None or df.empty:
        return None
    priors = df[df.index.date < day]
    if priors.empty:
        return None
    last = priors.iloc[-1]
    return float(last["High"]), float(last["Low"])


def session_vwap(regular_bars):
    """Standard intraday session VWAP: cumulative(typical price x volume) /
    cumulative(volume), reset at the regular-session open."""
    typical = (regular_bars["High"] + regular_bars["Low"] + regular_bars["Close"]) / 3.0
    cum_vol = regular_bars["Volume"].cumsum()
    cum_tp_vol = (typical * regular_bars["Volume"]).cumsum()
    return cum_tp_vol / cum_vol.replace(0, float("nan"))


def find_entry_trigger(
    regular, vwap, premarket_high, premarket_low, prior_high, prior_low,
    direction: str, window_start: datetime, window_end: datetime,
) -> dict | None:
    """First bar in [window_start, window_end] (the flow detection's
    staleness window) whose Close breaks any ONE of the technical levels
    named in H5's entry trigger (VWAP at that bar, premarket high/low, or
    prior-session high/low) in the flow-implied direction."""
    win = regular[(regular.index >= window_start) & (regular.index <= window_end)]
    if win.empty:
        return None
    for ts, bar in win.iterrows():
        close = float(bar["Close"])
        vwap_here = float(vwap.loc[ts]) if ts in vwap.index and vwap.loc[ts] == vwap.loc[ts] else None
        if direction == "long":
            levels = {"vwap": vwap_here, "premarket_high": premarket_high, "prior_high": prior_high}
            broken = [name for name, lvl in levels.items() if lvl is not None and close > lvl]
        else:
            levels = {"vwap": vwap_here, "premarket_low": premarket_low, "prior_low": prior_low}
            broken = [name for name, lvl in levels.items() if lvl is not None and close < lvl]
        if broken:
            return {"trigger_ts": ts, "trigger_price": close, "levels_broken": broken}
    return None


def measure_outcome(regular, direction: str, trigger_ts: datetime, entry_price: float) -> dict | None:
    """Same forward-outcome measurement as H1's evaluate_candidate: 60-minute
    continuation + T+5min-after-delivery remaining-move (delivery = the
    trigger event itself, mirroring H1's fallback for candidates with no
    real posted alert)."""
    horizon_60 = trigger_ts + timedelta(minutes=60)
    t5 = trigger_ts + timedelta(minutes=5)
    window = regular[(regular.index >= trigger_ts) & (regular.index <= horizon_60)]
    if window.empty:
        return None
    end_price = float(window["Close"].iloc[-1])
    at_t5 = regular[(regular.index >= trigger_ts) & (regular.index <= t5)]
    price_at_t5 = float(at_t5["Close"].iloc[-1]) if not at_t5.empty else entry_price

    if direction == "long":
        total_move = end_price - entry_price
        move_at_t5 = price_at_t5 - entry_price
        continued = end_price > entry_price
    else:
        total_move = entry_price - end_price
        move_at_t5 = entry_price - price_at_t5
        continued = end_price < entry_price

    remaining_after_t5 = total_move - move_at_t5
    remaining_pct = (
        (remaining_after_t5 / total_move * 100.0) if abs(total_move) > 1e-9 else None
    )
    return {
        "entry_price": round(entry_price, 4),
        "price_at_t5": round(price_at_t5, 4),
        "end_price_60min": round(end_price, 4),
        "total_move_pct_of_entry": round(total_move / entry_price * 100.0, 3),
        "continued_60min": continued,
        "remaining_move_pct_of_total_after_t5": (
            round(remaining_pct, 1) if remaining_pct is not None else None
        ),
    }


def load_h1_catalyst_baseline(h1_results_path: Path) -> tuple[list[dict], dict]:
    """Returns (catalyst_results, meta). Prefers h1_results.json -- per the
    task brief, H1 and H5 share the same catalyst-candidate universe, so
    reuse it directly rather than re-deriving. Falls back to H1's own method
    (same 40-day window, same gap/trigger logic) if that file is absent."""
    if h1_results_path.exists():
        data = json.loads(h1_results_path.read_text())
        return data["catalyst_results"], {
            "source": str(h1_results_path), "generated_at": data.get("generated_at_pacific"),
        }
    print(f"WARNING: {h1_results_path} not found -- re-deriving H1's catalyst "
          f"candidates directly via its own method")
    since_ts = time.time() - LOOKBACK_DAYS * 86400
    conn = _connect()
    try:
        candidates = load_catalyst_candidates(conn, since_ts)
    finally:
        conn.close()
    results = []
    for row in candidates:
        ticker = row["ticker"].upper()
        alert_dt = datetime.fromtimestamp(row["first_alert_at"], ET)
        day = alert_dt.date()
        prior = daily_prior_close(ticker, day)
        if prior is None:
            continue
        gap, _prior_close = prior
        if abs(gap) < GAP_FLOOR_PCT:
            continue
        outcome = evaluate_candidate(ticker, day, alert_dt, gap)
        if outcome is not None:
            outcome["catalyst_type"] = row["catalyst_type"]
            results.append(outcome)
    return results, {"source": "re-derived (h1_results.json missing)", "generated_at": None}


def summarize(records: list[dict]) -> dict:
    triggered = [r for r in records if r.get("triggered")]
    cont = [r["continued_60min"] for r in triggered if "continued_60min" in r]
    rem = [r["remaining_move_pct_of_total_after_t5"] for r in triggered
           if r.get("remaining_move_pct_of_total_after_t5") is not None]
    return {
        "n_candidates": len(records),
        "n_triggered": len(triggered),
        "continuation_rate_60min": (sum(cont) / len(cont)) if cont else None,
        "continuation_n": len(cont),
        "median_remaining_move_pct_after_t5": statistics.median(rem) if rem else None,
        "remaining_move_n": len(rem),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="cap the number of H1 catalyst candidates probed (for a quick run)")
    parser.add_argument("--h1-results", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h1_results.json")
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h5_results.json")
    args = parser.parse_args()

    catalyst_baseline, baseline_meta = load_h1_catalyst_baseline(args.h1_results)
    print(f"loaded {len(catalyst_baseline)} H1 catalyst candidates as the shared "
          f"candidate universe (source: {baseline_meta['source']})")
    if args.limit:
        catalyst_baseline = catalyst_baseline[: args.limit]

    conn = _connect()
    evaluated: list[dict] = []
    try:
        for i, cand in enumerate(catalyst_baseline):
            ticker = cand["ticker"].upper()
            day = datetime.strptime(cand["day"], "%Y-%m-%d").date()
            direction = cand["direction"]
            record = {
                "ticker": ticker, "day": str(day), "direction": direction,
                "gap_pct": cand.get("gap_pct"), "catalyst_type": cand.get("catalyst_type"),
                "has_flow": False,
            }
            day_start = datetime(day.year, day.month, day.day, tzinfo=ET)
            if day_start < FLOW_TABLE_FLOOR:
                record["reason"] = "before options_flow table floor (2026-06-01)"
                evaluated.append(record)
                continue

            print(f"[{i+1}/{len(catalyst_baseline)}] {ticker} {day} {direction} -- "
                  f"checking options_flow for a same-direction gate-passing detection")
            flow_row = find_flow_match(conn, ticker, day, direction)
            if flow_row is None:
                evaluated.append(record)
                continue

            record["has_flow"] = True
            record["flow_detected_at_et"] = datetime.fromtimestamp(
                flow_row["detected_at"], ET).isoformat()
            record["flow_contract_side"] = flow_row["side"]
            record["flow_buy_sell_side"] = flow_row["flow_side"] or None
            record["flow_side_confirmation"] = flow_row["side_confirmation"]
            record["flow_vol_oi_ratio"] = flow_row["vol_oi_ratio"]
            record["flow_volume"] = flow_row["volume"]
            record["flow_premium_usd"] = flow_row["premium_usd"]
            record["flow_contract"] = flow_row["contract_symbol"]

            bars = minute_bars(ticker, day)
            if bars is None or bars.empty:
                record["triggered"] = None
                record["reason"] = "no minute bars"
                evaluated.append(record)
                continue
            premarket = bars[bars.index.time < dtime(9, 30)]
            # True regular session only (9:30-16:00 ET) for VWAP and the
            # technical-level breakout check -- VWAP is a regular-hours
            # metric and after-hours bars are thin/non-representative, so
            # they'd corrupt both the average and a "break" read. Kept
            # separate from `after_open` below, which intentionally DOES
            # include after-hours, for the forward-outcome measurement.
            regular = bars[(bars.index.time >= dtime(9, 30)) & (bars.index.time < dtime(16, 0))]
            after_open = bars[bars.index.time >= dtime(9, 30)]
            if regular.empty:
                record["triggered"] = None
                record["reason"] = "no regular-session bars"
                evaluated.append(record)
                continue
            premarket_high = float(premarket["High"].max()) if not premarket.empty else None
            premarket_low = float(premarket["Low"].min()) if not premarket.empty else None
            prior_hl = prior_session_high_low(ticker, day)
            prior_high, prior_low = prior_hl if prior_hl else (None, None)
            vwap = session_vwap(regular)

            detected_dt = datetime.fromtimestamp(flow_row["detected_at"], ET)
            window_start = max(detected_dt, regular.index[0])
            window_end = min(detected_dt + timedelta(minutes=MAX_STALENESS_MIN), regular.index[-1])
            trig = find_entry_trigger(
                regular, vwap, premarket_high, premarket_low, prior_high, prior_low,
                direction, window_start, window_end,
            )
            if trig is None:
                record["triggered"] = False
                evaluated.append(record)
                continue

            # Forward outcome uses after_open (extends into after-hours) so a
            # late-day trigger (e.g. detected near the 16:00 close) still gets
            # a real forward read instead of being silently starved of bars --
            # labeled honestly, not hidden, in the reason/verdict if it happens.
            outcome = measure_outcome(after_open, direction, trig["trigger_ts"], trig["trigger_price"])
            if outcome is None:
                record["triggered"] = False
                record["reason"] = "no forward-window data after trigger"
                evaluated.append(record)
                continue

            record["triggered"] = True
            record["trigger_ts_et"] = trig["trigger_ts"].isoformat()
            record["levels_broken"] = trig["levels_broken"]
            record.update(outcome)
            evaluated.append(record)
    finally:
        conn.close()

    flow_confirmed = [r for r in evaluated if r["has_flow"]]
    baseline_summary = summarize(catalyst_baseline)
    h5_summary = summarize(flow_confirmed)

    out = {
        "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "options_flow_table_floor": FLOW_TABLE_FLOOR.isoformat(),
        "gate_used": {
            "min_vol_oi": MIN_VOL_OI, "min_volume": MIN_VOLUME,
            "min_premium_usd": MIN_PREMIUM_USD, "max_staleness_min": MAX_STALENESS_MIN,
            "nearest_expirations": NEAREST_EXPIRATIONS,
        },
        "direction_rule": "CALL=bullish/PUT=bearish (the definition options_flow's own "
                           "graded min_vol_oi evidence used); side_labels_live="
                           f"{SIDE_LABELS_LIVE} BUY/SELL refinement logged per-row as an "
                           "unproven secondary cross-check only (flow_side_confirmation), see script docstring",
        "catalyst_universe_source": baseline_meta,
        "catalyst_universe_count": len(catalyst_baseline),
        "flow_confirmed_count": len(flow_confirmed),
        "baseline_catalyst_only": baseline_summary,
        "h5_catalyst_plus_flow": h5_summary,
        "all_catalyst_candidates_checked": evaluated,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {len(evaluated)} checked candidates ({len(flow_confirmed)} flow-confirmed, "
          f"{h5_summary['n_triggered']} triggered) to {args.out}")
    print(f"baseline (catalyst-only, from {baseline_meta['source']}): "
          f"n={baseline_summary['n_candidates']} triggered={baseline_summary['n_triggered']} "
          f"continuation_rate={baseline_summary['continuation_rate_60min']}")
    print(f"H5 (catalyst+flow): n_flow_confirmed={h5_summary['n_candidates']} "
          f"triggered={h5_summary['n_triggered']} continuation_rate={h5_summary['continuation_rate_60min']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
