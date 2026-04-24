# OpenClaw — Signal-First Stock Alert Engine

Analyst tweets on Twitter/X trigger instant Discord alerts. Cross-reference sources (news, social, technical, SEC filings, options flow, LLM confidence) run asynchronously and post a score breakdown as a follow-up reply. Core principle: **speed + accuracy**.

---

## Architecture
### Signal Pipeline

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
            + Basic Score           → reliability_engine.py
                    |               → calibration.py
                    v                       |
            alerts/discord.py       alerts/discord.py
            (Phase 1 embed)         (Phase 2 embed: calibrated confidence,
                    |                contradiction, freshness, reason codes)
                    └──────────────→         |
                                             v
                                    price_followup_loop
                                    (1h + 24h tracking)
```

### Key Design Decisions

- **Signal-first** — tweet → instant alert → async cross-reference. No gates block the Phase 1 ping.
- **Precision engine gates suppression** — `precision["classification"]` decides ALERT/WATCHLIST/IGNORE. Cross-reference provides breakdown enrichment. Full xref deprecation: Week 6.
- **Reliability engine** — disabled by default (`alerts.reliability_engine_enabled: false`). Scheduled for Week 4.
- **Multimodal tweet parser** — text-only tweets use text model only; tweets with images run vision model per image then text synthesis. Models configured in `config/consensus.yaml` or overridden via env vars.

---

## Features
### Signal Sources

| Source | How it works |
|---|---|
| **TweetShift** | Discord Gateway listener mirrors analyst tweets. Parsed by `tweet_parser.py` (multimodal: text + vision via OpenRouter). |
| **YouTube transcripts** | `video_parser.py` extracts ticker mentions, direction, price levels, macro thesis. Quality gates: min 250 words, symbol disambiguation, negation handling. Channels managed via `!yt-follow` — no restart needed. |
| **News cascade** | 4-tier: Finnhub → Google News RSS → Brave Search → SearXNG. High-impact catalysts (Earnings, M&A, FDA): +25; medium (Upgrade, SEC): +15; low (Patent, Partnership): +8. |
| **SEC EDGAR** | 8-K, 10-K, 10-Q, Form 4, 13D/G within 48h. Form 4 adds +15. Standalone SEC alerts blocked by design. |
| **Technical filters** | Direction-aware: RVOL, VWAP, RSI, EMA crossover, price change %, ATR breakout. +2 each, max +12. |
| **Social** | Reddit JSON API (5 subreddits), ApeWisdom trending, Google Trends spike detection. |
| **Options flow** | Unusual vol/OI ratios (>3x, >100 contracts) via yfinance. Market-wide sweep scanner for proactive detection. |

### Background Loops

| Loop | Frequency |
|---|---|
| Reddit trend digest | Every 4h — crawls 7 subreddits, posts digest to Discord |
| Social scanner | Every 5m — Reddit, ApeWisdom, Google Trends |
| Price followup tracking | 1h + 24h after each alert for win-rate calculation |
| Signal pruner | Every 15m — expires stale signals after 2h |
| YouTube scanner | Polls RSS feed for each followed channel; new videos are transcribed and parsed automatically |
| Daily macro digest | 6 AM ET on weekdays — YouTube macro direction summary posted to #alerts |
| Level proximity alerter | Each tweet poll cycle — alerts when price is within 0.5% of a YouTube-flagged level |

### Proactive Scanners

- **Volume breakout scanner** — RVOL >5x + price change >1% during market hours
- **Unusual options sweep scanner** — vol/OI >5x, >$100K notional
- **Earnings calendar pre-alert** — day-before alert for tracked tickers via Finnhub
- **SEC 8-K real-time watcher** — optional background watcher; disabled by default

### Reliability & Classification

Each signal event gets a per-source weight `W = R_class × R_entity × Q × D × I`:
- `R_class` — source-type prior (youtube: 0.8, X: 0.7, news: 0.9)
- `R_entity` — rolling historical accuracy from `source_performance` table
- `Q` — extraction quality (tweet confidence, transcript quality, etc.)
- `D` — freshness decay: `exp(-age / half_life)`
- `I` — independence discount (cluster overlap detection)

Classification outputs: `ALERT` / `WATCHLIST` / `IGNORE` / `UNCERTAIN` (C > 0.75) / `INSUFFICIENT_EVIDENCE` / `DEGRADED_MODE`.
Calibrated confidence via isotonic regression on rolling `decision_snapshots`.

---

## Discord Commands
### General
| Command | Description |
|---|---|
| `!help` | List all available commands |
| `!status` | Active signal count and last alert summary |
| `!performance` | Alert win rates, avg P&L, top/worst alerts at 1h and 24h |

### On-Demand Scans
| Command | Description |
|---|---|
| `!scan <TICKER>` | Full cross-reference: news + technical + social + SEC + options + YouTube + LLM |
| `!news <TICKER>` | News cascade standalone — headline + catalyst type |
| `!sec <TICKER>` | Recent SEC filings (8-K, Form 4 insider trades, 13D activist) |
| `!options <TICKER>` | Unusual options activity — vol/OI ratios and top contract |
| `!technical <TICKER> [long\|short]` | 6 technical filters with pass/fail (defaults to long) |
| `!google-trends <TICKER>` | Google Trends interest spike % |
| `!market-view <TICKER>` | Probabilistic verdict: direction, P(up/down/flat), calibrated confidence, contradiction index |
| `!levels <TICKER>` | Price levels from YouTube transcripts + signal events with condition text |

### Ticker Intel
| Command | Description |
|---|---|
| `!signals <TICKER>` | Active signal counts by source (Twitter, Reddit, news, YouTube, etc.) |
| `!analysts <TICKER>` | Analysts who mentioned a ticker in the last hour |
| `!active-tickers` | All tickers with active signals right now |
| `!alert-history <TICKER>` | Past alerts with entry price and 1h/24h P&L outcomes |

### Market Scanners
| Command | Description |
|---|---|
| `!trend` | On-demand Reddit trend digest |
| `!apewisdom` | ApeWisdom trending tickers |
| `!leaderboard` | Per-analyst win rate rankings (1h + 24h accuracy, avg P&L) |

### YouTube Intelligence
| Command | Description |
|---|---|
| `!yt <URL>` | Analyse a YouTube video on demand — tickers, conviction, macro direction, price levels |
| `!yt-follow <@handle or URL>` | Add a channel to the follow list. Accepts `@FiguringOutMoney` or full URL. Resolves channel ID automatically, adds to DB + `sources.json`, starts scanning immediately. |
| `!yt-mentions <TICKER>` | YouTube signals for a ticker from the last 7 days, ordered by conviction |
| `!macro` | Macro digest across all followed channels (last 7 days): direction counts + top 3 themes |
| `!transcript <URL>` | Fetch and display the raw transcript for a YouTube video |

### Engine Health
| Command | Description |
|---|---|
| `!source-health` | Live status dashboard (heartbeat, error rate, freshness) with color-coded degradation |

---

## Quick Start
### Prerequisites
- Python 3.10+, Docker + Docker Compose, Ubuntu 22.04+

### 1. Install

```bash
pip3 install aiohttp aiosqlite pyyaml yfinance feedparser requests beautifulsoup4 playwright playwright-stealth
playwright install chromium && playwright install-deps chromium
```

### 2. Environment variables

Create `/root/.openclaw/.env`:

```bash
export FINNHUB_API_KEY="your_key"
export OPENROUTER_API_KEY="your_key"
export DISCORD_BOT_TOKEN="your_token"
export DISCORD_CHANNEL_ID="your_alerts_channel_id"
export DISCORD_FEED_CHANNEL_ID="your_tweetshift_channel_id"
export BRAVE_SEARCH_API_KEY="your_key"
export SERPAPI_API_KEY="your_key"

# Model overrides (defaults live in config/consensus.yaml)
export TEXT_MODEL="minimax/minimax-m2.5:free"
export VISION_MODEL="google/gemma-4-31b-it:free"
```

Then `source /root/.openclaw/.env` before running.

**Swap models without code changes** — update `VISION_MODEL` or `TEXT_MODEL` in `.env` and restart. OpenClaw reads from `models/model_config.py` at startup.

### 3. Discord bot setup

- Enable **Message Content Intent** + **Server Members Intent**
- Scopes: `bot` + `applications.commands`
- Permissions: Read Messages, Send Messages, Read Message History, Embed Links
- Set up [TweetShift](https://tweetshift.com) to mirror analyst tweets into `DISCORD_FEED_CHANNEL_ID`

### 4. Start services and run

```bash
python3 -m consensus_engine                  # full engine
python3 -m consensus_engine --dry-run --once # no Discord, logs only
python3 -m consensus_engine --once           # single poll cycle
python3 -m consensus_engine --status         # health report
python3 -m pytest tests/ -v                  # test suite
```

### 5. Systemd service (optional)

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

```bash
systemctl daemon-reload && systemctl enable --now openclaw
```

---

## Configuration

All settings in `config/consensus.yaml`. API keys use `$ENV_VAR` syntax.

| Section | Controls |
|---|---|
| `api_keys` | All API keys (`$ENV_VAR` refs) |
| `llm` | `text_model`, `vision_model`, `min_confidence`, `max_tokens` |
| `scoring` | Base scores, multipliers, catalyst tiers |
| `news_cascade` | Tier order, Finnhub lookback, Brave daily budget |
| `intervals` | Social scan (5m), Reddit trend (4h), prune (15m) |
| `social` | Subreddit list, ApeWisdom/Trends toggles |
| `technical` | RVOL threshold, RSI bounds, EMA periods, ATR |
| `ticker_validation` | Min market cap ($100M), cache TTL |
| `scanners` | Background scanner toggles (incl. SEC watcher on/off) |
| `alerts` | Cooldown, max per hour, embed colors, min score |
| `database` | SQLite path, signal TTL (2h), history retention |
| `reliability` | R_class priors, contradiction threshold (0.75), min evidence mass (0.35) |
| `freshness_max_age` | Per-source staleness limits (market: 60s, options: 30m, news: 90m, X: 4h, YouTube: 24h) |
| `youtube` | `standalone_alerts`, `min_trust`, `macro_digest_utc_hour`, `level_alert_proximity_pct` |

---

## Alert Format

**Phase 1 — Instant Ping** (sent on tweet detection):
- Analyst display name + avatar, `$TICKER LONG/SHORT/NEUTRAL`, tweet text, current price, base score

**Phase 2 — Score Breakdown** (reply after cross-reference):
- News catalyst (headline + source), SEC filings, technical filters (6 pass/fail), social signals, options flow, LLM reasoning
- Full score: `base(25) + news(15) + tech(6) = 46`

---

## Scoring Reference

| Source | Points |
|---|---|
| Base (conviction) | 20–30 |
| Additional analyst | +20 each (max 3 = +60) |
| News catalyst — high tier | +25 (Earnings Beat, M&A, FDA) |
| News catalyst — medium tier | +15 (Analyst Upgrade, SEC Filing) |
| News catalyst — low tier | +8 (Partnership, Patent) |
| SEC filing (recent) | +15 |
| ApeWisdom mentions | +10 |
| Reddit mentions (2+) | +10 |
| Options flow (unusual) | +10 |
| Technical filters | +2 each (max +12) |
| Google Trends spike | +5 |
| LLM confidence boost | up to +15 |

Actionable alerts typically score 35–80+. Quality gate blocks signals with base score < 20.

---

## Project Structure

```
consensus_engine/
├── main.py                    # Pipeline orchestrator: all loops + tweet processing
├── cross_reference.py         # Parallel cross-ref aggregator
├── db.py                      # SQLite schema, queries, channel registry, YouTube tables
├── models.py                  # Dataclasses: ParsedTweet, TickerSignal, CrossReferenceResult, etc.
├── config.py                  # YAML config loader with $ENV_VAR resolution
├── engine.py                  # Budget management (atomic SQL)
├── alerts/
│   ├── discord.py             # Two-phase alert delivery (instant ping + score followup)
│   └── commands.py            # Discord command router (26 commands)
├── analysis/
│   ├── tweet_parser.py        # Multimodal tweet classification (text + vision via OpenRouter)
│   ├── video_parser.py        # YouTube transcript parsing (direction normalization, finish_reason retry)
│   ├── snapshot_builder.py    # Assemble evidence snapshot from signal_events
│   ├── reliability_engine.py  # W = R_class × R_entity × Q × D × I (Week 4, currently disabled)
│   ├── calibration.py         # Isotonic regression for confidence calibration
│   ├── technical.py           # Direction-aware technical filters
│   ├── llm_scorer.py          # LLM confidence boost scoring
│   └── indicators.py          # RVOL, VWAP, RSI, EMA, ATR
├── scanners/
│   ├── discord_tweetshift.py  # Discord Gateway listener (primary tweet ingestion)
│   ├── youtube.py             # YouTube RSS scanner + standalone alert trigger
│   ├── news.py                # 4-tier news cascade
│   ├── social.py              # Reddit, ApeWisdom, Google Trends
│   ├── options.py             # Unusual options activity
│   ├── reddit_trend.py        # Reddit trend digest
│   ├── sec_edgar.py           # SEC EDGAR filing scanner
│   ├── sec_watcher.py         # Real-time 8-K ATOM feed (disabled by default)
│   ├── volume_scanner.py      # RVOL >5x breakout detector
│   ├── earnings_calendar.py   # Upcoming earnings pre-alert
│   └── searxng.py             # SearXNG self-hosted search
└── utils/
    ├── http.py                # Shared aiohttp session
    ├── rate_limiter.py        # Async per-source limiter with exponential backoff
    ├── tickers.py             # Ticker extraction + blacklist + market-cap validation
    ├── transcript_fetch.py    # fetch_transcript_cascade (yt-dlp + fallbacks)
    ├── xref_cache.py          # In-memory cross-reference cache (5-min TTL)
    └── browser.py             # Playwright stealth browser

config/
├── consensus.yaml             # Main config (models, thresholds, intervals, API keys)
└── searxng/settings.yml       # SearXNG Docker config

scripts/
└── backtest.py                # Replay decision_snapshots vs price outcomes

tests/                         # 287 pytest tests
sources.json                   # Analyst Twitter accounts + followed YouTube channels
```

---

## Self-Hosted Services

| Service | Port | Status | Purpose |
|---|---|---|---|
| SearXNG | 8888 | Active | Meta search engine (Tier 4 news fallback) |

---

## Testing

```bash
python3 -m pytest tests/ -v
```

287 tests covering signal pipeline, reliability weighting, YouTube parser (direction normalization, finish_reason handling, chunk voting), Discord embeds, all commands, calibration, source health, degraded-mode policy, backtest, tweet parsing (multimodal + fallback), technical filters, Reddit, options, SEC, TweetShift, and price followup.

---

## Recent Changes (April 2026)

- **ytfinal.md plan (Week 2):** YouTube channel registry (`youtube_channels` table + `!yt-follow`), `youtube_macro` table + macro digest loop, standalone HIGH-conviction alerts, `!yt`/`!yt-mentions`/`!macro` Discord commands, level proximity alerter, precision engine as decision-maker (xref stays as enrichment), atomic budget SQL, aiohttp session close on exit, video_parser direction normalization + finish_reason retry handling
- **FinalYTplan (Phase A–D):** Reliability weighting, calibration, source health, degraded-mode policy, backtest script
- **PR #2:** Multimodal tweet parsing (text + vision router via OpenRouter)

### Recent changes (2026-04-24 PR)

Phase-2 timeout fix + signal routing + calibration shadow mode + per-analyst cooldown + require_market_confirmation rename. Fixes 78.4% Phase-2 drop rate by wrapping xref with `asyncio.wait_for(timeout=120s)` while keeping precision engine unaffected. Enables tweet signals to flow into `signal_events` table for xref scoring. Calibration begins logging shadow predictions to `decision_snapshots.feature_vector_json` without retraining. Per-analyst cooldown replaces blanket 6h with precision-weighted lookup. See `.omc/plans/2026-04-24-top3-combined-pr-plan.md` for full design + 13 acceptance criteria.

**New config flags:**
- `calibration.shadow_mode.enabled` — log predictions to decision_snapshots; relabel Discord field to "score/100 (uncalibrated)"
- `calibration.retrain_enabled` — enable model retraining (default false until signal_events >80% populated)
- `alerts.per_analyst_cooldown.enabled` — use precision-weighted per-analyst cooldown instead of blanket ticker-level
- `alerts.per_analyst_cooldown.floor_minutes` — min cooldown even for 100% accuracy analysts (default 30)
- `alerts.per_analyst_cooldown.high_conviction_bypass` — base_score >= high_conviction_threshold skips cooldown
- `precision_engine.thresholds.high_conviction_threshold` — base_score cutoff for exemptions (default 30)
- `precision_engine.thresholds.sec_catalyst_exempt` — skip require_market_confirmation gate for SEC catalysts

**Renamed (atomic, no shim):**
- `precision_engine.thresholds.require_market_confirmation` → `precision_engine.thresholds.require_market_confirmation_for_low_conviction`

**Deleted:**
- `alerts.max_alerts_per_hour` (no enforcement code)
- `alerts.reliability_engine_enabled` (module removed, guarded import block deleted, orphan .pyc cleaned)
- `regime_detector:` config stanza (module preserved for tests)
