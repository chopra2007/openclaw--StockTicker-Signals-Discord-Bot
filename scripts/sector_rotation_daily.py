"""F1 daily cron: compute sector-rotation RRG rows and seed ``sector_rs_daily``.

Mirrors ``scripts/backfill_regime_daily.py``: fetches daily closes via yfinance,
computes the rows with the exact math in
``consensus_engine.analysis.sector_rotation`` (point-in-time, prior close only),
runs an independent pandas correctness gate, then INSERT OR REPLACEs into
``sector_rs_daily`` (idempotent on the (date_utc, etf) PK).

Usage:
    python3 scripts/sector_rotation_daily.py --dry-run        # print, NO DB write
    python3 scripts/sector_rotation_daily.py                  # seed (full window)
    python3 scripts/sector_rotation_daily.py --days 3         # self-heal last 3 days
    python3 scripts/sector_rotation_daily.py --days 3 --dry-run

Constraint 8 (final-plan §0): ETF closes are pulled with ``auto_adjust=False``
(RAW closes) so dividend restatement can't silently change historical RS ratios.

DO NOT run against the live consensus.db while the market_daily.timer is also
writing — SQLite serialises but a one-time seed should stop the timer or use
--dry-run first.
"""
from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

# Ensure the project root is on sys.path so consensus_engine imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consensus_engine import config as cfg
from consensus_engine.analysis import sector_rotation as sr

log = logging.getLogger("sector_rotation_daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Data fetch
# ---------------------------------------------------------------------------

def _fetch_closes(period: str = "2y") -> pd.DataFrame:
    """Download RAW (auto_adjust=False) daily closes for SPY + the 13 ETFs.

    Returns a date-indexed DataFrame with one column per symbol (SPY included),
    rows with any missing symbol dropped so the panel is aligned.
    """
    symbols = [sr.BENCHMARK, *sr.SECTOR_ETFS]
    raw = yf.download(symbols, period=period, interval="1d", auto_adjust=False,
                      progress=False, group_by="column")
    # yf.download with multiple tickers -> columns MultiIndex (field, ticker).
    close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    close = close.dropna(how="any")
    close.index = pd.to_datetime(close.index)
    return close.sort_index()


# ---------------------------------------------------------------------------
# Independent correctness gate (pandas re-implementation, like backfill_regime)
# ---------------------------------------------------------------------------

def _independent_check(rows: list[dict], closes_df: pd.DataFrame,
                       n: int, k: int, tolerance: float = 1e-9) -> None:
    """Re-compute >=5 sampled rows with pandas .rolling and assert they match.

    A genuinely separate implementation (pandas rolling) of the hand-rolled
    trailing-window math in sector_rotation, so a refactor that breaks the math
    is caught before any DB write.
    """
    spy = closes_df[sr.BENCHMARK].astype(float)
    date_pos = {str(ts)[:10]: i for i, ts in enumerate(closes_df.index)}

    def pop_z(s: pd.Series, window: int) -> pd.Series:
        mean = s.rolling(window).mean()
        std = s.rolling(window).std(ddof=0)
        z = (s - mean) / std
        return z.where(std > 0, 0.0)

    sample = random.sample(rows, min(10, len(rows)))
    failures = []
    for row in sample:
        etf = row["etf"]
        rs = 100.0 * closes_df[etf].astype(float) / spy
        rs_ratio = 100.0 + pop_z(rs, n)
        roc = rs_ratio.diff(1)
        rs_mom = 100.0 + pop_z(roc, k)
        i = date_pos[row["date_utc"]]
        exp_rr = float(rs_ratio.iloc[i])
        exp_rm = float(rs_mom.iloc[i])
        if (abs(exp_rr - row["rs_ratio"]) > tolerance
                or abs(exp_rm - row["rs_momentum"]) > tolerance):
            failures.append(
                f"  {row['date_utc']} {etf}: rr exp={exp_rr:.10f} got={row['rs_ratio']:.10f} "
                f"rm exp={exp_rm:.10f} got={row['rs_momentum']:.10f}"
            )
    if failures:
        raise AssertionError(
            f"Correctness gate FAILED ({len(failures)}/{len(sample)} samples):\n"
            + "\n".join(failures)
        )
    log.info("[gate] Correctness check PASSED: %d/%d sampled rows match pandas recompute",
             len(sample), len(sample))


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------

def build_rows(closes_df: pd.DataFrame, days_limit: int | None = None) -> list[dict]:
    """Compute every (date, etf) row with enough history; optionally last N days.

    Uses the canonical sector_rotation.compute_series (point-in-time), then emits
    rows. ``days_limit`` re-seeds only the last N calendar days (self-heal).
    """
    n = int(cfg.get("features.sector_rotation.n_window", 10))
    k = int(cfg.get("features.sector_rotation.k_window", 5))
    d = float(cfg.get("features.sector_rotation.distance", 2))
    p = int(cfg.get("features.sector_rotation.persistence", 2))

    series = sr.compute_series(closes_df, n, k, d, p)
    dates = [str(ts)[:10] for ts in closes_df.index]
    cutoff = (str((date.today() - timedelta(days=days_limit)).isoformat())
              if days_limit is not None else None)

    rows: list[dict] = []
    for etf, cells in series.items():
        for i, cell in enumerate(cells):
            if cell is None:
                continue
            if cutoff is not None and dates[i] < cutoff:
                continue
            rows.append({
                "date_utc": dates[i],
                "etf": etf,
                "rs_ratio": cell["rs_ratio"],
                "rs_momentum": cell["rs_momentum"],
                "quadrant": cell["quadrant"],
                "inflection": 1 if cell["inflection"] else 0,
                "n_window": n,
                "k_window": k,
            })
    return rows


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def _db_connect() -> sqlite3.Connection:
    path = cfg.get("database.path", "/home/openclaw/.openclaw/workspace/consensus.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def seed_db(rows: list[dict], conn: sqlite3.Connection) -> None:
    now_ts = time.time()
    for row in rows:
        conn.execute(
            """INSERT OR REPLACE INTO sector_rs_daily
               (date_utc, etf, rs_ratio, rs_momentum, quadrant, inflection,
                n_window, k_window, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (row["date_utc"], row["etf"], row["rs_ratio"], row["rs_momentum"],
             row["quadrant"], row["inflection"], row["n_window"], row["k_window"],
             now_ts),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute sector-rotation RRG rows and seed sector_rs_daily."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print rows; do NOT write to DB.")
    parser.add_argument("--days", type=int, default=None, metavar="N",
                        help="Self-heal: re-seed only the last N calendar days.")
    args = parser.parse_args()

    n = int(cfg.get("features.sector_rotation.n_window", 10))
    k = int(cfg.get("features.sector_rotation.k_window", 5))

    log.info("Fetching 2y daily closes (auto_adjust=False) for SPY + %d ETFs …",
             len(sr.SECTOR_ETFS))
    closes_df = _fetch_closes(period="2y")
    if closes_df.empty:
        log.error("No close data fetched — check yfinance coverage.")
        return 1
    log.info("Closes fetched: %d rows, %s → %s",
             len(closes_df), str(closes_df.index[0])[:10], str(closes_df.index[-1])[:10])

    rows = build_rows(closes_df, days_limit=args.days)
    if not rows:
        if args.days is not None:
            log.info("Self-heal: no new trading days in last %d days — already current.",
                     args.days)
            return 0
        log.error("No rows computed — check ETF data coverage.")
        return 1

    log.info("Running correctness gate …")
    _independent_check(rows, closes_df, n, k)

    quad_count: dict[str, int] = {}
    infl = 0
    for r in rows:
        quad_count[r["quadrant"]] = quad_count.get(r["quadrant"], 0) + 1
        infl += r["inflection"]
    print()
    print(f"Rows to {'print' if args.dry_run else 'seed'}: {len(rows)}")
    print(f"Quadrant distribution: {quad_count}")
    print(f"Inflections (lagging->improving): {infl}")
    print(f"Date range: {rows[0]['date_utc']} → {rows[-1]['date_utc']}")
    print()

    if args.dry_run:
        latest = rows[-1]["date_utc"]
        print(f"Latest date {latest}:")
        for r in rows:
            if r["date_utc"] == latest:
                print(f"  {r['etf']:<5s} rr={r['rs_ratio']:7.3f} rm={r['rs_momentum']:7.3f} "
                      f"{r['quadrant']:<9s} inflection={r['inflection']}")
        log.info("[dry-run] No writes performed.")
        return 0

    conn = _db_connect()
    seed_db(rows, conn)
    conn.close()
    log.info("Seeded %d rows into sector_rs_daily.", len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
