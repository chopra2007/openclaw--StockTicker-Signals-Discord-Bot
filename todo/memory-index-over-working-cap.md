# Trim the memory index back under its working size limit

**Status:** OPEN
**Created:** 2026-08-24

**CURRENT STATUS (2026-08-24):** `MEMORY.md` is 18,634 bytes. Its own header sets
a 17,000-byte working limit, so it is about 1.6KB over. It is NOT broken — the
hard limit where it would silently stop loading at session start is ~24,400
bytes, and it is comfortably under that. Four clearly-finished project lines
were moved out on 2026-08-24 (19,311 → 18,634). Getting the rest of the way
needs judgment calls about which entries are still worth loading every session,
which is a decision for the owner, not something to do unattended at session
close.

## What this is

`MEMORY.md` is the index of saved notes that gets loaded into every new session.
It is meant to be a routing list — one short line per note, with the detail in
a separate file. The file itself warns that if it grows past about 24.4KB it
quietly stops loading, which would silently drop every lesson and guard in it.
The 17KB limit is the safety margin below that.

## What was already done

- Moved 4 shipped, finished project lines to `indexes/project-index.md` on
  2026-08-24: the options-flow side tag (#80), the 2026-07 research build (#61),
  the Wolf verifier (#64), and the discover rebuild. All four are finished work
  with no ongoing constraint a session needs in front of it.
- That recovered 677 bytes.

## What is left, and why it needs a person

The remaining candidates all carry something a session might still need
ambiently, so demoting them is a real trade, not bookkeeping:

- `project_verifier_stop_hook_shipped.md` (#69) — shipped, but it describes a
  hook that changes what happens when a session claims "done".
- `project_forward_loggers_shipped.md` (#62) — shipped, but names
  `analyst_horizon()` as the only gate to live alerts.
- `project_discover_next_features_stage1.md` (#67) — 12 of 14 switches flipped,
  2 deliberately held back, so it is not finished.
- The feedback section is the largest block. Every line is a behaviour lesson,
  which is exactly what is supposed to load every session, so shortening the
  hooks is safer than removing entries.

## Possible next steps

1. Shorten the hook text on the longest feedback lines without removing any
   entry. Lowest risk, and the feedback section is where the bytes are.
2. Ask the owner which shipped-but-still-relevant items can move to the tier-2
   index.
3. Consider whether the 17KB working limit is still the right number, given the
   real load limit is ~24.4KB.

## Files

- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md`
- `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/indexes/project-index.md`
