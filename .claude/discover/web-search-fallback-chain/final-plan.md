# Final Plan — web-search-fallback-chain

**Feature:** Resilient web search for both the `@-mention`/`!ask` agent path and the Python consensus engine path (news cascade, !all gap_fill, research/sources).

**Scope:** 2 independent changes. Order doesn't matter; both are safe to apply together.

---

## 1. System Overview

There are two completely separate web-search code paths that both need resilience:

| Path | How it calls search | Current state | Gap |
|---|---|---|---|
| Agent (`@-mention`, `!ask`) | OpenClaw plugin tools (`web_search`, `web_search_plus`) | `web_search` → SearXNG localhost:8888, works | No fallback if SearXNG goes down |
| Python engine (`!all`, news, sources) | Python `search_searxng()` → localhost:8888 directly | 3 callers; returns `[]` on any failure | No Tavily/Firecrawl fallback |

**Fix:** Two surgical changes — one config edit (agent path), one Python edit (engine path). No new processes, no new services.

---

## 2. Component Architecture

### Change 1 — Plugin schema patch + `openclaw.json` config (agent path)

**Files:**
- `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/openclaw.plugin.json` (schema patch)
- `/home/openclaw/.openclaw/openclaw.json` (config)

**What:** The plugin already supports a `routingPreferences` object in its config that sets permanent provider priority. The only blocker is `routingPreferences` is missing from the plugin's JSON schema (`additionalProperties: false` rejects unknown fields). A one-field schema patch unlocks it. Then configure the plugin with `provider_priority: ["searxng", "tavily", "firecrawl"]`.

**Effect:** Agent gets `web_search_plus` tool. SearXNG runs first on every call. Tavily and Firecrawl only fire if SearXNG throws an exception (connection refused, timeout, non-200). No credits consumed when SearXNG is healthy.

### Change 2 — `consensus_engine/scanners/searxng.py` (engine path)

**File:** `consensus_engine/scanners/searxng.py`
**What:** Add a Tavily fallback inside `search_searxng()`. If SearXNG returns `[]` OR throws, try Tavily.
**Effect:** All 3 callers (`news.py:407`, `sources.py:87`, `gap_fill.py:108`) automatically get the fallback. Return type unchanged (`list[dict]` with `{"title", "url", "content"}`).

---

## 3. Integration Points — Exact File Changes

### Change 1a: Schema patch — `openclaw.plugin.json`

**Location:** `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/openclaw.plugin.json`

**Section to modify:** `configSchema.properties` — add one new field alongside the existing ones:

```json
"routingPreferences": {
  "type": "object",
  "description": "Static routing preferences loaded at startup. Supports provider_priority (array), auto_routing (bool), fallback_provider (string).",
  "additionalProperties": true
}
```

**Caveat:** This file is inside the installed plugin extension, not the git workspace. It may be overwritten if OpenClaw updates the plugin. Low risk — free plugins rarely auto-update.

---

### Change 1b: `openclaw.json`

**Location:** `/home/openclaw/.openclaw/openclaw.json`

**Section to modify:** `plugins.entries.web-search-plus-plugin-v2`

Current:
```json
"web-search-plus-plugin-v2": {
  "enabled": true
}
```

Target:
```json
"web-search-plus-plugin-v2": {
  "enabled": true,
  "config": {
    "tavilyApiKey": "<see key delivery below>",
    "firecrawlApiKey": "<see key delivery below>",
    "searxngInstanceUrl": "http://localhost:8888",
    "searxngAllowPrivate": true,
    "routingPreferences": {
      "provider_priority": ["searxng", "tavily", "firecrawl"]
    }
  }
}
```

**Provider priority result:** SearXNG runs first. If SearXNG throws (down, timeout, non-200) → Tavily. If Tavily throws → Firecrawl. No credits consumed when SearXNG is healthy.

**`tools.web.search.provider`**: Leave as `"searxng"`. Keeping both `web_search` (SearXNG) and `web_search_plus` (multi-provider) available is correct — the acceptance test asks `web_search` to work; `web_search_plus` is the resilient alternative.

**Key delivery — executor must do this in order:**

Step 1: Try env ref format first (same pattern as exa/brave plugins):
```json
"tavilyApiKey": {"source": "env", "provider": "default", "id": "TAVILY_API_KEY"},
"firecrawlApiKey": {"source": "env", "provider": "default", "id": "FIRECRAWL_API_KEY"}
```

Step 2: Restart openclaw-gateway.service:
```bash
sudo systemctl restart openclaw-gateway.service && sleep 5
```

Step 3: Test — this query forces `web_search_plus` and reveals the routing used:
```bash
sudo -u openclaw openclaw agent --local --agent main \
  --message "Use your web_search_plus tool to find recent NVDA news. After the search, tell me which provider field appears in the routing metadata."
```

Step 4: If the response shows `provider: "tavily"` or `provider: "firecrawl"` → env refs worked. Done.

Step 4 (alt): If the response shows `provider: "searxng"` only (no tavily/firecrawl tried), the env refs didn't resolve. Switch to plain strings:
```bash
# Read keys from .env
TAVILY_KEY=$(grep "^export TAVILY_API_KEY=" /home/openclaw/.openclaw/.env | cut -d= -f2)
FIRECRAWL_KEY=$(grep "^export FIRECRAWL_API_KEY=" /home/openclaw/.openclaw/.env | cut -d= -f2)
# Then set them as plain strings in the config JSON
```
Plain strings are safe: `openclaw.json` is not in the git workspace (`/home/openclaw/.openclaw/workspace/`).

---

### Change 2: `consensus_engine/scanners/searxng.py`

**Current end of file** (after `search_searxng()` returns):
```python
    except Exception as e:
        log.warning("SearXNG error: %s", e)
        rate_limiter.report_failure("searxng")
        return []
```

**Add after the imports** (top of file, with existing imports):
```python
import os
```
(Check first — may already be imported.)

**Modify `search_searxng()`** — change both return-empty paths to call a new helper, then add the helper:

```python
async def search_searxng(query: str) -> list[dict]:
    """Search via self-hosted SearXNG with Tavily fallback."""
    base_url = cfg.get("searxng.base_url", "http://localhost:8888")
    timeout = cfg.get("searxng.timeout", 10)

    if not await rate_limiter.acquire("searxng"):
        return await _tavily_fallback(query)

    try:
        session = await get_session()
        params = {"q": query, "format": "json"}
        async with session.get(
            f"{base_url}/search",
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                rate_limiter.report_failure("searxng")
                log.warning("SearXNG returned %d for '%s'", resp.status, query)
                return await _tavily_fallback(query)
            data = await resp.json()
            rate_limiter.report_success("searxng")
            results = _parse_searxng_results(data)
            log.debug("SearXNG: %d results for '%s'", len(results), query)
            if results:
                return results
            return await _tavily_fallback(query)
    except Exception as e:
        log.warning("SearXNG error: %s", e)
        rate_limiter.report_failure("searxng")
        return await _tavily_fallback(query)


async def _tavily_fallback(query: str) -> list[dict]:
    """Tavily fallback when SearXNG is unavailable or returns no results."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return []
    log.warning("searxng: using tavily fallback for query: %.80s", query)
    try:
        session = await get_session()
        async with session.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 5},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                log.warning("Tavily fallback returned %d", resp.status)
                return []
            data = await resp.json()
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                }
                for r in (data.get("results") or [])
            ]
            log.debug("Tavily fallback: %d results for query: %.80s", len(results), query)
            return results
    except Exception as e:
        log.warning("Tavily fallback error: %s", e)
        return []
```

**Why `os.environ.get` and not `cfg.get_api_key`:** The key is in `.env.service` (confirmed) which the systemd service loads. `os.environ.get` reads it directly without touching the cfg layer.

---

## 4. Data Structures

No new data structures. `_tavily_fallback()` returns the same `list[dict]` shape as `search_searxng()`: `{"title": str, "url": str, "content": str}`. Callers (news.py, sources.py, gap_fill.py) don't change.

---

## 5. Data Flow After Changes

### Agent path
```
@-mention → openclaw agent → [web_search] SearXNG plugin → localhost:8888
                            → [web_search_plus] web-search-plus-plugin-v2
                                  → Tavily (primary, exception-based fallback to ↓)
                                  → Firecrawl (if Tavily throws)
                                  → SearXNG localhost:8888 (if Firecrawl throws)
```

### Python engine path
```
news.py / sources.py / gap_fill.py
    → search_searxng(query)
        → SearXNG localhost:8888
        → if [] or exception → _tavily_fallback(query)
            → POST api.tavily.com/search
            → returns [] if Tavily also fails
```

---

## 6. Failure Handling

| Scenario | Agent path | Python engine path |
|---|---|---|
| SearXNG down | `web_search` fails; `web_search_plus` tries Tavily → Firecrawl | Tavily fallback fires |
| Tavily 402/down | `web_search_plus` tries Firecrawl → SearXNG | Returns `[]` (logs warning) |
| All three down | `web_search_plus` returns error to agent | `[]` returned to callers (existing behavior) |
| TAVILY_API_KEY missing from env | Plugin: env ref fails silently, Tavily not in pool | `_tavily_fallback()` returns `[]` immediately |
| `searxngAllowPrivate` key wrong | Plugin rejects localhost URL; SearXNG not in pool | Unaffected (Python doesn't use plugin) |

---

## 7. Feature Activation Plan

### Agent path (Change 1)
1. Edit `openclaw.json` with plugin config (follow key delivery steps above)
2. `sudo systemctl restart openclaw-gateway.service`
3. Test `web_search_plus` tool (see verification below)

No config flag to flip — the plugin is already in `plugins.allow`. Adding config activates it.

### Python engine path (Change 2)
1. Edit `consensus_engine/scanners/searxng.py` as specified
2. `sudo systemctl restart consensus-engine.service`
3. No new config keys needed — `TAVILY_API_KEY` already in `.env.service`

---

## 8. Verification Checklist

### Pre-check (confirm baseline)
- [ ] `systemctl is-active consensus-engine.service` → `active`
- [ ] `systemctl is-active openclaw-gateway.service` → `active`
- [ ] `curl -s "http://localhost:8888/search?q=test&format=json" | python3 -c "import sys,json; d=json.load(sys.stdin); print('SearXNG OK, results:', len(d.get('results',[])))"` → shows result count

### After Change 2 (Python engine)
- [ ] `sudo systemctl restart consensus-engine.service && sleep 3`
- [ ] `python3 -m consensus_engine --dry-run --once` → no import errors
- [ ] `python3 -c "import asyncio; from consensus_engine.scanners.searxng import search_searxng; r = asyncio.run(search_searxng('NVDA stock news')); print('results:', len(r), r[0] if r else 'empty')"` → shows results (SearXNG or Tavily)
- [ ] Confirm Tavily fallback log message: temporarily point `searxng.base_url` at a dead port, re-run, check logs for `"using tavily fallback"` warning

### After Change 1 (agent path)
- [ ] `sudo -u openclaw openclaw agent --local --agent main --message "Use web_search to find one recent NVDA headline."` → returns a real headline (acceptance test #1)
- [ ] `sudo -u openclaw openclaw agent --local --agent main --message "Use web_search_plus to find recent Trump or Iran news. Tell me which provider the routing metadata shows."` → `provider` field in response shows which provider ran
- [ ] (Live) Send `@-mention any trump or iran news today of note?` to Discord → bot replies with dated headline (acceptance test #2)

### Always-on checks
- [ ] `systemctl is-active consensus-engine.service` → `active`
- [ ] `systemctl is-active openclaw-gateway.service` → `active`
- [ ] `/root/.openclaw` symlink intact: `ls -la /root/.openclaw` → points to `/home/openclaw/.openclaw`

---

## 9. Files Changed

| File | Type | Description |
|---|---|---|
| `/home/openclaw/.openclaw/extensions/web-search-plus-plugin-v2/openclaw.plugin.json` | Config (not in git) | Add `routingPreferences` field to configSchema |
| `/home/openclaw/.openclaw/openclaw.json` | Config (not in git) | Add web-search-plus-plugin-v2 config with SearXNG-first priority |
| `consensus_engine/scanners/searxng.py` | Python | Add `_tavily_fallback()` helper; modify `search_searxng()` |

**Files NOT changed:** `news.py`, `sources.py`, `gap_fill.py`, `api_adapters.py`, any test files beyond adding Tavily fallback tests.

---

## 10. Tests to Add/Update

**New:** `tests/test_searxng_fallback.py`

```python
"""Test that search_searxng falls back to Tavily when SearXNG is unavailable."""
import pytest
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_searxng_returns_results_no_fallback():
    """When SearXNG has results, Tavily is not called."""
    with patch("consensus_engine.scanners.searxng.get_session") as mock_sess, \
         patch("consensus_engine.scanners.searxng._tavily_fallback", new_callable=AsyncMock) as mock_tavily:
        # mock SearXNG returning results
        mock_sess.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.status = 200
        mock_sess.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value.json = AsyncMock(
            return_value={"results": [{"title": "Test", "url": "http://example.com", "content": "test"}]}
        )
        result = await search_searxng("NVDA news")
        mock_tavily.assert_not_called()
        assert len(result) == 1

@pytest.mark.asyncio
async def test_searxng_empty_triggers_tavily():
    """When SearXNG returns [], Tavily fallback is called."""
    with patch("consensus_engine.scanners.searxng._tavily_fallback", new_callable=AsyncMock, return_value=[{"title": "Tavily result", "url": "http://t.com", "content": "x"}]) as mock_tavily, \
         patch(...):  # mock SearXNG to return []
        result = await search_searxng("NVDA news")
        mock_tavily.assert_called_once_with("NVDA news")
        assert result[0]["title"] == "Tavily result"

@pytest.mark.asyncio
async def test_tavily_missing_key_returns_empty():
    """If TAVILY_API_KEY is not set, fallback returns [] without error."""
    with patch.dict("os.environ", {}, clear=True):
        result = await _tavily_fallback("NVDA news")
        assert result == []
```

These are the minimum tests. The executor should flesh out mock patterns based on existing test conventions in the repo.

---

## 11. Known Limitations

- **Firecrawl in Python engine:** Not added as a second Python fallback after Tavily (would be diminishing returns; Tavily 1000/month is ample for the low-volume Python search calls).
- **SerpAPI catalyst mining in gap_fill.py:** Independent path with its own 3-key rotation; not touched.
- **Brave in news cascade:** Remains deprioritized; Brave circuit-breaker intact.
- **Exa in social.py:** Out of scope.
- **Plugin routing on empty results:** The plugin does NOT fall through on empty results (only on exceptions). This is correct behavior for provider-failure resilience (not result-quality enhancement).
