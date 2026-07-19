# Agent Workflows

Use this file for repeated coding-agent routines. Use `docs/agents/PROJECT_RULES.md` for the rules behind them.

## TODO System

The project uses two TODO layers:

- `TODO.md` is the short list.
- `todo/<name>.md` is the detail file for one task.

When the owner asks to add a TODO:

1. Read `todo/CONVENTION.md`.
2. Create the detail file.
3. Add the short entry to `TODO.md`.
4. Keep the title plain enough to understand without opening the detail file.

When the owner asks what is left:

1. Read `todo/CONVENTION.md`.
2. Use its table format.
3. Do not dump full detail files.
4. For tasks with `**Switches:**`, run `python3 scripts/todo_switch_state.py` and trust the live config read over old prose.

When resuming a TODO:

1. Find the detail file from `TODO.md`.
2. Read that detail file.
3. Write its filename to `todo/.active`.
4. Give a short summary: title, status, created date, goal, and next step.

When pausing:

1. Read `todo/.active`.
2. Append a dated session-notes block to the matching detail file.
3. Clear `todo/.active`.
4. Say one short line that notes the task was paused.

## `bye` Session Close

When the owner sends only `bye` or `goodbye`, follow `todo/SESSION_CLOSE.md`.

Codex replacement notes:

- The TODO update still happens first.
- If git is allowed, the session-close file still controls commit and push behavior.
- If git is forbidden for the current task, do not run git. Report that session-close git steps were skipped because the owner forbade git.
- Codex does not have the same turn-end claim checker as Claude. The replacement is written evidence: state what was verified and show the result.
- Codex does not clean Claude memory. Use the private Codex memory flow in `docs/agents/MEMORY_GUIDE.md`.
- `comm-check.md` remains a reactive writing-quality rubric. Do not preload it. Read it only when the owner pushes back on an explanation or when session-close instructions require it.

## Verification Workflow

Use the lightest proof that matches the risk.

For docs-only work:

1. Check links and paths named in changed docs.
2. Search changed public docs for secret-shaped text, webhook URLs, email addresses, Discord IDs, and real personal names.
3. Search for stale Claude-only claims in the changed docs.
4. Count lines if the task asks for line counts.
5. Do not run the full test suite unless code, config, scripts, or generated runtime files changed.

For code or config work:

1. Name the changed files.
2. Map them to the buckets in `docs/agents/PROJECT_RULES.md`.
3. Run the always-checks plus the triggered buckets.
4. Run targeted tests for changed behavior.
5. Run the regression gate when the change could break existing behavior.
6. Show exact output or exact errors for every claim.

For a failed check:

1. Copy the exact error.
2. Try the next reasonable fix.
3. Try another route to verify the same user-visible outcome.
4. If still blocked, say what was tried and what is still unknown.

## Deferred Tasks

Do not leave future work as a loose sentence.

Use one of these:

- Add a TODO when it is future project work.
- Use `/root/task_system/scripts/create_task.sh` when the task must run at a future time.
- Mark a TODO as `SOAKING` only when time will create new evidence.
- Mark a TODO as `AWAITING APPROVAL` only when the remaining blocker is the owner's yes/no decision.
- Mark a TODO as `PARKED` only when something outside the project blocks it.

If a broken check is outside this task's scope, report it once and make sure it lands in the TODO system.

## Memory Workflow

Codex does not use the Claude per-project memory tree automatically.

For OpenClaw work:

1. Start with `/root/.codex/openclaw-memory/MEMORY.md` when the task touches project behavior, config, operations, or prior decisions.
2. Follow one or two relevant links from that router.
3. Then read public repo docs.
4. Then inspect live files.

Do not bulk-load private memory.

Do not put private facts into public docs.

Durable new lessons go to the private corpus first. Public rules go into `docs/agents/PROJECT_RULES.md` only when they should guide every coding agent.

## Codex-Specific Replacements

Use these in place of Claude-only mechanics:

- Custom prompts live under `~/.codex/prompts/<name>.md`.
- Project rules live in `AGENTS.md` and linked docs.
- Hooks are configured through `hooks.json`.
- Supported hook moments here are `SessionStart`, `UserPromptSubmit`, and `PreToolUse`.
- MCP servers are added with `codex mcp add`.
- Sandboxed one-shot runs use `codex exec -s <sandbox> -C <dir>`.

Do not document or depend on unsupported hook moments.

## Known Migration Workflow Checks

- Private migrated memory target: `/root/.codex/openclaw-memory/`.
- Do not put the migrated corpus in Codex's auto-managed memories store. Codex owns and rewrites that store.
- The digest hook hash does not need re-trusting for script-body changes. The trusted hash covers the `hooks.json` entry.
- A root file named `.codex` breaks Codex startup because Codex expects `.codex/` to be a directory.
