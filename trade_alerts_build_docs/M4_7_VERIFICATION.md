# M4.7 implementation and verification handoff

Status: **BLOCKED AFTER INDEPENDENT REVIEW; NOT ACCEPTED**, 2026-09-14 Pacific.

## Historical implementation claim — rejected by current review

`M47_FIRST4_RESEARCH_V1` is frozen in M4_7_DEFINITION_PACKET and incorporated
into PLAYBOOKS, TESTING_AND_VALIDATION and DECISIONS_AND_OPEN_QUESTIONS.
`consensus_engine/options_portfolio.py` implements the pure supplied-record
option score/rank result, complete-batch candidate identity and portfolio
projection, producer cooldown and intent expiry. `event_store.py` atomically
retains the complete projection and every independent candidate.

The AT-08/AT-09 fixture file covers ordinary and same-day paths, other first-four
ordinary-only policies, poor versus unavailable results, stock independence,
median and tie behavior, UTF-8 identity, batch order and completeness, fixed
primary anchors, opposite conflicts, persistence, cooldown and expiry equality.
Existing M8.5 checked transition findings are the only accepted reversal-release
input. They retain their wrong-symbol, wrong-session, wrong-parent and input-time
checks.

## Protected test handoff

The controller must run the focused selector
`tests/trade_alerts_contracts/test_options_portfolio.py`, then its required broad
selection. Because deterministic projection and reopen behavior are required,
the recording selector must run in two fresh protected processes and the
`m4_7_options_portfolio.json` artifacts must match.

No protected result is claimed here. This Codex workspace cannot execute the
protected launcher because its temporary-directory ownership change is denied
with `OSError: [Errno 22] Invalid argument`. The controller stage must publish
the exact selector names, counts, times, artifacts, comparisons and complete
tested-source manifest.

## Boundaries retained

All switches remain off. No source, provider, broker, Discord or application
run occurred. Synthetic records do not prove source field units, chain
completeness, historical option execution, cross-strategy calibration, an edge,
shadow readiness or live readiness. M14/M15 retain remaining strategies and full
refinement. M0.2C remains proposed independent shared data work after review.

## Attempt 2 — focused failure diagnosis and repair

The prior controller run is preserved at
`/root/trade-alerts-builder/runs/20260914-005332-515740-build/`.
Its `verification.log` records the failing test
`tests/trade_alerts_contracts/test_options_portfolio.py::test_opposite_direction_is_a_conflict_without_comparable_score_arbitration`.
The exact pytest summary was `1 failed, 18 passed in 4.71s`. That is the
pytest summary time, not JUnit time or controller wall time. The reported
artifact root is `/tmp/trade-alerts-m04-lwhqxe2i`. This failed run is historical
diagnostic evidence, not acceptance. `changes.diff` and
`controller-normalized-build.json` preserve the original complete milestone
delta. No attempt counter or earlier proof was removed.

The assertion expected conflict fingerprint
`00173e57db65cf2662ee80eb6afa37e89c87d12f5f06e84f14309661f93dcbe4`
but received
`a421877ab9851841e109f125b19a098ff1e9f7c8aea3f2fc5ecce16d3db2b329`.
Both candidates have equal mechanical times and equal priority. Section 4 of
M4_7_DEFINITION_PACKET therefore makes the smaller fingerprint the incumbent,
which is the short candidate in this fixture. The test incorrectly treated
input order as ownership order. `project_portfolio` follows the frozen rule;
changing its order to satisfy that assertion would violate the contract.

This repair changes the test expectation to the frozen fingerprint tie and
checks both independent groups, conflict direction, retained IDs and reversed
input order. Additional cases give either direction an earlier mechanical time
and a later challenger a higher raw confidence score; the earlier owner must
remain primary. Product code and frozen rules are unchanged in this attempt.
The original implementation delta below remains part of the milestone.

Historical supplied test metadata: `tests.phase` is focused; `tests.runs` is
1; `tests.test_count` is null; `tests.selection_reason` is
`builder named directly affected checks`; `tests.selectors` is
`["tests/trade_alerts_contracts/test_options_portfolio.py"]`.
`tests.wall_seconds` and a separate `tests.focused` object were not supplied.
No new protected run was attempted. The known launcher ownership failure above
still prevents execution here. The controller must first rerun the failed case
and directly affected file, stop on any focused failure, then run its required
broader selection. It must separately run the deterministic recording selector
in two fresh protected processes and compare `m4_7_options_portfolio.json`.
The controller stages will supply current phase names, exact selectors, run
counts, test counts, pytest/JUnit/controller times, hashes, comparisons and the
complete tested-source manifest. No current pass or independent acceptance is
claimed.

## Complete milestone file delta

- `consensus_engine/event_store.py`
- `consensus_engine/options_portfolio.py`
- `tests/trade_alerts_contracts/test_options_portfolio.py`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M4_7_DEFINITION_PACKET.md`
- `trade_alerts_build_docs/M4_7_VERIFICATION.md`
- `trade_alerts_build_docs/PLAYBOOKS.md`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`

## Attempt 2 protected proof

The controller completed the repaired protected stages against source hash
`813b2af8d6dbf1fcc6522c1030916c1b241930f549c71467e4bc52749895e375`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260914-005332-515740-build/verified-manifest.json`
(SHA-256 `64befeda3b89d3eec51d8477daa07f1834ff9621c7f489963ee9af9f7eb741d2`).
Controller evidence is
`/root/trade-alerts-builder/runs/20260914-005332-515740-build/controller-evidence.json`
(SHA-256 `013e1962e781dd817f6fd52d0b763a30d70756b3c32959313fc17a235ea91156`).

### focused

Selector: `tests/trade_alerts_contracts/test_options_portfolio.py::test_opposite_direction_is_a_conflict_without_comparable_score_arbitration`.
Selection reason: `builder named directly affected checks`. Runs: 1. Test count:
1. Controller wall seconds: 4.821. Artifact directory:
`/root/trade-alerts-builder/runs/20260914-005332-515740-build/published-artifacts-cecf1eabd5b3`.
pytest line: `1 passed in 3.11s`. JUnit time: `3.115` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason:
`unknown dependency impact; safe broad fallback`. Runs: 1. Test count: 3020.
Controller wall seconds: 562.89. Artifact directory:
`/root/trade-alerts-builder/runs/20260914-005332-515740-build/published-artifacts-93586708c878`.
pytest line: `3020 passed in 559.04s (0:09:19)`. JUnit time: `558.924`
seconds.

### repeatability

The controller used the 38 selectors in its repeatability artifact because
`recording output requires fresh-process comparison`. Runs: 2. Test count: 62.
Controller wall seconds: 306.59. Artifact directory:
`/root/trade-alerts-builder/runs/20260914-005332-515740-build/published-artifacts-393ee55c4007`.

Run 1 pytest line: `62 passed in 151.30s (0:02:31)`. Run 1 JUnit time:
`151.299` seconds. Run 2 pytest line: `62 passed in 151.70s (0:02:31)`.
Run 2 JUnit time: `151.697` seconds.

Both fresh processes have matching ordered test IDs. Every phase has zero
failures, errors and skips, no unexpected isolation denials, and complete
cleanup. The controller marked repeatability stable. The acceptance artifact's
`m4_7_options_portfolio.json` has SHA-256
`f3218057cfeffdc7c0bd595a90a77188012a3134365a3b3817cdf3aba65657e6`.
The repeatability selector set does not emit that M4.7-specific file, so no
cross-run M4.7-file comparison is claimed.

## Final result and next milestone

The minimum first-four offline options and portfolio path is incomplete and not accepted. The current independent review supersedes the historical implementation claims above. Source field units, complete real chains,
historical option execution, calibration, early strategy validation, M14/M15
refinement and live use remain separate gates. All switches remain off.

The proposed next milestone is **M0.2C — measured saved-data capacity and
safe-activation assessment**. It is independent shared data work. Independent
review must confirm its place in the dependency order before the controller
advances.


## Current independent rejection and blocked assessment

Review: `/root/trade-alerts-builder/runs/20260914-013053-818349-review/review-result.json`. Both prior attempts and all valid historical test reports remain unchanged. The focused1/broad3020/repeat62+62 proof establishes only its collected cases. It does not establish the absent behavior or a fresh-process M4.7 recording comparison. No additional implementation repair is authorized after the exhausted attempt limit.

Required unresolved issues:
- AT-08/AT-09 coverage is incomplete. The 19-case options file omits many required boundaries, including both-direction option selection, every score factor and tie field, unknown units and standardness, future times, semantic identity collision, source isolation, simultaneous priority, producer quotas, invalid reversal releases, and restart without deadline extension.
- project_portfolio accepts any TransitionFinding marked ACCEPTED for matching record IDs. TransitionFinding can be constructed without checked reversal evidence, a session, or supporting records, so an unproved transition can take ownership.
- A reversal replaces the group primary and therefore moves the grouping anchor. The frozen rule says the original anchor never moves. The code also calculates released_from but omits it from PortfolioGroup and the saved projection, preventing required parent-release recovery.
- Cooldown and expiry are isolated helper checks only. No M4.7 state path stores or restores the original fingerprint, quota, mechanical clock, group owner, parent release, or absolute expiry as required.
- The two-process phase collected 62 tests from 38 unrelated selectors. It collected no options_portfolio test and emitted no m4_7_options_portfolio.json in either run. Therefore the required M4.7 recording was not compared across fresh processes. M4_7_VERIFICATION.md admits this, while ROADMAP marks M4.7 complete; reopen that row and correct the proof record without removing the valid historical runs.
- The records-only comparison itself is structurally valid: both manifest hashes recompute, the protected manifests match, and its exact delta contains only M4_7_VERIFICATION.md and ROADMAP.md. It cannot cure the missing behavior or repeatability evidence.

M4.7 remains a required blocked branch, with actual source, historical execution, calibration and live gates separately unresolved. M0.2C is proposed as independent measured storage work only; a fresh reviewer must confirm this truthful blocked assessment and next-step eligibility. No claim of complete M4.7, AT-08/09 or profitable/live readiness is made.


## M4.7A owner-reopened implementation — 2026-09-14 Pacific

The owner-authorized M4.7A task preserves the rejected M4.7 attempts, blocked
record and valid historical proof. It takes the different approach required by
the independent review: a TransitionFinding is no longer accepted as release
proof. ReversalReleaseEvidence retains the original trigger, handoff and
reversal requests plus the saved session and canonical supporting records.
project_portfolio binds reduced prices and times to those records, recomputes
all three producer results, and passes the newly computed reversal through the
existing cross-strategy check. Missing, changed or forged evidence leaves the
incumbent owner unchanged.

Groups now store the original anchor and current owner separately. Reversal
changes only the owner. The output retains the parent fingerprint and release
record ID. All later grouping measurements continue to use the original anchor.
Each candidate also carries explicit producer recovery facts, the original
mechanical time, canonical key and bytes, fingerprint, research arm, session
close and fixed intent deadline. ResearchEventStore stores that complete bundle
in the existing atomic write and verifies it when reopening the exact manifest.
Missing recovery data refuses a favorable projection.

The recording case now emits option scores and reasons, all independent
candidate IDs, checked release evidence, original anchor/current owner and the
recovery payload to m4_7_options_portfolio.json. The controller must collect
tests/trade_alerts_contracts/test_options_portfolio.py::test_projection_json_is_deterministic_and_keeps_every_independent_id
in both fresh repeatability processes and byte-compare that file. No protected
pass is claimed here. This Codex workspace cannot run the protected launcher
because its temporary-directory ownership change fails with
OSError: [Errno 22] Invalid argument. The controller must run the focused
options, research-store and cross-strategy checks first, then its required broad
selection and the two fresh recording processes.

M4.7A changes consensus_engine/event_store.py,
consensus_engine/options_portfolio.py,
tests/trade_alerts_contracts/test_cross_strategy_interaction.py,
tests/trade_alerts_contracts/test_options_portfolio.py,
trade_alerts_build_docs/M4_7_VERIFICATION.md and
trade_alerts_build_docs/ROADMAP.md.

Synthetic records establish only the offline contract. Source field units,
complete real chains, historical option execution, calibration, early strategy
validation, profitability, shadow use and live use remain blocked. All switches
remain off. Fresh controller proof and independent review are the only remaining
M4.7A acceptance steps.

## M4.7A protected acceptance — 2026-09-15 Pacific

Build run `/root/trade-alerts-builder/runs/20260914-060429-391233-build`
published passing protected proof. A prior focused attempt in this same run
failed `tests/trade_alerts_contracts/test_options_portfolio.py::test_both_stock_directions_and_signed_delta_boundaries[SHORT-PUT--0.5]`
and `[SHORT-PUT--0.7]` with `RecordError: SHORT risk and targets have invalid
geometry`; that failure and its diagnosis are preserved as historical. The
published proof below is the corrected result from the same build run and
supersedes it.

The focused phase (builder-named directly affected checks, reason "builder
named directly affected checks") collected the 2 selectors above, passing both
in one run, `2` tests, `3.888` wall seconds, at
`published-artifacts-fe3c98128a44`.

The broad acceptance phase (reason "unknown dependency impact; safe broad
fallback") selected `tests/trade_alerts_contracts`, exit code 0, `3070` tests
in one run, published at `published-artifacts-9b2dd666ae6c`.

The repeatability phase (reason "recording output requires fresh-process
comparison") collected 39 selectors including
`tests/trade_alerts_contracts/test_options_portfolio.py::test_projection_json_is_deterministic_and_keeps_every_independent_id`,
passing `65` tests in each of 2 runs, wall `307.119` seconds, stable, published
at `published-artifacts-30e92b1f08c3`. The required `m4_7_options_portfolio.json`
recording was collected and byte-compared in both fresh processes.

The mechanical evidence is recorded at
`controller-evidence.json` under that build run. The `verification_handoff`
records source hash
`bd367e7fded2d696a7cf4c0cba2a9d0889cc8486d7a2c5a0b68e59a6deea4daf` and
manifest `verified-manifest.json`, both under the same build run, timestamped
2026-09-15T22:14:00-07:00.

M4.7A is accepted on this protected proof. All earlier M4.7 blocked history
(attempt-exhausted review, the missing AT-08/09 boundaries, the moving-anchor
and missing-parent-release defects, and the absent fresh-process recording)
remains historical and is now resolved by the M4.7A repair described above and
proved by this run. Source field units, complete real chains, historical
option execution, calibration, early strategy validation, profitability,
shadow use and live use remain separately blocked. All switches remain off.

The next milestone is **M9.3 — shadow mode**, the early-validation gate for
strategies 1-4 that M4.7's adopted options and portfolio rules were blocking.
M9.3 also depends on the separate M0.2 provider/queue/storage/disk/memory
budget and continuity proof and on a separately reviewed environment repair
for its prior storage/temporary-folder acceptance failure; those gates are
unresolved by this record and remain open. Independent review must confirm
M9.3's eligibility before implementation advances.
