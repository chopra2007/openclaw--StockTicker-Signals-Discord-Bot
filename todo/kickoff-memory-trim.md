# Kickoff: trim MEMORY.md back under 17KB

**Created:** 2026-09-04

## The problem

`/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md` is
**20,152 bytes / 93 lines**. Its own header sets a soft cap of 17KB and warns
that the hard read cap is ~24.4KB, past which the file "silently stops loading"
— every session then starts with no routing index at all. Target: **under
17,000 bytes**, ideally ~15KB so it has room to grow again.

## Read first

The header of `MEMORY.md` itself. It states the rules this trim must follow:

- It is a **routing index only** — "one short hook per link, full detail in the
  topic file."
- "When a line goes dormant, fixed, or superseded, MOVE it to the project index."
- "related memories SHARE a line — add a link to an existing line, don't add a line."

Those three rules are the whole job. The file broke its own rules gradually; the
trim is enforcing them, not inventing a new format.

## Hard constraint

**Do not delete facts.** Every hook either stays in `MEMORY.md`, or its content
moves into the topic file / a Tier 2 index. A dropped line means a future session
repeats a mistake that was already paid for once. If something looks genuinely
obsolete, say so and ask — do not silently drop it.

The 253 individual memory files are NOT the target. Only `MEMORY.md` is oversized.

## Where things move

Two Tier 2 index files already exist and are read on demand, not preloaded:

- `memory/indexes/project-index.md` (11,155 bytes) — shipped/dormant project history
- `memory/indexes/comm-check-index.md` (7,896 bytes) — dated comm-check narratives

Anything settled, shipped, or historical belongs in one of these. Growing them is
free; growing `MEMORY.md` is not.

## Where the weight actually is

Measured 2026-09-04, longest lines:

```
681 ch  L74  #111 tournament SEALED result ...
569 ch  L18  Done-claims — ...
538 ch  L45  Root-edit ownership traps — ...
471 ch  L19  Close-out — ...
433 ch  L81  Shares / intraday — 3 day-trader methods #106 ...
429 ch  L20  Diagnosis — ...
423 ch  L22  Answer style — ...
415 ch  L61  Bake-offs — ...
```

The pattern: these are shared lines that kept absorbing new links until the
parenthetical explanations became summaries. The fix is per-line, not global —
cut each hook to the shortest phrase that still tells a future session *why it
would open that file*, and push the explanation into the file itself.

The `#111` cluster (L74 and the rejected-ideas block around L78-84) is the single
biggest win: that work is concluded, so most of it is history and belongs in
`indexes/project-index.md` behind one or two surviving hooks.

## Definition of done

1. `MEMORY.md` is under 17,000 bytes — print `stat -c %s` before and after.
2. Every link target still exists: check each `](file.md)` resolves to a real
   file in `memory/`.
3. No fact was deleted — anything cut from `MEMORY.md` is present in the topic
   file or a Tier 2 index. Say plainly which lines moved where.
4. Tier 1 content is untouched in spirit: current state, live traps, and
   behaviour lessons still route from `MEMORY.md`. Only settled history moves out.
5. Report the before/after size and the line count of what moved.

## Do not

- Do not touch `CLAUDE.md` or `comm-check.md` (standing rule).
- Do not reformat or reorder sections that are already short and compliant.
- Do not consolidate two memories into one file — this is an index trim, not a
  memory merge.
