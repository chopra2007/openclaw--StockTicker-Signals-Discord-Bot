# M9.1DJ retained BBO-1m null-time repair — 2026-09-22 Pacific

The retained reader now follows Databento's published BBO interval contract.
For `bbo-1m`, `ts_recv` is the minute interval end and is the quote time.
`ts_event` is the time of the last trade, not the quote time. Databento says it
is `UNDEF_TIMESTAMP` (`UINT64_MAX`, `18446744073709551615`) when no trade has
occurred in the session. The reader now converts that sentinel to an explicit
missing value. It does not invent a trade event time from `ts_recv`.

Official references checked for this repair:

- <https://databento.com/docs/schemas-and-data-formats/bbo>
- <https://databento.com/docs/standards-and-conventions/common-fields-enums-types>

The canonical quote keeps the real BBO interval end in `quote_time` and source
metadata. A real last-trade time, when present, stays separately in
`trade_time`. The retained record keeps the exact unsigned sentinel in
`raw_ts_event_ns` while canonical `trade_time` stays null. Empty bid and ask values remain missing with
status `MISSING`; zero sizes remain zero. A trade row may not use the undefined
event-time sentinel. A non-null event time after the interval end is still
rejected.

Direct cases cover a valid quote with no session trade, a completely empty
quote row, session selection from the BBO interval end, exact null
serialization, rejection of a null trade event time, and the existing future
event-time rejection. These are synthetic offline contracts only. They do not
qualify NBBO coverage, original availability, corrections, finality, point-in-
time membership, fills, returns or profit. Their dependent rules remain OFF
and untested.

The protected launcher was tried once for
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py`. It stopped
before collection at its unchanged temporary-folder ownership step:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-f7n0gb6s'
```

It was not retried. No application test ran outside protection, and the whole
contracts family was not self-run. The controller must provide fresh focused,
broad acceptance and repeatability proof. Current test counts, timings, tested
hashes and comparisons are not yet published.

The actual 47-session D-116 sample was not restarted in this implementation
session. M9.1DK must first receive fresh protected acceptance and independent
review of this reader repair, then restart the exact manifest-verified sample.
Only a clean sample may release the three D-114 shards. The eight held-out names
stay sealed, and no fill, return or supervised package may be calculated.

Complete M9.1DJ delta:

- `consensus_engine/retained_quote_trade_reader.py`
- `tests/trade_alerts_contracts/test_retained_quote_trade_reader.py`
- `trade_alerts_build_docs/M9_1DJ_IMPLEMENTATION.md`
- `trade_alerts_build_docs/ROADMAP.md`

## Historical escalated attempt diagnosis — 2026-09-22 Pacific

The controller reported `builder process failed`. The preserved first-attempt
log identifies the actual process failure after the repair and records were
written:

```text
Selected model is at capacity. Please try a different model.
```

The log is retained at
`/root/trade-alerts-builder/runs/20260922-162603-923149-build/attempt-history/build-1-build.log`.
This is outside the milestone code. It is separate from the protected launcher's
previously recorded `OSError`, which occurred before test collection. There are
no collected failing test IDs or published M9.1DJ acceptance results to report.

The escalated attempt used a different approach: it inspected the preserved
failure, current reader and tests, and compared the four paths above with the
controller's `before` copies. It retained the partial implementation and only
updated handoff records. It did not repeat the known launcher failure, run
application tests outside protection, or restart the real sample. The controller
must supply the protected stage figures and tested-source proof.

Static inspection also found an unverified test expectation that the next
repair must resolve: `test_trade_rejects_null_event_time_instead_of_inventing_one`
expects `outside the supported timestamp range`, but the unsigned nanosecond
sentinel is within Python datetime's range. The trade branch can therefore
reach `receipt precedes its event time` instead. This is a code-reading finding,
not a collected test failure or a passing rejection test. Preserve rejection of
the invalid trade time when resolving the mismatch under the next assignment.

M9.1DJ remains blocked. M9.1DK is the proposed continuation, subject to review:
resolve that focused expectation, obtain fresh protected acceptance, then have
the supervisor restart the exact D-116 sample. It is not independent permission
to run the sample before reader acceptance. Existing source gaps and all OFF
switches remain unchanged.

## Current focused-failure repair — 2026-09-22 Pacific

The controller subsequently collected the failure anticipated above. Its
preserved log is
`/root/trade-alerts-builder/runs/20260922-162603-923149-build/verification.log`.
The failing selector was
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_trade_rejects_null_event_time_instead_of_inventing_one`.
The exact mismatch was:

```text
Expected regex: 'outside the supported timestamp range'
Actual message: 'row 0 receipt precedes its event time'
1 failed, 13 passed in 1.65s
```

That last line is the historical controller pytest line, not a new acceptance
result or controller wall time. The supplied failed-stage record has runs `1`,
test_count `null`, selection_reason `builder named directly affected checks`,
and selectors `["tests/trade_alerts_contracts/test_retained_quote_trade_reader.py"]`.
No JUnit time or controller wall time was supplied for it.

Cause: the unsigned missing-time marker converts to a representable Python
date. Relying on date overflow cannot reject it by meaning. The current working
files already contained an explicit trade-only rejection and the matching
`trade event time is undefined` expectation when this repair session opened;
both were preserved. This approach rejects the missing trade time before the
receipt-order check instead of merely accepting the earlier accidental error.
The rejection test now also supplies equal raw event/receipt markers, so the
order check cannot mask the required rejection. A direct non-null BBO future
event case preserves the strict nanosecond boundary.

The existing recording test now includes ordinary rows, a BBO row with no
trade time and an empty BBO row. It checks serialized null trade time, the exact
raw marker and missing-book status. Its selector remains
`tests/trade_alerts_contracts/test_retained_quote_trade_reader.py::test_recorded_reader_proof_is_deterministic_and_contains_both_schemas`;
its output remains `m91cz-retained-quote-trade-reader-proof.json`. The controller
must collect this selector in both fresh repeatability runs and compare that
file before any repeatability claim.

The protected focused launch requested the reader file and its direct caller's
`tests/trade_alerts_contracts/test_retained_candidate_events.py`. It stopped
before collection:

```text
OSError: [Errno 22] Invalid argument: '/tmp/trade-alerts-m04-xn49o13k'
```

The unchanged launcher failed at `os.chown` on line 27. It was not retried and
no application tests ran outside protection. Fresh controller stages will
supply phase, runs, test_count, wall_seconds, selection_reason, selectors,
focused results, tested-source manifest and recording comparisons. None is
claimed here. Earlier failure evidence and attempt history remain preserved.

The reader repair is ready for protected verification, but the entire M9.1DJ
handoff remains blocked: the supervisor-owned exact 47-session D-116 restart
has not happened. M9.1DK remains open for that restart after protected acceptance
and independent review. No full D-114 shard, held-out inspection, fills, returns
or supervised package is released. Source-gap dependents remain OFF and untested.
