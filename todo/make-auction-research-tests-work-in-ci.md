# Make auction research tests work in GitHub

**Status:** DONE 2026-08-27
**Created:** 2026-08-27

**CURRENT STATUS (2026-08-27) — DONE.** All three test files now build their own
inputs instead of reaching outside the repository: the auction feature tests
write a temporary `phase1-gate.json` with the same shape, the auction safety
tests spell out the allowed roots the research scripts actually pin rather than
deriving them from wherever the repo happens to live, and the PUT-flow readiness
test supplies its own private-room id. No auction calculation, conclusion or
live behaviour changed — TODO #93 stays rejected.

Proved the way GitHub sees it: the three files were run from a clean copy of the
tracked tree with `.omc/research/opening-auction-imbalance/` absent. **113
passed.** Commit `ef1b53c`.

(The TODO said "64 affected checks" — that was GitHub's own tally. The three
files hold 113 tests in total and every one of them passes.)

One thing found along the way that was NOT the reported cause: the feature file
also fails at import as the `openclaw` user because `databento` was missing for
that user. It is in `requirements.txt` so CI installs it; it is now installed on
this machine too.

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
