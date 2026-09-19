# M0.2I bounded free source cost check

Date: 2026-09-14 Pacific. Status: **BOUNDED ATTEMPT COMPLETE; COST AND SOURCE GATES BLOCKED.**

`M0_2I_COST_CHECK_RESULT.json` records the six exact requests frozen in
`M0_2H_SOURCE_ACQUISITION_SPEC.json`. The installed Databento 0.84.0 client
started each `Historical.metadata.get_cost` call once, in order. The calls used
the frozen symbol lists, passed `end_exclusive` as the SDK `end` value and
omitted the old `mode` field.

The sandbox denied the named `.env.service` read. The child process therefore
received an empty credential value. Local name lookup then failed before any
connection to `hist.databento.com` was made. All six calls have status
`FAILED_NO_RETRY_LOCAL_DNS`; no provider response or cost was returned. M0.2I
allows no retry, so every cost stays `UNKNOWN`.

No source records were requested. No file was downloaded. No token was
refreshed. No reservation or spend ledger changed. New spending was $0. The
existing $40 total cap, $16 reservation, $24 unreserved amount and unknown
billing state are unchanged. No price, return or strategy result was inspected.

The bounded attempt record is complete, but it supplies no source-cost evidence.
Source qualification, original availability, corrections, finality, complete
stock tape and NBBO coverage, point-in-time membership, historical borrow and
options, catalyst history, untouched final dates, replay, promotion and live use
remain blocked. All switches stay off.

Protected document checks and independent review remain required. A later
source-access recovery must be separately reviewed before any request is sent;
this record does not authorize a retry.
