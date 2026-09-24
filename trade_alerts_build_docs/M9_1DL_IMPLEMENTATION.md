# M9.1DL retained BBO-1m session-date repair — 2026-09-22 Pacific

The retained reader now keeps the provider trading date for BBO-1m
initialization rows that have no last-trade time. These rows can end just before
midnight on the prior Pacific calendar date. Their UTC interval date matches
the verified retained condition list and is now stored as the session. The
quote time remains the exact interval end; no event time is invented.

Direct offline cases cover the real boundary shape and the harder case where
both the prior and current dates have condition entries. The row uses the
current provider date and cannot borrow the prior date's condition. The
deterministic reader recording also contains this boundary.

The protected launcher was tried once for
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py` and the
direct caller in
`tests/trade_alerts_contracts/test_retained_candidate_events.py`. It stopped
before collection at its unchanged temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-vcjrc_c4'
```

It was not retried. No application test ran outside protection, and the whole
contracts family was not self-run. The controller must publish fresh focused,
broad acceptance and repeatability proof. Its two fresh recording runs must collect
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas`
and compare `m91cz-retained-quote-trade-reader-proof.json`.

After fresh protected acceptance and independent review, M9.1DM must restart
the same manifest-verified 47-session D-116 sample. Only a clean sample may
release the three D-114 shards. The eight held-out names remain sealed. No
fills, returns or supervised package are calculated. Original availability,
corrections, finality and point-in-time membership remain recorded gaps; their
dependent rules stay OFF and untested.

Complete M9.1DL delta:

- `consensus_engine/retained_quote_trade_reader.py`
- `tests/trade_alerts_contracts/test_retained_quote_trade_reader.py`
- `trade_alerts_build_docs/M9_1DL_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`
