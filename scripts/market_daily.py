"""Daily market-context orchestrator (trade-edge layer).

ONE cron entrypoint that computes and persists the daily market-context rows by
calling the FROZEN analysis modules — it does not re-implement any of the math:

    sector_rotation.compute_series        -> sector_rs_daily        (F1)
    factor_rotation.compute_factor_series -> factor_rs_daily        (F2)
    regime._compute_trend                 -> trend_daily            (F3)
    internal_breadth.compute_internal_breadth -> internal_breadth_daily (F5)

These are DESCRIPTIVE market-context reads (a view, not a buy/sell signal). The
back-tests found NO tradeable edge, so nothing here gates a live alert; the rows
are surfaced read-only and shadow-logged. Rotation labels honestly distinguish
'improving (early)' from 'leading (already moved)' so a finished move is never
read as a fresh entry.

Data source: the cached Parquet store (``data/market_store``) — the same point-in-
time closes the back-tests used, NEVER a live yfinance call at run time. Every
value at date t uses ONLY closes up to and including t (trailing windows + the
prior close), so the value computed on the full series equals the value computed
on the prefix to t.

Usage:
    python3 scripts/market_daily.py --dry-run                  # compute + gate, NO write
    python3 scripts/market_daily.py                            # seed (full window)
    python3 scripts/market_daily.py --days 3                   # self-heal last 3 days
    python3 scripts/market_daily.py --db /tmp/x.db --days 3    # target a NON-live db
    python3 scripts/market_daily.py --days 3 --dry-run

``--db PATH`` targets a specific SQLite db (tests pass a tmp_path; the daily cron
omits it and falls back to ``database.path`` from config). The needed tables are
created on first write via the shared ``db.SCHEMA`` (CREATE TABLE IF NOT EXISTS),
so a fresh temp db works without a separate migration step. INSERT OR REPLACE on
the table primary keys makes every run idempotent.

DO NOT run against the live consensus.db while the consensus-engine service /
market_daily.timer is also writing — SQLite serialises, but a one-time seed should
stop the timer or use --dry-run first.
"""
from __future__ import annotations

import argparse
import logging
import math
import random
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Project root on sys.path so consensus_engine imports resolve.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import config as cfg
from consensus_engine.analysis import sector_rotation as sr
from consensus_engine.analysis import factor_rotation as fr
from consensus_engine.analysis import regime
from consensus_engine.analysis import internal_breadth as ib

log = logging.getLogger("market_daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Union of every symbol the three reads need (sector ETFs + factor ETFs + SPY).
_SYMBOLS: tuple[str, ...] = (sr.BENCHMARK,) + sr.SECTOR_ETFS + fr.FACTOR_ETFS


# ---------------------------------------------------------------------------
# Parquet panel (point-in-time closes from the cached store)
# ---------------------------------------------------------------------------

def _resolve_store_dir(store_dir: str | None) -> Path:
    if store_dir is not None:
        return Path(store_dir)
    rel = cfg.get("features.market_data.store_dir", None) or cfg.get(
        "market_data.store_dir", "data/market_store")
    p = Path(rel)
    return p if p.is_absolute() else (_ROOT / p)


def _load_closes(store_dir: str | None = None) -> pd.DataFrame:
    """Wide date-indexed close panel (one column per symbol), aligned across all.

    Reads the same Parquet files the back-tests use (``data/market_store``); each
    file is a date-indexed OHLCV frame with a lowercase ``close`` column. Rows with
    any missing symbol are dropped so the panel is aligned (mirrors
    ``sector_rotation_daily._fetch_closes`` which does ``dropna(how='any')``).
    """
    sdir = _resolve_store_dir(store_dir)
    cols: dict[str, pd.Series] = {}
    for sym in _SYMBOLS:
        path = sdir / f"{sym}.parquet"
        if not path.exists():
            log.warning("[panel] missing series %s (%s) — skipping", sym, path)
            continue
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        cols[sym] = df["close"].astype(float)
    if sr.BENCHMARK not in cols:
        raise FileNotFoundError(
            f"benchmark {sr.BENCHMARK} not found in store {sdir}")
    panel = pd.DataFrame(cols).sort_index().dropna(how="any")
    return panel


def _cutoff(days_limit: int | None) -> str | None:
    if days_limit is None:
        return None
    return str((date.today() - timedelta(days=days_limit)).isoformat())


# ---------------------------------------------------------------------------
# Row building (delegates the math to the frozen modules)
# ---------------------------------------------------------------------------

def build_sector_rows(panel: pd.DataFrame, days_limit: int | None) -> list[dict]:
    n = int(cfg.get("features.sector_rotation.n_window", 10))
    k = int(cfg.get("features.sector_rotation.k_window", 5))
    d = float(cfg.get("features.sector_rotation.distance", 2))
    p = int(cfg.get("features.sector_rotation.persistence", 2))
    series = sr.compute_series(panel, n, k, d, p)
    dates = [str(ts)[:10] for ts in panel.index]
    cutoff = _cutoff(days_limit)
    rows: list[dict] = []
    for etf, cells in series.items():
        for i, cell in enumerate(cells):
            if cell is None:
                continue
            if cutoff is not None and dates[i] < cutoff:
                continue
            rows.append({
                "date_utc": dates[i], "etf": etf,
                "rs_ratio": cell["rs_ratio"], "rs_momentum": cell["rs_momentum"],
                "quadrant": cell["quadrant"],
                "inflection": 1 if cell["inflection"] else 0,
                "n_window": n, "k_window": k,
            })
    return rows


def build_factor_rows(panel: pd.DataFrame, days_limit: int | None) -> list[dict]:
    rw = int(cfg.get("features.factor_rotation.rs_window", 21))
    mw = int(cfg.get("features.factor_rotation.mom_window", 63))
    series = fr.compute_factor_series(panel, rw, mw)
    dates = [str(ts)[:10] for ts in panel.index]
    cutoff = _cutoff(days_limit)
    rows: list[dict] = []
    for etf, cells in series.items():
        for i, cell in enumerate(cells):
            if cell is None:
                continue
            if cutoff is not None and dates[i] < cutoff:
                continue
            accel = cell["accelerating"]
            rows.append({
                "date_utc": dates[i], "factor_etf": etf,
                "rs_vs_spy": cell["rs_vs_spy"], "rs_momentum": cell["rs_momentum"],
                "leading": 1 if cell["leading"] else 0,
                "accelerating": None if accel is None else (1 if accel else 0),
            })
    return rows


def build_trend_rows(panel: pd.DataFrame, days_limit: int | None) -> list[dict]:
    """Compute the SPY trend leg per date via the FROZEN ``regime._compute_trend``.

    Point-in-time: each date is computed from the prefix of closes ending at it.
    trend_daily PK is date_utc only (one index/date) -> SPY.
    """
    spy = [float(x) for x in panel[sr.BENCHMARK].tolist()]
    dates = [str(ts)[:10] for ts in panel.index]
    cutoff = _cutoff(days_limit)
    rows: list[dict] = []
    for i in range(len(spy)):
        d = dates[i]
        if cutoff is not None and d < cutoff:
            continue
        res = regime._compute_trend(spy[: i + 1], d, "SPY")
        if res is None:
            continue
        rows.append(res)
    return rows


def build_breadth_rows(db_path: str | None, days_limit: int | None) -> list[dict]:
    """Internal-breadth series via the FROZEN ``internal_breadth.compute_internal_breadth``.

    Reads the bot's OWN directional stream (``signal_events``) from ``db_path`` —
    the same db we seed, which in production is the live consensus.db that holds
    signal_events. Returns one row per date that has informed directional signals,
    shaped for ``internal_breadth_daily``; empty when the db / table is absent
    (a brand-new temp db with no signals yet). This is DESCRIPTIVE breadth (F5),
    point-in-time by construction (the expanding z-score uses only prior dates).
    """
    if not db_path:
        return []
    if not Path(db_path).exists():
        return []
    window = int(cfg.get("features.internal_breadth.window", 5))
    alpha = float(cfg.get("features.internal_breadth.ema_alpha", 0.4))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_events'"
        ).fetchone()
        if not has:
            return []
        rows = conn.execute(
            "SELECT ticker, direction, source_type, recorded_at FROM signal_events"
        ).fetchall()
    finally:
        conn.close()
    series = ib.compute_internal_breadth(rows, window, alpha)
    cutoff = _cutoff(days_limit)
    return [c for c in series if cutoff is None or c["date_utc"] >= cutoff]


# ---------------------------------------------------------------------------
# Correctness gate — independent pandas recompute on >=3 sampled rows per table
# ---------------------------------------------------------------------------

def _pop_zscore_last(arr) -> float:
    # Drop NaN so an early-history rolling window (fewer than the cap of valid
    # distance points, with leading NaN from the 200-day SMA warm-up) computes
    # the z over the VALID points only — mirroring regime._compute_trend, which
    # builds its dist_series from valid distances exclusively. Without this the
    # NaN poison std -> NaN -> 0.0 and the gate spuriously fails early dates.
    arr = arr[~pd.isna(arr)]
    if len(arr) == 0:
        return 0.0
    m = arr.mean()
    s = arr.std(ddof=0)
    return float((arr[-1] - m) / s) if s > 0 else 0.0


def _gate_sector(rows: list[dict], panel: pd.DataFrame, tol: float = 1e-9) -> int:
    if not rows:
        return 0
    n = rows[0]["n_window"]
    k = rows[0]["k_window"]
    spy = panel[sr.BENCHMARK].astype(float)
    pos = {str(ts)[:10]: i for i, ts in enumerate(panel.index)}

    def pop_z(s: pd.Series, w: int) -> pd.Series:
        mean = s.rolling(w).mean()
        std = s.rolling(w).std(ddof=0)
        z = (s - mean) / std
        return z.where(std > 0, 0.0)

    sample = random.sample(rows, min(5, len(rows)))
    fails = []
    for row in sample:
        etf = row["etf"]
        rs = 100.0 * panel[etf].astype(float) / spy
        rs_ratio = 100.0 + pop_z(rs, n)
        roc = rs_ratio.diff(1)
        rs_mom = 100.0 + pop_z(roc, k)
        i = pos[row["date_utc"]]
        exp_rr, exp_rm = float(rs_ratio.iloc[i]), float(rs_mom.iloc[i])
        if abs(exp_rr - row["rs_ratio"]) > tol or abs(exp_rm - row["rs_momentum"]) > tol:
            fails.append(f"  sector {row['date_utc']} {etf}: rr {exp_rr} vs {row['rs_ratio']} "
                         f"rm {exp_rm} vs {row['rs_momentum']}")
    if fails:
        raise AssertionError("sector gate FAILED:\n" + "\n".join(fails))
    return len(sample)


def _gate_factor(rows: list[dict], panel: pd.DataFrame, tol: float = 1e-9) -> int:
    if not rows:
        return 0
    rw = int(cfg.get("features.factor_rotation.rs_window", 21))
    mw = int(cfg.get("features.factor_rotation.mom_window", 63))
    spy = panel[sr.BENCHMARK].astype(float)
    pos = {str(ts)[:10]: i for i, ts in enumerate(panel.index)}
    sample = random.sample(rows, min(5, len(rows)))
    fails = []
    for row in sample:
        etf = row["factor_etf"]
        rs = 100.0 * panel[etf].astype(float) / spy
        rsv = 100.0 * (rs / rs.shift(rw) - 1.0)
        rmo = 100.0 * (rs / rs.shift(mw) - 1.0)
        i = pos[row["date_utc"]]
        exp_v, exp_m = float(rsv.iloc[i]), float(rmo.iloc[i])
        if abs(exp_v - row["rs_vs_spy"]) > tol or abs(exp_m - row["rs_momentum"]) > tol:
            fails.append(f"  factor {row['date_utc']} {etf}: v {exp_v} vs {row['rs_vs_spy']} "
                         f"m {exp_m} vs {row['rs_momentum']}")
    if fails:
        raise AssertionError("factor gate FAILED:\n" + "\n".join(fails))
    return len(sample)


def _gate_trend(rows: list[dict], panel: pd.DataFrame, tol: float = 1e-6) -> int:
    if not rows:
        return 0
    sma_slow = cfg.get("features.trend_regime.sma_slow", 200)
    sma_fast = cfg.get("features.trend_regime.sma_fast", 50)
    tsmom_lb = cfg.get("features.trend_regime.tsmom_lookback_days", 63)
    slope_window = cfg.get("features.trend_regime.slope_window", 10)
    dist_cap = regime._DIST_Z_MAX_POINTS

    closes = panel[sr.BENCHMARK].astype(float)
    pos = {str(ts)[:10]: i for i, ts in enumerate(panel.index)}
    sma200 = closes.rolling(sma_slow).mean()
    sma50 = closes.rolling(sma_fast).mean()
    slope = (sma50 - sma50.shift(slope_window)) / sma50.shift(slope_window)
    tsmom = closes / closes.shift(tsmom_lb) - 1.0
    dist = closes / sma200 - 1.0
    distz = dist.rolling(dist_cap, min_periods=1).apply(_pop_zscore_last, raw=True)

    sample = random.sample(rows, min(5, len(rows)))
    fails = []
    for row in sample:
        i = pos[row["date_utc"]]
        checks = {
            "sma_200": (float(sma200.iloc[i]), row["sma_200"]),
            "sma_50": (float(sma50.iloc[i]), row["sma_50"]),
            "sma_50_slope": (float(slope.iloc[i]), row["sma_50_slope"]),
            "tsmom_3m": (float(tsmom.iloc[i]), row["tsmom_3m"]),
            "dist_200_z": (float(distz.iloc[i]), row["dist_200_z"]),
        }
        for name, (exp, got) in checks.items():
            if abs(exp - got) > tol:
                fails.append(f"  trend {row['date_utc']} {name}: {exp} vs {got}")
    if fails:
        raise AssertionError("trend gate FAILED:\n" + "\n".join(fails))
    return len(sample)


# ---------------------------------------------------------------------------
# Persistence (idempotent INSERT OR REPLACE into the target db)
# ---------------------------------------------------------------------------

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.create_function("unixepoch", 0, lambda: int(time.time()))  # 3.38 shim, mirror db.py
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the market tables if absent (CREATE TABLE IF NOT EXISTS, shared DDL)."""
    from consensus_engine.db import SCHEMA
    conn.executescript(SCHEMA)


def seed(conn: sqlite3.Connection, sector_rows: list[dict],
         factor_rows: list[dict], trend_rows: list[dict],
         breadth_rows: list[dict] | None = None) -> None:
    now_ts = time.time()
    for r in sector_rows:
        conn.execute(
            """INSERT OR REPLACE INTO sector_rs_daily
               (date_utc, etf, rs_ratio, rs_momentum, quadrant, inflection,
                n_window, k_window, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["etf"], r["rs_ratio"], r["rs_momentum"], r["quadrant"],
             r["inflection"], r["n_window"], r["k_window"], now_ts),
        )
    for r in factor_rows:
        conn.execute(
            """INSERT OR REPLACE INTO factor_rs_daily
               (date_utc, factor_etf, rs_vs_spy, rs_momentum, leading,
                accelerating, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["factor_etf"], r["rs_vs_spy"], r["rs_momentum"],
             r["leading"], r["accelerating"], now_ts),
        )
    for r in trend_rows:
        conn.execute(
            """INSERT OR REPLACE INTO trend_daily
               (date_utc, index_symbol, close, sma_200, sma_50, sma_50_slope,
                tsmom_3m, dist_200_z, trend_state, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["index_symbol"], r["close"], r["sma_200"], r["sma_50"],
             r["sma_50_slope"], r["tsmom_3m"], r["dist_200_z"], r["trend_state"], now_ts),
        )
    for r in (breadth_rows or []):
        conn.execute(
            """INSERT OR REPLACE INTO internal_breadth_daily
               (date_utc, net_bull_bear, n_bullish, n_bearish, osc_z, n_signals,
                computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r["date_utc"], r["net_bull_bear"], r["n_bullish"], r["n_bearish"],
             r["osc_z"], r["n_signals"], now_ts),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run(db_path: str, days: int | None, dry_run: bool,
        store_dir: str | None = None) -> dict[str, int]:
    """Compute + gate + persist the daily market-context rows; return write counts.

    ``db_path``    target SQLite db (NON-live in tests). Ignored on dry-run.
    ``days``       self-heal window (last N calendar days); None = full backfill.
    ``dry_run``    compute + run the correctness gate but write nothing.
    ``store_dir``  override the Parquet store dir (tests point at data/market_store).
    """
    panel = _load_closes(store_dir)
    if panel.empty:
        log.error("[market_daily] empty close panel — check the store at %s",
                  _resolve_store_dir(store_dir))
        return {"sector_rs_daily": 0, "factor_rs_daily": 0, "trend_daily": 0,
                "internal_breadth_daily": 0}
    log.info("[market_daily] panel %d rows, %s -> %s (%d symbols)",
             len(panel), str(panel.index[0])[:10], str(panel.index[-1])[:10],
             panel.shape[1])

    sector_rows = build_sector_rows(panel, days)
    factor_rows = build_factor_rows(panel, days)
    trend_rows = build_trend_rows(panel, days)
    # F5 breadth reads the bot's OWN directional stream (signal_events) from the
    # target db, not the parquet panel — empty on a fresh db with no signals.
    breadth_rows = build_breadth_rows(db_path, days)

    # Correctness gate BEFORE any write (independent pandas recompute).
    checked = (_gate_sector(sector_rows, panel)
               + _gate_factor(factor_rows, panel)
               + _gate_trend(trend_rows, panel))
    log.info("[gate] correctness check PASSED on %d sampled rows "
             "(sector+factor+trend, independent pandas recompute)", checked)

    summary = {
        "sector_rs_daily": len(sector_rows),
        "factor_rs_daily": len(factor_rows),
        "trend_daily": len(trend_rows),
        "internal_breadth_daily": len(breadth_rows),
    }
    if dry_run:
        log.info("[dry-run] computed %s — NO writes performed.", summary)
        return summary

    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        seed(conn, sector_rows, factor_rows, trend_rows, breadth_rows)
    finally:
        conn.close()
    log.info("[market_daily] seeded %s into %s", summary, db_path)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily market-context orchestrator: seed sector_rs_daily / "
                    "factor_rs_daily / trend_daily from the cached Parquet store.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute + run the correctness gate; do NOT write.")
    parser.add_argument("--days", type=int, default=None, metavar="N",
                        help="Self-heal: re-seed only the last N calendar days.")
    parser.add_argument("--db", type=str, default=None, metavar="PATH",
                        help="Target SQLite db (default: database.path from config). "
                             "Pass a NON-live path for backfills/tests.")
    parser.add_argument("--store-dir", type=str, default=None, metavar="DIR",
                        help="Override the Parquet store dir "
                             "(default: features.market_data.store_dir).")
    args = parser.parse_args()

    db_path = args.db or cfg.get(
        "database.path", "/home/openclaw/.openclaw/workspace/consensus.db")

    summary = run(db_path=db_path, days=args.days, dry_run=args.dry_run,
                  store_dir=args.store_dir)
    total = sum(summary.values())
    if total == 0 and args.days is not None:
        log.info("Self-heal: no new trading days in last %d days — already current.",
                 args.days)
        return 0
    if total == 0:
        log.error("No rows computed — check the Parquet store coverage.")
        return 1
    print()
    print(f"Rows {'computed (dry-run)' if args.dry_run else 'seeded'}: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
