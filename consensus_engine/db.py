"""SQLite database layer with an async-compatible sqlite3 wrapper."""

import asyncio
import json
import logging
import sqlite3
import time

from consensus_engine import config as cfg
from consensus_engine.models import TickerSignal, SourceType, Sentiment

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

# Sentinel: "leave this column unchanged" for partial UPDATE helpers.
_KEEP = object()

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

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id  TEXT PRIMARY KEY,
    channel_id  TEXT NOT NULL,
    status      TEXT NOT NULL,
    updated_at  REAL NOT NULL
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

-- Sub-industry peer layer (item 3): cache yfinance .info sector/industry for
-- tickers NOT in data/peer_groups.yaml, so the !all peer-comparison dynamic
-- fallback doesn't re-fetch a slow .info on every command. Sector/industry is
-- stable → long TTL (see analysis/peer_comparison.py).
CREATE TABLE IF NOT EXISTS ticker_sector_cache (
    ticker TEXT PRIMARY KEY,
    sector TEXT,
    industry TEXT,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
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

CREATE TABLE IF NOT EXISTS shadow_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    predicted_prob REAL NOT NULL,
    horizon TEXT NOT NULL,
    actual_hit INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_alert ON shadow_predictions(alert_id);
CREATE INDEX IF NOT EXISTS idx_shadow_pending ON shadow_predictions(actual_hit, horizon)
    WHERE actual_hit IS NULL;

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
CREATE INDEX IF NOT EXISTS idx_yla_ticker_alerted ON youtube_level_alerts(ticker, alerted_at);

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
CREATE TABLE IF NOT EXISTS youtube_analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    call_budget_used INTEGER DEFAULT 0,
    started_at REAL NOT NULL,
    completed_at REAL,
    UNIQUE(video_id, parser_version)
);
CREATE INDEX IF NOT EXISTS idx_yar_video ON youtube_analysis_runs(video_id);
CREATE TABLE IF NOT EXISTS youtube_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES youtube_analysis_runs(id),
    video_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    option_type TEXT NOT NULL,
    strike REAL,
    expiry TEXT,
    strategy TEXT,
    source TEXT,
    conviction TEXT,
    context_text TEXT,
    source_snippet TEXT,
    chunk_id INTEGER DEFAULT 0,
    parser_version TEXT NOT NULL,
    channel_name TEXT,
    published_at TEXT,
    extracted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yopt_ticker ON youtube_options(ticker);
CREATE INDEX IF NOT EXISTS idx_yopt_extracted ON youtube_options(extracted_at);

-- #18: near-real-time unusual options FLOW detected from live yfinance chains.
-- Distinct from youtube_options (analyst trade ideas from videos): this is
-- market-microstructure flow. Feeds both the instant alert and !all cross-ref.
CREATE TABLE IF NOT EXISTS options_flow (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    strike REAL,
    expiry TEXT,
    volume INTEGER,
    open_interest INTEGER,
    vol_oi_ratio REAL,
    premium_usd REAL,
    last_trade_ts REAL,
    spot REAL,
    contract_symbol TEXT,
    alerted INTEGER DEFAULT 0,
    detected_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_options_flow_ticker ON options_flow(ticker);
CREATE INDEX IF NOT EXISTS idx_options_flow_detected ON options_flow(detected_at);

CREATE TABLE IF NOT EXISTS youtube_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES youtube_analysis_runs(id),
    video_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    entry_low REAL,
    entry_high REAL,
    stop_price REAL,
    targets_json TEXT,
    timeframe TEXT,
    setup_type TEXT,
    context_text TEXT,
    source_snippet TEXT,
    chunk_id INTEGER DEFAULT 0,
    risk_reward REAL,
    parser_version TEXT NOT NULL,
    channel_name TEXT,
    published_at TEXT,
    extracted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yset_ticker ON youtube_setups(ticker);
CREATE INDEX IF NOT EXISTS idx_yset_extracted ON youtube_setups(extracted_at);

CREATE TABLE IF NOT EXISTS youtube_evidence_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES youtube_analysis_runs(id),
    video_id TEXT NOT NULL,
    ts_sec INTEGER NOT NULL,
    quote TEXT NOT NULL,
    tickers_json TEXT,
    numbers_json TEXT,
    dates_json TEXT,
    UNIQUE(run_id, ts_sec, quote)
);
CREATE INDEX IF NOT EXISTS idx_yes_run ON youtube_evidence_spans(run_id);
CREATE INDEX IF NOT EXISTS idx_yes_video ON youtube_evidence_spans(video_id);

CREATE TABLE IF NOT EXISTS youtube_visual_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    ts_sec INTEGER NOT NULL,
    value TEXT NOT NULL,
    kind TEXT,
    where_seen TEXT,
    created_at REAL NOT NULL,
    ticker TEXT  -- B3: per-number ticker tag (NULL = untagged → top-ticker attribution)
);
CREATE INDEX IF NOT EXISTS idx_yve_video ON youtube_visual_evidence(video_id);

CREATE TABLE IF NOT EXISTS youtube_catalysts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES youtube_analysis_runs(id),
    video_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    catalyst_type TEXT NOT NULL,
    mentioned_date TEXT,
    resolved_date TEXT,
    verified INTEGER DEFAULT 0,
    context_text TEXT,
    video_timestamp_sec INTEGER,
    evidence_span_ids TEXT,
    suppressed INTEGER DEFAULT 0,
    suppression_reason TEXT,
    UNIQUE(run_id, ticker, resolved_date, catalyst_type)
);
CREATE INDEX IF NOT EXISTS idx_ycat_ticker ON youtube_catalysts(ticker);
CREATE INDEX IF NOT EXISTS idx_ycat_run ON youtube_catalysts(run_id);

CREATE TABLE IF NOT EXISTS regime_daily (
    date_utc TEXT PRIMARY KEY,
    realized_vol_20d REAL NOT NULL,
    mean_252d REAL NOT NULL,
    std_252d REAL NOT NULL,
    z_score_raw REAL NOT NULL,
    z_score_smoothed REAL NOT NULL,
    regime_label TEXT NOT NULL CHECK(regime_label IN ('calm','normal','elevated','panic')),
    computed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS discord_command_user_rate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    command TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dcur_user_cmd_ts ON discord_command_user_rate(user_id, command, ts);

CREATE TABLE IF NOT EXISTS feature_flag_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature TEXT NOT NULL,
    prior_state INTEGER NOT NULL,
    new_state INTEGER NOT NULL,
    reason TEXT,
    flipped_by TEXT,
    flipped_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flag_audit_feature ON feature_flag_audit(feature);

CREATE TABLE IF NOT EXISTS form4_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    n_insiders INTEGER NOT NULL,
    total_dollars REAL NOT NULL,
    members_json TEXT NOT NULL,
    regime_label TEXT NOT NULL,
    falling_knife_threshold TEXT NOT NULL,
    alerted_at REAL NOT NULL,
    UNIQUE(ticker, window_end)
);
CREATE INDEX IF NOT EXISTS idx_form4_clusters_alerted ON form4_clusters(alerted_at);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS cluster_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    first_seen_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    cluster_size INTEGER NOT NULL,
    effective_size REAL NOT NULL,
    members_json TEXT NOT NULL,
    regime_label TEXT,
    fired_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cluster_events_ticker ON cluster_events(ticker);
CREATE INDEX IF NOT EXISTS idx_cluster_events_fired ON cluster_events(fired_at);

CREATE TABLE IF NOT EXISTS analyst_pair_correlations (
    analyst_a TEXT NOT NULL,
    analyst_b TEXT NOT NULL,
    co_post_rate REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (analyst_a, analyst_b),
    CHECK(analyst_a < analyst_b)
);

CREATE TABLE IF NOT EXISTS consolidated_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    window_start REAL NOT NULL,
    window_end REAL NOT NULL,
    sources_json TEXT NOT NULL,
    clusters_hit_json TEXT NOT NULL,
    effective_n_clusters INTEGER NOT NULL,
    combined_log_odds REAL NOT NULL,
    consensus_boost INTEGER NOT NULL,
    shadow_only INTEGER NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(ticker, window_start)
);
CREATE INDEX IF NOT EXISTS idx_consolidated_ticker ON consolidated_events(ticker);

CREATE TABLE IF NOT EXISTS seen_ingest_nonces (
    nonce TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL,
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sin_received ON seen_ingest_nonces(received_at);
CREATE INDEX IF NOT EXISTS idx_sin_routine_received ON seen_ingest_nonces(routine_id, received_at);

CREATE TABLE IF NOT EXISTS ingest_payload_results (
    nonce TEXT PRIMARY KEY,
    tickers_inserted INTEGER NOT NULL,
    completed_at REAL NOT NULL,
    FOREIGN KEY (nonce) REFERENCES seen_ingest_nonces(nonce)
);

CREATE TABLE IF NOT EXISTS seen_gmail_messages (
    message_id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    subject TEXT,
    received_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_gmail_bodies (
    body_sha1 TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    first_seen_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS routine_health (
    routine_id TEXT PRIMARY KEY,
    last_cycle_started REAL,
    last_success_at REAL,
    errors_in_cycle INTEGER DEFAULT 0,
    paused_until REAL,
    meta_json TEXT
);

-- Wolf macro-brain (TODO #20) phase 1. Separate from ticker_signals so Wolf's
-- macro commentary never enters the live per-ticker alert/scoring pipeline.
CREATE TABLE IF NOT EXISTS macro_theses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL,            -- market | sector | stock | asset
    scope_key TEXT NOT NULL,             -- canonical: SPX, XLE, NVDA, OIL, GOLD, BONDS, YIELDS, BTC, DXY
    direction TEXT NOT NULL,             -- bull | bear
    stage TEXT NOT NULL DEFAULT 'forming',  -- forming | diverging | imminent | acting | invalidated
    source TEXT NOT NULL DEFAULT 'wolf',
    key_levels_json TEXT NOT NULL DEFAULT '[]',  -- [{"price":.., "role":"support|resistance|target", "confidence":..}]
    price_at_creation REAL,
    created_at REAL NOT NULL,
    last_updated REAL NOT NULL,
    invalidated_at REAL,
    status TEXT NOT NULL DEFAULT 'active',   -- active | invalidated
    has_levels INTEGER NOT NULL DEFAULT 0,   -- 0 => surface tier only (no @-ping)
    evidence_log_json TEXT NOT NULL DEFAULT '[]'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_theses_active_unique
    ON macro_theses(scope_type, scope_key, direction) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_theses_scope ON macro_theses(scope_type, scope_key);
CREATE INDEX IF NOT EXISTS idx_theses_status ON macro_theses(status);

-- Durable outbox for #news posts (Codex review): build a 'pending' row, post,
-- then mark 'posted' so a crash can never double-post or lose an alert.
CREATE TABLE IF NOT EXISTS wolf_news_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,     -- e.g. "<thesis_id>|<stage>" — one alert per stage
    thesis_id INTEGER,
    tier TEXT NOT NULL DEFAULT 'surface',-- surface | high | critical
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | posted | failed
    payload_json TEXT NOT NULL DEFAULT '{}',
    discord_message_id TEXT,
    created_at REAL NOT NULL,
    posted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_wolf_alerts_status ON wolf_news_alerts(status);

-- Wolf email processing ledger (Codex review): Wolf signal lives in image URLs,
-- not text, so the generic text-only seen_gmail_bodies dedupe is insufficient.
-- Mark a Gmail message processed (label) ONLY after a row here is written.
CREATE TABLE IF NOT EXISTS wolf_emails_processed (
    message_id TEXT PRIMARY KEY,
    html_sha1 TEXT,
    image_urls_sha1 TEXT,
    parse_status TEXT NOT NULL DEFAULT 'ok',  -- ok | partial | error
    error TEXT,
    theses_touched INTEGER NOT NULL DEFAULT 0,
    processed_at REAL NOT NULL
);

-- Phase-2 cross-source confluence (TODO #20, Type-2): ONE current-state row per
-- thesis (UPSERT on thesis_id) so the table stays bounded by the small # of active
-- theses. alerted_tier carries the hysteresis (only a strict tier-UP re-posts).
CREATE TABLE IF NOT EXISTS wolf_confluence_checks (
    thesis_id INTEGER PRIMARY KEY,       -- one row per thesis (FK macro_theses.id)
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    direction TEXT NOT NULL,             -- bull | bear (the Wolf thesis side)
    checked_at REAL NOT NULL,
    window_days INTEGER NOT NULL,
    agree_count INTEGER NOT NULL DEFAULT 0,
    disagree_count INTEGER NOT NULL DEFAULT 0,
    tier TEXT NOT NULL DEFAULT 'surface',        -- confluence component: surface|high|critical
    combined_tier TEXT NOT NULL DEFAULT 'surface',-- max(phase1, confluence)
    divided INTEGER NOT NULL DEFAULT 0,
    agree_sources_json TEXT NOT NULL DEFAULT '[]',
    disagree_sources_json TEXT NOT NULL DEFAULT '[]',
    alerted_tier TEXT NOT NULL DEFAULT 'surface' -- last tier actually POSTED for this thesis
);

-- Phase-3 (TODO #20): Sunday-recap "what played out" outcomes. ONE row per thesis
-- (UPSERT on thesis_id). Only theses that reached an ACTIONABLE stage (imminent|acting)
-- are ever scored; everything else stays absent / inconclusive. Wording is humble: a
-- coarse proxy-price move from the actionable anchor, never a "win".
CREATE TABLE IF NOT EXISTS wolf_call_outcomes (
    thesis_id    INTEGER PRIMARY KEY,          -- FK macro_theses.id
    scope_type   TEXT, scope_key TEXT, direction TEXT,   -- denormalized for display
    proxy_symbol TEXT,
    anchor_stage TEXT,                          -- 'imminent' | 'acting' — the stage scored from
    anchor_ts    REAL,                          -- first evidence_log ts the thesis entered anchor_stage
    anchor_close REAL,                          -- proxy close on/just before anchor_ts date
    latest_close REAL,
    pct_move     REAL,                          -- sign-adjusted toward Wolf's direction
    band         REAL,                          -- vol-scaled threshold used
    state        TEXT,                          -- moved_with|moved_against|flat|invalidated|inconclusive
    computed_at  REAL
);

-- Phase-4 (TODO #20) #2: inferred beneficiary LONGs per macro/sector thesis. Precomputed
-- by the beneficiary cycle (never at digest time) and read cheaply by the digest. Rows are
-- the bot's RS-leadership inference (NOT Wolf's picks). Bounded by replace-per-thesis;
-- writes ONLY happen here in the wolf lane (isolation).
CREATE TABLE IF NOT EXISTS wolf_beneficiaries (
    thesis_id    INTEGER NOT NULL,              -- FK macro_theses.id
    ticker       TEXT NOT NULL,
    side         TEXT NOT NULL DEFAULT 'long',
    scope_type   TEXT, scope_key TEXT, direction TEXT,   -- denormalized for the digest
    score        REAL,                           -- winsorized-percentile rank_score (0-1)
    confidence   REAL,                           -- 0.15-0.95
    tier         TEXT,                           -- 'green' | 'yellow'
    reason       TEXT,                           -- terse honest justification
    signals_json TEXT,                           -- {rs_delta, rs_mode, catalyst, flow_bullish, ...}
    computed_at  REAL NOT NULL,
    PRIMARY KEY (thesis_id, ticker, side)
);
CREATE INDEX IF NOT EXISTS idx_benef_computed ON wolf_beneficiaries(computed_at);
"""

# Unique indices that reference columns added by _run_column_migrations.
# Applied AFTER migrations so run_id exists.
POST_MIGRATION_INDICES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_signals_uniq "
    "ON youtube_signals(run_id, ticker, direction)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_levels_uniq "
    "ON youtube_levels(run_id, ticker, level_type, price)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_setups_uniq "
    "ON youtube_setups(run_id, ticker, entry_low, entry_high)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_options_uniq "
    "ON youtube_options(run_id, ticker, option_type, strike, expiry)",
]


async def _run_column_migrations(conn) -> None:
    """Add provenance and run_id columns to pre-existing YouTube tables."""
    v2_span_cols = [
        ("video_timestamp_sec",  "INTEGER"),
        ("evidence_span_ids",    "TEXT"),
        ("classifier_confidence", "REAL"),
        ("suppressed",           "INTEGER DEFAULT 0"),
        ("suppression_reason",   "TEXT"),
    ]
    migrations = [
        # Wolf trade idea (action/entry/target Wolf framed) — null when he gave only analysis.
        ("macro_theses", "trade_setup_json", "TEXT"),
        ("youtube_signals", "run_id",         "INTEGER REFERENCES youtube_analysis_runs(id)"),
        ("youtube_signals", "source_snippet",  "TEXT"),
        ("youtube_signals", "chunk_id",        "INTEGER DEFAULT 0"),
        ("youtube_signals", "parser_version",  "TEXT"),
        ("youtube_levels",  "run_id",          "INTEGER REFERENCES youtube_analysis_runs(id)"),
        ("youtube_levels",  "source_snippet",  "TEXT"),
        ("youtube_levels",  "chunk_id",        "INTEGER DEFAULT 0"),
        ("youtube_levels",  "parser_version",  "TEXT"),
        ("youtube_levels",  "setup_id",        "INTEGER"),
        ("youtube_macro",   "run_id",          "INTEGER REFERENCES youtube_analysis_runs(id)"),
        ("youtube_macro",   "parser_version",  "TEXT"),
        ("youtube_macro",   "narrative",       "TEXT"),
        ("youtube_analysis_runs", "input_tokens",     "INTEGER"),
        ("youtube_analysis_runs", "output_tokens",    "INTEGER"),
        ("youtube_analysis_runs", "latency_ms",       "INTEGER"),
        ("youtube_analysis_runs", "json_parse_ok",    "INTEGER"),
        ("youtube_analysis_runs", "span_count",       "INTEGER"),
        ("youtube_analysis_runs", "filter_drop_count", "INTEGER"),
        # C1/C2: which chain method won (gemini/v2 = full chart read vs caption/
        # whisper fallback) and why Gemini stopped (timeout|quota|unavailable|
        # token_limit|unknown) — made queryable telemetry per video run.
        ("youtube_analysis_runs", "chain_winner",       "TEXT"),
        ("youtube_analysis_runs", "f2_failure_category", "TEXT"),
        ("api_usage_daily", "gemini_input_tokens",  "INTEGER NOT NULL DEFAULT 0"),
        ("api_usage_daily", "gemini_output_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("api_usage_daily", "gemini_video_calls",   "INTEGER NOT NULL DEFAULT 0"),
        ("api_usage_daily", "wolf_vision_calls",    "INTEGER NOT NULL DEFAULT 0"),
        ("decision_snapshots", "alert_id",  "INTEGER"),
        ("signal_events", "consumed_by_cluster_id", "INTEGER"),
        ("sec_form4_filings", "is_10b5_1", "INTEGER DEFAULT 0"),
        ("youtube_videos",    "description", "TEXT"),
        ("youtube_evidence_spans", "parser_version",   "TEXT"),
        ("youtube_evidence_spans", "chain_winner",     "TEXT"),
        ("youtube_evidence_spans", "grounding_status", "TEXT DEFAULT 'grounded'"),
        ("youtube_evidence_spans", "caption_entropy",  "REAL"),
        ("youtube_videos", "chain_failed_alerted_at", "REAL"),
        ("youtube_visual_evidence", "ticker", "TEXT"),  # B3 per-number ticker tag
        # Phase-3 (TODO #20): the email's Gmail internalDate (epoch seconds). The
        # digest scheduler triggers off THIS, never processed_at, so backfilled rows
        # (old received_at) can never fire a "fresh" digest. NULL on legacy rows.
        ("wolf_emails_processed", "received_at", "REAL"),
    ]
    for table in ("youtube_signals", "youtube_levels", "youtube_setups", "youtube_options"):
        for col, defn in v2_span_cols:
            migrations.append((table, col, defn))
    # Get set of existing table names to skip migrations for non-existent tables
    cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {r["name"] for r in await cur.fetchall()}
    for table, col, defn in migrations:
        if table not in existing_tables:
            continue
        cur = await conn.execute(f"PRAGMA table_info({table})")
        existing = {r["name"] for r in await cur.fetchall()}
        if col not in existing:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
    await conn.commit()


async def _dedup_legacy_rows(conn) -> None:
    """Delete legacy duplicate rows that violate v2 UNIQUE indices.

    Keeps the oldest row (MIN(id)) per composite key. Idempotent — safe to run
    on already-deduped tables. Must execute AFTER _run_column_migrations (so
    run_id exists) and BEFORE POST_MIGRATION_INDICES (so CREATE UNIQUE INDEX
    does not raise IntegrityError on legacy duplicates).
    """
    targets = [
        ("youtube_signals", "run_id, ticker, direction"),
        ("youtube_levels",  "run_id, ticker, level_type, price"),
        ("youtube_setups",  "run_id, ticker, entry_low, entry_high"),
        ("youtube_options", "run_id, ticker, option_type, strike, expiry"),
    ]
    removed = {}
    for table, cols in targets:
        cur = await conn.execute(
            f"DELETE FROM {table} WHERE id NOT IN ("
            f"SELECT MIN(id) FROM {table} GROUP BY {cols})"
        )
        removed[table] = cur.rowcount or 0
    await conn.commit()
    total = sum(removed.values())
    if total:
        log.info(
            "dedup: removed %d duplicate signals, %d levels, %d setups, %d options",
            removed["youtube_signals"], removed["youtube_levels"],
            removed["youtube_setups"], removed["youtube_options"],
        )


async def init_db() -> AsyncConnection:
    """Initialize database and create tables."""
    global _db
    db_path = DB_PATH or cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    # unixepoch() is a SQLite 3.38+ builtin; shim it so test/dev boxes on 3.37
    # (e.g. Ubuntu 22.04 default) can still run SQL that calls it.
    conn.create_function("unixepoch", 0, lambda: int(time.time()))
    _db = AsyncConnection(conn)
    _db.row_factory = sqlite3.Row
    # WAL mode for concurrent read/write from multiple coroutines
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    await _run_column_migrations(_db)   # add provenance columns to existing tables
    await _dedup_legacy_rows(_db)       # drop legacy dupes so UNIQUE index creation is safe
    for stmt in POST_MIGRATION_INDICES:
        await _db.execute(stmt)
    await _db.commit()
    # Insert schema_version rows (idempotent via INSERT OR IGNORE)
    _schema_versions = [
        (7, "cross-cutting feature-flag bundle"),
        (8, "A1 contradiction-penalty"),
        (9, "A5 regime tagger"),
        (10, "D1 form4 cluster-buy detector"),
        (11, "A4 sector ETF peer-confirmation gate"),
        (12, "A2 analyst herding detector"),
        (13, "A3 Bayesian source consolidation"),
        (14, "sub-industry peer layer cache (ticker_sector_cache)"),
        (15, "wolf macro-brain phase-1 (macro_theses, wolf_news_alerts, wolf_emails_processed)"),
        (16, "wolf macro-brain phase-2 cross-source confluence (wolf_confluence_checks)"),
        (17, "wolf macro-brain phase-3: wolf_call_outcomes + wolf_emails_processed.received_at"),
        (18, "wolf macro-brain phase-4: wolf_beneficiaries"),
    ]
    for version, note in _schema_versions:
        await _db.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at, note) VALUES (?, ?, ?)",
            (version, time.time(), note),
        )
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
    # Q2b: route tweet signals into signal_events so cross_reference scoring can see them.
    # M3 will replace the 0.5 placeholder with per-analyst precision.
    if signal.source_type == SourceType.TWITTER:
        direction = (
            "long" if signal.sentiment == Sentiment.BULLISH
            else "short" if signal.sentiment == Sentiment.BEARISH
            else None
        )
        await db.execute(
            """INSERT INTO signal_events
               (source_type, source_detail, ticker, direction, quality_score,
                latency_sec, provenance, model_version, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "twitter",
                signal.source_detail,
                signal.ticker,
                direction,
                0.5,
                None,
                "tweet",
                None,
                signal.detected_at,
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
    # desktop_local excluded: zero callers in v1; desktop_auth feeds cross-reference
    cursor = await db.execute(
        """SELECT source_type, source_detail, raw_text, sentiment, detected_at
           FROM ticker_signals
           WHERE ticker = ? AND source_type IN ('reddit', 'stocktwits', 'apewisdom', 'google_trends', 'desktop_auth')
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


async def get_analyst_precision(analyst: str, horizon: str = "1h") -> float | None:
    """Return rolling_accuracy for analyst at horizon, or None if sample_count < 5."""
    conn = await get_db()
    cursor = await conn.execute(
        """SELECT rolling_accuracy, sample_count FROM source_performance
           WHERE entity_id = ? AND horizon = ?""",
        (analyst, horizon),
    )
    row = await cursor.fetchone()
    if row is None or (row["sample_count"] or 0) < 5:
        return None
    return float(row["rolling_accuracy"])


async def check_alert_cooldown(
    ticker: str,
    analyst: str | None = None,
    base_score: int | None = None,
) -> bool:
    """Return True when an alert for (ticker, analyst, base_score) is allowed.

    M3: exploits per-analyst 1h-hit-rate spread (14%-83% observed). High-precision
    analysts get a shorter cooldown; every path still enforces floor_minutes.
    Falls back to blanket ticker-level 6h when per_analyst_cooldown is disabled
    OR the analyst has < 5 samples in source_performance.
    """
    cooldown_hours = cfg.get("alerts.cooldown_hours", 6)
    per_analyst_enabled = cfg.get("alerts.per_analyst_cooldown.enabled", True)
    high_conv_bypass = cfg.get("alerts.per_analyst_cooldown.high_conviction_bypass", True)
    high_conv_threshold = cfg.get(
        "precision_engine.thresholds.high_conviction_threshold", 30
    )
    floor_minutes = cfg.get("alerts.per_analyst_cooldown.floor_minutes", 30)

    conn = await get_db()

    async def _blanket_blocked() -> bool:
        cutoff = time.time() - (cooldown_hours * 3600)
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM alert_history WHERE ticker = ? AND alerted_at > ?",
            (ticker, cutoff),
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0

    async def _analyst_blocked_within(window_minutes: int) -> bool:
        cutoff = time.time() - (window_minutes * 60)
        cursor = await conn.execute(
            """SELECT COUNT(*) as cnt FROM alert_history
               WHERE ticker = ? AND analyst_mentions LIKE ? AND alerted_at > ?""",
            (ticker, f'%"{analyst}"%', cutoff),
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0

    # Legacy ticker-level blanket cooldown
    if not per_analyst_enabled or analyst is None:
        return not await _blanket_blocked()

    # HIGH-conviction bypass: skips every cooldown including the floor.
    if (
        high_conv_bypass
        and base_score is not None
        and base_score >= high_conv_threshold
    ):
        return True

    # Per-analyst path: weight = clamp(precision * 2, 0.5, 2.0).
    # cooldown_h = min(max_cap, base / weight); 50%-precision = baseline 6 h.
    # Cold-start AND sample_count<5 both arrive as precision=None -> weight=1.0 (= base 6 h).
    max_cooldown_hours = cfg.get("alerts.per_analyst_cooldown.max_cooldown_hours", 24)
    precision = await get_analyst_precision(analyst, horizon="1h")
    if precision is None:
        weight = 1.0
    else:
        weight = min(2.0, max(0.5, precision * 2.0))
    cooldown_h = min(max_cooldown_hours, cooldown_hours / weight)
    scaled_minutes = max(floor_minutes, int(cooldown_h * 60))
    if await _analyst_blocked_within(scaled_minutes):
        return False
    # Always enforce floor regardless of precision
    return not await _analyst_blocked_within(floor_minutes)


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


# #8 — gateway reconnect replay. A 'claimed' row older than this is treated as
# an orphan (a handler that crashed before mark_message_done) and re-driven.
# Set above the longest handler runtime (@-mention subprocess <=270s).
_CLAIM_STALE_SECONDS = 300.0


async def claim_message(message_id: str, channel_id: str) -> bool:
    """Atomically claim a Discord message for handling. Returns True iff the
    caller now owns the dispatch.

    A claim succeeds for a brand-new message, or for one whose prior 'claimed'
    row is older than _CLAIM_STALE_SECONDS (an orphan). It fails for a message
    already 'done', or one 'claimed' within the staleness window (a handler is
    still running, or a concurrent caller just won the claim).
    """
    conn = await get_db()
    now = time.time()
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO processed_messages "
        "(message_id, channel_id, status, updated_at) VALUES (?, ?, 'claimed', ?)",
        (message_id, channel_id, now),
    )
    if (cursor.rowcount or 0) > 0:
        await conn.commit()
        return True
    # A row already exists — re-drive only a stale 'claimed' orphan. The
    # UPDATE's WHERE keeps this atomic: a 'done' row or a fresh 'claimed' row
    # matches nothing, and exactly one caller flips a given orphan.
    cursor = await conn.execute(
        "UPDATE processed_messages SET updated_at = ? "
        "WHERE message_id = ? AND status = 'claimed' AND updated_at < ?",
        (now, message_id, now - _CLAIM_STALE_SECONDS),
    )
    await conn.commit()
    return (cursor.rowcount or 0) > 0


async def mark_message_done(message_id: str) -> None:
    """Mark a claimed message as fully handled so replay never re-drives it."""
    conn = await get_db()
    await conn.execute(
        "UPDATE processed_messages SET status = 'done', updated_at = ? "
        "WHERE message_id = ?",
        (time.time(), message_id),
    )
    await conn.commit()


async def channel_watermark(channel_id: str) -> str | None:
    """Return the newest processed message_id for a channel, or None.

    Discord ids are snowflakes — monotonically increasing — so the
    numerically-largest id is the most recent message on record.
    """
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT message_id FROM processed_messages WHERE channel_id = ? "
        "ORDER BY CAST(message_id AS INTEGER) DESC LIMIT 1",
        (channel_id,),
    )
    row = await cursor.fetchone()
    return row["message_id"] if row else None


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


def _xref_db_key(ticker: str, key_prefix: str = "") -> str:
    """Build the namespaced xref_cache row key.

    Empty prefix → bare ticker (preserves rows written before PR3).
    """
    return f"{key_prefix}:{ticker}" if key_prefix else ticker


async def get_xref_from_db(
    ticker: str,
    ttl_seconds: int = 300,
    key_prefix: str = "",
) -> str | None:
    """Get cached xref result JSON from DB, or None if missing/expired."""
    conn = await get_db()
    cutoff = time.time() - ttl_seconds
    db_key = _xref_db_key(ticker, key_prefix)
    cursor = await conn.execute(
        "SELECT result_json FROM xref_cache WHERE ticker = ? AND cached_at > ?",
        (db_key, cutoff),
    )
    row = await cursor.fetchone()
    return row["result_json"] if row else None


async def set_xref_in_db(ticker: str, result_json: str, key_prefix: str = ""):
    """Store or update an xref cache entry in DB."""
    conn = await get_db()
    db_key = _xref_db_key(ticker, key_prefix)
    await conn.execute(
        "INSERT OR REPLACE INTO xref_cache (ticker, result_json, cached_at) VALUES (?, ?, ?)",
        (db_key, result_json, time.time()),
    )
    await conn.commit()


async def get_ticker_sector(ticker: str, ttl_seconds: int = 2_592_000) -> dict | None:
    """Cached yfinance sector/industry for a ticker, or None if missing/expired.

    Default TTL 30 days — sector/industry classification is effectively static.
    Returns {"sector": str|None, "industry": str|None} or None on miss.
    """
    conn = await get_db()
    cutoff = time.time() - ttl_seconds
    cursor = await conn.execute(
        "SELECT sector, industry FROM ticker_sector_cache WHERE ticker = ? AND fetched_at > ?",
        (ticker.upper(), cutoff),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    return {"sector": row["sector"], "industry": row["industry"]}


async def set_ticker_sector(ticker: str, sector: str | None, industry: str | None):
    """Store or update a ticker's yfinance sector/industry classification."""
    conn = await get_db()
    await conn.execute(
        "INSERT OR REPLACE INTO ticker_sector_cache (ticker, sector, industry, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (ticker.upper(), sector, industry, time.time()),
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
    description: str = "",
) -> None:
    """Insert a video record with status=pending, ignoring if already present."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_videos
           (video_id, channel_id, title, description, published_at, fetched_at, transcript_status)
           VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
        (video_id, channel_id, title, description, published_at, fetched_at),
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
    run_id: int | None = None,
    source_snippet: str | None = None,
    chunk_id: int = 0,
    parser_version: str | None = None,
    video_timestamp_sec: int | None = None,
    evidence_span_ids: str | None = None,
    classifier_confidence: float | None = None,
    suppressed: int = 0,
    suppression_reason: str | None = None,
) -> None:
    """Insert a YouTube signal for a ticker extracted from a video."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_signals
           (video_id, channel_name, ticker, direction, conviction, mention_count, macro_thesis, parsed_at, published_at, extracted_at,
            run_id, source_snippet, chunk_id, parser_version,
            video_timestamp_sec, evidence_span_ids, classifier_confidence, suppressed, suppression_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, channel_name, ticker, direction, conviction, mention_count, macro_thesis, time.time(), published_at, time.time(),
         run_id, source_snippet, chunk_id, parser_version,
         video_timestamp_sec, evidence_span_ids, classifier_confidence, suppressed, suppression_reason),
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
    run_id: int | None = None,
    source_snippet: str | None = None,
    chunk_id: int = 0,
    parser_version: str | None = None,
    video_timestamp_sec: int | None = None,
    evidence_span_ids: str | None = None,
    classifier_confidence: float | None = None,
    suppressed: int = 0,
    suppression_reason: str | None = None,
) -> None:
    """Insert a price level (support/resistance) extracted from a YouTube video."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_levels
           (video_id, ticker, level_type, price, condition_text, consequence_text, confidence, channel_name, published_at, extracted_at,
            run_id, source_snippet, chunk_id, parser_version,
            video_timestamp_sec, evidence_span_ids, classifier_confidence, suppressed, suppression_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (video_id, ticker, level_type, price, condition_text, consequence_text, confidence, channel_name, published_at, time.time(),
         run_id, source_snippet, chunk_id, parser_version,
         video_timestamp_sec, evidence_span_ids, classifier_confidence, suppressed, suppression_reason),
    )
    await conn.commit()


async def get_youtube_video(video_id: str) -> dict | None:
    """Return the youtube_videos row for video_id, or None."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT video_id, channel_id, title, description, published_at FROM youtube_videos WHERE video_id = ?",
        (video_id,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_youtube_signals_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """Get all YouTube signals for a ticker from the last N days.

    LEFT JOIN youtube_videos so each row gains video_title (str or None).
    Signals without a matching youtube_videos row still appear (title=None).

    W4: also LEFT JOIN youtube_channels (display_name = channel_name) so each
    row carries `trust_score` (float or None for unregistered channels) and
    selects `extracted_at` so the freshness of each mention is available for
    the flag-gated recency decay / channel-reliability scoring in
    cross_reference._get_youtube_context. Both columns are additive — when the
    youtube_score flags are OFF they are simply ignored.

    Each row also carries `evidence_spans_for_ticker` — the count of
    youtube_evidence_spans rows for the same video whose tickers_json
    explicitly tags this ticker. The display layer uses that to
    distinguish primary coverage from incidental over-tagging.
    """
    conn = await get_db()
    cutoff = time.time() - (days * 86400)
    cursor = await conn.execute(
        """SELECT s.video_id, s.channel_name, s.ticker, s.direction, s.conviction,
                  s.mention_count, s.macro_thesis, s.parsed_at, s.published_at,
                  s.extracted_at,
                  v.title AS video_title,
                  yc.trust_score AS trust_score,
                  (SELECT COUNT(*) FROM youtube_evidence_spans e
                   WHERE e.video_id = s.video_id
                     AND e.tickers_json LIKE '%"' || s.ticker || '"%')
                  AS evidence_spans_for_ticker
           FROM youtube_signals s
           LEFT JOIN youtube_videos v ON v.video_id = s.video_id
           LEFT JOIN youtube_channels yc ON yc.display_name = s.channel_name
           WHERE s.ticker = ? AND s.extracted_at >= ?
           ORDER BY s.extracted_at DESC""",
        (ticker, cutoff),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_youtube_levels_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """Get all YouTube price levels for a ticker from the last N days.

    PR5: excludes rows marked `suppressed=1` (price-sanity violations or
    off-allowlist), so corrupt parser output never reaches the !all anchor
    pipeline. NULL `suppressed` (legacy rows pre-PR5) is treated as 0.

    W2: LEFT JOIN youtube_channels on display_name = channel_name so the
    caller gets `channel_id` and `trust_score` in the same query. This is
    the CEF-10 fix — `rank_anchors()` is sync and `get_channel_trust()`
    is async, so pre-fetching trust at query time eliminates the boundary.
    Levels for unregistered channels return `channel_id=NULL, trust_score=NULL`
    and downstream code applies the bootstrap default (0.5 yt tier).
    """
    conn = await get_db()
    cutoff = time.time() - (days * 86400)
    cursor = await conn.execute(
        """SELECT yl.ticker, yl.level_type, yl.price, yl.condition_text,
                  yl.consequence_text, yl.confidence, yl.channel_name,
                  yl.published_at, yl.source_snippet,
                  yc.channel_id AS channel_id,
                  yc.trust_score AS trust_score,
                  yc.approved AS approved
           FROM youtube_levels yl
           LEFT JOIN youtube_channels yc
             ON yc.display_name = yl.channel_name
           WHERE yl.ticker = ? AND yl.extracted_at >= ?
             AND (yl.suppressed IS NULL OR yl.suppressed = 0)
           ORDER BY yl.confidence DESC, yl.extracted_at DESC""",
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


async def create_analysis_run(video_id: str, parser_version: str) -> int:
    """Create or return existing analysis run for this video+version. Returns run_id."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_analysis_runs (video_id, parser_version, status, started_at)
           VALUES (?, ?, 'running', ?)""",
        (video_id, parser_version, time.time()),
    )
    await conn.commit()
    cur = await conn.execute(
        "SELECT id FROM youtube_analysis_runs WHERE video_id=? AND parser_version=?",
        (video_id, parser_version),
    )
    row = await cur.fetchone()
    return row["id"]


async def update_analysis_run(run_id: int, status: str, call_budget_used: int = 0) -> None:
    conn = await get_db()
    await conn.execute(
        """UPDATE youtube_analysis_runs
           SET status=?, call_budget_used=?, completed_at=?
           WHERE id=?""",
        (status, call_budget_used, time.time(), run_id),
    )
    await conn.commit()


async def insert_youtube_option(
    run_id: int, video_id: str, ticker: str, option_type: str,
    strike: float | None, expiry: str | None, strategy: str | None,
    source: str | None, conviction: str | None, context_text: str | None,
    source_snippet: str | None, chunk_id: int, parser_version: str,
    channel_name: str | None, published_at: str | None,
    video_timestamp_sec: int | None = None,
    evidence_span_ids: str | None = None,
    classifier_confidence: float | None = None,
    suppressed: int = 0,
    suppression_reason: str | None = None,
) -> None:
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_options
           (run_id, video_id, ticker, option_type, strike, expiry, strategy,
            source, conviction, context_text, source_snippet, chunk_id,
            parser_version, channel_name, published_at, extracted_at,
            video_timestamp_sec, evidence_span_ids, classifier_confidence,
            suppressed, suppression_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, video_id, ticker, option_type, strike, expiry, strategy,
         source, conviction, context_text, source_snippet, chunk_id,
         parser_version, channel_name, published_at, time.time(),
         video_timestamp_sec, evidence_span_ids, classifier_confidence,
         suppressed, suppression_reason),
    )
    await conn.commit()


async def get_youtube_options_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """SELECT * FROM youtube_options
           WHERE ticker=? AND extracted_at>=?
           ORDER BY extracted_at DESC""",
        (ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def insert_options_flow(hits: list, alerted_tickers: set | None = None) -> None:
    """#18: persist detected options-flow hits (FlowHit objects). Rows whose
    ticker is in alerted_tickers are marked alerted=1, which drives the
    per-ticker alert cooldown (get_last_flow_alert_ts)."""
    if not hits:
        return
    alerted = alerted_tickers or set()
    conn = await get_db()
    now = time.time()
    for h in hits:
        await conn.execute(
            """INSERT INTO options_flow
               (ticker, side, strike, expiry, volume, open_interest, vol_oi_ratio,
                premium_usd, last_trade_ts, spot, contract_symbol, alerted, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (h.ticker, h.side, h.strike, h.expiry, h.volume, h.open_interest,
             h.vol_oi_ratio, h.premium_usd, h.last_trade_ts, h.spot,
             h.contract_symbol, 1 if h.ticker in alerted else 0, now),
        )
    await conn.commit()


async def get_options_flow_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """#18: recent options-flow rows for a ticker, for !all cross-reference."""
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """SELECT * FROM options_flow WHERE ticker=? AND detected_at>=?
           ORDER BY premium_usd DESC""",
        (ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_last_flow_alert_ts(ticker: str) -> float | None:
    """#18: epoch of the most recent ALERTED options-flow row for a ticker
    (None if never), used to enforce the per-ticker alert cooldown."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT MAX(detected_at) AS ts FROM options_flow WHERE ticker=? AND alerted=1",
        (ticker,),
    )
    row = await cur.fetchone()
    return row["ts"] if row and row["ts"] else None


async def insert_youtube_setup(
    run_id: int, video_id: str, ticker: str,
    entry_low: float | None, entry_high: float | None, stop_price: float | None,
    targets: list[float], timeframe: str | None, setup_type: str | None,
    context_text: str | None, source_snippet: str | None, chunk_id: int,
    risk_reward: float | None, parser_version: str,
    channel_name: str | None, published_at: str | None,
    video_timestamp_sec: int | None = None,
    evidence_span_ids: str | None = None,
    classifier_confidence: float | None = None,
    suppressed: int = 0,
    suppression_reason: str | None = None,
) -> int:
    """Insert a trade setup and return its id."""
    import json as _json
    conn = await get_db()
    cur = await conn.execute(
        """INSERT OR IGNORE INTO youtube_setups
           (run_id, video_id, ticker, entry_low, entry_high, stop_price,
            targets_json, timeframe, setup_type, context_text, source_snippet,
            chunk_id, risk_reward, parser_version, channel_name, published_at, extracted_at,
            video_timestamp_sec, evidence_span_ids, classifier_confidence,
            suppressed, suppression_reason)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, video_id, ticker, entry_low, entry_high, stop_price,
         _json.dumps(targets or []), timeframe, setup_type, context_text,
         source_snippet, chunk_id, risk_reward, parser_version,
         channel_name, published_at, time.time(),
         video_timestamp_sec, evidence_span_ids, classifier_confidence,
         suppressed, suppression_reason),
    )
    await conn.commit()
    if cur.lastrowid:
        return cur.lastrowid
    # INSERT OR IGNORE hit an existing unique row — look it up.
    cur = await conn.execute(
        """SELECT id FROM youtube_setups
           WHERE run_id=? AND ticker=? AND entry_low IS ? AND entry_high IS ?""",
        (run_id, ticker, entry_low, entry_high),
    )
    row = await cur.fetchone()
    return row["id"] if row else 0


async def get_youtube_setups_for_ticker(ticker: str, days: int = 14) -> list[dict]:
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """SELECT * FROM youtube_setups
           WHERE ticker=? AND extracted_at>=?
           ORDER BY extracted_at DESC""",
        (ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_youtube_evidence_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """Canonical read model: setups first, then unabsorbed raw levels. Never double-counts."""
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """
        SELECT 'setup' AS evidence_type,
               s.id, s.ticker, s.entry_low, s.entry_high, s.stop_price,
               s.targets_json, s.timeframe, s.setup_type, s.context_text,
               s.source_snippet, s.risk_reward, s.channel_name, s.published_at,
               s.extracted_at,
               NULL AS price, NULL AS level_type, NULL AS condition_text,
               NULL AS consequence_text
        FROM youtube_setups s
        WHERE s.ticker=? AND s.extracted_at>=?
        UNION ALL
        SELECT 'level' AS evidence_type,
               l.id, l.ticker, NULL, NULL, NULL,
               NULL, NULL, NULL, l.condition_text,
               l.source_snippet, NULL, l.channel_name, l.published_at,
               l.extracted_at,
               l.price, l.level_type, l.condition_text,
               l.consequence_text
        FROM youtube_levels l
        WHERE l.ticker=? AND l.extracted_at>=? AND l.setup_id IS NULL
        ORDER BY extracted_at DESC
        """,
        (ticker, cutoff, ticker, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_youtube_visual_evidence_for_ticker(ticker: str, days: int = 7) -> list[dict]:
    """On-screen chart numbers (visual_evidence) attributed to a ticker.

    Two-tier attribution (B3-aware, backward-compatible):
      * A row whose `ticker` column is set (B3 per-number tagging, feature
        `youtube.visual.per_number_ticker_tagging`) is returned ONLY for that
        exact ticker — so a multi-stock video no longer dumps every number on
        its top ticker.
      * A row with `ticker` NULL (untagged: feature off, or Gemini left it
        unlabeled) keeps the original conservative behavior — returned only
        when `ticker` is the video's TOP-mentioned signal ticker in the window.
    When the feature is off every row is NULL, so this is identical to the
    pre-B3 query.
    """
    conn = await get_db()
    cutoff = time.time() - days * 86400
    cur = await conn.execute(
        """
        SELECT v.video_id, v.ts_sec, v.value, v.kind, v.where_seen,
            (SELECT s.channel_name FROM youtube_signals s
             WHERE s.video_id = v.video_id AND s.extracted_at >= ?
             ORDER BY s.mention_count DESC LIMIT 1) AS channel_name
        FROM youtube_visual_evidence v
        WHERE
          -- B3 tagged: surfaces ONLY under its own tag. The tag need not be a
          -- video signal (visual-only tickers are valid); the parser already
          -- rejects malformed tags, and a tag can only ever surface under
          -- itself — never leak onto a different real ticker.
          (v.ticker = ? AND EXISTS (
             SELECT 1 FROM youtube_signals s
             WHERE s.video_id = v.video_id AND s.extracted_at >= ?))
          OR
          (v.ticker IS NULL AND EXISTS (
             SELECT 1 FROM youtube_signals s
             WHERE s.video_id = v.video_id AND s.ticker = ? AND s.extracted_at >= ?
               AND s.mention_count = (
                 SELECT MAX(s2.mention_count) FROM youtube_signals s2
                 WHERE s2.video_id = v.video_id AND s2.extracted_at >= ?)))
        ORDER BY v.ts_sec ASC
        """,
        (cutoff, ticker, cutoff, ticker, cutoff, cutoff),
    )
    return [dict(r) for r in await cur.fetchall()]


async def mark_levels_absorbed_by_setup(level_ids: list[int], setup_id: int) -> None:
    """Tag raw level rows as belonging to a setup so canonical reads skip them."""
    if not level_ids:
        return
    conn = await get_db()
    placeholders = ",".join("?" * len(level_ids))
    await conn.execute(
        f"UPDATE youtube_levels SET setup_id=? WHERE id IN ({placeholders})",
        [setup_id, *level_ids],
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# v2 evidence spans + catalysts + analysis run metrics + user rate limit
# ---------------------------------------------------------------------------

async def insert_youtube_evidence_span(
    run_id: int,
    video_id: str,
    ts_sec: int,
    quote: str,
    tickers: list | None = None,
    numbers: list | None = None,
    dates: list | None = None,
    parser_version: str | None = None,
    chain_winner: str | None = None,
    grounding_status: str = "grounded",
    caption_entropy: float | None = None,
) -> None:
    """Idempotent insert of a grounded evidence span (quote + tags)."""
    import json as _json
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_evidence_spans
           (run_id, video_id, ts_sec, quote, tickers_json, numbers_json, dates_json,
            parser_version, chain_winner, grounding_status, caption_entropy)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, video_id, ts_sec, quote,
            _json.dumps(tickers) if tickers is not None else None,
            _json.dumps(numbers) if numbers is not None else None,
            _json.dumps(dates) if dates is not None else None,
            parser_version, chain_winner, grounding_status, caption_entropy,
        ),
    )
    await conn.commit()


async def insert_youtube_visual_evidence(video_id: str, items: list[dict]) -> None:
    """Insert on-screen visual-evidence items (chart numbers, scanner rows, labels).

    Each item is a dict shaped like
    ``{ts_sec:int, value:str, kind:str, where:str}`` (as produced by
    ``_clean_visual_evidence``). No-op when ``items`` is empty.
    """
    if not items:
        return
    now = time.time()
    conn = await get_db()
    for item in items:
        tkr = item.get("ticker")  # B3: None when untagged (feature off / unlabeled)
        await conn.execute(
            """INSERT INTO youtube_visual_evidence
               (video_id, ts_sec, value, kind, where_seen, created_at, ticker)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                video_id,
                int(item.get("ts_sec", 0)),
                str(item.get("value", "")),
                item.get("kind"),
                item.get("where"),
                now,
                str(tkr).upper() if tkr else None,
            ),
        )
    await conn.commit()


async def insert_youtube_catalyst(
    run_id: int,
    video_id: str,
    ticker: str,
    catalyst_type: str,
    mentioned_date: str | None = None,
    resolved_date: str | None = None,
    verified: int = 0,
    context_text: str | None = None,
    video_timestamp_sec: int | None = None,
    evidence_span_ids: str | None = None,
) -> None:
    """Idempotent insert of a catalyst row (unique per run/ticker/date/type)."""
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO youtube_catalysts
           (run_id, video_id, ticker, catalyst_type, mentioned_date, resolved_date,
            verified, context_text, video_timestamp_sec, evidence_span_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, video_id, ticker, catalyst_type, mentioned_date, resolved_date,
            verified, context_text, video_timestamp_sec, evidence_span_ids,
        ),
    )
    await conn.commit()


async def update_analysis_run_metrics(
    run_id: int,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    latency_ms: int | None = None,
    json_parse_ok: int | None = None,
    span_count: int | None = None,
    filter_drop_count: int | None = None,
    chain_winner: str | None = None,
    f2_failure_category: str | None = None,
) -> None:
    """Update telemetry columns on a youtube_analysis_runs row."""
    conn = await get_db()
    await conn.execute(
        """UPDATE youtube_analysis_runs
           SET input_tokens        = COALESCE(?, input_tokens),
               output_tokens       = COALESCE(?, output_tokens),
               latency_ms          = COALESCE(?, latency_ms),
               json_parse_ok       = COALESCE(?, json_parse_ok),
               span_count          = COALESCE(?, span_count),
               filter_drop_count   = COALESCE(?, filter_drop_count),
               chain_winner        = COALESCE(?, chain_winner),
               f2_failure_category = COALESCE(?, f2_failure_category)
           WHERE id = ?""",
        (input_tokens, output_tokens, latency_ms, json_parse_ok,
         span_count, filter_drop_count, chain_winner, f2_failure_category, run_id),
    )
    await conn.commit()


async def get_youtube_coverage_counts(hours: int = 24) -> dict[str, int]:
    """C1: count video runs in the last `hours` by chain method, so chart-read
    coverage (gemini/v2) vs caption/whisper fallback is visible day to day."""
    conn = await get_db()
    cutoff = time.time() - hours * 3600
    cur = await conn.execute(
        """SELECT COALESCE(chain_winner, 'none') AS method, COUNT(*) AS n
           FROM youtube_analysis_runs
           WHERE started_at >= ?
           GROUP BY method""",
        (cutoff,),
    )
    return {r["method"]: r["n"] for r in await cur.fetchall()}


async def log_user_command(user_id: str, command: str) -> None:
    """Record a user command invocation for rate limiting."""
    conn = await get_db()
    await conn.execute(
        """INSERT INTO discord_command_user_rate (user_id, command, ts)
           VALUES (?, ?, ?)""",
        (user_id, command, time.time()),
    )
    await conn.commit()


async def check_user_rate_limit(
    user_id: str, command: str, limit: int, window_sec: int,
) -> bool:
    """Return True if user has exceeded limit invocations of command in window_sec."""
    conn = await get_db()
    cutoff = time.time() - window_sec
    cur = await conn.execute(
        """SELECT COUNT(*) AS cnt FROM discord_command_user_rate
           WHERE user_id = ? AND command = ? AND ts >= ?""",
        (user_id, command, cutoff),
    )
    row = await cur.fetchone()
    return (row["cnt"] if row else 0) >= limit



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


async def was_level_recently_alerted(ticker: str, price: float, cooldown_seconds: int = 86400) -> bool:
    """Return True if a level alert for this ticker/price was fired within cooldown window.

    Defaults: 24h cooldown, ±0.5% price band (matches youtube.level_alert_proximity_pct
    so the dedup window matches the trigger window). Empirically validated by the
    2026-04-24 signal audit, which observed 76% repeat alerts under the previous
    4h / ±1% configuration.
    """
    conn = await get_db()
    cutoff = time.time() - cooldown_seconds
    cursor = await conn.execute(
        """SELECT 1 FROM youtube_level_alerts
           WHERE ticker = ?
             AND ABS(price - ?) / NULLIF(?, 0) < 0.005
             AND alerted_at >= ?
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
    alert_id: int | None = None,
) -> int:
    """Record a decision snapshot. Returns the new row ID."""
    conn = await get_db()
    cursor = await conn.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, contradiction_index, sources_json,
            feature_vector_json, weights_json, recorded_at, outcome_price_at_alert,
            alert_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, decision, final_score, contradiction_index, sources_json,
         feature_vector_json, weights_json, time.time(), outcome_price_at_alert,
         alert_id),
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


async def get_snapshot_id_for_alert(alert_id: int) -> int | None:
    """Return the decision_snapshots.id for a given alert_history.id, or None."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT id FROM decision_snapshots WHERE alert_id = ? LIMIT 1",
        (alert_id,),
    )
    row = await cursor.fetchone()
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Shadow-prediction helpers (Milestone-0 Spec 03)
# ---------------------------------------------------------------------------

async def insert_shadow_prediction(
    alert_id: int,
    predicted_prob: float,
    horizon: str,
) -> int:
    """Record an unlabelled calibration prediction. `alert_id` references
    `alert_history.id` (Section 3a). Returns the new row ID."""
    conn = await get_db()
    cursor = await conn.execute(
        """INSERT INTO shadow_predictions
           (alert_id, predicted_prob, horizon, actual_hit, created_at)
           VALUES (?, ?, ?, NULL, ?)""",
        (alert_id, float(predicted_prob), horizon, int(time.time())),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_pending_shadow_predictions(horizon: str, limit: int = 500) -> list[dict]:
    """Return shadow_predictions rows where actual_hit IS NULL for one horizon.
    Joins through alert_history (the canonical FK target) for ticker context."""
    conn = await get_db()
    cursor = await conn.execute(
        """SELECT sp.id, sp.alert_id, sp.predicted_prob, sp.horizon, sp.created_at,
                  ah.ticker
           FROM shadow_predictions sp
           JOIN alert_history ah ON sp.alert_id = ah.id
           WHERE sp.actual_hit IS NULL AND sp.horizon = ?
           ORDER BY sp.created_at ASC
           LIMIT ?""",
        (horizon, limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def update_shadow_actual(prediction_id: int, actual_hit: int) -> None:
    """Label a shadow prediction with the realised 0/1 outcome."""
    conn = await get_db()
    await conn.execute(
        "UPDATE shadow_predictions SET actual_hit = ? WHERE id = ?",
        (int(actual_hit), prediction_id),
    )
    await conn.commit()


async def label_shadow_predictions_for_alert_id(
    alert_history_id: int,
    horizon: str,
    entry_price: float,
    exit_price: float,
) -> int:
    """Label unlabelled shadow_predictions rows for a SPECIFIC alert_history.id
    and horizon.  Returns the number of rows labelled (0 or 1 in normal operation).

    Codex review fix #2 + re-review fix: the WHERE clause keys on alert_id (=
    alert_history.id, the canonical FK target per Section 3a), NOT on ticker, so
    multiple alerts for the same ticker get labelled independently with the
    correct entry/exit pair for each."""
    if entry_price <= 0 or exit_price <= 0:
        return 0
    actual = 1 if exit_price > entry_price else 0
    conn = await get_db()
    cursor = await conn.execute(
        """UPDATE shadow_predictions
              SET actual_hit = ?
            WHERE actual_hit IS NULL
              AND alert_id = ?
              AND horizon = ?""",
        (actual, alert_history_id, horizon),
    )
    await conn.commit()
    return cursor.rowcount or 0


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


# ─────────────────────────── Wolf macro-brain (TODO #20) ───────────────────────────

async def get_active_thesis(scope_type: str, scope_key: str, direction: str) -> dict | None:
    """Return the single active Wolf thesis matching scope+direction, or None."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM macro_theses WHERE scope_type = ? AND scope_key = ? "
        "AND direction = ? AND status = 'active'",
        (scope_type, scope_key, direction),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def get_active_theses(scope_type: str | None = None) -> list[dict]:
    """Return all active Wolf theses, optionally filtered by scope_type."""
    conn = await get_db()
    if scope_type:
        cur = await conn.execute(
            "SELECT * FROM macro_theses WHERE status = 'active' AND scope_type = ? "
            "ORDER BY last_updated DESC",
            (scope_type,),
        )
    else:
        cur = await conn.execute(
            "SELECT * FROM macro_theses WHERE status = 'active' ORDER BY last_updated DESC"
        )
    return [dict(r) for r in await cur.fetchall()]


async def insert_thesis(
    scope_type: str,
    scope_key: str,
    direction: str,
    stage: str,
    key_levels_json: str,
    price_at_creation: float | None,
    has_levels: int,
    evidence_log_json: str,
    created_at: float,
    trade_setup_json: str | None = None,
) -> int:
    """Insert a new active Wolf thesis. Returns the new thesis id."""
    conn = await get_db()
    cur = await conn.execute(
        """INSERT INTO macro_theses
           (scope_type, scope_key, direction, stage, key_levels_json, price_at_creation,
            created_at, last_updated, status, has_levels, evidence_log_json, trade_setup_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)""",
        (scope_type, scope_key, direction, stage, key_levels_json, price_at_creation,
         created_at, created_at, has_levels, evidence_log_json, trade_setup_json),
    )
    await conn.commit()
    return cur.lastrowid


async def update_thesis(
    thesis_id: int,
    stage: str,
    key_levels_json: str,
    has_levels: int,
    evidence_log_json: str,
    last_updated: float,
    trade_setup_json: str | None = _KEEP,
) -> None:
    """Update an existing thesis's stage/levels/evidence.

    ``trade_setup_json`` left at ``_KEEP`` leaves the trade-idea column untouched;
    pass a value (a JSON string, or None to clear it) to overwrite it."""
    conn = await get_db()
    if trade_setup_json is _KEEP:
        await conn.execute(
            """UPDATE macro_theses SET stage = ?, key_levels_json = ?, has_levels = ?,
               evidence_log_json = ?, last_updated = ? WHERE id = ?""",
            (stage, key_levels_json, has_levels, evidence_log_json, last_updated, thesis_id),
        )
    else:
        await conn.execute(
            """UPDATE macro_theses SET stage = ?, key_levels_json = ?, has_levels = ?,
               evidence_log_json = ?, last_updated = ?, trade_setup_json = ? WHERE id = ?""",
            (stage, key_levels_json, has_levels, evidence_log_json, last_updated,
             trade_setup_json, thesis_id),
        )
    await conn.commit()


async def invalidate_thesis(thesis_id: int, when: float) -> None:
    """Mark a thesis invalidated (frees the active-unique slot for that scope+direction)."""
    conn = await get_db()
    await conn.execute(
        "UPDATE macro_theses SET status = 'invalidated', stage = 'invalidated', "
        "invalidated_at = ?, last_updated = ? WHERE id = ?",
        (when, when, thesis_id),
    )
    await conn.commit()


async def count_active_theses(scope_type: str) -> int:
    """Count active theses for a scope_type (sprawl-cap enforcement)."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM macro_theses WHERE status = 'active' AND scope_type = ?",
        (scope_type,),
    )
    row = await cur.fetchone()
    return row["cnt"] if row else 0


async def get_oldest_active_thesis(scope_type: str) -> dict | None:
    """Return the least-recently-updated active thesis of a scope_type (for sprawl eviction)."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM macro_theses WHERE status = 'active' AND scope_type = ? "
        "ORDER BY last_updated ASC LIMIT 1",
        (scope_type,),
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def wolf_email_seen(message_id: str) -> bool:
    """True if this Gmail message was already durably processed by the Wolf pipeline."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT 1 FROM wolf_emails_processed WHERE message_id = ?", (message_id,)
    )
    return await cur.fetchone() is not None


async def record_wolf_email(
    message_id: str,
    html_sha1: str,
    image_urls_sha1: str,
    parse_status: str,
    error: str | None,
    theses_touched: int,
    processed_at: float,
    received_at: float | None = None,
) -> None:
    """Record durable processing of a Wolf email (write BEFORE applying the Gmail label).

    `received_at` is the email's Gmail internalDate (epoch seconds) — the digest
    scheduler triggers off this, NOT processed_at. Defaults None for legacy callers.
    """
    conn = await get_db()
    await conn.execute(
        """INSERT OR IGNORE INTO wolf_emails_processed
           (message_id, html_sha1, image_urls_sha1, parse_status, error, theses_touched,
            processed_at, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (message_id, html_sha1, image_urls_sha1, parse_status, error, theses_touched,
         processed_at, received_at),
    )
    await conn.commit()


async def record_call_outcome(
    thesis_id: int,
    scope_type: str,
    scope_key: str,
    direction: str,
    proxy_symbol: str | None,
    anchor_stage: str | None,
    anchor_ts: float | None,
    anchor_close: float | None,
    latest_close: float | None,
    pct_move: float | None,
    band: float | None,
    state: str,
    computed_at: float,
) -> None:
    """UPSERT one Sunday-recap outcome row (one per thesis_id)."""
    conn = await get_db()
    await conn.execute(
        """INSERT INTO wolf_call_outcomes
           (thesis_id, scope_type, scope_key, direction, proxy_symbol, anchor_stage,
            anchor_ts, anchor_close, latest_close, pct_move, band, state, computed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(thesis_id) DO UPDATE SET
             scope_type=excluded.scope_type, scope_key=excluded.scope_key,
             direction=excluded.direction, proxy_symbol=excluded.proxy_symbol,
             anchor_stage=excluded.anchor_stage, anchor_ts=excluded.anchor_ts,
             anchor_close=excluded.anchor_close, latest_close=excluded.latest_close,
             pct_move=excluded.pct_move, band=excluded.band, state=excluded.state,
             computed_at=excluded.computed_at""",
        (thesis_id, scope_type, scope_key, direction, proxy_symbol, anchor_stage,
         anchor_ts, anchor_close, latest_close, pct_move, band, state, computed_at),
    )
    await conn.commit()


async def get_call_outcomes(since_epoch: float = 0.0) -> list[dict]:
    """Return outcome rows computed at/after `since_epoch`, newest first."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM wolf_call_outcomes WHERE computed_at >= ? ORDER BY computed_at DESC",
        (since_epoch,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def get_wolf_alert(dedupe_key: str) -> dict | None:
    """Return the wolf_news_alerts row for a dedupe_key, or None. Used for the
    persistent digest-already-fired check (survives restart)."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM wolf_news_alerts WHERE dedupe_key = ?", (dedupe_key,)
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def count_wolf_emails_received_between(
    lo: float, hi: float, min_received: float = 0.0
) -> int:
    """Count Wolf emails whose received_at (Gmail internalDate) falls in [lo, hi] and is
    >= min_received. Legacy rows (received_at NULL) and old backfill rows are excluded —
    so they can never trigger a 'fresh' digest. This is the digest scheduler's trigger."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM wolf_emails_processed "
        "WHERE received_at IS NOT NULL AND received_at >= ? AND received_at <= ? "
        "AND received_at >= ?",
        (lo, hi, min_received),
    )
    row = await cur.fetchone()
    return row["c"] if row else 0


async def get_invalidated_theses_since(since_epoch: float) -> list[dict]:
    """Return theses invalidated at/after `since_epoch` (for the Sunday recap, so a
    call Wolf abandoned this week is reported as 'invalidated', not silently dropped)."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM macro_theses WHERE status = 'invalidated' AND invalidated_at >= ? "
        "ORDER BY invalidated_at DESC",
        (since_epoch,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def create_pending_alert(
    dedupe_key: str, thesis_id: int, tier: str, payload_json: str, created_at: float
) -> int | None:
    """Create a 'pending' outbox row. Returns its id, or None if dedupe_key already exists."""
    conn = await get_db()
    cur = await conn.execute(
        """INSERT OR IGNORE INTO wolf_news_alerts
           (dedupe_key, thesis_id, tier, status, payload_json, created_at)
           VALUES (?, ?, ?, 'pending', ?, ?)""",
        (dedupe_key, thesis_id, tier, payload_json, created_at),
    )
    await conn.commit()
    if cur.rowcount == 0:
        return None  # already alerted for this dedupe_key
    return cur.lastrowid


async def mark_alert_posted(alert_id: int, discord_message_id: str | None, when: float) -> None:
    """Mark an outbox row posted (after a successful Discord send)."""
    conn = await get_db()
    await conn.execute(
        "UPDATE wolf_news_alerts SET status = 'posted', discord_message_id = ?, posted_at = ? "
        "WHERE id = ?",
        (discord_message_id, when, alert_id),
    )
    await conn.commit()


async def mark_alert_failed(alert_id: int) -> None:
    """Mark an outbox row failed (Discord send error); a later cycle may retry."""
    conn = await get_db()
    await conn.execute(
        "UPDATE wolf_news_alerts SET status = 'failed' WHERE id = ?", (alert_id,)
    )
    await conn.commit()


# ───────────── Phase-2 cross-source confluence (TODO #20, Type-2) ─────────────

async def get_confluence_stances(window_days: int = 21) -> dict[str, list[dict]]:
    """Gather recent directional stances from the four confluence sources, within the
    trailing window. Returns {source_type: [{'ticker','dir','channel'?}, ...]}.

    Reads ONLY (no writes). SEC is buys-only (sells are routine pay events). Excludes
    apewisdom/google_trends/reddit (not on the user's confluence source list).
    """
    conn = await get_db()
    cutoff = time.time() - window_days * 86400
    out: dict[str, list[dict]] = {"twitter": [], "youtube": [], "options": [], "sec": []}

    # Twitter — signal_events.direction (long/short); youtube path there is dead.
    cur = await conn.execute(
        "SELECT ticker, direction FROM signal_events "
        "WHERE source_type='twitter' AND direction IN ('long','short') AND recorded_at >= ?",
        (cutoff,),
    )
    out["twitter"] = [{"ticker": r["ticker"], "dir": r["direction"]} for r in await cur.fetchall()]

    # YouTube — youtube_signals.direction, dropping suppressed rows; keep channel for breadth.
    cur = await conn.execute(
        "SELECT ticker, direction, channel_name FROM youtube_signals "
        "WHERE direction IN ('long','short') AND COALESCE(suppressed,0)=0 AND extracted_at >= ?",
        (cutoff,),
    )
    out["youtube"] = [
        {"ticker": r["ticker"], "dir": r["direction"], "channel": r["channel_name"]}
        for r in await cur.fetchall()
    ]

    # Options flow — side CALL/PUT (freshest of last_trade_ts / detected_at).
    cur = await conn.execute(
        "SELECT ticker, side FROM options_flow "
        "WHERE COALESCE(last_trade_ts, detected_at) >= ?",
        (cutoff,),
    )
    out["options"] = [{"ticker": r["ticker"], "dir": r["side"]} for r in await cur.fetchall()]

    # SEC — insider BUYS only (sentiment='bullish'); sells excluded by design.
    cur = await conn.execute(
        "SELECT ticker, sentiment FROM ticker_signals "
        "WHERE source_type='sec_filing' AND sentiment='bullish' AND detected_at >= ?",
        (cutoff,),
    )
    out["sec"] = [{"ticker": r["ticker"], "dir": r["sentiment"]} for r in await cur.fetchall()]

    return out


async def get_confluence_check(thesis_id: int) -> dict | None:
    """Return the current confluence state row for a thesis, or None."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM wolf_confluence_checks WHERE thesis_id = ?", (thesis_id,)
    )
    row = await cur.fetchone()
    return dict(row) if row else None


async def record_confluence_check(
    thesis_id: int, scope_type: str, scope_key: str, direction: str,
    checked_at: float, window_days: int, agree_count: int, disagree_count: int,
    tier: str, combined_tier: str, divided: int,
    agree_sources_json: str, disagree_sources_json: str, alerted_tier: str,
) -> None:
    """Upsert the single current-state confluence row for a thesis (bounded: one per thesis)."""
    conn = await get_db()
    await conn.execute(
        """INSERT INTO wolf_confluence_checks
            (thesis_id, scope_type, scope_key, direction, checked_at, window_days,
             agree_count, disagree_count, tier, combined_tier, divided,
             agree_sources_json, disagree_sources_json, alerted_tier)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(thesis_id) DO UPDATE SET
             scope_type=excluded.scope_type, scope_key=excluded.scope_key,
             direction=excluded.direction, checked_at=excluded.checked_at,
             window_days=excluded.window_days, agree_count=excluded.agree_count,
             disagree_count=excluded.disagree_count, tier=excluded.tier,
             combined_tier=excluded.combined_tier, divided=excluded.divided,
             agree_sources_json=excluded.agree_sources_json,
             disagree_sources_json=excluded.disagree_sources_json,
             alerted_tier=excluded.alerted_tier""",
        (thesis_id, scope_type, scope_key, direction, checked_at, window_days,
         agree_count, disagree_count, tier, combined_tier, divided,
         agree_sources_json, disagree_sources_json, alerted_tier),
    )
    await conn.commit()


async def delete_confluence_check(thesis_id: int) -> None:
    """Prune a thesis's confluence row (call when the thesis is invalidated)."""
    conn = await get_db()
    await conn.execute("DELETE FROM wolf_confluence_checks WHERE thesis_id = ?", (thesis_id,))
    await conn.commit()


async def prune_confluence_orphans() -> int:
    """Delete confluence rows whose thesis is no longer active. Keeps the table bounded
    by the small set of live theses. Returns rows deleted."""
    conn = await get_db()
    cur = await conn.execute(
        "DELETE FROM wolf_confluence_checks WHERE thesis_id NOT IN "
        "(SELECT id FROM macro_theses WHERE status='active')"
    )
    await conn.commit()
    return cur.rowcount or 0


# ---------------------------------------------------------------- phase-4 #2 beneficiaries
async def get_beneficiaries(thesis_id: int) -> list[dict]:
    """Inferred beneficiary rows for a thesis, best (highest confidence) first."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT * FROM wolf_beneficiaries WHERE thesis_id=? ORDER BY confidence DESC",
        (thesis_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def replace_beneficiaries(thesis_id: int, rows: list[dict]) -> None:
    """Atomically replace a thesis's beneficiary rows (delete-then-insert in ONE
    transaction; rollback on error). Callers pass the FULL precomputed set — never a
    partial result — so a thesis's rows are never left half-written or staler-but-fresh.
    An empty `rows` just clears the thesis (the digest then omits the section)."""
    conn = await get_db()
    try:
        await conn.execute("DELETE FROM wolf_beneficiaries WHERE thesis_id=?", (thesis_id,))
        for r in rows:
            await conn.execute(
                """INSERT INTO wolf_beneficiaries
                    (thesis_id, ticker, side, scope_type, scope_key, direction,
                     score, confidence, tier, reason, signals_json, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (thesis_id, r["ticker"], r.get("side", "long"), r.get("scope_type"),
                 r.get("scope_key"), r.get("direction"), r.get("score"), r.get("confidence"),
                 r.get("tier"), r.get("reason"), r.get("signals_json"), r["computed_at"]),
            )
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise


async def prune_beneficiary_orphans() -> int:
    """Delete beneficiary rows whose thesis is no longer active. Returns rows deleted."""
    conn = await get_db()
    cur = await conn.execute(
        "DELETE FROM wolf_beneficiaries WHERE thesis_id NOT IN "
        "(SELECT id FROM macro_theses WHERE status='active')"
    )
    await conn.commit()
    return cur.rowcount or 0
