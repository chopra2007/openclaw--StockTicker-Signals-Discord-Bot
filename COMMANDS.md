# OpenClaw Discord Commands

All commands are typed in the alerts Discord channel with a `!` prefix.

---

## General

### `!help`
Lists all available commands.

### `!status`
Engine health summary.
- Active signal count
- Last alerted ticker, score, and how long ago

### `!performance`
Alert win rates and P&L stats.
- Total alerts (all-time and last 7 days)
- Win rate at 1h and 24h
- Average P&L at 1h and 24h
- Top 3 best and worst alerts by 1h P&L

---

## On-Demand Scans

### `!scan <TICKER>`
Full cross-reference pipeline on any ticker.
Runs: news cascade + SEC check + technical filters + social signals + LLM confidence + options flow.
Returns score breakdown and top findings.
Example: `!scan NVDA`

### `!news <TICKER>`
Run the news cascade standalone without a full scan.
Returns: catalyst type (e.g. Earnings Beat, FDA Approval), summary, and sources.
Example: `!news TSLA`

### `!sec <TICKER>`
Recent SEC filings for a ticker (last 72 hours).
Covers: 8-K (material events), 10-K/10-Q (earnings), Form 4 (insider trades), SC 13D/G (activist/institutional).
Example: `!sec AAPL`

### `!options <TICKER>`
Unusual options activity for a ticker.
Returns: put/call ratio, unusual call/put flags, max vol/OI ratio, top contract.
Example: `!options NVDA`

### `!technical <TICKER> [long|short]`
Run the 6 technical filters for a ticker. Direction defaults to `long`.
Filters: RVOL, VWAP, RSI, EMA crossover, price change %, ATR breakout.
Returns pass/fail for each filter plus current price and % change.
Example: `!technical NVDA` or `!technical NVDA short`

### `!google-trends <TICKER>`
Google Trends interest change % for a ticker.
A spike of 20%+ is flagged as notable.
Example: `!google-trends NVDA`

---

## Ticker Intel

### `!signals <TICKER>`
Active signal counts broken down by source (Twitter, Reddit, StockTwits, news, etc.).
Example: `!signals NVDA`

### `!analysts <TICKER>`
Analyst handles who mentioned a ticker in the last hour.
Example: `!analysts NVDA`

### `!active-tickers`
All tickers that currently have at least one active signal in the DB.

### `!alert-history <TICKER>`
Last 10 alerts for a ticker with entry price and 1h/24h P&L outcomes.
Example: `!alert-history NVDA`

---

## Market Scanners

### `!trend`
Trigger an on-demand Reddit trend digest.
Crawls 7 finance subreddits, ranks tickers by mentions/momentum, and posts a digest embed.

### `!stocktwits`
Fetch StockTwits trending symbols (via Playwright stealth browser).

### `!apewisdom`
Fetch ApeWisdom trending tickers (direct REST API).

---

## Engine Health

### `!nitter-health`
Check if the Nitter Docker service is online and responding.
Returns: online / degraded (HTTP status) / offline.

---

## Scoring Reference

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

Typical actionable alerts score **35–80+**. The quality gate blocks anything below a base score of 25.
