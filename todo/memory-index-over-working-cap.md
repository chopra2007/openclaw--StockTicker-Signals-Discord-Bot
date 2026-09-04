# Trim the memory index back under its working size limit

**Status:** DONE 2026-09-04
**Created:** 2026-08-24

**CURRENT STATUS (2026-09-04):** Complete. The current private Codex router had
grown to 20,460 bytes. It is now 15,567 bytes, below its 17,000-byte working
limit. Routing descriptions were shortened without deleting active lessons,
and five clearly shipped project entries moved to `indexes/project-index.md`.
Every retained link in both edited files resolves. No private memory was copied
into the public repository, and Codex's automatic `/root/.codex/memories/`
store was not edited.

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

- `/root/.codex/openclaw-memory/MEMORY.md`
- `/root/.codex/openclaw-memory/indexes/project-index.md`

### Session notes — 2026-09-04

- **Worked on:** trimmed the current private router from 20,460 to 15,567 bytes and moved five shipped entries to the existing history index.
- **Decisions:** preserved active warnings and behavior lessons; shortened route text instead of deleting those notes.
- **Next:** none; all retained links resolve and the router is below its working limit.
