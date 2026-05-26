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
## N. <short title>

**File:** `<descriptive-name>.md`

<one sentence describing the TASK/GOAL — see rule above>
```

## Completion marker

When a task is done, mark its TODO.md header `— DONE YYYY-MM-DD`. Keep both the index entry and the detail file as a soak window. Remove ONLY once the work is proven stable AND the user has explicitly approved removal. Never auto-delete soaked items without the user's say-so.

## Stable IDs — never re-use deleted item numbers

When an item is removed (post-soak), its number is retired forever. The next new item is `N+1` of the highest number ever used, not the lowest available. This ensures references like "look at #14" never silently break by pointing at a different task than originally meant. If the highest item ever was #17 and #4 was removed, the next item is #18, not #4.

## Listing the backlog

The phrasing the user uses determines the filter:

**Open items only** — when the user asks for what's *remaining* or *outstanding*. Triggers include: "what's left on the to do list?", "what's remaining?", "what's open?", "what's pending?", "what still needs doing?", "what's outstanding?". Command:
```
grep -nE '^## ' TODO.md | grep -v '— DONE'
```
For each open item, also surface its `**Created:** YYYY-MM-DD` from the detail file so the user sees how long it has been outstanding. Quick lookup:
```
grep -h '^\*\*Created:\*\*' todo/<filename>.md
```

**Everything (open + completed)** — when the user asks for the full list. Triggers include: "what's on the to do list?", "the whole todo list", "the entire todo list", "show me all todos", "everything on the list". Command:
```
grep -nE '^## ' TODO.md
```

Summarise the matching headers in plain English. The index is short by design (each item is 4 lines: title + file + summary + blank), so reading the whole index is cheap — but headers alone are usually all the user wants. NEVER load detail files unless the user drills into a specific item.

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
