# M9.1DK real D-116 sample stop — 2026-09-22 Pacific

M9.1DK restarted the same manifest-verified offline 47-session D-116 sample
after the M9.1DJ reader repair passed protected review. The sample again used
all nine training names, five normal sessions, one degraded session and one
half-day session. The eight held-out names stayed sealed.

The repaired reader passed the earlier null-event-time row. It then stopped on
the first retained BBO-1m initialization rows for the next trading date:

```text
consensus_engine.trade_alerts_models.RecordError: row 23753 session 2025-10-05 is not in the retained condition list
```

Bounded inspection found that row 23753 is an empty BBO-1m initialization row.
Its interval end is `2025-10-06T05:57:00+00:00`, its `ts_event` is the same
unsigned null sentinel accepted by M9.1DJ, and the verified retained condition
list names the trading date `2025-10-06` as available. The reader currently
turns the interval end into a Pacific calendar date, which makes this early
pre-open record appear on the prior calendar day. This is a retained-session
date mapping bug. It is not evidence that the retained file or its condition
list failed verification.

The run stopped before candidate evaluation and before the D-116 count and
field inspection. No retry, row skip, made-up time, full D-114 shard, fill,
return, supervised package, held-out read, provider call or spend occurred.
Every D-104 gap-dependent rule remains OFF and untested.

M9.1DL must repair the retained BBO-1m session-date boundary with direct cases
for these early initialization rows, obtain fresh protected proof, and restart
the same 47-session sample. Only a clean D-116 sample may release the three
D-114 shards.
