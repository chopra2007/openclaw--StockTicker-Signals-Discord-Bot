# Fix the regression gate so a failed push doesn't just sit there

**Status:** DONE 2026-07-09
**Created:** 2026-07-01

**CURRENT STATUS (2026-07-09) — DONE.** The AI layer is raced, pinned, wired, and deliberately weak-but-safe.

**How often this even matters (measured, 64 session_close logs).** 13 red gates in 64 sessions — but **7 of those 13 were the same persistent frozen-date test**, a time bomb unrelated to that session's work. Since it was fixed on 07-02: **1 red gate in 17 sessions (~6%)**. The `undeclared_dependency` class the deterministic layer handles has happened **once, ever**, and in CI rather than at session close. So a genuine logic bug reddens the gate roughly **once a month**.

**The race (3 cheap OpenRouter models, real corpus, cross-family from Claude).** A single attempt each said `qwen/qwen3-coder-next` won. Re-running its exact case by hand did **not** reproduce the pass — these models are nondeterministic at `temperature=0`. So each was run **5 times** against the reproduced bug, verifying every patch:

| model | working patch | bad patch | no usable patch |
|---|---|---|---|
| `qwen/qwen3-coder-next` | **1 / 5** | 4 | 0 |
| `deepseek/deepseek-chat-v3.1` | 0 / 5 | 5 | 0 |
| `z-ai/glm-4.5-air` | 0 / 5 | 2 | 3 |

`qwen/qwen3-coder-next` is the only model that ever fixes it, and the cheapest. Pinned — at one attempt in five, not the "it works" the single sample implied. The branch therefore **retries 3×**, verifying and reverting between attempts: ~49% per red gate, ~1.5 cents. Full evidence: `plans/ci-fixer-model-race-2026-07-09.md`.

**Two bugs the first race exposed, both mine:**
- The models never saw the code under test — context came only from files named in the traceback, and the bug's cause (`wolf_news.post_event` stamping `time.time()`) appears nowhere in it. `relevant_files()` now follows the failing test's imports two hops deep. **This single change flipped the winner from "can't fix it" to "can."**
- A hung model call could hang forever: `requests`' read timeout measures the gap *between* bytes, and OpenRouter's SSE keepalives reset it indefinitely. One call blocked 25 minutes under a 240s timeout. The fixer now streams under a hard wall-clock deadline; `glm-4.5-air` tripped it during the re-race.

**Fix + HOLD, as decided.** `scripts/ci_ai_fixer.py` classifies and patches; `ci_autofix.sh` verifies the failing tests pass, then runs the **full suite diffed against `.test-baseline`**, then **commits locally and stops**. It posts to `#errors` with an @-mention telling you a fix is waiting. It never pushes. Missing-package fixes still auto-push — those are mechanical. All old guardrails intact: retry cap, forbidden-path gate (config/CI/flags/go-live), clean-tree freshness skip, `git checkout` never `stash`.

A wrong patch is harmless by construction: it must make the failing tests pass **and** leave the suite clean, or it is reverted and you are paged — exactly today's behaviour. `claude` is gone from the script; it was never needed.

---
_Original notes below._

**Status (historical):** LARGELY DONE (2026-07-03) — Part 1 SHIPPED; Part 2 deterministic auto-fixer LIVE (no AI); AI upgrade opt-in/deferred.
  - **Part 1 LIVE:** `ci-monitor.sh` now extracts REAL failing test ids from the FULL CI log (proven on the 07-02 pyarrow run — old `--log-failed` returned nothing); `session_close.sh` captures push exit + writes a loud `notifications.log` line on rejection; `openclaw-digest.sh` SessionStart hook banners any GATE/CI/PUSH alert; `scripts/pre-push` uses a per-user `/tmp` log (fixes the 07-02 stale-root-owned-tmp reject) synced to `.git/hooks/pre-push`; `notifications.log` made openclaw-writable. pyarrow live symptom fixed (ed143c9).
  - **Part 2 LIVE (deterministic, no AI, no login):** `/root/task_system/scripts/ci_autofix.sh` runs as openclaw when the gate is red and: (1) auto-declares an undeclared dependency — extracts the missing module from the CI error (incl. pandas' "Missing optional dependency 'X'" phrasing = the real 07-02 pyarrow signature), adds it to requirements.txt, verifies import + tests pass, commits + pushes; (2) detects flaky (local pass ×2 → no-op); (3) escalates a real logic bug to a human. Guardrails proven end-to-end (2026-07-03): retry cap fires at 2; clean-tree freshness skip; HARD forbidden-path gate (never auto-pushes config/flag/vision/go-live/CI); local re-verify; `git checkout` never stash. Full chain ci-monitor→fixer verified on the real pyarrow run (extracts 'pyarrow', skipped safely under unpushed work). ci-monitor delegates whenever the fixer exists (no AI precondition). State files (`ci-autofix.log`, `ci-autofix-attempts.txt`) pre-created openclaw-writable.
  - **Part 2 AI upgrade (deferred, opt-in):** a guarded `claude` branch in the same script fixes genuine LOGIC bugs unattended — was believed dormant until claude is installed+authed for the openclaw user (root-only auth today; Codex has the same hurdle). **Premise corrected 2026-07-08:** it never needed claude — Gemini, Groq, and OpenRouter all answer live as the `openclaw` user with keys already in `.env`. Next step is the cheap-model race below, NOT provisioning claude.
**CURRENT STATUS (2026-07-02):** The concrete example test is FIXED (option (b) below — made deterministic), but the general auto-recovery process this item is actually about (a mechanism that checks/fixes/re-pushes ANY future gate failure, not just this one test) is still not built. Also found and fixed a second, unrelated pre-existing gate failure the same session (`test_sunday_recap_and_addon_restart_safe` — a frozen-date test whose posted-at timestamp used the real wall clock instead of the simulated one, so it silently started failing as real time passed the simulated date). Both fixes are commits `9557ca8` and `db47044`; `.test-baseline` is back to just the one unrelated ApeWisdom test. Next concrete step for the item itself: still need to decide/build the general auto-recovery mechanism (see "What the user wants" below) — today's fixes closed the two known instances, not the underlying process gap.

**CURRENT STATUS (2026-07-01):** Active/open, no fix built yet. Now has a live, reproducible instance — the flaky `test_market_command_renders_all_four_reads` (see "Concrete flaky-test example" below). Next concrete step: decide per that example whether the general fix is (a) a scoped "re-run the failed test once before blocking" retry in the gate, or (b) making these live-data tests deterministic (mock the fetch) so they can't flake at all.

## Concrete flaky-test example (2026-07-01, FIXED 2026-07-02) — the market-command test

**Test:** `tests/test_market_command.py::test_market_command_renders_all_four_reads`

**What happens:** the test calls `_seed_temp_db()`, which fetches **live daily price history (OHLCV) from yfinance** for the sector/factor ETFs, then asserts the four market reads are non-zero (`summary["sector_rs_daily"] > 0`, etc.). When this VPS's IP is being throttled by yfinance, the fetch returns almost no history — the logs show `[F3] Not enough closes to compute trend (got 19, need 220)` — so zero reads are computed and the assertion `assert 0 > 0` fails.

**Why it's a flake, not a real regression:** it passes when yfinance is not throttling (it passed cleanly earlier the same day on identical code) and fails only when the data source is starved. The failure is in the test's live-data seeding step, which runs *before* the command code it is meant to exercise is even called — so it is independent of whatever code change is being pushed. (First observed while pushing the multi-ticker-commands change, which never touches `!market`.) Note the VPS IP is already known to be blacklisted/throttled by some providers (see the YouTube IP-blacklist notes), so this can persist for a while, not just seconds.

**Why it matters for this item:** the test is **NOT in `.test-baseline`**, so when it flakes at session-close the gate counts it as a new regression, blocks the push, and the commit sits local-only — exactly the failure mode this item exists to fix. It is the canonical "flaky/known-safe" case #59 needs to tell apart from a real regression.

**Fix options to weigh when this item is worked:**
- Make the test deterministic — mock/stub the yfinance fetch (or seed the temp DB from a fixed OHLCV fixture) so it never depends on a live, rate-limited source. Best long-term fix; removes the flake entirely.
- Or, in the gate's recovery layer, re-run just this failed test once (and/or check for the throttle signature `Not enough closes ... got N, need 220`) before deciding it's a real regression.
- Avoid simply adding it to `.test-baseline` — that permanently exempts a test that normally passes and would hide a genuine future break of `!market`.

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

## Next step for the AI layer — race 3 cheap OpenRouter models (user, 2026-07-08)

**Not started. Do this before writing any AI branch.**

The "AI upgrade" was parked on the wrong premise — that it needed `claude`, which is installed
root-only. **It never needed Claude.** Probed 2026-07-08 as the `openclaw` user (the user the fixer
actually runs as):

| Option | Works as `openclaw`? | Note |
|---|---|---|
| Gemini API key | ✅ live completion | key already in `.env`; free tier; hit one transient 503 |
| Groq API key | ✅ live completion | key already in `.env` |
| OpenRouter key | ✅ live completion (paid, has credit) | `/api/v1/key` authenticates; opens the whole model catalog |
| Codex CLI | ❌ | binary on PATH but auth is root-only (`/root/.codex/auth.json`) — same hurdle as claude |
| Claude CLI | ❌ | `/root/.local/bin/claude`, root-only |

**The task:** pick the **top 3 cheap OpenRouter models**, then run a **quick race** to find which is
both cheap AND actually capable of the job. Cheap alone is worthless if it can't fix a test.

- **The job to race them on** is narrow and checkable, which is what makes a race meaningful:
  given a failing test id + the CI error + the diff, either (a) correctly classify it as
  `undeclared-dependency` / `flaky` / `real-logic-bug`, and (b) for a real logic bug, produce a
  patch that makes the failing test pass **without breaking any test in `.test-baseline`**.
- **Score on:** correct classification rate, patch-passes-the-gate rate, $/attempt, latency. A model
  that is 3× cheaper but escalates everything to a human has not done the job.
- **Selection rule (user, 2026-07-08): paid is fine — cheap AND capable, in that order of constraint.**
  Capability is a **gate**, not a score to trade away: any model that can't clear the bar is out at
  any price. Among those that DO clear it, take the cheapest — "don't spend 50 cents if a capable
  30-cent model exists." Do **not** buy the most capable model on the board; the extra ability is
  wasted on a job this narrow. Free is not a requirement and not a tiebreaker — a free model that
  escalates a real bug costs a human's whole session, which dwarfs the cents saved.
- **Use a real corpus, not toy cases.** The 2026-07-02 pyarrow run is a known-good
  `undeclared-dependency` case; the 2026-07-01 market-command flake (documented above) is a known-good
  `flaky` case. Need at least one real logic-bug case — mine `logs/session_close_*.log` history.
- **Pick a different model family from the one that wrote the code** for the review/fix step, on the
  same "cross-family judge can't rubber-stamp its own work" reasoning as the Wolf verifier (#64).
- **Rate the incumbent too:** the deterministic fixer already handles the common case (a missing
  package) with zero AI. The AI layer only earns its place on the **real-logic-bug** class. Measure
  how often that class actually occurs before spending on it.
- **Don't restrict the field to `:free` slugs.** They churn (`deepseek-chat-v3.1:free` 404'd on
  2026-07-08 — "paid version available now") and they rate-limit under load, which is exactly when a
  red gate needs fixing. Cheap paid models are in scope and probably win. Whatever wins, **pin the
  exact slug** and expect to re-race when it's retired. See [[reference_model_bakeoff_2026-06-15]]
  and `reference_glm_air_free_dead` for prior results.
- **Budget the job, then shop.** The fixer runs only when the gate is red — a handful of times a
  month, one-to-three attempts each. Even a "pricey" cheap model is pennies per month at that volume,
  so the real risk is picking something too weak, not something too dear. Price the candidates against
  that expected volume before ruling any out on cost.

## Open questions

- Is there an existing task_system agent/cron mechanism this could hook into for "wake up, diagnose, fix, retry" automatically? (`/root/task_system/scripts/create_task.sh` + systemd timers is the existing pattern for deferred tasks — worth checking if it fits here.)
- What's an acceptable number of auto-retry attempts before giving up and falling back to manual, so this doesn't turn into an infinite fix-loop?
- How often does a genuine logic bug actually redden the gate? If it's rare, the AI layer may not be worth its complexity — the race should answer this before it's built.

### Session notes — 2026-07-09
- **Decision (user):** AI fixer autonomy = fix + HOLD — it may commit a logic-bug fix locally + notify loudly, but a human pushes; missing-package fixes keep auto-pushing. Race plan: `.omc/plans/active-items-completion-2026-07-09.md` Phase D (includes measuring how often real logic bugs actually redden the gate before wiring anything).
