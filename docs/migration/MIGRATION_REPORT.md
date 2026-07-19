# Migration Report — Claude Code ➜ Codex

Date: 2026-07-19. Branch: `migration/claude-to-codex`.

## 1. Executive summary

The project can now be worked on from Codex CLI. Nothing belonging to Claude Code was
deleted, so both tools work until you decide otherwise.

Three things made this possible:

1. **A shared rule book in the repository.** `docs/agents/PROJECT_RULES.md` is the
   working rules — plain language, no tool-specific wording — plus supporting docs for
   workflows and memory. Any coding tool can read them. `CLAUDE.md` is untouched and
   still works; for now the same rules exist in both places on purpose.
2. **A private Codex setup on this machine.** `/root/.codex/AGENTS.md` gained the
   plain-language communication rule, the Pacific-time rule, and the private facts that
   must never go in the public repo. Codex also got the `/todo` and session-close
   commands, a fixed startup alert hook, and two working MCP tool servers.
3. **A copy of the knowledge base.** All 208 memory files were copied to
   `/root/.codex/openclaw-memory/`. Link health was measured before and after and is
   identical, so nothing was lost or broken.

**The single most important finding:** a zero-byte file named `.codex` at the repository
root stopped Codex from starting in this project at all. Every Codex command aimed at the
repo failed with `Failed to read project hooks config file .../.codex/config.toml: Not a
directory`. Codex expects `<repo>/.codex/` to be a folder, and a file of the same name
blocks it. Removing that file is what makes Codex usable here, and this branch removes it.

**One thing fixed along the way that was not part of the migration:** the
`openclaw-gateway` background service had been dead for 19 hours, since 2026-07-18
17:21 PDT — before this work started. That service is what powers the bot's `@mention`
replies. It is fixed and running again. Details in section 8.

## 2. Codex access — what was tested and what works

Codex CLI 0.144.6 at `/usr/bin/codex`, model `gpt-5.5`, already logged in.

| Check | Result |
|---|---|
| Run a command, read files, list hidden files | Works |
| Create, read, append, delete a file in the work area | Works |
| Run shell commands | Works |
| Read files outside the project | Works |
| Write access with `--write` (sandbox `workspace-write`) | Works |
| Approval prompts | Set to `never`; it does not stop to ask |
| Network access while in write mode | Off by default |
| `git` | Does **not** work from inside the sandbox — see below |
| Startup hooks (`SessionStart`, `UserPromptSubmit`) | Fire correctly |
| MCP tool servers | 2 of 3 working, 1 needs a token — section 9 |

**Codex cannot run git here, by design.** The work area is a linked copy (a git
"worktree") whose real git folder lives under the owner's home directory, which the
sandbox cannot reach. So Codex edits files and a supervising session runs every git
command. That split worked fine.

**Codex cannot work directly in the live workspace.** Codex's Linux sandbox builds a
private user namespace where only the root user is mapped. Inside it, root loses its
usual override powers over files owned by the `openclaw` user, and
`/home/openclaw` (permissions 750) plus `/home/openclaw/.openclaw` (700) become
impassable — the exact error is `bwrap: Can't find source path ... Permission denied`.
The fix is in section 9. As a side effect, the secret files under `/home/openclaw` are
unreachable from Codex, which is a good thing.

## 3. What was found

- Instructions: `CLAUDE.md` (the project rule book), a global rule file, `comm-check.md`
  (a writing-quality rubric), and `AGENTS.md` at the repo root.
- `AGENTS.md` is **not** a coding-agent file. It is the live personality file for the
  Discord bot, which reads it every session. It says `CLAUDE.md` is authoritative, but
  Codex reads `AGENTS.md` and never reads `CLAUDE.md` — the core conflict this migration
  had to solve.
- `.claude/` inside the repository is a **data folder**, not tool config. Live code reads
  it: the feature go-live evidence gate, four backtests, the options flow shadow logs and
  the `!all` command's comparison log. It must never be renamed.
- Memory: 208 markdown files plus 2 old backups, in three tiers.
- Claude-only machinery with no Codex equivalent: two turn-end hooks, the plugin system,
  and automatic memory loading.
- A Codex setup already existed but was out of date.
- **No Anthropic SDK or API is used anywhere in the code.** Claims in `USER.md` and
  `CHANGES.md` that an Anthropic API does the text parsing are simply stale; the engine
  uses OpenRouter. So there was no model dependency to unwind.

## 4. Mapping — where each thing went

| From | To | What changed |
|---|---|---|
| `CLAUDE.md` | `docs/agents/PROJECT_RULES.md` | Rewritten in tool-neutral plain language. Every operative rule kept. Original untouched. |
| Workflow rules in `CLAUDE.md` + `todo/SESSION_CLOSE.md` | `docs/agents/WORKFLOWS.md` | The TODO system, the `bye` close routine, and what replaces the Claude-only cleanup steps. |
| Memory design | `docs/agents/MEMORY_GUIDE.md`, `docs/agents/memory/INDEX.md` | How to use and maintain the knowledge base. Categories only, no private facts. |
| `AGENTS.md` | same file | 7 lines appended at the end. No existing line touched. Bot behaviour unchanged. |
| Global Claude rules | `/root/.codex/AGENTS.md` | Added the missing plain-language rule, the Pacific-time rule, working-style rules, and private facts. |
| `.claude/commands/todo.md` | `/root/.codex/prompts/todo.md` | Ported as a Codex `/todo` command. |
| `todo/SESSION_CLOSE.md` | `/root/.codex/prompts/session-close.md` | New Codex command for the `bye` routine. |
| `/root/.claude/hooks/openclaw-digest.sh` | `/root/.codex/hooks/openclaw-digest.sh` | Replaced the stale copy. The old one silently dropped the unresolved-alerts banner. |
| MCP servers in Claude's config | Codex global config | Recreated. Keys are read at run time, never copied. |
| 208 memory files | `/root/.codex/openclaw-memory/` | Copied, not moved. Structure and links preserved exactly. |

## 5. Files created, changed, and left alone

**Created in the repository (public):**

- `docs/agents/PROJECT_RULES.md`
- `docs/agents/WORKFLOWS.md`
- `docs/agents/MEMORY_GUIDE.md`
- `docs/agents/memory/INDEX.md`
- `docs/migration/codex-plan.md` (Codex's own plan, kept as a record)
- `docs/migration/MIGRATION_REPORT.md` (this file)
- `MIGRATION_STATUS.md`

**Changed in the repository:** `AGENTS.md` (7 lines appended at the end).

**Removed from the repository:** the zero-byte `.codex` file at the root — the blocker in
section 1.

**Created outside the repository (private to this machine):**

- `/root/.codex/prompts/todo.md`, `/root/.codex/prompts/session-close.md`
- `/root/.codex/openclaw-memory/` — 205 topic files, 2 indexes, 3 archived snapshots, plus
  a new `README.md` explaining the layout and how to keep it up to date
- Additions to `/root/.codex/AGENTS.md`; MCP entries in `/root/.codex/config.toml`;
  refreshed `/root/.codex/hooks/openclaw-digest.sh`

**Deliberately left exactly as they were:** `CLAUDE.md`, `comm-check.md`, everything under
`.claude/`, all global Claude files, and the whole Claude plugin setup.

**Backups** of every file changed outside the repository are in
`/root/codex-migration-handoff/`, ending in `.bak`.

## 6. What could not be migrated

- **Turn-end checks.** Claude runs two scripts when a reply finishes: one re-runs affected
  tests when you claim work is done, one blocks unverified claims like "X is expired".
  Codex has no equivalent event — it only has session-start, prompt-submit and
  before-tool-use. The rules were written into `PROJECT_RULES.md`, but they are now a
  habit rather than something enforced automatically. **This is a real reduction in
  safety.** The push-time regression gate and CI still run and are unaffected.
- **Plugins.** The plugin marketplace, the `discover` research tool, and the orchestration
  layer are Claude-specific. Keep Claude installed while you still want them.
- **Automatic memory loading.** Claude loads the memory index every session by itself.
  Codex will not. It is told where to look instead, which depends on it choosing to read.
- **Windows desktop routines** under `windows_runtime/` are a separate product and out of
  scope.

## 7. Deliberately excluded, and why

- **Nothing was deleted from the Claude setup.** The instruction was to keep it until the
  new setup is proven.
- **The same rules now exist in both `CLAUDE.md` and `docs/agents/PROJECT_RULES.md`.**
  That duplication is intentional for the transition. Retire `CLAUDE.md` only after real
  Codex sessions have proven themselves.
- **No private fact went into the repository.** The repo is public. Real names, the
  Discord webhook, channel IDs and email addresses stayed on the private side.
- **Memory files were kept flat rather than sorted into folders.** The corpus has 315
  internal links written as relative paths; moving files would have broken them for no
  real benefit, since the category is already the filename prefix.
- **A stale approval rule in `/root/.codex/rules/default.rules` was left alone.** It
  mentions an old plugin version, but two of its four paths still exist, so it could not
  be proven unused. Reported rather than deleted.
- **The cross-family reviewer ban in `scripts/ci_ai_fixer.py` was not touched.** It blocks
  `anthropic/` models from reviewing. The reasoning behind it changes if Codex becomes the
  main author, but tests assert the current behaviour, so this is your decision.

## 8. Validation — what was run and what came back

| Check | Result |
|---|---|
| Both background services active | Pass — `consensus-engine` and `openclaw-gateway` both active |
| `/root/.openclaw` still points to `/home/openclaw/.openclaw` | Pass |
| Broken links in the new docs | 0 broken out of all relative links checked |
| Secret scan of every new or changed public file | 0 findings (webhooks, keys, tokens, emails, Discord IDs) |
| Memory corpus copied completely | Pass — 205 + 2 + 3 files, none dropped |
| Memory link health, before vs after | Identical: 315 links, same 142 unresolved, same 33 loose `[[links]]` — all pre-existing |
| Codex starts and its hooks fire | Pass — verified with a real `codex exec` run |
| `sec-edgar` MCP server | Pass — real handshake, "SEC EDGAR MCP" v1.26.0 |
| `exa` MCP server | Pass — key resolved at run time and the server connected |
| `github` MCP server | Blocked — token not on this machine outside Claude's config |
| Full test suite vs `.test-baseline` | See "Test results" below |

Commands used:

```bash
systemctl is-active consensus-engine.service openclaw-gateway.service
python3 -m pytest tests/ -q --color=no          # compare against .test-baseline
codex exec -s read-only -C /root/codex-migration-work "reply with exactly OK"
codex mcp list
```

**Test results:** 2992 passed, 10 skipped, 2 deselected, 0 failed, in 12 minutes 22
seconds. No regressions: no test that was passing before is failing now. The one test
listed in `.test-baseline` as a known failure
(`tests/test_i13_apewisdom_zscore.py::test_baseline_two_days_std`) actually passed this
run — it depends on how much data has accumulated, so it comes and goes. It was left in
the baseline file rather than removed, because one passing run is not proof it is stable.

**Independent re-read by a fresh Codex session.** A clean Codex session was told to
pretend `CLAUDE.md` and `comm-check.md` did not exist, start only from `AGENTS.md`, and
answer five questions about the rules, citing file and line for each. It found all five
correctly — the rules location and the "do not adopt the bot persona" instruction, the
Pacific-time rule, the evidence standard, the regression gate and baseline file, and the
private knowledge base with the never-publish list. Its verdict was that a coding agent
could work on this project from these docs alone.

It also found two real gaps, both since fixed:

1. The always-checks were described but the actual commands were missing, so a new agent
   could not run them. The exact commands are now in `PROJECT_RULES.md`, including how to
   revive the gateway and how to confirm it is really serving.
2. `AGENTS.md` still said `CLAUDE.md` was authoritative, which contradicted the new
   coding-agent section. The appended section now states the order of precedence plainly:
   that line describes the Discord bot, and for coding work `PROJECT_RULES.md` wins.

**The gateway outage.** While running the always-required health checks, the
`openclaw-gateway` service was found dead — failed since 2026-07-18 17:21 PDT, about 19
hours before, and unrelated to this migration. The cause was a leftover file,
`update-check.json`, that recorded when the tool last checked for an update. Its contents
disagreed with the newer database that replaced it, so the startup upgrade step refused to
finish, and the service refused to report itself ready. It had crash-looped ten times and
systemd had given up restarting it. The file held nothing but a date and a version number
from 2026-07-01, so it was backed up and removed, and the service was restarted. It is now
active and accepting connections on port 18789. Backup:
`/root/codex-migration-handoff/update-check.json.bak`.

**Remaining Claude references: 174 tracked files.** All are intentional and fall into
three groups. First, `.claude/` used as a **live data path** by working code — the go-live
evidence gate, the `!all` comparison log, backtest outputs and the CI fixer's protected
list. These must not change. Second, historical records under `todo/`, `plans/`,
`docs/superpowers/` and `.claude/discover/` that describe what happened at the time.
Third, genuinely stale wording in `USER.md` and `CHANGES.md` claiming an Anthropic API is
used for text parsing — untrue, and listed in section 11 as a later cleanup rather than
changed now, to keep this pass non-destructive.

## 9. Manual setup you may still want

**1. Add the GitHub token so the third tool server works.** The GitHub MCP server is
configured and its container image is already downloaded, but the token only exists inside
Claude's config file as plain text. It was not copied. To finish it, add a line naming
`GITHUB_PERSONAL_ACCESS_TOKEN` to `/root/.openclaw/.env.service`. **Rotate that token
first** — it has been sitting in a plain-text config file.

**2. Let Codex work directly in the live workspace.** Today Codex works in a copy under
`/root` because it cannot reach the real folder. To change that, run these as root — they
grant only the `root` user passage, and change nothing for anyone else:

```bash
setfacl -m u:root:x /home/openclaw
setfacl -m u:root:x /home/openclaw/.openclaw
setfacl -R -m u:root:rwX /home/openclaw/.openclaw/workspace
setfacl -R -d -m u:root:rwX /home/openclaw/.openclaw/workspace
```

These could not be run automatically — the permission system blocked them twice, so they
are left for you to run deliberately. Afterwards:

```bash
cd /home/openclaw/.openclaw/workspace
codex                                    # interactive
codex exec -s workspace-write "<task>"   # one-shot
```

The blunt fallback, if you would rather not use the commands above, is
`codex exec -s danger-full-access "<task>"`. That turns the sandbox off completely, so
Codex could reach the secret files and anything else on the machine. Prefer the ACL route.

**3. Merge this branch** to remove the `.codex` file for good.

Correcting an earlier claim in this report: it previously said Codex would keep failing
from the live workspace until this branch merged. That is **not true**, and was tested
afterwards. The blocker depends on where Codex is started from:

- Started from the **linked copy** at `/root/codex-migration-work`: still fails. Codex
  works out the project root from git, lands on the live workspace, finds the `.codex`
  file and stops.
- Started from the **live workspace** itself: works. Both `codex exec` and
  `codex mcp list` succeed there with the file still present.

This could not have been checked earlier, because before the ACL commands above were run
Codex could not enter the live workspace at all. So the merge is worth doing to clear the
file, but it is not blocking day-to-day use from the live workspace.

**4. Check the `/todo` command once by hand.** How Codex fills in a command's arguments
could not be confirmed from the documentation on this machine. Run `/todo open` in a Codex
session; if the arguments do not come through, the fix is a one-line edit to
`/root/.codex/prompts/todo.md`.

**If the plugin route is ever unavailable**, this is the direct command that does the same
job, with no plugin involved:

```bash
codex exec -s workspace-write -C /root/codex-migration-work --add-dir /root/.codex "<task>"
```

## 10. How to undo all of this

Nothing here is hard to reverse.

```bash
# 1. Drop the branch and the work area
git worktree remove /root/codex-migration-work --force
git branch -D migration/claude-to-codex

# 2. Restore the private Codex files from their backups
cp /root/codex-migration-handoff/AGENTS.md.codex-original.bak        /root/.codex/AGENTS.md
cp /root/codex-migration-handoff/config.toml.codex-original.bak      /root/.codex/config.toml
cp /root/codex-migration-handoff/openclaw-digest.sh.codex-original.bak /root/.codex/hooks/openclaw-digest.sh

# 3. Remove what was added
rm -rf /root/.codex/openclaw-memory /root/.codex/prompts

# 4. If the ACLs in section 9 were applied and you want them gone
setfacl -b /home/openclaw
setfacl -b /home/openclaw/.openclaw
setfacl -R -b /home/openclaw/.openclaw/workspace
```

Claude Code needs no restoring — it was never changed. Undoing the gateway fix is not
recommended; that service was simply broken.

## 11. Worth cleaning up later

Found while auditing, deliberately left alone to keep this pass safe:

- **The pre-commit hook never runs.** Git's `core.hooksPath` points at
  `.git/hooks`, which contains only `pre-push`. The tracked `.githooks/pre-commit`, which
  checks that model settings stay in sync, has therefore never fired. The push-time
  regression gate is live and unaffected.
- Stale claims in `USER.md` and `CHANGES.md` that an Anthropic API parses text. It does
  not; OpenRouter does.
- `/root/task_system/scripts/ci-monitor.sh` line 3 says it launches Claude to fix failures.
  It does not — it hands off to another script that explicitly avoids Claude. Comment only.
- `/root/.claude/hooks/lib/stdin.mjs` points at a plugin version that no longer exists.
- The memory index is about 19KB against its own 17KB limit; 9 files still say
  `description: TODO`; 33 `[[links]]` do not match a filename.
- `/root/.codex/hooks.json` runs a display script from `/root/.claude/hud/`. If Claude is
  ever removed, that path must be changed first or the Codex display breaks.
- `openclaw.json` points the bot's memory search at Claude's memory folder. That folder
  must stay where it is unless `openclaw.json` is updated in the same change.
- `/root/scripts/update_plugins.sh`, a 3am scheduled task, is the only automation that
  still calls the `claude` command. Retire it only when you retire Claude.
- Decide the cross-family reviewer question in section 7.
