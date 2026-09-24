# M9.1DF implementation record — 2026-09-22 Pacific

M9.1DF adds `retained_first_four_candidate_run.py`. It combines the accepted
first-two and remaining-two producer maps and sends them through the accepted
training-nine candidate-event isolation boundary. The remaining producers call
the accepted M0.3D and M0.3E parent scans. Their exact candidate, no-event or
unavailable decisions and retained source identities pass through unchanged.

The retained source still lacks required original-availability, finality,
correction, halt, complete trade-coverage, numeric parent, quote-decision and
confidence facts. Those gaps stay named. Their dependent rules remain OFF and
untested. The run does not calculate fills, returns or supervised packages and
does not open held-out names.

Focused coverage is
`tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py`. It
checks all four concrete producers across the frozen training nine, exact
source identities, parent-scan unavailable reasons and the D-104 off switches.
Its recording selector is
`tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py::test_recorded_first_four_candidate_run_is_deterministic`.
The recording output is
`m91df-retained-first-four-candidate-run-proof.json`; the controller must
collect and compare it in both fresh repeatability processes.

Complete M9.1DF delta:

- `consensus_engine/retained_first_four_candidate_run.py`
- `tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py`
- `trade_alerts_build_docs/M9_1DF_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Fresh protected focused, broad acceptance and two-process recording proof is
required. No test count, timing, hash or pass is claimed before the controller
publishes it. M9.1DG is the next bounded step after independent acceptance: run
the concrete boundary on the already retained training-nine inputs and record
the exact candidate, no-event and unavailable totals without opening held-out
names or calculating fills, returns or supervised packages.

The protected focused launcher was tried once with the focused test file. It
stopped before collection at line 27 during the unchanged temporary-directory
ownership change with `OSError: [Errno 22] Invalid argument:
'/tmp/trade-alerts-m04-ytnucldo'`. It was not retried, and no application test
ran outside protection. The controller must publish all passing figures and
compare the named recording in two fresh processes.

## Final protected proof — 2026-09-22 Pacific

This records-only finalization uses controller protected proof with source hash
`bb59cf7e57a9cb1abd29b53690f62b05be893b976e9f951bcd70f60ea26c33a6`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260922-130729-064978-build/verified-manifest.json`.
The complete milestone delta remains the four paths listed above; only this
record and `ROADMAP.md` changed after the tested source.

Focused: `tests.phase=focused`, `tests.runs=1`, `tests.test_count=3`,
`tests.wall_seconds=33.835`, and
`tests.selection_reason="builder named directly affected checks"`; selectors:
`tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py` and
`tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py::test_recorded_first_four_candidate_run_is_deterministic`.
Its protected artifact directory is
`/root/trade-alerts-builder/runs/20260922-130729-064978-build/published-artifacts-53d42f6e2d9c`.
The pytest JUnit time was `31.898` seconds.

Acceptance: `tests.phase=acceptance`, `tests.runs=1`, `tests.test_count=3903`,
`tests.wall_seconds=733.695`, and
`tests.selection_reason="unknown dependency impact; safe broad fallback"`;
selector: `tests/trade_alerts_contracts`. Its protected artifact directory is
`/root/trade-alerts-builder/runs/20260922-130729-064978-build/published-artifacts-a5bd46894314`.
The pytest JUnit time was `729.207` seconds.

Repeatability: `tests.phase=repeatability`, `tests.runs=2`,
`tests.test_count=85`, `tests.wall_seconds=286.832`, and
`tests.selection_reason="recording output requires fresh-process comparison"`.
Its exact published selector list includes
`tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py::test_recorded_first_four_candidate_run_is_deterministic` and is recorded in
`/root/trade-alerts-builder/runs/20260922-130729-064978-build/published-artifacts-a0c72532f422/summary.json`.
Its protected artifact directory is
`/root/trade-alerts-builder/runs/20260922-130729-064978-build/published-artifacts-a0c72532f422`.
The two pytest JUnit times were `140.671` and `141.801` seconds. The two fresh
`m91df-retained-first-four-candidate-run-proof.json` files match SHA256
`7773fc24f68756b8ff9185f1d619049bd82ed5ad6fff7a19ce820dee5729a6f8`.

All three protected phases exited 0 with stable output and zero failures,
errors and skips. This remains an offline synthetic-record contract only.
Original availability, finality, correction, halt, complete trade coverage,
numeric parent, quote-decision and confidence gaps keep their dependent rules
OFF and untested. No fill, return, supervised package, held-out result, source,
final-result, profit or live claim follows.
