# Auto-switch web-search keys when one runs out

**Status:** OPEN
**Created:** 2026-06-01

## The goal (plain English)

The bot pays for web searches through SerpAPI, and we have **three keys**. Right now the bot is hard-wired to use **one** key. When that key runs out of searches for the month, the bot's web search just silently returns nothing — even though the other two keys still have credit sitting unused. We want the bot to automatically switch to the next key with credit instead of going dark.

## What happened that surfaced this (2026-05-31)

- `config/consensus.yaml` pointed `api_keys.serpapi` at `$SERPAPI3_API_KEY` (key 3). Key 3 was **exhausted** (HTTP 429, "Your account has run out of searches"). Keys 1 and 2 had full quota — unused.
- Effect: every SerpAPI search (the `!all` catalyst queries AND the new macro/China-news risk query) returned empty in production. The macro/China news the user wanted in the risk section couldn't appear.
- Manual fix already applied (commit d596453): repointed config to `$SERPAPI_API_KEY` (key 1). **This is a band-aid** — it just moves the problem to key 1 when it exhausts.

## Why the existing "failover" doesn't work

- The code does `get_api_key("serpapi3") or get_api_key("serpapi2") or get_api_key("serpapi")` in `consensus_engine/alerts/all_command/gap_fill.py` (`_search_serpapi_raw`, `_search_serpapi_trusted`).
- But `serpapi2`/`serpapi3` aren't mapped in `config/consensus.yaml`'s `api_keys:` block, so `get_api_key` returns "" for them and falls through to the env fallback `os.environ.get("SERPAPI2")` / `("SERPAPI3")` — wrong names (real env vars are `SERPAPI2_API_KEY` / `SERPAPI3_API_KEY`). So it always lands on the single mapped `serpapi` key.
- Even if all three were mapped, the `or` chain only skips **missing** keys — it does NOT skip an **exhausted** key, because an exhausted key still returns a non-empty string. The `or` short-circuits on the first non-empty key regardless of whether it has quota.

## Suggested approach (priority-ordered)

1. **Rotate-on-429 in the SerpAPI helpers.** In `_search_serpapi_raw` / `_search_serpapi_trusted`, try keys in priority order; on HTTP 429 (or `error` containing "run out of searches"), move to the next key and retry. Cache "this key is exhausted" for the rest of the day so we don't waste a call probing it each time.
2. **Map all three keys** in `config/consensus.yaml` (`serpapi: $SERPAPI_API_KEY`, `serpapi2: $SERPAPI2_API_KEY`, `serpapi3: $SERPAPI3_API_KEY`) so the rotation has all keys to choose from. Fix the env-var fallback name bug in `get_api_key` (`SERPAPI3` → `SERPAPI3_API_KEY`) or stop relying on it.
3. **Optional: surface exhaustion.** When ALL keys are exhausted, emit one alert (like the LLM-health alert) so it's visible instead of silent.
4. **Consider the same pattern for other paid providers** (Brave, Exa) that also have monthly caps — they hit the same silent-failure mode (see memory: web-search providers credit status).

## Files involved
- `consensus_engine/alerts/all_command/gap_fill.py` — `_search_serpapi_raw`, `_search_serpapi_trusted` (the retry loop goes here).
- `consensus_engine/config.py` — `get_api_key` (env-var fallback name bug).
- `config/consensus.yaml` — `api_keys:` block.
- Reference: memory `reference_apis.md` (key status), `project_web_search_fixed.md` (provider history).

## Open questions
- Do keys 1/2/3 share one SerpAPI account/plan (so all exhaust together near month-end) or separate accounts (true failover)? Verify before relying on rotation as a real capacity boost vs just resilience.
- Should rotation be SerpAPI-only, or a generic "try providers in order until one returns results" layer across SerpAPI/Brave/Exa/SearXNG?
