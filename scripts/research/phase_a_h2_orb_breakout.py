#!/usr/bin/env python3
"""Phase A test for H2 -- opening-range breakout with volume confirmation.

Pre-registered hypothesis (do not edit without bumping the version --
see .omc/research/short-duration-scanner-phaseA/hypotheses-v1.md):

  Setup: first-15-minute opening range (09:30-09:45 ET) established;
  candidate's relative volume in that window is >=2.0x its own trailing
  norm (reusing config/consensus.yaml technical.filters.rvol_threshold: 2.0).
  Entry trigger: price breaks the opening-range high (long) or low (short)
  within the first 45 minutes after the open, on rising volume (the
  breakout minute's own volume above the range's average minute volume).
  Claim: the breakout continues beyond the range's own height more often,
  and captures more of that follow-through, than a magnitude- and
  time-matched sample of non-breakout moves in the same universe.

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.

Control-group proxy (documented since the plan leaves the exact matching
method to the test script): the "non-breakout" comparison arm is every
ticker-day whose opening range ALSO cleared the rvol>=2.0 setup bar but
where no volume-confirmed break happened within the 45-minute window. This
keeps everything else equal (same volume-elevated mornings, same universe,
same day) except the one thing under test -- whether the entry trigger
itself adds edge -- and it reuses that day's own opening-range height/
midpoint as the outcome scaffold, which is what gives the match its
"magnitude" component. The control's pseudo-entry point is the close of the
last bar in the 45-minute window (i.e. the same clock-time cutoff real
triggers must fire within), with direction taken from which side of the
range midpoint price is sitting on at that mark. This is an endogenous
control drawn from data the setup screen already produces, not a separately
sampled population -- chosen deliberately over an ad hoc synthetic sample
so nothing here is a free parameter that could be tuned after seeing results.

RVOL proxy: first-15-minute volume on day D divided by the mean
first-15-minute volume over the trailing lookback (up to 20 prior days,
requiring at least 10 -- see MIN_TRAILING_DAYS) of days in this same window
for the same ticker. A true 20-day trailing baseline needs 20 prior days of
clean data; the available window is only ~34 trading days total, so the
first ~10-14 days of each ticker's window never get evaluated (no stable
baseline yet) -- this is a real, disclosed limitation of testing on a short
lookback, not a modeling choice.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time as time_module
from datetime import datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402

ET = ZoneInfo("America/New_York")
DB_PATH = ROOT / "consensus.db"

# Regular-session-only minute bars are reliable back to ~47-49 calendar days
# (verified live 2026-08-22, commit c4b0cbd). H2's setup is entirely
# regular-session (first 15 minutes after the 09:30 open), so unlike H1 it
# needs no premarket data and can use the fuller window with
# extended_hours=False.
LOOKBACK_DAYS = 47
RVOL_THRESHOLD = 2.0  # config/consensus.yaml technical.filters.rvol_threshold
MIN_TRAILING_DAYS = 10  # floor for a usable trailing-volume baseline (see docstring)
TRAILING_WINDOW_DAYS = 20
OR_WINDOW_MINUTES = 15  # 09:30-09:45
BREAKOUT_WINDOW_MINUTES = 45  # 09:30-10:15, i.e. minutes 16-45 after the OR closes
PRIMARY_HORIZON_MINUTES = 60
MIN_SAMPLE_FLOOR = 20
DEFAULT_UNIVERSE_LIMIT = 300

OR_START, OR_END = dtime(9, 30), dtime(9, 44)
BREAKOUT_START, BREAKOUT_END = dtime(9, 45), dtime(10, 15)  # END exclusive


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def load_control_universe(conn: sqlite3.Connection, limit: int | None) -> list[str]:
    """Tickers the bot already watches (alert history over the last 6 months)
    -- a bounded stand-in for 'the market' per plan Section 9 (stock-level
    discovery within current data limits), not a full exchange scan.
    (Same approach as phase_a_h1_gap_continuation.load_control_universe.)"""
    since_ts = time_module.time() - 180 * 86400
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM alert_history WHERE alerted_at >= ? ORDER BY ticker",
        (since_ts,),
    ).fetchall()
    tickers = [r["ticker"].upper() for r in rows]
    if limit:
        tickers = tickers[:limit]
    return tickers


def fetch_minute_bars(ticker: str, since_dt: datetime, until_dt: datetime):
    """Whole ~47-day regular-session minute-bar history in a single call per
    ticker (verified live: one get_price_history call with a wide date
    window returns the full available range, not just a slice)."""
    try:
        df = schwab_client.get_price_history(
            ticker, interval="1m", start=since_dt, end=until_dt, extended_hours=False,
        )
    except Exception as exc:
        print(f"  [{ticker}] minute bars failed: {type(exc).__name__}: {exc}")
        return None
    if df is None or df.empty:
        return None
    return df


def _measure_outcome(day_bars, entry_ts, entry_price: float, direction: str,
                      or_range: float, or_mid: float) -> dict | None:
    """T+5min remaining-move figure over the 60-minute primary horizon
    (delivery = breakout-trigger time, per plan instructions -- there's no
    alert to anchor to for this hypothesis), plus H2's own win test (move
    reaches 1x range height from the entry point without first returning to
    the range midpoint) which is allowed to run to session close."""
    horizon_end = entry_ts + timedelta(minutes=PRIMARY_HORIZON_MINUTES)
    window = day_bars[(day_bars.index >= entry_ts) & (day_bars.index <= horizon_end)]
    if len(window) < 2:
        return None  # not enough forward bars for even a T+5 read

    end_price = float(window["Close"].iloc[-1])
    t5 = entry_ts + timedelta(minutes=5)
    at_t5 = window[window.index <= t5]
    price_at_t5 = float(at_t5["Close"].iloc[-1]) if not at_t5.empty else entry_price

    if direction == "long":
        total_move = end_price - entry_price
        move_at_t5 = price_at_t5 - entry_price
    else:
        total_move = entry_price - end_price
        move_at_t5 = entry_price - price_at_t5
    remaining_after_t5 = total_move - move_at_t5
    remaining_pct = (
        remaining_after_t5 / total_move * 100.0 if abs(total_move) > 1e-9 else None
    )

    # Win test: scan from the entry bar to session close (may extend past
    # the 60-minute primary horizon per H2's "Holding window" note).
    full_window = day_bars[day_bars.index >= entry_ts]
    target = entry_price + or_range if direction == "long" else entry_price - or_range
    win = False
    outcome_resolved = False
    for i, (_ts, row) in enumerate(full_window.iterrows()):
        high, low = float(row["High"]), float(row["Low"])
        if i == 0:
            # Entry bar itself: by construction its close already broke the OR edge,
            # so only a same-bar target hit is checkable (a midpoint return on the
            # entry bar would be a data anomaly, not a real reversal signal).
            if direction == "long" and high >= target:
                win, outcome_resolved = True, True
                break
            if direction == "short" and low <= target:
                win, outcome_resolved = True, True
                break
            continue
        hit_mid = (low <= or_mid) if direction == "long" else (high >= or_mid)
        hit_target = (high >= target) if direction == "long" else (low <= target)
        if hit_mid:
            # Conservative tie-break: if the same bar also reaches target, OHLC bars
            # can't tell us which happened first intra-minute, so a midpoint touch
            # counts as the loss outcome either way.
            win, outcome_resolved = False, True
            break
        if hit_target:
            win, outcome_resolved = True, True
            break

    return {
        "end_price_60min": round(end_price, 4),
        "price_at_t5": round(price_at_t5, 4),
        "total_move_pct_of_entry": round(total_move / entry_price * 100.0, 3),
        "remaining_move_pct_of_total_after_t5": (
            round(remaining_pct, 1) if remaining_pct is not None else None
        ),
        "win_target_reached_no_midpoint_return": win,
        "win_outcome_resolved": outcome_resolved,
    }


def analyze_ticker(ticker: str, since_dt: datetime, until_dt: datetime) -> dict:
    counts = {
        "days_valid_or": 0, "days_with_baseline": 0, "days_qualifying_setup": 0,
        "triggered": 0, "control": 0,
    }
    df = fetch_minute_bars(ticker, since_dt, until_dt)
    if df is None:
        return {"results": [], "counts": counts}

    daily: dict = {}
    for day in sorted(set(df.index.date)):
        day_bars = df[df.index.date == day]
        first15 = day_bars[(day_bars.index.time >= OR_START) & (day_bars.index.time <= OR_END)]
        if len(first15) < OR_WINDOW_MINUTES:
            continue  # incomplete opening-range data for this day -- not evaluable
        or_high = float(first15["High"].max())
        or_low = float(first15["Low"].min())
        if or_high <= or_low:
            continue
        first15_vol = float(first15["Volume"].sum())
        daily[day] = {
            "day_bars": day_bars,
            "or_high": or_high, "or_low": or_low,
            "or_mid": (or_high + or_low) / 2.0, "or_range": or_high - or_low,
            "first15_vol": first15_vol, "avg_minute_vol": first15_vol / OR_WINDOW_MINUTES,
        }
    counts["days_valid_or"] = len(daily)

    results = []
    ordered_days = sorted(daily.keys())
    for idx, day in enumerate(ordered_days):
        prior_days = ordered_days[:idx]
        if len(prior_days) < MIN_TRAILING_DAYS:
            continue  # no stable trailing-volume baseline yet (see module docstring)
        trailing = prior_days[-TRAILING_WINDOW_DAYS:]
        baseline_vol = sum(daily[d]["first15_vol"] for d in trailing) / len(trailing)
        if baseline_vol <= 0:
            continue
        counts["days_with_baseline"] += 1
        rvol = daily[day]["first15_vol"] / baseline_vol
        if rvol < RVOL_THRESHOLD:
            continue  # never clears H2's own setup bar -- not a "setup", nothing to log
        counts["days_qualifying_setup"] += 1

        rec = daily[day]
        day_bars, or_high, or_low = rec["day_bars"], rec["or_high"], rec["or_low"]
        or_mid, or_range, avg_minute_vol = rec["or_mid"], rec["or_range"], rec["avg_minute_vol"]

        breakout_window = day_bars[
            (day_bars.index.time >= BREAKOUT_START) & (day_bars.index.time < BREAKOUT_END)
        ]
        trigger = None
        for ts, row in breakout_window.iterrows():
            if row["Close"] > or_high and row["Volume"] > avg_minute_vol:
                trigger = ("long", ts, float(row["Close"]))
                break
            if row["Close"] < or_low and row["Volume"] > avg_minute_vol:
                trigger = ("short", ts, float(row["Close"]))
                break

        candidate = {
            "ticker": ticker, "day": str(day),
            "or_high": round(or_high, 4), "or_low": round(or_low, 4),
            "or_range": round(or_range, 4), "or_mid": round(or_mid, 4),
            "rvol_15min": round(rvol, 2),
        }

        if trigger is not None:
            direction, entry_ts, entry_price = trigger
            candidate.update({
                "group": "breakout", "triggered": True, "direction": direction,
                "entry_time": str(entry_ts), "entry_price": entry_price,
            })
            outcome = _measure_outcome(day_bars, entry_ts, entry_price, direction, or_range, or_mid)
            if outcome is None:
                continue  # not enough forward data to score this candidate either way
            candidate.update(outcome)
            results.append(candidate)
            counts["triggered"] += 1
        else:
            if breakout_window.empty:
                continue
            entry_ts = breakout_window.index[-1]
            entry_price = float(breakout_window["Close"].iloc[-1])
            if entry_price == or_mid:
                continue  # ambiguous direction at the pseudo-entry -- drop
            direction = "long" if entry_price > or_mid else "short"
            candidate.update({
                "group": "control", "triggered": False, "direction": direction,
                "entry_time": str(entry_ts), "entry_price": entry_price,
            })
            outcome = _measure_outcome(day_bars, entry_ts, entry_price, direction, or_range, or_mid)
            if outcome is None:
                continue
            candidate.update(outcome)
            results.append(candidate)
            counts["control"] += 1

    return {"results": results, "counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_UNIVERSE_LIMIT,
                         help="cap the number of universe tickers scanned")
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h2_results.json")
    args = parser.parse_args()

    conn = _connect()
    try:
        universe = load_control_universe(conn, args.limit)
    finally:
        conn.close()
    print(f"loaded {len(universe)} candidate universe tickers (alert_history, last 180 days)")

    until_dt = datetime.now(ET)
    since_dt = until_dt - timedelta(days=LOOKBACK_DAYS)

    all_results: list[dict] = []
    totals = {"days_valid_or": 0, "days_with_baseline": 0, "days_qualifying_setup": 0,
              "triggered": 0, "control": 0}
    for i, ticker in enumerate(universe):
        print(f"[{i+1}/{len(universe)}] {ticker} -- scanning {LOOKBACK_DAYS}-day window")
        out = analyze_ticker(ticker, since_dt, until_dt)
        all_results.extend(out["results"])
        for k, v in out["counts"].items():
            totals[k] += v

    breakout_results = [r for r in all_results if r["group"] == "breakout"]
    control_results = [r for r in all_results if r["group"] == "control"]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "generated_at_pacific": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "rvol_threshold": RVOL_THRESHOLD,
        "min_trailing_days": MIN_TRAILING_DAYS,
        "trailing_window_days": TRAILING_WINDOW_DAYS,
        "breakout_window_minutes": BREAKOUT_WINDOW_MINUTES,
        "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "universe_size": len(universe),
        "scan_totals": totals,
        "breakout_results": breakout_results,
        "control_results": control_results,
    }, indent=2))
    print(f"scan totals: {totals}")
    print(f"wrote {len(breakout_results)} breakout + {len(control_results)} control "
          f"evaluated candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
