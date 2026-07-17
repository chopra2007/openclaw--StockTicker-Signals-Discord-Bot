# Pass 5 — Execution log (run verify-gate, TODO #77)

**Date:** 2026-07-17
**Builder:** main session (discover Pass 5). Plan: `final-plan.md` (minimal-diff winner 8.7, 8 grafts + SubagentStop structural revision).

## Files changed

| File | Change |
|---|---|
| `/root/.claude/hooks/verify-claim-gate.py` | NEW — deterministic Stop+SubagentStop claim gate (C9), ~230 lines, modeled on verify-on-done.py (fail-open, scope gate, stop_hook_active guard, recursion sentinel). Decision ledger to `/root/.claude/hooks/logs/claim-gate-YYYYMMDD.log`. |
| `/root/.claude/hooks/tests/test_verify_claim_gate.py` | NEW — 15 subprocess-driven tests. |
| `/root/.claude/settings.json` | EDIT — verify-claim-gate.py appended to `hooks.Stop[0].hooks` (timeout 30); new `hooks.SubagentStop` entry, same script. JSON re-validated. |
| `/root/.claude/hooks/openclaw-digest.sh` | EDIT — Block 1 now emits each notifications.log line under `UNVERIFIED as of <ts> — machine snapshot; probe the primary source before repeating:` (ts from the line's own `[...]` stamp, fallback file mtime). Banner + footer unchanged. |

All four are root:root; hook + digest executable (verified `ls -l` 2026-07-17 14:31).

Deviation from plan (1): plan assumed notification stamps are `[YYYY-MM-DD HH:MM:SS UTC]`; real lines also use ISO `[2026-07-14T22:01:41-07:00]`. Extraction made format-agnostic (first bracketed token); both formats probed OK.
Addition (2): `VERIFY_CLAIM_GATE_LOG_DIR` env override (tests only) — needed because root ignores file permissions, so the unwritable-ledger case is simulated via an impossible path.
Addition (3): ledger records carry an extra `msg_len` field (evidence for the live last_assistant_message check).

## Test results

- `python3 -m pytest /root/.claude/hooks/tests/test_verify_claim_gate.py -v` → **15 passed** in 0.92s (2026-07-17 14:30).

## Probe evidence

**Feature 1 (C9 tripwire) — live_probe, all 6 cases ran 2026-07-17 14:30:**
- (a) unverified claim + no tool → `{"decision": "block", ...}` exit 0 ✅
- (b) same claim, Read ran this turn → silent, exit 0 ✅
- (c) claim with citation `schwab_client.py:88` → silent ✅
- (d) benign "market is down 2%" → silent ✅
- (e) malformed stdin → silent, exit 0 (fail-open) ✅
- (f) SubagentStop without agent_transcript_path → falls back to transcript_path → block ✅
- Ledger: one JSON record per invocation with ts/event/decision/matched_verb/snippet/tools_this_turn/transcript_source ✅; unwritable LOG_DIR still blocks correctly (test) ✅

**Feature 2 (C3 digest relabel) — live_probe, ran 2026-07-17 14:31:**
- Seeded Schwab line → `UNVERIFIED as of 2026-07-15 23:00:01 UTC — machine snapshot; probe the primary source before repeating: [...] Schwab login has EXPIRED [...]`, banner + 👉 footer intact, memory digest below unchanged ✅
- ISO-stamp line → correct extraction ✅
- Empty log → Block 1 skipped, digest prints, exit 0 ✅; notifications.log left empty, owner still openclaw:openclaw ✅

**Feature 3 (C4 LLM escalation) — deferred_probe, reason: forward_data.**
Prerequisite verified absent: the go/no-go input is C9's LIVE false-fire rate, which cannot exist before C9 runs in real sessions. The measurement instrument (decision ledger) is installed and already landing records. Owed check: after ~2 weeks live, count `block` records that fired on already-evidenced messages; build C4 only if >5%.

**Live sanity (checklist #13), ran 2026-07-17 14:32:**
- `claude -p "say ok"` in the worktree → replied "Ok.", exit 0, no hang, no spurious block.
- NEW ledger record from that real session: `{"ts": "2026-07-17T14:32:19-0700", "event": "Stop", "decision": "allow_noclaim", "snippet": "Ok.", "msg_len": 3}` — proves the hook fires on a real Stop and `last_assistant_message` is populated on the installed Claude Code version.

## Regression / health verification

Fresh verifier agent (separate from builder, per regression gate), completed 2026-07-17 14:41 — ALL PASS:
1. Repo suite (pre-push invocation replicated): **2992 passed, 10 skipped, 0 failures, 0 new vs `.test-baseline`** (450s).
2. Hook tests independent re-run: 15 passed.
3. `consensus-engine.service` + `openclaw-gateway.service` both `active`.
4. No `GATEWAY drift` / `❌` markers in last 200 engine journal lines.
5. `/root/.openclaw` → `/home/openclaw/.openclaw`.
6. settings.json valid; both Stop hooks + SubagentStop entry present.

Non-blocking finding: `.test-baseline` carries one stale entry (`tests/test_i13_apewisdom_zscore.py::test_baseline_two_days_std` now passes; likely flaky/time-dependent). Left untouched; clear at next `make test-baseline`.

Bonus live evidence: the verifier's own 3 real SubagentStop turn-ends were processed by the new gate (ledger records 14:40–14:41, all `allow_noclaim`).

## Commit / push

Probe gate OK'd by the user 2026-07-17 ("Commit + push + draft PR"). TODO #77 set to SOAKING until 2026-07-31 (ledger accrues the C4 go/no-go); `todo_status_sync.py --fix` + `--check` clean.
