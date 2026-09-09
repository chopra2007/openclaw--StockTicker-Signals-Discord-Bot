# Session-close gate treats shell scripts as documentation

**Status:** Active

**Created:** 2026-09-08

**CURRENT STATUS (2026-09-08):** OPEN, found while fixing TODO #69. `session_close.sh` line ~106 decides
"code change vs doc-only" with `grep -E "^(consensus_engine/|scripts/.*\.py|tests/|config/)"`. A `.sh`
under `scripts/` matches nothing, so it is classified doc-only and pushed with `--no-verify` — no test
gate at all. This is not theoretical: on 2026-09-08 a change to `scripts/run_pytest_isolated.sh` — the
script that RUNS every test gate — went to master ungated for exactly this reason. `scripts/pre-push`
itself has the same exposure.

**File:** `/root/task_system/scripts/session_close.sh` (line ~106)

**Fix:** widen the pattern to `scripts/.*\.(py|sh)`, then prove it: make a throwaway `.sh` commit and
confirm the log says "Code changes detected — running regression gate", not "Doc-only".

**Why it wasn't fixed on the spot:** it was found at session close, after that session's gate had already
run. Editing the close-time push script without time to test it risked breaking "bye" itself.

### Session notes — 2026-09-08
- **Worked on:** Found and recorded the gap; ran the full suite by hand to cover the change that slipped through.
- **Decisions:** Log rather than fix at close time — untested edits to the push script are how "bye" breaks.
- **Next:** Widen the pattern to include `.sh` and verify with a throwaway commit.
