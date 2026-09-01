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

`allowedActions` must contain `modify_repository` and `run_goal_check`. The
controller asks for those two by name: `start-build` consumes an open
`modify_repository` authorization and `final-gate` consumes an open
`run_goal_check` one. A mission missing either is refused at validation.
`modify_repository` is authorized in `PLANNED` and `run_goal_check` in
`FINAL_GATE`; every other action may be authorized in `PLANNED` or `BUILDING`,
so repair-cycle spend still passes the budget check.

Evidence IDs and kinds are lower-case slugs. Evidence must be a regular file under
an allowed repository root. The controller copies and hashes it once, when it is
recorded. That copy is the durable record and must stay unchanged through review
and completion; the source file is only a snapshot at record time and may keep
changing, because the repair loop is expected to edit it.

Candidate identity is the normalized method only: family, sorted unique inputs,
transformation, decision rule, and output. Names, thresholds, and claimed
differences do not change identity. Attempt 2 and later must name a rejected
attempt and list at least one method field that actually changed.

Use `status` or `resume` after interruption. The append-only hash-chained ledger,
frozen mission, and frozen checkers are the sources of truth. A missing view is
rebuilt. A corrupt ledger, mission, checker, or evidence file fails closed.
