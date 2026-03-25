"""SQLite database layer using aiosqlite for async operations."""

import json
import logging
import time

import aiosqlite

from consensus_engine import config as cfg
from consensus_engine.models import TickerSignal, SourceType

log = logging.getLogger("consensus_engine.db")

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_detail TEXT,
    raw_text TEXT,
    sentiment TEXT DEFAULT 'neutral',
    detected_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_ticker ON ticker_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_signals_detected ON ticker_signals(detected_at);
CREATE INDEX IF NOT EXISTS idx_signals_expires ON ticker_signals(expires_at);

CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    confidence_score REAL,
    catalyst TEXT,
    catalyst_type TEXT,
    consensus_breakdown TEXT,
    technical_data TEXT,
    analyst_mentions TEXT,
    alerted_at REAL NOT NULL,
    price_at_alert REAL,
    price_1h_later REAL,
    price_24h_later REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alert_history(ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON alert_history(alerted_at);

CREATE TABLE IF NOT EXISTS pipeline_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL,
    recorded_at REAL NOT NULL
);
"""


async def init_db() -> aiosqlite.Connection:
    """Initialize database and create tables."""
    global _db
    db_path = cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()
    log.info("Database initialized at %s", db_path)
    return _db


async def get_db() -> aiosqlite.Connection:
    """Get the database connection, initializing if needed."""
    global _db
    if _db is None:
        return await init_db()
    return _db


async def close_db():
    """Close the database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None


async def insert_signal(signal: TickerSignal):
    """Insert a ticker signal into the database."""
    db = await get_db()
    await db.execute(
        """INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            signal.ticker,
            signal.source_type.value,
            signal.source_detail,
            signal.raw_text[:2000],  # Truncate long texts
            signal.sentiment.value,
            signal.detected_at,
            signal.expires_at,
        ),
    )
    await db.commit()


async def insert_signals(signals: list[TickerSignal]):
    """Batch insert multiple signals."""
    if not signals:
        return
    db = await get_db()
    await db.executemany(
        """INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (s.ticker, s.source_type.value, s.source_detail, s.raw_text[:2000],
             s.sentiment.value, s.detected_at, s.expires_at)
            for s in signals
        ],
    )
    await db.commit()
    log.debug("Inserted %d signals", len(signals))


async def get_twitter_signals(ticker: str, window_seconds: int = 1800) -> list[dict]:
    """Get Twitter signals for a ticker within the rolling window."""
    db = await get_db()
    cutoff = time.time() - window_seconds
    cursor = await db.execute(
        """SELECT source_detail, raw_text, detected_at FROM ticker_signals
           WHERE ticker = ? AND source_type = 'twitter' AND detected_at >= ?
           ORDER BY detected_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_social_signals(ticker: str, window_seconds: int = 3600) -> list[dict]:
    """Get social signals for a ticker within window."""
    db = await get_db()
    cutoff = time.time() - window_seconds
    cursor = await db.execute(
        """SELECT source_type, source_detail, raw_text, sentiment, detected_at
           FROM ticker_signals
           WHERE ticker = ? AND source_type IN ('reddit', 'stocktwits', 'apewisdom', 'google_trends')
           AND detected_at >= ?
           ORDER BY detected_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_news_signals(ticker: str, window_seconds: int = 3600) -> list[dict]:
    """Get news signals for a ticker within window."""
    db = await get_db()
    cutoff = time.time() - window_seconds
    cursor = await db.execute(
        """SELECT source_detail, raw_text, sentiment, detected_at
           FROM ticker_signals
           WHERE ticker = ? AND source_type = 'news' AND detected_at >= ?
           ORDER BY detected_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_active_tickers(min_signals: int = 1) -> list[str]:
    """Get all tickers that have unexpired signals, sorted by signal count."""
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        """SELECT ticker, COUNT(*) as cnt FROM ticker_signals
           WHERE expires_at > ?
           GROUP BY ticker HAVING cnt >= ?
           ORDER BY cnt DESC""",
        (now, min_signals),
    )
    rows = await cursor.fetchall()
    return [r["ticker"] for r in rows]


async def check_alert_cooldown(ticker: str) -> bool:
    """Returns True if we can alert on this ticker (cooldown has passed)."""
    cooldown_hours = cfg.get("alerts.cooldown_hours", 6)
    cutoff = time.time() - (cooldown_hours * 3600)
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM alert_history WHERE ticker = ? AND alerted_at > ?",
        (ticker, cutoff),
    )
    row = await cursor.fetchone()
    return row["cnt"] == 0


async def insert_alert(ticker: str, confidence: float, catalyst: str, catalyst_type: str,
                       consensus_json: str, technical_json: str, analysts_json: str,
                       price: float):
    """Record an alert in history."""
    db = await get_db()
    await db.execute(
        """INSERT INTO alert_history
           (ticker, confidence_score, catalyst, catalyst_type, consensus_breakdown,
            technical_data, analyst_mentions, alerted_at, price_at_alert)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, confidence, catalyst, catalyst_type, consensus_json,
         technical_json, analysts_json, time.time(), price),
    )
    await db.commit()
    log.info("Alert recorded: %s (confidence=%.1f)", ticker, confidence)


async def prune_expired():
    """Remove expired signals from the database."""
    db = await get_db()
    now = time.time()
    cursor = await db.execute("DELETE FROM ticker_signals WHERE expires_at < ?", (now,))
    await db.commit()
    deleted = cursor.rowcount
    if deleted > 0:
        log.info("Pruned %d expired signals", deleted)
    return deleted


async def record_metric(name: str, value: float):
    """Record a pipeline performance metric."""
    db = await get_db()
    await db.execute(
        "INSERT INTO pipeline_metrics (metric_name, value, recorded_at) VALUES (?, ?, ?)",
        (name, value, time.time()),
    )
    await db.commit()


async def get_signal_counts_by_source(ticker: str) -> dict[str, int]:
    """Get signal counts grouped by source type for a ticker."""
    db = await get_db()
    now = time.time()
    cursor = await db.execute(
        """SELECT source_type, COUNT(*) as cnt FROM ticker_signals
           WHERE ticker = ? AND expires_at > ?
           GROUP BY source_type""",
        (ticker, now),
    )
    rows = await cursor.fetchall()
    return {r["source_type"]: r["cnt"] for r in rows}
