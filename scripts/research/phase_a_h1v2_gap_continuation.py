#!/usr/bin/env python3
"""Phase A test for H1-v2 — premarket gap-and-go continuation (CORRECTED).

Pre-registered hypothesis (do not edit without a fresh version bump — see
.omc/research/short-duration-scanner-phaseA/hypotheses-v2.md, section H1-v2):

  Setup: stock gaps >4% premarket on a same-morning fresh catalyst, with
  premarket relative volume standing out vs its own 20-day average (>=1.5x).
  Entry trigger: price holds the premarket gap direction through the first
  5 real wall-clock minutes of the regular session (09:30:00-09:34:59 ET).
  Claim: continues in the gap direction over the next 60 minutes more often,
  and by more, than magnitude-matched gaps with no identifiable catalyst.

This is a REPLACEMENT for phase_a_h1_gap_continuation.py (v1), not an edit of
it. v1 is left untouched as the historical record of what v1 actually tested
(.omc/research/short-duration-scanner-phaseA/phaseA-audit.md references its
exact line numbers). Every one of the 5 defects the audit found in v1 is
fixed here — see the docstring on each function below for exactly where.

Read-only against consensus.db and the live/historical Schwab price API.
Writes nothing back to the production database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402
from consensus_engine.utils.prices import fetch_history  # noqa: E402

ET = ZoneInfo("America/New_York")
DB_PATH = ROOT / "consensus.db"

GAP_FLOOR_PCT = 4.0

# Candidate window: same ~40-day bound v1 used, for the same reason -- extended
# hours (premarket) minute bars are reliably returned by Schwab only within
# roughly this range (verified live 2026-08-22, commit c4b0cbd; re-verified
# during this v2 build -- see MINUTE_FETCH_LOOKBACK_DAYS below).
LOOKBACK_DAYS = 40

# How far back to ASK for minute bars. Schwab silently returns whatever
# history it actually has for extended-hours 1-minute data regardless of how
# far back the request goes -- empirically ~28-32 trading days per ticker as
# of this build (verified live: a 68-calendar-day request for AAPL returned
# data starting 2026-07-09, i.e. ~45 calendar days back, not 68). Asking for
# more than that costs nothing (it is a single API call either way) and lets
# tickers with deeper history use it, so we ask generously and let the
# per-ticker RVOL-eligibility check (see compute_rvol) adapt to whatever each
# ticker actually returns.
MINUTE_FETCH_LOOKBACK_DAYS = 90

# defect #3 fix: the premarket relative-volume filter, actually implemented.
RVOL_THRESHOLD = 1.5
RVOL_TRAILING_DAYS = 20

# defect #4/#5 fix: ONE shared ticker universe feeds both arms. Pool is "every
# ticker the bot has alerted on in the last 180 days" (same pool v1 used for
# its control universe -- plan Section 9's bounded stand-in for "the market"),
# then hash-sampled down to a budget-sized, non-biased subset -- see
# build_shared_universe().
UNIVERSE_POOL_LOOKBACK_DAYS = 180
UNIVERSE_CAP = 400

MIN_SAMPLE_FLOOR = 20

PREMARKET_START = dtime(9, 0)
REGULAR_OPEN = dtime(9, 30)
ENTRY_WINDOW_END = dtime(9, 35)  # exclusive -- bars 09:30..09:34 = the real 5-minute window


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


# --------------------------------------------------------------------------
# Universe (defect #4/#5 fix)
# --------------------------------------------------------------------------

def build_shared_universe(conn: sqlite3.Connection, pool_lookback_days: int, cap: int) -> list[str]:
    """ONE ticker universe used to build BOTH the catalyst and control arms.

    v1's bug (audit section H1(b)): `load_control_universe` used
    `ORDER BY ticker LIMIT n`, taking an alphabetical prefix (A-B only, 87
    tickers) while the catalyst side pulled from the full alphabet with no
    universe cap at all (60 tickers, AAOI..ZION) -- 5-ticker overlap out of a
    combined 142. The two arms were built from almost entirely different
    tickers.

    Fix: pull the full pool once (every ticker alerted on in the last
    `pool_lookback_days` days), rank it by a fixed, content-derived hash
    (sha1 of the ticker string -- NOT Python's builtin hash(), which is
    salted per-process and would make the sample non-reproducible run to
    run), and take the first `cap` entries in hash order. Hash order has no
    relationship to alphabetical order or to when a ticker first appears, so
    truncating it doesn't systematically favor one letter range or one time
    period the way `ORDER BY ticker LIMIT n` or `ORDER BY date LIMIT n` do.
    The SAME resulting list then feeds catalyst-day lookup AND control gap-day
    scanning for every ticker in it -- neither arm gets its own separate,
    differently-truncated universe.
    """
    since_ts = time.time() - pool_lookback_days * 86400
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM alert_history WHERE alerted_at >= ?", (since_ts,),
    ).fetchall()
    pool = sorted({r["ticker"].upper() for r in rows})
    ranked = sorted(pool, key=lambda t: hashlib.sha1(t.encode()).hexdigest())
    sample = ranked[:cap] if cap else ranked
    print(f"universe pool: {len(pool)} distinct tickers alerted on in the last "
          f"{pool_lookback_days} days; hash-sampled down to {len(sample)}")
    return sorted(sample)  # alphabetical here is only for readable logging --
    # the actual sampling decision already happened above, in hash order.


def ticker_catalyst_days(conn: sqlite3.Connection, ticker: str, since_ts: float) -> list[dict]:
    """One row per day this ticker had a non-blank catalyst_type alert, deduped
    to the EARLIEST alert that day ('one setup, one sample', plan Section 8.6).
    Same dedup rule as v1's load_catalyst_candidates, now scoped to one ticker
    from the shared universe instead of scanning alert_history unbounded."""
    rows = conn.execute(
        """SELECT catalyst_type, MIN(alerted_at) AS first_alert_at
           FROM alert_history
           WHERE ticker=? AND alerted_at >= ? AND catalyst_type IS NOT NULL AND catalyst_type <> ''
           GROUP BY date(alerted_at, 'unixepoch', 'localtime')
           ORDER BY first_alert_at""",
        (ticker, since_ts),
    ).fetchall()
    return [dict(r) for r in rows]


def ticker_alert_days(conn: sqlite3.Connection, ticker: str, since_ts: float) -> set[str]:
    """Every day this ticker had ANY alert (not just catalyst-tagged) -- the
    control group excludes these entirely so it stays a genuine no-catalyst
    comparison. Unchanged from v1's catalyst_days_for_ticker."""
    rows = conn.execute(
        """SELECT DISTINCT date(alerted_at, 'unixepoch', 'localtime') AS d
           FROM alert_history WHERE ticker=? AND alerted_at>=?""",
        (ticker, since_ts),
    ).fetchall()
    return {r["d"] for r in rows}


# --------------------------------------------------------------------------
# Daily bars -> gap %  (prior close always from DAILY bars, per platform note)
# --------------------------------------------------------------------------

def daily_gap_dict(ticker: str, since_dt: datetime, end_dt: datetime) -> dict[date, float]:
    """One daily-history call per ticker covering the whole candidate window
    (plus a 10-day buffer so the earliest in-window day still has a real
    prior close) -- feeds BOTH the catalyst-day gap check and the control
    gap-day scan, so there is only one daily API call per ticker instead of
    v1's two separate call sites (per-day for catalyst, per-ticker for
    control)."""
    start = since_dt - timedelta(days=10)
    end = end_dt + timedelta(days=1)
    try:
        df = fetch_history(ticker, start=start, end=end, interval="1d")
    except Exception as exc:
        print(f"  [{ticker}] daily history failed: {type(exc).__name__}: {exc}")
        return {}
    if df is None or df.empty:
        return {}
    out: dict[date, float] = {}
    for day in sorted(set(df.index.date)):
        if day < since_dt.date():
            continue  # buffer days only serve as a prior-close source, never scored
        todays = df[df.index.date == day]
        priors = df[df.index.date < day]
        if todays.empty or priors.empty:
            continue
        open_price = float(todays["Open"].iloc[0])
        prior_close = float(priors["Close"].iloc[-1])
        if prior_close <= 0:
            continue
        out[day] = (open_price - prior_close) / prior_close * 100.0
    return out


# --------------------------------------------------------------------------
# Minute bars -> premarket reference, RVOL, entry trigger, outcome
# --------------------------------------------------------------------------

def fetch_minute_series(ticker: str, start_dt: datetime, end_dt: datetime):
    """ONE extended-hours minute-bar call per ticker for the whole lookback
    span. Schwab returns the entire session (07:00-19:59 ET) for every
    trading day it has in range regardless of the requested start/end
    (verified live, commit c4b0cbd) -- confirmed here it also does this
    across a MULTI-day span in one call, not just one day, so a single call
    per ticker covers every candidate day plus the RVOL trailing baseline."""
    try:
        df = schwab_client.get_price_history(
            ticker, interval="1m", start=start_dt, end=end_dt, extended_hours=True,
        )
    except Exception as exc:
        print(f"  [{ticker}] minute bars failed: {type(exc).__name__}: {exc}")
        return None
    return df


def premarket_dollar_volume_by_day(minute_df) -> dict[date, float]:
    """defect #1 fix, part A: the reference window is bounded to 09:00-09:29
    ET (v1 used the unbounded whole premarket session, 07:00-09:29, so one
    premarket spike anywhere in a 2.5-hour window could set the bar).

    dollar volume per day = sum over each 1-minute bar in 09:00:00-09:29:59
    ET of (bar Volume x bar Close) -- a per-minute VWAP-ish proxy, summed."""
    pm = minute_df[(minute_df.index.time >= PREMARKET_START) & (minute_df.index.time < REGULAR_OPEN)]
    if pm.empty:
        return {}
    dollar_vol = pm["Volume"] * pm["Close"]
    grouped = dollar_vol.groupby(pm.index.date).sum()
    return {d: float(v) for d, v in grouped.items() if v > 0}


def compute_rvol(pm_dv: dict[date, float], sorted_pm_days: list[date], day: date) -> dict | None:
    """defect #3 fix: the premarket RVOL filter, actually computed and applied.

    Baseline = the mean premarket (09:00-09:29 ET) dollar volume over the
    ticker's own most recent 20 PRIOR trading days that have premarket data
    in this same pulled series -- unconditional on whether those prior days
    were themselves gap days, catalyst days, or anything else (the
    pre-registration says 'its own trailing-20-day average', not a
    quiet-days-only average). Requires a FULL 20 prior days to be present;
    if fewer exist (this ticker's Schwab-returned history doesn't reach back
    that far), the candidate is excluded as insufficient baseline rather than
    silently averaging over a shorter window -- see the
    excluded_insufficient_rvol_baseline counts in the screening log."""
    if day not in pm_dv:
        return None
    idx = sorted_pm_days.index(day)
    prior_days = sorted_pm_days[:idx]
    if len(prior_days) < RVOL_TRAILING_DAYS:
        return None
    baseline_days = prior_days[-RVOL_TRAILING_DAYS:]
    baseline_vals = [pm_dv[d] for d in baseline_days]
    baseline_mean = sum(baseline_vals) / len(baseline_vals)
    if baseline_mean <= 0:
        return None
    return {
        "rvol": pm_dv[day] / baseline_mean,
        "baseline_mean_dollars": baseline_mean,
        "baseline_days": [str(d) for d in baseline_days],
    }


def premarket_high_low(minute_df, day: date) -> tuple[float, float] | None:
    """defect #1 fix, part B: same 09:00-09:29 ET bound applied to the
    high/low reference used by the entry trigger."""
    day_pm = minute_df[
        (minute_df.index.date == day)
        & (minute_df.index.time >= PREMARKET_START)
        & (minute_df.index.time < REGULAR_OPEN)
    ]
    if day_pm.empty:
        return None
    return float(day_pm["High"].max()), float(day_pm["Low"].min())


def evaluate_trigger_and_outcome(
    minute_df, ticker: str, day: date, gap_pct: float, alert_time_et: datetime | None,
) -> dict | None:
    """gap_pct comes from daily_gap_dict (the real prior regular-session
    close) -- minute bars are used only for the premarket reference, the
    entry trigger, and the forward-outcome measurement, never to re-derive
    the gap itself.

    defect #2 fix: the entry trigger is checked over the real wall-clock
    window 09:30:00-09:34:59 ET (bars with time in [09:30, 09:35)), not
    v1's `regular.iloc[:5]` first-5-*bars* slice, which let missing minute
    bars on thin names silently widen or narrow the tested window."""
    pm_hl = premarket_high_low(minute_df, day)
    if pm_hl is None:
        return None
    premarket_high, premarket_low = pm_hl

    day_regular = minute_df[(minute_df.index.date == day) & (minute_df.index.time >= REGULAR_OPEN)]
    if day_regular.empty:
        return None
    entry_window = day_regular[day_regular.index.time < ENTRY_WINDOW_END]
    if entry_window.empty:
        return None

    direction = "long" if gap_pct > 0 else "short"
    if direction == "long":
        held = bool((entry_window["Low"] >= premarket_high * 0.999).all())
    else:
        held = bool((entry_window["High"] <= premarket_low * 1.001).all())
    if not held:
        return {
            "ticker": ticker, "day": str(day), "direction": direction,
            "gap_pct": round(gap_pct, 2), "premarket_high": premarket_high,
            "premarket_low": premarket_low, "triggered": False,
        }

    open_ts = day_regular.index[0]
    delivery_ts = open_ts
    if alert_time_et is not None and alert_time_et > open_ts:
        delivery_ts = alert_time_et
    horizon_60 = delivery_ts + timedelta(minutes=60)
    t5 = delivery_ts + timedelta(minutes=5)
    window = day_regular[(day_regular.index >= delivery_ts) & (day_regular.index <= horizon_60)]
    if window.empty:
        return None
    entry_price = float(window["Open"].iloc[0])
    end_price = float(window["Close"].iloc[-1])
    at_t5 = day_regular[day_regular.index <= t5]
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
    return {
        "ticker": ticker, "day": str(day), "direction": direction,
        "gap_pct": round(gap_pct, 2), "triggered": True, "continued_60min": continued,
        "premarket_high": premarket_high, "premarket_low": premarket_low,
        "entry_price": entry_price, "price_at_t5": round(price_at_t5, 4),
        "end_price_60min": end_price,
        "total_move_pct_of_entry": round(total_move / entry_price * 100.0, 3),
        "remaining_move_pct_of_total_after_t5": (
            round(remaining_pct_of_total, 1) if remaining_pct_of_total is not None else None
        ),
    }


# --------------------------------------------------------------------------
# Summary stats (Wilson 95% CI, matching the audit's own method)
# --------------------------------------------------------------------------

def wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return max(0.0, lo) * 100.0, min(1.0, hi) * 100.0


def summarize(results: list[dict], label: str) -> dict:
    triggered = [r for r in results if r.get("triggered")]
    wins = [r for r in triggered if r.get("continued_60min")]
    n_eval, n_trig, n_win = len(results), len(triggered), len(wins)
    ci = wilson_ci(n_win, n_trig)
    remaining = sorted(
        r["remaining_move_pct_of_total_after_t5"] for r in triggered
        if r.get("remaining_move_pct_of_total_after_t5") is not None
    )
    median_remaining = remaining[len(remaining) // 2] if remaining else None
    print(f"  {label}: evaluated={n_eval} triggered={n_trig} continued_60min={n_win} "
          f"rate={(n_win/n_trig*100.0) if n_trig else 0:.1f}% "
          f"Wilson95%CI={ci} median_T+5_remaining={median_remaining}")
    return {
        "evaluated": n_eval, "triggered": n_trig, "continued_60min_wins": n_win,
        "continuation_rate_pct": round(n_win / n_trig * 100.0, 1) if n_trig else None,
        "wilson_95ci_pct": ci, "median_remaining_move_pct_after_t5": median_remaining,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe-cap", type=int, default=UNIVERSE_CAP,
                         help="cap on the shared ticker universe (hash-sampled -- "
                              "see build_shared_universe; does NOT reintroduce "
                              "alphabetical/chronological truncation)")
    parser.add_argument("--out", type=Path, default=ROOT / ".omc" / "research"
                         / "short-duration-scanner-phaseA" / "h1v2_results.json")
    args = parser.parse_args()

    now_dt = datetime.now(ET)
    since_dt = now_dt - timedelta(days=LOOKBACK_DAYS)
    since_ts = since_dt.timestamp()
    minute_start = now_dt - timedelta(days=MINUTE_FETCH_LOOKBACK_DAYS)

    conn = _connect()
    try:
        universe = build_shared_universe(conn, UNIVERSE_POOL_LOOKBACK_DAYS, args.universe_cap)
    finally:
        conn.close()

    catalyst_results: list[dict] = []
    control_results: list[dict] = []
    screening_log: list[dict] = []
    calls_made = {"daily": 0, "minute": 0}
    tickers_with_no_candidates = 0

    for i, ticker in enumerate(universe):
        conn = _connect()
        try:
            alert_days = ticker_alert_days(conn, ticker, since_ts)
            catalyst_rows = ticker_catalyst_days(conn, ticker, since_ts)
        finally:
            conn.close()

        gap_dict = daily_gap_dict(ticker, since_dt, now_dt)
        calls_made["daily"] += 1
        if not gap_dict:
            continue

        tentative_catalyst = []
        for row in catalyst_rows:
            alert_dt = datetime.fromtimestamp(row["first_alert_at"], ET)
            day = alert_dt.date()
            gap = gap_dict.get(day)
            if gap is None:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                       "status": "excluded_no_daily_gap_data"})
                continue
            if abs(gap) < GAP_FLOOR_PCT:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                       "status": "excluded_gap_below_floor", "gap_pct": round(gap, 2)})
                continue
            tentative_catalyst.append({
                "day": day, "gap_pct": gap, "catalyst_type": row["catalyst_type"],
                "alert_time_et": alert_dt,
            })

        control_candidates = []
        for day, gap in gap_dict.items():
            if day < since_dt.date():
                continue
            if str(day) in alert_days:
                continue  # excludes ANY alert day, not just catalyst-tagged ones
            if abs(gap) < GAP_FLOOR_PCT:
                continue
            control_candidates.append({"day": day, "gap_pct": gap})

        if not tentative_catalyst and not control_candidates:
            tickers_with_no_candidates += 1
            continue

        minute_df = fetch_minute_series(ticker, minute_start, now_dt)
        calls_made["minute"] += 1
        if minute_df is None or minute_df.empty:
            for c in tentative_catalyst:
                screening_log.append({"ticker": ticker, "day": str(c["day"]), "arm": "catalyst",
                                       "status": "excluded_no_minute_data"})
            for c in control_candidates:
                screening_log.append({"ticker": ticker, "day": str(c["day"]), "arm": "control",
                                       "status": "excluded_no_minute_data"})
            continue

        pm_dv = premarket_dollar_volume_by_day(minute_df)
        sorted_pm_days = sorted(pm_dv.keys())

        for c in tentative_catalyst:
            day = c["day"]
            if day not in pm_dv:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                       "status": "excluded_no_premarket_data"})
                continue
            rvol_info = compute_rvol(pm_dv, sorted_pm_days, day)
            if rvol_info is None:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                       "status": "excluded_insufficient_rvol_baseline"})
                continue
            if rvol_info["rvol"] < RVOL_THRESHOLD:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                       "status": "excluded_rvol_below_threshold",
                                       "rvol": round(rvol_info["rvol"], 2)})
                continue
            outcome = evaluate_trigger_and_outcome(minute_df, ticker, day, c["gap_pct"], c["alert_time_et"])
            if outcome is None:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                       "status": "excluded_no_regular_session_data"})
                continue
            outcome["catalyst_type"] = c["catalyst_type"]
            outcome["rvol"] = round(rvol_info["rvol"], 2)
            outcome["rvol_baseline_dollars"] = round(rvol_info["baseline_mean_dollars"], 2)
            catalyst_results.append(outcome)
            screening_log.append({"ticker": ticker, "day": str(day), "arm": "catalyst",
                                   "status": "triggered" if outcome["triggered"] else "evaluated_not_triggered"})

        for c in control_candidates:
            day = c["day"]
            if day not in pm_dv:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "control",
                                       "status": "excluded_no_premarket_data"})
                continue
            outcome = evaluate_trigger_and_outcome(minute_df, ticker, day, c["gap_pct"], None)
            if outcome is None:
                screening_log.append({"ticker": ticker, "day": str(day), "arm": "control",
                                       "status": "excluded_no_regular_session_data"})
                continue
            control_results.append(outcome)
            screening_log.append({"ticker": ticker, "day": str(day), "arm": "control",
                                   "status": "triggered" if outcome["triggered"] else "evaluated_not_triggered"})

        print(f"[{i+1}/{len(universe)}] {ticker}: catalyst_tentative={len(tentative_catalyst)} "
              f"control_candidates={len(control_candidates)} minute_days_available={len(sorted_pm_days)} "
              f"catalyst_results_so_far={len(catalyst_results)} control_results_so_far={len(control_results)}")

    print(f"\n{len(universe)} tickers scanned; {tickers_with_no_candidates} had zero candidate "
          f"days; API calls made: daily={calls_made['daily']} minute={calls_made['minute']} "
          f"total={calls_made['daily']+calls_made['minute']}")

    print("\n--- summary ---")
    catalyst_summary = summarize(catalyst_results, "catalyst (RVOL-confirmed)")
    control_summary = summarize(control_results, "control (no-catalyst, same universe/window)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "generated_at_pacific": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "minute_fetch_lookback_days": MINUTE_FETCH_LOOKBACK_DAYS,
        "gap_floor_pct": GAP_FLOOR_PCT,
        "rvol_threshold": RVOL_THRESHOLD,
        "rvol_trailing_days": RVOL_TRAILING_DAYS,
        "universe_pool_lookback_days": UNIVERSE_POOL_LOOKBACK_DAYS,
        "universe_size": len(universe),
        "universe_sample_method": "sha1(ticker) hash order, first N -- see build_shared_universe()",
        "universe": universe,
        "tickers_with_no_candidates": tickers_with_no_candidates,
        "api_calls_made": calls_made,
        "catalyst_summary": catalyst_summary,
        "control_summary": control_summary,
        "catalyst_results": catalyst_results,
        "control_results": control_results,
        "screening_log": screening_log,
    }, indent=2, default=str))
    print(f"\nwrote {len(catalyst_results)} catalyst + {len(control_results)} control evaluated "
          f"candidates ({len(screening_log)} screening-log rows total) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
