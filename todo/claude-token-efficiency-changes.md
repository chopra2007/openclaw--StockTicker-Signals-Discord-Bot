# Claude token-efficiency changes (2026-09-22) and how to undo them

**Status:** AWAITING APPROVAL
**Created:** 2026-09-22

**CURRENT STATUS (2026-09-22):** Three small changes are live and a new helper exists. One planned change is still waiting on the user: deleting the status-bar hook that pastes the usage bar into every message. Claude's own safety check blocked Claude from editing its settings, so the user decides and makes that edit by hand. Everything can be undone with one script (commands below).

## What changed

| Change | File | Effect |
|---|---|---|
| Compact session-start text | `/root/.claude/hooks/openclaw-digest.sh` | 10,494 → 3,075 characters. Repeated alerts collapse into one line with a count, long lines are cut to 140 characters (the full text path is shown), and only the newest 5 #errors messages appear, with a command to see the rest. The OpenClaw memory note is skipped when it is older than 14 days (it was 125 days old). Every alert now actually reaches Claude. Before, Claude Code showed only a 2 KB preview of the old 10 KB text. |
| Tighter project instructions | `CLAUDE.md` (workspace) | 15,551 → 15,160 characters, no rule removed. Commit `7b69ccb`. |
| New "Token Use" section | `/root/.claude/CLAUDE.md` | Tells Claude to read files once, avoid whole-file rewrites, use `bounded-run` for noisy commands, and keep endings brief. |
| New helper | `~/.local/share/cli-token-efficiency/bin/bounded-run` | Runs a noisy command, saves the full output to a file, and shows only the status, test counts and errors. A noisy test run went from 75,522 to 4,622 characters, with the error kept. It has 10 tests: `python3 ~/.local/share/cli-token-efficiency/bin/test_bounded_run.py` |

## Measured results

- Startup context per session: 45,024 → 45,708 tokens (+1.5%). The cost is slightly higher because all the alerts now show.
- Three practice tasks: 581,697 → 542,711 total tokens (−6.7%). That drop mostly comes from how many steps Claude happened to take, since there was only one run per task. Treat it as a smoke test.
- The 50% target was not reached. The real saving shows up on noisy commands, when `bounded-run` is used.

## Waiting on the user (the approval question)

Should the status-bar hook be removed? In `/root/.claude/settings.json`, delete the `UserPromptSubmit` entry whose command is
`node $HOME/.claude/hud/omc-hud.mjs --hook`. It pastes about 330 characters of usage bar into every message. The status bar on screen uses a separate command, so it keeps working. A backup of settings.json already exists (see below).

## How to undo

Record folder (report, manifest, backups, undo script, Codex handoff):
`~/.local/share/cli-token-efficiency/projects/-home-openclaw--openclaw-workspace/20260922/`

```bash
R=~/.local/share/cli-token-efficiency/projects/-home-openclaw--openclaw-workspace/20260922
$R/rollback.sh status                    # which files still match the changed version
$R/rollback.sh --dry-run --all           # preview, changes nothing
$R/rollback.sh --group hooks-settings    # undo the session-start text change only
$R/rollback.sh --group instructions      # undo both CLAUDE.md changes
$R/rollback.sh --group helpers           # delete bounded-run and its tests
$R/rollback.sh --file /root/.claude/CLAUDE.md   # undo one file
$R/rollback.sh --all                     # undo everything
```

The script refuses to overwrite a file edited after the change and shows the difference instead. Restored files get their original owner and permissions back. It was tested on copies: an undo gave back the exact originals, a redo gave back the new versions, and an edited file was refused.

After undoing the workspace `CLAUDE.md`, commit it as openclaw, not as root (`sudo -u openclaw git commit CLAUDE.md ...`).

## Considered and not done

- Plugin hook that pastes the workspace AGENTS.md and README.md on the first file touch: its only off switch also disables 3 other plugin hooks, and Claude Code already cuts it to a 2 KB preview.
- Superpowers plugin (about 1,000 tokens per session): turning it off removes skills in use.
- Headroom, 9Router and Caveman: evaluated, none installed. Reasons are in `report.md` in the record folder.
- MEMORY.md: reviewed and left unchanged, because it is already a trimmed index.

## Next steps

1. The user says yes or no to removing the status-bar hook. On yes, delete the entry by hand, then start a new session and check that the status bar still shows.
2. Optionally, re-measure a week from now: `cd ~/.local/share/cli-token-efficiency/bench && python3 bench.py later Z`. Compare `first_request_context_tokens` with 45,708.
3. Codex session: read `claude-handoff.md` in the record folder.
