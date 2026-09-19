# M0.2D offline shared request queue

Date: 2026-09-14 Pacific. Status: **PROTECTED VERIFICATION COMPLETE; INDEPENDENT ACCEPTANCE PENDING.** All
switches remain off.

## Result

`consensus_engine/request_queue.py` adds the disabled-by-default
`M02D_REQUEST_QUEUE_V1` offline queue. Processes that open the same SQLite file
share admission, priority, expiry and rolling account-ceiling records. Dispatch
accepts only replies supplied in a `RecordedProvider`; it has no provider client,
credential access or runtime registration.

The fixed limits are 110 dispatches per rolling 60 seconds and 256 pending
requests. Interactive, actionable, background and research requests have
priority 0/1/2/3, expiry of 5/10/60/300 seconds and timeout of 2/5/15/15 seconds.
At capacity, higher-priority work displaces the newest lowest-priority work;
otherwise the new request is rejected. Expired requests are marked before
selection and never make a recorded call. Recorded timeouts, throttling,
authentication failures and other provider failures remain visible.

## Complete milestone delta

- `consensus_engine/request_queue.py`
- `tests/trade_alerts_contracts/test_request_queue.py`
- `trade_alerts_build_docs/CODING_STANDARDS.md`
- `trade_alerts_build_docs/DATA_REQUIREMENTS.md`
- `trade_alerts_build_docs/M0_2D_VERIFICATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Published protected proof

Source hash: `1ba81359f46dcc9b5c38f54ed4bae6b29dc2c2625080be8aee7582c850a7b4b8`.
Complete tested-source manifest:
`/root/trade-alerts-builder/runs/20260914-020948-570101-build/verified-manifest.json`
(SHA-256 `ea2974f3753ec2709334830e109027ab6c2d2687db4bbf58e43517332b7e3e47`).
Controller evidence:
`/root/trade-alerts-builder/runs/20260914-020948-570101-build/controller-evidence.json`
(SHA-256 `deff1cca5cf0386d965084386c4ba80386ee52708c9f69d083963034a8a594f0`).

### focused

Selector: `tests/trade_alerts_contracts`. Selection reason: `builder named directly affected checks`.

Runs: 1. Test count: 3037. Controller wall seconds: 553.453.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-020948-570101-build/published-artifacts-9dfa4f2dfe09`.

pytest line: `3037 passed in 549.27s (0:09:09)`. JUnit time: `549.119` seconds.

### acceptance

Selector: `tests/trade_alerts_contracts`. Selection reason: `unknown dependency impact; safe broad fallback`.

Runs: 1. Test count: 3037. Controller wall seconds: 542.547.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-020948-570101-build/published-artifacts-84fc8b0b968c`.

pytest line: `3037 passed in 538.65s (0:08:58)`. JUnit time: `538.539` seconds.

### repeatability

The controller used the 39 exact selectors in its repeatability publication
because `recording output requires fresh-process comparison`. Runs: 2. Test
count: 63. Controller wall seconds: 310.963.

Artifact directory: `/root/trade-alerts-builder/runs/20260914-020948-570101-build/published-artifacts-d1fcf026e267`.

Run 1 pytest line: `63 passed in 151.46s (0:02:31)`. Run 1 JUnit time: `151.462` seconds.

Run 2 pytest line: `63 passed in 155.68s (0:02:35)`. Run 2 JUnit time: `155.680` seconds.

Both fresh processes and the focused and acceptance runs published
`m02d-request-queue-proof.json` with SHA-256
`7b6e50e91d0d50d7033e375bb78f18a43e3681b881b141588b169f6d98b2a71e`.
The bytes match. All three phases have zero failures, errors and skips. There
were no unexpected isolation denials, all cleanup checks are true, and the
controller marked repeatability stable.

## Limits and next milestone

Synthetic recorded replies prove only the offline queue contract. Existing
consumers are not wired to it. The current provider ceiling, subscription rules,
field units, combined load and source continuity remain unverified. M0.2C also
remains blocked by its separate local-capacity admission rule. No source,
historical, early-validation or live gate closes here.

The proposed next milestone is **M0.2E — current provider-limit and source-contract
reconciliation**. It should use existing dated evidence and official sources,
without another provider request or new spending. Independent review must first
confirm dependency order.
