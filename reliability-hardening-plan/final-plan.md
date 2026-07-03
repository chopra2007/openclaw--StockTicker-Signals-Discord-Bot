# final-plan.md — Reliability & Efficiency Hardening (build-ready)

**Run:** reliability-hardening · **Date:** 2026-06-28 PDT · **Worktree:** `/home/openclaw/wt-reliability-hardening` (branch `reliability-hardening`, off master `f044485`) · **Status:** AWAITING USER APPROVAL — no code written.

**Provenance:** Pass 0 (live logs + 4 code researchers, all cross-verified) → Pass 1 (2 web-research agents) → Pass 2 (filter/rank) → Pass 3 (opus critic + Codex + Gemini, every claim re-verified at file:line). 15 fixes ship; 1 (C9) deferred; 1 (C6) documented-only.

> **North star (unchanged):** the bot keeps posting real, high-probability Discord alerts at no added cost. Every fix makes that pipeline more dependable/faster and **must never block, delay, or drop a real alert.** "Signal-first" is inviolable: breakers/timeouts make an *enrichment* absent, never gate the trade signal.

---

## 1. System Overview

The consensus-engine is already substantially resilient (parallel news race, full yfinance thread-offload, a retry classifier, a persistent daily-budget gate, per-source backoff). This run does **not** rewrite that — it closes the **gaps**: (a) breaker/quota state that resets on restart, (b) a dead source (Exa) that loops silently, (c) a blank LLM thesis / collapsed score on a live alert, (d) CPU math on the event loop, (e) two instant-trigger correctness holes, and (f) the absence of a global Yahoo concurrency budget. Almost every fix **extends** an existing module; the only new files are one breaker module + its table. **Zero new production dependencies** (stdlib `random`, already-present `numpy` via pandas, already-present `aiosqlite`).

**Fixes ranked by live-impact × feasibility:**

| Rank | Fix | Gap | Impact | Phase |
|---|---|---|---|---|
| 1 | **C4** LLM blank-thesis + score-collapse fallback | G18 | HIGH | 3 |
| 2 | **C20** Global Yahoo concurrency semaphore (new) | G8/G10 class | med-high | 0 |
| 3 | **C2** Persistent SQLite circuit breaker (new) | G2/G4/G19 | med-high | 1 |
| 4 | **C7** Vectorize max-pain + move into executor | G7 | med-high | 4 |
| 5 | **C12** Options staleness fail-closed (guarded) | G16 | med-high | 5 |
| 6 | **C11** aiohttp default session timeout | G11 | med | 0 |
| 7 | **C5** Dead-source ladder + health counters + ops alert | G3 | med | 2 |
| 8 | **C3** Wire `burst_retry` into news cascade + LLM | G13 | med | 1 |
| 9 | **C10** peer_comparison cache + concurrent `.info` + ceiling | G10 | med | 4 |
| 10 | **C13** Options "no-flow vs fetch-failed" visibility | G17 | med | 0 |
| 11 | **C14** api_adapters `report_failure` + log level | G14 | med | 1 |
| 12 | **C1** Equal-jitter backoff + first-request stagger | G1 | low-med | 2 |
| 13 | **C8** `iterrows`→`itertuples`/vectorized | G9 | low-med | 0 |
| 14 | **C19** social.py `_has_market_cap` fail-closed | G6 | low | 5 |
| 15 | **C15** systemd `OOMScoreAdjust` + MemoryMax (ops) | G12 | low-op | 0 |
| — | **C9** Parallelize flow watcher | G8 | **DEFERRED** behind C20+C13 | later |
| — | **C6** Unify budget tracking | G5 | **DOC-ONLY** (deferred) | — |

**Build sequence (respects Pass-3 ordering constraints):** Phase 0 (no-behavior-change foundations) → Phase 1 (breaker+retry core) → Phase 2 (dead-source visibility) → Phase 3 (LLM) → Phase 4 (efficiency) → Phase 5 (correctness). C2→C5, C3→C5, C20→C9, C13→C9; decide C2/C14 failure-authority before both land; C1 after C2+C5.

---

## 2. Component Architecture

### NEW: `consensus_engine/utils/circuit_breaker.py` (C2)
- **Purpose:** canonical 3-state breaker (closed→open→half-open) with optional SQLite persistence, replacing/backing the ad-hoc in-memory breakers (Brave-402, Gemini-bench). Groq head-start breaker stays as-is (intentionally per-cycle, in-memory).
- **Inputs:** `source` name, a `cred_version` (so a key rotation clears a stuck breaker), failure/success signals, optional `Retry-After` seconds.
- **Outputs:** `allow(source) -> bool` (False when OPEN and not yet probe-time; True for closed OR the single half-open probe), state-transition events for logging/alerting.
- **Core logic:** `fail_max=5` (config), `reset_timeout=120s` (config), `success_threshold=1`, rolling-window failure reset. **`opened_at` stored as wall-clock UTC `time.time()` — NEVER `time.monotonic()`** (the verified stuck-open defeater). On every `allow()`: if OPEN and `now-opened_at ≥ reset_timeout` → transition to half-open and return True for exactly ONE probe (self-driven, does not depend on external traffic). On load/restart: same check runs immediately (half-open-on-restart). Hard max-expiry (e.g. 30 min) caps any OPEN that isn't an explicit per-day quota. In-memory cache (5 s TTL) over the SQLite row to avoid per-call DB hits; SQLite opened WAL.
- **Persistence policy:** persist ONLY durable conditions — `QUOTA_BLOCKED`/HTTP-402/per-key-bench (these survive a restart and must not re-probe blindly). TRANSIENT failures stay in-memory (a restart warm-up retry is correct — Gemini's point).

### EXTEND: `utils/rate_limiter.py` (C1)
- Equal-jitter on the existing formula: `d = min(30·2^(n-3), 600); sleep = d/2 + random.uniform(0, d/2)`. Preserves the mean (full jitter would halve it → 2× more probes of a dead source). Plus a small per-source kickoff stagger (±≤0.5 s) so all sources don't fire at top-of-cycle.

### EXTEND: `utils/burst_retry.py` consumers (C3)
- Wire the EXISTING `classify_retry()` + `parse_retry_after()` into `scanners/news.py` tier functions and `llm_client.py`. `rate_limiter` remains the SINGLE backoff authority (owns the sleep); the classifier only assigns the *category*; the breaker (C2) owns "is this source open." PERMANENT requires corroboration (stable 4xx/auth body, not a one-off 403). **Retry-After applied to the LLM/openrouter bucket capped at ≤120 s** (raw value can be 86399 s).

### NEW (small): Global Yahoo budget (C20)
- A process-wide `asyncio.Semaphore` (or a registered `"yahoo"` source in `rate_limiter`) shared by `scanners/options.py` (flow + max-pain) and `analysis/peer_comparison.py`. Bounds total concurrent hits to the unauth Yahoo host. Default cap small (e.g. 3), config-driven. This is the root-cause fix for the timeout class.

### EXTEND: alert/score paths (C4)
- `llm_client.py` / `analysis/llm_scorer.py` / `cross_reference.py`: when the openrouter bucket is backed off, (a) add a non-openrouter (Groq) fallback on BOTH the thesis and the `score_confidence` path; (b) the alert ALWAYS fires (instant ping already gated by `base_score`, LLM-independent — verified main.py:1259); (c) emit an ERROR + increment a "thesis/score unavailable" counter; (d) any wait is tiny/bounded and OFF the instant path.

### EXTEND: dead-source ladder + health (C5 + cross-cutting)
- Layer on C2+C3: TRANSIENT(1-2)→DEGRADED(3-4/quota)→OPEN(5+/permanent), state-transition logging, ONE throttled (30-min, keyed by `source+class`) ops-channel alert on closed→open. Per-source health counter (`attempted/skipped-by-breaker/failed-by-class/recovered/alerts-affected`), reusing the `DailyBudgetTracker.skipped_sources` surfacing pattern. Quota reset uses parsed `Retry-After`/documented reset, not a blanket UTC-midnight.

### EXTEND: efficiency (C7/C8/C10/C20)
- C7: vectorize `_max_pain_for_chain`/`_payout` with numpy broadcasting **and move it INTO the `_f` executor closure** (it currently runs on the loop after the fetch returns). Preserve the tiebreak `min(payout, abs(S-mid))` and the OI-dedup semantics. C8: `.iterrows()`→`.itertuples()`/vectorized. C10: TTL-cache (1 h) the slow `.info`, fetch it concurrently with the history gather (not front-loaded), raise the `wait_for` ceiling 12→20-25 s (OFF the instant path), explicit TimeoutError→`None` sector (degrade, don't drop).

### EXTEND: correctness (C12/C13/C19)
- C12: `_ts_to_epoch` returns a sentinel; the staleness guard treats unparseable/`0.0` as STALE **only when staleness is enabled** AND only drops when a 2nd stale signal agrees (e.g. volume==0/low OI) — otherwise allow with a "[staleness unverified]" tag. C13: replace `except Exception: pass` (options.py:164/307/555) with WARN + a per-scan fetch-failure counter; surface a systemic (all-expiries-failed) outage once/scan. C19: social.py:37 `return True`→`log.warning; return False`.

### OPS (C15) — not a code commit
- `/etc/systemd/system/{consensus-engine,openclaw-gateway}.service`: `OOMScoreAdj`→`OOMScoreAdjust`; add `MemoryMax` to consensus-engine. `systemd-analyze verify` + `daemon-reload` (no restart needed to register; applies next start).

---

## 3. Data Flow Pipeline (where the new pieces sit)

```
poll cycle / instant tweet
  ├─ source fetch (news cascade, social, SEC, options, ...)
  │     ├─ rate_limiter.acquire(src)        [C1 equal jitter]
  │     ├─ circuit_breaker.allow(src)        [C2 — NEW gate; OPEN→skip this source, never blocks alert]
  │     ├─ on failure: classify_retry()      [C3] → rate_limiter.report_failure + breaker.record [C5 ladder, health counter]
  │     └─ yahoo-touching fetch → global Yahoo semaphore  [C20]
  ├─ instant ping  ── gated by base_score (LLM-independent) ── ALWAYS fires if it qualifies
  ├─ enrichment / score
  │     ├─ options flow: _ts_to_epoch staleness [C12], no-flow-vs-failed [C13], flow watcher (serial for now; C9 deferred)
  │     ├─ max-pain: vectorized, in executor   [C7], bounded by Yahoo sem [C20]
  │     ├─ peer_comparison: cached .info + concurrent + 20-25s ceiling [C10], Yahoo sem [C20]
  │     └─ LLM thesis + score_confidence: openrouter→Groq fallback, never blank/zero-silently [C4]
  └─ alert assembled (thesis/score degrade visibly if LLM exhausted, alert still posts)
```

---

## 4. Data Structures

### New SQLite table `circuit_breaker_state` (db.py schema + migration)
```sql
CREATE TABLE IF NOT EXISTS circuit_breaker_state (
    source_key    TEXT PRIMARY KEY,   -- "<source>@<cred_version>" so key rotation clears stale OPEN
    state         TEXT NOT NULL DEFAULT 'closed',   -- 'closed'|'open'|'half_open'
    failure_count INTEGER NOT NULL DEFAULT 0,
    opened_at     REAL,               -- WALL-CLOCK UTC epoch (time.time()); NULL when closed
    open_reason   TEXT,               -- 'quota'|'402'|'bench'|'permanent'
    next_probe_at REAL,               -- opened_at + reset_timeout
    last_alerted_at REAL,             -- ops-alert throttle (30 min), keyed by source+class
    last_updated  REAL NOT NULL DEFAULT (unixepoch())
);
```
Only `open_reason IN ('quota','402','bench')` rows are *persisted-meaningfully* across restart; transient OPENs may be written but are superseded by the hard max-expiry on load.

### Reused: `api_usage_daily.skipped_sources` pattern for per-source health counters (no new table needed; in-memory per-cycle set + a log line). Optional small `source_health` counters can live in `api_usage_daily` columns if persistence is wanted (decision).

---

## 5. Integration Plan (exact connection points)

| Fix | File(s) | Change point | Config key (default) |
|---|---|---|---|
| C1 | `utils/rate_limiter.py:78` | equal-jitter formula; stagger in `acquire` | `rate_limiter.jitter_mode` ("equal") |
| C2 | NEW `utils/circuit_breaker.py`; `db.py` (~:199 schema + migration list ~:876) | new module + table; wire into news.py:363 (Brave) & gemini_video_parser.py:95 (bench) | `circuit_breaker.enabled` (false), `.fail_max` (5), `.reset_timeout_s` (120), `.hard_max_open_s` (1800) |
| C3 | `scanners/news.py` tier fns (166/265/315/423), `llm_client.py:155-170` | call `classify_retry`/`parse_retry_after`; cap Retry-After→LLM ≤120 | `retry.use_classifier` (false), `retry.llm_retry_after_cap_s` (120) |
| C4 | `llm_client.py`, `analysis/llm_scorer.py:131`, `cross_reference.py:1093` | non-openrouter fallback on thesis+score; "(unavailable)" note; counter | `llm.score_fallback_enabled` (false) |
| C5 | `utils/circuit_breaker.py` + `alerts/` ops-channel send | ladder + transition log + throttled ops alert + health counter | `dead_source.ops_alert_enabled` (false), `.ops_channel_id` |
| C7 | `scanners/options.py` `_max_pain_for_chain`/`_payout` (≈457-478) + move into `_f` (≈560-595) | numpy vectorize; compute inside executor | (no flag — numeric-equivalent; equivalence test gates it) |
| C8 | `scanners/options.py:180,366` | `.iterrows()`→`.itertuples()` | (no flag) |
| C9 | `scanners/options.py:362-364` | **DEFERRED** — only after C20+C13 | `options_flow.parallel` (false) |
| C10 | `analysis/peer_comparison.py:85,119-121,199` | TTL `.info` cache + concurrent fetch + ceiling 12→`peer.timeout_s` | `peer.info_cache_ttl_s` (3600), `peer.timeout_s` (22) |
| C11 | `utils/http.py` | `ClientTimeout(total=30, connect=10, sock_read=20)` on shared session | `http.default_timeout_total_s` (30) |
| C12 | `scanners/options.py:227,268` | sentinel + staleness-enabled-guarded fail-closed + 2nd-signal | `options_flow.staleness_failclosed` (false) |
| C13 | `scanners/options.py:164/307/555` | WARN + fetch-failure counter; systemic-outage surface | (no flag — logging) |
| C14 | `api_adapters.py:70/92/145/201/244/291/318` | `rate_limiter.report_failure(src)` + WARN on repeated | `adapters.report_failure` (false) |
| C19 | `scanners/social.py:37-38` | `return True`→`log.warning; return False` | (no flag — 2-line correctness) |
| C20 | NEW small helper (in `utils/http.py` or `rate_limiter`) + call sites in `options.py`, `peer_comparison.py` | shared `asyncio.Semaphore` around Yahoo fetches | `yahoo.max_concurrency` (3) |
| C15 | `/etc/systemd/system/*.service` | OOMScoreAdj→OOMScoreAdjust; MemoryMax | (ops, not config) |

**Flag convention:** all read via `config.get("dot.path", default)`, **default-OFF** for anything alter-able. Pure-internal fixes (C1, C7, C8, C11, C13, C19, C20) have no behavior flag but DO get a reproducing test + regression-gate proof.

---

## 6. Failure Handling (per-fix, data missing/delayed/conflicting)

- **C2 breaker:** if the SQLite read fails → fail OPEN-to-CLOSED (treat as closed, i.e. allow the call) so a DB hiccup never silently blocks a source. OPEN always returns `None` to the caller (source absent that cycle); never raises into the alert path. Hard max-expiry guarantees no permanent stuck-open for non-quota reasons.
- **C3 classifier:** unknown/ambiguous status → TRANSIENT (retry, not give-up). PERMANENT only on corroborated 4xx/auth.
- **C4 LLM:** all providers down → alert posts with "(thesis unavailable — LLM rate-limited)" + score uses its non-LLM components; never blank, never blocked, never a silent 0.0.
- **C7/C8 math:** empty/<2-strike chain → return None (current behavior); NaN OI → treated as 0 (matches loop); equivalence test asserts identical strike vs the loop incl. ties.
- **C10 peer:** `.info` timeout/empty → `None` sector, ticker still scored on history; cache miss → one slow fetch then cached.
- **C11 timeout:** a legitimately slow call must pass its own per-call `ClientTimeout` (those still win); session default only protects callers that pass none.
- **C12 staleness:** unparseable + genuine volume/OI → allow with "[staleness unverified]" tag (don't drop a real contract); only hard-drop when staleness enabled AND a 2nd stale signal agrees.
- **C20 Yahoo sem:** semaphore is bounded but NEVER held across an alert decision; if contended, enrichment waits or is skipped — the alert is not delayed.
- **C5 dead-source:** OPEN = absent that cycle; half-open re-probes next cycle; ops alert throttled 30 min/source+class so a flapping source can't spam.

---

## 7. Feature Activation Plan

Every alter-able fix ships **default-OFF**; we validate on stored data, then flip ON in `config/consensus.yaml` and the engine **hot-reloads config each poll cycle** (no restart needed for `config.get` reads) — EXCEPT C2's new table (created on startup via the migration; needs one restart to create the table, then flag flip is hot). C11/C20/C7/C8 are code paths active on next deploy (restart). C15 is an `/etc/systemd` edit + `daemon-reload`.

**Validation per fix (stored-data + live-check-owed):**

| Fix | Stored-data validation | Live check still owed |
|---|---|---|
| C2 | replay `decision_snapshots`: would the breaker have dropped any cross-ref that *later* succeeded? Count false-trips. | shadow-log breaker transitions for N cycles before flag ON |
| C3 | unit: classifier maps known statuses correctly; no PERMANENT on one-off 403 | shadow-log classifications vs current behavior |
| C4 | unit: forced all-LLM-fail → alert still assembled, score non-zero from non-LLM parts, counter increments | **staged**: shadow-log "thesis/score unavailable" rate; confirm real alerts unaffected before ON |
| C5 | replay Exa failure window: ladder reaches OPEN, ONE alert, half-open recovers | shadow-log ops alerts (to a test channel) before live ops channel |
| C7 | **equivalence test**: numpy max-pain == loop on recorded chains incl. payout-ties, dup strikes, NaN OI, empty/<2-strike | spot-check `!all` output for 3 tickers matches pre-change |
| C9 | (deferred) | (deferred) |
| C10 | measure `!all` p95 latency before/after; relative-strength field present more often | confirm no `!all` regression live |
| C11 | repro test: stalled local server hits sock_read cap | confirm slow SEC/LLM calls still pass (per-call timeouts) |
| C12 | **LIVE-DB** count of `lt==0.0` historical hits (worktree DB empty); how many real hits would drop | shadow-log would-drop count before hard-drop ON |
| C13 | unit: systemic fetch-failure logs once + counter | confirm "no flow" vs "fetch failed" distinguishable in live logs |
| C14 | unit: adapter failure calls report_failure | shadow-log adapter backoff |
| C1/C8/C19/C20/C15 | reproducing test + regression-gate (set-not-count) | C20: confirm Yahoo 429 rate drops; C15: services stay `active` |

**Always-on post-change checks (every flip):** `consensus-engine.service` + `openclaw-gateway.service` both `active`; no `❌ GATEWAY drift`; no LLM-health failure alert; `/root/.openclaw` symlink intact.

---

## 8. Verification Checklist (input → output, Pass 5 must pass ALL)

1. **C4 blank-thesis:** force all LLM providers to fail (monkeypatch) → assert (a) `send_instant_ping` still fires for a base_score≥20 tweet, (b) the alert text contains the "(thesis unavailable)" note not an empty string, (c) `score_confidence` returns a non-zero from non-LLM components (or the documented degraded value, never a silent 0.0), (d) the "unavailable" counter incremented, (e) ERROR logged.
2. **C2 breaker:** simulate 5 failures → OPEN; `allow()` returns False; advance wall-clock past `reset_timeout` → next `allow()` returns True (half-open probe) without external traffic; success → CLOSED. **Restart simulation:** write an OPEN row with `opened_at` in the past, reload → breaker enters half-open immediately (NOT stuck). Inject a `time.monotonic`-style value → test FAILS (guards against the defeater).
3. **C20 Yahoo sem:** with the semaphore at cap N, assert concurrent Yahoo-touching fetches never exceed N across flow+max-pain+peer; assert the alert decision is never awaited behind the semaphore.
4. **C7 max-pain equivalence:** numpy result == loop result (strike, total_oi, call/put OI) on recorded SPY/QQQ/IWM chains AND synthetic chains with payout-ties, duplicate strikes, NaN OI, and <2-strike/empty. Confirm the math now runs inside the executor (loop not blocked) via a timing assertion.
5. **C12 staleness:** a contract with unparseable `lastTradeDate` + volume==0 → dropped (when staleness enabled); same with real volume/OI → allowed with "[staleness unverified]"; with staleness DISABLED → behavior unchanged (no new drops). LIVE-DB `lt==0.0` count reported.
6. **C11 timeout:** a stalled endpoint trips `sock_read=20` (no hang); a call passing its own `ClientTimeout(total=60)` still gets 60 s.
7. **C5 dead-source:** replay Exa's failure window → ladder reaches OPEN, exactly ONE ops alert (to test channel), half-open recovery on next success; the per-source health counter reflects `skipped-by-breaker`.
8. **C3 classifier:** a one-off 403 → TRANSIENT (not PERMANENT); a quota body → QUOTA_BLOCKED; Retry-After of 86399 s applied to the LLM bucket is capped at 120 s.
9. **C10 peer:** `.info` cached after first call; `.info` fetched concurrently with history (not front-loaded); a throttled `.info` → ticker still scored with `None` sector, not dropped; `!all` p95 not worse.
10. **C13/C14/C19/C1/C8:** unit tests for each (systemic-outage log once; adapter report_failure called; social.py returns False on error; equal-jitter preserves mean within tolerance; itertuples output == iterrows output).
11. **Regression gate:** full `pytest -n 2`; **no currently-passing test newly fails** (set, not count, vs `.test-baseline`); every new validation test forces its own flag ON in-body (conftest forces them OFF). `grep -rn` each changed signature/output-string across `tests/` and run the matches.
12. **Shared-file coordination (serialize merges with the 2nd discover run; no git stash in the shared tree):** `db.py` (C2 table), `llm_client.py` (C3 + C4 both edit it), `narrator.py:~1102/1160` (C4 thesis path), `config/consensus.yaml` (every flag), and **`rate_limiter.py` — high fan-in: C1 + C2/C5/C14 all interact with it, treat as shared.** Also verify the `!all` aggregator's None-filter still holds when a breaker/timeout returns None (C9/C10). Re-run the gate after each merge.
13. **Always-on:** both services `active`; no GATEWAY drift / LLM-health alert; symlink intact; one real `--dry-run --once` end-to-end cycle inspected for expected output.

---

## 9. Decisions to confirm at approval

1. **C2 persistence scope** — persist quota/402/bench only (recommended) vs fully in-memory.
2. **C1 jitter** — equal jitter (recommended) vs full-jitter-after-C2/C5.
3. **C9** — confirm DEFERRED behind C20+C13 (recommended) vs ship now.
4. **C12** — hard-drop-on-2nd-signal vs always allow-with-note (pending LIVE-DB `lt==0.0` count).
5. **Scope trim?** — if you want a smaller first cut, Tier-1 (C4, C20, C2, C7, C12, C11) delivers most of the live-alert reliability win; Tiers 2-3 are cleanup.

**STOP — awaiting approval. No code, no commits, no Pass 5 until you approve.**
