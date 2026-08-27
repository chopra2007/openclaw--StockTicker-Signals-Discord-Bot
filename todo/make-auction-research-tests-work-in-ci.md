# Make auction research tests work in GitHub

**Status:** OPEN
**Created:** 2026-08-27

**CURRENT STATUS (2026-08-27):** GitHub run 33024400974 failed because the
auction tests expect machine-only research files and paths that do not exist on
GitHub, plus one readiness test depends on live-machine state. The same 64
affected checks pass on the live machine. This is a test-setup problem, not
evidence that the morning PUT feature broke. Next: replace those outside-file
and live-state assumptions with small test-owned fixtures, then rerun the full
GitHub gate.

## What happened

- GitHub reported 5 failures and 10 setup errors.
- Most came from a missing `.omc/research/opening-auction-imbalance/phase1-gate.json`
  file or safety checks rejecting machine-local research paths.
- `test_preflight_is_silent_when_everything_is_ready` also relied on readiness
  state available on the live machine but absent on GitHub.
- A focused local rerun passed all 64 affected checks.

## Next steps

1. Make the auction tests create their own temporary research files.
2. Make the readiness test supply its own timer and access state.
3. Run the focused checks locally, then the full suite, then the GitHub gate.

## Files involved

- `tests/research/test_auction_pressure_features.py`
- `tests/research/test_auction_pressure_safety.py`
- `tests/test_put_flow_shortlist.py`
- `.github/workflows/regression.yml`
