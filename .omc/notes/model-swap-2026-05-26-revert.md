# Model-swap snapshot — 2026-05-26

Use this file to revert the LLM model changes made on 2026-05-26.

## Goal of the change

- **Tweetshift signal scoring** → `openrouter/free` (free meta-router)
- **!ask, @mention, morning brief** → `deepseek/deepseek-v4-flash` (paid) with
  `openrouter/free` as the single fallback
- **YouTube digest** → unchanged
- **!all command (`all_command_chain`)** → unchanged
- **Vision (`vision_model`)** → unchanged

## What this change actually touches

1. `config/consensus.yaml` — `llm:` block
2. `consensus_engine/analysis/llm_scorer.py` — switch `role="primary"` → `role="text"`
   so the tweetshift scoring chain is configurable separately from the
   morning-brief chain.
3. `openclaw.json` — `agents.defaults.model` (synced from consensus.yaml by
   `scripts/sync_gateway_models.py`)

## Previous values (revert source-of-truth)

### `config/consensus.yaml` — `llm:` block, fields being changed

```yaml
llm:
  model: "openai/gpt-oss-120b:free"
  fallback_models:
    - "openai/gpt-oss-20b:free"
    - "nvidia/nemotron-3-nano-30b-a3b:free"
    - "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    - "z-ai/glm-4.5-air:free"
  text_model: "openai/gpt-oss-120b:free"
  text_fallback_models:
    - "openai/gpt-oss-20b:free"
    - "nvidia/nemotron-3-nano-30b-a3b:free"
    - "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    - "z-ai/glm-4.5-air:free"
  agent_model: "poolside/laguna-m.1:free"
  agent_fallback_models:
    - "z-ai/glm-4.5-air:free"
    - "nvidia/nemotron-3-nano-30b-a3b:free"
    - "free"
  max_tokens: 4096
```

### `consensus_engine/analysis/llm_scorer.py:122`

```python
    content = await call_with_fallback(
        role="primary",
        messages=[...],
        ...
    )
```

### `openclaw.json` — `agents.defaults.model`

```json
{
  "primary": "openrouter/poolside/laguna-m.1:free",
  "fallbacks": [
    "openrouter/z-ai/glm-4.5-air:free",
    "openrouter/nvidia/nemotron-3-nano-30b-a3b:free",
    "openrouter/free"
  ]
}
```

## Revert procedure

1. Copy the YAML block above back into `config/consensus.yaml`.
2. In `consensus_engine/analysis/llm_scorer.py`, change `role="text"` back to
   `role="primary"`.
3. Run: `sudo -u openclaw python3 scripts/sync_gateway_models.py`
4. `sudo systemctl restart consensus-engine openclaw-gateway`
5. Verify with `python3 scripts/sync_gateway_models.py --check` — should print
   "in sync".

## Side-effects of the change worth knowing about

- `consensus_engine/research/sources.py` (Atlas research summaries) and
  `consensus_engine/analysis/video_parser.py` (YouTube OpenRouter fallback)
  also use `role="primary"`. Both now hit deepseek instead of gpt-oss-120b.
  Not user-visible directly; behavior should still be correct (deepseek-v4-flash
  is a more capable model). If anything breaks here, this is the suspect.
- DeepSeek V4 Flash paid pricing: $0.10/M input, $0.20/M output. ~$0.06–$0.12/day
  estimated for current morning-brief + !ask + @mention volume.
- `openrouter/free` is a meta-router — OpenRouter picks any free model under
  the hood. Built-in failover; rate limits apply to the free tier as a whole.
