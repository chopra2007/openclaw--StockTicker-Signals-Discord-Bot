# Public Memory Index

This is a sanitized routing index.

It tells coding agents what kind of private memory may exist. It does not contain private facts.

For OpenClaw work, start with:

`/root/.codex/openclaw-memory/MEMORY.md`

Then read one or two relevant private topic files.

## Categories

Communication rules:

- Plain-language writing.
- Pacific-time display.
- How to answer owner questions without jargon.
- When to use `comm-check.md`.

Verification traps:

- Definition of Done.
- Scoped check buckets.
- Regression gate behavior.
- Evidence needed before saying a task is complete.
- Known checks that can pass for the wrong reason.

Runtime architecture:

- Engine background program.
- Gateway background program.
- Discord command paths.
- Agent mention path.
- Data ingest paths.
- `.claude/` directories that are still live data paths.

Model-chain notes:

- Runtime model-chain ownership.
- Gateway drift checks.
- Safe ways to change model config.
- Stale public wording to clean up later.

Data-source gotchas:

- Quote and historical price source limits.
- SEC filing rules.
- Video ingest limits.
- Search-provider limits.
- Social-source data limits.

Current-task pointers:

- Active migration work.
- Open TODOs that need private context.
- Soaking work that is collecting evidence.
- Parked work blocked by outside access or cost.

Historical project records:

- Old decisions that explain current shape.
- Debugging histories worth preserving.
- Obsolete notes that should not drive new work.

Private pointers:

- Where private credential instructions live.
- Which files must not be opened or copied into public docs.
- Which runtime paths contain private local state.

## Public Docs To Read Next

- `docs/agents/PROJECT_RULES.md`
- `docs/agents/WORKFLOWS.md`
- `docs/agents/MEMORY_GUIDE.md`
- `todo/CONVENTION.md`
- `todo/SESSION_CLOSE.md`

## Public Safety Rule

Do not copy private memory into this repo.

Do not write API keys, token values, webhook URLs, email addresses, Discord user IDs, real personal names, or credential-file contents into public docs.
