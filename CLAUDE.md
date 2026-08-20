# CLAUDE.md

## Communication Style

User is not a coder. See global CLAUDE.md for the full rule. Short version: plain language, no jargon (translate it), short sentences, concrete examples, no filler.

## Timezone — PDT only (hard rule)

User's timezone is **PDT (Pacific)**. Never show or mention "ET"/Eastern anywhere (chat, alerts, examples, bot output) — all times in PDT. (internal NYSE logic may stay Eastern but must never surface). New time code → `ZoneInfo("America/Los_Angeles")`, never a fixed offset or `"ET"` label.

## Communication Discipline

The style rules above erode without active enforcement. This section is the operational layer.

### Pre-send check — before any explanation or factual claim

1. **Translate jargon.** Any technical term not translated? Translate it. See table below.
2. **Cold-read test.** Could a non-coder read this without context? If not, rewrite.
3. **No filler.** No "let me break this down," "there are several factors," "let me explain," "in summary." Every sentence must move the explanation forward or be cut.
4. **Concrete example.** Did I use a real example, specific name, path, or number? If not, add one.
5. **Completeness check.** Did I stop at the first plausible cause? Force one more pass — "what else?" — and either name everything I actually know or flag the gap.
6. **One yardstick — consistent framing.** Explaining a scale, ratio, or two-sided thing? Hold one sentence shape across every value, whole numbers only (never "half of X" beside "twice the Y"), with a constant anchor word per line — the reader should never invert, divide, or re-orient. Show the full scale so a single value has context. Answer at the asker's level: no unrequested primer, no pointing at the code. (See `comm-check.md` Section 6.)

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

`comm-check.md` (workspace root) is a **reactive** grading rubric for the rules above — never preload it (`comm-check-fail-*` entries in `MEMORY.md` are NOT a reason to load it). Read it only on: (1) **user pushback on an explanation** — any correction or pointed-out failure mode; find the matching section (1 = jargon, 2 = lazy/incomplete, 3 = verify/probe, 4 = unflagged deferred scope, 5 = whole-feature verification, 6 = inconsistent framing), save a feedback memory entry (template in the file's "When Claude fails a check" section), apply the fix for the rest of the session; (2) **session close** — list any comm-check failures saved this session (open the file then only if you need the failure template).

## Behavior

Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?".

Don't assume you can't access, research, or figure something out — assume you can, and work from there.

## TODO List

When the user says "add X to the to do list" (or "put that on the list", "add this to the todo", "save that as a todo"), asks "what's on the to do list?", references a TODO by number (e.g. "look at #14"), says "resume #N" / "/todo-resume N" / "work on #N" / "pick up #N", or says "pause" / "/todo-pause" / "save progress": read `todo/CONVENTION.md` and follow its instructions.

## Session Close Trigger

When the user sends only "goodbye" or "bye": read `todo/SESSION_CLOSE.md` and follow it exactly, in order (TODO updates → commit → background gate → close summary).

## Start of Build

Run these before writing code, not after (TODO #88 — the checks that judgement, not a script, has to carry):

- Read the actual code before writing a probe or a test. Never from memory.
- Before calling a scheduled feature done, read its real posted output, from a real run, at the real time. A replay of stored data is not proof.
- Run `python3 scripts/when_does_it_run.py` on the changed paths — a market feature scheduled before the market opens is a different feature.
- Run `python3 scripts/check_ownership.py` before committing.

## Definition of Done

A task is not done if an **in-scope** user-facing critical path is broken. In scope = the `[always]` bucket plus every bucket your changed file paths trigger (table in "What to verify" #3). Within those buckets, "pre-existing," "out of scope," "not my regression" are NOT valid exemptions — regardless of who broke it or when. Only three responses when verification surfaces a broken in-scope path:
1. Fix it.
2. Attempt a fix, surface the specific failure, ask whether to keep digging.
3. Get explicit user permission to defer.

A broken check in a bucket your change did NOT touch doesn't block done — but you must report it in one sentence and make sure it lands on the TODO list (reported, never silently dropped). (Scope-aware since 2026-07-12, TODO #5 — before that, one flaky unrelated check could block honest completion of unrelated work.)

### Built switches default to ON

A feature built and tested on stored data is turned ON in the same session, not left OFF "to be safe." Leaving it OFF is a deferral — name the exception. Legitimate exceptions: it is genuinely broken; it needs an API key we don't have; it needs forward-collected data that can't be filled in for the past (e.g. ApeWisdom's 14-day history); or it depends on an unreliable outside source. One more: if it changes live user-facing alerts, a stored-data backtest is necessary but may not be enough — say what live check (shadow log, staged ramp) is still owed before real alerts change.

### What to verify

1. **Test the whole feature you changed**, not just the line you touched. Changed catalyst code inside `!all`? Test all of `!all`.
2. **Find the hidden dependents before committing.** When a change alters a function's arguments or a user-visible output string, `grep -rn` the symbol/old-string across `tests/` and run every match before committing. The breakage usually hides in *other* files — assertions on the old text, or mock/`monkeypatch.setattr` stubs with the old signature — not the file you edited.
3. **Scoped critical-path checks.** Decide which buckets apply from the changed file paths (`git diff --name-only` for the session; an explicit `surfaces:` list in a kickoff file overrides). Run `[always]` plus every triggered bucket:

   | Bucket | Triggered when the diff touches | Checks |
   |---|---|---|
   | `[always]` | anything — every session | `consensus-engine.service` + `openclaw-gateway.service` both `active`; no `❌ GATEWAY drift` and no LLM-health failure alert; `/root/.openclaw` still resolves to `/home/openclaw/.openclaw` |
   | `[discord-commands]` | `consensus_engine/alerts/**`, command routing in `main.py` | the touched command (or `!all <ticker>` if several) returns a coherent reply in Discord |
   | `[agent-mention]` | `_handle_mention` in `main.py`, agent config in `openclaw.json` | `@-mention` of the bot (or `!ask`) returns a coherent reply |
   | `[gateway]` | LLM chains in `openclaw.json` or the `llm:` section of `config/consensus.yaml` | engine boot log shows the gateway/consensus chain drift check passing |
   | `[infra]` | systemd units, `/root/task_system/**`, cron/timer scripts, VPS paths | touched timers/scripts run clean under systemd as `openclaw`; file ownership unchanged |
   | `[ingest]` | `consensus_engine/scanners/**`, `local_video_ingest.py`, ingest parsers | one real poll/ingest of the touched source lands sane rows/log lines |

   Shared files (#4's tripwire list, incl. `config/consensus.yaml`) cut across buckets — touching one triggers every bucket that uses it.
4. **Shared-file tripwire** — if your change touches any of these, test every feature that uses them:
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

Do real-world testing whenever the user-observable outcome can be checked from this environment — before deferring a test, probe what's actually accessible (and check memory) rather than assuming a tool is unavailable. When a real-world test errors: diagnose the real cause → attempt a fix → try alternative paths to the same outcome → only then surface to the user, with what was tried and a specific recommendation. Never ask the user to do something you can do yourself.

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

- After every functional change: commit locally. Do NOT push mid-session — push + regression gate happen only at session close (rules in `todo/SESSION_CLOSE.md`).
- Commit style: imperative (e.g., "Add multi-agent logic").
- Remote: `chopra2007/openclaw--StockTicker-Signals-Discord-Bot` (public).
- Keep `README.md` current with architecture, setup, and features.
