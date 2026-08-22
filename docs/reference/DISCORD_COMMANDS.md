# Discord Command Guide

Type commands in Discord with a `!` prefix. The built-in `!help` card lists the 34 main commands below.

Ticker commands accept uppercase or lowercase symbols. Most accept more than one ticker, such as `!em spy qqq`; `!all` accepts up to three.

## Core

| Command | Result |
|---|---|
| `!scan <ticker>` | Full check with one score, evidence, and a green/yellow/red result. |
| `!sweep` | Scores and ranks the current watchlist. |
| `!all <ticker>` | Gathers every source into one AI-written analysis. |
| `!ask <question>` | Answers a free-form question using the bot's research tools. |
| `!status` | Shows engine health, active signals, and the most recent alert. |
| `!performance` | Shows recorded alert win rates and profit/loss results. |
| `!trend` | Posts the latest Reddit trend digest. |
| `!help` | Shows the command card in Discord. |

## Ticker Research

| Command | Result |
|---|---|
| `!signals <ticker>` | Active signal counts grouped by source. |
| `!analysts <ticker>` | Analysts who mentioned the ticker recently. |
| `!news <ticker>` | Recent headlines and detected catalysts. |
| `!sec <ticker>` | Recent company filings and insider activity. |
| `!options <ticker>` | Unusual options activity and volume/open-interest ratios. |
| `!em <ticker>` | Options-implied daily expected move and chart. |
| `!emw <ticker>` | Options-implied weekly expected move and chart. |
| `!technical <ticker> [long\|short]` | Direction-aware technical checks. |
| `!google-trends <ticker>` | Search-interest change for the ticker. |
| `!alert-history <ticker>` | Recent alerts with recorded 1-hour and 24-hour outcomes. |
| `!active-tickers` | Every ticker with an active signal. |

## YouTube Research

| Command | Result |
|---|---|
| `!yt <url>` | Analyzes a video for tickers, conviction, levels, and evidence. |
| `!transcript <url>` | Fetches the video's transcript text. |
| `!yt-mentions <ticker>` | Recent YouTube signals for a ticker. |
| `!macro` | Builds a macro digest across followed channels. |
| `!yt-follow <channel>` | Adds a YouTube channel to the followed list. |
| `!yt-health` | Shows recent pipeline health and processing limits. |
| `!yt-evidence <video-id>` | Shows grounded evidence spans from a processed video. |

## Levels and Scanners

| Command | Result |
|---|---|
| `!levels <ticker>` | Support and resistance from videos and stored signals. |
| `!cluster <ticker>` | Price-level cluster history. |
| `!apewisdom` | ApeWisdom's currently trending tickers. |
| `!leaderboard` | Analyst results ranked from recorded outcomes. |
| `!catalysts` | Catalyst calls graded against their market sector. |

## Engine Health

| Command | Result |
|---|---|
| `!source-health` | Freshness and error status for outside data sources. |
| `!feature-health` | Feature state and the most recent state change. |
| `!shadow-mode-report <feature>` | A 14-day measurement report for a feature still being evaluated. |

Additional live routes include `!market` for market context and `!short <ticker>` for short-interest research. The source of truth is [`consensus_engine/alerts/commands.py`](../../consensus_engine/alerts/commands.py).
