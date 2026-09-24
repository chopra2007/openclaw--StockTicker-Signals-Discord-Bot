# M9.1DQ offline producer-input connection — 2026-09-22 Pacific

Status: **first bounded connection built; the parent milestone remains open**.

This step connects the retained minute bars and BBO-1m rows to one typed,
point-in-time input record for every frozen producer decision moment. It uses
the existing core-price builder for minute ATR and session VWAP. It also uses
the existing quote-event checker for each retained BBO snapshot. The first-two
and remaining-two producer request records now retain these exact inputs.

The connection does not fill facts the retained files cannot prove. Halt status
and macro blackout stay null. Catalyst coverage stays `UNKNOWN`. Daily ATR stays
unavailable because no qualifying daily history is supplied. The BBO decision
stays unusable while its policy, source quality, delayed state, trade price and
continuity are unproved. Confidence stays unavailable. Original availability,
corrections, finality and point-in-time membership dependents remain OFF and
untested under D-104.

Direct cases cover the exact unknown status facts, missing quotes, a valid
20-ended-bar minute ATR and VWAP calculation, quote-scope rejection and a
deterministic recording. Existing first-two and remaining-two recording cases
now include the connected input records.

The protected launcher was tried once with
`tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py`. It
stopped before collection at the known temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-wbzjw4zr'
```

It was not retried. No application test ran outside protection. A read-only
syntax check passed for the three changed source files and three changed test
files, but that is not protected acceptance.

## Focused failure and repair

The controller subsequently ran the directly affected selection. Its preserved
log is `/root/trade-alerts-builder/runs/20260922-181802-352435-build/attempt-history/focused-1-verification.log`;
that log names `/tmp/trade-alerts-m04-m2di3uwt` as its artifact directory.
The published pytest line is `1 failed, 22 passed in 39.96s`.
This is failed historical proof, not acceptance. The supplied controller summary
records `tests.runs: 1`, `tests.test_count: null`, and
`tests.selection_reason: "builder named directly affected checks"`.
Its focused `tests.selectors`, in published order, are:

- `tests/trade_alerts_contracts/test_retained_first_two_producers.py`
- `tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py`
- `tests/trade_alerts_contracts/test_retained_remaining_producers.py`

The failed case is
`tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_computes_point_in_time_minute_atr_and_vwap_from_twenty_ended_bars`.
It raised `TypeError: replace() should be called on dataclass instances` while
constructing the test history, before calling the input builder. The imported
`_retained` helper creates `SimpleNamespace` history wrappers; `dataclasses.replace`
cannot copy that type. The repair constructs the canonical `SessionHistory`
record directly, with the same synthetic bars and no prior daily history.
It leaves the shared helper and production calculations unchanged. The earlier
failure and attempts remain preserved.

After this repair, the protected launcher was attempted for that exact failed
selector. It stopped before collection at its ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-26h93prc'
```

That sandbox failure was not retried. No application tests ran outside the
protected launcher. The controller must supply fresh focused, broad acceptance
and recording-comparison proof, including their counts, hashes, JUnit time and
`tests.wall_seconds`; none is claimed here. The deterministic recordings in all
three directly affected test files still require comparison in both fresh
repeatability runs. The code repair alone does not establish a passing test.

## Escalated diagnosis of the ATR assertion

The next controller focused run reached the same case and reported
`Obtained: None` and `Expected: 2.0 ± 2.0e-06`. Its log is
`/root/trade-alerts-builder/runs/20260922-181802-352435-build/attempt-history/focused-2-verification.log`,
with artifacts at `/tmp/trade-alerts-m04-yot5qj21` and published pytest line
`1 failed in 2.15s`. The supplied summary records `tests.runs: 1`,
`tests.test_count: null`, and
`tests.selection_reason: "builder named directly affected checks"`.
Its only `tests.selectors` entry is
`tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_computes_point_in_time_minute_atr_and_vwap_from_twenty_ended_bars`.
No JUnit time or controller wall time was supplied for this failure.

The earlier history-wrapper correction exposed a second test setup defect:
the shared bar template defaults to `quality="UNKNOWN"`. Setting finality and
synthetic mode alone does not make it valid. `HistoryBatch.coverage_at` returns
`QUALITY_UNKNOWN`, so the core-price builder correctly withholds both features.
The supplied milestone diff lacked an explicit quality value; the current test
already contained `quality="VALID"` when this repair session began. That local
correction was preserved, together with the canonical `SessionHistory` repair.

The different approach traces the full coverage gate before the calculation.
The test now asserts that every required interval is `FINAL`, checks the exact
synthetic VWAP as well as ATR, then changes the last bar back to unknown quality
and requires both features and their missing-input flags to remain unavailable.
Production calculations, retained source facts and the shared helper were not
changed by this repair. These assertions describe synthetic contract coverage;
they do not qualify real source data or establish a passing result.

The protected launcher was tried for that exact failing selector after the
repair and stopped before collection:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-ug02mk7d'
```

This sandbox failure was not retried. No application tests ran outside
protection. The controller stage must supply fresh focused and broad proof,
including phase, runs, test count, wall seconds, selection reason, selectors,
focused details, JUnit time and tested-source hashes. Both fresh recording runs
must collect and compare the recordings from these exact selectors:

- `tests/trade_alerts_contracts/test_retained_first_two_producers.py::test_recorded_first_two_request_proof_is_deterministic`
- `tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_recorded_offline_input_proof_is_deterministic`
- `tests/trade_alerts_contracts/test_retained_remaining_producers.py::test_recorded_remaining_producer_proof_is_deterministic`

No current acceptance or recording comparison is claimed. Prior failures and
attempts remain historical evidence, with no counter reset.

M9.1DR is the next bounded step, subject to independent review. It must use these connected records in the
actual producer evaluations, combine quote and trade facts only through an
explicit source-identity contract, preserve every remaining unknown, and add
the required confidence and parent-evidence paths before the exact D-116 sample
can run again. No full D-114 shard, held-out name, fill, return, supervised
package, provider call, spending or live action was opened.

## Historical first timeout diagnosis and blocked handoff

The latest reported failure is `verification error: protected verification timed out`.
This attempt used a different approach: inspect the controller's published
single-case result and stage sequence before considering another test repair.
No code, test, configuration, protected input or launcher was changed in this
attempt, and no failing command was rerun.

The corrected ATR/VWAP case subsequently passed in the controller publication:
`/root/trade-alerts-builder/runs/20260922-181802-352435-build/published-artifacts-55173ab7bdb2/`.
Its `summary.json` records `runs: 1`, `exit_codes: [0]`, and this exact selector:

- `tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_computes_point_in_time_minute_atr_and_vwap_from_twenty_ended_bars`

The published pytest line is `1 passed in 2.10s`. The JUnit suite separately
records `tests="1"`, `errors="0"`, `failures="0"`, `skipped="0"`, and
`time="2.105"`. Its isolation record has no unexpected denials and all cleanup
checks are true. `publication.json` retains the original artifact inventory and
SHA256 values, including `results.xml`:
`d18d0339fa009adab94b7808a8ce7c53f2d2005ad211570a58efbcf721590382`.
This is focused case evidence only. The log is archived as
`attempt-history/acceptance-1-verification.log` because the controller archives
the preceding log using the incoming phase name; that filename does not turn
the focused result into broad acceptance.

The packet's `tests.runs: 1`, `tests.test_count: null`, and
`tests.selection_reason: "builder named directly affected checks"` describe
its supplied failure summary. Its selector is the same exact case above.
The saved state still describes the earlier failed focused stage; it does not
provide the successful stage's controller wall time or a completed broad-stage
result. The controller must publish current `tests.phase`, `tests.runs`,
`tests.test_count`, `tests.wall_seconds`, `tests.selection_reason`,
`tests.selectors`, and `tests.focused`, plus the complete tested-source manifest.
No missing timing or phase result is inferred from the pytest or JUnit figures.

The current `verification.log` contains only
`Artifacts: /tmp/trade-alerts-m04-aczpvk38`. The controller's coverage mapping
does not cover these changed source/test paths, so its required next selection
is the broad fallback `tests/trade_alerts_contracts`. Its stage sequence and
archived focused pass place the timeout in that later acceptance stage.
The failed stage has no published completion summary. Reading its child output
failed literally with:

```text
tail: cannot open '/tmp/trade-alerts-m04-aczpvk38/run-1/output.txt' for reading: Permission denied
```

The known stopping mechanism is the controller's verification timeout. The
underlying cause of the long run, last running case, and any child failure
remain unknown. The inaccessible evidence prevents assigning this timeout to a
milestone-code defect or to a harmless slow run. A supervisor must publish the
existing child output and stage details for diagnosis before a justified repair
or rerun. This session did not change permissions, bypass protection, adjust
timeouts, reduce coverage, reset attempts, or self-run the broad family.

Status remains **blocked**, with the bounded input connection preserved but no
broad acceptance or fresh-process recording comparison claimed. The three
recording selectors above still need both fresh runs, emitted artifacts and
hash comparisons. All prior failures remain recorded. M9.1DR remains the open
proposed continuation, not an independently accepted bypass of this proof gate;
the reviewer must confirm its dependency readiness before advancement.

## Attempt 5: focused pass and launcher timeout

The current failure is in broad acceptance, after the affected selection passed.
The different diagnostic approach reads the latest launcher traceback, its
subprocess deadline and the published focused artifacts together. The immediate
cause is the launcher's `subprocess.TimeoutExpired`, not another reported ATR
assertion failure. The traceback in
`/root/trade-alerts-builder/runs/20260922-181802-352435-build/verification.log`
ends with `timed out after 1199.9999513289658 seconds` for the protected child
running `tests/trade_alerts_contracts`. This is the exception's timeout value,
not a completed controller wall time or a pytest duration.

The current read-only launcher inspection shows `timeout=1800`, whereas that
failed invocation reports the earlier deadline above. This session did not
change the launcher and cannot infer that the current limit resolves the cause.
No timeout adjustment, permission change, coverage reduction or rerun was made.
The last running case and reason for the long run remain unknown because reading
the latest child output returned exactly:

```text
tail: cannot open '/tmp/trade-alerts-m04-fsj1lswo/run-1/output.txt' for reading: Permission denied
```

The supervisor must make that existing child output readable and identify the
slow or failing case before assigning a code repair or justified rerun. This is
an evidence-access gate outside the assigned product changes. The earlier
`aczpvk38` timeout and both test-setup failures above remain historical evidence.

The latest focused publication is
`/root/trade-alerts-builder/runs/20260922-181802-352435-build/published-artifacts-df2d4f7d873c`.
Its `summary.json`, `publication.json`, `run-1/output.txt`, `run-1/results.xml`
and `run-1/isolation.json` were read; the published artifact hashes match.
The pytest line is `23 passed in 39.35s`. Separately, JUnit records
`tests="23"`, `errors="0"`, `failures="0"`, `skipped="0"`, `time="39.352"`.
Isolation has no unexpected denials and all cleanup checks are true.
The controller packet supplies the following phase figures, copied without
substituting pytest or JUnit time for controller wall time:

```json
{
  "tests": {
    "runs": 1,
    "test_count": null,
    "selection_reason": "unknown dependency impact; safe broad fallback",
    "selectors": ["tests/trade_alerts_contracts"],
    "focused": {
      "artifacts": true,
      "artifacts_path": "/root/trade-alerts-builder/runs/20260922-181802-352435-build/published-artifacts-df2d4f7d873c",
      "at": "2026-09-22T19:02:47-07:00",
      "exit_code": 0,
      "phase": "focused",
      "protected": true,
      "run": "/root/trade-alerts-builder/runs/20260922-181802-352435-build",
      "runs": 1,
      "selection_reason": "builder named directly affected checks",
      "selectors": [
        "tests/trade_alerts_contracts/test_retained_first_two_producers.py",
        "tests/trade_alerts_contracts/test_retained_first_two_producers.py::test_recorded_first_two_request_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py",
        "tests/trade_alerts_contracts/test_retained_offline_producer_inputs.py::test_recorded_offline_input_proof_is_deterministic",
        "tests/trade_alerts_contracts/test_retained_remaining_producers.py",
        "tests/trade_alerts_contracts/test_retained_remaining_producers.py::test_recorded_remaining_producer_proof_is_deterministic"
      ],
      "stable": true,
      "test_count": 23,
      "wall_seconds": 41.207
    }
  }
}
```

The outer failure summary has `exit_code: 1` and an empty `artifacts_path`.
Its phase field and wall time were not supplied; broad acceptance is identified
from the actual child command and stage failure, not a fabricated summary field.
The controller stage must supply its missing completion figures and complete
tested-source manifest. The starting manifest is not a tested-source manifest.
No verification handoff was supplied.

The publication contains the first-two, remaining-two and offline-input proof
files named in its hash inventory. They belong to the single focused run;
no fresh-process repeatability comparison was supplied or is claimed. Both
required fresh runs and their recording comparisons remain outstanding.

Only this evidence record and ROADMAP changed in attempt 5. The full milestone
delta remains the three producer source files, their three test files, this
record and ROADMAP listed in the work packet. All previous failures, attempts,
unknown inputs and OFF switches are preserved. M9.1DQ remains **blocked**;
actual evaluation, combined quote/trade, confidence and complete parent evidence
also remain unfinished. M9.1DR stays open as the proposed bounded continuation,
subject to the reviewer confirming dependency readiness; it is not permission
to bypass this unresolved evidence gate or restart the exact sample.

## Safe pause after repeatability failure — 2026-09-22 20:06 Pacific

The corrected broad run completed successfully. Its published pytest line is
`3987 passed in 1350.59s (0:22:30)`; JUnit separately records
`tests="3987"` and `time="1350.424"`. The earlier pause note incorrectly
said 3,982; this corrects that transcription from the published result.
The supplied controller summary does not include its wall time.
The published result is
`/root/trade-alerts-builder/runs/20260922-181802-352435-build/published-artifacts-92f0b6c3d5be`,
and Databento credit used was zero. The next required two-process recording
check failed twice in the same test. Their published pytest lines are
`1 failed, 87 passed in 387.81s (0:06:27)` and
`1 failed, 87 passed in 387.93s (0:06:27)`. The failure was the test's own 120-second limit while
`build_retained_offline_producer_inputs` was rebuilding core price coverage.

The supervisor tested one narrow hypothesis: remove only the second identical
inspection inside the proof test because the outer runner already performs two
fresh processes. The single-test retry still timed out during the first
inspection after 121.60 seconds, so that edit was not a valid fix and was
reverted. Preserved retry evidence is under
`/root/trade-alerts-builder/supervisor-evidence/m91dq-pause-20260922-2006/`.
No product source was changed by that attempt. No new controller run, exact
sample, full-count job, paid call, held-out work, or live action was started.


## Attempt 6: exact-history reuse repair — 2026-09-23 Pacific

The failed case remains
`tests/trade_alerts_contracts/test_retained_training_candidate_parts.py::test_recording_sharded_candidate_contract_is_deterministic`.
The current controller traceback and the supervisor's preserved single-case
retry were read before editing or launching tests. Both point through the new
M9.1DQ input connection into the core-price builder. The cold recording builds
each ticker's part and then the full sample fixture. Each invokes all four
playbooks on the same history and decision grid. The new connection rebuilt the
same complete bar coverage and price features for each playbook. In the broad
run, earlier cases had already populated the test's `_sample_fixture` cache;
the fresh recording selection instead pays that fixture's full cost inside the
failed case. Passing broad tests therefore did not establish fresh-run timing.

The different approach fixes this repetition in the milestone's own input
module. `_measurement` uses a bounded cache keyed by the complete immutable
`HistoryBatch` and exact evaluation instant. It calls the unchanged canonical
core-price builder, then the caller restores the original playbook/session/index
record ID. The key includes the request, conventions, source, every bar identity,
value, quality, finality, revision and availability field. It does not use only a
ticker, session, record ID or rounded time. The cache holds at most 512 snapshots;
eviction changes only whether work is repeated. Quote streams remain fresh per
request. No calculation, missing-input rule or unknown source fact was changed.

New checks compare serialized measurements with direct canonical calculations,
prove reuse across all four playbooks with distinct output identities, and
cover changes to price, record identity, revision, availability, quality,
finality, conventions, request window, source, ticker and exact moment. A later
provisional revision leaves the earlier instant unchanged and blocks VWAP once
available. Cold/warm outputs and quote-state separation are also checked.
These are added checks awaiting execution, not claimed passes. The original
sharded recording test, including its second inspection, remains unchanged.
The launcher and timeout settings were not edited in this repair.

The protected launcher was attempted with the failed recording selector first,
then the three affected producer test files. It stopped before collection:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-frae3kr6'
```

That reproduced sandbox failure was not retried. No application tests ran
outside protection and no broad family was self-run. Read-only syntax parsing
and the scoped whitespace check passed; neither establishes protected behavior
or a speed improvement. The controller must execute the failed case and the
added/directly affected cases first, stop on a focused failure, then supply its
required broader selection and both fresh recording runs with file comparisons.
Changed product code and tests invalidate affected prior proof; the historical
pause instruction to reuse prior passing proof cannot establish this repair.

[M9_1DQ_REPAIR6_EVIDENCE.json](M9_1DQ_REPAIR6_EVIDENCE.json) copies the supplied
controller phase records, exact selectors and their original order, including
`tests.focused` and the separate failed `tests.repeatability`. It preserves both
published output inventories and their original hashes. The repeatability
summary's `stable: true` does not mean recordings passed: `exit_code: 1`,
`artifacts: false` and both timeout failures remain explicit. Its controller wall
time is `779.576`, distinct from the two pytest durations; no JUnit duration or
successful comparison was supplied for those failed runs. No complete tested
source manifest was supplied; the controller must publish it with fresh proof.
The starting manifest is not relabelled as tested evidence. Missing usage and
missing acceptance wall time remain unknown.

Only the offline-input source, its test file and milestone records changed in
this repair. The complete inherited milestone delta also includes the first-two
and remaining-two producer source/tests and the protected launcher; the latter
is a pre-existing supervisor change and was preserved without editing. All
prior failures and attempt history remain intact.

The bounded repair is ready for protected verification, with no acceptance or
runtime improvement claimed yet. M9.1DQ's last progress row remains `[!]` for
its unfinished parent scope. M9.1DR remains the proposed open continuation,
subject to independent review after this proof gate. It must complete actual
producer evaluation, exact quote/trade combination, confidence and parent
wiring. No exact D-116 sample, D-114 shard, held-out work, provider request,
spending or live switch was opened. All D-104 gap dependents remain OFF and
untested; halt/macro/catalyst/daily-history/confidence gaps remain explicit.
