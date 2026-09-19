# M4.4 supplied confidence composition

Date: 2026-09-07 Pacific. The offline implementation and protected proof are
complete. Both fresh supervisor runs passed 949 tests, including all 68 M4.4
cases; see §8. The earlier unchanged-launcher failure remains in §3 and
M4_4_LAUNCHER_LIMITATION.txt as history.
The required full scoring-definition/source gate remains blocked in §4.
Proposed independent next_milestone: **M4.5**, bounded in §5, after proof and review.

## 1. Assignment, preservation and done criteria

The M4.4 assignment agrees with ROADMAP §31 and M4_3_VERIFICATION §5. M4.3's
892-test proof establishes that earlier offline prerequisite only. Its separate
full structural gate remains blocked. All nine canonical files were read in the
required order, followed by PREBUILD_REVIEW, relevant M0.4/M4.3 evidence, the
project working rules and implementation sources. Earlier dated handoffs remain
historical. M0.3B is still proposed; no scoring formula is adopted by this work.

Before editing, 563 source, test, protection, configuration and document files
were hashed with ownership and modes. Recoverable document copies and the saved
starting manifest are at `/tmp/m44-start-7mljztgn/`. Read-only Git checks used
GIT_OPTIONAL_LOCKS=0. The existing failing-test list was empty and is unchanged.
All earlier uncommitted work belongs to the owner and is preserved.

Done for the assigned offline slice means: exact weighted arithmetic from three
supplied scores; an explicit versioned roster of supplied factor contributions;
finite 0–100 scores; complete immutable feature/configuration attribution;
missingness without replacement or reweighting; canonical candidate round trips;
both-direction offline recordings; affected compatibility checks; two successful
protected runs; and saved evidence. Full factor production, definitions and
source readiness are separate required gates, not implied by supplied examples.

## 2. Implementation and written checks

`consensus_engine/confidence.py` adds one pure composition boundary. The existing
ConfidenceBreakdown, ConfidenceComponent, FeatureSnapshot, StrategyContext and
SessionRecord are reused unchanged. Legacy ScoreBreakdown.total is a different
point sum and is not reused as a trade-alert confidence score. No live caller,
configuration default, dependency, database table or factor producer is added.

ConfidencePolicy holds the explicit strategy/version, composition-policy version,
three weights and required term roster. Each term names its Setup/Context/Execution
component, SCORE/FACTOR role, exact feature name, definition version and data mode.
Each component requires exactly one score and at least one declared factor.
Weights must be finite fractions in [0,1] summing exactly to one. No missing term
is silently removed, including when its component weight is zero. Supplied
weights are preserved; this boundary does not select or approve playbook weights.
The test policies use the existing common 50/30/20, #5 45/35/20, #7 40/40/20 and
#8 45/30/25 values, with explicitly synthetic factor definitions.

ConfidenceRequest binds policy terms to original canonical snapshots in M4.1's
fixed context. Missing bindings, snapshots, features and values yield an
UNAVAILABLE result with reasons and no ConfidenceBreakdown. Unknown sources,
wrong identity/type/definition/mode/units, stale/invalid quality, missing input
references and older calculations cannot become passing scores. The existing
context rejects future availability/evaluation/source time, wrong sessions and
duplicate input IDs. A declared strategy version cannot contradict a non-null
version in the saved session configuration.

All selected scores and contributions use SCORE_POINTS. Scores must already be
within 0–100. Factors retain finite signed contributions and their original
versions. Component normalization, factor-to-score formulas, factor bounds and
omission rules are deliberately not inferred: a component score is independently
supplied, not recomputed by summing its factors. For example, a supplied -3.25
factor remains -3.25 without changing the independently supplied Context score.
Their required adopted upstream relationship remains §4 work. Current supplied
score/contribution snapshots must have this evaluation time; creating a new
request cannot refresh an older calculation. Raw ancestor windows stay upstream.

Exact rational arithmetic from canonical decimal text combines the scores before
display rounding. The bounded final value becomes the existing immutable
ConfidenceBreakdown; factor entries retain their names, values and versions.
The full result preserves the complete request, component membership, weights,
policy, original feature records and fixed session/configuration for M5 retention.
Its deterministic JSON and detached exports introduce no second store. Candidate
serialization stays unchanged. The compact breakdown alone is not full
attribution; M5 must retain the complete calculation alongside its candidate.

The written tests cover the hand-worked weights, 0/100 limits, unrounded decimal
values, all eight identities, every missing score/factor, missing bindings and
records, wrong units/identity/source/mode/definition/quality, explicit proxies,
old/future inputs, unknown ancestry, invalid policy shapes and weights, multiple
factor versions, immutable exports and unchanged configuration/record contracts.
The static count is in M4_4_LOCAL_CHECKS.json; it is not a collected or passing count.

## 3. Required protected proof and actual local limitation

Run only the unchanged `scripts/testing/run_trade_alerts_contracts.py` with:

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_confidence.py`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`

The directory covers all prior canonical, configuration, feature, interface,
transition/storage and structural-risk contracts. The legacy model tests preserve
the current point-sum score. No existing source/test file is changed, so the
earlier expanded database selection is not a new dependency of this addition.
Full release and listener-isolation checks retain their M18 owners.

The two end-to-end cases round-trip supplied Bars, calculate the actual shared
five-minute opening range, then attach explicitly test-only supplied score/factor
snapshots to that feature reference. Actual composition produces 66 from
80/60/40 and weights 0.5/0.3/0.2. Both HEADS_UP and ACTIONABLE canonical candidates
round-trip in each direction. A missing Context factor returns no confidence and
cannot be put into a canonical candidate. A later score revision produces 100
only for the new calculation. The original candidates remain byte-identical
after that revision and a separately linked unavailable-options result. Scores,
factor normalization, geometry and candidate assembly are synthetic facts; this
does not evaluate a trading playbook or establish source coverage.

Both protected children must save `m44-confidence-long-proof.json` and
`m44-confidence-short-proof.json`, each below 100,000 bytes. Inspect the actual
scores, weights, term membership, factor versions, original input/session/config
links, missing result and unchanged candidates. Require matching recordings and
ordered test IDs across runs, zero failures/errors/skips, no unexpected isolation
denials and successful cleanup. Read the XML, output, summary and isolation files.
Source grammar/compilation and hand inspection cannot replace those tests.

The local attempt exited 1 at the launcher's first ownership operation, before
child creation or collection. Exact final error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-bbbda9mz'`

M4_4_LAUNCHER_LIMITATION.txt preserves the full output. No test artifacts or
passing count were produced. No test or application was run outside protection.
Both protection files are unchanged. Status: **ready_for_verification** for the
offline slice. The supervisor must execute the saved selection externally,
publish readable proof and a tested-file manifest, and check new-file ownership.
A fresh builder must finalize evidence/roadmap without code or test changes.
After successful proof, retain the offline [x] row and required §4 [!] row and
return **blocked**, with independent M4.5 for review. Do not call full M4.4 complete.

## 4. Required full confidence gate and reopening proof

Status: **BLOCKED BY DEFINITION / DATA / separately supervised source access**.
These are required remaining M4.4 capabilities, not optional improvements.

- M0.3/M0.3B and M4.4 must freeze and adopt the exact factor roster, transformations,
  scales, normalization/clamping and factor-to-component formulas for each
  affected playbook. The prepared M03B_ORB5_V1 B-SCORE proposal remains unadopted.
  Existing per-playbook weights stay binding. A supplied version label is not
  approval of a formula or a new weighting choice.
- M0.3/M4.4 must supply exact mandatory/modifier/optional factor treatment,
  missing-factor penalties/omissions, freshness windows and data modes. This slice
  has no favorable substitute, score cutoff or missing-weight renormalization.
  No permission to omit one factor follows from a synthetic complete roster.
- M0.2, M3.3–M3.5, M6–M13 and existing source owners must establish actual
  point-in-time factor inputs, original receipt/availability, source/venue and
  adjustment basis, coverage, correction handling and approved proxy treatment.
  Synthetic score snapshots and reference IDs do not prove those source facts.
- M16.4 retains confidence calibration, train-only fitting, locked future evidence
  and ranking analysis. It is required later validation, not a probability claim
  or a reason to manufacture a scoring cutoff now. M5.1 retains actual durable
  full-attribution storage and candidate linking.

Reopen the dependent full scoring branch after a version-scoped owner decision
is recorded and synchronized, with hand-worked long/short and missing-input
examples giving a unique factor-to-score result. Then obtain separately
authorized supervised dated input/coverage/revision evidence and run it through
the same calculations and full attribution storage. Verify each applicable
factor's actual source and formula; do not infer coverage from supplied labels.
Use existing local/Schwab/free evidence first. Any purchase must name the missing
fields/dates/fidelity and verified bounded cost under the cumulative D-091 ledger
in a separately supervised step. No purchase is needed for this offline work;
usage and reservations remain $0. Engineering completion proves no profitability.

## 5. Proposed independent next milestone

- [ ] **M4.5 — offline supplied candidate assembly and consistency prerequisite**,
  after M4.4 offline proof, saved blocked-gate handoff and independent review.

M1.3 already supplies AlertCandidate, SuppressionEvent and ConfluenceLink. Do not
rebuild their record shapes. Add only a pure assembly/consistency boundary for
explicit supplied HEADS_UP/ACTIONABLE facts, expiry, suppression and confluence,
using M4.1 context, existing risk/target records and the full M4.4 result. Validate
identity, direction, strategy/version, feature/configuration links and evaluation
times before constructing the existing records. Preserve suppression as a separate
fact; no missing confidence may become zero. Keep all supplied component
candidates and original immutable facts. Use explicit expiry instants and reasons;
do not select a cooldown, expiry duration, fingerprint, trading graph, confluence
priority, score cutoff or validity rule. Full automatic suppression/deduplication,
strategy eligibility and storage remain their M0.3/M4.7/M5/M6–M15 owners.

Prove supplied features/confidence/risk -> consistent canonical candidate and
separate suppression record, both directions and alert types, wrong identity/time/
version, missing mandatory supplied facts, expiry boundaries, confluence links and
unchanged prior bytes under protected tests with compact recordings. This common
assembly mechanism can be tested without choosing the blocked full scoring
formulas or structural producers. Any newly encountered unresolved rule blocks its
own branch and cannot become a default. The supervisor's independent reviewer
must validate this scope and ordering. Saved proposed `next_milestone`: **M4.5**.

## 6. Entire milestone paths and safety

- `consensus_engine/confidence.py`
- `tests/trade_alerts_contracts/test_confidence.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M4_4_VERIFICATION.md`
- `trade_alerts_build_docs/M4_4_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M4_4_LAUNCHER_LIMITATION.txt`

No Git, controller, runtime memory, protection, baseline or configuration file is
changed. All switches stay off. No live access, broker/Discord call, message,
order, deployment, restart, charged request or paid fallback occurred. All eight
playbooks, all nine canonical authorities, all required capabilities and earlier
unfinished roadmap rows remain. Local static/document/preservation checks and
exact host-check limits are recorded in M4_4_LOCAL_CHECKS.json. These checks are
separate from the pending protected test execution.

## 7. Local checks saved before verification handoff

Both new Python files pass compilation and Python 3.10 grammar checks. Static
source inspection counts 21 test functions and 68 written cases and confirms all
11 canonical constructor calls with keyword arguments use existing field names.
This is source inspection only; no tests were collected or executed. The 96 local
Markdown links resolve. Added text, whitespace, requirement coverage and prior
blocked-row checks pass. All existing saved file contents outside this milestone
and all existing ownership/modes remain unchanged; the delta is exactly §6's
11 paths. Canonical models, configuration, protection and both definition packets
retain their saved hashes. The failing-test list is unchanged.

Restoring ownership of each of the five new files returned `[Errno 22] Invalid
argument`; M4_4_LOCAL_CHECKS.json saves each exact path/error. The supervisor must
verify host ownership with the protected evidence. The read-only running-program
check returned exactly:

`Failed to connect to bus: Operation not permitted (consider using --machine=<user>@.host --user to connect to bus of other user)`

No running-state claim is made. The workspace shortcut resolves correctly. The
read-only recent health/drift search exited 0 with zero matching lines. No restart
or application test followed. These host checks do not replace protected proof.

## 8. Fresh supervisor proof and records-only finalization

The controller returned readable proof from two fresh runs of the unchanged
protected launcher at 01:14:41 Pacific. Both runs used the five selectors in §3
and passed **949 tests**, including all **68 M4.4 cases**, with zero failures,
errors or skips. Ordered test IDs match. Each isolation record has no unexpected
denials and confirms database, HTTP, configuration and lock cleanup. Databento
credit use was zero.

Both runs produced the required recordings. The long record is 11,958 bytes with
SHA-256 `8c1da24c4a14eb1edbd48eb0c2184818b2b75e4d36c1107cb75312edb24f9816`.
The short record is 11,966 bytes with SHA-256
`749d78f41e8a215b501590f9d4eb3284ac76d8644fe6706f6af1e713074a74b8`.
Each pair is byte-identical across runs. The publication includes XML, logs,
isolation records and recordings. The tested-file manifest source hash is
`f1115ce6204c40de56a39b6189426deb9829a6e92aba03d90640e0df4569f336`.
The five new milestone files retain the same owner and mode shown before this
records-only update; the supervisor proof created no workspace ownership change.

This closes only the offline supplied-confidence row. Section 4 remains a
required blocked gate. Full factor definitions, missingness/freshness rules and
actual compatible source readiness are still unavailable. M4.5 is independent
next work after review. No code, test, protection, configuration or switch was
changed during this finalization, and no profitability or live-readiness claim
follows.
