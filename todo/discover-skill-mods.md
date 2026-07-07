# Discover skill modifications (3 changes)

**Status:** DONE.
**Created:** 2026-05-25
**→ Living record:** this tmux-era work was superseded by the v1.1.0 rebuild; the plugin's ongoing history is consolidated into TODO #68 (`discover-plugin-logbook.md`).

**Layperson:** Three quality-of-life upgrades to the `discover` skill (installed at `/root/.claude/plugins/cache/discover/discover/0.1.0/skills/discover/SKILL.md`, source-of-truth at `/root/work/claude-discover-publish/repo/skills/discover/SKILL.md`). Today discover only composes `superpowers:brainstorming`; the rest is OMC agents. Verification is enforced by `ralph` + the `verifier` agent looping on Pass 4's checklist, not by the dedicated superpowers gate skill.

## 7a. Invoke `superpowers:verification-before-completion` in Pass 5

**Why:** Pass 5 already has a checklist + verifier agent, but the superpowers skill enforces "no completion claim without fresh evidence in the same message" — a stronger gate than "verifier eventually says ok." Layering it on top of the existing loop catches premature "implementation complete" claims from the executor/ralph loop itself.

**Where:** Pass 5 section in `SKILL.md` (currently lines 260–299). Insert an explicit `Skill` invocation step *before* the commit step (currently step 4). Also add the skill to the composition table (currently line 312, "Pass 5" row).

**Acceptance:** Pass 5 documentation now lists `superpowers:verification-before-completion` in the pass-5 composition row; the execution flow tells the orchestrator to invoke the skill before any "ready to commit" claim; a dry-run of Pass 5 against a trivial fixture shows the skill being invoked.

## 7b. Add a non-tmux parallel-agent option

**Why:** Today discover *requires* tmux (`SKILL.md:26` lists it as a hard prerequisite) and forces a 3-pane or 6-pane layout (`SKILL.md:65–107`). On systems without tmux — or when the user just wants the skill to dispatch parallel agents via Claude Code's native `Agent` / `Task` tools — the skill bails. Add a native layout option that uses the native parallel-agent dispatch from `superpowers:dispatching-parallel-agents` instead of tmux panes.

**Agent count:** The current fixed 3-pane / 6-pane choice should be replaced with a free-form "how many parallel agents?" question. Show `(suggested: 2–6)` in parentheses — below 2 there's no parallelism benefit; above 6, coordination overhead and token costs outweigh the gains. This applies to both the native layout and the tmux layout.

**Where:**
- `discover.sh` (bundled with skill) — add a code path that skips the `tmux new-session` setup when the native layout is selected; pass the user-chosen agent count through to the pane/agent spawning logic.
- `SKILL.md:24` and `SKILL.md:65–107` (layout selection question + the tmux multi-agent layout section) — replace the fixed 3/6 choice with a free-form agent-count question (`how many parallel agents? (suggested: 2–6)`); document the new native option and stop treating tmux as a hard prerequisite.
- `references/tmux-layout.md` — add a "Native (no tmux) layout" sibling doc or extend the existing one.
- Pass 0 / Pass 1 dispatch steps that currently say "dispatch into pane X" — branch on layout so they instead spawn parallel `Agent` tool calls in a single message when native layout is active.

**Acceptance:** Running `/discover` on a system without tmux installed no longer fails the prerequisite check; the layout question now offers tmux / native; both paths ask "how many parallel agents? (suggested: 2–6)" instead of offering only 3 or 6; selecting native completes Pass 0 + Pass 1 by dispatching parallel `Agent` calls instead of tmux panes; final-plan.md is produced identically (same schema) regardless of layout or agent count chosen.

## 7c. Kickoff prompt must be one short sentence

**Why:** Today the Pass 4 → Pass 5 handoff generates an `EXECUTE.md` file and asks the user to **paste its contents** into a fresh session to start Pass 5. That's exactly the workflow the personal-preference rule in `/root/.claude/CLAUDE.md` forbids:
> "When generating a kickoff prompt for the user to paste into a fresh session, keep it to a single short trigger line; all detailed instructions go in a file the new session reads, never inline in the prompt."

The kickoff prompt should be one sentence like `discover: resume EXECUTE.md` (or `discover: resume <run-dir>`) and nothing else. Pass 5 re-activates from that trigger, then reads `EXECUTE.md` / `state.json` / `final-plan.md` from disk itself.

**Where:**
- Pass 4 / end-of-pass-4 step that emits the kickoff prompt (search `SKILL.md` for "EXECUTE.md" and "kickoff" / "paste").
- Pass 5 entry point (`SKILL.md:260–262`) — already says it "reads `state.json` and `final-plan.md`", so the on-disk read path already exists; the change is purely on the prompt-generation side.
- Update the discover hard-trigger list in the skill description (line 3) if `discover: resume ...` needs to be recognized as a trigger variant.

**Acceptance:** Pass 4 output instructs the user to paste exactly one short line (`discover: resume <abs-path-to-EXECUTE.md>` or similar); the literal contents of `EXECUTE.md` no longer appear in the kickoff prompt; pasting that single sentence into a fresh Claude Code session correctly re-enters Pass 5 and reads the on-disk state.

## 7d. Update plugin README to make tmux optional

**Why:** Once 7b ships a native parallel-agent layout, the public-facing plugin README at https://github.com/chopra2007/claude-discover (local clone at `/root/work/claude-discover-publish/repo/README.md`) is out of date. Today it positions tmux as a hard dependency:
- Line 3 tagline: "Composes existing OMC and superpowers skills via tmux multi-agent orchestration — does not reinvent them."
- Line 90 Prerequisites: `**tmux** — required for parallel multi-agent panes`

After 7b ships, tmux becomes one of two parallelization options and should be moved from "Prerequisites" to "Optional" (or annotated as "required only for tmux layouts; native layout uses Claude Code's built-in parallel `Agent` dispatch").

**Where:**
- `/root/work/claude-discover-publish/repo/README.md` line 3 (tagline)
- `/root/work/claude-discover-publish/repo/README.md` line 87–91 (Prerequisites section)
- `/root/work/claude-discover-publish/extracted/discover-plugin/README.md` (mirror copy, same edits)
- Push the updated README to the GitHub repo (`chopra2007/claude-discover`) alongside the 7b release so the docs match the code.

**Acceptance:** Plugin README no longer lists tmux as a hard prerequisite; it documents both layout options (tmux vs native); GitHub `README.md` on the default branch matches; release notes for the version that ships 7b call out the new layout option.

## Notes for whoever picks this up

- The cache copy at `/root/.claude/plugins/cache/discover/discover/0.1.0/skills/discover/SKILL.md` will be overwritten on next plugin update — edit the source at `/root/work/claude-discover-publish/repo/skills/discover/SKILL.md` (and `extracted/discover-plugin/skills/discover/` if that's the publish staging path) and bump the version.
- 7d (README update) is gated on 7b shipping — don't announce tmux as optional until the native layout actually works.
- The three sub-items are independent — each can ship as its own patch. 7c is the smallest / highest-leverage (matches an explicit personal preference).
- Verify with a real `/discover` invocation on a small toy feature before declaring done — not just by reading the diff.
