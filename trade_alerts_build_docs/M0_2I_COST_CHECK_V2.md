# M0.2I separately reviewed V2 source-cost check

Date: 2026-09-14 Pacific. Status: **BOUNDED COST EVIDENCE RECORDED; SOURCE AND BUDGET GATES BLOCKED.**

The original `M0_2I_COST_CHECK_RESULT.json` remains unchanged. Its six local SDK
failures, zero provider connections and zero provider responses remain part of
the history. The separately assigned V2 task did not reset or hide them.

The V2 task used the same six frozen request shapes and a narrower common start
of March 28, 2023. It sent three `Historical.metadata.get_cost` POST requests,
once each and in order:

- `EQUS.MINI` trades returned HTTP 200 and estimated USD 101.393871814013.
- `EQUS.MINI` `mbp-1` returned HTTP 200 and estimated USD 931.397507786751.
- `OPRA.PILLAR` `cmbp-1` returned HTTP 400. Its specific cause is unknown.

The task stopped at that first failure. OPRA trades, statistics and definition
were not attempted. It made no retry, redirect, download, source-record request,
additional metadata call, reservation or ledger change. New spending was USD 0.

Both returned estimates exceed the USD 24 unreserved amount under the existing
USD 40 total cap and USD 16 reservation. They are estimates, not bills, account
authorization, reservations or source qualification. Billing remains unknown.
Dates before March 28, 2023 remain unpriced. OPRA availability remains unknown.

The exact result is in `M0_2I_COST_CHECK_V2_RESULT.json`. Its source references
point to the saved assignment, execution report and independent review. No
credential or private owner identifier is copied into these project records.

Complete stock tape and NBBO, original availability, corrections and finality,
adjustments, point-in-time membership, historical borrow, complete historical
options and executable quotes, catalyst history, untouched final dates and local
capacity remain blocked. The qualifying source list and chronological split
remain blocked. No source request, purchase, replay, promotion or live use is
authorized. All switches stay off.

Fresh protected document checks and independent review remain required. The
source path remains at a real owner and data boundary: no returned estimate fits
the current unreserved amount, one OPRA request failed for an unknown reason,
three requests remain unattempted, and the other required source groups remain
unpriced or unidentified. Separately, the owner's delegated direction allowed
the supervisor to reopen the independently reviewed first-four options repair as
M4.7A. That offline shared repair does not change any M0.2I source, cost,
capacity, historical or live gate.

## Protected verification record

The controller's protected acceptance run passed 3,048 tests from
`tests/trade_alerts_contracts` with zero failures, errors or skips. The JUnit
time was 545.476 seconds and the controller wall time was 549.701 seconds. Its
published artifacts are
`/root/trade-alerts-builder/runs/20260914-051046-194921-build/published-artifacts-5e32c2eba17d`.

The separate repeatability phase ran the controller's 40 recorded-output
selectors in two fresh processes. Each run passed 64 tests with zero failures,
errors or skips. The JUnit times were 151.826 seconds and 154.191 seconds; the
controller wall time for the phase was 309.964 seconds. The compared artifacts
are in
`/root/trade-alerts-builder/runs/20260914-051046-194921-build/published-artifacts-813978acf2d6`.
The controller marked the output stable.

The tested source hash is
`32e42616572168d66f827690ed7c94a31642c7c005920bd7d371f79b6db027bf`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260914-051046-194921-build/verified-manifest.json`.
These checks verify the records and existing offline contracts. They do not
fill the missing source, cost, budget, capacity or historical evidence.
