# M2.4 offline reference proof finalized — required source gate blocked

Date: 2026-09-06 Pacific. Status: **blocked** for required M2.4 source completion.
The bounded offline implementation and evidence are finished: §9 records two
supervisor runs with 537 passing tests each and identical reference recordings.
The earlier local launcher errors in §4 are historical. The required source gate
in §7 remains open. Saved independent next_milestone: **M3.1**, subject to the
supervisor's separate review. This is supporting evidence, not a new specification,
trading decision or claim of profitability.

## 1. Assigned scope and preserved starting work

ROADMAP §31 and M2_3_VERIFICATION §6 name M2.4: a supplied-record snapshot and
coverage interface for SPY, QQQ, all 11 specified sector ETFs and explicit VIX
missingness. M2.3 §12 supplies the prior completed offline evidence: two supervisor
runs with 490 passing tests and identical 43-decision recordings. Those results
predate M2.4 and do not verify it. This automatic assignment selects the saved
next scope; no earlier completed milestone was rebuilt.

All nine canonical files, PREBUILD_REVIEW, applicable earlier evidence,
PROJECT_RULES and WORKFLOWS were read. The two M2.4 Python files already existed
as uncommitted owner work. They were inspected before further work, preserved,
and included in this whole-milestone list. No source was restored from Git.
The local starting snapshot covers 571 source, test, configuration and document
files, including both partial M2.4 files. Recoverable document/source copies,
hashes, modes and ownership are saved at the temporary location in
M2_4_LOCAL_CHECKS.json. The existing failing-test list is empty and unchanged.

Read-only Git checks used GIT_OPTIONAL_LOCKS=0. They reported `Permission denied`
for unrelated saved workflow paths. Those files were not read or changed. No
Git metadata, controller file, runtime memory or protection script was edited.
The existing application, all switches, D-090 and the M0.3B proposals remain
unchanged. This lane made no live, credential, broker, Discord or paid request.

## 2. Implemented contract

The existing partial implementation is completed under CODING_STANDARDS §61:

- `ReferenceScope` fixes each ETF's source, quote/history modes, supplied quote
  policy and optional history request. There is no chosen live age or window.
- `build_reference_snapshot` reuses M2.3 Quote decisions at the exact supplied
  evaluation time and M2.2 history coverage at that time. Each ETF keeps its own
  source, session, original availability, quality, missingness and reasons.
- Thirteen expected ETF identities remain separate from usable quote and complete
  history counts. Missing QQQ or a sector cannot be filled by fresh SPY data.
  Empty supplied history retains requested intervals and their missing states.
- Current stock mappings reuse `analysis.wolf_scope.stock_sector_etf` and stay
  separately labeled CURRENT_MAP_ONLY / historical membership UNAVAILABLE.
  Unknown stocks stay unknown. Frozen outputs cannot be changed by later map,
  dictionary, stream or history revisions.
- VIX stays UNSUPPORTED_INDEX_INPUT. The existing text/transport aliases do not
  provide a canonical index type or supported index quote/history semantics.
  Neither an ETF label nor a volatility fund can substitute for spot VIX.
- Deterministic M24_V1 JSON preserves individual inputs, supplied policy,
  history conventions, coverage and explicit reasons. It calculates no return,
  relative-strength, breadth, score or strategy rule and starts no live consumer.

The 11 expected sector symbols come from DATA_REQUIREMENTS §12. The current stock
lookup file has 10 distinct mapping values: IWM, QQQ, SPY, XLC, XLE, XLF, XLK, XLP,
XLV and XLY. That is not all-sector input coverage or historical membership.
No mapping source or old caller behavior was changed.

A bounded read-only source check found no actionable issue after tracing the
canonical time validation. The source comment now explains that inherited guard;
three added test cases cover future quote/trade components and a missing history
request with a usable quote. Existing production behavior is preserved. This
static check is not the supervisor's final independent acceptance review.

## 3. Required protected tests and offline recording

Run the unchanged `scripts/testing/run_trade_alerts_contracts.py` with these
selectors, in both protected child processes:

- `tests/trade_alerts_contracts`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`

The directory contains every existing M0.4/M1/M2 contract plus the M2.4 tests.
The legacy model/client tests retain old behavior and VIX transport aliases;
the named stock-mapping test covers the reused helper. No existing helper,
normalizer, calendar, record or live consumer was modified. No new protection
permission is needed for the code or the supplied fixtures.

Required end-to-end case:
`test_supplied_reference_coverage_recording_end_to_end`.
It uses synthetic raw responses, actual normalization, canonical Bar/Quote round
trips, real per-symbol event decisions and history coverage, then saves
`m24-reference-inputs-proof.json`. All price/age/continuity labels in that test
are explicitly synthetic; they establish no provider fact.

Expected results below are now observed in both supervisor recordings; see §9:

- At 06:35:01 Pacific, 9 of 13 ETF quotes are usable and 11 histories are complete.
  QQQ/XLV quotes are missing, XLE is delayed, XLP is disconnected, XLK's history
  arrives later and XLF has no history. VIX remains unavailable.
- At 06:35:04, no quote is usable and 12 histories are complete. XLK's supplied
  late bar is now available; it cannot change the first saved snapshot.
- Reordered input dictionaries and stock lists produce the same snapshot bytes.
  Current NVDA mapping is XLK; the synthetic unknown stock has no mapping.

Other cases exercise every expected ETF independently, empty inputs, unsupported
VIX/proxies, unknown stock mapping, wrong source/symbol/session/type/mode, future
quote decisions and availability, stale sides/trades, bad source quality,
reconnection, missing/different policies, history revisions/conventions and
immutable nested output. The supervisor must inspect both XML/isolation reports,
require zero failures/errors/skips, matching test IDs, no unexpected denials,
successful cleanup and byte-identical M2.4 recordings. Earlier milestones' proof
must remain passing. A skip or empty artifact folder is not successful execution.

## 4. Local checks and exact launcher limitation — historical

The initial protected attempt returned exit 1 before either child:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-q5s_8_k3'`

The error occurs at the launcher's initial `os.chown` step. No test results,
isolation reports or M2.4 recording were produced. The final post-work attempt
and full tracebacks are retained in M2_4_LAUNCHER_LIMITATION.txt.
Neither protection file was changed or bypassed; no legacy test was run directly.
M2_4_LOCAL_CHECKS.json records actual local source/grammar, document, preservation,
ownership and all-off configuration checks. These are not execution proof.
There is no configured repository lint/type-check task; no tool was installed.

The final attempt also stopped at `os.chown`, with exit 1:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-yf6zfyuj'`

New evidence-file ownership restoration returned `[Errno 22] Invalid argument`
for all three new records; the exact per-file errors are saved in the local check
record. Existing files kept their original locally reported ownership and modes.
The supervisor must check/restore host ownership when preparing external proof;
the sandbox's reported ownership is not a separate host check.

The supervisor must run the unchanged protection externally, publish the actual
artifacts and supply them to a fresh builder. That builder must inspect source
identity, both full selections and both recordings before records-only
finalization. Do not change code/tests while finalizing successful proof.
If proof fails, repair this same offline scope with the partial files retained.

## 5. Whole milestone paths

The list includes the supplied partial M2.4 implementation and tests, not just
this attempt's record edits. Earlier owner M0.4/M1/M2 files are excluded.

- `consensus_engine/reference_inputs.py`
- `tests/trade_alerts_contracts/test_reference_inputs.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/SESSION_PROTOCOL.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M2_4_VERIFICATION.md`
- `trade_alerts_build_docs/M2_4_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M2_4_LAUNCHER_LIMITATION.txt`

## 6. Saved handoff and independent next work

**next_milestone: M3.1**, proposed after independent review of this blocked-gate
handoff. Section 9 finalizes successful M2.4 protected proof. The required source
gate in §7 remains blocked; do not repeat M2.4 as its own next milestone. The
separate reviewer must validate the blocker and independent next scope before
the controller advances. This session does not start M3.1.

- [ ] **M3.1:** bounded offline core price features using the approved D-090
  F-01/F-02/F-03 definitions and supplied available-time-safe inputs.

Reuse canonical Bar/FeatureSnapshot records, M2.2 scheduled coverage and the shared
calendar. Inspect `analysis.indicators` before reusing arithmetic; its existing
Wilder ATR must not replace D-090's fixed-window arithmetic ATR. Implement the
approved minute/daily ATR, bar HLC3 session VWAP, prior/premarket extrema, and only
uniquely defined point-in-time session levels/open/gap paths. Explicitly require
an identified first regular-session trade for GAP_OPEN_V1; do not take a polling
last price or an incomplete bar as proof of the open. Unknown compatible source,
adjustment, preceding close, finality or scheduled coverage must yield UNKNOWN.
Do not skip a missing required minute/session or use future revisions.

Full trade VWAP remains required and blocked until complete eligible-trade
coverage and condition/duplicate/cancel/correction rules are supplied. Missing
opening-trade evidence blocks its dependent open/gap result. Actual source coverage
stays M0.2; no synthetic feature case certifies it. M3.2 retains RVOL, M3.3 relative
strength, M3.4 slope/crosses, M3.5 structural geometry and M3.6 actual opening range.
M0.3B choices and other playbooks' unspecified definitions cannot be adopted.

Acceptance for the next offline scope: hand-calculated approved feature cases,
window/warm-up/no-trade/zero/missing/correction cases, open and shortened-session
boundaries, actual Bar -> available-time coverage -> FeatureSnapshot -> recording
proof identical in two protected runs, and affected old-indicator compatibility.
This scope is independent of live M2.3 streaming and M2.4 provider checks because
it uses supplied records and already approved arithmetic. The separate reviewer
must validate this next selection before the controller advances.

The saved roadmap now retains an [x] row for finished offline work and an [!]
row for the required source gate below. Under the controller's blocked-gate rule,
return **blocked** with M3.1 as the independent next milestone. Full M2.4 is not
complete; successful software tests do not close the source requirement.

## 7. Required source blocker and supervised reopening

- [!] **M2.4 source completion:** BLOCKED BY DATA and separately supervised access.
  The offline interface does not finish actual reference-market inputs.

Affected paths: SPY/QQQ/sector context across the playbooks, mandatory market/sector
inputs in #2/#4/#5/#6, and VIX where available. Missing evidence is current per-symbol
1m/L1/reference history coverage and timing for SPY, QQQ and all 11 sectors;
source/venue/adjustment/finality compatibility; official spot-VIX identity, fields,
instrument/session/time semantics and access; and point-in-time sector membership
for historical use. Existing current mappings and bounded collector counts prove
none of those complete inputs. No index type or VIX price was invented here.

Reopening: in a separately authorized supervised step, inspect existing local/raw
Schwab and free-source records first. Save dated per-symbol/session coverage,
original times, delay/quality, missing intervals, finality/adjustments and source
field evidence. Resolve supported VIX canonical identity/type and event semantics
before adding that path; preserve old record readers and test exact source mapping.
For historical membership, supply dated original-availability mappings or keep the
historical result unavailable. Reconcile shared capacity with M0.2/M2.3, use an
approved explicit age/coverage policy and a recording sink, then obtain independent
acceptance of the source-dependent branch.

No data purchase is needed for the offline M2.4 or proposed M3.1 contracts. Any
later purchase must name exact missing fields/dates, the existing/free-source gap,
fidelity difference and verified bounded cost for a separately supervised step.
D-091 remains $25 total authorized, $0 used and $0 reserved. The live M2.3 gate,
M0.2 history/corporate-action coverage, M0.3B adoption, other seven definitions,
full breadth, faithful catalyst, true profiles and every later roadmap feature
remain required. No live activation or engineering-profitability inference follows.

## 8. Final local record — before supervisor proof

Both M2.4 Python files pass source compilation and Python 3.10 grammar checks.
All 131 local document links resolve. The eight playbooks, 31 numbered requirements
and 22 additional capability rows remain present. All 13 new switches remain off
and the configured sink remains recording. Of 571 saved files, 562 are unchanged;
the other nine and three new evidence files are exactly the twelve paths in §5.
No unexpected content, ownership or mode change was found in that saved set.
The two protection scripts, failing-test list, configuration and approved/proposed
packets retain their original hashes. Added text passed the bounded private-text
and whitespace checks. The saved roadmap and evidence agree on M3.1.
These local results left protected execution and independent review pending.
Section 9 now supersedes that execution status; independent review still remains.


## 9. Supervisor proof finalized and required blocker retained — 2026-09-06 Pacific

Status: **blocked** for required source completion, with **finished offline
implementation and evidence**. The supervisor supplied successful protected
results at **13:03:09 Pacific**. This records-only session inspected the publication
manifest, both XML reports, both isolation reports, output logs and both reference
recordings. All **25 published file hashes** match, totaling **635,068 bytes**.
The original publication stays with the supervisor; its private location is not
copied into public records. [M2_4_LOCAL_CHECKS.json](./M2_4_LOCAL_CHECKS.json) saves
the checked hashes, source identity, test counts and both per-symbol summaries.

Both runs passed **537 tests** (1,074 executions), including **46 M2.4 cases**,
with zero failures, errors or skips and identical ordered test IDs. All four
selectors in §3 ran. The end-to-end case, both future-component cases and the
missing-history-request case passed in each process. Earlier contract cases and
the existing model, Schwab client and stock-sector lookup checks remain passing.
The six deliberate forbidden-access checks were denied as intended. No unexpected
isolation denial occurred; all four cleanup checks passed and all four database
connections in each run used temporary files. The unchanged launcher reports two
zero exits and $0 Databento use. This session did not rerun tests or import the
application; these are inspected supervisor results.

The synthetic raw response → canonical Bar/Quote round trips → actual M2.2
coverage and M2.3 per-symbol decisions → reference snapshot → recording path
produced byte-identical `m24-reference-inputs-proof.json` files. Their SHA-256 is
`b687e7eac79cb63ced959c0ebafdb1c87cda3156a07591cc7bf37739a4e49110`.
Both saved snapshots match the §3 expectations:

- At 06:35:01 Pacific, 9 of 13 ETF quotes are usable and 11 histories are complete.
  Missing QQQ/XLV quotes, delayed XLE, disconnected XLP, missing XLF history and
  not-yet-available XLK history remain individually visible.
- At 06:35:04 Pacific, no quote is usable and 12 histories are complete. XLK's late
  bar is now final and available; XLF still has no history. The earlier snapshot
  stays unchanged. VIX remains unsupported in both snapshots.
- Current NVDA → XLK mapping stays CURRENT_MAP_ONLY. The unknown stock stays null;
  both mappings retain historical membership UNAVAILABLE. Counts remain
  SUPPLIED_RECORDS_ONLY. Reordered inputs give identical bytes in the passing case.

The M1.3, M2.1, M2.2 and M2.3 recordings and configuration fixture are also
byte-identical across these two processes. This closes only M2.4's supplied-record
acceptance, not source coverage, breadth/return calculations, full replay, live
inputs, delivery, strategy validation or profitability.

The recomputed source identity equals the supplied handoff identity. All **781
saved file contents** matched the supervisor's manifest before any edit. Both
M2.4 Python files and both protection scripts keep their exact tested hashes.
Recoverable copies and local ownership/mode checks are saved in
M2_4_LOCAL_CHECKS.json. This session changes only that record, this evidence file
and ROADMAP.md. The whole milestone's twelve-path list in §5 includes earlier
partial work. All other owner files, the failing-test list, configuration and both
definition packets are preserved. In-place record writes preserve local ownership
and modes. The sandbox's mapped ownership differs from the supervisor manifest;
this is not an independent host ownership check.

Pending-proof notes in PROJECT_INDEX §31, SESSION_PROTOCOL §44, DATA_REQUIREMENTS
§39, TESTING_AND_VALIDATION §59 and DECISIONS §40 describe the earlier M2.4 handoff.
This §9 and ROADMAP §31 supersede their execution status. Those files and their
contracts stay unchanged under this records-only assignment. Sections 4/8 and
M2_4_LAUNCHER_LIMITATION.txt remain historical; the local launcher failure no
longer blocks the offline handoff.

- [x] **M2.4 offline prerequisite:** implementation, successful supervisor proof
  and required records are ready for the separate independent review.
- [!] **M2.4 source completion:** §7's per-symbol source/history coverage, supported
  spot-VIX contract, historical sector membership and shared capacity evidence
  still require a separately authorized supervised step.
- [ ] **M3.1:** exact next independent milestone, using §6's approved offline price
  calculations. The reviewer must validate this choice before the controller moves.

The blocker and its reopening test remain exactly as saved in §7. No new data
or authority was obtained. M3.1 can use supplied records and D-090 arithmetic
without M2.3 live streaming or M2.4 source completion. Its own full trade VWAP,
opening-trade and actual source coverage gates remain required. All other unfinished
roadmap features, M0.3B proposals and the other seven definitions remain tracked.
All switches stay off; D-091 remains $0 used and $0 reserved. No live/provider call,
credential read, message, order, restart, deployment, purchase, Git mutation,
controller edit or runtime-memory edit occurred. The supervisor's separate reviewer
decides acceptance; this blocked result does not claim full M2.4 completion.
