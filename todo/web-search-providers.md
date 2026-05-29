# OpenClaw web-search providers degraded — Exa out of credits, Brave plugin unstable

**Status:** DONE 2026-05-28 — engine + agent paths resilient (Python fallback + searxng-proxy:8899), live-verified under SearXNG outage. (soak)
**Created:** 2026-05-19

**Layperson:** The `@-mention` bot path delegates to `openclaw agent --local --agent main`. That agent's `web_search` tool is currently broken at the provider level — Exa (the configured provider in `openclaw.json`) returns `402 NO_MORE_CREDITS`, and a swap to the official `@openclaw/brave-plugin` (installed via `openclaw plugins install clawhub:@openclaw/brave-plugin`) destabilized the whole agent path (even non-tool messages timed out, plus secret resolution failed: `unresolved SecretRef "env:default:BRAVE_SEARCH_API_KEY"`). Reverted to Exa so the gateway stays usable.

## Observed during 2026-05-19 gateway-flap fix session

- CLI probe under brave: `openclaw agent --local --agent main --message "Reply with exactly: brave_ok"` → 30s timeout, no reply.
- Gateway side: `[secrets] plugins.entries.brave.config.webSearch.apiKey: unresolved SecretRef ... Resolve this command against an active gateway runtime snapshot before reading it.`
- Plugin manifest installed cleanly (`Installed plugin: brave`), `plugins.allow` list now contains `brave`, `plugins.entries.brave` has the same `apiKey: env:default:BRAVE_SEARCH_API_KEY` shape that exa uses successfully.
- Yet exa says `secret ref is configured on an inactive surface; skipping command-time assignment` (warning only — still works enough to hit the API), while brave says the same is a hard failure.

## Options

### Current state (2026-05-28)
- `tools.web.search.provider` is set to `searxng` (local instance at `localhost:8888`) — working.
- `web-search-plus-plugin-v2` is installed but dormant (`{ "enabled": true }`, no config).
- Tavily API key added to `.env` and `.env.service` as `TAVILY_API_KEY` (1,000 free credits/month).
- No paid providers will be added. Only free/already-owned options in scope.

### Free providers available
- **SearXNG** — self-hosted, fully free, already working. Only truly unlimited option.
- **Tavily** — 1,000 credits/month free. Key in env.
- **Firecrawl** — ~500 credits/month free. Key already in `.env`.
- Brave, Exa — have free monthly tiers but previously caused problems; low priority.

### Approach A — Patch the plugin's local schema (agent path)
`web-search-plus-plugin-v2` supports a `provider_priority` list in its TypeScript code, but the field is missing from `openclaw.plugin.json`'s `configSchema` (which has `additionalProperties: false`), so OpenClaw rejects it. A one-line addition to the local plugin schema at `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/openclaw.plugin.json` would allow setting a persistent ordered priority (e.g. searxng → tavily → firecrawl) in `openclaw.json`. Caveat: the schema also requires `tavilyApiKey` as a plain `string`, but the key can't be hardcoded in a public repo — would need openclaw to support `env:` string interpolation, which is unconfirmed.

### Approach B — Python fallback in the consensus engine (`!all` path)
The `!all` command does web searches via Python code directly (not through openclaw agent tools). Wrapping those calls in try/except logic that cycles through providers — SearXNG → Firecrawl → Tavily — is fully under our control, no schema issues, no key exposure. Covers the `!all` search path but not `@-mention`/`!ask`.

### Approach C — Debug Brave plugin secret-resolution
The original Brave plugin fails because it requires key delivery through the active gateway runtime snapshot, not the `--local` surface. Worth a 30-minute dig comparing `dist/exa-web-search-provider*.shared*.js` vs `dist/brave-web-search-provider*.shared*.js`. Could be a plugin bug worth filing upstream.

### Approach D — SearXNG-proxy (from scratch, no plugin)
Write a small Python HTTP server that mimics the SearXNG API (`GET /search?q=...&format=json`). Point openclaw's existing SearXNG provider at it instead of `localhost:8888`. Internally the proxy tries the real SearXNG first, then falls back through Firecrawl, Tavily, etc. in whatever order you choose. Runs as a systemd service. No plugin, no JavaScript, no schema workarounds — covers both the `@-mention` agent path and `!all` in one shot. Keys stay in `.env`, never in `openclaw.json`.

**Fallback API details (confirmed from docs):**
- **Tavily**: POST `https://api.tavily.com/search` — body `{"api_key": "...", "query": "..."}`. Key from `TAVILY_API_KEY` env var. 1,000 free credits/month.
- **Firecrawl**: already has a key in `.env` as `FIRECRAWL_API_KEY`. ~500 free credits/month.
- Tavily MCP server was investigated as an alternative but ruled out — openclaw has no MCP server config support (confirmed: `mcporter` plugin exists but is disabled and unrelated).

**Recommended fallback order:** SearXNG (localhost, unlimited) → Tavily → Firecrawl.

### Dropped
- ~~Top up Exa credits~~ — no paid options.

## Where

- Config: `/home/openclaw/.openclaw/openclaw.json` — `tools.web.search.provider` + `plugins.entries.exa` and `plugins.entries.brave`.
- Installed plugin: `/home/openclaw/.openclaw/extensions/brave/` (linked back to `openclaw` peer at `/usr/lib/node_modules/openclaw`).
- Backup of pre-brave-swap config: `/home/openclaw/.openclaw/openclaw.json.bak.pre-brave-swap`.

## Acceptance

- `sudo -u openclaw openclaw agent --local --agent main --message "Use web_search to find one recent NVDA headline."` returns a non-error result with a real headline string.
- Bot reply to `<@bot> any trump or iran news today of note?` produces a coherent answer with at least one fresh dated headline cited.

**Discovered:** 2026-05-19 during the gateway-flap fix — bot quality-degradation root cause #2 (the #1 root cause was the gateway env-file ownership bug, fixed in-session).

## Plan (2026-05-28)

Full discover run complete. Plan at `.claude/discover/web-search-fallback-chain/final-plan.md`. Execute with: `discover: resume web-search-fallback-chain`

**Planned approach — 3 file changes:**

1. **Schema patch** — add `routingPreferences` field to `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/openclaw.plugin.json` (one field, unlocks static priority config)
2. **Plugin config** — configure `web-search-plus-plugin-v2` in `openclaw.json` with SearXNG first, Tavily + Firecrawl as exception-only fallbacks
3. **Python fallback** — modify `search_searxng()` in `consensus_engine/scanners/searxng.py` to call Tavily when SearXNG returns empty or throws (covers `!all`, news cascade, sources — all 3 callers automatically)

**Before executing — review these open questions:**

- Is this the right approach, or is there a simpler one? The plugin schema patch is a local-file hack that could be overwritten by a plugin update. Alternative: skip the plugin entirely and rely only on the Python fallback in `searxng.py` (covers the engine path) + leave the agent path as SearXNG-only (it's currently working).
- The `web-search-plus-plugin-v2` plugin adds a `web_search_plus` tool alongside the existing `web_search`. Is having two search tools confusing to the agent, or is the distinction useful?
- Tavily API confirmed working (tested 2026-05-28, 1 credit used). Firecrawl not tested yet.

### Session notes — 2026-05-28 (DONE — discover run todo-autobatch)
- **Root cause of the 12h gateway outage found + fixed:** a PRIOR partial execution of the old plan wrote an invalid `web-search-plus-plugin-v2` config into `openclaw.json` (rejected: additionalProperties + `tavilyApiKey must be string`), crash-looped the gateway past its restart limit. Config was reverted on disk but the service was left `failed`. Restored via `reset-failed` + `restart`.
- **Rejected the old plan's plugin approach (Changes 1+2).** Verified in the plugin's `dist/*.js`: AUTO mode picks provider by query-score (would burn paid credits while SearXNG is healthy); STRICT mode has NO fallback. Plus the schema patch lives outside git (lost on plugin reinstall) and forces cleartext keys. It literally cannot deliver "SearXNG-first, fallback-only" AND it's what crashed the gateway.
- **Shipped a better, gateway-safe 2-part fix instead:**
  - **Engine path:** in-process Tavily→Firecrawl fallback inside `search_searxng()` (consensus_engine/scanners/searxng.py). Covers all 3 callers (news, sources, gap_fill). Live-verified: SearXNG stopped → engine search returned 5 results via Tavily.
  - **Agent path:** new `scripts/searxng_proxy.py` (SearXNG-compatible) running as `searxng-proxy.service` on :8899; one-string repoint of `openclaw.json` `plugins.entries.searxng.config.webSearch.baseUrl` 8888→8899 (existing allowed field — cannot trip the validator). Live-verified end-to-end: SearXNG stopped → `openclaw agent --local` web_search returned a real headline, proxy log confirmed `Tavily served`.
- **GOTCHA recorded:** editing `openclaw.json` as root changes its ownership to root:root → gateway (user openclaw) gets EACCES → fails. Always `chown openclaw:openclaw openclaw.json && chmod 600` after any root edit, then restart.
- **Acceptance met:** both acceptance bullets pass (agent web_search returns a real headline; resilient to provider failure). Keys present in `.env.service` (engine) and `.env` (proxy uses `.env.service` via systemd since `.env` has `export` prefixes systemd can't parse).
- web-search-plus-plugin-v2 left dormant ({enabled:true}, no config).
