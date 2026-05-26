# Restore 5-model roulette for `!ask` and `@-mention` paths

**Status:** DONE 2026-05-20.

Resolved. The premise was wrong: openclaw.json's `openrouter/auto` `params.models` array is **dead config** — openclaw drops a bare `params.models` key (verified in the openclaw 2026.5.18 bundle: not sent to OpenRouter, not iterated client-side). The "gateway 5-model roulette" the earlier writeup assumed never existed; `!ask`/`@-mention` ran on a 2-deep `agents.defaults.model` = `glm-4.5-air → openrouter/auto`.

openclaw's real failover engine (`runWithModelFallback`) walks `agents.defaults.model.{primary,fallbacks}` and already classifies errors (429/5xx/timeout vs fatal) and detects empty content — so the fix was config, not a Python reimplementation:

- `consensus.yaml` `llm.agent_model` + `llm.agent_fallback_models` — verified agent chain `glm-4.5-air → nemotron-3-nano-30b → openrouter/auto`, kept SEPARATE from the `!all` chain (the `main` agent's ~6-8K-token prompt overflows gpt-oss-120b's free tier; the path sends `tool_choice`, which nemotron-omni-reasoning 404s on).
- `sync_gateway_models.py` + `health.py` drift check repointed off the dead `params.models` onto the real `agents.defaults.model.{primary,fallbacks}`.
- `_handle_mention` `--timeout` 120→240s, retry 3→2 (the roulette is openclaw's job within one invocation; the Python loop is only a subprocess-level net).
- `make sync-models` now runs as `openclaw`, not root (see `sync-gateway-models-ownership.md`).

**Verified:** forced-failure probe (bad primary → openclaw failed over, replied), live `!ask` → "391", live `@-mention` → "pong", clean boot drift check.
