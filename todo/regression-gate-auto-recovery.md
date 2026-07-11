# Fix the regression gate so a failed push doesn't just sit there

**Status:** ACTIVE — **NEXT SESSION: execute the v3 test plan at `.omc/plans/ci-fixer-race-v3-2026-07-10.md`.** It supersedes the ROUND 2 section below (do NOT run round 2 as-is — it inherits the flaws). A 2026-07-10 late-session audit found the round-1/retest races were graded on a flawed exam, so their verdict ("no ≤25¢ model works; kimi 38¢ is the only passer") is unproven: (1) the single benchmark bug is a TEST-file bug (human fix `db47044` edits only `tests/test_wolf_digest.py`) scored as if it were a source bug — deepseek-v4-pro's "fake green" was actually the human's exact fix, and production's own fake-green guard would escalate the CORRECT fix for this case, making it unwinnable by design; (2) the ≥70% bar was applied to single tries, but production `ci_autofix.sh` retries 3× (`AI_ATTEMPTS=3`) — per-incident success is 1-(1-p)³, so the "1/3 failures" (qwen3-max, glm-5) sat AT the bar, not below it; (3) 10 of 30 trials died to harness artifacts (glm-5's whole 0/3 was the 300s deadline — it finished 3/3 times at 600s; plus JSON/search-string rejections with no repair round, no response_format enforcement, uncapped reasoning tokens); (4) field gaps (mimo-v2.5 #2, minimax-m3 #3, step-3.7-flash #9 on the programming leaderboard — never raced) and one impossible entrant (coder-large: 32k context < the ~45k-token prompt). The v3 plan: mine git history for 4-6 genuine source-bug cases (stage via `git checkout <sha>^ -- <src files>` so the reference fix is source-only by construction), harden the harness (JSON enforcement, one repair round, 600s deadline, reasoning caps, provider logging), screen ~22 under-cap models 1 trial/case, deep-run survivors 5 trials/case, score per-incident, pick the cheapest qualifier, confirm at production settings, then pin. Budget ≤$12. Raw so far: `.omc/ci_fixer_trials_raw.json` + `.omc/ci_fixer_trials_timeout_retest.json`.

## ROUND 2 — SUPERSEDED 2026-07-10 by the v3 plan (`.omc/plans/ci-fixer-race-v3-2026-07-10.md`) — do not run as-is

**Why this exists:** round 1 raced a 10-model list copied from an earlier session, not a fresh scan of OpenRouter. When the catalog was actually swept (the user asked "did you test glm-5.2?" — no, I'd tested the older, pricier glm-5), ~27 coding-capable models UNDER the 25¢ cap turned out to be unraced. The important ones are cheaper **cousins of `moonshotai/kimi-k2.7-code`** — the ONLY round-1 model to clear the 70% bar (3/3). If the kimi family (not that one version) is what's good at this job, a cheaper cousin could clear the bar AND fit the cap — solving the whole thing without lifting the budget.

**The round-2 field (all ≤25¢/mo, verified live 2026-07-10, pre-loaded as `CANDIDATES_ROUND2` in `scripts/ci_fixer_trials.py`):**

| model | ~$/mo | why |
|---|---|---|
| `moonshotai/kimi-k2.5` | 11¢ | kimi cousin — best-value shot |
| `moonshotai/kimi-k2` | 17¢ | kimi cousin |
| `moonshotai/kimi-k2.6` | 20¢ | kimi cousin |
| `z-ai/glm-5.2` | 12¢ | newer + cheaper than glm-5 (which went 1/3) |
| `mistralai/devstral-2512` | 12¢ | Mistral coding model (distinct from codestral, 0/3) |
| `kwaipilot/kat-coder-pro-v2` | 9¢ | dedicated coder |
| `arcee-ai/coder-large` | 14¢ | dedicated coder |

**Exact command (pre-create worktrees serially first to dodge the git-lock race, as in round 1):**
```
cd /home/openclaw/.openclaw/workspace
sudo -u openclaw python3 -c "import sys; sys.path.insert(0,'scripts'); import ci_fixer_trials as t
for s,_,_,_ in t.CANDIDATES_ROUND2: print('ready:', t.make_worktree(s).name)"
sudo -u openclaw python3 scripts/ci_fixer_trials.py --trials 3 --workers 7 \
  --models moonshotai/kimi-k2.5 moonshotai/kimi-k2 moonshotai/kimi-k2.6 \
  z-ai/glm-5.2 mistralai/devstral-2512 kwaipilot/kat-coder-pro-v2 arcee-ai/coder-large \
  --out .omc/ci_fixer_trials_round2.json
```
Scoring reminder: only `passes_source_only` counts (a test-only edit is a FAKE green). Bar ≥70% = need ≥3/3 clean here (or run 10 trials on any that look promising). **Decision after round 2:** if a model clears ≥70% AND is under 25¢ → pin the cheapest such (update `scripts/ci_ai_fixer.py` `DEFAULT_MODEL` + `reference_ci_fixer_model.md`), done. If NONE do → the A/B fork below is the real decision.

_Round-2 candidate catalog also had (under cap, lower priority — qwen/deepseek families already went ~0/3 in round 1): qwen3.6-plus ~10¢, qwen3.5-397b ~12¢, kimi-k2-thinking ~18¢, kimi-k2.5 already listed, deepseek-v3.2-exp ~8¢. Add if round 2's shortlist comes up empty._
**Created:** 2026-07-01

## RACE RESULT — 2026-07-10 (10-model strong field, 3 trials each, production-audited scoring)

Ran the confirmed ≤25¢ field, workers=10, `--trials 3 --max-tokens 16000 --deadline 300`. **Cost below is MEASURED per attempt × 6 runs/mo — the real number, which for reasoning models runs well above the pre-race sticker estimate.** Production caps output at `MAX_TOKENS=8000` (half the race's 16k), so the winner still needs a production-settings re-verify.

| model | fixed (real source) | $/mo measured | vs 25¢ cap | note |
|---|---|---|---|---|
| `moonshotai/kimi-k2.7-code` | **3 / 3** | ~38¢ | **OVER** | only model that cleared the bar; burned ~9k output tokens reasoning — may truncate at production 8k |
| `qwen/qwen3-max` | 1 / 3 | ~21¢ | under | fails 70% bar |
| `qwen/qwen3-coder-plus` | 0 / 3 | ~11¢ | under | one trial emitted unparseable JSON |
| `deepseek/deepseek-v3.1-terminus` | 0 / 3 | ~8¢ | under | |
| `deepseek/deepseek-v3.2` | 0 / 3 | ~6¢ | under | |
| `mistralai/codestral-2508` | 0 / 3 | ~6¢ | under | one trial bad edit-format |
| `qwen/qwen3-coder-flash` | 0 / 3 | ~5¢ | under | |
| `deepseek/deepseek-v4-pro` | 0 / 3 | ~5¢ | under | its lone "pass" was a FAKE green (test-only edit); other 2 timed out / truncated — consistent with prior 1/5 skepticism |
| `z-ai/glm-5` | no verdict | — | — | timed out all 3 at 300s (no reply) |
| `qwen/qwen3.7-plus` | no verdict | — | — | timed out all 3 at 300s (no reply) |

**Read:** the job IS solvable cheaply-ish by one model (kimi, 3/3) — but kimi is over the 25¢ cap at measured cost, and every model that stayed under the cap failed the 70% bar (best under-cap = qwen3-max at 1/3). Two cheaper models (`glm-5` ~17¢, `qwen3.7-plus` ~9¢) never answered inside 300s, so they had NO verdict — retested below.

### Timed-out retest — 2026-07-10 (glm-5 + qwen3.7-plus, deadline raised 300→600s, `.omc/ci_fixer_trials_timeout_retest.json`)

| model | fixed (real source) | note |
|---|---|---|
| `qwen/qwen3.7-plus` | 1 / 3 | 2 of 3 STILL timed out even at 600s (never finished generating); the one that finished (84s) fixed it correctly. Too slow/hangs to be a gate fixer. |
| `z-ai/glm-5` | 1 / 3 | finished all 3 this time (no timeouts), but 2 of 3 produced malformed edits (pointed at text not in the file). Fast enough, unreliable at valid patches. |

**VERDICT — no ≤25¢ model is reliable.** kimi (3/3, ~38¢/mo) is the ONLY model that clears the 70% bar, and it's over the cap. Under the cap it's a three-way tie at 1/3 (qwen3-max, qwen3.7-plus, glm-5) — all 33%, all fail. Deeper trials on them aren't worth it: qwen3.7-plus can't finish in time, glm-5 can't emit valid patches. This is the goal-2 contingency exactly. **Decision now a true fork:** (A) lift cap to ~40¢ so kimi qualifies — but kimi needs a production-settings confirm run first (it passed only with 16k token room; production caps at 8k and kimi burned ~9k reasoning, so it may truncate/fail at 8k), then 10 trials to confirm ≥70%; or (B) keep the 25¢ cap and keep escalating logic bugs to a human (today's safe default) — auto-fixer stays limited to the mechanical missing-package case. Pending user pick.

---

## REOPENED 2026-07-10 — the model choice is wrong; redo the race

**What still stands (do not touch):** detection + safety net (Part 1), and the deterministic missing-package auto-fixer (Part 2). Those are done and correct.

**What's wrong:** the AI logic-bug fixer is pinned to `qwen/qwen3-coder-next` at 1-in-5, and that number comes from a **badly chosen field.** I raced mostly cheap/fast/small models — the same "default to cheap" mistake the user has now corrected three times in this task. The user's rule (2026-07-08, in this file): **capability is a GATE, cost is not the constraint.** 10c/month is fine; every strong coding model is under 40c/month.

**Full 10-model race, 2026-07-10 (audited harness — each patch verified by running the test; a "pass" now requires a SOURCE fix, not a test edit):**

| model | passes | notes |
|---|---|---|
| `codex/gpt-5.5` (via logged-in Codex CLI, $0 on the $20 Plus plan) | **5 / 5** — all real source fixes, 18s each | the only model that cleared the bar |
| `deepseek/deepseek-v4-pro` | 1 / 5 (pre-audit; rerun killed at session close) | the strongest OpenRouter model I bothered to include; a signal I under-weighted |
| everything else (gpt-oss-120b, glm-4.7-flash, qwen3-coder-30b, qwen3-235b, deepseek-v4-flash, qwen3-coder-next, qwen3-coder, gemini-2.5-flash) | 0 / 5 | a weak/fast field — of course they failed |

So the race did NOT prove "only Codex can do this." It proved "one frontier model beats a bench of flash/mini models," which is meaningless. **The open question is untested: among the STRONG coding models, how many clear 70%, and which is cheapest?**

**NEXT STEPS (in order):**
1. **Redo the race with the ≤25¢/month strong-coding field** (see goal 5 below for the list + the exclusions), 5 tries each, then 10 tries on survivors, target ≥70% source-only pass. Exclude `anthropic/*` (cross-family), `google/gemini-3.1-pro` (user), **and Codex** (control only — see below). Harness ready: `scripts/ci_fixer_trials.py` (`--models`, `--trials`). **Get the user to confirm the field before launching** (the AskUserQuestion was pending at close).
2. **Pick the cheapest per-token model that clears ≥70%.** If NONE of the ≤25¢ models clear 70%, that's a real result — surface it and ask the user whether to lift the 25¢ cap or keep escalating logic bugs to a human (today's safe default). Codex proved the job is doable; it does NOT get wired in.
3. **Re-pin** the winner in `scripts/ci_ai_fixer.py` `DEFAULT_MODEL` and update `reference_ci_fixer_model.md`.

**Two on-disk fixes from this session — UNSTAGED, keep them (both real production bugs):**
- `scripts/ci_ai_fixer.py` — **streaming fallback** (`_call_unstreamed`). OpenRouter load-balances providers per call; some deliver a reasoning model's answer in a way the SSE `delta.content` path never sees → silent "empty reply." Would have unfairly failed EVERY reasoning model. Falls back to a non-streaming call inside the remaining deadline; also flags `finish_reason=length` truncation (that's how `glm-4.7-flash` was caught burning 16k tokens on hidden reasoning).
- `/root/task_system/scripts/ci_autofix.sh` (not repo-tracked) — **fake-green guard** (user-approved 2026-07-10). A patch that makes a red test green by editing ONLY `tests/` is a fake green (it may have weakened the assertion). `tests/` isn't a forbidden path (a test asserting a changed output string is a legit fix), so it can't be banned outright — instead a test-only patch now posts its diff to `#errors` and escalates, never commits. Source-touching patches commit as before. **Note the benchmark bug this exposed:** the one real-logic-bug case's reference fix (`db47044`) edits the TEST file — so scoring "any passing patch" would reward the exact fake-green behavior production must forbid. The harness now scores source-only.
- `scripts/ci_fixer_trials.py` — the audited multi-trial race harness (new). Also `.omc/trials/*.json` raw results (gitignored).

**Harness lessons re-confirmed (third time in this task):** (a) all-candidates-fail → suspect the harness, not the models (the streaming bug); (b) nondeterministic at temp 0 → never trust a single sample (qwen was 1/5 then 0/5 on rerun); (c) I keep defaulting to cheap when told capability is the gate.

---

_Historical (2026-07-09 — SUPERSEDED by the reopen above; the qwen pin is wrong):_

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

**Two more goals for the AI-fixer part of #1 (user, stated across 2026-07-08 → 2026-07-10):**
4. **Compare candidate models head-to-head to find the best success rate** — actually race them on a real failing test and measure, don't pick one and hope. **Bar: a model must hit ≥70% success to qualify** (user, 2026-07-10).
5. **Hard cost cap: ≤ 25 cents / month** (user, 2026-07-10 — revised up from 10¢ the same day). Real ceiling, not a comfort level.

**CODEX IS NOT A PRODUCTION CANDIDATE (user, 2026-07-10, explicit).** The Codex subscription was used ONLY as a *control* — to prove a capable model can go 5/5, i.e. that the task is solvable and ≥70% is achievable, so the hunt for a cheap model is worth continuing. Codex has done that one job and is **retired from the running.** Do NOT propose wiring Codex / `codex exec` into production. The deliverable is a **pay-per-token model** that clears goal 4 AND goal 5.

**The redo-race field (strong coding models that FIT under 25¢/month, ~6 runs/mo) — re-bucketed 2026-07-10 when the cap rose from 10¢ to 25¢:**
- `deepseek/deepseek-v3.2` ~6¢ · `qwen/qwen3-coder-flash` ~6¢ · `deepseek/deepseek-v3.1-terminus` ~8¢ · `mistralai/codestral-2508` ~9¢ · `qwen/qwen3.7-plus` ~9¢ · `deepseek-v4-pro` ~12¢ · `glm-5` ~17¢ · `qwen3-coder-plus` ~19¢ · `kimi-k2.7-code` ~22¢ · `qwen3-max` ~23¢ (add any other strong coder priced ≤ ~$0.042/attempt). The five 12–23¢ models were excluded under the old 10¢ cap and now qualify. **Caveat on `deepseek-v4-pro`:** it is the ONLY model in this list already tested, and it scored **1/5 (20%)** — far below the 70% bar. That run was pre-audit AND before the streaming-fallback fix (which was unfairly failing reasoning models), so a fair retest could be higher, but do NOT treat it as a favourite — a 1/5 model rarely jumps to passing. Retest it once with the fixed harness; deprioritize if it doesn't clearly improve.
- **OVER the wall — excluded:** `gpt-5.1-codex` ~34¢, `grok-4.3` ~35¢.
- The "under 40c/month" framing in the REOPENED notes above is WRONG against this cap; this ≤25¢ list supersedes it.
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
