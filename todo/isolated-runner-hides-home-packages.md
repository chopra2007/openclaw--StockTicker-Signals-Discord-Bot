# Isolated test runner hides packages installed in openclaw's home

**Status:** DONE 2026-10-04

**Created:** 2026-09-08

**CURRENT STATUS (2026-10-04):** DONE. Added `PYTHONUSERBASE=/home/openclaw/.local` to `PYTEST_ENV` in `scripts/run_pytest_isolated.sh` (commit 130ee75). The `databento` collection error is gone; `test_auction_pressure_features.py` 32 passed; full suite 4386 passed, 121 skipped, 0 failed (21 min).

**EARLIER STATUS (2026-09-08):** OPEN, pre-existing since 2026-08-03 (commit f82ee38), found while
running the full suite on 2026-09-08. `scripts/run_pytest_isolated.sh` sets `HOME=/tmp` for containment.
Python looks for user-installed packages under `$HOME/.local`, so every package installed that way â€” e.g.
`databento`, which lives in `/home/openclaw/.local/lib/python3.10/site-packages` â€” is invisible inside the
runner. Result: `tests/research/test_auction_pressure_features.py` fails to import and the suite exits
non-zero (3807 passed, 21 skipped, 1 collection error). Proven: `sudo -u openclaw python3 -c "import
databento"` works; the same command with `HOME=/tmp` fails.

**File:** `scripts/run_pytest_isolated.sh`

**Fix options:** set `PYTHONUSERBASE=/home/openclaw/.local` alongside `HOME=/tmp` (keeps the scratch-dir
containment, restores the packages), or install the affected packages system-wide. Either way, re-run the
full suite and confirm it ends 0 errors.

### Session notes â€” 2026-09-08
- **Worked on:** Identified the cause while verifying the TODO #69 hook fix; not caused by that work.
- **Decisions:** Record rather than fix â€” unrelated to the session's change and found at close time.
- **Next:** Add `PYTHONUSERBASE`, re-run the suite, then refresh `.test-baseline` (currently empty).

### Session notes â€” 2026-10-04
- **Worked on:** applied the `PYTHONUSERBASE` fix; ran the target test file and the full suite.
- **Result:** 0 errors, 0 failures.
- **Next:** none. `.test-baseline` refresh was not needed (suite fully green).

### Analyst-bias verification note - 2026-10-04 Pacific

The runner fix above remains DONE. Separate clean tracked-file test copies lack
ignored research evidence files. The analyst-bias baseline and broad candidate
runs had the same 12 research failure IDs; the candidate had no setup errors.
These missing evidence inputs are a separate clean-checkout regression-gate issue,
not a return of the package-path bug. Final analyst and shared-path checks passed.
