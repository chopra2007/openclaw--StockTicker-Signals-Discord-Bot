# M2.1 offline Schwab normalization evidence

## 1. Scope and acceptance

Session date: 2026-09-06 Pacific. Status: COMPLETE for the bounded M2.1 offline mapping contract.
This supporting execution record does not replace a canonical specification.

M2.1 converts synthetic raw Schwab-shaped bars, equity quotes and option rows into
M1.3 records. It preserves source/receipt/availability/normalization times,
missingness and exact contracts before legacy conversion. The existing client,
authentication, legacy outputs, runtime and configuration remain unchanged.
No provider, database, strategy or delivery path is activated.

## 2. Starting evidence

The pre-edit backup is `/root/trade-alerts-m21-20260906-014400/`. It records source
and document copies, hashes, ownership/modes, Git revision/index/status/diff and
the bounded plan. Existing M1 foundation work, tests and local data were present.
The stored failing-test list was empty. Both background programs reported active,
the workspace shortcut resolved correctly and recent drift/health checks were clear.

The starting protected selection was:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py \
  tests/trade_alerts_contracts tests/test_models.py \
  tests/test_batch1_measurement_store.py
```

At `/tmp/trade-alerts-m04-fxffrsu2/`, each independent process passed 289 tests.
The coordinator read both XML and isolation records: no failures/errors/skips,
identical test IDs, no unexpected denials and all four cleanup checks true.
This is bounded compatibility evidence, not the full release suite.

## 3. Implemented contract and changed files

The implementation contract is recorded in
CODING_STANDARDS section 58. The new implementation is
[schwab_normalization.py](../consensus_engine/scanners/schwab_normalization.py).
The new protected tests are
[test_schwab_normalization.py](../tests/trade_alerts_contracts/test_schwab_normalization.py).

Changed files are the two new Python files above, this evidence record and
PROJECT_INDEX, ROADMAP, SESSION_PROTOCOL, CODING_STANDARDS, DATA_REQUIREMENTS,
TESTING_AND_VALIDATION, DECISIONS_AND_OPEN_QUESTIONS and PREBUILD_REVIEW.

Three typed pure functions consume raw pieces from the existing client. No second
transport or client is added. Invalid optional fields become null while real zero
counts survive. Crossed/false-valid quotes, identity conflicts, impossible times
and incomplete candles fail. Equity last uses its own raw trade value; existing
regular-session last semantics are untouched. Caller-supplied bar intervals do
not infer source start-stamping. Exact option expiry/side/strike are reconciled
with the contract symbol while adjusted roots/deliverables remain intact.

Independent review identified and closed missing quote time on valid input,
zero quote sides, an assumed candle-start stamp, newer trades refreshing an old
bid/ask source time, and option-symbol contradictions. The final reviewer found
no remaining issue within this contract. Quality/finality are independent supplied
facts, and optional invalid numeric values explicitly become missing; no dynamic
freshness or provider-coverage policy was invented.

## 4. Final verification

The final focused artifact is `/tmp/trade-alerts-m04-31ka3b8k/`: 41 new cases
passed in each protected process. The coordinator independently ran:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py tests/trade_alerts_contracts tests/test_schwab_client.py tests/test_models.py tests/test_batch1_measurement_store.py tests/test_feature_flags.py tests/test_source_health.py tests/test_expected_move.py tests/test_sessions.py tests/test_put_flow_shortlist.py::test_friday_signal_enters_on_monday tests/test_put_flow_shortlist.py::test_entry_skips_a_market_holiday tests/test_put_flow_shortlist.py::test_exit_is_four_trading_sessions_later tests/test_put_flow_shortlist.py::test_exit_counts_sessions_not_calendar_days_over_a_holiday tests/test_put_flow_option_monitor.py::test_trading_day_calendar_knows_holidays_and_weekends tests/test_put_flow_option_monitor.py::test_shortened_session_stops_at_the_early_close
```

Final artifacts: `/tmp/trade-alerts-m04-34v10bqz/`. Each process passed **420 tests**
(840 executions), with zero failures/errors/skips, identical test IDs,
no unexpected isolation denials and all four cleanup checks true. The coordinator
read both XML results, isolation reports and three-record proof files directly.
The Bar/Quote/OptionQuote proof is byte-identical; SHA-256:
`481aa8aad4ff3667fe01adafddea7c9e34677fe2367e3256966df5b8e3cef6ba`.

Exact tested source hashes are stored in `final-tested-source.json` in the private
backup; final checks require them to remain unchanged. The existing stored
failing-test list, production sources, prior foundation code/tests, protected
launcher, approved/proposed packets, Git revision and Git index are preserved.
New/changed files retain openclaw ownership and original modes where applicable.
Ordinary test discovery skips this protected-only module before application
imports; the skip is not acceptance evidence. The full application release suite
was not run; the known wider listener isolation gaps remain outside this addition.
Existing dependency warnings are unchanged and remain with M18.6.

No repository lint/type-check command is configured. Source compilation and
Python 3.10 grammar checks passed. Final preservation and document checks live
in the private backup. No Git save or push, background restart, live call,
credential access or paid request was made. D-091 remains $0 used/$0 reserved.

The final `final-checks.json` verifies preserved sources and Git state, file
ownership/modes, local document links, all eight playbook rows, 31 functional
requirements and 22 additional capability rows. Both background programs still
reported active, the workspace shortcut resolved correctly, and the recent
drift/health search was clear. These read-only checks do not claim live operation
of the new offline mappings.

## 5. Remaining limits

Synthetic request-payload mappings do not prove current entitlement, coverage,
provider units, historical publication/finality or stream transport. Numeric
age/skew/coverage policies remain with M0.2/M0.3 and their runtime owners. Only
the normalization portion of AT-04 is tested. Provider fallback, historical
coverage/finality and session alignment remain M2.2; streaming, duplicate/reconnect
and dynamic staleness controls remain M2.3; options alignment/selection remains
M4.7/M14.2. M0.3B and the other seven strategy definitions remain unresolved.
The two previously recorded listener-test isolation gaps remain M18.4 work.

## 6. Exact next milestone

M2.2 — Historical bar interface: daily, one-minute, premarket and regular-session
records. Read PROJECT_INDEX and ROADMAP section 31, then verify M2.1's actual
source and protected evidence. Reuse the existing historical request interface,
M1 clock/configuration/records and M2.1 mappings. Preserve legacy callers.

Choose one coherent offline interface/coverage slice. Make requested versus
observed intervals, original availability, missing intervals, revisions, session
boundaries and adjustment/finality conventions explicit. Do not turn a request
parameter, synthetic candle or older data file into proof of present provider
coverage. Check M0.2 evidence for every dependent source claim; retain unknown
semantics and affected data blockers when proof is unavailable. Missing intervals
are not certified no-trade bars. No daily-bar convention may silently change a
regular-session definition or an approved strategy formula.

Use the protected launcher, preserve existing work, verify the selected scope and
save exact completion/partial status. The kickoff grants no live provider/Discord
call, restart, deployment, trade, Git mutation or unresolved product decision.
D-090 and D-091 remain unchanged. End with SESSION_PROTOCOL section 32's one-line
kickoff after updating the current roadmap.
