# Project Rules for Coding Agents

This is the main rules file for coding agents working in this repo.

The root `AGENTS.md` is also read by the live Discord bot. Do not use it as a coding-agent identity file. Use this file for coding work.

## Plain Language

The owner is not a coder.

- Use short sentences.
- Use plain words.
- If a technical word is needed, explain it in the same sentence.
- Use a real file name, command, or number when that makes the answer clearer.
- Cut filler like "in summary" and "there are several factors."
- Do not point at code and call that an answer.
- Before sending an explanation, ask one more time: what else could be true?

Plain-word examples:

- "parser" means the program that reads input and pulls out structured pieces.
- "aggregator" means the controller for the `!all` command. It gathers data from every source at once.
- "narrator" means the part that turns gathered data into readable alert text using AI.
- "schema" means the shape of records in a database table.
- "service" means a long-running background program managed by the system.
- "hook" means a script the system runs automatically at a certain moment.
- "regression" means a thing that used to work and now does not.
- "baseline" means the list of tests that were already failing before this work.
- "429" means an outside service said "too many requests."
- "LLM" means the AI model that writes alert text.
- "commit" means a saved change to the codebase.

Add a new plain-word example only after checking the code or docs.

## Pacific Time Only

Anything the owner can see must use Pacific time.

- Chat replies, alerts, examples, logs shown to the owner, and docs must not show another time-zone label.
- New time code must use `ZoneInfo("America/Los_Angeles")`.
- Do not use a fixed offset. The offset changes during the year.
- Internal stock-market math may use whatever the exchange needs, but that label must not be shown to the owner.

## Working Style

- Keep going without asking permission first. Do not ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?". Just do the work and report what happened.
- Stop only for something the owner alone can decide: destroying data, a real change of scope, or missing access you cannot get yourself.
- Do not assume something is out of reach. Assume you can access, research, or work it out, and start from there. Check what is actually available before saying a tool or path is unavailable.
- Make the smallest change that solves the stated problem. Do not tidy nearby code, rename things, or add flexibility nobody asked for.
- If a simpler approach exists, say so before building the complicated one.

## Verify Before Claiming

Never describe code, config, files, or paths from memory alone.

Use the smallest check that proves the point:

1. If the proof is already loaded in this conversation, quote or name it.
2. If not, search the exact text or symbol first.
3. Read 20 to 50 lines around the match.
4. Read a whole file only when the file is small or the question is about the whole file.
5. When several files matter, search or read them in parallel.

If a claim cannot be checked, say so plainly.

## Definition Of Done

A task is not done if an in-scope user-facing path is broken.

In scope means:

- The always-checks.
- Every check bucket touched by the changed files.
- Every hidden dependent found by searching for changed function names or changed output text.

When an in-scope check is broken, choose one of these:

1. Fix it.
2. Try to fix it, then report the exact failure and what was tried.
3. Get clear user permission to defer it.

"It was already broken" does not excuse an in-scope broken path.

A broken check outside the changed area does not block done. Report it in one sentence and make sure it is on the TODO list.

If a feature was built and tested on stored data, turn it on in the same session. Leaving it off is a deferred task. Name the reason.

Valid reasons to leave it off:

- It is broken.
- It needs a key or paid access that is not available.
- It needs future data that cannot be filled in from old records.
- It changes live alerts and still needs a shadow run or staged rollout.
- The outside source is unreliable.

## What To Verify

Always-checks for any real code or config work. Both background programs must say
`active`, and the symlink must resolve to `/home/openclaw/.openclaw`:

```bash
# 1. Both background programs running. Expect "active" twice.
#    consensus-engine = the signal engine. openclaw-gateway = the bot's live
#    connection, which also powers @mention replies.
systemctl is-active consensus-engine.service openclaw-gateway.service

# 2. The shortcut still points where it should. Expect /home/openclaw/.openclaw
readlink -f /root/.openclaw

# 3. No model-chain drift alert and no AI-health failure in the recent log.
#    Expect no output.
journalctl -u consensus-engine.service --since "30 min ago" --no-pager \
  | grep -iE "GATEWAY drift|LLM.*health.*fail"
```

If the gateway is dead, `openclaw doctor` (run as the `openclaw` user, never as root)
explains why. After fixing the cause, clear the failed state and restart:
`systemctl reset-failed openclaw-gateway.service && systemctl restart openclaw-gateway.service`.
Then confirm it is really serving, not just "started": `ss -ltnp | grep 18789`.

For doc-only changes, run the lighter doc checks listed in `docs/agents/WORKFLOWS.md`.

Check buckets:

- Discord commands: touched command routing or alert files. Check the touched command, or `!all <ticker>` if several commands changed.
- Bot mention replies: touched mention handling or agent config. Check an at-mention or `!ask`.
- Gateway and model chains: touched model-chain config. Check the boot log shows the drift check passing.
- Background programs and timers: touched unit files, task scripts, cron-style timers, or VPS paths. Check the touched script or timer runs as the right system user and ownership is unchanged.
- Data ingest: touched scanners, video ingest, or input readers. Check one real poll or ingest writes sane rows or log lines.

Shared-file tripwires:

- `consensus_engine/llm_client.py`
- `consensus_engine/config.py`
- `config/consensus.yaml`
- `consensus_engine/db.py`
- `consensus_engine/alerts/all_command/narrator.py`
- `consensus_engine/alerts/all_command/aggregator.py`

If one of those files changes, test every feature that uses it.

## Evidence Standard

Do not claim a task is complete because code looks right, a program started, or one small test passed.

For each user-visible claim:

1. Name the claim in plain words. Example: "the bot answers `!help`."
2. Trace the path from input to output.
3. Show the actual output or exact error.
4. Test separate paths separately. A command and a mention are different paths.
5. Verify after a restart when the restart matters.
6. Check the code before saying what a config key, flag, or function does.
7. Judge the real output against the goal.

For multi-step agent work, run at least one real end-to-end check and inspect the output before saying it is done.

## Regression Gate

Before feature work, establish the current test baseline.

- The baseline is `.test-baseline`.
- Refresh it with `make test-baseline` when needed.
- A passing test must not become failing.
- The set of failing test IDs matters, not just the count.
- Fix any new failing test before committing.
- A separate reviewer or verifier should rerun the full suite for large work.

The pre-push script at `scripts/pre-push` enforces this. Bypass it only for a real exception and say why.

## Alert Philosophy

Alerts should be useful, not noisy.

- Prefer quality over quantity.
- Prefer two independent sources before alerting.
- Some strong signals can alert without a second source: large options activity, insider trading, unusual flow, technical breakouts with clear levels, and quant or factor signals.
- Major-company-event filings do not trigger standalone alerts.
- Insider-trading filings are stored for cross-checking and scoring.
- SEC data feeds thesis text and cross-checks.

Alert shape:

Ticker plus direction, main catalyst, analyst view, supporting data, confidence score, and one short AI-written thesis.

## Common Commands

```bash
python3 -m consensus_engine
python3 -m consensus_engine --once
python3 -m consensus_engine --dry-run --once
python3 -m consensus_engine --status
python3 -m pytest tests/ -v
docker compose up -d
```

Use `python3 -m consensus_engine --dry-run --once` when the bot should not post live alerts.

## Key Design Decisions

- Signal-first: a tweet can create an instant alert, then cross-checks run after it.
- Free quote data is used for real-time quotes only.
- Historical daily price data comes from the Python finance library and runs in a thread pool because it blocks.
- Runtime thresholds and non-secret settings live in `config/consensus.yaml`.
- Secret values stay in machine-local env files. Do not put secret names, values, webhook URLs, email addresses, Discord IDs, or real personal names in public repo files.
- YouTube source config lives outside the public repo.
- Playwright stealth usage is `from playwright_stealth import Stealth`, then `Stealth().apply_stealth_async(page)`.
- Tests use `pytest.ini` with `asyncio_mode = auto`.

## Deferred Tasks

If a task must run later, schedule it.

- Use `/root/task_system/scripts/create_task.sh`.
- Use a systemd timer.
- Include retries, logging, and cleanup.
- Do not leave future work as a vague note.

At session start, check `/root/task_system/notifications.log` when available. If it has entries, summarize them clearly, then clear it. If it is empty, say nothing.

## Git And Session Close

Normal project policy:

- Commit local work after every functional change.
- Do not push mid-session.
- On `bye` or `goodbye`, follow `todo/SESSION_CLOSE.md`.

If a user says not to run git, do not run git. That instruction wins for the current task.

## Known Migration Traps

- A repo-root file named `.codex` breaks Codex startup here. Codex expects `<repo>/.codex/` to be a directory. The failure text was: `Failed to read project hooks config file .../.codex/config.toml: Not a directory`. If Codex fails that way, remove the file and use a directory only when project config is needed.
- The Codex digest hook hash does not need re-trusting when only the script body changes. The trusted hash covers the `hooks.json` entry, not the script body.
- Codex supports `AGENTS.md`, `config.toml`, `hooks.json` with `SessionStart`, `UserPromptSubmit`, and `PreToolUse`, custom prompts under `~/.codex/prompts/<name>.md`, `codex mcp add`, `codex exec -s <sandbox> -C <dir>`, and rules files.
- Do not invent unsupported hook events.
- Do not edit `CLAUDE.md`, `comm-check.md`, or anything under `.claude/` during the first migration pass.
- Do not move `.claude/` paths. Some are live data paths despite the name.
