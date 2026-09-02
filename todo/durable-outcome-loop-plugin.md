# Build a reusable durable outcome loop
**Status:** DONE 2026-09-01
**Created:** 2026-08-29

**CURRENT STATUS (2026-09-01):** DONE. The reusable outcome-loop plugin rejects
false completion, survives repair and restart, requires separate review, and
works for both analyst-record and invented trading-shaped missions. Runaway
checker output now uses no disk, keeps at most 2 MiB in memory, and stops at
64 MiB total. Final proof: 125 focused tests and 3,970 full-project tests passed;
code review APPROVE; design review CLEAR; cleanup PASS; both saved proof runs
remain `COMPLETE` byte-for-byte. Five non-blocking maintenance gaps are recorded
separately in TODO #112.

## Goal

Build a reusable skill/plugin for feature work where completing a prompt is not
the finish line. The loop must brainstorm, research, check feasibility, plan,
build, test, independently verify, and then either finish on a real pass or use
the failure evidence to try a meaningfully different approach.

The core must be general. Trading budgets, brokerage permissions, Discord data,
and other project-specific rules belong in each mission file, not in the skill.

## What is already decided

- Use one controller skill, tentatively named `outcome-loop`.
- Use a separate read-only reviewer, tentatively named
  `independent-verifier`. The builder cannot approve its own work or assumptions.
- Store a durable mission, attempt ledger, evidence paths, budget use, and final
  result so a new session resumes instead of starting over.
- A machine-checkable command or script is the final judge. Assistant prose,
  completed code, or a Ralph completion phrase cannot mark the mission complete.
- A failed candidate returns to discovery. A failed build returns to repair. A
  failed independent review returns to correction or a different candidate.
- Ralph or a stop-loop may keep the process moving, but it is only the motor.
  It is not the planner, reviewer, or final judge.
- Reuse the installed OMX durable-goal and autonomous-build pieces where they
  help. Do not duplicate them without a concrete need.
- Keep the kickoff for a future session to one short line. The detailed mission
  belongs in a file.

## Why the previous process failed

- Each prompt was treated as a complete job even when its result was `NO PASS`
  or `NOT TESTABLE`.
- Required data was sometimes discovered to be missing only after a large
  research execution had already run.
- One agent could design, build, interpret, and effectively approve the same
  result.
- A failure ended the session instead of becoming input to the next attempt.
- Repeated prompts lost the accumulated list of rejected approaches and their
  failure reasons.

## Priority-ordered next steps

1. Inspect the current Codex/OMX skill, plugin, goal, hook, and subagent
   conventions in this workspace.
2. Define a small mission format with the goal, measurable pass condition,
   permissions, forbidden actions, budget, allowed evidence, and true stop
   conditions.
3. Build the `outcome-loop` controller and durable attempt ledger.
4. Build or configure the separate read-only reviewer so it receives the frozen
   mission and raw artifacts, not just the builder's summary.
5. Add deterministic checks that reject completion when the goal failed, the
   reviewer is missing, the reviewer is the builder, required evidence is
   missing, or the budget/permission boundary was crossed.
6. Test a deliberately false result and prove the loop continues.
7. Test a valid result and prove the loop finishes only after independent
   verification.
8. Run a realistic dry test based on a non-trading feature, such as measuring
   Discord analyst records, so the design is proven reusable.
9. Write the short kickoff and hand TODO #111 to a fresh session.

## Expected files and code

- A reusable skill/plugin directory selected after inspecting the current
  project and personal-plugin conventions.
- `SKILL.md` files for the controller and independent reviewer.
- Small scripts for mission initialization, state checking, and the final pass
  gate where deterministic behavior is needed.
- A mission template and concise reference describing required fields.
- Focused tests for resume behavior, false completion, reviewer separation,
  budget enforcement, and successful completion.
- OMX state/goal artifacts under `.omx/` for each run; these are run records,
  not substitutes for the reusable skill.

## Completion requirements

- A stopped or compacted session can resume from the saved attempt and evidence.
- A failed candidate cannot end the mission.
- A new candidate must be meaningfully different, not the same rule with a new
  threshold or name.
- Data and permission feasibility are checked before substantial building.
- The independent reviewer is a separate agent/thread and cannot edit the
  implementation it reviews.
- A seeded false pass is rejected in a realistic test.
- A seeded valid pass is accepted only after the independent reviewer and final
  checking script agree.
- The plugin works for both the trading mission and at least one clearly
  different feature mission.

## Open questions for the build

- Whether the reusable core should begin as a personal Codex plugin with a thin
  repository wrapper, or as a repository skill that is packaged after its first
  successful use.
- Whether Claude Code needs a thin wrapper around the same shared skill files.
  If used, its Ralph stop loop must consult the checking script rather than rely
  only on a model-written completion phrase.
- Which existing OMX state files can be reused without creating competing
  sources of truth.

### Session notes — 2026-08-31

- **Worked on:** Built the reusable outcome-loop plugin, added strict fail-closed checks and 105 focused tests, completed two independent false-then-valid proof missions, prepared the #111 mission, and passed the full project run with 3,846 passed, 1 skipped, and 3 known hanging cases excluded.
- **Decisions:** Keep #110 OPEN until a fresh independent code reviewer says APPROVE, a fresh design reviewer says CLEAR, and the final quality record is written. Do not redo the implementation or proof runs.
- **Next:** Continue from `.omx/plans/todo-110-claude-handoff.md`, finish the two reviews and closing records, then mark #110 done without starting #111.

### Session notes — 2026-09-01
- **Worked on:** Removed the runaway-checker disk-fill path, added exact output-limit and escaped-writer tests, preserved old saved ledgers, completed independent cleanup and code review, reran both proof missions, and passed 125 focused plus 3,970 full-project tests.
- **Decisions:** Keep checker output off disk; retain only 1 MiB per stream in memory; stop at 64 MiB combined; preserve legacy ledgers that omit the new output-limit field; move the five non-blocking maintenance gaps to TODO #112.
- **Next:** none for TODO #110. TODO #111 stays separate for a fresh session.

### Session notes — 2026-09-01 (second session)
- **Worked on:** Added `/loopgoal`, a front door for the loop — it asks six rounds of plain-English questions (round 1 optionally names a TODO item and pre-fills every later answer from it), then writes the mission JSON and its frozen pass/fail script itself, so nothing has to be hand-created.
- **Decisions:** Questions are always asked even when the TODO item answers them (pre-filled and marked recommended, one click to accept); the pass/fail script is drafted by Claude and proved with a fake pass and a fake fail before anything runs; the last question is always "start now or save for later".
- **Next:** none. First real use will be `/loopgoal #111`.
