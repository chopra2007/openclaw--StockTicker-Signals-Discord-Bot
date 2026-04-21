# CLAUDE.md

## Behavior
Always proceed without asking for confirmation. Never ask "shall I proceed?", "do you want me to continue?", or "would you like me to...?". Assume the answer is always yes and execute immediately.

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
docker compose up -d                 # Nitter (8585) + SearXNG (8888)
```

## Key Design Decisions
- **Signal-first**: tweet → instant alert → async cross-reference. No gates block the alert.
- **Finnhub free tier**: real-time quotes only (`/quote`). Historical OHLCV via yfinance in `ThreadPoolExecutor` (blocking).
- **Config**: all thresholds/keys in `config/consensus.yaml` via `config.get("dot.path", default)`. Twitter accounts: `/root/.openclaw/sources.json`.
- **playwright-stealth** v2.0.2: `from playwright_stealth import Stealth` → `Stealth().apply_stealth_async(page)` — NOT `stealth_async()`.
- ApeWisdom: free REST API, no auth required.
- Tests: `pytest.ini` `asyncio_mode = auto`.

## GitHub & Documentation Automation
- After every functional change: commit locally then push immediately.
- Commit style: imperative (e.g., "Add multi-agent logic").
- No remote configured: use `gh repo create` to init private repo.
- Keep `README.md` current with architecture, setup, and features.

## Karpathy Guidelines

Source: https://github.com/forrestchang/andrej-karpathy-skills
Bias: caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding
- State assumptions explicitly; if uncertain, ask.
- If multiple interpretations exist, surface them — never pick silently.
- If simpler approach exists, push back.
- Stop and name what's confusing before coding.

### 2. Simplicity First
- Minimum code that solves the stated problem. Nothing speculative.
- No abstractions for single-use code. No unrequested flexibility/configurability.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite.

### 3. Surgical Changes
- Touch only what the request requires.
- Don't "improve" adjacent code, comments, formatting, or style.
- Match existing style even if you'd do it differently.
- Remove only orphans YOUR change created; mention but don't delete pre-existing dead code.
- Test: every changed line traces directly to the user's request.

### 4. Goal-Driven Execution
- Transform the task into a declarative Definition of Done before coding.
- "Add validation" → "tests for invalid inputs pass".
- "Fix bug" → "failing repro test now passes, no regressions".
- For multi-step work: numbered plan with per-step verification.
- Strong success criteria enable independent looping; weak ones cause thrash.

### Negative-Constraint Examples (condensed from EXAMPLES.md)
- **Export user data** → don't silently pick scope/format; ask (all users vs filtered? file vs API? which fields?).
- **Discount calculator** → don't introduce ABCs, Strategy pattern, or plugin hooks for a single function. Ship the plain function.
- **Empty-email validation bug** → fix only the validation branch. Don't reformat quotes, add type hints, or rename variables in the same diff.
- **"Review and improve"** is not a goal. "Write failing test → implement fix → test passes → no regressions" is.
- Overcomplicated code often uses legitimate patterns at the wrong time. Solve today's problem; refactor when real complexity arrives.

### Working-correctly signals
Fewer unnecessary lines in diffs · fewer rewrites from overengineering · clarifying questions before implementation, not after mistakes.
