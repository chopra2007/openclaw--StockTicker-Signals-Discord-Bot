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

Watch for premature-closure tells: counting passing checks while moving on from failures, reframing a broken feature as a "documented limitation", declaring a summary before all critical paths report green.

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
- Remote: `chopra2007/openclaw--StockTicker-Signals-Discord-Bot` (private).
- Keep `README.md` current with architecture, setup, and features.
