# Stock Signals

Stock Signals is a self-hosted stock-research and Discord alert system. It watches independent market sources, sends fast analyst-call alerts, adds supporting evidence, and measures what happened after each call.

**Python 3.10+ · Discord · SQLite · self-hosted**

[Features](#features) · [Signal sources](#signal-sources) · [How it works](#how-it-works) · [Quick start](#quick-start) · [Commands](#discord-commands) · [Project map](#project-map)

## Features

| Area | What Stock Signals does |
|---|---|
| **Fast alerts** | Turns an analyst call into an immediate Discord alert, then adds the deeper cross-check when it is ready. |
| **Whole-market research** | Combines news, SEC filings, options, technical levels, social activity, and video evidence. |
| **One-command analysis** | `!all NVDA` gathers every available source and turns it into one readable AI summary. |
| **Options intelligence** | Finds unusual activity and builds daily or weekly expected-move charts with `!em` and `!emw`. |
| **YouTube research** | Tracks channels, reads transcripts, extracts ticker calls and levels, and keeps evidence tied to the source video. |
| **Honest measurement** | Stores alert entry prices and later outcomes so `!performance` and `!leaderboard` use recorded results. |
| **Health checks** | Reports stale or failing sources, feature state, and degraded behavior directly in Discord. |

## Signal Sources

| Source | What it contributes |
|---|---|
| **Analyst posts** | Direction, conviction, ticker, catalyst, and chart text or images. |
| **YouTube** | Transcript-based calls, price levels, macro views, and grounded evidence. |
| **News** | Earnings, deals, approvals, analyst actions, filings, partnerships, and other catalysts. |
| **SEC EDGAR** | Recent company filings and insider activity used as evidence. |
| **Options** | Unusual volume, open-interest ratios, implied volatility, and expected moves. |
| **Technical data** | Relative volume, VWAP, RSI, moving averages, breakouts, support, and resistance. |
| **Social interest** | Reddit, ApeWisdom, and search-interest changes. |
| **Market context** | Breadth, sector rotation, volatility, regime, and short-interest context. |

## How It Works

```text
Analyst or scanner signal
        ↓
Immediate Discord alert
        ↓
Parallel cross-check across independent sources
        ↓
Evidence, score, conflicts, and follow-up results
```

The first alert is built for speed. Slower research runs after it, so one delayed source does not hold up the initial message. Stored outcomes feed the performance and analyst-ranking commands.

## Quick Start

### 1. Install

```bash
git clone https://github.com/chopra2007/openclaw--StockTicker-Signals-Discord-Bot.git
cd openclaw--StockTicker-Signals-Discord-Bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Add your service keys

The core setup uses Discord, OpenRouter, Finnhub, and a TweetShift feed channel. Keep keys in a local environment file; never save them in Git.

```bash
export DISCORD_BOT_TOKEN="<your token>"
export DISCORD_CHANNEL_ID="<alerts channel>"
export DISCORD_FEED_CHANNEL_ID="<analyst-feed channel>"
export OPENROUTER_API_KEY="<your key>"
export FINNHUB_API_KEY="<your key>"
```

Enable **Message Content** and **Server Members** for the Discord bot. Grant it permission to read messages, send messages, read history, and add embeds.

Optional sources are controlled in [`config/consensus.yaml`](config/consensus.yaml).

### 3. Run

```bash
python3 -m consensus_engine --dry-run --once  # one safe check; sends no Discord alert
python3 -m consensus_engine                  # start the engine
python3 -m consensus_engine --status         # print current health
```

SearXNG is an optional self-hosted news fallback:

```bash
docker compose up -d
```

## Discord Commands

The built-in `!help` card lists 34 main Discord commands. These are the main entry points:

| Command | Result |
|---|---|
| `!all NVDA` | One AI-written analysis using every available source. |
| `!scan NVDA` | A fast score, evidence list, and green/yellow/red result. |
| `!sweep` | Ranks the current watchlist. |
| `!em SPY` / `!emw SPY` | Daily or weekly options-implied expected move with a chart. |
| `!market` | Market breadth, sector, volatility, and regime context. |
| `!yt <url>` | Video analysis with tickers, conviction, levels, and evidence. |
| `!performance` | Recorded alert results and profit/loss statistics. |
| `!source-health` | Freshness and error status for outside data sources. |

See the [full Discord command guide](docs/reference/DISCORD_COMMANDS.md), or type `!help` in Discord.

## Project Map

```text
consensus_engine/   main engine, alerts, analysis, scanners, and research
config/             non-secret settings and source controls
scripts/            setup, maintenance, reports, and research tools
tests/              automated behavior checks
docs/               setup notes, project rules, history, and reference guides
infra/              background-program and deployment files
todo/               detailed work records linked from TODO.md
```

The main settings file is [`config/consensus.yaml`](config/consensus.yaml). The engine starts in [`consensus_engine/main.py`](consensus_engine/main.py), Discord commands live in [`consensus_engine/alerts/commands.py`](consensus_engine/alerts/commands.py), and source readers live in [`consensus_engine/scanners/`](consensus_engine/scanners/).

## Development

```bash
python3 -m pytest tests/ -v
```

Start with the [documentation index](docs/README.md) for commands, project rules, and migration notes. Historical design work stays under [`plans/`](plans/) so the front page can stay focused on what the project does today.
