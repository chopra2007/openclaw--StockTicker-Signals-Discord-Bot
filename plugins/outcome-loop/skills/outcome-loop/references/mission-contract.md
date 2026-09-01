# Mission contract

The mission is frozen JSON. Use `templates/mission.template.json` as the starting
shape. Version 1 requires a general domain label, a zero-exit deterministic goal
command, four feasibility commands (`data`, `access`, `cost`, and `permission`),
allowed and forbidden actions, decimal cost and attempt limits, evidence roots and
kinds, and declared stop conditions.

Checker commands are argument lists. They run directly without a shell, with a
clean environment, a 1–300 second timeout, and bounded output. List every checker
in `checkerFiles`. Feasibility commands must contain exactly one `{evidence}`.
Every goal input that is not a checker must be `{evidence:<id>}`. Direct work-file
arguments are refused.

Evidence IDs and kinds are lower-case slugs. Evidence must be a regular file under
an allowed repository root. The controller copies and hashes it. Source and copy
must remain unchanged through review and completion.

Candidate identity is the normalized method only: family, sorted unique inputs,
transformation, decision rule, and output. Names, thresholds, and claimed
differences do not change identity. Attempt 2 and later must name a rejected
attempt and list at least one method field that actually changed.

Use `status` or `resume` after interruption. The append-only hash-chained ledger,
frozen mission, and frozen checkers are the sources of truth. A missing view is
rebuilt. A corrupt ledger, mission, checker, or evidence file fails closed.
