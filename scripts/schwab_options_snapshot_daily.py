"""#57 — daily Schwab real-time options-chain snapshot logger.

ONE cron entrypoint that pulls the real-time option chain from the user's
Schwab account for the watchlist tickers and persists ONE derived-summary row
per ticker per day into `schwab_options_snapshots` — building our own
options-history table over time on top of Schwab's real-time (not ~15-min
delayed) feed.

License (see consensus_engine/scanners/schwab_client.py docstring): store
DERIVED SUMMARIES ONLY (vol/OI, max-pain, ATM IV). This script NEVER stores
the raw per-strike chain — only the aggregate fields below.

Universe: the SAME tickers `_run_options_flow_scan` (consensus_engine/main.py)
scans — the engine's active watchlist (unexpired `ticker_signals`, mirroring
`db.get_active_tickers`) UNIONed with `options_flow.fixed_core` from config.
Falls back to `config.get("watchlist", ...)` or a small liquid-core default if
neither source is reachable. Pass `--tickers A,B,C` to override entirely.

`features.schwab_snapshot_logger.enabled` exists in config/consensus.yaml but
is NOT read here — per the plan, the systemd timer is the real on/off switch
for this script; the config flag is informational only.

Fail-soft: a per-ticker Schwab error (SchwabError / SchwabRefreshTokenExpired
/ anything else) logs a warning and skips that ticker — one bad symbol never
aborts the run.

Retention: after writing, rows older than ``--retention-days`` (default 750)
are pruned so the table stays bounded.

Usage:
    python3 scripts/schwab_options_snapshot_daily.py --dry-run                 # compute + print, NO write
    python3 scripts/schwab_options_snapshot_daily.py                           # active watchlist ∪ fixed_core, upsert
    python3 scripts/schwab_options_snapshot_daily.py --tickers SPY,QQQ,NVDA    # explicit universe
    python3 scripts/schwab_options_snapshot_daily.py --db /tmp/x.db            # target a NON-live db
"""
from __future__ import annotations

import argparse
import logging
import math
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Project root on sys.path so consensus_engine imports resolve.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from consensus_engine import config as cfg
from consensus_engine.scanners import schwab_client
from consensus_engine.scanners.options import _max_pain_for_chain

log = logging.getLogger("schwab_options_snapshot_daily")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Small, always-included liquid core — last-resort fallback if neither the
# active watchlist nor options_flow.fixed_core/config watchlist is reachable.
DEFAULT_TICKERS: tuple[str, ...] = (
    "SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD",
)

_PER_TICKER_SLEEP = 0.3  # seconds between Schwab pulls (courtesy; client has its own rate limiter)


# ---------------------------------------------------------------------------
# Universe — same source as _run_options_flow_scan in consensus_engine/main.py
# ---------------------------------------------------------------------------
def _active_watchlist(db_path: str) -> list[str]:
    """Tickers with unexpired signals in the target db — the same
    `ticker_signals` query as `consensus_engine.db.get_active_tickers`, done
    as a direct read-only connection so this standalone process doesn't need
    to spin up the full async db layer. Fail-soft: returns [] on any error."""
    if not db_path or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except Exception as e:  # noqa: BLE001
        log.warning("[universe] could not open %s read-only (%s)", db_path, e)
        return []
    try:
        has = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_signals'"
        ).fetchone()
        if not has:
            return []
        rows = conn.execute(
            "SELECT ticker, COUNT(*) as cnt FROM ticker_signals WHERE expires_at > ? "
            "GROUP BY ticker HAVING cnt >= 1 ORDER BY cnt DESC",
            (time.time(),),
        ).fetchall()
    except Exception as e:  # noqa: BLE001
        log.warning("[universe] watchlist read failed (%s)", e)
        return []
    finally:
        conn.close()
    return [r[0] for r in rows if r and r[0]]


def build_universe(explicit: str | None, db_path: str) -> tuple[list[str], str]:
    """Resolve the snapshot universe + a label describing which source fed
    it. ``--tickers`` overrides everything; otherwise the active watchlist
    UNIONed with options_flow.fixed_core (active first, core second — same
    order as `_run_options_flow_scan`)."""
    if explicit:
        seen: dict[str, None] = {}
        for t in explicit.split(","):
            t = t.strip().upper()
            if t:
                seen.setdefault(t, None)
        return list(seen), "explicit --tickers override"

    active = _active_watchlist(db_path)
    core = cfg.get("options_flow.fixed_core", []) or []
    source = "db active ticker_signals ∪ config options_flow.fixed_core"
    if not core:
        core = cfg.get("watchlist", []) or list(DEFAULT_TICKERS)
        source = "db active ticker_signals ∪ config watchlist/default core"
    seen = {t.upper(): None for t in [*active, *core] if t}
    if not active:
        source += " (no active signals — core/default only)"
    return list(seen), source


# ---------------------------------------------------------------------------
# Compute (derived summaries only — never the raw per-strike grid)
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


def _closest_atm_iv(calls, spot: float | None) -> float | None:
    """impliedVolatility (fraction) of the call whose strike is closest to
    spot. None if calls are empty or spot is unusable."""
    if calls is None or getattr(calls, "empty", True) or spot is None:
        return None
    try:
        diffs = (calls["strike"] - spot).abs()
        idx = diffs.idxmin()
        return _clean(calls.loc[idx, "impliedVolatility"])
    except Exception:  # noqa: BLE001
        return None


def _top_vol_oi(df) -> tuple[str | None, float | None]:
    """Among rows with openInterest > 0, the contract with the highest
    volume/openInterest ratio. Returns (contractSymbol, ratio) or (None, None)."""
    if df is None or getattr(df, "empty", True):
        return None, None
    try:
        d = df[df["openInterest"] > 0].dropna(subset=["volume", "openInterest"])
        if d.empty:
            return None, None
        ratio = d["volume"] / d["openInterest"]
        idx = ratio.idxmax()
        return d.loc[idx, "contractSymbol"], _clean(ratio.loc[idx])
    except Exception:  # noqa: BLE001
        return None, None


def _snapshot_one(ticker: str, snapshot_date: str) -> dict | None:
    """Compute one ticker's snapshot row via the Schwab client. Returns a row
    dict, or None on any failure (logged) so the caller can skip it."""
    try:
        ch = schwab_client.get_option_chain(ticker)
    except schwab_client.SchwabRefreshTokenExpired as e:
        log.warning("[schwab] %s skipped — refresh token expired: %s", ticker, e)
        return None
    except schwab_client.SchwabError as e:
        log.warning("[schwab] %s skipped — %s", ticker, e)
        return None
    except Exception as e:  # noqa: BLE001 — never let one symbol abort the run
        log.warning("[schwab] %s skipped — unexpected error: %s", ticker, e)
        return None

    if ch is None or not ch.expirations:
        log.warning("[schwab] %s skipped — no option chain data", ticker)
        return None

    nearest_expiry = ch.expirations[0]
    leg = ch.by_expiry(nearest_expiry)
    calls, puts = leg.calls, leg.puts

    total_call_vol = _clean(calls["volume"].sum()) if not calls.empty else 0.0
    total_put_vol = _clean(puts["volume"].sum()) if not puts.empty else 0.0
    call_oi = _clean(calls["openInterest"].sum()) if not calls.empty else 0.0
    put_oi = _clean(puts["openInterest"].sum()) if not puts.empty else 0.0

    put_call_vol_ratio = (total_put_vol / total_call_vol) if total_call_vol else None
    put_call_oi_ratio = (put_oi / call_oi) if call_oi else None

    try:
        mp = _max_pain_for_chain(leg)
        max_pain = _clean(mp[0]) if mp else None
    except Exception as e:  # noqa: BLE001 — a glitch strike/OI must not drop the row
        log.debug("[schwab] %s max-pain skipped: %s", ticker, e)
        max_pain = None

    atm_iv = _closest_atm_iv(calls, ch.underlying_price)
    top_call_contract, top_call_vol_oi = _top_vol_oi(calls)
    top_put_contract, top_put_vol_oi = _top_vol_oi(puts)

    return {
        "snapshot_date": snapshot_date,
        "ticker": ticker.upper(),
        "spot": _clean(ch.underlying_price),
        "total_call_vol": total_call_vol,
        "total_put_vol": total_put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
        "put_call_vol_ratio": _clean(put_call_vol_ratio),
        "put_call_oi_ratio": _clean(put_call_oi_ratio),
        "max_pain": max_pain,
        "atm_iv": atm_iv,
        "top_call_contract": top_call_contract,
        "top_call_vol_oi": top_call_vol_oi,
        "top_put_contract": top_put_contract,
        "top_put_vol_oi": top_put_vol_oi,
        "nearest_expiry": nearest_expiry,
        "is_delayed": 1 if ch.is_delayed else 0,
        "captured_at": time.time(),
    }


def compute_rows(universe: list[str], snapshot_date: str,
                 sleep_s: float = _PER_TICKER_SLEEP) -> list[dict]:
    rows: list[dict] = []
    for i, ticker in enumerate(universe):
        row = _snapshot_one(ticker, snapshot_date)
        if row is not None:
            rows.append(row)
        if i < len(universe) - 1 and sleep_s > 0:
            time.sleep(sleep_s)
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
                """INSERT OR REPLACE INTO schwab_options_snapshots
                   (snapshot_date, ticker, spot, total_call_vol, total_put_vol,
                    call_oi, put_oi, put_call_vol_ratio, put_call_oi_ratio,
                    max_pain, atm_iv, top_call_contract, top_call_vol_oi,
                    top_put_contract, top_put_vol_oi, nearest_expiry, is_delayed,
                    captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["snapshot_date"], r["ticker"], r["spot"], r["total_call_vol"],
                 r["total_put_vol"], r["call_oi"], r["put_oi"], r["put_call_vol_ratio"],
                 r["put_call_oi_ratio"], r["max_pain"], r["atm_iv"], r["top_call_contract"],
                 r["top_call_vol_oi"], r["top_put_contract"], r["top_put_vol_oi"],
                 r["nearest_expiry"], r["is_delayed"], r["captured_at"]),
            )
        cutoff = (date.today() - timedelta(days=retention_days)).isoformat()
        conn.execute("DELETE FROM schwab_options_snapshots WHERE snapshot_date < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()
    return len(rows)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run(db_path: str, tickers: str | None, dry_run: bool,
        retention_days: int = 750, sleep_s: float = _PER_TICKER_SLEEP) -> dict:
    # US-Eastern trading date (NOT PT/UTC) — the option chain is Schwab's
    # real-time NYSE-session data, so the snapshot bucket follows the market's
    # own calendar day. This is internal NYSE-logic only; never surfaced.
    snapshot_date = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    universe, source = build_universe(tickers, db_path)
    log.info("[schwab_snapshot] %s universe (%d) via %s: %s",
             snapshot_date, len(universe), source, ", ".join(universe))

    rows = compute_rows(universe, snapshot_date, sleep_s)
    log.info("[schwab_snapshot] computed %d/%d tickers", len(rows), len(universe))
    for r in rows:
        log.info(
            "[schwab]   %-6s spot=%s call_vol=%s put_vol=%s call_oi=%s put_oi=%s "
            "pc_vol=%s pc_oi=%s max_pain=%s atm_iv=%s exp=%s delayed=%s",
            r["ticker"], r["spot"], r["total_call_vol"], r["total_put_vol"],
            r["call_oi"], r["put_oi"], r["put_call_vol_ratio"], r["put_call_oi_ratio"],
            r["max_pain"], r["atm_iv"], r["nearest_expiry"], r["is_delayed"],
        )

    if dry_run:
        log.info("[dry-run] computed %d rows — NO writes performed.", len(rows))
        return {"computed": len(rows), "written": 0, "universe": len(universe)}

    written = write_rows(db_path, rows, retention_days)
    log.info("[schwab_snapshot] wrote %d rows into %s", written, db_path)
    return {"computed": len(rows), "written": written, "universe": len(universe)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily Schwab real-time options-chain snapshot logger "
                    "(#57; persists schwab_options_snapshots — derived summaries only).")
    parser.add_argument("--tickers", type=str, default=None, metavar="A,B,C",
                        help="Override the universe with an explicit comma list.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute + print; do NOT write.")
    parser.add_argument("--db", type=str, default=None, metavar="PATH",
                        help="Target SQLite db (default: database.path from config).")
    parser.add_argument("--retention-days", type=int, default=750, metavar="N",
                        help="Prune schwab_options_snapshots rows older than N days (default 750).")
    parser.add_argument("--sleep", type=float, default=_PER_TICKER_SLEEP, metavar="S",
                        help="Seconds to sleep between tickers (default 0.3).")
    args = parser.parse_args()

    db_path = args.db or cfg.get(
        "database.path", "/home/openclaw/.openclaw/workspace/consensus.db")

    summary = run(db_path=db_path, tickers=args.tickers, dry_run=args.dry_run,
                  retention_days=args.retention_days, sleep_s=args.sleep)
    print()
    print(f"Schwab options snapshot {'computed (dry-run)' if args.dry_run else 'written'}: {summary}")
    return 0 if summary["computed"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
