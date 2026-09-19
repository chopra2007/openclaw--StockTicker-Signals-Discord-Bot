# M3.4 supplied-input VWAP context — protected proof complete

Date: 2026-09-13 Pacific. Status: **offline implementation and protected proof complete**. All switches remain off.

## Scope and result

`consensus_engine/vwap_context_features.py` adds one offline calculation over caller-supplied records. It uses accepted canonical one-minute bars, M3.1 core price snapshots and one supplied current-price observation. It does not use the unaccepted M3.3 relative-strength engine.

The immutable output records the exact three-minute session-VWAP slope in minute-ATR units, signed price distance from VWAP in dollars and minute-ATR units, strict completed-close cross count, signed side, and separate strict above/below facts. Equal closes and certified no-trade minutes break cross adjacency. Missing or incompatible supplied facts remain unavailable with a named reason. The function performs no fetch, storage, clock read, alert, order or live activation.

`tests/trade_alerts_contracts/test_vwap_context_features.py` covers long, short and neutral arithmetic, the exact three-minute lookup, strict crossing, missingness, finality, identity, source basis, freshness, serialization, immutability and compact recording. The recording is synthetic software proof only and does not prove trading results.

## Published protected proof

Original tested source hash: `59921ba78493425f87e219e98efa3d9567965f8b9af68c2d12c407aa0937ea99`.
Complete tested-source manifest: `/root/trade-alerts-builder/runs/20260913-185914-681831-build/verified-manifest.json`.
Mechanical controller record: `/root/trade-alerts-builder/runs/20260913-185914-681831-build/controller-evidence.json`.

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`. Runs: 1. Test count: 2970. Controller wall seconds: 558.322. Artifact directory: `/root/trade-alerts-builder/runs/20260913-185914-681831-build/published-artifacts-99d1b88567f1`. Publication SHA-256: `eee5eadcc6b8050bddc1aca09dc4862771ac5497115442ddb620ee2fecbe6c63`. pytest line: `2970 passed in 553.94s (0:09:13)`. JUnit time: `553.825` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`. Runs: 1. Test count: 2970. Controller wall seconds: 536.647. Artifact directory: `/root/trade-alerts-builder/runs/20260913-185914-681831-build/published-artifacts-f250ffe2ae76`. Publication SHA-256: `706962cd477a5916ba6a1664b4e532dbfdb92e53383bc3d9852d867c53934e28`. pytest line: `2970 passed in 532.56s (0:08:52)`. JUnit time: `532.415` seconds.

### repeatability

Selection reason: `recording output requires fresh-process comparison`. Runs: 2. Test count: 61. Controller wall seconds: 305.237. Artifact directory: `/root/trade-alerts-builder/runs/20260913-185914-681831-build/published-artifacts-dcc0850578fd`. Publication SHA-256: `4a63b9beca95715635ab01d585453d19cddb96010a2cca6acf112f7dfa99d2f4`.

Run 1 pytest line: `61 passed in 150.29s (0:02:30)`. Run 1 JUnit time: `150.290` seconds. Run 2 pytest line: `61 passed in 151.08s (0:02:31)`. Run 2 JUnit time: `151.083` seconds.

Exact selectors in controller order:

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
- `tests/trade_alerts_contracts/test_structural_risk.py::test_supplied_bars_to_shared_features_risk_candidate_recording_end_to_end`
- `tests/trade_alerts_contracts/test_vwap_context_features.py::test_vwap_context_recording_end_to_end`

Every published run has zero failures, errors and skips. Every isolation record has no unexpected denial and all cleanup checks are true. Repeatability test IDs match in order. `m34-vwap-context-proof.json` matches byte for byte between the focused run, acceptance run and both repeatability runs. Each copy is 3749 bytes with SHA-256 `d9660abc714e7cf4faf38369793afd20d5022f62e47599eaf61c4ec4ded15c2e`.

The earlier launcher failure in `M3_4_LAUNCHER_LIMITATION.txt` is historical. The controller completed the required protected runs in its proper environment. This records-only finalization changed no code, tests, configuration, dependency or protected input, so the original tested source hash and manifest remain the proof for the implementation.

## Separate required gate

- [!] **M3.4 source and historical-data completion:** actual point-in-time one-minute bars, each interval's same-mode VWAP, current price, original availability, finality, correction history, session identity, eligible venue coverage and compatible adjustment proof remain required under M0.2/M2.2/M3.1. Synthetic supplied records cannot close this gate or prove trading results.

## Entire milestone changed paths

- `consensus_engine/vwap_context_features.py`
- `tests/trade_alerts_contracts/test_vwap_context_features.py`
- `trade_alerts_build_docs/M3_4_LAUNCHER_LIMITATION.txt`
- `trade_alerts_build_docs/M3_4_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Proposed next milestone

- [ ] **M3.5 — Structural geometry:** proposed after M3.4 independent review. It remains a separate implementation step and does not close M3.3 or either milestone's source gate.

## Current blocked independent review — 2026-09-13 Pacific

The independent review at `/root/trade-alerts-builder/runs/20260913-193537-463283-review/review-result.json` found the supplied-input calculations
and protected proof sound, but returned blocked, not acceptance, because
actual source and historical-data availability/finality/correction/session/venue/
adjustment evidence remains unresolved. Existing collected proof is retained;
no code or tests change in this records-only blocked assessment. M3.5 structural
geometry was explicitly confirmed as independent next work. No source, trading-
result or live-use gate is closed.
