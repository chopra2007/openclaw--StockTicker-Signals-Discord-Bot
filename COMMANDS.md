# AVAILABLE COMMANDS

The following commands are actively monitored in chat to trigger the **Stock Trend Consensus Engine** — a 5-stage pipeline requiring multi-source agreement before alerting.

- **`!help`**
  Outputs the comprehensive guide and key for using Clawdbot (same as !readme).

- **`!readme`**
  Outputs the comprehensive guide and key for using Clawdbot, including explanations of all commands, metrics, and an output example.

- **`!list`**
  Lists all available commands and what they do.

- **`!trend`**
  Runs a single cycle of the consensus engine. Scans Twitter/X (49 analyst accounts), social platforms (Reddit, StockTwits, ApeWisdom, Google Trends), news sources (15+ trusted outlets via Brave Search), runs technical analysis (6 filters: RVOL, VWAP, RSI, EMA cross, price change, ATR breakout), and LLM confidence scoring. Only tickers passing ALL 5 gates trigger a Discord alert.

- **`!trend live`**
  Starts the consensus engine in continuous mode with concurrent scanner loops. Runs indefinitely until stopped.

- **`!trend stop`**
  Stops any running consensus engine process.

- **`!trend status`**
  Shows the engine health dashboard: signal counts per scanner, scanner timings, recent alerts, and active tickers under evaluation.

- **`!scan [TICKER]`**
  Bypasses the trending threshold logic and performs an immediate, deep-dive research on a specific stock. Spawns a researcher sub-agent to summarize Reddit sentiment, find recent catalysts, and flag risks for that specific ticker.

- **`!status`**
  Same as `!trend status` — returns the consensus engine health dashboard.
