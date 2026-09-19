# M2.3 offline Quote event handling — second repair proof finalized

Date: 2026-09-06 Pacific. Status: **completed** for the bounded offline
implementation and evidence handoff. Section 12 records fresh supervisor proof
for both source-time repairs in §11: **490 tests passed in each of two protected
runs**, with identical 43-decision recordings. The separate reviewer still decides
acceptance. Section 10's 489-test/35-decision proof and §8's 487-test proof remain
historical. The live-provider branch in §7 remains blocked. This supporting record
adds no specification, data, trading or live-operation approval.

## 1. Scope, starting state and preservation

The assignment matches ROADMAP §31's saved M2.3 handoff and M2_2_VERIFICATION §6.
All nine canonical files, PREBUILD_REVIEW, M0.4/M1/M2 evidence, PROJECT_RULES and
WORKFLOWS were read. Existing Quote records, REST mapping, shared clock, protected
fixtures and relevant legacy callers were inspected before adding a new module.
No prior M2.3 implementation or repair files were present. Repaired M2.2 and all
owner work were preserved; nothing was restarted from saved Git code.

A recoverable starting snapshot contains 528 source/test/configuration/document
files with hashes, modes and ownership. Its temporary path is saved in
M2_3_LOCAL_CHECKS.json. The starting failing-test list was empty. Read-only Git
used GIT_OPTIONAL_LOCKS=0 and reported permission errors for unrelated saved
workflow files; those files were not opened, altered or used as project state.
No Git operation changed files or metadata. No controller or runtime-memory file
was edited. No setup, background workflow or application execution occurred.

The drift check found the offline prerequisite independent of missing provider
facts and proposed trading choices. D-090 and its packet are unchanged. M0.3B
remains proposed; current source coverage, live streaming, full-data modes and
other seven strategy definitions remain open. Earlier evidence handoffs are dated
history; current routing follows ROADMAP §31. All new switches remain off.

## 2. Implemented contract and acceptance claims

CODING_STANDARDS §60 records the exact engineering contract. The additions are:

1. `QuoteEventPolicy`, with explicit supplied quote/trade age and observation-gap
   limits, no defaults, strict finite positive seconds and a known policy label.
   Missing policy cannot produce usable data; test values are synthetic only.
2. `QuoteEventStream`, one synchronous owner per source/instrument/type/session/
   mode, using canonical Quote snapshots and supplied aware evaluation times.
   Current data and two timestamp/fact watermarks are the bounded retained state.
   No network, clock read, queue, database, transport or live consumer is added.
3. Separate quote/trade ages, original availability, exact latest duplicates,
   component-wise time advances, conservative older/conflicting-event handling,
   missing/delayed/bad-source results and explicit revision handling. Re-reading
   the same snapshot cannot refresh timestamps, heal a gap or inflate forwarding.
   Invalid snapshots remain visible rather than falling back to old good data.
4. Disconnect/gap/reconnect and explicit recovery proof. A connection does not
   restore continuity. Confirmation needs a newly consumed healthy snapshot in
   the current epoch, matching record/evidence identity and source/quote/trade
   times after the recovery boundary. Same-time reconnect cannot reuse old data.
5. Frozen deterministic `QuoteEventDecision` recording, including original Quote,
   policy, ages, reasons, action, continuity and independent forwarding flags.
   Only forwarding flags supply downstream observations. `usable` describes the
   current retained data, not acceptance of an ignored/mismatched input. A trade
   snapshot is not a complete tape feed or a certified transaction count.

Two bounded read-only helpers checked reuse and traced source/test paths. The
static test check found and prompted the same-time reconnect repair above. This
assistance is not the supervisor's final independent review or passing execution.

## 3. Required protected selection and end-to-end proof

Section 12 verifies the second review repair in §11 with two fresh protected
runs of the full selection below. Sections 8 and 10 remain historical proof for
earlier source. The supervisor's independent review still decides acceptance.

Use the unchanged `scripts/testing/run_trade_alerts_contracts.py` with:

- `tests/trade_alerts_contracts`
- `tests/test_models.py`
- `tests/test_schwab_client.py`

The directory includes all prior M0.4/M1/M2 contracts and new M2.3 cases. Existing
record/client tests cover the unchanged legacy interfaces used alongside this
addition. No earlier production file, mapper, clock, config or launcher changed.
Search found no live consumer or other existing dependent of the new symbols.
Do not run legacy tests directly or expand the filesystem protection.

Required case: `test_normalized_events_failure_reconnect_recording_end_to_end`.
It passes synthetic REST-shaped input through the real M2.1 mapping, canonical
Quote serialization, M2.3 decisions and a recording output. Fixed input covers
independent ages/advances, duplicates, old data, connection loss/reconnect, wrong
and unknown recovery proof, explicit/elapsed gaps, delayed/missing data and new
recovery observations. The §9 repair extends it with missing/wrong-session source
times on repeated quote/trade timestamps, rejected confirmation and a cache repeat
that cannot restore usability. Section 11 adds a same-session source time before
recovery, a source time after availability, rejected confirmations, inspection
after the clock catches up, and fresh recovery. Written expected quote IDs are
q1/q2/q5/q10/q14/q18; expected last-trade snapshot IDs are q1/q3/q5/q10/q14/q18,
across 43 decisions. Section 12 confirms these expanded expectations in both
protected runs. Sections 8/10's 27/35-decision recordings are historical.

Each protected child must write `m23-quote-events-proof.json`. The supervisor
must run the whole selection twice and provide both JSON files, XML results,
isolation reports, logs and launcher summary. Require matching test IDs, zero
failures/errors/skips, no unexpected denials, successful cleanup and byte-identical
end-to-end recordings. The fresh builder must inspect the actual artifacts and
source identity, finalize evidence/roadmap only, and return completed. The separate
reviewer decides acceptance. An empty artifact folder is not a passing result.

Other written cases cover exact age boundaries, missing policy/evidence, invalid
limits, cache repeats across an elapsed gap, conflicting/revised inputs, wrong
scope/session, future availability/source time, current ID reuse, stale recovery
proof, same-time reconnect, opaque sequence jumps, source quality, zero/missing
prices, impossible crossed input, monotonic time and immutable output.

## 4. Local checks and exact test limitation — historical

Sections 8 and 9 supersede this section's original handoff. The original builder
errors remain evidence of those attempts, not verification of the review repair.

The starting protected selection stopped before either child at the launcher's
ownership step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-job26gup'`

[M2_3_LAUNCHER_LIMITATION.txt](./M2_3_LAUNCHER_LIMITATION.txt) retains the complete
traceback and the final post-implementation attempt. Neither protection script
was changed or bypassed. No acceptance test or actual end-to-end artifact was
produced by the builder. Fresh supervisor execution is required.

[M2_3_LOCAL_CHECKS.json](./M2_3_LOCAL_CHECKS.json) records source compilation,
Python 3.10 grammar, changed-file and preservation checks, document links, dormant
settings and actual launcher status. Compilation does not execute or test the
application. No configured lint/type-check task exists; no tool or dependency was
installed. Existing owner/mode settings were preserved through in-place writes;
new-file ownership restoration was attempted and also returned `[Errno 22] Invalid argument`
for all five new files. The supervisor must restore their project ownership as
part of external verification preparation; these files have no live consumer.
The exact per-file errors are saved in that check record. The full application
and live checks are not run or claimed passing in this unattended offline lane.

## 5. Whole milestone change list

These are the M2.3 changes from its saved starting snapshot, including all changes
from the initial implementation, prior records-only finalization and §9 review
repair. Earlier owner foundation/normalization/history work is excluded. During
the prior finalization only this record, M2_3_LOCAL_CHECKS.json and ROADMAP.md
changed. The repair also changes the M2.3 source/tests and synchronizes its
canonical contract/status records; all twelve milestone paths remain listed.
The §10 finalization changed only this record, M2_3_LOCAL_CHECKS.json and ROADMAP.md.
The second review repair in §11 preserves that work and updates the same twelve
milestone paths; its complete change list remains below. The §12 finalization
changes only this record, M2_3_LOCAL_CHECKS.json and ROADMAP.md.

- `consensus_engine/quote_events.py`
- `tests/trade_alerts_contracts/test_quote_events.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/SESSION_PROTOCOL.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M2_3_VERIFICATION.md`
- `trade_alerts_build_docs/M2_3_LAUNCHER_LIMITATION.txt`
- `trade_alerts_build_docs/M2_3_LOCAL_CHECKS.json`

## 6. Saved handoff

**next_milestone: M2.4 (proposed, gated on independent acceptance).** Section 12
completes fresh protected proof and records-only finalization for the second
M2.3 repair. Independent acceptance of that repair and this next scope remains.
The controller stays on M2.3 until that review passes. Neither §8 nor §10's
earlier proof satisfies the current repair gate. This record does not start M2.4.

- [ ] **M2.4:** offline reference-input snapshot/coverage prerequisite; current
  provider coverage and historical sector membership remain separate data gates.

Build one small supplied-record interface for SPY, QQQ and DATA_REQUIREMENTS §12's
11 sector ETFs, with VIX explicitly unavailable unless a supported supplied input
exists. Reuse canonical Bar/Quote records, M2.2 available-time coverage and M2.3
per-symbol event decisions where applicable. Reuse `analysis.wolf_scope.stock_sector_etf`
and its current source mapping without changing its old caller behavior. Unknown
stock mapping stays unknown; a current mapping is not historical membership.
Any supplied per-symbol age/continuity policy remains explicit and versioned.

Keep expected references separate from observed valid records. Preserve individual
source/session/availability times and explicit missing/stale/delayed/bad-quality
states. A fresh SPY input cannot make missing QQQ or a missing sector available.
Do not silently substitute proxies, renormalize missing sector weights, calculate
new RS/breadth/return formulas, infer complete data from symbols, or add live calls.
If raw VIX identity/type/semantics lack support, keep that path unavailable and
record the exact data dependency; do not invent an index mapping or source fact.

Acceptance: protected fixed-input tests for present/missing SPY/QQQ/sectors/VIX,
unknown mapping, wrong symbol/session/source, future availability, stale component
and immutable snapshots, with the actual supplied-record -> per-symbol coverage ->
recording path producing identical output in two protected runs. Inspect affected
mapping tests such as `tests/test_wolf_macro_brain.py::test_stock_sector_etf` before
selecting supported compatibility tests. Preserve the launcher and all owner work.
After the repaired M2.3 verification/acceptance gate, this offline interface can
proceed without current provider data or new trading choices. It does not complete
the full live reference-input requirement.

## 7. Required live branch blocker and reopening proof

- [!] **M2.3 live-provider completion:** BLOCKED BY DATA and separately supervised
  access authority. No transport or provider evidence is supplied by this offline
  prerequisite; the required full streaming branch remains unfinished.

Affected path: all playbooks' mandatory live L1 and faithful sub-minute studies.
Missing evidence: official streaming field definitions and partial-update meaning;
current account entitlement/subscriptions; source/quote/trade timestamps, cadence
and per-symbol coverage; authentication refresh/resubscription; disconnect/lost
input and recovery/warm-up continuity; shared request/subscription and queue,
timeout, storage, retention, disk and memory budgets alongside existing consumers.

Reopening test: in a separately authorized supervised step, inspect existing
local/raw/provider records first; obtain official/account evidence for the actual
transport; save dated per-symbol/session samples and measurements; exercise bounded
refresh/reconnect/resubscription and missed-input recovery with a recording sink;
verify shared capacity and an approved explicit age/coverage policy. Only then
implement/accept the required transport branch using existing authentication and
host controls. REST fixtures, synthetic event labels and a successful socket
connection do not establish those facts.

Existing Schwab/local/free routes are first. No purchase is necessary for M2.3's
offline contract or proposed M2.4 offline scope. If a purchase is later needed,
record exact fields/dates/fidelity, the existing/free gap and verified bounded
cost for separate supervised authorization under D-091. This session read no
credential and made no live/paid request; $0 used and $0 reserved remain unchanged.

M0.2 history/finality/adjustment/corporate-action and reference coverage, M0.3B
adoption, the other seven definitions, M10.7 full breadth, M12 faithful catalyst,
M13.7 true profile and every later required feature remain tracked. The known
broader listener isolation gap stays M18.4. There is no application run, message,
order, restart, deployment, activation, account reset-credit use or billing fallback.
Engineering completion would not be evidence of profitability.


## 8. Supervisor proof finalized — 2026-09-06 Pacific

**Historical, before the §9 review repair.** These results and the completed
status below describe the earlier source only. Review reopened offline acceptance;
they cannot certify the repaired code/tests or authorize advancing to M2.4.

The supervisor supplied successful protected tests and the unchanged-source
handoff at **10:58:04 Pacific**. This fresh builder read the publication manifest,
both result files, isolation reports, output logs and Quote decision recordings.
All **23 published file hashes** match, totaling **317,292 bytes**.
[M2_3_LOCAL_CHECKS.json](./M2_3_LOCAL_CHECKS.json) saves the inspected hashes,
per-run counts, source identity and all 27 decision summaries with Pacific times.
The original artifacts remain in the supervisor's readable publication; its
private location is not copied into public records.

Both runs passed **487 tests** (974 executions), including **84 M2.3 cases**,
with zero failures, errors or skips and identical ordered test IDs. All three
selectors in §3 were included. The six deliberate forbidden-access checks were
denied as intended. There were no unexpected isolation denials; all four cleanup
checks passed and every database connection was temporary. The unchanged launcher
reports two zero exits and $0 Databento use. These are supervisor executions,
not a builder launcher retry or a source-compilation result.

The actual synthetic raw response → M2.1 normalization → canonical Quote round
trip → M2.3 age/continuity decisions → recording path produced byte-identical
`m23-quote-events-proof.json` files. Their SHA-256 is
`1b229326ed7bdcac63d2aadc66cdc21f1b4ef42b8af6be847985c376cffdfe40`.
The 27 recorded decisions show:

- Quote observations forward only for q1/q2/q5/q10; last-trade snapshots forward
  only for q1/q3/q5/q10. Duplicate and recovery snapshots forward neither.
- At 06:35:04 Pacific, q1's quote age of 3 seconds is within the supplied test
  limit. At 06:35:04.001, age 3.001 is stale and the snapshot is unusable.
- The out-of-order input at 06:35:08 loses continuity. Reconnection at 06:35:10
  and a repeated snapshot do not restore it. Old and unknown proof are rejected;
  new matching proof at 06:35:11 restores usability without forwarding a sample.
- Explicit and elapsed observation gaps stop forwarding. Delayed and missing
  inputs remain unusable. Fresh recovery proof at 06:35:24 allows q10 to forward
  at 06:35:25. No retained good quote conceals the missing input.

Other passing cases cover the same-time reconnect repair, independent stale
quote/trade ages, future availability, revisions, conflicts, identity/session
mismatches, missing policy and immutable output. Prior record, normalization and
history proof files also match across runs. This closes only the offline ordering,
continuity and age slices of AT-03/AT-04. Feature sampling/counts, full observation
windows, stock/option alignment and durable replay retain their M3/M6/M14.2/M5
owners. Synthetic limits and evidence labels prove neither live policy approval
nor provider coverage. No full-suite, live-delivery or profitability claim follows.

Before any edit, all **776 file contents** matched the supervisor's saved manifest.
Its canonical SHA-256 matches the supplied source identity:
`211f42f66ee5243e84aa56165758abc92d2b1c2cd46d2d8781fdff2f694b8a90`.
Recoverable before-edit copies and final preservation/document checks are recorded
in M2_3_LOCAL_CHECKS.json. Code, tests, configuration, both protection scripts,
the failing-test list, approved/proposed packets and owner work remain unchanged.
Document writes preserve local ownership and modes. The supervisor manifest records
project ownership; this sandbox maps old and new files to the same different local
owner, so it cannot independently confirm host ownership. No ownership change was
attempted in this finalization.

The earlier pending-proof wording in PROJECT_INDEX §§21–22/30, SESSION_PROTOCOL
§§35–36/41/43, DATA_REQUIREMENTS §38, TESTING_AND_VALIDATION §58 and DECISIONS
§§29/37/39 describes the initial implementation handoff. This §8 and ROADMAP §31
supersede that status. Those files stay unchanged under this records-only assignment;
no governing contract or next-milestone scope changes. The nine canonical authorities,
eight playbooks, 31 functional rows and 22 additional capability rows remain intact.

M2.3 is **completed** for the assigned offline implementation and evidence handoff.
The supervisor's separate reviewer still decides acceptance. **M2.4 remains the
proposed exact next milestone**, with its unchecked row and scope in §6 and
ROADMAP §31. The required live M2.3 blocker in §7 remains open. No application,
provider, credential, live database, message, order, restart, deployment, purchase,
Git mutation, runtime-memory or controller change occurred. All new switches
remain off; D-090, M0.3B's proposed status and D-091's $0 usage/$0 reservations
are preserved.


## 9. Review repair — 2026-09-06 Pacific

**Historical repair handoff. Section 10 supersedes the pending-proof status below.**

Status: **ready for protected verification**. Offline acceptance is incomplete
until two fresh protected runs pass on this repaired source and the supervisor's
independent review accepts the result. The code and tests were inspected in place;
no earlier work was discarded or restored from Git. The repair-start source/test
hashes match the §8 proof. Recoverable copies and preservation checks are saved in
M2_3_LOCAL_CHECKS.json. The whole milestone's twelve-file list in §5 is unchanged.

The reported defect was `consume()` returning `REPEATED_TIMESTAMPS` before checking
an incoming source timestamp. When quote/trade times and prices stayed the same,
a null source time or a source time from the previous session left the old good
quote usable. The shortcut now requires a present source time in the stream's
session. Otherwise the existing invalid-data path retains the supplied bad Quote,
records `SOURCE_TIME_UNKNOWN` or `SOURCE_SESSION_MISMATCH`, loses continuity and
forwards neither component. This enforces CODING_STANDARDS §60 and DATA §32; it
adds no default, source assumption or trading rule. Ordinary valid duplicates and
same-time cache healing restrictions retain their contracts.

`test_repeated_timestamps_cannot_hide_invalid_source_time` has two cases: source
time null and source time one day earlier, with unchanged quote/trade timestamps.
Each requires the exact bad snapshot and reason to remain visible on consumption
and inspection; unusable state and no forwarding; lost continuity; rejected
confirmation and old proof; inability of a healthy cache repeat to heal the gap;
and a fresh observation plus current proof before forwarding resumes. The earlier
frozen decision must remain unchanged. These are written assertions, not a passing
execution claim.

The existing end-to-end recording test still runs real M2.1 normalization,
canonical Quote round trips and M2.3 decisions with fixed synthetic input. It now
adds both bad source-time cases after q10, rejected confirmations, a cache repeat,
fresh q13-recovery plus evidence, and q14 forwarding. Expected output: 35 decisions,
quote IDs q1/q2/q5/q10/q14 and trade-snapshot IDs q1/q3/q5/q10/q14. The two protected
`m23-quote-events-proof.json` files must be byte-identical. The existing 27-decision
recordings cannot stand in for this expanded proof. Neither synthetic counts nor
these source checks establish provider coverage or profitability.

Use exactly the three selectors in §3 through the unchanged launcher. Search found
no live caller or additional supported dependent of QuoteEventStream/QuoteEventPolicy.
The two existing compatibility selectors and all prior contracts remain included.
Do not weaken protection or execute legacy tests outside it. Successful supervisor
artifacts must return to a fresh builder for records-only finalization, then the
separate reviewer decides acceptance. M2.4 remains gated as recorded in §6 and
ROADMAP §31; the required M2.3 live-provider blocker in §7 is unchanged.

The post-repair protected attempt stopped before either child at the launcher's
ownership step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-0zcf8mc7'`

The launcher exit code is 1. The artifact directory is empty: no tests, XML,
isolation report or repaired recording output were produced. The complete exact
traceback is appended in M2_3_LAUNCHER_LIMITATION.txt. Neither protection script
was changed or bypassed. Source compilation and Python 3.10 grammar pass; they
are not execution proof. No configured lint/type-check task exists. Current local
checks, preserved historical proof and source identities are separated in
M2_3_LOCAL_CHECKS.json. Existing ownership and modes are preserved through in-place
writes; no ownership change is needed or attempted for this repair.

Implementation is finished and protected execution is the sole remaining step
before records-only finalization and independent review. Return
`ready_for_verification`, keeping M2.3 [~] and the required live branch [!]. The
supervisor must supply two successful protected runs of §3's selection, including
both added cases and the expanded 35-decision recording, before a fresh builder
can mark offline evidence complete. The saved proposed next milestone remains
M2.4; it cannot advance while this gate is open. No application run, live call,
credential access, live database access, purchase, switch change, Git mutation,
controller change or runtime-memory edit occurred. D-091 remains $0 used and
$0 reserved; all other unfinished roadmap work stays tracked.


## 10. Repaired source proof finalized — 2026-09-06 Pacific

**Historical, before the second review repair in §11.** This proof describes the
previous source only. Its completion statements cannot close the reopened gate.

The supervisor supplied fresh protected execution and its unchanged-source
handoff at **11:25:50 Pacific**. This builder read the published result files,
isolation reports, output and diagnostic logs, launcher summary and both repaired
Quote recordings. All **23 published file hashes** match, totaling **343,979 bytes**.
[M2_3_LOCAL_CHECKS.json](./M2_3_LOCAL_CHECKS.json) saves the publication hashes,
source identity, counts and all 35 decision summaries with Pacific times. The
original artifacts remain in the supervisor's readable publication; its private
location is not copied into public records.

Both runs passed **489 tests** (978 executions), including **86 M2.3 cases** and
both `test_repeated_timestamps_cannot_hide_invalid_source_time` cases. The complete
three-selector selection in §3 ran twice. There were zero failures, errors or
skips, and the ordered test IDs match. The six deliberate forbidden-access checks
were denied as intended; unexpected denial maps are empty. All four cleanup checks
passed and every recorded database connection was temporary. The unchanged launcher
records two zero exits and $0 Databento usage. Diagnostic warnings/errors came from
the synthetic delivery-failure and missing-credential cases. These are supervisor
executions; this builder did not retry the launcher or run the application.

The actual synthetic raw response → M2.1 normalization → canonical Quote round
trip → M2.3 age/continuity decisions → recording path produced byte-identical
`m23-quote-events-proof.json` files, each containing **35 decisions**. Their SHA-256 is
`915e86e03cfde40c903c0c4b490080bb9b28ee525ef45f291233493e9bfd2b71`.
The inspected output shows:

- Forwarded quote IDs are q1/q2/q5/q10/q14. Forwarded last-trade snapshot IDs are
  q1/q3/q5/q10/q14. Repeated and recovery snapshots forward neither component.
- At 06:35:26 Pacific, q11-source-missing remains visible with SOURCE_TIME_UNKNOWN,
  lost continuity and no forwarding. Confirmation fails. At 06:35:27, the old
  healthy q10 cache repeat still retains that unusable q11 snapshot.
- At 06:35:28 Pacific, q12-source-wrong-session remains visible with
  SOURCE_SESSION_MISMATCH, lost continuity and no forwarding. Confirmation fails.
- At 06:35:29 Pacific, fresh q13-recovery stays unusable until matching current
  proof confirms continuity. Confirmation forwards nothing. At 06:35:30, q14
  forwards both components.

The earlier age boundary, independent component advances, duplicate/old inputs,
disconnect/reconnect, wrong/unknown proof, explicit/elapsed gaps and delayed/missing
input cases also pass on this repaired source. Prior domain, normalization and
history proof files match between the two runs. This closes only M2.3's offline
ordering/continuity and age slices of AT-03/AT-04. Feature sampling/counts and full
windows remain M3/M6; stock/option timing remains M14.2; durable replay/recovery
remains M5. Synthetic input proves no provider coverage, live policy, trading
return or release readiness. The full live branch remains blocked in §7.

Before any edit, all **776 saved file contents** matched the supervisor's manifest.
Its canonical SHA-256 matches the supplied source identity:
`980bc34bbb0bdad0259a6f1cac57550651f1310118d715788fdbe1312eb90873`.
Recoverable before-edit copies and final preservation/document checks are recorded
in M2_3_LOCAL_CHECKS.json. Only this evidence record, its local-check JSON and
ROADMAP.md changed during this finalization. Code, tests, configuration, both
protection scripts, the failing-test list, approved/proposed packets and all other
owner work remain unchanged. In-place document writes preserve local ownership
and modes. The sandbox's mapped owner view cannot independently establish host
ownership; no ownership change was needed or attempted.

Pending-proof wording in PROJECT_INDEX §§21–22/30, SESSION_PROTOCOL §§35–36/41/43,
DATA_REQUIREMENTS §38, TESTING_AND_VALIDATION §58 and DECISIONS §§29/37/39 describes
the §9 repair handoff. This §10 and ROADMAP §31 supersede that status. Those files
stay unchanged under this evidence-and-roadmap-only assignment; no governing
contract or next-milestone scope changes. The nine authorities, eight playbooks,
31 functional rows and 22 additional capability rows remain intact.

M2.3 is **completed** for the assigned offline implementation and evidence handoff.
The supervisor's separate reviewer still decides acceptance. **M2.4 is the proposed
exact next milestone**, with its unchecked row and unchanged scope in §6 and
ROADMAP §31. The required live M2.3 row remains [!]. No application run, provider
request, credential/live-database access, message, order, restart, deployment,
purchase, Git mutation, controller change or runtime-memory edit occurred. All new
switches stay off; D-090, M0.3B's proposed status and D-091's $0 used/$0 reserved
are unchanged. Engineering completion is not evidence of profitability.


## 11. Second review repair — 2026-09-06 Pacific

**Historical repair handoff. Section 12 supersedes the pending-proof status below.**

Status: **ready for protected verification**. The earlier 489-test/35-decision
proof in §10 predates both findings below. Offline completion is reopened in
ROADMAP §31; it stays [~] until fresh protected proof and records-only finalization.
The supervisor's independent review still decides acceptance. The required live
M2.3 blocker in §7 stays [!], and M2.4 stays gated as recorded in §6.

The existing partial work and evidence were inspected before editing. Recoverable
copies, starting hashes and ownership/mode checks are recorded in
M2_3_LOCAL_CHECKS.json. No file was restored from Git. The whole milestone delta
remains the twelve paths in §5, including both earlier repair/finalization attempts.

The repair addresses two observed source-code defects:

1. A repeated quote with recovery at 06:35:00 Pacific and source time 06:34:59,
   in the same session, took the repeated-timestamp shortcut and left the prior
   good quote usable. The shortcut now checks the recovery boundary before
   preserving a healthy current snapshot. The bad input is retained with
   SOURCE_BEFORE_RECOVERY, continuity is lost and neither component forwards.
2. A source time after original availability was rejected, but the decision
   retained the previous quote and hid the offending timestamp. The invalid input
   is now retained with INVALID_SOURCE_TIME. That reason remains on inspection
   even when evaluation time reaches the source timestamp. Neither a cache repeat
   nor old recovery proof restores usable data.

A small retained-state marker records whether the current snapshot was rejected
when consumed. It preserves the earlier non-healing contract: a same-time cache
repeat cannot replace a rejected snapshot or turn it valid. A newly consumed
healthy observation clears that marker; separate current recovery proof is still
required. This adds no provider assumption, trading threshold or live default.
The marker is bounded state alongside the existing current record and watermarks.

`test_repeated_timestamps_cannot_hide_invalid_source_time` keeps its earlier
missing/wrong-session and cache-preservation assertions and adds the exact
06:34:59 same-session case. `test_unknown_or_future_source_time_cannot_confirm`
now requires the exact bad input/timestamp and reason on consumption/inspection,
no forwarding, lost continuity, rejected confirmation even after the clock catches
up, rejection of old proof/cache repair, fresh recovery and immutable prior output.
The existing missing-snapshot/cache test gains explicit no-forwarding assertions.

The actual normalization -> canonical Quote round trip -> event decisions ->
recording test adds both defects and recovery after the earlier 35 decisions.
Written expectations are **43 decisions**, quote IDs q1/q2/q5/q10/q14/q18 and
trade-snapshot IDs q1/q3/q5/q10/q14/q18. The source-before-recovery record at
06:35:31 Pacific and source-after-availability record at 06:35:32 stay unusable;
inspection/confirmation at 06:35:33 cannot heal the latter. Fresh q17 at 06:35:34
needs matching proof; q18 at 06:35:35 can then forward. These are synthetic test
expectations, not observed passing output or evidence of provider coverage.

Required protected selection remains exactly §3's three selectors. Read-only
consumer search found no live caller or additional affected test outside them.
No protection change is required or permitted. The supervisor must provide two
successful protected runs with matching test IDs, zero failures/errors/skips,
no unexpected isolation denials, successful cleanup and byte-identical
`m23-quote-events-proof.json` files containing the expanded decisions. A fresh
builder must inspect those actual artifacts and source identity, finalize only
records/roadmap, and return completed for independent review.

Source compilation, Python 3.10 grammar, preservation and documentation checks
are recorded separately in M2_3_LOCAL_CHECKS.json. They cannot replace protected
execution. The post-repair launcher attempt and its exact result are recorded
below and in M2_3_LAUNCHER_LIMITATION.txt. Neither protection script is changed or
bypassed. The application and live checks are not run in this offline lane.

All new switches remain off and the sink remains recording. D-090, proposed
M0.3B rules and the D-091 $0 used/$0 reserved ledger remain unchanged. All other
unfinished roadmap rows and the live-branch reopening requirements remain intact.
No provider request, credential/live-database access, message, order, activation,
restart, deployment, purchase, account reset-credit use, billing fallback, Git
mutation, controller change or runtime-memory edit occurred.

The post-repair protected launcher stopped before either child at its ownership
step, with exit 1:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-dpt9v7y2'`

The artifact directory is empty. No tests, result XML, isolation report or
43-decision recording were produced by this attempt. The complete traceback is
saved in M2_3_LAUNCHER_LIMITATION.txt. Protected execution is the sole remaining
implementation-verification step. Return `ready_for_verification`; the supervisor
must run the unchanged launcher externally and return fresh proof for records-only
finalization. All earlier passing evidence remains historical.

Final local checks: both changed Python files compile and satisfy Python 3.10
grammar. All 85 local document links resolve; all eight playbook rows, 31 numbered
requirements and 22 additional capability rows remain present. The original
528-file milestone snapshot confirms the twelve-path delta in §5. Of 566 files
checked at this repair start, only those twelve changed; all other checked files
and local ownership/modes are preserved. Both protection scripts, the failing-test
list, configuration and approved/proposed packets are unchanged. A bounded read-only
source/test check found no further concrete issue and reconciled the 43 written
decisions; it is not execution proof or the supervisor's independent acceptance.


## 12. Second repair proof finalized — 2026-09-06 Pacific

Status: **completed** for the assigned offline implementation and evidence handoff.
The supervisor supplied the fresh protected results at **11:58:34 Pacific**.
This records-only session read the publication manifest, both XML test reports,
both isolation reports, output logs and both Quote recordings. All **23 published
file hashes** match, totaling **370,538 bytes**. The original publication remains
with the supervisor; its private location is not copied into public records.
[M2_3_LOCAL_CHECKS.json](./M2_3_LOCAL_CHECKS.json) saves the checked hashes, test
counts, source identity and all 43 decision summaries with Pacific times.

Both runs passed **490 tests** (980 executions), including **87 M2.3 cases**,
with zero failures, errors or skips and identical ordered test IDs. All three
selectors in §3 ran. The two named repair tests and the end-to-end recording case
passed in both processes, including the added same-session source-time case.
The six deliberate forbidden-access checks were denied as intended. There were
no unexpected isolation denials; all four cleanup checks passed and all four
database connections per run used temporary files. The unchanged launcher reports
two zero exits and $0 Databento use. This session did not rerun tests or import
the application; these are inspected supervisor results.

The synthetic raw response → M2.1 normalization → canonical Quote round trip →
M2.3 decisions → recording path produced byte-identical
`m23-quote-events-proof.json` files. Their SHA-256 is
`f11ddba2d05d678b765c8503b2f7e6749d0861fa0b3d7847e120ff2fb9557bf4`.
All **43 decisions** match. Quote observations forward only for
q1/q2/q5/q10/q14/q18; last-trade snapshots forward only for
q1/q3/q5/q10/q14/q18. The new failure/recovery sequence shows:

- At 06:35:31 Pacific, the same-session source time before recovery remains on
  q15. The record is unusable with SOURCE_BEFORE_RECOVERY, both forwarding flags
  are false, and confirmation is rejected.
- At 06:35:32, q16 retains its source time after original availability with
  INVALID_SOURCE_TIME. Inspection and confirmation at 06:35:33 keep that record
  unusable; waiting for the source timestamp cannot heal it.
- At 06:35:34, fresh q17 still needs matching recovery proof. Confirmation
  restores usability without forwarding an observation. q18 forwards at 06:35:35.

The supplied source identity matches the saved manifest, and all **776 file
contents** matched before any record edit. Both M2.3 Python files and both
protection scripts retain the exact tested hashes. Recoverable copies and local
ownership/mode checks are saved in M2_3_LOCAL_CHECKS.json. This session changes
only that file, this evidence record and ROADMAP.md. It preserves the whole
milestone's twelve-path list in §5, all prior owner work, the failing-test list,
configuration and both definition packets. Local ownership/modes are unchanged;
the sandbox's mapped ownership is not an independent host ownership check.

The pending-proof wording in PROJECT_INDEX §§21–22/30, SESSION_PROTOCOL
§§35–36/41/43, DATA_REQUIREMENTS §38, TESTING_AND_VALIDATION §58 and DECISIONS
§§29/37/39 records the second-repair handoff. This §12 and ROADMAP §31 supersede
that status. Those files and their contracts stay unchanged under this
records-only assignment. Sections 8–11 and the saved launcher errors remain
historical; the local launcher failure no longer blocks the offline handoff.

**M2.4 remains the proposed exact next milestone**, with the unchanged scope and
unchecked row in §6. Independent review must accept repaired M2.3 and that scope
before the controller advances. The required live M2.3 row in §7 remains [!].
All other unfinished/data/definition gates remain tracked, all switches stay off,
M0.3B remains proposed, and D-090/D-091 are unchanged at $0 used/$0 reserved.
No live/provider/credential/database access, message, order, restart, deployment,
purchase, Git mutation, controller edit or runtime-memory edit occurred.
These synthetic software checks do not establish provider coverage or profitability.
