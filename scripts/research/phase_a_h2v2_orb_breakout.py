#!/usr/bin/env python3
"""Phase A test for H2-v2 -- opening-range breakout, geometry-neutral outcome metric.

Pre-registered hypothesis (do not edit without bumping the version --
see .omc/research/short-duration-scanner-phaseA/hypotheses-v2.md, section
"H2-v2 -- Opening-range breakout, geometry-neutral outcome metric"):

  Setup and entry trigger: UNCHANGED from H2 v1 (see
  scripts/research/phase_a_h2_orb_breakout.py, which this script reuses
  candidate-detection logic from). First-15-minute opening range
  (09:30-09:45 ET) established; candidate's relative volume in that window
  is >=2.0x its own trailing norm. Entry trigger: price breaks the
  opening-range high (long) or low (short) within the first 45 minutes
  after the open, on rising volume (breakout minute's own volume above the
  range's average minute volume).

  Claim (v2 outcome metric): price is still net favorable (beyond a small
  noise band, +/-0.1%) in the breakout direction at the 60-minute primary
  horizon after the trigger, more often than a magnitude- and time-matched
  sample of non-breakout setups in the same universe on the same day.

WHY THIS SCRIPT EXISTS (do not re-derive H2 v1's win metric here): the
independent audit (phaseA-audit.md, H2 section) proved v1's "reach 1x
range-height before returning to the range midpoint" win metric is a
two-barrier race whose win rate is driven almost entirely by how far the
entry price already sits from the midpoint stop -- a geometry effect, not a
directional signal. Breakout entries are, by construction, always outside
the range (median entry-to-stop distance 0.622 range-units); control
entries mostly sit inside it (median 0.250). Matched on stop distance the
gap collapsed (36.9% vs 28.0%, overlapping CIs); against a driftless
random-walk null the breakout group scored BELOW chance (z=-0.57). v2
replaces that metric with the same continuation-rate convention used
elsewhere in Phase A (H1/H3/H5): net favorable vs. unfavorable at a fixed
forward horizon, which does not depend on where an artificial target/stop
sits relative to entry.

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.

Control-group proxy: UNCHANGED from v1 (this was not the defect the audit
found -- see hypotheses-v2.md, "Same setup and entry trigger as H2 v1 ...
One defect the audit found is fixed"). The control arm is every ticker-day
whose opening range ALSO cleared the rvol>=2.0 setup bar but where no
volume-confirmed break happened within the 45-minute window. Both arms are
built from the same per-ticker daily scan, so universe and window are
identical between them by construction. The control's pseudo-entry point
is the close of the last bar in the 45-minute breakout window (the same
clock-time cutoff a real trigger must fire within), with direction taken
from which side of the range midpoint price sits on at that mark.

RVOL proxy: UNCHANGED from v1 -- first-15-minute volume on day D divided by
the mean first-15-minute volume over the trailing lookback (up to 20 prior
days, requiring at least 10 -- MIN_TRAILING_DAYS) of days in this same
window for the same ticker.

Universe sampling: v1 capped its universe with `ORDER BY ticker LIMIT 300`,
which silently restricted the scan to an alphabetical prefix (AAL..DECK,
~179 of 1,115 tickers -- audit finding, secondary issue). v2 fixes this:
when a cap is applied it takes an EVENLY-SPACED sample across the full
alphabetically-sorted universe (a fixed stride, deterministic and
reproducible) instead of a prefix, so the scanned tickers spread across the
whole watchlist rather than clustering at the start of the alphabet.
"""
from __future__ import annotations

import argparse
import json
import math
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
NOISE_BAND_PCT = 0.1  # +/-0.1% -- H2-v2's pre-registered noise band
REMAINING_MOVE_FLOOR_PCT = 30.0  # shared T+5min-after-trigger floor used across Phase A

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

    Capped with an EVENLY-SPACED sample across the sorted universe, not an
    alphabetical prefix (v1 defect -- see module docstring)."""
    since_ts = time_module.time() - 180 * 86400
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM alert_history WHERE alerted_at >= ? ORDER BY ticker",
        (since_ts,),
    ).fetchall()
    tickers = [r["ticker"].upper() for r in rows]
    if limit and limit < len(tickers):
        step = len(tickers) / limit
        tickers = [tickers[int(i * step)] for i in range(limit)]
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


def _measure_outcome(day_bars, entry_ts, entry_price: float, direction: str) -> dict | None:
    """H2-v2's geometry-neutral outcome: is price still net favorable (beyond
    the +/-0.1% noise band) in the breakout direction at the 60-minute
    primary horizon, plus the T+5min-after-trigger remaining-move figure
    using the same convention as H1/H3/H5. Unlike v1, this does NOT run a
    target-vs-midpoint race to session close -- everything is scored inside
    the fixed 60-minute window, so the metric can't inherit the entry-to-stop
    geometry bias the audit found."""
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
    total_move_pct = total_move / entry_price * 100.0
    remaining_pct = (
        remaining_after_t5 / total_move * 100.0 if abs(total_move) > 1e-9 else None
    )

    return {
        "end_price_60min": round(end_price, 4),
        "price_at_t5": round(price_at_t5, 4),
        "total_move_pct_of_entry": round(total_move_pct, 3),
        "remaining_move_pct_of_total_after_t5": (
            round(remaining_pct, 1) if remaining_pct is not None else None
        ),
        "favorable_60min": total_move_pct > NOISE_BAND_PCT,
        "unfavorable_60min": total_move_pct < -NOISE_BAND_PCT,
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
        or_mid, avg_minute_vol = rec["or_mid"], rec["avg_minute_vol"]

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
            "or_range": round(rec["or_range"], 4), "or_mid": round(or_mid, 4),
            "rvol_15min": round(rvol, 2),
        }

        if trigger is not None:
            direction, entry_ts, entry_price = trigger
            candidate.update({
                "group": "breakout", "triggered": True, "direction": direction,
                "entry_time": str(entry_ts), "entry_price": entry_price,
            })
            outcome = _measure_outcome(day_bars, entry_ts, entry_price, direction)
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
            outcome = _measure_outcome(day_bars, entry_ts, entry_price, direction)
            if outcome is None:
                continue
            candidate.update(outcome)
            results.append(candidate)
            counts["control"] += 1

    return {"results": results, "counts": counts}


def _wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score 95% confidence interval for a binomial proportion,
    returned as (low_pct, high_pct). Same method used to check H2 v1's
    numbers in phaseA-audit.md."""
    if n == 0:
        return None
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    adj = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    low = (centre - adj) / denom
    high = (centre + adj) / denom
    return round(low * 100.0, 1), round(high * 100.0, 1)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return round((s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0), 3)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_UNIVERSE_LIMIT,
                         help="cap the number of universe tickers scanned")
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h2v2_results.json")
    args = parser.parse_args()

    conn = _connect()
    try:
        universe = load_control_universe(conn, args.limit)
    finally:
        conn.close()
    print(f"loaded {len(universe)} candidate universe tickers "
          f"(evenly-spaced sample of alert_history, last 180 days)")

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

    breakout_fav = sum(1 for r in breakout_results if r["favorable_60min"])
    control_fav = sum(1 for r in control_results if r["favorable_60min"])
    breakout_ci = _wilson_ci(breakout_fav, len(breakout_results))
    control_ci = _wilson_ci(control_fav, len(control_results))

    breakout_remaining = [r["remaining_move_pct_of_total_after_t5"]
                           for r in breakout_results
                           if r["remaining_move_pct_of_total_after_t5"] is not None]
    breakout_remaining_fav_only = [
        r["remaining_move_pct_of_total_after_t5"] for r in breakout_results
        if r["favorable_60min"] and r["remaining_move_pct_of_total_after_t5"] is not None
    ]
    control_remaining = [r["remaining_move_pct_of_total_after_t5"]
                          for r in control_results
                          if r["remaining_move_pct_of_total_after_t5"] is not None]

    summary = {
        "generated_at_pacific": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        "hypothesis": "H2-v2",
        "lookback_days": LOOKBACK_DAYS,
        "rvol_threshold": RVOL_THRESHOLD,
        "min_trailing_days": MIN_TRAILING_DAYS,
        "trailing_window_days": TRAILING_WINDOW_DAYS,
        "breakout_window_minutes": BREAKOUT_WINDOW_MINUTES,
        "primary_horizon_minutes": PRIMARY_HORIZON_MINUTES,
        "noise_band_pct": NOISE_BAND_PCT,
        "remaining_move_floor_pct": REMAINING_MOVE_FLOOR_PCT,
        "min_sample_floor": MIN_SAMPLE_FLOOR,
        "universe_size": len(universe),
        "scan_totals": totals,
        "counts": {
            "breakout_scored": len(breakout_results),
            "control_scored": len(control_results),
        },
        "breakout_favorable_60min": f"{breakout_fav}/{len(breakout_results)}",
        "control_favorable_60min": f"{control_fav}/{len(control_results)}",
        "breakout_favorable_60min_rate_pct": (
            round(breakout_fav / len(breakout_results) * 100.0, 1) if breakout_results else None
        ),
        "control_favorable_60min_rate_pct": (
            round(control_fav / len(control_results) * 100.0, 1) if control_results else None
        ),
        "breakout_wilson_95ci_pct": breakout_ci,
        "control_wilson_95ci_pct": control_ci,
        "breakout_median_remaining_move_pct_after_t5": _median(breakout_remaining),
        "breakout_median_remaining_move_pct_after_t5_favorable_only": _median(breakout_remaining_fav_only),
        "control_median_remaining_move_pct_after_t5": _median(control_remaining),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        **summary,
        "breakout_results": breakout_results,
        "control_results": control_results,
    }, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"wrote {len(breakout_results)} breakout + {len(control_results)} control "
          f"evaluated candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
