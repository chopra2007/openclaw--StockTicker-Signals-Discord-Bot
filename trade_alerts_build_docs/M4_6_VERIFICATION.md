# M4.6 offline alert rendering and delivery boundary

Date: 2026-09-07 Pacific. **Current status: completed for independent review.**
Section 13 finalizes fresh protected proof for the primary-attribution repair:
both runs passed 1,193 tests, including all 130 M4.6 cases. Expanded recordings
match. The earlier 1,145-test/82-case proof and §12's pending state are historical.
No assigned gate remains. Proposed next_milestone: **M5.1**, after independent
acceptance.

## 1. Assignment, preservation and done criteria

The assigned M4.6 matches ROADMAP §31 and M4_5_VERIFICATION §5. M4.5's two
1,045-test runs are historical prerequisite evidence, not proof of these changes.
All nine canonical files were read in their required order, followed by the
prebuild record, M0.4/M4.5 evidence, project rules/workflows and relevant code.
D-090 remains adopted; M0.3B remains proposed. Earlier dated handoffs do not
replace ROADMAP §31. No material definition conflict blocks this supplied boundary.

Before editing, 610 readable source, test, configuration, protection and document
files were hashed with ownership and modes. Recoverable documentation and sender
copies and the starting manifest are in `/tmp/m46-start-mzgqbus3/`. Read-only Git
checks used GIT_OPTIONAL_LOCKS=0. Git status reported `Permission denied` for
unrelated private workflow paths; they were not accessed or edited. All earlier
owner changes are preserved. The empty failing-test list remains unchanged.

Done for this assigned offline scope requires deterministic HEADS_UP/ACTIONABLE
and long/short rendering from frozen candidates; complete essential facts and
fallback; mention safety; canonical separate receipts; recording-only replay and
shadow; explicit injected fake transport; persisted supplied assembly and intent
before send; safe expiry/failure/unknown handling; compatible old callers; two
passing protected runs with identical end-to-end recordings; and saved records.
No required live, data or product-definition gate belongs to this bounded
mechanism. Actual storage/recovery and notification validation remain §5 work.

## 2. Implemented contract and written checks

`consensus_engine/alert_delivery.py` adds a frozen renderer, separate receipt/result
values, recording and explicit Discord test sinks, and the supplied persistence
boundary. `consensus_engine/alerts/discord.py:send_trade_alert_payload` extends the
existing sender module using its payload-safety helper and an explicitly bound
POST operation. It selects no transport session, destination, credentials or
clock. Existing pooled transport can be bound only in a later authorized host
integration. This adds no second client, authentication path or application task.
All 31 earlier sender functions/classes have identical syntax trees to the saved
starting copy. Existing send_message chunk-ID and _safe_send behavior are unchanged.

The renderer formats only supplied prices, risk, targets, confidence components,
quality/mode, expiry, human checks and any separately linked option result. It
calculates no score, geometry, selection or trading rule. Missing values are
visible. AI prose is not required or called. External markup/mentions/line breaks
are escaped. Rich output and its plain fallback contain identical complete text.
The full fallback must fit one 2,000-character message (counted conservatively as
UTF-16 units); overlong facts fail explicitly before any send instead of being
trimmed or partly confirmed. M15 retains later rendering refinement.

Delivery requires the original full M4.5 assembly, including context, full
confidence attribution and every component candidate, plus matching canonical
candidate/session. The injected save callback receives that whole assembly,
option result, rendered text and PENDING intent. It must atomically retain facts
and refuse an already unresolved intent before acknowledging. A separate
SEND_STARTED record is saved before the sink. Storage failure sends nothing.
This callback contract and test store do not implement the M5 durable store.
Replay and shadow always record, even if their saved sink setting says discord;
a Discord sink is rejected there. Only explicit `offline_test` accepts the supplied
fake transport. There is no live mode or switch activation.

Recording produces REJECTED_BEFORE_SEND / RECORDING_ONLY, with no remote reference
or request. Successful fake transport requires a structured whole-message receipt.
A legacy string, partial chunk ID, None, empty success body, transport exception
or ambiguous server response cannot become confirmed whole-message delivery.
Unknown errors retain a fixed code, never raw exception text. Requests rejected
with 400 can use one complete plain fallback within the supplied total attempt
bound. Only an explicit provider delay permits a throttled retry. Both delay and
expiry are checked again after I/O/waiting; no fixed provider retry delay is guessed.
The request timeout cannot outlive remaining expiry. Ambiguous sends are not
retried. A failed final save raises an error carrying the immutable result for
later reconciliation; cancellation leaves the saved start record. No automatic
resend or exactly-one-remote-message claim is made. An unstructured sender result
counts one attempted sender invocation; it proves no HTTP request occurred.

Before the primary-attribution repair, `test_alert_delivery.py` contained
**82 written cases** in 36 test functions; §12 records the current count.
The earlier 77-case supervisor proof predates the five component-link repair
cases. Coverage includes both
alert types/directions, known zero/unknown fields, malformed/oversized text,
markup/mentions, winter/summer Pacific display, option outage/poor quality,
immutable facts, complete assembly/session links, storage failure, a real temporary
transaction rollback, expiry boundaries, fallback, partial/unknown receipt,
server errors, response-body errors, provider delay and exhausted retries,
expiry during storage/fallback/wait, failed acknowledgment storage and cancellation.
No test strategy, supplied score/geometry or fake receipt proves a live setup.

Public documentation was checked for the existing transport format only. Message
content is limited to 2,000 characters and rich descriptions to 4,096; the new
complete fallback fits both. Rate responses supply their own retry delay.
Sources: [Discord message reference](https://docs.discord.com/developers/resources/message)
and [Discord rate handling](https://docs.discord.com/developers/topics/rate-limits).
No authenticated Discord or broker request was made.

## 3. Required protected proof

Use only the unchanged launcher with all these selectors:

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_alert_delivery.py`
- `tests/trade_alerts_contracts/test_candidate_assembly.py`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/test_discord_alerts.py`
- `tests/test_discord_embed_limits.py`
- `tests/test_pass5_steps_6_7_8.py::test_step8_safe_send_returns_json_on_200`
- `tests/test_pass5_steps_6_7_8.py::test_step8_safe_send_400_falls_back_to_plaintext`
- `tests/test_pass5_steps_6_7_8.py::test_step8_safe_send_429_retries_then_succeeds`
- `tests/test_pass5_steps_6_7_8.py::test_step8_safe_send_429_exhaustion_posts_truncation_notice`
- `tests/test_pass5_steps_6_7_8.py::test_step8_safe_send_500_returns_none_no_retry`
- `tests/test_pass5_steps_6_7_8.py::test_step8_safe_send_network_exception_returns_none`

The directory includes all earlier foundation, configuration, canonical record,
feature, strategy, state/storage, risk, confidence and candidate contracts. Explicit
legacy sender/renderer cases protect the touched module. The two unrelated
listener tests with unfaked reaction requests remain the saved M18.4 isolation
gap; they are neither run outside protection nor claimed passing. No old database
function or migration changes, so M4.2's broader legacy database selection is not
newly affected. The new rollback case uses the real existing temporary connection
and transaction method with test-only tables.

Both long/short end-to-end cases round-trip supplied Bars, run actual history
coverage and opening-range calculation, attach supplied score inputs, run actual
confidence composition and M4.5 assembly, then exercise the new persistence,
recording and fake sender boundaries. Expected opening width is 10, supplied
risk/share is 1, target is 2R and composed quality is 66. Both alert types retain
the original full assembly. Fake rich rejection followed by success has two
attempts and an exact complete plain fallback. A partial old-style ID stays
UNKNOWN. Exact expiry sends nothing. Options-unavailable leaves stock validity
and all original candidate bytes unchanged.

Require both protected runs to pass all selected cases with zero failures/errors/
skips, matching ordered IDs, no unexpected isolation denials and successful
cleanup. Both must save `m46-alert-delivery-long-proof.json` and
`m46-alert-delivery-short-proof.json`, each below 100,000 bytes. Read the XML,
output, summary, isolation and actual recordings; require byte-identical matching
pairs. Inspect original prices, quality, options status, sink, fallback text,
receipt statuses and unchanged-candidate assertions. Compilation is not test proof.
The supervisor must return readable fresh artifacts to a builder that finalizes
evidence and ROADMAP without code/test edits, before independent acceptance.

## 4. Historical local launcher result

This was the pre-proof **ready_for_verification** status. M4_6_LOCAL_CHECKS.json
records Python 3.10 grammar/compilation, written case count, existing-function
preservation, protection/configuration preservation, links, source/document scans
and ownership observations. There is no configured lint or type-check command;
ruff and mypy are not installed. No dependency was installed.

The first unchanged-launcher attempt stopped at its initial ownership operation:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-3i5wbheo'`

That attempt predates the last assembly/test additions. The final saved attempt
against the finished implementation is in M4_6_LAUNCHER_LIMITATION.txt and
LOCAL_CHECKS. Neither attempt collected tests or produced proof; section 7 now
records the later successful supervisor runs and records-only finalization. No
workaround, weaker protection or direct legacy test run was used.

Attempting to restore files to the named host account also returned Errno 22 in
this sandbox. The supervisor must verify/preserve host ownership when capturing
its test manifest; sandbox UID numbers do not establish host ownership. Existing
visible modes remain matched to their saved values. No bot restart occurred.
The read-only running-program check returned:

`Failed to connect to bus: Operation not permitted (consider using --machine=<user>@.host --user to connect to bus of other user)`

No running-state claim is made. The workspace shortcut resolved correctly and the
recent health/drift log search returned no matching lines.

## 5. Preserved gates and dependency-ready next work

Full M5.1/M5.5 storage must resolve and retain raw/feature/component/suppression/
option links and atomically store facts plus intent in the host database. M5.5
also owns crash/resume state reconstruction, started/unknown delivery
reconciliation, receipt persistence and expiry-aware recovery. M15.5–M15.7 retain
complete rendering/reliability refinement. M9.3/M17 and the applicable AT-06/10
gates require separately authorized source and notification evidence; this offline
M4.6 cannot be called delivery-tested. A true setting or a fake confirmation grants
no live authority. These required later rows remain open in ROADMAP.

- [!] **M4.7 — minimum options and portfolio path:** the required exact option
  candidate/filter/factor/0DTE rules, deterministic ranking/ties and per-strategy
  policies are not adopted. Full fingerprints, cooldown/structure counts,
  confluence priority and reversal/equal-score ownership also need their exact
  P-01/P-02 definitions. M0.3B's options and scoring proposals remain proposals;
  preparation must not be redone or adopted by inference. The other first-four
  playbook definitions remain open under PLAYBOOKS §13. M0.2/M14 still need
  compatible quote/contract/Greek/time/coverage evidence for actual use.
  Reopen after scoped owner adoption is recorded and canonical rules synchronized,
  then implement the one shared options/portfolio path and pass AT-08/AT-09
  with exact hand-worked fixtures. Actual-source claims need separately supervised
  evidence. No purchase or owner invention of provider facts is needed here.
- [ ] **M5.1 — research event store:** independent supplied-record storage is ready
  after M4.6 proof and review. Reuse db.py migrations/transactions, the M4.2
  transition store, immutable canonical records, full M4.4/M4.5 results and the
  M4.6 supplied intent/result boundary. Add the minimum append-only storage and
  typed linkage for supplied raw/feature/state/candidate/component/suppression/
  option/configuration records and delivery intent. Preserve all original facts,
  reject conflicting IDs/links, keep missing data visible, and prove atomic
  rollback/retry/reopen in temporary databases with a recording sink. Use the
  unchanged protected launcher and affected legacy database compatibility tests.
  Do not build a strategy, option ranker, outcome rule, live sender or full M5.5
  recovery. Storing supplied option/portfolio records does not require inventing
  the blocked M4.7 producers. Full recovery and all required original storage
  capabilities remain tracked until their own acceptance passes.

Saved proposed `next_milestone`: **M5.1**, subject to independent validation of
this ordering. M4.7 is retained as a required blocked row, not silently skipped or
completed. M3.3–M3.5, prior full-source/definition rows and all eight playbooks
remain required. Missing data blocks its dependent path. Existing/local/free
source evidence comes first in separately authorized supervised work; any purchase
needs named fields/dates/fidelity and a verified bounded cost under the cumulative
D-091 ledger. This session used $0 and reserved $0. Engineering proof establishes
no profitability.

## 6. Entire milestone paths

- `consensus_engine/alert_delivery.py`
- `consensus_engine/alerts/discord.py`
- `tests/trade_alerts_contracts/test_alert_delivery.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/M4_6_VERIFICATION.md`
- `trade_alerts_build_docs/M4_6_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M4_6_LAUNCHER_LIMITATION.txt`

No controller, protection, baseline, configuration, runtime memory or Git metadata
is modified. No application run, live activation, message, broker request, order,
deployment, restart, charged request or paid fallback occurred. All new switches
remain off. All nine authorities and original required work remain intact.

## 7. Fresh supervisor proof and records-only finalization

The controller returned readable proof from two fresh runs of the unchanged
protected launcher. Both runs used the selectors in §3 and passed **1,140 tests**,
including all **77 M4.6 cases**, with zero failures, errors or skips. Ordered test
IDs match. Each isolation record has no unexpected denials and confirms database,
HTTP, configuration and lock cleanup. Databento credit use was zero.

Both runs produced the required recordings. The long record is 25,813 bytes with
SHA-256 `99a0685f490ac581effac5ff2e57bd45872e4861a4a17bf500689b986fcdf37f`.
The short record is 25,850 bytes with SHA-256
`fe806c36e8e8302b53872f1c46123b7d2cb3f3019a72f5a5ed031c58d96ba2b2`.
Each pair is byte-identical across runs. The publication includes XML, logs,
isolation records and recordings. The tested-file manifest source hash is
`caf9ee85338b8cd1f9d4a4a174bfc744dca5f1a09ffa9b97409547edc0525b32`.
The milestone files retain their saved owner and mode; the supervisor proof
created no workspace ownership change.

This closes the assigned offline rendering and recording boundary. No required
live, data or definition gate belongs to M4.6. M5.1 is the dependency-ready next
work after independent review. Earlier full-source, full-definition and approval
gates remain open under their existing owners. No code, test, protection,
configuration or switch was changed during this finalization, and no trading
return or live-readiness claim follows. Actual durable recovery (M5.5), source
(M2/M9/M17) and notification (M9.3/M17) proof remain with their existing owners.


## 8. Returned-proof recheck and status repair — 2026-09-07 Pacific

This fresh records-only session inspected the published XML, summary, isolation,
logs and both long/short outputs again. All 55 published file hashes match.
Both runs contain 1,140 passing cases, including 77 M4.6 cases, with identical
ordered IDs and no failures, errors or skips. Both isolation reports have no
unexpected denials and all four cleanup checks pass. Required selectors match §3.

All code, tests, configuration and protection match the tested manifest. Of its
828 file entries, only four documentation records differed on entry: this file,
M4_6_LOCAL_CHECKS.json, PROJECT_INDEX.md and ROADMAP.md. Those differences were
existing partial finalization, preserved here. No code or test was changed or
rerun. The manifest records the expected host owner/group for all ten milestone
paths. This session edits existing files in place and preserves visible modes.

The actual recordings retain both alert types, price 100, long stop/target 99/102,
short stop/target 101/98, risk 1, target 2R and quality 66. Recording and expiry
have zero sends; fake confirmation has two attempts; partial receipts stay UNKNOWN.
Options stay unavailable and all original-candidate checks are true. The matching
record hashes and lengths remain those in §7. Synthetic output proves no live
notification or market coverage.

At that time, this session corrected the stale pending paragraph in ROADMAP's
M4.6 description and TESTING §68. It marked M4.6 `[x]` and completed for review.
Section 9's later component-link repair supersedes that status and proof. All ten
milestone paths in §6 remain part of the repair handoff.

## 9. Component-link review repair

Independent review found that `CandidateAssembly` can be copied with missing or
mismatched component candidates after its original construction. The candidate
could still name those components in its confluence links, while the old M4.6
delivery check accepted the altered assembly. That could save or send an
incomplete research record.

`deliver_candidate` now rechecks every supplied component before persistence or
send. Component IDs must be distinct from the primary and each other. Every
component must match the assembly's instrument, session and configuration and
must already exist by the evaluation time. Every confluence link must resolve to
the exact supplied strategy and same-direction component. Unlinked opposing
components remain valid research facts and are preserved in their supplied order.
No portfolio priority, scoring or trading rule is added.

Five new protected cases cover missing, wrong-strategy, opposite-direction and
wrong-configuration linked components, plus preservation of valid linked and
unlinked components in the saved intent. The long/short end-to-end proof now also
stores and checks both component kinds. The file now has 82 written M4.6 cases.
Python 3.10 grammar and compilation passed for both changed Python files. This is
not passing test evidence.

The unchanged protected launcher was attempted with every selector in §3. It
stopped before collection with:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ogra10xt'`

No direct or weaker test path was used. That pending state is historical: the
fresh two-run proof in §10 below now passes all selectors and all 82 M4.6 cases,
with matching ordered IDs, clean isolation/cleanup and byte-identical updated
long/short recordings. M4.6 is therefore `[x]` and completed for review. The
prior 1,140-test, 77-case results and their recordings remain historical. M4.7
stays `[!]`; M5.1 remains the proposed independent next milestone after independent
acceptance.

## 10. Component-link repair protected proof — complete 2026-09-07 Pacific

The supervisor returned readable proof from two fresh runs of the unchanged
protected launcher after the component-link repair. Both runs used the selectors
in §3 and passed **1,145 tests**, including all **82 M4.6 cases**, with zero
failures, errors or skips. The five new component-link cases
(`missing`, `wrong_strategy`, `opposite`, `wrong_config`) and the valid linked/
unlinked preservation case all pass. Ordered test IDs match across runs: both XML files list the same 1,145
testcases in the same order. Their elapsed-time fields differ. Both
isolation records are identical, have no unexpected denials and confirm database,
HTTP, configuration and lock cleanup. Databento credit use was zero on both runs.

Both runs produced the required updated recordings. The long record is 26,915
bytes with SHA-256 `c3e08785c07266ed465c447170f34e5f61297776d5d7d98c453dd7006d50d579`;
the short record is 26,966 bytes with SHA-256
`56d5344b9c1c9da608f6048a514d070e20ed52608488a7d310fd21484f048a61`. Each pair is
byte-identical across runs. The actual long/short recordings store both component
kinds (linked `m46-LONG-HEADS_UP-linked` and unlinked `m46-LONG-HEADS_UP-unlinked`)
in the saved intent, confirming the §9 preservation requirement end-to-end, with
ALERT price 100, both alert types, long stop/target 99/102, short stop/target
101/98, supplied risk 1, target 2R and quality 66. Synthetic fixtures show no
live notification or market coverage.

The tested-file manifest source hash is
`d281071baae618c34c2ed3b749ae9945a1b2b727030d07aa215f8772f7d04438`. The
supervisor proof created no workspace ownership change. This closes the assigned
offline rendering and recording boundary, including the §9 component-link repair.
No required live, data or definition gate belongs to M4.6. Actual durable
recovery (M5.5) and notification (M9.3/M17) proof remain with their existing
owners. M5.1 is the dependency-ready next work after independent review. No code,
test, protection, configuration or switch was changed during this finalization,
and no trading return or live-readiness claim follows.


## 11. Returned-proof recheck and result handoff — 2026-09-07 Pacific

The fresh records-only session preserved the existing finalization and inspected
the published summary, XML, logs, isolation reports and actual recordings. All
55 published file hashes match. Both runs passed 1,145 cases, including all 82
M4.6 cases, in 238.980 and 235.647 seconds. Ordered IDs match, failures/errors/
skips are zero, isolation has no unexpected denials and all cleanup checks pass.
The full selector list matches §3. No test or application was rerun.

Of 828 tested manifest entries, only five documentation records differed on
entry: M4_6_LOCAL_CHECKS.json, this file, PROJECT_INDEX.md, ROADMAP.md and
TESTING_AND_VALIDATION.md. These are the preserved partial finalization. Code,
tests, settings and both protection files match the tested contents. The host
manifest records the expected owner/group for all ten milestone paths. This
session edits records in place and preserves their visible ownership and modes.

Both long/short recordings match §10's lengths and hashes. Direct checks confirm
both alert types, width 10, price 100, risk 1, target 2R, quality 66, both saved
component kinds and exact confluence links. Complete fallback text matches the
recording text; fake confirmation takes two attempts, recording and expiry take
zero, partial receipts stay UNKNOWN, and original candidate checks stay true.

M4.6 is completed for independent review, with no remaining assigned gate.
M4.7 stays [!] for §5's unadopted policies. M5.1 stays the proposed independent
next milestone after review; all later source, recovery and notification gates
remain required. All ten milestone paths in §6 remain in the result. No code,
test, protection, switch, trading rule or live authority changed.

## 12. Primary-attribution review repair — 2026-09-07 Pacific

Review found that equality between the candidate and a copied assembly was not
enough: both could name HOD_COMP_RS while the full confidence still named
CRVOL_ORB5. A primary feature absent from the context could also pass. The earlier
completion statements in §§7–11 describe previous file states only.

Before edits, the existing partial source/tests and records were inspected and
backed up at `/tmp/m46-primary-repair-4bh7ibbl`. All owner work is preserved.
The assigned M4.6 matches ROADMAP §31; no new trading definition is needed.
The repair plan and done condition are: reuse the existing assembly checks,
prove rejection before either storage callback or transport, extend the complete
long/short offline path, and obtain fresh protected proof before completion.

`alert_delivery.py` now calls the existing `assemble_candidate` with all original
supplied facts and compares the complete result with the supplied assembly.
This replaces the narrower duplicate component validator. It rechecks primary
instrument/session identity, strategy/version, creation instant, original PENDING
status, required feature/input references, full confidence composition and every
component link. It creates no new score, rule, feature or record shape. The
original candidate and assembly remain immutable; the checked copy is not stored.
No source outside the assigned delivery file changes in this repair.

Forty-eight new protected cases cover twelve alterations across both directions
and alert types: strategy, version, symbol, instrument type, absent feature,
missing primary link, missing confidence link, unknown input, reused input ID,
creation time, delivery status and altered confidence result. Both storage
callbacks and transport must remain uncalled. Primary and confidence snapshots
are deliberately distinct. The test file has 130 written cases in 37 test
functions. These counts are static, not collected or passing results.

Both long/short end-to-end cases still run supplied Bars through real coverage,
opening-range calculation, confidence composition, assembly and fake delivery.
They now use the opening snapshot as the distinct primary feature and save all
twelve rejected alterations per alert type, each with zero records and sends.
Valid paths retain width 10, risk 1, target 2R, quality 66, complete fallback,
linked/unlinked components, unknown receipts and expiry checks. The existing
82 cases and all compatibility selectors in §3 are preserved.

The unchanged protected launcher was attempted with every §3 selector. Its exact
latest result is saved in M4_6_LAUNCHER_LIMITATION.txt and M4_6_LOCAL_CHECKS.json.
It stopped at the initial ownership step before collection with:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-i4_f31uw'`

Python 3.10 grammar
and compilation checks are local syntax evidence only. No direct test execution,
protection workaround, new dependency or application run was used.
Host ownership restoration for the two edited Python files returned Errno 22
again; exact errors are in LOCAL_CHECKS. Visible modes are unchanged. The
supervisor must verify host ownership with its fresh test manifest.

Status: **ready_for_verification**, with the offline row [~]. The supervisor must
run the unchanged full selection twice and return fresh XML, logs, isolation and
expanded long/short recordings. Require all 130 M4.6 cases, zero failures/errors/
skips, matching ordered IDs, clean isolation/cleanup and byte-identical recordings
below 100,000 bytes. A fresh builder must inspect those artifacts and finalize
records without changing code/tests. Independent acceptance remains afterward.
The earlier supplied artifact copy proves only the previous source state.

All ten milestone paths in §6 remain the complete delta. The separate required
M4.7 gate stays [!], with its exact reopening proof in §5. Saved proposed
next_milestone is **M5.1**, whose unchecked independent row remains in ROADMAP §31
and §5 here. Full recovery, source and notification proof retain their existing
owners. All switches stay off; no live access, purchase or profitability claim.

## 13. Primary-attribution repair proof finalized — 2026-09-07 Pacific

The supervisor returned fresh protected proof at **22:03:30 Pacific**. Both runs
passed **1,193 tests**, including all **130 M4.6 cases** and all **48 new rejection
cases**, in **240.754 and 244.006 seconds**. The complete §3 selection ran through
the unchanged launcher. Ordered test IDs match, failures/errors/skips are zero,
and both isolation reports show no unexpected denials and successful cleanup.
The XML, summary, output, logs and expanded recordings were inspected directly.

All **55 published file hashes** and all **828 tested file contents** matched
before this records-only finalization. The supervisor manifest records the
expected host owner/group for all ten milestone paths. Existing records were
backed up before editing. This session preserves visible ownership and modes;
no code, test, setting, protection or application run changed. The source hash is
`789edf991e750308668c742b5381fe2e5aeeac37486c81c876abb661626e78b4`.
M4_6_LOCAL_CHECKS.json saves the publication/manifest hashes, readable proof
location, per-run results and checks. Earlier local ownership errors remain
historical in M4_6_LAUNCHER_LIMITATION.txt and §12.

Both expanded long/short recording pairs match byte for byte:

- Long: **28,043 bytes**, SHA-256
  `4f9487e326eb9ead290d44588c40fce5091880d29d353d487b8ee1a6bc2a0d6b`.
- Short: **28,094 bytes**, SHA-256
  `9a8eabf74b662e2c4b8945b6146b6b4435275e0485f6568d95c3850b71cf26bc`.

Each direction retains both alert types and all twelve rejected alterations per
alert type, each with zero stored records and zero sends. The actual outputs
retain width 10, price 100, risk 1, target 2R and quality 66. Long stop/target are
99/102; short are 101/98. Both linked and unlinked components survive. Complete
fallback text matches recording text; fake confirmation takes two attempts,
recording and expiry take zero, partial receipts stay UNKNOWN, options remain
unavailable and original candidate checks stay true. These supplied examples
prove no market coverage, live notification or profitability.

M4.6 is **completed** for the supervisor's separate acceptance review. No required
live, data, authority or definition gate remains for this assigned offline
boundary. ROADMAP §31 retains M4.6 [x], the separate M4.7 [!] gate and the unchecked
independent **M5.1** row, bounded by §5. All prior unfinished source/definition
branches, full storage/recovery and later notification proof retain their owners.
All ten milestone paths in §6 remain the complete change list. All switches stay
off; no live access, purchase or new trading rule is added.
