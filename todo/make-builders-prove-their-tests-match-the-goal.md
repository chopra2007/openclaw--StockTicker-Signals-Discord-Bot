# Make builders prove their tests match the real goal

**Status:** OPEN
**Created:** 2026-08-27

**CURRENT STATUS (2026-08-27):** No builder-instruction file has been changed. The next session must first produce carefully reviewed wording and a safe edit plan. Claude will lead, but it must use the installed `codex@openai-codex` plugin so Claude and Codex independently challenge the idea, combine the strongest parts, and review the final changes.

## Goal

Make Codex and Claude judge every build by the owner's real-world result, not by whether they faithfully completed a prompt, passed a convenient test, or collected an easy measurement.

The rule must be general. It cannot be an options-only correction. A builder should have to:

1. Restate the real goal in plain English.
2. Describe how a rational user acts from the start through the final result.
3. Look for important events that can happen between measurements.
4. Treat supplied dates, thresholds, tests and measurements as assumptions that may be wrong.
5. Include the real opportunities, failures, costs, timing and available actions.
6. Ask whether passing the proposed test would actually prove meaningful progress toward the goal.
7. Get an independent review of the goal and proposed test before implementation begins.

## Why this is needed

Several high-reasoning builds followed a flawed option test exactly. They checked a price at one later time even though the option could hit a profitable sale target and then collapse before that check. The builds were technically faithful but did not answer the real question: could a rational trade have made money during the full holding window?

More reasoning effort did not prevent the mistake because the agents reviewed whether the plan was implemented correctly. They did not first challenge whether the plan measured the real goal. The permanent fix must change that behavior across future features, including features unrelated to trading.

## What worked so far

- The failure is now understood as a goal-and-test design failure, not an options-data problem.
- A useful core principle emerged: objective first, then real user actions across the full life of the feature, then the test, then the code.
- The Claude plugin `codex@openai-codex` version 1.0.6 is installed and enabled. It provides a real Codex partner through `codex:codex-rescue`, plus Codex review commands.

## What did not work

- Bigger prompts and higher reasoning settings still allowed the wrong test to become the build contract.
- Independent checks verified compliance with the plan instead of challenging the plan itself.
- The first proposed remedy was too easy to read as an options-specific rule.
- Referring to OpenClaw as the builder was wrong. Codex and Claude build the features; OpenClaw only runs the finished daily work.

## Priority-ordered plan

1. **Map the real instruction files and their loading order.** Verify which files actually guide Codex and Claude globally and inside this project. Start with `/root/.codex/AGENTS.md`, `/root/.claude/CLAUDE.md`, `docs/agents/PROJECT_RULES.md`, and the repo-root `AGENTS.md` and `CLAUDE.md`. Do not assume that every file should change. The repo-root `AGENTS.md` is also read by the live Discord bot, so avoid it unless evidence proves it is the right target.

2. **Create the specification and edit plan before changing instructions.** Keep both under `.omc/plans/`, following the project's co-location rule. The specification must state the desired behavior, where it belongs, what wording is proposed, what existing rules it may overlap, and how success will be tested.

3. **Use genuine two-model planning.** Claude must make its own draft, then call the installed Codex plugin through a fresh, read-only `codex:codex-rescue` task. Codex receives the original failure and goal, not Claude's conclusion, and produces an independent recommendation. Claude then compares both drafts, explains disagreements in the planning file, and combines only the strongest, least repetitive wording.

4. **Challenge the wording with unrelated examples.** At minimum, test it against:
   - an option that reaches a profit target before a later fixed-time check;
   - a background program that works during one health check but fails intermittently;
   - a data job whose daily average hides missing hours;
   - an alert feature that increases alert count while making the owner's decisions worse.

   The wording passes only if it causes the builder to reject each convenient substitute and test the full real-world result.

5. **Require a clean-room review before editing.** A Codex reviewer should see the original owner goal, the proposed wording, its target files, and the four test cases. It should not receive the authors' justification. It must answer whether the rule is general, actionable, hard to game, short enough to be remembered, and free of conflicts with existing instructions.

6. **Make only the agreed surgical edits.** Claude owns the final file edits so two agents do not overwrite each other. Codex participates during execution by reviewing the exact proposed changes and checking the resulting diff. The execution kickoff must explicitly name every important instruction file it is authorized to edit, especially any `CLAUDE.md`, because those files must never be changed through vague authority.

7. **Test fresh behavior, not just Markdown wording.** Start fresh Claude and Codex test sessions with at least two deliberately flawed build requests. One must use the option-path mistake; one must be unrelated to trading. Neither test may edit production files. Both agents must identify the false measurement and propose a test that follows the complete path before the instruction change can be called successful.

8. **Run a final Codex challenge review and record proof.** Use the Codex plugin on the finished working-tree changes. Fix valid findings, rerun the fresh-session tests, and record the exact tested prompts and responses in the plan artifact. Do not claim success because both models merely approved the prose.

## Files and tools involved

- `/root/.codex/AGENTS.md` — global Codex instructions; inspect before deciding whether to edit.
- `/root/.claude/CLAUDE.md` — global Claude instructions; may be edited only when the execution request explicitly names it.
- `docs/agents/PROJECT_RULES.md` — shared project coding rules and likely home for the full project rule.
- `AGENTS.md` — also read by the live Discord bot; avoid unless verified necessary.
- `CLAUDE.md` — project Claude instructions; may be edited only with explicit file-named authority.
- `.omc/plans/` — store the jointly reviewed specification, implementation plan and proof.
- Installed Claude plugin: `codex@openai-codex` version 1.0.6.
- Plugin planning partner: `codex:codex-rescue` in fresh, read-only mode.
- Plugin final review: Codex adversarial review of the exact working-tree changes.

## Definition of done

- Claude and the real Codex plugin independently analyze the original problem.
- A jointly reasoned specification and edit plan exist before any instruction file changes.
- The final rule is short, general and tells builders exactly what to do before coding.
- Existing instruction files are not bloated with repeated versions of the same rule.
- Only files proven necessary are edited, with explicit authority for every `CLAUDE.md` target.
- Fresh Claude and Codex sessions both reject the flawed option test and at least one unrelated false measurement.
- Codex reviews the final changes adversarially, valid findings are resolved, and the tested evidence is saved.
- OpenClaw runtime behavior is unchanged; this task changes how Codex and Claude design and verify future builds.

## Open questions the planning phase must resolve

- Should the full rule live only in `docs/agents/PROJECT_RULES.md` with short global pointers, or should a compact complete rule appear in each global builder file?
- Which fresh-session tests best prove the behavior transfers beyond options?
- How can the independent review see enough context to judge the test without inheriting the first author's assumptions?
- What is the shortest wording that still forces a builder to examine the entire real-world path?
