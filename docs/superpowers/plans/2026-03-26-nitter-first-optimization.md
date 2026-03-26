# Nitter-First Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 5-gate consensus model with a signal-first architecture where any analyst tweet triggers an instant Discord alert, with cross-references adding score multipliers asynchronously.

**Architecture:** Self-hosted Nitter polls 49 Twitter accounts via RSS every 60s. New tweets are parsed by an LLM for ticker/direction/options details. Actionable tweets fire an instant Discord ping, then an async cross-reference engine (news cascade + social + technical) posts a detail follow-up reply 1-2 minutes later.

**Tech Stack:** Python 3 asyncio, aiohttp, aiosqlite, Docker (Nitter + SearXNG), OpenRouter LLM API, Finnhub API, Discord Bot API, xml.etree.ElementTree for RSS

**Spec:** `docs/superpowers/specs/2026-03-26-nitter-first-optimization-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `docker-compose.yaml` | Nitter + SearXNG container definitions |
| `config/nitter.conf` | Nitter server configuration |
| `config/searxng/settings.yml` | SearXNG engine configuration |
| `consensus_engine/scanners/nitter.py` | RSS poller — fetches/deduplicates tweets from all 49 accounts |
| `consensus_engine/analysis/tweet_parser.py` | LLM intent extraction — classifies tweets, extracts tickers/options/direction |
| `consensus_engine/cross_reference.py` | Orchestrates all multiplier sources in parallel, computes final score |
| `consensus_engine/scanners/searxng.py` | SearXNG JSON API client |
| `tests/test_tweet_parser.py` | Tests for tweet parsing and classification |
| `tests/test_nitter.py` | Tests for RSS parsing and deduplication |
| `tests/test_cross_reference.py` | Tests for scoring logic |
| `tests/test_news_cascade.py` | Tests for news cascade ordering and catalyst detection |
| `tests/test_discord_alerts.py` | Tests for two-phase alert formatting |
| `tests/test_ticker_validation.py` | Tests for expanded blacklist + market-cap filter |

### Modified Files
| File | Changes |
|------|---------|
| `consensus_engine/models.py` | Add `ParsedTweet`, `OptionsDetail`, `CrossReferenceResult`, `ScoreBreakdown`, `AlertMessage` dataclasses |
| `consensus_engine/db.py` | Add `seen_tweets`, `alert_messages`, `ticker_metadata` tables + query helpers |
| `consensus_engine/main.py` | Replace 5-gate loops with Nitter poller → parser → alert → cross-ref pipeline |
| `consensus_engine/scanners/news.py` | Rewrite to 4-tier cascade (Finnhub → Google RSS → Brave → SearXNG) |
| `consensus_engine/scanners/social.py` | Remove hard-gate `evaluate_social_consensus()`, keep scan functions for scoring |
| `consensus_engine/alerts/discord.py` | Two-phase alerts: instant ping + detail follow-up reply |
| `consensus_engine/analysis/llm_scorer.py` | Update prompt to accept new data shapes from cross-reference |
| `consensus_engine/utils/tickers.py` | Expand blacklist + add market-cap validation |
| `consensus_engine/utils/rate_limiter.py` | Add rate entries for `finnhub_news`, `google_news_rss`, `searxng`, `nitter` |
| `config/consensus.yaml` | Add nitter, searxng, scoring, news cascade config sections; remove apify section |

### Removed Files
| File | Reason |
|------|--------|
| `consensus_engine/scanners/twitter.py` | Replaced by `scanners/nitter.py` |
| `consensus_engine/consensus.py` | 5-gate model replaced by signal-first scoring |
| `consensus_engine/utils/apify_client.py` | No longer needed |

---

## Work Streams

Tasks are organized into 7 parallel work streams. Streams 1-6 are independent and can be assigned to separate teammates. Stream 7 (integration) depends on all others completing first.

| Stream | Tasks | Can Parallelize With |
|--------|-------|---------------------|
| **A: Foundation** (models, db, config) | 1-3 | None — do first, all others depend on this |
| **B: Docker Infrastructure** | 4 | Everything after A |
| **C: Nitter RSS Poller** | 5 | Everything after A |
| **D: Tweet Parser** | 6 | Everything after A |
| **E: News Cascade** | 7-8 | Everything after A |
| **F: Discord Alerts** | 9 | Everything after A |
| **G: Cross-Reference + Ticker Fix** | 10-11 | Everything after A |
| **H: Integration** | 12-13 | After all above |

---

## Stream A: Foundation

### Task 1: Add New Data Models

**Files:**
- Modify: `consensus_engine/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write tests for new models**

Create `tests/test_models.py`:

```python
"""Tests for new data models."""
import time
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, CrossReferenceResult,
    ScoreBreakdown, AlertMessage, TweetType, Conviction, Direction,
)


def test_parsed_tweet_actionable_type_a():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/123",
        analyst="unusual_whales",
        raw_text="$NVDA looking strong, going long",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.MEDIUM,
        summary="Going long NVDA",
    )
    assert tweet.is_actionable is True
    assert tweet.base_score == 25


def test_parsed_tweet_actionable_type_c():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/456",
        analyst="OptionMillionaire",
        raw_text="Buying TSLA 500c Friday",
        tweet_type=TweetType.OPTIONS_TRADE,
        tickers=["TSLA"],
        direction=Direction.LONG,
        options=OptionsDetail(
            present=True,
            strike=500.0,
            expiry="2026-03-28",
            option_type="call",
            target_price=510.0,
            profit_target_pct=100.0,
        ),
        conviction=Conviction.HIGH,
        summary="Buying TSLA 500c Friday expiry targeting 510",
    )
    assert tweet.is_actionable is True
    assert tweet.base_score == 30
    assert tweet.options.strike == 500.0


def test_parsed_tweet_not_actionable_type_b():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/789",
        analyst="NickTimiraos",
        raw_text="Fed signaling rate pause at next meeting",
        tweet_type=TweetType.MACRO,
        tickers=[],
        direction=Direction.NEUTRAL,
        options=None,
        conviction=Conviction.LOW,
        summary="Fed rate pause signal",
    )
    assert tweet.is_actionable is False


def test_parsed_tweet_not_actionable_type_d():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/status/101",
        analyst="Walter_Bloomberg",
        raw_text="Market looking weak into close",
        tweet_type=TweetType.SENTIMENT,
        tickers=[],
        direction=Direction.NEUTRAL,
        options=None,
        conviction=Conviction.LOW,
        summary="Bearish market sentiment",
    )
    assert tweet.is_actionable is False


def test_score_breakdown_total():
    breakdown = ScoreBreakdown(
        base=30,
        additional_analysts=40,
        news_catalyst=15,
        sec_filing=0,
        social_apewisdom=10,
        social_stocktwits=0,
        social_reddit=0,
        google_trends=0,
        technical=10,
        llm_boost=12,
    )
    assert breakdown.total == 117


def test_cross_reference_result():
    breakdown = ScoreBreakdown(base=25)
    result = CrossReferenceResult(
        ticker="NVDA",
        breakdown=breakdown,
        catalyst_summary="",
        catalyst_type="",
        catalyst_sources=[],
        catalyst_urls=[],
        technical=None,
        other_analysts=[],
        social_summary="",
        llm_reasoning="",
    )
    assert result.final_score == 25


def test_alert_message():
    msg = AlertMessage(
        ticker="TSLA",
        analyst="OptionMillionaire",
        instant_msg_id="123456",
        followup_msg_id=None,
        base_score=30,
        final_score=30,
    )
    assert msg.followup_msg_id is None
    assert msg.final_score == 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_models.py -v`
Expected: FAIL with ImportError (new classes don't exist yet)

- [ ] **Step 3: Add new enums and dataclasses to models.py**

Add these to the end of `consensus_engine/models.py` (keep all existing classes):

```python
class TweetType(str, Enum):
    TICKER_CALLOUT = "A"   # Explicit ticker + direction
    MACRO = "B"            # Macro/geopolitical
    OPTIONS_TRADE = "C"    # Options with strike/expiry
    SENTIMENT = "D"        # General market mood


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class Conviction(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


_CONVICTION_SCORES = {
    Conviction.HIGH: 30,
    Conviction.MEDIUM: 25,
    Conviction.LOW: 20,
}


@dataclass
class OptionsDetail:
    """Options trade details extracted from a tweet."""
    present: bool = False
    strike: Optional[float] = None
    expiry: Optional[str] = None
    option_type: Optional[str] = None  # "call" or "put"
    target_price: Optional[float] = None
    profit_target_pct: Optional[float] = None


@dataclass
class ParsedTweet:
    """LLM-parsed tweet with extracted trade details."""
    tweet_url: str
    analyst: str
    raw_text: str
    tweet_type: TweetType
    tickers: list[str]
    direction: Direction
    options: Optional[OptionsDetail]
    conviction: Conviction
    summary: str
    parsed_at: float = field(default_factory=time.time)

    @property
    def is_actionable(self) -> bool:
        return self.tweet_type in (TweetType.TICKER_CALLOUT, TweetType.OPTIONS_TRADE)

    @property
    def base_score(self) -> int:
        return _CONVICTION_SCORES.get(self.conviction, 25)


@dataclass
class ScoreBreakdown:
    """Additive score from all cross-reference sources."""
    base: int = 0
    additional_analysts: int = 0
    news_catalyst: int = 0
    sec_filing: int = 0
    social_apewisdom: int = 0
    social_stocktwits: int = 0
    social_reddit: int = 0
    google_trends: int = 0
    technical: int = 0
    llm_boost: int = 0

    @property
    def total(self) -> int:
        return (self.base + self.additional_analysts + self.news_catalyst
                + self.sec_filing + self.social_apewisdom + self.social_stocktwits
                + self.social_reddit + self.google_trends + self.technical
                + self.llm_boost)


@dataclass
class CrossReferenceResult:
    """Aggregated cross-reference data for detail follow-up."""
    ticker: str
    breakdown: ScoreBreakdown
    catalyst_summary: str
    catalyst_type: str
    catalyst_sources: list[str] = field(default_factory=list)
    catalyst_urls: list[str] = field(default_factory=list)
    technical: Optional[TechnicalResult] = None
    other_analysts: list[str] = field(default_factory=list)
    social_summary: str = ""
    llm_reasoning: str = ""

    @property
    def final_score(self) -> int:
        return self.breakdown.total


@dataclass
class AlertMessage:
    """Tracks Discord message IDs for two-phase alerts."""
    ticker: str
    analyst: str
    instant_msg_id: Optional[str] = None
    followup_msg_id: Optional[str] = None
    base_score: int = 0
    final_score: int = 0
    created_at: float = field(default_factory=time.time)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_models.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/models.py tests/test_models.py
git commit -m "feat: add new data models for signal-first architecture

Add ParsedTweet, OptionsDetail, CrossReferenceResult, ScoreBreakdown,
AlertMessage dataclasses plus TweetType, Direction, Conviction enums."
```

---

### Task 2: Extend Database Schema and Helpers

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write tests for new DB operations**

Create `tests/test_db.py`:

```python
"""Tests for new database tables and queries."""
import asyncio
import time
import pytest
from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    """Load config before each test."""
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = str(tmp_path / "test.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


@pytest.mark.asyncio
async def test_seen_tweet_insert_and_check(test_db):
    url = "https://x.com/unusual_whales/status/123456"
    is_new = await db.is_new_tweet(url)
    assert is_new is True

    await db.mark_tweet_seen(url, "unusual_whales")

    is_new = await db.is_new_tweet(url)
    assert is_new is False


@pytest.mark.asyncio
async def test_seen_tweet_duplicate(test_db):
    url = "https://x.com/user/status/789"
    await db.mark_tweet_seen(url, "user")
    await db.mark_tweet_seen(url, "user")  # Should not raise
    is_new = await db.is_new_tweet(url)
    assert is_new is False


@pytest.mark.asyncio
async def test_alert_message_insert_and_get(test_db):
    msg_id = await db.insert_alert_message(
        ticker="TSLA",
        analyst="OptionMillionaire",
        instant_msg_id="discord_msg_111",
        base_score=30,
    )
    assert msg_id is not None

    row = await db.get_alert_message(msg_id)
    assert row["ticker"] == "TSLA"
    assert row["instant_msg_id"] == "discord_msg_111"
    assert row["followup_msg_id"] is None


@pytest.mark.asyncio
async def test_alert_message_update_followup(test_db):
    msg_id = await db.insert_alert_message(
        ticker="NVDA", analyst="CheddarFlow",
        instant_msg_id="discord_msg_222", base_score=25,
    )
    await db.update_alert_message_followup(msg_id, "discord_msg_333", final_score=87)

    row = await db.get_alert_message(msg_id)
    assert row["followup_msg_id"] == "discord_msg_333"
    assert row["final_score"] == 87


@pytest.mark.asyncio
async def test_ticker_metadata_cache(test_db):
    await db.cache_ticker_metadata("NVDA", "NVIDIA Corp", 2.8e12, "NASDAQ")

    meta = await db.get_ticker_metadata("NVDA")
    assert meta is not None
    assert meta["name"] == "NVIDIA Corp"
    assert meta["market_cap"] == 2.8e12

    # Unknown ticker returns None
    meta = await db.get_ticker_metadata("ZZZZ")
    assert meta is None


@pytest.mark.asyncio
async def test_ticker_metadata_stale(test_db):
    await db.cache_ticker_metadata("OLD", "Old Corp", 1e9, "NYSE")

    # Manually backdate last_checked
    conn = await db.get_db()
    stale_time = time.time() - (8 * 86400)  # 8 days ago
    await conn.execute(
        "UPDATE ticker_metadata SET last_checked = ? WHERE ticker = ?",
        (stale_time, "OLD"),
    )
    await conn.commit()

    meta = await db.get_ticker_metadata("OLD", max_age_days=7)
    assert meta is None  # Stale, should return None


@pytest.mark.asyncio
async def test_get_recent_analysts_for_ticker(test_db):
    from consensus_engine.models import TickerSignal, SourceType, Sentiment
    # Insert some twitter signals
    signals = [
        TickerSignal(ticker="TSLA", source_type=SourceType.TWITTER,
                     source_detail="analyst1", raw_text="long TSLA"),
        TickerSignal(ticker="TSLA", source_type=SourceType.TWITTER,
                     source_detail="analyst2", raw_text="buying TSLA"),
        TickerSignal(ticker="TSLA", source_type=SourceType.TWITTER,
                     source_detail="analyst1", raw_text="still long TSLA"),  # duplicate
    ]
    await db.insert_signals(signals)

    analysts = await db.get_recent_analysts_for_ticker("TSLA", window_seconds=3600)
    assert set(analysts) == {"analyst1", "analyst2"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_db.py -v`
Expected: FAIL with AttributeError (new functions don't exist yet)

- [ ] **Step 3: Add new tables to SCHEMA in db.py**

Append to the `SCHEMA` string in `consensus_engine/db.py`, after the `pipeline_metrics` table:

```python
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
```

- [ ] **Step 4: Add new query helpers to db.py**

Add these functions to the end of `consensus_engine/db.py`:

```python
async def is_new_tweet(tweet_url: str) -> bool:
    """Check if we've already seen this tweet."""
    conn = await get_db()
    cursor = await conn.execute(
        "SELECT 1 FROM seen_tweets WHERE tweet_url = ?", (tweet_url,)
    )
    row = await cursor.fetchone()
    return row is None


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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_db.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/db.py tests/test_db.py
git commit -m "feat: add seen_tweets, alert_messages, ticker_metadata tables

New DB helpers for tweet deduplication, two-phase alert tracking,
and ticker metadata caching."
```

---

### Task 3: Update Configuration

**Files:**
- Modify: `config/consensus.yaml`
- Modify: `consensus_engine/utils/rate_limiter.py`

- [ ] **Step 1: Update consensus.yaml**

Replace the full `config/consensus.yaml` with the new configuration. Key changes:
- Remove `apify` section entirely
- Add `nitter` section
- Add `searxng` section
- Add `scoring` section with point values
- Add `news_cascade` section
- Change `consensus` section to signal-first model
- Keep all existing sections that are still used (api_keys, social, news, technical, llm, alerts, browser, logging, database)

```yaml
# =============================================================================
# Stock Trend Consensus Engine — Configuration
# =============================================================================
# Signal-first architecture: analyst tweets trigger instant alerts.
# Cross-references add score multipliers but never block alerts.
# =============================================================================

api_keys:
  brave_search: "$BRAVE_SEARCH_API_KEY"
  finnhub: "$FINNHUB_API_KEY"
  openrouter: "$OPENROUTER_API_KEY"
  discord_bot_token: "$DISCORD_BOT_TOKEN"
  discord_channel_id: "$DISCORD_CHANNEL_ID"
  twitter_auth_token: "$TWITTER_AUTH_TOKEN"
  twitter_ct0: "$TWITTER_CT0"
  twitter_cookie_string: "$TWITTER_COOKIE_STRING"

# Self-hosted Nitter (Docker)
nitter:
  base_url: "http://localhost:8585"
  accounts_file: "/root/.openclaw/sources.json"
  poll_interval_market_hours: 60    # seconds (9:00-16:30 ET)
  poll_interval_off_hours: 180      # seconds (outside market hours)
  market_open_hour: 9               # ET
  market_close_hour: 16             # ET (16:30 but we use 16 for simplicity)
  health_check_interval: 300        # seconds

# Self-hosted SearXNG (Docker)
searxng:
  base_url: "http://localhost:8888"
  timeout: 10

# Scoring Model
scoring:
  conviction:
    high: 30
    medium: 25
    low: 20
  multipliers:
    additional_analyst: 20
    news_catalyst: 15
    sec_filing: 15
    social_apewisdom: 10
    social_stocktwits: 10
    social_reddit: 10
    google_trends: 5
    technical_per_filter: 2
    technical_max: 12
    llm_boost_max: 15

# News Cascade (tried in order, stops when catalyst found)
news_cascade:
  tiers:
    - finnhub       # Tier 1: Finnhub /company-news (already have key)
    - google_rss    # Tier 2: Google News RSS (free, no auth)
    - brave         # Tier 3: Brave Search (quota-limited)
    - searxng       # Tier 4: SearXNG self-hosted (fallback)
  finnhub_news_days_back: 2
  brave_daily_budget: 50

# Polling intervals (seconds)
intervals:
  nitter_poll: 60           # Overridden by market hours config
  social_scan: 300
  cross_reference_timeout: 120
  state_prune: 900

# Stage 2: Social & Sentiment Scanner (used for cross-reference scoring)
social:
  subreddits:
    - wallstreetbets
    - stocks
    - investing
    - options
    - pennystocks
  stocktwits_enabled: true
  apewisdom_enabled: true
  google_trends_enabled: true

# Stage 3: News & Catalyst Finder
news:
  trusted_sources:
    - reuters
    - cnbc
    - bloomberg
    - wsj
    - marketwatch
    - finance.yahoo
    - sec.gov
    - fda.gov
    - prnewswire
    - business-wire
    - seekingalpha
    - benzinga
    - barrons
    - investors.com
    - ft.com
  max_article_age_hours: 24
  max_search_results: 10

# Stage 4: Technical Verification (used for cross-reference scoring)
technical:
  filters:
    rvol_threshold: 2.0
    rvol_lookback_days: 20
    vwap_enabled: true
    rsi_period: 14
    rsi_lower: 40
    rsi_upper: 75
    ema_fast: 9
    ema_slow: 21
    price_change_min_pct: 1.0
    atr_period: 14
    atr_multiplier: 1.5

# LLM Configuration (OpenRouter)
llm:
  model: "openrouter/minimax/minimax-m2.5"
  min_confidence: 70
  max_tokens: 1024

# Ticker validation
ticker_validation:
  min_market_cap: 100000000   # $100M floor
  cache_ttl_days: 7

# Alert Configuration
alerts:
  cooldown_hours: 6
  max_alerts_per_hour: 10
  embed_color_long: 0x00FF00
  embed_color_short: 0xFF0000
  embed_color_neutral: 0xFFAA00

# Browser Stealth Configuration (still used for StockTwits)
browser:
  headless: true
  user_agents:
    - "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    - "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    - "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
  min_delay_seconds: 2
  max_delay_seconds: 8
  page_timeout_seconds: 30
  proxy: null

# Logging
logging:
  level: "INFO"
  format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
  file: "/root/.openclaw/workspace/consensus_engine.log"

# Database
database:
  path: "/root/.openclaw/workspace/consensus.db"
  signal_ttl_hours: 2
  alert_history_days: 90
```

- [ ] **Step 2: Add new rate limiter entries**

Add these entries to `_min_intervals` in `consensus_engine/utils/rate_limiter.py`:

```python
"nitter": 0.1,          # Nitter RSS is local, very fast
"finnhub_news": 1.0,    # 60/min on free tier
"google_news_rss": 0.5, # No rate limit, but be polite
"searxng": 0.5,         # Local, but don't hammer it
```

- [ ] **Step 3: Commit**

```bash
cd /root/.openclaw/workspace
git add config/consensus.yaml consensus_engine/utils/rate_limiter.py
git commit -m "feat: update config for signal-first architecture

Remove apify section, add nitter, searxng, scoring, news_cascade
config. Add rate limiter entries for new sources."
```

---

## Stream B: Docker Infrastructure

### Task 4: Set Up Nitter and SearXNG Docker Containers

**Files:**
- Create: `docker-compose.yaml`
- Create: `config/nitter.conf`
- Create: `config/searxng/settings.yml`

- [ ] **Step 1: Create docker-compose.yaml**

Create `docker-compose.yaml` in the workspace root:

```yaml
version: "3.8"

services:
  nitter:
    image: zedeus/nitter:latest
    container_name: openclaw-nitter
    restart: unless-stopped
    ports:
      - "127.0.0.1:8585:8080"
    volumes:
      - ./config/nitter.conf:/src/nitter.conf:ro
    environment:
      - NITTER_ACCOUNTS_FILE=/src/nitter.conf
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8080"]
      interval: 30s
      timeout: 5s
      retries: 3

  searxng:
    image: searxng/searxng:latest
    container_name: openclaw-searxng
    restart: unless-stopped
    ports:
      - "127.0.0.1:8888:8080"
    volumes:
      - ./config/searxng:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8888
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
```

- [ ] **Step 2: Create Nitter config**

Create `config/nitter.conf`:

```ini
[Server]
hostname = "0.0.0.0"
port = 8080
https = false
httpMaxConnections = 100
staticDir = "./public"
title = "openclaw-nitter"
hostname = "localhost"

[Cache]
listMinutes = 1
rssMinutes = 1
redisHost = ""
redisPort = 6379

[Config]
hmacKey = "openclaw_nitter_key_change_me"
base64Media = false
enableRSS = true
enableDebug = false
proxy = ""
proxyAuth = ""
tokenCount = 10

[Preferences]
replaceTwitter = ""
replaceYouTube = ""
replaceReddit = ""
```

Note: The actual Nitter fork chosen at deploy time may require different config fields. The teammate deploying this should check the fork's documentation and adjust. The key requirements are: RSS enabled, listening on port 8080, minimal cache time (1 min).

- [ ] **Step 3: Create SearXNG settings**

Create `config/searxng/settings.yml`:

```yaml
use_default_settings: true

general:
  instance_name: "openclaw-searxng"
  debug: false

search:
  safe_search: 0
  default_lang: "en"
  formats:
    - html
    - json

server:
  secret_key: "openclaw_searxng_change_me"
  bind_address: "0.0.0.0"
  port: 8080

engines:
  - name: google
    engine: google
    shortcut: g
    disabled: false
  - name: bing
    engine: bing
    shortcut: b
    disabled: false
  - name: duckduckgo
    engine: duckduckgo
    shortcut: ddg
    disabled: false
  # Disable everything else to keep results focused
  - name: wikipedia
    disabled: true
  - name: wikidata
    disabled: true
```

- [ ] **Step 4: Test containers start**

```bash
cd /root/.openclaw/workspace
docker compose up -d
sleep 10
# Verify Nitter
curl -s -o /dev/null -w "%{http_code}" http://localhost:8585
# Verify SearXNG
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/healthz
# Verify SearXNG JSON API
curl -s "http://localhost:8888/search?q=test&format=json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Results: {len(d.get(\"results\",[]))}')"
```

Expected: HTTP 200 for both health checks, SearXNG returns results.

If Nitter requires auth tokens, the teammate should check the fork's docs for how to configure Twitter auth. Some forks read from environment variables, others from the config file.

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add docker-compose.yaml config/nitter.conf config/searxng/settings.yml
git commit -m "feat: add Docker infrastructure for Nitter + SearXNG

Self-hosted Nitter on localhost:8585 for Twitter RSS feeds.
Self-hosted SearXNG on localhost:8888 as tier-4 news search."
```

---

## Stream C: Nitter RSS Poller

### Task 5: Build Nitter RSS Poller

**Files:**
- Create: `consensus_engine/scanners/nitter.py`
- Test: `tests/test_nitter.py`

- [ ] **Step 1: Write tests for RSS parsing and deduplication**

Create `tests/test_nitter.py`:

```python
"""Tests for Nitter RSS poller."""
import time
import pytest
from unittest.mock import AsyncMock, patch
from consensus_engine.scanners.nitter import parse_rss_feed, NitterPoller


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>@unusual_whales / Twitter</title>
    <item>
      <title>$NVDA unusual call activity detected. Large block at 950 strike.</title>
      <link>https://x.com/unusual_whales/status/111111</link>
      <pubDate>Wed, 26 Mar 2026 14:30:00 GMT</pubDate>
      <description>$NVDA unusual call activity detected. Large block at 950 strike.</description>
    </item>
    <item>
      <title>Market looking choppy today, be careful out there</title>
      <link>https://x.com/unusual_whales/status/222222</link>
      <pubDate>Wed, 26 Mar 2026 14:00:00 GMT</pubDate>
      <description>Market looking choppy today, be careful out there</description>
    </item>
  </channel>
</rss>"""

EMPTY_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>@nobody</title></channel></rss>"""

MALFORMED_RSS = """<not valid xml at all"""


def test_parse_rss_feed_extracts_items():
    items = parse_rss_feed(SAMPLE_RSS, "unusual_whales")
    assert len(items) == 2
    assert items[0]["url"] == "https://x.com/unusual_whales/status/111111"
    assert items[0]["analyst"] == "unusual_whales"
    assert "$NVDA" in items[0]["text"]


def test_parse_rss_feed_empty():
    items = parse_rss_feed(EMPTY_RSS, "nobody")
    assert items == []


def test_parse_rss_feed_malformed():
    items = parse_rss_feed(MALFORMED_RSS, "broken")
    assert items == []


def test_parse_rss_feed_timestamp():
    items = parse_rss_feed(SAMPLE_RSS, "unusual_whales")
    # pubDate should be parsed to a float timestamp
    assert isinstance(items[0]["timestamp"], float)
    assert items[0]["timestamp"] > 0


@pytest.mark.asyncio
async def test_poller_deduplication(tmp_path):
    """Poller should skip tweets it has already seen."""
    from consensus_engine import db, config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db"), "signal_ttl_hours": 2}
    await db.init_db()

    await db.mark_tweet_seen("https://x.com/unusual_whales/status/111111", "unusual_whales")

    poller = NitterPoller()
    items = parse_rss_feed(SAMPLE_RSS, "unusual_whales")

    new_items = []
    for item in items:
        if await db.is_new_tweet(item["url"]):
            new_items.append(item)

    # Only the second item should be new (first was already seen)
    assert len(new_items) == 1
    assert "222222" in new_items[0]["url"]

    await db.close_db()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_nitter.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement nitter.py**

Create `consensus_engine/scanners/nitter.py`:

```python
"""Nitter RSS Poller — fetches tweets from self-hosted Nitter via RSS.

Polls all 49 configured analyst accounts concurrently every 60-90 seconds.
Deduplicates by tweet URL. New tweets are returned for parsing.
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.scanner.nitter")


def parse_rss_feed(xml_text: str, analyst: str) -> list[dict]:
    """Parse a Nitter RSS feed XML string into tweet dicts.

    Returns list of {"url": str, "text": str, "analyst": str, "timestamp": float}.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        log.warning("Failed to parse RSS for @%s", analyst)
        return []

    items = []
    for item in root.iter("item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext("description", "")
        pub_date = item.findtext("pubDate", "")

        text = description or title
        if not text or not link:
            continue

        timestamp = time.time()
        if pub_date:
            try:
                dt = parsedate_to_datetime(pub_date)
                timestamp = dt.timestamp()
            except (ValueError, TypeError):
                pass

        items.append({
            "url": link,
            "text": text,
            "analyst": analyst,
            "timestamp": timestamp,
        })

    return items


def _is_market_hours() -> bool:
    """Check if current time is within US market hours (ET)."""
    from datetime import timezone, timedelta
    et = timezone(timedelta(hours=-5))
    now_et = datetime.now(et)
    open_hour = cfg.get("nitter.market_open_hour", 9)
    close_hour = cfg.get("nitter.market_close_hour", 16)
    # Weekday check: 0=Monday, 4=Friday
    if now_et.weekday() > 4:
        return False
    return open_hour <= now_et.hour < close_hour


class NitterPoller:
    """Polls Nitter RSS feeds for all configured accounts."""

    def __init__(self):
        self._base_url = cfg.get("nitter.base_url", "http://localhost:8585")
        self._accounts = cfg.get_twitter_accounts()

    async def health_check(self) -> bool:
        """Check if Nitter is reachable."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._base_url,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            log.error("Nitter health check failed: %s", e)
            return False

    async def _fetch_rss(self, session: aiohttp.ClientSession, handle: str) -> str:
        """Fetch RSS feed for a single account."""
        url = f"{self._base_url}/{handle}/rss"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    log.debug("Nitter RSS %d for @%s", resp.status, handle)
                    return ""
                return await resp.text()
        except Exception as e:
            log.debug("Nitter RSS error for @%s: %s", handle, e)
            return ""

    async def poll_all(self) -> list[dict]:
        """Poll all accounts concurrently. Returns only new (unseen) tweets."""
        if not self._accounts:
            log.warning("No Twitter accounts configured")
            return []

        start = time.time()
        new_tweets = []

        async with aiohttp.ClientSession() as session:
            # Fetch all RSS feeds concurrently
            tasks = [self._fetch_rss(session, handle) for handle in self._accounts]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for handle, result in zip(self._accounts, results):
                if isinstance(result, Exception):
                    log.debug("RSS fetch error for @%s: %s", handle, result)
                    continue
                if not result:
                    continue

                items = parse_rss_feed(result, handle)
                for item in items:
                    if await db.is_new_tweet(item["url"]):
                        await db.mark_tweet_seen(item["url"], handle)
                        new_tweets.append(item)

        elapsed = time.time() - start
        if new_tweets:
            log.info("Nitter poll: %d new tweets from %d accounts in %.1fs",
                     len(new_tweets), len(self._accounts), elapsed)
        else:
            log.debug("Nitter poll: no new tweets (%.1fs)", elapsed)

        await db.record_metric("nitter_poll_seconds", elapsed)
        return new_tweets

    def get_poll_interval(self) -> int:
        """Return poll interval based on market hours."""
        if _is_market_hours():
            return cfg.get("nitter.poll_interval_market_hours", 60)
        return cfg.get("nitter.poll_interval_off_hours", 180)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_nitter.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/scanners/nitter.py tests/test_nitter.py
git commit -m "feat: add Nitter RSS poller for Twitter monitoring

Polls self-hosted Nitter RSS feeds for all 49 analyst accounts.
Concurrent fetching, tweet deduplication, market-hours awareness."
```

---

## Stream D: Tweet Parser

### Task 6: Build LLM Tweet Parser

**Files:**
- Create: `consensus_engine/analysis/tweet_parser.py`
- Test: `tests/test_tweet_parser.py`

- [ ] **Step 1: Write tests for tweet parsing**

Create `tests/test_tweet_parser.py`:

```python
"""Tests for LLM tweet parser."""
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from consensus_engine.models import TweetType, Direction, Conviction
from consensus_engine.analysis.tweet_parser import parse_tweet, _build_parser_prompt, _parse_llm_response


def test_build_parser_prompt():
    prompt = _build_parser_prompt("unusual_whales", "$NVDA unusual call activity 950 strike")
    assert "unusual_whales" in prompt
    assert "$NVDA" in prompt
    assert "950" in prompt


def test_parse_llm_response_type_a():
    raw = json.dumps({
        "type": "A",
        "tickers": ["NVDA"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "medium",
        "summary": "Going long NVDA on unusual activity"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/123", "user", "original text")
    assert tweet.tweet_type == TweetType.TICKER_CALLOUT
    assert tweet.tickers == ["NVDA"]
    assert tweet.direction == Direction.LONG
    assert tweet.conviction == Conviction.MEDIUM
    assert tweet.is_actionable is True


def test_parse_llm_response_type_c_options():
    raw = json.dumps({
        "type": "C",
        "tickers": ["TSLA"],
        "direction": "long",
        "options": {
            "present": True,
            "strike": 500,
            "expiry": "2026-03-28",
            "type": "call",
            "target_price": 510,
            "profit_target_pct": 100
        },
        "conviction": "high",
        "summary": "Buying TSLA 500c Friday expiry, targeting 510"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/456", "OptionMillionaire", "original")
    assert tweet.tweet_type == TweetType.OPTIONS_TRADE
    assert tweet.options is not None
    assert tweet.options.strike == 500.0
    assert tweet.options.option_type == "call"
    assert tweet.options.target_price == 510.0
    assert tweet.is_actionable is True
    assert tweet.base_score == 30


def test_parse_llm_response_type_b():
    raw = json.dumps({
        "type": "B",
        "tickers": ["USO"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "medium",
        "summary": "Strait of Hormuz tensions bullish for oil"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/789", "analyst", "text")
    assert tweet.tweet_type == TweetType.MACRO
    assert tweet.is_actionable is False


def test_parse_llm_response_type_d():
    raw = json.dumps({
        "type": "D",
        "tickers": [],
        "direction": "neutral",
        "options": {"present": False},
        "conviction": "low",
        "summary": "Market looking weak"
    })
    tweet = _parse_llm_response(raw, "https://x.com/user/101", "analyst", "text")
    assert tweet.tweet_type == TweetType.SENTIMENT
    assert tweet.is_actionable is False


def test_parse_llm_response_malformed_json():
    """Malformed JSON should fall back to regex extraction."""
    tweet = _parse_llm_response(
        "not valid json at all",
        "https://x.com/user/999", "analyst",
        "$AAPL looking strong, buying calls"
    )
    # Fallback: Type A, medium conviction, tickers from regex
    assert tweet.tweet_type == TweetType.TICKER_CALLOUT
    assert tweet.conviction == Conviction.MEDIUM
    assert "AAPL" in tweet.tickers


def test_parse_llm_response_markdown_wrapped():
    """Handle LLM responses wrapped in ```json ... ```."""
    raw = '```json\n{"type":"A","tickers":["AMD"],"direction":"long","options":{"present":false},"conviction":"high","summary":"AMD breakout"}\n```'
    tweet = _parse_llm_response(raw, "https://x.com/user/555", "analyst", "AMD breakout")
    assert tweet.tweet_type == TweetType.TICKER_CALLOUT
    assert tweet.tickers == ["AMD"]


@pytest.mark.asyncio
async def test_parse_tweet_llm_call():
    """Test full parse_tweet with mocked LLM."""
    mock_response = json.dumps({
        "type": "A",
        "tickers": ["NVDA"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "high",
        "summary": "NVDA breakout"
    })

    with patch("consensus_engine.analysis.tweet_parser._call_openrouter",
               new_callable=AsyncMock, return_value=mock_response):
        tweet = await parse_tweet(
            url="https://x.com/whales/123",
            analyst="unusual_whales",
            text="$NVDA breaking out, going long",
        )
        assert tweet.tickers == ["NVDA"]
        assert tweet.is_actionable is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_tweet_parser.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement tweet_parser.py**

Create `consensus_engine/analysis/tweet_parser.py`:

```python
"""Tweet Parser — LLM-based intent extraction from analyst tweets.

Classifies each tweet as:
  A (ticker callout) — actionable
  B (macro/geo)      — context only
  C (options trade)   — actionable
  D (sentiment)       — context only

Extracts tickers, direction, options details, conviction level.
Falls back to regex extraction if LLM fails.
"""

import json
import logging
import re
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, TweetType, Direction, Conviction,
)
from consensus_engine.utils.tickers import extract_tickers

log = logging.getLogger("consensus_engine.analysis.tweet_parser")

_SYSTEM_PROMPT = """You are a stock market tweet classifier. Given a tweet from a financial analyst, extract structured trade information.

Respond ONLY in this exact JSON format (no extra text, no markdown):
{
  "type": "A|B|C|D",
  "tickers": ["TICKER1"],
  "direction": "long|short|neutral",
  "options": {
    "present": true|false,
    "strike": <number or null>,
    "expiry": "<YYYY-MM-DD or null>",
    "type": "call|put|null",
    "target_price": <number or null>,
    "profit_target_pct": <number or null>
  },
  "conviction": "high|medium|low",
  "summary": "<one-line summary of the trade idea>"
}

Classification rules:
- Type A: Explicit ticker mention with directional language ("buying NVDA", "long USO", "$AAPL looks good")
- Type B: Macro/geopolitical commentary implying trades ("Strait of Hormuz closing", "Fed rate decision")
- Type C: Options trade with any of: strike price, expiry, calls/puts ("TSLA 500c Friday", "buying puts on SPY")
- Type D: General market sentiment with no specific ticker ("market weak", "careful out there")

Conviction rules:
- high: "bought", "loaded", "all in", "adding more", mentions position size
- medium: "buying", "looking at", "watching for entry", "like this setup"
- low: "might", "considering", "interesting", "on radar", "watching"

If the tweet mentions both a ticker AND options details (strike/expiry/calls/puts), classify as C not A.
If no specific ticker is mentioned, tickers should be an empty array.
Always return valid JSON."""


def _build_parser_prompt(analyst: str, text: str) -> str:
    """Build the user prompt for the LLM."""
    return f"Analyst: @{analyst}\nTweet: {text}"


async def _call_openrouter(user_prompt: str) -> str:
    """Call OpenRouter API and return raw response text."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return ""

    model = cfg.get("llm.model", "openrouter/minimax/minimax-m2.5")

    async with aiohttp.ClientSession() as session:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 512,
            "temperature": 0.1,
        }

        async with session.post(
            url, headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.warning("OpenRouter error (%d) for tweet parse", resp.status)
                return ""
            data = await resp.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content.strip()


def _parse_llm_response(raw: str, url: str, analyst: str, original_text: str) -> ParsedTweet:
    """Parse the LLM JSON response into a ParsedTweet. Falls back to regex on failure."""
    # Strip markdown code blocks if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        log.debug("LLM parse failed, falling back to regex for: %s", original_text[:100])
        return _fallback_parse(url, analyst, original_text)

    # Extract type
    raw_type = str(data.get("type", "A")).upper()
    type_map = {"A": TweetType.TICKER_CALLOUT, "B": TweetType.MACRO,
                "C": TweetType.OPTIONS_TRADE, "D": TweetType.SENTIMENT}
    tweet_type = type_map.get(raw_type, TweetType.TICKER_CALLOUT)

    # Extract direction
    raw_dir = str(data.get("direction", "neutral")).lower()
    dir_map = {"long": Direction.LONG, "short": Direction.SHORT, "neutral": Direction.NEUTRAL}
    direction = dir_map.get(raw_dir, Direction.NEUTRAL)

    # Extract conviction
    raw_conv = str(data.get("conviction", "medium")).lower()
    conv_map = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}
    conviction = conv_map.get(raw_conv, Conviction.MEDIUM)

    # Extract tickers
    tickers = data.get("tickers", [])
    if not isinstance(tickers, list):
        tickers = []
    tickers = [t.upper() for t in tickers if isinstance(t, str)]

    # Extract options
    options_data = data.get("options", {})
    options = None
    if isinstance(options_data, dict) and options_data.get("present"):
        options = OptionsDetail(
            present=True,
            strike=_to_float(options_data.get("strike")),
            expiry=options_data.get("expiry"),
            option_type=options_data.get("type"),
            target_price=_to_float(options_data.get("target_price")),
            profit_target_pct=_to_float(options_data.get("profit_target_pct")),
        )

    summary = str(data.get("summary", ""))

    return ParsedTweet(
        tweet_url=url,
        analyst=analyst,
        raw_text=original_text,
        tweet_type=tweet_type,
        tickers=tickers,
        direction=direction,
        options=options,
        conviction=conviction,
        summary=summary or original_text[:100],
    )


def _fallback_parse(url: str, analyst: str, text: str) -> ParsedTweet:
    """Regex fallback when LLM fails. Extracts tickers, defaults to Type A medium."""
    tickers = list(extract_tickers(text))
    tweet_type = TweetType.TICKER_CALLOUT if tickers else TweetType.SENTIMENT
    return ParsedTweet(
        tweet_url=url,
        analyst=analyst,
        raw_text=text,
        tweet_type=tweet_type,
        tickers=tickers,
        direction=Direction.NEUTRAL,
        options=None,
        conviction=Conviction.MEDIUM,
        summary=text[:100],
    )


def _to_float(val) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def parse_tweet(url: str, analyst: str, text: str) -> ParsedTweet:
    """Parse a tweet using LLM with regex fallback.

    This is the main entry point called by the pipeline.
    """
    user_prompt = _build_parser_prompt(analyst, text)

    try:
        raw_response = await _call_openrouter(user_prompt)
        if not raw_response:
            return _fallback_parse(url, analyst, text)
        return _parse_llm_response(raw_response, url, analyst, text)
    except Exception as e:
        log.warning("Tweet parse error for @%s: %s", analyst, e)
        return _fallback_parse(url, analyst, text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_tweet_parser.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/analysis/tweet_parser.py tests/test_tweet_parser.py
git commit -m "feat: add LLM tweet parser for intent extraction

Classifies analyst tweets into types A/B/C/D, extracts tickers,
direction, options details, conviction. Regex fallback on LLM failure."
```

---

## Stream E: News Cascade

### Task 7: Build News Cascade (Finnhub + Google RSS + SearXNG)

**Files:**
- Create: `consensus_engine/scanners/searxng.py`
- Modify: `consensus_engine/scanners/news.py`
- Test: `tests/test_news_cascade.py`

- [ ] **Step 1: Write tests for news cascade**

Create `tests/test_news_cascade.py`:

```python
"""Tests for 4-tier news cascade."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from consensus_engine.scanners.news import news_cascade, _search_finnhub_news, _search_google_news_rss
from consensus_engine.scanners.searxng import search_searxng
from consensus_engine.models import CatalystResult


@pytest.mark.asyncio
async def test_finnhub_news_returns_catalyst():
    """Tier 1 hit should stop the cascade."""
    mock_result = CatalystResult(
        ticker="NVDA",
        catalyst_summary="NVDA beats earnings estimates",
        catalyst_type="Earnings Beat",
        news_sources=["reuters.com"],
        source_urls=["https://reuters.com/nvda-earnings"],
        confidence=0.8,
    )
    with patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=mock_result):
        result = await news_cascade("NVDA")
        assert result is not None
        assert result.catalyst_type == "Earnings Beat"
        assert result.news_sources == ["reuters.com"]


@pytest.mark.asyncio
async def test_cascade_falls_through_to_google_rss():
    """If Finnhub returns nothing, try Google RSS."""
    mock_google = CatalystResult(
        ticker="TSLA",
        catalyst_summary="Tesla analyst upgrade",
        catalyst_type="Analyst Upgrade",
        news_sources=["cnbc.com"],
        source_urls=["https://cnbc.com/tsla"],
        confidence=0.7,
    )
    with patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=mock_google):
        result = await news_cascade("TSLA")
        assert result is not None
        assert result.catalyst_type == "Analyst Upgrade"


@pytest.mark.asyncio
async def test_cascade_all_miss():
    """If all tiers miss, return None."""
    with patch("consensus_engine.scanners.news._search_finnhub_news",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_google_news_rss",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_brave",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.scanners.news._search_searxng",
               new_callable=AsyncMock, return_value=None):
        result = await news_cascade("ZZZZ")
        assert result is None


def test_searxng_parse_results():
    """SearXNG JSON response should be parseable."""
    from consensus_engine.scanners.searxng import _parse_searxng_results
    raw = {
        "results": [
            {"title": "NVDA earnings beat estimates", "url": "https://reuters.com/nvda", "content": "NVIDIA beat..."},
            {"title": "Random blog post", "url": "https://random.blog/nvda", "content": "My thoughts..."},
        ]
    }
    results = _parse_searxng_results(raw)
    assert len(results) == 2
    assert results[0]["title"] == "NVDA earnings beat estimates"
    assert results[0]["url"] == "https://reuters.com/nvda"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_news_cascade.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create SearXNG client**

Create `consensus_engine/scanners/searxng.py`:

```python
"""SearXNG JSON API client — tier 4 news search fallback.

Self-hosted SearXNG on localhost:8888 aggregates Google, Bing, DuckDuckGo.
"""

import logging
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.utils.rate_limiter import rate_limiter

log = logging.getLogger("consensus_engine.scanner.searxng")


def _parse_searxng_results(data: dict) -> list[dict]:
    """Parse SearXNG JSON response into a list of result dicts."""
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        })
    return results


async def search_searxng(query: str) -> list[dict]:
    """Search via self-hosted SearXNG. Returns list of {"title", "url", "content"}."""
    base_url = cfg.get("searxng.base_url", "http://localhost:8888")
    timeout = cfg.get("searxng.timeout", 10)

    if not await rate_limiter.acquire("searxng"):
        return []

    try:
        async with aiohttp.ClientSession() as session:
            params = {"q": query, "format": "json"}
            async with session.get(
                f"{base_url}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("searxng")
                    log.warning("SearXNG returned %d for '%s'", resp.status, query)
                    return []
                data = await resp.json()
                rate_limiter.report_success("searxng")
                results = _parse_searxng_results(data)
                log.debug("SearXNG: %d results for '%s'", len(results), query)
                return results
    except Exception as e:
        log.warning("SearXNG error: %s", e)
        rate_limiter.report_failure("searxng")
        return []
```

- [ ] **Step 4: Rewrite news.py with cascade**

Replace `consensus_engine/scanners/news.py` with:

```python
"""News Cascade — 4-tier news source for catalyst detection.

Tiers (tried in order, stops on first catalyst found):
  1. Finnhub /company-news
  2. Google News RSS
  3. Brave Search
  4. SearXNG (self-hosted)
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import CatalystResult, TickerSignal, SourceType, Sentiment
from consensus_engine.utils.rate_limiter import rate_limiter
from consensus_engine.scanners.searxng import search_searxng

log = logging.getLogger("consensus_engine.scanner.news")

# Catalyst classification patterns (kept from original)
_CATALYST_PATTERNS = [
    (["short squeeze", "squeeze", "short interest"], "Short Squeeze"),
    (["acquisition", "merger", "acquire", "buyout", "m&a"], "M&A"),
    (["upgrade", "price target raised", "outperform"], "Analyst Upgrade"),
    (["downgrade", "price target cut", "underperform"], "Analyst Downgrade"),
    (["earnings beat", "beat estimates", "revenue beat", "eps beat"], "Earnings Beat"),
    (["earnings miss", "missed estimates", "revenue miss", "eps miss"], "Earnings Miss"),
    (["fda approv", "fda clear", "drug approv"], "FDA Approval"),
    (["fda reject", "fda deny", "clinical fail"], "FDA Rejection"),
    (["government contract", "defense contract", "military contract"], "Government Contract"),
    (["partnership", "collaboration", "joint venture", "deal with"], "Partnership"),
    (["ipo", "public offering", "going public"], "IPO"),
    (["stock split", "reverse split"], "Stock Split"),
    (["dividend", "special dividend", "dividend increase"], "Dividend"),
    (["insider buy", "insider purchas"], "Insider Buying"),
    (["insider sell", "insider sold"], "Insider Selling"),
    (["sec filing", "13f", "13d", "sec investigat"], "SEC Filing"),
    (["patent", "intellectual property"], "Patent"),
    (["product launch", "new product", "announced", "unveil"], "Product Launch"),
    (["revenue guidance", "raised guidance", "lowered guidance"], "Guidance Update"),
    (["breaking", "just announced", "just reported"], "Breaking News"),
]


def _classify_catalyst(text: str) -> Optional[str]:
    """Classify catalyst type from text."""
    lower = text.lower()
    for patterns, label in _CATALYST_PATTERNS:
        if any(p in lower for p in patterns):
            return label
    return None


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    parts = url.split("/")
    return parts[2] if len(parts) > 2 else "unknown"


def _is_trusted_source(url: str) -> bool:
    """Check if URL is from a trusted news source."""
    trusted = cfg.get("news.trusted_sources", [])
    url_lower = url.lower()
    return any(source in url_lower for source in trusted)


def _build_catalyst(ticker: str, title: str, url: str, catalyst_type: str) -> CatalystResult:
    """Build a CatalystResult from a single news hit."""
    return CatalystResult(
        ticker=ticker,
        catalyst_summary=title[:200],
        catalyst_type=catalyst_type,
        news_sources=[_extract_domain(url)],
        source_urls=[url],
        confidence=0.8 if catalyst_type != "Market Movement" else 0.5,
    )


# ---------------------------------------------------------------------------
# Tier 1: Finnhub /company-news
# ---------------------------------------------------------------------------

async def _search_finnhub_news(ticker: str) -> Optional[CatalystResult]:
    """Search Finnhub company news endpoint."""
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return None
    if not await rate_limiter.acquire("finnhub_news"):
        return None

    days_back = cfg.get("news_cascade.finnhub_news_days_back", 2)
    from datetime import datetime, timedelta
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    try:
        async with aiohttp.ClientSession() as session:
            url = "https://finnhub.io/api/v1/company-news"
            params = {"symbol": ticker, "from": from_date, "to": to_date, "token": api_key}
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("finnhub_news")
                    return None
                articles = await resp.json()
                rate_limiter.report_success("finnhub_news")

        if not isinstance(articles, list):
            return None

        for article in articles[:10]:
            headline = article.get("headline", "")
            source = article.get("source", "")
            article_url = article.get("url", "")
            full_text = f"{headline} {source}"
            catalyst_type = _classify_catalyst(full_text)

            if catalyst_type and _is_trusted_source(article_url):
                log.info("Finnhub news catalyst for %s: %s (%s)", ticker, catalyst_type, source)
                return _build_catalyst(ticker, headline, article_url, catalyst_type)

        return None
    except Exception as e:
        log.warning("Finnhub news error for %s: %s", ticker, e)
        rate_limiter.report_failure("finnhub_news")
        return None


# ---------------------------------------------------------------------------
# Tier 2: Google News RSS
# ---------------------------------------------------------------------------

async def _search_google_news_rss(ticker: str) -> Optional[CatalystResult]:
    """Search Google News via RSS feed (free, no auth)."""
    if not await rate_limiter.acquire("google_news_rss"):
        return None

    query = f"{ticker}+stock"
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                rss_url,
                timeout=aiohttp.ClientTimeout(total=10),
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("google_news_rss")
                    return None
                xml_text = await resp.text()
                rate_limiter.report_success("google_news_rss")

        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            source_el = item.find("source")
            source_name = source_el.text if source_el is not None else ""

            catalyst_type = _classify_catalyst(title)
            # Check if source or link domain is trusted
            is_trusted = _is_trusted_source(link) or any(
                s.lower() in source_name.lower()
                for s in cfg.get("news.trusted_sources", [])
            )

            if catalyst_type and is_trusted:
                log.info("Google RSS catalyst for %s: %s (%s)", ticker, catalyst_type, source_name)
                return _build_catalyst(ticker, title, link, catalyst_type)

        return None
    except Exception as e:
        log.warning("Google News RSS error for %s: %s", ticker, e)
        rate_limiter.report_failure("google_news_rss")
        return None


# ---------------------------------------------------------------------------
# Tier 3: Brave Search (existing, quota-limited)
# ---------------------------------------------------------------------------

async def _search_brave(ticker: str) -> Optional[CatalystResult]:
    """Search Brave for news (quota-limited, tier 3)."""
    api_key = cfg.get_api_key("brave_search")
    if not api_key:
        return None
    if not await rate_limiter.acquire("brave_search"):
        return None

    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
            params = {
                "q": f"{ticker} stock news today",
                "count": cfg.get("news.max_search_results", 10),
                "freshness": "pd",
            }
            async with session.get(url, headers=headers, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    rate_limiter.report_failure("brave_search")
                    return None
                data = await resp.json()
                rate_limiter.report_success("brave_search")

        for r in data.get("web", {}).get("results", []):
            title = r.get("title", "")
            result_url = r.get("url", "")
            description = r.get("description", "")
            full_text = f"{title} {description}"
            catalyst_type = _classify_catalyst(full_text)

            if catalyst_type and _is_trusted_source(result_url):
                log.info("Brave catalyst for %s: %s", ticker, catalyst_type)
                return _build_catalyst(ticker, title, result_url, catalyst_type)

        return None
    except Exception as e:
        log.warning("Brave search error for %s: %s", ticker, e)
        rate_limiter.report_failure("brave_search")
        return None


# ---------------------------------------------------------------------------
# Tier 4: SearXNG (self-hosted fallback)
# ---------------------------------------------------------------------------

async def _search_searxng(ticker: str) -> Optional[CatalystResult]:
    """Search SearXNG for news (self-hosted, unlimited)."""
    results = await search_searxng(f"{ticker} stock news")
    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        content = r.get("content", "")
        full_text = f"{title} {content}"
        catalyst_type = _classify_catalyst(full_text)

        if catalyst_type and _is_trusted_source(url):
            log.info("SearXNG catalyst for %s: %s", ticker, catalyst_type)
            return _build_catalyst(ticker, title, url, catalyst_type)

    return None


# ---------------------------------------------------------------------------
# Public API: News Cascade
# ---------------------------------------------------------------------------

async def news_cascade(ticker: str) -> Optional[CatalystResult]:
    """Run the 4-tier news cascade. Stops at first catalyst found.

    Order: Finnhub → Google RSS → Brave → SearXNG
    """
    tiers = cfg.get("news_cascade.tiers", ["finnhub", "google_rss", "brave", "searxng"])

    tier_funcs = {
        "finnhub": _search_finnhub_news,
        "google_rss": _search_google_news_rss,
        "brave": _search_brave,
        "searxng": _search_searxng,
    }

    for tier_name in tiers:
        func = tier_funcs.get(tier_name)
        if not func:
            continue
        result = await func(ticker)
        if result and result.passed:
            log.info("News cascade hit at tier '%s' for %s", tier_name, ticker)
            return result

    log.debug("News cascade: no catalyst found for %s across all tiers", ticker)
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_news_cascade.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/scanners/news.py consensus_engine/scanners/searxng.py tests/test_news_cascade.py
git commit -m "feat: rewrite news to 4-tier cascade with SearXNG

Finnhub company-news → Google News RSS → Brave Search → SearXNG.
Stops at first trusted catalyst. Preserves Brave quota."
```

---

### Task 8: Ticker Noise Fix

**Files:**
- Modify: `consensus_engine/utils/tickers.py`
- Test: `tests/test_ticker_validation.py`

- [ ] **Step 1: Write tests for expanded blacklist and market-cap validation**

Create `tests/test_ticker_validation.py`:

```python
"""Tests for ticker validation and noise filtering."""
import pytest
from consensus_engine.utils.tickers import extract_tickers, is_valid_ticker, BLACKLIST


def test_common_words_blacklisted():
    """Words from the log noise should all be blacklisted."""
    noise_tickers = [
        "AAA", "BBC", "CIA", "CO", "CD", "BE", "BK", "CF", "BDC",
        "BNO", "AL", "AM", "ATR", "BA", "BATL", "CC", "CL",
        "CORN", "CAN", "CBOE",
    ]
    for t in noise_tickers:
        assert t in BLACKLIST, f"{t} should be blacklisted"


def test_real_tickers_not_blacklisted():
    """Real traded tickers should NOT be in the blacklist."""
    real_tickers = ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "GOOGL", "AMZN", "META"]
    for t in real_tickers:
        assert t not in BLACKLIST, f"{t} should NOT be blacklisted"


def test_extract_tickers_filters_noise():
    """Extract should not return known noise words."""
    text = "The BBC reported that AM trading was BE quiet. Also CIA filed a CO report."
    tickers = extract_tickers(text)
    assert "BBC" not in tickers
    assert "AM" not in tickers
    assert "BE" not in tickers
    assert "CIA" not in tickers
    assert "CO" not in tickers


def test_extract_tickers_finds_real():
    text = "$NVDA breaking out, $TSLA also running"
    tickers = extract_tickers(text)
    assert "NVDA" in tickers
    assert "TSLA" in tickers


@pytest.mark.asyncio
async def test_validate_ticker_market_cap(tmp_path):
    """Market cap filter should reject tiny/nonexistent tickers."""
    from consensus_engine.utils.tickers import validate_ticker_market_cap
    from consensus_engine import db, config as cfg
    cfg.load_config()
    cfg._config["database"] = {"path": str(tmp_path / "test.db"), "signal_ttl_hours": 2}
    await db.init_db()

    # Manually cache a ticker above threshold
    await db.cache_ticker_metadata("NVDA", "NVIDIA", 2.8e12, "NASDAQ")
    result = await validate_ticker_market_cap("NVDA")
    assert result is True

    # Manually cache a ticker below threshold
    await db.cache_ticker_metadata("TINY", "Tiny Corp", 50e6, "OTC")
    result = await validate_ticker_market_cap("TINY")
    assert result is False

    await db.close_db()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_ticker_validation.py -v`
Expected: FAIL

- [ ] **Step 3: Expand the blacklist in tickers.py**

Replace the `BLACKLIST` set in `consensus_engine/utils/tickers.py` with:

```python
BLACKLIST: set[str] = {
    # Common English words
    "A", "I", "IT", "ON", "IN", "TO", "DO", "BE", "UP", "ALL", "OUT", "FOR", "ARE", "ANY",
    "HAS", "WAS", "NOW", "SEE", "DAY", "BUY", "RUN", "BIG", "MAN", "CAN", "NEW", "ONE",
    "TWO", "SIX", "TEN", "CAR", "JOB", "PAY", "TAX", "THE", "MY", "SO", "AT", "NO", "GO",
    "OR", "AM", "US", "YOU", "SAVE", "HELP", "JUST", "PLUS", "REAL", "OPEN", "LIVE", "TODAY",
    "ADD", "RAN", "SET", "OLD", "LOW", "HOT", "OUR", "HIS", "HER", "OWN", "WAY", "GOT",
    "HIT", "LET", "PUT", "SAY", "SHE", "TOO", "USE", "HIM", "HOW", "ITS", "MAY", "OIL",
    "AGE", "AGO", "AID", "AIM", "AIR", "ARM", "ASK", "ATE", "BAD", "BAR", "BED", "BIT",
    "BOX", "BOY", "BUS", "BUT", "CUT", "DID", "DIG", "DOG", "DRY", "EAR", "EAT", "END",
    "ERA", "EYE", "FAR", "FAT", "FEW", "FIT", "FLY", "GAP", "GAS", "GOD", "GUN",
    "HAD", "HAT", "ICE", "ILL", "KEY", "LAY", "LED", "LEG", "LIE", "LOT", "MAP", "MET",
    "MIX", "MOM", "MUD", "NET", "NOR", "NOT", "NUT", "ODD",
    # Corporate / financial acronyms
    "CEO", "CFO", "CTO", "COO", "DD", "EPS", "ROI", "YTD", "SEC", "FED", "GDP", "ATH",
    "OTC", "IPO", "PNL", "PR", "HR", "LLC", "INC", "ETF", "API", "NYSE", "ISIN",
    "IOT", "GDP", "CPI", "PMI", "ISM",
    # Reddit / WSB slang
    "YOLO", "FOMO", "LFG", "WSB", "MOON", "HOLD", "PUMP", "DUMP", "APE", "APES",
    "BULL", "BEAR", "GUH", "TEND", "DFV", "RH", "MAGA", "WIKI",
    # Geopolitics / general
    "USA", "UK", "EU", "UAE", "IMF", "WHO", "NATO", "CIA", "FBI", "NSA", "BBC", "CNN",
    "PBS", "NPR", "EPA", "IRS", "DOJ", "FDA",
    # Tech buzzwords that collide
    "AI", "EV", "AR", "VR", "PC", "TV", "OS", "IT",
    # Two-letter noise and short words that appear as ticker symbols
    "CL", "ES", "CC", "UI", "AA", "HL", "IP", "FM", "PL", "IG", "CD", "EA", "RR",
    "VG", "SF", "RS", "IQ", "AL", "CO", "CF", "BK", "RE",
    # Three-letter words commonly confused for tickers
    "AAA", "ABC", "ACE", "ACT", "AGE", "ATR", "AVG",
    "BAN", "BAT", "BDC", "BNO", "BATL",
    "CAB", "CAP", "CBOE", "CORN",
    "DIP", "DUE", "ERA",
    "FUN", "GAP", "GIG",
    "MAX", "MIN", "MIX", "MOB",
    "OPT", "ORE",
    "POP", "PRO",
    "RAW", "RIG", "ROW",
    "SAP", "SUM", "SUB",
    "TIP", "TOP",
    "VIA", "WAR", "WEB", "WIN", "ZAP",
    # Common tickers that are too noisy to track (index ETFs)
    "SPY", "QQQ", "JOSE",
}
```

- [ ] **Step 4: Add market-cap validation function to tickers.py**

Add to end of `consensus_engine/utils/tickers.py`:

```python
async def validate_ticker_market_cap(ticker: str) -> bool:
    """Check if a ticker has sufficient market cap ($100M+).

    Uses cached metadata from DB. If not cached, fetches from Finnhub
    and caches the result.
    """
    from consensus_engine import db, config as cfg

    min_cap = cfg.get("ticker_validation.min_market_cap", 100_000_000)
    max_age = cfg.get("ticker_validation.cache_ttl_days", 7)

    # Check cache first
    meta = await db.get_ticker_metadata(ticker, max_age_days=max_age)
    if meta is not None:
        return meta["market_cap"] >= min_cap

    # Fetch from Finnhub
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return True  # Can't validate, allow through

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = "https://finnhub.io/api/v1/stock/profile2"
            params = {"symbol": ticker, "token": api_key}
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return True  # Can't validate, allow through
                data = await resp.json()

        name = data.get("name", "")
        market_cap = data.get("marketCapitalization", 0) * 1_000_000  # Finnhub returns in millions
        exchange = data.get("exchange", "")

        if not name:
            # Ticker doesn't exist on Finnhub
            await db.cache_ticker_metadata(ticker, "", 0, "")
            return False

        await db.cache_ticker_metadata(ticker, name, market_cap, exchange)
        return market_cap >= min_cap

    except Exception:
        return True  # On error, allow through rather than blocking
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_ticker_validation.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/utils/tickers.py tests/test_ticker_validation.py
git commit -m "fix: expand ticker blacklist and add market-cap validation

Add ~80 new blacklist entries for words showing up as false positives.
Add Finnhub-based market cap validation with 7-day cache."
```

---

## Stream F: Discord Alerts

### Task 9: Build Two-Phase Discord Alerts

**Files:**
- Modify: `consensus_engine/alerts/discord.py`
- Test: `tests/test_discord_alerts.py`

- [ ] **Step 1: Write tests for two-phase alert formatting**

Create `tests/test_discord_alerts.py`:

```python
"""Tests for two-phase Discord alert formatting."""
import pytest
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, TweetType, Direction, Conviction,
    CrossReferenceResult, ScoreBreakdown, TechnicalResult, TechnicalFilter,
)
from consensus_engine.alerts.discord import format_instant_ping, format_detail_followup


def test_format_instant_ping_type_a():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="WallStreetSilv",
        raw_text="Strait of Hormuz closing, going long USO",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["USO"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="Going long USO on geopolitical catalyst",
    )
    embed = format_instant_ping(tweet, current_price=78.15)
    assert "WallStreetSilv" in embed["title"]
    assert "USO" in embed["title"]
    assert "LONG" in embed["title"]
    assert "78.15" in embed["fields"][0]["value"]  # price field


def test_format_instant_ping_type_c_with_options():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/456",
        analyst="OptionMillionaire",
        raw_text="Buying TSLA 500c Friday targeting 510",
        tweet_type=TweetType.OPTIONS_TRADE,
        tickers=["TSLA"],
        direction=Direction.LONG,
        options=OptionsDetail(
            present=True, strike=500.0, expiry="2026-03-28",
            option_type="call", target_price=510.0, profit_target_pct=100.0,
        ),
        conviction=Conviction.HIGH,
        summary="Buying TSLA 500c Friday expiry targeting 510",
    )
    embed = format_instant_ping(tweet, current_price=487.32)
    # Should contain options details
    fields_text = " ".join(f["value"] for f in embed["fields"])
    assert "500" in fields_text  # strike
    assert "call" in fields_text.lower() or "Call" in fields_text
    assert "510" in fields_text  # target


def test_format_detail_followup():
    breakdown = ScoreBreakdown(
        base=30, additional_analysts=40, news_catalyst=15,
        social_apewisdom=10, social_stocktwits=10,
        technical=10, llm_boost=12,
    )
    tech = TechnicalResult(
        ticker="TSLA",
        filters=[
            TechnicalFilter(name="RVOL", value=2.8, threshold="> 2.0x", passed=True),
            TechnicalFilter(name="RSI", value=62.0, threshold="40-75", passed=True),
        ],
        price=487.32, volume=50000000, price_change_pct=3.2,
    )
    xref = CrossReferenceResult(
        ticker="TSLA",
        breakdown=breakdown,
        catalyst_summary="Tesla PT raised to $550",
        catalyst_type="Analyst Upgrade",
        catalyst_sources=["reuters.com"],
        catalyst_urls=["https://reuters.com/tsla"],
        technical=tech,
        other_analysts=["unusual_whales", "CheddarFlow"],
        social_summary="StockTwits trending, ApeWisdom #4",
        llm_reasoning="Strong multi-source confirmation",
    )
    embed = format_detail_followup(xref)
    assert "TSLA" in embed["title"]
    assert "127" in embed["title"]  # total score
    assert "Analyst Upgrade" in str(embed["fields"])
    assert "unusual_whales" in str(embed["fields"])


def test_format_detail_followup_no_signals():
    breakdown = ScoreBreakdown(base=25)
    xref = CrossReferenceResult(
        ticker="NVDA", breakdown=breakdown,
        catalyst_summary="", catalyst_type="",
        technical=None, other_analysts=[],
        social_summary="", llm_reasoning="",
    )
    embed = format_detail_followup(xref)
    assert "No additional signals" in str(embed["fields"]) or "25" in embed["title"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_discord_alerts.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Rewrite discord.py for two-phase alerts**

Replace `consensus_engine/alerts/discord.py` with:

```python
"""Two-Phase Discord Alert Delivery.

Phase 1: Instant ping — analyst name, ticker, direction, options, price
Phase 2: Detail follow-up — replies to ping with cross-reference results
"""

import json
import logging
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    Direction, TweetType,
)

log = logging.getLogger("consensus_engine.alerts.discord")


def format_instant_ping(tweet: ParsedTweet, current_price: float = 0.0) -> dict:
    """Build Discord embed for the instant ping (Phase 1)."""
    direction_str = tweet.direction.value.upper()
    ticker = tweet.tickers[0] if tweet.tickers else "???"

    # Color based on direction
    color_map = {
        Direction.LONG: cfg.get("alerts.embed_color_long", 0x00FF00),
        Direction.SHORT: cfg.get("alerts.embed_color_short", 0xFF0000),
        Direction.NEUTRAL: cfg.get("alerts.embed_color_neutral", 0xFFAA00),
    }
    color = color_map.get(tweet.direction, 0xFFAA00)

    fields = []

    # Price field
    if current_price > 0:
        fields.append({
            "name": "Current Price",
            "value": f"${current_price:.2f}",
            "inline": True,
        })

    # Options details if present
    if tweet.options and tweet.options.present:
        opt = tweet.options
        parts = []
        if opt.option_type:
            parts.append(opt.option_type.capitalize())
        if opt.strike:
            parts.append(f"${opt.strike:.0f} strike")
        if opt.expiry:
            parts.append(f"{opt.expiry} expiry")
        if opt.target_price:
            parts.append(f"Target: ${opt.target_price:.0f}")
        if opt.profit_target_pct:
            parts.append(f"{opt.profit_target_pct:.0f}% profit target")

        if parts:
            fields.append({
                "name": "Options",
                "value": " | ".join(parts),
                "inline": False,
            })

    # Score field
    fields.append({
        "name": "Score",
        "value": f"{tweet.base_score} (cross-references pending...)",
        "inline": True,
    })

    embed = {
        "title": f"@{tweet.analyst} \u2014 ${ticker} {direction_str}",
        "description": f"\"{tweet.raw_text[:300]}\"",
        "color": color,
        "fields": fields,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine"},
    }

    return embed


def format_detail_followup(xref: CrossReferenceResult) -> dict:
    """Build Discord embed for the detail follow-up (Phase 2)."""
    b = xref.breakdown
    total = b.total

    fields = []

    # News catalyst
    if xref.catalyst_summary:
        catalyst_text = f"**{xref.catalyst_type}**\n{xref.catalyst_summary[:200]}"
        if xref.catalyst_sources:
            catalyst_text += f"\nSources: {', '.join(xref.catalyst_sources[:3])}"
        fields.append({"name": "News Catalyst", "value": catalyst_text, "inline": False})

    # Technical snapshot
    if xref.technical and xref.technical.filters:
        tech_lines = []
        for f in xref.technical.filters:
            icon = "\u2705" if f.passed else "\u274c"
            tech_lines.append(f"{icon} {f.name}: {f.value} ({f.threshold})")
        fields.append({"name": "Technical Snapshot", "value": "\n".join(tech_lines), "inline": False})

    # Social
    if xref.social_summary:
        fields.append({"name": "Social", "value": xref.social_summary, "inline": False})

    # Other analysts
    if xref.other_analysts:
        analyst_text = ", ".join(f"@{a}" for a in xref.other_analysts[:10])
        analyst_text += f" (+{b.additional_analysts} pts)"
        fields.append({"name": "Other Analysts", "value": analyst_text, "inline": False})

    # LLM reasoning
    if xref.llm_reasoning:
        fields.append({"name": "LLM Analysis", "value": f"+{b.llm_boost} pts \u2014 {xref.llm_reasoning[:150]}", "inline": False})

    # Score breakdown
    parts = []
    if b.base: parts.append(f"base({b.base})")
    if b.additional_analysts: parts.append(f"analysts({b.additional_analysts})")
    if b.news_catalyst: parts.append(f"news({b.news_catalyst})")
    if b.sec_filing: parts.append(f"sec({b.sec_filing})")
    if b.social_apewisdom: parts.append(f"ape({b.social_apewisdom})")
    if b.social_stocktwits: parts.append(f"st({b.social_stocktwits})")
    if b.social_reddit: parts.append(f"reddit({b.social_reddit})")
    if b.google_trends: parts.append(f"trends({b.google_trends})")
    if b.technical: parts.append(f"tech({b.technical})")
    if b.llm_boost: parts.append(f"llm({b.llm_boost})")
    breakdown_text = " + ".join(parts) + f" = {total}"
    fields.append({"name": "Breakdown", "value": breakdown_text, "inline": False})

    if not xref.catalyst_summary and not xref.other_analysts and not xref.social_summary:
        fields.insert(0, {"name": "Status", "value": "No additional signals found", "inline": False})

    embed = {
        "title": f"Cross-Reference: ${xref.ticker} | Score: {total}",
        "color": 0x5865F2,  # Discord blurple
        "fields": fields,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "footer": {"text": "OpenClaw Signal Engine"},
    }

    return embed


async def send_instant_ping(tweet: ParsedTweet, current_price: float = 0.0) -> Optional[str]:
    """Send the instant ping to Discord. Returns the message ID or None."""
    if cfg.dry_run:
        ticker = tweet.tickers[0] if tweet.tickers else "???"
        log.info("[DRY-RUN] Instant ping: @%s $%s %s (score=%d)",
                 tweet.analyst, ticker, tweet.direction.value, tweet.base_score)
        return "dry_run_msg_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Discord not configured for instant ping")
        return None

    embed = format_instant_ping(tweet, current_price)

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            body = {"embeds": [embed]}

            async with session.post(url, headers=headers, json=body,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    msg_id = data.get("id")
                    log.info("Instant ping sent for $%s by @%s (msg_id=%s)",
                             tweet.tickers[0] if tweet.tickers else "???",
                             tweet.analyst, msg_id)
                    return msg_id
                else:
                    error = await resp.text()
                    log.warning("Discord ping error (%d): %s", resp.status, error[:200])
                    return None
    except Exception as e:
        log.error("Failed to send instant ping: %s", e)
        return None


async def send_detail_followup(xref: CrossReferenceResult, reply_to_msg_id: str) -> Optional[str]:
    """Send the detail follow-up as a reply to the instant ping. Returns message ID."""
    if cfg.dry_run:
        log.info("[DRY-RUN] Detail follow-up: $%s score=%d", xref.ticker, xref.final_score)
        return "dry_run_followup_id"

    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("api_keys.discord_channel_id", ""))
    if not token or not channel_id or not channel_id.isdigit():
        return None

    embed = format_detail_followup(xref)

    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
            headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
            body = {
                "embeds": [embed],
                "message_reference": {"message_id": reply_to_msg_id},
            }

            async with session.post(url, headers=headers, json=body,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    msg_id = data.get("id")
                    log.info("Detail follow-up sent for $%s (score=%d, msg_id=%s)",
                             xref.ticker, xref.final_score, msg_id)
                    return msg_id
                else:
                    error = await resp.text()
                    log.warning("Discord follow-up error (%d): %s", resp.status, error[:200])
                    return None
    except Exception as e:
        log.error("Failed to send detail follow-up: %s", e)
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_discord_alerts.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/alerts/discord.py tests/test_discord_alerts.py
git commit -m "feat: two-phase Discord alerts (instant ping + detail reply)

Phase 1: instant embed with analyst, ticker, direction, options, price.
Phase 2: reply with cross-reference score breakdown and catalysts."
```

---

## Stream G: Cross-Reference Engine

### Task 10: Build Cross-Reference Engine

**Files:**
- Create: `consensus_engine/cross_reference.py`
- Test: `tests/test_cross_reference.py`

- [ ] **Step 1: Write tests for cross-reference scoring**

Create `tests/test_cross_reference.py`:

```python
"""Tests for cross-reference scoring engine."""
import pytest
from unittest.mock import AsyncMock, patch
from consensus_engine.models import (
    ParsedTweet, TweetType, Direction, Conviction,
    CatalystResult, TechnicalResult, TechnicalFilter,
    ScoreBreakdown,
)
from consensus_engine.cross_reference import (
    compute_technical_score, compute_social_score, cross_reference,
)


def test_compute_technical_score_all_pass():
    tech = TechnicalResult(
        ticker="NVDA",
        filters=[
            TechnicalFilter(name="RVOL", value=2.5, threshold="> 2.0x", passed=True),
            TechnicalFilter(name="VWAP", value=100, threshold="> 98 (VWAP)", passed=True),
            TechnicalFilter(name="RSI", value=60, threshold="40-75", passed=True),
            TechnicalFilter(name="EMA Cross", value=0.5, threshold="9EMA > 21EMA", passed=True),
            TechnicalFilter(name="Price Change", value=3.0, threshold="> +1.0%", passed=True),
            TechnicalFilter(name="ATR Breakout", value=1.8, threshold="> 1.5x ATR", passed=True),
        ],
        price=100, volume=50000000,
    )
    score = compute_technical_score(tech)
    assert score == 12  # 6 filters * 2 pts = 12 (capped at 12)


def test_compute_technical_score_partial():
    tech = TechnicalResult(
        ticker="NVDA",
        filters=[
            TechnicalFilter(name="RVOL", value=2.5, threshold="> 2.0x", passed=True),
            TechnicalFilter(name="RSI", value=80, threshold="40-75", passed=False),
            TechnicalFilter(name="EMA Cross", value=0.5, threshold="9EMA > 21EMA", passed=True),
        ],
        price=100, volume=50000000,
    )
    score = compute_technical_score(tech)
    assert score == 4  # 2 passed * 2 pts


def test_compute_technical_score_none():
    score = compute_technical_score(None)
    assert score == 0


def test_compute_social_score():
    social_data = {
        "apewisdom": 5,
        "stocktwits": 2,
        "reddit": 3,
        "google_trends": 1,
    }
    score = compute_social_score(social_data)
    # apewisdom >= 1 → 10, stocktwits >= 1 → 10, reddit >= 2 → 10, trends >= 1 → 5
    assert score == 35


def test_compute_social_score_empty():
    score = compute_social_score({})
    assert score == 0


@pytest.mark.asyncio
async def test_cross_reference_with_mocked_sources():
    tweet = ParsedTweet(
        tweet_url="https://x.com/user/123",
        analyst="unusual_whales",
        raw_text="$NVDA breaking out",
        tweet_type=TweetType.TICKER_CALLOUT,
        tickers=["NVDA"],
        direction=Direction.LONG,
        options=None,
        conviction=Conviction.HIGH,
        summary="NVDA breakout",
    )

    mock_catalyst = CatalystResult(
        ticker="NVDA", catalyst_summary="NVDA earnings beat",
        catalyst_type="Earnings Beat", news_sources=["reuters.com"],
        source_urls=["https://reuters.com/nvda"], confidence=0.8,
    )

    with patch("consensus_engine.cross_reference._run_news_cascade",
               new_callable=AsyncMock, return_value=mock_catalyst), \
         patch("consensus_engine.cross_reference._run_sec_check",
               new_callable=AsyncMock, return_value=False), \
         patch("consensus_engine.cross_reference._run_social_check",
               new_callable=AsyncMock, return_value={"apewisdom": 3}), \
         patch("consensus_engine.cross_reference._run_technical",
               new_callable=AsyncMock, return_value=None), \
         patch("consensus_engine.cross_reference._run_other_analysts",
               new_callable=AsyncMock, return_value=["CheddarFlow"]), \
         patch("consensus_engine.cross_reference._run_llm_score",
               new_callable=AsyncMock, return_value=(75.0, "Strong setup")):
        result = await cross_reference("NVDA", tweet)

    assert result.breakdown.base == 30
    assert result.breakdown.news_catalyst == 15
    assert result.breakdown.additional_analysts == 20
    assert result.breakdown.social_apewisdom == 10
    assert result.breakdown.llm_boost > 0
    assert result.final_score > 30
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_cross_reference.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement cross_reference.py**

Create `consensus_engine/cross_reference.py`:

```python
"""Cross-Reference Engine — orchestrates all multiplier sources.

Runs in parallel after the instant Discord ping. Computes a final
score from news, social, technical, other analysts, and LLM confidence.
"""

import asyncio
import logging
from typing import Optional

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import (
    ParsedTweet, CrossReferenceResult, ScoreBreakdown,
    CatalystResult, TechnicalResult,
)
from consensus_engine.scanners.news import news_cascade
from consensus_engine.analysis.technical import verify_technical
from consensus_engine.analysis.llm_scorer import score_confidence

log = logging.getLogger("consensus_engine.cross_reference")


def compute_technical_score(technical: Optional[TechnicalResult]) -> int:
    """Compute score from technical filters. +2 per passing filter, max 12."""
    if not technical or not technical.filters:
        return 0
    per_filter = cfg.get("scoring.multipliers.technical_per_filter", 2)
    max_pts = cfg.get("scoring.multipliers.technical_max", 12)
    return min(technical.passed_count * per_filter, max_pts)


def compute_social_score(social_data: dict[str, int]) -> int:
    """Compute social cross-reference score from platform signal counts."""
    score = 0
    m = cfg.get("scoring.multipliers", {})
    if social_data.get("apewisdom", 0) >= 1:
        score += m.get("social_apewisdom", 10)
    if social_data.get("stocktwits", 0) >= 1:
        score += m.get("social_stocktwits", 10)
    if social_data.get("reddit", 0) >= 2:
        score += m.get("social_reddit", 10)
    if social_data.get("google_trends", 0) >= 1:
        score += m.get("google_trends", 5)
    return score


def _compute_social_breakdown(social_data: dict[str, int]) -> dict[str, int]:
    """Return per-source social points for the ScoreBreakdown."""
    m = cfg.get("scoring.multipliers", {})
    return {
        "social_apewisdom": m.get("social_apewisdom", 10) if social_data.get("apewisdom", 0) >= 1 else 0,
        "social_stocktwits": m.get("social_stocktwits", 10) if social_data.get("stocktwits", 0) >= 1 else 0,
        "social_reddit": m.get("social_reddit", 10) if social_data.get("reddit", 0) >= 2 else 0,
        "google_trends": m.get("google_trends", 5) if social_data.get("google_trends", 0) >= 1 else 0,
    }


# ---------------------------------------------------------------------------
# Internal runners (thin wrappers for mocking in tests)
# ---------------------------------------------------------------------------

async def _run_news_cascade(ticker: str) -> Optional[CatalystResult]:
    return await news_cascade(ticker)


async def _run_sec_check(ticker: str) -> bool:
    """Check SEC EDGAR for recent filings. Returns True if relevant filing found."""
    # SEC EDGAR MCP integration — placeholder that returns False until MCP is wired
    # TODO: Wire to sec-edgar MCP server
    return False


async def _run_social_check(ticker: str) -> dict[str, int]:
    """Get social signal counts for a ticker from the database."""
    counts = await db.get_signal_counts_by_source(ticker)
    return {
        "apewisdom": counts.get("apewisdom", 0),
        "stocktwits": counts.get("stocktwits", 0),
        "reddit": counts.get("reddit", 0),
        "google_trends": counts.get("google_trends", 0),
    }


async def _run_technical(ticker: str) -> Optional[TechnicalResult]:
    return await verify_technical(ticker)


async def _run_other_analysts(ticker: str, exclude_analyst: str = "") -> list[str]:
    """Get other analysts who recently mentioned this ticker."""
    analysts = await db.get_recent_analysts_for_ticker(ticker, window_seconds=3600)
    return [a for a in analysts if a != exclude_analyst]


async def _run_llm_score(ticker: str, catalyst: Optional[CatalystResult],
                          technical: Optional[TechnicalResult]) -> tuple[float, str]:
    """Get LLM confidence score."""
    return await score_confidence(ticker, None, None, catalyst, technical)


async def cross_reference(ticker: str, tweet: ParsedTweet) -> CrossReferenceResult:
    """Run all cross-reference sources in parallel and compute final score."""
    log.info("Starting cross-reference for $%s (base=%d)", ticker, tweet.base_score)
    m = cfg.get("scoring.multipliers", {})

    # Run all sources concurrently
    catalyst, sec_hit, social_data, technical, other_analysts, (llm_score, llm_reasoning) = \
        await asyncio.gather(
            _run_news_cascade(ticker),
            _run_sec_check(ticker),
            _run_social_check(ticker),
            _run_technical(ticker),
            _run_other_analysts(ticker, exclude_analyst=tweet.analyst),
            _run_llm_score(ticker, None, None),  # Will be enriched below
        )

    # If we got technical + catalyst, re-run LLM with full data
    if technical or catalyst:
        llm_score, llm_reasoning = await _run_llm_score(ticker, catalyst, technical)

    # Compute score components
    analyst_pts = len(other_analysts) * m.get("additional_analyst", 20)
    news_pts = m.get("news_catalyst", 15) if (catalyst and catalyst.passed) else 0
    sec_pts = m.get("sec_filing", 15) if sec_hit else 0
    tech_pts = compute_technical_score(technical)
    social_breakdown = _compute_social_breakdown(social_data)

    # LLM boost: scale 0-100 score to 0-15 pts
    llm_max = m.get("llm_boost_max", 15)
    llm_pts = int(llm_score / 100 * llm_max)

    # Build social summary
    social_parts = []
    if social_data.get("apewisdom", 0) >= 1:
        social_parts.append(f"ApeWisdom ({social_data['apewisdom']} mentions)")
    if social_data.get("stocktwits", 0) >= 1:
        social_parts.append("StockTwits trending")
    if social_data.get("reddit", 0) >= 2:
        social_parts.append(f"Reddit ({social_data['reddit']} mentions)")
    if social_data.get("google_trends", 0) >= 1:
        social_parts.append("Google Trends spike")

    breakdown = ScoreBreakdown(
        base=tweet.base_score,
        additional_analysts=analyst_pts,
        news_catalyst=news_pts,
        sec_filing=sec_pts,
        technical=tech_pts,
        llm_boost=llm_pts,
        **social_breakdown,
    )

    result = CrossReferenceResult(
        ticker=ticker,
        breakdown=breakdown,
        catalyst_summary=catalyst.catalyst_summary if catalyst else "",
        catalyst_type=catalyst.catalyst_type if catalyst else "",
        catalyst_sources=catalyst.news_sources if catalyst else [],
        catalyst_urls=catalyst.source_urls if catalyst else [],
        technical=technical,
        other_analysts=other_analysts,
        social_summary=", ".join(social_parts) if social_parts else "",
        llm_reasoning=llm_reasoning,
    )

    log.info("Cross-reference for $%s: score=%d (base=%d + xref=%d)",
             ticker, result.final_score, tweet.base_score,
             result.final_score - tweet.base_score)

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/.openclaw/workspace && python3 -m pytest tests/test_cross_reference.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/cross_reference.py tests/test_cross_reference.py
git commit -m "feat: add cross-reference engine with parallel scoring

Orchestrates news cascade, social, technical, analyst, and LLM
sources concurrently. Computes additive score breakdown."
```

---

### Task 11: Remove Old Consensus Pipeline and Apify Client

**Files:**
- Remove: `consensus_engine/consensus.py`
- Remove: `consensus_engine/scanners/twitter.py`
- Remove: `consensus_engine/utils/apify_client.py`
- Modify: `consensus_engine/scanners/social.py` (remove hard-gate evaluation)

- [ ] **Step 1: Remove consensus.py**

```bash
cd /root/.openclaw/workspace
git rm consensus_engine/consensus.py
```

- [ ] **Step 2: Remove old twitter.py**

```bash
git rm consensus_engine/scanners/twitter.py
```

- [ ] **Step 3: Remove apify_client.py**

```bash
git rm consensus_engine/utils/apify_client.py
```

- [ ] **Step 4: Clean up social.py — remove evaluate_social_consensus and Apify imports**

In `consensus_engine/scanners/social.py`:

1. Remove the import of `apify` from `consensus_engine.utils.apify_client`
2. Remove `_scan_reddit_apify()` function
3. Remove `scan_reddit()` function (the Apify→Playwright wrapper)
4. Remove `evaluate_social_consensus()` function
5. Remove `_google_trends_apify()` function
6. Keep: `scan_stocktwits()`, `scan_apewisdom()`, `_quick_sentiment()`, `_scan_reddit_playwright()`, `_google_trends_playwright()`
7. Rename `_scan_reddit_playwright()` to `scan_reddit()` (it's the only Reddit scanner now)
8. Rename `_google_trends_playwright()` to `scan_google_trends()` (update signature to match)

- [ ] **Step 5: Remove Apify references from scanners/__init__.py**

Check `consensus_engine/scanners/__init__.py` and `consensus_engine/utils/__init__.py` for any Apify imports and remove them.

- [ ] **Step 6: Verify no broken imports**

```bash
cd /root/.openclaw/workspace
python3 -c "from consensus_engine.scanners.social import scan_stocktwits, scan_apewisdom; print('social OK')"
python3 -c "from consensus_engine.scanners.nitter import NitterPoller; print('nitter OK')"
python3 -c "from consensus_engine.scanners.news import news_cascade; print('news OK')"
python3 -c "from consensus_engine.cross_reference import cross_reference; print('xref OK')"
python3 -c "from consensus_engine.alerts.discord import send_instant_ping; print('discord OK')"
```

Expected: All print "OK"

- [ ] **Step 7: Commit**

```bash
cd /root/.openclaw/workspace
git add -A
git commit -m "refactor: remove old consensus pipeline and Apify client

Remove 5-gate consensus.py, old twitter.py scanner, apify_client.py.
Clean up social.py to remove hard-gate evaluation and Apify Reddit."
```

---

## Stream H: Integration

### Task 12: Rewrite Main Loop

**Files:**
- Modify: `consensus_engine/main.py`

- [ ] **Step 1: Rewrite main.py**

Replace `consensus_engine/main.py` with the new signal-first pipeline:

```python
"""Main orchestrator for the OpenClaw Signal Engine.

Pipeline: Nitter RSS poll → LLM tweet parse → instant Discord ping
          → async cross-reference → detail follow-up reply

Usage:
    python3 -m consensus_engine              # Run the full engine
    python3 -m consensus_engine --once       # Run one poll cycle and exit
    python3 -m consensus_engine --status     # Print engine health report
    python3 -m consensus_engine --dry-run    # Run without sending Discord alerts
"""

import asyncio
import logging
import os
import signal
import sys
import time

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.utils import setup_logging
from consensus_engine.scanners.nitter import NitterPoller
from consensus_engine.analysis.tweet_parser import parse_tweet
from consensus_engine.analysis.technical import verify_technical
from consensus_engine.cross_reference import cross_reference
from consensus_engine.alerts.discord import send_instant_ping, send_detail_followup
from consensus_engine.scanners.social import scan_stocktwits, scan_apewisdom
from consensus_engine.models import TickerSignal, SourceType, Sentiment

log = logging.getLogger("consensus_engine")


async def _fetch_price(ticker: str) -> float:
    """Quick Finnhub quote for the instant ping."""
    import aiohttp
    api_key = cfg.get_api_key("finnhub")
    if not api_key:
        return 0.0
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://finnhub.io/api/v1/quote"
            params = {"symbol": ticker, "token": api_key}
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("c", 0.0)
    except Exception:
        pass
    return 0.0


async def process_tweet(raw_tweet: dict):
    """Process a single new tweet through the full pipeline.

    1. Parse with LLM
    2. If actionable: fetch price → send instant ping → async cross-reference → follow-up
    3. If context: store signal for cross-reference enrichment
    """
    tweet = await parse_tweet(
        url=raw_tweet["url"],
        analyst=raw_tweet["analyst"],
        text=raw_tweet["text"],
    )

    if not tweet.is_actionable:
        # Store as context for cross-reference (Type B/D)
        for ticker in tweet.tickers:
            await db.insert_signal(TickerSignal(
                ticker=ticker,
                source_type=SourceType.TWITTER,
                source_detail=tweet.analyst,
                raw_text=tweet.raw_text[:500],
                sentiment=Sentiment.NEUTRAL,
                detected_at=raw_tweet.get("timestamp", time.time()),
            ))
        log.debug("Context tweet from @%s (type=%s): %s",
                  tweet.analyst, tweet.tweet_type.value, tweet.summary[:80])
        return

    # Actionable tweet — process each ticker
    for ticker in tweet.tickers:
        # Store signal
        await db.insert_signal(TickerSignal(
            ticker=ticker,
            source_type=SourceType.TWITTER,
            source_detail=tweet.analyst,
            raw_text=tweet.raw_text[:500],
            sentiment=Sentiment.BULLISH if tweet.direction.value == "long" else
                      Sentiment.BEARISH if tweet.direction.value == "short" else
                      Sentiment.NEUTRAL,
            detected_at=raw_tweet.get("timestamp", time.time()),
        ))

        # Check alert cooldown
        if not await db.check_alert_cooldown(ticker):
            log.debug("Skipping $%s alert: cooldown active", ticker)
            continue

        # Fetch price and send instant ping
        price = await _fetch_price(ticker)
        msg_id = await send_instant_ping(tweet, current_price=price)
        if not msg_id:
            continue

        # Record in DB
        alert_row_id = await db.insert_alert_message(
            ticker=ticker, analyst=tweet.analyst,
            instant_msg_id=msg_id, base_score=tweet.base_score,
        )

        # Async cross-reference (don't block the poll loop)
        asyncio.create_task(
            _run_cross_reference_and_followup(ticker, tweet, msg_id, alert_row_id),
            name=f"xref-{ticker}-{msg_id}",
        )


async def _run_cross_reference_and_followup(ticker: str, tweet, instant_msg_id: str,
                                              alert_row_id: int):
    """Run cross-reference and send detail follow-up (runs as background task)."""
    try:
        xref = await cross_reference(ticker, tweet)

        followup_id = await send_detail_followup(xref, instant_msg_id)
        if followup_id:
            await db.update_alert_message_followup(
                alert_row_id, followup_id, final_score=xref.final_score,
            )

        # Also record in alert_history for status reporting
        import json
        await db.insert_alert(
            ticker=ticker,
            confidence=xref.final_score,
            catalyst=xref.catalyst_summary,
            catalyst_type=xref.catalyst_type,
            consensus_json=json.dumps({"score": xref.final_score}),
            technical_json=json.dumps([
                {"name": f.name, "value": f.value, "passed": f.passed}
                for f in xref.technical.filters
            ] if xref.technical else []),
            analysts_json=json.dumps([tweet.analyst] + xref.other_analysts),
            price=xref.technical.price if xref.technical else 0,
        )

    except Exception as e:
        log.error("Cross-reference error for $%s: %s", ticker, e, exc_info=True)


async def nitter_poll_loop(stop_event: asyncio.Event):
    """Main Nitter polling loop."""
    poller = NitterPoller()

    # Health check on startup
    healthy = await poller.health_check()
    if not healthy:
        log.error("Nitter is not reachable at %s — check Docker container",
                  cfg.get("nitter.base_url", "http://localhost:8585"))
        log.error("Twitter monitoring will not work until Nitter is running")

    while not stop_event.is_set():
        try:
            new_tweets = await poller.poll_all()
            for tweet_data in new_tweets:
                await process_tweet(tweet_data)
        except Exception as e:
            log.error("Nitter poll error: %s", e, exc_info=True)

        interval = poller.get_poll_interval()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def social_scan_loop(stop_event: asyncio.Event):
    """Social scanning loop (StockTwits, ApeWisdom) for cross-reference data."""
    interval = cfg.get("intervals.social_scan", 300)
    while not stop_event.is_set():
        try:
            results = await asyncio.gather(
                scan_stocktwits(), scan_apewisdom(),
                return_exceptions=True,
            )
            all_signals = []
            for r in results:
                if isinstance(r, list):
                    all_signals.extend(r)
                elif isinstance(r, Exception):
                    log.error("Social scanner error: %s", r)

            if all_signals:
                await db.insert_signals(all_signals)
                log.info("Social: stored %d signals", len(all_signals))

        except Exception as e:
            log.error("Social scanner error: %s", e, exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def prune_loop(stop_event: asyncio.Event):
    """Database pruning loop."""
    interval = cfg.get("intervals.state_prune", 900)
    while not stop_event.is_set():
        try:
            await db.prune_expired()
        except Exception as e:
            log.error("Prune error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def run(once: bool = False):
    """Main engine entry point."""
    cfg.load_config()
    global log
    log = setup_logging()

    log.info("=" * 60)
    log.info("OpenClaw Signal Engine starting...")
    log.info("Mode: %s", "single-cycle" if once else "continuous")
    log.info("Nitter: %s", cfg.get("nitter.base_url", "http://localhost:8585"))
    log.info("Accounts: %d analysts", len(cfg.get_twitter_accounts()))
    log.info("=" * 60)

    await db.init_db()

    if once:
        poller = NitterPoller()
        new_tweets = await poller.poll_all()
        for tweet_data in new_tweets:
            await process_tweet(tweet_data)
        # Wait for any background cross-reference tasks
        tasks = [t for t in asyncio.all_tasks() if t.get_name().startswith("xref-")]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await db.close_db()
        log.info("Single cycle complete.")
        return

    # Continuous mode
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    tasks = [
        asyncio.create_task(nitter_poll_loop(stop_event), name="nitter-poller"),
        asyncio.create_task(social_scan_loop(stop_event), name="social-scanner"),
        asyncio.create_task(prune_loop(stop_event), name="pruner"),
    ]

    log.info("All loops started. Monitoring %d analysts...", len(cfg.get_twitter_accounts()))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        await db.close_db()
        log.info("Engine stopped.")


async def print_status():
    """Print engine health report."""
    cfg.load_config()
    await db.init_db()
    conn = await db.get_db()
    now = time.time()

    print("=" * 55)
    print("  OpenClaw Signal Engine \u2014 Status Report")
    print("=" * 55)

    # Database size
    db_path = cfg.get("database.path", "/root/.openclaw/workspace/consensus.db")
    try:
        db_size = os.path.getsize(db_path)
        size_str = f"{db_size / 1_048_576:.1f} MB" if db_size >= 1_048_576 else f"{db_size / 1024:.1f} KB"
    except OSError:
        size_str = "unknown"
    print(f"\n  Database: {db_path} ({size_str})")

    # Active signals
    cursor = await conn.execute(
        """SELECT source_type, COUNT(*) as cnt FROM ticker_signals
           WHERE expires_at > ? GROUP BY source_type ORDER BY cnt DESC""", (now,))
    source_counts = await cursor.fetchall()
    total = sum(r["cnt"] for r in source_counts)
    print(f"\n  Active signals: {total}")
    for row in source_counts:
        print(f"    {row['source_type']:20s} {row['cnt']}")

    # Seen tweets
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM seen_tweets")
    row = await cursor.fetchone()
    print(f"\n  Seen tweets: {row['cnt']}")

    # Recent alerts
    cutoff_24h = now - 86400
    cursor = await conn.execute(
        """SELECT ticker, base_score, final_score, analyst, created_at
           FROM alert_messages WHERE created_at > ? ORDER BY created_at DESC LIMIT 10""",
        (cutoff_24h,))
    alerts = await cursor.fetchall()
    print(f"\n  Alerts (last 24h): {len(alerts)}")
    for a in alerts:
        ago = (now - a["created_at"]) / 60
        print(f"    ${a['ticker']:8s} @{a['analyst']:20s} score={a['final_score'] or a['base_score']}  {ago:.0f}m ago")

    # Nitter poll timing
    cursor = await conn.execute(
        """SELECT value, recorded_at FROM pipeline_metrics
           WHERE metric_name = 'nitter_poll_seconds' ORDER BY recorded_at DESC LIMIT 1""")
    row = await cursor.fetchone()
    if row:
        ago = (now - row["recorded_at"]) / 60
        print(f"\n  Last Nitter poll: {row['value']:.1f}s ({ago:.0f}m ago)")

    print("\n" + "=" * 55)
    await db.close_db()


def main():
    """CLI entry point."""
    once = "--once" in sys.argv
    status = "--status" in sys.argv
    dry_run = "--dry-run" in sys.argv

    if status:
        asyncio.run(print_status())
    else:
        if dry_run:
            cfg.dry_run = True
        asyncio.run(run(once=once))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify imports resolve**

```bash
cd /root/.openclaw/workspace
python3 -c "from consensus_engine.main import main; print('main.py imports OK')"
```

Expected: "main.py imports OK"

- [ ] **Step 3: Commit**

```bash
cd /root/.openclaw/workspace
git add consensus_engine/main.py
git commit -m "feat: rewrite main loop for signal-first pipeline

Nitter poll → LLM parse → instant ping → async cross-reference →
detail follow-up. Replaces old 5-gate consensus loop."
```

---

### Task 13: Integration Test and Final Verification

**Files:**
- Modify: `tests/test_consensus.py` (or replace with integration test)

- [ ] **Step 1: Write integration smoke test**

Create `tests/test_integration.py`:

```python
"""Integration smoke test for the full signal pipeline."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from consensus_engine import db, config as cfg
from consensus_engine.main import process_tweet
from consensus_engine.models import TweetType, Conviction


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()
    cfg.dry_run = True  # Don't hit Discord


@pytest.fixture
async def test_db(tmp_path):
    cfg._config["database"] = {"path": str(tmp_path / "test.db"), "signal_ttl_hours": 2, "alert_history_days": 90}
    await db.init_db()
    yield
    await db.close_db()


@pytest.mark.asyncio
async def test_full_pipeline_actionable_tweet(test_db):
    """An actionable tweet should produce an instant ping and schedule cross-reference."""
    mock_llm_response = json.dumps({
        "type": "A",
        "tickers": ["NVDA"],
        "direction": "long",
        "options": {"present": False},
        "conviction": "high",
        "summary": "NVDA breakout",
    })

    with patch("consensus_engine.analysis.tweet_parser._call_openrouter",
               new_callable=AsyncMock, return_value=mock_llm_response), \
         patch("consensus_engine.main._fetch_price",
               new_callable=AsyncMock, return_value=950.0), \
         patch("consensus_engine.alerts.discord.send_instant_ping",
               new_callable=AsyncMock, return_value="msg_123") as mock_ping, \
         patch("consensus_engine.main._run_cross_reference_and_followup",
               new_callable=AsyncMock) as mock_xref:

        raw = {
            "url": "https://x.com/unusual_whales/status/999",
            "text": "$NVDA breaking out, going long",
            "analyst": "unusual_whales",
            "timestamp": 1711000000.0,
        }
        await process_tweet(raw)

        # Instant ping should have been called
        mock_ping.assert_called_once()
        call_args = mock_ping.call_args
        tweet_arg = call_args[0][0]
        assert tweet_arg.tickers == ["NVDA"]
        assert tweet_arg.base_score == 30

        # Signal should be in DB
        signals = await db.get_twitter_signals("NVDA", 7200)
        assert len(signals) >= 1


@pytest.mark.asyncio
async def test_full_pipeline_context_tweet(test_db):
    """A non-actionable tweet should be stored but not trigger an alert."""
    mock_llm_response = json.dumps({
        "type": "D",
        "tickers": [],
        "direction": "neutral",
        "options": {"present": False},
        "conviction": "low",
        "summary": "Market weak",
    })

    with patch("consensus_engine.analysis.tweet_parser._call_openrouter",
               new_callable=AsyncMock, return_value=mock_llm_response), \
         patch("consensus_engine.alerts.discord.send_instant_ping",
               new_callable=AsyncMock) as mock_ping:

        raw = {
            "url": "https://x.com/user/status/888",
            "text": "Market looking weak into close",
            "analyst": "Walter_Bloomberg",
            "timestamp": 1711000000.0,
        }
        await process_tweet(raw)

        # No ping should have been sent
        mock_ping.assert_not_called()
```

- [ ] **Step 2: Run full test suite**

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/ -v --tb=short
```

Expected: All tests PASS

- [ ] **Step 3: Run a dry-run single cycle**

```bash
cd /root/.openclaw/workspace
python3 -m consensus_engine --dry-run --once
```

Expected: Engine starts, attempts Nitter poll (may fail if Docker not up yet — that's OK), logs output, exits cleanly.

- [ ] **Step 4: Update CLAUDE.md with new commands and architecture**

Update the "What This Is" and "Commands" sections of `CLAUDE.md` to reflect the new signal-first architecture.

- [ ] **Step 5: Final commit**

```bash
cd /root/.openclaw/workspace
git add -A
git commit -m "feat: complete signal-first pipeline integration

Full Nitter → LLM parse → instant ping → cross-reference → follow-up
pipeline. Integration tests passing. Old consensus model removed."
```
