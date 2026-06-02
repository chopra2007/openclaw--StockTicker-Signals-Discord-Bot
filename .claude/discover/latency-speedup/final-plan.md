# Final Plan — latency-speedup (#6 `!all` slow response)

**Branch:** `feat/latency` · worktree `/home/openclaw/wt-latency` · commit-only (push at session close).
**One-line:** make the `!all` AI summary fast in the tail without changing the healthy-case output, by giving groq a head-start and racing the fallback models only when it stalls — shipped dark (off) behind a config flag, then flipped on after a measured before/after on 3 tickers.

---

## 1. System Overview
Today `consensus_engine/llm_client.py:61 call_with_fallback` walks its 3-model chain **serially** (`for idx, model in enumerate(chain)` at line 85), giving each model up to its full `timeout` (synthesis uses up to 90s — `narrator.py:923`). When groq is healthy it wins in ~5s; when groq is down the loop walks all 3 models and `!all` takes 200–240s (measured: MSFT 240.1s, TSLA 234.3s, both `fallback_data_only`).

The fix adds a **strategy** to `call_with_fallback`, opted into **only by the `!all` synthesis call**:
- **`serial`** (default) — exactly today's loop. Dark-ship: no behavior change until flipped.
- **`head_start`** — try groq alone for a short window; if it stalls, fan out to the 2 free models concurrently and take the first *structurally-valid* answer; cancel the losers.
- **`race_all`** — fire all 3 at once (used only by the circuit-breaker during a sustained groq outage).

Everything else — the 9 sanitize batch calls and the **6 other callers** (`alfred`, `research/sources`, `wolf_email_parser`, `captions_llm_parser`, `video_parser`, `llm_scorer`) — keeps the serial loop untouched.

## 2. Component Architecture
**A. `llm_client.py` — strategy router + helpers (the only logic change)**
- Extract today's per-model body (lines 85–151) into `async def _try_model(idx, model, *, messages, max_tokens, temperature, timeout) -> str | None` — returns content on success, `None` on any failure. Preserves provider routing, `rate_limiter.acquire`, `get_session`, payload, and the per-model log lines. **Adds `except asyncio.CancelledError: return None` (DEBUG) before the generic handler.**
- `async def _serial(chain, ...) -> str` — the existing loop verbatim (calls `_try_model`), keeps `idx>0` "fallback hit" info-log + "chain exhausted → ''" error-log. Behavior identical to master.
- `async def _head_start(chain, *, window, accept, ...) -> str` — groq=chain[0]: `await asyncio.wait_for(_try_model(0, chain[0], timeout=min(window, timeout)), ...)`. If it returns non-empty → return it (parity: groq's own sectionless output is handled by narrator's existing re-prompt). If it times out/None → fan out chain[1:] (see §C race), then if still nothing, return ''.
- `async def _race(models, *, accept, ...) -> str` — `create_task` each; consume via `as_completed`; the **first result that is non-empty AND (accept is None or accept(result))** wins → cancel+await the rest → return it. If none pass `accept`, take the first non-empty; else ''. Logs which model won (fallback-hit) and "exhausted" if all None.
- Circuit-breaker (module state): `_groq_breaker_open_until: float = 0.0`, `_groq_fail_streak: int = 0`. On groq timeout/5xx (not 429) → `_groq_fail_streak += 1`; at threshold → `_groq_breaker_open_until = loop.time() + 120`. On any groq success → reset both. In `_head_start`, **if breaker open → skip the groq head-start and go straight to `_race(chain)`** (all 3); after `open_until`, allow one half-open groq probe.

**B. `call_with_fallback` signature** — add keyword-only params, fully backward-compatible:
```python
async def call_with_fallback(role, messages, *, max_tokens=1024, temperature=0.3,
    timeout=30, chain=None, strategy="serial", head_start=15.0, accept=None) -> str
```
Body: build/validate chain (unchanged), then dispatch: `serial`→`_serial`; `head_start`→`_head_start`; `race_all`→`_race(chain)`. `accept` is consulted **only** by the concurrent strategies (serial keeps the bare `if content:` check → exact master parity).

**C. `narrator._invoke_synthesis` (lines 911–935) — the opt-in (1 call site)**
```python
return await call_with_fallback(
    role="primary", messages=messages, max_tokens=8000, temperature=0.35,
    timeout=timeout, chain=_all_command_chain(),
    strategy=cfg.get("llm.all_command_strategy", "serial"),
    head_start=float(cfg.get("llm.all_command_head_start_timeout", 15)),
    accept=quality_bar.has_required_sections)
```
Also pass deadline-awareness: window passed = `min(head_start, max(1.0, deadline_seconds*0.5))` so a near-deadline retry never spends the whole budget on the head-start. No other narrator change. Sanitize's `_batch_summarize` (line 180) and the 6 other callers are **not** touched → they stay `strategy="serial"` by default.

## 3. Data Flow Pipeline
```
!all → aggregator.handle_all → narrator.synthesize_narrative
   sanitize: 9× _batch_summarize  ........ strategy=serial (UNCHANGED)
   synthesis: _invoke_synthesis ........... strategy=<flag>
        serial    → today's loop
        head_start→ groq(window)  ─hit→ return
                      └stall→ race(free models, accept=has_required_sections) ─valid→ return / '' 
        (breaker open) → race(all 3) immediately, skip the window
   → embed.build_embed → Discord post   (unchanged)
```

## 4. Data Structures
No DB/schema changes. New in-memory module state in `llm_client.py`: `_groq_breaker_open_until: float`, `_groq_fail_streak: int`. New config keys (strings/ints) — see §5. `accept` is a `Callable[[str], bool]`.

## 5. Integration Plan (exact)
| File | Change |
|---|---|
| `consensus_engine/llm_client.py:61-155` | Add `strategy`/`head_start`/`accept` kwargs; extract `_try_model`; add `_serial`/`_head_start`/`_race`; add `CancelledError` handling; add circuit-breaker module state + logic. |
| `consensus_engine/alerts/all_command/narrator.py:911-935` | Pass `strategy`/`head_start`/`accept=quality_bar.has_required_sections` + deadline-scaled window. Import `quality_bar` (already imported locally at line 1011 — hoist or import in `_invoke_synthesis`). |
| `config/consensus.yaml` (`llm:` block, near line 251) | Add `all_command_strategy: serial`, `all_command_head_start_timeout: 15`, `all_command_circuit_breaker_threshold: 3`. `all_command_chain` unchanged. |
| `tests/test_llm_client_fallback.py` (+ new cases) | See §8. |

Config keys (read via `cfg.get`): `llm.all_command_strategy`, `llm.all_command_head_start_timeout`, `llm.all_command_circuit_breaker_threshold`.

## 6. Failure Handling
- **groq stalls** → fan out (window expiry). **groq down (sustained)** → breaker opens → skip window, race all 3 → still ~one slowest-free-model latency, not serial sum.
- **A free model returns incomplete content** → `accept=has_required_sections` rejects it; race waits for the other; if all incomplete, first non-empty is used (narrator's existing re-prompt still applies); if all empty → `''` → `fallback_data_only` (today's behavior).
- **Cancellation** → losers `task.cancel()`-ed and awaited; `CancelledError` caught → `None`, DEBUG log, no rate-limiter debris.
- **Tight deadline** → window scaled to `deadline*0.5`; if `<` floor, effectively serial-groq.
- **Transient 429** → handled by existing `rate_limiter` backoff; does NOT trip the breaker.
- **Flag absent/unknown value** → defaults to `serial` (master behavior).

## 7. Feature Activation Plan
1. Land code with `all_command_strategy: serial` (dark — zero behavior change). All tests + 7-caller checks green.
2. **Probe groq P50/P90** on the real synthesis prompt (repurpose `.omc/research/llm-chain-2026-05-16/probe_llm_chain.py`). Set `all_command_head_start_timeout = max(round(P90)+5, 8)`.
3. Flip `all_command_strategy: head_start` in `config/consensus.yaml`. The engine reads config at process start → **restart `consensus-engine.service`** (coordinate — other sessions are live on the bot). Verify both services `active`, symlink intact, no GATEWAY-drift/LLM-health alert.
4. Run the measured gate (§8). If it passes, keep `head_start` + commit. If quality regresses, revert flag to `serial`, commit the dark code, and surface the measurement.

## 8. Verification Checklist (Pass-5 must satisfy ALL)
**Correctness / regression**
- [ ] `pytest tests/ -n 2` — zero NEW failures vs `.test-baseline` (refresh baseline first).
- [ ] New unit tests pass: (a) head_start groq-wins-in-window → free models never spawned; (b) groq-stall → race picks first *valid* free model, losers cancelled, no `CancelledError`/unclosed-session warning; (c) race where 20b returns sectionless first + 120b returns valid → **120b wins** (accept guard); (d) all fail → `''`; (e) `strategy="serial"` path byte-for-byte equals master (same model order, same logs); (f) breaker opens after N groq timeouts → next call skips window; half-open probe restores; success resets.
**Scope / shared-file tripwire (the 7 callers)**
- [ ] Prove the 6 non-`!all` callers (`alfred.py:92`, `research/sources.py:30`, `wolf_email_parser.py:261`, `captions_llm_parser.py:192`, `video_parser.py:475`, `llm_scorer.py:123`) still call with default `strategy="serial"` and are unchanged — exercise at least `alfred` briefing + one parser end-to-end.
- [ ] `@mention`/`!ask` unaffected (separate path — sanity PONG).
**The HARD requirement — faster WITHOUT quality loss (measured)**
- [ ] Wall-clock real `!all` on **NVDA, AMD, and a mid-cap**, serial vs head_start. Tail/cold case must be materially faster (target: 200s-class → <100s); healthy case unchanged.
- [ ] Narrative **equal-or-better**: blind-compare vs Gemini using `.claude/discover/gemini-quality-all-command/judge-spec.md` (or the chain probe) — all 3 tickers `prefer-bot` OR `tie`; hard-fail rules hold (no `—` in SL/TP, SL drawdown ≤50%, no influencer-name catalysts).
**Always-on**
- [ ] `consensus-engine.service` + `openclaw-gateway.service` both `active`; no GATEWAY-drift, no LLM-health-fail alert; `/root/.openclaw` symlink intact; verified AFTER the restart.

## Out of scope (logged follow-ups)
- C4 2-stage embed (instant deterministic fields, edit narrative in) — perceived-latency win for the typical ~36s case. Revisit if typical case stays slow.
- Sanitize phase ~17–25s (9 LLM calls) and gather ~12–18s — the typical-case floor; separate optimization.
