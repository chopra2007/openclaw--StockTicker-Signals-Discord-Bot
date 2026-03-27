# 📖 StockBot README & User Guide 📖

Welcome to **StockBot**, the automated US equity research agent that scans social media and financial platforms to detect rapidly trending stocks before they break out.

---

## 🛠️ COMMANDS
- **`!readme`** — Displays this guide and key.
- **`!list`** — Lists all available commands.
- **`!trend`** — Forces a fresh web crawl across all sources, calculates new scores, and spawns AI researchers to write a full catalyst report on the Top 5 tickers.
- **`!trend digest`** — Instantly outputs the math and rankings from the most recently cached data (no waiting for a new crawl).
- **`!scan [TICKER]`** — Spawns an AI researcher to perform an immediate deep-dive on a specific stock (e.g., `!scan AAPL`), summarizing sentiment, catalysts, and risks.
- **`!status`** — Checks the background crawler's health and database cache size.

---

## 📊 METRICS & ATTRIBUTES KEY
When a stock is listed in a digest, you will see several metrics. Here is how to interpret them:

- **Trend Score:** The master "quality" score. It combines volume, velocity, and user breadth. Scores scale infinitely. (<5 is noise, 10+ is a strong trend, 20+ is a viral frenzy). Cross-platform mentions add a +20% multiplier.
- **Momentum (e.g., 📈 2.0x):** Velocity metric measuring the last 24 hours vs the previous 24 hours. `1.0x` means flat background chatter. `2.0x` means mentions doubled overnight. `4.0x+` means the ticker is going viral.
- **Mentions (24h):** The raw number of times the ticker was mentioned across all tracked platforms in the last 24 hours.
- **Unique Authors:** The number of distinct users discussing the stock. High authors = organic crowd consensus. Low authors = potential bot spam.
- **Upvote Velocity:** The hourly rate of upvotes the posts are receiving (primarily Reddit data). High velocity means the posts are hitting the front page.
- **Spotted On:** The platforms where the ticker was detected (e.g., Reddit, Yahoo, StockTwits). 

---

## 🎭 SENTIMENT TONES & EMOJIS
- **Bullish 📈**: Retail/institutional expectation of price rising. Driven by earnings beats, upgrades, options flow, or strong technicals.
- **Bearish 📉**: Expectation of price falling. Driven by short interest, negative catalysts, or profit-taking.
- **Meme-Bullish 🦍 📈**: Pure speculative frenzy. Driven by "diamond hands", FOMO, and short-squeeze narratives. Price can rocket on pure social momentum.
- **Meme-Bearish 🦍 📉**: The hype wave is crashing. Panic selling and fading momentum on a former meme stock.

---

## 📝 OUTPUT EXAMPLE
**1. $PLTR** - Meme-Bullish 🦍 📈 (Trend Score: 18.5)
- **Mentions (24h):** 145 | **Unique Authors:** 112 | 📈 3.2x Momentum
- **Spotted On:** Reddit, StockTwits, Yahoo Finance
- *(AI Sub-agent will follow up with catalyst notes: e.g., "New $178M DOD contract announced today, massive retail FOMO.")*
