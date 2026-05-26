# Speed-accuracy optimization plan — partially unimplemented

**Status:** OPEN — 5 of 13 items complete, 8 remaining.
**Created:** 2026-05-10

**Layperson:** The speed-accuracy optimization plan (`plans/speed-accuracy-optimization.md`, dated 2026-03-30) was marked complete in a prior session but was not. A prior Claude session created the infrastructure in one commit (87f4478, 2026-03-31) and stopped, without verifying the acceptance criteria.

## What was actually done (5 of 13 items)
- Phase 0: latency instrumentation in cross_reference.py ✅
- Phase 1.3: alert cooldown wired into process_tweet ✅
- Phase 1.4: composite DB index on alert_history(ticker, alerted_at) ✅
- Phase 1.5: news cascade early exit on first hit ✅
- Phase 3.1: persistent L1+L2 xref cache (SQLite-backed) ✅

## What is NOT done

- ~~**Phase 1.1 migration**~~ — **DONE** in commit `0a0309e` (25 sites across 24 files + 8 test fixes; grep verifies zero bare `aiohttp.ClientSession()` calls outside `utils/http.py`).
- ~~**Phase 1.2** — `ThreadPoolExecutor` max_workers~~ — **DONE** in commit `2cc59ee` (bumped to 8 at `main.py:1136`).
- **Phase 2.1 (biggest win)** — Parallel news cascade with tiered-timeout. Currently sequential `for tier_name in tiers:` loop in `news.py`. Plan calls for running all 4 tiers concurrently with a 3-second Finnhub priority window. Estimated latency improvement: 10–30s → 3–8s. **Note:** parallelizing Brave Search means Brave fires on every alert instead of only on Finnhub misses — review Brave budget before implementing (see item below).
- **Phase 2.2** — Technical filter short-circuit (`short_circuit` parameter in `technical.py`) — not implemented.
- **Phase 2.3** — Batch price followups with concurrent yfinance — not implemented.
- ~~**Phase 3.2 (one-liner bug)** — Rate limiter slot-drift fix~~ — **DONE** in commit `2cc59ee` (`rate_limiter.py:58` now uses `now + wait_time`).
- **Phase 3.3** — Shared `get_active_watchlist()` across scanners — not implemented.
- **Phase 4** (nice-to-haves) — Discord retry on 429, social signal dedup, configurable cascade strategy, Exa.ai tier — none implemented. Note: Exa.ai is no longer used.

## Also discovered — dead config and missing enforcement

- `news_cascade.brave_daily_budget: 50` in `config/consensus.yaml` is **dead config**. No Python file reads this key. The news cascade path (`scanners/news.py`) has no daily cap on Brave at all — only the per-call rate limiter (0.5s between calls).
- The only enforced daily Brave cap is `precision_engine.budget.brave_queries: 200` inside `engine.py`'s BudgetManager, which only covers the precision engine code path.
- Actual observed Brave usage: 85–121 queries/day on active trading days (May 6–8). Brave free tier allows 2,000/month. Currently well within limit.

## Effort

Phase 2.1 is the high-value item and requires the most care (Brave budget implications + HTTP connection cleanup after task cancellation). Phase 1.1 migration and Phase 3.2 are mechanical/low-risk. Full plan detail at `plans/speed-accuracy-optimization.md`.
