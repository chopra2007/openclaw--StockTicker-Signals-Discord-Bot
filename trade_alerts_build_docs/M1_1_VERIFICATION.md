# M1.1 shared market clock evidence

Historical evidence and handoff: M1.2 has since completed in
[M1_2_VERIFICATION.md](./M1_2_VERIFICATION.md). Current next work is M1.3 in
ROADMAP §31; the original clock evidence and handoff below remain unchanged.

## 1. Scope and acceptance

Completed 2026-09-05 Pacific. Status: COMPLETE for M1.1. This is a supporting
implementation/evidence record; the nine canonical documents retain authority.

1. Extend `consensus_engine/utils/time_context.py` with additive, typed helpers.
   Reuse its installed exchange calendar and keep existing functions compatible.
   Reject timestamps without a time zone, preserve absolute instants, and format
   new visible timestamps with the correct Pacific seasonal label.
2. Expose the exchange session date, a caller-configured Pacific premarket window,
   regular-session phase, and caller-supplied windows relative to the regular open.
   Use inclusive starts and exclusive ends; clip windows at the actual close.
   Validate ordinary days, closures, shortened days and both seasonal clock changes.
   D-090 tests supply 01:00 explicitly; that research choice is not a platform default.
3. Run new and existing relevant tests through the M0.4 protected launcher, inspect
   its denial/cleanup reports, independently review the change, and synchronize
   the roadmap and next-session instructions with actual results.

Success means a tested clock foundation only. A clock window never establishes
bar finality, coverage, data availability or opening-range readiness. AT-02's
remaining data/feature proof stays with M2.2/M3.6. Trading windows are supplied by
callers; M1.2 will own validated configuration. D-090's opening-five-minute and
open-plus-5-to-45-minute windows are test examples, not new hardcoded strategy
rules. No M0.3B proposal is adopted.

Existing prompt builders, research rolling-session helpers, scores, data adapters,
configuration and live callers retain their current behavior. This session does
not authorize activation, external messages, orders, restarts or Git mutation.

## 2. Starting evidence

Private backup and original source/status hashes:
`/root/trade-alerts-m11-20260905-204757/`. Existing untracked files were preserved.
The stored failing-test list is empty. Before application edits, all 31 M0.4 tests
passed in each of two protected processes at `/tmp/trade-alerts-m04-0_l4ko1e/`.
Both reports have zero unexpected denials and all cleanup checks true.

The existing engine and gateway both reported active. The workspace shortcut
resolved correctly, and the recent model-drift/health-failure log check found no
matches. No provider request or credential read was needed. D-091 remains $25
authorized, $0 used and $0 reserved.

## 3. Implemented contract and changed files

- [Clock helpers](../consensus_engine/utils/time_context.py): `as_utc` rejects
  naive/no-offset events and preserves their absolute instant and precision;
  `format_pacific` supplies seasonal Pacific text; `session_date_at` normalizes
  the source zone before selecting the exchange calendar date. That date remains
  a lookup key on holidays/outside hours, not a claim that a session is open.
  `premarket_bounds` requires an explicit Pacific start time; `session_phase`
  returns CLOSED/PREMARKET/REGULAR. After the regular close it returns CLOSED,
  without claiming extended-hours data is unavailable. `regular_session_window`
  takes elapsed offsets from the scheduled open and clips at the actual close.
  Bounds use inclusive starts/exclusive ends and return absolute instants.
- [New tests](../tests/trade_alerts_contracts/test_market_clock.py): 41 fixed-input
  cases using actual clock functions and the installed exchange calendar. Normal
  discovery skips this module before application imports; that skip is not proof.
- [Protected launcher](../scripts/testing/run_trade_alerts_contracts.py): one extra
  read-only mount for the existing `scripts/put_flow_shortlist_job.py`, needed to
  collect its calendar consumer tests. The script itself is unchanged and its
  command entry point is not executed. All pre-import child guards are unchanged.
- Build notes: PROJECT_INDEX, ROADMAP, SESSION_PROTOCOL and DECISIONS now route to
  M1.2. CODING_STANDARDS and TESTING_AND_VALIDATION record the clock contract and
  partial AT-02 boundary. PREBUILD_REVIEW and M0_4_VERIFICATION distinguish their
  historical handoffs from current progress. FIRST_BUILD_SESSION and an added
  navigation note before the unchanged approved M0.3A packet body also direct old
  handoffs to current progress. This file holds implementation proof.

All original functions from `session_dates` onward are byte-for-byte unchanged,
including old prompt wording and caller return types. New consumers can use the
new helpers; no existing caller or live strategy was switched to them. Records
and serialization remain M1.3 work. No new dependency, configuration, database
layout or trading formula was introduced.

## 4. Executed results and independent review

The initial 31 compatibility cases passed twice before application edits. Nearby
calendar consumers then passed **53 cases in each of two protected processes**;
artifacts: `/tmp/trade-alerts-m04-shykaiob/`.

An independent verifier reviewed the final source/tests/protection and ran:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py \
  tests/trade_alerts_contracts tests/test_expected_move.py tests/test_sessions.py \
  tests/test_put_flow_shortlist.py::test_friday_signal_enters_on_monday \
  tests/test_put_flow_shortlist.py::test_entry_skips_a_market_holiday \
  tests/test_put_flow_shortlist.py::test_exit_is_four_trading_sessions_later \
  tests/test_put_flow_shortlist.py::test_exit_counts_sessions_not_calendar_days_over_a_holiday \
  tests/test_put_flow_option_monitor.py::test_trading_day_calendar_knows_holidays_and_weekends \
  tests/test_put_flow_option_monitor.py::test_shortened_session_stops_at_the_early_close
```

Final artifacts: `/tmp/trade-alerts-m04-gmhvqdfz/`. Each process passed **125 cases**
with zero failures, errors or skips (250 total executions). This comprises 41 new
clock cases, 31 compatibility cases and 53 existing consumer cases. The coordinator
read both XML and isolation reports directly. `summary.json` preserves the exact
selection and exit codes `[0, 0]`. Both isolation reports have no unexpected
denials, all expected sentinels denied, all four cleanup checks true, and only
temporary database paths. Independent verdict: PASS, no material findings.

Cases include both sides of both seasonal clock changes; repeated autumn clock
times as distinct instants; microseconds; source-date rollover while the market
is open; holiday/weekend closures; November 27's 10:00 Pacific close; configurable
premarket starts; invalid timestamps/windows; and exact 06:34:59, 06:35 and 07:15
clock boundaries. None asserts that reaching 06:35 makes bars final or available.

An earlier nearby-test collection attempt at `/tmp/trade-alerts-m04-v8u1f4ct/`
failed because the protected filesystem lacked `scripts.put_flow_shortlist_job`.
The single read-only mount above fixed collection. No guard was relaxed and no
failure was absorbed into `.test-baseline`. This was a launcher boundary repair,
not an application failure.

All three changed Python files passed syntax compilation without application
imports. No repository lint/type-check command is configured; none was invented
or installed. The full application suite was not run and is not claimed passing.

## 5. Preservation and remaining limits

The original clock functions, child protection and existing contract tests match
their backups. The only previously tracked file changed is the clock module;
the launcher, contract-test folder and build documents were already untracked.
The empty failing-test list, source revision, approved D-090 packet body, proposed
M0.3B packet, data requirements, master scope and D-091 ledger are preserved.
Owned files retain `openclaw:openclaw` ownership. No memory file was edited.

Final document checks found no broken local links, unbalanced code fences or
secret-shaped additions. All eight strategy rows and all 31 functional-requirement
rows remain present. Both background programs still reported active, the workspace
shortcut resolved correctly, and the recent model-drift/health-failure check found
no matches. The private backup holds `session-changes.diff` and `final-checks.json`.

Only M1.1's clock portion of AT-02 is complete. M2.2/M3.6 still own finality,
receipt/availability, missing-minute, revision and actual opening-range readiness
proof. Current provider access and unapproved strategy choices retain their
existing gates. The two broader listener test-isolation gaps remain tracked at
M18.4 in M0_4_VERIFICATION; they were not run or claimed fixed here. Live activation
and full release verification remain later milestones.

No broker/Discord contact, restart, Git mutation, order or paid request occurred.
D-091 remains $25 authorized, $0 used and $0 reserved.

## 6. Exact next build: M1.2

Read PROJECT_INDEX and current ROADMAP §31, then inspect the actual configuration
loader, callers and M0.4 configuration tests. Implement one bounded canonical
configuration step: validated non-secret settings, a stable config hash/version
and a fixed session snapshot, while preserving the existing loader/cache/reload
contracts. Do not duplicate the loader or adopt M0.3B/other-strategy choices as
defaults. Keep unresolved choices absent or explicitly unavailable until approved;
missing approval blocks only dependent behavior. Reuse this clock contract for
timing values rather than adding another market calendar.

Use the protected launcher and expand only the fixtures required for the selected
configuration scope. Inspect shared-config dependents and test actual enabled
and disabled paths where applicable. Preserve prior work, D-090 rules, D-091's
cumulative balance, and all existing live/deployment/Git boundaries. Stop after
the scoped milestone, save actual results and the next step, and return the
single-line kickoff required by SESSION_PROTOCOL §32.
