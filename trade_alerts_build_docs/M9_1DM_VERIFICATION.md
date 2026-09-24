# M9.1DM verification stop and evidence repair — 2026-09-22 Pacific

Status: **blocked**. The M9.1DL reader change is preserved. Fresh protected
acceptance and independent review are still required before restarting the
exact manifest-verified 47-session D-116 sample. The sample has not restarted
in M9.1DM, and no full D-114 shard is released.

## Escalated diagnosis

The first M9.1DM attempt returned no changed paths and no evidence record.
The controller rejected that handoff with:

```text
Builder evidence is incomplete. changed_files must list the complete milestone delta, including earlier repair edits: []. evidence_files must name new or changed evidence records in that delta.
```

This was a missing evidence-record failure, not a collected application-test
failure. The separate execution barrier occurred in the protected launcher's
temporary-folder ownership step, before test collection:

```text
  File "/home/openclaw/.openclaw/workspace/scripts/testing/run_trade_alerts_contracts.py", line 27, in main
    os.chown(artifact_root, account.pw_uid, account.pw_gid)
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-gzxr028z'
```

The preserved original result and literal failure are in:

- `/root/trade-alerts-builder/runs/20260922-173724-120787-build/attempt-history/build-1-build-result.json`
- `/root/trade-alerts-builder/runs/20260922-173724-120787-build/attempt-history/build-1-build.log`
- `/root/trade-alerts-builder/runs/20260922-173724-120787-build/controller-normalized-build.json`

The different approach in this repair is to publish this evidence record and
correct the roadmap handoff. The reproduced sandbox failure was not retried;
the launcher, code, tests, configuration and protected inputs were not changed.
No application tests ran outside protection. Prior attempts remain intact.

## Pending protected proof

The original focused request named exactly:

- `tests/trade_alerts_contracts/test_retained_quote_trade_reader.py`
- `tests/trade_alerts_contracts/test_retained_candidate_events.py`

The controller must publish the focused result first, then its required broader
selection after a focused pass. Repeatability must also collect
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas`
in both fresh recording runs and compare
`m91cz-retained-quote-trade-reader-proof.json`.

No current controller proof or verification handoff was supplied. Phase names,
run counts, collected test counts, wall times, selection reasons, exact final
selections, focused results, tested-source manifest, artifact hashes and
comparisons remain pending; the controller stage will supply them. No pass,
test failure ID, cleanup result or repeatability result is inferred from a
launcher failure before collection. Earlier milestone proof is not M9.1DM proof.

## Remaining execution and boundary

Proposed continuation **M9.1DN** carries the unfinished real sample execution;
it is not an independent way around the verification barrier. The reviewer must
confirm the handoff and fresh reader acceptance before the supervisor restarts
the same manifest-verified 47 training ticker-sessions. Only a clean D-116
sample may release the three D-114 shards. The prior real-data failure and
reader repair remain in [M9_1DK_EXECUTION.md](M9_1DK_EXECUTION.md) and
[M9_1DL_IMPLEMENTATION.md](M9_1DL_IMPLEMENTATION.md).

Held-out names stay sealed. No fills, returns, supervised packages, provider
calls, spending or live activation occurred. Original availability, corrections,
finality and point-in-time membership remain recorded gaps, with their dependent
rules OFF and untested. All switches remain off.

The complete M9.1DM delta is this record and `trade_alerts_build_docs/ROADMAP.md`.
The earlier M9.1DL source and test changes are preserved prerequisite work,
not new M9.1DM edits. Documentation checks cover referenced paths, the final
roadmap rows and this complete delta; they do not establish product acceptance.
