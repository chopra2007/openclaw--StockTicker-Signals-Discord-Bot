# Memory Guide

This guide explains how coding agents should use memory for this project.

Public repo docs must stay sanitized. Private facts belong outside the repo.

## Memory Order

Use memory in this order:

1. Private Codex corpus: `/root/.codex/openclaw-memory/MEMORY.md`.
2. Public repo docs, especially `docs/agents/PROJECT_RULES.md` and `docs/agents/WORKFLOWS.md`.
3. Live files in the checkout.

Use the private corpus when the task touches:

- Project behavior.
- Runtime config.
- Operations.
- Past decisions.
- Known traps.
- Current migration work.

Skip private memory for tiny self-contained tasks.

## Private Corpus Shape

The private migrated corpus lives at:

`/root/.codex/openclaw-memory/`

Actual shape as migrated:

- `README.md`: what the corpus is and how to maintain it.
- `MEMORY.md`: short router. Read this first.
- `indexes/`: larger routing files (`project-index.md`, `comm-check-index.md`).
- The detailed topic files sit flat alongside `MEMORY.md`. The category is the filename
  prefix: `feedback_`, `reference_`, `project_`, `comm-check-fail-`, `user_`.
- `archive/`: obsolete snapshots, not part of the live corpus.

The files were kept flat on purpose. The corpus has 315 internal links written as
relative paths, so moving files into folders would have broken them for no real gain.

The top-level `MEMORY.md` should stay a router. It should point to one or two useful files, not repeat every detail.

Do not use Codex's auto-managed memories store for this corpus. Codex owns that store and may rewrite it.

## Public Memory Docs

Public memory docs may name categories and safe paths only.

Allowed:

- Category names.
- Public file paths.
- Safe architecture facts.
- How to choose the next file to read.
- Maintenance rules.

Not allowed:

- API keys.
- Token values.
- Webhook URLs.
- Email addresses.
- Discord user IDs.
- Real personal names.
- Private account details.
- Credential-file contents.

## Reading Rules

Do not bulk-load memory.

1. Read `/root/.codex/openclaw-memory/MEMORY.md`.
2. Pick one or two linked topic files that match the task.
3. Stop when you have enough context.
4. Verify live facts from the repo or running system before claiming they are current.

If private memory conflicts with live files, trust live files for current behavior. Keep the memory note as history.

## Writing New Memory

When a durable lesson appears:

1. Put private facts in a new topic file in `/root/.codex/openclaw-memory/`, named with the matching category prefix (`feedback_`, `reference_`, `project_`, `user_`).
2. Add one short routing line to `/root/.codex/openclaw-memory/MEMORY.md`.
3. Put public agent rules in `docs/agents/PROJECT_RULES.md` only when every coding agent should follow them.
4. Put repeated workflow steps in `docs/agents/WORKFLOWS.md`.
5. Keep public docs free of private facts.

Good private topic categories:

- `behavior`
- `coding-standard`
- `operations`
- `architecture`
- `current-task`
- `history`
- `obsolete`
- `private-pointer`

## Maintenance

Future sessions should keep memory small and useful.

- Move shipped or dormant current-task lines out of the top router and into an index.
- Keep full debugging steps in topic files when the steps matter.
- Do not compress a hard-won fix into one vague sentence.
- Do not copy obsolete backups into the active router.
- Run a link check before public memory-doc changes are committed.
- Run a public secret scan before public memory-doc changes are committed.

## Migration Notes

- The private migration target is `/root/.codex/openclaw-memory/`.
- The old Claude memory tree may still be read by runtime code. Do not move or delete it during the migration.
- A zero-byte repo-root file named `.codex` breaks Codex startup here. Codex expects `.codex/` to be a directory.
- The digest hook does not need re-trusting when only its script body changes. The trusted hash covers the `hooks.json` entry.
