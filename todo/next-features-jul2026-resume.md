# Finish the feature-idea sweep, reusing the already-saved codebase map

**Status:** OPEN
**Created:** 2026-07-06

## Goal

Complete the discover feature-idea-sweep run named `next-features-jul2026` — generating a broad,
creative menu of 10-30 candidate feature ideas for the bot — but reuse the system map (the
codebase overview) that's already saved to disk instead of re-scanning the codebase from scratch.

## Prerequisite — check before starting

This requires the discover plugin (repo: `chopra2007/claude-discover`, installed at the plugins
marketplace/cache locations) to support a `from_pass=1` resume path — one that reparses the saved
`pass-0-system-map.md` from disk (same mechanism the script already uses for `from_pass=3/4`) and
then runs Pass 1 (research) and Pass 2 (filter) fresh from there, skipping Pass 0 entirely.

As of this writing, that resume path does **not** exist in the script yet — it's planned to be
added in a separate session before this item is picked up. **Verify it exists first** (grep the
script for `from_pass === 1`) before launching this. If it's still missing, that addition needs to
happen before this item can run.

## Map file to reuse (already verified accurate — do not regenerate)

`/home/openclaw/.openclaw/workspace/.claude/discover/next-features-jul2026/pass-0-system-map.md`

## Run directory

`/home/openclaw/.openclaw/workspace/.claude/discover/next-features-jul2026`

## Launch settings

- dial: `deep`
- run_style: `checkpoints`
- from_pass: `1`, to_pass: `2`
- greenfield: `false`
- capabilities: `{omc: true, superpowers: true, codex: "healthy", gemini: "healthy"}`
- budget_override: `null`
- free_data_only: `true`

## Exact feature_ask to pass verbatim

Broad feature-discovery sweep across the whole trading-signal Discord bot (consensus_engine).
Looking at the TODO list and the last 24h of commits (mostly #57 Schwab options shadow-compare,
#63 decision-first alerts, #64 Wolf newsletter verifier rebuild, #65/#66 dedup+idempotency+DB
pruning), generate a wide, creative menu of things that could be worked on next - big or small:
refactors/improvements to features that already work, sub-features that extend a shipped feature,
and brand-new feature ideas. Think outside the box. Do NOT converge to just 1-2 ideas - the
deliverable IS the breadth of the list; the user explicitly wants 10-30 candidate ideas surfaced,
not narrowed early.

Specifically encouraged: composite/confluence ideas that combine multiple existing signals into
one higher-conviction read - e.g. Expected Move (the !em command, expected_move.py) + max-pain
(options.py) + supply/demand zones + smart chart levels + options-flow imbalances, combined into
'high-probability zones of interest' for long/short setups. This pattern - combine several
individually-noisy signals into one clearer picture - is exactly the kind of idea being sought,
not just single-signal tweaks.

User-supplied lead to research explicitly: VVIX relative strength vs VIX (volatility-of-volatility
vs volatility - e.g. CBOE ^VVIX/^VIX ratio or its trend) as a candidate input into that same
combined-zones/confluence approach, alongside EM, max-pain, and more. IMPORTANT CONTEXT: a pure
VIX-level-based market top/bottom PREDICTOR was already researched this repo and found NO-GO on
free daily data (see TODO #47 / vol-indicator-accuracy-research - proven no statistical edge
across 5+ rigorous phases). VVIX/VIX relative strength is a DIFFERENT angle (a volatility
term-structure / 'fear-of-fear' regime signal, not a standalone top/bottom caller) proposed as one
descriptive input alongside EM/max-pain/etc., not a revival of the already-rejected predictor -
research whether it is genuinely additive (free data availability via yfinance ^VVIX, and whether
it's actually independent of signals already feeding the score) rather than auto-rejecting it as
'already tried' or auto-accepting it without checking for overlap.

Free/public data sources only. Read the actual current code for all named features before
proposing changes to them (expected_move.py, options.py max-pain + unusual-flow, the smart-levels
engine, wolf_beneficiaries.py, insider_display.py, etc.) - this repo has ~500 Python files and a
long feature history (66 TODO items), so redundancy-checking against what's already shipped
matters more here than usual.

## Next steps, priority-ordered

1. Confirm the discover plugin has a working `from_pass=1` resume path (see Prerequisite above).
2. Launch the burst with the settings above.
3. Once Pass 1-2 complete: present the full ranked idea list to the user for checkpoint review —
   that list is the deliverable.
4. Ask the user whether to stop there or continue to Pass 3 (kill-test) + Pass 4 (plan) for the
   top picks.

## Files / code involved

- `chopra2007/claude-discover` — `workflows/discover-pipeline.js` (the resume-path prerequisite)
- `.claude/discover/next-features-jul2026/` — run directory, existing map file, state.json

## Open questions

- None — this item is fully specified and ready to execute once the prerequisite is confirmed.
