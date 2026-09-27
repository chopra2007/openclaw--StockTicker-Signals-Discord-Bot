# M9.1EP saved-market-data qualification — 2026-09-25 Pacific

## Result

The first coherent M9.1EP part is complete. The two existing saved minute-bar
files now have one reproducible, read-only coverage and defect audit in
`M9_1EP_SAVED_DATA_QUALIFICATION.json`. The audit binds the saved files to the
prior raw-file inventory, prior capability record and the two extraction
scripts by SHA-256. It made no network call and spent nothing.

The audit found 19,653,306 EQUS.MINI rows and 20,625,054 XNYS.PILLAR rows across
60 symbols. Both files have zero duplicate keys, zero out-of-order keys, zero
invalid OHLC rows, zero non-finite or nonpositive prices, and zero negative or
zero-volume rows. Their common 40-date sample has 878,139 matching
symbol-minute rows. The median close difference is 0.9013068949981218 basis
points; the 95th and 99th percentiles are 5.123153516952694 and
10.034950548642984 basis points.

Coverage is incomplete. EQUS.MINI has 13,281 complete regular-session
symbol-dates and 37,705 incomplete ones, with 666,650 missing regular minutes.
XNYS.PILLAR has 15,264 complete symbol-dates and 39,144 incomplete ones, with
649,525 missing regular minutes. A missing minute remains a missing trade bar;
the audit does not fill it.

## Safety and evidence boundary

Only bar-native OHLCV and saved minute identity are observed. Historical
bid/ask is absent. Original availability, corrections, finality,
point-in-time membership, historical borrow, complete option-chain execution
and adjustment provenance remain gaps. Under D-104, all rules depending on
those facts stay OFF and untested. The prior records describe the minute files
as raw and unadjusted, but the saved parquet alone cannot prove the complete
adjustment history, so the new audit does not upgrade that fact.

No held-out strategy result was opened in this part. No source was qualified
for executable fills, no strategy was promoted, and no alert, live action,
provider call, deployment or spending occurred.

## Verification and handoff

The new focused protected selector is
`tests/trade_alerts_contracts/test_saved_market_data_audit.py`. The launcher
stopped before collection at its unchanged temporary-folder ownership step
with `OSError: [Errno 22] Invalid argument`; it was not retried and no
application test ran outside the protected launcher. Static Python compilation
passed. The generated real-data audit completed successfully.

M9.1EP is larger than one session. M9.1EQ must connect only the honestly
supported bar-native inputs for the frozen first four playbooks to this audited
inventory, publish the exact enabled/disabled input matrix, and keep the
held-out result closed until that binding and its protected proof pass.
