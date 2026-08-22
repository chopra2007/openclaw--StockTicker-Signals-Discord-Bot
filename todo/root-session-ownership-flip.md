# Run the Claude Code session as `openclaw` so it stops leaving root-owned files

**Status:** OPEN
**Created:** 2026-08-22

**CURRENT STATUS (2026-08-22):** Not started — this is the follow-up split out of #90 (Part B).
Proven on 2026-08-22: the root-ownership flip happens *only* because the Claude Code session runs
as `root`. Every file the session or its add-ons write in the bot's tree lands root-owned, and the
bot (which runs as `openclaw`) then cannot write it. One turn of this session left **53** such
files behind. Next concrete step: work out what breaks if the session runs as `openclaw` (plugin
cache under `/root/.claude`, hooks, git credentials) and try it.

## The proof

Same directory, same minute, two writers:

```
root writes    -> -rw-rw-r-- root     root     .omc/state/hud-stdin-cache.json
openclaw writes-> -rw-rw-r-- openclaw openclaw .omc/state/zzz-asopenclaw.json
```

The owner simply follows whoever runs the process. Nothing about the add-ons is special. So any
per-file ignore list (what #90 did) only hides one symptom.

## What it actually costs today

- 53 root-owned files after a single turn of a root session on 2026-08-22 — `.omc/state/`,
  `.omc/sessions/`, `.omc/state/session-end-jobs/**`, `identity/device-auth.json`.
- On 2026-08-22 the same cause left seven git files root-owned after a commit, including
  `.git/index` and `.git/refs/heads/master`. That one genuinely breaks pushes.
- It killed the Schwab options feed for 2.1 days on 2026-08-17 (`reference_schwab_token_ownership_trap`).

## Why it is not a quick fix

Running the session as `openclaw` moves everything the session depends on out from under `/root`:
the plugin cache (`/root/.claude/plugins/cache`), the hooks in `/root/.claude/hooks/`, the task
system under `/root/task_system/`, and the git push credentials. Each needs checking before the
switch, and a half-done switch is worse than today (files owned by a third mix of users).

## Cheaper partial options, if the full switch is too big

1. Give the whole bot tree the setgid bit + a shared group so group-write survives a root write.
   Fixes writability without changing who the session runs as. Does not fix owner-only operations.
2. Run `python3 scripts/check_ownership.py --fix` automatically at the end of every turn instead of
   blocking on it. Turns the alarm into a repair. Hides real problems too, so it needs thought.

## Files / code involved

- `scripts/check_ownership.py` — the guard
- `/root/.claude/hooks/ownership-on-done.py` — the Stop hook that blocks the turn
- `/root/.claude/plugins/cache/omc/oh-my-claudecode/<version>/` — the add-ons that write as root

## Open questions

- Does the Claude Code CLI support running as a non-root user here without losing the plugin cache
  and hooks under `/root/.claude`?
- Would the setgid-group option (partial option 1) be enough on its own?
