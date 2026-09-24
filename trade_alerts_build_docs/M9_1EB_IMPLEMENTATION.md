# M9.1EB retained filled-candidate outcome connection — 2026-09-23 Pacific

M9.1EB adds one offline boundary after the accepted M9.1EA fill run. Only rows
with an exact `FILLED` D-106/D-107 result reach a caller-supplied accepted
outcome evaluator. The ORB5 path must return its accepted quote-filled outcome
type. The other three playbooks must return the accepted shared outcome type.
Each outcome must preserve the exact fill and may cite only records retained for
that candidate session.

Unfilled candidates, no-event rows and unavailable rows remain counted
exclusions. Genuine unknown outcomes stay unknown. Result-shard, held-out,
alert and live release remain off. The real retained rows remain unavailable
because confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity and parent facts are missing. Their dependent rules remain OFF and
untested. Synthetic complete records prove only this offline connection.

The recording test writes `m91eb-retained-first-four-outcome.json`. It commits
to the filled-candidate-only output and keeps every later release false. The
controller must collect and compare it in both fresh repeatability processes.

## Complete milestone delta

- `consensus_engine/retained_first_four_outcome.py`
- `tests/trade_alerts_contracts/test_retained_first_four_outcome.py`
- `trade_alerts_build_docs/M9_1EB_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

The protected focused launch was attempted once and stopped before collection
at the launcher's temporary-folder ownership step with:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-18ppl9ud'
```

It was not retried, and no application tests ran outside protection. Static
syntax checks passed. Applying the controller's actual repeatability predicate
to the test source selects
`tests/trade_alerts_contracts/test_retained_first_four_outcome.py::test_recorded_outcome_connection_is_deterministic_and_keeps_release_off`.
This is discovery eligibility only, not collected proof.

Fresh controller focused proof, broad acceptance and two-process recording proof
remain required. No source, final-result, held-out, alert, profit or live gate is
closed by this milestone.

## Historical controller verification handoff — 2026-09-23 Pacific

This proof predates the candidate-input repair below. Independent review found
an untested foreign-input path; these passes do not establish acceptance of the
repaired source or test. The original proof and failures remain preserved.

The supplied controller verification handoff supersedes the earlier
temporary-folder ownership stop. It tested the complete M9.1EB delta without
changing code, tests, configuration, dependencies, or protected inputs during
this records-only finalization.

- Focused: one protected run selected
  `tests/trade_alerts_contracts/test_retained_first_four_outcome.py` and
  `tests/trade_alerts_contracts/test_retained_first_four_outcome.py::test_recorded_outcome_connection_is_deterministic_and_keeps_release_off`.
  It passed 4 tests; JUnit time was 14.067 seconds and controller wall time was
  16.252 seconds.
- Broad acceptance: one protected run selected
  `tests/trade_alerts_contracts` for `unknown dependency impact; safe broad
  fallback`. It passed 4,218 tests; JUnit time was 981.507 seconds and
  controller wall time was 987.503 seconds.
- Repeatability: two fresh protected runs selected the controller-recorded 97
  deterministic/recording selectors, including
  `tests/trade_alerts_contracts/test_retained_first_four_outcome.py::test_recorded_outcome_connection_is_deterministic_and_keeps_release_off`.
  The controller recorded 97 tests and 420.732 seconds; the JUnit times were
  208.656 seconds for run 1 and 206.420 seconds for run 2. The two
  `m91eb-retained-first-four-outcome.json` artifacts matched byte-for-byte and
  each had SHA-256
  `e39b5534cefedc152ee617968b0590c98a3f399054c00057980e7799e6d54e11`.

The controller's published evidence is under
`/root/trade-alerts-builder/runs/20260923-124535-072001-build/`; its verified
source manifest has hash
`1524a9b556619e1c80297b0e51ee84343a29969479931ae5d8cb395cb159e191`.
The focused, broad, and repeatability artifacts all reported exit code zero.

This proof covers only the synthetic offline connection. Real retained rows
still lack confidence, halt, macro, catalyst, daily-history, quote-policy,
continuity, and parent facts. Their dependent rules remain OFF and untested.
Result-shard, held-out, alert, profit, and live release remain off.

## Review repair awaiting fresh protected proof — 2026-09-23 Pacific

The reported failure was in `_validate_outcome` in
`consensus_engine/retained_first_four_outcome.py`: the ORB5 branch checked only
`row.fill.input_record_ids`, leaving
`outcome.record.candidate.input_record_ids` unchecked. An outcome could retain
the exact accepted fill while citing a foreign candidate input. The existing
`test_rejects_wrong_outcome_type_changed_fill_or_opened_input` tested an opened
release flag, not that foreign-input case.

The repair checks both sets of ORB5 input identities against the retained
candidate session. The different test approach adds
`test_rejects_orb5_candidate_input_outside_retained_session`, which appends a
foreign ID only to the nested candidate and asserts the fill is unchanged and
its input IDs remain retained. The existing valid-input, fill-preservation,
exclusion and recording checks remain in place.

The focused protected launch stopped before collection at temporary-folder
ownership with this exact error:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-bi87wiho'
```

The sandbox failure was not retried; no application tests ran outside the
protected launcher. Static syntax checks are separate from protected proof.
The controller stage will supply fresh counts, timings, hashes and collected
test IDs. Required focused selection is
`tests/trade_alerts_contracts/test_retained_first_four_outcome.py`; the
reviewer-required broad selection remains `tests/trade_alerts_contracts`.
The controller must also collect
`tests/trade_alerts_contracts/test_retained_first_four_outcome.py::test_recorded_outcome_connection_is_deterministic_and_keeps_release_off`
in both fresh repeatability runs and compare
`m91eb-retained-first-four-outcome.json`. Earlier proof above is historical,
not proof of this code/test change. The complete milestone delta remains the
same four paths listed above. No protection, source inputs or release switches
changed. M9.1EC remains proposed only after M9.1EB acceptance.

## Final protected verification record — 2026-09-23 Pacific

The supplied controller verification handoff covers the repaired four-path
M9.1EB delta. The focused phase was one protected run of
`tests/trade_alerts_contracts`, selected because the builder named directly
affected checks. It collected 4,219 tests in 990.515 seconds. The broad
acceptance phase was one protected run of `tests/trade_alerts_contracts`,
selected for `unknown dependency impact; safe broad fallback`; it collected
4,219 tests in 976.57 seconds. Both phases reported exit code zero.

The repeatability phase ran two fresh protected processes over the
controller-recorded 97 deterministic/recording selectors, including
`tests/trade_alerts_contracts/test_retained_first_four_outcome.py::test_recorded_outcome_connection_is_deterministic_and_keeps_release_off`.
It collected 97 tests in 419.946 seconds. The two
`m91eb-retained-first-four-outcome.json` artifacts matched byte-for-byte; the
published artifact is under
`/root/trade-alerts-builder/runs/20260923-124535-072001-build/published-artifacts-d7be8e4b1a48`.

The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-124535-072001-build/verified-manifest.json`
with source hash
`e4c4cd868179ea44dcef07fd44eee88256c68f050e6f342e76a057452df60fb4`.
This records-only update changes no tested code, tests, configuration,
dependencies, or protected inputs. The real retained rows still lack
confidence, halt, macro, catalyst, daily-history, quote-policy, continuity,
and parent facts. Their dependent rules remain OFF and untested. Result-shard,
held-out, alert, profit, and live release remain off.
