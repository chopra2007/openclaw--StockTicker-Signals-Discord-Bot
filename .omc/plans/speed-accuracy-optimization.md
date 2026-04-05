# OpenClaw Signal Engine — Speed + Accuracy Optimization Plan

**Date:** 2026-03-30
**Status:** REVISED — Iteration 2
**Estimated complexity:** HIGH (13 files, 5 phases)

---

## RALPLAN-DR Summary

### Principles (5)

1. **Signal-first is sacred** — Never add latency to the Phase 1 instant ping path. All optimizations target the cross-reference (Phase 2) or background loops.
2. **Parallelize before optimizing** — Sequential I/O is the biggest bottleneck. Convert serial calls to concurrent before micro-optimizing individual calls.
3. **Share expensive resources** — aiohttp sessions, DB connections, and executor pools are expensive to create. Create once, reuse everywhere.
4. **Fail fast, score later** — Short-circuit evaluation paths when early results are decisive. Don't run all 6 technical filters if the first 2 fail.
5. **Persist what's expensive** — Cache results that cost API calls or CPU, survive restarts where possible.

### Decision Drivers (Top 3)

1. **Cross-reference latency** — Currently 10-30s due to sequential news cascade + per-request session creation. Target: < 5s.
2. **Resource waste** — 26 `aiohttp.ClientSession()` creates per cycle, `ThreadPoolExecutor(max_workers=4)` for 9+ concurrent loops, memory-only xref cache lost on restart.
3. **Alert accuracy** — Technical filters don't short-circuit, news cascade processes all articles before checking catalyst, no index on alert_history cooldown query, `check_alert_cooldown` defined but never wired in.

### Viable Options

#### Option A: Incremental Optimization (RECOMMENDED)
Phased approach targeting bottlenecks in priority order. Each phase is independently deployable and testable.

| Pros | Cons |
|------|------|
| Each phase delivers measurable improvement | 5 phases = 5 deploy cycles |
| Low risk — no architecture changes | Doesn't address fundamental SQLite scaling limits |
| Can stop after Phase 2 with 80% of gains | Some redundancy remains across scanner loops |

#### Option B: Full Pipeline Rewrite with Connection Pooling
Replace all I/O patterns with a centralized connection pool, shared session manager, and event-driven pipeline.

| Pros | Cons |
|------|------|
| Cleanest architecture | 2-3x more effort, high regression risk |
| Single deploy | All-or-nothing — can't partially ship |
| Better long-term scalability | Over-engineered for current 48-account scale |

**Option B invalidation rationale:** The current architecture is sound — signal-first with async cross-reference. The bottlenecks are implementation-level (per-request sessions, sequential cascades, missing indexes), not architectural. A rewrite would risk breaking 148 passing tests and the production alert pipeline for marginal architectural gains at current scale.

---

## ADR: Incremental Optimization Strategy

- **Decision:** Incremental 5-phase optimization (Option A), with Phase 0 baseline instrumentation gate
- **Drivers:** Minimize risk to production alerts, deliver measurable gains per phase, maintain 148 test compatibility, validate bottleneck assumptions before optimizing
- **Alternatives considered:** Full pipeline rewrite (Option B)
- **Why chosen:** 80/20 rule — Phase 1+2 eliminate ~80% of latency with ~20% of rewrite effort. Phase 0 ensures optimization targets are data-driven. Current architecture is fundamentally sound.
- **Consequences:** Some code duplication remains across scanner loops. SQLite scaling ceiling unchanged.
- **Follow-ups:** If scale exceeds 100+ accounts, revisit Option B or consider PostgreSQL migration.

---

## Phase 0: Baseline Latency Instrumentation (< 15 minutes, must run first)

### 0.1 Per-Component Timing Inside cross_reference()

**Files:** `consensus_engine/cross_reference.py` (lines 135-143), `consensus_engine/db.py` (pipeline_metrics table at lines 48-53)
**Change:** Wrap each component call inside `cross_reference()` with `time.perf_counter()` start/stop. Record per-component latency to the existing `pipeline_metrics` table with keys: `news_cascade_ms`, `technical_ms`, `social_ms`, `sec_check_ms`, `analyst_check_ms`, `options_check_ms`, `llm_score_ms`. Use `perf_counter` (not `time.time`) for sub-millisecond accuracy.

```python
# Pattern for each component:
t0 = time.perf_counter()
result = await news_cascade(ticker)
metrics["news_cascade_ms"] = int((time.perf_counter() - t0) * 1000)
```

**Purpose:** Validates whether the optimization targets stated in this plan are correct before any implementation work. Optimization phases that follow are premised on news cascade being the dominant bottleneck. If instrumentation reveals a different bottleneck (e.g., LLM scorer at 8s), the phase ordering should be revised accordingly.

**Acceptance criteria:**
- [ ] Each of the 7 components has individual ms timing recorded
- [ ] Timings written to `pipeline_metrics` table with existing schema (or schema extended if needed)
- [ ] `--status` output includes average per-component latency from last 100 runs
- [ ] No measurable latency added to the cross-reference path (perf_counter overhead is nanoseconds)

---

## Phase 1: Quick Wins (< 1 hour each, high impact)

### 1.1 Global aiohttp Session Singleton

**Files:** New `consensus_engine/utils/http.py`, then update all 26 call sites
**Change:** Create a module-level `get_session()` that lazily initializes a single `aiohttp.ClientSession` with connection pooling (`TCPConnector(limit=30)`). Replace all `async with aiohttp.ClientSession() as session:` patterns.

**Shared session failure mode:** A shared session entering a bad state (e.g., `ServerDisconnectedError`, `ClientConnectionError`) affects all 26 call sites simultaneously. Mitigate with a recreation strategy: catch `aiohttp.ClientConnectionError` at the `get_session()` level, close the bad session, and recreate it. This ensures a single bad connection doesn't permanently break all HTTP calls.

**Graceful shutdown:** The shared session must be closed cleanly in two paths:
- **Continuous mode** (`main.py:569-572` finally block): call `await close_session()` in the existing `finally` clause.
- **`--once` mode** (`main.py:529-531`): add a `try/finally` around the single-run block to ensure `close_session()` is called before process exit, even on exception.

**Impact:** Eliminates ~0.5s TCP/TLS handshake overhead per HTTP request. At 26 call sites, saves 5-13s per full cross-reference cycle.
**Testability:** Existing tests pass unchanged (mock at session level). Add unit test for session lifecycle and recreation-on-error behavior.

**Acceptance criteria:**
- [ ] Zero `aiohttp.ClientSession()` calls remain outside `utils/http.py`
- [ ] Session is created once, reused across all modules
- [ ] `TCPConnector(limit=30)` configured for connection pooling
- [ ] `ClientConnectionError` triggers session recreation (not permanent failure)
- [ ] Graceful shutdown closes the session in both continuous mode finally block AND `--once` mode finally block
- [ ] All 148 tests pass

### 1.2 Increase ThreadPoolExecutor to 8 Workers

**Files:** `consensus_engine/main.py` line 44
**Change:** `ThreadPoolExecutor(max_workers=4)` -> `ThreadPoolExecutor(max_workers=8)`

**Corrected rationale (low-impact):** The 9 loops in `main.py:549-561` are asyncio coroutines scheduled via `asyncio.gather`, NOT threads. Only three functions actually use `run_in_executor`: `_fetch_price`, `scan_volume_breakouts`, and `scan_unusual_options_market`. Thread starvation is therefore unlikely at current 48-account scale. This change is cheap headroom insurance for future growth, not a fix for a current bottleneck. **Categorized as low-impact.**

**Acceptance criteria:**
- [ ] `max_workers=8` in main.py
- [ ] No regression in scanner loop timing (verify via logs after deploy)

### 1.3 Wire check_alert_cooldown into process_tweet()

**Files:** `consensus_engine/db.py` lines 228-238, `consensus_engine/main.py` — `process_tweet()` function

**Decision:** `check_alert_cooldown` at `db.py:228-238` is currently defined but never called anywhere (dead code). **Option A is chosen:** wire it into `process_tweet()` before `send_instant_ping`. This adds useful spam prevention — if the same ticker triggered an alert within the last 6 hours, skip the instant ping and log a suppression notice. This aligns with the signal-first architecture by preventing alert fatigue without adding latency (the cooldown DB query is fast with the index from step 1.4).

**Rationale for Option A over Option B (delete):** The signal-first architecture benefits from cooldown enforcement. Without it, a ticker mentioned by multiple analysts in quick succession generates redundant Discord pings, degrading the user experience.

**Impact:** Prevents duplicate alerts for same ticker within 6-hour cooldown window.
**Testability:** Add test: process two tweets for same ticker within cooldown window; verify second is suppressed.

**Acceptance criteria:**
- [ ] `check_alert_cooldown(ticker)` called in `process_tweet()` before `send_instant_ping`
- [ ] Suppressed alerts logged at INFO level with reason
- [ ] Cooldown window configurable (default: 6 hours, via `config/consensus.yaml`)
- [ ] Test covers suppression path and non-suppression (different ticker, or expired cooldown)

### 1.4 Add Index on alert_history for Cooldown Query

**Files:** `consensus_engine/db.py` — SCHEMA section
**Change:** Add `CREATE INDEX IF NOT EXISTS idx_alerts_ticker_time ON alert_history(ticker, alerted_at);` (composite index for the cooldown query at `db.py:234`).
**Impact:** Cooldown check (now wired in per 1.3) goes from full table scan to index lookup. As `alert_history` grows, this keeps the cooldown check O(log n) instead of O(n).
**Testability:** Run `EXPLAIN QUERY PLAN` on the cooldown query to verify index usage.

**Acceptance criteria:**
- [ ] Composite index `(ticker, alerted_at)` exists in schema
- [ ] Cooldown query uses index (verified via `EXPLAIN QUERY PLAN`)
- [ ] All DB tests pass

### 1.5 News Cascade: Early Exit on Article Match

**Files:** `consensus_engine/scanners/news.py` — each `_search_*` function
**Change:** Confirm and enforce that each tier function returns immediately on first catalyst match without processing remaining articles. The `for article in articles[:10]` loop should `break` or `return` on first trusted-source match rather than exhausting the article list.
**Impact:** Minor (~10-50ms per tier), compounds across 4 tiers.
**Testability:** Existing news cascade tests cover this path.

**Acceptance criteria:**
- [ ] Each tier function returns as soon as first catalyst is found
- [ ] No unnecessary article iteration after a match is confirmed

---

## Phase 2: Core Pipeline Optimizations (Medium effort, critical path)

### 2.1 Parallel News Cascade with Tiered-Timeout

**Files:** `consensus_engine/scanners/news.py` — `news_cascade()` function
**Change:** Replace the sequential `for tier_name in tiers: result = await func(ticker)` loop with a tiered-timeout concurrent approach:

1. Launch all 4 tier tasks concurrently via `asyncio.create_task()`
2. Use `asyncio.wait({finnhub_task}, timeout=3)` to give Finnhub (tier 1, highest quality) a 3-second head start
3. If Finnhub returns within 3s, use its result and cancel the remaining 3 tasks
4. If Finnhub times out at 3s, call `asyncio.wait(remaining_tasks, return_when=asyncio.FIRST_COMPLETED)` to accept the first result from any remaining tier
5. Cancel all still-pending tasks after a result is accepted
6. **Task cancellation must also close underlying HTTP connections** — when cancelling tasks that hold open HTTP requests from the shared session pool, call `task.cancel()` and then `await asyncio.shield(asyncio.gather(*pending, return_exceptions=True))` to ensure cancelled coroutines release their connections back to the pool. Orphaned connections exhaust the `TCPConnector(limit=30)` pool.

**Why tiered-timeout over FIRST_COMPLETED alone:** Using `asyncio.wait(return_when=FIRST_COMPLETED)` across all 4 tiers simultaneously would discard quality preference — a slow Finnhub response (4s) and a fast SearXNG response (1s) would always pick SearXNG. The tiered-timeout approach gives Finnhub priority while still parallelizing.

**Impact:** News cascade drops from sequential 10-30s to ~3-8s (Finnhub head start + parallel fallback). This is the single biggest latency win.
**Testability:** Existing `test_news_cascade.py` tests still pass. Add tests for: (a) Finnhub fast path (returns within 3s), (b) Finnhub timeout, fallback to first-available, (c) all tiers fail → return None, (d) connection release after cancellation.

**Acceptance criteria:**
- [ ] All 4 tiers launch concurrently
- [ ] Finnhub gets a 3-second priority window before fallback triggers
- [ ] First valid result after window expires cancels remaining tasks AND releases their HTTP connections
- [ ] Fallback: if all tiers fail, return None (existing behavior)
- [ ] No orphaned connections in the shared aiohttp pool after cancellation
- [ ] Latency metric recorded and < 8s average (per Phase 0 baseline)

### 2.2 Technical Filter Short-Circuit

**Files:** `consensus_engine/analysis/technical.py` — `_run_filters()` function
**Change:** Currently all 6 filters run unconditionally. For the cross-reference scoring path (not the "all must pass" gate), add an optional `short_circuit=True` parameter. When enabled, stop running filters after 2 consecutive failures.

**Corrected impact estimate:** Technical filters operate on in-memory data (already-fetched price/volume structs) and are pure computation — individual filter execution is microseconds, not ~50ms. **The primary benefit is not execution time savings but preventing unnecessary downstream scorer calls** when a ticker clearly fails basic technical checks. Impact is LOW for latency; MEDIUM for code clarity and resource hygiene.

**Acceptance criteria:**
- [ ] `short_circuit` parameter defaults to `False` (backward compatible)
- [ ] When enabled, stops after 2 consecutive failures
- [ ] Score computation handles partial filter results correctly
- [ ] Tests cover both modes
- [ ] Impact notes in code comments reflect that this is a hygiene improvement, not a major latency win

### 2.3 Batch Price Followups with Concurrent yfinance

**Files:** `consensus_engine/main.py` — `price_followup_loop()`
**Change:** Currently iterates alerts sequentially: `for alert in alerts: price = await _fetch_price(alert["ticker"])`. Replace with batched `asyncio.gather()` for up to 5 concurrent price fetches.
**Impact:** If 10 alerts need price updates, drops from 10 * 3s = 30s to 2 * 3s = 6s (2 batches of 5 concurrent).
**Testability:** Mock `_fetch_price`, verify all alerts get updated. Add timing assertion.

**Acceptance criteria:**
- [ ] Price fetches run in batches of 5 concurrently
- [ ] Error in one fetch doesn't block others (`return_exceptions=True`)
- [ ] DB updates still happen per-alert (not batched)
- [ ] Loop timing < 10s for 10 alerts

---

## Phase 3: Reliability and Scaling Improvements (Larger effort)

### 3.1 Persistent XRef Cache (SQLite-backed)

**Files:** `consensus_engine/utils/xref_cache.py`, `consensus_engine/db.py`
**Change:** Replace the in-memory `dict` cache with a SQLite table `xref_cache(ticker TEXT PRIMARY KEY, result_json TEXT, cached_at REAL)`. On startup, warm from DB. On cache miss, check DB before making API calls. TTL remains 5 minutes.
**Impact:** Cross-reference results survive restarts. If the engine crashes and restarts during market hours, it doesn't re-run expensive API calls for tickers processed in the last 5 minutes.
**Testability:** Add tests for cache persistence across simulated restarts.

**Acceptance criteria:**
- [ ] Cache persists to SQLite `xref_cache` table
- [ ] TTL enforcement works from DB timestamps
- [ ] Cache hit rate logged as a metric
- [ ] Startup warmup reads cached entries < 5 min old
- [ ] All existing xref_cache tests pass

### 3.2 Rate Limiter Slot-Drift Fix

**Files:** `consensus_engine/utils/rate_limiter.py` — `acquire()` method (lines 39-55)

**Corrected bug description:** The `async with self._lock:` at line 39 serializes all callers, so two coroutines cannot both read `_last_request` simultaneously — there is no read-before-write race. The actual bug is subtler: line 55 calls `time.time()` again (a second syscall) instead of reusing `now` captured at line 40. By the time execution reaches line 55 (after computing `wait_time` and any other work inside the lock), the value of `time.time()` has drifted forward by the time spent inside the lock. This means the reserved slot is stamped later than intended, compressing the gap between consecutive reservations and potentially causing rate limit violations.

**Fix:** Replace:
```python
self._last_request[source] = time.time() + wait_time
```
With:
```python
self._last_request[source] = now + wait_time
```
where `now` is the value captured at the top of the `async with` block (line 40).

**Impact:** Prevents Finnhub/Brave API rate limit violations that trigger 30-600s backoff penalties. Under high concurrency (many tickers processed in parallel), slot drift compounds and increases violation probability.
**Testability:** Add concurrent acquire test with 5 simultaneous callers. Verify all get monotonically increasing slots at least `min_interval` apart.

**Acceptance criteria:**
- [ ] `self._last_request[source]` set to `now + wait_time` (not `time.time() + wait_time`)
- [ ] Consecutive reservations are always at least `min_interval` apart
- [ ] 5 concurrent acquires for same source yield distinct, non-overlapping slots
- [ ] Backoff penalty count drops to zero in production logs

### 3.3 Deduplicate Proactive Scanner Watchlists

**Files:** `consensus_engine/main.py` — scanner loop functions, `consensus_engine/scanners/premarket.py`, `volume_scanner.py`, `options.py`
**Change:** Premarket, volume, and options scanners each independently load and iterate the watchlist. Create a shared `get_active_watchlist()` function that returns the merged, deduplicated watchlist with a short cache (60s TTL). Each scanner calls this instead of loading its own.
**Impact:** Reduces redundant Finnhub/yfinance calls by ~30% across scanner loops. Prevents the same ticker being fetched 3 times in parallel from different scanners.
**Testability:** Mock watchlist source, verify deduplication. Count API calls.

**Acceptance criteria:**
- [ ] Single `get_active_watchlist()` function used by all 3 scanners
- [ ] Watchlist cached for 60s
- [ ] No duplicate API calls for same ticker within 60s window
- [ ] Scanner loop behavior unchanged from user perspective

---

## Phase 4: Advanced Optimizations (Nice-to-have)

### 4.1 Discord Session Reuse with Bot Client

**Files:** `consensus_engine/alerts/discord.py`
**Change:** The Discord module creates a new `aiohttp.ClientSession` for every message sent (4 functions). After Phase 1.1 (global session), these will use the shared session. Additionally, add a simple retry with exponential backoff for Discord 429 (rate limit) responses.
**Impact:** Eliminates 4 redundant session creates per alert cycle. Retry logic prevents lost alerts during Discord rate limiting.
**Testability:** Mock Discord API, test retry on 429.

**Acceptance criteria:**
- [ ] All Discord functions use shared session from `utils/http.py`
- [ ] 429 responses trigger retry (max 3 attempts, exponential backoff)
- [ ] Alert delivery success rate > 99%

### 4.2 Social Scanner Signal Deduplication

**Files:** `consensus_engine/scanners/social.py`, `consensus_engine/scanners/reddit_trend.py`
**Change:** Reddit and ApeWisdom scanners currently create signals for every ticker found in every post, causing DB bloat. Add a dedup check: skip if a signal for the same ticker+source exists within the last `signal_ttl` window.
**Impact:** Reduces DB writes by ~50% in the social scanner loop. Faster `get_signal_counts_by_source()` queries.
**Testability:** Run social scanner twice with same data, verify no duplicate signals.

**Acceptance criteria:**
- [ ] No duplicate signals for same ticker+source within TTL window
- [ ] DB row count growth rate drops by 40%+
- [ ] Signal counts for cross-reference scoring unchanged

### 4.3 Configurable News Cascade Strategy

**Files:** `consensus_engine/scanners/news.py`, `config/consensus.yaml`
**Change:** Add config option `news_cascade.strategy: "parallel" | "sequential"` (default: "parallel" after Phase 2.1). Allow users to fall back to sequential if API rate limits are a concern. Add `news_cascade.max_concurrent_tiers: 4` config.
**Impact:** Flexibility for different deployment environments (free tier API limits vs. paid).
**Testability:** Test both strategies produce identical results.

**Acceptance criteria:**
- [ ] Config key `news_cascade.strategy` controls behavior
- [ ] Default is "parallel"
- [ ] Sequential mode matches current behavior exactly

### 4.4 Exa.ai as News Cascade Tier

**Files:** `consensus_engine/scanners/news.py`, `config/consensus.yaml`
**Change:** Add Exa.ai semantic search as a news cascade tier (between Finnhub and Google RSS). Exa's semantic search can query things like "NVDA earnings beat analyst expectations" which is far more targeted than keyword-based RSS. Uses the existing `EXA_AI_API_KEY` from `~/.openclaw/.env`. In the tiered-timeout cascade from Phase 2.1, Exa runs alongside tiers 2-4 (after Finnhub's 3s priority window).
**Impact:** Higher quality catalyst detection — Exa returns contextually relevant results vs keyword matches. Replaces or supplements Brave Search (Tier 3) which has an unenforced daily budget.
**Testability:** Mock Exa API, test catalyst classification from Exa results.

**Acceptance criteria:**
- [ ] `_search_exa()` function added to `news.py`
- [ ] Exa tier integrated into parallel cascade
- [ ] Config key `exa.enabled` controls activation (default: true if API key present)
- [ ] Catalyst classification works on Exa results
- [ ] Rate limiting applied via existing rate_limiter

---

## Success Criteria (Overall)

1. **Phase 0 baseline captured** — per-component latency in `pipeline_metrics` for at least 20 cross-reference cycles before Phase 1 begins
2. **Cross-reference latency < 5s** (down from baseline) — measured via `pipeline_metrics` table
3. **Zero per-request `aiohttp.ClientSession()` creates** — verified via grep
4. **All 148+ tests passing** after each phase
5. **No regression in alert delivery** — Discord ping success rate stays > 99%
6. **Price followup loop < 10s** for 10 alerts (down from 30s)
7. **XRef cache survives restart** — verified by restart test
8. **No rate limiter slot drift** — verified by concurrent acquire test showing monotonic slots
9. **Alert cooldown wired and functional** — same ticker suppressed within 6-hour window

---

## Guardrails

### Must Have
- Phase 0 instrumentation runs and data collected before any other phase begins
- Each phase is independently deployable and rollback-safe
- No changes to the Phase 1 instant ping latency path
- All existing tests pass after each phase
- New functionality has test coverage

### Must NOT Have
- No changes to the scoring algorithm or weights
- No new external dependencies beyond what's already installed
- No changes to config file format (only additive keys)
- No database migration that breaks existing data
- No task cancellation that leaves orphaned HTTP connections in the shared pool
