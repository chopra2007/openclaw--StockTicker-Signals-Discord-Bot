# Brave Search API monthly cap maxed out

**Status:** DONE 2026-05-22.

**Layperson:** The Brave Search free tier got fully used up this month ($5/$5). Until the cap resets or you upgrade, the news cascade loses its Brave tier (still has Finnhub / Google RSS / SearXNG, so it degrades rather than breaks).

**Surfaced during gemini-quality-all-command discover run (2026-05-19).** Live probe from `gap_fill._search_brave_raw` returned HTTP 402 with body:
```json
{"error":{"message":"Usage limit exceeded","status":402,
"metadata":{"plan":"Search","current_spend":5.0,
"usage_limit":5.0,"usage_limit_type":"monthly","component":"api"}}}
```
The session moved to SerpAPI for catalyst mining (free tier was plenty; pre-flight worked first try). But the production news cascade in `consensus_engine/scanners/news.py` still tries Brave on every alert and will fail silently the rest of the month.

**Where the key lives:** `BRAVE_SEARCH_API_KEY` in `/home/openclaw/.openclaw/.env`. Counter accounting at `scanners/news.py:330` `_brave_budget_ok()` — note this only checks the local per-day budget (`news_cascade.brave_daily_budget: 50`), not the upstream Brave monthly cap, so it'll happily fire requests that 402 until the cap resets.

## Fix options

1. Add credit to the Brave Search plan (~$5/mo for 5k queries).
2. Add a 402-detection circuit-breaker in `_search_brave` so we stop firing after the first usage-limit response — saves the per-call latency cost of always-failing requests.
3. Bump Brave to a lower tier of the cascade so SearXNG fires first (currently Brave is between SearXNG and Finnhub).

**Earliest reset:** roughly the first of next calendar month per Brave's billing cycle.
