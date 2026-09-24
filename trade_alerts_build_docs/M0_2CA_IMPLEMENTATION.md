# M0.2CA measured saved-data capacity repair

M0.2CA reconciles the owner-authorized measured resource profile with the
offline storage contract. The bounded compactor now reads source rows in
1,024-row batches, writes SQLite rows in batches, and keeps the scratch database
under its own configured byte bound. Admission counts that scratch bound plus
one complete chain/open-interest/proof/publication set. The 12,000,000,000-byte
or 15% reserve, 1,500,000,000-byte memory limit and 256,000,000-byte decoded
batch limit are unchanged. The owner-authorized measured wall limit is 1,800
seconds.

`M0_2C_CAPACITY_ASSESSMENT.md` and its JSON record carry the measured saved-data
result. The run covered all 390 source files and 3,721,860 option rows, preserved
the source identities, verified source-to-compact record equality and stayed
inside every preregistered resource bound. The historical blocked M0.2C result
remains recorded separately.

Direct tests cover the separate scratch admission and enforced database bound,
plus the collector's forwarding of the scratch and wall limits.

## Protected verification — 2026-09-24 Pacific

The earlier two-case proof and the stopped full-file launch are historical.
The controller then completed fresh protected proof with exit code zero, no
failures, errors, or skips, and clean isolation and cleanup. The focused phase
ran once for `builder named directly affected checks`. It used
`tests/test_full_chain_collector.py` and `tests/test_full_chain_storage.py`,
collected 396 tests, and took 136.833 controller wall seconds. Its artifact
directory is `published-artifacts-8cbb3efc5108/`.

The broad acceptance phase ran once for `unknown dependency impact; safe broad
fallback`. It used `tests/trade_alerts_contracts`,
`tests/test_full_chain_collector.py`, and `tests/test_full_chain_storage.py`,
collected 4,951 tests, and took 1224.369 controller wall seconds. Its artifact
directory is `published-artifacts-39836501d7b7/`.

The separate repeatability phase ran 2 fresh protected processes for
`recording output requires fresh-process comparison`. It used the controller's
published 109-selector list, collected 109 tests, stayed stable, and took
457.999 controller wall seconds. Its artifact directory is
`published-artifacts-cfe697f57738/`. The tested-source manifest is
`verified-manifest.json` with source hash
`6512f21632207d81cb14675dd61197dfda62027be1cfe579f7f037fddb562e70`.

Cleanup stays off. Every live switch stays off. This capacity result does not
qualify the market source, prove a trading result or open Strategies #5 through
#8. M0.2CB is limited to the separately reviewed off-by-default cleanup
decision.

## Full-file review repair resolved — 2026-09-24 Pacific

The fresh protected focused run covered both complete changed test files on the
current hashes. No code or test changed during this records-only finalization.
Independent review then passed with no issues and named M0.2CB next. M0.2CA is
accepted. Cleanup and every live switch remain off.
