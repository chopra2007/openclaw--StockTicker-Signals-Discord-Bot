# OpenClaw Optimization & Proactive Scanners — Design Spec

## Goal

Maximize signal quality from existing analyst-tweet pipeline AND add proactive scanners that detect trending stocks before analysts tweet about them.

---

## Phase 1: Quick Wins (Bug Fixes + Reddit)

### 1.1 Remove Double LLM Call
- **File**: `consensus_engine/cross_reference.py:125`
- **Problem**: `_run_llm_score(ticker, None, None)` in `asyncio.gather()` always returns 0. Then called again with real data at line 130. Wastes an API call + 2-3s latency.
- **Fix**: Remove line 125 from gather. Initialize `llm_score, llm_reasoning = 0, ""`. After gather, if `technical or catalyst`, call LLM once with real data.

### 1.2 Fix Quality Gate Threshold
- **File**: `consensus_engine/main.py:78`, `config/consensus.yaml:141`
- **Problem**: `min_base_score_for_alert: 25` blocks all LOW conviction tweets (score=20), even those with explicit LONG/SHORT direction.
- **Fix**: In `_passes_quality_gate()`, allow LOW conviction through if direction is LONG or SHORT (not NEUTRAL). Line 74 already filters LOW+NEUTRAL — remove the blanket score check for directional tweets OR lower threshold to 20.
- **Chosen approach**: Lower `min_base_score_for_alert` to 20 in config. The existing line 74 filter (LOW+NEUTRAL → skip) is sufficient quality control.

### 1.3 Cap Analyst Multiplier
- **File**: `consensus_engine/cross_reference.py:132`, `config/consensus.yaml`
- **Problem**: `additional_analyst: 20` per analyst, no cap. 10 analysts = +200 artificial points.
- **Fix**: Add `max_additional_analysts: 3` to config. Cap: `min(len(other_analysts), max_cap) * pts`.

### 1.4 Reddit JSON API Migration
- **File**: `consensus_engine/scanners/social.py`
- **Problem**: Reddit RSS (`/new/.rss`) returns 403 (rate limited). Scanner disabled.
- **Fix**: Replace `_fetch_subreddit_rss()` with `_fetch_subreddit_json()` using `https://www.reddit.com/r/{sub}/new.json?limit=25`. Parse JSON response instead of XML. Keep existing `User-Agent` header. Rate limit: 1 req/sub/min (well within Reddit's 100 req/min).

---

## Phase 2: New Signal Sources

### 2.1 Pre-Market Gap Scanner
- **New file**: `consensus_engine/scanners/premarket.py`
- **Purpose**: Scan top tickers for >3% pre-market gaps, 8:00-9:25am ET
- **Data source**: Finnhub `/quote` (free tier, real-time quotes)
- **Config**: `premarket.enabled`, `premarket.gap_threshold_pct: 3.0`, `premarket.scan_interval: 300`
- **Ticker list**: Top 200 by volume from `config/consensus.yaml` watchlist
- **Output**: Discord digest message listing gaps, sorted by magnitude
- **Discord command**: `!gaps` — show current pre-market gaps on demand
- **Loop integration**: New background task in `main.py`, runs only during pre-market window

### 2.2 SEC 8-K Real-Time Watcher
- **New file**: `consensus_engine/scanners/sec_watcher.py`
- **Purpose**: Poll SEC EDGAR for new 8-K filings every 15 min. Catches material events before analysts.
- **Data source**: SEC EDGAR ATOM feed (`https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=40&output=atom`)
- **Flow**: Parse ATOM → extract company/CIK → resolve ticker via existing `sec_edgar.py` or Finnhub → market cap filter ($100M+) → classify filing type → trigger cross-reference for high-significance filings
- **Dedup**: Use filing accession number in `seen_tweets` table
- **Alert format**: Same two-phase format (instant ping + xref reply) with "SEC Filing" source label

### 2.3 Tiered Catalyst Scoring
- **Files**: `config/consensus.yaml`, `consensus_engine/cross_reference.py`
- **Problem**: All catalysts score equally (+15 points)
- **Fix**: Add tiered config:
  ```yaml
  catalyst_tiers:
    high: 25   # Earnings Beat, M&A, FDA Approval, Government Contract
    medium: 15 # Analyst Upgrade, SEC Filing, Insider Buying, Guidance
    low: 8     # Partnership, Patent, Product Launch, Breaking News
  ```
- **Lookup**: Use `catalyst.catalyst_type` string to match tier. Default to `medium` if unknown.

---

## Phase 3: Smart Money & Proactive

### 3.1 Unusual Options Sweep Scanner
- **File**: Expand `consensus_engine/scanners/options.py`
- **Purpose**: Market-wide scan for unusual options volume (not just per-ticker validation)
- **New function**: `scan_unusual_options_market()` — scan top 100 optionable tickers
- **Criteria**: Single chain >5x normal volume AND >$100K notional
- **Interval**: Every 30 min during market hours
- **Alert**: "Options Sweep Alert" with ticker, direction (call/put), strike, expiry

### 3.2 Volume Breakout Scanner
- **New file**: `consensus_engine/scanners/volume_scanner.py`
- **Purpose**: Detect RVOL >5x during market hours (9:30am-4pm ET)
- **Data source**: Finnhub `/quote` for current volume, yfinance for historical avg
- **Filter**: RVOL >5x AND price change >1% AND market cap >$500M
- **Action**: Trigger full cross-reference pipeline for qualifying tickers
- **Interval**: Every 15 min during market hours

### 3.3 Earnings Calendar Pre-Alert
- **New file**: `consensus_engine/scanners/earnings_calendar.py`
- **Purpose**: Alert 24h before tracked stocks report earnings
- **Data source**: Finnhub `/calendar/earnings` (free tier)
- **Cross-reference**: Filter to tickers mentioned by analysts in last 7 days (from DB)
- **Alert**: "$NVDA reports earnings TOMORROW after close. Last 4 quarters: beat x3, miss x1."
- **Schedule**: Runs daily at 6pm ET

---

## Phase 4: Quality & Trust

### 4.1 Per-Analyst Win Rate + Leaderboard
- **Files**: `consensus_engine/db.py`, `consensus_engine/alerts/commands.py`
- **New DB function**: `get_analyst_performance_stats()` — join `alert_messages` (analyst) with `alert_history` (price outcomes) via ticker + time window
- **Metrics**: Total alerts, win rate @1h, win rate @24h, avg P&L
- **Discord command**: `!leaderboard` — top/bottom analysts by win rate

### 4.2 Cross-Reference Result Cache
- **New file**: `consensus_engine/utils/xref_cache.py`
- **Purpose**: Cache xref results per ticker for 5 minutes. 3 analysts tweet same ticker in 60s → 1 real xref + 2 cache hits.
- **Implementation**: In-memory dict with TTL. Key: ticker. Value: `CrossReferenceResult` + timestamp.
- **Integration**: Check cache at top of `cross_reference()`, populate after computation.

### 4.3 Fallback Parser Direction Detection
- **File**: `consensus_engine/analysis/tweet_parser.py:176-190`
- **Problem**: `_fallback_parse()` always returns `Direction.NEUTRAL`.
- **Fix**: Add keyword scan before defaulting:
  - LONG keywords: "long", "buy", "bullish", "calls", "moon", "breakout", "gap up"
  - SHORT keywords: "short", "put", "bearish", "puts", "dump", "gap down", "crash"
  - If match → set direction accordingly. Else → NEUTRAL.

---

## Testing Strategy

Each phase adds tests:
- Phase 1: Unit tests for fixed quality gate logic, capped multiplier, Reddit JSON parsing
- Phase 2: Unit tests for premarket gap detection, SEC feed parsing, tiered scoring lookup
- Phase 3: Unit tests for options sweep criteria, volume breakout thresholds, earnings calendar filtering
- Phase 4: Unit tests for analyst stats query, cache TTL behavior, fallback direction detection

All tests must pass (`pytest tests/ -v`) before each phase is committed.

---

## Files Modified/Created Summary

| Action | File |
|--------|------|
| Modify | `consensus_engine/cross_reference.py` |
| Modify | `consensus_engine/main.py` |
| Modify | `consensus_engine/scanners/social.py` |
| Modify | `consensus_engine/scanners/options.py` |
| Modify | `consensus_engine/analysis/tweet_parser.py` |
| Modify | `consensus_engine/db.py` |
| Modify | `consensus_engine/alerts/commands.py` |
| Modify | `config/consensus.yaml` |
| Create | `consensus_engine/scanners/premarket.py` |
| Create | `consensus_engine/scanners/sec_watcher.py` |
| Create | `consensus_engine/scanners/volume_scanner.py` |
| Create | `consensus_engine/scanners/earnings_calendar.py` |
| Create | `consensus_engine/utils/xref_cache.py` |
