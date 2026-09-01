# AI model bake-offs — master reference (what we picked, how to re-run one)

**Status:** DONE 2026-06-15
**Created:** 2026-06-04

**This is the one file to open when you want to re-compare AI models for the bot.**
It now holds all three bake-offs we have run. Old TODO items **#24** (first re-test,
2026-06-04) and **#85** (question-answering model, 2026-08-18) are folded in here —
their own detail files are kept only for history and point back to this one.

Raw data + re-runnable harnesses for each round live under `.omc/research/`:
`model-bakeoff-2026-06-04/`, `model-bakeoff-2026-06-15/`, and the #85 evidence at
`.omx/evidence/todo-85/`.

---

## Cost rules (owner, hard requirements)

- **Give the owner a total cost estimate BEFORE running any tests** — how much the whole
  bake-off will spend on API calls. No test run starts without that number stated first.
- **Target: about $1 total. Hard ceiling: $5.** An earlier round overshot and cost the
  owner real money. If the plan estimates over ~$1, cut scope (fewer models, fewer
  questions, cheaper screening prompts) or ask before proceeding. Never let a run pass $5.
- **Meter spend live and stop at a budget.** The harness must track its own running cost
  and cut a model off mid-run if it blows the budget (the #85 harness already does this —
  it dropped one expensive model after two questions).
- Keep costs down the proven way: screen every model on ~3 cheap prompts first, run the
  full set only on survivors, small token caps, defeat caching with nonces.
- For reference, done right the whole exercise is cheap: the 2026-06-15/16 round was
  ~$0.05 total; the 2026-08-18 question round was $0.39 (vs $3.00 the naive way).

---

## The AI jobs, and how each one must be tested

The engine has four model "slots" in `config/consensus.yaml` (`llm:` block). They fall
into two groups, and the two groups need **different test methods** — this is the most
important thing in this file.

### Group 1 — the simple one-shot jobs (cheap and safe to test)

| Slot (yaml key) | What it does | What it needs |
|---|---|---|
| **text** (`text_model`) | Scores every incoming tweet; cleans up `!all` alert text | Fast, cheap, reliable, and ranks signals in the right order (strong signal scores above weak one) |
| **primary** (`model`) | Morning brief, `!all` write-up, research | Smart financial writing, reliable under load |

Also here but **not re-tested in these rounds** (separate slots, own requirements):
the `!all` synthesis chain (`all_command_chain`, groq-led) and the Wolf newsletter
`extraction_models`.

**How to test Group 1:** one throwaway script. Send every candidate the same prompt,
grade the answer, hit each model ~5 times (1 cold, 1 warm, 3 in a burst) for
reliability, and defeat caching with a random nonce per call so latency is real. Grade
`primary` on a real analysis task (0–10). Grade `text` on a tight 512-token / 5-second
cleanup call — that is the test that catches "think-out-loud" models that return blank
when the token budget is small. Whole exercise costs about **$0.05**.
Harness: `.omc/research/model-bakeoff-2026-06-15/harness.py` (+ `calibration.py` for
scorer ordering).

### Group 2 — the question-answering bot (must be tested for real)

| Slot (yaml key) | What it does | What it needs |
|---|---|---|
| **agent** (`agent_model`) | `!ask` and `@`-mention — reads the live code with tools and answers the owner's questions in plain English | Opens the right file, understands it, explains it simply, spots a false-premise question, finishes inside the timeout without its tool loop ballooning |

**How to test Group 2:** the cheap one-shot test **lies here — proven twice.**
`gpt-oss-120b` won the cheap screen both times, then timed out on every real heavy
question ("what's your read on NVDA") because its tool-call loop piles up context
(277k+ tokens) without ever finishing. You must run the **real `openclaw agent --local`
path** with live tools and the full ~18–50k-token prompt.

The #85 method is the template:
1. Build the question set from the **owner's own past `#chat` messages**, not invented easy ones. Keep multi-turn pairs so follow-up memory is tested.
2. Have Codex independently open the current files and write a **blind answer key** first.
3. Run each question through the real `!ask` path. Grade: facts correct, right files actually read, plain English a non-coder can follow, time, and cost.
4. Screen every model on ~3 cheap questions first; only run the full set on survivors; make the harness meter its own spend and stop at a budget.
5. Pick the cheapest model that clears the quality bar. Change **only** the agent chain — leave `text`, `primary`, and `!all` alone.

---

## Current live chains (config/consensus.yaml, as of 2026-09-01)

| Chain | Order (lead → fallbacks) |
|---|---|
| **primary** (`model`) | `gpt-oss-120b` → `qwen3-235b-a22b-2507` → `deepseek-v4-flash` → `openrouter/free` |
| **text** (`text_model`) | `qwen3-235b-a22b-2507` → `gpt-4.1-nano` → `mistral-nemo` → `openrouter/free` |
| **agent** (`agent_model`) | `gemini-3.7-flash` → `qwen3.7-flash` → `solar-pro4` → `gpt-5.6-luna` |

`openrouter/free` is a random free meta-router kept as the last-resort credit-exhaustion
net on `primary`/`text` only. The `!all` synthesis chain is separate and not covered here.

---

## Round 3 — 2026-08-18 — the question-answering model (was TODO #85)

**Goal:** when the owner asks what a bot feature means, the Discord bot should read the
real code on the server and answer in plain English — including saying "that doesn't
exist" when a question assumes something that isn't there.

**Result:** agent model changed from `gpt-4.1-nano` to **`gemini-3.7-flash`**, plus two
prompt fixes. Measured on **9 real questions** from the owner's own past `#chat`,
graded against a blind answer key: old model **0 of 9** (answered from memory, barely
opened a file), new model **6 of 9**.

Two prompt problems fixed at the same time:
- The steering prompt told every model "options flow comes from yfinance." That stopped
  being true on 2026-07-02 when the feed moved to Schwab — the bot was being taught the
  wrong answer. Fixed.
- The bot used to play along with a false premise. Asked "can you add 2 more tickers to
  the list?" it said yes — there is no such list. It now checks first and says so.

**Cost control:** $0.39 this round vs $3.00 the naive way — screen on 3 cheap questions,
full set only on survivors, harness meters its own spend and cut one expensive model off
after two questions.

**Still open:** "why is it giving false signals" — unanswered by every model raced; needs
a longer investigation than the ~2-minute live budget allows.
Evidence: `.omx/evidence/todo-85/model-race-and-live-proof.md`.

Files: `consensus_engine/main.py` (`_STEERING_TEMPLATE`, mention handler),
`config/consensus.yaml` (`llm.agent_model` / `agent_fallback_models`),
`openclaw.json` (`agents.defaults.{model,models}`),
`consensus_engine/analysis/internal_breadth.py` (the example feature),
`scripts/sync_gateway_models.py`.

---

## Round 2 — 2026-06-15 / 16 — the three chains (this item, TODO #44)

Shared harness, identical prompts per use case, small token caps, then an adversarial
verify pass re-checked every verdict against the raw API output.
Total OpenRouter spend: **~$0.05**. Harnesses: `.omc/research/model-bakeoff-2026-06-15/`.

### RESULT 1 — 3-chain screen (8 models each, vs incumbents ★)

**Headline: every candidate passed.** The cheap-model field has caught up — none of the
reasoning-leak / tooling / cap failures that used to disqualify models appeared. So the
differentiator is now **cost + provider diversity**, not pass/fail.

TEXT (decider: clean tight-512 + 3/3 reliability + 8k scorer floor):

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

→ gemini-2.5-flash-lite works but is the **most expensive** option that passed. Six
cheaper models passed identically. **Best value = qwen3-235b-2507** (4× cheaper,
+Alibaba diversity).

PRIMARY (financial-writing quality + reliability): all 8 "fit", quality "strong/high".
gemma-3-27b + qwen3-30b tied the lead; none clearly beat gpt-oss-120b. → **Keep as-is.**

AGENT — cheap proxy (~4k prompt): all 8 accepted tools and made valid tool calls; all
hold ≥128k context. But this proxy can't prove real-path survival — RESULT 3 overturns it.

### RESULT 2 — front-line TEXT scorer calibration (does it rank sensibly)

5 scenarios tiered strongest(A)→weakest(E), scored against the real scorer prompt's own
0-100 guideline bands.

| Model | A | B | C | D | E | ordering A>B>C>D>E | in-band |
|---|--|--|--|--|--|---|---|
| **gpt-4.1-nano** (then-current) | 92 | 78 | 42 | 45 | 25 | ❌ **BAD** (D>C) | 4/5 |
| **qwen3-235b-2507** | 95 | 76 | 52 | 35 | 25 | ✅ OK | **5/5** |
| gemma-3-27b | 85 | 72 | 55 | 35 | 25 | ✅ OK | 5/5 |
| mistral-nemo | 85 | 75 | 55 | 45 | 35 | ✅ OK | 4/5 |
| ling-2.6-flash | 88 | 72 | 45 | 30 | 20 | ✅ OK | 4/5 |

→ The then-current front-line model was the ONLY one to mis-order — it scored the
hype/bearish scenario above the mixed-but-legit one. qwen3-235b was best-calibrated at
1/4 the cost.

### RESULT 3 — AGENT real-path test (the important one)

Real `openclaw agent --local` path (real ~18k+ prompt, live tools), 3 models × 2 questions.

| Model | Q1 "AAPL price?" | Q2 "read on NVDA?" (240s prod timeout) |
|---|---|---|
| gpt-oss-120b (incumbent) | ✅ $296.42 (52s, 100k tok) | ❌ **TIMED OUT** at 160s AND 240s (ballooned to 277k tok) |
| qwen3-30b-a3b-instruct | ✅ $296.42 (33s, 58k tok) | ❌ **TIMED OUT** both (ballooned to 976k tok) |
| **mistral-small-3.2-24b** | ✅ $295.75 (20-38s, 84k tok) | ✅ **clean answer in 25s** — both runs |

→ On a heavy, tool-triggering question the then-current agent model **timed out even at
the production 240s limit** — its tool-call loop accumulates runaway context without
converging.

### ROUND 2 follow-up (2026-06-16) — deeper tests + final orders

Expanded scorer calibration (9 scenarios, 36 ordering checks): **qwen3-235b-2507 best**
(0/36 mis-orderings, 9/9 in band, widest spread) AND 4× cheaper than gpt-4.1-nano.

Agent real-path matrix (4 models × 3 heavy questions, 150s screen):

| Model | converged? | time | tokens/turn | answered |
|---|---|---|---|---|
| **gpt-4.1-nano** | ✅ 3/3 | **11–13s** | **2k–21k (leanest)** | 3/3 substantive |
| mistral-small-3.2-24b | ✅ 3/3 | 12–14s | 1.5k–84k | 2/3 |
| qwen3-235b-2507 | ✅ 3/3 | 27–68s | 173k–687k (token hog) | 2/3 |
| gpt-oss-120b (prior lead) | ❌ **0/3** | 150–178s | 233k–325k | timed out / empty on all 3 |

→ Cost driver = **token efficiency** (tool-loop ballooning), not per-word rate.
gpt-oss-120b failed 5/5 heavy questions across both rounds → dropped from the agent chain.

**Orders set live 2026-06-16** (engine restarted, sync verified, real `!ask` confirmed):
- text: `qwen3-235b-2507` → `gpt-4.1-nano` → `mistral-nemo` → `openrouter/free`
- agent: `gpt-4.1-nano` → `mistral-small-3.2-24b` → `qwen3-235b-2507` → `gpt-oss-120b:free`
  *(agent lead later replaced by `gemini-3.7-flash` in Round 3)*
- primary: unchanged (`gpt-oss-120b` → `qwen3-235b` → `deepseek-v4-flash` → `openrouter/free`)

---

## Round 1 — 2026-06-04 — first full re-test (was TODO #24)

24 OpenRouter models tested live for speed + financial-analysis competence + reliability
under a concurrency burst. Raw data: `.omc/research/model-bakeoff-2026-06-04/`
(`results.json`, `harness.py`, agent test scripts).

**Primary**, ranked: gpt-oss-120b 9.5/10 @0.3s $0.18/M (WON) > gpt-5-nano 9.0 >
qwen3-235b-thinking 8.5 > qwen3-235b-2507 8.5 > minimax-m2.1 8.5 > deepseek-v4-flash 8.0
(incumbent, slow 7.6s cold) > xiaomi-mimo 8.0 > glm-4.7-flash 7.5. Failed the "smart"
bar: gemini-2.5-flash-lite 6.0, llama-4-maverick 6.5. Reliability miss: nemotron-3-super
4/5 (one empty).

**Text**: all top picks 5/5 @0.3–0.6s. FAILED — gpt-5-nano and qwen3.5-9b returned EMPTY
at 512 tokens (reasoning models burn the budget); llama-3.2-3b:free got 429'd;
gemini/ministral wrap output in ```json fences.

**Agent** (real path): gpt-oss-120b PAID 6.1s correct (WON) vs gpt-oss-120b:free 18.9s
(free pool congested, 3× slower). FAILED — qwen3-235b-THINKING context overflow,
minimax-m2.1 43.9s, xiaomi-mimo HTTP 451, gemini-2.5-flash-lite timeout.

Owner's named models this round: xiaomi/mimo-v2-flash (good, not top-3);
minimax/minimax-m2.5 ($1.15/M out, over cap); owl-alpha (a slow router, last-resort
only); nvidia/llama-nemotron-embed-vl-1b-v2:free (doesn't exist / is an embedding model).

---

## Key learnings that outlast the specific picks

1. **The cheap agent test lies.** A model can ace a 4k-prompt tool proxy and still time
   out on every real heavy question. Always finish with the real `openclaw agent` path.
2. **Cost driver for the agent chain = token efficiency**, not the per-word price. Lean
   models (gpt-4.1-nano, mistral-small) sidestep the tool-loop context balloon that
   kills token hogs (gpt-oss-120b, qwen3-235b) on heavy questions.
3. **Reasoning / "think-out-loud" models return EMPTY at tight token budgets** — they
   burn the budget on hidden reasoning. Keep them off the `text` and `agent` leads;
   they're fine at full budget.
4. **The free pool is ~3× slower than paid** for the same model (gpt-oss-120b: 18.9s
   free vs 6.1s paid). `openrouter/free` is a random meta-router — last resort only.
5. **The agent prompt is ~18–50k tokens** — agent models need ≥130k context or they
   overflow.
6. **"Works" isn't "ranks right."** The `text` scorer must order strong signals above
   weak ones — test calibration, not just non-empty output.
7. **An agent model must be in `openclaw.json` `agents.defaults.models`** or the
   `--model` override is rejected. `openclaw agent --local` also needs
   `TMPDIR=/home/openclaw/.openclaw/.octmp` when run as the openclaw user here.
8. **Restart the engine after a chain change** (`systemctl restart
   consensus-engine.service`) and sync the agent chain to `openclaw.json`
   (`scripts/sync_gateway_models.py`), then confirm with a real `!ask` / `!all`.

---

## If you re-run this

- **First: estimate the total API cost and tell the owner.** Target ~$1, never over $5.
  See "Cost rules" at the top of this file.
- **Models change monthly** — re-run the harness for fresh rankings; ignore the specific
  picks above, keep the method.
- Group 1 (text/primary): `.omc/research/model-bakeoff-2026-06-15/harness.py` +
  `calibration2.py`. Cheap; ~$0.05.
- Group 2 (agent): rebuild the question set from recent `#chat`, blind answer key via
  Codex, real `!ask` path, budget-metered harness. See `.omx/evidence/todo-85/`.
- Separate slots never re-tested here and worth their own round if they misbehave: the
  `!all` synthesis chain (`all_command_chain`, groq-led) and Wolf `extraction_models`.
- Related: `todo/agent-tool-loop-context-blowup.md` — the tool-loop context balloon as
  its own bug, independent of model choice.
- Tests that assert chain values: `tests/integration/test_all_command_chain_order.py`.
