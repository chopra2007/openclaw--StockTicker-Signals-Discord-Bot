# Isolated test runner hides packages installed in openclaw's home

**Status:** Active

**Created:** 2026-09-08

**CURRENT STATUS (2026-09-08):** OPEN, pre-existing since 2026-08-03 (commit f82ee38), found while
running the full suite on 2026-09-08. `scripts/run_pytest_isolated.sh` sets `HOME=/tmp` for containment.
Python looks for user-installed packages under `$HOME/.local`, so every package installed that way — e.g.
`databento`, which lives in `/home/openclaw/.local/lib/python3.10/site-packages` — is invisible inside the
runner. Result: `tests/research/test_auction_pressure_features.py` fails to import and the suite exits
non-zero (3807 passed, 21 skipped, 1 collection error). Proven: `sudo -u openclaw python3 -c "import
databento"` works; the same command with `HOME=/tmp` fails.

**File:** `scripts/run_pytest_isolated.sh`

**Fix options:** set `PYTHONUSERBASE=/home/openclaw/.local` alongside `HOME=/tmp` (keeps the scratch-dir
containment, restores the packages), or install the affected packages system-wide. Either way, re-run the
full suite and confirm it ends 0 errors.

### Session notes — 2026-09-08
- **Worked on:** Identified the cause while verifying the TODO #69 hook fix; not caused by that work.
- **Decisions:** Record rather than fix — unrelated to the session's change and found at close time.
- **Next:** Add `PYTHONUSERBASE`, re-run the suite, then refresh `.test-baseline` (currently empty).
