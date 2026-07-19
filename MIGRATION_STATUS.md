# Migration status — Claude Code ➜ Codex

Short version: the project works from Codex now. Nothing Claude-related was deleted, so
both tools work side by side until you decide to retire one.

Full detail: [`docs/migration/MIGRATION_REPORT.md`](docs/migration/MIGRATION_REPORT.md).

## Completed

- Shared rule book in the repo: `docs/agents/PROJECT_RULES.md`, plus `WORKFLOWS.md`,
  `MEMORY_GUIDE.md` and `memory/INDEX.md`. Plain language, no tool-specific wording.
- `AGENTS.md` points coding agents at those rules. 7 lines appended at the end; the live
  Discord bot's personality text is untouched.
- Removed a zero-byte `.codex` file from the repo root. That file stopped Codex from
  starting in this project at all — the single biggest blocker found.
- Codex's own instruction file gained the plain-language rule, the Pacific-time rule and
  the private machine facts. The plain-language rule — the top priority — had been missing.
- `/todo` and session-close commands added for Codex.
- Fixed Codex's start-up hook, which had been silently dropping the unresolved-alerts
  banner.
- All 208 memory files copied to `/root/.codex/openclaw-memory/`, with a README covering
  layout and upkeep. Link health measured before and after: identical.
- Two tool servers working under Codex: `sec-edgar` and `exa`. Keys are read at run time,
  never copied into config.
- **Unrelated fix:** the `openclaw-gateway` service, which powers the bot's `@mention`
  replies, had been dead for 19 hours before this work began. Diagnosed, fixed, running.

## Partial

- **Turn-end safety checks are weaker.** Claude ran two scripts at the end of every reply:
  one re-ran affected tests when work was claimed done, one blocked unverified claims.
  Codex has no equivalent event. The rules are written down, but nothing enforces them
  automatically now. Push-time and CI checks are unaffected.
- The same rules now live in both `CLAUDE.md` and `docs/agents/PROJECT_RULES.md`. That is
  deliberate for the transition. Retire `CLAUDE.md` only once Codex has proven itself.

## Blocked

- **The `github` tool server needs a token.** It is configured and its container image is
  downloaded, but the token exists only as plain text inside Claude's config and was not
  copied. See "Manual" below.

## Manual — needs a person

1. **Add the GitHub token** to `/root/.openclaw/.env.service` as
   `GITHUB_PERSONAL_ACCESS_TOKEN`. The value currently lives in one root-only file
   (`/root/.claude.json`, permissions 600) and was deliberately not copied by an
   automated step. It is a classic token with `repo` and `workflow` rights, meaning full
   write access to every repository on the account and the ability to change CI files.
   Better than copying it: create a fine-grained token limited to this one repository,
   with an expiry date, and use that instead.
2. ~~Run four `setfacl` commands~~ — **done.** Codex can now work directly in the live
   workspace. Verified by running Codex there and having it read files.
3. **Merge this branch** to remove the stray `.codex` file for good. It is not urgent:
   Codex works from the live workspace even with the file present. It only breaks when
   Codex is started from the linked copy under `/root`. See the report for detail.
4. **Try `/todo open` once in Codex.** How Codex passes command arguments could not be
   confirmed from the docs on this machine. If it misbehaves it is a one-line fix.

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
