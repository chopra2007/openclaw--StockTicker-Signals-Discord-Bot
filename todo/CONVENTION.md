# TODO list convention

The user maintains a two-layer TODO system:
- `TODO.md` (workspace root) — short scannable INDEX of all tasks
- `todo/<descriptive-name>.md` — one detail file per task

## How to add an item

When the user says "add X to the to do list" (or any equivalent — "put that on the list", "add this to the todo", "save that as a todo"):

1. **Write a detail file** at `todo/<descriptive-name>.md` containing all pertinent context. The top of the file must include two short metadata lines right under the H1 title:
   ```
   **Status:** OPEN
   **Created:** YYYY-MM-DD   (today's date)
   ```
   Then the body, covering:
   - What worked (so far)
   - What didn't work and why
   - Possible next steps, priority-ordered
   - Files / code involved
   - Open questions
   - Anything else a future session would need to pick this up cold

2. **Append an index entry to TODO.md** — just the filename (NOT the full path) plus a single plain-English sentence that describes the TASK or GOAL itself (what the user is trying to accomplish), NOT a meta-description of the file's contents. The sentence must let the user know what the task/goal is at a glance, without opening the file.

   - ✅ Good: "Teach the video-watcher to read precise chart numbers the speaker glosses over."
   - ❌ Bad: "Contains 6 priority items and a test summary." (describes the file, not the goal)

No confirmation needed — execute both steps immediately on trigger.

## TODO.md entry format

```
## N. <plain-English title — a few words, goal-readable>

**File:** `<descriptive-name>.md`

<one sentence describing the TASK/GOAL — see rule above>
```

**Title rule:** the `## N. ...` header is what shows in the `/todo` table view. It must be plain English, a few words, so the user can understand the goal without opening the file or knowing extra context. Avoid file names, code symbols, abbreviations, and project jargon. The longer summary sentence below `**File:**` is where detail and jargon belong.

- ✅ Good: `## 14. Fix missing direction on manual !all alerts`
- ❌ Bad: `## 14. Cross-ref scorer's breakdown.direction is None on manual !all`

## Status markers

An item's status lives in a marker at the END of its `## N. ...` header. Five statuses; the marker
grammar is strict so `scripts/todo_switch_state.py` can parse it. A trailing parenthetical after the
marker is allowed (`— DONE 2026-06-15 (verified working)`).

| Status | Header marker | Means | Shows in "what's left?" |
|---|---|---|---|
| Active | *(no marker)* | Real work you can pick up today | ✅ yes |
| Soaking | `— SOAKING until YYYY-MM-DD` | Built and live; waiting on time (a shadow soak, a live-alert watch) | only once the date passes |
| Parked | `— PARKED: <reason>` | Blocked on something outside our control (money, an upstream API). Nothing accrues; nothing changes on its own | ❌ no |
| Ongoing | `— ONGOING` | A feature that is never "finished" — a living record, or a menu you pick one item from per session | ❌ no |
| Complete | `— DONE YYYY-MM-DD` | Finished | ❌ no (shows in the full list) |

Rules that keep the statuses honest:

- **Soaking must name a date.** No date = no marker; it stays Active. When the date passes the item
  becomes work again: `--check` prints a `soak window ended` line and the list renders it
  `Soaking (due)` in the Status column and includes it in "what's left". At that point either close it
  (`— DONE`) or drop it back to Active with a reason.
- **Parked must name the blocker** in the marker itself, in a few plain words — `— PARKED: needs paid
  options history (~$29)`. If the blocker is something we could clear ourselves, it is Active, not Parked.
- **Ongoing items still need a current-status line.** They're hidden from "what's left", not from
  maintenance. An Ongoing item with a stale body is worse than an Active one, because nothing nags it.
- Parked and Ongoing never appear in "what's left", but ALWAYS appear in the full list — otherwise
  they rot unseen.

Why this exists (2026-07-08): the two-status system (Active / Complete) forced everything unfinished
into Active, so "what's left on the todo list?" returned 13 items of which ~5 weren't workable — a
shadow soak, two money-blocked research items, and two never-ending feature menus. Statuses that
answer *"can I work on it, is it waiting on the clock, is it waiting on me to spend, or does it never
end?"* make that question return only real work.

## Completion marker

When a task is done, mark its TODO.md header `— DONE YYYY-MM-DD`. Keep both the index entry and the detail file as a soak window. Remove ONLY once the work is proven stable AND the user has explicitly approved removal. Never auto-delete soaked items without the user's say-so.

## Lead with current status (multi-step / partially-done items)

The `— DONE` marker is binary, but many items land in stages across sessions (a switch flipped one at a time, a phased build, a soak). For ANY item not yet fully done whose state has moved, the item must lead with a `**CURRENT STATUS (YYYY-MM-DD):** …` paragraph stating the latest state in plain English — what's live, what's left, and the next concrete step.

**Where it gets written (changed 2026-07-12, TODO #72): the DETAIL file only.** The CURRENT STATUS paragraph is written and rewritten in the detail file (first body paragraph, dated; history stays below it). `TODO.md`'s copy is machine-made — **never hand-edit a CURRENT STATUS paragraph in TODO.md**:

- `python3 scripts/todo_status_sync.py --fix` mirrors each detail file's lead paragraph into its TODO.md entry (replaces the existing lead paragraph; inserts one for non-DONE items; DONE items get no new insertion — the header marker is enough).
- `python3 scripts/todo_status_sync.py --check` flags drift: header marker vs detail `**Status:**` kind mismatch; an index lead out of sync with the detail file (run `--fix`); a DONE item whose lead line predates its DONE date; a DONE item whose status prose still contains forward-looking work ("Next:", "owed", "stays OPEN", "eyeball it"…); and a CURRENT STATUS line older than the newest `### Session notes` block below it.
- The daily drift timer (`todo-switch-drift-check.timer`, 06:00 PDT) runs `--check` and appends any drift to `notifications.log`, which session start surfaces.

**Before writing or refreshing a CURRENT STATUS line, re-read the session-notes blocks at the bottom of the same file.** The status line's date must be ≥ the newest session note's date (`--check` enforces this). This rule exists because a status line written from session memory instead of from the file produced a sentence that was false the moment it was committed (#20, 2026-07-12) — the correct fact was already sitting in the same file's session notes, written two hours earlier.

Rationale: the `/todo` view and any quick scan show the TOP of the item. If the top is frozen at an old "what remains" note while the real work is done, the reader (and the next session) wastes time and tokens re-deriving the actual state — this happened with #32/#42 on 2026-06-27, and again (despite this rule) with #20/#57 on 2026-07-12, which is why the mirror + checker now exist (full post-mortem: `todo/todo-index-refresh-contradiction-bug.md`, TODO #72). Rules in prose don't execute; the script does.

## Switch-bearing items — derive live state from config, never hand-copy it

The deepest version of that trap: an item that says "turn on switches X, Y, Z" holds a HAND-TYPED copy of a fact that already lives authoritatively in `config/consensus.yaml` (what the engine actually runs). Copies drift. So such items must NOT rely on prose alone — they declare the config flags they govern and let a reader resolve the real state:

- Add one line to the item body, under `**File:**`:
  `**Switches:** features.cross_asset.enabled=on; features.consensus_logodds.enabled=noop`
  Each entry is `<dotted config key>=<expected>`, `;`-separated. `expected` is `on` (must be ON in a healthy live state — OFF means still pending) or `noop`/`off` (intentionally OFF — ON means unexpected drift).
- `scripts/todo_switch_state.py` reads those lines and resolves each key with the same `config.get()` the engine uses, so the list can never silently disagree with the engine. `--check` prints drift only: an OPEN item whose switches are ALL in their expected state (looks done but isn't closed — the #32/#42 failure), or an unexpected-ON / typo'd key.
- A daily timer (`todo-switch-drift-check.timer`, 06:00 PDT) runs `--check` and appends any drift to `notifications.log`, which session start surfaces — so "all live but still OPEN" is caught even if nobody opens `/todo`.

When rendering `/todo` or reviewing a switch-item, run `python3 scripts/todo_switch_state.py` and trust its live read over the prose.

## Stable IDs — never re-use deleted item numbers

When an item is removed (post-soak), its number is retired forever. The next new item is `N+1` of the highest number ever used, not the lowest available. This ensures references like "look at #14" never silently break by pointing at a different task than originally meant. If the highest item ever was #17 and #4 was removed, the next item is #18, not #4.

## Listing the backlog

Render the backlog as a four-column **Markdown pipe table**: `#`, `Task`, `Created`, `Status`. Use real pipe-table syntax (`| ... |`) so the chat UI renders it as an actual table — NOT a fenced code block. The phrasing the user uses determines which rows to include.

**Open items only** — when the user asks for what's *remaining* or *outstanding*. Triggers include: "what's left on the to do list?", "what's remaining?", "what's open?", "what's pending?", "what still needs doing?", "what's outstanding?". Include only `Active` rows plus `Soaking (due)` rows (soak date passed). Exclude `Complete`, `Parked`, `Ongoing`, and in-window `Soaking`.

**Everything (open + completed)** — when the user asks for the full list. Triggers include: "what's on the to do list?", "the whole todo list", "the entire todo list", "show me all todos", "everything on the list", a bare `/todo` with no args. Include every row, every status.

Two-source render:
1. `grep -nE '^## ' TODO.md` → number, title, DONE marker.
2. `grep -h '^\*\*Created:\*\*' todo/<filename>.md` → Created date for each row. Detail filename comes from the `**File:**` line in TODO.md.

3. For items carrying a `**Switches:**` line, run `python3 scripts/todo_switch_state.py` and trust its live config read over the prose — an **Active** item whose switches are all in their expected state is stale: flag it `⚠️ verify/close`, don't render it as plain pending work. (Soaking/Parked/Ongoing items are NOT nagged — all-switches-live is their normal state.)

Status column values: `Active`, `Soaking` (in window — append the date, e.g. `Soaking → 07-15`), `Soaking (due)` (date passed), `Parked`, `Ongoing`, `Complete`. Strip the status marker from the displayed Task. Show Created on every row, whatever the status. If a detail file is missing the `**Created:**` line, BACKFILL it (insert the line right after `**Status:**` in the detail file, using the DONE date as the proxy if the item is complete, otherwise the date the detail file was first added to git) — don't render `—`.

Output format (verbatim — keep the header + separator row exactly so the renderer recognises it as a table):

```
| #  | Task                              | Created    | Status         |
|----|-----------------------------------|------------|----------------|
| 1  | Plain-English summary of the task | 2026-05-09 | Active         |
| 4  | Another task                      | 2026-05-22 | Complete       |
| 6  | A never-ending feature menu       | 2026-05-12 | Ongoing        |
| 47 | Blocked on money                  | 2026-06-18 | Parked         |
| 67 | Built, live, watching             | 2026-07-06 | Soaking → 07-15 |
```

The Task column is the `## N. <title>` from TODO.md verbatim (minus any `— DONE …` suffix). Don't use angle-bracket placeholders like `<TICKER>` in titles — they may be parsed as HTML by the table renderer; write `the !all command` or use square brackets.

Don't read full detail-file bodies for a list view — just grep for the `**Created:**` line.

## Resume / Pause — working on a single task across turns

Two commands let the user formally "open" a task for focused work and "save" what was learned back into its detail file. This keeps detail files current automatically instead of relying on manual updates.

### Active-task marker

A one-line file at `todo/.active` holds the currently-focused detail filename (e.g. `youtube_vision_upgrade.md`). Gitignored — session state, not committed knowledge. Present means a task is "resumed"; absent means none.

### Resume — `/todo-resume N` (or "resume #N", "work on #N", "pick up #N")

1. Find the detail filename: `grep -A2 "^## N\." TODO.md | grep -oP '`\K[^`]+\.md'`.
2. Read `todo/<filename>`.
3. Write `<filename>` (single line, no trailing newline) to `todo/.active`.
4. Print to the user, in plain English:
   - Title + status + Created date
   - The one-sentence goal
   - The highest-priority "next step" still open
   Do NOT dump the whole file. Keep the resume printout under ~15 lines.

### Pause — `/todo-pause` (or "pause", "save progress")

1. Read `todo/.active`. If missing/empty: tell the user "no active task" and stop.
2. Append a dated session-notes block to the bottom of `todo/<filename>`. Format:
   ```
   ### Session notes — YYYY-MM-DD
   - **Worked on:** <one line>
   - **Decisions:** <one line, or "none">
   - **Next:** <one line of the most important next step>
   ```
   Use today's actual date. Pull content from the current session: what got done, what got decided, what's the obvious next thing.
3. **Append-only — never edit existing prose in the detail file.** The session-notes blocks stack at the bottom in chronological order.
4. Clear `todo/.active` (delete the file or write empty).
5. Print a one-line confirmation: "Paused #N — session notes appended."

### Edge cases

- User says "pause" with no active task → tell them, do nothing.
- User says "resume #N" while another task is already active → pause the old one first (run the pause flow), then resume the new one. Tell the user both things happened in one line.
- User says "resume" with no number → if `todo/.active` exists, treat as a no-op + reprint the resume summary. If not, ask which task.

## Why this two-layer system exists

The user wants rich, recoverable context captured in the moment without bloating the index, then a short scannable list later to pick what to work on next. Don't paste full file contents into TODO.md — that defeats the index pattern.
