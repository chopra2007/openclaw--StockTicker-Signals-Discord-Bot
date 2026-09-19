# M3.2 supplied-Bar participation — offline proof complete

Date: 2026-09-06 Pacific. Status: the supplied-Bar offline slice has fresh
protected proof. The separate required definition/source gate is blocked in §5. Proposed independent next
milestone after offline proof and review: **M3.6**, scoped in §6.

## 1. Assigned scope and completed implementation

The assignment was checked against ROADMAP §31 and M3_1_VERIFICATION §5. All
nine canonical documents, PREBUILD_REVIEW, D-090's approved packet, relevant
M3.1/M2.2 source/evidence contracts, PROJECT_RULES and WORKFLOWS were read.
M3.1's existing code, 54-case proof and required source gate were preserved.
M0.3B is still proposed. No finished milestone was rebuilt.

`consensus_engine/participation_features.py` implements only:

- `RVOL_OPEN5_MEAN20_V1`: current opening-five-minute shares / arithmetic mean
  of the same five minutes from exactly the 20 prior exchange sessions.
- `PM_RVOL_MEAN20_V1`: current 01:00 Pacific-to-open shares / arithmetic mean
  of the same complete windows from those 20 sessions.
- `DOLLAR_VOLUME_CLOSE_PROXY20_V1`: median of regular close times regular share
  volume over exactly the 20 prior sessions; average sorted entries 10 and 11.

The pure function returns the existing immutable FeatureSnapshot. It uses a
caller-supplied instrument scope, shared calendar and M2.2 available-time coverage.
No new fetch, database, clock read, switch, runtime consumer or threshold is added.
Existing relative-volume helpers use different windows or missingness; their
callers and arithmetic are unchanged. Source conventions remain on input history;
selected input IDs and missing reasons stay on each feature. Daily dollar volume
is explicitly a close-based estimate, never exact traded-dollar volume.

All required windows are chosen before observations. Missing scheduled references
cannot be replaced by older sessions. Required invalid/provisional/conflicting
records, unavailable finals, wrong units/modes/instruments and incompatible source
conventions cannot pass. Certified zero current share volume may give zero RVOL;
zero reference volume is unavailable. Current daily totals, later regular minutes,
and unrelated malformed or different-mode records cannot enter the fixed windows.
Newly available revisions affect newly built snapshots only; saved snapshots are
immutable. Callers retain the original ready snapshot and input references.

## 2. Required protected proof

Run twice using the unchanged `scripts/testing/run_trade_alerts_contracts.py`:

- `tests/trade_alerts_contracts`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/trade_alerts_contracts/test_participation_features.py`

The directory includes earlier foundation/compatibility tests and M3.1's 54 cases.
The new file contains **46 written cases**, counted statically from its parameter
lists. The real collected count must be checked in the fresh XML reports. Both
runs must have zero failures/errors/skips, matching ordered test IDs, every M3.2
case, no unexpected isolation denials and successful cleanup. Require identical
`m32-participation-features-proof.json` files, each under 100,000 bytes. Inspect
both files; do not infer a pass from an empty folder or source compilation.

The end-to-end case exercises Bar serialization -> actual M2.2 coverage -> actual
M3.2 calculation -> canonical immutable snapshot serialization -> compact recording.
The 12 written snapshots cover opening/premarket readiness, the hand-computed
2.0/2.75/$50,000,000 values, missing/invalid references, late finality, valid zero
numerator, zero denominator, clock changes and a shortened prior daily session.
Coverage counts show that missing unneeded later minutes cannot erase complete
opening-five-minute windows. Each full output is hashed without publishing large
repeated histories. These are synthetic assertions until execution is inspected.

## 3. Initial local checks and execution status — historical

`M3_2_LOCAL_CHECKS.json` saves the starting backup reference, input preservation,
source/test/protection hashes, grammar/document checks and actual launcher result.
A recoverable starting copy covers 221 relevant source/test/config/document files;
all existing owner changes remain intact. The existing failing-test list is empty
and unchanged. M3.1's 591-test evidence predates this implementation and is not
M3.2 evidence. No tests are run outside the protected launcher.

Both new Python files passed compilation without execution and Python 3.10 grammar
parsing. No configured ruff/mypy tool was found. These source checks do not prove
runtime correctness. No application, broker/Discord call, live check, credential
read, charged request, deployment, restart or Git mutation occurred. New switches
remain off. Runtime memories and controller/protection files were not edited.

The unchanged launcher returned exit 1 before either child or test collection.
`M3_2_LAUNCHER_LIMITATION.txt` saves its exact traceback:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-5libtqff'`

This happened at the launcher's initial ownership step. No test result or recording
was produced, and no protection was changed or bypassed. Status is
**ready_for_verification** under the owner's sandbox-execution handoff: successful
protected execution is the remaining offline proof step. The supervisor must
supply two fresh protected runs to a fresh builder. That builder verifies source/test identity, reads both
XML/isolation/recording artifacts, and finalizes evidence/roadmap without code or
test changes. Keep the offline row unfinished until those checks pass. Then keep
its `[x]` row and §5's `[!]` row and return **blocked**, with **M3.6** as proposed
independent work. The supervisor's separate reviewer decides acceptance and
independence before any advancement.

Restoring the five newly created files to the existing host account also returned
`[Errno 22] Invalid argument` for each path. Exact per-file errors are in
M3_2_LOCAL_CHECKS.json. Existing files retain their starting ownership/mode and new
files remain readable. The supervisor must restore ownership outside this sandbox
as part of verification preparation; no account identity is copied into this public
record. This local check does not claim host ownership was restored.

## 4. Entire milestone changed paths

- `consensus_engine/participation_features.py`
- `tests/trade_alerts_contracts/test_participation_features.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/M3_2_VERIFICATION.md`
- `trade_alerts_build_docs/M3_2_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M3_2_LAUNCHER_LIMITATION.txt`

## 5. Required blocker and exact reopening proof

- [!] **M3.2 required definition/source completion.** Full M3.2 is not complete
  from the supplied-Bar slice. General same-time/cumulative RVOL beyond the
  two named fixed windows lacks an adopted numerator, reference window/population,
  warm-up and current partial-minute policy. M0.3/PLAYBOOKS §13 owns its exact
  versioned definition and hand-worked boundary cases. Do not adopt M0.3B or
  invent this formula to close the row.

D-090 already approves `INTENSITY_15S_MEAN20_V1` and projected-minute arithmetic.
Their formulas need no repeat approval, but the inputs remain unavailable here:
complete eligible executed-share coverage for the current and 20 reference
15-second intervals, source trade-condition/duplicate/cancel/correction rules;
or a verified minute-start volume baseline and complete same-basis intraminute
volume with known resets/corrections. M0.2/M2.3 own official source semantics and
measured input/recovery/capacity proof. Final one-minute Bars and polled last
prices cannot stand in for these observations. Retain these required branches
under M3.2 and their later strategy owners.

Actual opening-five-minute, full premarket and regular daily data also need dated
per-symbol current plus exact 20-prior-session evidence: original event/receipt/
availability times, finality and missing/no-trade distinctions, session boundaries,
revisions, source/venue scope, share/price units and compatible corporate-action
adjustments. Existing local metadata is not that coverage proof.

Reopen source work only in a separately authorized supervised step. Inspect
existing local/raw records and the existing Schwab/free route first. Save a
per-interval coverage report and frozen source evidence, then run the same feature
path with actual inputs and report its remaining missingness. Missing inputs keep
the dependent feature unavailable. If a paid source is necessary, name the fields,
dates, fidelity and verified bounded cost before a separately authorized request
under the cumulative D-091 ledger. Cost is unverified here. No purchase is needed
for the offline slice; **$0 used and $0 reserved** remain unchanged. No synthetic
example establishes source coverage, execution feasibility or profitability.

## 6. Exact independent next milestone

- [ ] **M3.6 — supplied-record five-minute opening range**, proposed after M3.2
  offline protected proof and independent review.

This stays within Phase 3. M3.3's benchmark/sector selection and RS warm-up,
M3.4's slope/cross convention and M3.5's unresolved swing/compression/structure
choices remain under PLAYBOOKS §13/M0.3; M0.3B is still proposed. None is silently
implemented, approved or removed by this handoff. M3.6 has a unique already
approved D-090 §2 definition and needs none of those values or §5's tape/projection
inputs. The reviewer must independently validate this ordering and independence.

Reuse M1.1 clock, M1.3 records and M2.2 supplied 1m history. Implement only the
five scheduled intervals starting at regular open, their high/low/mid/width and
complete/usable status. Before the fifth interval ends, or while any required
interval is missing, provisional, invalid or unavailable, no completed range may
be exposed. Certified no-trade intervals add no invented high/low; at least one
traded interval is required. Enforce known compatible symbol/type/source/mode/
price/volume/adjustment/session coverage, select only available revisions and keep
frozen output immutable. Leave source proof and strategy triggers separate.

Require hand-worked high/low/mid/width, all-no-trade, partial/missing/revised-invalid,
wrong units/identity/intervals, duplicate/order, holiday, clock-change, shortened
session and 06:34:59/06:35/late-final cases. Save Bar -> coverage -> feature ->
identical compact recording proof through the unchanged protected launcher,
including affected compatibility selectors. Add no live consumer or switch.
Preserve M0.2/M0.3 and every full-data/later capability row.

Saved `next_milestone`: **M3.6**. No M3.6 implementation starts here. Full M3.2
remains blocked after its bounded offline proof; do not return M3.2 as its own
next milestone or hide required unfinished work as completed.

## 7. Timeout repair — 2026-09-06 Pacific

The failed supervisor verification log was readable. Its first child reported
`637 passed in 296.18s (0:04:56)` and no unexpected isolation denials. The second
child raised `subprocess.TimeoutExpired` under the unchanged 300-second limit.
This is incomplete historical evidence, not a successful two-run proof. The
controller supplied no published proof copy. Access to the named temporary
run directories returned `PermissionError: [Errno 13] Permission denied`.
No individual failing assertion was reported in the readable log.

Repair plan: preserve the production calculation and all 46 cases. Reuse the
real calendar result for an identical immutable test request, instead of asking
the calendar to rebuild the same 20-session schedule for each snapshot. Cache
only the request's scheduled intervals, never Bars, coverage, feature values or
assertion results. Every distinct request still runs the existing calendar code.
The end-to-end case will use ordinary uncached HistoryRequest objects, including
its raw Bar round trips and all 12 output snapshots. Preserve both protection
files, every test selector and the launcher's time limit. Fresh protected proof
must establish whether this repair resolves the timeout; no speedup is assumed.

A recoverable copy was saved before repair. M3_2_LOCAL_CHECKS.json records
the repair's exact hashes, source preservation and launcher result. Required
definition/source work in §5 and proposed next_milestone M3.6 in §6 stay open.

Implemented: a test-only HistoryRequest subclass caches at most 64 immutable
calendar results by the complete request value. Changed dates, boundaries,
intervals, symbol or session scope have separate entries. Coverage and features
still run for every evaluation and input revision. The end-to-end test converts
every history, including its clock-change cases, to an ordinary HistoryRequest
and round-trips every supplied Bar. No production or protection file changed in
this repair. A source-structure comparison confirms every original test name,
parameter list and assertion expression is preserved. Both Python files compile
and parse with Python 3.10 grammar, without executing application code.
The 214 unrelated readable files in the original snapshot still match; database
files were excluded from reads. All nine canonical files, 31 requirement rows,
72 local document links and the retained source/definition gates were checked.
File ownership and modes match the repair's starting copy. The original
host-ownership restoration gap in §3 remains for supervised preparation.

The local protected attempt returned exit 1 before collection at the initial
ownership step:
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-qpjvlp31'`.
Its exact traceback is appended to M3_2_LAUNCHER_LIMITATION.txt. No repaired test
result or timing measurement exists. The supervisor must run the full unchanged
selection twice within the existing limit and return published artifacts. Check
all 46 M3.2 cases, every compatibility selector, ordered IDs, isolation/cleanup
and both compact recordings before finalizing records. If it times out again,
retain the failure and repair repeated work; do not raise or bypass the limit.

Current status: **ready_for_verification** for the offline repair. After successful
fresh proof, the records-only session must apply §5's required blocked-gate
handoff with **next_milestone M3.6**. No speedup, complete M3.2 result, source
coverage or trading return is claimed here.

## 8. Fresh supervisor proof and records-only finalization

The supervisor supplied protected results at **18:03:46 Pacific**. This
records-only session inspected the publication record, both XML reports, both
isolation reports, both output logs and both M3.2 recordings. The tested source,
test and protection hashes match `M3_2_LOCAL_CHECKS.json`. No code, test or
protection file changed during finalization.

Both runs passed **637 tests** in 262.14 and 271.11 seconds. Each run included all
**46 M3.2 cases**, with zero failures, errors or skips and identical ordered test
IDs. All selectors in §2 ran. Both isolation reports show no unexpected denials
and successful database, HTTP, configuration and lock cleanup. The two
10,041-byte `m32-participation-features-proof.json` files are byte-identical with
SHA-256 `23d7748ed5c043602236784d1f3052ed748d3f7c8143fe7ae898c649b701b02e`.
No Databento credit was used.

The bounded supplied-Bar row is now `[x]` for independent review. Section 5's
required definition/source row remains `[!]`; synthetic software proof does not
establish actual coverage, live access, execution feasibility or profitability.
The milestone therefore returns **blocked**, with proposed independent
`next_milestone` **M3.6** under §6.
