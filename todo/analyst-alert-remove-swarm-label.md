# Remove the repeated SWARM label from analyst alerts

**Status:** OPEN
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** Not started. The live `#alerts` room and its sender were checked:
this room currently receives only analyst-group alerts, and all of its last 10 messages repeated
`SWARM` in the title. The owner added a historical-proof requirement for every feature in this batch.
Next: simplify the title/footer, then replay saved analyst groups and prove that every other card fact
is unchanged before checking the real Discord card.

## What the user wants

`#alerts` always says `SWARM`, but there is no visible alternative type that makes that label useful.
If this room contains only analyst-group alerts, remove the repeated word and make the title say the
important facts directly.

Example target:

`🚨 $MU — 2 analysts tweeting in 37 min`

## What worked so far

- The dedicated room is configured by `api_keys.swarm_alert_channel_id`.
- `consensus_engine/alerts/discord.py::send_swarm_alert` is the only production sender found using
  that room setting.
- The last 10 live messages checked on 2026-08-17 were all the same alert type. There was no second
  category whose meaning depended on seeing the word `SWARM`.
- The current alert already has useful analyst links, elapsed time, price, and the owner ping. Keep
  those behaviors.

## What does not work and why

`format_swarm_alert()` currently hard-codes both:

- `🚨 SWARM:` at the start of every title.
- `analyst swarm` in every footer.

Those labels repeat the room's only purpose instead of helping the owner read the alert.

## Next steps, in order

1. Change only the user-visible title and footer in
   `consensus_engine/alerts/discord.py::format_swarm_alert`.
2. Keep the internal names (`detect_swarm`, `SwarmResult`, `swarm_state`, and config keys). Renaming
   working internals adds risk and gives the owner no benefit.
3. Update the matching assertions in `tests/test_analyst_swarm.py`.
4. Render a sample with 2 analysts and one with 4 analysts. Confirm the ticker, count, elapsed span,
   links, price, and ping behavior are unchanged.
5. Read the real Discord test card before marking this done.

## Historical verification required before DONE

- Rebuild every recoverable analyst-group alert from the stored group and tweet rows, not only one
  hand-written fixture.
- Compare the old and new cards. Apart from the requested title/footer wording, the ticker, analyst
  count, elapsed span, analyst links, price, and ping behavior must stay the same.
- Have Codex inspect the replay mismatches and explain each one. No unexplained mismatch can be waved
  through as “formatting only.”
- Finally read a real test card in Discord. Unit tests and a local dictionary are not enough.

## Files / code involved

- `consensus_engine/alerts/discord.py` — builds and sends the analyst-group card.
- `consensus_engine/analysis/herding.py` — detector and state; should not need behavioral changes.
- `tests/test_analyst_swarm.py` — current title/footer checks and ping coverage.
- `config/consensus.yaml` — confirms this room is dedicated to these alerts; no config change needed.

## Open questions

None. The room and code both show that `SWARM` is the only current alert type there.
