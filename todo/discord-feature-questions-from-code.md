# Make feature questions get grounded, smart answers

**Status:** OPEN
**Created:** 2026-08-17

**CURRENT STATUS (2026-08-17):** Not started. The live Discord agent already has the repository as its
workspace, full file and shell tools, and a prompt that tells it to read code before answering. The
missing proof is answer quality: the current lead model is `gpt-4.1-nano`, chosen for speed on an older
test set. Next: grade the exact feature-question examples against the live path, then choose a stronger
model or tighter prompt from measured results rather than adding more permissions.

## What the user wants

When the owner asks what a bot feature means, the Discord bot should inspect the real code on the
server and answer intelligently in plain English. It should handle follow-up questions instead of
giving a generic definition or promising a change that does not fit how the feature works.

The key example is:

`What is Our own signal breadth, what tickers are measured, and can you add 2 more tickers to the list if I give them to you now?`

## What worked so far

- `consensus_engine/main.py::_STEERING_TEMPLATE` already tells the agent to read the host's code,
  config, and database before answering a concrete feature question.
- `/home/openclaw/.openclaw/openclaw.json` points the agent at this repository and gives the owner-only
  Discord path full tools.
- The reliability work in TODO #79 already fixed repeated tool loops, bad retries, and missing room
  context.
- The code gives a precise answer to the example: `Our own signal breadth` is not based on a fixed
  ticker list. `consensus_engine/analysis/internal_breadth.py` counts every distinct ticker with a
  qualifying bullish or bearish row in `signal_events` over a rolling 5-calendar-day window. Neutral
  rows, ApeWisdom, and SEC/Form-4 rows are excluded. Therefore there are not “two more tickers” to add
  to a list; qualifying tickers enter automatically when their signals arrive.

## What does not work and why

The current model choice was proven on an older three-question tool test, not on owner-facing feature
explanations, multi-part questions, or follow-ups that require recognizing a false premise. Tool access
alone does not prove that the model will open the correct file, understand it, and explain it clearly.

Adding broader server permission is not the answer. The agent already has code access. The work is to
measure correctness, plain language, and safe follow-through, then use a model capable enough to pass.

## Required answer behavior for the example

The bot should say, in plain English, roughly:

> It measures the bot's own recent bullish and bearish signal stream. It counts every qualifying
> ticker seen in the last five calendar days, not a fixed watchlist. So there is no ticker list to add
> two names to; they are included automatically when qualifying signals arrive.

It may name the exclusions if useful. It must not invent a watchlist, claim it changed code, or dump
internal implementation detail at the owner.

## Next steps, in order

1. Build a small real test set of 8–12 feature questions. Include `Our own signal breadth`, VVIX vs
   VIX, expected move, alert scores, analyst groups, and one question whose premise is wrong.
2. Run the questions through the same `!ask` / mention path the owner uses. Grade factual correctness,
   whether the right files were read, plain English, completion time, and cost.
3. Use the current lead model as the control. Race capable current models from the live provider
   catalog, including strong models first. Do not conclude from cheap or small models alone that the
   task is impossible.
4. Pick the least expensive model that clears the quality gate reliably. Update the agent chain only;
   do not disturb the separate models used by alerts, `!all`, or the morning brief.
5. Tighten `_STEERING_TEMPLATE` only where the failures show a specific need. Avoid adding a long
   feature manual to every prompt; the agent should read the code.
6. Test a multi-turn follow-up. The agent must remember which feature is being discussed and correct
   the “ticker list” premise rather than agreeing blindly.
7. Restart the gateway if the model config changes. Ask the exact example in `#chat`, read the real
   answer, and compare it to the code before marking this done.

## Files / code involved

- `consensus_engine/main.py` — mention handler, steering prompt, retries, and model overrides.
- `config/consensus.yaml` — `llm.agent_model` and `llm.agent_fallback_models`.
- `/home/openclaw/.openclaw/openclaw.json` — live agent workspace, tools, and synced model chain.
- `scripts/sync_gateway_models.py` — keeps the live gateway chain in sync.
- `consensus_engine/analysis/internal_breadth.py` — truth source for the example feature.
- `scripts/market_daily.py` — reads `signal_events` and writes the daily breadth row.
- `tests/test_handle_mention.py` — existing mention and room-context coverage.

## Open questions

- Which current model clears the real feature-question set with acceptable speed and cost. This must
  be measured live; the older bake-off is not enough.
- Code-changing requests from Discord need a separately bounded safety rule. This item proves smart,
  grounded answers first; it must not silently widen the bot into an unrestricted self-deployer.
