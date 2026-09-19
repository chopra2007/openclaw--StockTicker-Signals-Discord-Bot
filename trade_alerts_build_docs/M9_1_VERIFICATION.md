# M9.1 historical replay #1-#4 — blocked data assessment

Date: 2026-09-13 Pacific. Status: **blocked** for the required historical
replay. This record closes the bounded M9.1 assessment only. It does not close
the historical-validation gate, establish data coverage, calculate returns or
authorize any live action.

## 1. Result

The exact M9.1 result is `INSUFFICIENT_DATA` for all four playbooks:

- `CRVOL_ORB5`
- `HOD_COMP_RS`
- `OR_FAILURE_REV`
- `FIRST_PULLBACK_VWAP`

The repository has deterministic replay support and synthetic supplied-record
examples. It does not have a verified point-in-time historical dataset that can
support the required early historical study. The existing M6.4, M7.5, M8.2 and
M8.4 source and historical-data gates all remain open. Their synthetic records
cannot be relabeled as historical observations.

The first four playbooks also retain unresolved definition gates. In particular,
their thresholds, timing rules, participation rules, risk choices and confidence
floors are not all approved. Selecting those values after seeing returns would
break the testing rules. No replay, outcome calculation or parameter choice was
performed.

## 2. Missing evidence

The required study cannot start until a dated source manifest proves, for the
requested symbols and sessions:

- point-in-time minute bars, quotes, benchmark/reference inputs and required
  participation inputs;
- original source and availability times, finality, revisions, corrections and
  compatible price/volume adjustments;
- the prior-session history each playbook needs;
- corporate-action and historical-universe handling for the selected sample;
- approved frozen definitions and an execution/outcome policy for each tested
  playbook.

Current provider access, history depth, field meaning and complete coverage are
still supervised source questions under M0.2, M2.3 and M2.4. This offline session
made no provider, broker, Discord or paid request and used no testing credit.

## 3. Reopening test

Reopen M9.1 only after the source owners M0.2, M2.2, M2.3, M2.4, M6.4,
M7.5, M8.2 and M8.4 supply the missing point-in-time facts, M0.3 supplies
approved frozen playbook definitions, and M5.2 supplies the approved executable
outcome and execution policy.
Then freeze the dataset ID, date range, symbols, strategy versions, configuration
hashes, feature version, code revision and execution model before any result is
calculated. Replay events in original availability order through the existing
isolated recording path. Confirm that no future or revised fact enters an earlier
decision. Keep full and proxy data modes separate. A second fresh process must
produce the same ordered state changes, candidates, suppressions and recording
bytes from the same manifest.

## 4. Test handoff

No product code, test, configuration, dependency or protected input changed.
The controller nevertheless published matching protected proof for the tested
source hash `e0df56aba65cd9d15a32d728cee882ddade52dc3b544e2168cb1d7b97f14b1b8`:

- Focused phase: one run of `tests/trade_alerts_contracts`, selected because the
  builder named directly affected checks, passed 2,922 tests in 518.128 seconds
  of controller wall time. Artifacts:
  `/root/trade-alerts-builder/runs/20260913-020835-174260-build/published-artifacts-20bfac445fbd`.
- Acceptance phase: one run of `tests/trade_alerts_contracts`, selected by the
  unknown-dependency-impact safe broad fallback, passed 2,922 tests in 514.037
  seconds of controller wall time. JUnit recorded 510.106 seconds. Artifacts:
  `/root/trade-alerts-builder/runs/20260913-020835-174260-build/published-artifacts-338f337aacae`.
- Repeatability phase: two fresh-process runs of the controller's 35 recording
  selectors passed 59 tests per run in 301.993 seconds of controller wall time.
  JUnit recorded 149.703 and 148.304 seconds. The ordered test results and the
  required recording files matched. Artifacts:
  `/root/trade-alerts-builder/runs/20260913-020835-174260-build/published-artifacts-597feafaedf8`.

All phases report zero failures, errors and skips with protected isolation and
cleanup intact. The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-020835-174260-build/verified-manifest.json`
with SHA-256 `32ad21dab94bb22eb306c50128635597977aeeed888f7898a5054973e8c9a5e9`.
This proof checks the unchanged offline contracts. It does not supply the missing
historical data, approved M0.3 definitions or M5.2 execution/outcome policy.

## 5. Next milestone

`M9.2` is the independent next milestone after review. It can publish the initial
validation report with these four `INSUFFICIENT_DATA` results, the missing fields,
the responsible owner milestones and the reopening test. It must not turn this
assessment into historical, profitability, shadow, promotion or activation
evidence. All switches stay off.
