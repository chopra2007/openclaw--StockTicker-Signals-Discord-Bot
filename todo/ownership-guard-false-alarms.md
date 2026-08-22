# Stop the ownership guard crying wolf every turn

**Status:** OPEN
**Created:** 2026-08-22

**CURRENT STATUS (2026-08-22):** Part A done and verified. `scripts/check_ownership.py` now has a
`SKIP_PATHS` list holding exactly one path — `.omc/state/idle-notif-cooldown.json`, the scratch
timestamp the `persistent-mode` add-on rewrites as root at the end of every turn. Verified live: with
that file deliberately root-owned, the guard reports "clean"; with a throwaway root-owned file next to
it, the guard still reports the throwaway. The directory stays guarded.

But the item's own goal — the guard stops crying wolf every turn — is NOT met, so this stays OPEN.
The cooldown file was never the only one. A single turn of this session left **53** root-owned files
in the bot's tree: `.omc/state/hud-stdin-cache.json`, `.omc/sessions/*.json`, the whole
`.omc/state/session-end-jobs/**` tree, and `identity/device-auth.json`. They all trip the guard, and
ignoring them one by one would blind it.

Part B is answered, and it settles the argument: the flip happens **only because the session runs as
root**. Proof — in the same directory in the same minute, a file written by an `openclaw` process
came out `openclaw`-owned while one written by this root session came out `root`-owned. So option 3
(run the session as `openclaw`) is the real fix and Part A is a patch. That work is now **TODO #91**
(`root-session-ownership-flip.md`). Next concrete step: pick up #91.

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

1. **Tell the guard to skip this ONE filename.** Add `idle-notif-cooldown.json` to an ignore list
   in `scripts/check_ownership.py` (the file currently has `SKIP_DIRS` at line 35 but no
   per-file ignore, so a small addition is needed). Smallest change.
   **Do NOT ignore the whole `.omc/state/` directory** — checked on 2026-08-22 and it holds real bot
   data: `calibration_model.pkl` (read by `consensus_engine/analysis/calibration.py`) and
   `news_cascade_brave_counter.json` (read by `consensus_engine/scanners/news.py`). Silencing the
   directory would blind the guard to both.
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

- ~~What else lives under `.omc/state/`?~~ Answered 2026-08-22: real bot data lives there
  (calibration model, news counter, SearXNG health). Ignore the single filename only, never the
  directory.
- ~~Does the same flip happen in sessions that are not run as root?~~ Answered 2026-08-22: **no.**
  A file written by an `openclaw` process in the same directory came out `openclaw`-owned. The flip
  is caused by the session running as root, so option 3 is the real fix — now TODO #91
  (`root-session-ownership-flip.md`).

### Session notes 2026-08-22

- Applied option 1: `SKIP_PATHS` in `scripts/check_ownership.py`, one exact path only.
- Verified: root-owned cooldown file present -> guard "clean"; root-owned throwaway
  `.omc/state/zzz-ownership-probe.json` -> guard reports it. Throwaway deleted.
- No tests reference `check_ownership` (grepped the repo).
- Handed 53 root-owned files back to `openclaw` with `--fix` while testing.
