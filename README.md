# OpenClaw — Signal-First Stock Alert Engine

Analyst tweets on Twitter/X trigger instant Discord alerts. Cross-reference sources (news, social, technical, SEC filings, options flow, LLM confidence) run asynchronously and post a score breakdown as a follow-up reply. Core principle: **speed + accuracy**.

---

## Architecture

### Unified Signal Pipeline (Phase A–D: FinalYTplan)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Signal Sources → Signal Events (idempotent, normalized)                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ • TweetShift (Discord) → tweet_parser.py (multimodal: text + vision)        │
│ • YouTube transcripts → video_parser.py (quality-gated extraction)          │
│ • News cascade (Finnhub/RSS/Brave/SearXNG)                                  │
│ • Technical (RVOL, RSI, EMA, ATR via Finnhub + yfinance)                    │
│ • Social (Reddit, ApeWisdom, Google Trends)                                 │
│ • SEC EDGAR (8-K, Form 4, 13D filings)                                      │
│ • Options flow (unusual vol/OI via yfinance)                                │
│                      ↓                                                       │
│          write → signal_events table (idempotency_key UNIQUE)               │
└─────────────────────────────────────────────────────────────────────────────┘
                                |
                    ┌───────────┴───────────┐
                    v                       v
            Phase 1: Instant Alert    Phase 2: Score + Reliability
            (Discord ping)            (Async cross_reference)
                    |                       |
                    v                       v
            Quality Gate            snapshot_builder.py
            + Basic Score           (assemble evidence window)
                    |                       |
                    v                       v
            alerts/discord.py       reliability_engine.py
            (Phase 1 embed)         (W = R_class × R_entity × Q × D × I)
                    |                       |
                    |                   Compute:
                    |                   • p_up, p_down, p_flat
                    |                   • contradiction index C
                    |                   • direction + confidence
                    |                   • reason codes
                    |                       |
                    |                   Classify:
                    |                   • ALERT / WATCHLIST / IGNORE
                    |                   • UNCERTAIN (C > 0.75)
                    |                   • INSUFFICIENT_EVIDENCE
                    |                   • DEGRADED_MODE
                    |                       |
                    |                       v
                    |               calibration.py
                    |               (isotonic regression)
                    |                       |
                    |                       v
                    |               alerts/discord.py
                    |               (Phase 2 embed with
                    └──────────────→ calibrated confidence
                                     + contradiction
                                     + freshness
                                     + reason codes)
                                            |
                                            v
                                    price_followup_loop
                                    (1h + 24h tracking)
```

### Signal Deduplication & Idempotency

- Every signal gets an idempotency key: `hash(source_type + source_id + origin_ref + as_of_bucket + parser_version)`
- signal_events table has UNIQUE(idempotency_key) to prevent reprocessing
- decision_snapshots table records all (ticker, horizon, as_of) snapshots for calibration/backtest

### Source Health & Degraded Mode

- `source_health` table tracks per-source heartbeat, error rate, and freshness
- If ≥2 critical sources (Finnhub, yfinance, Nitter) are stale → DEGRADED_MODE
- Regime shift detector (vol + breadth + trend) raises abstain threshold temporarily
- `!source-health` command renders live status dashboard

**Tweet ingestion** is handled by TweetShift, a third-party bot that mirrors analyst tweets into a designated Discord channel. The engine connects to the Discord Gateway, intercepts those messages, and feeds them into the pipeline. Nitter RSS polling is available as a fallback but currently disabled.

For tweet parsing, the engine now uses a **hybrid multimodal router**:
- **Text-only tweet** → text model only
- **Tweet with image(s)** → vision model per image, then text model synthesis
- Model defaults live in `config/consensus.yaml` and can be overridden via env (`TEXT_MODEL`, `VISION_MODEL`) for one-line runtime swaps.

---

## Features

### Signal Pipeline & Reliability (FinalYTplan)
- **Two-phase Discord alerts** — Phase 1 instant ping with ticker/direction/price, Phase 2 reply with probabilistic decision + confidence + reason codes
- **Probabilistic classification** — emits ALERT/WATCHLIST/IGNORE/UNCERTAIN/INSUFFICIENT_EVIDENCE/DEGRADED_MODE instead of just a score
- **Reliability-weighted evidence** — each source gets weight `W = R_class × R_entity × Q × D × I`:
  - `R_class` = source-type prior (config-driven)
  - `R_entity` = rolling historical accuracy from source_performance table
  - `Q` = extraction quality score
  - `D` = freshness decay (`exp(-age/half_life)`)
  - `I` = independence discount (cluster overlap detection)
- **Contradiction detection** — `C = min(bull, bear) / max(bull, bear)` gates UNCERTAIN when C > 0.75
- **Calibrated confidence** — isotonic regression (sklearn) trained on rolling decision_snapshots
- **Quality gate** — blocks low-quality signals before alerting (ticker validation, conviction check, minimum base score, text length)
- **Multimodal tweet parser** — classifies tweets into 4 types via OpenRouter; text-only or vision+text hybrid; extracts tickers, direction (long/short/neutral), conviction, and options details

### Cross-Reference Sources (Evidence Graph)
- **YouTube transcripts** — `video_parser.py` extracts ticker mentions + direction + price levels + macro thesis. Quality gates: min 250 words, symbol disambiguation (reject ambiguous tickers), negation handling ("not bullish" flips to neutral). Stores to signal_events with source_type='youtube'. **Channel management:** channels are stored in the `youtube_channels` DB table and persisted to `/root/.openclaw/sources.json` under the `youtube_channels` key. Add channels via `!yt-follow @handle` in Discord — no restart required. Channels seed automatically on startup from sources.json.
- **News catalyst** — 4-tier cascade: Finnhub company news, Google News RSS, Brave Search, self-hosted SearXNG. Tiered scoring: high-impact catalysts (Earnings Beat, M&A, FDA Approval) score +25, medium (Analyst Upgrade, SEC Filing) +15, low (Partnership, Patent) +8
- **SEC EDGAR** — checks for recent 8-K, 10-K, 10-Q, Form 4, SC 13D/G filings within 48 hours. Form 4 (insider trading) adds +15 to reliability_engine
- **Technical filters** — direction-aware (long vs short thresholds): RVOL, VWAP, RSI, EMA crossover, price change %, ATR breakout. Weighted by freshness and historical accuracy
- **Social scanners** — Reddit JSON API (5 subreddits), ApeWisdom trending, Google Trends spike detection
- **Options flow** — detects unusual volume/open-interest ratios (>3x with >100 contracts) via yfinance option chains; market-wide sweep scanner for proactive detection
- **Other analysts** — checks if multiple tracked analysts mention the same ticker within 1 hour (capped at 3 for scoring)
- **LLM confidence boost** — called only when technical or catalyst data exists, up to +15 points
- **Cross-reference cache** — 5-minute TTL in-memory cache prevents redundant API calls when multiple analysts tweet the same ticker
- **Freshness policy** — each source has max-age windows (market: 60s, options: 30m, news: 90m, X: 4h, YouTube: 24h). Stale sources marked STALE and weighted down

### Background Loops
- **Reddit trend digest** — crawls 7 finance subreddits every 4 hours, extracts trending tickers, posts digest to Discord
- **Price followup tracking** — records price at 1h and 24h after each alert for win-rate calculation
- **Social scanner** — polls Reddit (JSON API), ApeWisdom, Google Trends every 5 minutes to populate cross-reference data
- **Signal pruner** — expires stale signals after 2 hours, cleans DB every 15 minutes

### Proactive Scanners
- **Pre-market gap scanner** — detects >3% gaps on a 20-ticker watchlist between 8-9am ET via Finnhub quotes
- **SEC 8-K real-time watcher** — optional background watcher for EDGAR ATOM feed; when enabled, filings are stored for context/cross-reference (not standalone alerts)
- **Volume breakout scanner** — flags tickers with RVOL >5x and price change >1% during market hours
- **Earnings calendar pre-alert** — fetches upcoming earnings for tracked tickers via Finnhub, alerts day-before
- **Unusual options sweep scanner** — market-wide scan for high-notional sweeps (vol/OI >5x, >$100K notional)

> **Important safety rule:** SEC/EDGAR data is cross-reference context only. Standalone SEC alerts are blocked in the tweet pipeline, and background SEC watcher loops are disabled by default unless explicitly enabled in config.

### Discord Commands

**General**
| Command | Description |
|---|---|
| `!help` / `!readme` | List all available commands |
| `!list` / `!commands` | List all available commands |
| `!status` | Active signal count and last alert summary |
| `!performance` | Alert win rates, avg P&L, top/worst alerts at 1h and 24h |

**On-Demand Scans**
| Command | Description |
|---|---|
| `!scan <TICKER>` | Full cross-reference on any ticker (news + technical + social + SEC + options + YouTube + LLM) |
| `!news <TICKER>` | Run news cascade standalone — returns headline and catalyst type |
| `!sec <TICKER>` | Recent SEC filings (8-K, Form 4 insider trades, 13D activist, etc.) |
| `!options <TICKER>` | Unusual options activity — call/put vol/OI ratios and top contract |
| `!technical <TICKER> [long\|short]` | Run 6 technical filters with pass/fail (defaults to long) |
| `!google-trends <TICKER>` | Google Trends interest spike % for a ticker |
| `!market-view <TICKER>` | Current probabilistic verdict: direction, P(up/down/flat), calibrated confidence, contradiction index |
| `!levels <TICKER>` | Price levels from YouTube transcripts + signal events with condition text |

**Ticker Intel**
| Command | Description |
|---|---|
| `!signals <TICKER>` | Active signal counts by source (Twitter, Reddit, news, YouTube, etc.) |
| `!analysts <TICKER>` | Analysts who mentioned a ticker in the last hour |
| `!active-tickers` | All tickers with active signals right now |
| `!alert-history <TICKER>` | Past alerts with entry price and 1h/24h P&L outcomes |

**Market Scanners**
| Command | Description |
|---|---|
| `!trend` | Trigger on-demand Reddit trend digest |
| `!apewisdom` | ApeWisdom trending tickers |
| `!gaps` | Pre-market gap scanner (>3% moves on watchlist) |
| `!leaderboard` | Per-analyst win rate rankings (1h + 24h accuracy, avg P&L) |

**YouTube Intelligence**
| Command | Description |
|---|---|
| `!yt <URL>` | On-demand analysis of a YouTube video — returns tickers, conviction, macro direction, and price levels found |
| `!yt-mentions <TICKER>` | YouTube signals for a ticker from the last 7 days, ordered by conviction |
| `!macro` | Macro digest across all followed channels (last 7 days): direction counts + top 3 themes |
| `!yt-follow <@handle or URL>` | Add a YouTube channel to the follow list. Accepts `@FiguringOutMoney`, `https://youtube.com/@FiguringOutMoney`, or any YouTube channel URL. Resolves the channel ID automatically, adds it to the DB and `sources.json`, and starts scanning on the next poll cycle. |

**Engine Health**
| Command | Description |
|---|---|
| `!source-health` | Live dashboard of source statuses (heartbeat, error rate, freshness) with color-coded degradation |
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
# Optional runtime overrides (defaults also exist in config/consensus.yaml)
export TEXT_MODEL="minimax/minimax-m2.5:free"
export VISION_MODEL="google/gemini-2.5-flash-preview"
export DISCORD_BOT_TOKEN="your_token"
export DISCORD_CHANNEL_ID="your_alerts_channel_id"
export DISCORD_FEED_CHANNEL_ID="your_tweetshift_channel_id"
export BRAVE_SEARCH_API_KEY="your_key"
export SERPAPI_API_KEY="your_key"
```

Then `source /root/.openclaw/.env` before running.

### Swap models instantly (no code change)

To change the vision model, only update your `.env` and restart:

```bash
export VISION_MODEL="openai/gpt-4.1-mini"
```

Similarly, to switch text model:

```bash
export TEXT_MODEL="anthropic/claude-3.5-sonnet"
```

OpenClaw will pick these up automatically from `models/model_config.py`.

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

## Scoring & Classification Model

### Reliability Weighting (Phase A–D: FinalYTplan)

Each signal event gets a per-source weight:

```
W_i = R_class × R_entity × Q_i × D_i × I_i
```

Where:
- **R_class** — Source-class reliability prior (e.g., youtube: 0.8, X: 0.7, news: 0.9). Config-driven.
- **R_entity** — Rolling historical accuracy of the source entity from `source_performance` table. Defaults to 0.5 if insufficient samples.
- **Q_i** — Extraction quality (0–1). From tweet parser confidence, transcript quality, option contract volume, etc.
- **D_i** — Freshness decay: `exp(-age / half_life)`. Age in seconds; half_life from config per source.
- **I_i** — Independence discount (0–1). Reduces weight for cluster overlaps (same URL reposted by multiple sources, identical text, etc.).

**Direction mass:**
```
S_bull = Σ W_i × p_i(bull)
S_bear = Σ W_i × p_i(bear)
```

**Contradiction:**
```
C = min(S_bull, S_bear) / max(S_bull, S_bear) + ε
```

### Classification Logic

Given (S_bull, S_bear, C, evidence_mass):

| Rule | Output |
|------|--------|
| `evidence_mass < 0.35` | `INSUFFICIENT_EVIDENCE` |
| `C > 0.75` | `UNCERTAIN` |
| `critical_source_stale` | `DEGRADED_MODE` |
| `S_bull >> S_bear` | `ALERT` (if confidence > threshold) |
| `S_bear >> S_bull` | `ALERT` (if confidence > threshold) |
| `S_bull ≈ S_bear, mass > 0.35` | `WATCHLIST` |
| low evidence mass | `IGNORE` |

**Calibration:** Isotonic regression (sklearn) trained on rolling `decision_snapshots` to map raw confidence → calibrated confidence.

### Legacy Scoring (Phase 1 only, backward-compatible)

Base score from analyst conviction; cross-reference sources add multipliers:

| Source | Points |
|---|---|
| Base (conviction) | 20–30 |
| Additional analyst | +20 each (capped at 3 = +60 max) |
| News catalyst (high tier) | +25 (Earnings Beat, M&A, FDA) |
| News catalyst (medium tier) | +15 (Analyst Upgrade, SEC Filing) |
| News catalyst (low tier) | +8 (Partnership, Patent) |
| SEC filing (recent) | +15 |
| ApeWisdom mentions | +10 |
| Reddit mentions (2+) | +10 |
| Options flow (unusual) | +10 |
| Technical filters | +2 each (max +12) |
| Google Trends spike | +5 |
| LLM confidence boost | up to +15 |

Typical actionable alerts score 35–80+. Quality gate blocks alerts with a base score below 20.

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
| `scoring` | Conviction base scores, multipliers, catalyst tiers (high/medium/low) |
| `news_cascade` | Tier order, Finnhub lookback days, Brave daily budget |
| `intervals` | Social scan (5m), Reddit trend (4h), prune (15m) |
| `social` | Subreddit list, toggle ApeWisdom/Trends |
| `technical` | RVOL threshold, RSI bounds (long + short), EMA periods, ATR |
| `llm` | OpenRouter model, min confidence, max tokens |
| `ticker_validation` | Minimum market cap ($100M floor), cache TTL |
| `scanners` | Background scanner toggles (includes SEC watcher enable/disable switch) |
| `premarket` | Gap scanner: threshold %, watchlist, scan hours |
| `volume_scanner` | Volume breakout: RVOL threshold, min price change |
| `alerts` | Cooldown hours, max per hour, embed colors, min score |
| `database` | SQLite path, signal TTL (2h), alert history retention |
| `reliability` | Source-type priors (R_class), contradiction threshold (0.75), min evidence mass (0.35) |
| `freshness_max_age` | Max age per source (market: 60s, options: 30m, news: 90m, X: 4h, youtube: 24h) |
| `alerts` | suppress_when_degraded (bool), require_calibrated_confidence (bool), suppress_on list |

### SQLite Schema (Phase A)

**New tables from FinalYTplan:**
- `signal_events` — immutable event records with idempotency_key (UNIQUE). Fields: event_id, as_of, source_type, source_id, ticker, horizon, signal_type, signal_payload (JSON), quality, origin_ref, parser_version
- `decision_snapshots` — point-in-time snapshots of (ticker, horizon, as_of). Fields: snapshot_id, as_of, features (JSON), weights (JSON), output (JSON), versions (JSON)
- `source_health` — per-source monitoring. Fields: source_id, last_heartbeat, error_rate, freshness_seconds
- `source_performance` — rolling accuracy by entity+horizon. Fields: entity_id, horizon, rolling_accuracy, sample_count

**Existing tables (preserved):**
- `seen_tweets`, `active_signals`, `alert_history`, `ticker_validation_cache`, YouTube tables (`youtube_analysis`, `youtube_ticker_mentions`, `youtube_levels`, `youtube_macro`)

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
│   ├── tweet_parser.py        # Multimodal tweet classification (text + vision via OpenRouter)
│   ├── video_parser.py        # YouTube transcript extraction (quality gates + negation handling)
│   ├── snapshot_builder.py    # Assemble (ticker, horizon, as_of) evidence snapshot from signal_events
│   ├── reliability_engine.py  # W = R_class × R_entity × Q × D × I; compute contradiction + direction
│   ├── calibration.py         # Isotonic regression for confidence calibration
│   ├── technical.py           # Direction-aware technical filters (Finnhub + yfinance)
│   ├── llm_scorer.py          # LLM confidence boost scoring
│   └── indicators.py          # RVOL, VWAP, RSI, EMA, ATR calculations
├── scanners/
│   ├── discord_tweetshift.py  # Discord Gateway listener (primary tweet ingestion)
│   ├── nitter.py              # Nitter RSS poller (disabled, fallback)
│   ├── news.py                # 4-tier news cascade
│   ├── social.py              # Reddit JSON API, ApeWisdom, Google Trends
│   ├── options.py             # Unusual options activity via yfinance
│   ├── reddit_trend.py        # Reddit trend digest (7 subreddits)
│   ├── sec_edgar.py           # SEC EDGAR filing scanner (8-K, 10-K, Form 4, etc.)
│   ├── sec_watcher.py         # Real-time SEC 8-K ATOM feed watcher
│   ├── premarket.py           # Pre-market gap scanner via Finnhub quotes
│   ├── volume_scanner.py      # RVOL >5x volume breakout detector
│   ├── earnings_calendar.py   # Upcoming earnings pre-alert via Finnhub
│   └── searxng.py             # SearXNG self-hosted search client
└── utils/
    ├── rate_limiter.py        # Async per-source rate limiter with exponential backoff
    ├── tickers.py             # Ticker extraction + blacklist + market-cap validation
    ├── xref_cache.py          # In-memory cross-reference cache (5-min TTL)
    └── browser.py             # Playwright stealth browser

config/
├── consensus.yaml             # Main configuration file
├── nitter.conf                # Nitter Docker config
└── searxng/settings.yml       # SearXNG Docker config

scripts/
└── backtest.py                # Replay decision_snapshots vs price outcomes; accuracy + calibration curves

tests/                         # 280 pytest tests
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

280 tests covering:
- **Phase A:** signal_events + decision_snapshots schema, snapshot_builder, reliability_engine weighting/contradiction/classification
- **Phase B:** video_parser (quality gates, negation handling, disambiguation), cross_reference × reliability_engine integration
- **Phase C:** calibration (isotonic regression, identity fallback, monotonicity), Discord embeds (confidence/contradiction/freshness/reason-codes), !market-view + !levels commands
- **Phase D:** source_health monitoring + !source-health command, degraded-mode policy + alert suppression, backtest/walk-forward script
- **Existing:** tweet parsing (multimodal + fallback), technical direction filters, Reddit trend pipeline, options scanner, SEC EDGAR, TweetShift listener, price followup, all Discord commands

---

## Technical Notes

### FinalYTplan (Phase A–D)

- **Idempotency** — All signals deduplicated via `hash(source_type + source_id + origin_ref + as_of_bucket + parser_version)`. signal_events table has UNIQUE(idempotency_key).
- **Snapshot builder** — Assembles evidence from signal_events within freshness windows; marks stale sources explicitly.
- **Reliability engine** — Weight formula: `W = R_class × R_entity × Q × D × I`. Contradiction gating at C=0.75. Insufficient evidence threshold: 0.35.
- **YouTube quality gates** — Transcripts < 250 words rejected. Symbol disambiguation filters common-word false positives. Negation handling ("not bullish") flips direction to neutral.
- **Calibration** — Isotonic regression (sklearn) trained on rolling snapshots. Falls back to identity if <50 samples.
- **Source health** — Background heartbeat loop updates source_health table every poll cycle. Degraded-mode triggered when ≥2 critical sources stale.
- **Backtest script** — `scripts/backtest.py` replays snapshots against yfinance outcomes; outputs accuracy, calibration curves (reliability diagram), contradiction-vs-accuracy plot.

### Existing (Stable)

- **Finnhub free tier** only supports real-time quotes (`/quote`). Historical OHLCV comes from yfinance, run in a `ThreadPoolExecutor` because it is blocking.
- **ApeWisdom** uses a free direct REST API with no authentication.
- **Signal dedup** via `seen_tweets` SQLite table prevents reprocessing. Signals expire after 2 hours.
- **Ticker validation** enforces a $100M market-cap floor via Finnhub, cached 7 days in DB.
- **Rate limiting** on all external sources uses an async rate limiter with exponential backoff.
- **LLM models**: OpenRouter (configurable via env; defaults in config.yaml). Text model for tweet/video parsing; vision model for image analysis.
- **Exchange name filtering**: CME, CBOE, OPRA, NASDAQ, NYSE etc. are blacklisted from ticker extraction to prevent false positives on industry-context mentions.
- **Multimodal router** — Hybrid text + vision processing. Text-only tweets skip vision model; tweets with images run vision per image, then text synthesis.

---

## Recent Changes (April 2026)

**Merged PRs:**
- PR #2: Multimodal tweet parsing (text + vision router, vision_model + text_model + OpenRouter client)
- FinalYTplan phases A–D: Reliability weighting, YouTube intelligence, calibration, source health, degraded-mode policy, backtest script (280 tests passing)
