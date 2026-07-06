# Make the bot's alerts honest and decision-first (one clear alert, ACT vs WATCH)

**Status:** OPEN
**Created:** 2026-07-05

## What this is
From the #61 research run (UX lens + user pick "one clear alert, not three"). The bot's alert
output fails on the exact axis the product cares about — separating "act now" from "just watch" —
and it overstates confidence. This is the biggest user-facing improvement, but it CHANGES LIVE
ALERTS, so it needs a shadow/staged check before going live (that's why it wasn't shipped in the
research session).

## Verified problems (real, from logs/code 2026-07-05)
- **3 embeds in one second.** A real $MU spike (Jul-5 17:09) fired a SWARM alert + an instant ping +
  a detail follow-up within 8 seconds, and two shown scores DISAGREE (ping "25 (cross-refs
  pending)" vs detail "83"). This trains users to mute the channel (alarm-fatigue research).
- **"83" reads as 83%** but the engine itself prints `score/100 (uncalibrated)`. The honesty eval
  proved the score has ~no real edge (AUC ~0.507), so a numeric score is false precision.
- **No price stop on the alert face** — the "Invalidation" line is a process index ("disagreement
  below 60/100"), not a price. Every trade needs a price invalidation.
- **LOW-confidence ideas written as ACT-NOW orders** (e.g. "Long $MU above $1132" on a LOW card).

## What to build (all free render changes)
1. **One embed per event** — merge SWARM + instant ping + detail into ONE message that EDITS itself
   in place when cross-ref lands (ping → edit). Kills the 25-vs-83 contradiction and the fatigue.
   Builders live in `consensus_engine/alerts/discord.py` (instant ping `:264/308`, Score-card
   `:343-540`) — merge carefully, PRESERVE the louder SWARM styling.
2. **ACT vs WATCH** as the first token (color-coded). Splits actionable from passive.
3. **Score → Watch/Lean/Strong bucket** (raw score to vault only). Buckets should be defined by the
   measured lift from `consensus_engine/eval/` — but since edge is ~nil today, default most alerts to
   WATCH (abstention). This is the "abstention as a feature" idea.
4. **Price stop on the card face** (levels are already computed — just render).
5. **Kill-list** (move to vault): duplicate score restatements, Breakdown arithmetic,
   Precision/Regime/Freshness telemetry, low-signal `!all` stats. Progressive disclosure.

## Discipline / gates
- LIVE ALERT change → per DoD, run a shadow/staged check before flip (compare old vs new render on
  recent real alerts; confirm no regressions in what fires). Do NOT flip blind.
- Shared-file tripwire: touches `discord.py` + maybe `embed.py` — test all `!all`/alert render tests
  and grep `tests/` for the old field strings.
- The abstention buckets should read from the eval module so "Strong" means something measured.

## Files
- `consensus_engine/alerts/discord.py`, `consensus_engine/alerts/all_command/embed.py`.
- Full before/after sample output in `.omc/plans/bot-research-build/lens5-ux.md` (section B).

## Open questions
- How aggressive should abstention be given the ~nil measured edge? (Maybe most alerts → WATCH.)
