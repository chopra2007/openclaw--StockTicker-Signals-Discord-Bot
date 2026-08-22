# Migration status — Claude Code ➜ Codex

Short version: the project works from Codex now. Nothing Claude-related was deleted, so
both tools work side by side until you decide to retire one.

Full detail: [`MIGRATION_REPORT.md`](MIGRATION_REPORT.md).

Updated 2026-07-25 after the native Codex plugin and safety-check setup.

## Completed

- Shared rule book in the repo: `docs/agents/PROJECT_RULES.md`, plus `WORKFLOWS.md`,
  `MEMORY_GUIDE.md` and `memory/INDEX.md`. Plain language, no tool-specific wording.
- `AGENTS.md` points coding agents at those rules. 7 lines appended at the end; the live
  Discord bot's personality text is untouched.
- Removed a zero-byte `.codex` file from the repo root. That file stopped Codex from
  starting in this project at all — the single biggest blocker found.
- Codex's own instruction file gained the plain-language rule, the Pacific-time rule and
  the private machine facts. The plain-language rule — the top priority — had been missing.
- Native OpenClaw workflow skills added for Codex. Use `$todo open` for the TODO list and
  `$session-close` for the close routine. `/todo` is only a compatibility phrase inside a
  normal prompt, not a real slash command.
- Fixed Codex's start-up hook. It keeps the unresolved-alert banner, but no longer injects
  raw conversation text; it points Codex to the private memory router instead.
- The private memory copy now has 208 topic files. Four newer Claude topics were synced
  after the original migration, with concise links added to the private router.
- Four tool servers are configured under Codex: `sec-edgar`, `exa`, GitHub and Context7.
  Keys are read at run time, never copied into config.
- The official `oh-my-codex` 0.20.3 package is installed and enabled. Firecrawl and
  Superpowers are also installed and enabled. The native `openclaw-workflows` plugin,
  version `0.1.0+codex.20260725212304`, provides the two workflow skills above.
- The project-specific Discover workflow now has a native Codex plugin. Version
  `0.1.0+codex.20260725205158` is installed and enabled; its implementation checks pass.
- The affected-test and unverified-claim scripts are configured at both `Stop` and
  `SubagentStop`. All 9 synthetic tests pass, live `Stop` enforcement passed after trust
  was saved, and independent verification passed.
- **Unrelated fix:** the `openclaw-gateway` service, which powers the bot's `@mention`
  replies, had been dead for 19 hours before this work began. Diagnosed, fixed, running.

## Partial

- The same rules now live in both `CLAUDE.md` and `docs/agents/PROJECT_RULES.md`. That is
  deliberate for the transition. Retire `CLAUDE.md` only once Codex has proven itself.

## Blocked

Nothing.

## Manual setup record

1. ~~Add the GitHub token~~ — **done, and it needed no copying.** The token was already in
   `/root/.openclaw/.env.service` under the name `GITHUB_TOKEN`, and it is the same value
   that sits in Claude's config. Codex's `github` server now reads that name. Verified
   working: the server authenticated and fetched its permissions back from GitHub.

   Still worth doing when convenient: this is a classic token with `repo` and `workflow`
   rights — full write access to every repository on the account, plus the ability to
   change CI files, and no expiry date. A fine-grained token limited to this one
   repository, with an expiry, would do the same job with far less at stake. Swapping it
   means changing one line in `.env.service`; nothing else needs to change.
2. ~~Run four `setfacl` commands~~ — **done.** Codex can now work directly in the live
   workspace. Verified by running Codex there and having it read files.
## Safe to remove once you have confirmed Codex works for you

Not yet — keep all of it until real Codex sessions have proven themselves.

- `CLAUDE.md` and `comm-check.md` (their content now also lives in `docs/agents/`).
- The Claude plugin setup and `/root/scripts/update_plugins.sh`, the 3am task that is the
  only automation still calling the `claude` command.

Do **not** remove these, whatever you decide about Claude:

- Anything under `.claude/` in the repo. Despite the name it is a **data** folder that
  live code reads — the feature go-live gate, backtest outputs, and the `!all` comparison
  log all depend on those paths.
- `/root/.claude/projects/.../memory/`, which the Discord bot still reads at run time.
- `/root/.claude/hud/`, which Codex's own display script still calls.
