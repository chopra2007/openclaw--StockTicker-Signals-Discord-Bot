# Stop root sessions from leaving files the bot cannot write

**Status:** DONE
**Created:** 2026-08-22

**CURRENT STATUS (2026-08-22):** DONE — fixed without the risky full switch (running the
session as `openclaw`) that this file originally proposed. Two things are live now:

1. **Prevention, partial.** `root` was added to the bot's `openclaw` group, and every directory
   under `/home/openclaw/.openclaw` now carries the setgid bit (new files/folders inherit the
   `openclaw` group automatically). This alone was proven **not enough** for the worst files —
   `schwab_token.json`, `.env`, `.env.service`, and the reauth marker are hard-coded to
   `chmod 0600` by `schwab_client.py` / `schwab_login.py` on every write, which locks out the
   group entirely no matter what the directory allows. So this step helps the general case
   (`.omc/state/*`, `.git/*`) but does not fully solve it on its own.
2. **The real fix: auto-heal.** `/root/.claude/hooks/ownership-on-done.py` (the Stop hook) no
   longer just reports and blocks — it now runs `check_ownership.py --fix` itself (it already
   runs as root, so it can) and lets the session end silently when the repair succeeds. It only
   still blocks if a file genuinely can't be handed back. A repair line is appended to
   `/root/task_system/logs/ownership_sweep.log` each time so the trail stays visible without
   interrupting the session. Verified live with two real cases: a plain root-owned `.omc/state`
   file, and a `chmod 600 root:root` secret file matching the exact `schwab_token.json` failure
   shape — both were silently handed back to `openclaw` and the hook exited clean (no block).

The daily `ownership-sweep.timer` was left as a report-only monitor on purpose (it says so in its
own comment) — this fix only changed the interactive Stop hook, which is what was firing "every
session."

**Answers to this file's original open questions:**
- Running the session as `openclaw` was not attempted — the auto-heal hook makes it unnecessary
  for the actual complaint (the every-session interruption).
- The setgid-group option (partial option 1) is **not** enough on its own — the hard-coded
  `chmod 0600` calls on secrets defeat it. It is still worth keeping as it reduces how much the
  auto-heal step has to do on the common (non-secret) files.

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
