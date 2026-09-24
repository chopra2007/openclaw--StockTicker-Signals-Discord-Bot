# M9.1DI real retained candidate-job stop — 2026-09-22 Pacific

M9.1DI began the required offline D-116 sample against the manifest-verified
retained OHLCV-1m, BBO-1m and trades folders. The frozen full plan contains
2,349 training ticker-sessions, so the rounded-up 2% sample contains 47. The
sample was spread across all nine training names and included normal, half-day
and degraded sessions. The eight held-out names stayed sealed.

The run stopped while decoding the first selected BBO-1m file, before any
candidate decision or full-run release. The retained reader raised:

```text
consensus_engine.trade_alerts_models.RecordError: row 2 receipt precedes its event time
```

Direct bounded inspection of the first three decoded rows found the concrete
cause: these empty BBO-1m rows carry the unsigned null sentinel in `ts_event`,
while `ts_recv` carries the real minute timestamp. The current reader treats
that sentinel as a real future instant and then rejects the row because receipt
appears earlier. Nineteen of the first twenty rows had this same null event-time
shape. This is a retained-reader compatibility issue, not proof that the file
failed its manifest hash or that the market data is usable.

No retry, substitute timestamp, skipped row, full shard, fill, return,
supervised package, held-out read, provider call or spend occurred. Every D-104
dependent rule remains OFF and untested. M9.1DJ must establish the official
BBO-1m null-row meaning, repair the reader without inventing an event time, add
direct cases, and then restart the exact D-116 sample. Only a clean sample may
release the three D-114 shards.

