# M9.1DO reader-proof reconciliation — 2026-09-22 Pacific

Status: **blocked: the exact 47-session D-116 sample has not restarted**.
Protected reader proof is available and reusable. Broad acceptance and the two
fresh recording runs passed under M9.1DL; the current M9.1DO focused run emits
the same reader-proof bytes. Independent review decides this corrected handoff
and the M9.1DP continuation. No sample result or full D-114 shard is claimed.

## Cause and different approach

The earlier records confused a local launcher failure with missing controller
proof. They considered only the current focused summary and omitted the earlier
published broad and repeatability artifacts. This repair reconciles those
artifacts, their file fingerprints and the complete source manifests. It changes
records only and runs no application tests or sample job. The prior launcher
failures and rejected handoffs remain historical evidence.

## Historical local stop and handoff

The following local failure remains true; its missing-proof conclusion is
superseded by the published evidence below.

The focused protected run was tried once with the two direct reader selectors:

- `tests/trade_alerts_contracts/test_retained_quote_trade_reader.py`
- `tests/trade_alerts_contracts/test_retained_candidate_events.py`

It stopped before test collection at the launcher's temporary-folder ownership
step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-vqlv63bd'
```

The reproduced sandbox failure was not retried. No application tests ran
outside protection. Code, tests, configuration, dependencies and protected
inputs were not changed. The original handoff incorrectly said the controller
must publish fresh focused,
broad acceptance and two-process reader recording proof. The reconciliation
below supersedes that missing-proof claim. The repeatability requirement was to collect
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas`
in both fresh runs and compare `m91cz-retained-quote-trade-reader-proof.json`.

The D-116 sample was not restarted. The original handoff treated protected
acceptance as unavailable; the published proof below corrects that premise.
No candidate result or full D-114 shard was released. The eight held-out names remain sealed. No fills, returns,
supervised packages, provider calls, spending or live activation occurred.
Original availability, corrections, finality and point-in-time membership
remain recorded gaps; their dependent rules stay OFF and untested. All switches
remain off.

After independent review of this corrected handoff, M9.1DP may restart
the same manifest-verified 47 training ticker-sessions.
Only a clean D-116 sample may release the three D-114 shards.

The complete M9.1DO delta is this record and
`trade_alerts_build_docs/ROADMAP.md`. Earlier M9.1DL source and test changes
remain preserved prerequisite work, not new M9.1DO edits.

## Reused controller proof

The original M9.1DL tested-source hash is
`7a352a33e9abbbbf135897c4c690e8ab25cd317c83082051688d07b582dca250`, recorded in
`/root/trade-alerts-builder/runs/20260922-170955-875873-build/controller-evidence.json`.
Its complete post-test source manifest is preserved at
`/root/trade-alerts-builder/runs/20260922-173436-241483-review/start-manifest.json`.
The independent review at
`/root/trade-alerts-builder/runs/20260922-173436-241483-review/review-result.json`
found the reader repair sound and named the unfinished sample restart as the
remaining blocker. That blocked verdict did not claim sample acceptance.

The current M9.1DO tested-source hash remains
`8ec5d5e4b6054dcf1357b7a73e400adc377cda0f73e87e3907068a46d7312454`; its complete
manifest is
`/root/trade-alerts-builder/runs/20260922-174640-607738-build/verified-manifest.json`.
Comparison with the earlier post-test manifest changes only these records:
`trade_alerts_build_docs/M9_1DM_VERIFICATION.md`,
`trade_alerts_build_docs/M9_1DN_EXECUTION.md`,
`trade_alerts_build_docs/M9_1DO_EXECUTION.md`, and
`trade_alerts_build_docs/ROADMAP.md`. Product code, tests, configuration,
dependencies and protected inputs match. The two build runs' `protected-start.json`
files also match. The current `records-only-comparison.json` confirms only the
M9.1DO record and ROADMAP changed after current focused proof, with
`records_only=true`, `protected_unchanged=true`, and original/final protected hash
`0d0bfd3ef94602739b9e52291eefd65747b5123c5be94a3e3ef9064bd265b709`.
This correction adds only final prose changes to those same two records; a
changed full-manifest hash for records does not invalidate tested code.

The following fields copy the controller evidence, supplied focused packet and
published repeatability summary. The broad acceptance is the earlier M9.1DL run;
`tests.focused` is the current M9.1DO run, not a new broad acceptance.

```json
{
  "tests": {
    "phase": "acceptance",
    "runs": 1,
    "test_count": 3982,
    "wall_seconds": 800.913,
    "selection_reason": "unknown dependency impact; safe broad fallback",
    "selectors": [
      "tests/trade_alerts_contracts"
    ],
    "artifacts_path": "/root/trade-alerts-builder/runs/20260922-170955-875873-build/published-artifacts-ddc3d4ac486a",
    "exit_code": 0,
    "focused": {
      "phase": "focused",
      "runs": 1,
      "test_count": 53,
      "wall_seconds": 7.538,
      "selection_reason": "builder named directly affected checks",
      "selectors": [
        "tests/trade_alerts_contracts/test_retained_candidate_events.py",
        "tests/trade_alerts_contracts/test_retained_quote_trade_reader.py"
      ],
      "artifacts_path": "/root/trade-alerts-builder/runs/20260922-174640-607738-build/published-artifacts-34ce24e2bcdb",
      "protected": true,
      "stable": true,
      "exit_code": 0
    },
    "repeatability": {
      "runs": 2,
      "test_count": 87,
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
        "tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_first_two_producers.py::test_recorded_first_two_request_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py::test_recorded_parent_scan_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas",
        "tests/trade_alerts_contracts/test_retained_remaining_producers.py::test_recorded_remaining_producer_proof_is_deterministic",
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
      "artifacts_path": "/root/trade-alerts-builder/runs/20260922-170955-875873-build/published-artifacts-28f56891de4f",
      "exit_codes": [
        0,
        0
      ]
    }
  }
}
```

The current top-level controller summary separately gives
`selection_reason="records-only change reuses focused proof"`; that reuse reason
does not replace the focused phase's original selection reason above.
Repeatability controller wall time and selection reason were not supplied in
the inspected published summary; they remain unknown, not inferred from pytest
or JUnit times. Any additional controller stage will supply its own figures.

The earlier M9.1DL focused run is also preserved at
`/root/trade-alerts-builder/runs/20260922-170955-875873-build/published-artifacts-f3086cac0e88`.
Its exact selectors are in that directory's `summary.json`: the two current
focused files, followed by the explicit reader recording selector below. Its
pytest line is `53 passed in 5.52s`; its JUnit time is `5.523`.

Published timing measures are separate:

- M9.1DL broad acceptance: pytest line `3982 passed in 796.55s (0:13:16)`;
  JUnit time `796.382`; controller wall time `800.913`.
- M9.1DL repeatability `run-1`: pytest line `87 passed in 171.07s (0:02:51)`;
  JUnit time `171.070`.
- M9.1DL repeatability `run-2`: pytest line `87 passed in 171.69s (0:02:51)`;
  JUnit time `171.690`.
- M9.1DO focused: pytest line `53 passed in 5.84s`; JUnit time `5.847`;
  controller wall time `7.538`.

Every listed run has zero failures, errors and skips in `results.xml`, exit zero,
no unexpected isolation denials and all cleanup checks true in `isolation.json`.
The published files match their `publication.json` SHA256 fingerprints.

Both repeatability runs collect
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas`.
Both emit `m91cz-retained-quote-trade-reader-proof.json` with SHA256
`8b569ff6eb6121dcae9b7ddd03405e49ae0a4e3f9edc24e076ca6259977a9088`.
The earlier focused and broad artifacts and current focused artifact have that
same reader-proof hash. The two fresh recording runs are separate proof from
the one-run broad acceptance. These synthetic checks prove the offline reader
contract only; they do not establish a successful real D-116 sample.

## Remaining work

M9.1DO remains blocked because the exact manifest-verified 47 training
ticker-sessions have not restarted. M9.1DP is open for that execution after
independent review of this handoff; another broad/repeatability run is not a
missing prerequisite for unchanged code. Only a clean D-116 sample may release
the three D-114 shards. No full shard was released here. Held-out names stay
sealed. No fills, returns, supervised packages, provider calls, spending or live
activation occurred. Original availability, corrections, finality and
point-in-time membership remain gaps; dependent rules stay OFF and untested.
All switches remain off.
