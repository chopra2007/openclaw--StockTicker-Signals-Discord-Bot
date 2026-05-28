# Pass 3 — Adversarial Review + Stress Test

## Source: Adversarial critic + security reviewer agents (parallel), plus orchestrator verification of disputed claims.

---

## Critical Findings — Required Plan Changes

### C1 — Feature 2 must modify `search_searxng()` in `searxng.py`, not `gap_fill.py`

**Finding:** `search_searxng()` is called from 3 places: `news.py:407`, `sources.py:87`, `gap_fill.py:108`. Patching only `gap_fill.py` leaves `news.py` and `sources.py` using SearXNG with no fallback.

**Resolution:** Add the Tavily fallback inside `search_searxng()` itself (in `scanners/searxng.py`). All 3 callers benefit automatically. No changes to `news.py`, `sources.py`, or `gap_fill.py` needed for the fallback.

**Why `search_searxng()` instead of a new wrapper:** The function signature (`query: str → list[dict]`) is already the right shape. A simple "if result is empty, try Tavily" at the bottom of the function is ~10 lines and covers everything.

### C2 — Plugin fallback fires on exception, not empty results (confirmed from source)

**Finding:** Plugin routing loop: `if (strictProviderMode || (result2.results || []).length >= count || errors.length === 0) break`. The `errors.length === 0` clause means: if the first provider succeeds without throwing (even returning `[]`), the loop stops. Fallback only fires if a provider throws an exception.

**Implication for the plan:**
- **Agent path (plugin):** Plugin correctly handles "SearXNG goes DOWN" (throws connection error → tries Tavily). Does NOT provide "SearXNG returns empty results for this query → try Tavily for richer results." That's acceptable — the acceptance criteria is about SearXNG being unavailable, not about result quality per query.
- **Python engine path (searxng.py):** Fallback should trigger on BOTH exception AND empty results (want Tavily's results if SearXNG has nothing). This is implemented in `search_searxng()` directly.

---

## Major Findings — Plan Adjustments

### M1 — Key format in openclaw.json: try env ref first, plain string fallback

**Finding:** The critic noted other plugins use `{"source":"env","provider":"default","id":"X"}` format while the plan proposed plain strings. The web-search-plus-plugin-v2 reads `pluginConfig?.tavilyApiKey` with `maybeString()`. If OpenClaw resolves env refs before passing to plugin, env ref format works; if not, the object is passed as-is and `maybeString()` returns null (key ignored).

**Resolution:** At execution time, first try env ref format for both keys. Test immediately with a `web_search_plus` call. If Tavily/Firecrawl are not called (agent falls through to SearXNG only or key shows as missing), switch to plain strings. Plain strings are safe: `openclaw.json` is at `/home/openclaw/.openclaw/openclaw.json`, outside the git workspace, not in the public repo.

Verification command: `sudo -u openclaw openclaw agent --local --agent main --message "search for NVDA news using web_search_plus and tell me which provider was used"`

The plugin's response includes routing metadata (`fallback_used`, `provider` field) that proves which provider ran.

### M2 — Tavily quota observability

**Finding:** If SearXNG is down, Tavily handles ALL Python engine calls. With no counter, quota exhaustion (1000/month) would be invisible until it hits 402.

**Resolution:** `search_searxng()` should log a WARNING whenever Tavily fallback fires: `logger.warning("searxng: empty/failed, using tavily fallback for query: %s", query)`. This gives visibility in logs without adding a counter (low volume; not worth the state management).

For the agent path: the plugin already logs `routing.fallback_used: true` in its response metadata.

### M3 — Dual-tool situation: disable searxng built-in cleanly

**Finding:** If `searxng` is removed from `plugins.allow` but `tools.web.search.provider: "searxng"` remains, OpenClaw may log a warning or silently degrade on the next restart.

**Resolution:** Change `tools.web.search.provider` from `"searxng"` to `null` or remove the key. Keep `searxng` in `plugins.allow` — there's no harm in having the plugin enabled as a fallback signal, and it avoids breaking anything that reads the allow list. The important change is retiring `web_search` as the agent's active tool and relying on `web_search_plus` instead.

Actually simpler: keep searxng in the allow list (it's harmless), set `tools.web.search.provider` to `"web-search-plus-plugin-v2"` if that's a valid value, or remove the provider key entirely. The agent will use `web_search_plus` from the plugin directly.

### M4 — Add `timeout` to TavilyAdapter HTTP call

**Finding (security reviewer):** No timeout on Tavily HTTP call could stall the consensus loop if Tavily is slow.

**Resolution:** Add `timeout=aiohttp.ClientTimeout(total=10)` to the aiohttp session in `TavilyAdapter.search()`. 10 seconds matches the existing pattern in `BraveAdapter`.

---

## Dismissed Findings

| Critic claim | Verdict | Evidence |
|---|---|---|
| `searxngAllowPrivate` key name unverified | DISMISSED | Key confirmed in plugin manifest configSchema AND in dist/index.js:155 |
| `.env.service` might not have TAVILY_API_KEY | DISMISSED | `.env.service` confirmed to have both TAVILY_API_KEY and FIRECRAWL_API_KEY |
| Plain keys in openclaw.json regress env-indirection pattern | NOTED, not blocking | openclaw.json is outside git; plain strings are safe. env ref format is tried first. |

---

## CCG Synthesis (compressed — no live CCG run needed)

The problem is well-characterized enough that a full ccg call would add noise. Key cross-perspective checks:

**Strongest reason to ship Feature 1 (plugin config):** Config-only change, reversible in 30 seconds, covers the user-visible acceptance test.

**Strongest reason to drop Feature 1:** If env ref resolution fails AND the user is uncomfortable with plain keys in openclaw.json, the agent path stays SearXNG-only. Risk: low — plain keys are safe in this file.

**Strongest reason to ship Feature 2 (Python fallback):** Covers 3 call sites simultaneously; the !all and news cascade paths get resilience.

**Strongest reason to drop Feature 2:** 40 lines of code in a working system. Could be deferred. Counter: the code follows an established pattern; risk of regression is minimal.

**Single-model risk:** None — both features are independently motivated by the acceptance criteria.

---

## Refined Feature Set

**Feature 1 (agent path):** Configure `web-search-plus-plugin-v2` with SearXNG + Tavily + Firecrawl. Try env ref key format first; fall back to plain strings if unresolved.

**Feature 2 (Python engine):** Modify `search_searxng()` in `scanners/searxng.py` to call Tavily if SearXNG returns `[]` or throws. Add Tavily WARNING log. Add `timeout=` to HTTP call. All 3 callers (news.py, sources.py, gap_fill.py) benefit automatically.

---

## Concrete Limitations (what this doesn't fix)

- **SerpAPI catalyst mining in gap_fill.py** — uses its own 3-key rotation and is separate from SearXNG. Not touched; already has resilience.
- **Brave circuit-breaker** — remains in news.py; Brave is still installed but deprioritized (correct).
- **Firecrawl in Python engine** — not wired as Python fallback (only Tavily). Firecrawl is a scraper-first tool; adding it as a search fallback after Tavily would be diminishing returns. Defer.
- **Exa social trends scanner** — `scan_google_trends_exa()` in social.py uses Exa directly; out of scope for this fix.
