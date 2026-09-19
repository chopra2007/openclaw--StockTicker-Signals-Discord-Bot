# M4.1 shared strategy interface — protected proof complete

Date: 2026-09-06 Pacific. Status: **completed**. The earlier local launcher
limitation is retained in §3 as historical evidence. Fresh supervisor proof is
recorded in §7. Proposed next milestone after review: **M4.2**.

## 1. Assigned scope and preservation

The assignment matches ROADMAP §31 and M3_6_VERIFICATION §5. All nine canonical
files were read in the required order, followed by PREBUILD_REVIEW and relevant
M0.4/M1.3/M3.6 evidence, approved D-090 state boundaries, PROJECT_RULES and
WORKFLOWS. Existing records and interface patterns were inspected before editing.
The read-only lookup helper inspected existing test/recording and launcher paths;
it made no edits or acceptance decisions.

The before-edit manifest and recoverable document copies are in
`/tmp/m41-start-h4s_xfj9/`. They cover 230 source/test/protection/document/config
files. The existing failing-test file is empty and remains unchanged. The prior
saved M3.6 evidence reports 665 passing tests in each protected run; that is
historical evidence, not a current M4.1 test run. Existing uncommitted source,
configuration, prior tests, data and records belong to the owner and are preserved.
The initial broad read-only Git status reported permission-denied messages for
unrelated runtime files. No Git mutation was attempted.

## 2. Implementation and acceptance proof

`consensus_engine/strategy_interface.py` adds the `M41_V1` common interface,
`RequiredData`, `StrategyState` and `StrategyContext`. It reuses canonical
snapshots, Quote decisions, catalyst/session records, transitions, candidates,
confidence, risk and targets. There is no provider payload in the interface,
live registration, order method, scheduler, settings/clock read, persistence or
delivery. Source identity, original availability, current quote evaluation,
missingness and fixed session/configuration attribution remain explicit.

The 55 written cases in `test_strategy_interface.py` cover shape completeness,
all eight existing ID labels, roles, state/substate separation, frozen context,
zero/missing/unknown values, future and duplicate inputs, reference identity,
stale/missing quotes, wrong versions/modes/units, invalidation, expiry and reset.
The concrete `FixtureStrategy` is a test script only. Neither its first/second
ready-input behavior nor its fixed score, geometry or expiry is a trading rule.
Testing all eight labels does not implement or validate eight playbooks.

The two end-to-end cases use canonical Bar round trips, the real historical
coverage/opening-range calculation, actual Quote event checks, immutable context,
the common strategy consumer, and canonical transition/candidate round trips.
Expected states at 06:34:59, 06:35:00 and 06:35:01 Pacific are WATCHING,
SETUP_FORMING and ALERT_TRIGGERED, with no candidate, HEADS_UP and ACTIONABLE.
The synthetic long has stop/target 99/102 around entry 100; the short has 101/98.
Missing/stale input clears current output. Invalidation and expiry clear output;
reset reproduces the earlier records exactly and clears the previous session.
Earlier alert bytes remain fixed through all later operations.

Required protected selectors:

- `tests/trade_alerts_contracts`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/trade_alerts_contracts/test_strategy_interface.py`

The directory includes all affected feature/Quote/config/record compatibility
cases and the reused opening-range test helper. Both children must pass all 55
M4.1 cases with zero failures/errors/skips, matching ordered test IDs, no unexpected
isolation denials and successful cleanup. Read both XML and isolation reports,
output logs and the launcher summary. Each child must save
`m41-strategy-interface-long-proof.json` and
`m41-strategy-interface-short-proof.json`. Corresponding files must be byte-identical
across runs and each be below 100,000 bytes. Section 7's inspected supervisor proof
meets these requirements, including all 55 cases and both produced records.

## 3. Historical local attempt and ownership notes — superseded by §7

This section describes the earlier failed local attempt, not current pending work.
Section 7 records successful supervisor execution and records-only finalization.
M4_1_LOCAL_CHECKS.json retains the original local snapshot in its explicitly
historical section. The ownership errors below belong to that earlier attempt;
this records-only repair preserves the files' observed ownership and modes and
does not infer host ownership from the sandbox's displayed values.

Both new Python files compile and parse with Python 3.10 grammar without importing
or running them. No repository lint/type-check command is configured. Local checks
and final content/protection hashes are saved in M4_1_LOCAL_CHECKS.json.
Compilation and static inspection do not replace protected tests.

The protected launcher must remain unchanged. Its actual attempt and any exact
limitation are saved in M4_1_LAUNCHER_LIMITATION.txt and M4_1_LOCAL_CHECKS.json.
The attempt stopped at the initial temporary-folder ownership step, before child
creation or test collection, with this exact final error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-6tlzls3e'`

No XML, isolation report or M4.1 recording was produced. Both protection files
match their starting hashes. No alternate unprotected test was run. Ownership
restoration for the five new files also returned `[Errno 22] Invalid argument`;
the exact per-file results are in the historical local checks. At that time, the
handoff required host ownership restoration and external execution of the same
selection. One invocation performs both required runs. It required readable proof
files and a tested-file manifest for a fresh builder to check identity and finalize
records without code or test changes. Section 7 now records that completed proof
and finalization; the M4.1 row is `[x]` for independent review.
No required live/data/definition gate remains for this interface milestone itself.

The read-only running-program check could not connect to the system manager:
`Failed to connect to bus: Operation not permitted (consider using --machine=<user>@.host --user to connect to bus of other user)`.
No active-status claim is made. The workspace shortcut resolves correctly and the
read-only recent model-drift/health-failure search returned zero matching lines.
No application run or restart was used as verification.

## 4. Remaining project gates

M0.2, the M2.3/M2.4/M3.1/M3.2/M3.6 source rows, M3.3–M3.5 definitions,
M0.3B adoption and all other playbook definitions remain required. The interface
does not certify any source or adopt an unresolved rule. Actual trading state
graphs, expiry policies, scores, structural producers, options, suppression,
storage, recovery, replay and delivery keep their later owners. Full AT-05/07
acceptance remains open. The two legacy listener isolation gaps stay with M18.4.

No purchase or live access is needed for M4.1. Separately supervised source work
retains the existing-source-first route and exact reopening proof in the prior
evidence records. D-091 remains $0 used and $0 reserved. All switches remain off
under the build contract. Engineering proof is not provider coverage or profit.

## 5. Exact next dependency-ready milestone

- [ ] **M4.2 — state transition engine**, proposed after independent M4.1 review.
  Protected proof and records-only finalization are complete in §7.

Build one serially owned common transition engine using M4.1 and the existing
`StrategyStateTransition` records. Preserve timestamp, symbol, strategy/version,
old/new state/substate, reason and feature/input references. Use explicitly supplied
transition rules in offline cases, rather than inventing a playbook graph. Reject
inconsistent state/time/identity without replacing prior facts. Persist complete
transition records through the existing database framework, with an injected
recording boundary and temporary-database proof. Any additive transition storage
must be reusable by M5.1, not a second database system. Full event-store layout,
atomic candidate/delivery transactions
and crash/restart recovery remain M5.1/M5.5 and must stay open.

This common mechanism can be tested without actual provider access or new trading
choices. M3.3–M3.5 and all source/definition gates remain tracked. The supervisor's
independent reviewer must validate this ordering before the controller advances.
Saved `next_milestone`: **M4.2**. Do not start M4.2 in this session.

## 6. Entire milestone changed paths

- `consensus_engine/strategy_interface.py`
- `tests/trade_alerts_contracts/test_strategy_interface.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M4_1_VERIFICATION.md`
- `trade_alerts_build_docs/M4_1_SUPERVISOR_TESTS.json`
- `trade_alerts_build_docs/M4_1_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M4_1_LAUNCHER_LIMITATION.txt`

No code, tests or protection from an earlier milestone is changed.

## 7. Supervisor proof finalized — 2026-09-06 Pacific

The supervisor supplied readable protected proof at **20:50:15 Pacific**. This
records-only session inspected the publication record, both XML reports, both
isolation reports, both test logs and all four M4.1 compact records. The verified
source hash is `cbe9b00eff98bd19e368ed693eacfcb33b734acc4db62a7cdf14a36f4964095b`.
Current source, test and protection hashes match the tested manifest. No code,
test or protection file changed during finalization.

Both runs passed **720 tests**, in 275.243 and 281.661 seconds. Each included all
**55 M4.1 cases**, with zero failures, errors or skips and matching ordered test
IDs. Both isolation reports show no unexpected denials and successful cleanup.
The long records are 16,032 bytes and byte-identical across runs with SHA-256
`23be25927e7f876715901a37b83504df58555e95db17d86b3bb34eccf48a8db6`.
The short records are 16,044 bytes and byte-identical across runs with SHA-256
`4a3736d671827e4a447483a95f485546b3fbb20ca3d13e81f1827a3b41381593`.
No Databento credit was used.

- [x] **M4.1 — shared strategy interface:** implementation, 55 protected cases
  and both end-to-end records have fresh supervisor proof.
- [ ] **M4.2 — state transition engine:** proposed independent next milestone
  after review, within §5.

Status: **completed**. Saved `next_milestone`: **M4.2**. This proves the shared
interface only. It does not prove provider coverage, a playbook, live operation,
execution results or profitability.


## 8. Status-record repair — 2026-09-06 21:07 Pacific

The review found stale pending-test text in ROADMAP §9, PROJECT_INDEX §34,
TESTING_AND_VALIDATION §63 and DECISIONS §§13/41. Those entries now agree with
§7 and ROADMAP §31. M4_1_LOCAL_CHECKS.json leads with **completed** and references
M4_1_SUPERVISOR_TESTS.json. Its full original local snapshot, including the failed
launcher attempt and ownership errors, is preserved unchanged under
`historical_local_attempt`. Section 3 labels those notes as historical.

This repair rechecked all **35 published proof files** against their saved hashes,
both XML reports and logs, both isolation reports, and all four M4.1 recordings.
The results remain **720 passing tests per run**, including **55 M4.1 cases**,
matching ordered IDs, clean isolation/cleanup and matching long/short records.
All **801 tested manifest files** were compared before editing. Only the already
finalized verification document and roadmap differed; source, tests and protection
matched. M4_1_LOCAL_CHECKS.json saves the publication and manifest fingerprints.
No test or application was rerun in this records-only repair.

Recoverable copies and the before/after checks are saved at
`/tmp/m41-status-repair-lznb5qna/`. Only six status/evidence documents changed in this
repair. The entire milestone still has the **11 changed paths** in §6, including
its earlier code and tests. All other captured file contents and observed ownership
and modes are preserved. The 72 local Markdown links, cited file paths, code fences,
whitespace and added-text checks passed. All nine canonical documents, eight
playbooks, 31 functional rows and 22 additional capability rows remain present.
D-090, D-091, M0.3B proposals and every required blocked roadmap row are unchanged.

- [x] **M4.1 — shared strategy interface:** implementation, protected proof and
  corrected records are complete for independent acceptance review.
- [ ] **M4.2 — state transition engine:** saved proposed next milestone, within §5,
  after the separate reviewer accepts M4.1. No M4.2 work started here.

Status: **completed**. Saved `next_milestone`: **M4.2**. All switches remain off;
no purchase, live access, new trading rule or profitability claim is added.
