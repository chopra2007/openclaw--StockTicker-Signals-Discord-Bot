# M0.2B offline shared-storage implementation

Current status: **protected proof complete; awaiting independent review**.

## 1. Result

M0.2B implements the off-by-default bounded compactor, complete option-chain set publication, verified reader, storage admission check and dry-run retention planner required by `M0_2A_STORAGE_CONTRACT`. The repair uses a bounded SQLite scratch merge and streamed Parquet output. It inventories retained and temporary bytes, checks disk reserve during writes, verifies current source-file identities, keeps missing open interest unpublished, and preserves invalid or conflicting work for review. No switch was enabled. No provider, broker, Discord or live path was used.

The prior passing proof remains historical because it omitted required adverse cases. The current proof covers the repaired code and expanded cases.

## 2. Complete milestone delta

- `config/full_chain_collector.yaml`
- `consensus_engine/full_chain_storage.py`
- `scripts/full_chain_collector.py`
- `tests/test_full_chain_storage.py`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/M0_2B_CONTROLLER_EVIDENCE.json`
- `trade_alerts_build_docs/M0_2B_TESTED_SOURCE_MANIFEST.json`
- `trade_alerts_build_docs/M0_2B_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## 3. Protected focused proof — 2026-09-13 Pacific

The focused phase selected `tests/test_full_chain_collector.py`, `tests/test_full_chain_storage.py` and `tests/trade_alerts_contracts` because `builder named directly affected checks`. It ran once and passed 3388 tests. Pytest reported `3388 passed in 624.27s (0:10:24)`. JUnit recorded 624.139 seconds. Controller wall time was 628.831 seconds.

Artifacts: `/root/trade-alerts-builder/runs/20260913-225525-864306-build/published-artifacts-0369165b8e86`.

The M0.2B storage proof SHA-256 was `a1c8a9e2b6824e4fabe8b5fd2ab71c5c0249ff62963846e7f6b4df379975f36b`.

## 4. Protected broad acceptance proof — 2026-09-13 Pacific

The acceptance phase selected `tests/trade_alerts_contracts`, `tests/test_full_chain_collector.py` and `tests/test_full_chain_storage.py` because `unknown dependency impact; safe broad fallback`. It ran once and passed 3388 tests. Pytest reported `3388 passed in 630.92s (0:10:30)`. JUnit recorded 630.798 seconds. Controller wall time was 635.29 seconds.

Artifacts: `/root/trade-alerts-builder/runs/20260913-225525-864306-build/published-artifacts-1ebd3d797ae3`.

The M0.2B storage proof SHA-256 was `a1c8a9e2b6824e4fabe8b5fd2ab71c5c0249ff62963846e7f6b4df379975f36b`, matching the focused phase byte for byte.

## 5. Protected repeatability proof — 2026-09-14 Pacific

The repeatability phase used the 38 selectors recorded in `M0_2B_CONTROLLER_EVIDENCE.json` because `recording output requires fresh-process comparison`. It ran twice and passed 62 tests in each fresh process. Controller wall time for the phase was 308.612 seconds.

Run 1: pytest reported `62 passed in 154.33s (0:02:34)` and JUnit recorded 154.332 seconds.

Run 2: pytest reported `62 passed in 150.35s (0:02:30)` and JUnit recorded 150.349 seconds.

Artifacts: `/root/trade-alerts-builder/runs/20260913-225525-864306-build/published-artifacts-fe50b508ea16`.

All deterministic proof artifact hashes matched between the two fresh processes.

## 6. Tested source and isolation

The controller tested source hash was `6fad85282215c27582984c1a01fea889bd81b289d3490625d580e49bc9e76777`. The complete tested-source manifest is published in `M0_2B_TESTED_SOURCE_MANIFEST.json`. The mechanical record is published in `M0_2B_CONTROLLER_EVIDENCE.json`.

All phases report zero failures, errors and skips, stable protected isolation and complete cleanup. The controller blocked outside network, credential reads, child processes, database paths and outside writes. Synthetic inputs prove only the offline contract.

## 7. Remaining gates and handoff

This proof does not establish capacity on saved owner data. It does not authorize deletion, cleanup activation, source qualification, historical completeness or live use. M0.2C remains the separate measured saved-data capacity and safe-activation assessment.

The proposed next milestone is **M3.3**, the owner-reopened relative-strength calculation repair. It must reject selected 15-minute bars whose revision is above zero and add the five named direct rejection cases. Its prior rejected proof remains historical, and its separate source and historical-data gate stays blocked. Independent review must confirm eligibility.
