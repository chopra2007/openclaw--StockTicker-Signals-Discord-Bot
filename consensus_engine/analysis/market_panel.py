"""Read-only accessor for the daily market-context tables (trade-edge layer).

The daily cron (``scripts/market_daily.py`` / ``scripts/sector_rotation_daily.py``)
writes the cross-sectional reads once per day into SQLite (sector_rs_daily,
factor_rs_daily, trend_daily, macro_legs_daily, internal_breadth_daily). The live
engine and the read-only Discord command must NOT fetch yfinance at alert time —
they read the persisted rows through this thin wrapper.

Shape mirrors ``regime.py:lookup_regime`` (lines 86-105): SELECT the newest row,
then apply a staleness no-op — if the freshest row is older than ``max_age_days``
the caller should treat it as a cold start rather than acting on stale data.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

# Allowlist of the daily market tables this accessor may read. Table names are
# never user-supplied (callers pass these constants), but the allowlist keeps the
# interpolated identifier safe by construction.
MARKET_TABLES = frozenset(
    {
        "sector_rs_daily",
        "factor_rs_daily",
        "trend_daily",
        "macro_legs_daily",
        "internal_breadth_daily",
        "market_breadth_daily",
    }
)

# Default staleness horizon (days). Mirrors regime.py's 7-day fallback: a daily
# read more than a week old means the cron stopped running, so degrade to no-op.
DEFAULT_MAX_AGE_DAYS = 7


def row_age_days(computed_at: float, now: Optional[float] = None) -> float:
    """Age in days of a row given its ``computed_at`` unix timestamp."""
    now = time.time() if now is None else now
    return (now - computed_at) / 86400.0


def is_stale(computed_at: float, max_age_days: float = DEFAULT_MAX_AGE_DAYS,
             now: Optional[float] = None) -> bool:
    """True when the row is older than ``max_age_days`` (→ caller no-ops)."""
    return row_age_days(computed_at, now) > max_age_days


def _filter_clause(filters: Optional[dict]) -> tuple[str, list]:
    """Build a parameterised ``WHERE`` clause from {column: value} (values bound)."""
    if not filters:
        return "", []
    cols = sorted(filters)  # deterministic ordering
    clause = " WHERE " + " AND ".join(f"{c} = ?" for c in cols)
    params = [filters[c] for c in cols]
    return clause, params


async def get_latest_row(table: str, filters: Optional[dict] = None) -> Optional[dict]:
    """Return the newest row of ``table`` (by date_utc) as a dict, or None.

    ``filters`` is an optional {column: value} equality filter (e.g. {"etf": "XLK"}).
    Does NOT apply staleness — the caller decides via ``is_stale`` so it can log /
    cold-start on its own terms (mirroring regime.lookup_regime).
    """
    if table not in MARKET_TABLES:
        raise ValueError(f"market_panel: unknown table {table!r}")
    from consensus_engine import db

    conn = await db.get_db()
    where, params = _filter_clause(filters)
    cur = await conn.execute(
        f"SELECT * FROM {table}{where} ORDER BY date_utc DESC LIMIT 1", params
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_recent_rows(table: str, limit: int,
                          filters: Optional[dict] = None) -> list[dict]:
    """Return up to ``limit`` newest rows of ``table`` (newest first) as dicts."""
    if table not in MARKET_TABLES:
        raise ValueError(f"market_panel: unknown table {table!r}")
    from consensus_engine import db

    conn = await db.get_db()
    where, params = _filter_clause(filters)
    cur = await conn.execute(
        f"SELECT * FROM {table}{where} ORDER BY date_utc DESC LIMIT ?",
        [*params, int(limit)],
    )
    rows = await cur.fetchall()
    return [dict(r) for r in rows]
