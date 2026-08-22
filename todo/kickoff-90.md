# Kickoff: fix TODO #90 — the ownership guard fires every turn on a scratch file

**Created:** 2026-08-22

## Read first

`todo/ownership-guard-false-alarms.md` — the full root cause, already proven. Do not re-investigate
what is already settled there. In particular, these are DONE, do not redo them:

- The writer is identified: the `persistent-mode` Stop hook, registered at
  `/root/.claude/plugins/cache/omc/oh-my-claudecode/4.15.10/hooks/hooks.json` under `EVENT: Stop`.
- Codex is ruled out (`lsof` on all five Codex PIDs shows no `.omc` file open).
- Timing is proven: fix at 11:06:38, file root-owned again at 11:06:43, same turn.

## The job

Apply fix option 1 from the detail file, and answer the one open question that decides whether
option 3 is worth a separate item.

### Part A — stop the false alarm

Add a per-file ignore to `scripts/check_ownership.py` for exactly one filename:

```
.omc/state/idle-notif-cooldown.json
```

`scripts/check_ownership.py` has `SKIP_DIRS` at line 35 but no per-file ignore list, so add one.

**Hard constraint — do not widen this.** `.omc/state/` holds real bot data and must stay guarded:

| File | Read by |
|---|---|
| `calibration_model.pkl` | `consensus_engine/analysis/calibration.py` |
| `news_cascade_brave_counter.json` | `consensus_engine/scanners/news.py` |
| `searxng_health.json` | `scripts/check_searxng_health.sh` |

Ignoring the directory would blind the guard to all three. Ignore the single filename only.

### Part B — answer the open question

Does the root-owned flip happen in sessions NOT running as root? Find out. If the answer is "no,
this only happens because the session runs as root", then option 3 (run the session as `openclaw`)
is the real fix and Part A is a patch — say so plainly and add a follow-up TODO item for it rather
than pretending #90 closed the underlying problem.

Evidence that this is not just cosmetic: on 2026-08-22 the same root-ownership problem left seven
real git files root-owned after a commit, including `.git/index` and `.git/refs/heads/master`. Same
cause, and that one genuinely breaks pushes.

## Definition of done

1. `python3 scripts/check_ownership.py` runs clean at the end of a turn WITHOUT the cooldown file
   being reported — verified by finishing a real turn, not by reasoning about it.
2. A deliberate check that the guard still catches a real one: chown a throwaway file under
   `.omc/state/` to root, confirm the guard reports it, chown it back. Do NOT use
   `calibration_model.pkl` or any live file for this — make a temp file.
3. Existing tests for `check_ownership.py` still pass. Grep `tests/` for `check_ownership` first and
   run every match (the usual hidden-dependents rule).
4. `todo/ownership-guard-false-alarms.md` CURRENT STATUS rewritten to what is actually true, and the
   header marked `— DONE YYYY-MM-DD` in `TODO.md` only if Part B confirms nothing is left owed.
   Then `python3 scripts/todo_status_sync.py --fix` and `--check`.

## Scope

Small. One file changed, one ignore entry, plus the Part B answer. Do not refactor the guard, do not
touch the plugin cache (it is wiped on every plugin update), and do not attempt option 3 in this
session — if Part B says it is needed, write it up as a new TODO item and stop.
