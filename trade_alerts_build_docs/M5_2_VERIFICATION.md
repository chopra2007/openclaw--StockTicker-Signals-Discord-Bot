# M5.2 supplied-bar outcome evaluator

Date: 2026-09-09 Pacific. Status: **ready for verification — decimal fixture
repair written; protected proof pending**.
Section 19 is current. Sections 5–18 preserve earlier attempts, proof and repair.
The supervisor's separate reviewer decides acceptance and the independent handoff.

## 1. Assignment and boundary

The assigned M5.2 matches ROADMAP section 31 and the M5.1 section 7 handoff.
This bounded offline slice implements the adopted D-090 O-01
`BAR_ONLY_ORB5_O1_PROXY` from M0_3_DEFINITION_PACKET section 7. It evaluates
supplied complete regular-session one-minute Bars only. It does not fetch data,
create a strategy signal, estimate sub-minute quotes, add unapproved costs or
borrow terms, calculate expectancy, claim returns, send anything or activate a
switch.

All owner changes were preserved. No Git mutation, setup, controller, background
run, application run, live call, purchase, message, order, deployment or restart
occurred. D-091 remains $0 used and $0 reserved.

## 2. Implementation

`consensus_engine/outcome_evaluator.py` adds the pure
`evaluate_bar_outcome` calculation under policy
`BAR_ONLY_ORB5_O1_PROXY_V1`. It requires a valid actionable `CRVOL_ORB5`
candidate, its frozen stop and T1/optional T2, and supplied history covering the
alert date's full regular session through its calendar-aware close.

The calculation selects the next observed minute open strictly after the
supplied reference and within 60 seconds. It rejects known bad entry geometry
without moving the stop or targets. It uses two equal research units, T1 for the
first and T2 or the session close for the second. Each bar open is checked before
its range. Stop gaps use the open and favorable target gaps use the frozen target.
A stop after T1 closes only the remaining unit.

A stop/next-target bar is marked ambiguous, uses
`STOP_FIRST_CONSERVATIVE`, and records the required sensitivity as
`UNRESOLVED`. The result retains MFE, MAE, maximum R, stop and target facts and
times, unit exits and the resolved two-unit R result. Missing entry data remains
unresolved. Incomplete later coverage stays censored without invented non-hits
or a closing price.

`consensus_engine/event_store.py` now recognizes the existing canonical
`OutcomeRecord` as an append-only `OUTCOME` fact, linked to its candidate and
supplied inputs. Its existing optional option-result id remains inside the
canonical fact. No table or migration changed.

## 3. Written protected cases and offline proof

`tests/trade_alerts_contracts/test_outcome_evaluator.py` contains 49 collected
cases when its protection marker is present. They cover mirrored long/short,
T1 plus horizon, distinct T1/T2, same-bar stop/target, T1 then stop, stop and target gaps,
missing entry, missing later coverage, two known invalid entries, excursions and
hit times, exact and just-over 0.35 entry-extension boundaries in both directions,
rejected contracts, append-only storage/reopen linkage, and compact long/short
end-to-end recordings.

The recordings run the actual M4.5 candidate assembly, the new evaluator and
canonical serialization. The supervisor must compare
`m52-outcome-long-proof.json` and `m52-outcome-short-proof.json` from both runs.
Both must stay below 100,000 bytes and be byte-identical between runs. Inspect
the entry, fixed geometry, two exits, MFE/MAE/max R, hit times, ambiguity fields,
status reason, policy version and input ids. Synthetic Bars prove the
calculation, not actual source coverage or profit.

## 4. Required protected selection

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_outcome_evaluator.py`
- `tests/trade_alerts_contracts/test_research_event_store.py`
- `tests/trade_alerts_contracts/test_domain_models.py`
- `tests/trade_alerts_contracts/test_candidate_assembly.py`
- `tests/trade_alerts_contracts/test_historical_bars.py`
- `tests/test_models.py`
- `tests/test_migration_idempotency.py`
- `tests/test_market_layer_schema.py`
- `tests/test_batch2_trade_tracking.py::test_storage_retries_keep_stable_entity_ids_without_duplicate_facts`
- `tests/test_batch2_trade_tracking.py::test_batch2_fact_tables_reject_update_and_delete`

Require two clean protected runs, identical ordered test ids, zero failures,
errors or skips, no unexpected isolation denial, clean cleanup and matching
recordings.

## 5. Current verification

This section preserves the pre-proof local state as history. It was superseded
by the finalized protected proof in section 7.

Python compilation and whitespace checks passed. These are static checks, not
the required proof. The unchanged launcher was attempted and stopped before
collection at `os.chown` with `OSError: [Errno 22] Invalid argument`. The exact
output is in M5_2_LAUNCHER_LIMITATION.txt. No launcher/child change or direct
test workaround was used. M5_2_LOCAL_CHECKS.json saves the current hashes and
check results. A scoped ownership normalization attempt also returned
`Invalid argument` for every milestone path; no broader filesystem action was
taken.

Before the protected proof, status was `ready_for_verification`: protected test
execution was the only remaining gate for this bounded offline implementation.
After the supervisor returned the proof (section 7), the offline row is `[x]`,
while the separate required source/definition row stays `[!]`; M5.3 remains the
independent next milestone for reviewer approval. Section 7 supersedes this.

## 6. Required separate gates and saved next work

- [x] **M5.2 offline supplied-bar evaluator:** implementation and its written
  tests are complete; the fresh protected proof in section 7 passes for
  independent review. The earlier `[~]` pending row was historical pre-proof.
- [!] **M5.2 actual-source and executable-profit completion:** actual compatible
  point-in-time adjusted one-minute coverage, gaps/halts/corrections and the
  adopted remaining costs/borrow/statistical terms are not available in this
  offline lane. These gates remain with M0.2/M0.3/M5.2/M5.4/M16–M17. They are
  not needed to prove this supplied-input calculation and cannot be closed by
  synthetic Bars.
- [ ] **M5.3 historical replay:** proposed independent next milestone after the
  M5.2 offline proof and independent review. It must use chronological supplied
  data, the same runtime and isolated non-network storage/sink. It must not
  invent source coverage or implement unapproved trading rules.
- [!] M4.7 and every earlier saved source/definition gate remain required.

Saved proposed next_milestone: **M5.3**. The controller stays on M5.2 until
protected proof and independent review pass.

## 7. Protected proof finalized — 2026-09-08 Pacific

The readable supervisor proof returned at **02:22:16 Pacific** was inspected:
`summary.json`, both reports, `output.txt`, `pytest.log`, both `isolation.json`
records, `results.xml` from both runs and the long/short outcome recordings.
Both fresh protected runs passed **1,216 tests**, including all **15 M5.2
outcome-evaluator cases**, in 273.10 and 266.97 seconds. Ordered test IDs match
exactly (1,216/1,216); failures, errors and skips are zero. There are no
unexpected isolation denials and every cleanup check passed.

Every required section 4 selector is present in the run. The outcome recordings
are byte-identical across runs at **10,890/10,891 bytes** — both well under the
100,000-byte limit. They run the actual M4.5 candidate assembly, the new
evaluator and canonical serialization. The long recording shows direction LONG,
entry 2026-07-06T13:36:00+00:00, actual risk 1.0, resolved two-unit R, a
complete session-close horizon, unambiguous sensitivity NOT_APPLICABLE and all
supplied bar input ids retained. Short recording mirrors the same shape.
Code, tests, configuration and both protection files remain unchanged. No
application, live call, purchase, message, order or deployment occurred during
this records-only finalization. D-091 remains $0 used and $0 reserved.

The local ownership error in M5_2_LAUNCHER_LIMITATION.txt remains historical.
Successful protected proof completes the assigned offline supplied-bar outcome
scope for independent review. The separate required actual-source and
executable-profit gates below are not closed by synthetic Bars and stay `[!]`.

- [x] **M5.2 offline supplied-bar outcome evaluator:** implementation, protected
  proof and records-only finalization complete; independent review decides
  acceptance.
- [!] **M5.2 actual-source and executable-profit completion:** actual compatible
  point-in-time adjusted one-minute coverage, gaps/halts/corrections and the
  remaining adopted costs/borrow/statistical terms remain unavailable in this
  offline lane. They stay with M0.2/M0.3/M5.2/M5.4/M16–M17 and cannot be closed
  by synthetic Bars.
- [ ] **M5.3 historical replay:** proposed independent next milestone after the
  M5.2 proof and independent review, using chronological supplied data, the same
  runtime and isolated non-network storage/sink; no invented source coverage or
  unapproved trading rules.

Saved proposed next_milestone: **M5.3**. The controller stays on M5.2 until
independent review passes. All switches stay off. The offline proof is complete, but the required
source/definition gate remains open. The overall M5.2 handoff is blocked,
with independent next_milestone M5.3 subject to reviewer approval.


## 8. Records-only handoff repair and blocker — 2026-09-08 Pacific

The earlier overall completed status did not account for the required gate in
sections 6–7. It is corrected to **blocked**, without undoing the finished
offline [x] row or changing code, tests or protection. The supervisor's separate
review must validate the blocker and independent next milestone before advancing.

The fresh records check verified all **63 published file hashes**. Of **838
tested file contents**, 834 still match; the only four differences are the
previous records-only edits to M5_2_LOCAL_CHECKS.json, M5_2_VERIFICATION.md,
ROADMAP.md and TESTING_AND_VALIDATION.md. Every source, test, configuration
and protection file matches the tested manifest. Both XML reports contain
1,216 passing cases, including all 15 M5.2 cases and both Batch 2 storage
checks. Ordered IDs match; isolation and cleanup pass. The existing section 7
proof remains valid. No tests were rerun during this records-only repair.

The mirrored recordings retain 390 supplied input IDs each, entry at 06:36
Pacific, T1 at 06:38 and the remaining unit closed at 13:00 on July 6, 2026.
Entry is 100, risk per share is 1, favorable excursion is 2, adverse excursion
is approximately 0.1, and the two-unit result is 1R. Long exits are 102/100;
short exits are 98/100. These are synthetic calculation examples only.

**Exact remaining dependency:** M0.2/M5.2 must establish dated, per-symbol
one-minute source coverage and compatible price/share adjustments, original
availability, publication/finality, gaps, halts and corrections through the
required entry and session-close paths. M0.3/P-03 must adopt the remaining
spread/slippage/fee assumptions, dated short-borrow eligibility/cost treatment,
chronological splits, overlap handling and uncertainty terms before dependent
after-cost research under M5.4/M16–M17. M0.3B proposals are not adopted.

Reopen the source gate in separately authorized supervised work: inspect existing
local/Schwab/free records first, freeze a dated source manifest and coverage
report, then run those actual records through this same evaluator with explicit
missing and ambiguous outcomes. No specific required symbol/date corpus has yet
been frozen; M0.2 must record it before a source-coverage claim or purchase. Any
remaining purchase must name missing fields/dates/fidelity and a verified bounded
cost under D-091. No purchase is needed or made in this lane. Reopen the
definition gate only with a version-scoped owner decision and synchronized
canonical requirements; synthetic examples cannot close either gate.

- [x] **M5.2 offline supplied-bar evaluator:** implementation and protected proof
  complete for independent review.
- [!] **M5.2 required actual-source and executable-profit completion:** blocked
  by the source evidence and unadopted terms above.
- [ ] **M5.3 historical replay:** independent next work after reviewer approval,
  limited to a chronological supplied-record runner using the existing common
  strategy interface, state engine, fixed configuration, research store and
  recording sink. Prove deterministic repeated output, original availability
  and revisions, stable input/version attribution and network/credential/live-
  database isolation under the unchanged protected launcher. Use test-only
  strategy behavior; do not implement pending playbooks or infer actual history
  coverage. Full recovery stays M5.5; strategy-specific replay stays M6–M13.

M1–M5.1 already supply the common engineering prerequisites, so this bounded
M5.3 runner does not need missing cost/borrow definitions or actual provider
access. Preserve all earlier unfinished rows and all-off switches.
Saved next_milestone: **M5.3**. Overall status: **blocked**.


## 9. Outcome review repair — 2026-09-08 Pacific

Inspected the existing partial source/tests and the five review issues before
editing. Preserved all eight milestone paths from the supplied starting delta.
No owner work, protection, configuration or database migration was replaced.

The repaired evaluator processes every target reached at the open before
checking the bar range, then every range target when no stop competes. Thus an
open beyond T2 closes both units at frozen targets even if a later range touches
the stop. T1 at open followed by competing T2/stop remains ambiguous for only
the second unit. Long and short cases mirror these paths.

Entry open and original availability must both precede the approved scheduled
open + 45-minute boundary, capped by session close. At 07:15 Pacific entry is
unavailable. A 07:14 bar first available at 07:15 is also excluded. The separate
bar-proxy next-open search remains strictly after reference and within 60 seconds;
this does not introduce sub-minute quote fills or adopt M0.3B.

Evaluation walks scheduled coverage in order and stops assigning exits at the
first missing or unusable minute while units remain. Earlier exits survive;
later targets/stops cannot resolve exposed units. Certified no-trade intervals
remain distinct from gaps. Full-session observed excursions stay labeled with
partial coverage; they are not complete-path or profit evidence.

`BarOutcomeEvaluation.as_dict()` preserves entry time, actual and original risk,
each unit's exit price/reason/time, ambiguity and its unresolved sensitivity,
status reason, actual-entry resolved R, original-entry resolved R and the
complete canonical outcome under evaluation version M52_V1.
`ResearchEventStore.store_outcome()` writes that envelope and the canonical
outcome together in the existing transaction. Conflicting details fail without
partial writes; identical retries retain original rows. No table/guard change
is needed. Candidate and supplied-input links remain intact.

The test file has 43 written parameter-expanded cases (not a collected pass
count). Earlier assertions remain. Added cases cover both targets in one open
or range, competing stops, T1-open then ambiguous range, the entry boundary and
missing minutes before later targets/stops with zero or one earlier exit,
trailing certified no-trade minutes and original-risk return retention.
The two asynchronous end-to-end recording tests now run actual candidate
assembly, evaluation, atomic storage, database close/reopen, full row equality,
canonical/full-detail comparison and repeated-save equality for resolved,
ambiguous and partial cases in each direction. Compact recordings also include
both range targets, entry at 07:15 and a gap before targets. Inspect the actual
recordings after execution; written assertions are not passing evidence.
Immutable common synthetic Bars are reused to keep this expanded selection
within the unchanged launcher time bound. Storage fixtures save supplied history
as one existing transaction rather than one transaction per minute.

The unchanged protected launcher was attempted and stopped before collection:
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-9tobc8k9'`
at its initial `os.chown`. The exact traceback is appended to
M5_2_LAUNCHER_LIMITATION.txt. No direct legacy test or weaker workaround ran.
Python 3.10 grammar and in-memory compilation checks are recorded separately;
they cannot replace tests. Both protection hashes remain unchanged.

Require all section 4 selectors, two clean protected runs, matching ordered IDs,
no failures/errors/skips, clean isolation/cleanup and byte-identical long/short
recordings below 100,000 bytes. The supervisor returns fresh artifacts to a new
builder for records-only finalization. Section 7's 1,216-test proof and section
8's source-match claims are historical after this repair.

- [~] **M5.2 offline supplied-bar evaluator:** repair written; protected proof
  and independent acceptance pending. Return ready_for_verification for this
  repair while local protected execution is the remaining offline step.
- [!] **M5.2 required source/definition completion:** section 8's exact missing
  coverage/adjustment/gap/halt/correction evidence and unadopted cost, borrow and
  statistical terms remain required. Reopening remains separately supervised.
- [ ] **M5.3 historical replay:** proposed independent next work only after M5.2
  repaired proof and acceptance, bounded exactly by section 8. Do not advance now.

Saved proposed next_milestone: **M5.3**. After fresh offline proof, retain the
finished [x] row and the separate [!] gate and return blocked for that gate,
with independent M5.3 subject to reviewer validation. All earlier unfinished
work remains tracked. All switches stay off; no charged request, application
run, live call or profitability claim is added.


## 10. Repaired protected proof finalized — 2026-09-08 Pacific

The readable supervisor proof supplied at **13:55:36 Pacific** was inspected:
summary, publication hashes, both XML reports, output/logs, isolation reports and
both expanded outcome recordings. Both runs passed **1,244 tests**, including
all **43 M5.2 cases**, in **284.77 and 286.10 seconds**. Ordered test IDs match;
failures, errors and skips are zero. Both required Batch 2 storage checks and
every section 4 selector are covered by the directory and explicit selections.
Isolation reports contain no unexpected denials and all cleanup checks pass.
No tests were rerun during this records-only finalization.

The fresh repair changed `consensus_engine/outcome_evaluator.py` and
`tests/trade_alerts_contracts/test_outcome_evaluator.py`. Configuration and both
protection files remain unchanged. The supplied tested manifest records the
existing host ownership for the milestone paths. The local filesystem reports
different owner/group values for all eight paths, so this view cannot
independently confirm host ownership. This session used in-place record writes
and made no ownership change.
The earlier local ownership error remains historical. M5_2_LOCAL_CHECKS.json
saves the current proof, hashes and the earlier local checks separately.

Expanded long/short recordings are byte-identical across runs at **52,588/52,594
bytes**, below 100,000 bytes each. Both use actual candidate assembly, evaluation,
atomic storage and database close/reopen. All three complete-row comparisons per
direction pass, including canonical and full evaluation details and repeat saves.
The inspected synthetic examples show:

- Both targets reached at the open close at frozen T1/T2 prices: 102/103 long
  and 98/97 short, at 06:37 Pacific. The two-unit result is 2.5R despite a later
  stop touch in that minute. Both range targets also produce 2.5R.
- A competing stop and target remains AMBIGUOUS with conservative -1R and
  UNRESOLVED sensitivity. Storage retains both stop exits and the ambiguity.
- Missing coverage after T1 preserves that exit, leaves the second unit and
  total R unresolved, and retains PARTIAL/CENSORED status after reopen.
- Certified no-trade minutes at the session end no longer borrow an older close;
  the remaining unit stays unresolved and the stored record reopens as CENSORED.
- A gap before targets yields no exits and no resolved R. Entry at 07:15
  Pacific remains ENTRY_WINDOW_UNRESOLVED.
- The original horizon example retains entry 100 at 06:36, T1 at 06:38 and
  the remainder at 13:00 Pacific, with 390 supplied inputs, 1R actual-entry
  result and 1R original-entry result.

These are synthetic calculation and storage checks, not actual history coverage
or evidence of trading profit. Section 8's exact missing source and adopted-term
requirements, owners and separately supervised reopening tests remain unchanged.
No corpus or purchase is invented. M0.3B remains proposed; all switches stay off.
No application, live call, credential use, purchase, message, order or deployment
occurred. D-091 remains $0 used and $0 reserved.

- [x] **M5.2 offline supplied-bar evaluator:** repaired implementation, successful
  protected proof and records-only finalization complete for independent review.
- [!] **M5.2 required actual-source and executable-profit completion:** blocked
  by the source evidence and unadopted cost/borrow/statistical terms in section 8.
- [ ] **M5.3 historical replay:** independent supplied-record runner, bounded
  exactly by section 8, after reviewer validation of this handoff. The existing
  common runtime/configuration/store/sink prerequisites are available; actual
  source access and missing profit terms are not needed for that offline runner.

Saved next_milestone: **M5.3**. Overall status: **blocked**. The controller may
advance only after independent review validates this result and next work.
All earlier unfinished roadmap work remains required.

## 11. Original-risk proof repair — 2026-09-08 Pacific

The reviewer found that the saved example reported equal actual-entry and
original-entry R. That did not prove the two required figures are calculated
and stored separately when the modeled entry moves.

The evaluator already stores `resolved_r` and `original_resolved_r` separately
in the append-only evaluation record. The new mirrored long/short test moves the
modeled entry from 100 to 100.20 long and 99.80 short while keeping original
entry 100. It requires actual risk 1.20, original risk 1.00, actual-entry result
2/3R and original-entry result 1R. It saves the result, closes and reopens the
database, compares all rows, and checks both different figures in the stored
evaluation.

The existing mirrored trailing certified-no-trade tests still require no
session-close exit, no outcome price and unresolved remaining units after
database reopen. The evaluator requires an observed final bar ending exactly at
session close before it can use that close; complete scheduled coverage alone
is not enough.

Static Python compilation passed. The unchanged protected launcher was attempted
and stopped before collection at its initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-8ywjjki6'`.
The exact result is saved in M5_2_LAUNCHER_LIMITATION.txt. No direct test or
weaker workaround ran. The supervisor must return fresh artifacts for this
changed test state. Section 10's proof is historical after this test edit.

- [~] **M5.2 offline supplied-bar evaluator:** implementation and affected tests
  are ready; fresh protected proof and records-only finalization remain.
- [!] **M5.2 required source/definition completion:** the exact section 8 source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 12. Controller repair check — 2026-09-08 Pacific

The full section 4 selection was sent to the unchanged protected launcher at
21:45 Pacific. It stopped before collection at the initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-8ghnzwfx'`.
Exit code was 1. No artifact path was printed and no passing result is claimed.
The exact output is appended to M5_2_LAUNCHER_LIMITATION.txt.

The implementation and affected tests remain ready. Fresh protected supervisor
proof is the sole remaining offline step. M5.3 remains the proposed independent
next milestone after proof and review. The separate section 8 source/definition
gate remains `[!]`; no actual history or trading profit is established.

## 13. Invalid synthetic-bar repair — 2026-09-08 Pacific

The supervisor's two fresh runs collected 1,246 tests and reported 1,244 passes.
Both long and short forms of the new original-risk storage test failed before
evaluation because the synthetic entry bar had open 100.20 but high 100.10.
That is invalid OHLC geometry.

The test fixture now sets that bar's high to 100.20. The existing short mirror
turns the same supplied change into open/low 99.80, so both directions have valid
geometry while preserving the intended moved entry. Production code, storage,
configuration and both protection files are unchanged. Static Python compilation
passed for the affected test and M5.2 source files.

The full section 4 selection was sent to the unchanged launcher at 22:18 Pacific.
It stopped before collection at its initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-rcc14n69'`.
Exit code was 1 and no artifact path was printed. The exact output is appended to
M5_2_LAUNCHER_LIMITATION.txt. No direct test or weaker workaround ran.

- [~] **M5.2 offline supplied-bar evaluator:** the reported test fault is repaired;
  fresh protected proof and records-only finalization remain.
- [!] **M5.2 required source/definition completion:** section 8's actual source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 14. Exact 1.50R boundary repair — 2026-09-08 Pacific

The supervisor's fresh runs reached the repaired long/short storage test but
returned an unfilled result. The intended remaining room is exactly 1.50R:
long `(102 - 100.20) / (100.20 - 99)`, with the mirrored short equivalent.
Binary decimal rounding made that value slightly smaller than 1.50 in the
evaluator and incorrectly rejected the approved inclusive boundary.

`consensus_engine/outcome_evaluator.py` now uses exact decimal values for the
approved extension `<=0.35` and remaining-room `>=1.50` comparisons, matching
the established boundary method in `structural_risk.py`. The stored numeric
results remain ordinary numbers and the test expectations are unchanged.
Static Python compilation passed.

The full section 4 selection was sent to the unchanged protected launcher at
22:34 Pacific. It stopped before collection at its initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-cn5s9ora'`.
Exit code was 1 and no artifact path was printed. The exact result is appended
to M5_2_LAUNCHER_LIMITATION.txt. No direct test or weaker workaround ran.

- [~] **M5.2 offline supplied-bar evaluator:** the inclusive-boundary fault is
  repaired; fresh protected proof and records-only finalization remain.
- [!] **M5.2 required source/definition completion:** section 8's actual source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 15. 420-second launcher repair check — 2026-09-08 Pacific

The controller reported that one fresh protected run passed 1,246 tests, while
the second exceeded the old 300-second per-run limit. That incomplete pair does
not close the required two-run proof. The protected launcher now has the verified
420-second limit.

The full section 4 selection was sent to that protected launcher at 22:52
Pacific. It stopped before collection at its initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ectkvi_j'`.
Exit code was 1. No artifact path was printed and no passing result is claimed.
The launcher and child were not changed or bypassed in this session.

- [~] **M5.2 offline supplied-bar evaluator:** the code and affected tests are
  ready; two fresh protected runs with the 420-second limit remain the sole
  offline verification step.
- [!] **M5.2 required source/definition completion:** section 8's actual source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 16. Fresh 420-second protected proof finalized — 2026-09-08 Pacific

The readable supervisor proof supplied at **23:06:53 Pacific** was inspected:
summary, all **63 published hashes**, both XML reports, output/logs, isolation
reports and both expanded outcome recordings.

Both protected runs passed **1,246 tests**, including all **45 M5.2 cases** and
both required Batch 2 storage checks, in **306.46 and 305.01 seconds** within
the verified 420-second limit. Ordered test IDs are identical across runs;
failures, errors and skips are zero. Isolation reports contain no unexpected
denials and all cleanup checks pass. D-091 remains $0 used and $0 reserved;
Databento credit used is 0. No test was rerun during this records-only
finalization.

All 63 published hashes matched their files. Expanded long/short recordings are
byte-identical across runs at **52,588/52,594 bytes**, below 100,000 bytes each,
matching the exact-boundary repair state. The inspected synthetic examples show
the approved inclusive 1.50R remaining-room boundary filling at 2.5R with both
targets, the competing stop/target ambiguity kept conservative at -1R with
UNRESOLVED sensitivity, missing coverage preserving the first exit while the
second unit and total R stay unresolved, and the trailing no-trade minutes
keeping the remaining unit unresolved as CENSORED after reopen. These are
synthetic calculation and storage checks, not actual history coverage or trading
profit.

`consensus_engine/outcome_evaluator.py` uses exact decimal values for the
approved `<=0.35` extension and `>=1.50` remaining-room comparisons; the stored
numeric results remain ordinary numbers. `consensus_engine/event_store.py` still
recognizes the canonical `OutcomeRecord` as an append-only `OUTCOME` fact. No
table, migration, configuration, switch or protection file changed. No live
call, application run, purchase or message occurred.

- [x] **M5.2 offline supplied-bar evaluator:** repaired implementation, successful
  fresh protected proof and records-only finalization complete for independent
  review.
- [!] **M5.2 required actual-source and executable-profit completion:** blocked
  by the source evidence and unadopted cost/borrow/statistical terms in section 8.
- [ ] **M5.3 historical replay:** independent supplied-record runner, bounded
  exactly by section 8, after reviewer validation. It needs no actual source
  access or missing profit terms; the common runtime/configuration/store/sink
  prerequisites are already present. Full recovery stays M5.5.

Saved next_milestone: **M5.3**. Overall status: **blocked** for the required
source/definition gate. The controller advances only after independent review
validates this result and next work. All earlier unfinished roadmap rows remain
required. All switches stay off; no live access, purchase, new trading rule or
profitability claim is added.

## 17. Exact 0.35 extension repair — 2026-09-08 Pacific

The reviewer found that the exact extension was compared with the binary float
`0.35`. That made the approved inclusive 0.35 boundary fail. The evaluator now
compares it with `Fraction("0.35")`, matching the exact 1.50R comparison. Four
protected cases cover the exact boundary and a value just above it for long and
short candidates. Section 3 now records the current 49 collected M5.2 cases.

- [~] **M5.2 offline supplied-bar evaluator:** the reviewer-required code, tests
  and written evidence are repaired; fresh protected proof is the only remaining
  offline step.
- [!] **M5.2 required source/definition completion:** section 8's actual source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 18. Exact-boundary fixture repair — 2026-09-09 Pacific

The supervisor found that all four section 17 cases failed before evaluation.
Their changed frozen target price kept the old target R multiple, so the
canonical candidate correctly rejected the inconsistent geometry. The test
helper now changes the target price and its matching R multiple together. This
keeps a valid frozen candidate while isolating the approved inclusive 0.35
entry-extension check. Production code is unchanged by this repair.

Python compilation, JSON syntax and scoped whitespace checks passed. The full
section 4 selection was sent to the unchanged protected launcher. It stopped
before collection at its initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-rs_oasqu'`.
The exact output is appended to M5_2_LAUNCHER_LIMITATION.txt. No direct test or
weaker workaround ran.

- [~] **M5.2 offline supplied-bar evaluator:** the reported fixture fault is
  repaired; fresh protected proof is the sole remaining offline step.
- [!] **M5.2 required source/definition completion:** section 8's actual source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 19. Decimal target fixture repair — 2026-09-09 Pacific

The supervisor's fresh protected runs collected 1,250 tests and reported 1,248
passes. The exact 0.35 long and short cases still returned `UNFILLED`. Their
target prices were calculated with binary decimal math, producing a value just
inside the required 1.50R remaining-room boundary before the evaluator reached
the intended 0.35 check.

The four-case fixture now calculates the entry, risk and target with exact
decimal values before converting the final supplied prices to ordinary numbers.
The helper still updates the target price and matching target R multiple. This
keeps the candidate valid and makes the test isolate the exact 0.35 boundary.
Production code is unchanged by this repair.

Python compilation, JSON syntax and scoped whitespace checks passed. The full
section 4 selection was sent to the unchanged protected launcher. It stopped
before collection at its initial `os.chown` call with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-grko4uin'`.
The exact output is appended to M5_2_LAUNCHER_LIMITATION.txt. No direct test or
weaker workaround ran.

- [~] **M5.2 offline supplied-bar evaluator:** the reported decimal fixture fault
  is repaired; fresh protected proof is the sole remaining offline step.
- [!] **M5.2 required source/definition completion:** section 8's actual source,
  adjustment, gap, halt, correction, cost, borrow and statistical gates remain.
- [ ] **M5.3 historical replay:** proposed independent next work after fresh M5.2
  proof and review, bounded by section 8.

Saved proposed next_milestone: **M5.3**. Current status:
**ready_for_verification**. All switches remain off.

## 20. Decimal fixture protected proof finalized — 2026-09-09 Pacific

The supervisor returned fresh proof for the section 19 fixture repair at
00:32:11 Pacific. Both protected runs passed **1,250 tests**, including all
**49 M5.2 cases** and both required Batch 2 storage checks, in **304.67 and
306.15 seconds**. Ordered test IDs match. Failures, errors and skips are zero.
Isolation and cleanup passed with no unexpected denials.

The long and short outcome recordings are byte-identical across runs at
**52,588 and 52,594 bytes**. The tested evaluator and fixture hashes match the
current files. The protected launcher and child hashes also match the supplied
manifest. `M5_2_SUPERVISOR_TESTS.json` saves the checked results and hashes.

- [x] **M5.2 offline supplied-bar evaluator:** repaired implementation, all 49
  cases, protected proof and records-only finalization are complete for
  independent review.
- [!] **M5.2 required actual-source and executable-profit completion:** section
  8's actual source, adjustment, gap, halt, correction, cost, borrow and
  statistical gates remain blocked. Synthetic bars cannot close them.
- [ ] **M5.3 historical replay:** independent supplied-record runner, bounded by
  section 8, after reviewer validation.

Saved next_milestone: **M5.3**. Overall status: **blocked** for the separate
required source/definition gate. All switches remain off. No live access,
purchase, new trading rule or profitability claim is added.
