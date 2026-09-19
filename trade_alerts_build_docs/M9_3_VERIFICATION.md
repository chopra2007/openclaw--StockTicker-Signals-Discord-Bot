# M9.3 blocked assessment and acceptance failure diagnosis

Status: blocked. M9.3 has no product implementation in this milestone.
The full milestone change is ROADMAP.md and this record. Existing code, tests,
configuration, protected launchers and switches remain unchanged.

## Required gates

ROADMAP's M9.3 requirement depends on M4.6, M4.7, M5.5, selected M0.2
provider/queue/storage/disk/memory budgets, validated input continuity and AT-13
bounded-load proof. Section 31 records M4.7's adopted options and portfolio rules
as unavailable and M0.2's shared capacity and actual source coverage as unfinished.
The M9.3 row remains `[!]`. Reopen only when these prerequisite owners publish
their required proof. Actual delivery needs separately authorized evidence.

Proposed independent next milestone: M0.2, continuing its existing open audit
with supplied evidence and local metadata. The reviewer must confirm that scope.
No live access, spending, strategy rule, activation or return claim is added.

## Different repair approach and exact cause

The prior builder changed only ROADMAP.md to record the prerequisite block.
This repair read the first acceptance failure, its callers and shared test
setup before making any change. It did not retry the failed command.

The first failed case is
`tests/trade_alerts_contracts/test_orb5_replay.py::test_each_supplied_scenario_replays_its_own_recorded_states[short]`.
Its `replay()` calls `db.init_db()` before running the scenario. The trace reaches
`consensus_engine/db.py` in `_run_column_migrations()` while adding a database
column and reports:

```text
sqlite3.OperationalError: database or disk is full
```

Subsequent cases fail during temporary-folder setup. For example:

```text
OSError: could not create numbered dir with prefix test_a_refused_recording_leave in /tmp/pytest after 10 tries
```

The packet's other named errors are preserved here:

- `tests/trade_alerts_contracts/test_rs_trend_eligibility.py::test_the_measured_rs_and_compression_inputs_reach_armed[LONG]`
- `tests/trade_alerts_contracts/test_rs_trend_eligibility.py::test_the_measured_rs_and_compression_inputs_reach_armed[SHORT]`
- `tests/trade_alerts_contracts/test_rs_trend_eligibility.py::test_measured_inputs_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_rs_trend_eligibility.py::test_a_refused_recording_leaves_the_machine_below_armed`

The shared `tests/trade_alerts_contracts/conftest.py` fixture requires `tmp_path`
for every case. The storage error followed by folder-creation errors supports
test-environment storage exhaustion, outside this milestone's documentation
change. The logs do not establish which storage limit filled. No storage cleanup,
protection edit, application test or unchanged retry was attempted here. The
controller environment needs diagnosis and any protection repair needs its own
reviewed assignment; then it can run failing cases before broader acceptance.
Fixing that environment alone cannot close M9.3's separate prerequisite gates.

## Prior controller evidence, not a new acceptance claim

Controller run directory:
`/root/trade-alerts-builder/runs/20260913-032845-523298-build`.
The original result is retained in `attempt-history/build-1-build-result.json`;
`changes.diff` carries its ROADMAP-only delta. The packet's root
`build-result.json` was absent when read. Both `verification.log` and
`attempt-history/acceptance-1-verification.log` retain the failed acceptance.

The published focused proof is
`/root/trade-alerts-builder/runs/20260913-032845-523298-build/published-artifacts-06713fe7d6c1`.
Its `summary.json`, `publication.json`, `run-1/output.txt`, `run-1/results.xml`
and `run-1/isolation.json` retain the run result, artifact hashes and isolation
record. This earlier focused pass does not replace the later failed acceptance.

The following fields copy the supplied controller packet. Null means the
controller did not supply the figure; a future controller stage must supply it.
The acceptance phase name below identifies the failed stage described in the
packet; no successful broad publication or repeatability section was supplied.

```json
{
  "tests": {
    "phase": "acceptance",
    "runs": 1,
    "test_count": null,
    "wall_seconds": null,
    "selection_reason": "unknown dependency impact; safe broad fallback",
    "selectors": ["tests/trade_alerts_contracts"],
    "exit_code": 1,
    "artifacts_path": "",
    "focused": {
      "artifacts": true,
      "artifacts_path": "/root/trade-alerts-builder/runs/20260913-032845-523298-build/published-artifacts-06713fe7d6c1",
      "at": "2026-09-13T03:38:29-07:00",
      "exit_code": 0,
      "phase": "focused",
      "protected": true,
      "run": "/root/trade-alerts-builder/runs/20260913-032845-523298-build",
      "runs": 1,
      "selection_reason": "builder named directly affected checks",
      "selectors": ["tests/trade_alerts_contracts"],
      "stable": true,
      "test_count": 2922,
      "wall_seconds": 504.979
    }
  }
}
```

Focused pytest output: `2922 passed in 501.29s (0:08:21)`.
Focused JUnit time: `501.180` seconds. The separate controller wall time is
recorded above. Failed acceptance pytest output:
`1 failed, 2152 passed, 769 errors in 349.65s (0:05:49)`.
No failed-stage JUnit time or controller wall time was supplied.
No new pass, tested-source match, or repeatability claim is made by this repair.

## Current blocked assessment and record repair — 2026-09-15 Pacific

This section replaces the status statements above for current state; the earlier
sections stay as the historical record of the first M9.3 attempt and its failed
controller acceptance run. No figure, test ID or failure above is changed.

### What changed since the earlier sections

`M4.7A` was accepted on 2026-09-15 (build run `20260914-060429-391233-build`,
recorded in ROADMAP section 31 and `M4_7_VERIFICATION.md`). That clears only the
adopted options and portfolio dependency named in M9.3's requirement. It closes
no other gate.

### Gates still open

- Selected M0.2 provider, queue, storage, disk and memory budgets: the last M0.2
  rows are `[!]`. Both returned cost estimates exceed the USD 24 unreserved
  amount, billing is unknown, the OPRA HTTP 400 cause is unknown, three OPRA
  requests and dates before March 28, 2023 are unpriced, and local capacity
  admission is unresolved. This boundary needs an owner or data decision; no
  agent step closes it, and no further provider request, download or spending is
  authorized.
- Validated input continuity for the shadow pipeline depends on that same
  unresolved source and capacity evidence.
- The test-environment storage failure recorded above (database or disk full
  during setup, then temporary test folders could not be created) still needs a
  separately reviewed environment repair before another protected acceptance run
  of the full family. Disk on `/` remained tight when this record was written.

AT-13 bounded-load proof is recorded complete under M0.2D; it does not cover the
storage and continuity parts above.

### Complete M9.3 milestone change

Records only, across all M9.3 attempts:

- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/M9_3_VERIFICATION.md`

No product code, test, configuration, dependency or protected input changed in
any M9.3 attempt. No new protected run, pass, test count, timing or repeatability
comparison is claimed by this repair; the only protected figures for M9.3 are the
historical ones quoted in the earlier sections, copied there from the controller
packet.

### Cause of the rejected evidence and the different approach used

The two prior repair attempts reported `trade_alerts_build_docs/ROADMAP.md` as
the milestone delta but wrote nothing: the controller's `changes.diff` for build
run `20260915-221719-418520-build` is empty and its normalized
`actual_changed_files` is `[]`, because the ROADMAP row they described had been
written by the earlier M4.7A session, not by M9.3. They also never named this
evidence record, which the first M9.3 attempt created. So the reported delta
could not be verified and the evidence list was incomplete.

This attempt did not repeat that. It wrote the actual records: the truthful
`[!]` M9.3 blocked row in ROADMAP section 31 and this section, so the reported
delta matches real file changes, and it reports both files. The blocked verdict
itself is unchanged, because the gate is an owner, data and environment one that
is outside M9.3's own scope.

### Next step

No dependency-ready next milestone remains. Every other open row is a blocked
source, data, capacity or owner-decision gate, so the truthful stop is this
blocked assessment awaiting an owner or data decision, not a proposed milestone.
All switches remain off.

## Status after the owner-decision release — 2026-09-16 Pacific

The section above is now historical where it says the boundary "needs an owner
or data decision". The owner answered all five named items on 2026-09-16
(D-101 to D-105; ROADMAP "M0.2 / M9.3 owner-decision release"): a fresh USD 60
Databento total, the BRK.B OPRA symbol cause, a fixed one-year paid window,
freed local disk, and the D-104 gap policy.

M9.3 is still blocked, for a narrower reason: its dependencies need published
proof, not only decisions. Still missing:

- the selected mode's M0.2 provider, queue, storage, disk and memory budgets and
  validated input continuity, measured and recorded under D-104 (gaps recorded,
  dependent rules off and labelled untested);
- a verification run showing the storage repair cures the earlier
  "database or disk is full" and temporary-folder failures.

Proposed next milestone: `M0.2K` (added as an open row in ROADMAP), shared data
prerequisite work using data already held. The reviewer must confirm eligibility.

## M0.2K published the missing proof — 2026-09-16 Pacific

`M0_2K_GAP_REGISTER.json` and `M0_2K_VERIFICATION.md` (ROADMAP "M0.2K
finalization" section) now publish both items this section named as missing:
the selected offline recording-sink shadow mode's provider, queue,
storage/disk and memory budgets and its input continuity, and a protected
verification run (`test_orb5_replay.py`, `test_rs_trend_eligibility.py`, one
fresh process, 225 passed, exit code 0) showing the storage repair cures the
"database or disk is full" and temporary-folder failures recorded above. M9.3
itself is not implemented or accepted by this note; ROADMAP proposes it as the
next open row, subject to independent review, since M4.7A and M0.2K together
now cover every dependency this section named. The bounded compactor's own
narrower admission gap and every D-104-recorded field gap stay open.

Complete M9.3 change across all attempts is still records only:
`trade_alerts_build_docs/ROADMAP.md` and this file. No new protected run, count,
timing or hash is claimed for M9.3 itself; the M0.2K run above is M0.2K's own
evidence, referenced here. All switches remain off.

## Blocked on a missing replay adapter, not a data/owner gate — 2026-09-16 Pacific

M4.7A and M0.2K together close every dependency the earlier sections in this
file name. Reading the four playbook modules before making any change surfaces
a different, concrete gap that those sections did not name: M9.3's own text
requires proving "the initial pipeline with the first four playbooks" using the
shared M5.3 `Strategy` protocol (`consensus_engine/strategy_interface.py`) and
`HistoricalReplayRunner` (`consensus_engine/historical_replay.py`) — the same
runner M0.2K's selected offline recording-sink shadow mode is built on.

- `consensus_engine/orb5_replay.py`'s `Orb5ReplayStrategy` (M6.4) and
  `consensus_engine/hod_comp_rs_replay.py`'s `HodCompRsReplayStrategy` (M7.5)
  both subclass `Strategy` and are already driven end to end by
  `HistoricalReplayRunner.run()`, proved by
  `tests/trade_alerts_contracts/test_orb5_replay.py` and
  `test_rs_trend_eligibility.py`.
- `consensus_engine/or_failure_rev.py`'s `OrFailureRevMachine` (M8.2) and
  `consensus_engine/first_pullback_vwap.py`'s `FirstPullbackVwapMachine` (M8.4)
  do not subclass `Strategy` and expose only their own
  `ReversalRequest`/`ReversalAssessment` and
  `PullbackRequest`/`PullbackAssessment` shapes. Neither is callable from
  `HistoricalReplayRunner` today.

ROADMAP Phase 8 (M8.1 through M8.5) never reserved a milestone for that
adapter step for these two playbooks, unlike M6.4 and M7.5 for the first two.
That makes this a gap in the plan itself, not a data, source or owner-decision
gate: writing two new ~500-line `Strategy` adapters that correctly re-derive
`StrategyState`/`StrategyStateTransition` from each Machine's existing gate
logic is new, strategy-specific implementation work with its own correctness
risk and its own required protected test coverage, not a same-session
extension of M9.3's records-only budget/continuity proof. It is not
attempted in this M9.3 session.

`trade_alerts_build_docs/ROADMAP.md` section 31 records this as `M9.3 —
shadow mode: BLOCKED` (last row `[!]`) and adds `M8.6 — replay adapters for
OR_FAILURE_REV and FIRST_PULLBACK_VWAP` as an open `[ ]` next milestone,
proposed because it reuses only already-adopted M8.2/M8.4 gate logic and the
existing M5.3 runner, adding no new threshold, source claim or spending.
Independent review must confirm eligibility before the controller advances.

No code, test, configuration, dependency or protected input changed in this
M9.3 attempt; the only changes are this section and the matching ROADMAP
section. No new protected run is claimed. All switches remain off.
