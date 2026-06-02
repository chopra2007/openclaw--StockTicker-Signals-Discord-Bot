# Pass 1 — Candidates (latency-speedup)

Synthesis of 6 code-grounded research lanes. All file:line from current master 3134b89.

## Measured timing profile (ground truth, from real logs)
| Case | gather | sanitize | synthesize | total | status |
|---|---|---|---|---|---|
| PLTR 05-26 (best) | 7.5s | 17.4s | 4.6s | **22.0s** | ok |
| NVDA 05-29 (typical) | 12.3s | 18.9s | 4.9s | **36.8s** | ok |
| AMD 05-29 (typical) | 17.8s | 18.3s | 5.0s | **42.1s** | ok |
| MSFT 05-21 (tail) | — | — | ~200s | **240.1s** | fallback_data_only |
| TSLA 05-21 (tail) | — | — | ~195s | **234.3s** | fallback_data_only |

**Reading:** In the healthy/typical case synthesis is only ~5s; the floor (~36s) is **gather + sanitize**. The 60–240s pain is the **tail** — groq down → synthesis serial-walks 3 models × up to 90s × up to 3 retries.

## Mechanism (confirmed)
- `llm_client.py:85` `for idx, model in enumerate(chain)` — serial walk, full `timeout` per model.
- Synthesis: `narrator.py:923` timeout `max(15,min(90,deadline))`; fires up to **3×** per !all (primary @1014 + missing-sections retry @1036 + contradiction retry @1064; retries at deadline×0.5). `deadline_seconds` from `aggregator.py:1126 _remaining(start)`, total budget `_DEADLINE_SECONDS=160`.
- Sanitize: `narrator.py:280-291` — **9 concurrent** `_batch_summarize`, each `timeout=5` (`_BATCH_TIMEOUT`), each ALSO walks the chain on failure → steady ~17-25s tax.
- Rate limiter (`rate_limiter.py:16-33`): per-provider buckets, openrouter min-interval 1.0s, groq 2.0s. Shared across all callers.

## Candidate fixes

### C1 — Head-start chain strategy (RECOMMENDED PRIMARY) [from lane 5, strongest]
Try groq alone for a head-start window (~15s, configurable); fan out to the 2 free models concurrently ONLY if groq stalls/fails. Take first good of the fan-out.
- **Quality parity:** groq is already chain position 0, wins ~100% when healthy → typical output **unchanged**. Free-tier quota burned **only on groq failure** (rare), so the 7 shared callers aren't starved.
- **Latency:** typical stays ~5s synth (groq fast). Tail: 200s → **45–75s**.
- **Risk:** head-start window tuning (if groq P75 > window, fan-out fires too often). Mitigate: probe groq P90 first; circuit-breaker to 'race' if groq fails N consecutive.
- **Touch:** `llm_client.py` `call_with_fallback` only. Behind config flag. **Scope to the synthesis call site** (do NOT change the 5s sanitize path or the 6 other callers — opt-in per call).

### C2 — Pure race-all [from lanes 1,2,6]
Fire all 3 concurrently, first-good-wins, cancel losers (`asyncio.as_completed` / `wait(FIRST_COMPLETED)` + manual `task.cancel()`).
- **Bigger tail cut** but **fires all 3 every call** → 3× free-tier quota burn even when groq wins → risk of self-inflicted 429s hurting the other 7 callers; and the **smaller 20b model can win the race in the tail** = possible quality drop. Inferior to C1 on the hard requirement.

### C3 — Short per-model timeout [from lanes 1,2]
Keep serial loop, cut per-model timeout 90s→~15-30s.
- Simple (3 lines) but **cuts off legitimately-slow groq** (groq can take 30-80s under load) → more fallbacks → quality risk. Lower-value; useful only as a safety cap combined with C1.

### C4 — 2-stage embed (ORTHOGONAL, optional) [lane 3 pro, lanes 5/6 con]
Post deterministic embed (Direction/Confidence/Trade Plan/levels/snapshot — all computed pre-LLM) in ~2-5s, then `asyncio.create_task` the synthesis and **edit** the message to add the narrative.
- **Improves *perceived* latency for ALL cases** (typical 36s and tail) — user sees the trade plan instantly. Does not reduce real compute.
- Lane 3: low technical risk — `build_embed` already renders fine with `narrative=''`; `send_command_embed_reply` (`discord.py:640-665`) returns the message id; need a new PATCH `edit_command_embed_reply`. Vault write currently in `asyncio.gather` (`aggregator.py:1262-1266`).
- Lanes 5/6 caution: two-embed UX, Discord edit rate limits (5/2s, space 400ms+), vault-timing coupling, edit 404 if user deletes.

## Integration points (consolidated)
- `consensus_engine/llm_client.py:61-155` — extract per-model body into `_try_model(idx,model)`; add `_serial_models` (verbatim today) + `_head_start`/`_race` strategies; preserve idx>0 fallback log + exhausted-chain `return ''`; special-case `CancelledError → None` (no spurious logs).
- `config/consensus.yaml:251-254` (`all_command_chain`) — add strategy + head_start_timeout params (default = serial/off → dark ship).
- `narrator.py:911-935` `_invoke_synthesis` — opt the synthesis call into the new strategy (sanitize + others stay serial).
- (C4) `aggregator.py:1147-1267 handle_all` — split embed send into stage-1 (deterministic) + background synth+edit+vault; `discord.py` add `edit_command_embed_reply` (PATCH).

## Verification harnesses found (reuse for the gate)
- `.omc/research/llm-chain-2026-05-16/probe_llm_chain.py` — 3-phase (liveness→synthesis→parallel), 12-point quality checklist, groq P50/P90 timing.
- `.omc/research/llm-chain-2026-05-16/live_test_all.py` — end-to-end via webhook, polls xref_cache, extracts journalctl latency + narrative_status.
- `.claude/discover/gemini-quality-all-command/judge-spec.md` — Layer-C blind-compare vs Gemini, 5 dimensions + hard-fail rules; exit = all 3 tickers prefer-bot OR tie.

## Recommendation into Pass 2/3
**Primary: C1 (head-start), scoped to synthesis, config-flagged.** Consider **C4 (2-stage embed)** as a complementary perceived-latency win (separate flag) — but weigh its UX/complexity. **C2 rejected** (quota + tail-quality). **C3** only as a safety cap inside C1. The crux Pass 3 must attack: (1) does head-start ever produce a worse narrative than today? (2) is synthesis-only scoping enough speedup, or is C4 needed to move the typical 36s? (3) async-cancellation / shared-file correctness.
