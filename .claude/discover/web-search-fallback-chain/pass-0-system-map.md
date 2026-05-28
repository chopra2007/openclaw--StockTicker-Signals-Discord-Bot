# Pass 0 — Existing System Map

## Component Inventory

### Agent Path (@-mention / !ask)
- **Entry:** `openclaw agent --local --agent main` dispatches to the `main` agent defined in `openclaw.json`
- **Web search tool:** OpenClaw's built-in SearXNG plugin (`tools.web.search.provider = "searxng"`) → `http://localhost:8888`
- **Plugins installed:** searxng (active), brave (installed+enabled, key in .env), exa (installed+enabled, key in .env), web-search-plus-plugin-v2 (installed+enabled, no config = dormant), google (enabled)
- **Keys available in .env but NOT wired into agent path:** `TAVILY_API_KEY`, `FIRECRAWL_API_KEY`
- **No fallback chain.** If localhost:8888 (SearXNG) goes down → agent gets an empty search result, no retry.

### Consensus Engine — News Cascade (!all, ticker alerts)
Python code, not OpenClaw plugin tools.

| Code path | File | Provider | Error handling |
|---|---|---|---|
| news.py news cascade | scanners/news.py:340-400 | Brave API → HTTP 402 trips global circuit-breaker | Returns empty, circuit-breaker latches open |
| news.py tier 4 | scanners/news.py:403-423 | SearXNG localhost:8888 | Returns empty list on error |
| gap_fill catalyst mining | alerts/all_command/gap_fill.py:48-87 | SerpAPI (3-key rotation) | Returns empty on non-200 |
| gap_fill anchor/filing | alerts/all_command/gap_fill.py:131-200 | SearXNG | Returns empty |
| social trends | scanners/social.py:441-510 | Exa AI | Returns empty |

**No cross-provider fallback anywhere.** Each provider fails independently and silently (returns empty list). The news cascade runs tiers serially and takes the first non-empty hit, but that's within Brave/SearXNG/RSS tiers — not a fallback chain where Tavily/Firecrawl substitute for a failed provider.

### Adapters Available (consensus engine)
`api_adapters.py` has fully-implemented classes for Brave, Exa, Firecrawl (scrape), SerpAPI. **Tavily has no adapter class.** FIRECRAWL_API_KEY and TAVILY_API_KEY are in .env but unused by Python code.

### web-search-plus-plugin-v2
Installed at `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/`. The TypeScript source reportedly supports a `provider_priority` list, but the `openclaw.plugin.json` configSchema has `additionalProperties: false` — so the field is invisible to OpenClaw's config validator. Currently: `{ "enabled": true }` with no config = dormant.

## Data Flow (Agent Path)

```
@-mention / !ask
     ↓
openclaw agent --local --agent main
     ↓
web_search tool call
     ↓
OpenClaw SearXNG plugin → GET localhost:8888/search?q=...
     ↓
[if localhost:8888 down] → empty result, no retry
```

## Data Flow (Consensus Engine !all path)

```
!all <TICKER>
     ↓
aggregator.py → gap_fill.run_gap_fill()
     ↓
┌─ searxng.search_searxng() → localhost:8888
└─ _search_serpapi_raw()   → serpapi.com (3-key rotation)
     ↓
Each: returns [] on failure, no fallback to other provider
```

## Strengths (what's working)
- SearXNG self-hosted at localhost:8888 is functional and free (no credit caps)
- SerpAPI in !all path has 3-key rotation — limited resilience
- Brave circuit-breaker prevents wasting calls after 402
- TAVILY_API_KEY and FIRECRAWL_API_KEY are already in .env — keys ready, just not wired

## Gaps (confirmed absent)
1. **Agent path has no fallback.** SearXNG goes down → agent gets empty search results, replies degrade silently.
2. **Tavily not wired anywhere.** Key is present; no code uses it.
3. **Firecrawl not wired as a search fallback** (it's a scraper, not a search adapter — but Tavily search works similarly).
4. **web-search-plus-plugin-v2 is dormant.** The `provider_priority` field it supports is blocked by schema `additionalProperties: false`.
5. **Python engine has no unified search fallback layer** — each adapter is called directly, no coordinator.
