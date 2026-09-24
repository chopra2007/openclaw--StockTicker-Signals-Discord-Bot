# M9.1DD repair — 2026-09-22 Pacific

Historical pre-proof status: implementation was ready for protected verification;
no repair pass was claimed at that time. The later controller proof is recorded
below.
The controller's current milestone remains M9.1DD. M9.1DE is the existing next
parent-scan step, subject to independent review. All switches stay off.

## Cause and changed approach

The prior scan used the provisional-admitting research opening-range adapter,
read bars without checking finality or continuous coverage, and constructed
`MinuteClose(..., True, True)` even when the source bar was not final. Its
trade list admitted unknown-quality records and checked availability only at
the last decision of the session. It searched the entire deadline for an
extreme, including observations after the first reacceptance. It consumed a
crossing only after a successful handoff, so a later crossing could restart an
unsuccessful structure's timer. Its recording used synthetic data but the
ROADMAP called it a real retained match.

The repair uses the strict `HistoryBatch.coverage_at` and
`build_opening_range_snapshot` paths. It checks opening bars at the crossing,
requires continuous final available bars for ATR and reacceptance, rejects
unknown conventions, conflicting intervals and selected revisions, and retains
the actual close availability. It freezes each direction's first crossing
before looking for a successful reacceptance. Only eligible trades available
through that reacceptance can establish its excursion. The original deadline
includes equality; the setup-window end is exclusive.

Trade observations require valid source quality and status, a known non-delayed
flag, matching event time, and freshness within the frozen three-second limit.
Covered observations and the crossing-to-close interval also require explicit
`TradeCoverage` evidence, including source identities, availability, complete
coverage and known non-halted status. Neither trade presence nor bar coverage
creates tape coverage. This supplied evidence defaults to absent. The retained
reader does not supply it; synthetic tests label their supplied evidence as
`SYNTHETIC_TEST_ONLY`. No retained field is upgraded or invented.

The remaining-producer connection now carries the scan's specific unavailable
reason. The retained source still lacks finality/original-availability and
correction proof, trade interval coverage, halt status and delayed-status proof.
The dependent M0.3D arm stays **OFF and untested on retained data**. Point-in-time
membership and the other existing source/final/live gates stay unchanged.
A synthetic successful handoff proves only the supplied-record contract.

## Required checks and recording

Focused selectors:

- `tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py`
- `tests/trade_alerts_contracts/test_retained_remaining_producers.py`

The first file covers mirrored synthetic handoffs; provisional, unknown,
missing, conflicting, revised and late bars; missing ATR intervals; trade
quality/status/delay/freshness/identity failures; absent, partial, late or
mismatched tape evidence; unknown halt status; unsuccessful and expired first
crossings; the original deadline; the exclusive setup end; and observations
that are unavailable at an earlier decision. The connection tests require
specific unavailable reasons to survive into the producer decision.

`tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py::test_recorded_parent_scan_is_deterministic`
emits `m91dd-retained-or-failure-parent-scan-proof.json`. It sends explicitly
synthetic rows through the actual Databento minute converter, preserves its
unknown fields and records the unavailable outcome. It states that no real
retained session was matched and no retained file was opened. The source gap
assessment names the actual bar and trade adapter paths. This is not retained
market validation. The unchanged controller discovery predicate recognizes this
recording test. Collection, emission and hash comparison in both fresh
repeatability runs still need controller proof.

The protected launcher stopped before collection:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-_zx4fa9p'
```

This came from `os.chown` at line 27 of
`scripts/testing/run_trade_alerts_contracts.py`. The reproduced sandbox failure
was not retried or bypassed. No application tests ran outside protection.
Static syntax checks passed. The controller stages will supply fresh phase,
runs, selectors, selection reason, collected counts, wall time, pytest time,
JUnit time, source manifest and recording comparisons. None is claimed here.
The required broad selection remains controller-owned.

## Prior rejected evidence retained

The review reported behavior/proof failures, not a failing pytest assertion.
The prior success test was named
`tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py::test_selects_real_ended_orb_parent_and_builds_canonical_reversal_step`;
it has been renamed to identify its synthetic evidence. The original review
specifically found nonfinal bars converted into final closes, invalid or
uncovered trades admitted, restarted crossing deadlines and a synthetic-only
recording presented as retained proof. Those findings are not erased by the
previous passing aggregate.

Original controller run root:
`/root/trade-alerts-builder/runs/20260922-041209-116801-build`.
The original source hash is
`8cf8606fedf1dde6bd4f1cc31fd8e604f9ce9dc2b8f46637cd1da23bf1a3e61f`.
Its unchanged `controller-evidence.json`, `changes.diff`, `start-manifest.json`,
`protected-start.json` and `attempt-history/` retain the original evidence and
attempt history. The original published directories remain:

- Focused: `published-artifacts-8e28f0ec91c7` under that root.
- Acceptance: `published-artifacts-0623330f05b1` under that root.
- Repeatability: `published-artifacts-1f5b90a1be24` under that root, including
  both `run-1` and `run-2` and their publication hash inventory.

Those artifacts apply only to the rejected pre-repair source. The code and test
changes invalidate their use as current acceptance. They remain historical;
this is not a records-only proof reuse or an attempt-counter reset.

Complete milestone delta, including the earlier implementation:

- `consensus_engine/retained_or_failure_parent_scan.py`
- `consensus_engine/retained_remaining_producers.py`
- `tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py`
- `tests/trade_alerts_contracts/test_retained_remaining_producers.py`
- `trade_alerts_build_docs/ROADMAP.md`
- `trade_alerts_build_docs/M9_1DD_REPAIR.md`

The M0.3E impulse parent selection remains M9.1DE work. This repair does not
calculate fills, returns, confidence or supervised packages, open held-out
names, qualify a source, or release stage 2, stage 3, final or live gates.

## Protected proof recorded

This records-only finalization uses the controller's protected proof for source
hash `009eb4e5762522a3034941d426d51613515a37fc562149517f607afa627d08f7`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260922-041209-116801-build/verified-manifest.json`.
This finalization changes only this record and `ROADMAP.md`; the tested Python
and test paths keep the identities in that manifest.

The focused phase had `tests.phase=focused`, `tests.runs=1`,
`tests.test_count=88`, `tests.wall_seconds=7.195`, and
`tests.selection_reason="builder named directly affected checks"`. Its exact
selectors were
`tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py`,
`tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py::test_recorded_parent_scan_is_deterministic`,
and `tests/trade_alerts_contracts/test_retained_remaining_producers.py`.
The controller recorded protected isolation, exit code 0, stable output, and
zero failures, errors and skips. Pytest reported 88 passed in 5.34 seconds;
JUnit reported 5.341 seconds.

The acceptance phase had `tests.phase=acceptance`, `tests.runs=1`,
`tests.test_count=3871`, `tests.wall_seconds=758.898`, and
`tests.selection_reason="unknown dependency impact; safe broad fallback"`.
Its selector was `tests/trade_alerts_contracts`. The controller recorded
protected isolation, exit code 0, stable output, and zero failures, errors and
skips. Pytest reported 3871 passed in 754.35 seconds; JUnit reported 754.166
seconds.

The repeatability phase had `tests.phase=repeatability`, `tests.runs=2`,
`tests.test_count=83`, `tests.wall_seconds=279.956`, and
`tests.selection_reason="recording output requires fresh-process comparison"`.
The controller's exact selector list is recorded in
`published-artifacts-f76e91f6971a/summary.json` under the run root above; it
includes `tests/trade_alerts_contracts/test_retained_or_failure_parent_scan.py::test_recorded_parent_scan_is_deterministic`.
Both fresh processes exited 0 with stable output, zero failures, errors and
skips, and identical `m91dd-retained-or-failure-parent-scan-proof.json` SHA256
`1bf1691064737603240aa44483c166cc9240351460b55f5ba9482bac5748c94f`.
Pytest reported 83 passed in 137.42 seconds and 83 passed in 138.11 seconds;
JUnit reported 137.415 seconds and 138.112 seconds.

The proof records only the synthetic contract and retained-field gap assessment:
no retained file was opened, no real retained session matched, and no handoff,
reversal, fill, return or package was made. Finality, original availability,
correction state, halt status, delayed status and trade-interval coverage remain
unavailable. The dependent M0.3D rule remains OFF and untested on retained
data. M9.1DE remains the open next parent-scan step.
