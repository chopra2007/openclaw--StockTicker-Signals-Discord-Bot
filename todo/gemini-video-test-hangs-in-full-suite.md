# One Gemini video test hangs and stalls the whole test run

**Status:** OPEN
**Created:** 2026-08-27

**CURRENT STATUS (2026-08-27):** A single test —
`tests/test_gemini_video_parser.py::test_extract_evidence_chunked_budget_abort_keeps_partial`
— never finishes. Because pytest runs tests one after another, it does not just
fail: it **stops the entire suite** at roughly the 45% mark, so nothing after it
is checked at all. Next: find what it waits on and give it a bounded fake
instead of the real thing.

## Why we know it is not new

It was found during TODO #100, but it is **not caused by that work**. The same
test was run against commit `f390d17` — the state of the code *before* that
session started — in a clean copy of the tree, and it still ran past two
minutes. Nothing in TODO #100 touches the Gemini video parser.

## What it looks like

- On its own the file takes **156 seconds** and the test fails once a 45-second
  cap is imposed. With no cap it simply never returns.
- The stack shows a worker thread parked on `work_queue.get(block=True)` — it is
  waiting for a job that never arrives, or for a real network call.
- Two full-suite runs stalled at exactly the same place before the cause was
  found.

## Why it matters more than one failing test

`.test-baseline` is empty, which is meant to say "every test passes". That claim
cannot currently be checked, because the run never reaches the last 55% of the
suite. Any real regression hiding in that half would go unnoticed.

## Next steps

1. Read the test and find what it waits on — most likely a real Gemini call or a
   thread pool that is never fed.
2. Replace that with a bounded fake so the test finishes on its own.
3. Add `pytest-timeout` to the dev requirements and set a default cap in
   `pytest.ini`, so a future hang fails loudly in seconds instead of silently
   eating the rest of the run. It is installed on this machine but not recorded
   anywhere.
4. Re-run the whole suite with no deselect and confirm the count.

## Files involved

- `tests/test_gemini_video_parser.py`
- `consensus_engine/scanners/` — whichever module the test drives
- `pytest.ini`, `requirements.txt`
