# Kickoff: build TODO #85, #86, #87 autonomously (research already done)

**Created:** 2026-08-17

## Where things stand

Research/evidence-gathering for #85, #86, #87 is DONE and saved to disk — Discord chats, code,
and stored-data dumps are all in `.omx/evidence/todo-85/`, `todo-86/`, `todo-87/`, each with its
own README. No feature code has been written yet.

Read the full plan for each item before starting:
- `todo/discord-feature-questions-from-code.md` (#85)
- `todo/vvix-vix-relative-lead-streak.md` (#86)
- `todo/morning-brief-embed-expected-move-images.md` (#87)

## Owner decisions already made (2026-08-17) — do not re-ask these

1. **Build order:** #85 first, fully done and verified, then #86, then #87. One at a time, not parallel.
2. **#86 wording:** The VVIX evidence found **zero 3-day upward lead streaks in the real 23 days of
   data** — so "may foreshadow higher volatility" cannot be backed up yet. Show the streak as a plain
   fact only (e.g. `VVIX leading higher by 2.0 pts today · ↑ 1 day`). Do NOT include any
   foreshadowing/predictive language until enough real streaks exist to check the claim against.
3. **#85 live testing:** OK to post live test questions in `#chat` as part of building and verifying
   this — no need to keep it to a private/test channel.

## Keep context small: delegate the actual coding to subagents

Three features' worth of code, tests, and Discord/Codex checks will blow out the main session's
memory if done inline. Use the `ralph` skill as intended: each PRD story's real implementation work
goes to a delegated executor agent (Task tool), not written directly in the main conversation. The
main session should only hold short summaries/results back from each subagent, plus the PRD/progress
tracking. If context still gets tight partway through, that's fine — start a fresh session, paste the
same trigger line, and it picks up from the DONE markers already written to TODO.md/detail files plus
the PRD state.

## Run mode: autonomous, one item at a time

Work through #85, then #86, then #87, in that order. For each item: build it, verify it fully
(see "Historical-proof requirement" below), mark it DONE, THEN move to the next item. Do not stop
to ask for confirmation between items or between build/verify steps — only stop for a genuine
blocker (missing API key, a dependency that's actually broken) and report it plainly. This is a
good fit for the `ralph` skill (PRD-driven persistence loop with mandatory reviewer verification
each story) — if using it, build a fresh task-specific `prd.json` for these three items only; do
NOT reuse or extend any existing unrelated `prd.json` in this repo.

## What's left, in order

### #85 — grounded feature-question answers
1. Build the test question set from real recovered `#chat` questions (see
   `.omx/evidence/todo-85/feature-questions-extracted.md`) plus the required coverage: signal breadth,
   VVIX vs VIX, expected move, alert scores, analyst groups, and one question with a false premise.
2. Have Codex independently read the current code and write the correct plain-English answer for each
   question BEFORE seeing what the bot says.
3. Run the same questions through the real `!ask` / @-mention path and grade each answer against
   Codex's answer key (factual correctness, right files read, plain English, no invented features).
4. Race current strong models from the live provider catalog on this graded test; pick the cheapest one
   that passes reliably. Update only the agent chain — don't touch the models used by alerts, `!all`,
   or the morning brief.
5. Test a multi-turn follow-up — the bot must remember the topic and correct a wrong premise instead of
   agreeing with it.
6. Ask the real breadth example in Discord `#chat` and read the actual reply before marking done.

### #86 — VVIX leadership and streaks
1. Build the streak/lead calculation and the display line (percentage-point lead + consecutive-day
   count), per the wording decision above.
2. Add tests: 3-day up streak, 2-day down streak, mixed directions, tie, weekend gap, missing/stale data.
3. Render it for real in `!market` and check the live Discord card before marking done.

### #87 — morning brief compact card with charts
1. Design the compact card shape (Overnight / Levels to Watch / High-Conviction Calls / Macro / Top
   Tickers), matching the July 30 reference style.
2. Make the AI return structured section text (or parse/validate it) with a deterministic fallback.
3. Reuse the existing `!em`/`!emw` expected-move code for the SPY chart(s) — don't recalculate.
4. Build a sender for one embed + 1-2 PNG attachments; keep existing retry/archive/idempotency behavior.
5. Test embed limits, image failure, missing daily/weekly data, and the fallback path.
6. Post a labeled test in `#chat`, compare to the July 30 reference, then check the next real scheduled
   brief before marking done.

## Historical-proof requirement (applies to all three — this is what "verify each" means)

Each item's detail file has a "Historical verification required before DONE" section — replay against
real stored data, have Codex independently verify, and do a real live-Discord check. Don't mark any of
these done on unit tests alone. Between items: mark the finished one DONE in TODO.md (status marker)
and in its detail file (CURRENT STATUS line), commit, then move to the next item.
