# Codex Migration Plan

> **Historical document.** This is Codex's own independent plan, kept as a record of what
> was proposed. It was reviewed and then corrected in three places before being carried
> out. Where this file and `MIGRATION_REPORT.md` disagree, **the report is what actually
> happened**. The three corrections:
>
> 1. The private memory corpus went to `/root/.codex/openclaw-memory/`, **not**
>    `/root/.codex/memories/openclaw/**` as written below. `/root/.codex/memories/` is
>    Codex's own automatic memory store and rewrites itself, so a hand-migrated corpus
>    placed there would be overwritten.
> 2. The digest hook does **not** need its trust hash re-approved when only the script
>    body changes. That was verified by running it.
> 3. A zero-byte file named `.codex` at the repository root stopped Codex from starting
>    in this project at all. Removing it is what makes Codex usable here.

This is the first-pass plan for moving this project from Claude Code to Codex CLI without deleting the Claude setup. The repo is public, so this plan names paths and decisions but does not include secret values, personal email addresses, webhook URLs, or Discord user IDs.

## Ground Rules

- Do not delete Claude-side files in this pass.
- Do not rename `/root/codex-migration-work/.claude/`. In this repo it is a data directory, not just Claude Code config.
- Keep `/root/codex-migration-work/CLAUDE.md`, `/root/codex-migration-work/comm-check.md`, and all global Claude files untouched during the first implementation pass.
- Treat `/root/codex-migration-work/AGENTS.md` as sensitive runtime text because the Discord bot also reads it. Extend it only with a small coding-agent routing section.
- Put private facts in `/root/.codex/`, not in the repo.
- Codex edits repo files only. The supervisor handles git and all writes outside `/root/codex-migration-work`.

## 1. Direct Transfers

These work under Codex without conversion, or with only wording cleanup later.

- `/root/codex-migration-work/todo/CONVENTION.md` - the TODO system is plain files plus Python helper scripts. Codex can follow it as-is.
- `/root/codex-migration-work/todo/SESSION_CLOSE.md` - steps 1-5 are model-neutral. The memory and comm-check cleanup steps need Codex substitutes, covered below.
- `/root/codex-migration-work/TODO.md` and `/root/codex-migration-work/todo/*.md` - keep the two-layer task system unchanged.
- `/root/codex-migration-work/scripts/pre-push` - the regression gate is shell plus pytest. Keep `--color=no`; it is harmless under Codex.
- `/root/codex-migration-work/.github/workflows/regression-gate.yml` - already agent-neutral.
- `/root/codex-migration-work/Makefile` - targets are usable by any runner.
- `/root/codex-migration-work/infra/systemd/**` and `/root/codex-migration-work/systemd/bgutil-pot.service` - no Claude runtime dependency.
- `/root/task_system/scripts/session_close.sh`, `/root/task_system/scripts/ci-monitor.sh`, `/root/task_system/scripts/ci_autofix.sh`, and most `/root/task_system/scripts/**` - execution is model-neutral. Codex only needs the session-start alert surfacing restored.
- `/root/codex-migration-work/.claude/go-live-evidence/**`, `/root/codex-migration-work/.claude/discover/**`, and `/root/codex-migration-work/.claude/flow-shadow/**` - keep as historical and live data paths. Do not move in this pass.
- `/root/codex-migration-work/comm-check.md` - the rubric is usable by Codex, but wording still says Claude. Leave untouched now; later create a model-neutral wrapper instead of editing it.

## 2. Required Conversions

| Source | Target | Transformation |
|---|---|---|
| `/root/codex-migration-work/CLAUDE.md` | `/root/codex-migration-work/docs/agents/PROJECT_RULES.md` | Convert the operative project rules into model-neutral language. Preserve the plain-language rule, PDT-only rule, verification ladder, Definition of Done buckets, regression gate, alert philosophy, commands, deferred-task rules, and session-close trigger. Translate Claude-only mechanics into explicit Codex actions. |
| `/root/codex-migration-work/AGENTS.md` | same file | Add a short `Coding Agents` section that says Codex coding sessions must read `docs/agents/PROJECT_RULES.md` and must not adopt the Discord-bot persona. Leave existing bot persona text behaviorally unchanged. |
| `/root/codex-migration-work/.claude/commands/todo.md` | `/root/.codex/prompts/todo.md` | Port the slash command almost verbatim. It should read `todo/CONVENTION.md` and route `$ARGUMENTS` to list, open, resume, pause, add, done, and show actions. Supervisor writes this private Codex file. |
| `/root/codex-migration-work/todo/SESSION_CLOSE.md` | `/root/codex-migration-work/docs/agents/WORKFLOWS.md` | Keep the existing file, but add a model-neutral workflow doc that explains `bye`, TODO updates, regression gate, and what replaces Claude memory/comm-check cleanup under Codex. |
| `/root/.claude/CLAUDE.md` | `/root/.codex/AGENTS.md` | Add the missing global Communication Style section and reconcile the older Karpathy guidance already present in Codex. Supervisor writes this. |
| `/root/.claude/hooks/openclaw-digest.sh` | `/root/.codex/hooks/openclaw-digest.sh` | Replace the stale Codex copy with the Claude copy because the Claude copy also surfaces `/root/task_system/notifications.log` with `UNVERIFIED` labels. Supervisor must re-trust the hook hash in `/root/.codex/config.toml`. |
| `/root/.claude.json` project MCP servers | `/root/.codex/config.toml` or `codex mcp add` | Recreate `sec-edgar`, `exa`, and `github` MCP servers for Codex. Do not copy plaintext key values. Use environment-variable injection from machine-local env files. Supervisor handles this because the source contains credentials. |
| `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/**` | `/root/.codex/memories/openclaw/**` plus sanitized repo docs | Copy or convert memory topics into a Codex-readable private memory tree. Publish only sanitized routing docs in the repo. Details below. |
| `/root/codex-migration-work/USER.md` | same file, later cleanup | Remove the stale "Anthropic API for LLM parsing" claim after the migration plan is approved. Current code uses OpenRouter, not an Anthropic SDK. |
| comments in `scripts/schwab_login.py`, `scripts/schwab_reauth_check.py`, `scripts/schwab_flow_shadow_compare.py`, `consensus_engine/main.py`, `consensus_engine/scanners/trading_halts.py`, `Makefile`, and `config/consensus.yaml` | same files, later cleanup | Change user-facing or authority text from Claude-specific to model-neutral wording where it is only a label. Do not change hardcoded `.claude/` data paths in this pass. |

## 3. No Codex Equivalent

- Claude Stop hooks: `/root/.claude/hooks/verify-on-done.py` has no confirmed Codex Stop event. Compensation: keep `scripts/pre-push`, CI, and session-close gates; add a Codex rule that final answers must show verification evidence. Mechanical turn-end blocking is lost unless a Codex wrapper is built later.
- Claude Stop/SubagentStop claim gate: `/root/.claude/hooks/verify-claim-gate.py` depends on Claude hook JSON and Claude transcript format. Compensation: port the rule into `PROJECT_RULES.md`; optionally build a later Codex-specific transcript checker if Codex exposes the needed session format.
- Claude plugin marketplace: `/root/.claude/plugins/**`, `enabledPlugins`, and `/root/scripts/update_plugins.sh` have no direct Codex marketplace equivalent. Keep while Claude remains installed; retire only after Codex workflows are validated.
- Discover plugin: `chopra2007/claude-discover` and repo docs under `docs/superpowers/**` depend on Claude Code Workflow engine. Compensation: keep historical `.claude/discover/**`; rebuild a Codex-native discover workflow later if still needed.
- Claude Workflow engine and subagent/team semantics: Codex has OMC-style orchestration here, but not the same Claude Workflow runtime. Compensation: document equivalent prompt/team patterns only after testing them under Codex.
- Claude status line and HUD: `/root/.claude/hud/omc-hud.mjs` is still called by `/root/.codex/hooks.json`. Keep the path or repoint it; do not remove `/root/.claude`.
- Claude auto-memory loading: Codex will not auto-load the Claude per-project memory tree. Compensation: tiered private Codex memory plus explicit routing from `AGENTS.md`.
- Claude Desktop routines in `windows_runtime/**`: out of scope for Codex CLI migration. They remain a separate Anthropic-product dependency.

## 4. Model-Agnostic Shared Surface

These should be the shared source of truth for Claude Code, Codex, and the Discord bot:

- `/root/codex-migration-work/docs/agents/PROJECT_RULES.md` - project engineering rules in plain language.
- `/root/codex-migration-work/docs/agents/WORKFLOWS.md` - TODO, session close, verification, and deferred-task workflows.
- `/root/codex-migration-work/todo/CONVENTION.md` - detailed TODO mechanics.
- `/root/codex-migration-work/todo/SESSION_CLOSE.md` - existing close procedure until replaced.
- `/root/codex-migration-work/comm-check.md` - current rubric, referenced through a model-neutral wrapper.
- `/root/codex-migration-work/.claude/**` data directories - retained as model-neutral data paths despite the name.
- `/root/codex-migration-work/config/consensus.yaml` - functional runtime config. Only comments should be de-branded unless a separate feature change requires more.
- `/root/codex-migration-work/scripts/**`, `/root/codex-migration-work/consensus_engine/**`, `infra/systemd/**`, and `.github/workflows/**` - code and automation stay model-neutral.

Keep `/root/codex-migration-work/SOUL.md`, `/root/codex-migration-work/USER.md`, `IDENTITY.md`, `TOOLS.md`, and heartbeat files as Discord-bot runtime files. Codex coding sessions should not read them as their own identity once the new coding-agent routing exists.

## 5. Codex-Native Surface

Private Codex files the supervisor should create or update:

- `/root/.codex/AGENTS.md` - add global plain-language communication rules, user preference for short kickoff prompts, and the rule to keep private facts out of the public repo.
- `/root/.codex/config.toml` - keep trusted project entries for `/root/codex-migration-work`; add MCP servers; remove or revise stale rules only after testing.
- `/root/.codex/hooks.json` - keep `SessionStart`, `UserPromptSubmit`, and `PreToolUse`. Do not invent `Stop` or `SubagentStop` events.
- `/root/.codex/hooks/openclaw-digest.sh` - sync from Claude version and re-trust hash.
- `/root/.codex/prompts/todo.md` - Codex replacement for `.claude/commands/todo.md`.
- `/root/.codex/prompts/session-close.md` - optional Codex prompt for the `bye` procedure, pointing to `todo/SESSION_CLOSE.md`.
- `/root/.codex/memories/openclaw/**` - private migrated memory corpus.
- `/root/.codex/rules/default.rules` - remove or replace the stale OMC 4.9.3 allow rule after confirming current oh-my-Codex behavior.

Repo files Codex can write:

- `/root/codex-migration-work/docs/agents/PROJECT_RULES.md`
- `/root/codex-migration-work/docs/agents/WORKFLOWS.md`
- `/root/codex-migration-work/docs/agents/MEMORY_GUIDE.md`
- `/root/codex-migration-work/docs/agents/memory/INDEX.md`
- a small addition to `/root/codex-migration-work/AGENTS.md`

## 6. Duplicates, Conflicts, and Stale Instructions

- `AGENTS.md` says `CLAUDE.md` wins, but Codex reads `AGENTS.md`. Migration winner: `docs/agents/PROJECT_RULES.md` for coding agents, with `CLAUDE.md` retained for Claude during transition.
- Root `AGENTS.md` is a Discord-bot persona. Coding-agent instructions must be scoped so Codex does not become the bot persona.
- `/root/.codex/AGENTS.md` lacks the global plain-language Communication Style rule from `/root/.claude/CLAUDE.md`. Winner: the global Claude wording, ported to Codex.
- `/root/.codex/hooks/openclaw-digest.sh` is stale and misses the notifications banner. Winner: `/root/.claude/hooks/openclaw-digest.sh`.
- Claude memory `MEMORY.md` index says one E2 value, while the topic file records a newer value. Winner: the topic file body, not the stale index hook.
- Claude memory user profile is stale: it describes a deferred machine migration and old repo naming. Winner: current project docs and audited current state.
- `USER.md` and `CHANGES.md` mention Anthropic API usage, but code and requirements show no Anthropic SDK dependency. Winner: current code reality: OpenRouter chains.
- `ci-monitor.sh` has a stale comment saying it invokes Claude. Its body does not. Winner: script body.
- `/root/.claude/hooks/lib/stdin.mjs` is a dangling symlink. Do not migrate.
- `/root/.codex/rules/default.rules` contains a stale OMC 4.9.3 path rule. Re-test before carrying it forward.
- `.githooks/pre-commit`, `.pre-commit-config.yaml`, and `.git/hooks/pre-push` can conflict depending on `core.hooksPath`. Supervisor must verify live git hook wiring because Codex cannot run git here.
- `CLAUDE.md.backup.2026-05-27` contradicts current policy. Do not migrate.
- Memory backups `MEMORY.md.backup-2026-06-20`, `MEMORY.md.pre-refactor-bak`, and `archive/MEMORY-before-tiered-index-2026-07-08.md` are obsolete snapshots. Do not migrate except as private archive if desired.

## 7. Information at Risk of Silent Loss

- Notifications from `/root/task_system/notifications.log`: Codex currently has the stale digest hook, so gate and push alerts can be missed. Preserve by syncing the hook.
- Claude memory corpus: operational lessons, current project state, and debugging traps do not auto-transfer to Codex. Preserve with a private Codex memory tree and a public sanitized index.
- Discord mention-agent memory search: `/home/openclaw/.openclaw/openclaw.json` points memory search at the Claude memory directory. If that directory is moved, the mention agent loses memory. Preserve by leaving the Claude memory directory in place until `openclaw.json` is updated by the supervisor.
- Go-live evidence: scripts require `.claude/go-live-evidence/<flag>.md`. Preserve by keeping `.claude/` paths.
- Discover history and map cache: `.claude/discover/**` contains historical run artifacts and data consumed by scripts. Preserve by not relocating it.
- Stop-hook verification: Codex lacks the Claude hook event. Preserve partially through written rules, pre-push, CI, and session-close checks.
- Claim-tripwire behavior: Codex lacks the Claude transcript checker. Preserve the rule and mark enforcement as weaker.
- MCP access: Claude MCP credentials live in a credential-bearing global config. Preserve functionality by re-adding MCP servers to Codex using env vars, not copied values.
- TODO resume/pause state: `todo/.active` is gitignored session state. Preserve by documenting the exact workflow in Codex prompts.
- Cross-family reviewer policy in `scripts/ci_ai_fixer.py`: the current `anthropic/` ban was written for Claude-authored code. Preserve by surfacing this as a user decision before changing tests or policy.

## 8. Memory Migration Design

Audit says the Claude memory corpus has 209 markdown findings; this environment currently sees 208 markdown files under `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/`. The implementation should reconcile that count before copying.

### Public Repo Tier

Public files must be sanitized and concise:

- `/root/codex-migration-work/docs/agents/MEMORY_GUIDE.md`
  - Explains how Codex should use memory: search private Codex memory first, then repo docs, then live files.
  - Names private path roots but contains no private facts.
- `/root/codex-migration-work/docs/agents/memory/INDEX.md`
  - Sanitized routing index with categories only: communication rules, verification traps, runtime architecture, model-chain notes, data-source gotchas, current-task pointers, historical project records.
  - Links to public model-neutral docs only.
- `/root/codex-migration-work/docs/agents/memory/PUBLIC_PROJECT_STATE.md`
  - Sanitized architecture facts that are safe for a public repo: engine service, gateway service, TODO system, CI gate, `.claude/` data-path convention.

Do not put the following in public repo files: webhook URLs, API keys, auth-token details, personal emails, Discord user IDs, live account identities, or private contact names.

### Private Codex Tier

Supervisor-created private target:

- `/root/.codex/memories/openclaw/README.md` - explains the migrated structure and source corpus path.
- `/root/.codex/memories/openclaw/MEMORY.md` - concise routing index, kept under a load target such as 17KB.
- `/root/.codex/memories/openclaw/indexes/project-index.md` - port of Claude `indexes/project-index.md`.
- `/root/.codex/memories/openclaw/indexes/comm-check-index.md` - port of Claude `indexes/comm-check-index.md`.
- `/root/.codex/memories/openclaw/topics/feedback/*.md` - behavior and coding-standard lessons.
- `/root/.codex/memories/openclaw/topics/reference/*.md` - operations references and traps.
- `/root/.codex/memories/openclaw/topics/project/*.md` - current and historical project state.
- `/root/.codex/memories/openclaw/private/credential-pointers.md` - names where secrets live, without values.
- `/root/.codex/memories/openclaw/archive/` - optional private backup-only area for obsolete Claude memory snapshots.

Migration rules:

- Migrate bodies, not frontmatter alone. Several topic files have `description: TODO`, truncated descriptions, or empty names while the body is complete.
- Do not copy obsolete duplicates into the active index: old user profile, autonomous preference superseded by no-confirmations, done-claim stubs consolidated into Definition of Done, duplicate memory backups, and stale Debian migration notes.
- Keep technical detail by linking to topic files. Do not compress debugging history into a one-line summary if the full steps matter.
- Mark each private topic with one of: `behavior`, `coding-standard`, `operations`, `architecture`, `current-task`, `history`, `obsolete`, or `private-pointer`.
- Keep the top-level private `MEMORY.md` as a router only. Move shipped or dormant project entries into `indexes/project-index.md`.

Maintenance process for future Codex sessions:

1. At session start, read `/root/.codex/memories/openclaw/MEMORY.md` only when the task touches OpenClaw behavior, config, operations, or prior decisions.
2. Follow links to one or two relevant topic files; do not bulk-load the corpus.
3. New durable lessons go into a new private topic file plus one short routing line.
4. Instructions that should affect every coding agent go into `docs/agents/PROJECT_RULES.md`; private facts stay under `/root/.codex/memories/openclaw/`.
5. Once a current item ships, move its routing line from private `MEMORY.md` to `indexes/project-index.md`.
6. Run a simple link check and secret scan before any public memory doc changes are committed.

## 9. Validation Checklist

After implementation:

- Check that `AGENTS.md` contains only a small coding-agent route and that the Discord-bot persona text is not behaviorally rewritten.
- Check that `docs/agents/PROJECT_RULES.md` preserves all operative rules from `CLAUDE.md`.
- Run a public-file scan for secret-shaped values, email addresses, webhook URLs, and Discord IDs before commit.
- Search unresolved Claude references with `rg "CLAUDE|Claude|Anthropic|anthropic|CLAUDECODE_WEBHOOK|\\.claude"` and classify each as intentional, converted, stale, or blocked.
- Verify `.claude/` data paths still exist and are not moved.
- Verify links in `docs/agents/**` and `docs/migration/codex-plan.md`.
- Supervisor verifies `/root/.codex/hooks/openclaw-digest.sh` hash is trusted in `/root/.codex/config.toml`.
- Supervisor starts a fresh Codex session and confirms the SessionStart hook surfaces notifications and memory digest.
- Supervisor verifies `/root/.codex/prompts/todo.md` can route at least list and resume cases.
- Supervisor verifies Codex MCP servers are listed and one safe read-only call works for each.
- Supervisor verifies git hook wiring, because Codex was instructed not to run git here.
- Run `python3 -m pytest tests/ -v` only if implementation touches code or config. Doc-only changes need link/secret/reference validation instead.
- Re-read the final structure from Codex in a clean session to confirm the instructions are discoverable without Claude.

## 10. Ordered Implementation Tasks

1. [CODEX] Create `/root/codex-migration-work/docs/agents/PROJECT_RULES.md` from `CLAUDE.md`, model-neutral and plain-language.
2. [CODEX] Create `/root/codex-migration-work/docs/agents/WORKFLOWS.md` covering TODO, `bye`, verification, session-close, and the Codex replacement for Claude memory cleanup.
3. [CODEX] Create `/root/codex-migration-work/docs/agents/MEMORY_GUIDE.md` and `/root/codex-migration-work/docs/agents/memory/INDEX.md` with sanitized memory-routing guidance.
4. [CODEX] Add the smallest safe coding-agent section to `/root/codex-migration-work/AGENTS.md`, pointing Codex to `docs/agents/PROJECT_RULES.md` and telling coding agents not to adopt the Discord-bot persona.
5. [CODEX] Add public-safe validation notes to `/root/codex-migration-work/docs/migration/` after implementation, if requested in the next phase.
6. [SUPERVISOR] Update `/root/.codex/AGENTS.md` with the missing global Communication Style section and private-user guidance.
7. [SUPERVISOR] Copy `/root/.claude/hooks/openclaw-digest.sh` to `/root/.codex/hooks/openclaw-digest.sh`, then re-trust the hook hash in `/root/.codex/config.toml`.
8. [SUPERVISOR] Add `/root/.codex/prompts/todo.md` from `.claude/commands/todo.md`.
9. [SUPERVISOR] Optionally add `/root/.codex/prompts/session-close.md` pointing at `todo/SESSION_CLOSE.md`.
10. [SUPERVISOR] Migrate Claude memory into `/root/.codex/memories/openclaw/**`, skipping credential-bearing files and keeping private facts private.
11. [SUPERVISOR] Recreate MCP servers in Codex with `codex mcp add`, using env-variable injection instead of copying credential values.
12. [SUPERVISOR] Review `/root/.codex/rules/default.rules` and remove stale OMC 4.9.3 rules only after confirming they are unused.
13. [SUPERVISOR] Verify live git hook wiring and decide whether `.githooks/pre-commit`, `.pre-commit-config.yaml`, and `.git/hooks/pre-push` need consolidation.
14. [CODEX] In a later cleanup phase, update stale public wording in `USER.md`, comments, and docs, without changing functional `.claude/` paths.
15. [SUPERVISOR] Decide whether the CI auto-fixer cross-family ban should change after Codex becomes the primary author. Do not change `scripts/ci_ai_fixer.py` silently.
16. [SUPERVISOR] Keep `/root/scripts/update_plugins.sh` until Claude is intentionally retired; then disable it as a separate cleanup.
17. [SUPERVISOR] Validate with the checklist above, then handle all git operations.

## Implementation Posture

The safest migration is additive:

1. Add Codex-readable shared docs.
2. Add private Codex-native prompts, hooks, MCP, and memory.
3. Keep Claude files and `.claude/` data paths.
4. Validate a clean Codex session.
5. Only after validation, decide what Claude-only automation can be retired.
