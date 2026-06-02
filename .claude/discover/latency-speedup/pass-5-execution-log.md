# Pass 5 — Execution log (latency-speedup)

Worktree `/home/openclaw/wt-latency` · branch `feat/latency` · commit **85ac88f** (local only).
Baseline before build: `.test-baseline` empty → **0 known-red**.

## Built (commit 85ac88f)
| File | Change |
|---|---|
| `consensus_engine/llm_client.py` | Extracted `_try_model`; added `_serial`/`_race`/`_head_start` + time-based half-open groq circuit breaker; `call_with_fallback` gains `strategy`/`head_start`/`accept` kwargs (default `serial` = unchanged). |
| `consensus_engine/alerts/all_command/narrator.py` | `_invoke_synthesis` opts the !all synthesis call into the configured strategy with a deadline-scaled window + `accept=quality_bar.has_required_sections`. Only this call site opts in. |
| `config/consensus.yaml` | `all_command_strategy: serial` (dark), `all_command_head_start_timeout: 15`, `all_command_circuit_breaker_threshold: 3`. |
| `tests/test_llm_client_fallback.py` | +8 tests (head-start win/stall, race valid-over-fast-invalid, first-nonempty, all-fail, serial parity, breaker open/reset). |
| `tests/test_all_command_narrator_timeout.py`, `tests/test_pr4b_orchestration.py` | Test doubles updated to accept the new kwargs (invariants unchanged). |

## Design refinement vs plan (deliberate)
Plan said add `except asyncio.CancelledError: return None` in `_try_model`. **Did not** — swallowing `CancelledError` breaks task teardown, and in Python 3.8+ it's a `BaseException` so the existing `except Exception` never catches it anyway. Instead: `_try_model` lets it propagate and `_race` absorbs losers via `gather(return_exceptions=True)`. Correct async practice; same end goal (no spurious logs, clean cancel).

## Verification (done)
- **Full suite `pytest -n 2`: 1639 passed, 1 skipped, 0 failed** (twice — once to find the 7 call-signature regressions I introduced in the two narrator-call test files, once after fixing them). **Zero regressions** vs the 0-red baseline.
- Targeted: `test_llm_client_fallback.py` 18/18, the two narrator-call files green.
- Scope proof (correctness critic HIGH): the 6 non-!all callers + the 9 sanitize batch calls never pass `strategy`, so they stay `serial` — confirmed by reading the call sites; `_serial` is behaviorally identical to the pre-change loop (test `test_serial_strategy_explicit_matches_default`).

## NOT yet done — activation gate (the live "go-live", kickoff Step 2)
The hard requirement (measured faster + equal-or-better quality on 3 tickers) is an **activation** step that needs the live bot:
1. Probe groq P50/P90 → set `all_command_head_start_timeout` = P90+5.
2. Merge `feat/latency` → master; flip `all_command_strategy: head_start`; **restart `consensus-engine.service` (coordinate — other sessions live on the bot)**.
3. Time real `!all` on NVDA/AMD/mid-cap; blind-compare quality vs Gemini (`judge-spec.md`).
**Honesty note:** the headline tail speedup (200s→~75s) only manifests during a real groq stall, which can't be summoned on demand — it's proven by the unit tests + design. Live measurement with groq healthy proves *parity* (typical case unchanged, no quality loss), which is the other half of the requirement.

Status: **build complete, tested, committed, dark.** Go-live pending (outward-facing, shared bot → surfaced to user).
