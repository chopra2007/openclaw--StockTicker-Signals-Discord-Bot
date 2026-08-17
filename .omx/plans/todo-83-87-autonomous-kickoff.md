# Autonomous completion brief for TODO #83-#87

Complete OpenClaw TODO #83 through #87. Work autonomously until all five items are proven complete, or a genuine decision only the owner can make blocks further progress.

## Read first

Read these sources before planning or editing:

- `AGENTS.md`
- `docs/agents/PROJECT_RULES.md`
- `/root/.codex/openclaw-memory/MEMORY.md`, then only the one or two links relevant to the work in progress
- `todo/CONVENTION.md`
- `TODO.md`
- `todo/analyst-alert-remove-swarm-label.md`
- `todo/analyst-alert-direction-catalyst.md`
- `todo/discord-feature-questions-from-code.md`
- `todo/vvix-vix-relative-lead-streak.md`
- `todo/morning-brief-embed-expected-move-images.md`

Treat the five TODO detail files as the product requirements. Do not weaken, shorten, or silently reinterpret their historical review, backtesting, display, or live-proof requirements.

## Plan before editing

Inspect the real code, tests, stored data, and referenced Discord messages. Create one coordinated specification and one implementation plan under `.omx/plans/`. Cover shared code and data once. Split the work into small feature-sized changes with a clear proof check for each one.

Use this order unless the code proves a different dependency order is safer:

1. #83 and #84 together because they share analyst alert code and data.
2. #85 on its own.
3. #86 on its own.
4. #87 on its own.

Use capable subagents for independent code reading, historical-data analysis, test design, and final review when that improves accuracy. Keep implementation ownership clear. This repository uses one shared working tree, so never run `git stash`, `git reset`, `git checkout .`, or `git clean`, and never overwrite another task's edits.

## Implementation standard

- Understand the current behavior and its callers before changing it.
- Prefer the smallest change that fully meets the requirement.
- Establish the current test baseline before feature work.
- Add focused tests before or with each behavior change.
- Search for every caller and test affected by changed functions or visible text.
- Keep analyst meaning accuracy separate from whether the stock later moved in the predicted direction.
- Use every recoverable historical record required by the TODO files. Do not use a convenient small sample and call it a backtest.
- Make uncertainty and missing evidence visible instead of inventing confidence.
- Use Pacific time for anything the owner can see.
- Never read, print, expose, or commit secrets.

## Prove each feature before closing it

For every item, run focused tests, affected tests, and the repository's required broader checks. Then verify the real user-visible path with existing data in the same session:

- #83-#84: replay the recoverable analyst tweet history, inspect the direction and catalyst judgments, compare price movement from the first tweet, and inspect the rendered Discord alert.
- #85: ask representative real feature questions drawn from `#chat`, including the signal-breadth example and a safe request to add tickers. Confirm answers are grounded in current server code and written in plain English.
- #86: replay all stored VVIX/VIX rows required by the TODO, separately test whether streaks had predictive value, and inspect the rendered display.
- #87: reproduce the requested morning-brief style, inspect the actual embed and expected-move images, and confirm the daily and weekly image behavior with real data.

Do not defer proof to a future alert, market day, or scheduled brief when stored data or a safe manual run can prove it now. If a check fails, diagnose it, fix it, and repeat the check. Restart the affected background program when new code is only loaded at startup, then verify it is actually serving.

## Finish cleanly

Complete and verify one feature-sized change before moving to the next. Save verified changes in local commits, but do not push. Update each TODO detail file and `TODO.md` according to `todo/CONVENTION.md`, run the TODO sync and check scripts, and mark an item done only after its real output and required history checks pass.

Run the Ultragoal final cleanup, full verification, architecture check, and independent code review. Stop only when #83-#87 are all proven complete or when a genuine owner-only blocker remains after safe alternatives have been exhausted and documented with exact evidence.
