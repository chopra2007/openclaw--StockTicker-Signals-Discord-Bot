# Close the remaining outcome-loop maintenance gaps
**Status:** OPEN
**Created:** 2026-09-01

**CURRENT STATUS (2026-09-01):** The reusable outcome loop is complete and
verified. Five non-blocking maintenance gaps remain. They cannot create a false
`COMPLETE`, but they can waste work, omit useful failure history, or slow every
command. Fix them without changing the accepted evidence-copy and repair rules.

## Goal

Close the five issues left after the independent design and code reviews of the
outcome-loop plugin.

## Priority-ordered next steps

1. Add a `maxRepairCycles` budget field so repeated review or final-check repair
   cannot loop forever. Both shipped dry runs use a zero-dollar budget, so cost
   checks do not provide this limit.
2. Record repository changes made during repair cycles. Today
   `modify_repository` is allowed only before the first build, so later repair
   edits do not appear in the action ledger.
3. Stop `build-result` when any unrelated authorization is still unfinished,
   instead of carrying it to the final gate and spending a repair cycle there.
4. Record refused review submissions and blocked final gates. The event names
   exist, but replay rejects them and the controller never writes them.
5. Avoid walking the whole repository once per command argument, and avoid
   repeating frozen-file validation when a cheaper unchanged check is safe.

## Constraints

- Preserve the accepted rule that final checks read hashed evidence copies, not
  working files that may change during repair.
- Preserve recoverable repair behavior. Do not add a source-file hash rule that
  permanently traps an attempt after a legitimate repair edit.
- Keep the controller general. Trading rules belong in mission files.
- Add a failing test for each behavior before changing it.

## Files involved

- `plugins/outcome-loop/scripts/outcome_loop.py`
- `plugins/outcome-loop/tests/test_outcome_loop.py`
- `plugins/outcome-loop/templates/mission.template.json`
- `.omx/plans/todo-110-outcome-loop-spec.md`

## Open questions

- Whether all five fixes belong in one version change or should be split into
  the repair-limit/ledger work and the command-speed work.
