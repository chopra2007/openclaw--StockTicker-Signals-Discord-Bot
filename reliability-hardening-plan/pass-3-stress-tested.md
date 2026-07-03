# Pass 3 — Adversarial Stress-Test + Cross-Model Synthesis

**Run:** reliability-hardening · **Date:** 2026-06-28 PDT · **Inputs:** pass-2-filtered.md + local opus critic (p3-critic) + cross-model (Codex gpt-5.5 + Gemini). All critic file:line claims were **independently re-verified by the orchestrator** against live code (see ✓ marks).

> **Outcome:** the *concept* survives intact (signal-first held, zero-new-dep honored, redundancy guard clean), but **4 fixes had concrete "makes-it-worse" mechanisms** and one gap (G6) was mischaracterized. The plan is revised accordingly. Two NEW fixes emerged from the stress test (C19, C20) plus one cross-cutting requirement (health metrics).

---

## A. Cross-model agreement matrix (Claude / Codex / Gemini)

| Concern | Claude | Codex | Gemini | Resolution |
|---|---|---|---|---|
| **C2 stuck-open is #1 risk; half-open must be self-driven** | ✓ | ✓ | ✓ | **Unanimous.** Breaker drives its own time-based half-open; OPEN→None (source absent, never blocks alert); `opened_at` = wall-clock UTC; half-open-on-restart; hard max-expiry. |
| **C9 N=4 too aggressive for Yahoo; can cause its own 429s** | partial | ✓ | ✓ | **Unanimous → C9 DROPPED as specced.** Root fix = global Yahoo semaphore (C20) + N=2 + 429 visibility first. |
| **C12 fail-closed too blunt; drops real fresh contracts** | ✓ | ✓ | ✓ | **Unanimous.** Require a 2nd stale signal; only when staleness enabled; allow-with-note when volume/OI prove activity. |
| **Degradation fixes must expose visible per-source health** | partial | ✓ (metrics) | ✓ (counters) | **Unanimous → new cross-cutting requirement.** |
| **C4 must never delay the alert** | ✓ | ✓ (tiny budget) | ✓ (latency stacking) | Agree; critic additionally proved the instant ping is already LLM-independent. |
| **C1 jitter strategy** | full (research) | — | equal/structured | **DIVERGENCE.** Critic: full jitter halves the mean → probes a dead source ~2× more. → switch to **equal jitter** or sequence C1 behind C2+C5. |
| **C2 persistence worth it?** | persist quota/402 | persist (w/ safeguards) | **net-negative for transient** | **Partial divergence → resolved:** persist ONLY quota/402 (durable); transient stays in-memory (Gemini's warm-up point is right for transient). Decision flagged for user. |
| **Breaker key should include credential/config version** | — | ✓ (single-model) | — | **Single-model (Codex) — adopt:** key breaker by `source+cred_version` so a key rotation clears a stuck-open breaker. |
| **±500ms first-request jitter (herd at top-of-cycle)** | — | — | ✓ (single-model) | **Single-model (Gemini) — adopt as small add** to C1 (stagger source kickoffs). |

No model defended a fix the others rejected; the only true divergences are the jitter *strategy* (resolved: equal) and *how much* to persist (resolved: quota/402 only). Both are now decisions, not gambles.

---

## B. Verified defeaters (critic findings, re-confirmed by orchestrator)

1. **C9 causes its own 429s; its safeguard is unobservable.** ✓ `_fetch_flow_chains` = ~3-4 Yahoo calls/ticker (options.py:289-306); `sem(4)` → 12-16 concurrent on the same unauth Yahoo host that already times out peer_comparison. The flow loop (900 s) can overlap an `!all` also hitting Yahoo (max-pain + peer). The per-expiry 429 is **swallowed at options.py:307 (`except Exception: pass`)** ✓ → "auto-reduce N→2 on 429s" can't fire. → **C9 DROPPED as specced; replaced by C20 (global Yahoo semaphore) + C13-on-flow first.**

2. **C2 stuck-OPEN via monotonic-clock persistence.** ✓ The existing Groq breaker uses `time.monotonic()` (llm_client.py:44). Monotonic is meaningless across a restart → `now - opened_at` garbage → stuck OPEN or instant-open. → **persist `opened_at` as `time.time()` (wall-clock UTC); on load, if `now-opened_at ≥ reset_timeout` enter half-open immediately.** Both Codex & Gemini independently flagged the clock failure.

3. **C7 math is ON the loop, not in an executor; tiebreak would be lost.** ✓ `min(strikes, key=lambda S:(_payout(S), abs(S-mid)))` (options.py:477); `_max_pain_for_chain` runs after `run_in_executor(_f)` returns (options.py:580/594) → on the loop. → **move the math into the `_f` executor closure AND vectorize**; equivalence test must cover payout-ties, duplicate-strike dedup (the loop accumulates OI into a dict at :457 — numpy on raw columns won't), NaN OI (:452), empty/<2-strike chains (:461).

4. **C1 full jitter worsens the loudest current problem.** ✓ `random.uniform(0, cap)` halves the mean backoff → Exa (already ~450 log lines/cycle) probed ~2× more. → **equal jitter `d/2 + uniform(0, d/2)`** (preserves mean), or land C1 only after C2+C5 quarantine dead sources.

5. **G6 mischaracterized + un-dispositioned.** ✓ `validate_ticker_market_cap` uses **Finnhub** and **fails CLOSED** (tickers.py:255/268/277/283); main tweet path calls it directly fail-closed (main.py:1339). The fail-OPEN is ONLY social.py's `_has_market_cap` wrapper (:37-38), narrow. → **new C19: 2-line consistency fix** (`return False` + log) — low severity, not the "high" Pass-0 implied.

6. **C4 instant-ping-blocking fear REFUTED; real impact is the score path.** ✓ Instant ping gated by `base_score>=20` (main.py:1259, LLM-independent); `llm_scorer.py:131` returns `0.0, "LLM scoring unavailable"` on exhaustion → **confidence SCORE collapses to 0.0**, not just thesis text. → **widen C4** to add a non-openrouter (Groq) fallback on the score path too; keep any bounded wait OFF the instant path (it already is).

7. **C3 misclassification + unbounded Retry-After.** ✓ direction confirmed (burst_retry classifies; parse_retry_after can return ~86399 s). → require corroboration for PERMANENT (stable 4xx/auth, not a one-off 403); **cap Retry-After applied to the LLM bucket at ≤120 s**; specify the action each class drives (NEEDS-DECISION baked into C3).

8. **C12 staleness-disabled interaction.** ✓ guard short-circuits on `max_stale_sec` falsy (options.py:268). → **fail-closed ONLY when staleness is enabled**; downstream already COALESCEs `lt→detected_at` (db.py:3806); validate the `lt==0.0` rate against the **LIVE service DB** (worktree DB copies are empty).

9. **conftest forces flags OFF (tests/conftest.py:32).** ✓ every new fix's stored-data validation test MUST force its own flag ON in-body or it silently no-ops. Bake into every test.

10. **Shared-file clobber.** ✓ C2→db.py; C3+C4→llm_client.py; C4→narrator/score path; all flags→consensus.yaml. **Pass-5 must serialize these merges with the 2nd discover run** (the brief's coordination rule).

---

## C. NEW fixes that emerged from the stress test

**C20 — Global Yahoo concurrency budget** (the architectural root cause)
A single process-wide `asyncio.Semaphore` (or a registered "yahoo" source in `rate_limiter`) shared by the options-flow scan, `compute_max_pain`, and `peer_comparison` — the three paths that hammer the same unauth Yahoo host. Fixes the *class* (G8, G10, and the existing peer/max-pain timeouts) instead of patching each instance. **This is the prerequisite that makes a safe C9 revival possible.** Zero new dep.

**C19 — G6 social.py fail-open → fail-closed (2 lines)**
`social.py:37-38` `except Exception: return True` → `log.warning(...); return False`, matching the fail-closed `validate_ticker_market_cap` it wraps. Low severity (narrow path), but restores correctness/traceability.

**Cross-cutting requirement — per-source health visibility** (Codex + Gemini unanimous)
Every degradation fix (C2, C4, C5, C13, C14) must expose a per-source counter: `attempted / skipped-by-breaker / failed-by-class / recovered / alerts-affected`, surfaced every cycle (log line or a small status line) — so a fix makes outages **more** visible, never hides them. Reuse the existing `DailyBudgetTracker.skipped_sources` pattern.

---

## D. Revised per-fix dispositions (the Pass-4 input)

| Fix | Disposition | Final safeguard |
|---|---|---|
| C1 jitter | KEEP | **equal jitter** (not full); + small first-request stagger |
| C2 SQLite breaker | KEEP | wall-clock UTC `opened_at`; self-driven half-open; half-open-on-restart; hard max-expiry; key by `source+cred_version`; persist **quota/402 only**; flag-gated |
| C3 wire burst_retry | KEEP (needs decision) | PERMANENT needs corroboration; cap Retry-After→LLM ≤120 s; specify per-class action; single backoff authority with rate_limiter |
| C4 blank-thesis/score | KEEP | widen to score path; Groq fallback w/ tiny fixed budget; never on instant path; count "thesis/score unavailable" rate |
| C5 dead-source ladder | KEEP | depends on C2+C3; rolling-window so a flapping source isn't called dead; per-source health counter; quota reset via Retry-After/documented time, not blanket UTC-midnight |
| C6 unify budget | DEFER (documented) | (Pass-2 decision stands; optional SerpAPI local-TZ→UTC one-liner) |
| C7 vectorize max-pain | KEEP | move math INTO the `_f` executor + numpy; equivalence test w/ ties/dups/NaN/empty |
| C8 iterrows→itertuples | KEEP | equivalence test |
| **C9 parallel flow** | **DROP as specced** | revive only AFTER C20 + C13-on-flow; then N=2, tied to backoff state |
| C10 peer cache+ceiling | KEEP | concurrent `.info` + 1 h TTL; raise ceiling only because it's OFF the instant path (verified: enrichment/`!all`); confirm `!all` p95 doesn't regress |
| C11 aiohttp timeout | KEEP | per-call `ClientTimeout` overrides still win (llm_client.py:143); verify slow SEC downloads pass their own |
| C12 staleness fail-closed | KEEP | only when staleness enabled; require 2nd stale signal; validate vs LIVE DB |
| C13 flow "no-flow vs failed" | KEEP | **prerequisite for any C9 revival**; log systemic failure once/scan |
| C14 adapter report_failure | KEEP | decide C2/C14 single failure-authority before both land (avoid double backoff) |
| C15 systemd OOMScoreAdjust | KEEP | ops step, not a code commit; `systemd-analyze verify` + `daemon-reload`, no restart needed |
| **C19 G6 fail-closed** (new) | KEEP | 2-line; matches the fail-closed validator |
| **C20 global Yahoo semaphore** (new) | KEEP | the root-cause fix; prerequisite for C9 |

---

## E. Realistic edge / what this actually buys

- **Eliminates the blank-thesis & score-collapse on live alerts** (C4) — the highest user-facing reliability win.
- **Stops the Exa dead-loop log flood and makes dead sources visible** (C5+C2+health counters) instead of silently emitting 0/10.
- **Removes the biggest event-loop stall in `!all`** (C7 max-pain) and the throttle-driven loss of relative-strength (C10), **without adding Yahoo load** (C20 bounds it).
- **Closes two instant-trigger correctness holes** (C12 staleness, C13 outage-masking).
- **Hardens restart behavior** (C2 persistence for quota/402; C11 hang-prevention; C15 OOM).

## F. Explicit limitations / what it does NOT solve

- Does not make dead external sources work (Exa quota, Brave monthly cap) — it makes them **degrade visibly and cheaply**, not recover.
- Does not add new signal sources or change scoring math (out of scope — reliability run).
- C9's latency win is deferred until the global Yahoo budget exists.
- numpy max-pain is faster but still on a single process; not a throughput change.

## G. Open decisions for the user (surface at Pass-4 approval)

1. **C2 persistence scope:** persist quota/402 only (recommended) vs fully in-memory (Gemini's "warm-up is cheaper than stuck-open"). Recommend: persist quota/402 with the self-driven half-open + hard expiry.
2. **C1 jitter:** equal jitter (recommended, preserves mean) vs full jitter only after C2/C5.
3. **C9:** confirm it's deferred behind C20 + C13 (recommended) rather than shipped now.
4. **C12 hard-drop vs allow-with-note:** drop unparseable-and-zero-volume contracts vs always allow with a "[staleness unverified]" tag — pending the LIVE-DB `lt==0.0` count.
