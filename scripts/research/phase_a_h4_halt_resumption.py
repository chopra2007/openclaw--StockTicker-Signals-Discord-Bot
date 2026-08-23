#!/usr/bin/env python3
"""Phase A test for H4 -- trading-halt resumption continuation.

Pre-registered hypothesis (do not edit without bumping the version --
see .omc/research/short-duration-scanner-phaseA/hypotheses-v1.md):

  Setup: stock is halted for a volatility/news pause during the regular
  session, per the trading_halts feed (r14, Nasdaq/NYSE trade-halts RSS).
  Entry trigger: on resumption, price breaks the pre-halt directional
  extreme (the high just before an up-halt, the low just before a
  down-halt) within the first few minutes of trading resuming.
  Claim: the stock continues in the pre-halt direction over the following
  15-60 minutes; no matched control required (a halt is itself the rare,
  unambiguous trigger).

FIRST STEP finding (this script also prints it): the `trading_halts` table
only has rows going back to when features.trading_halts.enabled was flipped
to true (commit c4b0cbd-era discover-next-features flip, 2026-08-16) -- the
Nasdaq RSS feed is a LIVE feed, polled every 60s, not a queryable history, so
there is no way to backfill halts from before the flag flip. As of this run
that is ~5 calendar days of coverage (2026-08-17 through 2026-08-21), not the
~47-day minute-bar window available for the other hypotheses. The table is
also filtered to `db.get_active_tickers(min_signals=1)` at poll time -- i.e.
only halts on tickers the bot already tracks, not every Nasdaq/NYSE halt.

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
DB_PATH = ROOT / "consensus.db"

# Pre-halt lookback used to classify the halt as "up" (price rising into the
# halt) vs "down" (price falling into the halt), and to find the directional
# extreme the entry trigger has to break. Bounded by session start (a halt in
# the first few minutes of premarket has less than this available).
PRE_HALT_LOOKBACK_MIN = 30
# Entry trigger must fire within this many minutes of resumption, per the
# pre-registered "within the first few minutes of trading resuming".
ENTRY_WINDOW_MIN = 5
# Primary continuation horizon -- matches the shared Batch 2
# primary_horizon_seconds: 3600 convention already used for H1-H3; H4's
# pre-registered window (15-60min) fits inside it. 15/30min logged as
# secondary, same as the reaction-delay gate's 3-minute secondary figure.
PRIMARY_HORIZON_MIN = 60
SECONDARY_HORIZONS_MIN = [15, 30]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _parse_feed_ts(raw: str | None) -> datetime | None:
    """Parse a trading_halts.halt_ts / resumption_ts value:
    'MM/DD/YYYY|HH:MM:SS[.mmm]', stored ET (see scanners/trading_halts.py)."""
    if not raw or "|" not in raw:
        return None
    date_part, time_part = raw.split("|", 1)
    time_part = time_part.split(".")[0]
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%m/%d/%Y %H:%M:%S").replace(tzinfo=ET)
    except ValueError:
        return None


def load_halt_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT symbol, halt_ts, reason_code, resumption_ts, alerted_at
           FROM trading_halts ORDER BY alerted_at"""
    ).fetchall()
    return [dict(r) for r in rows]


def minute_bars_for_day(ticker: str, day) -> "object | None":
    """Full extended-hours session (07:00-19:59 ET) for one calendar day.
    get_price_history returns the whole session regardless of start/end for
    intraday intervals (verified live, commit c4b0cbd) -- slice ourselves."""
    start = datetime(day.year, day.month, day.day, 7, 0, tzinfo=ET)
    end = start + timedelta(hours=13)
    try:
        df = schwab_client.get_price_history(
            ticker, interval="1m", start=start, end=end, extended_hours=True,
        )
    except Exception as exc:
        print(f"  [{ticker} {day}] minute bars failed: {type(exc).__name__}: {exc}")
        return None
    if df is None or df.empty:
        return None
    return df[df.index.date == day]


def evaluate_halt(row: dict) -> dict:
    """Returns a log entry for this halt -- always logged, per the
    shadow-ranking discipline, whether or not it was even evaluable."""
    symbol = row["symbol"]
    halt_dt = _parse_feed_ts(row["halt_ts"])
    resumption_dt = _parse_feed_ts(row["resumption_ts"])
    base = {
        "ticker": symbol, "halt_ts_raw": row["halt_ts"],
        "reason_code": row["reason_code"], "resumption_ts_raw": row["resumption_ts"],
    }
    if halt_dt is None:
        return {**base, "evaluated": False, "skip_reason": "unparseable halt_ts"}
    if resumption_dt is None:
        return {**base, "evaluated": False,
                "skip_reason": "no resumption timestamp recorded (halt unresolved/never resumed in feed)"}

    day = halt_dt.date()
    bars = minute_bars_for_day(symbol, day)
    if bars is None or bars.empty:
        return {**base, "evaluated": False, "skip_reason": "no minute bars returned for halt day"}

    pre_halt = bars[(bars.index >= halt_dt - timedelta(minutes=PRE_HALT_LOOKBACK_MIN)) & (bars.index < halt_dt)]
    if pre_halt.empty:
        return {**base, "evaluated": False, "skip_reason": "no pre-halt bars in lookback window"}

    pre_open = float(pre_halt["Open"].iloc[0])
    pre_last_close = float(pre_halt["Close"].iloc[-1])
    if pre_last_close == pre_open:
        return {**base, "evaluated": False, "skip_reason": "flat pre-halt window -- no directional classification"}
    direction = "long" if pre_last_close > pre_open else "short"
    pre_halt_high = float(pre_halt["High"].max())
    pre_halt_low = float(pre_halt["Low"].min())
    extreme = pre_halt_high if direction == "long" else pre_halt_low

    post = bars[bars.index >= resumption_dt]
    if post.empty:
        return {**base, "evaluated": False, "skip_reason": "no post-resumption bars available"}

    entry_window = post[post.index <= resumption_dt + timedelta(minutes=ENTRY_WINDOW_MIN)]
    trigger_bar = None
    for ts, bar in entry_window.iterrows():
        if direction == "long" and float(bar["High"]) > extreme:
            trigger_bar = (ts, bar)
            break
        if direction == "short" and float(bar["Low"]) < extreme:
            trigger_bar = (ts, bar)
            break

    result = {
        **base, "evaluated": True, "halt_dt_et": halt_dt.isoformat(),
        "resumption_dt_et": resumption_dt.isoformat(), "direction": direction,
        "pre_halt_open": pre_open, "pre_halt_last_close": pre_last_close,
        "pre_halt_extreme": round(extreme, 4),
        "pre_halt_bars_used": len(pre_halt),
    }
    if trigger_bar is None:
        result["triggered"] = False
        result["skip_reason"] = "no break of pre-halt extreme within entry window"
        return result

    trigger_ts, _ = trigger_bar
    entry_price = extreme  # entry at the level break, matching the pre-registered trigger
    horizon_end = trigger_ts + timedelta(minutes=PRIMARY_HORIZON_MIN)
    window = post[(post.index >= trigger_ts) & (post.index <= horizon_end)]
    if window.empty:
        result["triggered"] = True
        result["skip_reason"] = "no bars in post-trigger horizon window"
        return result

    end_price = float(window["Close"].iloc[-1])
    t5 = trigger_ts + timedelta(minutes=5)
    at_t5 = post[(post.index >= trigger_ts) & (post.index <= t5)]
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
    remaining_pct_of_total = (
        (remaining_after_t5 / total_move * 100.0) if abs(total_move) > 1e-9 else None
    )

    secondary = {}
    for m in SECONDARY_HORIZONS_MIN:
        h_end = trigger_ts + timedelta(minutes=m)
        w = post[(post.index >= trigger_ts) & (post.index <= h_end)]
        if w.empty:
            continue
        p = float(w["Close"].iloc[-1])
        secondary[f"continued_{m}min"] = bool(p > entry_price if direction == "long" else p < entry_price)
        secondary[f"move_pct_{m}min"] = round(
            ((p - entry_price) if direction == "long" else (entry_price - p)) / entry_price * 100.0, 3
        )

    result.update({
        "triggered": True,
        "trigger_ts_et": trigger_ts.isoformat(),
        "entry_price": round(entry_price, 4),
        "price_at_t5": round(price_at_t5, 4),
        "end_price_60min": round(end_price, 4),
        f"continued_{PRIMARY_HORIZON_MIN}min": continued,
        "total_move_pct_of_entry": round(total_move / entry_price * 100.0, 3),
        "remaining_move_pct_of_total_after_t5": (
            round(remaining_pct_of_total, 1) if remaining_pct_of_total is not None else None
        ),
        **secondary,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h4_results.json")
    args = parser.parse_args()

    conn = _connect()
    try:
        rows = load_halt_rows(conn)
    finally:
        conn.close()
    print(f"loaded {len(rows)} raw trading_halts rows from consensus.db")

    results = []
    for i, row in enumerate(rows):
        print(f"[{i+1}/{len(rows)}] {row['symbol']} halt_ts={row['halt_ts']} "
              f"reason={row['reason_code']} resumption_ts={row['resumption_ts']}")
        results.append(evaluate_halt(row))

    evaluated = [r for r in results if r.get("evaluated")]
    triggered = [r for r in evaluated if r.get("triggered")]
    completed = [r for r in triggered if f"continued_{PRIMARY_HORIZON_MIN}min" in r]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "generated_at_pacific": datetime.now(PT).isoformat(),
        "raw_row_count": len(rows),
        "evaluated_count": len(evaluated),
        "triggered_count": len(triggered),
        "completed_count": len(completed),
        "primary_horizon_min": PRIMARY_HORIZON_MIN,
        "entry_window_min": ENTRY_WINDOW_MIN,
        "pre_halt_lookback_min": PRE_HALT_LOOKBACK_MIN,
        "results": results,
    }, indent=2))
    print(f"wrote {len(results)} logged halt rows ({len(evaluated)} evaluated, "
          f"{len(triggered)} triggered, {len(completed)} completed the horizon) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
