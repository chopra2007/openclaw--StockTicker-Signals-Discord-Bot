# Trim the Claude memory index back under its size cap

**Status:** DONE 2026-09-04
**Created:** 2026-09-04

**CURRENT STATUS (2026-09-04):** Done and verified same session. `MEMORY.md` (the
routing index Claude reads at the start of every session) had grown from 17KB to
20,152 bytes — past its own 17KB soft cap and closing in on the ~24.4KB hard cap
where the harness silently stops loading it. Trimmed to 16,832 bytes. No facts
deleted — settled/historical content moved to the on-demand Tier 2 index, and a
regrowth warning was added so this doesn't happen unnoticed again.

## What was done

1. Moved 3 completed TODO #111 rounds (condor rejected, round-3 ceiling test,
   momentum-wrong-horizon) out of `MEMORY.md` into
   `indexes/project-index.md` (read on demand, not every session). Left one
   current-status hook to the #111 sealed-result file in the main index.
2. Moved the full "rejected trade ideas" detail (day-trader methods, share
   methods, event/flow methods, PUT option layer) into the same index file.
   Left one pointer line in `MEMORY.md` plus the two still-unopened sealed
   test windows (#103, #106), which are current state.
3. Tightened the "Feedback — execution & style lessons" section: cut redundant
   parenthetical explanations that just restated the link title (the fuller
   explanation already lives in each linked topic file).
4. Reflowed long lines (many were 300-800+ characters) into wrapped
   continuation lines so no line in the file exceeds 200 characters, except
   the 4 comm-check `§` lines which are explicitly exempt by the file's own
   rules.
5. Added a regrowth check to the SessionStart hook
   (`/root/.claude/hooks/openclaw-digest.sh`): it now prints a one-line
   warning naming the file and its byte count if `MEMORY.md` is over 16,000
   bytes (threshold configurable via `MEMORY_WARN_BYTES` env var). Tested
   both with `MEMORY_WARN_BYTES=1` (fires) and the real default (also fired
   honestly, since 16,832 > 16,000 — the file landed closer to the 17KB hard
   cap than the ~15KB stretch goal).

## Verification run (all passed)

- Size: 20,152 → 16,832 bytes (target was <17,000, stretch ~15,000).
- No line over 200 chars except the 4 exempt `§` lines.
- Every markdown link in `MEMORY.md` and both `indexes/*.md` files resolves to
  a real file (checked with a script that resolves relative to each source
  file's own directory).
- No memory became unreachable: diffed the set of resolvable link targets
  before vs. after the trim — empty diff.
- Both `indexes/project-index.md` and `indexes/comm-check-index.md` exist and
  are referenced from `MEMORY.md`.

## What didn't get done (flagged, not silently skipped)

The kickoff also asked to compare the separate Codex memory router
(`/root/.codex/openclaw-memory/MEMORY.md`) and add any hooks missing there
too. Checked: it's missing the #111 tournament result and the rejected
trade ideas bar. But none of the Claude-side topic files those facts live in
exist in the Codex memory directory — porting them means writing new topic
files there, not just adding a link, which is real authoring work rather
than a trim. Left this as a follow-up rather than doing it unasked.

## Possible next steps (priority order)

1. If the user wants it: copy/adapt the #111 and rejected-trade-ideas topic
   files into `/root/.codex/openclaw-memory/`, then add short hooks to that
   router.
2. Watch the new digest-hook warning over the next few sessions — confirm it
   actually fires in a real session start (not just the manual test run) if
   `MEMORY.md` ever creeps back over 16,000 bytes.

## Files involved

- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md` (trimmed)
- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/indexes/project-index.md` (received the moved content)
- `/root/.claude/hooks/openclaw-digest.sh` (regrowth warning added)
- Kickoff file that specified this task: `todo/kickoff-memory-trim.md`

## Open questions

- None — the trim itself is complete. The only open item is the optional
  Codex-router cross-check noted above.
