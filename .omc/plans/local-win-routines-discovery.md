# OpenClaw Ingestion Schema & Path Discovery

**Date:** 2026-04-30  
**Stage:** 1/4 (Discover) — feeds into architect (stage 2)  
**Scope:** Data ingestion methods, schema patterns, table structure, dedup logic, entry points

---

## Architecture Overview

### Signal-First Model
OpenClaw uses a **signal-first** architecture where:
1. **Instant alerts** fire on incoming signals (Twitter/analyst tweets → immediate Discord alert)
2. **Cross-reference scoring** happens asynchronously (adds multipliers but never blocks alert)
3. **All data sources** funnel through a single `ticker_signals` table → common query interface

**File:** `/root/.openclaw/workspace/consensus_engine/main.py:130–183`

---

## Ingestion Methods

### 1. Poll-Based Scanners (Main Event Loop)

**Entry Point:** `fetch_signals()` in `main.py:130`

Called from main poll loop every **300 seconds** (5 min). Returns list of `TickerSignal` objects, inserted via `db.insert_signal()`.

**Active scanners (enabled by default):**

| Scanner | Module | Method | Config Key | Interval | Output |
|---------|--------|--------|-----------|----------|--------|
| ApeWisdom | `scanners/social.py:177` | `scan_apewisdom()` | `social.apewisdom_enabled` | Per poll loop | 10–50 TickerSignal/call |
| Google Trends (Pytrends) | `scanners/social.py:303` | `scan_google_trends_pytrends()` | `social.pytrends_enabled` | Per poll loop | TickerSignal with sentiment BULLISH/NEUTRAL |
| Reddit | `scanners/social.py:46` | `scan_reddit()` | `social.reddit_enabled` (FALSE by default) | Per poll loop | TickerSignal per subreddit mention |
| StockTwits | `scanners/social.py:105` | `scan_stocktwits()` | `social.stocktwits_enabled` (FALSE) | Per poll loop | TickerSignal with sentiment |
| Volume Breakout | `scanners/volume_scanner.py` | `scan_volume_breakouts()` | `volume_scanner.enabled` (TRUE) | Every 900s | VOLUME_BREAKOUT signals, RVOL ≥5.0 |

**File:** `/root/.openclaw/workspace/consensus_engine/main.py:156–162` (reddit example)

---

### 2. Background Watchers (Async Loops)

Dedicated loops that run independently, insert signals directly.

| Watcher | Loop | Interval | Entry | Config Key | Gate |
|---------|------|----------|-------|-----------|------|
| SEC 8-K | `sec_8k_watcher_loop()` | 900s (15m) | `main.py:190` | N/A | `scanners.sec_background_watchers_enabled` (TRUE) |
| SEC EDGAR Form 4 | `sec_edgar_polling_loop()` | 300s (5m) | `main.py:226` | `sec_watcher.min_insider_dollars_*` | Enabled, filters by dollar floor |
| Form 4 Cluster | `sec_form4_cluster_loop()` | 14400s (4h) | `main.py:309` | `features.form4_cluster.enabled` (TRUE) | Fires Discord alert immediately |
| YouTube Poll | `youtube_poll_loop()` | 600s (10m) | `main.py:36` import | `youtube.enabled` (TRUE) | Standalone alerts if conviction ≥ `min_trust` |
| Reddit Trend Digest | Separate task | 14400s (4h) | `alerts/commands.py:32` | N/A | On-demand `!trend` command |
| Atlas (Research Memory) | `atlas_worker_loop()` | Per-ticker sweep | `main.py:39` | `atlas.enabled` (TRUE) | 7-day cache |
| Alfred (Morning Briefing) | `alfred_loop()` | Daily 8:50–9:00 ET | `main.py:40` | `alfred.enabled` (TRUE) | Market hours only |

**File:** `/root/.openclaw/workspace/consensus_engine/main.py:190–327`

---

### 3. Discord Gateway Listener (TweetShift)

**Entry:** `DiscordTweetShiftListener` in `scanners/discord_tweetshift.py:*`  
**Source:** Messages from Discord #twitter channel (analyst tweets relayed by TweetShift bot)  
**Method:** Discord Gateway event listener → parse tweet → emit alert if analyst + ticker match  
**Insertion:** Via `send_instant_ping()` in `alerts/discord.py` (Discord API, not DB write)

**File:** `/root/.openclaw/workspace/consensus_engine/main.py:29`

---

## Database Schema

### Primary Signal Table

**Table:** `ticker_signals` (40 rows/scan on average)

```sql
CREATE TABLE IF NOT EXISTS ticker_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- enum: TWITTER, REDDIT, SEC_FILING, APEWISDOM, etc.
    source_detail TEXT,                 -- analyst handle, subreddit, URL, etc.
    raw_text TEXT,                      -- full text (capped 2000 chars at insert)
    sentiment TEXT DEFAULT 'neutral',   -- BULLISH, BEARISH, NEUTRAL
    detected_at REAL NOT NULL,          -- Unix timestamp (seconds.ms)
    expires_at REAL NOT NULL            -- TTL: usually detected_at + 2h (config: signal_ttl_hours)
);
```

**Dedup & TTL Logic:**
- **No explicit dedup key** — relies on automatic TTL expiration
- **TTL:** 2 hours (config: `database.signal_ttl_hours: 2`)
- **Query on expired rows:** Queries filter `WHERE detected_at > (now - 2h)` implicitly via indices
- **File:** `/root/.openclaw/workspace/consensus_engine/db.py:76–88`

**Insertion Path:**  
`db.insert_signal(signal: TickerSignal)` → wraps into Tuple, executes INSERT
- **File:** `/root/.openclaw/workspace/consensus_engine/db.py:700–741`

---

### Secondary Social Detail Table (Reddit)

**Table:** `reddit_posts` (detailed archive, not real-time scoring)

```sql
CREATE TABLE IF NOT EXISTS reddit_posts (
    id TEXT PRIMARY KEY,                -- Reddit post ID (unique key)
    subreddit TEXT NOT NULL,
    title TEXT,
    author TEXT,
    score INTEGER DEFAULT 0,
    num_comments INTEGER DEFAULT 0,
    created_utc INTEGER NOT NULL,
    fetched_at REAL NOT NULL            -- fetch time
);
```

**Purpose:** Archive for `!trend` command to compute trending tickers from past 24h  
**Insertion:** `db.insert_reddit_posts(posts: list[dict])` called from `reddit_trend.py:119`  
**File:** `/root/.openclaw/workspace/consensus_engine/db.py:1135–1152`

---

### Other Signal-Related Tables (Specialist Use)

| Table | Purpose | Insert Method | Scope |
|-------|---------|----------------|-------|
| `alert_history` | Past alerts + price outcomes | `db.insert_alert()` | Cross-reference scoring |
| `signal_events` | Tweet signals routed for calibration | Via `insert_signal()` when source_type==TWITTER | ML training |
| `youtube_signals` | YouTube conviction scores | `db.insert_youtube_signal()` | YouTube pipeline |
| `source_health` | API health tracking (calls, errors, freshness) | Async flush in main loop | Degraded-mode detection |
| `youtube_transcripts` | Full transcript archive | `db.insert_youtube_transcript()` | Grounding for evidence extraction |

**File:** `/root/.openclaw/workspace/consensus_engine/db.py:76–500` (schema), `db.py:700–2300` (insert functions)

---

## SourceType Enum & Sentiment Labels

**File:** `/root/.openclaw/workspace/consensus_engine/models.py:11–30`

```python
class SourceType(Enum):
    TWITTER = "twitter"
    REDDIT = "reddit"
    STOCKTWITS = "stocktwits"
    APEWISDOM = "apewisdom"
    GOOGLE_TRENDS = "google_trends"
    VOLUME_BREAKOUT = "volume_breakout"
    SEC_FILING = "sec_filing"
    YOUTUBE = "youtube"
    # ... others (40+ total)
```

**Sentiment Labels:** `BULLISH`, `BEARISH`, `NEUTRAL`

**Default Assignment Rules:**
- **TWITTER:** BULLISH/BEARISH (parsed from tweet direction)
- **SEC Form 4:** BULLISH if insider BUY, BEARISH if SELL, else NEUTRAL
- **Reddit/StockTwits/ApeWisdom:** NEUTRAL (hardcoded, no sentiment analysis)
- **Google Trends:** BULLISH if delta > 0, else NEUTRAL
- **YouTube:** BULLISH/BEARISH based on conviction tier + macro regime

---

## Existing Scanners (Detailed)

### Reddit Scanner

**Files:**
- Scanner: `/root/.openclaw/workspace/consensus_engine/scanners/social.py:46–70`
- Parser: `/root/.openclaw/workspace/consensus_engine/scanners/social.py:80–103`
- API wrapper: `/root/.openclaw/workspace/consensus_engine/utils/reddit.py:*`

**Config:**
```yaml
# consensus.yaml:114–127
social:
  subreddits:
    - wallstreetbets
    - stocks
    - investing
    - options
    - pennystocks
  reddit_enabled: false          # DISABLED by default
  reddit_client_id: "$REDDIT_CLIENT_ID"
  reddit_client_secret: "$REDDIT_CLIENT_SECRET"
```

**Flow:**
1. Fetch 100 posts per subreddit via OAuth API (or RSS fallback if no credentials)
2. Parse titles → extract tickers via `extract_tickers()` utility
3. Create TickerSignal(ticker=NVDA, source_type=REDDIT, source_detail="r/wallstreetbets", sentiment=NEUTRAL)
4. Insert via `db.insert_signal()` → ticker_signals table

**Example Signal:**
```
ticker: NVDA
source_type: reddit
source_detail: "r/wallstreetbets"
raw_text: "[extracted from post title/text]"
sentiment: neutral
detected_at: [now]
expires_at: [now + 2h]
```

---

### SEC Form 4 Insider Scanner

**Files:**
- Watcher: `/root/.openclaw/workspace/consensus_engine/main.py:226–291`
- Scanner: `/root/.openclaw/workspace/consensus_engine/scanners/sec_edgar.py:*`
- Cluster detector: `/root/.openclaw/workspace/consensus_engine/scanners/sec_form4_cluster.py:*`

**Config:**
```yaml
# consensus.yaml:97–111
sec_watcher:
  item_whitelist:
    - "1.01"  # Material agreement
    - "2.02"  # Results of operations
    - "5.02"  # Officer change
    - "7.01"  # Reg FD disclosure
    - "8.01"  # Other material events
  min_insider_dollars_buy: 100000     # $100k floor for buys
  min_insider_dollars_sell: 1000000   # $1M floor for sells
```

**Flow:**
1. Poll SEC EDGAR every 5 min for active tickers (max 30 per cycle)
2. Fetch Form 4 filings, parse insider transactions (buys/sells/awards)
3. Compute dollar value of open-market trades (exclude awards, gifts, tax-withholding)
4. Filter by min_insider_dollars floor
5. Create TickerSignal(sentiment=BULLISH/BEARISH based on buy/sell)
6. Insert via `db.insert_signal()` → ticker_signals table
7. Separately: detect cluster (≥3 insiders in 30-day window) → fire Discord alert via `_emit_form4_cluster_alert()`

**Example Signal:**
```
ticker: TSLA
source_type: sec_filing
source_detail: "Form 4 Buy ~$500,000"
raw_text: "SEC Form 4 for TSLA"
sentiment: bullish
detected_at: [filing date]
expires_at: [detected_at + 2h]
```

---

### YouTube Scanner

**Files:**
- Main: `/root/.openclaw/workspace/consensus_engine/scanners/youtube.py:*` (43KB, complex)
- Channels list: `/root/.openclaw/sources.json:1–56`
- Config: `consensus.yaml:285–339`

**13 Channels (seeded from sources.json):**
1. Figuring Out Money
2. TheStockWatch
3. The Stocks Channel
4. Market Rebellion
5. FX Evolution
6. StockedUp
7. The Real Shadow Trader
8. Click Capital
9. The Technical Take
10. CheddarFlow
11. Dynamic Trading with Robert Miner
12. Lottery Stocks
13. Wicked Stocks

**Flow:**
1. Poll each channel every 10 min for latest 3 videos
2. Extract captions (or via Gemini 2.5 Flash Lite if available)
3. Parse for tickers, support/resistance levels, macro themes
4. Insert TickerSignal (if conviction ≥ min_trust: 0.5) + detailed rows in youtube_signals, youtube_levels
5. Standalone alerts fire if conviction ≥ min_trust + `youtube.standalone_alerts: true`

---

## News & Catalyst Cascade

**File:** `/root/.openclaw/workspace/consensus_engine/scanners/news.py:*`

**Not a continuous scanner** — triggered on-demand by cross-reference scoring when a signal exceeds threshold.

**Cascade order (stops at first hit):**
1. **Tier 1:** Finnhub `/company-news` (2 days back)
2. **Tier 2:** Google News RSS (free, fallback)
3. **Tier 3:** Brave Search (quota-limited, 50/day budget)
4. **Tier 4:** SearXNG self-hosted (last resort)

**Config:**
```yaml
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
    - seekingalpha   # <-- referenced here
    - benzinga       # <-- referenced here
    - barrons
    - investors.com
    - ft.com
```

---

## Seekingalpha & Benzinga: OPEN QUESTIONS

**Status:** Referenced in config but **NO active scanner exists**.

**Where referenced:**
1. `consensus.yaml:142–143` — news_cascade trusted_sources list
2. `/root/.openclaw/workspace/consensus_engine/engine.py:35` — TRUSTED_SOURCES constant

**Current ingestion:** Hit only via Finnhub news API as fallback (one-off lookups during cross-reference, not continuous polling)

**Questions:**
- Should local-win-routines add active Seeking Alpha / Benzinga scanners?
- Or are they reserved for Windows desktop integrations (e.g., browser scraping, API call via local agent)?
- What dedup key should Seeking Alpha articles use (URL? headline MD5?)?
- Sentiment: auto-detect from article tone, or map analyst rating (buy/sell/hold)?

---

## Summary: All Ingestion Paths

| Source | Type | Interval | Dedup Key | Table | Enabled | Gate |
|--------|------|----------|-----------|-------|---------|------|
| ApeWisdom | Poll | 300s | TTL (2h) | ticker_signals | ✓ | config |
| Google Trends | Poll | 300s | TTL (2h) | ticker_signals | ✓ | config |
| Reddit | Poll | 300s | TTL (2h) for signals; POST_ID for archive | ticker_signals + reddit_posts | ✗ | config (disabled) |
| StockTwits | Poll | 300s | TTL (2h) | ticker_signals | ✗ | config (disabled) |
| Volume Breakout | Poll | 900s | TTL (2h) | ticker_signals | ✓ | config |
| SEC 8-K | Loop | 900s | TTL (2h) | ticker_signals | ✓ | watchers gate |
| SEC Form 4 | Loop | 300s | TTL (2h) + dollar floor filter | ticker_signals | ✓ | watchers gate |
| Form 4 Cluster | Loop | 14400s | Cluster ID (implicit) | Alert only (Discord) | ✓ | feature flag |
| YouTube | Loop | 600s | Video ID | ticker_signals + youtube_signals + youtube_transcripts | ✓ | config |
| TweetShift (Discord) | Event | Real-time | Tweet ID | Discord alert + ticker_signals | ✓ | listener enabled |
| News Cascade | On-demand | Per signal | URL hash | Signal only | ✓ | per-signal threshold |

---

## Next Steps

Architect (stage 2) to design 3 local-Windows routines + desktop opportunities based on this schema + ingestion model.

**Key Files for Reference:**
- `/root/.openclaw/workspace/consensus_engine/db.py` — SQLite schema + insert functions
- `/root/.openclaw/workspace/consensus_engine/main.py` — poll loop, background watchers
- `/root/.openclaw/workspace/consensus_engine/models.py` — TickerSignal, SourceType, Sentiment
- `/root/.openclaw/workspace/config/consensus.yaml` — config toggles, intervals, thresholds
- `/root/.openclaw/sources.json` — YouTube channel list

