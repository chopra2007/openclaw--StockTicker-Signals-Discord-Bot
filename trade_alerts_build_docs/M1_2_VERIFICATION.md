# M1.2 configuration foundation evidence

## 1. Scope and acceptance

Session date: 2026-09-05 Pacific. Status: COMPLETE for M1.2.
This supporting record does not change the nine-document authority hierarchy.

The selected milestone extends the existing configuration loader with one strict,
non-secret `trade_alerts` namespace. Acceptance is a validated configuration
foundation covering strategy/data/options/alert/research controls, a reproducible
version/hash and a fixed session snapshot, while preserving legacy callers.
Unfinished trading choices remain null or absent. This does not complete any
strategy, data feed, replay, promotion, or live-delivery milestone.

The reversible engineering contract is recorded in CODING_STANDARDS §56.
D-090's written research formulas and M0.3B's unapproved proposals are not encoded
as application defaults. All new switches in the actual YAML remain false.
Policy/version labels identify requested settings; they cannot approve a rule or
satisfy runtime/data/release gates. No new runtime consumes these switches yet.

## 2. Starting evidence and preservation

Private pre-edit backup, source hashes, original ownership/modes, revision/index
and starting status: `/root/trade-alerts-m12-20260905-211527/`.
The existing M1.1 clock edit, protected launcher/tests, build documents and local
data were already unsaved work. They were preserved. The stored failing-test list
was empty. Both background programs reported active, the workspace shortcut
resolved correctly, and the recent model-drift/health-failure check had no matches.
No credential, provider or paid request was needed; D-091 remains $0 used/$0 reserved.

An initial protected selection ran the 72 existing contracts plus 21 flag/source
health cases in each process at `/tmp/trade-alerts-m04-8v8hzsds/`: 91 passed and two
failed because importing the source-health loop needed the unmounted `models`
code package. The errors were `ModuleNotFoundError: No module named 'models'` in
`test_source_health_updater_writes_rows` and
`test_record_source_error_affects_error_rate`. No isolation denial was bypassed.
Adding that existing code folder as read-only fixed both: the 21 nearby cases
passed in each process at `/tmp/trade-alerts-m04-54s645o1/`. The child protection,
credential/network/live-storage exclusions and cleanup rules are unchanged.
The failing-test list was not changed to absorb the collection gap.

## 3. Changed files and implemented behavior

- [Existing loader](../consensus_engine/config.py): validate only a present new
  section before legacy environment expansion; expose `get_trade_alerts_config()`.
  Legacy get/cache/reload behavior and callers keep their existing contracts.
- [Pure settings model](../consensus_engine/trade_alerts_config.py): strict known
  fields/types, explicit unavailable values, cross-field checks, frozen snapshot,
  detached exports and SHA-256 of normalized JSON. It performs no file or network
  access. Missing section means disabled defaults; explicit null is an error.
- [Configuration](../config/consensus.yaml): append the dormant section, all eight
  strategy IDs, explicit null policy/version/window/premarket fields and recording
  sink. Existing configuration values are preserved.
- [New tests](../tests/trade_alerts_contracts/test_configuration.py): default and
  enabled settings through the actual loader, strict invalid-input cases, stable
  identity, secret exclusion, mutation/reload separation and the actual M1.1
  clock consuming configured values. Normal discovery skips this protected-only
  module; a skip is not proof of execution.
- [Protected launcher](../scripts/testing/run_trade_alerts_contracts.py): the
  single read-only `models` code mount needed for source-health consumer tests.
- Build documentation: record the contract/results and route current progress
  to M1.3; old verification records remain historical evidence.

The dormant config's expected hash is
`bbe2460d8bd241a94d019da3542375bee4170bcd887e8b57315927ed4d290591`.
It was independently derived from the explicit appended YAML and is asserted in
the tests. Equivalent key order and omitted engineering defaults normalize to
that identity. Legacy secret changes do not affect the hash or enter the JSON.

## 4. Executed verification

An independent verifier reviewed the source/diff and ran the following selection
through the protected launcher, which executes it in two separate processes:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py \
  tests/trade_alerts_contracts tests/test_feature_flags.py tests/test_source_health.py \
  tests/test_expected_move.py tests/test_sessions.py \
  tests/test_put_flow_shortlist.py::test_friday_signal_enters_on_monday \
  tests/test_put_flow_shortlist.py::test_entry_skips_a_market_holiday \
  tests/test_put_flow_shortlist.py::test_exit_is_four_trading_sessions_later \
  tests/test_put_flow_shortlist.py::test_exit_counts_sessions_not_calendar_days_over_a_holiday \
  tests/test_put_flow_option_monitor.py::test_trading_day_calendar_knows_holidays_and_weekends \
  tests/test_put_flow_option_monitor.py::test_shortened_session_stops_at_the_early_close
```

Artifacts: `/tmp/trade-alerts-m04-mwf9udwx/`. **194 tests passed in each process**
(388 executions): 48 new configuration cases, 72 existing protected compatibility/
clock cases, 21 feature-flag/source-health cases and 53 existing calendar consumers.
Both XML files show zero failures, errors or skips; the executed test IDs match.
Both isolation reports have zero unexpected denials and all four cleanup checks
true. The expected credential/network/database/write/child-process sentinels were
denied. The coordinator read the actual XML, summary and isolation records.

Both per-process configuration proof files are byte-identical and contain the
expected dormant hash above. An independent readback of the appended actual YAML
through the pure settings model produced the same hash with all switches off.
Review found and corrected a test gap before the final run: configured regular
window values now reach the actual M1.1 clock, and the secret-change test confirms
the changed synthetic value was actually reloaded. Independent final verdict: PASS
for the bounded M1.2 contract, with no material source findings.

All four changed Python files passed syntax compilation without application
imports. No repository lint/type-check command is configured; none
was installed or invented. The full application suite is not claimed passing.

## 5. Remaining limits

M1.2 proves a local configuration foundation. Capturing a new snapshot deliberately
uses the current legacy cache; the eventual session controller must capture once
and retain it. It must attach version/hash/canonical settings to records and enforce
approval, source coverage, data readiness, output-sink and release gates. Those
consumers, persistence and restart/replay tests remain M1.3/M4/M5/M9/M17/M18.
A true flag with a syntactically valid policy name is not a complete trading policy.

M0.3B adoption and the other seven strategy definitions remain open. M0.2 still
owns dependent provider/data proof. AT-02 still needs bar finality/availability
and opening-range checks under M2.2/M3.6. The two older listener-test isolation
gaps remain at M18.4; this session does not claim the full release suite passed.
Runtime/deployment compatibility and actual activation retain their later gates.
No live activation, broker/Discord call, restart, Git mutation, order or paid
request occurred. No private memory file was edited.

Final preservation checks confirmed identical legacy YAML values and unchanged
`get`, `get_api_key`, `reload` and environment-resolution function bodies. The
previous clock work, child isolation guard, empty failing-test list, approved
packet body, proposed packet, data/master/playbook contracts and spending ledger
were preserved. Current handoff review found no material drift. All 81 local
Markdown links, code fences, source syntax, added whitespace, visible time labels
and secret-shaped additions passed checks; all eight playbooks, 31 functional
requirements and 22 extra capability rows remain tracked. Owned files retain
`openclaw:openclaw` ownership and original modes. Source revision and Git index
are unchanged. The private backup contains `session-changes.diff`,
`preservation-checks.json`, `independent-verification.json` and `final-checks.json`.

## 6. Exact next build: M1.3

Read PROJECT_INDEX and ROADMAP §31, then implement one coherent canonical-domain
record milestone. Inspect `consensus_engine/models.py`, the existing quote/option
mappings, measurement records, SQLite migration framework and M0.4 contracts.
Reuse the M1.1 clock and M1.2 fixed configuration snapshot/version/hash.

At minimum retain the required Bar, Quote, OptionQuote, CatalystEvent,
StrategyStateTransition, FeatureSnapshot, AlertCandidate, OptionRecommendation
and OutcomeRecord semantics. Preserve source/receive/available times, bar
start/end/finality/revision, source/adjustment/quality/missingness, separate stock
and option validity, and immutable mechanical facts versus linked outcomes/human
choices. An explicit unavailable field is allowed; a proposed formula is not a
default. Do not build a parallel provider, database or strategy runtime merely to
create these records. Actual migrations/storage remain their owning milestones
unless a minimal tested prerequisite is necessary.

Use isolated round-trip, invalid-input, timestamp/missingness, version attribution
and legacy compatibility tests; independently verify them. Stop after the bounded
M1.3 record contract, save its actual evidence and exact next dependency-ready
step, then return SESSION_PROTOCOL §32's one-line kickoff. Preserve all existing
strategy/data/approval, D-091 budget, live/deployment and Git boundaries.
