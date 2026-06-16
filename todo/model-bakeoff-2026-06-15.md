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

---

## ROUND 2 (2026-06-16) — deeper tests + FINAL chain orders

### RESULT 2b — expanded scorer calibration (9 scenarios, 36 ordering checks each)
`calibration2.py` / `calibration2_results.json`. Intended strength rank S1>...>S9.

| Model | mis-orderings | in-band | spread | consistency | $/M out |
|---|---|---|---|---|---|
| **qwen3-235b-2507** | **0/36** | **9/9** | **70** | 2.3 | 0.10 |
| ling-2.6-flash | 1/36 | 8/9 | 67 | 4.7 | 0.03 |
| gpt-4.1-nano (prior text lead) | 1/36 | 7/9 | 50 | 0.0 | 0.40 |
| gemma-3-27b | 0/36 | 5/9 | 50 | 1.0 | 0.16 |
| mistral-nemo | 0/36 | 6/9 | 50 | 3.3 | 0.03 |

→ **qwen3-235b is the best scorer** (perfect ordering + band + widest spread) AND 4× cheaper than
gpt-4.1-nano. gpt-4.1-nano under-scored the mid range and rated a 🚀-pump above a delisting lotto.
(gpt-4.1-nano is the most deterministic — 0-pt repeat gap — kept as backup 1.)

### RESULT 3b — agent real-path MATRIX (4 models × 3 heavy questions, 150s screen)
`agent_matrix.sh` / `agent_matrix_out/`. Real `openclaw agent` path.

| Model | converged? | time | tokens/turn | answered |
|---|---|---|---|---|
| **gpt-4.1-nano** | ✅ 3/3 | **11–13s** | **2k–21k (leanest)** | 3/3 substantive |
| mistral-small-3.2-24b | ✅ 3/3 | 12–14s | 1.5k–84k | 2/3 (punted "market today") |
| qwen3-235b-2507 | ✅ 3/3 | 27–68s | 173k–687k (token hog) | 2/3 (punted AMD) |
| gpt-oss-120b (prior lead) | ❌ **0/3** | 150–178s | 233k–325k | timed out / **empty on all 3** |

→ Cost driver = TOKEN EFFICIENCY (tool-loop ballooning), not the per-word rate. **gpt-4.1-nano is
the clear winner** — fastest, leanest (so cheapest in practice despite $0.40/M), converged AND
answered every heavy question. gpt-oss-120b failed 5/5 heavy questions across both rounds → dropped.

## FINAL ORDERS SET (live 2026-06-16, engine restarted, sync verified, real `!ask` confirmed on gpt-4.1-nano)
- **text** (scorer + `!all` cleanup): `qwen3-235b-2507` → `gpt-4.1-nano` → `mistral-nemo` → `openrouter/free`
- **agent** (`@`/`!ask`): `gpt-4.1-nano` → `mistral-small-3.2-24b` → `qwen3-235b-2507` → `gpt-oss-120b:free`
- **primary** (brief/`!all` writeup/research): UNCHANGED (`gpt-oss-120b` → `qwen3-235b` → `deepseek-v4-flash` → `openrouter/free`) — re-test if heavy `!all` writeups ever time out (gpt-oss-120b's tool-loop issue is agent-path-specific; primary synthesis doesn't loop tools).

## CHANGES MADE
- text backup gemini→qwen3-235b (Round 1), then text LEAD gpt-4.1-nano→qwen3-235b + agent LEAD
  gpt-oss-120b→gpt-4.1-nano + agent fallbacks reordered (Round 2). `config/consensus.yaml` +
  `tests/integration/test_all_command_chain_order.py` updated; agent chain synced to openclaw.json
  via `scripts/sync_gateway_models.py`. 54 chain/sync/health/llm tests green.

## OPEN / NEXT (reference this file)
1. **Investigate the agent tool-loop context blow-up** (gpt-oss-120b 233–325k, qwen3-235b 173–687k
   tokens on heavy questions) — likely a tool-result-size / loop-termination issue independent of
   model. Worth a separate look; lean models (gpt-4.1-nano) sidestep it.
2. **Soak the new orders** ~1 week; watch for any text-scorer drift (qwen 2.3-pt run-to-run variance
   vs nano's 0) or agent regressions, then this item closes.
3. If adding **more than 2 backups** to any chain: cheap clean text options ranked by value =
   mistral-nemo ($0.03) > ling-2.6-flash ($0.03) > qwen3-235b ($0.10) > gemma-3-27b ($0.16).
   For the agent chain, prioritize TOKEN-EFFICIENT models (gpt-4.1-nano, mistral-small) over
   token-hogs (qwen3-235b, gpt-oss-120b) — efficiency drives both cost and timeout-avoidance.
