# Pass 1 — Candidate Features / Approaches

## Context

The gap has two independent paths:

1. **Agent path** (`@-mention` / `!ask`) — uses OpenClaw's plugin system, currently SearXNG-only via built-in searxng plugin. No fallback if localhost:8888 goes down.
2. **Python engine path** (`!all`, news cascade) — calls Python adapters directly. SearXNG is tier-4 fallback; SerpAPI handles catalyst mining. No Tavily or Firecrawl wired in.

Keys available: `TAVILY_API_KEY`, `FIRECRAWL_API_KEY` both confirmed in `/home/openclaw/.openclaw/.env`. Note: `openclaw.json` is at `/home/openclaw/.openclaw/openclaw.json` — outside the git workspace — so plain key strings there are not exposed to the public repo.

---

## Candidate A — Configure web-search-plus-plugin-v2 (agent path)

**What it does:** The already-installed `web-search-plus-plugin-v2` has built-in multi-provider routing with automatic fallback. Configure it with `tavilyApiKey`, `firecrawlApiKey`, `searxngInstanceUrl`, and `searxngAllowPrivate: true` (needed because localhost resolves to a private IP and the plugin has SSRF protection). The plugin's `DEFAULT_PROVIDER_PRIORITY` tries Tavily → Firecrawl → SearXNG automatically when earlier providers fail. The agent gets a `web_search_plus` tool with 3-provider fallback built in.

**Rationale:** Zero new Python code. The plugin is already installed and running (just dormant with `{ "enabled": true }`). Config-only change in a file that's not tracked by git.

**Failure modes:**
- Tavily/Firecrawl hit monthly caps → SearXNG catches it
- SearXNG localhost goes down → Tavily or Firecrawl handles it
- All three fail simultaneously → empty result (acceptable; logs the failure)

**Caveat:** The agent would now have both `web_search` (from built-in searxng plugin) and `web_search_plus` (from this plugin). The LLM agent picks one. We'd want to either remove the searxng built-in or make instructions favor `web_search_plus`. Alternatively: change `tools.web.search.provider` to a null/disabled value to retire the built-in `web_search` tool and let `web_search_plus` be the only option.

**Source quality:** High — reads actual plugin JS source confirming routing logic.

---

## Candidate B — Add TavilyAdapter to Python engine (engine path)

**What it does:** Add a `TavilyAdapter` class to `consensus_engine/api_adapters.py` (same shape as existing `BraveAdapter`, `ExaAdapter`). POST to `https://api.tavily.com/search` with `{"api_key": "...", "query": "..."}`. Wire it as a fallback in `gap_fill.py` after `search_searxng()` returns empty. Optionally wire Firecrawl search (if Tavily also fails).

**Rationale:** Surgical. Follows the exact pattern already established by existing adapter classes. No infrastructure changes. Covers the `!all` search path which is completely separate from the plugin layer.

**Failure modes:**
- Tavily 402 (cap) → need a circuit breaker like Brave's (or just let it fall through to empty)
- Bad Tavily API response → adapter returns empty list, existing behavior preserved

**Source quality:** High — Tavily API is POST `https://api.tavily.com/search` with JSON body `{"api_key": "...", "query": "..."}` — identical to how the todo file describes it.

---

## Candidate C — Combined A + B (full coverage)

**What it does:** Apply both A and B. Agent path gets `web_search_plus` with 3-provider routing. Python engine gets Tavily as fallback. Two code changes, both surgical, covering both paths.

**Rationale:** Neither A nor B alone covers both paths. C is the union.

**Source quality:** Derived from A+B above.

---

## Candidate D — SearXNG-proxy Python service (Approach D from todo)

**What it does:** Write a small FastAPI/Flask proxy on a different port (e.g. 8889) that mimics the SearXNG `/search?q=...&format=json` API. Internally: hit real SearXNG → if empty/error, hit Tavily → if empty, hit Firecrawl. Register as a systemd service. Point `openclaw.json` `tools.web.search.provider = "searxng"` and the plugin `searxngInstanceUrl` at the proxy port. The Python engine's `search_searxng()` function would also point there.

**Rationale:** Single fallback layer covers both paths with no per-caller changes. No new tool in the agent layer.

**Failure modes:**
- Proxy itself goes down → both paths break (adds a new SPOF)
- Systemd startup ordering — proxy must start before consensus-engine

**Source quality:** Medium — pattern is sound, but adds infrastructure a combined A+B avoids.

---

## Candidate E — Debug Brave plugin secret resolution

**What it does:** Investigate why Brave plugin fails hard at env ref resolution (vs exa's soft warning). Could be a plugin version difference or an OpenClaw bug.

**Rationale:** Low. Brave hit its monthly cap anyway (#11 was resolved by deprioritizing Brave). Not worth debugging a paid-tier plugin when free alternatives work.

**Source quality:** Low — speculative, no evidence of a fixable bug.

---

## Eliminated at Pass 1

- **Top up Exa credits** — explicitly out of scope (no paid providers)
- **MCP server for Tavily** — `mcporter` plugin is disabled and unrelated; confirmed dead end in todo notes
- **Rewrite OpenClaw plugin in Python** — massively over-engineered
