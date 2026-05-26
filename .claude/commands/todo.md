---
description: TODO list — list, add, resume, pause, mark done
---

Read `todo/CONVENTION.md` and follow its rules. Route based on `$ARGUMENTS`:

- **Empty** (`/todo`) → list everything (open + completed). Use the "Everything (open + completed)" path in CONVENTION.md.
- **`open`** / **`pending`** / **`left`** → list open items only with their Created date. Use the "Open items only" path.
- **`resume N`** / **`N`** (a bare number) → resume task #N. Follow the "Resume" steps.
- **`pause`** → pause the active task. Follow the "Pause" steps.
- **`add <description>`** → add new task. Follow the "How to add an item" steps.
- **`done N`** / **`complete N`** → mark task #N done (append `— DONE YYYY-MM-DD` to its TODO.md header; update detail file status). Soak before removal.
- **`show N`** / **`look N`** / a bare number → read `todo/<filename>` for item #N and summarize.
- **Anything else** → interpret as natural language and route accordingly.

Always follow the rules in CONVENTION.md verbatim — never improvise on item numbering (stable IDs), deletion (requires explicit user approval), or the session-notes append format.

User input: `$ARGUMENTS`
