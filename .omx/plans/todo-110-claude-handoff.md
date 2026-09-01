# TODO #110 Claude handoff

Continue in `/home/openclaw/.openclaw/workspace`. Do not redo the implementation or the proof runs.

## What is finished

- The reusable plugin is under `plugins/outcome-loop/` and registered in `.agents/plugins/marketplace.json`.
- The controller is `plugins/outcome-loop/scripts/outcome_loop.py`.
- The focused plugin run passed: `105 passed in 303.29s`.
- Plugin, skill, mission, Python compile, unused-code, ownership, and whitespace checks passed.
- The full project run passed on 2026-08-31: `3846 passed, 1 skipped, 3 deselected, 10 warnings in 861.63s`.
- The three excluded cases are the already-known hanging forms of `tests/test_gemini_video_parser.py::test_extract_evidence_chunked_budget_abort_keeps_partial`.
- `.omx/outcome-loop/todo-110-analyst-dry-run` is COMPLETE on attempt 2. Its independent reviewer rejected attempt 1.
- `.omx/outcome-loop/synthetic-trading-dry-run` is COMPLETE on attempt 2. Its independent reviewer rejected attempt 1.
- Fresh resume and repeated final checks left both ledgers and final results byte-for-byte unchanged.
- The #111 draft mission and one-line kickoff are in `.omx/plans/todo-111-outcome-loop-mission.json` and `.omx/plans/todo-111-outcome-loop-kickoff.md`. Do not start #111 while closing #110.
- Older proof runs were moved recoverably under `.omx/outcome-loop-archives/`.

## Important fixes already made

- Exact review fields and reviewer fields are checked everywhere: submission, replay, final checking, and completed-run loading.
- Approval cannot contain findings. Rejection must contain a concrete finding.
- Controller, builder, and reviewer IDs must all differ.
- Repository changes are allowed only after feasibility and build start. The final goal check is allowed only at the final stage.
- Two simultaneous mission starts produce one successful run and one clean refusal. Partial initialization is recoverable.
- Mission files, checkers, evidence, reviews, state, ledgers, and final results reject unsafe links and changed bytes.
- The one-time review value is never saved in the review output.

## What remains

1. Run a fresh independent code review. It must return `APPROVE` with no unresolved blocker.
2. Run a fresh independent design review. It must return `CLEAR` with no unresolved blocker. The last attempt did not review the fixes because that reviewer hit its usage limit.
3. Run the final small cleanup check after the last repairs. Do not rewrite working code unless it finds a real issue.
4. Write `.omx/evidence/todo-110/final-quality-gate.json` with the focused test, full project test, proof-run, cleanup, code-review, and design-review evidence.
5. Mark Ultragoal goal G003 complete and record the final checkpoint in `.omx/ultragoal/ledger.jsonl`.
6. Update this TODO item to DONE only after steps 1-5 pass. Run `python3 scripts/todo_status_sync.py --fix` and then `--check`.
7. Save the closing changes locally. Do not push unless the owner separately approves it.

## Honest limitation

The ledger is hash-linked but not signed by an outside key. A person who can replace every saved file can fabricate a new internally consistent history. The plugin does detect ordinary corruption, changed evidence, unsafe links, illegal stage changes, reused reviewer identity, stale reviews, and altered final results.
