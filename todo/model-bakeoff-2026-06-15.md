# Model bake-off — text / primary / agent chains (2026-06-15)

**Status:** DONE 2026-06-15
**Created:** 2026-06-15

Reference file for future model decisions. If you want to change a chain model, add
backups, or re-check whether the current pick is still best, start here. Raw data +
re-runnable harnesses live in `.omc/research/model-bakeoff-2026-06-15/`:
`harness.py` (3-chain), `calibration.py` (scorer calibration), `agent_realpath*.sh`
(real `openclaw agent` path), `results.json`, `calibration_results.json`.

**Total OpenRouter spend for the whole exercise: ~$0.05** (cheap proxy harness; the
only non-trivial cost was the heavy real-path NVDA runs).

---

## The three chains (what each does)

| Chain | Fires when | Current order (2026-06-15) |
|---|---|---|
| **text** | every tweet-score + `!all` alert cleanup | gpt-4.1-nano → mistral-nemo → **qwen3-235b-2507** *(was gemini-2.5-flash-lite)* → openrouter/free |
| **primary** | morning brief, `!all` writeup, research | gpt-oss-120b → qwen3-235b-2507 → deepseek-v4-flash → openrouter/free |
| **agent** | `@`-mention / `!ask` (answers user questions) | gpt-oss-120b → gpt-4.1-nano → qwen3-235b-2507 → gpt-oss-120b:free |

`$/M out` below = cost per million output words, live from OpenRouter on 2026-06-15.
`:nitro` is a routing preference, not a model id — nothing separate to test.

---

## METHOD

Shared harness, identical prompts per use case (fair), small token caps (cheap), then
an adversarial verify pass re-checked every verdict against the raw API output. The
decisive text test is the one that killed the old free Nemotrons: a tight 512-token /
5-second cleanup call where "think-out-loud" models return blank.

---

## RESULT 1 — 3-chain screen (8 models each, vs incumbents ★)

**Headline: every candidate passed.** The cheap-model field has caught up — none of the
reasoning-leak / tooling / cap failures that used to disqualify models appeared. So the
differentiator is now **cost + provider diversity**, not pass/fail.

### TEXT (decider: clean tight-512 + 3/3 reliability + 8k scorer floor)
| Model | $/M out | tight-512 | reliability | verdict |
|---|---|---|---|---|
| ★ gpt-4.1-nano | 0.40 | clean | 3/3 | fit (incumbent) |
| ★ gemini-2.5-flash-lite | 0.40 | clean | 3/3 | fit (incumbent, priciest) |
| ★ mistral-nemo | 0.03 | clean | 3/3 | fit (incumbent) |
| qwen3-235b-2507 | **0.10** | clean | 3/3 | fit — beats gemini |
| gemma-3-27b | 0.16 | clean | 3/3 | fit — beats gemini |
| mistral-small-3.2-24b | 0.20 | clean | 3/3 | fit — beats gemini |
| qwen3-30b-a3b-instruct | 0.19 | clean | 3/3 | fit — beats gemini |
| ling-2.6-flash | 0.03 | clean | 3/3 | fit — beats gemini |

→ gemini-2.5-flash-lite works but is the **most expensive** option that passed. Six cheaper
models passed identically. **Best value = qwen3-235b-2507** (4× cheaper, +Alibaba diversity).

### PRIMARY (financial-writing quality + reliability)
All 8 "fit", quality "strong/high". gemma-3-27b + qwen3-30b TIED the lead; none clearly beat
gpt-oss-120b. Cheapest-strong (qwen3-235b, $0.10) is already #2. → **Keep as-is.**

### AGENT (tools + tool_choice + big context) — CHEAP PROXY (~4k prompt)
All 8 accepted tools and made valid tool calls; all hold ≥128k context. But this proxy can't
prove real-path survival — see RESULT 3, which overturns it.

---

## RESULT 2 — front-line TEXT scorer CALIBRATION (does it score *sensibly*)

The text chain's first model (gpt-4.1-nano) fires on every tweet-score, so "does it work" isn't
enough — does it *rank* signals correctly? 5 scenarios tiered strongest(A)→weakest(E), scored
against the real scorer prompt's own 0-100 guideline bands.

| Model | A | B | C | D | E | ordering A>B>C>D>E | in-band | $/run |
|---|--|--|--|--|--|---|---|---|
| **gpt-4.1-nano** (current) | 92 | 78 | 42 | 45 | 25 | ❌ **BAD** (D>C) | 4/5 | 0.00034 |
| **qwen3-235b-2507** | 95 | 76 | 52 | 35 | 25 | ✅ OK | **5/5** | 0.00026 |
| gemma-3-27b | 85 | 72 | 55 | 35 | 25 | ✅ OK | 5/5 | 0.00027 |
| mistral-nemo | 85 | 75 | 55 | 45 | 35 | ✅ OK | 4/5 | 0.00006 |
| ling-2.6-flash | 88 | 72 | 45 | 30 | 20 | ✅ OK | 4/5 | 0.00004 |

→ **The current front-line model was the ONLY one to mis-order** — it scored the hype/bearish
scenario (D=45) above the mixed-but-legit one (C=42). qwen3-235b was best-calibrated (perfect
order, all 5 in band) at 1/4 the cost. **Caveat: 3-point miss on one run — could be noise.** Not
proof gpt-4.1-nano is "bad", but it's **not clearly best**. Decide a front-line swap later from
this data; would want more boundary scenarios first.

---

## RESULT 3 — AGENT real-path test (the important one)

Ran the REAL `openclaw agent --local` path (real ~18k+ prompt, live tools) per model via
`--model` override (temp allow-map entry, reverted after). 3 models × 2 questions.

| Model | Q1 "AAPL price?" | Q2 "read on NVDA?" (240s prod timeout) |
|---|---|---|
| gpt-oss-120b (incumbent) | ✅ $296.42 (52s, 100k tok) | ❌ **TIMED OUT** at 160s AND 240s (ballooned to 277k tok) |
| qwen3-30b-a3b-instruct | ✅ $296.42 (33s, 58k tok — leanest) | ❌ **TIMED OUT** both (ballooned to 976k tok) |
| **mistral-small-3.2-24b** | ✅ $295.75 (20-38s, 84k tok) | ✅ **clean answer in 25s** (84k tok) — both runs |

→ **Significant, reproducible finding:** on a heavy, tool-triggering question, the current agent
model (gpt-oss-120b) **times out even at the production 240s limit** — its tool-call loop
accumulates runaway context (277k tokens) without converging. qwen3-30b is worse (976k). Only
**mistral-small-3.2-24b converged fast** (25s) on the same question with the same tools.

This means live users asking the bot heavy questions ("read on NVDA") may currently get
"⚠️ Agent unavailable". **mistral-small-3.2-24b looks like a genuinely better agent lead.**
Caveat: n=1 heavy question (run twice, consistent). Before swapping the live agent lead, confirm
with 3-5 more heavy questions and check it reproduces under the real live config (not just the
`--model` override). The token-ballooning may also be partly a tool-result-size issue worth a
separate look.

---

## CHANGES MADE THIS SESSION
- **text chain backup: gemini-2.5-flash-lite → qwen/qwen3-235b-a22b-2507** (`config/consensus.yaml`;
  test `tests/integration/test_all_command_chain_order.py` updated; 32 chain/llm tests green).
  4× cheaper, same test results, +provider diversity.

## OPEN / NEXT (decide later, reference this file)
1. **Agent lead:** strongly consider gpt-oss-120b → mistral-small-3.2-24b after a 3-5 heavy-question
   confirmation. Current lead times out on heavy questions.
2. **Investigate the agent tool-loop context blow-up** (277k–976k tokens on one NVDA question) — may
   be a tool-result-size / loop-termination bug independent of model choice.
3. **Front-line text scorer:** gpt-4.1-nano mis-ordered one calibration case; qwen3-235b scored
   cleaner & cheaper. Re-test with more boundary scenarios before any swap.
4. If adding **more than 2 backups** to any chain: the cheap clean text options ranked by value are
   mistral-nemo ($0.03) > ling-2.6-flash ($0.03) > qwen3-235b ($0.10) > gemma-3-27b ($0.16).
