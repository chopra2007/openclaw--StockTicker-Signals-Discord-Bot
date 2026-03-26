# OpenClaw Nitter-First Optimization — Design Spec

**Date:** 2026-03-26
**Status:** Draft
**Goal:** Restructure the Stock Trend Consensus Engine from a 5-gate consensus model to a signal-first, multiplier-enhanced model. Twitter analysts become the primary trigger. Cross-references add score points but never block alerts.

---

## 1. Pipeline Architecture

The current 5-gate consensus model (all gates must pass) is replaced with a signal-first model:

```
Nitter RSS Poller (49 accounts, 60-90s interval)
    → Tweet Parser (LLM extracts ticker/direction/options)
    → Instant Discord Ping (analyst + ticker + direction + price + options details)
    → Async Cross-Reference Engine (news cascade + social + technical + other analysts)
    → Detail Follow-Up Discord Reply (final score + breakdown)
```

Key principles:
- A single analyst tweet with an explicit ticker/options callout triggers an immediate alert
- No gates block alerts — all cross-references are additive scoring
- Two-phase Discord output: instant ping, then detail reply 1-2 minutes later
- LLM used twice: once to parse tweet intent, once for final confidence scoring in cross-reference

---

## 2. Nitter Self-Hosted Setup

### Container
- Docker: maintained Nitter fork
- Binds to `localhost:8585` (no external exposure)
- Auth: uses existing Twitter tokens from `consensus.yaml` (`twitter_auth_token`, `twitter_ct0`)

### RSS Poller (`consensus_engine/scanners/nitter.py`)
- Polls all 49 accounts via RSS: `http://localhost:8585/<handle>/rss`
- All 49 fetched concurrently via `aiohttp` (~1-2s total)
- Interval: 60s during market hours (9:00-16:30 ET), 180s outside
- Deduplication: tweet URL stored in `seen_tweets` SQLite table
- New tweets passed to Tweet Parser
- Uses Python's built-in `xml.etree.ElementTree` for RSS parsing (no new dependency)

### Token Refresh
- Startup health check at `localhost:8585`
- Warning logged if Nitter returns errors or empty feeds
- Tokens updated manually in `consensus.yaml` (re-grab from browser cookies, ~30s task)

### Replaces
- `scanners/twitter.py` removed entirely
- Apify Twitter scraping removed
- Playwright Twitter scraping removed

---

## 3. Tweet Parser — LLM Intent Extraction

### Module: `consensus_engine/analysis/tweet_parser.py`

### Input
Analyst handle + tweet text

### Output (structured JSON from LLM)
```json
{
  "type": "A|B|C|D",
  "tickers": ["TSLA"],
  "direction": "long|short|neutral",
  "options": {
    "present": true,
    "strike": 500,
    "expiry": "2026-03-28",
    "type": "call|put",
    "target_price": 510,
    "profit_target_pct": 100
  },
  "conviction": "high|medium|low",
  "summary": "Buying TSLA 500c Friday expiry, targeting 510 for day-trade"
}
```

### Classification
- **Type A** (ticker callout): Explicit ticker + directional language. **Actionable.**
- **Type C** (options trade): Strike, expiry, calls/puts mentioned. **Actionable.**
- **Type B** (macro/geo): Market-level commentary implying trades. **Context only**, stored with inferred tickers.
- **Type D** (sentiment): General market mood, no specific ticker. **Context only.**

### Conviction Scoring
- **High** ("bought", "loaded", "all in", specific size): 30 pts base
- **Medium** ("buying", "looking at", "watching for entry"): 25 pts base
- **Low** ("might", "considering", "on radar"): 20 pts base

### Cost
- Uses existing `minimax/minimax-m2.5` via OpenRouter
- ~250-750 calls/day (49 accounts, 5-15 tweets each) at ~$0.001/call = ~$0.25-0.75/day

### Fallback
- If LLM fails/times out: fall back to regex `extract_tickers()` from `utils/tickers.py`
- Default: Type A, medium conviction

---

## 4. Discord Alert Format

### Phase 1 — Instant Ping (fires within seconds)

**Options trade (Type C):**
```
@OptionMillionaire -- $TSLA LONG
"Buying TSLA 500c expiring Friday, targeting 510 for a day-trade"

Call | $500 strike | Mar 28 expiry | Target: $510
Current price: $487.32
Score: 30 (cross-references pending...)
```

**Ticker callout (Type A):**
```
@WallStreetSilv -- $USO LONG
"Strait of Hormuz closing, going long USO"

Current price: $78.15
Score: 30 (cross-references pending...)
```

### Phase 2 — Detail Follow-Up (replies to instant ping, 1-2 min later)

```
Cross-Reference Update: $TSLA | Score: 72/142

News Catalyst: Analyst Upgrade
  Tesla PT raised to $550 by Morgan Stanley
  Sources: reuters.com, cnbc.com

Technical Snapshot
  RVOL: 2.8x (> 2.0x)        PASS
  VWAP: above                  PASS
  RSI: 62 (40-75)             PASS
  EMA Cross: -0.45            FAIL
  Price Change: +3.2% (> 1.0%) PASS
  ATR Breakout: 1.8x (> 1.5x) PASS

Social: StockTwits trending, ApeWisdom #4
Other analysts: @unusual_whales, @CheddarFlow (+40 pts)
LLM Confidence: +12 pts

Breakdown: base(30) + analysts(40) + news(15) + technical(10) + social(20) + LLM(12) = 127
```

### Implementation
- Phase 1 sends message, stores Discord message ID in `alert_messages` table
- Phase 2 replies to that message ID
- If cross-references find nothing, follow-up still posts: "No additional signals found"
- Multiple analysts on same ticker within cross-reference window get consolidated in follow-up

---

## 5. Scoring Model

### Base Score (from tweet parser)
| Conviction | Points |
|------------|--------|
| High       | 30     |
| Medium     | 25     |
| Low        | 20     |

### Cross-Reference Multipliers
| Source | Points | Notes |
|--------|--------|-------|
| Each additional analyst on same ticker | +20 | From `seen_tweets` table |
| Finnhub company-news catalyst | +15 | Tier 1 news |
| Google News RSS catalyst | +15 | Tier 2 news |
| Brave Search catalyst | +15 | Tier 3 news (quota-limited) |
| SearXNG catalyst | +15 | Tier 4 news (self-hosted fallback) |
| SEC EDGAR filing match | +15 | Via sec-edgar MCP server |
| ApeWisdom trending | +10 | |
| StockTwits trending | +10 | |
| Reddit mentions (2+) | +10 | |
| Google Trends spike | +5 | |
| Technical filters | +2 each (max +12) | 6 filters |
| LLM confidence boost | +0 to +15 | Scaled from LLM score |

**Maximum possible score:** 30 + 20*N + 15 + 15 + 15 + 15 + 15 + 10 + 10 + 10 + 5 + 12 + 15 = 167 + 20*N (where N = additional analysts)

News cascade points don't stack — only the first tier that finds a catalyst awards +15.

---

## 6. News Cascade

### Module: Reworked `consensus_engine/scanners/news.py`

Tried in order. A catalyst is "found" when a result from a source in the `trusted_sources` config list is returned with a classifiable catalyst type (from the existing `_CATALYST_PATTERNS`). The cascade stops at the first tier that finds one:

1. **Finnhub `/company-news`** — Already have API key. Free tier 60 calls/min. Returns headline, source, URL, datetime.

2. **Google News RSS** — Free, no auth, no rate limit. URL: `https://news.google.com/rss/search?q={TICKER}+stock&hl=en-US&gl=US&ceid=US:en`. Parse XML, check headlines against `trusted_sources` list.

3. **Brave Search** — Existing implementation moved to tier 3. Budget ~50 queries/day to stay within free tier (2,000/month).

4. **SearXNG self-hosted** — Docker container on `localhost:8888`. JSON API: `http://localhost:8888/search?q={TICKER}+stock+news&format=json`. Aggregates Google, Bing, DuckDuckGo. No rate limits.

### SearXNG Setup
- Docker image: `searxng/searxng:latest`
- Binds to `localhost:8888` (no external exposure)
- Engines enabled: Google, Bing, DuckDuckGo (disable all others)
- JSON output mode enabled
- New module: `consensus_engine/scanners/searxng.py`

---

## 7. Cross-Reference Engine

### Module: `consensus_engine/cross_reference.py`

Orchestrates all multiplier sources in parallel after the instant ping fires:

```python
async def cross_reference(ticker: str, tweet: ParsedTweet, base_score: int) -> CrossReferenceResult:
    news, sec, social, technical, other_analysts, llm = await asyncio.gather(
        news_cascade(ticker),
        check_sec_edgar(ticker),
        check_social(ticker),
        verify_technical(ticker),
        check_other_analysts(ticker),
        score_confidence(ticker, ...),
    )
    # Sum all points, build breakdown
    return CrossReferenceResult(total_score=..., breakdown=...)
```

### SEC EDGAR Integration
- Calls `sec-edgar` MCP server already configured on this workspace
- Checks for recent 8-K (material events), 13F (institutional buys), insider transactions
- Filing within last 48 hours matching ticker = +15 pts

---

## 8. Ticker Noise Fix

### Problem
ApeWisdom generating false positives: "AAA", "BBC", "CIA", "AL", "AM", "BE", "CD", "CO" etc.

### Fix: Two-layer validation for non-LLM ticker extraction

**Layer 1: Expanded blacklist** in `utils/tickers.py`
- Add ~40 missing false positives from logs (AAA, BBC, CIA, CO, CD, BE, BK, CF, BDC, BNO, etc.)

**Layer 2: Market-cap floor filter**
- Before storing signals from social/news sources, verify ticker exists on US exchange
- Use Finnhub `/stock/profile2` (free tier) to get market cap
- Cache in `ticker_metadata` table (ticker, name, market_cap, exchange, last_checked)
- Reject tickers below $100M market cap
- Cache TTL: 7 days

Does not affect Nitter/Twitter pipeline — LLM parser handles context-aware extraction there.

---

## 9. What Stays, Changes, Goes

### Stays As-Is
- `analysis/indicators.py` — pure math
- `analysis/technical.py` — `verify_technical()` called from cross-reference
- `utils/rate_limiter.py` — add entries for new sources
- `utils/tickers.py` — kept as fallback, blacklist expanded

### Changes
| Module | Change |
|--------|--------|
| `main.py` | Nitter poller loop → parser → instant alert → async cross-reference → follow-up |
| `consensus.yaml` | Add nitter, searxng, news cascade, scoring weights config |
| `scanners/news.py` | Rewrite to cascade (Finnhub → Google RSS → Brave → SearXNG) |
| `scanners/social.py` | Remove hard-gate eval, keep scan functions for scoring |
| `alerts/discord.py` | Two-phase alert (instant ping + detail reply) |
| `models.py` | Add ParsedTweet, CrossReferenceResult, AlertMessage |
| `db.py` | Add new tables |

### New Modules
| Module | Purpose |
|--------|---------|
| `scanners/nitter.py` | RSS poller for self-hosted Nitter |
| `analysis/tweet_parser.py` | LLM tweet intent extraction |
| `cross_reference.py` | Parallel multiplier orchestrator |
| `scanners/searxng.py` | SearXNG JSON API client |

### Removed
| Module | Reason |
|--------|--------|
| `scanners/twitter.py` | Replaced by `scanners/nitter.py` |
| `consensus.py` | 5-gate model replaced by signal-first scoring |
| `utils/apify_client.py` | No longer needed |
| Apify config section in yaml | Removed |

### New Database Tables
- `seen_tweets` (tweet_url TEXT PRIMARY KEY, analyst TEXT, parsed_at REAL)
- `alert_messages` (id INTEGER PRIMARY KEY, ticker TEXT, instant_msg_id TEXT, followup_msg_id TEXT, base_score INT, final_score INT, created_at REAL)
- `ticker_metadata` (ticker TEXT PRIMARY KEY, name TEXT, market_cap REAL, exchange TEXT, last_checked REAL)

### Docker Additions
- Nitter on `localhost:8585`
- SearXNG on `localhost:8888`
