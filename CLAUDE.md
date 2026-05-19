# CLAUDE.md

## Behavior
Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?". Assume the answer is always yes and execute immediately.

## Definition of Done

A task is not done if a user-facing critical path is broken at the end of the work — regardless of who broke it, when, or whether it's technically in scope.

"Pre-existing", "out of scope", "not my regression", "upstream issue" are NOT valid exemptions for declaring a task complete. If verification surfaces a broken critical path, only three responses are acceptable:
1. Fix it
2. Attempt a fix, then surface the specific failure and ask whether to keep digging
3. Get explicit spoken user permission to defer

The path the user asked me to verify is critical by definition — I don't get to redefine "critical" mid-task to exclude something that's failing.

**Critical paths for this project** (must work end-to-end before any "done"):
- `consensus-engine.service` and `openclaw-gateway.service` both `active` under systemd
- `!ask`, `!trend`, `!all <ticker>` return coherent replies in Discord
- `@-mention <BOT>` returns coherent replies (tests workspace shell + LLM path)
- Both cron scripts (`check_searxng_health.sh`, `run_reference_assertions_cron.sh`) run as `openclaw` user with exit 0
- Engine boot logs `boot drift check: gateway chain matches consensus.yaml` (no `❌ GATEWAY drift` Discord alert)
- `/root/.openclaw` resolves to `/home/openclaw/.openclaw` (single-user consolidation intact)

**Verification standard:** Never claim a fix or feature is complete until you have produced evidence of it working from the user's perspective — not just "the service started" or "the code looks right" or "unit tests pass."
1. Name the user-observable claim precisely ("the bot responds to `!help`", not "the gateway is connected")
2. Trace the full end-to-end path from input to output
3. Produce evidence at the output end — show the actual output, not just that code ran without errors
4. Test each distinct claim separately (e.g. commands and mentions route through different code paths)
5. Verify after every restart — not before

**Real-world test requirement:** For any multi-phase project execution (discover Pass 5, ralph, autopilot), unit tests passing is not sufficient. Before declaring a phase done, run at least one real end-to-end invocation against the production system with real input and inspect the actual output. Before deferring a test to the user, actively check what tools are accessible — look up available tools in memory, consider what commands and APIs are already wired up in the project, probe the runtime environment. Do not assume a tool is available or unavailable; check first.

**Before typing any "done" / "complete" / "fixed" / "ready" claim:**
1. Re-read this Definition of Done at the moment of claiming — not just at session start
2. List every test failure, red probe, and unverified critical path from the work just done
3. For each one, assign exactly one of the three acceptable responses above — "pre-existing" and "unrelated to my changes" are not on the list
4. If any item has no response assigned, the work is not done — state that and ask

**Premature-closure tells to watch for:**
- Counting passing checks ("3/5 passed") while moving on from failures
- Reframing a broken feature as a "documented limitation"
- Declaring a summary before all critical paths report green
- Marking a real-world test as "deferred to user" without first checking whether the tools to run it are already available
- Any sentence combining a passing claim with a failure caveat ("X passes, Y fails but it's pre-existing") — that sentence shape is the violation
- The word "pre-existing" in my own output about a user-facing feature — treat as a yellow flag, stop and dig instead

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
