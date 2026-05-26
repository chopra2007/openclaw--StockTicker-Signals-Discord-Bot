# OpenRouter free-tier chain reliability — all 6 models flaky

**Status:** DONE 2026-05-22.

**Layperson:** The bot's primary text-generation chain (six free OpenRouter models tried in fallback order) is failing very often during real-world tests. Many `!all` captures during the 2026-05-19 session returned `fallback_data_only` (just the structured fields, no narrative) because every model in the chain timed out or returned empty.

## Observed failure modes per model

From `iter6/iter10/iter10b/iter15-*-bot.err.txt` and the `consensus_engine.log` `fallback_data_only` log lines:

| Model | Failure mode | Frequency seen |
|---|---|---|
| `openai/gpt-oss-120b:free` | connection error / TimeoutError | almost every run |
| `openai/gpt-oss-20b:free` | HTTP 429 ("rate-limited upstream") | almost every run |
| `nvidia/nemotron-3-nano-30b-a3b:free` | returns empty content | most runs |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | returns empty content | most runs |
| `z-ai/glm-4.5-air:free` | connection error / TimeoutError | most runs |
| `nvidia/nemotron-3-super-120b-a12b:free` | connection error / TimeoutError | most runs |

Commit 11 (raise synth timeout cap 50s → 90s) helped the primary finish more often. But the secondaries are genuinely flaky — when the primary doesn't complete in 90s, the fallbacks rarely do either.

**Aggregator-level fallout:** even 2026-05-18 production traffic (before any of the session's work) shows `narrative_status=fallback_data_only` runs (e.g. log line at 15:19 for NVDA). Not a regression; a chronic free-tier-degradation pattern.

## Fix options (ranked)

1. **Add `GROQ_API_KEY` to the chain.** The key exists in `/home/openclaw/.openclaw/.env` but isn't wired into the chain (verified: `consensus_engine/llm_client.py` doesn't import it). Groq Llama-3.3-70B-versatile responded with 200 in ~1s in a smoke test this session — far more reliable than free-tier OpenRouter. Free tier is ~30 req/min, plenty for `!all` cadence. Estimated effort: 30-60 min to add a Groq provider class and slot it in before the OpenRouter chain.
2. **Switch primary to a paid OpenRouter model.** `openai/gpt-4o-mini` or `anthropic/claude-3-5-haiku` at ~$0.50/M tokens means ~$10/mo at current call volume. Far more reliable than the free chain.
3. **Reorder the chain** so `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` (the one that returns empty content fastest) is removed entirely. It's making the chain look slower than it is.

**Files to touch:** `consensus_engine/llm_client.py` (chain definition + provider class), `config/consensus.yaml` (which models are in the `primary` / `text` roles), `.env` (Groq key already present).
