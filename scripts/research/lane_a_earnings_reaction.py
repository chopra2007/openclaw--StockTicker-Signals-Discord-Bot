#!/usr/bin/env python3
"""Lane A -- earnings reaction continuation.

Event-reaction short-duration research, Lane A only. Governed by
.omc/plans/event-reaction-short-duration-scanner-research-prompt.md
sections 5-13. Builds the Lane A slice of the shared point-in-time event
table, applies realistic entry timing, splits chronologically into a
development period (used to freeze the rule -- see
.omc/research/event-reaction-short-duration/hypotheses-v1.md, "## Lane A")
and an untouched evaluation period, then runs the frozen rule once on eval.

Event source: yfinance Ticker.earnings_dates (real historical report date +
time, EPS estimate/actual/surprise -- cross-validated 97.8% exact-day
against SEC EDGAR 8-K filings, see lane-ac-resolvability.md). Finnhub's
earnings calendar CANNOT be used -- confirmed no historical report-date
field beyond ~3 weeks back (data-capability-audit.md item 6).

Price data: Schwab extended-hours bars via schwab_client.get_price_history
called DIRECTLY (never consensus_engine.utils.prices.fetch_history, which
does not pass extended_hours through -- briefing.md section "Code
inconsistency"). 30-minute bars for the 20-day premarket baseline (reach
verified live 2025-12-07, see probe output in the builder verdict -- do NOT
compute this baseline from 1-minute bars, briefing.md do-not-repeat #4).
5-minute bars, pulled in narrow per-event windows (not one big per-ticker
pull -- a single large 5-minute pull was observed to silently truncate to
the most recent ~40,000 candles, which would drop older history for liquid
tickers), for the entry price and the 30/60-minute outcome measurement.

Read-only against consensus.db. No production writes. Raw pulls cached
under /tmp/event-reaction-audit/lane_a_cache/ (gitignored scratch, outside
the repo). No secrets printed.

Usage:
  python3 scripts/research/lane_a_earnings_reaction.py --stage build
  python3 scripts/research/lane_a_earnings_reaction.py --stage dev-inspect
  python3 scripts/research/lane_a_earnings_reaction.py --stage eval-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consensus_engine.scanners import schwab_client  # noqa: E402
from consensus_engine.utils.prices import fetch_history  # noqa: E402

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
DB_PATH = ROOT / "consensus.db"
OUT_DIR = ROOT / ".omc" / "research" / "event-reaction-short-duration"
CACHE_DIR = Path("/tmp/event-reaction-audit/lane_a_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Universe: same method as Phase A's build_shared_universe -- every ticker
# the bot alerted on in the trailing lookback, sha1-hashed (never Python's
# salted builtin hash()), first N in hash order. This project has no fixed
# tracked-ticker list (config/consensus.yaml's watchlist is DB-driven via
# get_active_tickers(), confirmed in briefing.md); alert_history is the
# closest thing to "tickers this project actually follows."
# --------------------------------------------------------------------------
UNIVERSE_POOL_LOOKBACK_DAYS = 365
UNIVERSE_CAP = 200

# Verified live 2026-08-23 (bounded probe, 5 tickers x 2 intervals): 30m
# extended-hours reach is 2025-12-07 for every ticker tried, identical to
# the independent data-capability-audit.md. Leave a couple days of margin.
SCHWAB_30M_REACH = date(2025, 12, 8)
RVOL_TRAILING_DAYS = 20

PREMARKET_START = dtime(9, 0)   # ET; = 6:00am Pacific
PREMARKET_END = dtime(9, 30)    # ET; = 6:30am Pacific (exclusive)
REGULAR_OPEN = dtime(9, 30)     # ET

# Realistic timing (research prompt section 9). Frozen, not tuned per event.
DETECTION_DELAY_MIN = 5     # system catches the public print
DELIVERY_DELAY_MIN = 2      # Discord delivery
OWNER_DELAY_MIN = 5         # owner's reaction delay, per the prompt's own wording
OWNER_WINDOW_START_PT = dtime(6, 15)
OWNER_WINDOW_END_PT = dtime(6, 45)

SECTOR_MAP_PATH = ROOT / "consensus_engine" / "data" / "sector_map.yaml"


def _connect_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _load_sector_map() -> dict[str, str]:
    import yaml
    d = yaml.safe_load(SECTOR_MAP_PATH.read_text())
    return {k.upper(): v for k, v in d.get("mappings", {}).items()}


def build_universe(cap: int) -> list[str]:
    conn = _connect_ro()
    try:
        since_ts = time.time() - UNIVERSE_POOL_LOOKBACK_DAYS * 86400
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM alert_history WHERE alerted_at >= ?", (since_ts,),
        ).fetchall()
    finally:
        conn.close()
    pool = sorted({r["ticker"].upper() for r in rows})
    ranked = sorted(pool, key=lambda t: hashlib.sha1(t.encode()).hexdigest())
    sample = ranked[:cap] if cap else ranked
    print(f"universe pool: {len(pool)} distinct tickers alerted on in the last "
          f"{UNIVERSE_POOL_LOOKBACK_DAYS} days; hash-sampled to {len(sample)}")
    return sorted(sample)


def ticker_alert_days(ticker: str, since_ts: float) -> set[str]:
    """Every day this ticker had ANY alert -- controls exclude these entirely
    so 'no identifiable catalyst' stays a genuine claim. Same convention as
    Phase A's H1v3 script."""
    conn = _connect_ro()
    try:
        rows = conn.execute(
            """SELECT DISTINCT date(alerted_at, 'unixepoch', 'localtime') AS d
               FROM alert_history WHERE ticker=? AND alerted_at>=?""",
            (ticker, since_ts),
        ).fetchall()
    finally:
        conn.close()
    return {r["d"] for r in rows}


# --------------------------------------------------------------------------
# yfinance earnings_dates -- raw manifest (uncorrected, preserved separately)
# --------------------------------------------------------------------------
def fetch_earnings_dates_cached(ticker: str) -> list[dict]:
    cache_path = CACHE_DIR / f"earnings_{ticker}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    try:
        ed = yf.Ticker(ticker).earnings_dates
    except Exception as exc:
        print(f"  [{ticker}] yfinance earnings_dates failed: {type(exc).__name__}: {exc}")
        ed = None
    rows: list[dict] = []
    if ed is not None and not ed.empty:
        for ts, row in ed.iterrows():
            rows.append({
                "ticker": ticker,
                "report_ts_et": ts.isoformat(),
                "eps_estimate": None if row["EPS Estimate"] != row["EPS Estimate"] else float(row["EPS Estimate"]),
                "reported_eps": None if row["Reported EPS"] != row["Reported EPS"] else float(row["Reported EPS"]),
                "surprise_pct": None if row["Surprise(%)"] != row["Surprise(%)"] else float(row["Surprise(%)"]),
            })
    cache_path.write_text(json.dumps(rows, indent=2))
    return rows


# --------------------------------------------------------------------------
# Schwab 30-minute bars (full-window, one call per ticker) -- baseline +
# reference level. Direct schwab_client call, extended_hours=True.
# --------------------------------------------------------------------------
def fetch_30m_cached(ticker: str, start_dt: datetime, end_dt: datetime):
    cache_path = CACHE_DIR / f"30m_{ticker}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if payload is None:
            return None
        import pandas as pd
        df = pd.DataFrame(payload["data"])
        df.index = pd.to_datetime(df["index"], utc=True).dt.tz_convert(ET)
        return df[["Open", "High", "Low", "Close", "Volume"]]
    try:
        df = schwab_client.get_price_history(
            ticker, interval="30m", start=start_dt, end=end_dt, extended_hours=True,
        )
    except Exception as exc:
        print(f"  [{ticker}] 30m fetch failed: {type(exc).__name__}: {exc}")
        df = None
    if df is None or df.empty:
        cache_path.write_text(json.dumps(None))
        return None
    payload = {"data": df.reset_index().assign(index=lambda d: d["Date"].astype(str)).drop(columns=["Date"]).to_dict("records")}
    cache_path.write_text(json.dumps(payload, default=str))
    return df


def premarket_30m_bar(df, day: date):
    """The single 09:00-09:29 ET 30-minute bar for `day`, or None."""
    day_pm = df[(df.index.date == day) & (df.index.time == PREMARKET_START)]
    if day_pm.empty:
        return None
    return day_pm.iloc[0]


def rvol_30m(df, day: date) -> dict | None:
    """20-day trailing MEDIAN (per research prompt section 5's exact wording
    -- 'its own prior 20-day 6:00-6:29am Pacific median', not a mean) of the
    premarket 30-minute bar's Volume, vs `day`'s own bar."""
    pm_days = sorted({d for d in df[(df.index.time == PREMARKET_START)].index.date})
    if day not in pm_days:
        return None
    idx = pm_days.index(day)
    prior = pm_days[:idx]
    if len(prior) < RVOL_TRAILING_DAYS:
        return None
    baseline_days = prior[-RVOL_TRAILING_DAYS:]
    baseline_vals = [float(df[(df.index.date == d) & (df.index.time == PREMARKET_START)]["Volume"].iloc[0])
                      for d in baseline_days]
    baseline_median = statistics.median(baseline_vals)
    day_bar = premarket_30m_bar(df, day)
    if day_bar is None or baseline_median <= 0:
        return None
    return {
        "rvol": float(day_bar["Volume"]) / baseline_median,
        "baseline_median_shares": baseline_median,
        "baseline_days": [str(d) for d in baseline_days],
        "day_volume_shares": float(day_bar["Volume"]),
    }


# --------------------------------------------------------------------------
# Schwab 5-minute bars -- narrow per-event window (avoids the ~40,000-row
# response cap observed on a single full-window pull, which silently
# truncates older history for liquid tickers).
# --------------------------------------------------------------------------
def fetch_5m_window_cached(ticker: str, start_dt: datetime, end_dt: datetime):
    key = f"5m_{ticker}_{start_dt.date()}_{end_dt.date()}"
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if payload is None:
            return None
        import pandas as pd
        df = pd.DataFrame(payload["data"])
        df.index = pd.to_datetime(df["index"], utc=True).dt.tz_convert(ET)
        return df[["Open", "High", "Low", "Close", "Volume"]]
    try:
        df = schwab_client.get_price_history(
            ticker, interval="5m", start=start_dt, end=end_dt, extended_hours=True,
        )
    except Exception as exc:
        print(f"  [{ticker}] 5m fetch failed: {type(exc).__name__}: {exc}")
        df = None
    if df is None or df.empty:
        cache_path.write_text(json.dumps(None))
        return None
    payload = {"data": df.reset_index().assign(index=lambda d: d["Date"].astype(str)).drop(columns=["Date"]).to_dict("records")}
    cache_path.write_text(json.dumps(payload, default=str))
    return df


def daily_closes_cached(ticker: str, start_dt: datetime, end_dt: datetime):
    key = f"1d_{ticker}"
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        payload = json.loads(cache_path.read_text())
        if payload is None:
            return None
        import pandas as pd
        df = pd.DataFrame(payload["data"])
        df.index = pd.to_datetime(df["index"], utc=True).dt.tz_convert(ET)
        return df[["Open", "High", "Low", "Close", "Volume"]]
    try:
        df = fetch_history(ticker, start=start_dt - timedelta(days=10), end=end_dt + timedelta(days=1), interval="1d")
    except Exception as exc:
        print(f"  [{ticker}] daily fetch failed: {type(exc).__name__}: {exc}")
        df = None
    if df is None or df.empty:
        cache_path.write_text(json.dumps(None))
        return None
    payload = {"data": df.reset_index().rename(columns={df.reset_index().columns[0]: "index"}).assign(index=lambda d: d["index"].astype(str)).to_dict("records")}
    cache_path.write_text(json.dumps(payload, default=str))
    return df


def prior_close(daily_df, day: date) -> float | None:
    if daily_df is None:
        return None
    idx = daily_df.index
    dates = idx.date if hasattr(idx, "date") else [d.date() for d in idx]
    prior_rows = daily_df[[d < day for d in dates]]
    if prior_rows.empty:
        return None
    return float(prior_rows["Close"].iloc[-1])


def next_trading_day(df_30m, day: date) -> date | None:
    """Next trading day present in this ticker's own 30m bar index, after `day`."""
    days = sorted({d for d in df_30m.index.date})
    later = [d for d in days if d > day]
    return later[0] if later else None


def next_trading_day_from_daily(daily_df, day: date) -> date | None:
    """Same idea as next_trading_day() but sourced from a daily-bar index
    (used for close/next-open/next-close, which need the ticker's own daily
    series, not the 30m series)."""
    if daily_df is None:
        return None
    days = sorted({d for d in daily_df.index.date})
    later = [d for d in days if d > day]
    return later[0] if later else None


if __name__ == "__main__":
    print("This module is imported by lane_a_pipeline.py -- run that instead.")
