# M9.1DR bounded implementation record

## Result

This session completed the first coherent M9.1DR part. Each frozen producer
moment now selects the latest separately retained BBO and trade that were
available by that moment. The pair preserves both original record IDs and the
full trade record. It is never merged into a made-up market record.

The pair fails closed. Missing quote or trade records stay named gaps. Unknown
source quality, unknown delay, missing quote policy and unproved continuity all
keep the pair unusable. Quote and trade scope must match the retained bar
source, ticker, instrument type and session. A later trade cannot appear in an
earlier decision.

The request records for all four playbooks receive this typed pair through the
existing offline-input record. The actual strategy evaluators, complete
canonical confidence inputs and complete parent evidence are not connected in
this bounded part. Those obligations move to M9.1DS. No candidate, fill,
return, supervised package, held-out result, outside call or live action was
opened.

## Changed paths

- `consensus_engine/retained_offline_producer_inputs.py`
- `tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py`
- `trade_alerts_build_docs/M9_1DR_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Checks

The changed Python files compile. The focused protected selector is
`tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py`.
Its protected launch stopped before collection at the known sandbox ownership
step with `OSError: [Errno 22] Invalid argument` for
`/tmp/trade-alerts-m04-0jmv8fph`. It was not retried and no test was run outside
the protected launcher. The controller must publish fresh focused and required
broader proof for this changed source and test.

## Safety boundary

Original availability, corrections, finality and point-in-time membership
remain gaps. Every dependent rule stays OFF and untested. Halt, macro,
catalyst, daily ATR, quote policy, continuity, confidence and required parent
evidence remain unknown where the retained records do not prove them. All live
switches stay off.

## Attempt 2: focused failure diagnosis and repair

The controller's prior focused run is preserved at
`/root/trade-alerts-builder/runs/20260923-032225-759647-build/verification.log`.
Its exact pytest line is `2 failed, 19 passed in 4.85s`. The failing selectors were:

- `tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_reused_measurement_never_hides_changed_history_or_time[source]`
- `tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_reused_measurement_never_hides_changed_history_or_time[ticker]`

Both stopped with `consensus_engine.trade_alerts_models.RecordError: retained
trades must share the candidate history scope`. The saved-measurement test
fixture removed quotes but still included the original trade. Changing the bar
source or ticker therefore created mismatched inputs. The new trade-scope check
correctly rejected those inputs before the measurement assertions could run.

The repair makes that fixture explicitly bar-only, with matching bar source IDs.
It preserves all direct-versus-reused measurement comparisons and adds source
mismatch to the separate trade-scope rejection check alongside ticker mismatch.
The production scope check is unchanged. This separates the two obligations
instead of weakening the rejection or expecting a mismatched input to succeed.

The controller's supplied prior test summary records `runs: 1`,
`test_count: null`, `selection_reason: builder named directly affected checks`,
and `selectors: [tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py]`.
No acceptance or repeatability result for the repair is available yet. The
controller stages must supply their own counts, timings, tested-source manifest
and recording comparisons; earlier proof cannot verify this changed test file.
The existing recording selector remains
`tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_recorded_offline_input_proof_is_deterministic`.

The repaired file's protected focused launch stopped before collection at
`scripts/testing/run_trade_alerts_contracts.py:27`, in `os.chown`, with
`OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-vfy3_7q4'`.
It was not retried. No application tests ran outside protection, and no broader
stage ran. No passing result is claimed.

M9.1DR remains a blocked parent handoff: the bounded pair connection is built,
but actual first-four evaluation, complete canonical confidence inputs and
complete parent evidence remain M9.1DS work, subject to fresh proof and review.
The complete milestone delta is still the four paths above; this repair changes
only the test fixture, its rejection coverage and these progress records.

## Attempt 3: controller publication failure — 2026-09-23 Pacific

The current failure is `verification error: artifact publication is too large`.
It supersedes the earlier sandbox launch failure as the current verification
blocker; neither earlier failure nor its repair is removed.

Read-only diagnosis found that `/root/trade-alerts-builder/controller.py`, in
`publish_artifacts`, raises this exact error when the combined bytes selected
for publication exceed `MAX_PUBLISHED_ARTIFACT_BYTES`. This is the controller's
aggregate publication limit, not a reported failing application test. The
current controller log is
`/root/trade-alerts-builder/runs/20260923-032225-759647-build/verification.log`;
it names `/tmp/trade-alerts-m04-1zhvf867` as its artifact root. The exception
occurs before `verify` returns its complete phase summary. No valid verification
handoff was supplied, so this record does not claim acceptance, full proof
publication or verified recording comparisons.

Earlier controller publications remain preserved at
`/root/trade-alerts-builder/runs/20260923-032225-759647-build/published-artifacts-5072de842331/publication.json`
and
`/root/trade-alerts-builder/runs/20260923-032225-759647-build/published-artifacts-d70e00bb7140/publication.json`.
The latter lists the retained-input recording. Its presence does not prove the
unpublished fresh-run comparison. Attempt logs and saved build results remain
under the same build directory's `attempt-history/`.

The different approach in this attempt is to diagnose the publication boundary
and record the external blocker without repeating the failed command or changing
product code, tests, recordings, protection limits or controller files. A
separately authorized controller repair is required. The controller must supply
the missing complete phase records, counts, timings, selectors, tested-source
manifest and comparisons. No new product test run was made in this attempt.

M9.1DR remains blocked. M9.1DS remains the proposed next implementation slice,
subject to independent review of its dependency and this publication blocker;
it is not a workaround for missing proof. Actual first-four evaluation, complete
canonical confidence inputs and complete parent evidence remain unfinished.
All unknown-input dependent rules remain OFF and untested.

## Attempt 4: protected proof and independent review — 2026-09-23 Pacific

The separately authorized controller publication repair raised only the
combined publication allowance while preserving the per-file limit and all
protected execution rules. Fresh controller proof then passed 22 focused
checks, 4,004 broader checks and two independent 88-check recording runs with
matching artifacts and clean isolation. The earlier publication-size failure
is superseded.

The independent review found the bounded retained BBO/trade connection sound
and named M9.1DS as the last open eligible roadmap row. M9.1DR remains blocked
as a parent only because actual first-four strategy evaluation, complete
canonical confidence inputs and complete parent evidence are unfinished.
Those are the stated M9.1DS obligations, not a reason to prevent M9.1DS from
starting. Unknown-input dependent rules remain OFF and untested.
