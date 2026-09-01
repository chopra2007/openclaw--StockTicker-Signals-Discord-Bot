# Build a reusable durable outcome loop
**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-09-01):** The two independent reviews were run and both
came back BLOCK, so the session became a repair pass. Six real defects were
found and fixed, each with a regression test proved to fail without the fix. The
worst: editing a file you had already recorded as evidence killed every command
including `status` and `stop`, which broke the build-repair loop the plugin
exists for. The design review is now **CLEAR**. The code review is still BLOCK on
**one open defect** — a runaway checker now fills the host disk (28.3 GB of
29.3 GB free consumed in four seconds, verified), introduced by the fix that
stopped checkers hanging the controller. Focused suite: 119 passed. The full
project suite still needs one clean run. Next session: read
`.omx/plans/todo-110-claude-handoff.md` and start at "THE ONE OPEN BLOCKER".

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
