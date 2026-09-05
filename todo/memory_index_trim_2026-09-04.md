# Trim the Claude memory index back under its size cap

**Status:** DONE 2026-09-04
**Created:** 2026-09-04

**CURRENT STATUS (2026-09-04):** Done and independently repaired. The Claude
router is now 13,881 bytes, below both its 17,000-byte cap and 16,000-byte
warning. The separate Codex router is 15,159 bytes and now carries the missing
current #111 facts. Stale wording that rejected the owner's long-hold momentum
option and claimed Databento was still blocked has been corrected in both
memory copies.

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
   with `MEMORY_WARN_BYTES=1` (fires) and the real default (quiet at 13,881).
6. Repaired the #111 history wording: the three-month momentum method is an
   owner-kept option, not a rejected or unusable method. Nothing is live and
   its concentration and market-cycle caveats remain.
7. Corrected the Databento record from its obsolete 401/access blocker to the
   two current spend ledgers: $12.4457 spent, about $112.55 of the original
   $125 credit left. The older PUT-layer test remains untested, not rejected.
8. Added the missing current #111, data-source, trade-horizon and rejected-idea
   routing to `/root/.codex/openclaw-memory/`, with the needed topic files.

## Verification run (all passed)

- Claude router size: 20,152 → 13,881 bytes.
- Codex router size: 15,159 bytes after adding the missing current facts.
- No line over 200 chars except the 4 exempt `§` lines.
- Every markdown link in `MEMORY.md` and both `indexes/*.md` files resolves to
  a real file (checked with a script that resolves relative to each source
  file's own directory).
- No memory became unreachable: diffed the set of resolvable link targets
  before vs. after the trim — empty diff.
- Both `indexes/project-index.md` and `indexes/comm-check-index.md` exist and
  are referenced from `MEMORY.md`.
- Every new Codex-router Markdown link resolves to a real file.

## Files involved

- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md` (trimmed)
- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/indexes/project-index.md` (received the moved content)
- `/root/.claude/hooks/openclaw-digest.sh` (regrowth warning added)
- `/root/.codex/openclaw-memory/MEMORY.md` and its Tier 2 indexes (reconciled)
- Kickoff file that specified this task: `todo/kickoff-memory-trim.md`

## Open questions

- None.
