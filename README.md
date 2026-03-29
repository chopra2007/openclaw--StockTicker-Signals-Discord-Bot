# OpenClaw — Signal-First Stock Alert Engine

Analyst tweets on Twitter/X trigger instant Discord alerts. Cross-reference sources (news, social, technical, SEC filings, options flow, LLM confidence) run asynchronously and post a score breakdown as a follow-up reply. Core principle: **speed + accuracy**.

---

## Architecture

```
TweetShift (Discord Gateway)
    |
    v
tweet_parser.py (LLM classify: A=ticker, B=macro, C=options, D=sentiment)
    |
    v
Quality Gate (ticker validation, market-cap $100M floor, min score, conviction check)
    |
    v
+----------------------------+------------------------------------+
|                            |                                    |
v                            v                                    |
alerts/discord.py      cross_reference.py (background)            |
(Phase 1: instant ping)     |                                    |
                             +--------+--------+--------+----+    |
                             |        |        |        |    |    |
                             v        v        v        v    v    |
                          news.py  technical  social  sec   opts  |
                          (4-tier)  .py       .py    edgar  .py   |
                                                     .py         |
                             +--------+--------+--------+----+    |
                             |                                    |
                             v                                    |
                       llm_scorer.py (confidence boost)           |
                             |                                    |
                             v                                    |
                       alerts/discord.py                          |
                       (Phase 2: score reply)                     |
                             |                                    |
                             v                                    |
                       price_followup_loop (1h + 24h tracking) <--+
```

**Tweet ingestion** is handled by TweetShift, a third-party bot that mirrors analyst tweets into a designated Discord channel. The engine connects to the Discord Gateway, intercepts those messages, and feeds them into the pipeline. Nitter RSS polling is available as a fallback but currently disabled.

---

## Features

### Signal Pipeline
- **Two-phase Discord alerts** — Phase 1 instant ping with ticker/direction/price, Phase 2 reply with full score breakdown
- **Quality gate** — blocks low-quality signals before alerting (ticker validation, conviction check, minimum base score, text length)
- **LLM tweet parser** — classifies tweets into 4 types via OpenRouter; extracts tickers, direction (long/short/neutral), conviction, and options details

### Cross-Reference Sources
- **News catalyst** — 4-tier cascade: Finnhub company news, Google News RSS, Brave Search, self-hosted SearXNG
- **SEC EDGAR** — checks for recent 8-K, 10-K, 10-Q, Form 4, SC 13D/G filings within 48 hours
- **Technical filters** — direction-aware (long vs short thresholds): RVOL, VWAP, RSI, EMA crossover, price change %, ATR breakout. +2 points per passing filter, max +12
- **Social scanners** — Reddit RSS (5 subreddits), ApeWisdom trending, Google Trends spike detection. StockTwits via Playwright stealth (Cloudflare-blocked API)
- **Options flow** — detects unusual volume/open-interest ratios (>3x with >100 contracts) via yfinance option chains
- **Other analysts** — checks if multiple tracked analysts mention the same ticker within 1 hour
- **LLM confidence boost** — final LLM pass incorporating news + technical data, up to +15 points

### Background Loops
- **Reddit trend digest** — crawls 7 finance subreddits every 4 hours, extracts trending tickers, posts digest to Discord
- **Price followup tracking** — records price at 1h and 24h after each alert for win-rate calculation
- **Social scanner** — polls Reddit, ApeWisdom, Google Trends every 5 minutes to populate cross-reference data
- **Signal pruner** — expires stale signals after 2 hours, cleans DB every 15 minutes

### Discord Commands

**General**
| Command | Description |
|---|---|
| `!help` | List all available commands |
| `!status` | Active signal count and last alert summary |
| `!performance` | Alert win rates, avg P&L, top/worst alerts at 1h and 24h |

**On-Demand Scans**
| Command | Description |
|---|---|
| `!scan <TICKER>` | Full cross-reference on any ticker (news + technical + social + SEC + options + LLM) |
| `!news <TICKER>` | Run news cascade standalone — returns headline and catalyst type |
| `!sec <TICKER>` | Recent SEC filings (8-K, Form 4 insider trades, 13D activist, etc.) |
| `!options <TICKER>` | Unusual options activity — call/put vol/OI ratios and top contract |
| `!technical <TICKER> [long\|short]` | Run 6 technical filters with pass/fail (defaults to long) |
| `!google-trends <TICKER>` | Google Trends interest spike % for a ticker |

**Ticker Intel**
| Command | Description |
|---|---|
| `!signals <TICKER>` | Active signal counts by source (Twitter, Reddit, news, etc.) |
| `!analysts <TICKER>` | Analysts who mentioned a ticker in the last hour |
| `!active-tickers` | All tickers with active signals right now |
| `!alert-history <TICKER>` | Past alerts with entry price and 1h/24h P&L outcomes |

**Market Scanners**
| Command | Description |
|---|---|
| `!trend` | Trigger on-demand Reddit trend digest |
| `!stocktwits` | StockTwits trending symbols |
| `!apewisdom` | ApeWisdom trending tickers |

**Engine Health**
| Command | Description |
|---|---|
| `!nitter-health` | Check if Nitter Docker service is responding |

---

## Quick Start

### Prerequisites
- Python 3.10+
- Docker + Docker Compose
- Ubuntu 22.04+ (or Debian-based Linux)

### 1. Clone and install

```bash
git clone https://github.com/chopra2007/openclaw-twitter-discord-StockMarketSignalsBot.git
cd openclaw-twitter-discord-StockMarketSignalsBot

pip3 install aiohttp aiosqlite pyyaml yfinance feedparser requests beautifulsoup4 playwright playwright-stealth
playwright install chromium && playwright install-deps chromium
```

### 2. Environment variables

Create `/root/.openclaw/.env` (sourced at startup):

```bash
export FINNHUB_API_KEY="your_key"
export OPENROUTER_API_KEY="your_key"
export DISCORD_BOT_TOKEN="your_token"
export DISCORD_CHANNEL_ID="your_alerts_channel_id"
export DISCORD_FEED_CHANNEL_ID="your_tweetshift_channel_id"
export BRAVE_SEARCH_API_KEY="your_key"
export SERPAPI_API_KEY="your_key"
```

Then `source /root/.openclaw/.env` before running.

### 3. Discord bot setup

In the Discord Developer Portal:
- Enable **Message Content Intent** and **Server Members Intent**
- Add bot with `bot` + `applications.commands` scopes
- Grant: Read Messages, Send Messages, Read Message History, Embed Links
- Set up [TweetShift](https://tweetshift.com) to mirror analyst tweets into a dedicated channel (`DISCORD_FEED_CHANNEL_ID`)
- Point the bot at your alerts channel (`DISCORD_CHANNEL_ID`) for commands and signal output

### 4. Start Docker services

```bash
docker compose up -d
docker compose ps   # verify both healthy
```

### 5. Run the engine

```bash
# Full engine (TweetShift listener + social scanner + price tracker + pruner)
python3 -m consensus_engine

# Dry run (logs alerts instead of sending to Discord)
python3 -m consensus_engine --dry-run

# Single poll cycle and exit
python3 -m consensus_engine --once

# Engine health report
python3 -m consensus_engine --status

# Run test suite
python3 -m pytest tests/ -v
```

### 6. Systemd service (optional)

```ini
[Unit]
Description=OpenClaw Signal Engine
After=network.target docker.service

[Service]
Type=simple
WorkingDirectory=/root/.openclaw/workspace
ExecStart=/usr/bin/python3 -m consensus_engine
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Save to `/etc/systemd/system/openclaw.service`, then:

```bash
systemctl daemon-reload
systemctl enable --now openclaw
```

---

## Scoring Model

Alerts use additive scoring. Base score comes from analyst conviction; cross-reference sources add multipliers:

| Source | Points |
|---|---|
| Base (conviction) | 20–30 |
| Additional analyst | +20 each |
| News catalyst | +15 |
| SEC filing (recent) | +15 |
| ApeWisdom mentions | +10 |
| StockTwits trending | +10 |
| Reddit mentions (2+) | +10 |
| Options flow (unusual) | +10 |
| Technical filters | +2 each (max +12) |
| Google Trends spike | +5 |
| LLM confidence boost | up to +15 |

Typical actionable alerts score 35–80+. The quality gate blocks alerts with a base score below 25.

---

## Alert Output Format

**Phase 1 — Instant Ping** (sent immediately on tweet detection):
- Author block: analyst display name + avatar (TweetShift-style embed)
- Title: `$TICKER LONG/SHORT/NEUTRAL` with link to original tweet
- Tweet text
- Current price and base score

**Phase 2 — Score Breakdown** (reply, posted after cross-reference completes):
- News catalyst (headline + source)
- SEC filings (if any)
- Technical snapshot (6 filters with pass/fail)
- Social signals
- Options flow (if unusual)
- LLM analysis reasoning
- Full score breakdown: `base(25) + news(15) + tech(6) = 46`

---

## Configuration

All settings live in `config/consensus.yaml`. API keys reference `$ENV_VAR` syntax.

| Section | Controls |
|---|---|
| `api_keys` | All API keys (reference `$ENV_VAR` syntax) |
| `nitter` | RSS poll intervals, accounts file path |
| `searxng` | Self-hosted search URL and timeout |
| `scoring` | Conviction base scores and all multiplier values |
| `news_cascade` | Tier order, Finnhub lookback days, Brave daily budget |
| `intervals` | Social scan (5m), Reddit trend (4h), prune (15m) |
| `social` | Subreddit list, toggle StockTwits/ApeWisdom/Trends |
| `technical` | RVOL threshold, RSI bounds (long + short), EMA periods, ATR |
| `llm` | OpenRouter model, min confidence, max tokens |
| `ticker_validation` | Minimum market cap ($100M floor), cache TTL |
| `alerts` | Cooldown hours, max per hour, embed colors, min score |
| `database` | SQLite path, signal TTL (2h), alert history retention |

---

## Project Structure

```
consensus_engine/
├── main.py                    # Pipeline orchestrator: all loops + tweet processing
├── cross_reference.py         # Parallel cross-ref aggregator
├── db.py                      # SQLite schema, queries, performance stats
├── models.py                  # Dataclasses: ParsedTweet, TickerSignal, CrossReferenceResult, etc.
├── config.py                  # YAML config loader with $ENV_VAR resolution
├── alerts/
│   ├── discord.py             # Two-phase alert delivery (instant ping + score followup)
│   └── commands.py            # Discord command router (17 commands)
├── analysis/
│   ├── tweet_parser.py        # LLM tweet classification via OpenRouter
│   ├── technical.py           # Direction-aware technical filters (Finnhub + yfinance)
│   ├── llm_scorer.py          # LLM confidence boost scoring
│   └── indicators.py          # RVOL, VWAP, RSI, EMA, ATR calculations
├── scanners/
│   ├── discord_tweetshift.py  # Discord Gateway listener (primary tweet ingestion)
│   ├── nitter.py              # Nitter RSS poller (disabled, fallback)
│   ├── news.py                # 4-tier news cascade
│   ├── social.py              # Reddit RSS, StockTwits, ApeWisdom, Google Trends
│   ├── options.py             # Unusual options activity via yfinance
│   ├── reddit_trend.py        # Reddit trend digest (7 subreddits)
│   ├── sec_edgar.py           # SEC EDGAR filing scanner (8-K, 10-K, Form 4, etc.)
│   └── searxng.py             # SearXNG self-hosted search client
└── utils/
    ├── rate_limiter.py        # Async per-source rate limiter with exponential backoff
    ├── tickers.py             # Ticker extraction + blacklist + market-cap validation
    └── browser.py             # Playwright stealth browser (StockTwits)

config/
├── consensus.yaml             # Main configuration file
├── nitter.conf                # Nitter Docker config
└── searxng/settings.yml       # SearXNG Docker config

tests/                         # 115 pytest tests
sources.json                   # Analyst Twitter accounts to monitor
docker-compose.yaml            # Nitter + SearXNG services
```

---

## Self-Hosted Services

| Service | Port | Status | Purpose |
|---|---|---|---|
| Nitter | localhost:8585 | Disabled | Twitter RSS proxy (TweetShift replaced it) |
| SearXNG | localhost:8888 | Active | Meta search engine (Tier 4 news fallback) |

Both are configured in `docker-compose.yaml` with health checks and auto-restart.

---

## Testing

```bash
python3 -m pytest tests/ -v
```

115 tests covering: tweet parsing, cross-reference scoring, DB operations, Discord alerts, quality gate, technical direction filters, Reddit trend pipeline, options scanner, SEC EDGAR, ticker validation, news cascade, TweetShift listener, price followup, and Discord commands.

---

## Technical Notes

- **Finnhub free tier** only supports real-time quotes (`/quote`). Historical OHLCV comes from yfinance, run in a `ThreadPoolExecutor` because it is blocking.
- **StockTwits** requires Playwright stealth browser (API blocked by Cloudflare). Currently disabled.
- **ApeWisdom** uses a free direct REST API with no authentication.
- **Signal dedup** via `seen_tweets` SQLite table prevents reprocessing. Signals expire after 2 hours.
- **Ticker validation** enforces a $100M market-cap floor via Finnhub, cached 7 days in DB.
- **Rate limiting** on all external sources uses an async rate limiter with exponential backoff.
- **LLM model**: OpenRouter MiniMax M2.5 (`minimax/minimax-m2.5`) for tweet parsing and confidence scoring.
- **Exchange name filtering**: CME, CBOE, OPRA, NASDAQ, NYSE etc. are blacklisted from ticker extraction to prevent false positives on industry-context mentions.
