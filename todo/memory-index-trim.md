# Trim the memory index (MEMORY.md) smartly before it stops loading

**Status:** DONE 2026-07-08
**Created:** 2026-07-07

**CURRENT STATUS (2026-07-08):** DONE. MEMORY.md cut from 21,997 bytes / 157 lines to 14,281 bytes / 109
lines — safely under the ~17.1KB warning target and the ~24.4KB hard read cap. Executed as a HYBRID of
the pasted prompt below and the original merge-don't-delete plan: behavior lessons, traps, and
current-state lines STAY in MEMORY.md (they only work when loaded every session — a pure router would
have made them invisible in practice); only lookup-style history moved to two new tier-2 files
(`indexes/project-index.md` — 47 shipped/dormant project links + 11 re-linked orphans from the June
trim; `indexes/comm-check-index.md` — full dated failure narratives, distilled rules kept in
MEMORY.md). All 142 old links verified still reachable, zero broken targets, no @-imports, no topic
file deleted; backup at `archive/MEMORY-before-tiered-index-2026-07-08.md`. MEMORY.md's header now
carries the growth rule: when a project line goes dormant, MOVE it to the project index.

## The pasted prompt (kept for the record; executed in modified form — see status above)

Based on your current `MEMORY.md`, this prompt tells Claude to **preserve all detail**, create a **tiered index**, and keep startup memory safely under the limit. 

You are working in my Claude Code auto-memory folder. My current `MEMORY.md` is already close to the startup load limit. It is currently being used as a flat routing index with many direct links to detailed topic files, but it is around 22KB and the limit is 25KB / 200 lines. I do **not** want to prune, delete, summarize away, or lose important details.

Your task: refactor the memory structure into a **tiered routing index**.

Goal:

* Keep `MEMORY.md` very small and stable.
* Preserve all existing detailed topic files.
* Preserve all current memory details.
* Move long flat sections out of top-level `MEMORY.md` into second-tier category index files.
* Make `MEMORY.md` point to those category indexes.
* Do **not** use `@file` imports, because imported files load into startup context and defeat the purpose.
* Use plain paths like `Read: indexes/project-index.md`, not `@indexes/project-index.md`.

Important constraints:

1. Do not delete any existing memory topic files.
2. Do not prune detail.
3. Do not merge away details unless there is an exact duplicate and you can prove it is redundant.
4. Do not edit `CLAUDE.md`.
5. Do not edit `comm-check.md` or any comm-check source/rules files unless absolutely necessary for this memory refactor.
6. Do not use `git stash`.
7. Back up the current `MEMORY.md` before editing.
8. Verify the result with byte count, line count, and link/path checks before claiming done.
9. Do not ask me for confirmation before starting. Inspect first, then execute.
10. When done, report exactly what changed and prove that no memory detail was lost.

Desired structure:

```text
memory/
├── MEMORY.md
├── indexes/
│   ├── user-index.md
│   ├── feedback-index.md
│   ├── comm-check-index.md
│   ├── reference-index.md
│   └── project-index.md
├── user_profile.md
├── feedback_*.md
├── reference_*.md
├── project_*.md
└── comm-check-fail-*.md
```

It is okay if the actual memory directory has more files than this. Preserve the existing filenames and only add the `indexes/` folder plus category index files.

Refactor plan:

1. Inspect the current memory directory.

   * Locate `MEMORY.md`.
   * List existing `feedback_*.md`, `reference_*.md`, `project_*.md`, `comm-check-fail-*.md`, and user/profile files.
   * Measure current `MEMORY.md` size and line count.

2. Create a backup:

   * Save the current top-level file as something like:
     `archive/MEMORY-before-tiered-index-YYYY-MM-DD.md`
   * If `archive/` does not exist, create it.

3. Create second-tier index files:

   `indexes/user-index.md`

   * Move the current `## User` routing entries here.
   * Include user profile, timezone rules, and durable user workflow preferences.
   * Keep hooks short but specific.

   `indexes/feedback-index.md`

   * Move the current `## Feedback — execution & style lessons` routing entries here.
   * Preserve all links and one-line hooks.
   * Keep the lessons grouped if helpful:

     * execution style
     * verification
     * testing / done criteria
     * agent / parallel work
     * memory / file handling
     * prompt-writing habits

   `indexes/comm-check-index.md`

   * Move the current `### Comm-check failures` section here.
   * Preserve every dated/section-specific lesson.
   * Keep the detailed comm-check failure file references intact.
   * Do not shorten in a way that loses the specific failure mode.

   `indexes/reference-index.md`

   * Move the current `## Reference` routing entries here.
   * Preserve all links and hooks.
   * Group if helpful:

     * API/auth/model references
     * Discord / gateway / service references
     * Git / ownership traps
     * market/data-provider references
     * environment/runtime references

   `indexes/project-index.md`

   * Move the current `## Project` routing entries here.
   * Preserve all project links and status hooks.
   * Group if helpful:

     * architecture / scanner
     * Wolf/news brain
     * signal features
     * market / options / volatility
     * shipped milestones
     * deferred or active work
   * Preserve live/off/deferred status language because it is load-bearing.

4. Rewrite top-level `MEMORY.md` into a compact router only.

Target shape:

```md
# Memory Index

Purpose: compact routing index only. Keep well under 25KB and under 200 lines.
Do not store long notes here. Detailed notes live in topic files and second-tier indexes.

## Highest-priority reminders

- Answer direct questions directly.
- Do not ask for confirmation when the user already gave enough direction.
- Investigate before fixing.
- Diagnose before blaming providers.
- Verify real output before claiming done.
- Do not edit CLAUDE.md or comm-check files unless explicitly instructed.
- Do not prune memory; preserve detail in topic files and second-tier indexes.
- Do not use @file imports in this memory index.

## User

Read: `indexes/user-index.md`

Contains user profile, timezone rules, durable preferences, and workflow constraints.

## Feedback and behavior lessons

Read: `indexes/feedback-index.md`

Contains execution/style lessons, verification rules, anti-patterns, and repeated correction history.

## Comm-check failures

Read: `indexes/comm-check-index.md`

Contains dated communication-check failures and section-specific lessons.

## Reference

Read: `indexes/reference-index.md`

Contains tool, API, service, environment, Discord, Git, auth, ownership, and model-reference notes.

## Project

Read: `indexes/project-index.md`

Contains OpenClaw/Wolf/scanner/project milestone state, shipped features, live flags, deferred work, and active plans.

## Routing rule

When a request touches one of these areas, read the relevant second-tier index first, then open only the needed detailed topic files.
```

5. Validate thoroughly.

Run checks equivalent to:

```bash
wc -c MEMORY.md
wc -l MEMORY.md
find indexes -type f -maxdepth 1 -print
```

Also verify:

* `MEMORY.md` is comfortably below 25KB.
* `MEMORY.md` is below 200 lines.
* No `@indexes/...` imports were added.
* Every link moved out of the old `MEMORY.md` still appears somewhere in the new tiered structure.
* Every existing topic file remains present.
* The second-tier indexes use plain markdown links or plain paths.
* The top-level `MEMORY.md` is now only a router.

6. Report completion with proof.

In your final response, include:

* Old `MEMORY.md` byte count and line count.
* New `MEMORY.md` byte count and line count.
* List of created index files.
* Confirmation that the old file was backed up.
* Confirmation that no detailed topic files were deleted.
* Confirmation that no `@file` imports were used.
* Any exact duplicate or broken link discovered, if any.

Do not say "done" until the checks pass.

Paste it into Claude Code from the memory folder or project root where Claude can access the current `MEMORY.md`.

### Session notes — 2026-07-08
- **Worked on:** Executed the trim as a hybrid tiered refactor: MEMORY.md 21,997→14,281 bytes (157→109 lines); created indexes/project-index.md + indexes/comm-check-index.md; re-linked 11 orphaned topic files the June trim had cut; backup in archive/.
- **Decisions:** Rejected the pasted prompt's pure-router design (would move behavior lessons out of ambient session context, where they'd almost never be read); kept lessons/traps/current-state in MEMORY.md, moved only shipped history. Growth rule added to MEMORY.md header.
- **Next:** None — done. Future growth: move dormant project lines to indexes/project-index.md instead of re-trimming.
