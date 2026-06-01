# RESUME — next session (wolf-news-brain, after phase-1 sample review)

Resume trigger (paste into a fresh session): `discover: resume wolf-news-brain`

## Where we are
Phase 1 is BUILT, committed clean (`ebf4ed1`, NOT pushed — push at session close), full suite green (1474 passed / 0 failed). A real Wolf email was posted as a sample to #news (`1510722777923981432`) and the user reviewed it. **Everything is still OFF** (`gmail_watcher.enabled: false` + `wolf.dry_run: true`). Nothing auto-posts.

The sample that posted (real email "Quick 3C Update - NDX"):
```
🔴 NDX (market) — Wolf turns BEAR
🆕 New thesis: divergences building
3C across multiple Nasdaq timeframes shows the Nasdaq rally maturing and showing signs of exhaustion through building negative divergences.
```

## User feedback to act on (THIS is the next work — do BEFORE going live)
1. **"Could look a bit more clear and clean."** → Improve the #news message format in `consensus_engine/alerts/wolf_news.py` `format_message()`. Current format = emoji + bold ticker + "Wolf turns BEAR" + stage line + italic snippet + optional levels. Make it cleaner/clearer. Consider: a Discord EMBED (title/fields/color) instead of plain text (the codebase already builds embeds via `send_command_embed_reply` in alerts/discord.py — model on that); clear sections (Direction · Stage · Key levels · Why); maybe a confidence/tier badge. Show the user 2-3 format options (mockups) before coding — they care about clarity.
2. **"Better quality info on the negative divergences without false positives."** → The 3C/divergence detail is the heart of Wolf's signal. Improve BOTH the extraction richness AND the precision:
   - Richer: capture which timeframes diverge (he often says "across multiple timeframes" / specific ones), confirming-vs-diverging, how mature, and the exact 3C reading per chart. The vision layer (`wolf_vision.py`) already reads "3C orange: divergence" per chart — plumb that detail into the thesis + the alert instead of collapsing to one line.
   - Fewer false positives: require corroboration before calling a divergence "real" — e.g. the email TEXT says divergence AND a chart read confirms it (cross-check text vs vision); or require >=2 charts/timeframes agreeing; gate the alert tier on divergence strength. This is essentially a mini-confluence WITHIN the Wolf email (text + N charts) — distinct from the phase-2 cross-source confluence engine.
   - Tie it to the stage machine: "diverging" stage should only fire when the divergence evidence is corroborated, else stay "forming".

## How to build next session
- Re-read this file + `final-plan.md` (esp. PLAN REVISION v2) + `pass-5-execution-log.md`.
- The phase-1 modules are all live and tested: `analysis/wolf_scope.py`, `wolf_vision.py`, `wolf_email_parser.py`, `wolf_theses.py`, `alerts/wolf_news.py`, rebuilt `scanners/gmail_watcher.py`, `wolf_news_supervisor` in `main.py`, 3 tables in `db.py` (schema v15).
- Test harness pattern: see `tests/test_wolf_macro_brain.py` (uses `fresh_db` fixture that resets `db._db`/`db.DB_PATH` — IMPORTANT, the old version polluted other tests).
- Real test assets: real charts at `/tmp/wolf_charts/` (102 of them); gmail token `/root/.openclaw/gmail/token.json`; pull real emails via the token (see `/tmp/wolf_sample_post.py` for the pattern). Gemini keys in `.env` (GEMINI_API_KEY/2).
- Mocked-LLM test pattern (no network): `monkeypatch.setattr(wolf_email_parser, "call_with_fallback", fake_llm)` — see `test_parse_email_end_to_end`.
- **KNOWN-BUG LESSON:** the prompt template has literal JSON braces; build it with `.replace("__BODY__", body)` NOT `.format()` (`.format` crashes KeyError on every real email). There are 2 regression tests guarding this now — keep them.

## After the format + divergence-quality work: the HARD GATE (unchanged)
Show the user a fresh dry-run sample with the new format → get sign-off → flip `wolf.dry_run: false` + `gmail_watcher.enabled: true` in config/consensus.yaml → `sudo systemctl restart consensus-engine` → verify both services active + no GATEWAY drift + no LLM-health fail + symlink intact → first live #news post.

## Then PHASE 2+ (per final-plan.md): confluence engine, digests/recap, beneficiary inference, backfill, level-break alerts, !all integration.

## Cleanup note
Two test/wiring lines are still sitting in #news (a "🔧 wiring test" and the "🐺 SAMPLE" header + NDX msg) — user can delete; or the next session can delete them via the bot API before posting the new sample.
