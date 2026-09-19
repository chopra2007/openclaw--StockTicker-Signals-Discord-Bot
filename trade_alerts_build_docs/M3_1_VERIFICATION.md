# M3.1 fifth repair proof finalized; required source gate blocked

Date: 2026-09-06 Pacific. Status: **blocked** by the separate required source gate.
The fifth review repair is implemented with 54 protected cases and an updated
compact recording. Two fresh protected runs passed 591 tests each, including all
54 M3.1 cases, with matching IDs, recordings, isolation and cleanup. Section 16
records that proof. Section 14's two 587-test/50-case runs are historical. The
offline row is `[x]`; the separate required source row stays `[!]`. Saved proposed
next milestone: **M3.2**, after independent review confirms its independence.
This evidence does not establish source coverage or profitability.

## 1. Completed offline implementation

`consensus_engine/core_price_features.py` implements only the approved D-090 core
price calculations. It consumes supplied canonical history, scheduled coverage and
an explicitly identified opening trade. It adds no client, database, switch,
background task or live consumer.

Outputs are fixed-window minute and daily ATR, bar HLC3 session VWAP, current and
prior session extrema, premarket extrema, identified session open and gap. Existing
Wilder ATR callers are unchanged. Trade VWAP is not replaced by bar VWAP.

Scheduled slots are selected before completeness checks. Malformed records block
only required overlapping slots, including any needed preceding close reference.
Unrelated older/prior-session records cannot erase a complete window.
Missing, late, provisional,
conflicting, invalid-revision or incompatible input blocks its feature. Certified
no-trade minutes add zero without an invented price. Daily ATR needs the exact 15
prior sessions. Holidays and shortened sessions use the shared calendar.

Session open requires a separate `OpeningTradeObservation` whose symbol, source,
session, availability, adjustment and price basis agree with the supplied history.
It does not require daily history or a prior close. Gap additionally needs a usable
positive prior close. A bar open or polling last price cannot fill the opening
observation.

The review repair adds three required boundaries. The first traded minute after
certified no-trade opening minutes uses high minus low. A trade/source time after
its availability or evaluation cannot supply the open. An older missing daily
session blocks daily ATR without erasing the complete prior session or a valid
opening observation.

## 2. Protected proof contract

Run twice through `scripts/testing/run_trade_alerts_contracts.py`:

- `tests/trade_alerts_contracts`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/trade_alerts_contracts/test_core_price_features.py`

Both fresh protected runs must have zero failures, errors and skips; identical
ordered test IDs; all **54 M3.1 cases**; no unexpected isolation denials; successful
cleanup; and byte-identical `m31-core-price-features-proof.json`. That recording
must use the compact summary format: visible feature values, missing reasons,
input/interval counts and SHA-256 hashes of each complete canonical object. It must
not publish the repeated full minute and premarket histories, and the test requires
the rendered file to stay below 100,000 bytes. The directory
selection includes the earlier compatibility contracts; the M3.1 file also checks
legacy Wilder ATR and weighted-price arithmetic. No protection change is needed.

## 3. Earlier local evidence — historical

Both new Python files compiled after the repair. Searches found no network,
credential or non-Pacific display-time code. The protected attempt ended before
collection with the exact trace in M3_1_LAUNCHER_LIMITATION.txt. No repair test pass
or failure is claimed. M3_1_LOCAL_CHECKS.json preserves the historical proof and the
fresh verification requirement.

## 4. Whole milestone paths

- `consensus_engine/core_price_features.py`
- `tests/trade_alerts_contracts/test_core_price_features.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/M3_1_VERIFICATION.md`
- `trade_alerts_build_docs/M3_1_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M3_1_LAUNCHER_LIMITATION.txt`

## 5. Proposed independent next milestone

- [ ] **M3.2:** D-090 supplied-record RVOL and participation calculations, after
  independent M3.1 review. It must retain exact 20-session windows, positive
  denominators, complete coverage and separate named modes.

The ready independent slice is `RVOL_OPEN5_MEAN20_V1`, `PM_RVOL_MEAN20_V1` and
`DOLLAR_VOLUME_CLOSE_PROXY20_V1`, from D-090 F-02 using supplied M2.2 Bar histories.
It needs no live stream, complete trade VWAP or identified opening trade. Require
exact reference sessions/windows, available-time finality, matching share/venue/
adjustment basis, a positive denominator and explicit missingness. Do not skip a
missing reference, substitute final current-day volume or pool full/estimated modes.
Hand-computed boundary/zero/missing/revision cases and Bar -> coverage -> immutable
feature -> identical protected recording proof are required. Same-time/cumulative
RVOL, tape intensity, projected-minute coverage and actual source evidence remain
tracked M3.2 obligations under their own definition/data gates; the bounded slice
cannot silently complete them or adopt M0.3B. No M3.2 code is added in this repair.

Saved `next_milestone`: **M3.2**. Section 16 finalizes the fifth repair's successful
protected proof. The offline row is `[x]`; return **blocked** because §6 remains
required. The reviewer must accept this evidence and confirm M3.2's independence
from that source gate before the controller advances. No M3.2 work starts here,
and full M3.1 is not complete.

## 6. Required full-data blocker and reopening proof

- [!] **M3.1 full-data/source completion:** full `SESSION_VWAP_TRADES_V1` remains
  blocked until complete eligible-trade coverage and frozen trade-condition,
  duplicate, cancel and correction treatment exist. Actual source evidence must also
  identify the first regular-session trade and prove compatible daily, minute and
  premarket coverage, finality, revisions, adjustments and availability.

Reopen only in a separately authorized supervised step. Inspect existing raw/local
and free-source records first. Save dated source fields, correction rules, interval
coverage, original availability, adjustments and identified opening observation.
Missing evidence keeps the dependent feature UNKNOWN. Synthetic records do not prove
coverage. No purchase is needed here; D-091 remains $0 used and $0 reserved.

## 7. Earlier supervisor proof — historical after review repair

The supervisor supplied protected results at **13:49:53 Pacific**. This records-only
session inspected the publication manifest, both XML reports, both isolation
reports, both output logs and both M3.1 recordings. The implementation and test
hashes matched that supervisor manifest at the time. The review repair changed both
files afterward; the protection files remain unchanged.

Both runs passed **549 tests** (1,098 executions), including **12 M3.1 cases**, with
zero failures, errors or skips and identical ordered test IDs. All four selectors
in §2 ran. Both isolation reports show no unexpected denials and successful database,
HTTP, configuration and lock cleanup. The two 504,899-byte
`m31-core-price-features-proof.json` files are byte-identical with SHA-256
`318198ce0e15587039a4896be3f4ab71303a071e5b21a1fb7e741b24be5d0478`.
No Databento credit was used.

These results established the pre-repair state only. They do not cover the four new
cases in §8 and no longer complete the bounded offline row. Section 6 remains blocked
and explicitly retained.

## 8. First review repair supervisor proof — historical after second repair

The repair preserves the existing implementation and adds only the reviewer-required
boundaries:

- a first traded minute after one or more certified no-trade opening minutes uses
  its own high minus low while those earlier minutes add zero;
- opening trade/source time cannot follow original availability or evaluation;
- daily ATR still needs all 15 sessions, while prior high, low, close, session open
  and gap depend only on the complete immediately prior session and valid opening
  observation.

Four protected cases cover those boundaries, bringing the M3.1 selection to 16
cases. The end-to-end recording also includes the repaired no-trade, daily-window
and evaluation-time snapshots.

The supervisor supplied fresh protected results at **14:13:26 Pacific**. Both runs
passed **553 tests** (1,106 executions), including all **16 M3.1 cases**, with zero
failures, errors or skips and identical ordered test IDs. Both isolation reports
show no unexpected denials and successful database, HTTP, configuration and lock
cleanup. The two 579,059-byte `m31-core-price-features-proof.json` files are
byte-identical with SHA-256
`b7f5b496906fcb7b06c21ddd1cbb76845a41971066c7585e2e59e3d09321ff79`.
The tested source and test hashes match M3_1_LOCAL_CHECKS.json. The protection files
remain unchanged. No Databento credit was used.

At that handoff the bounded offline row was `[x]` for independent review. The
second review found the issues in §9 and reopened that row. The proposed next
milestone remains **M3.2** after fresh verification and review. The required full-data/source row
remains `[!]` regardless of offline proof. The launcher error in
M3_1_LAUNCHER_LIMITATION.txt is retained as historical local evidence only.

## 9. Second review repair and fresh verification requirement

The assigned M3.1 repair was checked against ROADMAP §31. All nine canonical files,
PREBUILD_REVIEW, D-090's unchanged packet, M2_4_VERIFICATION, the existing M3.1
code/tests/evidence, PROJECT_RULES and WORKFLOWS were read. The existing partial
work was repaired in place. Recoverable copies of 227 source/test/config/document
files and their hashes/modes/ownership were saved before edits; the local backup
reference is in M3_1_LOCAL_CHECKS.json. Existing unrelated changes and the empty
failing-test list were preserved. The full nine-path list in §4 includes all eight
paths from previous M3.1 attempts plus this repair's PROJECT_INDEX update.

The reported boundaries are repaired:

- A valid identified session open survives absent daily history or a missing,
  invalid or no-trade prior daily bar. Only GAP_OPEN_V1 needs a usable prior close.
  Opening symbol/source/basis/session/time checks remain enforced.
- Unexpected records are checked for overlap with each selected feature window.
  An older malformed minute or daily record cannot erase a complete selected result.
  A prior-session malformed minute cannot erase current-session VWAP/HOD/LOD.
  Overlap with a selected interval or needed earlier close remains blocking. Missing
  close-reference slots cannot be skipped to borrow an older price.
- Direct cases now cover zero session volume, complete no-trade windows, nineteen
  supplied minute slots and fourteen daily sessions, and unchanged legacy arithmetic.
- Shortened-session proof uses actual synthetic Bars through coverage and snapshots.
  On 2026-11-27 there are 210 scheduled minutes, ending at 10:00 Pacific. With the
  last minute first available at 10:00:02, the expected VWAP sequence at 09:59:59,
  10:00:00 and 10:00:02 is 100, UNKNOWN, 100. The completed values are ATR 2, HOD 101
  and LOD 99. A shortened daily Bar supplies the next session's prior levels and
  14-day ATR of 2.1. These numbers are written synthetic expectations, not observed
  second-repair test output.

The end-to-end case writes the existing recording filename with the added
open-without-close/history, out-of-window coverage/snapshot pairs, shortened
minute/daily coverage/snapshots, zero-volume and short-history results. Assertions
check values, missingness, unchanged selected outputs and canonical round trips.
The supervisor must inspect both new recordings, not reuse an old hash or count.

Local compilation and Python 3.10 grammar checks passed for both Python files.
The unchanged protected launcher was attempted with every selector in §2. It
stopped at its initial ownership step before either child or test collection:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ci5g_qn0'`

The exact traceback is appended to M3_1_LAUNCHER_LIMITATION.txt. No test was run
outside the protection; neither protection script was changed or bypassed. The
supervisor must execute it externally and return actual artifacts to a fresh
builder. That builder must check the final source/test hashes, both full test
selections, zero failures/errors/skips, matching test IDs and recordings, no
unexpected isolation denials and successful cleanup, then finalize records only.

The supplied older XML reports and recording files were read again: they contain
553 passing cases and 16 M3.1 cases in each run, with §8's matching recording hash.
Those artifacts predate this repair. M3_1_LOCAL_CHECKS.json preserves their
historical attribution and resets current verification to pending. Canonical
status is synchronized in PROJECT_INDEX §31, TESTING_AND_VALIDATION §60 and
ROADMAP §31; old M2.3/M2.4 handoff notes are historical.

The controller later returned that same 553-case publication for this 32-case
repair. Its 579,059-byte M3.1 recording contains repeated complete histories and
was rejected as too large or unsafe for review. Its source/test hashes also predate
the second repair, so it cannot finalize M3.1. The recording test now keeps its
full calculations, assertions and canonical round trips, but publishes a compact
review record. Each summarized coverage or snapshot includes its complete canonical
JSON byte count and SHA-256 hash; coverage counts and feature values remain readable.
No production calculation changed. The protected launcher and child are unchanged.
Two fresh protected runs are still the only missing offline verification step.
The compact-recording launcher attempt stopped at the same ownership step with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-vsuneqri'`.
The exact trace is appended to M3_1_LAUNCHER_LIMITATION.txt.

- [~] **M3.1 offline core price features:** repaired code/tests and records ready;
  only fresh protected execution and records-only finalization remain for this row.
- [!] **M3.1 full-data/source completion:** §6 remains required and unproven.
- [ ] **M3.2:** proposed independent next milestone under §5, subject to review.

All switches remain off. No application execution, provider call, credential read,
message, order, purchase, restart, deployment, Git mutation, controller edit or
runtime-memory edit occurred. D-091 remains $0 used and $0 reserved. Synthetic
engineering checks cannot close the source gate or establish profitability.

## 10. Compact-recording supervisor proof — historical

The supervisor supplied fresh protected results at **15:07:09 Pacific**. This
records-only session inspected the publication summary, both XML reports, both
isolation reports, both output files, both compact M3.1 recordings and the verified
source manifest. The current source and test hashes match the tested manifest:
`c93270b0d888604bc2ee9c6ebe091a58fdc7a35cf1919c3c3a2a6d3f727b5518`
and `e6d4cb0c37eec0c51dd05c534384d8c0bc17f91e4ababb3592514bc54e6b9a92`.
Code, tests and protection were not changed in this finalization.

Both runs passed **569 tests** (1,138 executions), including all **32 M3.1 cases**,
with zero failures, errors or skips and identical ordered test IDs. Both isolation
reports show no unexpected denials and successful database, HTTP, configuration
and lock cleanup. The two 32,072-byte `m31-core-price-features-proof.json` files are
byte-identical with SHA-256
`521f642677824ad7f4500a640e63931bb6579385c98c5f40a5881623720e79c2`.
The protected launcher and child hashes remain unchanged. No Databento credit was
used.

- [x] **M3.1 offline core price features:** implementation, compatibility cases,
  end-to-end compact recording and fresh protected proof are complete.
- [!] **M3.1 full-data/source completion:** §6 remains required and blocked.
- [ ] **M3.2:** proposed independent next milestone under §5, subject to review.

Status: **blocked** because the required real-source branch is not available in this
offline lane. Saved `next_milestone`: **M3.2**. The reviewer must confirm that M3.2
is independent of the blocked source branch before the controller advances.

## 11. Third review repair — protected execution pending

The 569-test proof in §10 predates this repair and is historical. The latest review
found that arbitrary known price, volume and venue-basis labels could produce
features labeled `USD_PER_SHARE`, and that an opening record could use a non-finite
price or an incompatible instrument type.

The repair keeps the existing calculations and adds only these boundaries:

- price-producing history must use `USD_PER_SHARE`;
- bar VWAP additionally requires `SHARES`, while wrong volume units do not erase
  ATR or price extrema that do not use volume;
- each feature checks only its needed history, while gap also requires the daily
  close and opening observation to share one source, adjustment and venue basis;
- opening trades require a finite positive price, EQUITY/ETF identity, and an
  instrument type matching the supplied history; OPTION and mismatched records
  cannot supply session open or gap.

Eight added protected cases cover NaN and both infinities, OPTION identity,
EQUITY/ETF mismatch, cents-per-share history, non-share volume, unknown venue basis
and a daily/opening venue mismatch. The end-to-end compact recording now includes
the repaired feature results and constructor rejections. There are **40 written
M3.1 cases**.

Both changed Python files pass local compilation and Python 3.10 grammar parsing.
The unchanged protected launcher was run with every selector in §2. It stopped at
its first ownership operation before either child or test collection:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ruhx8u_r'`

The exact traceback is appended to M3_1_LAUNCHER_LIMITATION.txt. No test was run
outside the protection, and neither protection file changed. The supervisor must
run the selection twice and return fresh artifacts. A new builder must match the
current source/test hashes, inspect both XML/isolation reports and compact records,
then update records only.

- [~] **M3.1 offline core price features:** implementation, compatibility cases and
  end-to-end recording are ready; fresh protected execution is the only open step.
- [!] **M3.1 full-data/source completion:** §6 remains required and blocked.
- [ ] **M3.2:** proposed independent next milestone under §5 after proof/review.

All switches remain off. No application, provider, credential, message, order,
purchase, restart, deployment or Git action occurred. D-091 remains $0 used and
$0 reserved. No profitability claim is made.

## 12. Unit/instrument repair proof — historical after fourth repair

The supervisor supplied fresh protected results at **15:37:54 Pacific**. This
records-only session inspected the publication summary, verified source manifest,
both XML reports, both isolation reports, both output files and both compact M3.1
recordings. At that finalization the tested source and test hashes matched the files:
`9c3223a78b36ec7652b1367b155de344e606efb7e48499e310443aa597d11bf1`
and `7fbd3ebf6a38f39192a98c740d86b54a740526ea6ab0cd00fb1d8b3fd0bc1b92`.
Code, tests and protection were not changed in this finalization.

Both runs passed **577 tests** (1,154 executions), including all **40 M3.1 cases**,
with zero failures, errors or skips and identical ordered test IDs. Both isolation
reports show no unexpected denials and successful database, HTTP, configuration
and lock cleanup. The two 41,712-byte compact recordings are byte-identical with
SHA-256 `5b3a9ebf39f9f81e989af9880b9914c699c19cceba5fdc2a8bab19220ade1ee1`.
The protected launcher and child hashes still match the saved repair record. No
Databento credit was used.

- [~] **M3.1 offline core price features:** reopened by the fourth review. The
  577-test proof above remains historical; §13 requires two fresh passes.
- [!] **M3.1 full-data/source completion:** §6 remains required and blocked.
- [ ] **M3.2:** proposed independent next milestone under §5, subject to review.

Status: **blocked** because the required real-data/source branch is unavailable in
this offline lane. Saved `next_milestone`: **M3.2**. The reviewer must confirm that
M3.2 is independent of the blocked source branch before the controller advances.


## 13. Fourth review repair — historical handoff, proof finalized in §14

The assigned repair was checked against ROADMAP §31 after reading all nine
canonical files, PREBUILD_REVIEW, the D-090 packet, M2.4/M3.1 evidence, PROJECT_RULES
and WORKFLOWS. Existing partial work was inspected and repaired in place. Before
editing, 62 relevant source/test/document/configuration files were copied with
hashes, ownership and modes to the recoverable local backup named in
M3_1_LOCAL_CHECKS.json. No owner work was restored from Git or discarded.

The two reviewer findings were confirmed in the existing source. Instrument checks
read every raw bar, including future revisions, and snapshot metadata read the first
raw bar. All three now reuse M2.2's selected available-time coverage. A future ETF
revision cannot change an earlier EQUITY feature, opening value, gap or snapshot
identity, whether it is first or last in the raw input. At exact availability, a
mixed identity blocks dependent features. A later compatible revision supersedes
that older identity. An empty available view keeps UNKNOWN identity even when raw
future records exist.

Premarket selection now uses the shared calendar's current-day 01:00 Pacific
boundary and scheduled regular open. A request beginning at 01:01 can be complete
for its own 329 minutes but cannot supply complete PMH/PML. A two-session request
with 660 covered minutes can supply the current 330-minute window. Older synthetic
extrema of 150/50 do not change the current 101.3/98.7 levels or their input IDs.
These numbers are written test expectations, not observed passing repair output.

Ten added cases cover three histories with each future revision at the start and
end of the raw input (six cases), future-only identity, superseded identity, a
truncated premarket request and a complete multi-session request. The unchanged
previous 40 cases remain. The Bar -> coverage -> FeatureSnapshot -> compact
recording case now includes before/at-availability identity results and both
premarket boundaries. It checks complete snapshot equality, missing reasons,
canonical round trips and the existing under-100,000-byte recording limit.
Snapshot summaries now include instrument type so the repaired identity is readable.

Completion for this offline repair requires all **50 M3.1 cases** plus every §2
compatibility selector to pass in each of two fresh protected children. Compare
ordered test IDs and compact recordings; inspect both isolation and cleanup reports.
A read-only caller lookup found no live consumer of the M3.1 public functions;
the contract test is their only Python caller. Both changed Python files pass local
compilation and Python 3.10 grammar checks. No configured lint/type-check task was
found. These checks cannot establish a passing test or provider coverage.

- [~] **M3.1 offline core price features:** repair and recording assertions ready;
  fresh protected execution and records-only finalization remain.
- [!] **M3.1 full-data/source completion:** §6's exact data and supervised-access
  dependencies remain required. No supplied synthetic input closes them.
- [ ] **M3.2:** proposed independent next milestone under §5 after proof/review.

Saved `next_milestone`: **M3.2**. The controller must finish this repair's verification
first. A fresh builder receiving successful supervisor artifacts must match the
source/test hashes and finalize records without editing code or tests. Then restore
the offline `[x]` row and return blocked with the separately retained §6 source gate
and M3.2 handoff. The independent reviewer must validate that handoff.

All switches remain off. No application, live request, credential read, message,
order, purchase, restart, deployment, Git mutation, controller edit or runtime-memory
edit is authorized or needed. D-091 remains $0 used and $0 reserved. Engineering
completion is not evidence of profitability.

The unchanged protected launcher was attempted with all five §2 selectors. It
returned exit 1 before either child or collection, at its initial ownership step:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-byq2d5wg'`

The exact traceback is appended to M3_1_LAUNCHER_LIMITATION.txt. This attempt
produced no test or end-to-end result. Neither protection file was changed, and
no test was run outside it. Status: **ready_for_verification**, under the owner's
specific handoff for sandbox-blocked execution. Protected execution is the only
remaining offline step. The separately required §6 data gate remains `[!]`; after
successful offline proof, use the blocked-source handoff described above.

Final local checks found 61 valid document links, balanced code fences, all nine
canonical files, all eight strategy IDs and all 31 functional-requirement rows.
All 13 new switches remain off with the recording sink. Comparing the 62 saved
files found exactly the nine milestone paths in §4 changed, with no local ownership
or mode change. Protected launcher/child, owner rules, the failing-test list,
configuration, approved packet and existing indicator helpers retain their saved
contents. Read-only Git checks reported `Permission denied` for unrelated saved
workflow paths; direct comparisons covered every changed file. No repair tests
ran, and the old 577-test/40-case artifacts were retained as historical evidence.

## 14. Fourth repair proof finalized and required blocker retained

The supervisor supplied fresh protected results at **16:10:11 Pacific on
2026-09-06**. This records-only session inspected the publication manifest,
verified source manifest, both XML reports, both isolation reports, output logs
and both compact M3.1 recordings. All **27 published file hashes** match, totaling
**772,278 bytes**. The original publication remains with the supervisor; its
private location is not copied into public records. M3_1_LOCAL_CHECKS.json saves
the checked artifact hashes, source identity, counts and readable repair results.

Both runs passed **587 tests** (1,174 executions), including all **50 M3.1 cases**,
with zero failures, errors or skips and identical ordered test IDs. All five §2
selectors ran. This includes all six future-instrument revision placements, the
future-only and superseded-identity cases, both premarket request boundaries,
the legacy arithmetic case and the end-to-end recording case. Earlier contracts
and the existing model, Schwab client and stock-sector caller tests remain passing.
The six deliberate forbidden-access checks were denied as intended. No unexpected
isolation denial occurred; all four cleanup checks passed and every database
connection used a temporary file. Test totals come from XML and output.txt;
pytest.log contains the expected fake delivery-failure logs from negative cases.
No tests or application code were run again during this finalization.

The actual synthetic Bar -> available-time coverage -> FeatureSnapshot -> compact
recording path produced two byte-identical **60,249-byte** files. Their SHA-256 is
`06ae7c6697ff498fda2c27eb0ee43c95a97db9034f072a11954127fa3753f261`.
The records retain readable values, missing reasons, counts, instrument types and
hashes of complete canonical objects, below the required 100,000-byte limit.
The observed repair results are:

- Before each future instrument revision is available, the entire snapshot hash
  equals the original EQUITY snapshot. At 06:32:01 Pacific, the mixed minute,
  daily or premarket identity blocks its dependent open, gap or premarket feature
  with `INCOMPATIBLE_INSTRUMENT_TYPE`.
- A request beginning at 01:01 Pacific covers its own 329 minutes, but PMH/PML
  stay unavailable with `INCOMPLETE_PREMARKET_WINDOW`. Request completeness alone
  does not prove the required 01:00-to-open window.
- The complete two-session request covers 660 minutes. Its premarket levels use
  exactly the current 330-minute window: PMH **101.3**, PML **98.7**. The snapshot
  hash equals the original; the older 150/50 extrema do not enter it.
- Earlier repaired paths remain present: an identified open of **102** survives
  missing daily history while gap stays unavailable. The shortened session's
  VWAP is **100**, unavailable, then **100** at 09:59:59, 10:00:00 and 10:00:02
  Pacific as the last bar becomes final and available.

The configuration fixture and M1.3/M2.1/M2.2/M2.3/M2.4 recordings also match
between these two processes. This closes only M3.1's offline calculation,
availability and compatibility proof. It does not establish actual trade data,
full replay, live inputs, delivery, strategy performance or release readiness.

The recomputed source identity matches the supplied handoff. All **786 saved file
contents** matched the supervisor manifest before any edit. The tested M3.1 source
hash is `6e5f51466c86af7d2c736314df3a220ec25f82732d399bf03a0c5b43e52a10ec`;
the test hash is `1a1e54e6172aac68b768250112fdfc843f1738a8d5f19aa5a11ad2dd7cb5e544`.
Both protection files keep their tested hashes. Recoverable document copies and
local ownership/mode checks are saved in M3_1_LOCAL_CHECKS.json. This finalization
changes only that record, this evidence file and ROADMAP.md. Section 4's nine-path
list includes the earlier milestone work. All other saved owner files, code,
tests, configuration, owner rules, failing-test list and both definition packets
are preserved. In-place writes preserve local ownership and modes; this is not
an independent check of host ownership outside the sandbox.

Pending-proof notes in PROJECT_INDEX §§21–22/31 and TESTING_AND_VALIDATION §60
describe the earlier handoff. This §14 and ROADMAP §31 supersede their execution
status. Those documents and their contracts remain unchanged under this
records-only assignment. Earlier test counts and M3_1_LAUNCHER_LIMITATION.txt
remain historical; the local launcher error no longer blocks offline proof.

- [x] **M3.1 offline core price features:** implementation, compatibility tests,
  end-to-end recording and successful supervisor evidence are finalized for the
  separate independent review.
- [!] **M3.1 full-data/source completion:** §6 still requires complete eligible
  trades, frozen trade-condition/duplicate/cancel/correction rules, actual opening
  trade identity and compatible actual daily/minute/premarket source evidence.
- [ ] **M3.2:** proposed independent next milestone, limited to §5's three
  D-090 supplied-record participation calculations. The reviewer must validate
  this choice before the controller advances.

Status: **blocked**. Saved `next_milestone`: **M3.2**. The §6 reopening test remains
required in a separately authorized supervised step, starting with existing
local/free evidence. No data purchase is needed for the proposed offline slice;
any later purchase must name missing fields/dates/fidelity and a verified bounded
cost under D-091. No new data or authority was obtained. M3.2's supplied Bar
calculations need neither a live stream, full trade VWAP nor an opening trade.
Its unapproved or source-dependent branches remain tracked in §5. M0.2, M0.3B,
the other seven definitions and all later/full-data features remain required.
All switches stay off; D-091 remains $0 used and $0 reserved. No live/provider
call, credential read, message, order, purchase, restart, deployment, Git mutation,
controller edit or runtime-memory edit occurred. The supervisor's separate
reviewer decides acceptance; this result does not claim full M3.1 completion.

## 15. Fifth review repair — protected execution pending

The 587-test proof in §14 predates this repair and is historical. The reviewer
found two remaining input-boundary defects. Minute ATR searched all earlier bars
with the same calendar date for its previous close, so a premarket close could
inflate the first regular-session true range. The daily and minute feature paths
also did not reject a history request with the wrong interval.

The repair keeps D-090's arithmetic unchanged and narrows only those boundaries:

- previous-close lookup for minute ATR now uses regular-session minutes only;
- the first traded regular minute still uses high minus low after one or more
  certified no-trade opening minutes, without consulting premarket;
- minute ATR, bar VWAP and current HOD/LOD require a `1m` request;
- daily ATR and prior high/low/close require a `1d` request.

Four added protected cases use a premarket close of 110 followed by regular bars
with high 101, low 99 and close 100. The normal 20-minute window has ATR 2. The
window with a certified no-trade opening minute has ATR 1.9. The other two cases
prove minute history cannot supply daily features and a daily bar cannot supply
minute session features. The end-to-end compact recording includes all four paths.
The file now contains **54 written M3.1 cases**.

Both changed Python files compile. The unchanged protected launcher was attempted
with every selector in §2. It returned exit 1 before either child or collection:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-yfkvid9x'`

The exact traceback is appended to M3_1_LAUNCHER_LIMITATION.txt. No test was run
outside the protection. Neither protection file nor `.test-baseline` changed.
Two fresh protected runs must pass all §2 selectors, including all 54 M3.1 cases,
with matching ordered IDs and compact recordings, clean isolation and cleanup.
A fresh builder must then match the tested source and test hashes and finalize
records without changing code or tests.

- [~] **M3.1 offline core price features:** fifth repair and recording assertions
  are ready; fresh protected execution is the only remaining offline step.
- [!] **M3.1 full-data/source completion:** §6 remains required and blocked.
- [ ] **M3.2:** proposed independent next milestone under §5 after proof/review.

Saved `next_milestone`: **M3.2**. All switches remain off. No application, live
request, credential, message, order, purchase, restart, deployment, Git mutation,
controller edit or runtime-memory edit occurred. D-091 remains $0 used and $0
reserved. No profitability claim is made.

## 16. Fifth repair proof finalized and required blocker retained

The supervisor supplied fresh protected results at **16:47:22 Pacific on
2026-09-06**. This records-only session inspected the publication summary and
manifest, verified source manifest, both XML reports, both isolation reports,
both output files and both compact M3.1 recordings. The tested source, test and
protection hashes match the supplied manifest. Code, tests and protection were
not changed in this finalization.

Both runs passed **591 tests** (1,182 executions), including all **54 M3.1
cases**, with zero failures, errors or skips and identical ordered test IDs. All
five §2 selectors ran. Both isolation reports show the six expected denied
access checks, no unexpected denial, four successful cleanup checks and only
temporary database paths.

The two compact `m31-core-price-features-proof.json` files are byte-identical.
Each is **67,989 bytes**, below the 100,000-byte limit, with SHA-256
`89ed9dcbfce5f458dd452ed0cae0bdb4cf730eb282e24e46e136da32238d2234`.
The recording includes the fifth-repair results: regular-session minute ATR is
**2**, the certified-no-trade opening case is **1.9**, daily history is rejected
for minute features, and minute history is rejected for daily features. These
are synthetic contract results, not real-source coverage or trading returns.

The publication contains 27 files totaling 789,009 bytes. The tested hashes are:

- `consensus_engine/core_price_features.py`:
  `3a8f8115f40d1542fbd5dff8dc893e76eda4fbc0d1085635257b928323de76ba`
- `tests/trade_alerts_contracts/test_core_price_features.py`:
  `aab9bdd49945182024437679bf4fd906dccdd8a77f032e706d5872c674e0eec4`
- `scripts/testing/run_trade_alerts_contracts.py`:
  `6b609b643edfc467fc63480acd63ad50d4044616aec5efca61f32315af3d3ad2`
- `scripts/testing/trade_alerts_contract_child.py`:
  `85285dee88b1e2894e0ffa0239d20a27c073b27ba70908204e9b1f02cd79f24c`

- [x] **M3.1 offline core price features:** implementation, compatibility
  tests, end-to-end recording and fresh supervisor proof are finalized for
  independent review.
- [!] **M3.1 full-data/source completion:** §6 remains required and blocked.
- [ ] **M3.2:** proposed independent next milestone, limited to §5's three
  supplied-record calculations. The reviewer must validate this handoff.

Status: **blocked**. Saved `next_milestone`: **M3.2**. The offline row is complete,
but full M3.1 cannot be called complete until §6's real-source gate passes in a
separately authorized supervised step. All switches remain off. D-091 remains $0
used and $0 reserved. No live access, purchase or profitability claim is added.
