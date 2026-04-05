# System Issues & Changes Documentation

## User Goals & Requirements (As Stated by AK)

### Alert Philosophy
- **Quality over quantity** - Fewer alerts, but each tells the full story
- **Actionable intelligence** - Need to quickly understand if buy/sell
- **Multiple source confirmation** - Need 2+ independent sources before alerting

### Specific Requirements

#### 1. Minimum Confirmation Sources
- **2 sources minimum** for most alerts
- **EXCEPTION:** Trade-specific signals - these trigger instant alerts alone

**What Makes Something "Trade-Specific":**
The analyst tweet explicitly identifies a specific, actionable trade setup:
- Large options activity (e.g., "huge call volume on $XYZ")
- Insider trading detected (e.g., "CEO just bought $1M of stock")
- Unusual options flow
- Technical breakout setup with specific levels
- Quant/factor signals

**NOT Trade-Specific (needs 2+ sources):**
- General bullish/bearish commentary
- Market outlook
- Earnings predictions without specific levels
- General news about company

#### 2. Broader Catalysts Need Independent Confirmation
- News or earnings alerts need at least 1 independent source confirming:
  - Major news outlet
  - Social trend (ApeWisdom, Reddit, StockTwits)
  - SEC filing

#### 3. SEC Filing Rules (Updated April 2-3)
- **8-K filings NEVER trigger standalone alerts**
- Form 4 (insider trading) - stored for cross-reference, adds context/scoring (+15 points)
- All SEC filings integrated into LLM thesis generation
- SEC data used to build "bigger picture" thesis, not standalone alerts

#### 4. Alert Types
| Type | Trigger | Format |
|------|---------|---------|
| Trade-Specific | Analyst tweet with specific trade (options, insider) | Instant - Ticker, Direction, Price, Score |
| Broader Catalyst | 2+ sources confirming | Goes to digest - full cross-ref |

#### 5. Desired Alert Format
- Ticker + Direction
- Primary catalyst (what's driving the move)
- Analyst opinion
- Supporting data (social, news, SEC, technical)
- Confidence score
- **LLM-generated thesis** (1 paragraph explaining why bullish/bearish)

---

## Changes Made (Chronological)

---

## ✅ Changes Implemented

### 1. Pytrends Integration
- **Installed:** `pip3 install pytrends`
- **Added:** `scan_google_trends_pytrends()` function in `social.py`
- **Added:** `scan_google_trends_combined()` - tries Pytrends first, Exa AI fallback if disabled
- **Added:** `scan_google_trends_exa()` - Exa AI fallback using recent article count as trend proxy
- **Config:** Added `pytrends_enabled: true`, `pytrends_interval_minutes: 30`, `exa: "$EXA_AI_API_KEY"` in `consensus.yaml`
- **Non-blocking:** Pytrends runs as `asyncio.create_task()` in `social_scan_loop` — 300s loop stays on schedule
- **Executor:** Blocking pytrends calls run in thread executor so event loop stays free
- **NaN fix:** Skips tickers where pandas returns NaN (was causing false -100% on first-time queries)
- **Smart sleep:** 60s delay only between requests, not before first
- **Auto-disable:** If 3 rate-limits in 24h, Pytrends auto-disables → Exa AI takes over
- **Cron:** SerpAPI runs once/day at 5:50am via `jobs.json` (never called in social loop)

### 2. Command Updates
- Added `!serpapi-trends` command for manual SerpAPI runs
- Updated `COMMANDS.md` and `README.md`

### 3. Cross-Reference Timeout Fix (commit b520a4b)
- Added `_with_timeout()` helper wrapping each source in `asyncio.gather()`
- Per-source limits: news=15s, SEC=10s, social=5s, technical=20s, analysts=5s, options=15s, LLM=15s
- Timed-out sources return safe defaults so scoring continues with available data
- Overall 120s timeout on `cross_reference()` via `cross_reference_timeout` config
- Clean `asyncio.TimeoutError` log message in `_run_cross_reference_and_followup`

---

## ✅ Resolved Problems

### ~~Problem 1: Cross-Reference Hangs~~
**Status: FIXED** (commit b520a4b, April 1 2026)

~~**Symptom:** Alerts show "(cross-references pending...)" forever, `final_score = 0`~~

**Fix:** Per-source timeouts in `asyncio.gather()` + overall 120s cap. Sources that time out
return safe defaults (None/{}/[]) so the rest of scoring completes normally.

---

### ~~Problem 2: Pytrends Returns -100%~~
**Status: FIXED** (commit 2409a58, April 1 2026)

~~**Symptom:** Some tickers show `-100%` Google Trends~~

**Fix:** Added `pd.isna()` check before computing delta. Skip rows where recent or earlier
value is NaN. Both-zero case also skipped (no meaningful signal).

---

## 🔗 Related Files

- `/root/.openclaw/workspace/consensus_engine/scanners/social.py` - Pytrends + Exa functions
- `/root/.openclaw/workspace/consensus_engine/cross_reference.py` - Cross-reference logic
- `/root/.openclaw/workspace/config/consensus.yaml` - Config settings
- `/root/.openclaw/cron/jobs.json` - SerpAPI cron job (5:50am daily)

---

## 📊 SEC/EDGAR Integration (Updated April 3)

The LLM now receives SEC/EDGAR data in its prompt to synthesize a thesis.

### What's Included in LLM Prompt:
- Form 4 (insider buying/selling) - detected and detailed
- 8-K (material events) - stored for cross-ref only (no standalone alerts)
- 10-K/10-Q (earnings)
- SC 13D (activist stakes)

### LLM Output:
The LLM now generates a 1-paragraph thesis combining ALL signals:
- Twitter/X signals
- Social signals (Reddit, StockTwits, ApeWisdom)
- SEC/EDGAR filings (new)
- News catalyst
- Technical data

Example thesis:
> *"Analyst mentioned $TSLA with bullish call flow. SEC EDGAR shows 3 Form 4 filings (insider buying) in the last 48 hours. Combined with news of new model debut, this creates a high-confidence bullish setup."*
