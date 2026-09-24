# M9.1EM closed offline result shard — 2026-09-23 Pacific

## Scope

M9.1EM publishes the already-complete frozen M9.1EL D-108 record as a closed
offline result shard. It preserves the complete training, held-out and D-108
pass/fail evidence. It does not rerun D-108, send an alert or act live.

## Changed files

- `consensus_engine/retained_stage3_result_shard.py`
- `tests/trade_alerts_contracts/test_retained_stage3_result_shard.py`
- `trade_alerts_build_docs/M9_1EM_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`publish_retained_stage3_result_shard` accepts only the exact closed M9.1EL
record and a separately retained fingerprint of that accepted record. The
fingerprint uses sorted compact JSON, `ensure_ascii=True`, `allow_nan=False`
and UTF-8. Changed source evidence, changed D-108 measures, incomplete results,
wrong versions and any already-open later boundary fail closed.

The shard keeps the complete M9.1EL source record, selected candidate, exact
D-108 pass/fail result, every frozen measure and every source-gap OFF label.
The offline result-shard flag is true. Alert release and live action remain
false. The boundary does not recalculate D-108 while packaging its frozen
record.

## Focused checks and pending proof

The focused checks cover complete evidence preservation, exact fingerprint
binding, every closed-boundary rejection, changed-measure rejection and a
deterministic recording. The recording check writes
`m91em-retained-stage3-result-shard.json` for both fresh controller
repeatability processes.

The focused protected launch stopped before collection at the unchanged
launcher's temporary-folder ownership step with
`OSError: [Errno 22] Invalid argument`. It was not retried, and no application
test ran outside the protected launcher. Fresh controller focused, broad
acceptance and separate two-process recording proof and independent review
remain required.

## Open gates

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing. Their dependent rules
remain OFF and untested. The shard proves only its offline supplied-record
contract. It does not prove real held-out source coverage, a promotable edge,
alert readiness or live readiness. Source, promotion, alert and live gates
remain closed.

## Final protected verification record

Fresh controller proof passed for the closed offline result shard. The focused
phase ran once for `builder named directly affected checks` with the five
controller-recorded selectors in
`published-artifacts-bfe16149d1f8/summary.json`. It recorded 18 tests with zero
failures, errors, and skips. Its JUnit time was 13.909 seconds and controller
wall time was 16.644 seconds.

The broad acceptance phase ran once for `unknown dependency impact; safe broad
fallback` with `tests/trade_alerts_contracts`. It recorded 4540 tests with zero
failures, errors, and skips. Its JUnit time was 452.232 seconds and controller
wall time was 540.249 seconds.

The separate repeatability phase ran twice in fresh protected processes for
`recording output requires fresh-process comparison`. It used the
controller-recorded 77 selectors, including
`tests/trade_alerts_contracts/test_retained_stage3_result_shard.py::test_recorded_result_shard_is_deterministic_and_keeps_alert_and_live_closed`.
It recorded 108 tests with zero failures, errors, and skips. Run 1 JUnit time
was 88.645 seconds; run 2 JUnit time was 88.981 seconds; the two-run controller
wall time was 212.297 seconds. Both
`m91em-retained-stage3-result-shard.json` artifacts matched byte-for-byte with
SHA-256 `ede27465e4c0764c957d9c9e96d8e3141bdcdbe2d1aefada4e10336785d34457`.

The controller artifacts are
`/root/trade-alerts-builder/runs/20260923-203842-383030-build/published-artifacts-bfe16149d1f8`,
`/root/trade-alerts-builder/runs/20260923-203842-383030-build/published-artifacts-1c47dde181b5`,
and
`/root/trade-alerts-builder/runs/20260923-203842-383030-build/published-artifacts-a3ccd459b232`.
The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-203842-383030-build/verified-manifest.json`
with source hash
`456cb4d169e20d96e3d71aa61cc4b1a7e706cf7a23119c184f4e5101b43e67a6`.

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing. Their dependent rules
remain OFF and untested. Held-out source coverage, promotion, alert and live
release remain closed.
