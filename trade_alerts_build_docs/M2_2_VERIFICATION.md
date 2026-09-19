# M2.2 historical-bar interface: repair and offline evidence

Date: 2026-09-06 Pacific. Status: **completed** for the repaired bounded offline
M2.2 contract, ready for the supervisor's independent acceptance review. Section 11
records fresh supervisor proof: **424 tests passed in each of two protected runs**,
including all 75 historical-interface cases and both required peer-history cases.
This builder finalized records only; code, tests and protection are unchanged.
Sections 4 and 7–10 preserve earlier attempts and results. Their pending instructions
are historical, not the current handoff. This record does not replace ROADMAP §31
or approve live use. M2.3 remains proposed until M2.2 is independently accepted.

## 1. Assigned scope and starting state

The assigned milestone agrees with ROADMAP §31 and M2_1_VERIFICATION §6. All nine
canonical files, PREBUILD_REVIEW, prior foundation/normalization evidence,
PROJECT_RULES and WORKFLOWS were read. Existing code and dependents were inspected.
No earlier M2.2 source or evidence file existed. The controller's earlier failed
workspace-access attempt produced no inspected partial code to replace. During the initial attempt,
workspace reads and writes worked; ownership changes failed as recorded below.

The pre-edit snapshot is `/tmp/trade-alerts-m22-start-cu_lvtkc/`. It contains
201 source/test/document/configuration files with byte hashes and recoverable
copies. The stored failing-test list was empty and remains unchanged. All prior
M1/M2.1 code, settings, tests, approved/proposed packets and unrelated owner files
are preserved. Read-only Git used GIT_OPTIONAL_LOCKS=0. The initial status command
reported permission errors for unrelated saved workflow files; those files were
not opened, altered or used as build state. No Git mutation was performed.

The drift check found no unresolved product choice blocking this offline slice.
M0.3B remains proposed; D-090 rules are unchanged. Current provider access,
coverage and conventions remain M0.2 evidence gaps. Existing historical evidence
records have dated handoffs; current ROADMAP §31 was used instead of redoing them.

## 2. Implemented scope and acceptance claims

CODING_STANDARDS §59 defines the exact interface. The implementation adds:

1. A raw-response path extracted from the existing history request function.
   Authentication, parameter construction, legacy table output and the existing
   history wrapper's fallback behavior remain shared. The raw path propagates
   errors, with no silent fallback or runtime activation.
2. Explicit daily/minute/premarket/regular requests and expected scheduled
   intervals from the existing exchange clock. Closed hours are excluded, daily
   means a full regular session, early closes are respected, and premarket has no
   default. Requested coverage is separate from returned bars.
3. Raw response-to-Bar mapping using M2.1, one original context per candle and
   explicit timestamp/session/finality/publication/adjustment/price/volume/venue
   conventions. Unknown conventions cannot become complete coverage.
4. Available-time coverage, with immutable revisions, exact duplicate accounting,
   earliest availability on re-fetch, conflicting-revision rejection, visible
   gaps and provisional/invalid states. Disjoint outside-scope bars are retained
   without invalidating the requested set. Malformed overlapping bars remain
   unexpected and block coverage. No missing interval is turned into zero volume.

The batch archive retains every supplied record. Only coverage_at supplies an
evaluation-time view. Future records cannot change earlier views, including the
fact that a late final will eventually arrive. MISSING is unknown/unobserved at
that instant, not confirmed feed loss. Already observed unfinished bars remain
PROVISIONAL. Certified no-trade bars have null prices and zero volume. Complete
coverage alone does not compute an opening range or prove at least one trade;
M3.6 retains that feature work.

Two bounded read-only helpers examined reuse and source/test correctness. Static
review led to the outside-scope, repeat-fetch and explicit finality/publication
cases. This is implementation assistance, not the supervisor's final review.

## 3. Protected acceptance selection

The repaired selection for the unchanged `scripts/testing/run_trade_alerts_contracts.py`
is below. The supervisor's earlier runs in §9 used only the first five selectors.
All seven are required for this repair and included in the final result:

- `tests/trade_alerts_contracts`
- `tests/test_schwab_client.py`
- `tests/test_fetch_history_extended_hours.py`
- `tests/test_models.py`
- `tests/test_skew_index.py`
- `tests/test_all_command_levers.py::test_pct_change_short_history_returns_none`
- `tests/test_all_command_levers.py::test_pct_change_happy`

The new tests cover exact request arguments, raw normalization, late availability,
revisions, gaps, duplicate/conflicting/out-of-order rows, invalid quality, no-trade
certification, source/adjustment/mode compatibility, daily/early-close and
premarket coverage, holiday/weekend/seasonal boundaries and legacy consumers.

Required end-to-end case:
`test_request_raw_mapping_coverage_and_archive_end_to_end` calls the real raw
history path with fake transport, then the real M2.1 mapping, canonical records,
calendar coverage and archive round trip. Five synthetic opening-minute volumes
are 10/11/12/13/14, totaling 60. The last final arrives at 06:35:02. Expected views
are four final plus NOT_ENDED at 06:34:59; four final plus MISSING at 06:35; five
final at 06:35:02. Both fresh supervisor outputs show those results in §11 for
the repaired source under the unchanged protection.

Each fresh protected child wrote `m22-history-proof.json` into its artifact folder.
Both outputs are byte-identical. Both `results.xml` and `isolation.json` records
were read: zero failures/errors/skipped contracts, no unexpected access denials,
and all cleanup checks true. Section 11 records actual execution, not syntax proof.

Search found two broader legacy files whose top-level imports need scripts not
mounted by this launcher: `tests/test_r20_market_breadth.py` imports
`scripts.market_daily`; `tests/integration/test_batch2_quote_collection.py` imports
`scripts.check_batch2_trade_gate`. They are not supported selectors in this lane.
Their wrapper mocks do not test the changed request construction. The affected
direct daily-table consumer instead has a new focused protected fake-transport
case, `test_existing_share_reader_consumes_legacy_daily_table_with_fake_transport`.
The unchanged fallback wrapper is covered by existing protected adapter cases and
`tests/test_fetch_history_extended_hours.py`. No protection change is required for
this bounded proof. The full application/release suite remains unclaimed.

## 4. Initial checks and exact limitation — historical

Before edits, the launcher was attempted with the protected contracts and the two
history compatibility files. It stopped at `os.chown` before either child started:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-2bp0335g'`

[M2_2_LAUNCHER_LIMITATION.txt](./M2_2_LAUNCHER_LIMITATION.txt) preserves the exact
traceback and ownership attempts. No protected tests or end-to-end proof ran in
this attempt. There are no new passing XML/isolation artifacts to cite. The
supervisor subsequently ran the launcher externally; §9 supersedes this pending step.
Neither launcher nor child protection was modified or bypassed.

Source compilation and Python 3.10 grammar were checked without importing or
running the application. There is no configured repository lint/type-check task.
[M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json) retains the original source
hashes, static checks, preservation and missing execution evidence under
`historical_local_attempts`. Those checks are not test passes. The current
supervisor execution evidence is recorded separately in the same file.

Existing-file ownership/modes are preserved. Setting ownership on new files fails
with `OSError(22, 'Invalid argument')` in the initial attempt. The later supervisor
handoff reports ownership restored; see §9 for this session's observation limit. No credentials, provider calls, live database, messages,
orders, application run, restart, deployment, paid data, background workflow or
Git mutation occurred. D-091 remains $0 used and $0 reserved. All new switches
remain off. Engineering work supplies no profitability evidence.

## 5. Milestone change list

This is the whole M2.2 delta from its starting snapshot, not earlier foundation work:

- `consensus_engine/scanners/schwab_client.py`
- `consensus_engine/historical_bars.py`
- `tests/trade_alerts_contracts/test_historical_bars.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/SESSION_PROTOCOL.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M2_2_VERIFICATION.md`
- `trade_alerts_build_docs/M2_2_LAUNCHER_LIMITATION.txt`
- `trade_alerts_build_docs/M2_2_LOCAL_CHECKS.json`

## 6. Saved handoff

**next_milestone: M2.3.** Repaired M2.2 implementation, fresh protected proof and
records-only finalization are complete; see §11. Both runs of the seven selectors
in §3 passed 424 tests. The supervisor must independently accept M2.2 and validate
the proposed next scope before the controller starts M2.3. This record does not
claim that acceptance or start the next milestone.

- [ ] **M2.3:** proposed offline normalized L1 event/continuity prerequisite, after
  M2.2 independent acceptance; full live-provider requirements remain open.

M2.3's dependency-ready scope is the offline normalized L1 event interface:
consume the existing canonical `Quote` records, with known M2.1 REST-shaped
fixtures where mapping is needed. Reuse source/quote/trade/availability times and
the shared clock. Exercise exact duplicate delivery, out-of-order events, stale
cached sides versus last trade, delay/missingness, disconnect, lost continuity
and reconnect with a fixed clock and recording output. Repeated observations
must not refresh source time or inflate downstream event counts. A connection
alone does not prove restored data continuity.

Age/coverage policy must be an explicit supplied input, with no new live default
or guessed numeric rule. Missing policy or continuity evidence cannot produce
a valid live-ready result. Synthetic policy values prove software behavior only.
Do not invent Schwab streaming fields, partial-update meaning, subscription
limits, cadence, retry budgets or authentication behavior. The existing mappings
are REST mappings, not evidence of streaming response semantics.

Acceptance for that next offline slice requires the real normalized event path
through state/quality decisions into a deterministic recording output, including
failure/reconnect cases, in two protected runs. Keep all switches off. No new
transport, dependency, application startup, live call or launcher change is needed
for this prerequisite. Full M2.3 streaming integration and provider verification
remain unfinished after this slice; retain their explicit M0.2/M2.3 gate and
reopening proof in ROADMAP §31 rather than calling the whole live feed complete.

M0.2 remains open for dated provider interval/publication/finality, adjustment,
history depth, per-symbol/session/premarket coverage, corporate actions and
original availability evidence. Streaming also needs official field/partial-update
meaning, access/subscription evidence, measured cadence, disconnect/recovery
continuity and shared capacity. Those require separately authorized supervised
source checks. Existing/local/free evidence comes first; any purchase needs its
exact fields/dates/fidelity and verified cost under the cumulative D-091 ledger.
No data purchase or live request occurred here. Missing history blocks dependent
studies. M0.3B adoption, the other seven strategy definitions, every full-data
mode and all later roadmap work remain required.

## 7. Historical repair attempt 1 — 2026-09-06 03:53 Pacific

Status remains **PARTIAL**. The existing implementation and tests were inspected
before repair; their bytes are unchanged. The repair-start backup is
`/tmp/trade-alerts-m22-repair1-9cc6yy3h/`. The whole milestone change list in §5
still applies, including work from the first attempt.

The unchanged launcher was retried with all five selectors in §3. It again failed
at `os.chown`, with the exact new traceback in M2_2_LAUNCHER_LIMITATION.txt.
Launching the same protected command as the project account also failed before
startup: `setpriv: setresuid failed: Invalid argument`. No test or end-to-end
case ran. No passing execution artifact is claimed or substituted with a syntax
check. The saved local checks distinguish the first attempt from this repair.

A bounded read-only source/test search found no missing supported selector or
obvious compatibility break. This is inspection only, not independent acceptance.
No application code change can repair the observed account/ownership failure.
The user explicitly assigns external protected execution to the supervisor when
this sandbox cannot run it. Both protection files remain unchanged.

The exact dependency is still the supervisor's two protected runs, inspection of
both XML/isolation records and identical synthetic proof files, restoration of
the five new files' project ownership, then independent review. Keep M2.2 [~]
and **next_milestone: M2.2** while that verification is pending. This is incomplete
verification of written work, not a new data or product-definition blocker.
M2.3 is not selected or started. All other unfinished rows remain tracked.

## 8. Historical repair attempt 2 — 2026-09-06 03:59 Pacific

Status remains **PARTIAL**, with **next_milestone: M2.2**. The current source
and tests were read before repair and match the previously saved hashes.
All 11 milestone paths in §5 remain the whole change list. The repair backup
is `/tmp/trade-alerts-m22-repair2-gnaz7h8j/`; it saves 204 source, test, configuration
and document files. Live database files were excluded from this check.

The unchanged launcher failed at its ownership step again. Its exact output
is appended to M2_2_LAUNCHER_LIMITATION.txt. The new artifact directory is
empty: no XML, isolation report or synthetic end-to-end output exists from
this run. Fresh ownership attempts on the same five files also failed.
The earlier project-account alternative failed before startup and was not
repeated. No application code or launcher change can be justified by this
pre-test error. The owner assigns external protected execution to the
supervisor when this restricted process cannot run it.

A bounded read-only helper checked historical request callers, compatibility
tests and the next-step dependencies. It found no additional affected test
supported by the existing protection. Keep all five selectors in §3. M2.3
is not selected: its precise offline slice and streaming field, cadence,
coverage and freshness requirements still need the M0.2/source-definition
check. The current handoff requires M2.2 verification first. This helper
inspection does not replace the supervisor's independent review.

M2_2_LOCAL_CHECKS.json records this attempt separately, including unchanged
implementation/test/protection hashes, source syntax, file preservation,
document links, dormant switches and the whole milestone delta. These are
static checks, not passing tests. No product approval or source is missing
for the written M2.2 software slice; its remaining gate is protected
execution and ownership restoration by the supervisor, followed by review.
Keep M2.2 [~] rather than marking it complete or skipping to another build.
All existing data, approval, full-mode and later milestone obligations stay
open. No live access, paid request, runtime activation or Git change occurred.

## 9. Supervisor proof finalized — 2026-09-06 Pacific

Historical proof for the source before the review repair in §10. Its passing
results do not apply to the changed condition or newly required test selection.

The supervisor supplied fresh protected execution at 09:27:31 Pacific and its
unchanged-source handoff at 09:36:46 Pacific. This fresh builder session read
`publication.json`, checked all 21 published file hashes and the 208,512-byte
total, then inspected each run's XML, isolation report and history proof.
[M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json) saves the publication hashes,
per-run counts, identical test-ID proof, Pacific output summaries and source
comparison. Original execution artifacts remain in the supervisor's readable
publication; its machine-local location stays out of public documentation.

Both runs passed **418 tests** (836 executions), including **71 M2.2 cases**.
Each has zero failures, errors or skips, identical ordered test IDs, no unexpected
isolation denials and all four cleanup checks true. The six deliberate forbidden
access checks were denied as intended. `summary.json` records two zero exits and
$0 Databento use. Existing history/client/model/skew compatibility and all prior
protected contracts were included in the first five selectors now listed in §3. The full application
release suite and the unsupported broader legacy files in §3 were not executed
or claimed passing. Existing M18.4/M18.6 limits remain open.

Both `m22-history-proof.json` files have SHA-256
`8c8358e78348a6c13994400a7e6813fa328b471e2b51ba1336808a87c5ee2a56`.
The recorded synthetic request passes through the actual raw historical request
function with fake transport, M2.1 normalization, canonical bars, calendar coverage
and archive round trip. The inspected results on the synthetic June 30 session are:

- 06:34:59 Pacific: four FINAL intervals and one NOT_ENDED; incomplete; 46 shares.
- 06:35:00 Pacific: four FINAL intervals and one MISSING; incomplete; 46 shares.
- 06:35:02 Pacific: five FINAL intervals; complete; 60 shares.

The fifth interval's original availability is 06:35:02, while later normalization
is 13:30 Pacific. The archive preserves that difference. Separate passing cases
prove later revisions cannot change earlier views, duplicate re-fetches do not
refresh market facts, missing intervals are not no-trade certifications, and
calendar/convention mismatches cannot establish complete coverage. This closes
M2.2's offline bar-availability/coverage slice of AT-02. M3.6 still owns actual
opening-range extrema and its at-least-one-traded-input requirement. M0.2 retains
all real source/finality/coverage evidence. No strategy performance is measured.

All **771 file contents** in the supervisor's saved manifest matched before these
document edits. Its canonical manifest hash matches the supplied source identity:
`aec4e273f740d786f646b338718c176ec199b8d806634152b13453a05019c526`.
Final checks compare the unchanged code, tests, settings and protection again.
The supervisor reports new-source ownership restored. This sandbox reports the
same local owner for both old and new files, which differs from the supervisor's
saved owner metadata; that view cannot independently confirm host ownership.
No ownership change was attempted. Existing document files were written in place,
and their local ownership/modes were preserved.

The earlier launcher failures remain in §4/§7/§8 and
[M2_2_LAUNCHER_LIMITATION.txt](./M2_2_LAUNCHER_LIMITATION.txt); they are not the
current test status. The launcher was not repeated or changed in this session.
The recoverable document backup and final document checks are recorded in
M2_2_LOCAL_CHECKS.json. No source/test/configuration, approved rule, proposed
packet, failing-test list, runtime memory or controller file was changed. No
application, provider, broker, Discord, paid request, restart or Git mutation ran.
All new switches remain off. Engineering completion is not profitability evidence.

## 10. Review repair — 2026-09-06 Pacific

Historical repair record. Section 11 supplies the later passing protected proof
and supersedes this section's pending-execution instructions.

The reviewer returned three issues: unknown evidence-reference labels could
complete coverage; active handoffs still selected M2.2; two safe peer-history
caller tests were missing from the protected selection. Existing partial work
was inspected and preserved before edits. The recoverable repair backup is
`/tmp/trade-alerts-m22-review-repair-b6f94i1w/`; it contains 526 source, test,
configuration and documentation files plus their hashes and local ownership/modes.

The bounded repair changes one production condition: `UNKNOWN` and `UNSPECIFIED`
evidence references, ignoring case and outer spaces, cannot satisfy known source
conventions. Four added parameter cases require `UNKNOWN_CONVENTIONS`, incomplete
coverage and no final-bar subset, while retaining the observed closing price.
The raw request path, existing mappings and required end-to-end case are preserved.
No new data, strategy rule, switch, dependency or protection change is needed.

The two added selectors in §3 exercise `peer_comparison._pct_change()` through
the existing history wrapper: too few daily rows return no result; six synthetic
closes produce the expected 10% change. Their fake history source avoids live
access. A bounded read-only helper identified these exact supported cases; this
corrects the earlier helper's incomplete selection, without replacing the
supervisor's independent review. SESSION_PROTOCOL §§35/36/41 and DECISIONS
§§29/37 now select M2.3 after M2.2 acceptance. D-090/D-091 approval records and
ledger, M0.3B proposals and every unresolved gate remain unchanged.

The unchanged launcher was attempted with all seven selectors. It exited 1 before
either protected child or any test ran:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-a1ph9qzk'`

[M2_2_LAUNCHER_LIMITATION.txt](./M2_2_LAUNCHER_LIMITATION.txt) saves the full exact
traceback. The created artifact folder is empty: there is no fresh XML, isolation
report or end-to-end output. The earlier project-account workaround also failed
in §7; it was not repeated and no protection was bypassed. Fresh supervisor
execution of the repaired source is the sole remaining verification step.
Use **ready_for_verification**, keep M2.2 [~], and retain M2.3 as the next build
after acceptance. Do not count the old 418-test proof as this repair's results.

[M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json) separates current syntax,
preservation, documentation and source-hash checks from historical execution.
Source compilation is not a passing test. There is no configured lint/type-check
task. The existing M2.2 end-to-end proof must run again through fake transport,
real normalization, calendar coverage and archive round trip, with identical
outputs in both protected runs. No application, broker, Discord, credential,
live database, paid request, restart, deployment, Git mutation, runtime memory
or controller change occurred. All switches remain off; §6 retains the precise
supervised source-data requirements and every later feature obligation.

## 11. Repaired source proof finalized — 2026-09-06 Pacific

The supervisor supplied protected execution at **10:13:37 Pacific** and the
unchanged-source handoff at **10:15:24 Pacific**. This fresh builder read the
published artifacts and checked all **21 file hashes**, totaling **210,435 bytes**.
Both XML result files, isolation reports, output logs and history proofs were
inspected. The saved results in [M2_2_LOCAL_CHECKS.json](./M2_2_LOCAL_CHECKS.json)
identify these artifacts by hash; their private machine location is not reproduced
here. Earlier evidence remains under historical keys in that record.

Both runs passed **424 tests** (848 executions), with zero failures, errors or
skips and identical ordered test IDs. Each includes **75 M2.2 cases**, the four
unknown-reference repair cases and both peer-history caller cases. The six
deliberate forbidden-access checks were denied as intended. There were no
unexpected denials; all four cleanup checks passed and every database connection
was temporary. The unchanged launcher's summary records two zero exits and $0
Databento use. These results verify the repaired code and all seven §3 selectors.

The actual request → fake transport → raw response → M2.1 normalization → Bar
records → scheduled coverage → archive round trip produced byte-identical
`m22-history-proof.json` files. Their SHA-256 is
`8c8358e78348a6c13994400a7e6813fa328b471e2b51ba1336808a87c5ee2a56`.
The saved synthetic June 30 views show:

- 06:34:59 Pacific: four FINAL intervals and one NOT_ENDED; incomplete; 46 shares.
- 06:35:00 Pacific: four FINAL intervals and one MISSING; incomplete; 46 shares.
- 06:35:02 Pacific: five FINAL intervals; complete; 60 shares.

The last bar retains original availability at 06:35:02 despite normalization at
13:30 Pacific. Passing revision cases preserve earlier views. Unknown-reference
cases preserve observed prices but block complete coverage. This completes only
M2.2's offline availability/coverage slice of AT-02. Synthetic examples do not
establish provider coverage or trading returns. M3.6 retains actual opening-range
extrema and the traded-input requirement; M0.2 retains real source proof.

Before any document edit, all **771 file contents** matched the supervisor's
saved manifest. Its canonical SHA-256 matches the handoff:
`52b99cff0c95b5eb65c6981ff44900de5cae7eabcef371d6883eda306b50c158`.
The recoverable before-edit copies and final preservation/document checks are
identified in M2_2_LOCAL_CHECKS.json. This session changes only evidence and
handoff documents. Code, tests, configuration, both protection scripts, the
failing-test list, approval records and proposal packets remain unchanged.
Local document ownership and modes are preserved; this sandbox's mapped owner
view does not independently establish host ownership. No ownership change or
launcher retry was needed. No application, network, credential, live database,
paid request, message, restart, deployment, runtime-memory, controller or Git
mutation occurred. All new switches remain off.

M2.2 is **completed** for this bounded implementation and evidence handoff. The
supervisor's separate reviewer still decides acceptance. **M2.3 remains the
proposed next milestone**, with its unchecked row and unchanged scope in §6 and
ROADMAP §31. No unresolved product choice, data gate or later feature is closed
by this records-only finalization.
