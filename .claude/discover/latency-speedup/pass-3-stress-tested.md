# Pass 3 — Adversarial + cross-model (latency-speedup)

3 attackers (quality-loss critic, correctness/blast-radius reviewer, **Codex** cross-model). All three verdict: **ship-with-changes** — core design sound, refinements required. ccg NOT degraded this run (Codex responded).

## Agreement matrix
| Point | Quality critic | Correctness | Codex | Resolution |
|---|---|---|---|---|
| Head-start is the right default | (implicit) | (implicit) | **Agree** | Keep C1 |
| C4 2-stage embed OUT this build | Agree | Agree | **Agree** | Defer C4 | [WONTFIX 2026-06-06 — progressive/2-stage embed KILLED by user, do not build]
| Cancellation/cleanup under-specified | flag (MED) | **flag (CRITICAL)** | flag | **MUST FIX** |
| 15s window is a blind guess | flag (HIGH) | flag (MED) | flag | Probe-first gate |
| Quality nondeterminism in fan-out | flag (HIGH) | flag (MED) | flag | Structural-valid acceptance |
| Circuit-breaker design too crude | flag (MED) | flag (HIGH) | **better design** | Adopt Codex's time-based half-open |
| Scope isolation not enforced in code | — | **flag (HIGH)** | — | `strategy` as per-call param |

## Findings folded into the plan (the changes)

**CRITICAL — cancellation.** `call_with_fallback`'s except clause (`llm_client.py:146`) catches `TimeoutError`+`ClientError` but **not `asyncio.CancelledError`**. The race cancels losing tasks → CancelledError → spurious "unexpected error" logs + possible unclosed-session debris + a stale `rate_limiter._last_request['groq']` slot adding phantom 2s waits. → Explicitly catch `CancelledError` (DEBUG-level, return None), cancel-AND-await losers cleanly.

**HIGH — scope must be enforced, not intended.** A global `strategy` read inside `call_with_fallback` hits all 7 callers. → Add a **`strategy` parameter** to `call_with_fallback` (default `"serial"`); only `narrator._invoke_synthesis` passes `strategy=cfg.get("llm.all_command_strategy")`. The 9 sanitize batch calls + the 6 other callers stay serial by omission. Verification MUST exercise the 6 non-`!all` callers, not just `!all`.

**HIGH — quality nondeterminism (the hard requirement).** A free model can return non-empty-but-**structurally incomplete** content; today's "first non-empty wins" would lock it in, and in a race the faster *smaller* 20b model can beat the better 120b. → The fan-out accepts the first response that passes a **structural check** (has the required section headers — reuse narrator's existing `_qb.has_required_sections`); incomplete responses don't win, the race keeps waiting; only if all are incomplete/timeout does it fall through. Preserves/Improves quality vs today.

**HIGH — window must be data-driven + deadline-aware.** Probe groq P50/P90 on the real synthesis prompt **before** flipping the flag; set window = `max(P90+5s, floor)`. Also scale by budget: `window = min(configured, deadline_seconds * 0.5)` so a near-deadline retry (e.g. 20s left) doesn't spend 15s on groq then starve the fan-out.

**HIGH/Codex — time-based, half-open, per-provider circuit breaker** (replaces the raw module-level counter): after N consecutive groq timeouts/5xx, set `groq_breaker_open_until = monotonic()+120`; **while open, skip the head-start delay** and go straight to the concurrent race (don't waste 15s every call during a known outage); after it expires, allow ONE half-open groq probe before restoring head-start; reset on groq success. Do **not** count transient 429 (the rate-limiter already owns backoff).

**MED — first-SUCCESS not first-COMPLETED.** The race must return the first *successful & valid* result, not the first task to *finish* (a fast failure must not "win"). Explicit helper logic + unit tests for: groq-wins-in-window (free models never spawned), groq-stalls→fan-out-wins, all-fail→`''`.

**MED — preserve observability.** Keep the `idx>0` "fallback hit" log and the "chain exhausted → return ''" behavior through the concurrent path.

**LOW (noted, not built):** request-dedup for concurrent identical `!all` (rare); vault-write timing (pre-existing, C4 only).

## Codex's distinct contributions
- Best idea: the **time-based half-open breaker that skips the head-start while open** — neutralizes the one real "against head-start" argument (dead 15s during a known outage).
- Confirms cancellation/cleanup is under-weighted and shared-chain starvation during outages is real.
- Confirms C4 out for this build (synthesis is only ~5s of the typical ~36s).

## Realistic edge (what this actually buys)
- **Tail (groq down): ~200-240s → ~45-75s** (and during a sustained outage the breaker skips the 15s wait → faster still).
- **Typical (groq healthy): unchanged** (~5s synth; output identical — groq still wins).
- **No quota damage** to the 6 other features; **no quality loss** (structural-valid acceptance + groq-first preference).

## Limitations (what it does NOT solve)
- The typical-case ~36s floor (gather ~12-18s + sanitize ~17-25s) is untouched — that's a separate follow-up (C4 perceived-latency, or a sanitize redesign).
- Quality parity is *measured*, not assumed: the activation gate runs blind-compare on 3 tickers; if it regresses, revert the flag to `serial`.
