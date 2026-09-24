# M9.1DU fail-closed retained evaluator run — 2026-09-23 Pacific

This bounded step consumes each M9.1DT retained first-four evaluator plan and
returns one immutable `UNAVAILABLE` result when any mandatory input is missing.
It preserves the evaluator binding, retained source IDs and every named missing
input. It records zero evaluated steps and zero transitions.

The run also reads the canonical step and parent records. Removing a missing
label cannot make an incomplete plan run. Missing confidence blocks the first
two playbooks. Missing evaluator steps and parent evidence block the reversal
and first-pullback playbooks. A mismatched evaluator name is rejected.

No strategy owner is constructed or advanced. Complete canonical confidence,
halt, macro, catalyst, daily-history, quote-policy, continuity and parent facts
do not exist in the retained packet. Their dependent rules remain OFF and
untested under D-104. No exact sample, candidate, fill, return, result shard,
held-out name or live action is released.

Focused coverage is
`tests/trade_alerts_contracts/test_retained_first_four_evaluator_run.py`. Its
recording is `m91du-retained-first-four-evaluator-run.json`. Fresh protected
focused, broader acceptance and two-process recording proof remain required.

The initial protected focused launch was tried once. It stopped before
collection at the launcher's temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-4kwxj61x'
```

The reproduced sandbox failure was not retried or bypassed. No application
test ran outside the protected launcher. A static syntax check passed, but it
is not protected acceptance. This is historical evidence; the later controller
publication below supplies the required protected proof.

## Protected-proof finalization

The controller published protected proof at
`/root/trade-alerts-builder/runs/20260923-051950-083194-build/`. The focused
phase ran `tests/trade_alerts_contracts/test_retained_first_four_evaluator_run.py`
once: 4 checks in 7.376 seconds. Its pytest line is `4 passed in 5.40s`; JUnit
separately records `tests="4"`, `errors="0"`, `failures="0"`, `skipped="0"`,
and `time="5.406"`.

The broader acceptance phase ran `tests/trade_alerts_contracts` once: 4012
checks in 837.492 seconds. Its pytest line is `4012 passed in 830.93s
(0:13:50)`; JUnit separately records `tests="4012"`, `errors="0"`,
`failures="0"`, `skipped="0"`, and `time="830.736"`.

The repeatability phase ran twice with 90 checks per fresh process, in 377.34
seconds total. Its JUnit times are `186.169` and `185.095`; both have zero
errors, failures, and skips. The recorded
`m91du-retained-first-four-evaluator-run.json` hash is
`d3d50f625a47de1794a097eb950cb3d314743091f332f02cfd29952669f6b4e2` in
both fresh runs. The controller's tested-source hash is
`a740c851c0cd9b353b17dddc0882c06e3fb05c3e6bd93e9c30a87aa0f4fad5fb`.
All protected isolation records report no unexpected denials and completed
cleanup. The unavailable inputs and every dependent OFF and untested rule stay
unchanged; this proof releases no exact sample or live action.
