# M9.1DW retained first-four evaluator owners — 2026-09-23 Pacific

M9.1DW adds one construction boundary for the existing first-four replay
owners. It reruns the M9.1DV admission gate and constructs the exact owner type
only when that gate returns `READY`. The owner uses the exact session carried
by the admitted inputs. The policy types must match the admitted evaluator. The
first-pullback policy direction and impulse window are also checked before its
owner is created.

The real retained plans still contain confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity and parent gaps. They are rejected
before owner construction. Their dependent rules remain OFF and untested under
D-104. Complete synthetic records cover all four owner types in both
directions, plus unavailable inputs and mismatched policy and impulse
window cases. The synthetic records prove only this offline construction
contract. The owners are not evaluated or advanced. No exact sample,
candidate, fill, return, result shard, held-out name or live action is released.

The new recording writes
`m91dw-retained-first-four-evaluator-owners.json`. It records the eight
synthetic owner types, initial states and declared required inputs, with zero
evaluated steps and zero confirmed transitions. The test naturally qualifies
for the controller's two-fresh-process recording comparison.

The earlier protected focused launch stopped before collection with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-4f1nt52o'` at
temporary-folder ownership. It was not retried. That stop is historical.

## Protected-proof finalization

The controller then ran the protected focused selectors
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_owner.py` and
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_owner.py::test_recorded_owner_construction_is_deterministic_and_does_not_advance`
once: 14 checks, pytest time 17.58 seconds, JUnit time 17.580 seconds and
controller wall time 19.712 seconds. Broad acceptance ran
`tests/trade_alerts_contracts` once: 4,182 checks, pytest time 946.77 seconds,
JUnit time 946.557 seconds and controller wall time 953.184 seconds. The
controller selected the broad phase for unknown dependency impact.

The controller's published repeatability selector list ran in two fresh
processes: 92 checks per run, with pytest times 197.96 and 190.64 seconds and
JUnit times 197.956 and 190.636 seconds. The controller wall time for the
two-run phase was 394.817 seconds. The
`m91dw-retained-first-four-evaluator-owners.json` hash was
`4d48b8c3b8daa86b52eaf3be92eb14ecda9c6fce77d3c080ddae8923f62fcbdd` in
both runs. All published runs had zero failures, errors and skips, preserved
isolation, and completed cleanup. Artifacts are
`published-artifacts-0c58ef1a75d1/run-1`,
`published-artifacts-969c83180324/run-1`, and
`published-artifacts-b7eb262fb26f/run-1` plus `run-2` under the controller
build run. The controller's complete tested-source manifest is
`verified-manifest.json`; its tested-source hash is
`a73d299a80ac2c042cc0b189a9652106025db86458c2fbfceab76e35d91a727d`.

## Complete milestone delta

- `consensus_engine/retained_first_four_evaluator_owner.py`
- `tests/trade_alerts_contracts/test_retained_first_four_evaluator_owner.py`
- `trade_alerts_build_docs/M9_1DW_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

The focused selector is
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_owner.py`.
The controller broad stage and discovered repeatability selectors remain
required.
