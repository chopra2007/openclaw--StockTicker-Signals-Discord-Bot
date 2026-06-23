# CLAUDE.md

## Communication Style

User is not a coder. See global CLAUDE.md for the full rule. Short version: plain language, no jargon (translate it), short sentences, concrete examples, no filler.

## Communication Discipline

The style rules above erode without active enforcement. This section is the operational layer.

### Pre-send check — before any explanation or factual claim

1. **Translate jargon.** Any technical term not translated? Translate it. See table below.
2. **Cold-read test.** Could a non-coder read this without context? If not, rewrite.
3. **No filler.** No "let me break this down," "there are several factors," "let me explain," "in summary." Every sentence must move the explanation forward or be cut.
4. **Concrete example.** Did I use a real example, specific name, path, or number? If not, add one.
5. **Completeness check.** Did I stop at the first plausible cause? Force one more pass — "what else?" — and either name everything I actually know or flag the gap.

### Verification ladder — before claiming a fact about code, config, files, or paths

1. **Already loaded?** Direct evidence already in this conversation's context? Quote it. No new tool call needed.
2. **Smallest probe first.** `grep -n "thing" path` → targeted Read (20–50 lines around the match) → full Read only when file is small (<200 lines) or question is structural.
3. **Parallel for breadth.** Multiple files → parallel greps or Explore agent, not sequential full Reads.

Never describe behavior from memory or pattern-match alone. Verify, or say "I don't know."

### Jargon → plain English

| Project term | Say this instead |
|---|---|
| evidence span | the quoted sentence from a transcript |
| signal row | a saved record that a source mentioned a ticker |
| parser | the program that reads input and pulls out structured pieces |
| aggregator | the controller for the `!all` command — gathers data from every source in parallel |
| narrator | the part that turns gathered data into readable summary text, using AI calls |
| backfill | filling in missing data on old records |
| schema | the shape of records in a database table |
| endpoint | the address where a service answers requests |
| service | a long-running background program managed by the system |
| gateway | (a) Discord Gateway — the live connection that lets the bot receive messages. (b) openclaw-gateway — local background service (port 18789). |
| hook | a script the system runs automatically at certain moments (e.g. before a git push) |
| cron / cron job | a scheduled task |
| poll cycle | one round where the engine checks all its configured sources once |
| regression | a thing that used to work and now doesn't |
| baseline | the snapshot of which tests were already failing before this work |
| rate limit / 429 | a cap on how often you can call an API; 429 = "too many requests" |
| OHLCV | daily price data: open, high, low, close, volume |
| Form 4 | SEC filing showing insider trading |
| 8-K | SEC filing for major company events |
| LLM | the AI model that writes alert text |
| captions / transcript | the text version of a video's audio |
| commit | a saved change to the codebase |
| PR / pull request | a proposal to merge code |

Add new terms only after verifying their meaning from actual code, not from a filename.

### Cross-session test (`comm-check.md`)

The test file at `comm-check.md` (workspace root) is the grading rubric. Open it automatically on:

1. **User pushback on an explanation** — any correction, contradiction, or pointing-out of a failure mode ("you used jargon," "you assumed," "you didn't check," "again you," "you're being lazy"). Read `comm-check.md`, find the section that maps to the failure (Section 1 = jargon, Section 2 = lazy/incomplete, Section 3 = verify/probe), save a feedback memory entry (template in the file's "When Claude fails a check" section), apply the fix to the next answer and the rest of the session.
2. **Session start with prior failures** — if `MEMORY.md` lists any `comm-check-fail-*` entries, read `comm-check.md` before the first explanation.
3. **Session close** — list any comm-check failures saved this session in the close summary.

The trigger is the user's natural pushback, not a special command.

## Behavior

Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?".

Don't assume you can't access, research, or figure something out — assume you can, and work from there.

## TODO List

When the user says "add X to the to do list" (or "put that on the list", "add this to the todo", "save that as a todo"), asks "what's on the to do list?", references a TODO by number (e.g. "look at #14"), says "resume #N" / "/todo-resume N" / "work on #N" / "pick up #N", or says "pause" / "/todo-pause" / "save progress": read `todo/CONVENTION.md` and follow its instructions.

## Session Close Trigger

When the user sends only "goodbye" or "bye":
1. **If any item on the TODO list was worked on this session, update it first** (per `todo/CONVENTION.md`): mark finished items `— DONE YYYY-MM-DD` in `TODO.md` and the detail file's `**Status:**`, and/or append a dated session-notes block to the detail file capturing what changed. Skip this step only if no TODO item was touched this session.
2. `git status` — commit any uncommitted changes (do **not** push here — step 3's script does the push, automatically choosing the doc-only `--no-verify` path or the full test gate based on whether code changed)
3. Run `nohup /root/task_system/scripts/session_close.sh > /root/task_system/logs/session_close_latest.log 2>&1 &` to kick off the gate + push in the background
4. Tell the user: "Gate running in background — safe to close. ci-monitor will catch any CI failures."
5. Verify MEMORY.md is up to date
6. List any `comm-check-fail-*` entries saved this session

## Definition of Done

A task is not done if a user-facing critical path is broken — regardless of who broke it, when, or whether it's "in scope". "Pre-existing," "out of scope," "not my regression" are NOT valid exemptions. Only three responses when verification surfaces a broken path:
1. Fix it.
2. Attempt a fix, surface the specific failure, ask whether to keep digging.
3. Get explicit user permission to defer.

### Built switches default to ON

A feature built and tested on stored data is turned ON in the same session, not left OFF "to be safe." Leaving it OFF is a deferral — name the exception. Legitimate exceptions: it is genuinely broken; it needs an API key we don't have; it needs forward-collected data that can't be filled in for the past (e.g. ApeWisdom's 14-day history); or it depends on an unreliable outside source. One more: if it changes live user-facing alerts, a stored-data backtest is necessary but may not be enough — say what live check (shadow log, staged ramp) is still owed before real alerts change.

### What to verify

1. **Test the whole feature you changed**, not just the line you touched. Changed catalyst code inside `!all`? Test all of `!all`.
2. **Always-on checks — every time:**
   - `consensus-engine.service` and `openclaw-gateway.service` both `active`.
   - No `❌ GATEWAY drift` alert and no LLM-health failure alert.
   - `/root/.openclaw` still resolves to `/home/openclaw/.openclaw` (symlink intact).
3. **Shared-file tripwire** — if your change touches any of these, test every feature that uses them:
   - `consensus_engine/llm_client.py`
   - `consensus_engine/config.py` + `config/consensus.yaml`
   - `consensus_engine/db.py`
   - `consensus_engine/alerts/all_command/narrator.py`
   - `consensus_engine/alerts/all_command/aggregator.py`

### Evidence standard

Never claim complete on "service started," "code looks right," or "unit tests pass" alone.
1. Name the user-observable claim precisely ("the bot responds to `!help`", not "gateway is connected").
2. Trace the full path from input to output.
3. Show the actual output.
4. Test each distinct claim separately (commands and mentions are different code paths).
5. Verify after every restart, not before.
6. Before asserting what a function, flag, or config key does — grep or read the actual code. Never from memory.
7. Judge output against the goal, not the code against the spec. A feature that runs but produces generic or unhelpful output has not met its goal. Compare the real output to why the feature was built.

For multi-phase execution (discover, ralph, autopilot): run at least one real end-to-end invocation and inspect the actual output before declaring done.

## Regression Gate

Before feature work — especially a `discover` run or any multi-commit change — establish a test baseline.

1. **Baseline** = list of known-failing test IDs in `.test-baseline` (repo root, committed). Refresh with `make test-baseline`.
2. **No commit may make a passing test fail.** Any test failing now but absent from `.test-baseline` is a regression — fix before committing.
3. **Set matters, not count.** Fix one, break another = still a regression even if the count is unchanged.
4. **Separate verifier.** At end of feature work, a separate agent (not the one that wrote the code) re-runs the full suite and diffs the baseline.

Pre-push hook (`scripts/pre-push`) enforces this mechanically. Bypass only with `git push --no-verify` for genuine exceptions.

## Alert Philosophy

**Core:** Quality over quantity. Actionable intelligence. 2+ independent sources before alerting (with exceptions).

**Instant-trigger exceptions** (no second source needed): large options activity, insider trading, unusual flow, technical breakout with levels, quant/factor signals.

**SEC Filing Rules:**
- 8-K filings NEVER trigger standalone alerts.
- Form 4 stored for cross-ref, adds +15 points to scoring.
- All SEC data feeds LLM thesis generation only.

**Alert Format:** Ticker + Direction → Primary catalyst → Analyst opinion → Supporting data → Confidence score → LLM thesis (1-paragraph)

## Commands

```bash
python3 -m consensus_engine          # full engine
python3 -m consensus_engine --once   # single poll cycle
python3 -m consensus_engine --dry-run --once  # no Discord, logs only
python3 -m consensus_engine --status # health report
python3 -m pytest tests/ -v          # test suite
docker compose up -d                 # SearXNG (8888)
```

## Real-World Testing

Don't stop at code-functional. Do real-world testing whenever the user-observable outcome can be checked from this environment. "Unit tests pass" or "service started" does NOT discharge the verification standard if end-to-end behavior can be probed. Before deferring a test, actively check memory and probe what's accessible in the environment rather than assuming a tool is unavailable.

When real-world tests hit errors, follow this ladder before asking the user:
1. **Diagnose** — error strings often mask the real cause (a 429 may be IP-wide; "cookies invalid" may be downstream).
2. **Attempt to fix** — change request parameters, swap auth modes, retry with backoff, different endpoint.
3. **Explore alternative paths** — same outcome via different mechanism (yt-dlp dead → try `youtube_transcript_api`; provider down → try another).
4. **Only then surface to the user** — with what failed, what you tried, why each alternative did or didn't work, and a specific recommendation.

Don't ask the user to do something you can do yourself. Asking is acceptable only when the next step genuinely requires their access, their decision, or information not derivable from logs/code/docs.

## Key Design Decisions

- **Signal-first**: tweet → instant alert → async cross-reference. No gates block the alert.
- **Finnhub free tier**: real-time quotes only (`/quote`). Historical OHLCV via yfinance in `ThreadPoolExecutor` (blocking).
- **Config**: all thresholds/keys in `config/consensus.yaml` via `config.get("dot.path", default)`. YouTube channels: `/root/.openclaw/sources.json`. API keys live in **two** files — `/root/.openclaw/.env` **and** `/root/.openclaw/.env.service` (the engine service reads `.env.service` and won't start without it). A new key must be added to **both**.
- **playwright-stealth**: `from playwright_stealth import Stealth` → `Stealth().apply_stealth_async(page)` — NOT `stealth_async()`.
- Tests: `pytest.ini` `asyncio_mode = auto`.

## Deferred Task System

When a task must run in the future: create with `/root/task_system/scripts/create_task.sh`, use systemd timers, include retries + logging + cleanup. Never leave future tasks unscheduled.

At session start: check `/root/task_system/notifications.log`. If it has entries, summarize them clearly then clear the file. If empty, do nothing.

## GitHub & Documentation Automation

- After every functional change: commit locally. Do NOT push mid-session.
- Push and regression gate testing happen only at session close (the "bye"/"goodbye" trigger).
- **Doc-only commits** (only `*.md`, `todo/**`, `TODO.md`, comments changed) push with `git push --no-verify` at close — no test gate needed. **Code changes** (anything under `consensus_engine/`, `scripts/*.py`, `tests/`, config) must go through the full gate (`scripts/pre-push`, `pytest -n 2`) before pushing at close — never `--no-verify` those.
- Commit style: imperative (e.g., "Add multi-agent logic").
- Remote: `chopra2007/openclaw--StockTicker-Signals-Discord-Bot` (public).
- Keep `README.md` current with architecture, setup, and features.
