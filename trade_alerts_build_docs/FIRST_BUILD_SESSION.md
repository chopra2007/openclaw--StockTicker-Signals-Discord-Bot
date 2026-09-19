# FIRST_BUILD_SESSION.md

## 1. Current handoff

Prepared 2026-09-05 Pacific. This is a bounded engineering handoff for **M0.4**, subordinate to PROJECT_INDEX, CODING_STANDARDS, ROADMAP and SESSION_PROTOCOL. It is not a new strategy specification. No application code was written in this pre-build session.

A fresh session started by the owner's one-line build kickoff may execute this isolated compatibility milestone. Its inputs are existing interfaces and already approved D-090 facts; it does not depend on approval of new targets, scores, A/C entries or option filters. Keep those proposed choices out of implementation until approved. Do not mark M0.3B approved merely because M0.4 passes.

**Required first-session result (now complete; see M0_4_VERIFICATION.md):** actual existing modules pass focused contract tests inside a process that cannot contact services, load real credentials or open the live database. Existing behavior and limitations are recorded. This starts foundation work; it does not implement or enable a strategy.

## 2. Scope and file ownership

Read current Git status and applicable project rules, then inspect each source before editing. The repository is the parent of these docs. Preserve other sessions' changes; no stash/reset/clean/revert, Git commits or pushes. New scoped test/evidence files may be written locally; preserve all unrelated saved changes. Back up owned edits and preserve `openclaw:openclaw` ownership.

Own new tests under `tests/trade_alerts_contracts/`, a narrowly scoped test launcher under `scripts/testing/` if needed to establish protection before imports, and the matching evidence/handoff docs. Reuse the installed Python test tools. These paths are engineering placement guidance; follow an existing equivalent if fresh inspection finds one. Do not create another bot, data client, scheduler, database layer or generalized test framework.

Do not modify the live application behavior, production settings, dependency files, approved rule packet, startup definitions or existing failing-test list during M0.4. If an existing defect prevents compatibility, reproduce it safely and record the smallest proposed fix and its affected behavior; keep that dependent test honestly failing until a narrowly scoped compatibility remedy is completed. Test/launcher fixes within this milestone are already authorized; an application behavior change belongs in the next explicitly recorded repair scope, with its impact and required checks, rather than being hidden in test setup. The session can complete unaffected contracts. A failed check is not a reason to absorb a failure into `.test-baseline`.

## 3. Required isolation before imports

Static inspection found `consensus_engine/config.py` loads dotenv during module import. `tests/conftest.py` imports application modules through automatic fixtures; its one blocked Discord sender and live/smoke markers do not prevent every network call. Installing guards only inside a test function is too late.

The test launcher must start a child with an explicit minimal environment containing no real credentials. Do not change the parent environment or repurpose HOME/CODEX_HOME. Intercept dotenv loading and deny credential-file reads before importing any application module or collecting application tests. Use an isolated fixture configuration and fixed clock. Do not read or dump the real environment/configuration values to construct the fixture.

Block all outbound sockets/HTTP/DNS before import and before pytest collection, including requests/aiohttp/provider SDK paths and spawned child paths. Block writes outside the owned temporary test directory; block real database and credential-file reads even if code discovers their absolute paths. Disable bytecode/cache writes or route necessary test artifacts to that temporary directory. A guard violation must fail loudly and cannot be caught and converted to a successful test result. Inspect the guard's own failure counters after the run.

Test the guards themselves with benign synthetic attempts: a denied network connection, denied synthetic credential-path read, and denied outside-temp database path. The sentinels must not reach a real service or open real secret contents. An existing process or external live bot does not run under these test guards and must not be restarted or altered.

The existing DB_PATH temporary fixture is a reuse point, not the whole safety boundary. Reject any resolved database path outside the test root before SQLite connects. Close connections and clear module caches at the end so another test cannot inherit the previous state. Recording/dry-run delivery is not remote delivery confirmation.

## 4. Contract cases and exact source anchors

| Case | Actual module under test | Required evidence |
|---|---|---|
| C04-01 import/config isolation | `consensus_engine/config.py` `load_config/get/reload`; `tests/conftest.py` | Guards are active before imports. Only fixture settings are read. Nested values/defaults and caching/reload behavior are pinned; no real dotenv value appears in output. |
| C04-02 history routing | `consensus_engine/utils/prices.py` `fetch_history` | With the existing history flag false, only the fake yfinance boundary is used; with true and a nonempty fake Schwab frame, only Schwab is used. Empty/exception invokes the documented fallback. Preserve old frame shape and call arguments. Explicit call counters prove the chosen branch ran. |
| C04-03 quote/chain mapping | `consensus_engine/scanners/schwab_client.py` `_map_quote`, `_chain_map_to_df` | Synthetic payloads exercise separate quote/last-trade timestamps, invalid/sentinel numeric fields, regular versus extended last-price behavior, multiplier/deliverable/delayed metadata, and unknown versus false borrow. Preserve existing outputs. Record fields still missing for the new consumer; a coarse timestamp or absent provenance is not upgraded to full fidelity by a passing legacy contract. |
| C04-04 calendar | `consensus_engine/utils/time_context.py` `session_dates/session_bounds` | Test ordinary session, known holiday, early close, and a date on each side of a seasonal clock change. Display through America/Los_Angeles only. Compare exact selected dates/bounds against the installed calendar data; do not substitute weekday math. |
| C04-05 database | `consensus_engine/db.py` `init_db/get_db/close_db`, `AsyncConnection.execute_transaction` | Every connection resolves inside the temporary root. Real existing initialization/migrations run there; repeat initialization is idempotent. Inject a failure midway through a multi-statement transaction and verify rollback leaves no partial rows. Test actual modules, not a separate fake DB implementation. |
| C04-06 delivery boundary | `consensus_engine/alerts/discord.py` `_safe_send_kwargs`, `_safe_send`, `send_message` | Existing payload safeguards/chunk behavior remain intact against a fake transport. Success, empty/failure and dry-run results remain distinct. No recording or `dry_run_msg_id` result may be described as confirmed Discord receipt. Preserve the existing last-chunk return limitation and record it for M4.6, rather than claiming whole-message receipt. |
| C04-07 flags and process cleanup | `tests/conftest.py` `_audit_flags_default_off`, `_isolate_db`, HTTP singleton reset | A deliberate enabled-path test still runs after automatic fixtures; assert actual branch call counts, not merely a configured boolean. Run twice in separate child processes and prove no cached connection/settings or unintended writes escape. |

AT-01/AT-04/AT-10 are the parent requirements. M0.4 proves only the contract and isolation slices above; full new-strategy enabled/disabled coverage, canonical timestamp adapters and release proof remain in their later milestones. Tests must expose real mismatches rather than patching the function being asserted to return the expected answer.

## 5. Current facts, limits and data use

Fresh static inspection on 2026-09-05 Pacific found Python 3.10.12, pytest 9.0.2, pytest-asyncio 1.3.0, pandas 2.3.3, numpy 2.2.6, Databento package 0.84.0, aiohttp 3.13.3, PyYAML 5.4.1, python-dotenv 1.2.2 and pandas_market_calendars 5.3.2 in the inspecting interpreter. These are installed versions, not proof that every deployed process uses this interpreter or that dependencies are compatible. M0.4 records its actual interpreter and compares relevant declared/installed requirements before running. Do not upgrade packages merely because a newer release exists.

The existing history adapter can return the same frame shape after switching provider/adjustment basis. The quote mapper currently truncates provider millisecond times to whole seconds. The sender can return the last successful chunk ID after a later chunk fails. Tests should lock those inspected legacy facts while the new consumer's stricter provenance, precision and whole-delivery requirements stay visible. Do not change existing callers or label those gaps fixed by this milestone.

Local metadata confirms selected-60-symbol historical one-minute files exist. Their manifest reports 20,625,054 XNYS.PILLAR minute records and 19,325,105 EQUS.MINI minute records in the named files; this session verified file existence/metadata, not every record. Those datasets and counts do not establish full-market coverage, comparable consolidated volume, point-in-time membership/corporate actions, ten-second acceptance or executable option history. Forward collection reports also contain failed quality checks, as recorded in PREBUILD_REVIEW. Full strategy data gates remain M0.2/M2.

M0.4 uses synthetic fixtures and needs **$0 Databento credit**. Do not buy data to satisfy an isolation or mapping test. Later tests that need Databento may use D-091's cumulative $25 allowance only after source/fields/date range and cost reservations are recorded. Do not treat manifest costs from another project as this allowance's ledger or assume account balance. No credential was read or provider contacted during this handoff preparation.

## 6. Verification and end condition

1. Capture the initial relevant source hashes, Git status, interpreter/dependencies and exact existing failing-test IDs. Compare the checked-in and installed background-program definitions read-only, as CODING_STANDARDS §54 requires. Record the current running source, differences and any unresolved approval of a future deployment source; this is not permission to change either definition. Do not refresh the failing-test list to hide new failures.
2. Establish and verify pre-import isolation, then execute C04-01–C04-07 against actual modules. Record exact commands, results and the temporary artifact paths. Keep all network/credential/database guard failure counts visible.
3. Run focused existing tests for the reused modules under the same protection where compatible. A test excluded for an inspected side effect remains an explicit evidence gap, not a silent pass. Follow project rules for any broader required check; no provider/Discord smoke tests, application launch, deployment or push scripts are authorized here.
4. Compare the final source/Git status and owned changes with the initial snapshot. Confirm no application/config/dependency/live-data changes and no budget usage. Review the owned diff and retain test artifacts outside live storage.
5. Update ROADMAP with the actual C04 outcomes and scope. Complete M0.4 only when all its contract/isolation cases pass; leave later feature/release/data requirements open. M0.3B draft or approval status remains independent.
6. Select the next dependency-ready milestone. If M0.4 passes, the next shared foundation step can be M1.1 calendar/session work; unresolved trading formulas must remain excluded from coding until approved. If M0.4 fails, the next session resumes the named failing contract and its minimal remedy.
7. End with a short result, evidence/remaining blocker, exact next milestone and the mandatory one-line kickoff in SESSION_PROTOCOL §32. Do not ask the owner to reconstruct the handoff or repeat an already recorded approval.

## 7. Handoff verification record

The 2026-09-05 Pacific preparation passed 30 document-integrity and exact synthetic arithmetic checks, including links/source paths, all eight strategy IDs, approved-packet preservation, ownership, boundary scores/costs/profile allocation and unchanged tracked Git state. Independent architecture, scoring/options and research/reliability reviews checked their assigned sections. Their reported timing, stop-touch, missing-outcome-monitoring and wording findings were corrected before handoff. These are documentation checks; C04-01–C04-07 have not run and M0.4 is not marked complete.

## 8. Execution completed — 2026-09-05 Pacific

The first owner-started build completed C04-01–C04-07. See [M0_4_VERIFICATION.md](./M0_4_VERIFICATION.md) for commands, results, artifacts, guard checks, source/runtime comparison and remaining limitations. Section 7 above remains the dated preparation record. That build handed off M1.1, which has since completed, followed by M1.2; current next work is M1.3 in ROADMAP §31. Do not repeat M0.4, M1.1 or M1.2 as unfinished. The first build changed no production application behavior, trading rule, live connection or Databento balance.
