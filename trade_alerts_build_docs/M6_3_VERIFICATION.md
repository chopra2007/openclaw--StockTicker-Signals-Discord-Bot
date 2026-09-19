# M6.3 `CRVOL_ORB5` risk, targets and confidence at one frozen trigger

Date: 2026-09-10 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` approved-rule gate and
the `[!]` structure and source gate in ROADMAP section 31 stay open, and the M4.3
catalog and M4.4 factor gates stay open with their existing owners.

`consensus_engine/orb5_risk_confidence.py` composes three supplied results at one
evaluation instant: the M6.2 `TriggerAssessment`, the M4.3 `RiskTargetResult` and
the M4.4 `ConfidenceResult`. It re-checks that both supplied results describe this
frozen attempt at this exact instant, then reports the stop, targets and
confidence they already carry. It reads no clock, fetches no data, opens no
database, stores nothing, assembles no alert candidate and sends nothing.

`READY` here means the supplied composition held together at one instant in a
test process. It is not an alert, an approved rule, evidence of source coverage,
a quality cutoff or permission to act.

## 1. Why nothing is hardcoded

The M6.1 and M6.2 gate rows say the exact `CRVOL_ORB5` values come from
`M03B_ORB5_V1`, which is still PROPOSED. M6.3 keeps that rule:

- The module calculates no stop, no target, no R multiple, no factor, no score
  and no weight. Every one of those numbers arrives inside the supplied M4.3 and
  M4.4 results, which already carry their own definition versions and catalog.
- **No quality cutoff is applied.** A minimum confidence for this strategy is a
  rule-bearing number that no approved definition supplies, so the composition
  reports `CONFIDENCE_FLOOR_UNDEFINED` in its `unavailable` tuple instead of
  filtering. A final score of 0 and a final score of 100 both compose to `READY`.
- The caller names its own `strategy_version` and `definition_reference`. Naming
  them neither adopts a proposed rule nor claims the referenced definition was
  approved.
- `D-090` section 6's two undefined structures stay named: the geometry's own
  `SOFT_INVALIDATION_UNDEFINED` and `RUNNER_UNDEFINED`, plus `T2_UNAVAILABLE`
  when only one admitted target cleared the supplied reward minimum, are carried
  through to the composed result.
- A test asserts the module defines no numeric constant of its own.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **`Orb5OutcomeRequest`.** One composition of one frozen trigger with the two
  supplied results, the caller's strategy version and its definition reference.
  Each part must be the canonical record type; blank, `UNKNOWN` and
  `UNSPECIFIED` labels are refused.
- **The trigger gate.** Only a trigger whose supplied gates all passed
  (`ALERT_TRIGGERED`) carries risk, targets and confidence. An unknown trigger
  input keeps the outcome `UNAVAILABLE` and names the first unknown gate; a
  definite refusal, including an invalidated attempt, keeps it `REJECTED` and
  names the failing gate. The frozen crossing references are retained.
- **The M4.3 geometry, re-checked here.** M6.2 checked its own copy for the
  trigger decision; this boundary repeats the identity checks on the result it
  was actually handed, so a later, mirrored, differently framed or foreign-arm
  selection cannot arrive as this trigger's geometry. The supplied result must
  use this arm's D-090 variant, this direction, this crossing instant, this
  evaluation instant and this frozen boundary. A `READY` label with no risk or no
  target, an entry inside the frozen boundary, a stop on the wrong side of the
  entry or a target that is not beyond the entry never passes.
- **The M4.4 confidence for this instant.** The supplied composition must belong
  to `CRVOL_ORB5`, the caller's named strategy version, this direction and this
  evaluation instant, and must itself be `READY`. A missing score or a missing
  declared factor stays an explicit unknown; it never becomes a zero.
- **Per-gate reporting.** Each field is populated only by the gate that passed
  for it, so a refused or unknown input leaves its own facts absent instead of
  half-stated. A complete confidence never repairs refused geometry, and complete
  geometry never repairs an unknown confidence. Any unknown keeps the whole
  outcome `UNAVAILABLE`; a definite refusal with nothing unknown is `REJECTED`.
- **Exact comparison.** Entry, stop, target and boundary comparisons use
  `Fraction(str(value))`, so the frozen boundary and the entry beside it do not
  move on binary floating-point representation.
- **A deterministic compact record.** `as_dict`/`to_json` render the gates, the
  frozen candidate, the stop, the targets with their labels and input
  references, the confidence with its factors, and what stays undefined. The same
  supplied inputs render the same bytes.

Changed files: `consensus_engine/orb5_risk_confidence.py` (new),
`tests/trade_alerts_contracts/test_orb5_risk_confidence.py` (new).
No existing module, test, configuration, migration or protected launcher file
changed. `consensus_engine/orb5_trigger.py` still hashes to `eba26708…` and the
launcher to `a4ffdd55…` with child `85285dee…`, exactly as M6.2 recorded them.

## 3. Protected proof — 2026-09-10 Pacific

Every figure below is copied from the controller's published artifacts. All runs
used the unchanged protected launcher
`scripts/testing/run_trade_alerts_contracts.py` (`a4ffdd55…`, child
`85285dee…`), with zero failures, errors and skips, no unexpected isolation
denials, `pytest_exit_code` 0 and passing cleanup in every run.

The controller published three separate phases, each its own artifact set with
its own source directory. Three differently named figures are quoted per run:
pytest's own "passed in" line from that run's `output.txt`, the JUnit
`results.xml` suite `time` attribute, and the controller's wall figure for that
phase.

**The two full-selection runs.** Both ran the whole
`tests/trade_alerts_contracts` selection, each as a single run in its own fresh
process and its own published set:

- **Focused phase** (set `317a1f7c0550`, source `/tmp/trade-alerts-m04-19hrzllq`,
  1 run, "builder named directly affected checks"): **1,696 tests passed in
  330.37 seconds** by pytest's own figure (JUnit 330.303 s, controller wall
  333.567 s), exit code 0, inside the 420-second limit.
- **Acceptance phase** (set `5f8e5ed9e7d0`, source
  `/tmp/trade-alerts-m04-4im0o63e`, 1 run, "unknown dependency impact; safe broad
  fallback"): the same selection — **1,696 tests passed in 334.71 seconds**
  (JUnit 334.636 s, controller wall 338.006 s), exit code 0, inside the same
  limit.

The 1,696 tests are the previously accepted 1,616 plus the **80 new M6.3 cases**
in `tests/trade_alerts_contracts/test_orb5_risk_confidence.py`. Each run's
`results.xml` shows all 80 passing, taking 4.338 and 4.361 seconds of case time.
The ordered test IDs of the two runs are identical. Each of these two runs wrote
40 artifact files, including `pipeline-obs.jsonl`; comparing the two sets, 37 of
the 40 are byte-identical and only `output.txt`, `results.xml` and
`pipeline-obs.jsonl` differ, in timing text and observation timestamps.

**Repeatability phase** (set `c0cb382def13`, source
`/tmp/trade-alerts-m04-sj_kmihs`). This is a separate, narrower selection: the
**22 recording node IDs**, **34 tests per run**, run **twice in fresh
processes**, because recording output requires a fresh-process comparison. Run 1
passed 34 tests in 107.84 seconds (JUnit 107.842 s) and run 2 in 106.49 seconds
(JUnit 106.497 s); both exit code 0, controller wall 218.021 seconds for the
phase. The two M6.3 cases in this selection took 1.664 and 1.667 seconds. Ordered
test IDs match. Each of these runs wrote **39 artifact files** and no
`pipeline-obs.jsonl`; **37 are byte-identical** and only `output.txt` and
`results.xml` differ, and only in timing text. The M6.3 recordings match exactly
across both repeatability runs and across both full-selection runs:

| Artifact | Bytes | SHA-256 |
|---|---|---|
| `m63-orb5-risk-confidence-long-proof.json` | 3,045 | `3ca696f4bffa751e0c79c5e37f24376b3ac8930876ec134c2cd865e48f6298e6` |
| `m63-orb5-risk-confidence-short-proof.json` | 3,039 | `6a0baf9e7065cc451ecc9fa674a96c3a06866105e7ff1e1c908c77c7207f2373` |

Every earlier milestone recording in the same runs is unchanged, including the
M6.2 trigger recordings (`cd9817b4…` 5,065 bytes and `e8a84855…` 5,051 bytes),
the M6.1 eligibility recording (`f7e25fc2…`, 3,832 bytes) and the M5.3 replay
fingerprint (`2356f8e1…`), so this addition altered no accepted output.

The required selection was the whole `tests/trade_alerts_contracts` directory,
because the new test module imports fixtures from `test_orb5_trigger`,
`test_orb5_eligibility`, `test_structural_risk` and `test_strategy_interface`.

A builder-local run of the unchanged launcher was also made for convenience. It
was never published, so no figure from it is quoted here and it is no part of the
proof above.

Tested milestone files: `consensus_engine/orb5_risk_confidence.py` `36a73ed9…`
and `tests/trade_alerts_contracts/test_orb5_risk_confidence.py` `d97abefc…`, as
recorded in the supervisor's verified manifest (source hash `61373220…`).
`M6_3_LOCAL_CHECKS.json` records the full hashes, per-run figures and checks.

## 4. What the new cases cover

- Supplied record contracts: every part of the request must be canonical and
  explicitly labelled; the composition refuses anything but its own request type;
  gate names, statuses, reasons and input references are checked; composed
  results and their gates are immutable; the module defaults no number.
- The composed `READY` path for both directions and both participation arms: the
  reported stop, targets, target labels, target input references, extension and
  confidence are exactly the supplied ones, the entry stands at or beyond the
  frozen boundary with the stop behind it, both targets lie beyond the entry, and
  the caller's own weights and definition reference are preserved.
- What stays undefined: the confidence floor always, soft invalidation and the
  runner always, and `T2_UNAVAILABLE` when only one admitted target cleared.
- No quality cutoff: final scores of 0, 1 and 100 all compose to `READY`.
- The trigger gate: a failing acceptance window, an unknown participation input
  and an invalidated attempt each keep the outcome out of `READY`, with the right
  status and named reason for each.
- The geometry gate: foreign arm, foreign direction, another crossing, another
  instant, another boundary, an unknown boundary value, a refused selection, an
  incomplete selection, a `READY` label without levels, an entry inside the frozen
  boundary, a stop on the wrong side and a target behind the entry.
- The confidence gate: another strategy, another strategy version, another
  direction, another instant, and each of the six missing scores or declared
  factors.
- Mixed outcomes: one refusal beside one unknown stays `UNAVAILABLE`, and each
  reported reason keeps its own gate and status.
- End to end for long and short: the M6.2 owner, the M4.2 transition engine with
  the M4.2 SQLite store and an idempotent append into the M5.1 research event
  store, then the composed outcome at that recorded trigger, with the compact
  recording written per direction and the repeated composition byte-identical.

## 5. Boundaries kept open

- [x] **M6.3 offline risk, targets and confidence:** implemented and proved
  offline for independent review.
- [!] **M6.3 approved-rule gate:** the confidence floor, the component weights,
  the factor roster and the reward minimums for this strategy still need
  `M03B_ORB5_V1`, `M4.3`'s catalog gate and `M4.4`'s factor gate. A passing
  supplied policy adopts no number.
- [!] **M6.3 structure and source gate:** the anchor path, the ATR, the AVWAP,
  the profile and the other structural families, the soft invalidation and the
  runner, and the upstream score producers remain blocked under M3.2, M4.3, M4.4
  and M0.2/M2.3. The supplied fixtures here establish none of them.
- [ ] Replay and synthetic scenario coverage for this strategy belongs to M6.4.
  Candidate assembly, suppression, deduplication, the options path and delivery
  retain their existing owners.

## 6. Exact next milestone

**M6.4 — replay and synthetic tests for `CRVOL_ORB5`**, now an open row in
ROADMAP section 31: clean catalyst ORB, low-RVOL fakeout, resistance, wide OR,
stale and short, over the M5.3 replay runner, still on supplied inputs. Its
rule-bearing branch stays gated by the same PROPOSED `M03B_ORB5_V1` definition.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
