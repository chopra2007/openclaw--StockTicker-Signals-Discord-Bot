# M3.6 supplied-Bar opening range — request-window repair proved

Date: 2026-09-06 Pacific. Status: offline implementation and protected proof are
complete. The required source gate is blocked in §4. Proposed independent next
milestone after review: **M4.1**, scoped in §5. The final repaired proof is in §12.

## 1. Assigned scope and implementation

The assignment was checked against ROADMAP §31 and M3_2_VERIFICATION §6. All nine
canonical documents, PREBUILD_REVIEW, D-090's approved packet, relevant M2.2/M3.1/
M3.2 evidence, PROJECT_RULES and WORKFLOWS were read. Finished work was preserved.
M0.3B remains proposed. M3.3–M3.5 remain unfinished behind their exact definition
gates.

`consensus_engine/opening_range_features.py` implements only the approved first
five-minute range from supplied canonical Bars. It returns the existing immutable
FeatureSnapshot with:

- `OPENING_RANGE_HIGH_5M_V1`
- `OPENING_RANGE_LOW_5M_V1`
- `OPENING_RANGE_MID_5M_V1`
- `OPENING_RANGE_WIDTH_5M_V1`
- `OPENING_RANGE_COMPLETE_5M_V1`

The calculation selects exactly the five scheduled one-minute intervals starting
at the regular-session open. A complete range requires all five intervals to be
final and available and at least one traded. Certified no-trade intervals add no
invented high or low. Missing, provisional, invalid, conflicting, mixed-mode or
malformed overlapping records keep all four prices unavailable and complete false.
Later revisions affect newly built snapshots only. Wider requests cannot leak
later minutes into the opening range.

Known compatible symbol, EQUITY/ETF type, source, mode, `USD_PER_SHARE`, `SHARES`,
adjustment, session and venue basis are required. The module performs no fetch,
clock read, storage, config change, switch activation or live work. It makes no
source-coverage or profit claim.

## 2. Protected cases and required proof

`tests/trade_alerts_contracts/test_opening_range_features.py` covers hand-computed
range values, 06:34:59/06:35 boundaries, late final availability, missing/
provisional/invalid/conflicting revisions, duplicates and ordering, certified
no-trade and all-no-trade input, wrong interval/units/source/mode/identity, malformed
overlap, holidays, clock changes, a shortened session, broad requests and frozen
earlier snapshots.

The end-to-end case round-trips Bar records, uses actual M2.2 coverage, builds and
round-trips the M3.6 FeatureSnapshot and writes the compact
`m36-opening-range-features-proof.json` record. Run twice with the unchanged
protected launcher and these selectors:

- `tests/trade_alerts_contracts`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/trade_alerts_contracts/test_opening_range_features.py`

Both runs must have zero failures, errors and skips, matching ordered test IDs,
all M3.6 cases, no unexpected isolation denials and successful cleanup. The two
compact M3.6 records must be byte-identical and below 100,000 bytes. Read the XML,
isolation, output and recording files; an empty artifact folder is not proof.

## 3. Historical local checks and exact launcher limit

This section and §§7–11 preserve earlier attempts, not the current test status.
Section 12 finalized successful protected proof; §4's source gate stays blocked.

Both new Python files compile and parse with Python 3.10 grammar. The protected
launcher and child hashes match the saved starting hashes. No application, live
provider, credential, broker/Discord, database, charged request, deployment,
restart or Git mutation was used. All switches remain off.

The unchanged launcher exited before creating a child or collecting tests. The
exact traceback is saved in M3_6_LAUNCHER_LIMITATION.txt. Its final line is:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-vz7ki7zt'`

This occurred at the initial ownership step. No test result or M3.6 recording was
produced. Source compilation is not passing evidence. Under the controller's
rule, the milestone is **ready_for_verification**. The supervisor must run the
selection twice and return readable artifacts to a fresh builder. That builder
must verify file identity and finalize records without changing code or tests.

The sandbox also rejected ownership restoration for each of the five new files
with `Invalid argument`. Their readable modes are correct, but the supervisor must
restore host ownership before running proof. Existing edited documents kept their
starting ownership and modes.

## 4. Required source blocker and reopening proof

- [!] **M3.6 source completion.** Actual compatible first-five-minute data remains
  blocked by data and separately supervised access under M0.2/M2.2. Required proof
  is dated raw and normalized per-symbol opening minutes with original event,
  receipt and availability times; finality/publication rules; missing versus
  certified no-trade meaning; revision/correction/cancel treatment; source/venue
  basis; share and price units; compatible adjustments; and complete scheduled
  coverage on normal, clock-change and shortened sessions.

Reopen only in a separately authorized supervised step. Inspect existing local,
Schwab and free records first. Save per-interval coverage and run actual records
through the same feature path. Missing data keeps the dependent result unavailable.
Any paid source must first name fields, dates, fidelity and verified bounded cost
under D-091. No purchase is needed here; $0 used and $0 reserved remain unchanged.
Synthetic cases establish neither source coverage nor profitability.

## 5. Exact independent next milestone

- [ ] **M4.1 — shared strategy interface**, proposed after M3.6 protected proof
  and independent review.

M4.1 can define the common required-data, update/state, heads-up/actionable,
invalidate/expire/reset, confidence and stop/target interface against existing
canonical records without adopting a strategy's unresolved trading choices.
M3.3–M3.5 remain required and blocked by PLAYBOOKS §13/M0.3. M0.3B remains
proposed. The reviewer must independently validate this ordering and scope before
the controller advances.

Saved `next_milestone`: **M4.1**. Section 12 completed protected proof. The
controller remains on M3.6 until independent review passes. The offline row is
`[x]`, §4's required gate stays `[!]`, and the handoff is blocked with M4.1 as the
independent next milestone. Do not hide the source gate or call synthetic output
full coverage.

## 6. Entire milestone changed paths

- `consensus_engine/opening_range_features.py`
- `tests/trade_alerts_contracts/test_opening_range_features.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/M3_6_VERIFICATION.md`
- `trade_alerts_build_docs/M3_6_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M3_6_LAUNCHER_LIMITATION.txt`

## 7. Historical repair-session verification retry — 2026-09-06 Pacific

The controller returned no readable supervisor artifacts. The M3.6 production
and test file hashes still match §3's saved values, as do both protected files.
Python compilation and Python 3.10 grammar checks passed again.

The unchanged protected selection was retried at 18:38 Pacific. It again stopped
before child creation or test collection at the launcher's initial ownership
step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-voqb57lt'`

Starting the same protected launcher as the `openclaw` account was also attempted
without changing it. The sandbox stopped the account switch before the launcher
started: `setpriv: setresuid failed: Invalid argument`.

No passing result or compact recording is claimed. Implementation remains
**ready_for_verification**. The supervisor must restore host ownership and run
§2's saved selection twice. The required source gate in §4 and the proposed M4.1
handoff in §5 are unchanged.

## 8. Historical second repair handoff — 2026-09-06 18:54 Pacific

The supplied controller summary reports a failed verification at 18:49:57 Pacific
with no published artifacts or readable proof path. Its issue text is
`verification failed or protected evidence changed`. This is a reported status,
not an inspected test result. Without its output or artifacts, the cause of that
supervisor failure cannot be established.

The existing partial work was inspected before any edit. All six source, test,
dependency and protection hashes in M3_6_LOCAL_CHECKS.json still match. Both M3.6
Python files compile and parse with Python 3.10 grammar without executing them.
Static counting finds 18 test functions and 26 cases after parameter expansion;
these are written cases, not collected or passing tests. The existing input ->
coverage -> immutable feature -> compact recording case is preserved. No code,
test, configuration or protection change was made in this repair.

At 18:54:09 Pacific the unchanged launcher was attempted with all five selectors
in §2. It again stopped at its initial artifact-directory ownership step, before
either child or test collection:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-kf43l78w'`

M3_6_LAUNCHER_LIMITATION.txt preserves the full traceback. No XML, isolation report
or compact recording was produced. The earlier account-switch attempt is already
recorded in §7 and was not repeated. The launcher has no option to skip this step;
neither protection file was changed or bypassed.

The remaining offline step is successful protected execution by the supervisor
where the ownership/account handoff is supported. One launcher invocation creates
the required two child runs. Return both runs' XML, isolation, output and compact
recording files, the launcher summary and the tested-file manifest in a readable
proof copy. A fresh builder must verify those files and source identity, then
finalize evidence and roadmap without changing code or tests. Do not infer a
passing run from the controller's status summary or the local grammar checks.

- [~] **M3.6 offline opening range:** implementation preserved; protected proof
  remains the only unfinished offline verification step.
- [!] **M3.6 source completion:** §4's required actual-data gate remains blocked.
- [ ] **M4.1 — shared strategy interface:** proposed independent next milestone
  under §5, after protected proof and independent review.

Status: **ready_for_verification**. Saved `next_milestone`: **M4.1**. After fresh
offline proof, retain its `[x]` row and the separate required source `[!]` row,
then return **blocked** with M4.1. All ten milestone paths in §6 remain the whole
change list, including earlier attempts. Earlier verification records and all
other owner work are preserved. All switches remain off; no live or paid access,
application run, Git mutation or new trading rule was introduced.

## 9. Historical third repair handoff — 2026-09-06 19:11 Pacific

The supplied controller status again contains no readable proof path or test
artifacts. It reports exit 1 and `verification failed or protected evidence
changed`. Inspection found one test-only speed change made after §8: the broad
request helper now selects the five opening intervals before it creates Bars,
instead of creating a full regular session and then keeping five. The same real
HistoryRequest and five Bar values reach every assertion. All 18 test functions,
parameter lists and assertion expressions are unchanged, and static counting
still finds 26 cases. Production and both protection files are unchanged.

The current test SHA-256 is
`75a3aec87ed4eb3d6ba4256f79bc9715f8e2b55de7a44494ed1dc1ec967a6812`.
Both Python files compile and parse with Python 3.10 grammar. These checks are not
passing test evidence.

At 19:11 Pacific the unchanged launcher was run with all five selectors in §2.
It stopped before either child or test collection at the same initial ownership
step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-im7o5oft'`

No XML, isolation report or compact recording was produced. The speed change must
be included in the supervisor's tested-file manifest. Fresh two-run protected
proof is still the only unfinished offline step. The source blocker in §4 and
proposed M4.1 handoff in §5 are unchanged. Status remains
**ready_for_verification**.

## 10. Historical supervisor proof and records-only finalization

The supervisor supplied protected results at **19:23:52 Pacific**. This
records-only session inspected the publication record, both XML reports, both
isolation reports, both output logs and both M3.6 recordings. The tested source,
test and protection hashes match §9 and M3_6_LOCAL_CHECKS.json. No code, test or
protection file changed during finalization.

Both runs passed **663 tests** in 274.58 and 270.17 seconds. Each run included all
**26 M3.6 cases**, with zero failures, errors or skips and identical ordered test
IDs. All selectors in §2 ran. Both isolation reports show no unexpected denials
and successful database, HTTP, configuration and lock cleanup. The two
7,237-byte `m36-opening-range-features-proof.json` files are byte-identical with
SHA-256 `06d3d939ffa672da4869dc9ecf94c3d469640deb2cd926d8f105f1a704336906`.
No Databento credit was used.

This proof completed the then-current 26 cases. It predates the request-window
repair in §11 and could not verify that repair. Section 12 supplies its final proof.
Section 4's required source row remains `[!]`; synthetic software proof does not establish
actual coverage, live access, execution feasibility or profitability.

## 11. Request-window review repair — historical pre-proof state

The independent review found that the calculation replaced the supplied
HistoryBatch request with a new five-minute request before reading coverage.
HistoryBatch archives may contain records outside their original request, so a
truncated or disjoint request could wrongly produce a complete opening range.

The calculation now verifies that the original request includes every one of the
five scheduled opening intervals before it reads archived Bars. A request ending
after four minutes and a disjoint five-minute request both remain incomplete with
`OPENING_RANGE_NOT_REQUESTED`, even when their archives contain all five opening
Bars. A broad request that includes the opening continues to use only those five
slots. The compact end-to-end record includes both rejected-request paths.

The test file now contains 19 test functions and 28 cases after parameter
expansion. Both changed Python files compile and parse with Python 3.10 grammar.
These local checks are not passing test evidence. Section 10's 663-test proof and
7,237-byte records are historical because they predate this code and test change.

At 19:37 Pacific the unchanged launcher was run with all five selectors. It
stopped before child creation or test collection at its initial ownership step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-kdywcp4y'`

No XML, isolation report or compact record was produced. The full traceback is
saved in M3_6_LAUNCHER_LIMITATION.txt. Neither protection file was changed.

Run §2's same five selectors twice through the unchanged protected launcher.
Require all 28 M3.6 cases, matching ordered test IDs, zero failures/errors/skips,
clean isolation and cleanup, and byte-identical compact records. Until those
artifacts are returned and inspected, the offline row remains `[~]` and status is
**ready_for_verification**. Section 4's required source gate remains `[!]`.
Proposed `next_milestone` remains **M4.1** after proof and independent review.

## 12. Request-window repair proof finalized — 2026-09-06 Pacific

The supervisor supplied readable protected proof at **19:48:40 Pacific**. This
records-only session inspected the publication record, both XML reports, both
isolation reports, both output logs and both compact M3.6 records. The verified
source hash is `2d9961746cd076cdb7ab1d868364997a1d7ad866257d40540eb66c5c1fbb4b52`.
No code, test or protection file changed during finalization.

Both runs passed **665 tests**, in 266.63 and 270.14 seconds. Each included all
**28 M3.6 cases**, with zero failures, errors or skips and identical ordered test
IDs. Both isolation reports show no unexpected denials and successful cleanup.
The two 9,379-byte compact records are byte-identical with SHA-256
`e51116fd2f4430d33e53014d4c02bde9ee36a11e90e922d2749ec2eb208912a3`.
They include both rejected request-window paths. No Databento credit was used.

- [x] **M3.6 offline opening range:** implementation, 28 protected cases and the
  compact end-to-end record have fresh supervisor proof.
- [!] **M3.6 source completion:** actual opening-minute coverage and source
  behavior remain blocked under §4. Synthetic proof cannot close this row.
- [ ] **M4.1 — shared strategy interface:** proposed independent next milestone
  after review, within §5 and without adopting unresolved trading choices.

Status: **blocked** by the separate actual-data source gate. Saved
`next_milestone`: **M4.1**. Engineering completion is not proof of source coverage,
execution results or profitability.

## 13. Status record repair — 2026-09-06 Pacific

The four reported status conflicts were corrected without changing code, tests or
protection. ROADMAP §29 now separates completed offline opening range from the
blocked source row, matching §31. DATA_REQUIREMENTS §41 records completed offline
proof. TESTING_AND_VALIDATION §62 labels earlier pending states as historical.
M3_6_LOCAL_CHECKS.json places failed local attempts and their ownership notes
under historical evidence, with the finalized protected result at the top.
PROJECT_INDEX §33 and this record also distinguish current proof from old attempts.

The readable supervisor files were inspected again. Both protected runs passed
665 tests, including all 28 M3.6 cases, with matching ordered IDs, clean isolation
and cleanup, and identical 9,379-byte compact records. Current source, test and
protection hashes still match the saved proof. No tests or application code were
run again for these records-only changes. The recoverable before-edit copies,
proof-file hashes and document/preservation checks are recorded in
M3_6_LOCAL_CHECKS.json under `status_record_repair`.

- [x] **M3.6 offline opening range:** implementation and protected proof complete.
- [!] **M3.6 source completion:** §4's actual opening-minute evidence remains required.
- [ ] **M4.1 — shared strategy interface:** independent next work after review, within §5.

Status: **blocked** by the required source gate. Saved `next_milestone`: **M4.1**.
No new switch, trading rule, live access, purchase or profitability claim is added.
