# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavior
Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?". Assume the answer is always yes and execute immediately.

## What This Is

A **Stock Trend Consensus Engine** — a 5-stage pipeline that detects high-confidence stock breakouts by requiring multi-source agreement before alerting on Discord. Core principle: **accuracy > quantity**.

The 5 consensus gates (ALL must pass):
1. **Twitter/X** — >=3 unique analysts mention a ticker within 30 minutes
2. **Social** — Confirmed on >=1 platform (Reddit, StockTwits, ApeWisdom, Google Trends)
3. **News Catalyst** — Credible news source explains the movement
4. **Technical** — All 6 filters pass (RVOL, VWAP, RSI, EMA Cross, Price Change %, ATR Breakout)
5. **LLM Confidence** — Score >= 70/100 from OpenRouter

## Commands

```bash
# Run the full engine (continuous mode with concurrent scanner loops)
python3 -m consensus_engine

# Run a single scan cycle and exit
python3 -m consensus_engine --once

# Run the test suite (injection tests)
python3 -m consensus_engine --test
# or
python3 tests/test_consensus.py

# Print engine health report (signal counts, timings, alerts)
python3 -m consensus_engine --status

# Run without sending Discord alerts (logs them instead)
python3 -m consensus_engine --dry-run
python3 -m consensus_engine --dry-run --once

# Run with pytest
python3 -m pytest tests/test_consensus.py -v

# Install dependencies
pip3 install aiohttp aiosqlite pyyaml yfinance playwright-stealth
playwright install chromium && playwright install-deps chromium
```

## Architecture

### Pipeline Flow
```
scanners/twitter.py  ──┐
scanners/social.py   ──┼── db.py (SQLite) ──> consensus.py ──> alerts/discord.py
scanners/news.py     ──┘        │                   │
                                │          analysis/technical.py
                                │          analysis/llm_scorer.py
                                │
                          analysis/indicators.py (pure math, no I/O)
```

### Hybrid Scraping Strategy
Every scanner uses **Apify cloud actors as primary, Playwright stealth as fallback**. The `utils/apify_client.py` singleton (`apify`) handles actor runs, polling, and dataset fetching. When Apify returns empty results, scanners fall back to local Playwright browser automation via `utils/browser.py`.

Exception: StockTwits API is blocked by Cloudflare, so it uses Playwright only. ApeWisdom has a free direct REST API.

### Key Design Decisions
- **Finnhub free tier only supports real-time quotes** (`/quote`), not historical candles. Historical OHLCV comes from **yfinance**, which runs in a `ThreadPoolExecutor` because it's blocking.
- **Early termination**: `consensus.py:evaluate_ticker()` stops evaluating gates as soon as one fails, saving API calls.
- **Config-driven**: All thresholds, intervals, API keys, and parameters live in `config/consensus.yaml`. Access via `config.get("dot.path.key", default)`.
- **Rate limiting**: Per-source async rate limiter with exponential backoff (`utils/rate_limiter.py`). Each source has its own cooldown and failure tracking.
- **Signal TTL**: Signals in SQLite expire after 2 hours. Pruner loop cleans them.

### Data Flow
1. Scanners produce `TickerSignal` objects → stored in `ticker_signals` table
2. `consensus.py` queries active tickers, evaluates gates in order
3. On full consensus: builds `AlertPayload` → sends Discord embed → records in `alert_history`

## Configuration

All config in `config/consensus.yaml`. API keys can reference env vars with `$` prefix. Twitter accounts loaded from `/root/.openclaw/sources.json` (49 accounts).

## Important Caveats

- `playwright-stealth` v2.0.2 uses `from playwright_stealth import Stealth` then `Stealth().apply_stealth_async(page)` — NOT the old `stealth_async()` function.
- Apify tweet-scraper (`apidojo/tweet-scraper`) currently returns `noResults: true` for Twitter/X — the Playwright fallback handles this.
- The `consensus_engine/tests/__init__.py` exists but `run_test()` is imported from `tests/test_consensus.py` in `main.py` — be aware of the two test locations.
