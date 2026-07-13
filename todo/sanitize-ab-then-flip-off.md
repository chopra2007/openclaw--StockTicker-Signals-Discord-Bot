# A/B the !all "tidy text" step, then turn it off

**Status:** DONE 2026-06-09 — status line backfilled 2026-07-12 (TODO #72 cleanup; the header and session notes had already recorded completion).
**Created:** 2026-06-08

## The goal (plain English)
There's a cleanup step on `!all` (an AI "tidy the text" pass, flag `all_command.sanitize_enabled`).
Turning it OFF saves up to ~9 AI calls per command. The user approved turning it off — BUT only
after an A/B check confirms the free models don't start inventing numbers without that prose pass.

## Status
Approved by user 2026-06-08 ("A/B check, then OFF"). NOT done this session — the provider was flaky
(OpenRouter vision 502s, serpapi 429s) and a rushed comparison could give a wrong answer. So
`all_command.sanitize_enabled` is still **true** (no change, no risk).

## Next steps
1. Pick a calm moment (providers healthy). Run `!all` on NVDA, AMD, TSLA + one more, with
   `all_command.sanitize_enabled` ON, capture the output.
2. Flip it OFF (config), re-run the same 4, capture again.
3. Diff the two: confirm no fabricated/invented price numbers appear in the OFF version (the prose
   pass currently masks that). Format/wording differences are fine; invented numbers are not.
4. If clean → leave it OFF (commit the flip). If numbers get invented → leave it ON and report why.

## Files
- `config/consensus.yaml` → `all_command.sanitize_enabled` (currently true).
- Path: `consensus_engine/alerts/all_command/aggregator.py` (~1245, reads the flag) + narrator.
- Shared-file tripwire: this is on the !all critical path — re-test the whole `!all` feature, not
  just the narration diff.
