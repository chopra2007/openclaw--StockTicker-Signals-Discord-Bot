# Evaluate the SMART LEVELS shadow soak, then decide go-live

**Status:** DONE 2026-06-09 — status line backfilled 2026-07-12 (TODO #72 cleanup; the header and session notes had already recorded completion).
**Created:** 2026-06-08

## The goal (plain English)
The new chart-based buy/stop/target engine for `!all` is running in **shadow** mode — it computes
its levels and logs them but does NOT change what you see yet. After it's run for a day or so on real
tickers, compare its numbers to the current (ATR-guess) numbers and decide whether to switch it on
for real.

## Status (2026-06-08)
Turned on shadow mode this session (user approved "start SMART LEVELS shadow"):
`all_command.levels.technical_engine_enabled: true` + `technical_engine_shadow_mode: true`.
A safety fix landed so the engine can never crash `!all` even if price data is missing.

## Next steps
1. After ~1 day of real `!all` usage, read `.omc/logs/smart-levels-shadow.jsonl` — each line has the
   baseline (current) plan vs the shadow (new-engine) plan for a ticker.
2. Eyeball: are the shadow buy/stop/target levels sensible vs the chart? Better than the ATR guess?
   The earlier shadow pass scored 9/10 on real tickers.
3. If good → go live: set `technical_engine_shadow_mode: false` (+ consider
   `all_command.confluence_bonus_enabled: true`), restart. If not → keep shadow / tune.

## Files
- `config/consensus.yaml` → `all_command.levels.*`.
- `consensus_engine/alerts/all_command/aggregator.py` (the wrapped technical-engine block ~1028).
- Shadow log: `.omc/logs/smart-levels-shadow.jsonl`.
