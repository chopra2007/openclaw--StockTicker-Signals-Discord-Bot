# M1.3 canonical record evidence

## 1. Scope and acceptance

Session date: 2026-09-06 Pacific. Status: COMPLETE for M1.3.
This is a supporting execution record, not a new canonical specification.

M1.3 adds typed, immutable records and deterministic serialization for market
inputs, feature snapshots, state transitions, mechanical candidates and separately
linked results. It reuses the existing clock and fixed configuration snapshot.
Acceptance requires round trips, invalid-input and missingness checks, configuration
attribution, immutable nested facts and preserved legacy interfaces. No strategy
formula, provider adapter, database migration, outcome evaluator or runtime is
implemented in this record milestone.

## 2. Starting evidence and preservation

The private pre-edit backup is `/root/trade-alerts-m13-20260906-003752/`.
It contains the source/document copies, hashes, ownership/modes, starting revision,
Git index hash, status, diff and bounded plan. Prior clock/configuration work,
protected tests/launcher, build documents and local data were already present.
The stored failing-test list was empty. Both background programs reported active;
the workspace shortcut resolved correctly and the recent model-drift/health-failure
search returned no matches. No credential or provider request was needed.

Before edits, the protected launcher ran:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py \
  tests/trade_alerts_contracts tests/test_models.py \
  tests/test_batch1_measurement_store.py
```

Artifacts: `/tmp/trade-alerts-m04-kui8w08w/`. Both processes passed **145 tests**
with zero failures, errors or skips. Both isolation records have no unexpected
denials and all four cleanup checks true. This establishes the starting bounded
compatibility evidence; it is not the full release suite.

## 3. Implemented contract and changed files

- [Record layer](../consensus_engine/trade_alerts_models.py): thirteen top-level
  record types plus typed nested values, schema version 1, strict JSON round trips,
  source/time/quality/missingness, immutable candidate geometry and version links.
  Session records validate the existing fixed settings snapshot and hash. Other
  records separately preserve options, suppressions, delivery, human choices and
  outcomes; no evaluator or database writer is introduced.
- [New tests](../tests/trade_alerts_contracts/test_domain_models.py): valid and
  adversarial records, all type round trips, original availability and revisions,
  missing versus zero, exact contracts, nested immutability, separate results and
  real-loader configuration attribution across reloads. Ordinary discovery skips
  this protected-only module before application imports; that skip is not proof.
- Build documentation: PROJECT_INDEX, ROADMAP, SESSION_PROTOCOL, CODING_STANDARDS,
  TESTING_AND_VALIDATION, DECISIONS_AND_OPEN_QUESTIONS, PREBUILD_REVIEW and this
  evidence record. Current routing advances to M2.1; old evidence stays historical.

The bounded engineering contract is CODING_STANDARDS §57. Known no-trade bars
cannot be unavailable or provisional. Quote last size and unknown option flags
remain representable. Unavailable options have no selection facts; POOR may retain
rejected-contract evidence and a policy-attributed score, with reasons and no
selected rank. Partial observed outcomes remain PARTIAL; unavailable/unresolved
outcomes cannot silently become measured performance. These are record consistency
rules, not trading thresholds or evidence of source coverage.

## 4. Final verification

The final focused selection passed **144 tests in each of two processes**
at `/tmp/trade-alerts-m04-rjug7a0q/`. The coordinator independently ran:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py \
  tests/trade_alerts_contracts tests/test_models.py \
  tests/test_batch1_measurement_store.py tests/test_feature_flags.py \
  tests/test_source_health.py tests/test_expected_move.py tests/test_sessions.py \
  tests/test_put_flow_shortlist.py::test_friday_signal_enters_on_monday \
  tests/test_put_flow_shortlist.py::test_entry_skips_a_market_holiday \
  tests/test_put_flow_shortlist.py::test_exit_is_four_trading_sessions_later \
  tests/test_put_flow_shortlist.py::test_exit_counts_sessions_not_calendar_days_over_a_holiday \
  tests/test_put_flow_option_monitor.py::test_trading_day_calendar_knows_holidays_and_weekends \
  tests/test_put_flow_option_monitor.py::test_shortened_session_stops_at_the_early_close
```

Final artifacts: `/tmp/trade-alerts-m04-14fow9zj/`. **363 tests passed in each process**
(726 executions), with zero failures/errors/skips, identical executed test IDs,
no unexpected isolation denials and all four cleanup checks true. The coordinator
read the XML, isolation reports and both synthetic record-proof files directly.
The thirteen-record proof is byte-identical across processes; SHA-256:
`2fae11128857ae58d0aebb510131c6bb06bd0988d57ae01600e4c703890ed4c7`.

Earlier intermediate runs passed 106 new cases twice and the 325-case combined
selection twice, but independent review found missing consistency cases. Final
code/tests close no-trade/unknown conflicts, option-status contradictions,
unresolved-outcome metrics, invalid state labels and the missing last-trade size.
Rejected-option evidence remains explicitly POOR rather than being discarded.
The final review is limited to this record contract; no later runtime gate closes.

Both new Python files pass source compilation and Python 3.10 grammar checks.
No repository lint/type-check command is configured. The combined tests retain
existing dependency deprecation/interpreter warnings; runtime migration remains
M18.6. The full application suite was not run because this bounded addition has
no live consumer, and known listener tests still lack complete isolation.

One early developer smoke imported only the new record layer, the pure settings
model and the clock, then constructed synthetic in-memory records outside the
protected launcher. It made no provider/storage/runtime calls. All acceptance
and final combined evidence above comes from the protected launcher.

Final preservation/link/source checks are recorded in the private backup's
`final-checks.json`, `session-changes.diff` and `independent-verification.json`.
Existing production sources, prior foundation work, launcher, failing-test list,
approved/proposed rule packets, master/playbook/data contracts and spending ledger
are unchanged. Owned files retain openclaw ownership and the previous modes.
Source revision and Git index are unchanged; no commit or push was made.
The final check passed 179 preservation/syntax/document checks, including 92 local
links, all eight playbooks, 31 functional rows and 22 extra capability rows. Both
background programs still reported active and the recent health search was clear.

## 5. Remaining limits

M0.3B adoption and the other seven strategy definitions remain open. M0.2 still
owns dependent provider access, timestamps, source coverage and capacity evidence.
The two older listener-test isolation gaps remain with M18.4. Actual persistence,
recovery, replay, delivery, human input and option/outcome evaluation retain their
roadmap owners. Passing record tests does not close those downstream controls.
D-090 and D-091 remain unchanged, with $0 used and $0 reserved under D-091.

## 6. Next milestone after verified completion

M2.1 — Schwab normalization. First read PROJECT_INDEX and ROADMAP §31 and confirm
M1.3 has actually passed. Reuse the existing Schwab client and the canonical
records, clock and configuration snapshot. Implement one bounded offline mapping
milestone using synthetic payloads under the protected launcher. Preserve old
callers and their quote/option/bar field meanings.

Inspect source payloads before legacy conversions discard missingness, delayed
flags, last-price semantics or timestamp precision. Preserve exact option identity,
individual quote/trade times, original receipt/availability, source conventions,
quality and revisions. Unknown provider finality/adjustment/session coverage must
stay explicit; a fixture cannot prove current source access or historical coverage.
Streaming transport/reconnect is M2.3, historical coverage/finality is M2.2 and
live operational evidence remains behind its applicable authorization/data gates.
No new client, feed, database, strategy or live activation follows by implication.

The next session preserves the cumulative D-091 budget, unresolved trading choices,
existing work, live/deployment and Git boundaries, verifies its scoped result,
updates durable progress and returns SESSION_PROTOCOL §32's one-line kickoff.
