# M9.1DY retained first-four sample restart — 2026-09-23 Pacific

M9.1DY adds one offline restart boundary after the accepted M9.1DX evaluator
drive. Each supplied retained training session is rebuilt as its canonical
evaluator plan. The boundary requires the input set to cover all four playbooks
for every exact planned session. It rejects duplicate playbook/session
identities, held-out tickers and any input that drops the required source-gap
off switches.

Incomplete plans need no owner settings and no recorder. They return their
exact `UNAVAILABLE` result with zero evaluated steps and zero transitions.
Complete plans must have an exact owner-settings and recorder key before any
owner is driven. The M9.1DX boundary still requires every proposed transition
to be acknowledged unchanged before state advances. A missing dependency or
changed acknowledgment stops the restart instead of returning a partial sample
result.

The real retained fixture still contains confidence, halt, macro, catalyst,
daily-history, quote-policy, continuity and parent gaps. Its four first-playbook
rows therefore remain unavailable. Their dependent rules stay OFF and
untested. Synthetic complete records exercise all four canonical owner types;
they prove only the offline restart contract. The result type has fixed false
boundaries for candidate release, fill and return calculation, result-shard
release and held-out access. No alert or live action is possible here.

The recording test writes
`m91dy-retained-first-four-sample-restart.json`. It contains both the genuine
unavailable fixture result and the synthetic four-owner result, confirms exact
transition acknowledgment and records every later release boundary as false.
It is intended for the controller's two-fresh-process recording comparison.

## Protected test status

The protected focused launch was attempted once and stopped before collection
at the launcher's temporary-folder ownership step with:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-_1_4i_zo'
```

It was not retried. No application tests ran outside protection. The controller
must provide fresh focused, broad acceptance and two-process recording proof.

## Complete milestone delta

- `consensus_engine/retained_first_four_evaluator_drive.py`
- `consensus_engine/retained_first_four_sample_restart.py`
- `tests/trade_alerts_contracts/test_retained_first_four_sample_restart.py`
- `trade_alerts_build_docs/M9_1DY_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

The focused selector is
`tests/trade_alerts_contracts/test_retained_first_four_sample_restart.py`.
The controller broad stage and discovered repeatability selectors remain
required.

## Protected-proof finalization

The earlier temporary-folder ownership stop is historical. Fresh controller
proof passed with zero failures, errors, and skips while keeping protected
isolation and cleanup intact. Focused ran
`tests/trade_alerts_contracts/test_retained_first_four_sample_restart.py` once:
6 checks, pytest time 16.66 seconds, JUnit time 16.668 seconds, and controller
wall time 18.848 seconds. Broad acceptance ran
`tests/trade_alerts_contracts` once because of unknown dependency impact: 4,202
checks, pytest time 966.98 seconds, JUnit time 966.767 seconds, and controller
wall time 973.49 seconds.

Two fresh repeatability processes ran the controller's published selector list:
94 checks per run, pytest times 201.53 and 202.54 seconds, JUnit times 201.527
and 202.534 seconds, and controller wall time 410.142 seconds. The list
includes `tests/trade_alerts_contracts/test_retained_first_four_sample_restart.py::test_recorded_sample_restart_is_deterministic_and_keeps_later_release_off`.
The `m91dy-retained-first-four-sample-restart.json` hashes matched at
`3a14428816b018acccc32b808a792356c5c36c2c0ead338ae82f86470726a088`.

The focused, broad, and two repeatability artifacts are respectively
`/root/trade-alerts-builder/runs/20260923-085206-109568-build/published-artifacts-565104438195`,
`/root/trade-alerts-builder/runs/20260923-085206-109568-build/published-artifacts-27fad24c9445`,
and
`/root/trade-alerts-builder/runs/20260923-085206-109568-build/published-artifacts-273f116abb6b`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-085206-109568-build/verified-manifest.json`;
its source hash is
`cca3217aa11cc683b4a1087df2cd21cdfcbe37a047910b9b53617a82a8fd0016`.
This finalization changes only this record and the roadmap. All genuine retained
gaps remain unavailable, their dependent rules remain OFF and untested, and
candidate, fill, return, result-shard, held-out, alert, and live release remain
off.
