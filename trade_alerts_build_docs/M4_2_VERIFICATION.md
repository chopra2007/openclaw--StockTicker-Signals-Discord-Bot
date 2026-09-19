# M4.2 state transition engine — expanded protected proof complete

Date: 2026-09-06 Pacific. Status: **completed** for independent acceptance review.
Both fresh protected runs passed **826 tests**, including all **56 M4.2 cases**
and the four database checks added after review. Ordered test IDs and required
recordings match; isolation and cleanup passed. Section 13 records the inspected
proof and records-only finalization. Sections 3 and 7–12 retain historical
attempts and the earlier 822-test selection. No code, test, configuration or
protection file changed during finalization. The entire milestone still changes
16 paths. Saved proposed `next_milestone`: **M4.3**, after independent acceptance.

## 1. Assignment, preservation and acceptance

The assignment matches ROADMAP §31 and M4_1_VERIFICATION §5. Read all nine
canonical files in PROJECT_INDEX order, PREBUILD_REVIEW, relevant M0.4/M4.1
evidence, D-090 boundaries, PROJECT_RULES and WORKFLOWS. Earlier 720-test M4.1
proof is historical and does not verify these changes. The failing-test file
is empty and unchanged. No previous milestone was restarted or discarded.

The before-edit hashes and recoverable document/database-source copies are at
`/tmp/m42-start-9m_xh8kx/`; its manifest covers 555 source/test/protection/docs/
configuration files. Existing uncommitted work belongs to the owner. The scoped
read-only Git check confirmed prior config/provider/clock changes and untracked
foundation work. Its unrelated runtime permission errors did not justify touching
those files. No Git mutation, controller modification or runtime-memory edit ran.

Done for this assigned mechanism means: explicit supplied rules; correct ordered
state changes; complete canonical records and fixed session/config attribution;
no state advance on failed storage; exact retry without duplicate records;
temporary-database preservation; affected compatibility tests; deterministic
long/short end-to-end recordings; two passing protected runs; accurate records.
Independent review belongs to the supervisor. A read-only lookup helper checked
existing storage/test conventions and fixture imports only; it made no edits or
trading/acceptance decisions.

## 2. Implemented scope and required proof

`state_transitions.py` adds one serialized state owner using the M4.1 context and
state values plus existing canonical transitions. Rules supply an initial state
and exact allowed edges. Identity, original availability, evaluation order,
state/substate and feature/input references are checked. Invalid contract input
raises an explicit error without recording or changing state. An identical latest
retry returns its existing entry. No default trading graph or expiry time exists.

The recording boundary receives the complete immutable transition, full session/
configuration, rule definition/version, stable stream identity, position and
predecessor. Memory advances only after recording succeeds. The SQL store receives
an explicit existing database handle. Migration 35 adds one append-only table,
using the unchanged host transaction wrapper and existing initialization path.
Update/delete, conflicting identity/scope, competing positions and missing
predecessors cannot replace stored facts. Full event retention, atomic candidate/
delivery bundles and automatic restart recovery remain M5.1/M5.5.

There are **56 M4.2 cases**, all collected and passing in §13's expanded selection.
They include every canonical state, exact substates, immutable scope/configuration,
invalid identity/time/references, concurrent awaited writes, recording failures,
explicit invalidation/expiry/reset, missing inputs, actual SQL round trips and
rollback, duplicate retry, lost acknowledgment and additive migration/reopen.
C04-05's expected versions now include 35. Its original transaction, temporary
path, schema identity and close/reopen assertions remain intact.

Required protected selectors:

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_state_transitions.py`
- `tests/trade_alerts_contracts/test_strategy_interface.py`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/test_db.py`
- `tests/test_migration_idempotency.py`
- `tests/test_market_layer_schema.py`
- `tests/test_signal_events_tweet_routing.py::test_schema_version_34_and_nullable_event_link_exist`
- `tests/test_signal_events_tweet_routing.py::test_migration_34_upgrades_legacy_signal_events_idempotently`
- `tests/test_batch1_measurement_store.py`
- `tests/trade_alerts_contracts/test_core_price_features.py`
- `tests/trade_alerts_contracts/test_reference_inputs.py`
- `tests/test_db_youtube.py::test_init_db_survives_legacy_duplicates`
- `tests/test_db_youtube.py::test_tables_created`
- `tests/test_decision_outcomes_5d_20d.py::test_migration_adds_columns_idempotently_and_preserves_data`
- `tests/test_research_schema.py::test_research_tables_exist`

The directory covers all earlier foundation/feature/record/interface contracts.
The legacy selectors exercise existing schema, version 34, transaction and
measurement behavior. The four checks added after review also cover existing
YouTube tables and duplicate cleanup, research tables, and preservation of saved
5-day/20-day outcomes across migration and reopen. All use the unchanged protection. The two signal-event selectors avoid unrelated application
processing. The unchanged protection does not mount `scripts/check_batch2_trade_gate.py`,
required at import by test_batch2_trade_tracking, test_batch2_gate_check and the
Batch 2 quote-collection integration file. Those full-suite scripts are outside
this bounded selection and are not claimed passing. No existing Batch 2 table or
transaction code is changed. Full application/release checks remain M18 work.
No change to test protection is needed for this milestone.

Each long/short end-to-end case uses round-tripped supplied Bars, actual M2.2/M3.6
opening features, actual M2.3 Quote checks and M4.1's test-only strategy. The
canonical proposals pass through M4.2 and actual temporary-database storage.
Expected states at 06:34:59, 06:35:00, 06:35:01 and 06:35:02 Pacific are WATCHING,
SETUP_FORMING, ALERT_TRIGGERED and WATCHING. The last quote is stale; no candidate
remains. Invalidation, explicit reset and expiry produce nine saved transitions.
Replaying the first four adds no row; closing/reopening preserves all nine.
This verifies a supplied script only, not CRVOL_ORB5 eligibility or profitability.

Both runs must pass all 56 M4.2 cases with matching ordered IDs, zero failures,
errors or skips, no unexpected isolation denials and clean cleanup. Read the XML,
test logs, isolation and summary files. Each child must save
`m42-state-transitions-long-proof.json` and
`m42-state-transitions-short-proof.json`; corresponding files must match byte for
byte across runs and each stay below 100,000 bytes. Confirm nine ordered complete
entries per direction, original configuration/rules and no rows from replay.

## 3. Historical local checks and first verification handoff

This section records the initial attempt only. Its pending states and ownership
notes are historical; §11 records the narrower 822-test proof and §13 finalizes
the expanded selection. It is not a current test-result summary.

M4_2_LOCAL_CHECKS.json saves grammar/compilation, document checks, preservation and
source/test/protection hashes. No repository lint/type-check command is configured.
Compilation and source inspection do not count as passing tests.
M4_2_LAUNCHER_LIMITATION.txt saves the unchanged protected launcher's actual output.
Its exact exit/limitation and any read-only host checks are recorded in the JSON.

The local attempt exited 1 at the launcher's initial temporary-directory ownership
step, before child creation or test collection. Exact final error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-7unre0tj'`

No XML, isolation report or M4.2 recording was produced. Both protection files
remain unchanged. No unprotected alternative was run. This is a test-execution
limitation, not an M4.2 data/definition blocker; the roadmap row stays `[~]` pending
supervisor proof, rather than marking completed or removing the milestone.

The read-only running-program check returned:
`Failed to connect to bus: Operation not permitted (consider using --machine=<user>@.host --user to connect to bus of other user)`.
No active-state claim is made. The workspace shortcut resolves correctly; the
read-only recent model-drift/health-failure search returned zero matching lines.
No application startup, live check or restart was performed.

All five changed Python files pass local Python 3.10 grammar and compilation
checks. The legacy schema SQL is byte-identical after excluding the one additive
M4.2 block. The 80 local Markdown links, added-text checks, all nine canonical
files, eight playbooks, 31 functional rows and 22 additional capability rows
passed static checks. All prior blocked roadmap rows remain present. Captured
existing files outside this milestone have unchanged contents, ownership and
modes; configuration and both protection files are unchanged.

New-file ownership restoration was attempted and returned `[Errno 22] Invalid
argument` for each new path; M4_2_LOCAL_CHECKS.json preserves the exact per-file
errors. The supervisor must check host ownership with the protected proof.
Sandbox-displayed ownership does not establish host ownership. No permission
change was made to an existing owner file.

If local protection cannot start, the supervisor must execute the saved selection
externally through the unchanged launcher. One invocation runs both children.
Return the readable summary, both XML/isolation/log files, four M4.2 recordings
and tested-file manifest to a fresh builder. That session must verify matching
contents, finalize evidence and ROADMAP without changing code/tests, and return
completed only when all required M4.2 gates pass. The controller remains on M4.2
until successful proof and independent review. No alternate test or application
run may bypass protection.

## 4. Remaining project gates

This common mechanism needs no live access, purchase or new trading definition.
M0.2, M0.3B adoption, all other playbook definitions, required full source modes,
M3.3–M3.5 and every later feature remain tracked. State persistence does not
restore feature history, frozen playbook references, cooldowns, candidates or
delivery acknowledgment. Full AT-05/06/07 and M5 recovery remain unfinished.
All switches remain off. D-090 is unchanged; D-091 stays $0 used/$0 reserved.
Actual data checks or purchases require a separately authorized supervised step
using existing sources first. Synthetic examples establish neither source coverage
nor trading returns.

## 5. Exact next dependency-ready milestone

- [ ] **M4.3 — offline structural risk/target prerequisite**, proposed only after
  M4.2 protected verification and independent acceptance.

Use the already adopted D-090 M03A_ORB5_V1 §6 rules for the two named B research
variants. Build the pure supplied-input stop/risk/target selector, reusing existing
RiskLevel/TargetLevel and feature records. Inputs must explicitly carry frozen
anchor/ATR, valid price increment, crossing/entry reference, direction and a
versioned structural-level catalog with availability and per-family coverage.
Test raw/outward-rounded stop, positive directional R, the exact 0.35 extension
boundary, nearer obstacles, 1.5R T1, next distinct 2.5R T2, equal-price labels,
unknown increment, incomplete catalog and long/short symmetry using D-090's
FX-08/09 examples. Unknown inputs stay unavailable; do not invent obstacles,
level producers, swing paths, soft invalidation or runner formulas.

The selector can be built against supplied records without adopting M0.3B.
Actual anchor-path coverage, full structural producers/applicability/priority
and unavailable source branches remain required gates under M0.3B/M3.5/M4.3
before dependent action. Keep the offline result and required gated completion
as separate roadmap rows; a caller's fixture coverage flag proves no real source.
Do not implement full M3.5 or any strategy in this next slice. The independent
reviewer must validate this scope/ordering before the controller advances.
Saved `next_milestone`: **M4.3**.

## 6. Entire milestone changed paths

- `consensus_engine/db.py`
- `consensus_engine/state_transitions.py`
- `consensus_engine/transition_store.py`
- `tests/test_market_layer_schema.py`
- `tests/trade_alerts_contracts/test_foundations.py`
- `tests/trade_alerts_contracts/test_state_transitions.py`
- `tests/trade_alerts_contracts/test_core_price_features.py`
- `tests/trade_alerts_contracts/test_reference_inputs.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M4_2_VERIFICATION.md`
- `trade_alerts_build_docs/M4_2_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M4_2_LAUNCHER_LIMITATION.txt`

- [x] **M4.2:** implementation, expanded protected proof and records are complete in §13.
- [ ] **M4.3:** proposed independent next milestone within §5, after proof/review.

Status: **completed** for independent acceptance review. Both expanded runs
passed 826 tests, including the four added checks. Saved `next_milestone`: **M4.3**.

## 7. Historical first repair inspection — 2026-09-06 Pacific

Historical attempt only; its pending status is superseded by §§11–12.

The supplied failure summary reported exit 1 at 21:50:41 Pacific, stable tested
files, no published artifacts and no readable proof-copy path. The saved supervisor
verification log was readable. It shows the first child reached the unchanged
launcher's `subprocess.run` call with `timeout=300`, then raised
`subprocess.TimeoutExpired`. Its exact final suffix is
`timed out after 299.99996812001336 seconds`.
This is distinct from the builder's earlier local ownership error in §3. The
supervisor failure is not evidence of an assertion failure or passing tests.

The first child's detailed output could not be read. The exact command error was:

`tail: cannot open '/tmp/trade-alerts-m04-3x7b5nd0/run-1/output.txt' for reading: Permission denied`

No completed XML, isolation report or M4.2 recording was published in the supplied
handoff. No test count or slow-test diagnosis is inferred from that absence. The
supervisor must preserve and publish readable partial output and the pytest log
if another attempt times out, so a fresh builder can identify the slow operation.
Do not raise the limit, remove cases, bypass guards or call the application.

Before edits, all five M4.2 source/test hashes and both protection hashes matched
the preceding local record. The original 555-file snapshot showed no unrelated
content change. The read-only inspection covered the existing engine, storage,
additive migration and all 56 written cases. A bounded lookup confirmed that the
saved selectors cover the affected supported migration, schema, transaction and
measurement cases; it found no missing fixture or definite import/assertion error.
Source review is not executed proof. No speculative performance repair was made.

Recoverable copies and a 561-file repair-start manifest are saved at
`/tmp/m42-repair1-dne3rtkb/`. M4_2_LOCAL_CHECKS.json preserves the preceding local
attempt and records the fresh protection attempt, exact errors, file hashes and
document checks. M4_2_LAUNCHER_LIMITATION.txt keeps the earlier failure and the
fresh attempt separately. Host ownership still needs the supervisor check already
required in §3; displayed sandbox ownership is not host proof.

The fresh local attempt at **21:57:20 Pacific** exited 1 before child creation
or collection, at the unchanged launcher's initial `os.chown` step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-xf3f1p34'`

It produced no passing count or proof recording. This local failure cannot test
whether the supervisor's timeout repeats. All five changed Python files still
pass grammar/compilation checks; their contents and all 56 written cases are
unchanged. Successful protected execution remains the only M4.2 verification step
before the required records-only finalization and independent review.

- [~] **M4.2:** implementation preserved; two successful protected runs and
  matching long/short recordings remain required before records-only finalization.
- [ ] **M4.3:** saved proposed next milestone within §5, only after M4.2 proof
  and independent acceptance. It is not started by this repair.

Status: **ready_for_verification**. Saved `next_milestone`: **M4.3**. The
controller stays on M4.2. No required data/authority/definition blocker was found
for this common mechanism; all earlier blocked source and definition rows remain.
All switches stay off. No charged request, live access or trading claim is added.

## 8. Historical second repair inspection — 2026-09-06 Pacific

Historical attempt only; its pending status is superseded by §§11–12.

The latest supplied status reports protected exit 1 at **22:05:33 Pacific**, stable
files, no published artifacts and an empty readable-proof path. The saved
verification log confirms another timeout in the first child, before the launcher
could finish either run. Its exact exception suffix is
`timed out after 299.9999740560015 seconds` at the unchanged 300-second limit.
This supersedes §7 as the latest supervisor attempt; §7 remains historical.

Both detailed files were tried directly. The exact errors were:

```text
tail: cannot open '/tmp/trade-alerts-m04-gdj1ed3h/run-1/output.txt' for reading: Permission denied
tail: cannot open '/tmp/trade-alerts-m04-gdj1ed3h/run-1/pytest.log' for reading: Permission denied
```

No completed XML, isolation report, test count or M4.2 recording was supplied.
The failure summary's stable flag is not passing test evidence. The engine,
store, additive database change and existing cases were inspected before any
repair. A bounded read-only helper found repeated fixture construction but no
definite import error or measured slow operation. No speculative test rewrite,
case removal, protection change or timeout increase was made. The source has
19 test functions expanding to 56 written cases; this is a static count only.

All five M4.2 source/test hashes and both protection hashes match the prior
record. The controller's original 802-file content manifest confirms the entire
milestone still has exactly the 13 changed paths in §6. Recoverable copies and
a 552-file repair-start content/ownership/mode record are saved at
`/tmp/m42-repair2-1adw7_xq/`. No earlier owner work was discarded.

The unchanged protected launcher was tried with the full §2 selection at
**22:10:01 Pacific**. It exited 1 at its initial ownership step, before child
creation or test collection:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-uzqrwa95'`

M4_2_LAUNCHER_LIMITATION.txt and M4_2_LOCAL_CHECKS.json preserve this output and
the separate supervisor failure. No application or unprotected test ran. The
local failure cannot establish the cause of the supervisor's timeout.

**Remaining verification:** the supervisor must supply two successful protected
runs, matching long/short recordings, XML/isolation/log files, the tested-file
manifest and the host ownership check described in §3. If execution times out,
publish readable partial output and pytest.log before another diagnosis session.
Changing read permissions on a saved proof copy is a supervisor publication step;
this repair does not edit controller files or weaken either protection file.

- [~] **M4.2:** implementation preserved; successful protected proof is still
  required before records-only finalization and independent review.
- [ ] **M4.3:** saved proposed next milestone within §5, after M4.2 proof/review.

Status: **ready_for_verification**. Saved `next_milestone`: **M4.3**. The
controller stays on M4.2. No live/data/definition gate was added to this common
mechanism. Earlier blocked source/definition rows remain required. All switches
stay off; no spending, live access, trading rule or profitability claim is added.


## 9. Historical third repair inspection and preserved owner inputs — 2026-09-06 Pacific

Historical attempt only; its pending status is superseded by §§11–12.

The supplied protected status reports exit 1 at **22:20:53 Pacific**, stable files,
no artifacts and no readable proof path. The saved verification log confirms a
third timeout in the first child at the unchanged 300-second limit. Its exact
exception suffix is `timed out after 299.9999653759878 seconds`. Both child logs
were tried directly and returned these exact errors:

```text
tail: cannot open '/tmp/trade-alerts-m04-cowefu4b/run-1/output.txt' for reading: Permission denied
tail: cannot open '/tmp/trade-alerts-m04-cowefu4b/run-1/pytest.log' for reading: Permission denied
```

No completed proof or passing count was supplied. The failure summary does not
identify an assertion failure or a measured slow operation. The existing engine,
store, additive migration and all 19 M4.2 test functions were inspected. Counting
their parameter lists gives 56 written cases. Their hashes and both protection
hashes match the previous record. The read-only helper mapped repeated database
setup, but that source lookup supplies no timing evidence or timeout diagnosis.

The actual delta from the controller's 802-file starting manifest now has **15
paths**, including two existing owner edits absent from the supplied 13-path
list: `test_core_price_features.py` and `test_reference_inputs.py` under
`tests/trade_alerts_contracts/`. They reuse bounded, immutable synthetic history
inputs. Changed-input callbacks still receive separate lists. Coverage, feature
calculations and asserted results are not cached. Both files were preserved as
found; this session changed no code or tests.

A source-structure comparison against the saved starting copies confirms that
all test functions, parameter lists and bodies in those two files are unchanged,
as are all 164 core-price and 63 reference-input assertions. This is source
inspection, not passing execution. Their 54 and 46 previously written cases and
end-to-end paths still need fresh proof for the changed input helpers. Both files
are explicit selectors in §2 as well as members of the existing contract directory.
The full change list in §6 and M4_2_LOCAL_CHECKS.json includes both files.

Recoverable copies and a 233-file before-edit content/ownership/mode manifest are
saved at `/tmp/m42-repair3-nsskjxnk/`. All seven milestone Python files pass grammar
and compilation checks without importing or executing them. The original saved
manifest and this session's copies were checked; all prior owner work is retained.
No production or protection repair was made on an unmeasured timing assumption.

The unchanged protected launcher was attempted with the complete §2 selection at
**22:31:38 Pacific**. It exited 1 before child creation or test collection at its
initial temporary-folder ownership step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ntz2_91u'`

M4_2_LAUNCHER_LIMITATION.txt and M4_2_LOCAL_CHECKS.json preserve that exact output.
No unprotected test or application run followed. This local failure cannot prove
whether the owner input changes resolve the supervisor timeout.

**Remaining verification:** supply two successful runs through the unchanged
launcher with the full saved selection, matching ordered test IDs, zero failures,
errors or skips, clean isolation/cleanup, and matching long/short M4.2 recordings.
Also inspect matching `m31-core-price-features-proof.json` and
`m24-reference-inputs-proof.json` for the two affected input helpers. Return the
readable XML, isolation, logs, recordings, tested-file manifest and host ownership
check. If a timeout repeats, publish readable partial output and pytest.log before
another diagnosis session. Publishing a readable copy belongs to the supervisor;
this builder does not edit controller files, permissions or test protection.

- [~] **M4.2:** implementation and tests are ready; fresh successful protected
  proof remains before records-only finalization and independent review.
- [ ] **M4.3:** saved proposed next milestone within §5, after M4.2 proof/review.

Status: **ready_for_verification**. Saved `next_milestone`: **M4.3**. The
controller stays on M4.2. No required live/data/definition gate belongs to this
common mechanism. Earlier blocked source/definition rows remain required. All
switches stay off, with no spending, new trading rule or profitability claim.


## 10. Historical configuration-fixture repair — 2026-09-06 Pacific

Historical attempt only; its pending status is superseded by §§11–12.

The supplied status at **22:45:35 Pacific** still has exit 1, no published proof
copy and no artifact path. Direct reading of the latest supervisor verification
log changes the diagnosis: **both runs finished**, with **817 passed and five
failed** in **261.51 and 255.79 seconds**. Neither timed out. Both logged isolation
summaries have no unexpected denials and all four cleanup checks true. These
are failed-run summaries, not successful milestone proof. The summary, XML and
isolation files under the logged temporary path each returned `PermissionError:
[Errno 13] Permission denied`; no recording comparison or passing gate is claimed.
M4_2_LOCAL_CHECKS.json saves the exact read errors and verification-log hash.

All five failures are in `tests/test_market_layer_schema.py`:

- `test_new_flags_default_off[features.sector_rotation.enabled]`
- `test_new_flags_default_off[features.factor_rotation.enabled]`
- `test_new_flags_default_off[features.trend_regime.enabled]`
- `test_new_flags_default_off[features.internal_breadth.enabled]`
- `test_market_data_keys_present`

The first four report `assert None is False`. The fifth reports
`AssertionError: assert None == 'data/market_store'`. The launcher deliberately
omits the repository configuration and seeds its temporary file with only the
database path. The tests expected missing `features` keys. The existing shared
test fixture already forces the fifth macro flag false, explaining why that case
passed. This diagnosis comes from actual failures and the inspected loader and
fixtures; it is unrelated to the earlier unknown timeout causes.

The repair supplies a small non-secret configuration excerpt only when the
protected child marker is present. It writes a per-test temporary YAML file,
clears the loader cache through the existing test patch fixture and invokes the
real configuration loader. Ordinary suite runs still load repository settings.
It does not patch returned setting values, skip cases, alter assertions or mount
live configuration. A static comparison verifies all **11 excerpt values and
types** against the current `config/consensus.yaml`: five disabled flags, the
storage-path/provider strings and four 1,440-minute recency settings. Successful protected
execution will prove supplied-config compatibility; the separate source comparison
checks the repository values. Neither is a live activation or full release check.

Before editing, the existing engine, store, migration and all M4.2 cases were
inspected. A read-only helper found no omitted affected supported selector.
Only the market-layer fixture changed in this repair. All five test functions,
the existing database fixture, parameters and seven assertion expressions retain
their original bodies. All seven prior milestone source/test hashes and both
protection hashes match the previous record; owner input changes are preserved.
Eight milestone Python files pass grammar and compilation checks without imports
or execution. Recoverable copies of 20 relevant files and the failed supervisor
log are saved at `/tmp/m42-repair4-k5ss9zdj/`.

The unchanged local launcher at **22:55:18 Pacific** stopped before
child creation or test collection at the initial ownership step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-qj2rd_4q'`

The complete §2 selection remains required, including the full market-layer file.
The local protected attempt and its exact result are saved in
M4_2_LOCAL_CHECKS.json and M4_2_LAUNCHER_LIMITATION.txt. Fresh supervisor proof must
cover the repaired fixture, all 56 M4.2 cases, the earlier affected feature inputs,
matching ordered IDs, zero failures/errors/skips, clean isolation/cleanup and
matching M4.2 long/short plus M3.1/M2.4 recordings. Return readable proof, the tested
manifest and host ownership verification. A fresh builder then finalizes records
without changing source or tests; independent review still decides acceptance.

- [~] **M4.2:** test-fixture repair ready; fresh protected proof remains.
- [ ] **M4.3:** proposed next milestone within §5 after M4.2 proof and review.

Status: **ready_for_verification**. Saved `next_milestone`: **M4.3**. The controller
stays on M4.2. No launcher/guard/timeout change is needed. All prior source and
definition gates remain required, all switches stay off and no spending or live
access is added. This repair establishes no trading return.

## 11. Earlier protected proof and incomplete first finalization

These passing results remain evidence for the earlier 14-selector selection.
Review found it omitted the four compatibility checks now added to §2. The
completed status recorded below was the first finalization claim. Section 12
reopened missing coverage; §13 now finalizes the expanded proof.

The supervisor's protected run finished at **23:07:35 Pacific** against source
identity `c650429d4cb9be0266751bc30a587f82c4d6eba1f1d2fca1875c9584649fe186`.
Both children passed the then-saved 14-selector selection: **822 passed in 258.74 seconds**
and **822 passed in 254.21 seconds**. The ordered test IDs match. Both isolation
records report zero unexpected denials, a zero test exit code and all four cleanup
checks true.

The long M4.2 record is 52,627 bytes with SHA-256
`095254267472dfde371184fa449465ba1d9cde8631710f9dbcf7e56a4d39990c` in
both runs. The short record is 52,658 bytes with SHA-256
`a839fa776c4e9559067589a0bd8530f0d892ee7e09ee292130f6b31ee2c00ab0`
in both runs. Both stay below the 100,000-byte limit. The affected M3.1 and M2.4
records also match byte for byte across runs. The readable publication contains
both XML files, logs, isolation records and recordings. The separate supervisor
manifest records tested-file hashes and host ownership; it is not part of that
39-file proof publication.

This finalization changes records only. It does not change code, tests, the
launcher or its child. The earlier local launcher error and failed supervisor
runs remain historical evidence. No live access, data purchase, trading rule or
profitability claim follows from this proof.

- [x] **M4.2 at first finalization:** recorded complete for the earlier selection;
  review later reopened the missing compatibility proof in §12.
- [ ] **M4.3:** proposed next milestone within §5 after independent acceptance.

Historical first-finalization status: **completed**, superseded by §12. Its saved
`next_milestone` was **M4.3**. Earlier required source
and definition rows remain open, all switches remain off, and full M5 recovery
remains unfinished.


## 12. Historical review repair — expanded database compatibility proof

This section records the repair before fresh proof arrived. Its pending status
and local launcher limitation are superseded by §13; no verification gap remains
from this attempt.

The reviewer found conflicting current-status text and four missing existing
compatibility checks after the shared database initialization changed. This
records-only repair preserves all prior code, test fixtures and assertions.
The four exact selectors are now in §2 and M4_2_LOCAL_CHECKS.json, together with
all 14 earlier selectors. They use temporary databases under the existing
protection. No launcher, child guard or timeout change is needed.

The saved publication was inspected again: both XML files contain 822 passing
cases, with zero failures/errors/skips and matching ordered IDs. Neither contains
any of the four newly required cases. All 39 published artifact hashes match.
Both isolation reports are clean. Long and short M4.2 recordings and affected
M3.1/M2.4 recordings match across runs. These earlier results remain valid for
that selection; they cannot establish the missing compatibility coverage.

ROADMAP §§9/29/31, PROJECT_INDEX §35, TESTING_AND_VALIDATION §64 and DECISIONS §42
now agree: implementation is finished; the expanded protected proof remains.
Old failed local attempts and earlier repair states are explicitly historical.
M4_2_LOCAL_CHECKS.json separates the earlier successful selection, historical
failures and the current expanded selection. Recoverable before-edit copies are
at `/tmp/m42-compatibility-repair-a13shla2/`. The full milestone change list in §6
still has 16 paths, including all earlier repairs and preserved owner inputs.

The local launcher at **23:25:40 Pacific** exited 1 before child creation or
collection, at its initial temporary-folder ownership step. Exact final error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-wohbdoo_'`

No XML, isolation report or new recording was produced. The complete output is
saved in M4_2_LAUNCHER_LIMITATION.txt and the JSON's current review-repair record.
The separate supervisor manifest confirms the earlier source/test/protection
hashes and records host ownership/modes; the repair changes records only. If local execution stops before collection, return
ready_for_verification. The supervisor must run all 18 saved selectors through
the unchanged launcher, which runs two children. Require every named compatibility
case, all 56 M4.2 cases, matching IDs and required recordings, no failures/errors/
skips, clean isolation/cleanup and a tested-file/ownership manifest. Return the
readable proof to a fresh builder for records-only finalization, then independent
review. Do not count the earlier 822-test selection as that expanded proof.

- [~] **M4.2:** implementation finished; expanded protected proof remains.
- [ ] **M4.3:** proposed next milestone within §5, after M4.2 proof and acceptance.

Status: **ready_for_verification**. Saved `next_milestone`: **M4.3**. No required
live/data/definition gate belongs to this common mechanism. Prior blocked rows,
all eight playbooks and every later feature remain required. All switches stay
off; no spending, live access, new trading rule or profitability claim is added.

## 13. Expanded supervisor proof finalized — 2026-09-06 Pacific

The supervisor returned fresh protected proof at **23:38:41 Pacific**, with source
identity `c909fa22bf4146a0f1bd637f9b9dfcd5ccbf65880e4ec26899c645b3857bdaa6`.
This records-only session inspected the publication, summary, both XML reports,
logs, isolation records and required recordings. All **39 published artifact
hashes** match. All **808 tested file contents** matched the separate tested-file
manifest before editing. That manifest also confirms the expected host ownership
of all 16 milestone paths. No host ownership claim comes from sandbox-displayed IDs.

The complete **18-selector** selection in §2 passed twice: **826 tests in 280.13
seconds** and **826 tests in 255.66 seconds**, within the unchanged limit. Each
run includes all 56 M4.2, 55 M4.1, 54 M3.1 and 46 M2.4 cases and all four added
database checks. Both have zero failures, errors or skips, matching ordered IDs,
no unexpected isolation denials and all four cleanup checks true. Expected
guard self-check denials remain separate. M4_2_LOCAL_CHECKS.json saves the actual
selectors, counts, artifact hashes and manifest fingerprint.

The long M4.2 recording is **52,627 bytes**, with SHA-256
`095254267472dfde371184fa449465ba1d9cde8631710f9dbcf7e56a4d39990c`.
The short recording is **52,658 bytes**, with SHA-256
`a839fa776c4e9559067589a0bd8530f0d892ee7e09ee292130f6b31ee2c00ab0`.
Corresponding records are byte-identical across runs and below 100,000 bytes.
Each direction contains nine ordered entries, an intact predecessor chain and
fixed session/configuration/rules. The observed states are WATCHING,
SETUP_FORMING, ALERT_TRIGGERED and WATCHING; the stale final observation has no
candidate. Replaying the first four changes adds zero rows. Closing and reopening
preserves all nine records. Affected M3.1/M2.4 recordings and both M4.1 recordings
also match byte for byte across runs.

Recoverable before-edit copies and verification details are saved at
`/tmp/m42-expanded-finalization-ehvbj44g/`. Only seven evidence/status documents
changed in this finalization. The entire milestone still has the 16 paths in §6,
including earlier repairs and owner inputs. Source, tests, configuration, both
protection files and the failing-test list are unchanged. No test or application
was rerun here. Earlier failed attempts and the narrower 822-test proof remain
historical, not open M4.2 gates.

All 74 local documentation links, required selector paths, status/next-step
references and added-text checks passed. All nine canonical files, eight
playbooks, 31 functional rows, 22 additional capability rows and earlier blocked
roadmap rows are preserved. Observed ownership and modes are unchanged.

- [x] **M4.2 — state transition engine:** implementation, expanded protected
  compatibility proof, long/short end-to-end evidence and records are complete.
- [ ] **M4.3 — offline structural risk/target prerequisite:** proposed next
  milestone within §5 after independent acceptance.

Status: **completed**. Saved `next_milestone`: **M4.3**. No required live, data,
authority or definition gate remains for this shared mechanism. The supervisor's
separate reviewer still decides acceptance. All earlier blocked rows, M0.3B
proposals and full M5 recovery remain open. All switches stay off; D-091 stays
$0 used and $0 reserved. This software proof establishes no provider coverage,
live readiness, new trading rule or profitability.
