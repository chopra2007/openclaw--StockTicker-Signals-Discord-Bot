# M0.4 compatibility evidence

Historical evidence and handoff: M1.1 has since completed in
[M1_1_VERIFICATION.md](./M1_1_VERIFICATION.md). Use ROADMAP §31 for current next work.

## 1. Result and scope

Completed 2026-09-05 Pacific. C04-01–C04-07 pass against the actual existing application modules. This closes only M0.4's compatibility/isolation slices of AT-01/AT-04/AT-10. Full canonical quote handling, strategy behavior, replay, live shadow and release acceptance remain with their later ROADMAP owners.

The session added tests and a protected launcher, and synchronized the handoff documents. No production application, configuration, dependency, deployment definition, approved trading-rule packet or existing failing-test list was changed. No broker/Discord contact, restart, Git mutation, trade or paid data request occurred. D-091 remains $25 authorized, $0 used and $0 reserved.

This is a supporting evidence record under PROJECT_INDEX, not a new canonical specification or proof of profitable trading.

## 2. Files and protection

- [Launcher](../scripts/testing/run_trade_alerts_contracts.py): starts two fresh child processes with a minimal explicit environment. Uses the installed `bwrap` tool to give each child separate process/network/mount areas, read-only code/libraries and one writable temporary directory. It runs as the existing `openclaw` account when launched by root; no parent environment is copied or changed.
- [Child protection](../scripts/testing/trade_alerts_contract_child.py): installs denial accounting before application imports and pytest collection; intercepts dotenv, rejects credential reads, outbound sockets/DNS, subprocess creation, non-temporary database connections and outside writes. Unexpected denials fail the process even when caught; unsuccessful cleanup also fails it.
- [Test fixtures](../tests/trade_alerts_contracts/conftest.py): synthetic configuration, real temporary database and connection closure before the parent fixture discards its cache.
- [Foundation contracts](../tests/trade_alerts_contracts/test_foundations.py): configuration, calendar, database, enabled flag and cleanup cases.
- [Adapter/delivery contracts](../tests/trade_alerts_contracts/test_adapters_delivery.py): history, quote/chain and fake-transport delivery cases.

The live configuration, credentials, data directories and Git metadata are absent from the child filesystem. Existing source files are mounted read-only. The child intercepts only the database module's hardcoded source-list file open to supply an empty synthetic registry; real initialization and migrations still execute. The diagnostic logger writes into temporary storage. The test environment declares IPv6 unavailable to suppress the installed urllib3 import-time socket probe; this is reported explicitly and is not a production IPv6 test.

Each child deliberately attempts six benign forbidden operations before application imports: IPv4 socket creation, DNS lookup for a synthetic invalid name, synthetic credential-file read, outside database connection, outside write and child-process launch. All six are denied and counted. These expected sentinels are recorded separately from unexpected access attempts. Ordinary pytest discovery skips the two launcher-only modules before application imports; a skip does not complete any contract.

## 3. Executed evidence

Run from the repository root:

```bash
python3 scripts/testing/run_trade_alerts_contracts.py tests/trade_alerts_contracts
```

Result: **31 passed in each of two fresh processes**, no skipped contracts, no unexpected denials, all four cleanup checks true. Artifacts: `/tmp/trade-alerts-m04-fmhh5kgi/run-1/` and `run-2/`, each containing `output.txt`, `results.xml`, `isolation.json` and temporary fixture records. The parent `summary.json` records both successful exit codes. All four SQLite connection openings in each contract run resolve inside that run's temporary mount.

| Contract | Directly tested behavior |
|---|---|
| C04-01 | Dotenv intercepted before imports; fixture-only nested configuration/defaults, cache identity and reload, synthetic environment substitution. |
| C04-02 | Disabled provider branch, enabled nonempty result, empty/None/exception fallback; exact forwarded arguments and explicit call counts. Legacy frame shape preserved. |
| C04-03 | Regular versus extended last price; independent quote/trade time; invalid/sentinel numbers; false versus unknown borrow; contract quote time, IV units, missing multiplier/Greeks, deliverable and delayed-chain fields. |
| C04-04 | Exact installed-calendar dates/bounds for ordinary sessions, holiday/weekend, early close and both sides of a seasonal clock change; fixed-clock Pacific display. July 2, 2026 is correctly a full session in the installed calendar; November 27 is the early-close case. |
| C04-05 | Actual schema and all version rows 7–34; temporary connection path; cache reuse; close/reopen with identical schema/versions; failed two-statement transaction leaves zero rows. |
| C04-06 | Real payload safety/clipping and sender logic against fake HTTP responses; success, empty response, 400 fallback, 429 retry, server/network failure, dry run, missing token and partial chunk result. Fake transport IDs are not confirmed Discord receipts. |
| C04-07 | Automatic flags demonstrably override enabled fixture settings; an explicit enabled test calls the actual selected history branch. Clean database/settings/HTTP state at test entry and process cleanup; two independent runs. |

Nearby existing coverage also passed: **52 tests in each of two protected processes**, zero unexpected denials, all cleanup checks true. Artifacts: `/tmp/trade-alerts-m04-govgldkv/`. Its `summary.json` preserves the exact command argument list: `tests/test_schwab_client.py`, `test_fetch_history_extended_hours.py`, `test_db.py`, `test_feature_flags.py`, `test_discord_embed_limits.py`, and the six `test_step8_safe_send_*` cases in `test_pass5_steps_6_7_8.py` (success, 400 fallback, 429 retry/exhaustion, server failure and network exception).

An independent reviewer reran the combined final selection after all test/launcher changes: **83 passed in each of two fresh processes (166 executions)**. Final evidence is `/tmp/trade-alerts-m04-vhayew2d/`, including the exact 12-argument test selection in `summary.json`, both `results.xml` files and both `isolation.json` files. Both exits are zero, unexpected denial maps are empty, and all cleanup checks pass. Final review: approved, no remaining findings in the assigned protection/foundation scope.

Earlier exploratory failures were retained rather than added to `.test-baseline`. Mount permissions required launching as `openclaw`; pytest logging, IPv6 capability probing, source-list reads and diagnostic writes required the explicit test boundaries above. One hand-written calendar expectation was corrected against the installed calendar. Those were launcher/fixture repairs; production functions were unchanged.

A wider 62-test attempt in `/tmp/trade-alerts-m04-7w1hc505/` returned **60 passed and 2 failed in both processes**. The exact remaining IDs are:

- `tests/test_pass5_steps_6_7_8.py::test_step6_buffer_drains_on_ready_in_arrival_order`
- `tests/test_pass5_steps_6_7_8.py::test_step6_bot_user_id_shortcut_bypasses_buffer`

Those listener tests reach `_route_message` → `_add_ack_reaction` → `_react` with an unmocked HTTP request. The guard stopped DNS before contact. They are outside the selected sender contracts and are explicitly excluded from the final focused sender command, not claimed passing. M18.4 owns their minimal remedy: supply a fake reaction transport in those tests, preserve ordering/routing assertions, then rerun them under protection. Do not weaken the network guard or change application behavior to hide this test-isolation gap.

The stored failing-test list was empty on entry and stays unchanged. The full application suite was not run; this session makes no full-suite passing claim. Ordinary collection of only the new guarded modules returned no tests collected (exit 5), with no collection error or application fixture execution; this was a discovery check, not a passing contract run.

## 4. Runtime, deployment and source preservation

Test interpreter: `/usr/bin/python3`, Python 3.10.12, matching the installed engine launch and the README's Python 3.10+ support. Tested installed packages include pytest 9.0.2, pytest-asyncio 1.3.0, pytest-timeout 2.4.0, pandas 2.3.3, numpy 2.2.6, aiohttp 3.13.3, PyYAML 5.4.1, python-dotenv 1.2.2, pandas_market_calendars 5.3.2 and yfinance 1.2.0. Ten relevant declared dependency bounds were compared with installed metadata and satisfied. No package upgrade was made. There is no configured repository lint/type-check command; new Python files are checked by syntax compilation and executed tests.

Read-only installed-versus-repository startup comparison confirms the running source is `/etc/systemd/system/consensus-engine.service` and `/etc/systemd/system/openclaw-gateway.service`, with the gateway's existing `10-selfheal.conf` addition. Both programs reported active. Startup commands agree; installed definitions add prerequisite-file checks, failure reporting and memory caps (3G engine, 2G gateway). The gateway also differs in restart burst/window controls. The repository copies are not a demonstrated safe replacement. An approved future reconciled deployment/rollback source remains M18.6 work before deployment; this session grants no approval to overwrite either source. The configured recovery addition was inspected read-only. Recent model-drift/health-failure log match count was zero.

Private backups and preservation proof: `/root/trade-alerts-m04-20260905/` contains the original documentation, `initial.json` source hashes/Git status/revision/failing-test IDs, `runtime.json`, `compatibility.json` and the gateway addition summary. Starting saved revision: `69044b270be08b5628606c0cd8a6717724904589`. Initial status contained untracked `data/` and `trade_alerts_build_docs/`; these were preserved. Owned repository files retain `openclaw:openclaw` ownership. No memory file was edited.

## 5. Remaining limits and owners

- M2.1/M2.2: legacy whole-second quote times, regular-session last-price preference and history fallback without canonical source/adjustment provenance remain unchanged. Passing old contracts does not establish new-consumer fidelity or provider access.
- M4.6: `send_message` can return a prior successful chunk ID after a later chunk fails. Whole-message acknowledgment and recovery remain unbuilt.
- M18.4: the two broader listener tests above still need explicit fake acknowledgment transport. Full release/old-command enabled-and-disabled proof remains open.
- M18.6: reconcile and approve a future deployment/rollback source while retaining installed protections.
- M0.2/M0.3: current data access/coverage and unapproved M0.3B/other-strategy definitions remain separate gates. This milestone changes neither data status nor trading approval.

## 6. Exact next build: M1.1

Read PROJECT_INDEX and its canonical documents, then current ROADMAP §31. Build one bounded shared time/session component by extending or adapting `consensus_engine/utils/time_context.py`; inspect all callers before choosing the smallest compatible change. Reuse its installed exchange calendar and preserve existing caller behavior. New display uses `ZoneInfo("America/Los_Angeles")` and correct seasonal labels. Cover absolute timestamps, session date/open/close, approved session windows, premarket, holidays, early closes and seasonal clock changes with fixed-clock tests. Explicitly distinguish a clock boundary from data finality: reaching 06:35 alone cannot claim all five opening bars are available.

Use the isolated launcher for relevant offline execution and expand only the fixtures needed for that scope. Preserve pre-import guards, actual-module assertions, temporary storage, source comparisons and explicit denial/cleanup results. Missing data or unapproved strategy formulas block their dependent logic only; do not implement A/C entries, scores, targets or options rules from M0.3B. No live activation, external messages, orders, restarts or Git mutation is authorized by this handoff. Stop after M1.1 and save actual progress plus SESSION_PROTOCOL §32's one-line kickoff.
