# TODO list convention

The user maintains a two-layer TODO system:
- `TODO.md` (workspace root) — short scannable INDEX of all tasks
- `todo/<descriptive-name>.md` — one detail file per task

## How to add an item

When the user says "add X to the to do list" (or any equivalent — "put that on the list", "add this to the todo", "save that as a todo"):

1. **Write a detail file** at `todo/<descriptive-name>.md` containing all pertinent context:
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

**Everything (open + completed)** — when the user asks for the full list. Triggers include: "what's on the to do list?", "the whole todo list", "the entire todo list", "show me all todos", "everything on the list". Command:
```
grep -nE '^## ' TODO.md
```

Summarise the matching headers in plain English. The index is short by design (each item is 4 lines: title + file + summary + blank), so reading the whole index is cheap — but headers alone are usually all the user wants. NEVER load detail files unless the user drills into a specific item.

## Why this two-layer system exists

The user wants rich, recoverable context captured in the moment without bloating the index, then a short scannable list later to pick what to work on next. Don't paste full file contents into TODO.md — that defeats the index pattern.
