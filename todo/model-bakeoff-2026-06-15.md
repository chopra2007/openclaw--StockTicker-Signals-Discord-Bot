# AI model bake-offs — master reference (what we picked, how to re-run one)

**Status:** Round 4 deployed, live-checked, and extended to six requested models 2026-10-05
**Created:** 2026-06-04

**This is the one file to open when you want to re-compare AI models for the bot.**
It now holds four bake-offs. Old TODO items **#24** (first re-test,
2026-06-04) and **#85** (question-answering model, 2026-08-18) are folded in here —
their own detail files are kept only for history and point back to this one.

Raw data + re-runnable harnesses for each round live under `.omc/research/`:
`model-bakeoff-2026-06-04/`, `model-bakeoff-2026-06-15/`, and the #85 evidence at
`.omx/evidence/todo-85/`. Round 4 uses `scripts/model_bakeoff_2026_10.py`; its
private raw responses are ignored under `.omc/research/model-bakeoff-2026-10-04/`.

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

## Round 4 — 2026-10-04 — recent cheap/free models across every role

**Before any paid call, the owner was told the estimated total was ~$0.80;
the hard cap was $5.** Candidate calls used the real OpenRouter model catalog,
response-level `usage.cost`, short screens, and capped follow-up runs. The
key-level daily spend counter lagged behind actual billed responses, so the
response-level costs below are the accounting source. Pre-deployment model
race: **$0.22755 direct OpenRouter + $0.35627 real OpenClaw agent = $0.58382**.
The six-model parallel follow-up below added **$0.03109** in response-billed
calls, making the measured research subtotal **$0.61491**.
The later live checks use the running bot and do not expose response-level bill
records. Allowing **up to $0.30** for those checks gives a conservative
**under-$0.92 round estimate**. This is not an exact billed total; the account's
daily meter also includes ordinary bot traffic. The estimate remains below
the roughly $1 target and $5 ceiling.

The discovery window was **2026-08-04 through 2026-10-04**. The catalog's
`created` field identified recent OpenRouter listings; it is not proof of a
model's original release date. We screened general text/tool/image models
that fit the bot's context and low-cost workload, then included the current
leads as controls. Translation-only, code-only, routers, batch-only, and
high-cost variants were not useful for these synchronous Discord paths.

To recheck one candidate on the Windows control host, use
`python scripts/model_bakeoff_2026_10.py --phase screen --models MODEL_ID
--max-spend 0.05 --total-cap 1.00 --tag UNIQUE_NAME`. Results go into ignored
`.omc/research/model-bakeoff-2026-10-04/`; each tag must be new. The script
reads the OpenRouter key through the configured Hetzner SSH alias. The
`calibrate` phase needs the earlier ignored frozen scorer scenarios; the
`wolf` and `vision` phases need the private saved fixtures. The agent race
used the existing #85 real-path harness and has its own separate bill ledger.

### Short screen: scoring, five-second `!all` cleanup, and writing

These are **single-call screens**, not full `!all` verdicts. Strong/weak
scores should land in 80–100/0–29. `200 empty` means the model returned HTTP
200 but no usable answer. Pricing is USD per million input/output tokens from
the live OpenRouter catalog on 2026-10-04. Times are observed wall time, not
provider guarantees. The actual full `!all` command is checked after deploy.

| Model | $/M in/out | Strong/weak | Cleanup | Write-up screen |
|---|---:|---:|---:|---:|
| `inclusionai/ling-3.1-flash` | 0/0 | 429 | 429 | 429 |
| `apodex/apodex-1.1-mini:free` | 0/0 | empty | empty | empty |
| `upstage/solar-mini4` | .050/.200 | 85/25 | 1.5s | 4.9s |
| `openai/gpt-6-luna` | .100/.500 | 74/12 | 1.6s | 2.8s |
| `xiaomi/mimo-v2.6-flash` | .140/.280 | 88/8 | 6.0s | 16.7s |
| `inclusionai/ling-3.0-flash-vl` | .021/.062 | 93/12 | 1.3s | 3.2s |
| `inception/mercury-2.5` | .040/.150 | empty | empty | empty |
| `nex-agi/nex-n2.5-pro` | .075/.250 | 94/5 | 4.5s | 18.2s |
| `meta/muse-spark-1.3-contributor` | .100/.200 | 403 | 403 | 403 |
| `inclusionai/ling-3.0-flash-fin` | .042/.123 | 93/empty | empty | empty |
| `qwen/qwen3.8-flash` | .150/.470 | 92/5 | 4.6s | 11.2s |
| `z-ai/glm-5.3-flash` | .150/.500 | 92/10 | 14.6s | empty |
| `nvidia/nemotron-3.5-lightning` | .060/.160 | empty/25 | empty | empty |
| `qwen/qwen3.8-27b:free` | 0/0 | 429 | 429 | 429 |
| `nvidia/nemotron-3.5-lightning:free` | 0/0 | invalid long answer | invalid long answer | invalid long answer |
| `openai/gpt-oss-120b` (control) | .037/.170 | 88/15 | 3.9s | 2.4s |
| `qwen/qwen3-235b-a22b-2507` (control) | .0875/.350 | 85/25 | 1.1s | 5.1s |
| `google/gemini-3.7-flash` (control) | .750/3.750 | 94/10 | 4.8s | 5.8s |
| `google/gemini-2.5-flash-lite` (control) | .100/.400 | 85/15 | 0.7s | 1.7s |
| `google/gemini-3.8-flash` | .750/3.750 | invalid/10 | 4.4s | 5.8s |
| `openai/gpt-6-luna-pro` | .100/.500 | 82/12 | 5.1s | 6.4s |
| `deepseek/deepseek-v4.1-flash` | .300/1.200 | 88/12 | 0.7s | empty |
| `xiaomi/mimo-v2.6-pro` | .435/.870 | 88/8 | timeout | 30.1s |
| `qwen/qwen3.8-omni-flash` | .150/.470 | 91/8 | 3.5s | 7.2s |
| `bytedance-seed/seed-2-1-turbo` | .500/2.500 | empty/15 | empty | empty |

**Tweet scoring winner stays Qwen 3-235B.** On the frozen nine-case scorer
set it had **9/9 scores in the prescribed bands, zero ranking inversions,
1-point average repeat difference, 1.7s median**. Solar Mini 4 was cheaper
but 6/9 in band; Ling 3.0 VL was 6/9 with three inversions; DeepSeek V4.1
Flash was 6/9 with one inversion and variable 1–15s latency. The live text
chain stays in place. GPT-OSS 120B stays the primary writer: its 2.4s clean
screen was cheaper and faster than the plausible new Solar Mini 4. Groq-led
`!all` synthesis keeps its existing chain because this short screen did not
establish a better full-command replacement.

### Real `!ask` / mentions route

The candidate agent runs used the production `openclaw agent --local` route,
the bot's steering prompt, and TODO #85's saved owner-question set. This is
the same model route used by `!ask` and mentions, with Discord sending omitted
during the race. A temporary model allow-list was restored afterward and the
gateway model chain still matched YAML. The current OpenClaw version did not
leave the session transcript where the old tool-audit script expects it, so
**file-read counts were not verifiable this round**; factual answers were
graded against the saved key and current code. Cost below is from each run's
provider-billed usage, not the delayed account counter.

| Model | False-premise breadth Q05 | Time / cost | Multi-turn options Q02 |
|---|---|---:|---|
| `gemini-3.7-flash` (current) | Correctly rejects nonexistent list | 18s / $0.0509 | Correct source; follow-up only acknowledged, 27s / $0.0749 |
| `gemini-3.8-flash` | Correctly rejects nonexistent list | 88s / $0.1106 | Correct source; follow-up only acknowledged, 32s / $0.0608 |
| `gpt-6-luna-pro` | Offers to edit a different basket | 91s / $0.0336 | Screened out |
| `qwen3.8-flash` | Offers to edit the separate options basket | 105s / $0.0088 | Screened out |
| `solar-mini4` | Timed out | 125s / $0.0128 | Screened out |

Solar Mini 4 also answered the simpler expected-move Q06 correctly, but took
68s and added unneeded claims. **Keep Gemini 3.7** for `!ask` and mentions:
3.8 did not fix the known follow-up miss or add accuracy on the two tested
questions, and it cost more on the discriminating false-premise case. The
previous nine-question result (6/9 for Gemini 3.7) remains the broader control.

### Wolf email extraction and both vision paths

Wolf text used **five saved real newsletter emails** from
`tests/fixtures/wolf_eval/` with the production extraction prompt and 4,096
output-token cap. The hard checks were IGV bear on the two specified emails,
no labeled recap-ticker false theses, valid JSON, and quotes found verbatim in
the same email. The private email text and raw responses stay ignored locally.

| Model | Valid | IGV bear | Recap false theses | Source-backed quotes | Observed time |
|---|---:|---:|---:|---:|---:|
| `gemini-3.8-flash` | 5/5 | 2/2 | 0 | 29/29 | 12–23s |
| `gemini-3.7-flash` | 5/5 | 2/2 | 0 | 33/35 | 10–15s |
| `solar-mini4` | 5/5 | 2/2 | 0 | Many unsupported; 82 theses vs lead's 29 | 9–43s |
| `gemini-2.5-flash-lite` | 5/5 | 2/2 | 3 | Several unsupported | 3–6s |
| `mistral-small-3.2-24b` | 5/5 | 2/2 | 4 | Mostly supported | 23–55s |
| `gpt-oss-120b` (old lead) | 1/2 | 0/2 | 0 in completed call | Incomplete on first; wrong IGV bull on second | 21–85s |

**Wolf extraction changes to Gemini 3.8 → Gemini 3.7**, then retains the
old OpenAI/DeepSeek/free emergency chain for cross-provider outages. The
first two are the only models that cleared the five-email gate. The older
emergency entries are fallback availability, not verified equal quality.
At current prices the lead's five full emails billed **$0.07049** in total,
about 1.4 cents per email.

Vision used two **real saved Wolf charts** (CAT daily and URA five-minute)
plus the general `models/vision_model.py` prompt on CAT. The first image probe
wrongly disabled reasoning; it is excluded from the decision. The corrected
replay sent the same request shape as the bot. Wolf's existing paid
`gemini-2.5-flash-lite` returned usable JSON on both charts in 2–3s, so its
chain stays. For general vision, the free `gemma-4-31b-it:free` lead returned
**429 on all three calls**. The same paid Gemma returned valid JSON on all
three in 3–5s at **$0.09/$0.34 per million input/output tokens**. General
vision changes to paid Gemma → Gemini 2.5 Flash Lite → free Gemma last.
Some chart details were imperfect (for example, Gemini Lite called the URA
five-minute chart daily); those errors limit what the benchmark proves.

### Rate limits and selection rule

OpenRouter's published free tier has **50 requests/day**; its own low-cost
guide states **20 requests/minute** and 1,000 free-model requests/day after
$10 in credits. Paid models pass through the selected provider's limits, so
no single published RPM covers every OpenRouter model. In this run Ling 3.1
Flash and free Qwen 3.8 27B returned upstream **429**; Muse Spark 1.3 returned
**403** requiring account attestation; several HTTP 200s had empty content.
These were counted as failures. The bot's Groq-led `!all` lead is a separate
account: Groq publishes GPT-OSS 120B at **$0.15/$0.60 per million** and its
base free limits at **30 RPM, 1,000 requests/day, 8,000 tokens/minute**;
account-specific limits may differ. Model price/context came from the
[OpenRouter model catalog](https://openrouter.ai/docs/api/api-reference/models/get-models),
free-tier limits from [OpenRouter pricing](https://openrouter.ai/pricing/) and
its [cost guide](https://openrouter.ai/blog/tutorials/how-to-get-the-lowest-cost-llm-inference-on-openrouter/),
and Groq limits/pricing from [Groq limits](https://console.groq.com/docs/rate-limits)
and [GPT-OSS 120B card](https://console.groq.com/docs/model/openai/gpt-oss-120b).

### Six-model parallel follow-up — 2026-10-05

The owner asked specifically about these six IDs. DeepSeek V4.1, GLM 5.3,
Mimo V2.6, and Qwen 3.8 already had the short screen above; free Nemotron
Ultra and DeepSeek V4 Flash 0731 were new to this round. Three independent
agents ran all six concurrently through the same four short prompts, the
frozen scorer set (nine cases plus three repeats), one difficult full Wolf
IGV newsletter, and the CAT/URA chart prompts where the catalog listed image
input. Each group had an $0.08 response-billed limit; combined cost was
**$0.03109**, well under the $0.45 added-cost estimate stated before testing.
Raw results remain in ignored `*-deepseek-pair*.jsonl`,
`*-glm-nemotron*.jsonl`, and `*-mimo-qwen*.jsonl` files under
`.omc/research/model-bakeoff-2026-10-04/`. Prices are current catalog USD
per million input/output tokens. Times are median wall time over all calls
for that model, under concurrent traffic.

| Exact model ID | $/M in/out | Visible answers | Median | Scorer in band, first 9 | Wolf IGV | Vision JSON |
|---|---:|---:|---:|---:|---|---|
| `deepseek/deepseek-v4.1-flash` | .30/1.20 | 15/20 | 2.90s | 7/9 | Empty | 0/3 |
| `deepseek/deepseek-v4-flash-0731` | .0152/1.28 | 16/17 | 8.83s | 7/9 | Empty | Text only |
| `z-ai/glm-5.3-flash` | .15/.50 | 18/20 | 17.7s | 5/9 | Empty | 2/3 |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 0/0 | 13/17 | 14.69s | 4/9 | Truncated, non-JSON | Text only |
| `xiaomi/mimo-v2.6-flash` | .14/.28 | 18/20 | 5.50s | 6/9 | Empty | 2/3 |
| `qwen/qwen3.8-flash` | .15/.47 | 17/20 | 5.35s | 5/9 | Empty | 1/3 |

All 114 attempted calls returned HTTP 200, so this parallel sample showed
no provider 429. **HTTP 200 did not mean a usable answer:** the Wolf calls
used their 4,096-token allowance on reasoning and ended before producing
the required JSON (Nemotron emitted unfinished prose). The image-capable
models also left some charts unread; a parsed JSON answer alone does not
establish correct chart direction. The existing Qwen 3-235B scorer was
**9/9** on these same frozen bands, and the new Wolf leads passed all five
saved emails. None of these six justifies changing a deployed chain. No
extra OpenClaw agent or Discord run was needed after these role-specific
failures.

### Live deployment and proof — 2026-10-05

Deployed only `config/consensus.yaml` and a corrected Wolf extraction comment
to the live checkout, then restarted `consensus-engine.service`. The unrelated
pre-existing edit in `consensus_engine/alerts/commands.py` was preserved.
Both services were active afterward; the `/root/.openclaw` link resolved to
`/home/openclaw/.openclaw`; the recent log had no gateway drift or LLM health
failure; `sync_gateway_models.py --check` reported the unchanged Gemini 3.7
agent chain in sync. The live checks used the configured production code paths:

| Path | Live result |
|---|---|
| Tweet scoring | `score_confidence` on a stored Twitter signal returned a parsed 35/100 score and reasoning in 5.7s. The price/speed/ordering choice rests on the frozen nine-case scorer set above. |
| Wolf text | `_extract_theses_llm` on the saved difficult newsletter returned seven theses including **IGV bear**, in 17.5s. |
| General chart vision | `analyze_image` on the saved CAT chart returned the full parsed schema, including ticker, direction and confidence, in 22.1s. The 3–5s figure above is the direct model probe; the full path took longer. |
| Wolf chart vision | `_call_vision_image` on that chart returned parsed instrument `CAT` in 2.7s. |
| `!all CAT` | Actual Discord command posted a **Full Analysis** card. Log: `narrative_status=ok`, 15 sources surfaced, zero source failures, 2,277 narrative characters, 21.6s synthesis; full run 56.8s. |
| `!all PLAB` | A second live card posted with `narrative_status=ok`, 11 sources surfaced, zero source failures, and 1,793 narrative characters; synthesis took 68.2s. |
| `!ask` | Actual Discord question about `!all` received a relevant one-sentence answer in 27.2s. |
| Bot mention | The same question sent as an @mention received a relevant separate answer in 18.5s. |

Both full `!all` prompts exceeded Groq's 8,000-token-per-minute request
budget once the 4,000-token output reserve was included, so the existing
router dropped Groq and used its OpenRouter fallback. This confirms that the
fallback path works; it does **not** prove Groq lead latency for today's large
`!all` payloads. A tiny ticker was rejected by the normal market-size gate,
so it did not exercise a model.

Focused tests for LLM fallback, general vision, Wolf vision, Wolf macro and
verifier, narrator prompt and Groq pruning, and `!all` chain order:
**163 passed** on the live Linux host. The full-project
regression run as root reported **4,464 passed, 122 skipped, 2 deselected,
3 failed**. The same three failures appeared before deployment. They were all
`tests/test_full_chain_storage.py` cases writing fixed `/tmp/m02*.json` paths
owned by `openclaw`; the server's `fs.protected_regular=2` denied root's
overwrite in the sticky directory. Rerunning those exact three tests as the
file owner (`openclaw`) gave **3 passed**. No model-path test failed. This is
a test-user mismatch, not an AI-model result.

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

The `!all` synthesis chain (`all_command_chain`, Groq-led) and Wolf newsletter
`extraction_models` are separate slots with their own requirements. Round 4
screened and live-checked both.

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

## Previous live chains (config/consensus.yaml, as of 2026-09-01)

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
