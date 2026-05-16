# 5-model LLM chain re-selection — 2026-05-16

Resolves [TODO #7](../../../TODO.md#7-decide-what-to-do-with-broken-all-slots-in-the-5-model-llm-chain) via Option B (re-test candidates, replace bad slots).

## Methodology

3-phase probe of 10 candidate free OpenRouter models against the `!all` synthesis profile (see `probe_llm_chain.py`):

1. **Liveness** — 50-token "PONG" prompt, 15s timeout. Filters dead/429.
2. **Synthesis** — single call mirroring `narrator._invoke_synthesis` (max_tokens=8000, temperature=0.35, 50s timeout). Realistic AMD fixture with COMPUTED SIGNAL, news/twitter/youtube/technical/earnings blocks. Quality scored against 12-check rubric (required sections, cited prices/YoY, no reasoning leakage, etc.).
3. **Parallel load** — 3 concurrent synthesis calls per model. Replicates the `!all` gather + gap_fill + synthesize overlap that broke slots 2/3/4 of the prior chain.

## Ruled out from candidate set

**Confirmed-bad (from prior testing — not re-tested):**
- `deepseek/deepseek-v4-flash:free` — 49s heavy-prompt latency > 30s timeout
- `arcee-ai/trinity-large-thinking:free` — thinking-model burns max_tokens on `.reasoning`, empty `.content` ~50%
- `baidu/cobuddy:free` — `TimeoutError` under `!all` parallel load
- `nvidia/nemotron-3-super-120b-a12b:free` — dumps planning into `.content`
- `minimax/minimax-m2.5:free` — 84s pause, ignores max_tokens
- `inclusionai/ring-2.6-1t:free` — Novita provider returns errors
- `openrouter/auto` — server-side router; bypasses manual ordering

**Off-target (skipped):** coding-specialized (`qwen3-coder`, `poolside/*`), audio (`lyria-*`), too-small (`liquid/lfm-2.5-1.2b-*`, `llama-3.2-3b`, `nemotron-nano-9b`), vision-only (`nemotron-nano-12b-vl`), uncensored (`dolphin-mistral-venice`), meta-routers (`owl-alpha`, `free`).

## Phase 1 — liveness

6/10 alive. 4 still 429 with "Provider returned error".

| Model | Status | Latency |
|---|---|---|
| openai/gpt-oss-120b:free | ✓ 200 | 1.0s |
| z-ai/glm-4.5-air:free | ✓ 200 | 3.2s |
| google/gemma-4-26b-a4b-it:free | ✓ 200 | 0.7s |
| openai/gpt-oss-20b:free | ✓ 200 | 0.7s |
| nvidia/nemotron-3-nano-30b-a3b:free | ✓ 200 | 0.5s |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | ✓ 200 | 0.5s |
| meta-llama/llama-3.3-70b-instruct:free | ✗ 429 | — |
| qwen/qwen3-next-80b-a3b-instruct:free | ✗ 429 | — |
| nousresearch/hermes-3-llama-3.1-405b:free | ✗ 429 | — |
| google/gemma-4-31b-it:free | ✗ 429 | — |

## Phase 2 — single synthesis call

All 6 live models produce legitimate financial narratives (≥11/12 quality, 1338-2404 chars):

| Model | Latency | Chars | Quality | Misses |
|---|---|---|---|---|
| openai/gpt-oss-20b:free | 1.0s | 2055 | **12/12** | — |
| z-ai/glm-4.5-air:free | 2.6s | 1735 | **12/12** | — |
| google/gemma-4-26b-a4b-it:free | 1.2s | 1498 | **12/12** | — |
| openai/gpt-oss-120b:free | 1.3s | 2404 | 11/12 | cites_yoy |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 0.5s | 1799 | 11/12 | cites_yoy |
| nvidia/nemotron-3-nano-30b-a3b:free | 0.5s | 1338 | 11/12 | cites_revenue |

## Phase 3 — 3x concurrent synthesis (the critical test)

This is the test that broke deepseek/trinity/cobuddy in the prior session and is what determines `!all` viability:

| Model | Single | Parallel 3x | Verdict |
|---|---|---|---|
| openai/gpt-oss-120b:free | 1.3s | **3/3 in 28s** | ✓ rock-solid |
| openai/gpt-oss-20b:free | 1.0s | **3/3 in 37s** | ✓ rock-solid |
| nvidia/nemotron-3-nano-30b-a3b:free | 0.5s | **3/3 in 28s** | ✓ fastest |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | 0.5s | **3/3 in 24s** | ✓ fastest |
| z-ai/glm-4.5-air:free | 2.6s | **1/3 in 50s** (2 TimeoutErrors) | ⚠ degrades under load |
| google/gemma-4-26b-a4b-it:free | 1.2s | **0/3** ("temporarily rate-limited upstream") | ✗ unsafe |

## Recommended 5-model chain

In `config/consensus.yaml` `llm.model` + `llm.fallback_models` (and `text_*` mirror):

| idx | Model | Why |
|---|---|---|
| 0 | `openai/gpt-oss-120b:free` | Proven primary; 3/3 parallel; current chain unchanged at top |
| 1 | `openai/gpt-oss-20b:free` | Fresh; 12/12 quality; 3/3 parallel; same family ⇒ consistent narrative style |
| 2 | `nvidia/nemotron-3-nano-30b-a3b:free` | FASTEST (0.5s); 3/3 parallel; different provider (failure decorrelation) |
| 3 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Fast (0.5s); 3/3 parallel; reasoning capable |
| 4 | `z-ai/glm-4.5-air:free` | 12/12 quality but parallel-weak; last-resort high-quality fallback when first 4 burn |

**Swaps made vs. prior chain:**
- Kept: `openai/gpt-oss-120b:free` (slot 0), `z-ai/glm-4.5-air:free` (was slot 1 → demoted to slot 4 since parallel-weak)
- **Removed**: `deepseek/deepseek-v4-flash:free`, `arcee-ai/trinity-large-thinking:free`, `baidu/cobuddy:free`
- **Added**: `openai/gpt-oss-20b:free`, `nvidia/nemotron-3-nano-30b-a3b:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`

**Not chosen** despite passing some tests:
- `google/gemma-4-26b-a4b-it:free` — single-call 12/12 but 0/3 parallel ("temporarily rate-limited upstream"). Unsafe under any meaningful load.

## Artifacts

- `phase1-20260516-011043.json` — liveness raw
- `phase2-20260516-011043.json` — full synthesis content per model
- `phase3-20260516-011043.json` — parallel batch results
- `ranking-20260516-011043.json` — consolidated ranking
- `probe_llm_chain.py` — reproducible test script
