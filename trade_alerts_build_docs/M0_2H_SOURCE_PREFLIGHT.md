# M0.2H first-four historical source coverage-and-cost preflight

Date: 2026-09-14 Pacific. Status: **PREFLIGHT COMPLETE; ACQUISITION AND SOURCE GATES BLOCKED.**

The finite request plan is in
`M0_2H_SOURCE_ACQUISITION_SPEC.json`. It covers the first four frozen research
versions and the exact 60 selected stocks already present in the inventory,
with SPY as the reference. The historical request window is January 1, 2023
through August 21, 2026 Pacific. The common existing window begins March 28,
2023. Those old selected60 dates may support only disclosed exploratory
development or calibration. They were selected through August 21, 2026 and
their earlier final dates were exposed, so they cannot become untouched final
validation.

The forward holdout collection window is September 15 through October 30, 2026
Pacific. No result from that window may be opened before source qualification,
the immutable coverage manifest and the exact chronological split are frozen.
Only qualifying completed exchange sessions may enter the later 60%/20%/
remainder split. This preflight does not invent those session lists.

## Saved evidence kept in scope

- The selected60 inventory has 40,278,360 checked identity/timestamp rows in
  separate `XNYS.PILLAR` and `EQUS.MINI` files. Opening gaps and selection bias
  remain.
- The separate 13-ETF files have 4,257,208 `XNYS.PILLAR` rows and 4,483,742
  `EQUS.MINI` rows, with four and fifteen provider-degraded dates. They cannot
  replace stock history.
- The September 13 Schwab check proved two free HTTP 200 reads and 20 restricted
  SPY option contracts. It did not prove official units, complete entitlement,
  current quote freshness, history or executable fills.
- M0.2G has zero qualifying rows. Its null manifest fingerprint and null date
  lists remain unchanged.

## Exact missing records

The JSON specification gives required fields and coverage for seven separate
record groups: stock trades, stock top-of-book quotes, point-in-time listing and
membership facts, corporate actions and adjustment factors, historical borrow,
historical options, and catalyst/halt history. Missing fields stay missing.

Official Databento material supports only narrow candidate facts:

- `EQUS.MINI` offers trades and `mbp-1`, but it is a derived component-venue
  source with anonymized trade venue. It is not proved to be a complete US stock
  tape or NBBO.
- `mbp-1` records contain top-of-book events, prices, sizes and source times.
  That record shape does not prove full venue coverage or original availability.
- Security Master supplies point-in-time listing facts. It does not recreate the
  selected60 choice, index/sector membership or original availability by itself.
- Corporate-actions and adjustment-factor records are candidates for split and
  dividend history. Account entitlement, price and complete revision history
  remain unknown.
- `OPRA.PILLAR` supplies consolidated options top-of-book and trades. It does not
  by itself establish this account's cost, complete eligible chains, IV/Greek
  history, open-interest timing, corrections or original availability.
- No qualifying historical borrow or low-latency catalyst source is identified.
  Short-stock and affected faithful catalyst arms stay unavailable.

Sources checked: [Databento venues and datasets](https://databento.com/docs/venues-and-datasets),
[MBP-1 fields](https://databento.com/docs/schemas-and-data-formats/mbp-1),
[Security Master](https://databento.com/docs/schemas-and-data-formats/security-master),
[corporate actions](https://databento.com/docs/schemas-and-data-formats/corporate-actions),
and [Historical cost requests](https://databento.com/docs/api-reference-historical).

## Unsent cost plan

Six exact free `Historical.metadata.get_cost` checks are preregistered for the
60 stocks plus SPY: `EQUS.MINI` trades, `EQUS.MINI` `mbp-1`, `OPRA.PILLAR`
`cmbp-1`, trades, statistics and definition. Each uses the exact historical
bounds and input-symbol form recorded in the JSON. All six prices are `UNKNOWN`;
none was sent. After fresh independent M0.2H review permits advancement, M0.2I
may send only these six requests, once each and serially, with no retries.
Translate `end_exclusive` to SDK `end`, resolve each `symbols_json_pointer` to
the frozen list, and omit deprecated `mode`. Record failed, unavailable and
unattempted requests explicitly. Security Master, corporate actions and
adjustment-factor entitlement and prices remain unresolved. No additional
reference, entitlement, coverage or symbology requests are authorized. A returned
cost estimates only the named dataset/schema request; it does not establish
entitlement, complete coverage, original availability, corrections or finality.

Current authority is $40 total Databento use. The prior two downloads retain
$16 in reservations, billing is unknown and $24 is unreserved. This milestone
spent $0, created no reservation and read no credential. A later paid download
must fit the shared locked ledger, local storage admission and the remaining
owner cap. The 175 GB Google Drive hard limit and 165 GB operating limit do not
replace local download and verification space.

## Decision

The finite preflight is complete. It authorizes no request. M0.2I may perform
only the six preregistered `Historical.metadata.get_cost` requests, once each
and serially, conditional on fresh independent M0.2H review permitting advancement.
No source-record request, download, token refresh, reservation or ledger change,
paid retry, purchase, or additional reference, entitlement, coverage or symbology
request is assigned. A paid download needs a later assigned acquisition step. Source qualification, the chronological
split, replay, executable short/option results, promotion and live use remain
blocked. Strategies 5-8 remain behind the required early first-four validation.
All switches stay off.

## Protected verification

The controller tested source hash
`0b91d49917b10989624a1df6ccea8b20a38f89fffe6aa937ec4e62c898e5d9f6`.
The complete tested-source list is
`/root/trade-alerts-builder/runs/20260914-042054-541631-build/verified-manifest.json`.
The focused phase selected `tests/trade_alerts_contracts` because the builder
named directly affected checks. Its one protected run passed 3,048 tests in
551.739 controller wall seconds. Its published files are in
`/root/trade-alerts-builder/runs/20260914-042054-541631-build/published-artifacts-8a2c4b36295e`.

The broad acceptance phase selected `tests/trade_alerts_contracts` because the
dependency impact was unknown and required the safe broad fallback. Its one
protected run passed 3,048 tests in 554.003 controller wall seconds. Its
published files are in
`/root/trade-alerts-builder/runs/20260914-042054-541631-build/published-artifacts-75c8a0b95890`.

The separate repeatability phase selected the controller's 40 recording checks
because recording output requires fresh-process comparison. It passed 64 tests
in each of two protected runs in 309.369 controller wall seconds. The controller
reported stable matching artifacts. Both runs and their file hashes are in
`/root/trade-alerts-builder/runs/20260914-042054-541631-build/published-artifacts-aef03df722be`.
These records-only final changes do not change code, tests, configuration,
dependencies or protected inputs.

## Records correction — 2026-09-14 Pacific

The prior wording incorrectly expanded M0.2I from six cost requests to additional
reference, entitlement and coverage requests. This correction narrows the JSON
plan, this report, DATA_REQUIREMENTS and both M0.2I ROADMAP rows to the owner's
exact assignment. It preserves the unsent request parameters, prior failures
and attempts, source gates and original protected proof. Independent review of
this correction remains required; no request was made and no product test was
rerun.

`M0_2H_RECORDS_ONLY_COMPARISON.json` records the complete milestone document
delta, current document hashes, comparison with the original tested manifest,
and exact controller phase records. It retains separate repeatability selectors,
both run artifact paths and their published hash comparisons. These locally
computed document hashes describe the prose correction, not a new protected
run or replacement controller source hash. The earlier controller comparison
is historical and does not describe these corrected bytes.
