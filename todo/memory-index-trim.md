# Trim the memory index (MEMORY.md) smartly before it stops loading

**Status:** OPEN
**Created:** 2026-07-07

**CURRENT STATUS (2026-07-07):** MEMORY.md is ~20KB and growing. At ~24.4KB it hits a hard
read cap and stops loading at session start — which would silently drop ALL of Claude's recall
at the start of every session. Not urgent yet (still loads), but it needs a careful, thoughtful
trim down to ~17KB before it crosses the line. Not yet started.

## What this is

`MEMORY.md` (at `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md`) is
the routing index that loads into Claude's context at the start of every session. It's meant to be
one short line per memory (a hook + a link to the full topic file). The rule at the top of the file
says keep it under 25KB so it fully loads. A PostToolUse hook now warns on every edit that it's
"approaching the 24.4KB read limit" and asks to compact to under 17.1KB.

If it ever exceeds the cap, the whole index stops loading — Claude starts sessions with no memory
routing at all. That's the risk being pre-empted.

## Why it must be done carefully, not with a blunt truncation

Each line points to a real topic file that holds hard-won context (past incidents, traps, shipped
features, reference facts). Cutting lines blindly loses the pointer to that knowledge. The trim has
to be SMART:

1. **Merge, don't delete.** Many lines cover the same theme (e.g. the long list of comm-check
   failures, the ownership-trap references, the vol-indicator no-go sub-entries). Related lines can
   be collapsed into one denser line or one grouped sub-section without losing the pointer.
2. **Drop only genuinely stale entries** — ones whose topic file is obsolete or fully superseded,
   and only after confirming nothing still references them. When in doubt, keep the pointer.
3. **Preserve every live pointer.** If a topic file still holds useful context, its line stays
   (possibly shortened), never removed.
4. **Shorten hooks, keep links.** Much of the size is verbose hooks — tighten the prose per line
   while keeping the `[Title](file.md)` link intact.
5. The topic files themselves are NOT the constraint (they don't all load at once) — only the index
   is. So detail moves OUT of the index into topic files, never the reverse.

## Possible next steps, priority-ordered

1. Read the whole MEMORY.md and bucket its lines by theme.
2. Identify the biggest, most-mergeable clusters (comm-check failures, ownership traps, model
   bake-off / reference entries, the vol-indicator no-go chain, project milestones).
3. Collapse each cluster to a tighter form; shorten verbose single-line hooks.
4. Confirm no line's topic file is still actively linked from elsewhere before dropping it.
5. Verify the result is under ~17KB and still loads, and that every remaining pointer resolves to a
   real file.

## Files / code involved

- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md` — the index to trim
- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/*.md` — the topic files it links

## Open questions

- Target size: hook asks for <17.1KB; the file's own header says <25KB. Aim for ~17KB to leave
  headroom for future growth.
- Whether any topic files can be safely deleted outright (vs. just unlinked from the index) — needs
  a check that nothing else references them.
