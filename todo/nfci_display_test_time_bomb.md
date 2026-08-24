# Fix the NFCI market-context test that fails once too many days pass

**Status:** OPEN
**Created:** 2026-08-24

**CURRENT STATUS (2026-08-24):** Root-caused, not fixed. Found while running the full test
suite for an unrelated session (TODO #91/#92) — confirmed unrelated to that work (no shared
code touched) and failing in isolation, so it's a pre-existing bug, not a regression from
that session.

## What's wrong

`tests/test_nfci_display.py::test_market_handler_uses_cached_nfci_row_only` hardcodes a fake
NFCI reading dated `"2026-08-07"` and expects the `!market` command's reply to contain the
line `"NFCI -0.549"`.

The real code that builds that line — `render_nfci_note()` in
`consensus_engine/alerts/nfci_display.py:37` — has a freshness check: if the reading is older
than `features.cross_asset.nfci_max_observation_age_days` (16 days, per the test's own config
mock) as of *today's real calendar date*, it treats the reading as stale and renders nothing.

The test never mocks "today's date" — it uses whatever the real clock says. `2026-08-07` was
fresh when the test was written (commit `467f7cd`, 2026-08-16) and stayed fresh through
`2026-08-23`. On `2026-08-24` the gap crossed 16 days and the test started failing — not
because anything broke, but because a fixed date got old.

## Why it matters

This is a "time bomb" test: it silently passes or fails depending only on what day the suite
happens to run, with zero code changes in between. That's exactly the kind of failure a
regression gate is supposed to catch as noise, not signal — and it will keep tripping (or
staying suspiciously green) at the wrong moments unless fixed.

## Fix

Mock "today" instead of hardcoding an aging date. In the test:
- Patch whatever `render_nfci_note()` receives as `as_of` (currently
  `datetime.now(ZoneInfo("America/Los_Angeles"))`, passed in by `_handle_market()` in
  `consensus_engine/alerts/commands.py:2687-2690`) so the test controls it directly, OR
- Compute the fake row's `nfci_observation_date` relative to real "today" at test-run time
  (e.g. `today - timedelta(days=5)`) instead of a fixed string.

Either way, the fix must not touch `nfci_display.py`'s actual staleness logic — that logic is
correct and intentional (an old NFCI reading genuinely shouldn't be shown as current). Only
the test's fixed date is the bug.

## Files involved

- `tests/test_nfci_display.py:157` — the failing test, `test_market_handler_uses_cached_nfci_row_only`
- `consensus_engine/alerts/nfci_display.py:25-37` — the real staleness check (correct, don't touch)
- `consensus_engine/alerts/commands.py:2687-2690` — where `_handle_market()` passes `nfci_row`/`as_of` in

## Open questions

- Are there other tests in this file (or elsewhere) with the same fixed-date-vs-freshness-window
  pattern that will time-bomb later? Worth a quick grep for other hardcoded dates near staleness
  checks while in this file.

## Currently pinned in `.test-baseline`

`tests/test_nfci_display.py::test_market_handler_uses_cached_nfci_row_only` is listed in
`.test-baseline` so the regression gate doesn't block unrelated work on it. Remove that line
once this is fixed.
