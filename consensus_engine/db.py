"""SQLite database layer with an async-compatible sqlite3 wrapper."""

import asyncio
import json
import logging
import sqlite3
import time

from consensus_engine import config as cfg
from consensus_engine.models import TickerSignal, SourceType

log = logging.getLogger("consensus_engine.db")


class AsyncCursor:
    """Small awaitable wrapper around sqlite3.Cursor."""

    def __init__(self, cursor: sqlite3.Cursor, lock: asyncio.Lock):
        self._cursor = cursor
        self._lock = lock
        self.rowcount = cursor.rowcount
        self.lastrowid = cursor.lastrowid

    async def fetchone(self):
        async with self._lock:
            return self._cursor.fetchone()

    async def fetchall(self):
        async with self._lock:
            return self._cursor.fetchall()


class AsyncConnection:
    """Async facade over a sqlite3 connection."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = asyncio.Lock()

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    async def execute(self, sql: str, params=()):
        async with self._lock:
            cursor = self._conn.execute(sql, params)
            return AsyncCursor(cursor, self._lock)

    async def executemany(self, sql: str, seq_of_params):
        async with self._lock:
            cursor = self._conn.executemany(sql, seq_of_params)
            return AsyncCursor(cursor, self._lock)

    async def executescript(self, sql_script: str):
        async with self._lock:
            cursor = self._conn.executescript(sql_script)
            return AsyncCursor(cursor, self._lock)

    async def commit(self):
        async with self._lock:
            self._conn.commit()

    async def close(self):
        async with self._lock:
            self._conn.close()


_db: AsyncConnection | None = None

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
CREATE INDEX IF NOT EXISTS idx_alerts_ticker_time ON alert_history(ticker, alerted_at);

CREATE TABLE IF NOT EXISTS pipeline_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name TEXT NOT NULL,
    value REAL,
    recorded_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_tweets (
    tweet_url TEXT PRIMARY KEY,
    analyst TEXT NOT NULL,
    parsed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    analyst TEXT NOT NULL,
    instant_msg_id TEXT,
    followup_msg_id TEXT,
    base_score INTEGER DEFAULT 0,
    final_score INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alert_msgs_ticker ON alert_messages(ticker);

CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker TEXT PRIMARY KEY,
    name TEXT,
    market_cap REAL,
    exchange TEXT,
    last_checked REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reddit_posts (
    id TEXT PRIMARY KEY,
    subreddit TEXT NOT NULL,
    title TEXT,
    author TEXT,
    score INTEGER DEFAULT 0,
    num_comments INTEGER DEFAULT 0,
    created_utc INTEGER NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reddit_posts_created ON reddit_posts(created_utc);
CREATE INDEX IF NOT EXISTS idx_reddit_posts_sub ON reddit_posts(subreddit);

CREATE TABLE IF NOT EXISTS xref_cache (
    ticker TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    cached_at REAL NOT NULL
);
"""


async def init_db() -> AsyncConnection:
    """Initialize database and create tables."""
    global _db
    db_path = cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    _db = AsyncConnection(conn)
    _db.row_factory = sqlite3.Row
    # WAL mode for concurrent read/write from multiple coroutines
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    await _db.commit()
    log.info("Database initialized at %s", db_path)
    return _db


async def get_db() -> AsyncConnection:
    """Get the database connection, initializing if needed."""
    global _db
    if _db is None:
        return await init_db()
    return _db


async def close_db():
    """Close the database connection."""
    global _db
    if _db:
        try:
            await _db.close()
        except Exception as e:
            log.warning("Error closing database: %s", e)
        finally:
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
    """Record an alert in history. Returns the alert_history row ID."""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO alert_history
           (ticker, confidence_score, catalyst, catalyst_type, consensus_breakdown,
            technical_data, analyst_mentions, alerted_at, price_at_alert)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, confidence, catalyst, catalyst_type, consensus_json,
         technical_json, analysts_json, time.time(), price),
    )
    await db.commit()
    log.info("Alert recorded: %s (confidence=%.1f)", ticker, confidence)
    return cursor.lastrowid


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


async def vacuum():
    """Run VACUUM to compact the database file."""
    conn = await get_db()
    await conn.execute("VACUUM")
    log.info("Database VACUUM complete")


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


async def is_new_tweet(tweet_url: str) -> bool:
    """Check if we've already seen this tweet."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT 1 FROM seen_tweets WHERE tweet_url = ?", (tweet_url,)
    )
    row = await cursor.fetchone()
    return row is None


async def check_seen_tweet(tweet_url: str) -> bool:
    """Return True when a tweet URL has already been processed."""
    return not await is_new_tweet(tweet_url)


async def mark_tweet_seen(tweet_url: str, analyst: str):
    """Record a tweet as seen (idempotent)."""
    conn = await get_db()
    await conn.execute(
        "INSERT OR IGNORE INTO seen_tweets (tweet_url, analyst, parsed_at) VALUES (?, ?, ?)",
        (tweet_url, analyst, time.time()),
    )
    await conn.commit()


async def insert_alert_message(ticker: str, analyst: str, instant_msg_id: str,
                                base_score: int) -> int:
    """Insert an alert message record. Returns the row ID."""
    conn = await get_db()
    cursor = await conn.execute(
        """INSERT INTO alert_messages (ticker, analyst, instant_msg_id, base_score, final_score, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ticker, analyst, instant_msg_id, base_score, 0, time.time()),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_alert_message(msg_id: int) -> dict | None:
    """Get an alert message by ID."""
    conn = await get_db()
    cursor = await conn.execute("SELECT * FROM alert_messages WHERE id = ?", (msg_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_alert_message_followup(msg_id: int, followup_msg_id: str, final_score: int):
    """Update an alert message with the follow-up Discord message ID and final score."""
    conn = await get_db()
    await conn.execute(
        "UPDATE alert_messages SET followup_msg_id = ?, final_score = ? WHERE id = ?",
        (followup_msg_id, final_score, msg_id),
    )
    await conn.commit()


async def update_alert_breakdown(alert_id: int, consensus_json: str, technical_json: str,
                                 analysts_json: str, confidence: float | None = None,
                                 catalyst: str | None = None,
                                 catalyst_type: str | None = None):
    """Enrich an existing alert_history row with cross-reference details."""
    conn = await get_db()
    await conn.execute(
        """UPDATE alert_history
           SET confidence_score = COALESCE(?, confidence_score),
               catalyst = COALESCE(?, catalyst),
               catalyst_type = COALESCE(?, catalyst_type),
               consensus_breakdown = ?,
               technical_data = ?,
               analyst_mentions = ?
           WHERE id = ?""",
        (
            confidence,
            catalyst,
            catalyst_type,
            consensus_json,
            technical_json,
            analysts_json,
            alert_id,
        ),
    )
    await conn.commit()


async def cache_ticker_metadata(ticker: str, name: str, market_cap: float, exchange: str):
    """Cache ticker metadata from Finnhub."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO ticker_metadata (ticker, name, market_cap, exchange, last_checked)
           VALUES (?, ?, ?, ?, ?)""",
        (ticker, name, market_cap, exchange, time.time()),
    )
    await conn.commit()


async def get_ticker_metadata(ticker: str, max_age_days: int = 7) -> dict | None:
    """Get cached ticker metadata. Returns None if missing or stale."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT * FROM ticker_metadata WHERE ticker = ?", (ticker,)
    )
    row = await cursor.fetchone()
    if not row:
        return None
    age = time.time() - row["last_checked"]
    if age > max_age_days * 86400:
        return None
    return dict(row)


async def get_recent_analysts_for_ticker(ticker: str, window_seconds: int = 3600) -> list[str]:
    """Get unique analyst handles who mentioned a ticker recently (from ticker_signals)."""
    conn = await get_db()
    cutoff = time.time() - window_seconds
    cursor = await conn.execute(
        """SELECT DISTINCT source_detail FROM ticker_signals
           WHERE ticker = ? AND source_type = 'twitter' AND detected_at >= ?""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [r["source_detail"] for r in rows]


async def get_alerts_needing_price_update(field: str) -> list[dict]:
    """Get alerts where a price follow-up field is NULL and enough time has passed.

    field must be 'price_1h_later' or 'price_24h_later'.
    """
    conn = await get_db()
    now = time.time()
    if field == "price_1h_later":
        min_age = 3600       # at least 1 hour old
        max_age = 7200       # no older than 2 hours (don't backfill ancient alerts)
    elif field == "price_24h_later":
        min_age = 86400      # at least 24 hours old
        max_age = 172800     # no older than 48 hours
    else:
        return []

    cursor = await conn.execute(
        f"""SELECT id, ticker, price_at_alert, alerted_at FROM alert_history
            WHERE {field} IS NULL
            AND alerted_at <= ? AND alerted_at >= ?
            ORDER BY alerted_at DESC LIMIT 20""",
        (now - min_age, now - max_age),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_alert_price(alert_id: int, field: str, price: float):
    """Update a price follow-up field on an alert."""
    if field not in ("price_1h_later", "price_24h_later"):
        return
    conn = await get_db()
    await conn.execute(
        f"UPDATE alert_history SET {field} = ? WHERE id = ?",
        (price, alert_id),
    )
    await conn.commit()


async def insert_reddit_posts(posts: list[dict]) -> int:
    """Bulk-insert Reddit posts, ignoring duplicates. Returns count inserted."""
    conn = await get_db()
    inserted = 0
    for post in posts:
        try:
            cursor = await conn.execute(
                """INSERT OR IGNORE INTO reddit_posts
                   (id, subreddit, title, author, score, num_comments, created_utc, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    post["id"], post["subreddit"], post.get("title", ""),
                    post.get("author", ""), post.get("score", 0),
                    post.get("num_comments", 0), post["created_utc"], time.time(),
                ),
            )
            if cursor.rowcount > 0:
                inserted += 1
        except Exception:
            pass
    await conn.commit()
    return inserted


async def get_performance_stats() -> dict:
    """Return aggregated performance stats from alert_history.

    Returns a dict with keys:
      total_all, total_7d,
      win_rate_1h, win_rate_24h,
      avg_pnl_1h, avg_pnl_24h,
      top3_best_1h, top3_worst_1h
    """
    conn = await get_db()
    now = time.time()
    seven_days_ago = now - 7 * 86400

    # Total counts
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM alert_history")
    row = await cursor.fetchone()
    total_all = row["cnt"] if row else 0

    cursor = await conn.execute(
        "SELECT COUNT(*) as cnt FROM alert_history WHERE alerted_at >= ?",
        (seven_days_ago,),
    )
    row = await cursor.fetchone()
    total_7d = row["cnt"] if row else 0

    # 1h stats
    cursor = await conn.execute(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN price_1h_later > price_at_alert THEN 1 ELSE 0 END) as wins,
             AVG((price_1h_later - price_at_alert) / price_at_alert * 100) as avg_pnl
           FROM alert_history
           WHERE price_at_alert > 0 AND price_1h_later IS NOT NULL"""
    )
    row_1h = await cursor.fetchone()
    total_1h = row_1h["total"] if row_1h else 0
    win_rate_1h = (row_1h["wins"] / total_1h * 100) if total_1h > 0 else None
    avg_pnl_1h = row_1h["avg_pnl"] if total_1h > 0 else None

    # 24h stats
    cursor = await conn.execute(
        """SELECT
             COUNT(*) as total,
             SUM(CASE WHEN price_24h_later > price_at_alert THEN 1 ELSE 0 END) as wins,
             AVG((price_24h_later - price_at_alert) / price_at_alert * 100) as avg_pnl
           FROM alert_history
           WHERE price_at_alert > 0 AND price_24h_later IS NOT NULL"""
    )
    row_24h = await cursor.fetchone()
    total_24h = row_24h["total"] if row_24h else 0
    win_rate_24h = (row_24h["wins"] / total_24h * 100) if total_24h > 0 else None
    avg_pnl_24h = row_24h["avg_pnl"] if total_24h > 0 else None

    # Top 3 best by 1h P&L
    cursor = await conn.execute(
        """SELECT ticker, alerted_at, price_at_alert, price_1h_later,
                  (price_1h_later - price_at_alert) / price_at_alert * 100 as pnl_pct
           FROM alert_history
           WHERE price_at_alert > 0 AND price_1h_later IS NOT NULL
           ORDER BY pnl_pct DESC LIMIT 3"""
    )
    top3_best = [dict(r) for r in await cursor.fetchall()]

    # Top 3 worst by 1h P&L
    cursor = await conn.execute(
        """SELECT ticker, alerted_at, price_at_alert, price_1h_later,
                  (price_1h_later - price_at_alert) / price_at_alert * 100 as pnl_pct
           FROM alert_history
           WHERE price_at_alert > 0 AND price_1h_later IS NOT NULL
           ORDER BY pnl_pct ASC LIMIT 3"""
    )
    top3_worst = [dict(r) for r in await cursor.fetchall()]

    return {
        "total_all": total_all,
        "total_7d": total_7d,
        "total_1h": total_1h,
        "total_24h": total_24h,
        "win_rate_1h": win_rate_1h,
        "win_rate_24h": win_rate_24h,
        "avg_pnl_1h": avg_pnl_1h,
        "avg_pnl_24h": avg_pnl_24h,
        "top3_best_1h": top3_best,
        "top3_worst_1h": top3_worst,
    }


async def get_analyst_performance_stats() -> list[dict]:
    """Get per-analyst win rates by joining alert_messages with alert_history.

    Returns list of dicts sorted by total_alerts desc:
      {analyst, total_alerts, wins_1h, win_rate_1h, wins_24h, win_rate_24h, avg_pnl_1h}
    """
    conn = await get_db()
    cursor = await conn.execute("""
        SELECT
            am.analyst,
            COUNT(*) as total_alerts,
            SUM(CASE WHEN ah.price_1h_later > ah.price_at_alert THEN 1 ELSE 0 END) as wins_1h,
            SUM(CASE WHEN ah.price_24h_later > ah.price_at_alert THEN 1 ELSE 0 END) as wins_24h,
            AVG(CASE WHEN ah.price_at_alert > 0 AND ah.price_1h_later IS NOT NULL
                THEN (ah.price_1h_later - ah.price_at_alert) / ah.price_at_alert * 100
                ELSE NULL END) as avg_pnl_1h
        FROM alert_messages am
        INNER JOIN alert_history ah ON am.ticker = ah.ticker
            AND abs(am.created_at - ah.alerted_at) < 60
        WHERE ah.price_at_alert > 0
        GROUP BY am.analyst
        HAVING total_alerts >= 1
        ORDER BY total_alerts DESC
    """)
    rows = await cursor.fetchall()
    results = []
    for r in rows:
        total = r["total_alerts"]
        results.append({
            "analyst": r["analyst"],
            "total_alerts": total,
            "wins_1h": r["wins_1h"] or 0,
            "win_rate_1h": (r["wins_1h"] / total * 100) if r["wins_1h"] else 0,
            "wins_24h": r["wins_24h"] or 0,
            "win_rate_24h": (r["wins_24h"] / total * 100) if r["wins_24h"] else 0,
            "avg_pnl_1h": r["avg_pnl_1h"] or 0,
        })
    return results


async def get_reddit_posts_since(since_utc: int) -> list[dict]:
    """Fetch posts created after since_utc."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT id, subreddit, title, author FROM reddit_posts WHERE created_utc > ? ORDER BY created_utc DESC",
        (since_utc,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_xref_from_db(ticker: str, ttl_seconds: int = 300) -> str | None:
    """Get cached xref result JSON from DB, or None if missing/expired."""
    conn = await get_db()
    cutoff = time.time() - ttl_seconds
    cursor = await conn.execute(
        "SELECT result_json FROM xref_cache WHERE ticker = ? AND cached_at > ?",
        (ticker, cutoff),
    )
    row = await cursor.fetchone()
    return row["result_json"] if row else None


async def set_xref_in_db(ticker: str, result_json: str):
    """Store or update an xref cache entry in DB."""
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO xref_cache (ticker, result_json, cached_at) VALUES (?, ?, ?)",
        (ticker, result_json, time.time()),
    )
    await conn.commit()


async def get_warm_xref_entries(ttl_seconds: int = 300) -> list[dict]:
    """Fetch all non-expired xref cache entries for warming in-memory cache on startup."""
    conn = await get_db()
    cutoff = time.time() - ttl_seconds
    cursor = await conn.execute(
        "SELECT ticker, result_json, cached_at FROM xref_cache WHERE cached_at > ?",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
