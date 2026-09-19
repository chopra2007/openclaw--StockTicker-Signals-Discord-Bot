# M4.3 supplied structural risk and targets

Date: 2026-09-07 Pacific. Offline implementation and protected proof are complete.
Both supervisor runs passed 892 tests, including all 105 M4.3 cases. The separate required
structure/definition/source gate remains blocked in §4. After successful offline
proof, keep its completed row separate and return blocked for that required gate.
Proposed independent next_milestone: **M4.4**, bounded in §5, after review.

## 1. Assignment, preservation and done criteria

The controller assignment agrees with ROADMAP §31 and M4_2_VERIFICATION §5.
M4.2's expanded 826-test proof is completed historical prerequisite evidence,
not proof of this change. All nine canonical documents were read in the required
order, followed by PREBUILD_REVIEW, D-090's packet, M0.4/M4.2 evidence and the
project working rules. No finished milestone or M0.3B proposal was rebuilt.

Before editing, 566 source/test/protection/configuration/document files were
hashed with their ownership and modes. Recoverable document copies and the
manifest are at `/tmp/m43-start-pg2c0w40/`. Existing local changes belong to the
owner. Read-only Git checks used GIT_OPTIONAL_LOCKS=0. The broad status command
reported Permission denied for unrelated runtime files; a scoped check showed
the existing changes without editing them. The failing-test list was empty and
is preserved. No Git, controller or runtime-memory mutation is part of this work.

Done for the assigned offline prerequisite means: D-090 §6 calculations over
explicit supplied inputs; outward tick rounding; positive directional risk;
unrounded extension and reward limits; complete per-family obstacle coverage;
canonical risk/targets; missingness and immutable attribution; long/short offline
recordings; affected compatibility tests; two passing protected runs; saved
records. Full structural producers, applicability and source evidence are required
separate gates. Engineering completion is not strategy readiness or profitability.

## 2. Implementation and acceptance cases

`consensus_engine/structural_risk.py` adds one pure selector for the two named
D-090 B variants. It reuses immutable FeatureSnapshot/FeatureValue inputs and
RiskLevel/TargetLevel outputs. Existing display target ladders and risk helpers
have different rules and remain unchanged. No live caller, configuration default,
new dependency, database change or trading strategy is added.

Five explicit feature bindings supply anchor, crossing-frozen 20-minute ATR,
known price increment, unrounded crossing boundary B and eligible latest trade E.
Each keeps original canonical identity, definition, availability, units, input
IDs and data mode. A shared supplied price-basis label identifies the original
source/venue/adjustment contract. Derived feature producer names may differ;
compatible underlying price basis must not. This label cannot certify actual
source compatibility. The anchor and entry must describe the trigger evaluation;
ATR, increment and boundary must already be known at crossing. Tape and quote
last-trade path estimates have separate required labels. Complete anchor-path
coverage and a known evidence reference are explicit caller inputs, not computed
or certified by this selector.

The raw stop is anchor minus/plus 0.05 frozen ATR, rounded outward to the supplied
increment. Decimal input text is converted to exact rational arithmetic for tick
rounding and comparisons. Exactly 0.35 extension passes. Zero ATR remains a known
value; zero/unknown increment and nonpositive/wrong-side risk cannot supply a
usable stop. Raw and rounded stop, E, B, risk and extension are retained.

A versioned supplied catalog must cover PREMARKET, PRIOR_DAY, OR_MEASURED_MOVE,
ATR, AVWAP, PROFILE and OTHER_STRUCTURE through the evaluation instant, with
known evidence available by that instant. No unspecified not-applicable rule can
remove a family. Every listed level has a canonical price input, family, label,
and explicitly supplied target/obstacle roles. Unknown, wrong-unit, incompatible,
late or stale input blocks the catalog even if its supplied price is on the
wrong side. Complete supplied empty families are possible only as caller facts;
synthetic coverage does not prove that real obstacles are absent.

Directional levels are sorted and equal prices merged while keeping all labels
and input references. A nearest obstacle below 1R rejects. Any nearer blocking
obstacle prevents selecting T1 beyond it; the admitted T1 must have at least 1.5R.
T2 is the next distinct admitted level beyond T1 with at least 2.5R. No T1 rejects;
no T2 stays explicitly unavailable. Soft invalidation and runner remain undefined
rather than being invented. A READY result describes supplied geometry only.
The complete frozen request remains on each result for later storage/review.

The protected cases include FX-08/09 in both B modes, mirrored exact tick/0.35/
1/1.5/2.5 boundaries, closer non-target obstacles, duplicate prices, missing T1/T2,
all seven missing families, old/late/unknown coverage, each missing risk input,
identity/basis/unit/quality/future-time failures, path-mode mixing, zero/invalid
geometry, nonfinite prices, conflicting IDs, immutable results and later revisions.
The static case count is saved in M4_3_LOCAL_CHECKS.json; it is not a collected
or passing count.

## 3. Required protected proof

Run only the unchanged `scripts/testing/run_trade_alerts_contracts.py` with:

- `tests/trade_alerts_contracts`
- `tests/trade_alerts_contracts/test_structural_risk.py`
- `tests/test_models.py`
- `tests/test_schwab_client.py`
- `tests/test_wolf_macro_brain.py::test_stock_sector_etf`
- `tests/test_risk_reward.py`

The directory includes all prior model, data, feature, strategy, state/storage
and configuration contracts. The separate legacy risk checks preserve the existing
display helper's different behavior. No shared old source/test file changed, so
M4.2's additional database-call-site selection is not a new M4.3 dependency.
No test protection change or live application check is needed or authorized.
The full release suite and old listener-isolation gaps remain M18 obligations.

Each end-to-end case round-trips 20 supplied canonical Bars, runs actual M2.2
coverage, M3.1 ATR and M3.6 opening range, supplies the frozen feature to the real
selector, then round-trips a canonical candidate and writes a recording. The
long case expects B=101.02, E=101.03, stop=100.78, R=0.25, extension=0.04 and
T1/T2=101.50/102.00 with 1.88R/3.88R. The short case expects B=49.98, E=49.97,
stop=50.22 and targets 49.50/49.00 with the same risk and multiples. Coverage/path
failure and a later nearby obstacle cannot rewrite the original candidate.
The catalog, path coverage, score and candidate assembly are synthetic supplied
facts; this test neither detects a B-entry nor supplies missing full producers.

Each protected child must write `m43-structural-risk-long-proof.json` and
`m43-structural-risk-short-proof.json`. Corresponding files must match byte for
byte across runs and remain below 100,000 bytes each. Inspect their actual values,
the XML, isolation reports, output and summary. Require zero failures/errors/skips,
matching ordered test IDs, no unexpected isolation denials and clean cleanup.
The test launcher runs both children itself. Compilation is not test proof.

M4_3_LAUNCHER_LIMITATION.txt and M4_3_LOCAL_CHECKS.json record the actual local
attempt. If the launcher cannot start in this sandbox, the supervisor must run
this selection externally through the same unchanged launcher, publish readable
proof and a tested-file manifest, and return them to a fresh builder. That builder
must finish records/roadmap without source/test changes. Only then may the offline
row become [x]. The required gate in §4 must stay [!] and the records-only builder
must return **blocked**, with §5's independent next milestone, for review.

## 4. Required blocked M4.3 completion and reopening evidence

Status: **BLOCKED BY DEFINITION / DATA / separately supervised source access**.
This is required remaining M4.3 work, not an optional improvement.

- M0.3B/M3.5/M4.3 must adopt exact full structural-level producers, applicability
  and priority: ATR multiples, AVWAP anchors, profile allocation and confirmation,
  other confirmed structure and the permitted family/role treatment. The prepared
  M03B_ORB5_V1 packet remains PROPOSED. No version-scoped adoption exists here.
- The full anchor producer needs the actual latest final traded-minute reference,
  coverage from that bar to crossing, and the eligible trade or quote-last-trade
  path through trigger, with original times, eligibility, cancels/corrections and
  price/venue/adjustment compatibility. A supplied anchor and coverage flag prove
  no part of that source path. M0.2/M2.3/M3.5/M4.3 retain this dependency.
- Valid instrument increments, actual PM/prior/OR/ATR/AVWAP/profile/other-structure
  inputs, original availability and complete per-family coverage require dated
  source evidence. M0.2 and the existing full-data rows remain open.
- Required full service behavior includes soft invalidation and runner policy
  where applicable. Their approved definitions are not supplied by D-090 §6;
  retain them under M0.3/M4.3 and their playbook owners.

Reopen only after the exact affected definitions are adopted and synchronized,
and a separately authorized supervised step saves dated raw/normalized input,
per-family/path coverage, increments, source/correction conventions and the
resulting long/short boundary recordings through these same calculations. Use
existing local/Schwab/free evidence first. Name exact missing fields/dates/fidelity
and verify a bounded cost before any separately authorized purchase. No purchase
is needed for this offline prerequisite. D-091 stays $0 used and $0 reserved;
this unattended lane makes no paid or live request. Synthetic examples do not
establish provider coverage, executable trades or profitability.

## 5. Proposed independent next milestone

- [ ] **M4.4 — offline supplied confidence composition and attribution prerequisite**,
  only after M4.3's offline proof, saved blocked-gate handoff and independent review.

M1.3 already supplies ConfidenceBreakdown/ConfidenceComponent
records; M4.1 supplies the common interface. Build only a pure composition boundary
for explicitly supplied Setup/Context/Execution scores and explicitly supplied
versioned weights/factor contributions. Preserve the canonical records, original
feature/configuration references, finite 0–100 score bounds, exact supplied
weights, missingness and deterministic output. No default factor formula, score
cutoff, new weight choice, missing-factor renormalization or trading rule is
permitted. Keep approved per-playbook weights intact and label any test-only
policy. Persistence of the full calculation's attribution belongs to the existing
M5 event-store work; do not add a second store.

Prove hand-worked weighted arithmetic, unknown mandatory scores/factors,
wrong units/identity/future inputs, detached immutable factors, unchanged canonical
serialization, both directions and supplied features -> composition -> candidate
recording under the protected launcher. Full normalization/factor formulas,
missing-factor policy, calibration and actual source readiness remain required
blocked M0.3B/M4.4/M6/M16 gates. They cannot become defaults in the offline slice.
This work does not depend on selecting real structural levels or resolving §4.
The supervisor's independent reviewer must validate this scope and ordering.
Saved proposed `next_milestone`: **M4.4**.

## 6. Entire milestone paths and safety

- `consensus_engine/structural_risk.py`
- `tests/trade_alerts_contracts/test_structural_risk.py`
- `trade_alerts_build_docs/PROJECT_INDEX.md`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/TESTING_AND_VALIDATION.md`
- `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `trade_alerts_build_docs/M4_3_VERIFICATION.md`
- `trade_alerts_build_docs/M4_3_LOCAL_CHECKS.json`
- `trade_alerts_build_docs/M4_3_LAUNCHER_LIMITATION.txt`

All earlier owner changes, all eight playbooks, all nine canonical authorities,
all FR/capability rows and prior unfinished roadmap work remain. No configuration
switch is enabled. No application, broker/Discord call, message, order, restart,
deployment, paid fallback, Git mutation or controller operation is performed.

## 7. Actual local result and supervisor handoff

The unchanged protected launcher exited 1 at its initial temporary-directory
ownership step, before creating a child or collecting tests. Exact final error:

`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-5t1ncx6x'`

No XML, isolation report, passing count or M4.3 recording was produced. No
unprotected test or application run followed. Both source files pass Python 3.10
grammar and compilation checks. Static inspection finds **26 test functions,
105 cases after parameter expansion**; these are written cases, not executed
results. M4_3_LOCAL_CHECKS.json records the selectors, current hashes and checks.

The 90 local document links resolve. All prior blocked rows and earlier owner
file contents/ownership/modes are preserved. Added text passed the local sensitive
text and visible-time checks. Canonical records, configuration, D-090's packet,
the failing-test list and both protection files are unchanged. The complete
milestone delta is the 11 paths in §6.

New-file ownership restoration was attempted and returned `[Errno 22] Invalid
argument` for each new path. Exact per-file errors are in M4_3_LOCAL_CHECKS.json.
The supervisor must check host ownership alongside protected proof; sandbox
ownership display is not host proof. Existing file owners/modes did not change.
The read-only background-program check returned exactly:

`Failed to connect to bus: Operation not permitted (consider using --machine=<user>@.host --user to connect to bus of other user)`

No active-state claim is made. The workspace shortcut resolves correctly; the
read-only recent health/drift search exited 0 with zero matching lines. No restart
or live application test was attempted.

That local result is historical. Section 8 records the completed supervisor proof.

## 8. Fresh protected proof and records-only finalization

At 00:36:35 Pacific on 2026-09-07, the supervisor ran §3's unchanged protected
selection twice against the saved source. Both runs passed **892 tests** in
231.59 and 233.66 seconds, including all **105 M4.3 cases**. Both XML files have
zero failures, errors and skips. Ordered test IDs match.

Isolation and cleanup passed in both runs. There were no unexpected denials.
The long recordings are byte-identical at 13,164 bytes; the short recordings are
byte-identical at 13,146 bytes. Their saved values include the expected 0.25 risk,
0.04 extension and 1.88R/3.88R targets in both directions. The publication and
tested-file manifest match source hash
`978eb70b4b89d241b93f3884ac551305d297d4ec40eb92c98c856cec691ed5ba`.
No code, tests, configuration or protection file changed during finalization.

The offline row is complete. The separate required §4 definition/source row
remains blocked. Status for this handoff is **blocked**, with proposed independent
**next_milestone: M4.4** after review. No live access, purchase, activation or
profitability claim follows from this proof.
