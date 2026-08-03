# Agent tool-loop context blow-up (runaway token accumulation on heavy questions)

**Status:** ACTIVE 2026-08-03 — the watchdog built for this item was killing the whole
server; that is fixed. The loop guard itself is still not built.
**Created:** 2026-06-16

**CURRENT STATUS (2026-08-03):** The watchdog's `kill_run()` would call
`os.killpg(1, SIGKILL)` whenever a test handed it a fake process — which Linux reads as
"kill every process this user owns", i.e. Claude, SSH, tmux, the bot and Docker.
**Fixed and verified this session** (full suite 3084 passed / 0 failed in an isolated
PID namespace, zero new kill records), and the Stop hook that kept re-running the test
that reaches it can no longer run tests as root, stack two suites, or instantly retry.
**Caveat:** the audit log does not actually show this firing — the records that looked
like proof were failed Codex kills, not Python (details below). The defect was real and
is disarmed; the true cause of the 2026-08-03 crashes remains unproven. See the
2026-08-03 section below. **The underlying loop guard — steps 1-4 of "Next steps" — is
still not built**, and the Stop hook is currently DISABLED pending the owner restoring
it (command in the session summary).

What closed this item in June was the workaround from #44: make gpt-4.1-nano the agent
lead, because in the bake-off it converged in 11-13s and used 2k-21k tokens/turn. The
file itself flagged that as insufficient — *"This item is to fix the underlying loop, so
a future model swap doesn't silently reintroduce timeouts."* It was then marked DONE
anyway during the #72 status backfill. **No model swap was even needed for it to come
back.**

### The 2026-07-21 recurrence
The user asked about the `#errors` channel. Their message contained `<#1521022584072831057>`,
which the agent read as a *message* id it should fetch. It could not, so it fell back to
the `chat_memory_rollups` query the steering prompt recommends — and ran **that identical
query 39 times**, same arguments, same stale result each time, until `timedOutByRunBudget`
killed the run at 120s. The retry reused the same session, inherited the loop transcript,
and did it again: 117k -> 336k prompt tokens. The user got
"⚠️ Agent unavailable after 2 attempts" — the exact string this item exists to prevent.

So the June conclusion was wrong in two ways:
1. It is **not purely model-dependent**. A lean, fast, "converging" model loops just as
   hard when the loop is driven by a question it cannot resolve rather than by verbose
   tool output.
2. The trigger was not a "heavy question" at all. It was one unresolvable reference.

### What was fixed 2026-07-21 (committed, tested — blast radius only)
These stop the loop from reaching the user; they do not stop the loop itself.
- **Trigger removed:** `<#id>` is rewritten to `#name` before the prompt is built, and a
  named room's real messages are injected (`consensus_engine/tools/read_channel.py`), so
  the unresolvable-reference case that started this no longer exists.
- **Retry can no longer inherit a loop:** every retry uses a wiped scratch session AND the
  next model down the chain. Cheap failures walk the chain; timed-out runs stop at 2.
- **Session growth capped:** the live transcript is rolled past 400KB (it had been
  accumulating since 2026-06-15 — that bloat is what made the prompts 117k/336k).
- **Prompt-level stop rule** on the exact query that looped ("run at most once per
  question; re-running cannot return anything new") — advisory, not a guarantee.
- Tests: `tests/test_handle_mention.py` (retry-differs, session-roll, channel expansion).

### What is still NOT fixed (the actual item)
There is still **no mechanical cap on repeated identical tool calls** and no max-tool-round
guard. Nothing stops a model from calling the same command 39 times; we only survive it
better. The guard belongs in the openclaw agent runtime, which is an npm package — patches
there are lost on reinstall ([[reference_plugin_cache_wiped]] pattern), so it needs either
an upstream change or a wrapper-level detector.

Wrapper-level option worth costing: parse the live trajectory file mid-run and kill the
subprocess when the same (tool, args) pair repeats N times. Everything needed is already
on disk — `/home/openclaw/.openclaw/agents/main/sessions/<id>.trajectory.jsonl` recorded
all 39 calls with identical `input.command`.

## The problem
When the `@`-mention / `!ask` agent answers a heavy, tool-triggering question (e.g. "give me a
read on NVDA today"), some models keep calling tools and re-feeding the results until the
accumulated context explodes — then the whole turn times out and the user gets
"⚠️ Agent unavailable".

Measured live on 2026-06-16 (real `openclaw agent --local` path, `.omc/research/model-bakeoff-2026-06-15/agent_matrix_out/`):
- **gpt-oss-120b**: 233k–325k cumulative tokens/turn → timed out or returned empty on 5/5 heavy questions, even at the 240s production limit.
- **qwen3-235b-2507**: 173k–687k tokens/turn (worst: 976k on one NVDA run) → converged but slow/expensive.
- **gpt-4.1-nano**: 2k–21k tokens/turn → converged in 11–13s. **mistral-small**: 1.5k–84k → converged in 12–14s.

So it is strongly **model-dependent**: lean models terminate the tool loop quickly; others loop and balloon. We already worked around it by making **gpt-4.1-nano the agent lead** (TODO #44) — the bot works now. This item is to fix the **underlying loop**, so a future model swap doesn't silently reintroduce timeouts.

## Suspected root cause (unverified)
The agent re-sends growing tool-result context each round and either (a) the web/news tools return
very large bodies that aren't trimmed before being fed back, and/or (b) there's no hard cap on
tool-call rounds / cumulative context, so a verbose model never converges. The 976k-token figure
on a single NVDA question points at un-trimmed tool results more than model choice alone.

## Next steps (priority-ordered)
1. **Instrument one heavy run** — re-run "read on NVDA" with gpt-oss-120b via `--model` (temp
   allow-map add, revert after — see the ownership trap notes) and capture the trajectory
   (`/home/openclaw/.openclaw/agents/main/sessions/<id>.jsonl`) to see how many tool rounds fire and
   how big each tool result is.
2. **Check for a tool-result size cap** in the openclaw agent config / tool definitions — if web
   search returns full pages, truncate tool results before they re-enter context.
3. **Check for a max-tool-rounds / max-context guard** in the agent loop; add one if absent.
4. Re-test the heavy questions across models afterward — goal: even token-hungry models converge.

## Files / where to pick up cold
- Real-path harness + raw outputs: `.omc/research/model-bakeoff-2026-06-15/agent_matrix.sh`, `agent_matrix_out/`.
- Mention handler (the subprocess + timeout): `consensus_engine/main.py:600` (`_handle_mention`), `--timeout 240`.
- Agent chain config: `config/consensus.yaml` `llm.agent_model` / `agent_fallback_models`; mirrored to openclaw.json by `scripts/sync_gateway_models.py`.
- Full bake-off context: `todo/model-bakeoff-2026-06-15.md` (TODO #44).

## 2026-08-03 — the watchdog's kill was killing the whole server

The loop guard shipped for this item (`consensus_engine/tools/agent_watchdog.py`,
commit `9fe9979`) had a fatal flaw in `kill_run()`. It called
`os.getpgid(proc.pid)` and then `os.killpg(pgid, SIGKILL)` with no check on what
`proc.pid` actually was.

`tests/test_handle_mention.py::test_handle_mention_timeouts_stop_at_the_timeout_budget`
drives that path with a `MagicMock` subprocess. A `MagicMock` attribute converts to
integer **1**, so the call became `os.killpg(1, SIGKILL)` — which Linux turns into
`kill(-1, 9)`, "kill every process this user owns". Run as root that kills Claude,
tmux, SSH, the bot, Docker and the logging services. Proven live this session:
replaying the old logic with a `MagicMock` reaches `killpg(1, SIGKILL)`.

**Evidence caveat — the audit log does NOT corroborate this firing.** The handoff
claimed kernel records on 2026-07-25 and 2026-08-03 showed Python issuing
`syscall=62 a0=ffffffff a1=9`. Checked directly: across every retained audit log
(they only reach back to 05:14 on 2026-08-03) there is exactly **one** successful
python3 `kill(-1, 9)` — the deliberate containment probe run during this session at
14:32:52. The 50 records between 13:05 and 14:18 that first looked like a match are
`comm="tokio-rt-worker"` from the **Codex CLI** binary, and every one returned
`success=no`, so they killed nothing. The engine's 14:18 restart was a clean systemd
`Stopped`→`Started`, not a kill. The audit rule does cover all processes
(`-S kill,tkill,tgkill -k openclaw_signal`) and it captured the probe, so it would
have captured a real watchdog kill. **Conclusion: the defect was a real loaded gun
and is now disarmed, but what actually crashed the box in that window is unproven.**

Separately worth watching: the Codex binary attempted `kill(-1, 9)` **58 times**
today, all failing. If it ever succeeds it does exactly the same damage.

The `verify-on-done.py` Stop hook was the delivery mechanism: it re-runs affected
tests whenever Claude finishes a message, so it reached the deadly test over and over
with no human in the loop.

**Fixed.** `kill_run()` now reads `proc.pid` once and group-kills only when every
check passes: `type(pid) is int` (not `isinstance` — `True` is integer 1), `pid > 1`,
`pgid > 1`, `pgid == pid` (proving the child leads its own group as
`start_new_session=True` promises), and `pgid != os.getpgrp()`. Anything else falls
back to `proc.kill()` on the single process. An already-exited run stays a quiet no-op.

Verified: 11 focused `kill_run` tests (every signal call mocked — no test sends a real
signal), covering `MagicMock().pid`, `None`, `True`, `0`, `1`, a missing `pid`
attribute, a child sharing our group, `pgid != pid`, and group-lookup failure, plus a
positive test that a real `pid == pgid > 1` produces exactly one group kill.
`tests/test_handle_mention.py` 23/23 and the full suite **3084 passed, 1 skipped, 0
failed** — both inside a PID namespace as non-root. Zero new `kill(-1, 9)` audit
records during either run; all services stayed up.

Hardening in `/root/.claude/hooks/verify-on-done.py`: it now refuses to run tests as
root (drops to `openclaw` via `setpriv`, or skips the run entirely if no unprivileged
account exists), takes a non-blocking `flock` so two suites can never stack, and
refuses to start within 60s of a previous start so an interrupted run cannot retry
into a loop. Scratch dirs are per-user. Proven: the hook's basetemp is now
`openclaw`-owned where the old one was `root`-owned.

**Still open on this item:** the underlying loop guard, "Next steps" 1-4 below, is
unchanged. This session fixed the watchdog's kill, not the loop it was built to catch.

## Caveat
n=1 question class (NVDA-style heavy reads, run repeatedly). Confirm it generalizes (it did across
qA/qB/qC in the matrix — all three heavy questions blew up gpt-oss-120b). Ownership trap: running
`openclaw` as root flips openclaw.json to root:root → breaks the openclaw-run gateway on next
restart. Always run as `sudo -u openclaw` and chown back.
