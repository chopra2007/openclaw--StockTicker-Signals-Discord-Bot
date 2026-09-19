# M4.5 supplied candidate assembly

Date: 2026-09-07 Pacific. The offline implementation and protected proof are
complete. Both fresh supervisor runs passed 1,045 tests, including all 96 M4.5
cases; see §8. The earlier unchanged-launcher failure remains in §7 and
M4_5_LAUNCHER_LIMITATION.txt as history.
Proposed next_milestone: **M4.6**, after independent review.

## 1. Assignment, preservation and done criteria

The assignment matches ROADMAP §31 and M4_4_VERIFICATION §5. M4.4's two 949-test
runs prove only that earlier offline prerequisite. Its required full scoring gate
stays blocked. All nine canonical files were read in order, followed by the
prebuild record, project rules/workflows, M0.4/M4.4 evidence and relevant sources.
M0.3B remains proposed. The small ROADMAP §9 note still saying M4.4 execution was
pending was corrected against its saved §8 proof; no old proof was rerun or replaced.

Before editing, 571 source/test/configuration/protection/document files were
hashed with ownership and modes. Recoverable document copies and the starting
manifest are at `/tmp/m45-start-onzs7j89/`. Read-only Git checks used
GIT_OPTIONAL_LOCKS=0. The existing failing-test list is empty and remains unchanged.
All earlier uncommitted files belong to the owner and are preserved. Read-only
Git status reported Permission denied on unrelated private workflow paths; none
was accessed for this implementation or changed. Preservation uses the saved
readable-file manifest, not an assumption of a clean checkout.

Done for M4.5 means: pure supplied assembly into existing canonical records;
both HEADS_UP/ACTIONABLE and long/short consistency; exact context, version,
feature/configuration and full confidence attribution; no zero substitute for
missing confidence; explicit expiry boundaries; separately linked suppression;
all supplied component candidates retained; immutable earlier bytes; two passing
protected runs with compact identical recordings; and saved evidence/roadmap.
No required live/data/definition gate belongs to this common assembly mechanism.
Full automatic behavior remains with the existing owners in §4.

## 2. Implementation and written checks

`consensus_engine/candidate_assembly.py` adds three pure functions and an immutable
assembly result. AlertCandidate, SuppressionEvent, ConfluenceLink, RiskLevel,
TargetLevel, StrategyContext and the full ConfidenceResult are reused. No
canonical record shape, existing consumer, loader, live switch or storage changes.
The full contract is CODING_STANDARDS §69.

The assembler uses supplied facts, deriving only the context's existing direction,
evaluation instant and fixed session/configuration links. It checks available
metadata, configured version, primary feature and confidence bindings, risk/target
geometry and exact component links. Missing required facts return no candidate;
invalid contracts raise RecordError. Full confidence is compared with its existing
supplied calculation, so changing its score/status/reasons cannot fake the result.
Known zero scores are preserved. Supplied degraded inputs remain visible.

All supplied component candidates survive, including unlinked opposite-direction
facts. Linked confluence must match the exact supplied candidate, strategy and
direction. No priority, new fingerprint, merge, bonus or selection rule is chosen.
Suppression preserves a caller-supplied reason in a separate canonical record,
with or without an existing candidate. Later suppression can use original
candidate inputs. Expiry inspection is read-only: equality means expired; no
duration, suppression reason, state transition or retry is inferred.

The written cases cover record round trips, both types/directions, all strategy
identities, null action facts on a heads-up, missing action inputs/confidence,
known zero confidence, future/wrong metadata, wrong direction/version/session/
configuration, altered confidence results, absent/duplicate/unknown input links,
wrong geometry and R, unknown source/quality, explicit proxies, expiry edges,
confluence failures and component preservation, candidate-less/later suppression,
immutability and repeatable output. The static count is saved in LOCAL_CHECKS;
it is not a collected or passing test count.

## 3. Required protected proof

Use only the unchanged `scripts/testing/run_trade_alerts_contracts.py` with:

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_candidate_assembly.py`
- `tests/trade_alerts_contracts/test_confidence.py`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`

The directory covers the existing canonical records, configuration, features,
interface, transition/storage and risk contracts. The additive module changes no
shared legacy file; earlier expanded database selections are not new dependencies.
The existing M4.4 selection is preserved and the new explicit selector is added.
No legacy test is run outside protection, and neither protection file is changed.

The long/short end-to-end cases use round-tripped supplied Bars, actual historical
coverage and opening-range calculation, supplied score/factor inputs, actual
confidence composition and the new assembly. The opening width is 10; supplied
R=1 and T1=2R; composition produces 66. Both alert types round-trip and retain
their full input/session/configuration links. A separate component survives
confluence unchanged. At one microsecond before/exactly at/after expiry the
observed expectations are false/true/true. Later explicit suppression is separate.
Missing confidence produces no candidate and a candidate-less suppression. A
later score revision gives 100 only to a new candidate, while previous bytes stay
identical after that revision and a separate unavailable-options record.

Scores, factor formulas, geometry, state and the one-second expiry are test-only
supplied facts. These tests do not detect a playbook or prove source coverage.
Each child must write `m45-candidate-assembly-long-proof.json` and
`m45-candidate-assembly-short-proof.json`, each below 100,000 bytes. Read both pairs
and require byte-identical recordings, matching ordered test IDs, zero failures/
errors/skips, no unexpected isolation denials and successful cleanup. Inspect
the XML, output, summary and isolation files. Local source checks cannot replace
this evidence. Actual launcher status is recorded below and in LOCAL_CHECKS.

## 4. Preserved required gates

This is the common supplied assembly mechanism, not the automatic suppression or
portfolio system. No new required definition is needed to assemble supplied facts.
Full candidate eligibility, heads-up conditions and expiry choices remain under
M0.3 and each M6–M13 strategy. M4.7/M15 retain cooldowns, fingerprints, structure
counts, merging, ties, confluence priority and reversal ownership. M5.1/M5.5 retain
actual input existence, durable candidate/full-confidence/component/suppression
storage, atomic delivery intent and recovery. IDs alone prove none of those facts.

M4.3's full structural producers/coverage, M4.4's full factor definitions/source
readiness, and all prior source rows remain explicitly blocked in ROADMAP §31.
Their evidence records retain exact reopening proofs. No purchase or live access
is needed for M4.5; D-091 remains $0 used and $0 reserved. Any later source check
or purchase belongs to separately authorized supervised work with named missing
fields/dates/fidelity and verified bounded cost. No trading returns are established.

## 5. Proposed exact next milestone

- [ ] **M4.6 — existing delivery adapter and non-network sinks**, after M4.5
  protected proof, records-only finalization and independent acceptance.

Build its bounded offline deterministic candidate renderer and recording/test
sink boundary, reusing the existing sender and canonical DeliveryRecord. Rendering
must format frozen facts, preserve essential prices/risk/targets/quality/expiry/
human checks, use Pacific time, and prevent unintended mentions. Preserve existing
sender callers and payload safety. Use injected fake transport only for the
adapter's compatibility and failure tests; recording is the replay/shadow default.
Do not contact Discord, create destinations or supply live credentials.

Existing `alerts/discord.py:send_message` returns the last successful chunk ID
even after a later chunk fails; `_safe_send` collapses several failures to None.
Do not treat that ID as whole-message confirmation or invent a specific failure
cause from None. Existing protected `_Response`/`_Session` helpers and the sender
cases in `test_adapters_delivery.py` provide the compatibility fixtures. Extend
the existing boundary additively when needed; no duplicate Discord client.

Exercise both alert types/directions, recording output, malformed/oversized input,
complete deterministic fallback, optional options/AI unavailable, explicit expiry,
partial/unknown send results and failure paths with the unchanged protection.
Keep rendering free of scoring, target calculation, trading policy or remote calls.
M5.5 retains full atomic persistence/recovery and crash reconciliation; M15.5–M15.7
retain full refinement. No send becomes permitted before the required persisted
facts/intent and applicable AT-06/AT-10 gates. Actual notification/delivery evidence
still needs separately authorized supervised access. If a required product choice
is unresolved, record its exact branch without guessing. M4.7's separate unresolved
options/portfolio rules do not prevent this offline renderer/adapter work.

Saved proposed `next_milestone`: **M4.6**. The supervisor reviewer decides whether
this bounded scope and ordering are ready. No further milestone is implemented here.

## 6. Entire milestone paths

- `consensus_engine/candidate_assembly.py`
- `tests/trade_alerts_contracts/test_candidate_assembly.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/M4_5_VERIFICATION.md`
- `trade_alerts_build_docs/M4_5_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M4_5_LAUNCHER_LIMITATION.txt`

No Git, controller, runtime memory, protection, baseline, configuration or existing
application file is modified. No live access, message, order, deployment, restart,
charged request or paid fallback occurred. All switches stay off. All nine
authorities, eight playbooks, required capabilities and unfinished work remain.

## 7. Historical local launcher result

The unchanged launcher exited 1 before child creation or test collection, at
its initial ownership operation. Exact final error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-fl0x2sd2'`

M4_5_LAUNCHER_LIMITATION.txt saves the complete output. No test count, XML,
isolation report or recording was produced. No tests were run outside protection.
This was the pre-proof **ready_for_verification** status. Section 8 now records
the later successful supervisor runs and records-only finalization. Independent
acceptance remains the separate reviewer's decision. The saved proposed
next_milestone remains **M4.6**.

Source grammar/compilation, written-case counts, local links, document drift,
added-text scans, preserved inputs and ownership results are saved in
M4_5_LOCAL_CHECKS.json. They were separate from the protected proof later supplied
in §8.
The read-only running-program check returned exactly:

`Failed to connect to bus: Operation not permitted (consider using --machine=<user>@.host --user to connect to bus of other user)`

No running-state claim is made. The workspace shortcut resolved correctly and
the recent health/drift search returned no matching lines. No restart followed.

## 8. Fresh supervisor proof and records-only finalization

The controller returned readable proof from two fresh runs of the unchanged
protected launcher at 01:54:53 Pacific. Both runs used the six selectors in §3
and passed **1,045 tests**, including all **96 M4.5 cases**, with zero failures,
errors or skips. Ordered test IDs match. Each isolation record has no unexpected
denials and confirms database, HTTP, configuration and lock cleanup. Databento
credit use was zero.

Both runs produced the required recordings. The long record is 19,511 bytes with
SHA-256 `768061f7a450d73459fed60019ee9f58b66f720e030789337224a8dcc0535d8f`.
The short record is 19,522 bytes with SHA-256
`a3a3ca0a8f75d91f88fdc04e34fb87cc905577bac2f0ef3e4194d53ca5aff1b5`.
Each pair is byte-identical across runs. The publication includes XML, logs,
isolation records and recordings. The tested-file manifest source hash is
`a0ba4a732a36c28b2b82e228107948d1ca268c70a7991e5c3c7ed561bde28702`.
The milestone files retain their saved owner and mode; the supervisor proof
created no workspace ownership change.

This closes the assigned common offline assembly mechanism. No required live,
data or definition gate belongs to M4.5. M4.6 is the dependency-ready next work
after independent review. Earlier full-source, full-definition and approval
gates remain open under their existing owners. No code, test, protection,
configuration or switch was changed during this finalization, and no trading
return or live-readiness claim follows.
