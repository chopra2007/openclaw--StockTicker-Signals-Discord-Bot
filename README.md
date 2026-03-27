# OpenClaw — Signal-First Stock Alert Engine

Analyst tweets on Twitter/X trigger instant Discord alerts. Cross-reference sources (news, social, technical, LLM) run asynchronously and add score multipliers via a follow-up reply. Core principle: **speed + accuracy**.

---

## How It Works

1. **Nitter RSS** polls 48 analyst accounts every 60s (market hours) / 180s (off-hours)
2. **LLM Tweet Parser** classifies tweets into types:
   - **Type A**: Ticker callout (e.g. "Buying $NVDA here")
   - **Type B**: Macro commentary
   - **Type C**: Options play
   - **Type D**: General sentiment
3. **Instant Discord Ping** — actionable tweets (A/C) fire an alert immediately
4. **Cross-Reference Engine** — runs in background, then replies with a score breakdown:
   - News catalyst (4-tier cascade: Finnhub → Google RSS → Brave → SearXNG)
   - Social momentum (Reddit, StockTwits, ApeWisdom, Google Trends)
   - Technical filters (RVOL, VWAP, RSI, EMA, ATR, Price Change)
   - Options flow (unusual volume/OI ratios via yfinance)
   - Other analysts mentioning the same ticker
   - LLM confidence boost

### Pipeline

```
Nitter RSS (60/180s)
    └─> tweet_parser.py (LLM classify)
            └─> main.py:process_tweet()
                    ├─> alerts/discord.py     ← instant ping (Phase 1)
                    └─> cross_reference.py    ← background task (Phase 2 reply)
                            ├─> scanners/news.py         (4-tier cascade)
                            ├─> analysis/technical.py    (RVOL, RSI, etc.)
                            ├─> scanners/social.py        (Reddit, StockTwits)
                            ├─> scanners/options.py       (yfinance unusual flow)
                            └─> analysis/llm_scorer.py   (confidence boost)
```

### Self-Hosted Services (Docker)
| Service  | Port            | Purpose                              |
|----------|-----------------|--------------------------------------|
| Nitter   | localhost:8585  | Twitter RSS proxy (no API key needed)|
| SearXNG  | localhost:8888  | Meta search engine (news fallback)   |

---

## Prerequisites

- **OS**: Ubuntu 22.04+ (or Debian-based Linux), running as `root` at `/root`
- **Python**: 3.10+
- **Docker** + **Docker Compose**
- **Claude Code** (OpenClaw orchestrator)
- **Git** + **GitHub CLI** (`gh`)

---

## Required API Keys

| Key                   | Source                          | Used For                          |
|-----------------------|---------------------------------|-----------------------------------|
| `FINNHUB_API_KEY`     | finnhub.io (free tier)          | News, real-time quotes, ticker validation |
| `OPENROUTER_API_KEY`  | openrouter.ai                   | LLM tweet parsing + confidence scoring |
| `DISCORD_BOT_TOKEN`   | Discord Developer Portal        | Sending alerts + reading commands |
| `DISCORD_CHANNEL_ID`  | Discord server                  | Alert destination channel         |
| `BRAVE_SEARCH_API_KEY`| api.search.brave.com (free tier)| Tier 3 news cascade               |

Optional (for Twitter cookie-based fallback):
- `TWITTER_AUTH_TOKEN`, `TWITTER_CT0`, `TWITTER_COOKIE_STRING`

---

## Setup (Fresh VPS)

### 1. Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3-pip git docker.io docker-compose-plugin curl

# Install GitHub CLI
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list
sudo apt-get update && sudo apt-get install -y gh
```

### 2. Clone the Repository

```bash
mkdir -p /root/.openclaw
cd /root/.openclaw
gh auth login
git clone https://github.com/chopra2007/openclaw-workspace.git workspace
cd workspace
```

### 3. Place sources.json

The engine reads analyst accounts from `/root/.openclaw/sources.json`. Copy it from the repo:

```bash
cp /root/.openclaw/workspace/sources.json /root/.openclaw/sources.json
```

### 4. Install Python Dependencies

```bash
pip3 install aiohttp aiosqlite pyyaml yfinance feedparser requests beautifulsoup4 playwright playwright-stealth
playwright install chromium
playwright install-deps chromium
```

### 5. Configure Environment Variables

Create `/root/.openclaw/workspace/.env`:

```bash
cat > /root/.openclaw/workspace/.env << 'EOF'
FINNHUB_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here
DISCORD_BOT_TOKEN=your_token_here
DISCORD_CHANNEL_ID=your_channel_id_here
BRAVE_SEARCH_API_KEY=your_key_here
# Optional Twitter cookie auth:
# TWITTER_AUTH_TOKEN=
# TWITTER_CT0=
# TWITTER_COOKIE_STRING=
EOF
```

The engine loads env vars at startup. Config values prefixed with `$` in `config/consensus.yaml` are resolved from environment.

### 6. Configure Discord Bot

In the Discord Developer Portal:
- Enable **Message Content Intent** and **Server Members Intent**
- Add bot to your server with `bot` + `applications.commands` scopes
- Grant permissions: Read Messages, Send Messages, Read Message History, Embed Links

Also set `discord_feed_channel_id` in `config/consensus.yaml` to your TweetShift input channel ID (where Twitter embeds arrive).

### 7. Start Docker Services

```bash
cd /root/.openclaw/workspace
docker compose up -d

# Verify both containers are healthy
docker compose ps
```

### 8. Initialize the Database

The database is created automatically on first run at `consensus.db`.

### 9. Run the Engine

```bash
cd /root/.openclaw/workspace

# Full engine (Nitter poller + Discord listener + social scanner + pruner)
python3 -m consensus_engine

# Dry run (no Discord sends — logs alerts instead)
python3 -m consensus_engine --dry-run

# Single poll cycle and exit
python3 -m consensus_engine --once

# Health report
python3 -m consensus_engine --status
```

---

## Discord Bot Commands

Send these in any channel the bot can read:

| Command          | Description                                         |
|------------------|-----------------------------------------------------|
| `!help`          | List all commands                                   |
| `!status`        | Active signal count + last alert summary            |
| `!trend`         | Post the latest Reddit trend digest on demand       |
| `!scan TICKER`   | Run full cross-reference on a ticker (e.g. `!scan NVDA`) |

---

## Scoring Model

Alerts use additive scoring:

| Signal                    | Points          |
|---------------------------|-----------------|
| Base (conviction)         | 20–30           |
| Additional analyst        | +20             |
| News catalyst             | +15             |
| SEC filing                | +15             |
| ApeWisdom social          | +10             |
| StockTwits social         | +10             |
| Reddit social             | +10             |
| Options flow (unusual)    | +10             |
| Technical filters (each)  | +2 (max 12)     |
| Google Trends             | +5              |
| LLM confidence boost      | up to +15       |

Higher scores = stronger multi-source confirmation. Typical actionable alerts score 35–80+.

---

## Configuration

All settings live in `config/consensus.yaml`. Key sections:

```yaml
api_keys:          # All reference $ENV_VAR
nitter:            # Poll intervals, accounts_file path
scoring:           # All score multipliers
news_cascade:      # Tier order + Finnhub lookback
intervals:         # social_scan, reddit_trend (4h), cross_reference_timeout
social:            # Subreddits, toggle StockTwits/ApeWisdom/Trends
technical:         # RVOL threshold, RSI bounds, EMA periods
llm:               # OpenRouter model + min_confidence
ticker_validation: # Min market cap ($100M floor)
alerts:            # Cooldown hours, max per hour
database:          # Path + signal TTL (2h)
```

---

## Project Structure

```
/root/.openclaw/workspace/
├── consensus_engine/           # Main Python package
│   ├── main.py                 # Orchestrator: polling loops, tweet pipeline
│   ├── cross_reference.py      # Background cross-ref aggregator
│   ├── db.py                   # SQLite (aiosqlite) schema + queries
│   ├── models.py               # Dataclasses: ParsedTweet, TickerSignal, etc.
│   ├── config.py               # Config loader (YAML + env var resolution)
│   ├── alerts/
│   │   ├── discord.py          # Instant ping + detail follow-up sends
│   │   └── commands.py         # !help/!status/!trend/!scan routing
│   ├── analysis/
│   │   ├── tweet_parser.py     # LLM tweet classification (OpenRouter)
│   │   ├── technical.py        # RVOL, VWAP, RSI, EMA, ATR
│   │   ├── llm_scorer.py       # LLM confidence boost scoring
│   │   └── indicators.py       # Technical indicator calculations
│   ├── scanners/
│   │   ├── nitter.py           # Nitter RSS poller
│   │   ├── discord_tweetshift.py # Discord Gateway listener (TweetShift input)
│   │   ├── news.py             # 4-tier news cascade
│   │   ├── social.py           # Reddit, StockTwits, ApeWisdom, Google Trends
│   │   ├── options.py          # Options flow (yfinance unusual volume/OI)
│   │   ├── reddit_trend.py     # Periodic Reddit trend digest
│   │   ├── sec_edgar.py        # SEC EDGAR filing scanner
│   │   └── searxng.py          # SearXNG self-hosted search
│   └── utils/
│       ├── rate_limiter.py     # Async per-source rate limiter + backoff
│       ├── tickers.py          # Ticker validation (market cap via Finnhub)
│       └── browser.py          # Playwright stealth browser (StockTwits)
├── tests/                      # pytest test suite (89 tests)
├── config/
│   ├── consensus.yaml          # Main configuration
│   ├── nitter.conf             # Nitter Docker config
│   └── searxng/settings.yml   # SearXNG Docker config
├── sources.json                # 48 analyst Twitter accounts to monitor
├── docker-compose.yaml         # Nitter + SearXNG services
├── install_deps.sh             # Quick dependency installer
├── pytest.ini                  # asyncio_mode = auto
└── CLAUDE.md                   # Claude Code instructions for this project
```

---

## Running Tests

```bash
cd /root/.openclaw/workspace
python3 -m pytest tests/ -v

# Or via engine CLI
python3 -m consensus_engine --test
```

89 tests covering: tweet parsing, cross-reference, DB operations, Discord alerts, Reddit trend, options scanner, ticker validation, news cascade, and more.

---

## Important Notes

- **Finnhub free tier**: Only supports real-time quotes (`/quote`). Historical OHLCV comes from **yfinance** (run in `ThreadPoolExecutor` — it's blocking).
- **StockTwits**: Uses Playwright stealth browser only (API blocked by Cloudflare). ApeWisdom uses a free REST API.
- **Playwright stealth** v2.0.2: Use `from playwright_stealth import Stealth` then `Stealth().apply_stealth_async(page)`.
- **Signal dedup**: Seen tweets stored in `seen_tweets` table. Signals expire after 2 hours.
- **Ticker validation**: $100M market-cap floor via Finnhub, cached 7 days in DB.
- **Rate limiting**: All external sources use async rate limiter with exponential backoff.
