# Pass 5 Kickoff — web-search-fallback-chain

## Run context
- **Run name:** `web-search-fallback-chain`
- **Plan:** `/home/openclaw/.openclaw/workspace/.claude/discover/web-search-fallback-chain/final-plan.md`
- **Git remote:** `chopra2007/openclaw--StockTicker-Signals-Discord-Bot` (push after verification)

## What was decided (Passes 0–4 summary)

Two independent changes to add web-search resilience:

**Change 1 — Plugin config (agent path, `@-mention`/`!ask`):**
- Edit `/home/openclaw/.openclaw/openclaw.json`
- Add config to `plugins.entries.web-search-plus-plugin-v2`: tavilyApiKey, firecrawlApiKey, searxngInstanceUrl + searxngAllowPrivate: true
- Try env ref format first (`{"source":"env","provider":"default","id":"TAVILY_API_KEY"}`), test, switch to plain string if env refs don't resolve (safe — this file is not in git)
- Restart `openclaw-gateway.service`
- Keys are already in `.env.service`

**Change 2 — Python fallback (engine path, `!all`, news cascade, sources):**
- Edit `consensus_engine/scanners/searxng.py`
- Modify `search_searxng()` to call new `_tavily_fallback()` helper when SearXNG returns `[]` or throws
- All 3 callers (news.py, sources.py, gap_fill.py) benefit automatically — no changes to those files
- Restart `consensus-engine.service`
- `TAVILY_API_KEY` already in `.env.service`

## Acceptance criteria (from todo/web-search-providers.md)

1. `sudo -u openclaw openclaw agent --local --agent main --message "Use web_search to find one recent NVDA headline."` → non-error result with a real headline
2. Bot reply to `<@bot> any trump or iran news today of note?` produces a coherent answer with at least one fresh dated headline cited

## Verification checklist (section 8 of final-plan.md)

All items in section 8 must pass before declaring done and committing.

## Resume trigger

In a fresh Claude Code session, type:

    discover: resume web-search-fallback-chain

The skill will load this file and the final-plan.md from disk.
