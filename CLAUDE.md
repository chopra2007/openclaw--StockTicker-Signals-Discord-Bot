# CLAUDE.md

## Communication Style

The user is not a coder. This applies to all user-facing text, every session, every project, and overrides any other instruction on how to explain things:
- Plain, everyday language only — no jargon. If a technical term is unavoidable, explain it in plain words right there.
- Clear, concise, to the point. Short sentences. No long wind-up, no filler.
- Use concrete, real examples instead of abstract description.

## Behavior
Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?". Assume the answer is always yes and execute immediately.

## Session Close Trigger
When the user sends a message containing only "goodbye" or "bye", act immediately with no confirmation:
1. `git status` — commit any uncommitted changes
2. `git log origin/master..HEAD` — push any unpushed commits
3. Verify memory index (MEMORY.md) is up to date
4. Report what was done (or "nothing to push, all clean")

## Definition of Done

A task is not done if a user-facing critical path is broken at the end of the
work — regardless of who broke it, when, or whether it's "in scope".
"Pre-existing", "out of scope", "not my regression", "upstream issue" are NOT
valid exemptions. If verification surfaces a broken critical path, only three
responses are acceptable:
1. Fix it.
2. Attempt a fix, then surface the specific failure and ask whether to keep digging.
3. Get explicit user permission to defer.

### What to verify — scope-aware

1. **Test the whole feature you changed** — not just the line you touched.
   Changed catalyst code inside `!all`? Test all of `!all`.
2. **Always-on checks — every time, no exceptions:**
   - `consensus-engine.service` and `openclaw-gateway.service` both `active`.
   - No `❌ GATEWAY drift` alert and no LLM-health failure alert.
   - `/root/.openclaw` still resolves to `/home/openclaw/.openclaw` (symlink intact).
3. **Shared-file tripwire** — if your change touches a file below, also test
   every feature that uses it:
   - `consensus_engine/llm_client.py`
   - `consensus_engine/config.py` + `config/consensus.yaml`
   - `consensus_engine/db.py`
   - `consensus_engine/alerts/all_command/narrator.py`
   - `consensus_engine/alerts/all_command/aggregator.py`

### Evidence standard

Never claim something is complete on "the service started", "the code looks
right", or "unit tests pass" alone. Produce evidence from the user's side:
1. Name the user-observable claim precisely ("the bot responds to `!help`", not
   "the gateway is connected").
2. Trace the full path from input to output.
3. Show the actual output — not just that code ran without errors.
4. Test each distinct claim separately (commands and mentions are different
   code paths).
5. Verify after every restart, not before.

For any multi-phase execution (discover Pass 5, ralph, autopilot), unit tests
passing is not enough: run at least one real end-to-end invocation against the
production system and inspect the actual output before declaring done.

### Never assume code behavior

Before asserting what a function, flag, config key, or path does — grep or read
the actual code to confirm it. Never describe behavior from memory or infer it
from a filename.

### Before typing "done" / "complete" / "fixed" / "ready"

Re-read this section. List every test failure, red probe, and unverified path
from the work just done; assign each one response 1, 2, or 3 above.
"Pre-existing" and "unrelated to my change" are not on that list. The word
"pre-existing" in your own output about a user-facing feature is a stop sign —
dig, don't close.

## Regression Gate (test baseline)

Before starting feature work — especially a `discover` run or any multi-commit change — establish a test baseline, and never let it regress.

1. **Baseline** = the list of known-failing test IDs in `.test-baseline` (repo root, committed). The `pre-push` hook creates it on first run; `make test-baseline` refreshes it.
2. **No commit may make a test fail that was passing at baseline.** Any test failing now but absent from `.test-baseline` is a regression — fix it before committing.
3. **It's the set that matters, not the count.** A change that fixes one test and breaks another is still a regression even though the count is unchanged. The suite is currently red — treat the baseline as debt to drive toward zero.
4. **Separate verifier.** At the end of feature work, have a separate agent (not one that wrote the code) re-run the full suite and diff the baseline.

The `pre-push` git hook (`scripts/pre-push`) enforces this mechanically — it runs the suite and blocks any push that introduces a test failure not in the baseline. Install it after cloning with `make install-hooks`. Bypass only for a genuine exception: `git push --no-verify`.

## Alert Philosophy

**Core Goals:** Quality over quantity. Actionable intelligence. 2+ independent sources before alerting (with exceptions).

**Instant-trigger exceptions** (no second source needed): large options activity, insider trading, unusual flow, technical breakout with levels, quant/factor signals.

**SEC Filing Rules:**
- 8-K filings NEVER trigger standalone alerts
- Form 4 stored for cross-ref, adds +15 points to scoring
- All SEC data feeds LLM thesis generation only

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

See the real-world test requirement under Definition of Done above. No static tool list is maintained here — before deferring a test, actively check memory and probe what's accessible in the environment rather than assuming a tool is unavailable.

**Don't stop at code-functional during verification — do real-world testing whenever the user-observable outcome can be checked from this environment.** "Unit tests pass" or "service started" does NOT discharge the verification standard if the actual end-to-end behavior can be probed.

**When real-world tests hit errors**, follow this ladder before pinging the user:
1. **Diagnose** what's actually failing — error strings often mask the real cause (e.g. a 429 may be IP-wide rate limit, not per-resource; "cookies invalid" may be a downstream symptom).
2. **Attempt to fix** with concrete repairs you can execute: change request parameters, swap auth modes, alternate flags, retry with backoff, different endpoint.
3. **If no fix is available from this environment, explore alternative paths to the same goal** — same outcome via different mechanism (e.g. yt-dlp cookies dead → try `youtube_transcript_api` for captions, which has no YouTube auth; one transcript provider down → try another; HTTP timeout → smaller chunk).
4. **Only then surface to the user** with concrete evidence: what failed, what you tried, why each alternative did or didn't work, and a specific recommendation.

**Do not ask the user to do something you are fully capable of doing yourself.** Asking is acceptable when the next step genuinely requires their access (interactive re-auth), their decision (product tradeoff), or their information (something not derivable from logs/code/docs). It is NOT acceptable as a substitute for running another probe yourself.

## Key Design Decisions
- **Signal-first**: tweet → instant alert → async cross-reference. No gates block the alert.
- **Finnhub free tier**: real-time quotes only (`/quote`). Historical OHLCV via yfinance in `ThreadPoolExecutor` (blocking).
- **Config**: all thresholds/keys in `config/consensus.yaml` via `config.get("dot.path", default)`. YouTube channels: `/root/.openclaw/sources.json`. API keys: `/root/.openclaw/.env`.
- **playwright-stealth**: `from playwright_stealth import Stealth` → `Stealth().apply_stealth_async(page)` — NOT `stealth_async()`.
- Tests: `pytest.ini` `asyncio_mode = auto`.

## Deferred Task System
When a task must run in the future:
- Create it using `/root/task_system/scripts/create_task.sh`
- Use systemd timers
- Include retries, logging, and cleanup
- Never leave future tasks unscheduled

At the start of every session:
- Check `/root/task_system/notifications.log`
- If it contains entries: summarize them clearly, then clear the file
- If empty: do nothing

## GitHub & Documentation Automation
- After every functional change: commit locally then push immediately.
- Commit style: imperative (e.g., "Add multi-agent logic").
- Remote: `chopra2007/openclaw--StockTicker-Signals-Discord-Bot` (public).
- Keep `README.md` current with architecture, setup, and features.
