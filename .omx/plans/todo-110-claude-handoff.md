# TODO #110 Claude handoff

Continue in `/home/openclaw/.openclaw/workspace`. Do not redo the implementation
or the proof runs. Work is committed locally on `master`, not pushed.

Last session: 2026-08-31 into 2026-09-01. It ran the two independent reviews the
previous handoff asked for. Both came back BLOCK, not the expected pass, so the
session became a repair pass. Six blockers were found and fixed across two
rounds. A seventh is open and is the first thing to do.

## Where the reviews stand

- **Design review: `VERDICT: CLEAR`.** Both of its blockers fixed and verified by
  the reviewer. It also withdrew its own suggested alternative after I showed it
  would refuse the repair case. Nothing outstanding from design.
- **Code review: still BLOCK, on one new blocker only.** It accepted both of my
  divergences from its proposed fixes, and explicitly withdrew its own mechanism
  for the evidence blocker after testing my trap argument and failing to break it.

## THE ONE OPEN BLOCKER — do this first

**A runaway checker fills the host disk.** I replaced the pipe-draining reader
threads in `clean_run` with temporary files (that fix was correct and is
accepted — it removed a whole class of hang). But the old pipe reader silently
discarded everything past `MAX_OUTPUT`, so output cost zero disk. The temp file
has no cap: `MAX_OUTPUT` is now applied only afterwards, at
`handle.read(MAX_OUTPUT)` in `plugins/outcome-loop/scripts/outcome_loop.py`.

The reviewer verified this on this machine. A checker looping
`sys.stdout.buffer.write(b'x'*(1<<20))`, killed at its 4-second timeout:

```
free at start: 29.3 GB   lowest during run: 1.0 GB   consumed: 28.3 GB
stdoutTotalBytes 2337050624   captured 1048576   truncated True
```

28.3 GB of 29.3 GB free, gone in four seconds. `tempfile.TemporaryDirectory()`
is called with no `dir=`, so the spool lands in `/tmp`, which is on `/` here —
the same filesystem as `consensus-engine.service`, the gateway, the SQLite
database, and the git checkout. `timeoutSeconds` may be up to 300, so the
ceiling is roughly 150 GB of writes against 28 GB of headroom. This needs no
hostility: a stray `print` in a loop does it.

**Reviewer's recommended fix.** Cap the spool. Poll `path.stat().st_size` in a
short wait loop (`process.wait(timeout=0.2)` inside a `while`, then `killpg`
when either the deadline or a byte cap is hit) and set `timed_out` or an
output-overrun flag. That bounds only the captured streams and keeps the current
truncation semantics. The existing 3 MB / 2 MB totals in
`test_goal_checker_output_capture_is_bounded_and_explicitly_truncated` sit far
below any sane cap, so a 64 MB cap leaves that test unaffected. The reviewer
noted `resource.RLIMIT_FSIZE` via `preexec_fn` is fewer lines but blunter,
because it applies to every file the child writes, not just the captured
streams — its full argument was cut off by a message truncation, so re-derive
that trade-off rather than trusting this summary of it.

After fixing, re-run the focused suite and send the code reviewer a re-review to
get its `VERDICT: APPROVE`.

## What was fixed last session (all verified, all committed)

Each fix has a regression test that was confirmed to FAIL against the pre-fix
controller before being accepted.

1. **Editing a recorded evidence file bricked the entire mission.** Every
   command died, including `status` and `stop`, with no recovery. This hit the
   build-repair loop, the plugin's core purpose. `evidence_ok` now verifies the
   *copy* under the run directory, not the live working file. The copy is the
   only thing review and the goal check ever read.
2. **A checker that exited but left a background child hung the controller
   forever**, holding the mission lock; the timeout never fired. Fixed, then
   found still broken for a child that calls `setsid` and escapes the process
   group (killpg cannot reach it; a daemon-thread fix also fails because
   `BufferedReader.close()` blocks on the reader thread's own lock). Final fix:
   the child writes to temp files instead of pipes, so nothing waits on a
   writer. The 120.4-second hang now returns in 0.1 s. **This is what introduced
   the open disk blocker above.**
3. **A misspelled action name in a mission file passed validation, then killed
   the run permanently** at first use (permission breach → STOPPED, terminal).
   `validate_mission` now requires `modify_repository` and `run_goal_check` in
   `allowedActions` and names the missing one.
4. **Repair-cycle spend never reached the ledger.** Authorization was only legal
   before building started. `authorize-action` and `complete-action` are now
   legal in BUILDING for every action except the two pinned by design
   (`run_goal_check` stays FINAL_GATE, `modify_repository` stays PLANNED).
   Replay validators mirrored; `legal_next` updated.
5. **`COMPLETE` could be certified with the implementation deleted from the
   repo.** The gate now requires recorded evidence sources to still *exist* —
   existence only, deliberately not an unchanged hash (see the trap below).
6. **Swapping a recorded source file for a symlink still bricked every command.**
   Outside the gate the source is now resolved lexically and never touched on
   disk (new `lexical_repo_path`); at the gate it is a real check, where a
   refusal is recoverable via `repair-final-gate`.

Also: `money()` rejects `Infinity`/`NaN` as a Refusal instead of a TypeError
traceback; `fingerprint()` rejects non-string method inputs the same way; the
verifier skill now states an approval must carry no findings.

## Reasoning you must not re-litigate blindly

**Why the gate checks evidence existence but NOT the source hash.** Both
reviewers initially proposed a source-hash check at the final gate. It is a
trap. Evidence ids cannot be re-recorded inside an attempt (`cmd_evidence`
refuses a duplicate id), and no repair event clears the current-attempt evidence
set — `cmd_repair_final` returns to BUILDING without clearing it. So an entry
recorded earlier in the attempt, whose source a repair cycle legitimately
edited, stays in the current-attempt set forever and the gate becomes
permanently unpassable, recoverable only by abandoning the attempt. The code
reviewer independently verified this, tested the narrower variant of hash-
checking only the evidence the goal command consumes, found it traps
identically, and withdrew its proposal: *"Existence-only is the strongest
recoverable check the current evidence model allows."* The design reviewer
withdrew its equivalent suggestion for the same reason.

**What `COMPLETE` now means, and where that is written down.** It means the
hashed evidence copies passed the frozen goal check — not that the repository as
it now stands passes. A file edited after being recorded leaves the live code
differing from what was certified. This is stated plainly in
`skills/outcome-loop/SKILL.md` at the design reviewer's request and with its
approval, and `test_goal_check_reads_the_reviewed_copy_not_the_working_source`
asserts it directly.

**An orphan-spawning checker is not failed.** With no drain to block on, a
checker that exits 0 inside its timeout passes even if it left a background
child. The old behavior was an unbounded hang, not a verdict, so nothing
regressed. Both the reviewer and I judged that failing a checker for its
children would be a new policy punishing a normal idiom.

## Tests: three existing tests were rewritten, deliberately

These asserted the bricking behavior itself. Do not restore them without
reading the trap argument above.

- `test_missing_or_changed_source_or_copied_evidence_blocks_completion` →
  `test_missing_or_changed_copied_evidence_blocks_completion`
- `test_changed_or_unrecorded_goal_input_blocks_completion` → split into
  `test_goal_check_reads_the_reviewed_copy_not_the_working_source` and
  `test_changed_copied_goal_input_blocks_completion`
- `test_repeated_final_gate_rechecks_every_source_and_copied_evidence[source|copied]`
  → `test_repeated_final_gate_rechecks_copied_evidence_from_every_attempt` plus
  `test_completed_run_survives_edits_to_working_sources`
- `test_same_byte_symlink_substitution_of_recorded_evidence_is_rejected` was
  narrowed from `[source, copied]` to `copied` only; the source semantics are
  now owned by the two new symlink tests at the end of the file.

The frozen spec was amended to match: `.omx/plans/todo-110-outcome-loop-spec.md`
line ~419, final-gate item 8, invariant 6, and acceptance-matrix entries 13 and
24. All 32 test names the spec cites were checked to exist in the suite.

## Test state

- Focused plugin suite: **119 passed in 342.56 s**, clean run, current code.
- Both proof runs still verify `COMPLETE` byte-for-byte under the changed
  controller: `.omx/outcome-loop/todo-110-analyst-dry-run` and
  `.omx/outcome-loop/synthetic-trading-dry-run`.
- **The full project suite has NOT had a clean run against the final code.**
  The one run that finished (`3957 passed, 2 skipped, 3 deselected` in 1230 s)
  is contaminated and must be discarded: I was A/B-swapping the original
  controller into the tree at the same time to prove the new tests fail without
  the fix, and pytest read the swapped file mid-run. Re-run it clean, with no
  concurrent swapping, before closing:

  ```
  python3 -m pytest tests/ plugins/outcome-loop/tests/ -q --tb=no -p no:cacheprovider \
    --deselect tests/test_gemini_video_parser.py::test_extract_evidence_chunked_budget_abort_keeps_partial
  ```

  Note the deselect: that is the known hanging test named in the previous
  handoff. Baseline before this work was `3846 passed, 1 skipped, 3 deselected`.

## Known open items — reported, not silently dropped

Neither reviewer treats these as blocking. Put them on the TODO list.

1. **The repair loop is unbounded.** `repairCycle` has no ceiling anywhere and
   `attempt` only increments through `reset_attempt`, so a reviewer that keeps
   returning REJECT/repair loops forever. My first argument — that making repair
   spend budget-checked bounds it — is WRONG, and the design reviewer corrected
   it on two counts: both shipped dry runs use `maxCostUsd: "0.00"` so a
   zero-cost authorization always passes, and nothing forces repair work through
   an authorization at all (`cmd_build_result` only requires the *builder's*
   authorization to be complete). It is a liveness problem, never a soundness
   one — it cannot write a false `COMPLETE`. A `maxRepairCycles` beside
   `maxAttempts` in `budget` would be the cheap fix, reusing the existing
   `attempt_limit_reached` stop condition. Deliberately not done: it changes the
   mission schema, and both reviewers called it out of scope for closing #110.
2. **Repo edits during a repair cycle are still off-ledger.** `modify_repository`
   stays pinned to PLANNED, so the second and later passes of a repair loop
   modify the repository with no open authorization. Pre-existing, not a
   regression, but it sits oddly beside the stated motivation for the BUILDING
   change: repair *spend* now reaches the ledger while repair *repo changes*
   still do not.
3. **An open non-`modify_repository` authorization in BUILDING** passes
   `build-result`, survives review, then trips "unrelated authorization remains
   open" at the final gate. Costs a repair cycle to recover.
4. **The ledger records successful steps only.** `review_invalid` and
   `final_gate_blocked` are listed in `EVENTS` but replay refuses them and
   nothing emits them, so a refused review submission or a blocked final gate
   leaves no trace. Both reviewers agreed leaving them is better than churning
   the spec — but say so in the closing evidence.
5. **`validate_command` runs `root.rglob(arg)` per argument**, a full tree walk
   per argument on every command, and `frozen_valid` re-validates on every
   command. Slow, not wrong.

## What remains, in order

1. Fix the open disk blocker above.
2. Get `VERDICT: APPROVE` from a code reviewer on the fixed code. The previous
   reviewer has the full history; a fresh one will need the trap argument.
3. Re-run the focused suite and the full project suite clean.
4. Write `.omx/evidence/todo-110/final-quality-gate.json` with the focused test,
   full project test, proof-run, cleanup, code-review, and design-review
   evidence. Record the design review as CLEAR with its reviewer identity, and
   record known open items 1-5 above.
5. Mark Ultragoal goal G003 complete and record the final checkpoint in
   `.omx/ultragoal/ledger.jsonl`.
6. Update this TODO item to DONE only after 1-5 pass. Run
   `python3 scripts/todo_status_sync.py --fix` then `--check`.
7. Save locally. Do not push unless the owner separately approves it.

Do not start #111 while closing #110. Its draft mission and one-line kickoff are
in `.omx/plans/todo-111-outcome-loop-mission.json` and
`.omx/plans/todo-111-outcome-loop-kickoff.md`.

## Honest limitation

The ledger is hash-linked but not signed by an outside key. A person who can
replace every saved file can fabricate a new internally consistent history. The
plugin does detect ordinary corruption, changed evidence copies, unsafe links,
illegal stage changes, reused reviewer identity, stale reviews, and altered
final results.

Separately: the controller prints the one-time review capability, so a
controller agent can mint any reviewer identity that merely differs from its own
and the builder's, then self-approve. `validate_review_contract` can only check
distinctness, never provenance. This is acknowledged in
`skills/outcome-loop/SKILL.md`. Do not let the framing drift into "a false pass
cannot be faked".
