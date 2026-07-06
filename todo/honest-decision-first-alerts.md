# Make the bot's alerts honest and decision-first (one clear alert, ACT vs WATCH)

**Status:** BUILT (flag-OFF) 2026-07-05 — live flip owed
**Created:** 2026-07-05

**CURRENT STATUS (2026-07-05):** Built behind `alerts.decision_first.enabled` (default OFF);
legacy render byte-identical when OFF. What's LEFT before it goes live: a real shadow soak
(flip `alerts.decision_first.shadow: true` on the live config, watch `[decision-first shadow]`
log lines against real alerts for a day), then flip `enabled: true`. Do NOT flip blind.
Built: `format_decision_card` + `edit_instant_ping_embed` + `send_decision_followup` in
`discord.py`, flag branch in `main.py`. Delivers items 2-5 and the ping→detail half of item 1
(the ping now EDITS itself in place into the decision card — kills the 25-vs-83 contradiction).
- **ACT/WATCH + bucket are keyed off catalyst + independent corroboration, NOT the score** — the
  eval proved the score has ~nil edge (AUC ~0.50), so most alerts honestly default to WATCH.
  Strong = STRONG_ALERT + a hard corroborator (SEC/options/news); ACT = Strong AND a real stop.
- **Price stop** is computed from `technical.atr14` via `_compute_atr_fallback` (lens5's "already
  computed" was WRONG for the alert path — only `!all` had levels). Presented at an honest 1:1 R:R
  (2×ATR symmetric), direction-correct (SHORT stops ABOVE spot — verified).
- **Kill-list applied**: no Breakdown arithmetic, Precision green-checks, Regime, Freshness codes,
  or repeated raw score on the card face (raw score still persists to DB/vault, unchanged).
- Shadow before/after rendered on 3 representative cases (MU long, GME social-only watch, NVDA short).

**Two items deliberately NOT built (raise as decisions, not silent drops):**
1. **SWARM-into-card merge** — the SWARM alert fires on a *different trigger* (2+ analysts) to a
   *different channel* and doesn't share the ping's message id. Merging it is a bigger refactor with
   a channel mismatch. Left standalone; only the ping+detail were merged. Decide if the SWARM should
   also fold in.
2. **R6 spot-price sanity gate** (from lens5) — NOT built: its premise ("$1154 MU = 10× bug") is
   FALSE; MU really traded ~$1150, so a sanity gate would reject real prices. Do not build as specced.

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
