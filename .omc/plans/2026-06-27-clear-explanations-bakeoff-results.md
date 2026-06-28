# Results — #52 clarity bake-off (2026-06-27)

Raw data: `2026-06-27-clear-explanations-bakeoff-raw.json` (all 9 answers + 9 verdicts).
Method/spec: `2026-06-27-clear-explanations-bakeoff.md`.

## Setup

Three "explain this" prompts, given **cold** to Claude (opus-4-8), ChatGPT (gpt-5.5 via
codex CLI), and Gemini (gemini CLI) — none told it was a test. Then each topic's three
answers were pasted side by side, **anonymized A/B/C and shuffled** (rotated so every
model sat in each slot once), and all three models judged blind: rank + why.

## Scoreboard — Claude won all 3 topics, 8 of 9 blind votes

| Topic | claude judge | chatgpt judge | gemini judge | Winner |
|---|---|---|---|---|
| Put/Call scale | Claude | Claude | Claude | **Claude 3/3** |
| vol/OI ratio | Claude | Claude | Claude | **Claude 3/3** |
| Score band | Claude | ChatGPT | Claude | **Claude 2/3** |

The only non-Claude vote: ChatGPT picked its own minimal score-band answer (a mild
self-vote — and a defensible "shorter is clearer for the exact question" view).
Self-vote check: of 9 judgments, only that one judge ranked its own answer first;
Gemini even ranked its own score-band answer *last*. Blind shuffling held up.

## What made the winners win (the rule, in the judges' own words)

Every judge, every topic, rewarded the same moves:

1. **One stable frame, in the reader's currency.** Put/Call winner translated to
   "down-bets per up-bet" and held it; judges dinged the loser for making you "flip
   the ratio in your head" and "switching which side is the baseline."
2. **Whole numbers, never fractions.** "Two up-bets for every one down-bet" beat
   "half as many puts as calls." Judges repeatedly punished forced mental division.
3. **A constant anchor per line** (a mood word / label) so even when the two nouns
   swap, the reader keeps one compass.
4. **Show the full scale for context.** Score-band winner listed all four bands so 72
   has a place; judges: "without the full list you don't know if Strong is the 2nd or
   3rd tier."
5. **Action verbs, not adjective bloat.** "Worth acting on" beat "high-conviction,
   robust, data-backed recommendation" ("filler words that add length, not clarity").
6. **A concrete image to make scale land.** "the 64 leftovers are a rounding error."
7. **Don't overclaim.** Judges punished "smart money / capital and conviction / often
   precedes a move" as "interpretations dressed as certainties" that hurt clarity.

## The sharpened rule (vs the naive read of #52)

The naive read was "never swap which noun is the baseline." The bake-off shows the
real target is **never make the reader do mental math or re-orient.** Swapping the two
nouns inside a *fixed whole-number structure* with a constant anchor is fine (it won).
What loses is (a) mixing a fraction frame with a whole-number frame, or (b) holding one
rigid noun-order by going abstract. So: one structure + whole numbers + constant anchor,
nouns may swap.

## Where it now lives

- `comm-check.md` **Section 6 — "Consistent framing (one yardstick)"** — full rule,
  gold answer, checklist (primary home).
- `CLAUDE.md` pre-send checklist **item 6** — one trigger line so it fires every session.
- Memory `feedback_consistent_framing_explanations.md` — failure log (unchanged + cross-link).

## Honest limits

Both rounds used the real external models: the answers are genuine codex (gpt-5.5) and
gemini CLI output, and the judging was done by Claude (direct) plus real codex and gemini
(run via a verbatim courier agent and checked against the raw on-disk files). The limits
are: n=3 prompts; LLM-as-judge is subjective; and Claude was one of the three judges, so
a third of the panel shares the winner's model — though it judged blind and the other two
models independently agreed on 2 of 3 topics. Treat the 8/9 as directional, not a
benchmark. The user is the final arbiter of what reads clearly.
