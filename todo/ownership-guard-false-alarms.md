# Stop the ownership guard crying wolf every turn

**Status:** OPEN
**Created:** 2026-08-22

**CURRENT STATUS (2026-08-22):** Root cause found and proven, no fix applied yet. A background
add-on called `persistent-mode` rewrites one scratch file as root at the end of every Claude Code
turn. The ownership guard then blocks the turn and demands a fix. The fix is applied, the next turn
ends, the file flips back to root, and the guard fires again. This happened five times in one
session. Nothing real is broken — the file holds no bot data — but the guard that protects the live
options feed is now firing constantly for a harmless reason, which is exactly how a real alert gets
ignored. Next concrete step: decide between the two options below and apply it.

## The file

`/home/openclaw/.openclaw/workspace/.omc/state/idle-notif-cooldown.json`

Its entire contents are one timestamp:

```json
{ "lastSentAt": "2026-08-22T18:06:43.083Z" }
```

It is a cooldown clock so the add-on does not send the same idle notification twice. It carries no
bot data, no market data, and no configuration. The bot (`consensus-engine`) never reads it.

## What actually writes it — verified, not assumed

`/root/.claude/plugins/cache/omc/oh-my-claudecode/4.15.10/hooks/hooks.json` registers it:

```
EVENT: Stop | matcher: *
  node "$CLAUDE_PLUGIN_ROOT"/scripts/run.cjs "$CLAUDE_PLUGIN_ROOT"/scripts/persistent-mode.mjs
```

`Stop` means it runs at the end of every assistant turn. This Claude Code session runs as root, so
the file it writes is owned by root.

Timing proof from 2026-08-22:

```
11:06:38  check_ownership.py --fix ran, file handed back to openclaw
11:06:43  file rewritten, owner root again   (5 seconds later, same turn's Stop hook)
```

## What it is NOT

The user asked whether an earlier Codex session in the same project caused it. Checked and ruled
out. Five Codex processes are running as root:

```
2797  2812  154967  2332907  2332923
```

`lsof` on every one of them returns nothing under `.omc`. No Codex process holds any file in that
directory. The cause is this Claude Code session's own Stop hook.

## Why it matters

The ownership guard exists because root-owned files in the bot's tree break the `openclaw` user
silently. That is not theoretical — it killed the Schwab options feed for 2.1 days on 2026-08-17
(see `reference_schwab_token_ownership_trap`). A guard that fires five times a session for a
throwaway timestamp file trains everyone to slap it away without reading it. The next time it points
at a real token file, it gets slapped away too.

## Possible fixes, priority-ordered

1. **Tell the guard to skip this path.** Add `.omc/state/` to the ignore list in
   `scripts/check_ownership.py`. Smallest change. Correct because nothing under `.omc/state/` is bot
   data — it is Claude Code session scratch, not part of the trading bot. Risk: if anything the bot
   DOES need ever lands under `.omc/`, the guard would go quiet on it. Worth checking what else is
   in that directory before widening the pattern; consider ignoring only the one filename.
2. **Make the add-on write as `openclaw`.** Cleaner in principle, but the add-on lives in
   `/root/.claude/plugins/cache/` and is overwritten on every plugin update, so any edit there is
   temporary. Would need to be re-applied after each update — that is the same trap that wiped the
   plugin cache before (`reference_plugin_cache_wiped`).
3. **Run the whole Claude Code session as `openclaw` instead of root.** Fixes this and every future
   variant of the same problem at once, since root-owned files would stop being created at all. Much
   larger change with its own knock-on effects — treat as a separate piece of work, not a quick fix.

## Files involved

- `scripts/check_ownership.py` — the guard
- `/root/.claude/hooks/ownership-on-done.py` — the Stop hook that blocks the turn
- `/root/.claude/plugins/cache/omc/oh-my-claudecode/4.15.10/hooks/hooks.json` — registers the writer
- `/root/.claude/plugins/cache/omc/oh-my-claudecode/4.15.10/scripts/persistent-mode.mjs` — the writer

## Open questions

- What else lives under `.omc/state/`? Decide whether to ignore the one filename or the directory.
- Does the same flip happen in sessions that are not run as root? If not, option 3 is the real fix
  and options 1 and 2 are just papering over it.
