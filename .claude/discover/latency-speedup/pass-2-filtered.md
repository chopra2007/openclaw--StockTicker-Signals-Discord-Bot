# Pass 2 — Filtered design (latency-speedup)

## Locked: C1 head-start, scoped to synthesis, dark-shipped, with a circuit-breaker.

**What:** the synthesis LLM call tries **groq alone** for a head-start window; only if groq stalls does it **fan out** to the 2 free models concurrently and take the first *good* answer. Everything else (the 5s sanitize batch calls, the 6 non-`!all` callers) stays on today's serial loop, byte-for-byte.

### Decisions
| Question | Decision | Why |
|---|---|---|
| head-start vs race-all vs short-timeout | **head-start (C1)** | groq is already position 0 → wins ~100% healthy → typical output unchanged. Free quota burned only on groq stall → the 7 shared callers are protected. Cuts tail 200s→~45-75s. |
| scope | **synthesis call only**, via a per-call `strategy` parameter | A global flag inside `call_with_fallback` would change all 7 callers. A parameter passed only by `_invoke_synthesis` keeps the rest unchanged + testable. |
| window value | **data-driven** — probe groq P50/P90 first; window = max(P90+5s, floor); also scaled by remaining deadline | A hardcoded 15s is a blind guess; if groq P90 > window, fan-out fires too often and the smaller model can win = quality loss. |
| C4 2-stage embed | **OUT (follow-up)** | Helps *perceived* latency only; typical case is already ~36s with synthesis just ~5s. Adds Discord-edit/vault complexity. Revisit only if the typical case stays slow after C1. |
| dark-ship | **default `serial`**; flip to `head_start` only after live before/after measurement | Zero behavior change until proven faster + equal-or-better on 3 tickers. |

### Config flags (in `config/consensus.yaml` under `llm:`)
- `all_command_strategy` (default `serial`) — `serial` | `head_start` | `race_all`
- `all_command_head_start_timeout` (default `15`, tuned post-probe)
- `all_command_circuit_breaker_threshold` (default `3`)

### Rejected
- **C2 race-all** — burns all 3 free quotas every call → self-inflicted 429s starve the other 6 callers; smaller model can win in tail = quality drop. Used only as the circuit-breaker's outage mode.
- **C3 short-timeout** — cuts off legitimately-slow groq → more fallbacks → quality risk. Kept only as a safety cap.
- **Global scope** — would silently change alfred briefing / tweetshift scoring / yt+wolf parsers.
- **C4 2-stage embed** — deferred (see above).
