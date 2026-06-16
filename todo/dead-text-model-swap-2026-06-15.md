# Replace the retired backup AI model in the text chain

**Status:** DONE 2026-06-15
**Created:** 2026-06-15

## What this was
The daily LLM health check flagged `nvidia/nemotron-nano-9b-v2` (the second
backup in the "text" model chain — the cheap/fast models that pull tickers out
of messages) as ❌ HTTP 404 "No endpoints found". OpenRouter retired the model.

## What was done
- Confirmed it's gone from OpenRouter's live list (337 models, not present).
- Swapped it for `google/gemini-2.5-flash-lite` in `config/consensus.yaml`
  (`llm.text_fallback_models`, line ~268). Chosen because it is: live, cheap
  ($0.40/M out), a non-reasoning "lite" model (so it won't return blank text on
  tight token budgets — the exact bug that got the NVIDIA one demoted), 65k
  completion cap (clears the 8k `llm.max_tokens` floor — `nova-lite` 5120 and
  `command-r` 4000 would not), and from a different provider (Google) than the
  text primary (OpenAI `gpt-4.1-nano`) and fallback 1 (Mistral `mistral-nemo`).
- Live tight-budget test (max_tokens=512): finish_reason=stop, non-empty, clean
  JSON — no empty-content failure.
- Restarted `consensus-engine.service` so it loads the new chain (config is
  cached at startup). New boot verified: both services active, Discord READY
  (20:01:08), boot drift check "gateway chain matches consensus.yaml", bot
  replied to a live @-mention.
- Live `run_chain_check()`: all 15 models across LLM/TEXT/ALL/GATEWAY chains ✅,
  no drift, no config error.

Commit: `7a00ba1`.

## Soak / follow-up
- Watch the next daily health check (the ❌ should be gone). Nothing else open.
- It's a fallback-of-a-fallback, so it only ever gets used if the text primary
  and fallback 1 both fail — low blast radius.
