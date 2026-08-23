#!/usr/bin/env python3
"""Phase A test for H1 — premarket gap-and-go continuation.

Pre-registered hypothesis (do not edit without bumping the version --
see .omc/research/short-duration-scanner-phaseA/hypotheses-v1.md):

  Setup: stock gaps >4% premarket on a same-morning fresh catalyst, with
  premarket relative volume standing out vs its own 20-day average.
  Entry trigger: price holds the premarket gap direction through the first
  5 minutes of the regular session.
  Claim: continues in the gap direction over the next 60 minutes more often,
  and by more, than magnitude-matched gaps with no identifiable catalyst.

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402
from consensus_engine.utils.prices import fetch_history  # noqa: E402

ET = ZoneInfo("America/New_York")
DB_PATH = ROOT / "consensus.db"
GAP_FLOOR_PCT = 4.0
# Regular-session-only minute bars are reliable to ~47-49 days back (verified
# live 2026-08-22, commit c4b0cbd). Extended-hours (premarket) bars -- which
# H1 needs -- are LESS reliable at that same distance: AMD/INTC/MU returned
# zero rows with extended_hours=True at 46-47 days back even though the
# identical request with extended_hours=False returned a full session, and
# even though other tickers (FISV) DID get extended-hours data on that same
# date. This looks like a ticker-specific Schwab data-completeness gap, not a
# hard system-wide cutoff -- bounding to 40 days keeps the sample inside the
# range where every ticker tested came back clean, rather than silently
# biasing the sample toward whichever tickers happen to have deeper history.
LOOKBACK_DAYS = 40
MIN_SAMPLE_FLOOR = 20


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def load_catalyst_candidates(conn: sqlite3.Connection, since_ts: float) -> list[dict]:
    """One row per ticker+day with a non-blank catalyst_type -- 'one setup,
    one sample' (plan Section 8.6): dedup to the EARLIEST alert that day."""
    rows = conn.execute(
        """SELECT ticker, catalyst_type, MIN(alerted_at) AS first_alert_at
           FROM alert_history
           WHERE alerted_at >= ? AND catalyst_type IS NOT NULL AND catalyst_type <> ''
           GROUP BY ticker, date(alerted_at, 'unixepoch', 'localtime')
           ORDER BY first_alert_at""",
        (since_ts,),
    ).fetchall()
    return [dict(r) for r in rows]


def load_control_universe(conn: sqlite3.Connection, limit: int | None) -> list[str]:
    """Tickers the bot already watches (alert history over the last 6 months)
    -- a bounded stand-in for 'the market' per plan Section 9 (stock-level
    discovery within current data limits), not a full exchange scan."""
    since_ts = time.time() - 180 * 86400
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM alert_history WHERE alerted_at >= ? ORDER BY ticker",
        (since_ts,),
    ).fetchall()
    tickers = [r["ticker"].upper() for r in rows]
    if limit:
        tickers = tickers[:limit]
    return tickers


def catalyst_days_for_ticker(conn: sqlite3.Connection, ticker: str, since_ts: float) -> set[str]:
    """Every day this ticker had ANY alert (not just non-blank catalyst_type)
    -- the control group must exclude these entirely, not just the H1
    candidate days, so it stays a genuine no-catalyst comparison."""
    rows = conn.execute(
        """SELECT DISTINCT date(alerted_at, 'unixepoch', 'localtime') AS d
           FROM alert_history WHERE ticker=? AND alerted_at>=?""",
        (ticker, since_ts),
    ).fetchall()
    return {r["d"] for r in rows}


def find_control_candidates(
    conn: sqlite3.Connection, ticker: str, since_ts: float,
) -> list[dict]:
    """One ticker's whole window scanned in a single daily-history call --
    cheaper than per-day calls, and this side needs every day in the window
    anyway (unlike the catalyst side, which only needs specific alert days)."""
    catalyst_days = catalyst_days_for_ticker(conn, ticker, since_ts)
    since_dt = datetime.fromtimestamp(since_ts, ET)
    end = datetime.now(ET) + timedelta(days=1)
    try:
        df = fetch_history(ticker, start=since_dt - timedelta(days=10), end=end, interval="1d")
    except Exception as exc:
        print(f"  [{ticker}] control daily history failed: {type(exc).__name__}: {exc}")
        return []
    if df is None or df.empty:
        return []
    out = []
    for day in sorted(set(df.index.date)):
        if day < since_dt.date() or str(day) in catalyst_days:
            continue
        todays = df[df.index.date == day]
        priors = df[df.index.date < day]
        if todays.empty or priors.empty:
            continue
        open_price = float(todays["Open"].iloc[0])
        prior_close = float(priors["Close"].iloc[-1])
        if prior_close <= 0:
            continue
        gap = (open_price - prior_close) / prior_close * 100.0
        if abs(gap) < GAP_FLOOR_PCT:
            continue
        out.append({"ticker": ticker, "day": day, "gap_pct": gap})
    return out


def daily_prior_close(ticker: str, day: "datetime.date") -> tuple[float, float] | None:
    """Cheap prefilter: returns (gap_pct, prior_regular_session_close).

    Minute bars only go back to 07:00 ET on `day` itself (verified live --
    commit c4b0cbd), so the true prior close has to come from the daily
    series, not from partial same-day premarket data.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=ET) - timedelta(days=10)
    end = datetime(day.year, day.month, day.day, tzinfo=ET) + timedelta(days=1)
    try:
        df = fetch_history(ticker, start=start, end=end, interval="1d")
    except Exception as exc:
        print(f"  [{ticker} {day}] daily history failed: {type(exc).__name__}: {exc}")
        return None
    if df is None or df.empty:
        return None
    df = df[df.index.date <= day]
    if len(df) < 2:
        return None
    todays = df[df.index.date == day]
    if todays.empty:
        return None
    open_price = float(todays["Open"].iloc[0])
    prior_close = float(df[df.index.date < day]["Close"].iloc[-1])
    if prior_close <= 0:
        return None
    gap_pct = (open_price - prior_close) / prior_close * 100.0
    return gap_pct, prior_close


def minute_bars(ticker: str, day: "datetime.date"):
    """Extended-hours 1-minute bars for one calendar day (verified this
    returns the whole session 07:00-19:59 ET regardless of start/end --
    commit c4b0cbd -- so we slice to the needed window ourselves)."""
    start = datetime(day.year, day.month, day.day, 8, 0, tzinfo=ET)
    end = start + timedelta(hours=1)
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


def evaluate_candidate(
    ticker: str, day, alert_time_et: datetime | None, gap_pct: float,
) -> dict | None:
    """gap_pct comes from daily_prior_close (the real prior regular-session
    close) -- minute bars are used only for the entry trigger and the
    forward-outcome measurement, never to re-derive the gap itself."""
    bars = minute_bars(ticker, day)
    if bars is None or bars.empty:
        return None
    premarket = bars[bars.index.time < datetime(2000, 1, 1, 9, 30).time()]
    regular = bars[bars.index.time >= datetime(2000, 1, 1, 9, 30).time()]
    if premarket.empty or regular.empty:
        return None
    premarket_high = float(premarket["High"].max())
    premarket_low = float(premarket["Low"].min())
    direction = "long" if gap_pct > 0 else "short"

    first5 = regular.iloc[:5]
    if direction == "long":
        held = bool((first5["Low"] >= premarket_high * 0.999).all()) if not first5.empty else False
    else:
        held = bool((first5["High"] <= premarket_low * 1.001).all()) if not first5.empty else False
    if not held:
        return {"ticker": ticker, "day": str(day), "direction": direction,
                "gap_pct": gap_pct, "triggered": False}

    open_ts = regular.index[0]
    delivery_ts = open_ts
    if alert_time_et is not None and alert_time_et > open_ts:
        delivery_ts = alert_time_et
    horizon_60 = delivery_ts + timedelta(minutes=60)
    t5 = delivery_ts + timedelta(minutes=5)
    window = regular[(regular.index >= delivery_ts) & (regular.index <= horizon_60)]
    if window.empty:
        return None
    entry_price = float(window["Open"].iloc[0])
    end_price = float(window["Close"].iloc[-1])
    at_t5 = regular[regular.index <= t5]
    price_at_t5 = float(at_t5["Close"].iloc[-1]) if not at_t5.empty else entry_price

    if direction == "long":
        total_move = end_price - entry_price
        move_at_t5 = price_at_t5 - entry_price
        continued = end_price > entry_price
    else:
        total_move = entry_price - end_price
        move_at_t5 = entry_price - price_at_t5
        continued = end_price < entry_price

    remaining_after_t5 = (total_move - move_at_t5)
    remaining_pct_of_total = (
        (remaining_after_t5 / total_move * 100.0) if total_move not in (0, None) and abs(total_move) > 1e-9
        else None
    )
    return {
        "ticker": ticker, "day": str(day), "direction": direction,
        "gap_pct": round(gap_pct, 2), "triggered": True, "continued_60min": continued,
        "entry_price": entry_price, "price_at_t5": round(price_at_t5, 4),
        "end_price_60min": end_price,
        "total_move_pct_of_entry": round(total_move / entry_price * 100.0, 3),
        "remaining_move_pct_of_total_after_t5": (
            round(remaining_pct_of_total, 1) if remaining_pct_of_total is not None else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="cap the number of catalyst candidates probed (for a quick run)")
    parser.add_argument("--control-limit", type=int, default=None,
                         help="cap the number of control (no-catalyst) candidates probed")
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h1_results.json")
    args = parser.parse_args()

    since_ts = time.time() - LOOKBACK_DAYS * 86400
    conn = _connect()
    try:
        candidates = load_catalyst_candidates(conn, since_ts)
    finally:
        conn.close()
    print(f"loaded {len(candidates)} catalyst-tagged ticker/day candidates from the last "
          f"{LOOKBACK_DAYS} days")
    if args.limit:
        candidates = candidates[: args.limit]

    catalyst_results = []
    for i, row in enumerate(candidates):
        ticker = row["ticker"].upper()
        alert_dt = datetime.fromtimestamp(row["first_alert_at"], ET)
        day = alert_dt.date()
        prior = daily_prior_close(ticker, day)
        if prior is None:
            continue
        gap, _prior_close = prior
        if abs(gap) < GAP_FLOOR_PCT:
            continue
        print(f"[catalyst {i+1}/{len(candidates)}] {ticker} {day} daily gap={gap:.1f}% -- probing minute bars")
        outcome = evaluate_candidate(ticker, day, alert_dt, gap)
        if outcome is not None:
            outcome["catalyst_type"] = row["catalyst_type"]
            catalyst_results.append(outcome)

    conn = _connect()
    try:
        control_universe = load_control_universe(conn, args.control_limit)
        control_days: list[dict] = []
        for i, ticker in enumerate(control_universe):
            print(f"[control ticker {i+1}/{len(control_universe)}] {ticker} -- scanning window for no-catalyst gaps")
            control_days.extend(find_control_candidates(conn, ticker, since_ts))
    finally:
        conn.close()
    print(f"found {len(control_days)} no-catalyst gap-day candidates across "
          f"{len(control_universe)} tickers")

    control_results = []
    for i, cand in enumerate(control_days):
        print(f"[control {i+1}/{len(control_days)}] {cand['ticker']} {cand['day']} "
              f"gap={cand['gap_pct']:.1f}% -- probing minute bars")
        outcome = evaluate_candidate(cand["ticker"], cand["day"], None, cand["gap_pct"])
        if outcome is not None:
            control_results.append(outcome)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "generated_at_pacific": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "gap_floor_pct": GAP_FLOOR_PCT,
        "catalyst_candidate_count": len(candidates),
        "control_universe_size": len(control_universe),
        "control_candidate_count": len(control_days),
        "catalyst_results": catalyst_results,
        "control_results": control_results,
    }, indent=2))
    print(f"wrote {len(catalyst_results)} catalyst + {len(control_results)} control "
          f"evaluated candidates to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
