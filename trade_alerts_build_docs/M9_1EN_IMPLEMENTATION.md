# M9.1EN parent engineering-pilot disposition — 2026-09-23 Pacific

## Scope

M9.1EN publishes the parent M9.1 engineering-pilot disposition from the exact
closed M9.1EM result shard. It records the shard's exact offline D-108 pass or
fail result. It keeps every source-gap dependent rule OFF and untested. It does
not promote a strategy, send an alert or act live.

## Changed files

- `consensus_engine/retained_stage3_pilot_disposition.py`
- `tests/trade_alerts_contracts/test_retained_stage3_pilot_disposition.py`
- `trade_alerts_build_docs/M9_1EN_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Contract

`publish_retained_stage3_pilot_disposition` accepts only the exact closed
M9.1EM shard and a separately retained fingerprint of that accepted shard. The
fingerprint uses sorted compact JSON, `ensure_ascii=True`, `allow_nan=False`
and UTF-8. The function also rebuilds the shard from its frozen M9.1EL source.
Changed nested evidence, changed result fields, wrong versions, incomplete
shards and any open alert or live boundary fail closed.

The output preserves the complete source shard, selected candidate, exact
D-108 result and every source-gap OFF label. Its disposition is
`ENGINEERING_PILOT_ONLY`. Engineering-pilot completion is true. Promotion,
alert and live release remain false.

## Pending proof

Focused checks cover complete evidence preservation, exact fingerprint binding,
source reconstruction, changed-result rejection, every closed release boundary
and deterministic recording. The recording check writes
`m91en-retained-stage3-pilot-disposition.json` for both fresh controller
repeatability processes.

Fresh controller focused, broad acceptance and separate two-process recording
proof and independent review remain required.

The focused protected launch stopped before collection at the unchanged
launcher's temporary-folder ownership step with
`OSError: [Errno 22] Invalid argument`. It was not retried, and no application
test ran outside the protected launcher. Static syntax and whitespace checks
passed. The controller must supply the fresh protected proof.

## Open gates

Accepted exit-side costs, confidence, halt, macro, catalyst, daily-history,
quote-policy, continuity and parent facts remain missing. Their dependent rules
remain OFF and untested. Original availability, corrections/finality and
point-in-time membership remain recorded gaps. This disposition proves only
the closed offline supplied-record engineering contract. It does not prove real
held-out source coverage, a promotable edge, alert readiness or live readiness.
Promotion, source, alert and live gates remain closed.

## Final protected verification record

Fresh controller proof passed for the parent engineering-pilot disposition. The
focused phase ran once for `builder named directly affected checks` with the
three controller-recorded selectors in
`published-artifacts-cfda8faf69df/summary.json`. It recorded 16 tests with zero
failures, errors, and skips. Its JUnit time was 14.138 seconds and controller
wall time was 16.718 seconds.

The broad acceptance phase ran once for `unknown dependency impact; safe broad
fallback` with `tests/trade_alerts_contracts`. It recorded 4555 tests with zero
failures, errors, and skips. Its JUnit time was 457.610 seconds and controller
wall time was 557.117 seconds.

The separate repeatability phase ran twice in fresh protected processes for
`recording output requires fresh-process comparison`. It used the controller's
published 83-selector list, including
`tests/trade_alerts_contracts/test_retained_stage3_pilot_disposition.py::test_recorded_pilot_disposition_is_deterministic_and_keeps_every_release_closed`.
It recorded 109 tests with zero failures, errors, and skips. Run 1 JUnit time
was 100.852 seconds; run 2 JUnit time was 102.544 seconds; the two-run
controller wall time was 212.264 seconds. Both
`m91en-retained-stage3-pilot-disposition.json` artifacts matched byte-for-byte
with SHA-256 `16d2b0aab56307fa187c403faf157dfbe17936beba3eef870d5d22a6029cc9ee`.

The controller artifacts are
`/root/trade-alerts-builder/runs/20260923-205906-558794-build/published-artifacts-cfda8faf69df`,
`/root/trade-alerts-builder/runs/20260923-205906-558794-build/published-artifacts-cc6c0f23b53e`,
and
`/root/trade-alerts-builder/runs/20260923-205906-558794-build/published-artifacts-fc0e66851bce`.
The tested-source manifest is
`/root/trade-alerts-builder/runs/20260923-205906-558794-build/verified-manifest.json`
with source hash
`15955883694930a36ba68df870360acf8e3e00fbea5fb9f52a0434532f695e83`.
