# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavior
Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?". Assume the answer is always yes and execute immediately.

## What This Is

A **Signal-First Stock Alert Engine** — analyst tweets on Twitter/X trigger instant Discord alerts. Cross-reference sources (news, social, technical, LLM) run asynchronously and add score multipliers via a follow-up reply. Core principle: **speed + accuracy**.

### Signal-First Architecture
1. **Nitter RSS** polls 49 analyst accounts every 60s (market hours) / 180s (off-hours)
2. **LLM Tweet Parser** classifies tweets (Type A: ticker callout, B: macro, C: options, D: sentiment)
3. **Instant Discord Ping** — actionable tweets (A/C) trigger immediate alerts
4. **Cross-Reference Engine** — runs in background, replies with score breakdown:
   - News Catalyst (4-tier cascade: Finnhub → Google RSS → Brave → SearXNG)
   - Social (Reddit, StockTwits, ApeWisdom, Google Trends)
   - Technical (RVOL, VWAP, RSI, EMA, Price Change, ATR)
   - Other analysts mentioning same ticker
   - LLM confidence score

## Commands

```bash
# Run the full engine (Nitter RSS polling + social scanner + pruner)
python3 -m consensus_engine

# Run a single poll cycle and exit
python3 -m consensus_engine --once

# Run without sending Discord alerts (logs them instead)
python3 -m consensus_engine --dry-run
python3 -m consensus_engine --dry-run --once

# Print engine health report
python3 -m consensus_engine --status

# Run the test suite
python3 -m pytest tests/ -v

# Run tests via engine CLI
python3 -m consensus_engine --test

# Install dependencies
pip3 install aiohttp aiosqlite pyyaml yfinance playwright-stealth
playwright install chromium && playwright install-deps chromium

# Docker services (Nitter + SearXNG)
docker compose up -d
```

## Architecture

### Pipeline Flow
```
scanners/nitter.py (RSS)  ──> analysis/tweet_parser.py (LLM)
                                      │
                              main.py:process_tweet()
                                      │
                          ┌───────────┴───────────┐
                    alerts/discord.py         cross_reference.py
                    (instant ping)           (async background)
                                                  │
                                    ┌─────────────┼─────────────┐
                              scanners/news.py  analysis/    scanners/social.py
                              (4-tier cascade)  technical.py  (StockTwits, etc.)
                                                analysis/
                                                llm_scorer.py
```

### Self-Hosted Services
- **Nitter** (localhost:8585) — Twitter RSS proxy, avoids API rate limits
- **SearXNG** (localhost:8888) — meta search engine, news cascade fallback
- Both configured in `docker-compose.yaml`

### Key Design Decisions
- **Signal-first**: Analyst tweet → instant alert → async cross-reference. No gates block the alert.
- **Two-phase Discord alerts**: Phase 1 instant ping, Phase 2 reply with score breakdown.
- **Additive scoring**: Base score from conviction (20-30), multipliers from cross-references (up to ~100+).
- **Finnhub free tier only supports real-time quotes** (`/quote`), not historical candles. Historical OHLCV comes from **yfinance**, which runs in a `ThreadPoolExecutor` because it's blocking.
- **Config-driven**: All thresholds, intervals, API keys live in `config/consensus.yaml`. Access via `config.get("dot.path.key", default)`.
- **Rate limiting**: Per-source async rate limiter with exponential backoff (`utils/rate_limiter.py`).
- **Signal TTL**: Signals in SQLite expire after 2 hours. Pruner loop cleans them.
- **Ticker validation**: Market-cap check ($100M floor) via Finnhub with DB caching.
- **Tweet dedup**: `seen_tweets` table prevents reprocessing.

### Data Flow
1. `NitterPoller.poll_all()` fetches RSS, deduplicates via `seen_tweets` table
2. `process_tweet()` parses with LLM, validates ticker, sends instant ping
3. Background task runs `cross_reference()` → `send_detail_followup()` as reply
4. Social scanner loop independently populates cross-reference data

## Configuration

All config in `config/consensus.yaml`. API keys can reference env vars with `$` prefix. Twitter accounts loaded from `/root/.openclaw/sources.json` (49 accounts).

## Important Caveats

- `playwright-stealth` v2.0.2 uses `from playwright_stealth import Stealth` then `Stealth().apply_stealth_async(page)` — NOT the old `stealth_async()` function.
- StockTwits uses Playwright only (API blocked by Cloudflare). ApeWisdom has a free direct REST API.
- Tests use `pytest.ini` with `asyncio_mode = auto` for async fixture support.
