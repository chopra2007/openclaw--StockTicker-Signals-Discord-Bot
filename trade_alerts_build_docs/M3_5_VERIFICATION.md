# M3.5 supplied-input structural geometry

Date: 2026-09-13 Pacific. Status: **protected proof complete; ready for independent review.** All switches remain off.

## Scope and result

`consensus_engine/structural_geometry.py` adds one pure calculation over caller-selected price facts and canonical bars. It records retracement, compression range ratio, drive efficiency, signed distance to a supplied level in dollars and minute-ATR units, confirmed equal-price plateau swings with two strict neighbors on each side, risk/reward and a supplied ATR buffer rule.

The calculation keeps long and short treatment mirrored. A negative retracement is recorded as zero and a retracement above one is retained. A flat drive path, zero prior range, nonpositive risk, missing input, future input, mixed identity, mixed source or price basis, uncovered swing window and no confirmed swing stay visible with separate reasons. No strategy threshold, anchor selection, target selection or live source is added.

The optional `M03B_ORB5_V1` prior-session profile and swing/AVWAP producer is not added here. That dependency applies only if that rule set is adopted. Actual profile source history remains separately blocked.

## Historical published protected proof — before recording publication repair

The following controller figures and tested-source manifest describe the prior
attempt only. The test change below invalidates affected proof for the current
delta. Preserve these reports as history; they do not prove the repaired test.

Source hash: `def8a224004be42fec4ad3a886fd83fead7909acea3af913f8ac79792f47dc21`.

Complete tested-source manifest: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/verified-manifest.json` (SHA-256 `7ae217c744745d0f44c1954f407c82a52635d95b843edd8fa513c63c4b4cd091`).

Controller evidence: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/controller-evidence.json` (SHA-256 `59a3883c24cd08c87188173563227c985a512651e40a6f34a72cbb97268a4af6`).

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.

Runs: 1. Test count: 2994. Controller wall seconds: 539.384.

Artifact directory: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/published-artifacts-e717fcb904ac`.

pytest line: `2994 passed in 535.19s (0:08:55)`. JUnit time: `535.065` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.

Runs: 1. Test count: 2994. Controller wall seconds: 530.751.

Artifact directory: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/published-artifacts-c8e599ecec2e`.

pytest line: `2994 passed in 526.65s (0:08:46)`. JUnit time: `526.524` seconds.

### repeatability

Runs: 2. Test count: 62. Controller wall seconds: 306.524. Selection reason: `recording output requires fresh-process comparison`.

Artifact directory: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/published-artifacts-c95a4b99f113`.

Selectors, in controller order:

- `tests/trade_alerts_contracts/test_alert_delivery.py::test_bars_to_candidates_to_recording_and_fake_delivery_end_to_end`
- `tests/trade_alerts_contracts/test_candidate_assembly.py::test_supplied_features_confidence_candidate_suppression_recording_end_to_end`
- `tests/trade_alerts_contracts/test_confidence.py::test_supplied_features_composition_candidate_recording_end_to_end`
- `tests/trade_alerts_contracts/test_configuration.py::test_known_default_hash_matches_canonical_record`
- `tests/trade_alerts_contracts/test_core_price_features.py::test_bar_to_coverage_to_feature_snapshot_recording_end_to_end`
- `tests/trade_alerts_contracts/test_cross_strategy_interaction.py::test_recording_is_deterministic_and_retains_every_component_candidate`
- `tests/trade_alerts_contracts/test_domain_models.py::test_deterministic_record_proof_is_written_under_tmp`
- `tests/trade_alerts_contracts/test_first_pullback_vwap.py::test_the_supplied_continuation_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_historical_bars.py::test_request_raw_mapping_coverage_and_archive_end_to_end`
- `tests/trade_alerts_contracts/test_historical_replay.py::test_chronological_same_runtime_replay_is_byte_deterministic`
- `tests/trade_alerts_contracts/test_hod_comp_rs_replay.py::test_the_same_supplied_scenario_replays_byte_identically`
- `tests/trade_alerts_contracts/test_hod_comp_rs_replay.py::test_the_five_scenarios_record_one_deterministic_proof`
- `tests/trade_alerts_contracts/test_hod_comp_rs_risk_confidence.py::test_the_composed_outcome_at_one_recorded_trigger`
- `tests/trade_alerts_contracts/test_hod_comp_rs_trigger.py::test_the_supplied_heads_up_and_trigger_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_hod_compression.py::test_hod_compression_recording_end_to_end`
- `tests/trade_alerts_contracts/test_impulse_pullback.py::test_impulse_pullback_recording_end_to_end`
- `tests/trade_alerts_contracts/test_opening_range_features.py::test_bar_coverage_opening_range_recording_end_to_end`
- `tests/trade_alerts_contracts/test_or_failure_handoff.py::test_the_supplied_handoff_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_or_failure_rev.py::test_the_supplied_reversal_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_orb5_eligibility.py::test_shared_features_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_orb5_replay.py::test_the_same_supplied_scenario_replays_byte_identically`
- `tests/trade_alerts_contracts/test_orb5_replay.py::test_the_six_scenarios_record_one_deterministic_proof`
- `tests/trade_alerts_contracts/test_orb5_risk_confidence.py::test_the_composed_outcome_at_one_recorded_trigger`
- `tests/trade_alerts_contracts/test_orb5_trigger.py::test_the_supplied_trigger_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_outcome_evaluator.py::test_compact_end_to_end_recording`
- `tests/trade_alerts_contracts/test_participation_features.py::test_bar_coverage_participation_recording_end_to_end`
- `tests/trade_alerts_contracts/test_quote_events.py::test_normalized_events_failure_reconnect_recording_end_to_end`
- `tests/trade_alerts_contracts/test_reference_inputs.py::test_supplied_reference_coverage_recording_end_to_end`
- `tests/trade_alerts_contracts/test_relative_strength_features.py::test_relative_strength_recording_end_to_end`
- `tests/trade_alerts_contracts/test_research_event_store.py::test_recording_pipeline_retains_full_facts_retry_and_reopen`
- `tests/trade_alerts_contracts/test_rs_trend_eligibility.py::test_measured_inputs_through_the_m42_engine_and_m51_store`
- `tests/trade_alerts_contracts/test_schwab_normalization.py::test_write_deterministic_normalization_proof`
- `tests/trade_alerts_contracts/test_session_recovery.py::test_interrupted_session_recovery_recording_end_to_end`
- `tests/trade_alerts_contracts/test_state_transitions.py::test_market_features_strategy_transition_database_recording_end_to_end`
- `tests/trade_alerts_contracts/test_strategy_interface.py::test_shared_feature_to_strategy_records_end_to_end`
- `tests/trade_alerts_contracts/test_structural_geometry.py::test_structural_geometry_recording_end_to_end`
- `tests/trade_alerts_contracts/test_structural_risk.py::test_supplied_bars_to_shared_features_risk_candidate_recording_end_to_end`
- `tests/trade_alerts_contracts/test_vwap_context_features.py::test_vwap_context_recording_end_to_end`

Run 1 pytest line: `62 passed in 151.01s (0:02:31)`. Run 1 JUnit time: `151.012` seconds.

Run 2 pytest line: `62 passed in 151.67s (0:02:31)`. Run 2 JUnit time: `151.674` seconds.

Every prior run has zero failures, errors and skips, no unexpected isolation denials, and all cleanup checks are true. The controller marked the repeatability stage stable. Its two fresh processes collected the same ordered tests, but neither published `m35-structural-geometry-proof.json`. Matching other recordings does not establish M3.5 repeatability. The earlier claim of matching required M3.5 recordings is withdrawn.

## Recording publication repair and final controller proof

Reported failure: neither repeatability run published
`m35-structural-geometry-proof.json`. The related test is
`tests/trade_alerts_contracts/test_structural_geometry.py::test_structural_geometry_recording_end_to_end`.
The cause was its use of pytest's nested temporary folder. Its hash comparison
also checked only bytes produced in the same process.

The test now writes `/tmp/m35-structural-geometry-proof.json`, following the
existing M3.4 recording convention. The unchanged protected launcher maps that
folder to a separate `run-1` or `run-2` output folder for each fresh process.
The redundant same-process hash assertion is removed; the local readback check
is only a write check. The long/short payload and product calculations are unchanged.

The controller completed the repaired protected stages against source hash
`7f25d2de1d3ad63cd040d93b6de9f3164f78a964297c0feba198737ef8c058b9`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-194434-371873-build/verified-manifest.json`
(SHA-256 `c74b26a70f573d09002a7d98258516dc25467ed8411d717ed8122c6d46b87a4d`).
Controller evidence is
`/root/trade-alerts-builder/runs/20260913-194434-371873-build/controller-evidence.json`
(SHA-256 `c7eb6448f1b93b7cd86d66ccb5ebc1bc1050654321c5d6c6151ffce6c89ab99a`).

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.

Runs: 1. Test count: 2994. Controller wall seconds: 540.255.

Artifact directory: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/published-artifacts-d21c500eb12d`.

pytest line: `2994 passed in 536.37s (0:08:56)`. JUnit time: `536.255` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.

Runs: 1. Test count: 2994. Controller wall seconds: 525.018.

Artifact directory: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/published-artifacts-349de70a3b3f`.

pytest line: `2994 passed in 521.23s (0:08:41)`. JUnit time: `521.112` seconds.

### repeatability

Runs: 2. Test count: 62. Controller wall seconds: 303.066. Selection reason: `recording output requires fresh-process comparison`.

Artifact directory: `/root/trade-alerts-builder/runs/20260913-194434-371873-build/published-artifacts-8ffab9841a7d`.

The selectors are the 38 ordered selectors listed in the historical repeatability
section above, including
`tests/trade_alerts_contracts/test_structural_geometry.py::test_structural_geometry_recording_end_to_end`.

Run 1 pytest line: `62 passed in 149.87s (0:02:29)`. Run 1 JUnit time: `149.874` seconds.

Run 2 pytest line: `62 passed in 149.52s (0:02:29)`. Run 2 JUnit time: `149.517` seconds.

Both fresh processes published the required recording. The SHA-256 fingerprint
for `run-1/m35-structural-geometry-proof.json` and
`run-2/m35-structural-geometry-proof.json` is
`498598c7ca58416937d5de39b093c023f5ab0683a9865e962ad382e99be0a570`.
The bytes match. All three stages have zero failures, errors and skips. Isolation
and cleanup passed, and the controller marked the repeatability stage stable.
The local launcher limitation remains recorded only as history.

## Separate required gate

- [!] **M3.5 source and historical-data completion:** actual point-in-time price, ATR, level, path and swing-bar availability, finality, corrections, session and venue coverage, compatible adjustments and any adopted profile family remain required under M0.2/M2.2/M3.1. Synthetic supplied records cannot close this gate or prove trading results.

## Entire milestone changed paths

- `consensus_engine/structural_geometry.py`
- `tests/trade_alerts_contracts/test_structural_geometry.py`
- `trade_alerts_build_docs/M3_5_LAUNCHER_LIMITATION.txt`
- `trade_alerts_build_docs/M3_5_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Next milestone

- [ ] **M0.2 — current data and shared-capacity audit:** after M3.5 review, use the owner's bounded read-only source authority to test the still-open actual data gates with zero additional spending. This is separate from M3.5 offline proof and needs its own controller assignment.
