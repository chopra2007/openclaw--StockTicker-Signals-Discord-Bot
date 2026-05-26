# 13 stale unit tests after the `!all` refactor + critical-sources change

**Status:** DONE 2026-05-22.

Surfaced 2026-05-20 during the agent-model-roulette full-suite verification run. 13 tests fail on `master` — pre-existing and unrelated to that work (confirmed: identical failures with the diff stashed). All are stale assertions, not real bugs — `!all` posts a coherent embed and degraded mode runs; the tests check old structure:

- `test_all_command_earnings_date.py` ×2 — `KeyError 'Next Catalyst'`
- `test_all_command_low_confidence_trade_plan.py` ×2 — `KeyError 'SL'`
- `test_all_command_narrator_prompt.py` — header `YOUTUBE ANALYST CALLS` changed
- `test_all_command_narrator_timeout.py` — expects synth timeout ≤50s; code is 90s (commit 31cbaa9 raised it). Confirm the ~80s `!all` wall-clock budget still holds — otherwise this one is a real perf regression, not a stale test.
- `test_degraded_mode.py` ×3 — `assert True is False` (critical_sources set changed in commit 108dcc9)
- `test_pr4a_data_layer.py` ×2 — dict-key rename; embed field count 11→3
- `test_pr5_all_command_e2e.py` ×2 — embed field list changed (`SL`/`TP1` gone)

Update each assertion to the current structure.
