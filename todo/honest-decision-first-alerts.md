# Make the bot's alerts honest and decision-first (detailed card + trade levels + one merged message)

**Status:** DONE 2026-07-05 (LIVE)
**Created:** 2026-07-05

**DEPLOYED 2026-07-05:** merged to master (merge commit da42a51, combined with the concurrent #64
Wolf-verifier work) and `consensus-engine.service` restarted clean (active, 0 restarts, all loops up).
`alerts.merged_detail_card.enabled` is ON in the live config. Full suite 2624 passed on the merged
tree. Render verified via the real builder in #chat (Step 1 ping → Step 2 self-editing detailed card).
**Live check still owed (cheap):** eyeball the FIRST real merged alert when a tweet next fires — confirm
the ping edits itself into the detailed card in place, the 📐 Trade Levels line renders, and the tweet
text + TweetShift link are preserved. Revert instructions below if anything looks wrong.

**CURRENT STATUS (2026-07-05):** DIRECTION CHANGED after the user reviewed live renders in Discord
#chat. The user REJECTED the stripped-down "decision-first ACT/WATCH card" — they want the FULL
DETAILED card KEPT ("I like having more info and detail"). Final approved design = keep the detailed
card, add two things, behind ONE revertible flag `alerts.merged_detail_card.enabled` (default **ON**):
1. **📐 Trade Levels field** on the detailed card — Enter / Stop / Target / R:R computed from
   `technical.atr14` (`_compute_atr_fallback`, 2×ATR symmetric, direction-aware). Fixes the old gap
   where the card only showed a process condition ("disagreement below 60/100"), never a stop price.
2. **Merge the instant ping INTO one self-editing detailed card** — the ping now EDITS itself in
   place into the full detail card when cross-ref lands (no separate 2nd message, no "25 vs 83"
   contradiction). The merge PRESERVES the ping's unique content the user called out: the analyst's
   **tweet text** (embed description), the **analyst identity** (author), and the **TweetShift link**
   (Source field). A failed in-place edit falls back to posting the detail as a new message (never
   drops the alert). The ping's pre-merge score line shows "⏳ cross-referencing sources…" (no number).
Built in `discord.py` (`format_merged_card`, `send_merged_followup`, `_trade_levels_field`, trade-levels
insert in `format_detail_followup`, neutral ping score) + `main.py` flag branch. Flag is forced OFF in
tests (`tests/conftest.py`) so existing renders stay byte-identical; new tests cover the ON behavior.
The earlier stripped `format_decision_card` / `alerts.decision_first` was REMOVED.

**➡️ HOW TO REVERT (if the new format isn't wanted later):** set
`alerts.merged_detail_card.enabled: false` in `config/consensus.yaml` (it's in the `alerts:` section),
then restart `consensus-engine.service`. That immediately restores the OLD behavior — the separate
instant-ping message + a separate detail follow-up message (2 cards), and removes the 📐 Trade Levels
field. No code change or redeploy needed; it's a pure config flip. To re-enable, set it back to `true`
and restart. (The DB/vault raw score was never on the card and is unaffected either way.)

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
