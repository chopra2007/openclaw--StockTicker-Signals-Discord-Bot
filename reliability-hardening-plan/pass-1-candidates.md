# Pass 1 — Candidate Fixes (unfiltered) + Research Synthesis

**Run:** reliability-hardening · **Date:** 2026-06-28 PDT · **Inputs:** pass-0-system-map.md (19 gaps) + 2 web-research agents (resilient-client patterns, async-performance patterns).

> **Overarching research verdict (both agents independently):** EXTEND existing infra; **zero new production dependencies.** stdlib `random` + already-present `numpy` (via pandas) + already-present `aiosqlite` cover everything. tenacity / backoff / pybreaker / aiobreaker / purgatory / pyresilience all rejected (redundant with `rate_limiter`+`burst_retry`, or asyncio-incompatible, or need Redis).

---

## Validated patterns (the toolbox Pass 2–4 draws from)

| Pattern | Decision | Source quality |
|---|---|---|
| **Full jitter** `random.uniform(0, min(base·2^n, cap))` | Winner vs equal/decorrelated (decorrelated obsolete, Thom Wright 2024). One-line retrofit. | **High** (AWS Architecture Blog) |
| **Honor `Retry-After`** over computed backoff | `burst_retry.parse_retry_after()` already written; just wire it in | **High** (HTTP RFC + existing code) |
| **3-state circuit breaker** (closed→open→half-open), `fail_max≈5`, `reset≈120s`, `success_threshold=1`, rolling-window failure reset | Hand-roll ~80 lines, SQLite-backed | **High** (Azure Arch Center 2025) |
| **Persist breaker state** for QUOTA/402/bench (survives restart → wakes in OPEN, probes after cooldown); **don't persist** Groq head-start / transient | New `circuit_breaker_state` table (same db as `api_usage_daily`) | **High** |
| **Failure ladder** TRANSIENT(1-2)→DEGRADED(3-4/quota)→OPEN(5+/permanent); state-transition logging; 1 throttled ops alert / 30 min | Layer on existing `classify_retry` | **High** (Azure + project's own burst_retry) |
| **Numpy vectorization releases the GIL** → wrap in executor for *true* loop-freeing; thread pool alone does NOT free the loop for pure-Python CPU | Vectorize max-pain; numpy is free (pandas dep) | **High** (Python docs — GIL + to_thread) |
| **Bounded fan-out** `gather(*[_bounded(sem, …)], return_exceptions=True)`, `BoundedSemaphore(4)`, timeout INSIDE the sem block | For the flow-watcher N+1 | **High** (Python docs + death.andgravity) |
| **Do NOT batch yfinance** (`yf.download([...])` `_DFS` global is thread-unsafe; one bad ticker poisons batch) → keep parallel `Ticker` + cache slow `.info` | Overrides r2's "batchable" idea | **High** (yfinance #2557) |
| **aiohttp default `sock_read=None` is a hang vector** → set `ClientTimeout(total=30, connect=10, sock_read=20)` | One-line session fix | **High** (aiohttp docs + #11740) |

---

## Candidate fixes (each maps to Pass-0 gap IDs; all zero-new-dep unless noted)

### Family A — Retry / backoff / breaker core (the structural heart)

**C1 — Full jitter on `rate_limiter` backoff** · gap G1
*Function:* wrap the existing `min(30·2^(n-3), 600)` in `random.uniform(0, …)`. *Rationale:* de-synchronizes retry storms when several sources back off together. *Change:* 1 line in `utils/rate_limiter.py:78`. *Risk:* near-zero. *Behavior-changing?* No (internal timing only).

**C2 — Persistent SQLite circuit breaker** (`utils/circuit_breaker.py`, new ~80 lines) · gaps G2, G4, G19
*Function:* canonical 3-state breaker, state in a new `circuit_breaker_state` table; replaces/backs the three ad-hoc in-memory breakers (Brave-402, Gemini-bench) and adds proper half-open recovery. *Rationale:* breakers currently reset on restart and re-hit the wall (Brave 402 every restart); no half-open probe means dead sources never auto-recover cleanly. *Persist:* quota/402/bench. *Don't persist:* Groq head-start (stays in-memory — intentionally per-cycle). *Behavior-changing?* Yes (affects when sources are tried) → **flag-gated + stored-data validation**.

**C3 — Wire `burst_retry.classify_retry()` + `parse_retry_after()` into news cascade + `llm_client`** · gaps G13, G18 (partial)
*Function:* use the already-written, already-tested classifier instead of each path's ad-hoc inline status checks; honor server `Retry-After`. *Rationale:* unifies retry logic; lets QUOTA vs TRANSIENT vs PERMANENT drive the breaker/backoff. *Behavior-changing?* Yes (retry decisions) → flag-gated.

**C4 — Fix LLM blank-thesis (0.5 s soft-retry vs ≥30 s backoff mismatch)** · gap G18 · **HIGH**
*Function:* when the shared `openrouter` bucket is backed off, don't silently skip the whole chain → either (a) include a non-`openrouter` provider (Groq) as a guaranteed fallback in the chain so one bucket's backoff can't blank the thesis, and/or (b) on "all models skipped due to rate-limit," do a single jittered wait up to the bucket's actual `blocked_until` (bounded) before declaring empty, and (c) emit a distinct ERROR ("thesis blank: all LLM providers rate-limited") rather than a silent `""`. *Rationale:* most direct path to a degraded live alert (blank thesis). *Behavior-changing?* Yes (alert text content) → flag-gated + **live shadow check owed** (LLM output is user-facing).

### Family B — Dead-source visibility & budget unification

**C5 — Dead-source detection + degraded ladder + throttled ops alert** · gap G3 (Exa) , G14
*Function:* via C2's breaker, declare a source DEGRADED→OPEN after sustained failures; stop hammering a dead source every cycle; emit ONE throttled ops-channel alert on the closed→open transition; half-open re-probe next cycle. For QUOTA_BLOCKED → dead-until-UTC-midnight (reuse `is_per_day_quota`). *Rationale:* Exa floods ~450 log lines/cycle stuck at 600 s; it degrades *silently* (0/10) instead of *visibly*. *Compat:* OPEN returns None → source absent that cycle (not globally disabled) → honors "never drop a real signal." *Behavior-changing?* Internal + a new ops alert (not #chat) → flag-gated.

**C6 — Unify budget tracking on `DailyBudgetTracker`** · gap G5
*Function:* migrate Brave JSON-file counter and SerpAPI in-memory dict onto the existing persistent `api_usage_daily` (UTC) gate; fix SerpAPI's local-TZ date → UTC. *Rationale:* three inconsistent budget mechanisms (one not persisted, one wrong-TZ); unify on the one that already persists + gates. *Behavior-changing?* Borderline (gating thresholds) → flag-gated; keep current caps as defaults so behavior is identical until tuned.

### Family C — Event-loop / latency efficiency

**C7 — Vectorize max-pain with numpy + keep executor offload** · gap G7
*Function:* replace the O(strikes²) pure-Python `_payout`/`_max_pain_for_chain` with a numpy broadcast (GIL-released), still wrapped in `run_in_executor`. *Rationale:* thread offload alone does NOT free the loop for pure-Python (GIL); numpy's C ops do. ~100-700× faster + loop runs free. *Dep:* numpy (already present via pandas — **free**). *Behavior-changing?* No (same numeric result) → still needs a reproducing/equivalence test.

**C8 — Replace `.iterrows()` with `.itertuples()`/vectorized column ops** · gap G9
*Function:* options.py:180/366 chain parse. *Rationale:* ~50-100× faster, less CPU on loop. *Behavior-changing?* No → equivalence test.

**C9 — Parallelize options-flow watcher** · gap G8
*Function:* options.py:362-364 `for tk: await …` → `gather(*[_bounded(sem, …)], return_exceptions=True)` with `BoundedSemaphore(4)`, timeout inside the sem block. *Rationale:* serial N+1 delays the unusual-flow **instant-trigger** alert; wall-clock = sum→max. *Behavior-changing?* Timing only (same hits) → but it's an instant-alert path, so **flag-gated + live check owed**; reduce N to 2 if Yahoo 429s.

**C10 — peer_comparison: TTL-cache `.info` + concurrent fetch + raise ceiling** · gap G10
*Function:* module-level TTL dict (1 h) for `.info` sector; fetch `.info` concurrently with the history gather (not front-loaded); raise the `wait_for` ceiling 12 s→20-25 s; explicit `TimeoutError` log with elapsed. *Rationale:* uncached ETF `.info` front-load blows the 12 s ceiling under throttle → relative-strength silently dropped (IWM/NET/WMT). *Behavior-changing?* Adds the field back more often (good) → flag-gated; validate it doesn't slow `!all`.

**C11 — Default timeout on shared aiohttp session** · gap G11
*Function:* `utils/http.py` → `ClientTimeout(total=30, connect=10, sock_read=20)`. *Rationale:* `sock_read=None` default is a documented hang vector; one stalled endpoint can tie up a pool slot. *Behavior-changing?* Internal safety → reproducing test (a hung-server simulation). *Note:* must be generous enough not to cut off legitimately slow calls — verify against current per-call timeouts.

### Family D — Fail-open / silent-failure correctness (instant-trigger path)

**C12 — Fix options staleness fail-open** · gap G16 · med-high
*Function:* options.py:227 `_ts_to_epoch` returns 0.0 on parse error → staleness guard treated as falsy → skipped. Treat 0.0/unparseable `lastTradeDate` as **STALE (fail-closed)**: a contract with no parseable trade time must not be alerted on. *Rationale:* protects a no-second-source instant-trigger path from stale/garbage data. *Behavior-changing?* Yes (could drop a contract) → flag-gated + stored-data validation (count how many real hits this would have dropped historically).

**C13 — Distinguish "no flow" from "fetch failed" in options scan** · gap G17
*Function:* options.py:164/307/555 `except Exception: pass` → log at WARN with the exception; track per-scan fetch-failure count; if a *systemic* failure (all expiries failed), surface it (don't return empty silently). *Rationale:* a yfinance outage currently looks identical to "no unusual flow today," masking an outage of a primary instant-trigger source. *Behavior-changing?* No (logging/observability) → still needs a test.

**C14 — `api_adapters` report failures + raise log level** · gap G14
*Function:* the 7 handlers log at `debug` and never call `rate_limiter.report_failure` → direct callers (precision engine) get no backoff. Add `report_failure(source)` + raise to WARN on repeated failures. *Rationale:* a flapping/exhausted Exa/SerpApi/Firecrawl key is hammered every call with no throttle. *Behavior-changing?* Internal (adds backoff) → flag-gated (could change how often a source is tried).

### Family E — Process / ops plumbing (pure-internal)

**C15 — Fix systemd units** · gap G12
*Function:* `OOMScoreAdj` → `OOMScoreAdjust` on both units; add `MemoryMax` to consensus-engine (gateway already has 2G); consider `WatchdogSec`. *Rationale:* OOM protection silently not applied. *Behavior-changing?* No alert impact (process hardening). *Note:* editing `/etc/systemd/system/*` + `systemctl daemon-reload` is outside the repo — flag as an ops step, NOT a code commit; needs care not to disrupt the running services.

### Family F — Marginal / likely-drop in Pass 2 (kept for completeness)

**C16 — youtube sustained-outage breaker/alert** · gap G15-yt · low
*Function:* a dead Supadata+Gemini re-queues forever behind a 3-day advisory log; add a breaker/ops-alert when the backlog grows under sustained failure. *Likely:* fold into C5's ladder or defer (it already degrades gracefully).

**C17 — `rate_limiter` success/failure lock** · low
*Function:* `report_success/failure` are sync, not lock-protected (GIL-safe but a technical data race). *Likely:* drop (no observed impact) unless C2 refactor touches it anyway.

**C18 — stocktwits note** · gap G15 · none
*Reality:* already has a soft rate-limiter breaker + negative cache. **Non-gap — drop.**

---

## Constraints carried into Pass 2

- **Free only.** No fix here needs a paid tier or a trial key. (Reliability run — as the brief predicted, no trial dependencies.)
- **Dead paths NOT re-proposed:** no bare youtube-transcript-api, no aiohttp-to-StockTwits.
- **House rule:** every alert-affecting candidate (C2, C3, C4, C5, C6, C9, C10, C12, C14) ships **flag-gated default-OFF** + validated on stored `decision_snapshots`/`shadow_predictions`; C4/C9/C10/C12 additionally owe a **live check** (shadow log / staged ramp) because they touch user-facing alert content or the instant-trigger path. Pure-internal (C1, C7, C8, C11, C13, C15) still need a reproducing test + regression-gate proof.
- **Redundancy guard honored:** no new retry lib, no new breaker lib, no new cache — all extend `rate_limiter` / `burst_retry` / `DailyBudgetTracker` / `xref_cache`.
