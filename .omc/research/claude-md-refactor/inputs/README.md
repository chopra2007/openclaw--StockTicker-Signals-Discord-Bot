# Inputs manifest — CLAUDE.md adversarial refactor

All files Codex needs are staged here, inside the workspace, to work around sandbox limits that blocked the first attempt at reading `/root/.claude/`.

## Primary targets (the files being refactored)

- `global-CLAUDE.md` — copy of `/root/.claude/CLAUDE.md` (117 lines). The user-level config loaded into every Claude Code session globally.
- `project-CLAUDE.md` — copy of `/home/openclaw/.openclaw/workspace/CLAUDE.md` (221 lines). The repo-level config loaded only in this project.

## Supporting context

- `comm-check.md` — copy of the workspace's `comm-check.md`. Test rubric referenced by the project CLAUDE.md's Communication Discipline section. Treat it as load-bearing alongside that section.
- `omc-config.json` — copy of `/root/.claude/.omc-config.json`. OMC plugin config.
- `project-claude-settings.json` — copy of `.claude/settings.json` (project-scoped). Permissions, env vars, HUD config.
- `project-claude-settings.local.json` — copy of `.claude/settings.local.json`. Local permission allowlist; no credentials.
- `hook-openclaw-digest.sh` — copy of the global `SessionStart` hook script.
- `skill-omc-reference.md` — copy of the `omc-reference` skill's SKILL.md. Important: the OMC block in the global CLAUDE.md says detailed agent/tool/skill catalogs live in this skill; cross-reference before deciding what to cut from the OMC block.
- `memory/` — full copy of `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/` (72 files). Auto-memory entries that may already cover topics currently restated in CLAUDE.md. Read `memory/MEMORY.md` first (it's the index).

## Output location

Write your deliverables to `../outputs/` (i.e. `/home/openclaw/.openclaw/workspace/.omc/research/claude-md-refactor/outputs/`). That directory has already been created.

## Constraints repeated

- Do not modify the live `/root/.claude/CLAUDE.md` or `/home/openclaw/.openclaw/workspace/CLAUDE.md`. Drafts only, written to `outputs/`.
- Do not modify the staged input copies in this directory.
- No git operations.
