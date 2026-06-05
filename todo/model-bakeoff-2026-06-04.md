# Model bake-off — pick best primary / text / agent models (2026-06-04)

**Status:** DONE
**Created:** 2026-06-04

Goal: re-test OpenRouter models and pick the best for each LLM slot. Targets —
**Primary** (smart analysis): cheap + intelligent + reliable. **Text** (tweet
scoring): cheap + fast + reliable. **Agent** (`!ask`/@-mention): handles the big
prompt + tool calls, reliable. User cost cap: cheap-paid OK (≤ ~$1/M out), prefer
free when reliable. `openrouter/free` kept as the final fallback on primary + text
as a credit-exhaustion net.

Raw data + harness scripts: `.omc/research/model-bakeoff-2026-06-04/`
(`results.json`, `harness.py`, agent test scripts). Reproduce by re-running
`harness.py` (set OPENROUTER_API_KEY).

## What shipped (the new config)

`config/consensus.yaml` `llm:` block (consensus-engine reads these directly):

| Slot | Lead → fallbacks |
|---|---|
| **Primary** (`model`) | `openai/gpt-oss-120b` → `qwen/qwen3-235b-a22b-2507` → `deepseek/deepseek-v4-flash` → `openrouter/free` |
| **Text** (`text_model`) | `openai/gpt-4.1-nano` → `mistralai/mistral-nemo` → `nvidia/nemotron-nano-9b-v2` → `openrouter/free` |
| **Agent** (`agent_model`, synced to openclaw.json) | `openai/gpt-oss-120b` → `openai/gpt-4.1-nano` → `qwen/qwen3-235b-a22b-2507` → `openai/gpt-oss-120b:free` |

Also: removed discontinued `deepseek/deepseek-v4-flash:free` (404 on OpenRouter)
from the agent chain AND the openclaw.json `agents.defaults.models` allow-map.
The allow-map was trimmed to exactly the 4 agent-chain models.

## Test method

- Direct OpenRouter calls (`harness.py`): each model hit 5× (1 cold, 1 warm, 3
  concurrent burst). Success rule mirrors `llm_client.py`: HTTP 200 AND non-empty
  `content` (empty-from-reasoning = failure). Primary got a real NVDA analysis
  task graded 0-10; text got a tweet-scoring task. Cache defeated with per-call
  nonces so latency/reliability are real.
- Agent path (`agent_test2.sh`): each model run end-to-end through the REAL
  `openclaw agent --local --model <id>` (big ~25-50K-token prompt + live tool
  calls), graded on correctness (read the file, said "yfinance") + latency.

## Key results (full table in results.json)

**Primary** (smart, reliable, cheap), ranked: gpt-oss-120b 9.5/10 @0.3s $0.18 (WON)
> gpt-5-nano 9.0 > qwen3-235b-thinking 8.5 > qwen3-235b-2507 8.5 > minimax-m2.1 8.5
> deepseek-v4-flash 8.0 (incumbent, slow 7.6s cold) > xiaomi-mimo 8.0 > glm-4.7-flash 7.5.
Failed the "smart" bar (generic, no specifics): gemini-2.5-flash-lite 6.0,
llama-4-maverick 6.5. Reliability miss: nemotron-3-super 4/5 (one empty).

**Text** (fast, reliable, cheap): all top picks 5/5 @0.3-0.6s. FAILED: gpt-5-nano
and qwen3.5-9b returned EMPTY at 512 tokens (reasoning models burn the budget);
llama-3.2-3b:free got 429'd. gemini/ministral wrap output in ```json fences.

**Agent** (real path): gpt-oss-120b PAID 6.1s correct (WON) vs gpt-oss-120b:free
18.9s (free pool congested, 3× slower). gpt-4.1-nano 8.6s. qwen3-235b-2507 12.4s.
deepseek-v4-flash 14.8s (correct here; fabricated on a different question 2026-06-02).
FAILED: qwen3-235b-THINKING context-overflow (reasoning blew the token budget —
the token-limit factor, live), minimax-m2.1 43.9s, xiaomi-mimo HTTP 451,
gemini-2.5-flash-lite timeout.

## Your 4 named models
- **xiaomi/mimo-v2-flash** — genuinely good (8/10 primary, 5/5, cheap); not top-3.
- **minimax/minimax-m2.5** — good but $1.15/M out is over the cap; cheaper models match it.
- **owl-alpha** — works but it's a router: ~10s slow + occasional non-JSON. Last-resort only.
- **nvidia/llama-nemotron-embed-vl-1b-v2:free** — N/A: doesn't exist on OpenRouter + it's an
  embedding model (text→vectors), can't chat/score.

## Key learnings (load-bearing)
1. **Free pool is ~3× slower than paid for the same model** (gpt-oss-120b: 18.9s free vs 6.1s paid).
2. **Reasoning models leak EMPTY content at tight token budgets** — gpt-5-nano/qwen-thinking
   failed the 512-tok text + agent paths. Keep reasoning models OFF the text/agent leads.
3. **The agent prompt is ~25-50K tokens** — agent models need ≥130K context; small-context
   models overflow. This is the "token limit" factor for the ask/mention chain.
4. **nemotron-nano-9b-v2 returned empty at very low budgets** (was the original text lead;
   demoted to fallback, gpt-4.1-nano promoted — it's non-reasoning + robust at 512 tok).
5. `openclaw agent --local` has `--model` and `--thinking` overrides, but a model must be in
   openclaw.json `agents.defaults.models` allow-map or it's rejected.
6. To run openclaw CLI as the openclaw user here, set `TMPDIR=/home/openclaw/.openclaw/.octmp`
   (host /tmp is root-only 0700; services use systemd PrivateTmp).

## Files involved
- `config/consensus.yaml` (llm block: model/fallback_models/text_model/text_fallback_models/agent_model/agent_fallback_models)
- `openclaw.json` `agents.defaults.{model,models}` (agent chain + allow-map; via `scripts/sync_gateway_models.py` + `openclaw config patch`)
- `tests/integration/test_all_command_chain_order.py` (asserts the chain values — updated)
- `.omc/research/model-bakeoff-2026-06-04/` (raw data + harnesses)

## If revisited (set back to Active)
- Models change monthly — re-run `harness.py` for fresh rankings; ignore these specific picks.
- Could test `--thinking` levels to tune reasoning-model token use if one is ever wanted on the agent path.
- The `!all` synthesis chain (`all_command_chain`, groq-led) and Wolf `extraction_models` were
  NOT re-tested this round — separate slots, different requirements.
