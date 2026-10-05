# Make research checks work in clean checkouts

**Status:** OPEN
**Created:** 2026-10-04

**CURRENT STATUS (2026-10-04 Pacific):** OPEN. Master GitHub regression run 37194805878 at commit 7b949be already fails 14 research checks. They require ignored research evidence bundles or a server-only opening-auction manifest. The analyst-bias clean-copy baseline and candidate reproduce the same 12 bundle failures; two additional manifest failures appear in GitHub CI, where server data is absent. Exact current-master failure IDs are recorded in `.test-baseline`; all checks continue to run, and any new failure still blocks the gate. This limitation does not prove the research results pass.

## Work required

1. Identify the smallest reproducible inputs required by each failing check.
2. Keep proprietary market data and private research files out of the public repository. Use lawful deterministic fixtures where they prove the same behavior.
3. Keep checks of actual sealed evidence in a separately configured evidence-validation job. Report unsupported when evidence is unavailable; never fabricate a successful research result.
4. Verify clean-clone CI and the configured evidence job, then remove genuinely fixed IDs from `.test-baseline`.

## Affected checks

- `tests/research/test_momentum_saved_summary_audit.py`: six missing-summary failures.
- `tests/research/test_verify_trading_edge_e1_result.py`: five missing-evidence failures.
- `tests/research/test_verify_trading_edge_e2_result.py`: one missing sealed-result failure.
- `tests/research/test_trading_edge_full.py`: two missing server-manifest failures.

## Evidence and limits

Current-master CI log was inspected before this branch was pushed. No analyst-bias failure was added to the baseline. The baseline does not contain timeout-induced setup errors or model/API failures. TODO #115 is already DONE; its package-path repair remains preserved.
