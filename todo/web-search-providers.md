# OpenClaw web-search providers degraded — Exa out of credits, Brave plugin unstable

**Status:** OPEN — decision pending between 3 options.

**Layperson:** The `@-mention` bot path delegates to `openclaw agent --local --agent main`. That agent's `web_search` tool is currently broken at the provider level — Exa (the configured provider in `openclaw.json`) returns `402 NO_MORE_CREDITS`, and a swap to the official `@openclaw/brave-plugin` (installed via `openclaw plugins install clawhub:@openclaw/brave-plugin`) destabilized the whole agent path (even non-tool messages timed out, plus secret resolution failed: `unresolved SecretRef "env:default:BRAVE_SEARCH_API_KEY"`). Reverted to Exa so the gateway stays usable.

## Observed during 2026-05-19 gateway-flap fix session

- CLI probe under brave: `openclaw agent --local --agent main --message "Reply with exactly: brave_ok"` → 30s timeout, no reply.
- Gateway side: `[secrets] plugins.entries.brave.config.webSearch.apiKey: unresolved SecretRef ... Resolve this command against an active gateway runtime snapshot before reading it.`
- Plugin manifest installed cleanly (`Installed plugin: brave`), `plugins.allow` list now contains `brave`, `plugins.entries.brave` has the same `apiKey: env:default:BRAVE_SEARCH_API_KEY` shape that exa uses successfully.
- Yet exa says `secret ref is configured on an inactive surface; skipping command-time assignment` (warning only — still works enough to hit the API), while brave says the same is a hard failure.

## Decision pending — three options

1. **Top up Exa credits.** Restores the current setup verbatim. Single-provider risk remains.
2. **Debug Brave plugin's `--local` secret-resolution path.** The error message ("Resolve this command against an active gateway runtime snapshot before reading it") suggests Brave wants its API key delivered through a different surface than Exa does. Worth a 30-minute dig: compare `dist/exa-web-search-provider*.shared*.js` vs `dist/brave-web-search-provider*.shared*.js` for the secret-resolution hook differences. Could be a plugin bug in @openclaw/brave-plugin@2026.5.18 worth filing upstream.
3. **Install `web-search-plus-plugin-v2`** (the alternative ClawHub plugin surfaced by `openclaw plugins search brave`) — it supports Serper/Google, Brave, Tavily, Exa, Querit, Linkup, Firecrawl, Perplexity, You.com, SearXNG behind one tool with multi-provider failover. Heavier dependency but eliminates the single-provider risk entirely.

## Where

- Config: `/home/openclaw/.openclaw/openclaw.json` — `tools.web.search.provider` + `plugins.entries.exa` and `plugins.entries.brave`.
- Installed plugin: `/home/openclaw/.openclaw/extensions/brave/` (linked back to `openclaw` peer at `/usr/lib/node_modules/openclaw`).
- Backup of pre-brave-swap config: `/home/openclaw/.openclaw/openclaw.json.bak.pre-brave-swap`.

## Acceptance

- `sudo -u openclaw openclaw agent --local --agent main --message "Use web_search to find one recent NVDA headline."` returns a non-error result with a real headline string.
- Bot reply to `<@bot> any trump or iran news today of note?` produces a coherent answer with at least one fresh dated headline cited.

**Discovered:** 2026-05-19 during the gateway-flap fix — bot quality-degradation root cause #2 (the #1 root cause was the gateway env-file ownership bug, fixed in-session).
