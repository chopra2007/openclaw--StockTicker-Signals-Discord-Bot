# M9.1DE implementation record — 2026-09-22 Pacific

M9.1DE adds `retained_first_pullback_parent_scan.py`. It applies the frozen
`M03E_FIRST_PULLBACK_VWAP_V1` first-structure rule to one isolated training
session. The scan starts at the 06:30 Pacific bar, requires a later directional
extreme, both the 0.40 minute-ATR and 0.15 daily-ATR distance minimums, the 0.25
minute-ATR VWAP distance, and two completed confirmation bars moving back toward
VWAP. Long and short are exact mirrors. A selected parent becomes the existing
canonical `PullbackReplayStep` and M8.3 measurement record.

The scanner requires final, available, complete, unrevised minute bars and
explicit minute ATR, daily ATR and VWAP evidence. It does not fill these facts
from another field. The current retained source does not provide the needed
finality, original-availability or numeric parent evidence. Its dependent rule
therefore remains OFF and untested, with explicit unavailable reasons. The new
recording is a synthetic contract only and does not claim a retained match.

The remaining producer now calls this scanner and preserves its canonical step
or exact unavailable reasons. It still names quote-decision and confidence gaps.
No fill, return, supervised package, held-out result, stage 2, stage 3 or live
permission is produced.

Focused checks are
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py` and
`tests/trade_alerts_contracts/test_retained_remaining_producers.py`. The new
recording selector is
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`.
Python syntax checks passed. The protected launcher was tried once and stopped
before collection at line 27 with `OSError: [Errno 22] Invalid argument:
'/tmp/trade-alerts-m04-p5bq7cvb'`. It was not retried, and no application tests
ran outside protection. The controller must supply focused, broad acceptance
and two-process recording proof.

## Focused failure repair — 2026-09-22 Pacific

The controller's first focused run failed at
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_wrong_playbook_and_source_scope_are_refused`.
The original error was `consensus_engine.trade_alerts_models.RecordError:
history record source or symbol contradicts its batch`. Its published pytest
line was `1 failed, 15 passed in 3.37s`. This is failed historical proof,
not acceptance. The controller log is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/verification.log`;
it names `/tmp/trade-alerts-m04-d60doz3v` as its artifact directory.

Cause: the test mixed an AAPL bar into an NVDA history batch outside the
expected-error check. `HistoryBatch` correctly rejected it before the scan
could run. The repair checks that batch-construction rejection explicitly,
then supplies a consistent AAPL request and AAPL bars to the NVDA producer.
That second case reaches the scan's own ticker/session check without bypassing
record validation. Product code and source rules were not changed by this repair.

The repaired focused run was attempted through the protected launcher. It
stopped before collection at line 27, during the temporary-directory ownership
change, with `OSError: [Errno 22] Invalid argument:
'/tmp/trade-alerts-m04-0g570xub'`. This sandbox failure was not retried. No
application tests ran outside protection and no passing result is claimed.

Fresh controller focused, broad acceptance and two-process recording stages
must supply their published phase names, selectors, counts, timings, source
manifest, artifact hashes and comparisons. The recording selector remains
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`;
its named output is `m91de-retained-first-pullback-parent-scan-proof.json` and
must be collected and compared in both fresh repeatability runs. Prior failure
history and attempts remain intact. M9.1DF remains the proposed next step,
subject to acceptance of this scan and independent review. All missing-field
dependent retained rules remain OFF and untested.

## Historical protected proof recorded — 2026-09-22 Pacific

The earlier records-only finalization used the controller's protected proof for source
hash `0e87148d258a62dcfce2f58a767b61d3051d337c40548fbc4d56b88df3f0dd89`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/verified-manifest.json`.
Only this record and `ROADMAP.md` changed in that finalization. The later
review rejected the timing and completeness behavior despite passing collected
cases. The repair below changes code and tests; this proof is historical and
does not verify the repair.

Focused: `tests.phase=focused`, `tests.runs=1`, `tests.test_count=1`,
`tests.wall_seconds=3.467`, and
`tests.selection_reason="builder named directly affected checks"`; selector:
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_wrong_playbook_and_source_scope_are_refused`.
Pytest reported `1 passed in 1.82s`; JUnit reported `1.823` seconds.

Acceptance: `tests.phase=acceptance`, `tests.runs=1`,
`tests.test_count=3880`, `tests.wall_seconds=752.94`, and
`tests.selection_reason="unknown dependency impact; safe broad fallback"`;
selector: `tests/trade_alerts_contracts`. Pytest reported `3880 passed in
748.49s`; JUnit reported `748.268` seconds.

Repeatability: `tests.phase=repeatability`, `tests.runs=2`,
`tests.test_count=84`, `tests.wall_seconds=284.037`, and
`tests.selection_reason="recording output requires fresh-process comparison"`.
The controller's selector list includes
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`.
Pytest reported `84 passed in 138.87s` and `84 passed in 140.97s`; JUnit
reported `138.869` seconds and `140.965` seconds. The two fresh
`m91de-retained-first-pullback-parent-scan-proof.json` files had identical
SHA256 `b12385e4160e066ac1d0bac4cb02599ab8b490bc2a452b0b168b4f58ed6c2f09`.

All three protected phases exited 0 with stable output and zero failures,
errors and skips. Their isolation records show no unexpected denials and full
cleanup. The retained finality, original-availability and numeric-parent gaps
remain explicit; their dependent rule remains OFF and untested. No retained
match, fill, return, package, held-out result, stage 2, stage 3, source,
final-result or live claim follows from this proof.

## Reviewed timing and completeness repair — 2026-09-22 Pacific

Independent review found two product errors after the historical passing proof:

- The scan selected bars and numeric evidence at the latest decision, then dated
  the resulting step at the earliest decision after confirmation. Later-arriving
  facts could therefore create a step before those facts were available.
- The scan demanded a complete window through the latest decision. A missing
  interval after confirmation could erase an already confirmed parent.

This repair uses a different selection path. Decisions are evaluated in time
order. Each decision selects only numeric evidence available then and checks
bar availability at that same instant. Each possible confirmation checks only
its own prefix from the session opening bar through the second confirmation
bar. A missing required bar blocks that prefix and longer prefixes. Missing
later bars do not erase it. The first selected parent per direction is retained;
later decisions, revisions and numeric evidence cannot replace its saved step.
A later pullback gap still appears as unavailable in the canonical measurement.

Direct long and short cases now cover later-arriving confirmation bars, late
numeric evidence, late qualifying numbers after earlier failing numbers,
missing intervals inside and after confirmation, and later revisions/numeric
changes after a saved parent. Connected remaining-producer assertions verify
that the canonical steps survive that boundary. The existing deterministic
recording now includes delayed-fact decision times and incomplete-later-window
measurements for both directions; it remains synthetic evidence only.

The complete milestone delta remains:

- `consensus_engine/retained_first_pullback_parent_scan.py`
- `consensus_engine/retained_remaining_producers.py`
- `tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py`
- `tests/trade_alerts_contracts/test_retained_remaining_producers.py`
- `trade_alerts_build_docs/M9_1DE_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

The previous source-scope test failure, original launcher errors, attempts and
collected passing proof above remain historical. The original controller
mechanical evidence is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/controller-evidence.json`.
Its focused artifact directory is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/published-artifacts-b9317a2e3f06`,
acceptance directory is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/published-artifacts-b1399d4d5d9a`,
and separate repeatability directory is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/published-artifacts-757dea93cea3`.
The original tested-source manifest and source hash remain identified above;
they do not describe this repaired code and expanded tests.

Syntax parsing succeeded. The protected focused launcher was attempted with
both reviewer-required test files. It stopped before collection at line 27,
during the temporary-directory ownership change, with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-klcq1f6c'`.
It was not retried; no application test ran outside protection. No passing
result is claimed for this repair. The controller stages will supply fresh
phase names, run counts, test counts, exact selectors, selection reasons,
wall times, pytest and JUnit times, source manifests and artifact comparisons.

Required focused selectors remain
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py` and
`tests/trade_alerts_contracts/test_retained_remaining_producers.py`.
After focused success, the controller runs its required broad acceptance.
Fresh repeatability must collect
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`
in both processes and compare the expanded
`m91de-retained-first-pullback-parent-scan-proof.json` files. Historical matching
recordings cannot stand in for those expanded files.

M9.1DE awaits protected verification and independent review. M9.1DF stays open
as the proposed next step after scan acceptance. Missing retained finality,
original availability and numeric parent facts keep dependent rules OFF and
untested. No source, execution, held-out, profit or live gate is closed.

## Historical timing-repair protected proof — 2026-09-22 Pacific

This records-only finalization uses the controller proof for source hash
`815f1cc1c89037ac93ff02cb54c6bc6338f60cc4826c09187bfcf5674f395b40` and
the complete tested-source manifest at
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/verified-manifest.json`.
Only this record and `ROADMAP.md` changed after that tested source.

Focused: `tests.phase=focused`, `tests.runs=1`, `tests.test_count=30`,
`tests.wall_seconds=5.757`, and
`tests.selection_reason="builder named directly affected checks"`; selectors:
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py`,
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`,
and `tests/trade_alerts_contracts/test_retained_remaining_producers.py`.

Acceptance: `tests.phase=acceptance`, `tests.runs=1`,
`tests.test_count=3894`, `tests.wall_seconds=737.008`, and
`tests.selection_reason="unknown dependency impact; safe broad fallback"`;
selector: `tests/trade_alerts_contracts`.

Repeatability: `tests.phase=repeatability`, `tests.runs=2`,
`tests.test_count=84`, `tests.wall_seconds=283.282`, and
`tests.selection_reason="recording output requires fresh-process comparison"`.
The published selector list includes
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`.
The two fresh `m91de-retained-first-pullback-parent-scan-proof.json` files
match SHA256 `116d4df270b29a4d2d41e327535d03a4051c75ace8dcce813afa41f870ce6a73`.

All three protected phases exited 0 with stable output. The retained finality,
original-availability and numeric-parent gaps remain explicit; their dependent
rule remains OFF and untested. No retained match, fill, return, package,
held-out result, stage 2, stage 3, source, final-result or live claim follows
from this proof.


## Exact unavailable-reason repair — 2026-09-22 Pacific

Current status: implementation ready for fresh protected verification and
independent review. The timing-repair proof above is preserved historical
collected-case evidence, not acceptance of this changed code and recording.

The review found that `build_retained_remaining_request` unconditionally added
`FIRST_PULLBACK_MISSING_INPUTS` whenever the scan selected no parent. That list
claimed `ATR_1M_UNAVAILABLE`, `IMPULSE_WINDOW_UNAVAILABLE` and
`IMPULSE_DIRECTION_UNAVAILABLE` even when valid numeric evidence was supplied
and the scan reported the exact `CONFIRMED_IMPULSE_UNAVAILABLE` or
`IMPULSE_WINDOW_MISSING` reason. The prior tests checked selected parents and
missing evidence, but did not check this supplied-evidence caller outcome.

The different approach makes the scan the sole source of parent-related
unavailable reasons. The caller appends only its still-missing quote-decision
and confidence inputs. The obsolete generic first-pullback list is removed;
the OR-failure path is unchanged. Direct long/short checks cover supplied valid
evidence that fails the distance gate and supplied evidence with an incomplete
bar window. Existing provisional, revised and conflicting-window cases now
also check the connected caller's exact reasons. Missing-numeric-evidence
checks retain the scan's minute ATR, daily ATR and VWAP gaps without inventing
window or direction gaps. The synthetic recording includes both no-parent
outcomes and exact caller reasons in both directions.

The complete milestone delta is still the six paths listed in the timing and
completeness repair section above. No prior failure, attempt or published proof
was removed. In particular, the prior timing-repair source hash
`815f1cc1c89037ac93ff02cb54c6bc6338f60cc4826c09187bfcf5674f395b40`
and tested-source manifest reference above describe historical tested source.
Its focused, acceptance and separate repeatability artifacts remain at:

- `/root/trade-alerts-builder/runs/20260922-051900-023131-build/published-artifacts-9a82fdb4b94c`
- `/root/trade-alerts-builder/runs/20260922-051900-023131-build/published-artifacts-dac68a515ef4`
- `/root/trade-alerts-builder/runs/20260922-051900-023131-build/published-artifacts-fbaef1d36b5c`

Syntax parsing passed. The protected focused launcher was attempted with both
reviewer-required files. It stopped before collection at line 27 during the
temporary-directory ownership change:
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-9y9_jfnb'`.
It was not retried, and no application test ran outside protection. The
controller stages will supply fresh phase names, runs, counts, selectors,
selection reasons, wall times, pytest and JUnit times, tested-source manifest,
artifact hashes and comparisons. No current protected pass is claimed.

Required focused selectors:

- `tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py`
- `tests/trade_alerts_contracts/test_retained_remaining_producers.py`

After focused success, the controller supplies its required broad acceptance
selection. Both fresh repeatability processes must collect
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`
and
`tests/trade_alerts_contracts/test_retained_remaining_producers.py::test_recorded_remaining_producer_proof_is_deterministic`.
They must compare the expanded
`m91de-retained-first-pullback-parent-scan-proof.json` and changed
`m91dc-retained-remaining-producers-proof.json` outputs. Historical matching
outputs do not establish these repaired recordings.

M9.1DF remains open after independent acceptance of the parent scans. Retained
finality, original availability and numeric parent gaps remain unresolved;
their dependent rules stay OFF and untested. Synthetic examples establish only
the offline contract. No retained match, fill, return, supervised package,
held-out result, source qualification, stage 2, stage 3, final-result, profit
or live permission is claimed.

## Exact unavailable-reason repair protected proof — 2026-09-22 Pacific

This records-only finalization uses the controller's protected proof for source
hash `112baa1f7c0db6a8b67cb5df34c2f168dec146e1800379cfee31d4043b367d14`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260922-051900-023131-build/verified-manifest.json`.
The complete milestone delta is the six paths listed above. Only this record and
`ROADMAP.md` changed after the tested source.

Focused: `tests.phase=focused`, `tests.runs=1`, `tests.test_count=36`,
`tests.wall_seconds=6.156`, and
`tests.selection_reason="builder named directly affected checks"`; selectors:
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py`,
`tests/trade_alerts_contracts/test_retained_first_pullback_parent_scan.py::test_recorded_impulse_parent_scan_is_deterministic`,
`tests/trade_alerts_contracts/test_retained_remaining_producers.py`, and
`tests/trade_alerts_contracts/test_retained_remaining_producers.py::test_recorded_remaining_producer_proof_is_deterministic`.
The pytest JUnit time was `4.315` seconds.

Acceptance: `tests.phase=acceptance`, `tests.runs=1`,
`tests.test_count=3900`, `tests.wall_seconds=718.391`, and
`tests.selection_reason="unknown dependency impact; safe broad fallback"`;
selector: `tests/trade_alerts_contracts`. The pytest JUnit time was `714.053`
seconds.

Repeatability: `tests.phase=repeatability`, `tests.runs=2`,
`tests.test_count=84`, `tests.wall_seconds=268.747`, and
`tests.selection_reason="recording output requires fresh-process comparison"`.
Its published selector list includes both M9.1DE recording selectors above.
The two process JUnit times were `131.311` and `133.429` seconds. The fresh
`m91de-retained-first-pullback-parent-scan-proof.json` files match SHA256
`5adf36336cb085f6272f00db4485593158ea5511637972de58df92704cc00a02`; the
fresh `m91dc-retained-remaining-producers-proof.json` files match SHA256
`18a051f4b09000ba1627c0fb97549c28456d5696aa7ec5b8b4e25f1c262acb09`.

All three protected phases exited 0 with stable output and zero failures,
errors and skips. This is an offline synthetic-record contract only. Retained
finality, original availability and numeric-parent gaps keep dependent rules
OFF and untested. No retained match, fill, return, package, held-out result,
stage 2, stage 3, source, final-result or live claim follows.
