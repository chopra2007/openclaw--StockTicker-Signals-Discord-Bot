# M5.1 typed append-only research event store

Date: 2026-09-08 Pacific. Status: **completed for independent review**.
Section 15 finalizes two fresh protected runs for the repairs in sections 10–14.
Earlier pending states, failures and section 9's older proof remain historical.
No code or tests changed during this finalization.

## 1. Assignment, preservation and scope

The assigned M5.1 matches ROADMAP section 31 ("Persist state, snapshots,
alerts, suppressions, option snapshots, versions") and the dependency-ready
M5.1 scope recorded in M4_6_VERIFICATION section 5. It reuses the host
database canonical records and transactions, the existing M4.2 append-only
transition table, the full M4.4/M4.5 attribution, and the M4.6 injected
delivery intent/result boundary.

All nine canonical files were read in PROJECT_INDEX order, then
PREBUILD_REVIEW, the relevant milestone evidence and docs/agents/PROJECT_RULES.md.
No finished work was redone and no proposed decision (M0.3B, M4.7 options or
portfolio rules) was adopted. All uncommitted owner files were preserved. No
Git mutation, commit, push, stash, reset, clean, checkout, branch or worktree
change occurred. No setup command, background supervisor, nested controller,
session-close skill, bot restart, review, broker or Discord call, message,
order or deployment occurred. The cumulative D-091 allowance stays unchanged
($0 used, $0 reserved); this offline lane makes no charged request.

Done for this offline scope requires: minimum append-only storage and typed
linkage for supplied raw, window, state, candidate, component, suppression,
option, configuration records plus delivery intent and result; preserved
original facts; rejection of conflicting ids and links; missing data kept
visible and never converted into favourable facts; atomic rollback, idempotent
retry and reopen proved in temporary databases with a recording sink; affected
compatibility tests; and updated evidence and roadmap. No strategy, option
ranker, outcome rule, live sender, deduplication or full M5.5 recovery is
built or claimed.

## 2. Initial implementation report (superseded by section 7)

`consensus_engine/event_store.py` adds `ResearchEventStore` (version M51_V1).
It persists supplied canonical records through the host `db.execute_...`
transaction into a new append-only table, and satisfies the injected M4.6
`save_intent`/`save_result` boundary without changing `deliver_candidate` or
the delivery adapter.

`consensus_engine/db.py` (additive change only) adds the table
`trade_alerts_research_events_v1` with UPDATE and DELETE triggers that abort
("append-only table") and bumps the schema version to 36. No existing table,
column or migration is modified.

Typed event kinds: CONFIGURATION, RAW_INPUT, FEATURE_SNAPSHOT,
STATE_TRANSITION, CANDIDATE, SUPPRESSION, OPTION_RESULT, DELIVERY. Every row
holds a stable record_id, a SHA-256 fingerprint of the serialized facts, the
serialized facts, and typed links (INPUTLINK, RAWLINK, FEATURELINK,
CONFIGLINK, CANDIDATELINK).

Behavior:
- Identical replay of the same record_id/kind/facts is idempotent (returns the
  stored row instead of rewriting).
- Reusing a stored record_id with different facts or a different kind is
  rejected.
- A link to an already-stored record whose kind is outside the allowed role is
  a conflicting link and is rejected.
- A missing linked input stays absent and is never converted into favourable
  data.
- `store_assembly` and `save_intent` each write as one atomic transaction, so
  a failure on one row leaves no partial bundle (proved by a forced trigger).
- `save_result` writes SEND_STARTED and the final delivery records append-only.
- Reopen preserves every stored fingerprint and serialized fact exactly.

## 3. Initial files and unverified local reports (historical)

Files changed by this milestone:
- `consensus_engine/event_store.py` (new)
- `consensus_engine/db.py` (additive schema 36 table, version bump)
- `tests/trade_alerts_contracts/test_research_event_store.py` (new, 6 cases)

The 6 cases build a real candidate (real opening-range history, confidence,
M4.5 assembly), persist the full assembly and run the injected delivery path,
proving: typed facts are append-only and idempotent; conflicting fact/id reuse
is rejected; UPDATE/DELETE are blocked by the trigger; assembly round-trip,
kind coverage and reopen preservation; intent and result through the real
deliver_candidate; duplicate pending intent refused; and atomic rollback
leaves no partial bundle.

Pre-proof local child-simulation passed the 6 cases plus the surrounding
alert-delivery, candidate-assembly, state-transition, domain, confidence,
strategy-interface and opening-range contracts (283 and then 288 cases in two
targeted runs) and the migration-idempotency, market-layer-schema, and
specified outcome schema selectors. The full-directory simulation's two
failures and a timeout are the already-documented M18.4 network-isolation gap,
not this change. Local simulation is not protected proof.

## 4. Required protected selectors

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_research_event_store.py`
- `tests/trade_alerts_contracts/test_alert_delivery.py`
- `tests/trade_alerts_contracts/test_candidate_assembly.py`
- `tests/trade_alerts_contracts/test_state_transitions.py`
- `tests/trade_alerts_contracts/test_domain_models.py`
- `tests/trade_alerts_contracts/test_confidence.py`
- `tests/trade_alerts_contracts/test_strategy_interface.py`
- `tests/trade_alerts_contracts/test_opening_range_features.py`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_migration_idempotency.py`
- `tests/test_market_layer_schema.py`
- `tests/test_signal_events_tweet_routing.py::test_schema_version_34_and_nullable_event_link_exist`
- `tests/test_signal_events_tweet_routing.py::test_migration_34_upgrades_legacy_signal_events_idempotently`
- `tests/test_decision_outcomes_5d_20d.py::test_migration_adds_columns_idempotently_and_preserves_data`
- `tests/test_db_youtube.py::test_init_db_survives_legacy_duplicates`
- `tests/test_db_youtube.py::test_tables_created`
- `tests/test_batch1_measurement_store.py`
- `tests/test_research_schema.py::test_research_tables_exist`
- `tests/test_db.py`
- `tests/trade_alerts_contracts/test_foundations.py`
- `tests/test_batch2_trade_tracking.py::test_storage_retries_keep_stable_entity_ids_without_duplicate_facts`
- `tests/test_batch2_trade_tracking.py::test_batch2_fact_tables_reject_update_and_delete`

The migration, market-layer and outcome selectors are the legacy compatibility
tests directly affected by the additive schema-version 36 bump; they passed in
local simulation. The two unrelated listener tests with unfaked reaction
requests remain the saved M18.4 isolation gap; they are not run outside
protection and not claimed passing.

## 5. Local launcher limitation

The unchanged protected launcher was attempted with the M5.1 selectors and
stopped before collection at its first ownership operation:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-*'`

This is the same sandbox `os.chown` limitation recorded for milestones M2.2
through M4.6 and is saved in M5_1_LAUNCHER_LIMITATION.txt. No workaround,
weaker protection, or direct legacy run was used. The supervisor must run the
protected launcher and return two fresh readable runs before the offline row
may be marked complete. Local compilation and simulation are not protected
proof.

## 6. Historical pre-proof gates and next work

- [!] **M4.7 — minimum options and portfolio path:** exact adopted option
  filters, factors, ranking/ties, strategy policies, cooldown/fingerprints and
  confluence/reversal ownership remain unavailable. M0.3B stays proposed.
  AT-08/AT-09 and actual-source evidence remain required (M4_6_VERIFICATION §5).
- [~] **M5.1 — research event store (offline implementation):** code and
  contract tests are ready; the protected-execution gate must pass and be
  reviewed before this row is completed.
- [ ] **M5.2 — outcome evaluator:** MFE/MAE/max R/T1/T2/stop/timing, same-bar
  ambiguity conservative. This is the dependency-ready independent next step
  (ROADMAP §31) and is the suggested next_milestone for the handoff.

This returns `ready_for_verification`. No required live, data, authority or
definition gate belongs to this milestone; the controller stays on M5.1 until
protected verification and independent review pass.


## 7. Verification-failure repair — historical handoff

The supplied controller summary reports a failed protected attempt at 23:37:26
Pacific on 2026-09-07, exit code 1, with no artifacts and no readable proof path.
It supplies no test traceback or measured cause. That summary does not establish
that tests ran, passed, or failed for any particular reason. The earlier local
simulation claims in section 3 have no inspected protected artifacts and are not
accepted proof. No simulation or direct legacy test was run in this repair.

Inspection found incomplete storage beyond the missing supervisor proof:
identical assembly retries still inserted duplicate keys, link checks missed
same-bundle and later-arriving targets, full confidence policy/context was lost,
and delivery storage dropped supplied options, rendered text and receipt details.
The original six tests did not save an end-to-end recording. Those readiness
claims are superseded by this repair; all original test cases remain.

Current implementation preserves the existing table and supplied record methods.
It adds transaction-time identity and forward/reverse link checks. Identical
facts retain their first stored row; conflicting kinds, facts, sessions,
configuration hashes/versions and exact option contracts fail atomically.
Identical assembly/history/result retries add no rows. Repeated delivery intents
are refused even when identical, preserving the M4.6 no-blind-resend boundary.
Missing references are reported as UNAVAILABLE by links(), without synthetic
records; a compatible later input resolves the reference without rewriting facts.

The store now retains full assembly/confidence/context, history requests and
conventions with original Bars/revisions, supplied components/catalysts/options,
rendered text, and delivery reasons/attempts in append-only versioned envelopes.
Existing canonical records stay separately readable. M4.6's existing assembly
check is reused. SQLite checks run inside the host transaction so separate store
instances cannot race past a prior Python-only check. M4.2 transition storage,
all old database functions and earlier migrations remain intact. M5.5 still owns
runtime reconstruction and delivery reconciliation; no live consumer is added.

The repaired file has 21 written cases. They add repeat/shared-input bundles,
forward/reverse and same-bundle conflicts, missing then supplied references,
session/configuration/contract identity, competing store owners, all eleven
supported canonical types, and both directions of the recording pipeline.
The pipeline uses supplied Bars, actual history/opening-range calculations,
actual confidence composition (66), supplied risk/share (1) and target (2R),
actual candidate/component assembly, separate suppression and unavailable options,
then real storage and the recording sink. It asserts full retained facts, safe
retry and byte-for-byte reopen equality. These are written assertions, not
passing results or actual market-data coverage.

Require the full section 4 selection in two fresh protected runs, with matching
ordered IDs, zero failures/errors/skips, clean isolation and cleanup. Each run
must publish m51-research-event-store-long-proof.json and
m51-research-event-store-short-proof.json, each below 100,000 bytes and identical
across runs. Inspect candidate geometry, quality, option missingness, recording
receipt, all stored IDs/kinds/fingerprints and resolved/unavailable references.
The full assembly/history equality assertions must pass in both runs. Existing
compatibility selectors are preserved; the research-table and core database
checks are added for the shared initialization change.

M5_1_LOCAL_CHECKS.json records current compilation, hashes, preservation checks
and the exact fresh launcher result. M5_1_LAUNCHER_LIMITATION.txt contains its
verbatim output. The launcher stops before collection at its ownership step.
No new protected pass is claimed, and neither protection file was changed.
Status remains ready_for_verification: successful protected execution is the
remaining gate. A fresh builder must inspect supervisor artifacts and finalize
records without code/test changes before independent review.

### Saved next work

- [~] M5.1: repaired offline storage awaits the two protected runs above.
- [ ] M5.2: proposed after M5.1 verification and review; implement the supplied
  input outcome evaluator under TESTING_AND_VALIDATION sections 15–16/49/51 and
  adopted D-090 O-01. Keep missing data and ambiguous ordering visible. Do not
  invent unadopted costs, borrow assumptions, sub-minute observations or other
  strategy horizons; retain those separate required definition/data gates.
- [!] M4.7 and every earlier source/definition gate remain required and unchanged.

Saved next_milestone: M5.2. The controller stays on M5.1 until proof and review
pass. All ten milestone paths from the supplied starting-delta list remain in the
final report, including earlier attempts. All switches remain off. No credentials,
live access, spending, Git mutation or profitability claim was introduced.

## 8. Schema expectation repair — 2026-09-08 Pacific

The controller reports 1,244 passing tests and a failing foundation migration
expectation in the previous protected attempt. This is a supplied summary only:
no readable XML, isolation files or recordings were returned. It cannot finalize
M5.1 or establish a successful two-run result.

The existing partial repair in `tests/trade_alerts_contracts/test_foundations.py`
now expects the exact versions 7 through 36 with `list(range(7, 37))`. Inspection
confirms migration 36 exists in db.py. All rollback, reopen, exact schema and
version preservation assertions remain. No further code or test edit was needed.
The earlier repaired db.py, event_store.py, research tests and both protection
files match section 7's saved hashes. The complete milestone delta now has eleven
paths, including the foundation test correction supplied before this session.

The section 4 selection is retained in full, with the explicit additional selector
`tests/trade_alerts_contracts/test_foundations.py`. It is also inside the directory
selection. The unchanged launcher was attempted again and stopped at os.chown
before collection. M5_1_LAUNCHER_LIMITATION.txt saves the exact output;
M5_1_LOCAL_CHECKS.json saves fresh hashes and Python 3.10 syntax/compilation checks.
No direct tests, child simulation, protection changes or application run occurred.

Require both fresh protected processes to pass the complete saved selection,
including the exact schema test, with matching ordered IDs, no failures/errors/
skips and clean isolation/cleanup. Section 7's complete long/short recording
requirements remain unchanged. The supervisor must return readable proof for
records-only finalization before independent review.

- [~] M5.1: implementation ready; protected execution is the sole remaining gate.
- [ ] M5.2: proposed supplied-input outcome evaluator after M5.1 proof and review,
  within section 7's adopted O-01 scope and preserved definition/data limits.
- [!] M4.7 and all earlier required source/definition gates remain unchanged.

Status: ready_for_verification. Saved next_milestone: M5.2. All switches remain
off. No live access, spending, new trading rule or profitability claim is added.

## 9. Protected proof finalized — 2026-09-08 Pacific

The readable supervisor proof returned at **00:16:15 Pacific** was inspected:
summary, both XML reports, output/log files, isolation records and long/short
recordings. All **59 published artifact hashes** and all **833 tested file
contents** matched before this records-only finalization. The saved manifest
records consistent host ownership for all eleven milestone paths. Code, tests,
configuration and both protection files remain unchanged. No application or
test was rerun in this finalization.

Both protected runs passed **1,245 tests**, including all **21 M5.1 cases** and
the repaired exact schema-version check, in **293.177 and 284.538 seconds**
(XML durations). Every section 4 selector plus section 8's foundation selector
is present. Ordered test IDs match; failures, errors and skips are zero.
There are no unexpected isolation denials, and every cleanup check passed.
M5_1_LOCAL_CHECKS.json saves the inspected hashes, selection and results.

The long/short recordings match byte for byte across runs at **11,304/11,325
bytes**. Each preserves 20 rows, full assembly attribution and identical facts
after reopen. Supplied entry is 100; long stop/target are 99/102 and short
stop/target are 101/98. Risk/share is 1, target is 2R and quality is 66.
Component, history, raw-input, configuration, suppression and delivery links
are resolved in these complete supplied examples. Options remain UNAVAILABLE;
the recording receipt says RECORDING_ONLY with zero send attempts. The separate
missing-link case passes and preserves UNAVAILABLE until a compatible input
arrives. Retry, rollback, competing-owner and full-history/assembly assertions
pass in both runs. No synthetic example proves actual source coverage or returns.

The local ownership error in M5_1_LAUNCHER_LIMITATION.txt and the prior
1,244-pass failed-attempt summary remain historical. Successful protected
proof now completes the assigned common storage scope. Full automatic recovery,
delivery reconciliation and strategy reconstruction remain M5.5; actual sources,
options/portfolio rules and all earlier blocked rows keep their existing owners.
No required live/data/authority/definition gate remains for this assigned M5.1.
The separate reviewer still decides acceptance.

- [x] M5.1: implementation, protected proof and records-only finalization complete.
- [ ] M5.2: proposed next after independent review, limited to section 7's
  supplied-input outcome evaluator under adopted D-090 O-01. Preserve its
  separate unadopted-cost, borrow, source and unsupported-resolution gates.
- [!] M4.7 and all earlier required source/definition gates remain unchanged.

Saved next_milestone: **M5.2**. All eleven milestone paths remain in the handoff.
All switches stay off. No live access, spending, new rule or profitability claim
is added. D-091 remains $0 used and $0 reserved.


## 10. Primary-feature identity review repair — 2026-09-08 Pacific

Review found that FEATURELINK checked only the target kind. Direct append could
resolve a candidate's primary feature to another stock, instrument type or
session. The transaction-time checks in db.py now enforce all three identities
for AlertCandidate primary links in both insertion orders. Reference-market
INPUTLINK ancestors remain allowed. Canonical records, earlier migrations,
store methods and both protected-launcher files are unchanged.

The 21 prior storage cases remain. Twelve new cases cover each of the three
identity fields in both insertion orders through append and through a bundle.
Append must reject the second record, leave the first record byte-identical and
keep a missing primary link unavailable. Bundle failure must also undo the valid
configuration record written before the conflicting pair. These are 33 written
storage cases, not a passing count.

Both long/short recording pipelines now exercise all six append rejection paths
using their actual assembled candidate and feature records, retain each result,
and check unchanged original candidate bytes and exact reopen equality after the
rejections. The earlier complete 20-row pipeline proof remains in each recording;
additional repair-path rows are separately exercised after that snapshot.
Synthetic inputs establish no actual source coverage or trading returns.

Require every section 4 selector in two fresh protected runs. The two named
trade-tracking compatibility checks are now mandatory. Require all 33 storage
cases, zero failures/errors/skips, matching ordered test IDs, clean isolation and
cleanup, and byte-identical expanded long/short recordings below 100,000 bytes.
Section 9's 1,245-test result predates the repair and omitted those two selectors;
it is historical evidence only. The supplied readable proof copy belongs to that
older source and is not reused as current proof.

The current local result and hashes are saved in M5_1_LOCAL_CHECKS.json; the exact
launcher output is in M5_1_LAUNCHER_LIMITATION.txt. No direct legacy tests, child
simulation, application run, live access, spending or protection change is allowed.
If the local launcher cannot execute, the supervisor must return fresh protected
proof to a new builder for records-only finalization, then independent review.

- [~] M5.1: identity repair and test assertions ready; fresh protected proof required.
- [ ] M5.2: proposed next after M5.1 proof and independent acceptance, within
  section 7's supplied-input O-01 scope and its preserved definition/data gates.
- [!] M4.7 and every earlier source/definition gate remain required and unchanged.

Saved next_milestone: **M5.2**. All eleven milestone paths from the saved delta
remain in the handoff. All switches stay off. No product rule is added.


Current local launcher result: exit 1 before collection at os.chown,
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-32lnz0ks'`.
This is the sole execution limitation. Python 3.10 grammar and compilation
passed for the four milestone Python files without importing the application.
Static checks found all 33 written cases, preserved prior test functions and
non-recording test bodies, valid local document links and unchanged protection.
No configured lint/type checker was found. These checks do not replace tests.
The supervisor must verify host ownership and publish two successful protected
runs, then return their proof for records-only finalization. Status remains
ready_for_verification; saved next_milestone remains M5.2 after acceptance.


## 11. Batch 2 test import isolation — 2026-09-08 00:38:20 Pacific

The supplied failure summary says the two required Batch 2 storage selectors
could not collect: the module imported `scripts.check_batch2_trade_gate`, which
is outside the protected mount. No readable supervisor artifacts were supplied.
The existing partial fix in `tests/test_batch2_trade_tracking.py` moves that
import into the three gate-only tests that use it. Inspection confirms the two
selected storage tests do not use that helper. A syntax-tree comparison against
the existing tracked file confirms all other test bodies and assertions remain
unchanged. No additional code or test edit was needed in this session.

All saved hashes for db.py, event_store.py, the foundation and research-store
tests, and both protection files still match section 10. The primary-feature
identity repair, all 33 written storage cases and both expanded recordings are
preserved. Five milestone Python files passed grammar and compilation checks
without application imports. These are source checks, not passing tests.

The unchanged launcher was attempted with every section 4 selector. It stopped
before collection at os.chown with the exact error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-pqczpvgw'`

M5_1_LAUNCHER_LIMITATION.txt appends the verbatim output and preserves earlier
attempts. M5_1_LOCAL_CHECKS.json saves the import check and fresh file hash.
Require two fresh protected runs of the entire section 4 selection, including
both Batch 2 storage selectors, and all section 10 recording checks. The
supervisor must return readable XML, isolation, cleanup and recording proof to
a fresh builder for records-only finalization, followed by independent review.
No protection change or direct test workaround was used.

- [~] M5.1: implementation ready; successful protected execution is the sole
  remaining execution gate. No current passing result is claimed.
- [ ] M5.2: proposed after M5.1 proof and independent acceptance, within
  section 7's supplied-input O-01 scope and preserved definition/data limits.
- [!] M4.7 and all earlier source/definition gates remain required.

Status: ready_for_verification. Saved next_milestone: **M5.2**. The full milestone
delta now contains **twelve paths**, including the supplied Batch 2 test fix.
All owner work and switches are preserved. No live access, spending, new rule
or profitability claim is added.


## 12. Protected timeout retry — 2026-09-08 00:49:02 Pacific

The controller's 00:44:11 Pacific failure summary supplied no readable proof copy.
The saved supervisor verification log was read. Its first protected child timed
out at the unchanged 300-second limit. Attempts to read that child's output.txt
and pytest.log both returned `Permission denied`. No completed test count or
measured slow-test cause is available. This timeout is separate from the local
ownership error and does not establish a code failure or a passing result.

All seven saved source, test and protection hashes match section 11. The identity
repair, Batch 2 import fix, all 33 written storage cases and both expanded
recording pipelines remain intact. No code, test or protection file was changed.
The five milestone Python files passed fresh Python 3.10 grammar and compilation
checks without application imports. Those checks are not passing test evidence.

The unchanged launcher was retried with every section 4 selector. It stopped
before collection with `OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-o1m6u518'`. The verbatim output is appended to
M5_1_LAUNCHER_LIMITATION.txt; M5_1_LOCAL_CHECKS.json saves this attempt.

The supervisor must run the complete selection twice and publish readable XML,
output, isolation, cleanup and expanded long/short recordings. If a child times
out again, publish readable partial output and pytest.log for diagnosis. Do not
raise the protection limit, omit cases or run tests outside protection. Successful
proof must return to a fresh builder for records-only finalization and independent
review. Earlier 1,245-test proof remains historical.

- [~] M5.1: implementation ready; successful protected execution remains required.
- [ ] M5.2: proposed after M5.1 proof and review, within section 7's supplied-input
  O-01 scope and its preserved definition/data gates.
- [!] M4.7 and every earlier required source/definition gate remain open.

Status: ready_for_verification. Saved next_milestone: **M5.2**. All twelve
milestone paths remain in the handoff. All switches stay off. No live access,
spending, new product rule or profitability claim is added.


## 13. Supplied setup repair and repeated timeout — 2026-09-08 01:17:03 Pacific

The supplied 01:09:13 Pacific failure summary has no readable proof copy. The
supervisor verification log confirms its first protected child exceeded the
unchanged 300-second limit. Both output.txt and pytest.log returned `Permission
denied` when read. The slow path and completed count remain unknown.

One additional partial change was already present at session start:
`tests/test_batch2_trade_tracking.py::test_batch2_fact_tables_reject_update_and_delete`
now builds its temporary database once and loops over the same five tables and
two operations. All ten UPDATE/DELETE rejection checks and the exact expected
error remain. The previous test text was reconstructed and matched its saved
hash; syntax-tree comparison confirms every other function is unchanged.
This preserves the supplied repair. Its time saving has not been measured, and
no successful protected execution is claimed. Ten separate reported cases become
one reported test with ten checks; this is not removal of a table or operation.

The other six source/test/protection hashes match section 12. Primary-feature
identity checks, all 33 storage cases, expanded long/short recordings and the
Batch 2 import fix remain intact. No code, test or protection file was edited in
this session. Five milestone Python files passed grammar and compilation checks
without application imports. These checks do not replace protected tests.

The unchanged launcher was attempted with the complete section 4 selection.
It stopped before collection with `OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ptsgqh19'`.
M5_1_LAUNCHER_LIMITATION.txt preserves verbatim output; M5_1_LOCAL_CHECKS.json
records the new supplied test hash and this retry.

Require two complete protected runs of every section 4 selector and section 10's
expanded recording proof. If a run times out again, publish readable partial
output and pytest.log for diagnosis. Do not raise the limit, remove checks or
run outside protection. Successful proof must return for records-only
finalization and independent review. Section 9's earlier proof is historical.

- [~] M5.1: implementation ready; protected execution remains the sole open gate.
- [ ] M5.2: proposed after M5.1 proof and review, within section 7's supplied-input
  O-01 scope and preserved definition/data limits.
- [!] M4.7 and every earlier required source/definition gate remain open.

Status: ready_for_verification. Saved next_milestone: **M5.2**. All twelve
milestone paths remain in the handoff. All switches remain off. No live access,
spending, new product rule or profitability claim is added.


## 14. Supplied identity-test setup repair — 2026-09-08 01:32:10 Pacific

The latest supervisor log reports `1259 passed, 10 warnings in 294.70s
(0:04:54)` in its first run, followed by a second-child timeout at the unchanged
300-second limit. This differs from section 13's earlier first-child timeout.
The current handoff supplies no readable proof copy. Reading the second child's
output.txt and pytest.log returned `Permission denied`. Its completed count and
slow path remain unknown. One log summary does not close the two-run proof gate.

A further owner partial repair was present at session start in
`tests/trade_alerts_contracts/test_research_event_store.py`. The two primary-feature
identity tests now each create one temporary database and loop through all three
identity fields and both insertion orders. All twelve rejection/rollback checks
remain; there are now **23 reported storage cases**, including two tests with
six checks each, instead of 33 individually reported cases. The append helper
still checks unchanged stored facts, absent rejected rows and unresolved primary
links. Each bundle check compares the whole store before and after rejection.
Both long/short recordings still include all six append rejection paths and
reopen preservation. No check or recording path is intentionally removed.

The current storage-test hash differs from section 13's saved hash. The other
six source/test/protection hashes match. The current test bodies were inspected;
an exact reconstruction of the prior file was not established. This session
changed no code, tests or protection. Five milestone Python files passed grammar
and compilation checks without application imports. No time saving or passing
result is claimed for the supplied repair.

The unchanged launcher was attempted with the full selection (the directory
selector includes its named child files). It stopped before collection with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-2fi5nb6t'`.
M5_1_LAUNCHER_LIMITATION.txt saves verbatim output and M5_1_LOCAL_CHECKS.json
saves the current hashes and result. Local source checks do not replace tests.

Require two fresh complete protected runs, all 23 storage cases with the twelve
identity checks, both required Batch 2 storage tests, and matching expanded
long/short recordings under section 10's requirements. Publish readable partial
output and pytest.log if a timeout repeats. Do not change the protection limit,
omit checks or run outside protection. Successful proof must return to a fresh
builder for records-only finalization before independent review.

- [~] M5.1: implementation ready; protected execution remains the sole open gate.
- [ ] M5.2: proposed after M5.1 proof and review, within section 7's supplied-input
  O-01 scope and preserved definition/data limits.
- [!] M4.7 and every earlier required source/definition gate remain open.

Status: ready_for_verification. Saved next_milestone: **M5.2**. All twelve
milestone paths remain in the handoff. All switches stay off. No live access,
spending, new trading rule or profitability claim is added.

## 15. Repair protected proof finalized — 2026-09-08 Pacific

The supervisor proof returned at **01:44:34 Pacific** was read: summary, both
XML reports, output and test logs, isolation reports and expanded recordings.
All **59 published artifact hashes** and **833 tested file contents** matched
before finalization. The tested manifest records consistent host ownership for
all twelve milestone paths. Code, tests, configuration and both protection files
remain unchanged. No application or test was rerun in this records-only session.
M5_1_LOCAL_CHECKS.json saves the inspected proof and its hashes.

Both fresh protected runs passed **1,249 tests**, including all **23 M5.1 cases**,
the two identity tests with twelve checks, both required Batch 2 storage tests,
and the exact versions-7-through-36 foundation assertion. XML durations are
**283.650 and 290.883 seconds**. The directory selector includes every named
contract file in section 4; all remaining selectors ran explicitly. Ordered test
IDs match. Failures, errors and skips are zero; there are no unexpected isolation
denials and every cleanup check passed. The ten reported warnings are retained
in the supervisor logs. Earlier 1,245-test proof and incomplete 1,259-test attempt
are historical; they do not describe this repaired selection.

Expanded long/short recordings match byte for byte at **12,092/12,113 bytes**.
Each has all six stock/type/session rejection paths in both insertion orders.
Every rejection leaves stored facts unchanged and the rejected record absent;
both initial reopen and reopen after rejection preserve exact facts. Each original
pipeline keeps 20 rows, full assembly attribution, resolved supplied links,
risk/share 1, target 2R and quality 66. Options remain UNAVAILABLE; delivery is
RECORDING_ONLY with zero send attempts. Separate passing cases prove missing-link
status, bundle rollback, stable retries and competing-owner protection.

The long recording SHA-256 is
`5a34168849a516af60ad437bc2aad5edc713c0bf7890b5f8f7470d57ab142a79`;
the short recording SHA-256 is
`63f41036a98086befc5f6fe46e9ff0fe2a63ed2eb57cec52e88290cdae498139`.
These supplied examples prove software behavior, not actual source coverage or
trading returns. The earlier local launcher errors remain historical.

- [x] **M5.1:** implementation, repaired protected proof and records-only
  finalization complete for independent acceptance review.
- [ ] **M5.2:** proposed next after review, within section 7's supplied-input
  outcome evaluation under adopted D-090 O-01. Preserve its separate unadopted
  cost, borrow, source and unsupported-resolution gates.
- [!] **M4.7** and every earlier required source/definition gate remain open.

No required live, data, authority or definition gate remains for this common
M5.1 storage mechanism. M5.5 retains full runtime recovery and delivery
reconciliation. The separate reviewer decides acceptance before advancing.
Saved next_milestone: **M5.2**. All twelve milestone paths remain in the handoff.
All switches stay off; D-091 remains $0 used/$0 reserved. No live access, purchase,
new trading rule or profitability claim is added.
