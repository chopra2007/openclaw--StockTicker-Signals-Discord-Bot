# Fix the regression gate so a failed push doesn't just sit there

**Status:** OPEN
**Created:** 2026-07-01

## The problem

At session close ("bye"), `session_close.sh` runs the test suite and, if code changed, only pushes when it's clean. When the gate fails (a real regression, the flag-flip evidence gate, or the vision smoke test), the script just writes a line to `/root/task_system/notifications.log` and stops — it does NOT push, and nothing fixes the failure or retries. The commit sits local-only until a human opens a new session, reads the notification, fixes the problem, and pushes by hand. This has happened at least 12 times in the logs so far (`grep -l "GATE FAILED\|GATE BLOCKED\|SMOKE FAILED" /root/task_system/logs/session_close_*.log`).

## What the user wants (in priority order)

1. **A process that checks, fixes, and re-pushes automatically** when the gate fails — so a failed session-close gate doesn't require the user to notice, open a new session, and push manually.
2. **If #1 turns out to not be safely automatable, shorten the regression gate** (currently the full `pytest tests/ -n 2` suite, ~1270+ tests) so failures are cheaper/faster to catch and clear, reducing how long a broken push sits unpushed.
3. **If #1 isn't feasible, Claude must proactively tell the user at the start of every new session** that a gate failure is sitting unpushed — not wait to be asked.
   - **Note (user, 2026-07-01):** this may be as simple as making the existing session-start check alert specifically when it sees a "gate failed" line — CLAUDE.md already has a "check `notifications.log` at session start, summarize if non-empty" rule, and `session_close.sh` already writes a line there on every gate failure (`GATE FAILED`/`FLAG-FLIP GATE BLOCKED`/`VISION SMOKE FAILED`). So #3 may not need new code — just confirming/tightening that the session-start check reliably flags those specific lines every time (not just when a gate happened to fail right before the last session ended), rather than treating it as a generic notification to summarize quietly. Worth explicitly testing before assuming it's "done."

## Why #1 is hard (needs real design, not a quick patch)

Auto-fixing a failing test is not mechanical — a naive "retry" or "auto-commit a fix" risks masking a real regression or, worse, silently patching over a bug just to get a green push. Whatever gets built needs guardrails, e.g.:
- Distinguish "flaky/known-safe to retry" failures from real regressions before ever attempting an automatic fix.
- Any auto-fix attempt should be narrow (e.g. re-run the specific failed test once to rule out flakiness) rather than an open-ended "have an agent fix it and push" loop.
- Vision smoke-test and flag-flip gate failures are evidence gates, not code bugs — those should probably never auto-push; they need a human decision (is the new switch actually safe?).
- Should still notify the user even when auto-recovery succeeds, so nothing pushes to master unattended without a trace.

## Possible next steps

1. Design a `session_close.sh` retry/recovery layer:
   - On gate failure, spin up an agent (cron/task_system job) to read the failure log, diagnose (flaky vs. real), attempt a scoped fix, re-run only the affected tests, and re-run the full gate before pushing.
   - Cap retries (e.g. 1 auto-fix attempt) — if it still fails, fall back to today's behavior (notify, leave unpushed).
   - Never auto-push on a flag-flip or vision-smoke gate failure — those require a human "yes, this switch is safe" call.
2. If #1 is judged unsafe/out of scope: speed up the gate itself.
   - Profile `pytest tests/ -n 2` to find the slowest test files/fixtures.
   - Consider more xdist workers, better test isolation, or splitting the suite (fast unit tests gate the push; slower integration tests run post-push and just alert on failure).
   - Any speed change must not weaken what already counts as a regression (`.test-baseline` diffing logic in `session_close.sh` / `scripts/pre-push` must stay intact).

## Files / code involved

- `/root/task_system/scripts/session_close.sh` — the gate + push script itself (see `set -e` block for gate logic, baseline diffing, flag-flip gate, vision smoke test)
- `scripts/pre-push` — the local git hook version of the same regression gate
- `scripts/flag_flip_gate.py` — the evidence-gate check
- `.test-baseline` — known-failing tests, used to separate "already broken" from "new regression"
- `/root/task_system/notifications.log` — where gate failures currently get logged (and nothing else happens)
- `/root/task_system/logs/session_close_*.log` — history of past gate runs; useful for measuring current gate runtime and failure frequency

## Open questions

- Is there an existing task_system agent/cron mechanism this could hook into for "wake up, diagnose, fix, retry" automatically? (`/root/task_system/scripts/create_task.sh` + systemd timers is the existing pattern for deferred tasks — worth checking if it fits here.)
- What's an acceptable number of auto-retry attempts before giving up and falling back to manual, so this doesn't turn into an infinite fix-loop?
