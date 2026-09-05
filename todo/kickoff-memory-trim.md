# Kickoff: trim MEMORY.md back under 17KB

**Created:** 2026-09-04

## The problem

`/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md` is
**20,152 bytes / 93 lines**. Its own header sets a soft cap of 17KB and warns
that the hard read cap is ~24.4KB, past which the file "silently stops loading"
— every session then starts with no routing index at all. Target: **under
17,000 bytes**, ideally ~15KB so it has room to grow again.

## Scope: two separate routers

This task trims the **Claude** router named above. It is still read by the
Discord mention agent through `memorySearch.extraPaths`, so it must stay small.

`/root/.codex/openclaw-memory/MEMORY.md` is a separate Codex router. It is
already under the cap, but it is not a copy to overwrite. Do not replace either
file with the other. After this trim, compare only the current facts that should
apply to both and add any missing short hooks deliberately.

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

Measured 2026-09-04, bytes per section:

```
6867  Feedback — execution & style lessons   (a third of the file)
3645  Reference — market data feeds          (#111 cluster is ~1.5KB of it)
3032  Reference — tooling & environment
1525  Project — current state
1470  Reference — Discord
1221  Reference — AI models
1216  Rejected trade ideas
 389  User
```

Two moves should get the file safely under 17KB. Aim for ~15KB if the short
hooks still say when to open their detail. Do both:

1. **Move settled history out.** Do **not** move the whole `#111` cluster:
   #111 is still active, and the latest status says nothing is proven or live.
   Move its completed round results to `indexes/project-index.md`, but leave
   one Tier 1 hook to the current #111 result/status file. Keep current data
   source links when they are needed for the active work. Move the whole
   "Rejected trade ideas" detail section to the project index, then leave ONE
   Tier 1 hook that says to read it before proposing a new trade method. The two
   still-unopened sealed windows (#103, #106) are current state and stay in
   Tier 1.
2. **Cut the Feedback parentheticals** (~2.5KB). Those lines kept absorbing
   links until the hooks became summaries. Per line: keep the shortest phrase
   that tells a future session *why it would open that file*, move the rest of
   the explanation into the topic file if it is not already there (usually it
   is — check with `grep` before pasting). Rule of thumb: no line over 200
   characters. The four comm-check `§` lines are the one exception — they are
   bare content, not links, and they are the repeat-offender lessons. Tighten
   wording only, do not cut items.

Do the moves with one script, not dozens of single edits.

## Definition of done — every check is a command, not a judgement

Run this exact block before and after, from the legacy Claude `memory/` folder:

```bash
stat -c %s MEMORY.md
awk 'length>200{print length, NR": "substr($0,1,60)}' MEMORY.md
python3 - <<'PY' > /tmp/memory-link-targets.txt
from pathlib import Path
import re
import sys

missing = []
targets = set()
for source in [Path("MEMORY.md"), *Path("indexes").glob("*.md")]:
    for link in re.findall(r'\]\(([^)\s]+\.md)\)', source.read_text()):
        target = (source.parent / link).resolve()
        if target.is_file():
            targets.add(str(target))
        else:
            missing.append(f"MISSING {source}: {link}")
for target in sorted(targets):
    print(target)
if missing:
    print("\n".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY
test -f indexes/project-index.md && test -f indexes/comm-check-index.md
rg -q 'indexes/project-index\.md' MEMORY.md
rg -q 'indexes/comm-check-index\.md' MEMORY.md
```

1. Size under 17,000 bytes (target ~15,000).
2. No line over 200 characters, except the four comm-check `§` lines.
3. Every Markdown link resolves from the folder of the file that contains it.
   The old check was wrong: it checked `indexes/../topic.md` from `memory/` and
   falsely reported 109 missing files.
4. **No memory went unreachable.** Save
   `/tmp/memory-link-targets.txt` BEFORE the trim as
   `/tmp/memory-link-targets-before.txt`. After, run:

   ```bash
   comm -23 /tmp/memory-link-targets-before.txt /tmp/memory-link-targets.txt
   ```

   It must print nothing. These are resolved paths, so moving a link from
   `MEMORY.md` into an index does not create a false failure.
5. Tier 1 still routes current state, live traps, and behaviour lessons. It
   must retain a current #111 hook; only its completed round history moves out.
6. Report: before/after bytes, and which lines moved to which index file.
7. **Stop the regrowth.** Add a small threshold check to `/root/.claude/hooks/openclaw-digest.sh`
   (the session-start hook) that print a one-line warning when this exact legacy
   `MEMORY.md` is over 16,000 bytes. Make the threshold an environment setting
   with a 16,000-byte default, so it can be tested without editing the script:
   run the hook once with `MEMORY_WARN_BYTES=1`. The warning must name the file
   and its actual byte count. The file grew from 17KB to 20KB and nobody
   noticed; a check at every session start fixes that cause.

## Do not

- Do not touch `CLAUDE.md` or `comm-check.md` (standing rule).
- Do not reformat or reorder sections that are already short and compliant.
- Do not consolidate two memories into one file — this is an index trim, not a
  memory merge.
