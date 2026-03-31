# USER.md - About Your Human

- **Name:** Akash Chopra
- **What to call them:** AK
- **Pronouns:** 
- **Timezone:** 
- **Notes:** Building an automated stock trend detection system

## Context

AK set me up on March 11, 2026 with a directive to discover trending US stock opportunities. The system has evolved into a **Signal-First Stock Alert Engine** that monitors analyst tweets on Twitter/X.

### Current Pipeline (Twitter/X-Based)

**Phase 1 - Detection:**
- Monitors 48 analyst accounts via Nitter (Twitter RSS proxy)
- LLM classifies tweets as Type A/B/C/D signals
- Instant Discord alert triggered for any signal

**Phase 2 - Cross-Reference (async cascade):**
- News validation (Finnhub → Google → Brave → SearXNG)
- Social sentiment (Reddit, ApeWisdom, Google Trends)
- Technical analysis (RVOL, VWAP, RSI, EMA, ATR)
- Analyst mention cross-reference
- LLM confidence scoring

**5 Proactive Scanners:**
- Pre-market gap scanner (>3% moves via Finnhub)
- Technical pattern detection (RSI, VWAP, EMA crossovers)
- Social sentiment spike detector
- Analyst leaderboard tracking
- Earnings beat catalyst scorer

### Commands

- `!trend` — On-demand analysis
- `!performance` — System monitoring
- Plus 12 other Discord commands

### Tech Stack

- Python 3.9+ with async/await
- SQLite for persistence & caching
- Discord.py for bot
- Finnhub API for quotes/news
- Anthropic API for LLM parsing