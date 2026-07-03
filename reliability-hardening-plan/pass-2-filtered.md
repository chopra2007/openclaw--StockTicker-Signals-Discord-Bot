# Pass 2 — Filtered, Deduplicated, Prioritized

**Run:** reliability-hardening · **Date:** 2026-06-28 PDT · **Input:** pass-1-candidates.md (18 candidates).

## Dropped / folded (redundancy + low-value cut)

| Candidate | Disposition | Why |
|---|---|---|
| **C18** stocktwits "no breaker" | **DROP** | Non-gap — already has a soft rate-limiter breaker + 90 s negative cache (Pass 0 verified). |
| **C17** rate_limiter sync lock | **DROP** | GIL-safe; no observed impact. Only revisit if C2 refactor touches those lines anyway. |
| **C16** youtube sustained-outage alert | **FOLD into C5** | Same dead-source ladder; not a separate workstream. Low priority within C5. |
| **C6** unify budget tracking | **DEFER (document, don't build)** | Real (TZ inconsistency) but the 3 mechanisms *work*; unifying is a migration with double-count/reset risk for **little live-alert benefit**. Out of proportion for a reliability run. Keep as a noted follow-up; fix only the SerpAPI local-TZ→UTC one-liner if cheap. |

Everything else survives. **No redundant breaker/retry/cache is proposed** — all extend `rate_limiter`/`burst_retry`/`DailyBudgetTracker`/`xref_cache`/`http.py`.

---

## Ranked surviving fixes (live-impact × feasibility)

Ranking axis: **live-alert reliability benefit** first, **feasibility/safety** second. Tier 1 = highest impact-per-risk.

### TIER 1 — High impact, low risk (do first)

**C4 — Fix LLM blank-thesis** · G18 · impact **HIGH** · feasibility med
- *Failure modes:* (a) the added Groq fallback is itself rate-limited → still blank; (b) a bounded wait-for-bucket adds latency to the alert; (c) changing thesis text could regress format.
- *Safeguards:* **signal-first — the alert ALWAYS fires; only the thesis paragraph degrades.** If all providers are rate-limited, emit the alert with a clear "(thesis unavailable — LLM providers rate-limited)" note + an ERROR log, never a silent `""` and never a blocked alert. Bounded wait ≤ a small cap (e.g. 2 s), never the full 600 s. Snapshot current thesis format in a golden test.

**C1 — Full jitter on backoff** · G1 · impact low-med · feasibility **trivial** (1 line)
- *Failure modes:* `random.uniform(0, cap)` can pick a near-zero sleep → a source retried almost immediately after a transient.
- *Safeguards:* `min_interval` still paces it; near-zero is *intended* for early/transient failures (fast recovery), full spread only accumulates at high failure counts. No downside for a single-process app.

**C11 — Default aiohttp session timeout** · G11 · impact med · feasibility high (1 line)
- *Failure modes:* a too-tight `sock_read`/`total` could cut off a legitimately slow call (large SEC submission download, slow LLM stream).
- *Safeguards:* verify against current per-call timeouts; keep per-call `ClientTimeout` overrides working (session default is only the floor for callers that pass none). Start generous (`total=30, sock_read=20`); a reproducing test with a deliberately-stalled local server.

**C12 — Options staleness fail-open fix** · G16 · impact med-high · feasibility high
- *Failure modes:* **north-star tension** — treating unparseable `lastTradeDate` as stale could drop a *real* fresh contract whose timestamp momentarily failed to parse → a dropped instant-trigger signal.
- *Safeguards:* **stored-data validation** — count how many historical flow hits had `lt==0.0`; if non-trivial, prefer "log + treat as stale only when other staleness signals agree" over a hard drop. Flag-gated. This is exactly a Pass-3 decision point.

### TIER 2 — High impact, more involved (structural)

**C7 — Vectorize max-pain (numpy) + keep executor offload** · G7 · impact med-high · feasibility med
- *Failure modes:* numpy rewrite produces a *different* max-pain strike (off-by-one in broadcast, NaN handling), silently changing a displayed number; large-N memory blow-up.
- *Safeguards:* **equivalence test** — assert numpy result == current loop result across recorded chains (SPY/QQQ/IWM + a small name); explicit NaN/empty handling; chunk if N>2000 (won't happen for listed names). No flag needed (pure numeric equivalence) but the equivalence test is mandatory.

**C2 — Persistent SQLite circuit breaker** (`utils/circuit_breaker.py`) · G2/G4/G19 · impact med-high · feasibility med-low
- *Failure modes:* **the central adversarial risk for this run** — a stuck-OPEN breaker hides a source that has actually recovered → drops a real signal; persisting OPEN across restart could keep a healthy source down; a too-low `fail_max` trips on normal blips; the breaker becomes a second source of truth that disagrees with `rate_limiter`.
- *Safeguards:* half-open probe **every cycle** after `reset_timeout` (120 s) so recovery is detected fast; `success_threshold=1`; OPEN returns `None` (source merely **absent that cycle**, the aggregator already None-filters — never blocks an alert); on restart, a persisted-OPEN breaker enters half-open immediately if cooldown already elapsed; `fail_max=5` (not 3) to avoid blip-trips; clear ownership — breaker wraps the *call*, `rate_limiter` still paces; state-transition logging so an OPEN is always visible. **Flag-gated default-OFF + stored-data validation** (replay: would this breaker have dropped any real cross-ref that later succeeded?).

**C9 — Parallelize options-flow watcher** · G8 · impact med-high · feasibility med
- *Failure modes:* parallel Yahoo requests → **a fix that adds load could trigger 429s**, making flow *less* reliable; a per-ticker stall holds a semaphore slot.
- *Safeguards:* `BoundedSemaphore(4)` (matches existing pool), `return_exceptions=True` (one bad ticker doesn't drop the batch), `wait_for` timeout **inside** the sem block; auto-reduce N→2 on observed 429s. Flag-gated; **live check owed** (instant-trigger path) — staged: log parallel timing vs serial before flipping.

**C10 — peer_comparison: TTL-cache `.info` + concurrent fetch + raise ceiling** · G10 · impact med · feasibility med
- *Failure modes:* a longer ceiling (20-25 s) could slow `!all` if `.info` genuinely hangs; stale cached sector label.
- *Safeguards:* fetch `.info` concurrently with the history gather (timeout absorbed, not additive); 1 h TTL is safe (sector doesn't change intraday); explicit TimeoutError → continue with `None` sector (degrade, don't drop the ticker). Flag-gated.

**C3 — Wire `burst_retry.classify_retry` + `parse_retry_after` into news cascade + llm_client** · G13 · impact med · feasibility med
- *Failure modes:* misclassification (a TRANSIENT treated as PERMANENT → source given up too early → dropped signal); double-applying backoff (classifier + rate_limiter both back off).
- *Safeguards:* classifier only *informs* the existing flow; PERMANENT must require a strong signal (4xx/auth, not a one-off 5xx); single backoff authority (rate_limiter owns the sleep; classifier owns the category). Flag-gated.

### TIER 3 — Lower impact / cleanup (cheap, do alongside)

**C8 — Replace `.iterrows()`** · G9 · impact low-med · feasibility high. *Safeguard:* equivalence test; no flag (same output).

**C13 — Distinguish "no flow" vs "fetch failed"** · G17 · impact low-med (observability) · feasibility high. *Failure mode:* over-logging. *Safeguard:* log systemic failure once per scan, not per expiry. No flag (logging only).

**C14 — `api_adapters` report_failure + log level** · G14 · impact med · feasibility med. *Failure mode:* adding backoff could throttle a source that's only briefly flapping. *Safeguard:* report_failure feeds the same rate_limiter (jittered) — bounded; flag-gated since it changes when direct-caller sources are tried.

**C15 — Fix systemd units** · G12 · impact low (ops hardening) · feasibility high BUT **not a code commit** — it's an `/etc/systemd/system/*` edit + `daemon-reload`. *Failure mode:* a botched unit edit could stop a service. *Safeguard:* edit one key, `systemd-analyze verify`, `daemon-reload` (no restart needed for OOMScoreAdjust to apply on next start), verify `is-active` stays green. Present as a **separate ops step**, applied carefully, NOT bundled into the code push.

---

## Cross-cutting safeguards (apply to every flag-gated fix)

1. **Signal-first is inviolable.** No fix may *block* an alert. Breakers/timeouts make an enrichment *absent*, never gate the trade signal. (Matches the engine's existing None-filter design.)
2. **Distinguish transient from persistent** everywhere (the north-star guard). Never hard-disable on a transient blip; never silently treat a parse-failure as a positive.
3. **Visible degradation.** Every place a source goes dark must log a state transition (and, for sustained outages, one throttled ops alert) — the run must make outages *more* visible, not hide them behind a new breaker.
4. **Single backoff authority.** `rate_limiter` owns sleeps; the new breaker owns "is this source open"; `DailyBudgetTracker` owns "is there budget." No two of them sleep on the same failure.

---

## Output for Pass 3 (adversarial + cross-model focus list)

The fixes whose failure modes most need adversarial + cross-model stress-testing (retry-storm / stuck-open / slower-or-dropped-signal / masks-outage):
- **C2** (stuck-open breaker hides a recovered source) — the #1 risk.
- **C4** (blank-thesis fix must never block the alert).
- **C9** (parallel fan-out could *worsen* Yahoo 429s).
- **C12** (fail-closed staleness could drop a real signal).
- **C5** (dead-source alert vs spam; declaring a source dead that's actually fine).
- **C3** (misclassification giving up on a source too early).
