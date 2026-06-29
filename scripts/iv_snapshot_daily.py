"""#55 Build B — daily options-implied IV / expected-move snapshot logger.

ONE cron entrypoint that captures the point-in-time options state (ATM implied
volatility, ATM-straddle expected move, and IV-implied expected move to expiry)
for a bounded ticker universe and persists one row per ticker per day into
`iv_snapshots`. This data is computed live from the yfinance option chain and is
NOT backfillable — every unlogged day is gone — which is why it is logged forward.

It does NOT re-implement the expected-move math: it calls the FROZEN
`consensus_engine.scanners.expected_move.compute_em`, the same code path behind
the `!em` Discord command, and just reads the fields off its result.

Universe: a small, always-included liquid core (SPY, QQQ, NVDA, ...) UNIONed with
the engine's currently-active watchlist (tickers with unexpired `ticker_signals`
in the target db). Pass `--tickers A,B,C` to override the whole universe.

Fail-soft: a per-ticker yfinance / option-chain error (EMUnavailable or anything
else) logs a warning and skips that ticker — one bad symbol never aborts the run.
A ~1s sleep between tickers respects yfinance's ~15-min option-data freshness and
its rate limits.

Retention: after writing, rows older than ``--retention-days`` (default 750) are
pruned so the table stays bounded.

Usage:
    python3 scripts/iv_snapshot_daily.py --dry-run                 # compute + print, NO write
    python3 scripts/iv_snapshot_daily.py                           # core ∪ watchlist, upsert
    python3 scripts/iv_snapshot_daily.py --tickers SPY,QQQ,NVDA    # explicit universe
    python3 scripts/iv_snapshot_daily.py --db /tmp/x.db            # target a NON-live db
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Project root on sys.path so consensus_engine imports resolve.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import config as cfg
from consensus_engine.scanners import expected_move as em

log = logging.getLogger("iv_snapshot_daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Small, always-included liquid core (mega-cap + the main index/sector proxies).
LIQUID_CORE: tuple[str, ...] = (
    "SPY", "QQQ", "NVDA", "AAPL", "MSFT", "TSLA", "AMD", "META", "AMZN", "GOOGL",
)

_PER_TICKER_SLEEP = 1.0  # seconds between yfinance pulls (freshness + rate-limit respect)


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------
def _active_watchlist(db_path: str) -> list[str]:
    """Tickers with unexpired signals in the target db (the engine's active
    watchlist). Read-only and fail-soft: a missing db/table returns []."""
    if not db_path or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception as e:  # noqa: BLE001
        log.warning("[universe] could not open %s read-only (%s) — core only", db_path, e)
        return []
    try:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_signals'"
        ).fetchone()
        if not has:
            return []
        rows = conn.execute(
            "SELECT ticker FROM ticker_signals WHERE expires_at > ? "
            "GROUP BY ticker ORDER BY COUNT(*) DESC",
            (time.time(),),
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("[universe] watchlist read failed (%s) — core only", e)
        return []
    finally:
        conn.close()
    return [r[0] for r in rows if r and r[0]]


def build_universe(explicit: str | None, db_path: str) -> list[str]:
    """Resolve the snapshot universe. ``--tickers`` overrides everything; otherwise
    the liquid core UNIONed with the active watchlist (core first, de-duped)."""
    if explicit:
        seen: dict[str, None] = {}
        for t in explicit.split(","):
            t = t.strip().upper()
            if t:
                seen.setdefault(t, None)
        return list(seen)
    seen = {t: None for t in LIQUID_CORE}
    for t in _active_watchlist(db_path):
        seen.setdefault(t.upper(), None)
    return list(seen)


# ---------------------------------------------------------------------------
# Compute (delegates the math to the frozen expected_move module)
# ---------------------------------------------------------------------------
def _clean(x) -> float | None:
    """NaN / inf / None -> None; otherwise a plain float (don't store NaN)."""
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return xf if math.isfinite(xf) else None


async def _snapshot_one(ticker: str, snapshot_date: str) -> dict | None:
    """Compute one ticker's IV snapshot via compute_em. Returns a row dict, or
    None on any failure (logged) so the caller can skip it."""
    try:
        res = await em.compute_em(ticker)
    except em.EMUnavailable as e:
        log.warning("[iv] %s skipped — %s", ticker, e)
        return None
    except Exception as e:  # noqa: BLE001 — never let one symbol abort the run
        log.warning("[iv] %s skipped — unexpected error: %s", ticker, e)
        return None
    moves = res.em or {}
    return {
        "snapshot_date": snapshot_date,
        "ticker": ticker.upper(),
        "spot": _clean(res.spot),
        "atm_iv": _clean(moves.get("atm_iv")),
        "straddle_em": _clean(moves.get("raw_straddle_em")),
        "iv_em_to_expiry": _clean(moves.get("iv_em_to_expiration")),
        "expiry": res.expiration,
        "captured_at": time.time(),
    }


async def compute_rows(universe: list[str], snapshot_date: str,
                       sleep_s: float = _PER_TICKER_SLEEP) -> list[dict]:
    rows: list[dict] = []
    for i, ticker in enumerate(universe):
        row = await _snapshot_one(ticker, snapshot_date)
        if row is not None:
            rows.append(row)
        if i < len(universe) - 1 and sleep_s > 0:
            await asyncio.sleep(sleep_s)
    return rows


# ---------------------------------------------------------------------------
# Persistence (idempotent INSERT OR REPLACE; shared DDL)
# ---------------------------------------------------------------------------
def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.create_function("unixepoch", 0, lambda: int(time.time()))  # 3.38 shim, mirror db.py
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    from consensus_engine.db import SCHEMA
    conn.executescript(SCHEMA)


def write_rows(db_path: str, rows: list[dict], retention_days: int = 750) -> int:
    """Upsert one row per ticker/day, then prune rows older than retention_days.
    Returns the number of rows written."""
    if not rows:
        return 0
    conn = _connect(db_path)
    try:
        _ensure_schema(conn)
        for r in rows:
            conn.execute(
                """INSERT OR REPLACE INTO iv_snapshots
                   (snapshot_date, ticker, spot, atm_iv, straddle_em,
                    iv_em_to_expiry, expiry, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["snapshot_date"], r["ticker"], r["spot"], r["atm_iv"],
                 r["straddle_em"], r["iv_em_to_expiry"], r["expiry"], r["captured_at"]),
            )
        cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
        conn.execute("DELETE FROM iv_snapshots WHERE snapshot_date < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run(db_path: str, tickers: str | None, dry_run: bool,
        retention_days: int = 750, sleep_s: float = _PER_TICKER_SLEEP) -> dict:
    snapshot_date = datetime.now(timezone.utc).date().isoformat()
    universe = build_universe(tickers, db_path)
    log.info("[iv_snapshot] %s universe (%d): %s",
             snapshot_date, len(universe), ", ".join(universe))

    rows = asyncio.run(compute_rows(universe, snapshot_date, sleep_s))
    log.info("[iv_snapshot] computed %d/%d tickers", len(rows), len(universe))
    for r in rows:
        log.info("[iv]   %-6s spot=%s atm_iv=%s straddle_em=%s iv_em=%s exp=%s",
                 r["ticker"], r["spot"], r["atm_iv"], r["straddle_em"],
                 r["iv_em_to_expiry"], r["expiry"])

    if dry_run:
        log.info("[dry-run] computed %d rows — NO writes performed.", len(rows))
        return {"computed": len(rows), "written": 0, "universe": len(universe)}

    written = write_rows(db_path, rows, retention_days)
    log.info("[iv_snapshot] wrote %d rows into %s", written, db_path)
    return {"computed": len(rows), "written": written, "universe": len(universe)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily options-implied IV / expected-move snapshot logger "
                    "(persists iv_snapshots via the frozen expected_move math).")
    parser.add_argument("--tickers", type=str, default=None, metavar="A,B,C",
                        help="Override the universe with an explicit comma list.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute + print; do NOT write.")
    parser.add_argument("--db", type=str, default=None, metavar="PATH",
                        help="Target SQLite db (default: database.path from config).")
    parser.add_argument("--retention-days", type=int, default=750, metavar="N",
                        help="Prune iv_snapshots rows older than N days (default 750).")
    parser.add_argument("--sleep", type=float, default=_PER_TICKER_SLEEP, metavar="S",
                        help="Seconds to sleep between tickers (default 1.0).")
    args = parser.parse_args()

    db_path = args.db or cfg.get(
        "database.path", "/home/openclaw/.openclaw/workspace/consensus.db")

    summary = run(db_path=db_path, tickers=args.tickers, dry_run=args.dry_run,
                  retention_days=args.retention_days, sleep_s=args.sleep)
    print()
    print(f"IV snapshot {'computed (dry-run)' if args.dry_run else 'written'}: {summary}")
    return 0 if summary["computed"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
