# M9.1DN protected-acceptance stop — 2026-09-22 Pacific

Status: **blocked**. M9.1DN could not restart the exact manifest-verified
47-session D-116 sample because the required fresh protected acceptance of the
M9.1DL reader repair is still unavailable.

The focused protected run was tried once with the two direct reader selectors.
It stopped before test collection at the launcher's unchanged temporary-folder
ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-xv4pejf3'
```

The reproduced sandbox failure was not retried. No application tests ran
outside protection. Code, tests, configuration, dependencies and protected
inputs were not changed.

The D-116 sample was not restarted because the current roadmap explicitly
requires fresh protected acceptance and independent review first. No candidate
result or full D-114 shard was released. The eight held-out names remain
sealed. No fills, returns, supervised packages, provider calls, spending or
live activation occurred. Original availability, corrections, finality and
point-in-time membership remain recorded gaps; their dependent rules stay OFF
and untested. All switches remain off.

M9.1DO carries the same execution boundary. The controller must first publish
fresh focused, broad acceptance and two-process reader recording proof, followed
by independent acceptance. Only then may the supervisor restart the same
manifest-verified 47 training ticker-sessions. Only a clean D-116 sample may
release the three D-114 shards.

The complete M9.1DN delta is this record and `trade_alerts_build_docs/ROADMAP.md`.
Earlier M9.1DL source and test changes remain preserved prerequisite work, not
new M9.1DN edits.
