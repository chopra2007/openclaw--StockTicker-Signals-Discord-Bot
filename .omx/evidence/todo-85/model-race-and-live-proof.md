# TODO #85 — model race (cheap method), grading, and live proof

**Date:** 2026-08-18
**Outcome:** the bot's chat model changed from `openai/gpt-4.1-nano` to `google/gemini-3.7-flash`,
with `qwen/qwen3.7-flash` → `upstage/solar-pro4` → `openai/gpt-5.6-luna` behind it.

## The cheap method (this is the part worth reusing)

The first pass at this race burned the whole $3/day OpenRouter allowance in one sitting, and left the
live bot unable to answer at all for a while. Three changes made the second pass cost **$0.39 for six
models** instead:

1. **Screen on 3 questions, not 9.** Q01 (does it read the code or guess), Q02 (does the follow-up
   turn produce content at all), Q06 (does it reject a wrong framing). Those three separate the
   field; the remaining six only ran for the three survivors.
2. **A spend meter inside the harness.** `scripts/qa_feature_questions.py` now reads this key's
   spend from OpenRouter before and after every question, records `cost_usd` on each result row, and
   stops the run at `--max-spend`. It fired once, on `deepseek-v4-pro-0813`, which had already spent
   $0.24 on two questions — that model was cut before it could eat the day's budget.
3. **Price the field first.** Pulled the live OpenRouter catalog and raced the cheap-but-current
   models rather than inheriting a previous session's hand-written list.

| Model | screen cost (3 q) | rest cost (6 q) |
|---|---|---|
| inclusionai/ling-3.0-flash | $0.015 | not run |
| upstage/solar-pro4 | $0.010 | $0.058 |
| qwen/qwen3.7-flash | $0.020 | $0.192 |
| deepseek/deepseek-v4-flash-0731 | $0.030 | not run |
| google/gemini-3.7-flash | $0.080 | $0.365 |
| deepseek/deepseek-v4-pro-0813 | $0.237 (cut by the budget guard) | not run |

Total for the whole race: **$0.39**, against $3.00 the first time.

## Scores against the blind key (9 questions)

| Model | Score | Where it fell down |
|---|---|---|
| **google/gemini-3.7-flash** (chosen) | **6 / 9** | Q02 follow-up was an acknowledgment only; Q03 turn 1 timed out; Q04 gave a general pipeline answer, not the earnings-calendar root cause |
| qwen/qwen3.7-flash | 6 / 9 | same Q02/Q04 misses, and **agreed to add tickers to a list that does not exist** — the exact failure the test set was built to catch |
| upstage/solar-pro4 | 3–4 / 9 | timed out on the three heavy investigative questions |
| openai/gpt-5.6-luna (earlier run) | 3 / 8 | two timeouts, leaked a raw tool error into a reply |
| **openai/gpt-4.1-nano (what was live)** | **0 / 9** | answered from thin air — barely opened a file |

Two models tie at 6/9. Gemini wins on the tiebreak because qwen's miss is the actively harmful kind
(offering to edit data on a false premise), and gemini is the fastest in the field (27–83s per
answer, against a ~150s live cut-off).

## A key correction found while grading

The blind answer key said Wolf's Google thesis is "bullish, forming". **That was wrong.** The live
database has no Google thesis at all — 41 thesis keys, none of them GOOG or GOOGL. Every model that
said "nothing on file for Google" was right, and the earlier grades that marked those replies as
failures were the ones in error. The key now carries this correction at Q03.

## Two prompt fixes, both justified by a real failure

1. **The stale line.** `_STEERING_TEMPLATE` told every model "options.py = options flow via
   yfinance". The feed moved to Schwab on 2026-07-02. The prompt was actively teaching the wrong
   answer to Q01. It now describes the Schwab-primary / yfinance-fallback arrangement.
2. **The false-premise rule.** After the swap, the live bot still answered "yes, give me the two
   tickers" to a question about adding to a ticker list that does not exist — twice. Added: *never
   accept a premise you have not checked; find the exact thing named in the code first, and never
   agree to extend a thing you did not find, or substitute a similarly-named one you did.*

## Live proof (real #chat, real bot, replies read back off Discord)

**Q01 — where does options flow come from?** (msg 1539166717064912917, 72s)
> Unusual options flow data is sourced primarily from the real-time **Charles Schwab API** option
> chains via `consensus_engine/scanners/options.py` (enabled under `features.schwab_options` …). If
> the Schwab real-time feed fails … falls back to delayed option chains fetched via **yfinance**.

Correct, grounded, and names the real file. The previous model got this wrong.

**Q05 — the false-premise question**, before the prompt rule (msg 1539167347460542485, 32s):
> "**Yes.** If you provide the 2 tickers, they can be added directly to the configuration …"

Wrong — and it had substituted `options_flow.fixed_core`, a different setting, for the thing asked
about. After the rule (msg 1539167931554856990, 83s):
> "**There is no static ticker list for internal signal breadth.** … **No**, because no static
> ticker list exists for signal breadth to add to. *(If you are thinking of the fixed background
> options-flow scan list, that is a separate configuration key: `options_flow.fixed_core` …)*"

Correct, and it now names the near-miss setting as a separate thing instead of quietly answering
about it. Its side note that internal breadth is `enabled: false, shadow: true` is also accurate
(`config/consensus.yaml:954`).

## Honest limits

- The harness run and the live run of Q05 disagreed before the prompt rule was added: gemini got it
  right in the harness and wrong live, twice. That is model variance on a borderline question, not a
  harness bug — which is why the prompt rule exists rather than relying on the model.
- Q04 (the earnings-calendar root cause) is still unanswered by every model raced. It needs a long
  investigation inside a ~120s budget, and no model in this price range finished it.
- The independent verifier for this item was the Gemini CLI, not Codex — Codex's account is out of
  quota until 2026-08-22. And the model now serving chat is from the same family as the verifier
  that wrote the key; the Q03 correction above was found by checking the database directly, not by
  trusting either one.
