# Speed-accuracy optimization plan — partially unimplemented

**Status:** DONE 2026-07-12 — re-audit against today's code closed the last 3 leftovers: each was built later by other work or is moot (see CURRENT STATUS).
**Created:** 2026-05-10

**CURRENT STATUS (2026-07-12):** CLOSED after a line-by-line re-audit of the "3 remaining" against today's code (TODO #72 follow-up, user go). Phase-4 leftovers: Discord 429 retry — BUILT (`alerts/discord.py` `_safe_send`: reads Retry-After, sleeps, retries, loud truncation notice on exhaustion); social signal dedup — BUILT via TODO #65 (DONE 2026-07-05); configurable cascade strategy — BUILT (`news_cascade.tiers` list + `news_cascade.parallel` in consensus.yaml drive order and racing); Exa.ai tier — MOOT (provider removed; its circuit breaker confirmed locking it out 2026-07-06, reason=402). Phase 3.3's event-driven scheduler — OBSOLETE BY DESIGN: the only true event source (tweets) already alerts instantly (signal-first core design); all other sources are polled, so there is no event to schedule on. Nothing buildable remains.

**Layperson:** The speed-accuracy optimization plan (`plans/speed-accuracy-optimization.md`, dated 2026-03-30) was marked complete in a prior session but was not. A prior Claude session created the infrastructure in one commit (87f4478, 2026-03-31) and stopped, without verifying the acceptance criteria.

## What was actually done (9 of 13 items, plus 1 WON'T-DO)
- Phase 0: latency instrumentation in cross_reference.py ✅
- Phase 1.1: aiohttp session singleton (commit `b1e85f1`) ✅
- Phase 1.2: ThreadPoolExecutor bumped to 8 workers (commit `b1e85f1`) ✅
- Phase 1.3: alert cooldown wired into process_tweet ✅
- Phase 1.4: composite DB index on alert_history(ticker, alerted_at) ✅
- Phase 1.5: news cascade early exit on first hit ✅
- Phase 2.1: parallel news cascade with tiered-timeout (`news.py:453-495`) ✅
- Phase 2.2: technical filter short-circuit — WON'T-DO (see below)
- Phase 2.3: concurrent yfinance on live path (`main.py:715-720`) ✅
- Phase 3.1: persistent L1+L2 xref cache (SQLite-backed) ✅
- Phase 3.2: rate limiter slot-drift fix (commit `b1e85f1`) ✅
- Phase 3.3: shared watchlist query done; event-driven scheduler NOT done (partial)

## What is NOT done

- ~~**Phase 1.1 migration**~~ — **DONE** in commit `b1e85f1`. Only remaining bare `aiohttp.ClientSession(` call is the singleton constructor itself at `utils/http.py:34`; grep confirms zero call sites outside that file.
- ~~**Phase 1.2** — `ThreadPoolExecutor` max_workers~~ — **DONE** in commit `b1e85f1` (bumped to 8 at `main.py:1136`).
- ~~**Phase 2.1 (biggest win)**~~ — **DONE**. Parallel news cascade with `asyncio.create_task` per tier + `as_completed`, `parallel_timeout_sec=12.0`, cancels losers. Live at `consensus_engine/scanners/news.py:453-495`. Brave budget concern resolved: `_brave_budget_ok` (`news.py:328-331`) reads `brave_daily_budget=50` from config plus an on-disk counter, and `_brave_quota_exhausted` (`news.py:337`) breaks on HTTP-402. Config: `config/consensus.yaml:94` `parallel: true`.
- **Phase 2.2** — **WON'T-DO.** Building it as spec'd (truncate the filter loop on consecutive failures) would corrupt `compute_technical_score` at `cross_reference.py:79`, which counts passed filters out of 6, and the user-facing "N/6" display at `commands.py:812`. The actual I/O cost (quote + history fetch) is already done concurrently before filters run (`technical.py:258`), and the LLM scorer runs once per ticker on the whole bundle — not per filter — so short-circuit saves zero LLM calls. Microsecond savings do not justify score corruption. Future option if alert cost is ever a concern: skip the LLM scorer at the call site when `passed_count < threshold` while still running all 6 cheap filters — that saves a real LLM call without corrupting the score.
- ~~**Phase 2.3**~~ — **DONE**. Concurrent yfinance fetch on the live signal path: `main.py:715-720` (`_check_youtube_level_alerts`, default executor + `asyncio.gather`). Note: `main.py:1246-1267` is a separate price-outcome backfill loop on an 8-worker pool — also concurrent but NOT the live alert path.
- ~~**Phase 3.2 (one-liner bug)** — Rate limiter slot-drift fix~~ — **DONE** in commit `b1e85f1` (`rate_limiter.py:58` now uses `now + wait_time`).
- **Phase 3.3** — **PARTIALLY DONE (query only).** The shared watchlist query — `db.get_active_tickers(min_signals=1)` (`db.py:868`) — is already reused by `main.py:173/250`, `sec_form4_cluster.py:260`, and `commands.py:651/870`. There is no function literally named `get_active_watchlist`; do not rename. What is NOT done: the event-driven scheduler / instant-alert-on-threshold described in the original spec. That part was never built.
- **Phase 4** (nice-to-haves) — Discord retry on 429, social signal dedup, configurable cascade strategy, Exa.ai tier — none implemented. Note: Exa.ai is no longer used.

## Also discovered — dead config and missing enforcement

- ~~`news_cascade.brave_daily_budget: 50` in `config/consensus.yaml` is **dead config**.~~ **RESOLVED** as part of Phase 2.1. `_brave_budget_ok` (`news.py:328-331`) now reads `brave_daily_budget=50` from config plus an on-disk counter; `_brave_quota_exhausted` (`news.py:337`) breaks on HTTP-402. The cap is actively enforced on the news cascade path.
- The `precision_engine.budget.brave_queries: 200` cap inside `engine.py`'s BudgetManager remains a separate, independent limit for the precision engine code path.
- Actual observed Brave usage: 85–121 queries/day on active trading days (May 6–8). Brave free tier allows 2,000/month. Well within limit.

## Effort

Phase 2.1 is the high-value item and requires the most care (Brave budget implications + HTTP connection cleanup after task cancellation). Phase 1.1 migration and Phase 3.2 are mechanical/low-risk. Full plan detail at `plans/speed-accuracy-optimization.md`.

---

**Verified 2026-05-29** — Status cross-checked against live code. Phases 1.1, 2.1, 2.3, 3.3 (query), 1.2, 3.2 confirmed done with line-level anchors. Commit hashes corrected from non-existent `0a0309e`/`2cc59ee` to real `b1e85f1`. Phase 2.2 recorded as WON'T-DO with rationale. Dead Brave-budget-config note resolved (cap now enforced at `news.py:328-337`).

### Session notes — 2026-07-12

- **Worked on:** Re-audit of the 3 "remaining" items against live code (verification detail in CURRENT STATUS above). No code changed — everything was already built by later work or moot.
- **Decisions:** Phase 3.3's event-driven scheduler declared obsolete (polled sources have no events; tweet path already instant). Phase 2.2 stays WON'T-DO as recorded.
- **Next:** none — item closed.
