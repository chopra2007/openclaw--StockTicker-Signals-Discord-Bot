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
DB_PATH: str | None = None  # Override for tests; falls back to config database.path

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

CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    fetched_at REAL NOT NULL,
    transcript_status TEXT NOT NULL DEFAULT 'pending',
    language TEXT,
    is_auto_generated INTEGER DEFAULT 0,
    export_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel ON youtube_videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_youtube_videos_status ON youtube_videos(transcript_status);
CREATE INDEX IF NOT EXISTS idx_youtube_videos_published ON youtube_videos(published_at);

CREATE TABLE IF NOT EXISTS api_usage_daily (
    day_utc TEXT PRIMARY KEY,
    finnhub_calls INTEGER NOT NULL DEFAULT 0,
    brave_queries INTEGER NOT NULL DEFAULT 0,
    exa_queries INTEGER NOT NULL DEFAULT 0,
    serpapi_queries INTEGER NOT NULL DEFAULT 0,
    firecrawl_credits INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS youtube_transcripts (
    video_id TEXT PRIMARY KEY,
    transcript_text TEXT NOT NULL,
    transcript_hash TEXT NOT NULL,
    summary_text TEXT,
    saved_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    conviction TEXT NOT NULL,
    mention_count INTEGER DEFAULT 1,
    macro_thesis TEXT,
    parsed_at REAL NOT NULL,
    published_at TEXT,
    extracted_at REAL NOT NULL,
    FOREIGN KEY (video_id) REFERENCES youtube_videos(video_id)
);
CREATE INDEX IF NOT EXISTS idx_youtube_signals_ticker ON youtube_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_youtube_signals_channel ON youtube_signals(channel_name);
CREATE INDEX IF NOT EXISTS idx_youtube_signals_extracted ON youtube_signals(extracted_at);

CREATE TABLE IF NOT EXISTS youtube_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    level_type TEXT NOT NULL,
    price REAL NOT NULL,
    condition_text TEXT,
    consequence_text TEXT,
    confidence REAL,
    channel_name TEXT,
    published_at TEXT,
    extracted_at REAL NOT NULL,
    FOREIGN KEY (video_id) REFERENCES youtube_videos(video_id)
);
CREATE INDEX IF NOT EXISTS idx_youtube_levels_ticker ON youtube_levels(ticker);
CREATE INDEX IF NOT EXISTS idx_youtube_levels_extracted ON youtube_levels(extracted_at);

CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_detail TEXT,
    ticker TEXT NOT NULL,
    direction TEXT,
    quality_score REAL DEFAULT 0.5,
    latency_sec REAL,
    provenance TEXT,
    model_version TEXT,
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_events_ticker ON signal_events(ticker);
CREATE INDEX IF NOT EXISTS idx_signal_events_source ON signal_events(source_type);
CREATE INDEX IF NOT EXISTS idx_signal_events_recorded ON signal_events(recorded_at);

CREATE TABLE IF NOT EXISTS decision_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    decision TEXT NOT NULL,
    final_score REAL NOT NULL,
    contradiction_index REAL DEFAULT 0.0,
    sources_json TEXT NOT NULL,
    feature_vector_json TEXT,
    weights_json TEXT,
    recorded_at REAL NOT NULL,
    outcome_price_at_alert REAL,
    outcome_price_1h REAL,
    outcome_price_24h REAL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON decision_snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_snapshots_recorded ON decision_snapshots(recorded_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_decision ON decision_snapshots(decision);

CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 1,
    trust_score REAL NOT NULL DEFAULT 1.0,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS youtube_macro (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    themes TEXT,
    timeframe TEXT,
    summary TEXT,
    confidence REAL DEFAULT 0.5,
    published_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_youtube_macro_channel ON youtube_macro(channel_id);
CREATE INDEX IF NOT EXISTS idx_youtube_macro_video ON youtube_macro(video_id);

CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    last_heartbeat REAL NOT NULL DEFAULT 0.0,
    error_rate REAL NOT NULL DEFAULT 0.0,
    freshness_seconds REAL NOT NULL DEFAULT 9999.0,
    updated_at REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS source_performance (
    entity_id TEXT NOT NULL,
    horizon TEXT NOT NULL,
    rolling_accuracy REAL DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (entity_id, horizon)
);

CREATE TABLE IF NOT EXISTS youtube_level_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    level_type TEXT NOT NULL,
    price REAL NOT NULL,
    channel_name TEXT,
    alerted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yla_ticker ON youtube_level_alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_yla_alerted ON youtube_level_alerts(alerted_at);

CREATE TABLE IF NOT EXISTS research_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_expires_at REAL,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_research_jobs_ticker_status ON research_jobs(ticker, status);
CREATE INDEX IF NOT EXISTS idx_research_jobs_status ON research_jobs(status);

CREATE TABLE IF NOT EXISTS research_sections (
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT,
    last_good_content TEXT,
    fetched_at REAL,
    last_good_at REAL,
    status TEXT,
    PRIMARY KEY (ticker, source)
);

CREATE TABLE IF NOT EXISTS briefing_runs (
    session_key TEXT PRIMARY KEY,
    session_start_utc REAL NOT NULL,
    session_end_utc REAL NOT NULL,
    rendered_content TEXT,
    discord_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    posted_at REAL,
    archived_at REAL
);
"""


async def init_db() -> AsyncConnection:
    """Initialize database and create tables."""
    global _db
    db_path = DB_PATH or cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    _db = AsyncConnection(conn)
    _db.row_factory = sqlite3.Row
    # WAL mode for concurrent read/write from multiple coroutines
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    await _db.commit()
    await seed_youtube_channels()
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
    # Atlas hook: enqueue a research job on every alert (non-blocking, coalesced).
    try:
        if cfg.get("atlas.enabled", False):
            await enqueue_atlas_job(ticker, "alert")
    except Exception as exc:
        log.warning("Atlas alert-enqueue failed: %s", exc)
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
        "SELECT id, subreddit, title, author, created_utc FROM reddit_posts WHERE created_utc > ? ORDER BY created_utc DESC",
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


# ---------------------------------------------------------------------------
# YouTube transcript helpers
# ---------------------------------------------------------------------------

async def has_video_been_processed(video_id: str) -> bool:
    """Return True if this video_id already has a non-pending status."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT transcript_status FROM youtube_videos WHERE video_id = ?",
        (video_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return False
    return row["transcript_status"] != "pending"


async def upsert_youtube_video(
    video_id: str,
    channel_id: str,
    title: str,
    published_at: str,
    fetched_at: float,
) -> None:
    """Insert a video record with status=pending, ignoring if already present."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_videos
           (video_id, channel_id, title, published_at, fetched_at, transcript_status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (video_id, channel_id, title, published_at, fetched_at),
    )
    await conn.commit()


async def save_youtube_transcript(
    video_id: str,
    transcript_text: str,
    transcript_hash: str,
    summary_text: str | None = None,
) -> None:
    """Upsert transcript content for a video."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO youtube_transcripts
           (video_id, transcript_text, transcript_hash, summary_text, saved_at)
           VALUES (?, ?, ?, ?, ?)""",
        (video_id, transcript_text, transcript_hash, summary_text, time.time()),
    )
    await conn.commit()


async def mark_youtube_video_status(
    video_id: str,
    status: str,
    language: str | None = None,
    is_auto_generated: bool = False,
    export_path: str | None = None,
) -> None:
    """Update the transcript_status (and optional metadata) for a video."""
    conn = await get_db()
    await conn.execute(
        """UPDATE youtube_videos
           SET transcript_status = ?,
               language = COALESCE(?, language),
               is_auto_generated = ?,
               export_path = COALESCE(?, export_path)
           WHERE video_id = ?""",
        (status, language, 1 if is_auto_generated else 0, export_path, video_id),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# YouTube signal analysis helpers
# ---------------------------------------------------------------------------

async def insert_youtube_signal(
    video_id: str,
    channel_name: str,
    ticker: str,
    direction: str,
    conviction: str,
    mention_count: int = 1,
    macro_thesis: str | None = None,
    published_at: str | None = None,
) -> None:
    """Insert a YouTube signal for a ticker extracted from a video."""
    conn = await get_db()
    await conn.execute(
        """INSERT INTO youtube_signals
           (video_id, channel_name, ticker, direction, conviction, mention_count, macro_thesis, parsed_at, published_at, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, channel_name, ticker, direction, conviction, mention_count, macro_thesis, time.time(), published_at, time.time()),
    )
    await conn.commit()


async def insert_youtube_level(
    video_id: str,
    ticker: str,
    level_type: str,
    price: float,
    condition_text: str | None = None,
    consequence_text: str | None = None,
    confidence: float = 0.8,
    channel_name: str | None = None,
    published_at: str | None = None,
) -> None:
    """Insert a price level (support/resistance) extracted from a YouTube video."""
    conn = await get_db()
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, condition_text, consequence_text, confidence, channel_name, published_at, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, ticker, level_type, price, condition_text, consequence_text, confidence, channel_name, published_at, time.time()),
    )
    await conn.commit()


async def get_youtube_signals_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """Get all YouTube signals for a ticker from the last N days."""
    conn = await get_db()
    cutoff = time.time() - (days * 86400)
    cursor = await conn.execute(
        """SELECT video_id, channel_name, ticker, direction, conviction, mention_count, macro_thesis, parsed_at, published_at
           FROM youtube_signals
           WHERE ticker = ? AND extracted_at >= ?
           ORDER BY extracted_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_youtube_levels_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """Get all YouTube price levels for a ticker from the last N days."""
    conn = await get_db()
    cutoff = time.time() - (days * 86400)
    cursor = await conn.execute(
        """SELECT ticker, level_type, price, condition_text, consequence_text, confidence, channel_name, published_at
           FROM youtube_levels
           WHERE ticker = ? AND extracted_at >= ?
           ORDER BY confidence DESC, extracted_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# YouTube channel registry helpers
# ---------------------------------------------------------------------------

async def seed_youtube_channels() -> None:
    """Seed youtube_channels from /root/.openclaw/sources.json if youtube_channels key present."""
    import json as _json
    sources_path = "/root/.openclaw/sources.json"
    try:
        with open(sources_path) as f:
            sources = _json.load(f)
    except (OSError, ValueError) as e:
        log.debug("seed_youtube_channels: could not read sources.json: %s", e)
        return

    channels = sources.get("youtube_channels", [])
    if not channels:
        return

    conn = await get_db()
    for ch in channels:
        channel_id = ch.get("channel_id", "").strip()
        display_name = ch.get("display_name", channel_id).strip() or channel_id
        trust_score = float(ch.get("trust_score", 1.0))
        approved = int(ch.get("approved", 1))
        if not channel_id:
            continue
        await conn.execute(
            """INSERT OR IGNORE INTO youtube_channels
               (channel_id, display_name, approved, trust_score)
               VALUES (?, ?, ?, ?)""",
            (channel_id, display_name, approved, trust_score),
        )
    await conn.commit()
    log.debug("seed_youtube_channels: seeded %d channels", len(channels))


async def get_channel_display_name(channel_id: str) -> str:
    """Return display name for a channel_id, or channel_id itself if not registered."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT display_name FROM youtube_channels WHERE channel_id = ?",
        (channel_id,),
    )
    row = await cursor.fetchone()
    return row["display_name"] if row else channel_id


async def get_channel_trust(channel_id: str) -> float:
    """Return trust_score for a channel_id (default 1.0 if not registered)."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT trust_score FROM youtube_channels WHERE channel_id = ?",
        (channel_id,),
    )
    row = await cursor.fetchone()
    return float(row["trust_score"]) if row else 1.0


async def get_approved_youtube_channels() -> list[str]:
    """Return all approved channel_ids from the youtube_channels table."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT channel_id FROM youtube_channels WHERE approved = 1"
    )
    rows = await cursor.fetchall()
    return [row["channel_id"] for row in rows]


async def insert_youtube_macro(
    video_id: str,
    channel_id: str,
    direction: str,
    themes: list | None = None,
    timeframe: str | None = None,
    summary: str | None = None,
    confidence: float = 0.5,
    published_at: str | None = None,
) -> None:
    """Upsert macro thesis for a video (one row per video_id)."""
    import json as _json
    conn = await get_db()
    themes_json = _json.dumps(themes) if themes else None
    await conn.execute(
        """INSERT OR REPLACE INTO youtube_macro
           (video_id, channel_id, direction, themes, timeframe, summary, confidence, published_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, channel_id, direction, themes_json, timeframe, summary, confidence, published_at),
    )
    await conn.commit()


async def get_recent_youtube_macro(days: int = 7) -> list[dict]:
    """Get all youtube_macro rows from the last N days."""
    import json as _json
    conn = await get_db()
    cutoff = time.time() - (days * 86400)
    cursor = await conn.execute(
        """SELECT video_id, channel_id, direction, themes, timeframe, summary, confidence, published_at, created_at
           FROM youtube_macro
           WHERE created_at >= datetime(?, 'unixepoch')
           ORDER BY created_at DESC""",
        (cutoff,),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["themes"] = _json.loads(d["themes"]) if d["themes"] else []
        except (ValueError, TypeError):
            d["themes"] = []
        result.append(d)
    return result


async def was_level_recently_alerted(ticker: str, price: float, cooldown_seconds: int = 14400) -> bool:
    """Return True if a level alert for this ticker/price was fired within cooldown window."""
    conn = await get_db()
    cutoff = time.time() - cooldown_seconds
    cursor = await conn.execute(
        """SELECT 1 FROM youtube_level_alerts
           WHERE ticker = ? AND ABS(price - ?) / ? < 0.01 AND alerted_at >= ?
           LIMIT 1""",
        (ticker, price, price, cutoff),
    )
    row = await cursor.fetchone()
    return row is not None


async def record_level_alert(ticker: str, level_type: str, price: float, channel_name: str) -> None:
    """Record that a level proximity alert was fired."""
    conn = await get_db()
    await conn.execute(
        """INSERT INTO youtube_level_alerts (ticker, level_type, price, channel_name, alerted_at)
           VALUES (?, ?, ?, ?, ?)""",
        (ticker, level_type, price, channel_name, time.time()),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Signal events helpers
# ---------------------------------------------------------------------------

async def record_signal_event(
    source_type: str,
    ticker: str,
    direction: str | None = None,
    source_detail: str | None = None,
    quality_score: float = 0.5,
    latency_sec: float | None = None,
    provenance: str | None = None,
    model_version: str | None = None,
) -> int:
    """Record a signal event. Returns the new row ID."""
    conn = await get_db()
    cursor = await conn.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score,
            latency_sec, provenance, model_version, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_type, source_detail, ticker, direction, quality_score,
         latency_sec, provenance, model_version, time.time()),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_signal_events_for_ticker(ticker: str, window_seconds: int = 3600) -> list[dict]:
    """Fetch signal events for a ticker within the rolling window."""
    conn = await get_db()
    cutoff = time.time() - window_seconds
    cursor = await conn.execute(
        """SELECT id, source_type, source_detail, ticker, direction, quality_score,
                  latency_sec, provenance, model_version, recorded_at
           FROM signal_events
           WHERE ticker = ? AND recorded_at >= ?
           ORDER BY recorded_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Decision snapshot helpers
# ---------------------------------------------------------------------------

async def record_decision_snapshot(
    ticker: str,
    decision: str,
    final_score: float,
    sources_json: str,
    contradiction_index: float = 0.0,
    feature_vector_json: str | None = None,
    weights_json: str | None = None,
    outcome_price_at_alert: float | None = None,
) -> int:
    """Record a decision snapshot. Returns the new row ID."""
    conn = await get_db()
    cursor = await conn.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, contradiction_index, sources_json,
            feature_vector_json, weights_json, recorded_at, outcome_price_at_alert)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, decision, final_score, contradiction_index, sources_json,
         feature_vector_json, weights_json, time.time(), outcome_price_at_alert),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_recent_decision_snapshots(ticker: str, limit: int = 10) -> list[dict]:
    """Get the most recent decision snapshots for a ticker."""
    conn = await get_db()
    cursor = await conn.execute(
        """SELECT id, ticker, decision, final_score, contradiction_index,
                  sources_json, feature_vector_json, weights_json, recorded_at,
                  outcome_price_at_alert, outcome_price_1h, outcome_price_24h
           FROM decision_snapshots
           WHERE ticker = ?
           ORDER BY recorded_at DESC LIMIT ?""",
        (ticker, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_snapshot_outcomes(
    snapshot_id: int,
    outcome_price_1h: float | None = None,
    outcome_price_24h: float | None = None,
) -> None:
    """Backfill price outcomes on a decision snapshot."""
    conn = await get_db()
    await conn.execute(
        """UPDATE decision_snapshots
           SET outcome_price_1h = COALESCE(?, outcome_price_1h),
               outcome_price_24h = COALESCE(?, outcome_price_24h)
           WHERE id = ?""",
        (outcome_price_1h, outcome_price_24h, snapshot_id),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Source health helpers
# ---------------------------------------------------------------------------

async def upsert_source_health(
    source_id: str,
    last_heartbeat: float,
    error_rate: float,
    freshness_seconds: float,
) -> None:
    """Upsert source health record."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO source_health
           (source_id, last_heartbeat, error_rate, freshness_seconds, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (source_id, last_heartbeat, error_rate, freshness_seconds, time.time()),
    )
    await conn.commit()


async def get_all_source_health() -> list[dict]:
    """Get all source health records, ordered by source_id."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT source_id, last_heartbeat, error_rate, freshness_seconds, updated_at FROM source_health ORDER BY source_id"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_source_health(source_id: str) -> dict | None:
    """Get health record for a single source."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT source_id, last_heartbeat, error_rate, freshness_seconds, updated_at FROM source_health WHERE source_id = ?",
        (source_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def enqueue_atlas_job(ticker: str, reason: str) -> int | None:
    """Enqueue a research job. Coalesces: returns None if a pending/running
    job for this ticker already exists.
    """
    conn = await get_db()
    cur = await conn.execute(
        "SELECT id FROM research_jobs WHERE ticker=? AND status IN ('pending','running')",
        (ticker.upper(),),
    )
    if await cur.fetchone():
        return None
    cur = await conn.execute(
        """INSERT INTO research_jobs (ticker, reason, status, attempts, created_at)
           VALUES (?, ?, 'pending', 0, ?)""",
        (ticker.upper(), reason, time.time()),
    )
    await conn.commit()
    return cur.lastrowid


async def acquire_atlas_lease(lease_ttl: float) -> dict | None:
    """Claim the oldest pending job (or one whose lease expired).
    Returns job dict with the lease stamped, or None if queue is idle.
    """
    conn = await get_db()
    now = time.time()
    cur = await conn.execute(
        """SELECT id, ticker, reason, attempts FROM research_jobs
           WHERE status='pending' OR (status='running' AND lease_expires_at < ?)
           ORDER BY created_at ASC LIMIT 1""",
        (now,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    job_id = row["id"]
    await conn.execute(
        """UPDATE research_jobs
           SET status='running', lease_expires_at=?, attempts=attempts+1
           WHERE id=?""",
        (now + lease_ttl, job_id),
    )
    await conn.commit()
    return {
        "id": job_id,
        "ticker": row["ticker"],
        "reason": row["reason"],
        "attempts": row["attempts"] + 1,
        "status": "running",
    }


async def finish_atlas_job(job_id: int, status: str) -> None:
    """Mark a job as done or failed."""
    conn = await get_db()
    await conn.execute(
        "UPDATE research_jobs SET status=?, finished_at=? WHERE id=?",
        (status, time.time(), job_id),
    )
    await conn.commit()


async def upsert_research_section(ticker: str, source: str,
                                  content: str | None, status: str) -> None:
    """Upsert a section. On status='ok' updates last_good_content/last_good_at.
    On any other status, preserves prior last_good_content.
    """
    conn = await get_db()
    now = time.time()
    cur = await conn.execute(
        "SELECT last_good_content, last_good_at FROM research_sections WHERE ticker=? AND source=?",
        (ticker.upper(), source),
    )
    existing = await cur.fetchone()

    if status == "ok":
        lg_content = content
        lg_at = now
    else:
        lg_content = existing["last_good_content"] if existing else None
        lg_at = existing["last_good_at"] if existing else None

    await conn.execute(
        """INSERT INTO research_sections
              (ticker, source, content, last_good_content, fetched_at, last_good_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ticker, source) DO UPDATE SET
              content=excluded.content,
              last_good_content=excluded.last_good_content,
              fetched_at=excluded.fetched_at,
              last_good_at=excluded.last_good_at,
              status=excluded.status""",
        (ticker.upper(), source, content, lg_content, now, lg_at, status),
    )
    await conn.commit()


async def get_research_sections(ticker: str) -> dict[str, dict]:
    """Return {source: {content, last_good_content, fetched_at, last_good_at, status}}."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT source, content, last_good_content, fetched_at, last_good_at, status "
        "FROM research_sections WHERE ticker=?",
        (ticker.upper(),),
    )
    rows = await cur.fetchall()
    return {r["source"]: dict(r) for r in rows}


async def get_briefing_run(session_key: str) -> dict | None:
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM briefing_runs WHERE session_key=?", (session_key,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def upsert_briefing_run(session_key: str, **fields) -> None:
    """Upsert a briefing row. Auto-stamps posted_at on status='posted' and
    archived_at on status='archived'. Requires session_start_utc / session_end_utc
    on first insert.
    """
    conn = await get_db()
    now = time.time()
    existing = await get_briefing_run(session_key)

    if fields.get("status") == "posted" and "posted_at" not in fields:
        fields["posted_at"] = now
    if fields.get("status") == "archived" and "archived_at" not in fields:
        fields["archived_at"] = now

    if existing is None:
        row = {
            "session_key": session_key,
            "session_start_utc": fields.get("session_start_utc", 0.0),
            "session_end_utc": fields.get("session_end_utc", 0.0),
            "rendered_content": fields.get("rendered_content"),
            "discord_message_id": fields.get("discord_message_id"),
            "status": fields.get("status", "pending"),
            "created_at": now,
            "posted_at": fields.get("posted_at"),
            "archived_at": fields.get("archived_at"),
        }
        await conn.execute(
            """INSERT INTO briefing_runs
               (session_key, session_start_utc, session_end_utc, rendered_content,
                discord_message_id, status, created_at, posted_at, archived_at)
               VALUES (:session_key, :session_start_utc, :session_end_utc, :rendered_content,
                       :discord_message_id, :status, :created_at, :posted_at, :archived_at)""",
            row,
        )
    else:
        allowed = {"session_start_utc", "session_end_utc", "rendered_content",
                   "discord_message_id", "status", "posted_at", "archived_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            cols = ", ".join(f"{k}=?" for k in sets)
            values = list(sets.values()) + [session_key]
            await conn.execute(
                f"UPDATE briefing_runs SET {cols} WHERE session_key=?", values,
            )
    await conn.commit()


async def get_top_tickers_session(session_start_utc: float, session_end_utc: float,
                                  limit: int = 10) -> list[str]:
    """Return tickers sorted desc by signal count within [start, end)."""
    conn = await get_db()
    cur = await conn.execute(
        """SELECT ticker, COUNT(*) AS cnt FROM ticker_signals
           WHERE detected_at >= ? AND detected_at < ?
           GROUP BY ticker ORDER BY cnt DESC, ticker ASC LIMIT ?""",
        (session_start_utc, session_end_utc, limit),
    )
    rows = await cur.fetchall()
    return [r["ticker"] for r in rows]
