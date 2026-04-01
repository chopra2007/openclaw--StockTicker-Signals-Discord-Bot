# System Changes & Issues Documentation

## Date: April 1, 2026

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
