# Changes & Updates - OpenClaw Project

## Overview
OpenClaw is a **Signal-First Stock Alert Engine** that monitors analyst tweets on Twitter/X and triggers instant Discord alerts with cross-referenced scoring from news, social, technical, and LLM sources.

---

## Recent Changes (Latest First)

### Performance Optimization (2026-03-30)
**Commit:** `87f4478`
- Parallel cross-reference cascade (news, social, technical, analyst mentions run concurrently)
- Global async session object for all HTTP requests (connection pooling)
- Database-backed caching for rate limiter state
- Alert cooldown mechanism to prevent duplicate notifications
- Improved latency: 2-3 seconds saved per cross-reference cycle

### Documentation & Test Suite Expansion (2026-03-29)
**Commit:** `35f5f26`
- Updated README with 5 proactive scanners
- Tiered catalyst scoring system documented
- New CLI commands documented
- **148 unit tests** now passing (comprehensive coverage)

### Proactive Scanners Implementation (2026-03-29)
**Commit:** `eaa029d`
- Added 5 new proactive scanners:
  - Pre-market gap scanner (>3% moves via Finnhub)
  - Technical pattern detection (RSI, VWAP, EMA crossovers)
  - Social sentiment spike detector
  - Analyst leaderboard tracking
  - Earnings beat catalyst scorer
- Cross-reference cache for faster lookups
- Analyst leaderboard ranking (tracks accuracy of analysts)
- Fallback direction detection for missing technical indicators

### Pre-Market Gap Scanner (2026-03-28)
**Commit:** `da68890`
- Detects stocks with >3% gaps before market open
- Uses Finnhub real-time quote API
- Triggers alerts for high-conviction gap moves
- Scheduled to run 30 minutes before market open

### Tiered Catalyst Scoring (2026-03-27)
**Commit:** `93e3857`
- Earnings beats scored highest: 25 points
- Partnership announcements: 8 points
- FDA approvals, SEC filings: variable tiers
- Prevents score inflation from low-conviction catalysts

---

## Major Features

### Reddit Integration Fix
**Commit:** `dcf54b8`
- Switched from deprecated RSS feed to Reddit JSON API (`/new.json`)
- Avoids rate limiting on old RSS endpoint
- Direct JSON parsing for faster processing

### Analyst Score Capping
**Commit:** `613b52c`
- Caps analyst mention multiplier at 3x
- Prevents score inflation when 10+ analysts mention same ticker
- Maintains signal credibility

### LLM Call Optimization
**Commit:** `69f5d91`
- Removed double LLM call in cross-reference engine
- Saves API budget and 2-3 seconds per alert
- Single LLM call for confidence scoring

### Quality Gate Adjustment
**Commit:** `c37c1f2`
- Lowered quality gate threshold to 20
- LOW conviction alerts with confirmed direction now trigger
- Improved signal sensitivity while maintaining accuracy

---

## Fixes & Improvements

### Command System Enhancement
**Commit:** `d7bc1f1`
- 12 new Discord commands added
- Consolidated documentation
- Improved user interface

### Alert Styling
**Commit:** `1b55a29`
- Alerts now match TweetShift embed format
- Exchange name false positives eliminated
- Better visual consistency in Discord

### API Key Management
**Commit:** `1b55a29`
- Switched to `SERPAPI2_API_KEY` after quota exhaustion
- Support for multiple API key rotation
- Graceful fallback to alternative search engines

### Model Configuration
**Commit:** `f71e0ea`
- Removed invalid `openrouter/` prefix from LLM model ID
- Correct Anthropic SDK format

### Testing & Validation
**Commit:** `e6a2c5b`
- Added 26 new unit tests
- Price-at-alert capture now correctly working
- Backtesting script for quality gate validation

### System Reliability
**Commit:** `0dcc242`
- Graceful shutdown handling
- `!performance` command for monitoring
- Blacklist system for noisy signals
- Database vacuum for cleanup
- Reddit tuning for better performance

---

## Architecture

### Core Pipeline
```
Scanners (Nitter RSS, TweetShift Discord Gateway)
    ↓
LLM Tweet Parser (Type A/B/C/D classification)
    ↓
Instant Discord Alert (Phase 1)
    ↓
Async Cross-Reference Engine (Phase 2)
    ├─ News Cascade (Finnhub → Google → Brave → SearXNG)
    ├─ Social Scanner (Reddit, ApeWisdom, Google Trends)
    ├─ Technical Analysis (RVOL, VWAP, RSI, EMA, ATR)
    ├─ Analyst Mentions (Cross-reference with other analysts)
    └─ LLM Confidence Scorer
    ↓
Detail Reply with Score Breakdown
```

### Self-Hosted Services
- **Nitter** (localhost:8585) — Twitter RSS proxy
- **SearXNG** (localhost:8888) — Meta search engine fallback

### Key Technologies
- **Python 3.9+** with async/await patterns
- **SQLite** for signal persistence and caching
- **Discord.py** for bot integration
- **aiohttp** for async HTTP requests
- **yfinance** for historical OHLCV data
- **Finnhub API** for real-time quotes
- **Anthropic API** for LLM parsing and scoring

---

## Configuration

All settings in `config/consensus.yaml`:
- Polling intervals (60s market hours, 180s off-hours)
- Quality thresholds (20 minimum for alert)
- Cross-reference weights (news, social, technical)
- Rate limiting settings
- Alert cooldown durations

API keys via environment variables (e.g., `$FINNHUB_API_KEY`).

Twitter analyst accounts loaded from `/root/.openclaw/sources.json` (48 accounts).

---

## Testing

**148 tests passing** covering:
- Tweet parsing and classification
- Score calculation and tiering
- Database operations
- API integrations
- Discord alert formatting

Run tests:
```bash
python3 -m pytest tests/ -v
python3 -m consensus_engine --test
```

---

## Installation

```bash
pip3 install aiohttp aiosqlite pyyaml yfinance playwright-stealth
playwright install chromium && playwright install-deps chromium
docker compose up -d
```

---

## Project Stats

- **20+ commits** documenting evolution from prototype to production system
- **5 proactive scanners** added for edge case detection
- **12 Discord commands** for monitoring and control
- **148 unit tests** ensuring reliability
- **2-3 second improvement** in cross-reference latency
- **4-tier news cascade** for catalyst validation

---

## Next Steps / Roadmap

- [ ] Backtest quality gates on historical data
- [ ] Add support for earnings calendar integration
- [ ] Implement ML-based analyst accuracy ranking
- [ ] Expand technical indicator library
- [ ] Add price target consensus from multiple sources
