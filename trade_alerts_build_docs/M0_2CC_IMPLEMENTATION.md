# M0.2CC off-by-default cleanup implementation

## Scope

The cleanup action now consumes the existing `plan_retention` result. It is a
separate `cleanup` command. Checked-in `cleanup_enabled` remains `false`, so the
command prints the dry-run plan and removes nothing by default.

An explicitly enabled run can remove only the three already approved classes:
verified minute option parts, verified duplicate temporary set members and
expired zero-byte notification markers. Primary and supporting research records
are not candidates.

## Safety checks

Immediately before each removal the action rechecks the configured root, legal
holds, target identity and the class-specific age rule. For minute parts and
temporary duplicates it also rechecks the immutable publication pointer, proof,
chain, open-interest file and every source identity that has not already been
removed by the same cleanup run. A new, missing, changed, linked or escaped path
stops the run.

Each target gets its own durable result file. The action records removal
authorization before unlinking the target, flushes the target folder after the
unlink, then records `removed`. A mismatch, result-write failure or removal
error stops the run at that file. The result write also respects the storage
reserve and a 16,384-byte bound.

## Verification boundary

The focused checks use only temporary synthetic files. No owner file is a test
target. The initial sandbox ownership failure is historical. Current controller
proof passes the focused mention cases and broad acceptance, including the full
storage and collector files. The required cleanup recording is absent from both
published repeatability runs, so M0.2CC remains blocked on that comparison. The
records-only proof reconciliation below holds the exact published results and
original tested-source identity. Cleanup, compaction, collection and every live
switch remain off.

This implementation does not qualify a market source, close a D-104 gap, open
Strategies #5 through #8, prove a result or authorize live use.

## Historical escalated diagnosis — 2026-09-24 Pacific

Status at that diagnosis: **blocked on a separately reviewed protected-input repair**.
The current continuation below supersedes this status; the failure remains recorded.
The earlier sandbox ownership error above describes the first local attempt.
The controller subsequently reached collection and reported
`KeyError: 'storage'` in
`tests/test_full_chain_collector.py::test_storage_cleanup_is_checked_in_off_and_dry_run_is_default`.
The original controller log is
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/verification.log`;
its artifacts path is `/tmp/trade-alerts-m04-43ku_89e`.

The cause is the protected settings substitution. In
`scripts/testing/run_trade_alerts_contracts.py`, `sandbox_command` mounts
`tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml` at
`/workspace/config/full_chain_collector.yaml`. That substitute file has no
`storage` section. The actual checked-in `config/full_chain_collector.yaml`
does have `storage.cleanup_enabled: false`. The failing assertion therefore
reads the substitute rather than the checked-in storage switch. The action
itself uses an absent-switch default of false; this does not establish the
checked-in-switch assertion or replace its required proof.

The different approach in this attempt was to trace the loaded settings back
through the protected mount, rather than rerun the same failing command or
weaken the assertion. No product code, tests, configuration, protected inputs
or launcher files were changed in this diagnosis. No test command was rerun.
The supplied escalation rule requires a blocked result when the cause lies
outside the milestone code. A separately reviewed protection repair must
resolve how the protected test verifies the checked-in switch while keeping
the sanitized temporary output root and isolation intact.

The supplied controller focused summary records `runs: 1`, `exit_code: 1`,
`test_count: null`, and selection reason
`builder named directly affected checks`. Its selectors, in published order:

- `tests/test_full_chain_collector.py::test_storage_cleanup_is_checked_in_off_and_dry_run_is_default`
- `tests/test_full_chain_storage.py::test_cleanup_defaults_to_dry_run_and_removes_nothing`
- `tests/test_full_chain_storage.py::test_cleanup_removes_only_revalidated_planned_classes_and_records_each_result`
- `tests/test_full_chain_storage.py::test_cleanup_stops_before_removal_when_eligibility_changes`
- `tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`

The controller log preserves `1 failed in 2.34s` for the collector group and
`4 passed in 2.66s` for the storage group. These are pytest lines, not controller
wall times or JUnit times. The supplied summary has no wall time. No successful
broad acceptance or two-run M0.2CC comparison is supplied; the controller must
supply those figures and artifacts after the focused failure is resolved.
The storage group's passing cases do not establish milestone acceptance.

The complete milestone delta remains:
`config/full_chain_collector.yaml`, `consensus_engine/full_chain_storage.py`,
`scripts/full_chain_collector.py`, `tests/test_full_chain_collector.py`,
`tests/test_full_chain_storage.py`, `trade_alerts_build_docs/M0_2CC_IMPLEMENTATION.md`,
and `trade_alerts_build_docs/ROADMAP.md`. Prior work, failures and attempt history
are preserved. Only these implementation and roadmap records changed in this
diagnosis. Cleanup and all live switches remain off. M0.2CD remains conditional
on M0.2CC acceptance and is not an independent next step while this gate is open.

## Historical continuation — 2026-09-24 Pacific

Direct inspection now finds the `storage` section in the protected substitute
`tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml`, including
`cleanup_enabled: false`. Its output root remains
`/tmp/test-full-chain-collector`. The launcher still mounts that file read-only
as the collector configuration. No protected file was edited in this continuation.
The earlier missing-section diagnosis explains the published failure but no
longer describes the current fixture.

The different approach was to inspect the actual mounted input before deciding
whether product code needed repair. The test assertion and product code were
preserved. With the missing section now present, the five focused selectors
listed above were submitted once to the unchanged protected launcher. It
stopped before collection at `os.chown(artifact_root, account.pw_uid,
account.pw_gid)` with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-al5onlwl'`.
This reproduced sandbox limitation was not retried. No application test ran
outside protection and no new test pass is claimed.

Current status: **ready for controller protected verification**. The controller
must supply fresh focused and broad acceptance proof, required two-process
recording comparison, tested-source identity, isolation and cleanup results,
and the published phase selectors, counts and timings. The failed controller
proof above remains historical evidence, not acceptance of the current inputs.
Independent review remains required. Only this record and ROADMAP were edited
in this continuation; the complete milestone delta above is preserved. Cleanup
and every live switch remain off. M0.2CD is the next step only after M0.2CC
acceptance; this handoff does not authorize advancing around a failed check.

## Historical controller proof finalization — 2026-09-24 Pacific

Independent review rejected this selection as incomplete coverage of the complete
milestone delta. These passing results remain historical collected-case evidence;
they do not establish M0.2CC acceptance. The current coverage repair below governs. The focused phase ran once with
`tests/test_full_chain_collector.py::test_storage_cleanup_is_checked_in_off_and_dry_run_is_default`:
one test passed, with controller wall time `3.796` seconds and JUnit time
`2.000` seconds. The broad acceptance phase ran once with the published six
selectors (the contracts directory plus that collector selector and the four
storage selectors): 4,560 tests passed, with controller wall time `1091.181`
seconds. Its three JUnit worker-suite times were `864.879`, `1086.525`, and
`952.398` seconds. All reported zero failures, errors, and skips.

The historical repeatability phase used the controller's published selector list
and reported `test_count: 109` with `runs: 2`: both passed, and the controller recorded wall
time `445.05` seconds. Its published artifacts compare the two runs; the
M0.2CC cleanup proof is an acceptance-run artifact, at
`published-artifacts-8ad1001d6fd6/run-1/m02cc-cleanup-proof.json`, with SHA-256
`48b037e63f0328a78b1285d9d39ea4d3aa5038ba5eda7537657ef16d2302a855`.
The controller's protected isolation records report no unexpected denials and
successful cleanup. The tested source hash is
`2ba42fb7ebfce481ce4fda97a66aa778e3d706806e5c5d85c0bd2b31ea83bc41`;
the complete tested manifest is
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/verified-manifest.json`.

These record edits do not change code, tests, configuration, or protected
inputs. Cleanup remains off by default; no owner file was removed, and no
source, strategy, validation, or live gate changed. M0.2CD remains a separate
assessment after independent review accepts M0.2CC.

## Historical escalated coverage repair — 2026-09-24 Pacific

The review failure was incomplete test selection, not a reported product-test
failure. The earlier broad phase selected individual cleanup cases instead of
all of `tests/test_full_chain_storage.py` and `tests/test_full_chain_collector.py`.
It therefore omitted affected retention, recovery, containment, reserve and
caller checks. The complete delta also includes the gateway reply and retry
changes in `consensus_engine/main.py`, the corresponding helper change in
`scripts/qa_feature_questions.py`, and `tests/test_handle_mention.py`; no mention
check was collected. A passing contracts-family run cannot cover those omissions.

The different approach is to carry the complete controller delta forward and
submit full affected files, including the dependent watchdog checks, instead of
resubmitting the earlier individual cleanup selection. Product code, tests,
configuration and protected inputs are preserved. The required focused selectors
are:

- `tests/test_full_chain_collector.py`
- `tests/test_full_chain_storage.py`
- `tests/test_handle_mention.py`
- `tests/test_agent_watchdog.py`

The unchanged protected launcher was invoked with that expanded selection and
stopped before collection at its temporary-directory ownership operation:
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ayqwiub2'`.
The sandbox failure was not retried, and no application test ran outside
protection. Status is **ready for controller protected verification**, not
accepted. The controller must publish the focused phase, then its required broad
selection including every file above; a focused failure stops broader execution.
The broad contracts family was not self-run. New counts, phase selectors, timings,
source identity, isolation and cleanup findings will come from controller proof.

The prior repeatability publication is
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-8d0b47d804c2`.
Its `summary.json` does not select the M0.2CC recording test, and neither `run-1`
nor `run-2` contains `m02cc-cleanup-proof.json`. Its successful comparisons do not
prove cleanup repeatability. Explicitly include
`tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`
in both fresh repeatability runs, and verify collection plus the emitted
`m02cc-cleanup-proof.json` identity and comparison in the published artifacts.
The existing test already writes this deterministic synthetic cleanup record;
no test or selector-discovery mechanism was altered here.

The complete milestone delta supplied by the controller is:

- `config/full_chain_collector.yaml`
- `consensus_engine/full_chain_storage.py`
- `consensus_engine/main.py`
- `scripts/full_chain_collector.py`
- `scripts/qa_feature_questions.py`
- `tests/test_full_chain_collector.py`
- `tests/test_full_chain_storage.py`
- `tests/test_handle_mention.py`
- `tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml`
- `trade_alerts_build_docs/M0_2CC_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

Only this document and ROADMAP changed in this repair. The earlier smaller delta
list describes that historical diagnosis, not the current complete delta.
Original failures, passing collected cases, source manifests and attempt history
remain preserved. Cleanup and all live switches remain off. No owner data was
removed. M0.2CD remains open only after M0.2CC acceptance; it is not independent
work around missing verification. Source, strategy and live gates are unchanged.

## Historical escalated mention-test diagnosis — 2026-09-24 Pacific

The expanded controller focused run reached the mention tests and failed with
`IsolationViolation: M0.4 isolation denied: outside_read`. The preserved log is
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/verification.log`,
which names `/tmp/trade-alerts-m04-pocnjc52` as its artifact root. Its pytest
line is `7 failed, 49 passed, 10 warnings in 9.34s`; this is not a controller
wall time or a JUnit time. The failing cases in `tests/test_handle_mention.py`
are:

- `test_handle_mention_retry_then_success_on_second_attempt`
- `test_handle_mention_cheap_failures_walk_the_whole_chain`
- `test_handle_mention_timeouts_stop_at_the_timeout_budget`
- `test_handle_mention_aborted_run_not_posted[meta_aborted]`
- `test_handle_mention_aborted_run_not_posted[stub_text]`
- `test_retry_changes_both_model_and_session`
- `test_live_session_is_size_checked_before_the_first_attempt`

Every traceback follows `_handle_mention` through `_build_agent_watchdog` and
`AgentWatchdog.__init__` to `row_ids` / `_rows`, where opening the transcript
is denied. The watchdog builds that path from its `SESSION_DIR` setting.
The saved pre-run delta did not redirect that setting in the mention fixture.
The current `pinned_agent_chain` fixture now accepts `tmp_path` and patches
`agent_watchdog.SESSION_DIR` to that temporary directory. This existing edit
postdates the failed log and is preserved; the failed run does not test it.

The different approach was to trace the denied read to the exact test input
and compare the current fixture with the saved delta before running anything.
The fix keeps the real watchdog active with synthetic session files rather
than bypassing the watchdog or weakening the protected file boundary. No
additional code, test, configuration or protected-input edit was needed in
this session. Only this record and ROADMAP were changed.

The supplied controller summary has `tests.runs: 1`, `tests.test_count: null`,
`exit_code: 1`, and `tests.selection_reason: builder named directly affected checks`.
It describes focused verification; no separate `tests.phase` or `tests.focused`
object or `tests.wall_seconds` is supplied. Its `tests.selectors`, in supplied
order, are:

- `tests/test_agent_watchdog.py`
- `tests/test_full_chain_collector.py`
- `tests/test_full_chain_storage.py`
- `tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`
- `tests/test_handle_mention.py`

After diagnosis, the unchanged protected launcher was tried once with
`tests/test_handle_mention.py` and `tests/test_agent_watchdog.py` so the reported
failures and their immediate dependency come first. It stopped before collection
at `os.chown(artifact_root, account.pw_uid, account.pw_gid)` with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-8_zz3_s5'`.
The sandbox failure was not retried. No broader stage or unprotected application
test was run, and no new passing result is claimed.

Status is **ready for controller protected verification** of the current fixture.
The controller must supply fresh focused and broad acceptance figures, source
identity, isolation and cleanup evidence, followed by the required two-run
recording comparison. Both repeatability runs must actually collect
`tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`
and emit and compare `m02cc-cleanup-proof.json`. Prior passing selections and
their manifests remain historical evidence; they cannot establish acceptance
of the current test setup. The complete milestone delta listed above is unchanged.
All failed attempts remain preserved. Cleanup and all live switches remain off;
no owner data was removed. M0.2CD remains conditional on M0.2CC acceptance.

## Current controller-proof assessment — 2026-09-24 Pacific

The supplied controller proof has a successful focused phase: its seven named
mention selectors passed once. The broad acceptance phase also passed once with
the published selectors `tests/trade_alerts_contracts`,
`tests/test_agent_watchdog.py`, `tests/test_full_chain_collector.py`,
`tests/test_full_chain_storage.py`, and `tests/test_handle_mention.py`. It
records `test_count: 5012`, `wall_seconds: 1218.847`, source hash
`3b27b0639e86401899bac77fb47c5c6cd43fcbd6491fe66eea78340fae3132bc`, and
the broad artifact includes `m02cc-cleanup-proof.json` with SHA-256
`48b037e63f0328a78b1285d9d39ea4d3aa5038ba5eda7537657ef16d2302a855`.

The separate repeatability phase reports `test_count: 109` and `runs: 2`
for its published selectors. Its published selector list and both artifact file lists do
not include
`tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`
or `m02cc-cleanup-proof.json`. Therefore that phase does not compare the new
cleanup recording, and the broad proof cannot replace the required two-process
comparison. This is a proof gap, not a product-test failure. No code, test,
configuration, or protected input was changed while recording this assessment.
Cleanup and every live switch remain off; no owner file was removed. M0.2CD
remains conditional on accepted M0.2CC and is not an independent next step.

## Records-only proof reconciliation — 2026-09-24 Pacific

Current status: **blocked on required cleanup repeatability evidence**.
The supplied request permits only evidence and roadmap edits. No test was rerun;
no code, test, configuration, protected input or launcher was changed. The earlier
mention failure came from the watchdog reading its live session directory. The
existing temporary-directory fixture repair now has passing focused proof. The
different approach here is to inspect actual phase selectors, collected test
records and published file hashes instead of repeating that resolved failure.

The remaining cause is outside the cleanup action: the controller's repeatability
selection omits `tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`.
Neither published repeatability run collects that case or emits
`m02cc-cleanup-proof.json`. No M0.2CC comparison or paired hashes exist there.
The acceptance-run copy alone cannot establish the required fresh-process
comparison. The protected selection/proof gate requires supervisor resolution;
this records-only assignment does not authorize changing selection machinery.

The JSON below copies the controller phase figures and selectors, in published
order. `test_count` is a collected-case count, not a selector count. The top-level
`tests.phase` was not supplied; the top-level object is the broad acceptance
result. Focused and repeatability phase names were supplied. Controller wall
seconds, JUnit suite times and pytest lines are distinct measures, kept separate.
These are published controller runs, not runs performed during this finalization.

```json
{
  "tests": {
    "runs": 1,
    "test_count": 5012,
    "wall_seconds": 1218.847,
    "selection_reason": "unknown dependency impact; safe broad fallback",
    "selectors": [
      "tests/trade_alerts_contracts",
      "tests/test_agent_watchdog.py",
      "tests/test_full_chain_collector.py",
      "tests/test_full_chain_storage.py",
      "tests/test_handle_mention.py"
    ],
    "exit_codes": [
      0
    ],
    "artifacts_path": "/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-303c76c7e307",
    "publication": "/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-303c76c7e307/publication.json",
    "summary_sha256": "ccc6f2e2fee874083b046f288f591a26a0a1fdf2432d81db8b4c5ed115000ca7",
    "run_details": {
      "run-1": {
        "junit_suites": [
          {
            "tests": "2181",
            "failures": "0",
            "errors": "0",
            "skipped": "0",
            "time": "1213.300"
          },
          {
            "tests": "1666",
            "failures": "0",
            "errors": "0",
            "skipped": "0",
            "time": "960.270"
          },
          {
            "tests": "1165",
            "failures": "0",
            "errors": "0",
            "skipped": "0",
            "time": "841.533"
          }
        ],
        "pytest_lines": [
          "2181 passed, 10 warnings in 1213.45s (0:20:13)",
          "1666 passed in 960.38s (0:16:00)",
          "1165 passed in 841.62s (0:14:01)"
        ],
        "unexpected_denials": {},
        "cleanup": {
          "db_closed": true,
          "http_closed": true,
          "config_cleared": true,
          "http_lock_cleared": true
        }
      }
    },
    "focused": {
      "phase": "focused",
      "runs": 1,
      "test_count": 7,
      "wall_seconds": 5.61,
      "selection_reason": "builder named directly affected checks",
      "selectors": [
        "tests/test_handle_mention.py::test_handle_mention_retry_then_success_on_second_attempt",
        "tests/test_handle_mention.py::test_handle_mention_cheap_failures_walk_the_whole_chain",
        "tests/test_handle_mention.py::test_handle_mention_timeouts_stop_at_the_timeout_budget",
        "tests/test_handle_mention.py::test_handle_mention_aborted_run_not_posted[meta_aborted]",
        "tests/test_handle_mention.py::test_handle_mention_aborted_run_not_posted[stub_text]",
        "tests/test_handle_mention.py::test_retry_changes_both_model_and_session",
        "tests/test_handle_mention.py::test_live_session_is_size_checked_before_the_first_attempt"
      ],
      "exit_codes": [
        0
      ],
      "artifacts_path": "/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-768b30fbeb74",
      "publication": "/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-768b30fbeb74/publication.json",
      "summary_sha256": "e68d31a734a2f521866a448904ae6f184e45549122343ce04862c85b96db9ae6",
      "run_details": {
        "run-1": {
          "junit_suites": [
            {
              "tests": "7",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "3.515"
            }
          ],
          "pytest_lines": [
            "7 passed, 10 warnings in 3.51s"
          ],
          "unexpected_denials": {},
          "cleanup": {
            "db_closed": true,
            "http_closed": true,
            "config_cleared": true,
            "http_lock_cleared": true
          }
        }
      }
    },
    "repeatability": {
      "phase": "repeatability",
      "runs": 2,
      "test_count": 109,
      "wall_seconds": 447.058,
      "selection_reason": "recording output requires fresh-process comparison",
      "selectors": [
        "tests/trade_alerts_contracts/test_alert_delivery.py::test_bars_to_candidates_to_recording_and_fake_delivery_end_to_end",
        "tests/trade_alerts_contracts/test_candidate_assembly.py::test_supplied_features_confidence_candidate_suppression_recording_end_to_end",
        "tests/trade_alerts_contracts/test_confidence.py::test_supplied_features_composition_candidate_recording_end_to_end",
        "tests/trade_alerts_contracts/test_configuration.py::test_known_default_hash_matches_canonical_record",
        "tests/trade_alerts_contracts/test_core_price_features.py::test_bar_to_coverage_to_feature_snapshot_recording_end_to_end",
        "tests/trade_alerts_contracts/test_cross_strategy_interaction.py::test_recording_is_deterministic_and_retains_every_component_candidate",
        "tests/trade_alerts_contracts/test_databento_minute_bars.py::test_recorded_source_identity_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_domain_models.py::test_deterministic_record_proof_is_written_under_tmp",
        "tests/trade_alerts_contracts/test_first_pullback_vwap.py::test_the_supplied_continuation_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_first_pullback_vwap_replay.py::test_the_same_supplied_scenario_replays_byte_identically",
        "tests/trade_alerts_contracts/test_first_pullback_vwap_replay.py::test_the_two_scenarios_record_one_deterministic_proof",
        "tests/trade_alerts_contracts/test_historical_bars.py::test_request_raw_mapping_coverage_and_archive_end_to_end",
        "tests/trade_alerts_contracts/test_historical_replay.py::test_chronological_same_runtime_replay_is_byte_deterministic",
        "tests/trade_alerts_contracts/test_hod_comp_rs_replay.py::test_the_same_supplied_scenario_replays_byte_identically",
        "tests/trade_alerts_contracts/test_hod_comp_rs_replay.py::test_the_five_scenarios_record_one_deterministic_proof",
        "tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py::test_the_composed_outcome_at_one_recorded_trigger",
        "tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py::test_the_supplied_heads_up_and_trigger_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_hod_compression.py::test_hod_compression_recording_end_to_end",
        "tests/trade_alerts_contracts/test_hod_compression_research_adapter.py::test_hod_compression_research_recording_end_to_end",
        "tests/trade_alerts_contracts/test_impulse_pullback.py::test_impulse_pullback_recording_end_to_end",
        "tests/trade_alerts_contracts/test_impulse_pullback_research_adapter.py::test_impulse_pullback_research_recording_end_to_end",
        "tests/trade_alerts_contracts/test_opening_range_features.py::test_bar_coverage_opening_range_recording_end_to_end",
        "tests/trade_alerts_contracts/test_options_portfolio.py::test_projection_json_is_deterministic_and_keeps_every_independent_id",
        "tests/trade_alerts_contracts/test_or_failure_handoff.py::test_the_supplied_handoff_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_or_failure_handoff_research_adapter.py::test_bar_coverage_handoff_opening_range_recording_end_to_end",
        "tests/trade_alerts_contracts/test_or_failure_rev.py::test_the_supplied_reversal_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_or_failure_rev_replay.py::test_the_same_supplied_scenario_replays_byte_identically",
        "tests/trade_alerts_contracts/test_or_failure_rev_replay.py::test_the_two_scenarios_record_one_deterministic_proof",
        "tests/trade_alerts_contracts/test_orb5_eligibility.py::test_shared_features_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_orb5_replay.py::test_the_same_supplied_scenario_replays_byte_identically",
        "tests/trade_alerts_contracts/test_orb5_replay.py::test_the_six_scenarios_record_one_deterministic_proof",
        "tests/trade_alerts_contracts/test_orb5_risk_confidence.py::test_the_composed_outcome_at_one_recorded_trigger",
        "tests/trade_alerts_contracts/test_orb5_trigger.py::test_the_supplied_trigger_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_outcome_evaluator.py::test_compact_end_to_end_recording",
        "tests/trade_alerts_contracts/test_participation_features.py::test_bar_coverage_participation_recording_end_to_end",
        "tests/trade_alerts_contracts/test_quote_events.py::test_normalized_events_failure_reconnect_recording_end_to_end",
        "tests/trade_alerts_contracts/test_reference_inputs.py::test_supplied_reference_coverage_recording_end_to_end",
        "tests/trade_alerts_contracts/test_relative_strength_features.py::test_relative_strength_recording_end_to_end",
        "tests/trade_alerts_contracts/test_request_queue.py::test_recorded_load_proof_is_deterministic_and_contains_every_consumer",
        "tests/trade_alerts_contracts/test_research_event_store.py::test_recording_pipeline_retains_full_facts_retry_and_reopen",
        "tests/trade_alerts_contracts/test_retained_candidate_events.py::test_recorded_candidate_event_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_four_candidate_run.py::test_recorded_first_four_candidate_run_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_four_evaluator_binding.py::test_recorded_evaluator_binding_is_deterministic_and_keeps_later_release_off",
        "tests/trade_alerts_contracts/test_retained_first_four_evaluator_drive.py::test_recorded_exact_context_drive_is_deterministic_and_keeps_release_off",
        "tests/trade_alerts_contracts/test_retained_first_four_evaluator_owner.py::test_recorded_owner_construction_is_deterministic_and_does_not_advance",
        "tests/trade_alerts_contracts/test_retained_first_four_evaluator_plan.py::test_recorded_first_four_evaluator_plan_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_four_evaluator_run.py::test_recorded_first_four_evaluator_run_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_four_fill.py::test_recorded_candidate_fill_is_deterministic_and_keeps_later_release_off",
        "tests/trade_alerts_contracts/test_retained_first_four_outcome.py::test_recorded_outcome_connection_is_deterministic_and_keeps_release_off",
        "tests/trade_alerts_contracts/test_retained_first_four_owner_inputs.py::test_recorded_owner_input_admission_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_four_sample_restart.py::test_recorded_sample_restart_is_deterministic_and_keeps_later_release_off",
        "tests/trade_alerts_contracts/test_retained_first_four_stage1_result.py::test_recorded_stage1_result_connection_is_deterministic_and_keeps_release_off",
        "tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_two_producers.py::test_recorded_first_two_request_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_recorded_offline_input_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py::test_recorded_parent_scan_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas",
        "tests/trade_alerts_contracts/test_retained_remaining_producers.py::test_recorded_remaining_producer_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_stage1_candidate_groups.py::test_recorded_candidate_groups_are_deterministic_and_keep_measurement_closed",
        "tests/trade_alerts_contracts/test_retained_stage1_candidate_measurements.py::test_recorded_candidate_measurements_are_deterministic_and_keep_release_closed",
        "tests/trade_alerts_contracts/test_retained_stage1_measurement_catalog.py::test_recorded_full_candidate_catalog_is_deterministic_and_keeps_ranking_closed",
        "tests/trade_alerts_contracts/test_retained_stage1_ranking.py::test_recorded_stage1_ranking_is_deterministic_and_keeps_later_release_closed",
        "tests/trade_alerts_contracts/test_retained_stage2_input.py::test_recorded_retained_stage2_input_is_deterministic_and_keeps_stage2_closed",
        "tests/trade_alerts_contracts/test_retained_stage2_training_run.py::test_recorded_retained_stage2_training_is_deterministic_and_keeps_held_out_closed",
        "tests/trade_alerts_contracts/test_retained_stage3_d108_evaluation.py::test_recorded_d108_evaluation_is_deterministic_and_keeps_release_closed",
        "tests/trade_alerts_contracts/test_retained_stage3_held_out_input.py::test_recorded_held_out_binding_is_deterministic_and_does_not_run_d108",
        "tests/trade_alerts_contracts/test_retained_stage3_input.py::test_recorded_retained_stage3_input_is_deterministic_and_keeps_held_out_sealed",
        "tests/trade_alerts_contracts/test_retained_stage3_pilot_disposition.py::test_recorded_pilot_disposition_is_deterministic_and_keeps_every_release_closed",
        "tests/trade_alerts_contracts/test_retained_stage3_result_shard.py::test_recorded_result_shard_is_deterministic_and_keeps_alert_and_live_closed",
        "tests/trade_alerts_contracts/test_retained_training_candidate_parts.py::test_recording_sharded_candidate_contract_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_training_candidate_record.py::test_recording_training_candidate_boundary_is_deterministic",
        "tests/trade_alerts_contracts/test_rs_trend_eligibility.py::test_measured_inputs_through_the_m42_engine_and_m51_store",
        "tests/trade_alerts_contracts/test_schwab_normalization.py::test_write_deterministic_normalization_proof",
        "tests/trade_alerts_contracts/test_session_recovery.py::test_interrupted_session_recovery_recording_end_to_end",
        "tests/trade_alerts_contracts/test_shadow_pipeline.py::test_the_same_shared_session_replays_byte_identically",
        "tests/trade_alerts_contracts/test_shadow_pipeline.py::test_the_shared_session_records_one_deterministic_pilot_proof",
        "tests/trade_alerts_contracts/test_stage1_result_package.py::test_recorded_package_proof_is_deterministic_and_reopen_equal",
        "tests/trade_alerts_contracts/test_stage1_supervised_package_run.py::test_recorded_supervised_package_is_deterministic_and_reopenable",
        "tests/trade_alerts_contracts/test_state_transitions.py::test_market_features_strategy_transition_database_recording_end_to_end",
        "tests/trade_alerts_contracts/test_strategy_interface.py::test_shared_feature_to_strategy_records_end_to_end",
        "tests/trade_alerts_contracts/test_structural_geometry.py::test_structural_geometry_recording_end_to_end",
        "tests/trade_alerts_contracts/test_structural_risk.py::test_supplied_bars_to_shared_features_risk_candidate_recording_end_to_end",
        "tests/trade_alerts_contracts/test_vwap_context_features.py::test_vwap_context_recording_end_to_end"
      ],
      "exit_codes": [
        0,
        0
      ],
      "artifacts_path": "/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-d069e1b395ec",
      "publication": "/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-d069e1b395ec/publication.json",
      "summary_sha256": "f95d1201ea9691b05f91e2ec2eb9efdf38ab954252dd0177c258090c3591be8b",
      "run_details": {
        "run-1": {
          "junit_suites": [
            {
              "tests": "33",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "217.977"
            },
            {
              "tests": "47",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "197.785"
            },
            {
              "tests": "29",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "216.597"
            }
          ],
          "pytest_lines": [
            "33 passed in 217.97s (0:03:37)",
            "47 passed in 197.78s (0:03:17)",
            "29 passed in 216.60s (0:03:36)"
          ],
          "unexpected_denials": {},
          "cleanup": {
            "db_closed": true,
            "http_closed": true,
            "config_cleared": true,
            "http_lock_cleared": true
          }
        },
        "run-2": {
          "junit_suites": [
            {
              "tests": "33",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "223.361"
            },
            {
              "tests": "47",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "201.658"
            },
            {
              "tests": "29",
              "failures": "0",
              "errors": "0",
              "skipped": "0",
              "time": "221.085"
            }
          ],
          "pytest_lines": [
            "33 passed in 223.35s (0:03:43)",
            "47 passed in 201.69s (0:03:21)",
            "29 passed in 221.08s (0:03:41)"
          ],
          "unexpected_denials": {},
          "cleanup": {
            "db_closed": true,
            "http_closed": true,
            "config_cleared": true,
            "http_lock_cleared": true
          }
        }
      }
    }
  }
}
```

The complete tested-source manifest is `/root/trade-alerts-builder/runs/20260924-080950-896105-build/verified-manifest.json`.
The original controller source hash remains `3b27b0639e86401899bac77fb47c5c6cd43fcbd6491fe66eea78340fae3132bc`,
from `/root/trade-alerts-builder/runs/20260924-080950-896105-build/controller-evidence.json`. Every non-record file in the complete
milestone delta matches that manifest's content hash. Final prose edits are
separate from tested code; their changed full-manifest identity does not replace
the original tested-source evidence. The prior records-only comparison is
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/records-only-comparison.json` and describes the earlier prose state,
not a new controller comparison of this finalization.

Both repeatability run directories and the complete per-file SHA-256 lists are
published in `/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-d069e1b395ec/publication.json`. Comparing its corresponding
`run-1` and `run-2` JSON entries finds matching hashes for the emitted JSON
records. This confirms only the records actually present. The omitted M0.2CC
record has no repeatability hash and no comparison. Its acceptance-only hash is
`48b037e63f0328a78b1285d9d39ea4d3aa5038ba5eda7537657ef16d2302a855` in
`/root/trade-alerts-builder/runs/20260924-080950-896105-build/published-artifacts-303c76c7e307/publication.json`.
All referenced published file hashes were checked against their retained bytes.
All supplied run suites report zero failures, errors and skips; their isolation
records report no unexpected denials and successful cleanup of test resources.
Those passing findings do not cure absent milestone recording evidence.

Only this document and ROADMAP changed in this finalization. The complete
milestone delta remains the controller list recorded above. Prior failures,
rejected selections, passing collected cases and attempt history remain intact.
No independent next milestone is eligible here: M0.2CD stays open but depends
on M0.2CC acceptance. An empty next-milestone field means this dependency blocks
advancement, not that the roadmap is complete. Cleanup and every live switch
remain off; no owner data was removed and no source or strategy gate changed.

## Final records-only correction — 2026-09-24 Pacific

The preceding records-only assessment is historical. The current controller
repeatability artifact is `published-artifacts-299cd5d04efc`. It ran 110 tests
twice in fresh protected processes, including
`tests/test_full_chain_storage.py::test_m02cc_cleanup_recording_is_deterministic`.
Both runs passed with zero failures, errors, and skips. Each emitted
`m02cc-cleanup-proof.json`; both files have SHA-256
`48b037e63f0328a78b1285d9d39ea4d3aa5038ba5eda7537657ef16d2302a855`.
The two-run controller wall time is 423.753 seconds.

The same controller proof has a focused phase of 7 tests and a broad acceptance
phase of 5,012 tests. The original tested-source hash is
`e30bbe5979e34c1318fbf60e076fcb86a26f5360f3ed9ba830bfd896fad6b913`.
These are record-only corrections; no code, tests, configuration, protected
inputs, cleanup settings, or live switches changed. Cleanup remains off by
default, no owner file was removed, and source, strategy, validation, and live
gates remain unchanged. M0.2CD remains the separate next assessment.
