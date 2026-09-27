# M9.1EQ audited saved-bar input binding — 2026-09-25 Pacific

## Result

`M9_1EQ_AUDITED_INPUT_BINDING.json` binds the unchanged M9.1EP audit to the
existing first-four adapter-count runner. Eleven inputs that need only observed
one-minute OHLCV, event time and complete required windows are conditionally
enabled. Eleven inputs remain `OFF_UNTESTED` because their daily, quote,
15-second tape, exact ATR, finality or unresolved VWAP convention is absent.

The binding refuses to upgrade absent bid/ask, unknown finality or unproven
adjustment history. It also checks that all six D-104 source gaps remain gaps,
that the two audited file identities are distinct, and that the audit records
zero network use and zero spend. The held-out evaluation remains closed. No
price, strategy result, alert, order, provider call, deployment or live switch
was opened.

## Controller verification record

The earlier local ownership error is historical. The controller later completed
the protected checks with isolation and no failures, errors or skips. The
original tested-source manifest is
`/root/trade-alerts-builder/runs/20260925-023518-211608-build/verified-manifest.json`
with source hash
`e490eeb5a4aa5803332b9669856ad543753025123856de78c8b087c5f6a7119b`.
These final record edits do not change tested code, tests, configuration or
protected inputs.

The focused phase ran once with selectors
`tests/trade_alerts_contracts/test_saved_market_data_audit.py` and
`tests/trade_alerts_contracts/test_saved_market_data_binding.py`: 7 tests,
controller wall time 4.702 seconds. Its published artifact is
`/root/trade-alerts-builder/runs/20260925-023518-211608-build/published-artifacts-1a364c1dd11e`.

The broad acceptance phase ran once with selector
`tests/trade_alerts_contracts`: 4,562 tests, controller wall time 1094.88
seconds. Its published artifact is
`/root/trade-alerts-builder/runs/20260925-023518-211608-build/published-artifacts-1e6fff279e25`.

The separate repeatability phase ran its published 109-selector recording
selection twice in fresh protected processes: 109 tests, controller wall time
445.378 seconds. The exact selector list, both per-run file hashes and their
comparison are preserved in
`/root/trade-alerts-builder/runs/20260925-023518-211608-build/published-artifacts-3476088967b3/summary.json`
and `publication.json`; the artifact directory is
`/root/trade-alerts-builder/runs/20260925-023518-211608-build/published-artifacts-3476088967b3`.

M9.1ER may now run development-only readiness counts through this binding. It
must not open a held-out result or fill any D-104 gap.
