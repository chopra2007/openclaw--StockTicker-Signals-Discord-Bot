# Pass 2 — Filtered & Prioritized

## Decision

**Winner: Candidate C — Configure web-search-plus-plugin-v2 (agent path) + Add TavilyAdapter (Python engine path)**

Candidates D and E are dropped.

---

## Why D is dropped

Approach D (proxy service) introduces a new process between callers and providers. It adds a SPOF (if the proxy goes down, both paths fail), requires a new systemd unit with startup ordering, and more code to maintain than A+B combined. C achieves the same resilience with no new infrastructure.

## Why E is dropped

Brave had its monthly cap hit and was already deprioritized. Debugging its secret-resolution mechanism has no payoff given we have Tavily and Firecrawl as better alternatives.

---

## Feature 1 — web-search-plus-plugin-v2 config (agent path)

**Scope:** `openclaw.json` only — config change, no code.

**What changes:**
```json
"plugins.entries.web-search-plus-plugin-v2": {
  "enabled": true,
  "config": {
    "tavilyApiKey": "<TAVILY_API_KEY value from .env>",
    "firecrawlApiKey": "<FIRECRAWL_API_KEY value from .env>",
    "searxngInstanceUrl": "http://localhost:8888",
    "searxngAllowPrivate": true
  }
}
```

**Routing behavior:** Plugin auto_routing=true by default. `DEFAULT_PROVIDER_PRIORITY` = Tavily → Exa → Firecrawl → ... → SearXNG. With only Tavily + Firecrawl + SearXNG configured, the order becomes: **Tavily → Firecrawl → SearXNG**. This is the desired order for the agent path (low-volume @-mentions: Tavily quality-first is fine, SearXNG unlimited as final catch).

**Dual-tool issue:** With both the built-in `searxng` plugin and `web-search-plus-plugin-v2` enabled, the agent gets two search tools: `web_search` and `web_search_plus`. Resolution: disable the built-in `searxng` provider by removing it from `plugins.allow` list, OR change `tools.web.search.provider` to a non-searxng value. Either way, `web_search_plus` becomes the sole search tool for the agent.

**Identified failure mode:** `searxngAllowPrivate: true` disables the SSRF check for the plugin. The existing `scanners/searxng.py` (Python code) is unaffected — it calls localhost:8888 directly via aiohttp, not through the plugin.

**Safeguards:**
- Tavily and Firecrawl have free monthly caps. Agent path is low-volume (<50 calls/day expected), well within limits.
- If all three fail, agent gets empty search result — same as current broken state; no regression.

**Rank:** High impact. Zero new code. Immediate fix for the user-visible acceptance test.

---

## Feature 2 — TavilyAdapter in Python engine (engine path)

**Scope:** `consensus_engine/api_adapters.py` (new class) + `consensus_engine/alerts/all_command/gap_fill.py` (fallback wire-up).

**What changes:**

New class in `api_adapters.py`:
```python
class TavilyAdapter:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.tavily.com/search"

    async def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        # POST {"api_key": ..., "query": ..., "max_results": ...}
        # Parse response["results"] → SearchHit(title, url, snippet/content)
        # Return [] on any error/timeout
```

Wire in `gap_fill.py`:
- After the `search_searxng()` call in `run_gap_fill()` returns empty, try `TavilyAdapter.search()` as fallback.
- Read `TAVILY_API_KEY` from env / config.
- No circuit-breaker needed for the planning phase (Tavily returns structured errors; a 402 just means empty results for this call — acceptable).

**Identified failure mode:** Tavily POST adds latency (~500ms). Since gap_fill already runs async and this is a fallback (SearXNG failing is rare), impact is minimal.

**Safeguards:**
- `TavilyAdapter.search()` wraps all exceptions; returns `[]` on any failure. Same contract as existing adapters.
- TAVILY_API_KEY is read from env, not hardcoded.

**Rank:** High impact. Covers the `!all` path that Feature 1 doesn't reach. ~40 lines of new code following an established pattern.

---

## Implementation Notes

1. **Key delivery:** Read actual key values from `.env` at install time and write directly into `openclaw.json`. Safe because `openclaw.json` is not in the git workspace.
2. **Test order:** Feature 1 (config change) can be done and tested before Feature 2 (code change). They're independent.
3. **Rollback:** Both features are reversible — revert `openclaw.json` for Feature 1, delete the adapter class for Feature 2.
4. **No regression risk to existing Python adapters** — TavilyAdapter is additive; existing SearXNG, Brave, Exa, SerpAPI calls are unchanged.
