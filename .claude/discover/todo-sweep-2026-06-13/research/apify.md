# TODO #34 — Apify signal source: live re-validation (2026-06-13)

> ## DECISION 2026-06-13: SKIP + REMOVE the Apify keys (user directive)
> **Did we decide Apify has no viable use? YES.** No budget-viable actor delivers reliably (the only
> one that fit the free $5, `doesaiknow`, returns 200-empty/500 today), and the unique value (per-ticker
> news) is **already covered for free** by the `google_rss` cascade tier + Finnhub. So: do not build #34.
>
> **Important safety finding — it CANNOT "accidentally trigger" today.** A full grep confirms **zero
> Apify references in any code, config, or script** (`consensus_engine/`, `scripts/`, `config/` → 0
> hits). Nothing reads the Apify keys; they are orphaned environment variables. (`xxxxxAPIFY2_TOKEN`
> even carries a manual `xxxxx` disable-prefix already.) So there is no running code path that could
> fire Apify — removing the keys is pure tidy-up, not a functional change.
>
> **Removal plan (a clean, safe cleanup step — execute at the start of the build phase):**
> Delete these 3 lines from each of the 3 env files, then `chown openclaw:openclaw` the files (the
> ownership trap: a root-edited .env crash-loops consensus-engine on next restart — see memory):
>   - `APIFY_TOKEN`, `APIFY_PROXY_PASSWORD`, `xxxxxAPIFY2_TOKEN`
>   - files: `/home/openclaw/.openclaw/.env`, `/home/openclaw/.openclaw/.env.service`,
>     `/home/openclaw/.openclaw/workspace/.env`
> No code/config edits needed (nothing references them). This research doc + TODO #34 stay as the
> historical record; mark TODO #34 SKIPPED/closed rather than building it.
>
> The original research below is retained for the record.


**Bucket: 1 (NOT BUILT).** Nothing in `consensus_engine/` calls Apify — confirmed by grep across all scanners (`grep -niE "apify" consensus_engine/` → 0 real hits). This is a research/design item, not a broken or off feature.

**Bottom line up front:** The free $5 budget is healthy ($4.65 left, resets in ~1 day). But the headline recommendation from the 2026-06-10 research — "Seeking Alpha delta feed via the `doesaiknow` actor" — **failed live re-validation today.** That actor is a thin proxy to a third-party backend that is currently returning errors (500) / empty results (0 items). Finviz (the free, no-Apify option) still works but its per-ticker page is mostly sector noise, not ticker-specific news. **Recommendation flipped: do not build the Apify Seeking Alpha integration on the `doesaiknow` actor as-is. Re-probe it after the credit reset; if still broken, the cheapest viable path is the free Finviz direct scrape with a strict relevance filter.**

---

## 1. Live Apify balance & usage (verified today)

Pulled from `GET /v2/users/me`, `/v2/users/me/limits`, `/v2/users/me/usage/monthly`:

- **Plan:** FREE. `maxMonthlyUsageUsd: 5`, `maxMonthlyActorComputeUnits: 625`, `maxConcurrentActorRuns: 25`, `dataRetentionDays: 7`.
- **Billing cycle:** `2026-05-15 → 2026-06-14 23:59:59 UTC`. **Resets in ~1 day** (tomorrow). Note this is mid-month (the 15th), not the 1st.
- **Used this cycle: $0.3505 of $5.00 → $4.65 left.**
- **Where the $0.35 went:** essentially all of it (`$0.35005`) is `PAID_ACTORS_PER_EVENT` on **2026-06-10** — i.e. last session's Reddit Lite + Seeking Alpha probes. Every other day is microscopic storage cost (~$0.0000045/day for kept datasets). So polling nothing = effectively free; the cost is per-actor-event only.
- **Proxy external access:** still `isEnabled: false` ("isn't enabled for your account... upgrade") — unchanged, blocks direct proxy use. Only datacenter group `BUYPROXIES94952` (5 IPs) is available; RESIDENTIAL/GOOGLE_SERP show 0 available.

This session's three Seeking Alpha probes cost a combined **$0.0000455** (4.5 millicents) — because all three returned 0 billable items. Balance moved $0.3504526 → $0.3504555.

---

## 2. Seeking Alpha probe — FAILED live (the key finding)

Actor: `doesaiknow/seeking-alpha-api-news-dividend-data` (the one the prior research recommended). I ran it three times today using the correct async pattern (POST run → poll `/v2/actor-runs/{id}` to SUCCEEDED → read `defaultDatasetId` from the run object → GET dataset items).

| Run | Input | Result | Dataset items |
|---|---|---|---|
| 1 | `{tickerSymbols:["NVDA"], onlyNewSinceLastRun:false, maxItems:10}` | SUCCEEDED (54s) | **0** |
| 2 | full explicit input (`dataType:news, analysisType:all, signalFilter:any, includeRawHeadline:true`) | SUCCEEDED | **0** |
| 3 | `{tickerSymbols:["AAPL"], maxItems:5}` | **FAILED** | **0** |

**The run logs explain why — and reveal a risk the prior research missed.** The actor does NOT scrape seekingalpha.com itself. It calls a hidden third-party backend owned by the actor author:

```
INFO  Dispatching to backend {"dataType":"news","endpoints":["/v1/seekingalpha"],"tickers":["NVDA"]}
INFO  Received 0 item(s) from /v1/seekingalpha {"count":0,"pages_fetched":1,"credits_estimate":5}   ← NVDA: 200 but empty
ERROR Backend /v1/seekingalpha 500 Internal Server Error: Internal Server Error                      ← AAPL: 500
```

So this actor is a **single hidden point of failure outside our control.** On 2026-06-10 it returned 10 NVDA articles; today the same actor with the same inputs returns nothing (NVDA) or a 500 (AAPL). The actor's own code is healthy (exit 0); its upstream `doesaiknow` API is down/degraded right now.

### Input schema (confirmed from the build object — these are the real fields)
`dataType` (news|dividends|both, default news), `tickerSymbols` (array), `maxItems` (int, default 100), `analysisType` (news|earnings|analysis), `signalFilter`, `includeRawHeadline` (bool), `onlyNewSinceLastRun` (bool — the delta switch), `includeHistory`. **My inputs were valid** — the 0 items is a backend failure, not an input error.

### Fields the prior research claims (NOT re-confirmed today, because 0 items came back)
The 2026-06-10 note lists: headline, url, article_id, author, date_iso, comments_count, tickers, category, content_hash, is_new_since_last_run, plus a useless built-in "neutral 0.5" signal. **I could not re-verify these today — the actor returned no data to inspect.** Treat the field list as unconfirmed until the backend recovers.

### Delta pricing — confirmed in principle, but moot while broken
Pricing model is `PAY_PER_EVENT` at $0.005/item with no start fee, so **0 items = $0** (today's runs prove this — $0.0000455 total across 3 runs). When it works, the delta-feed economics from the prior research hold ($1–1.50/month/ticker). But "works" is the open question.

### Alternative Seeking Alpha actors exist — but they're far pricier
Store search (`/v2/store?search=seeking+alpha`) returns 49 actors. The two real direct-scraper alternatives:

| Actor | Runs | Pricing |
|---|---|---|
| `fortuitous_pirate/seekingalpha-stock-analysis-scraper` | 240 | **$0.15 start + $0.02/result** → one ~40-article NVDA run ≈ **$0.95** |
| `parseforge/seekingalpha-scraper` | 36 | per-result event (price not published) |

`fortuitous_pirate` at $0.95/run is ~190× the `doesaiknow` per-item rate. A 3-ticker watchlist polled even twice a day would be ~$170/month — **does not fit the free $5.** I did not spend money running these (the budget guardrail + the start fee make a probe wasteful when the math already rules them out for polling).

---

## 3. Finviz — works free from the VPS, but URL changed and per-ticker relevance is LOW

- **URL changed since the 2026-06-10 note.** `https://finviz.com/quote.ashx?t=NVDA` now **301-redirects to `https://finviz.com/quote?t=NVDA`**. A plain GET to the old URL returns a 0-byte 301. With `-L` (follow redirect) the new URL returns **HTTP 200, 300 KB, 100 news rows.** Any scraper must use the new path or follow redirects.
- **Parses cleanly:** the `id="news-table"` block has 100 `<tr>` rows, each with a timestamp cell (`Today 10:48AM` / `Jun-12-26 10:07PM`), the source name (in the `onclick="trackAndOpenNews(event, 'Stocktwits', ...)"` and a label), the headline (`class="tab-link-news"`), and the article URL. No Apify needed — the VPS IP is not blocked by Finviz.
- **BUT per-ticker relevance is poor.** Smoke-tested the bot's own `_classify_catalyst` + `_headline_relevant` on the 18 most-recent real NVDA-page headlines: **only 1 of 18 actually mentions NVDA** ("Nvidia turns to Vera CPU in China as H200 sales stall"). The other 17 are SpaceX, AMD, Micron, Broadcom, Magnificent-Seven-ETF stories. Finviz's per-ticker news page is padded with sector/market-wide news, so the bot's relevance filter would correctly drop ~94% of it. Finviz is a **sector-news firehose**, not a precise per-ticker feed.
- The classifier handled all headline text cleanly (no crashes, sensible labels — it tagged the two "IPO" stories, left generic market news as `None`, which is the intended behavior since generic news still feeds the LLM thesis).

---

## 4. Reddit Lite — conclusion restated (not re-run)

Per 2026-06-10: `oAuCIx3ItNrs2okjQ` works but bills **per result stored ($0.004/post) + memory start fee** → ~$0.12–0.14 per 25-post run → **~$170–200/month at a 30-min poll.** Free $5 only covers ~40 runs/month (1–2 daily snapshots). No score/upvote/comment fields, so no way to rank by crowd engagement. **Not viable for polling on the free plan.** Not re-tested today (the economics are settled and a probe would burn budget for no new information).

---

## 5. Smoke test — does the bot's news extraction handle this text cleanly?

Yes. I ran the production `_classify_catalyst` and `_headline_relevant` functions (copied verbatim from `consensus_engine/scanners/news.py`) against the real Finviz NVDA headlines pulled live. No errors; sensible classification; the relevance filter behaves as designed (drops off-ticker headlines). Seeking Alpha headlines are the same shape (short English headline + source + ticker tag), so the existing pipeline would handle them identically — the bot already extracts tickers from Finnhub/Google-RSS headlines via this exact path. **No extraction work needed; the blocker is purely source availability/quality, not parsing.**

---

## 6. Integration design (if the Seeking Alpha backend recovers)

The cleanest fit is a **new tier in the existing news cascade**, not a standalone scanner — `consensus_engine/scanners/news.py` already has `news_cascade(ticker)` with a config-driven tier list (`news.cascade.tiers = [recent_earnings, finnhub, google_rss, brave, searxng]`) and a `tier_funcs` dict. Each tier is one `async def _search_X(ticker) -> Optional[CatalystResult]`.

- **Seeking Alpha tier** (`_search_seeking_alpha`): POST the `doesaiknow` actor with `{dataType:"news", tickerSymbols:[ticker], onlyNewSinceLastRun:true, maxItems:10}`, poll to SUCCEEDED, read dataset items, build a `CatalystResult` from the top relevant headline. Add `"seeking_alpha"` to the cascade tier list and `tier_funcs`. `onlyNewSinceLastRun:true` makes it a delta feed → $0 when nothing new.
- **DB table** (mirrors the existing `reddit_posts` / `signal_events` pattern in `db.py`): `seeking_alpha_articles(article_id TEXT PRIMARY KEY, ticker, headline, url, author, date_iso, comments_count INT, category, content_hash, recorded_at)` — dedup on `article_id`/`content_hash` so we never re-alert or re-pay for the same article. Add a `CREATE TABLE IF NOT EXISTS` block (the DB auto-creates tables on init; no migration framework needed).
- **Config keys** in `config/consensus.yaml`: `seeking_alpha.enabled: false` (ship flag-OFF), `seeking_alpha.watchlist: [...]`, `seeking_alpha.actor_id`, `seeking_alpha.poll_minutes: 30`, `seeking_alpha.monthly_budget_usd: 4.0` (hard stop — see fail-safe).
- **Feeds:** the `CatalystResult` flows into the signal engine exactly like Finnhub/Google-RSS news today, and into `!all` via the same news-catalyst surface.

### Overlap with existing sources
- **TweetShift** = analyst *Twitter* (individual analysts' tweets). **YouTube/Supadata** = video commentary. **Wolf** = one newsletter. **Options/SEC** = flow + filings. **SearXNG/Finnhub/Google-RSS** = general web/news search.
- **Seeking Alpha is genuinely non-overlapping in kind:** it's the analyst/news-wire layer with a real engagement signal (`comments_count`) that nothing else in the bot has. So the *concept* is sound — the problem is purely that the cheap actor delivering it is currently broken.

### Monthly-cost projection (proving the free-$5 fit, IF the actor works)
Pricing = $0.005/new article, $0 when nothing new (delta mode). Article volume drives cost, not poll frequency.

| Watchlist | New articles/day (est.) | Articles/month | Cost/month | Fits $5? |
|---|---|---|---|---|
| 3 tickers | ~5–10/ticker → ~20/day | ~600 | **~$3.00** | Yes |
| 5 tickers | ~30/day | ~900 | **~$4.50** | Tight — set budget cap |
| 8+ tickers | ~50+/day | 1500+ | **$7.50+** | No |

**Verdict: a 3-ticker delta watchlist at 30-min cadence fits the free $5 with headroom (~$3/mo, $2 to spare). 5 tickers is the ceiling and needs the budget cap. The cost is independent of poll frequency — polling more often just finds the same new articles sooner.**

### Fail-safe for when the $5 runs out mid-month
This is essential and the prior research did not specify it:
1. **Pre-flight budget gate.** Before each run, the tier calls `/v2/users/me/limits` (or tracks a local running total in `api_usage_daily`, the table already used for Brave) and **skips the Apify call if `monthlyUsageUsd >= seeking_alpha.monthly_budget_usd` (e.g. $4.0).** Leaves $1 buffer below the $5 hard limit so storage/other costs never push us over.
2. **Graceful degradation.** When the budget gate trips, or the actor returns 0 items / a 500 (today's exact failure modes), the tier returns `None` and the cascade simply falls through to the next tier (Finnhub/Google-RSS) — no crash, no alert gap. The bot already does this for any failing tier (`_news_cascade_serial` catches exceptions per-tier and continues).
3. **Apify's own hard cap.** The FREE plan stops actor runs at $5 server-side, so the absolute worst case is runs start failing — which the per-tier try/except already swallows.

---

## 7. Risks

1. **PRIMARY RISK — the recommended actor is a black-box proxy that's broken today.** `doesaiknow/seeking-alpha-api-news-dividend-data` doesn't scrape SA; it calls the author's private `/v1/seekingalpha` backend, which returned 0 items (NVDA) and a 500 (AAPL) in live tests today. We have no control over or visibility into that backend's uptime. Building on it = building on someone else's hobby API.
2. **Field set unconfirmed.** Because the actor returned nothing today, the field list (comments_count, date_iso, etc.) from 2026-06-10 could not be re-verified.
3. **Finviz per-ticker relevance is low** (1/18 on-ticker in the live sample) — usable only as a sector firehose with a strict relevance filter, not a precise per-ticker feed.
4. **Finviz URL drift** — already changed once (`.ashx` → clean path). A scraper must follow redirects or it silently gets 0 bytes.
5. **Budget reset timing** — the cycle resets the 15th, not the 1st; the $5 ceiling is the same but the date matters for any "monthly" accounting.

---

## 8. Recommendation

- **Do NOT build the Seeking Alpha Apify integration right now.** Its only budget-viable actor (`doesaiknow`) failed live re-validation today. The alternatives ($0.95/run) don't fit free $5 for polling.
- **Re-probe `doesaiknow`** with a single NVDA delta run (cost ~$0.05 if it returns ~10 items, $0 if still broken). If it returns real data two days running, the integration design in §6 is ready to build flag-OFF with the budget fail-safe. If it's still 500/empty, abandon this actor.
  > **[codex revision 2026-06-13 — two corrections]**
  > 1. **The "author's private backend hit a credit/rate limit" root cause is ASSERTED, not proven —
  >    label it UNVERIFIABLE.** `200 + 0 items + credits_estimate:5` (and an intermittent 500) is also
  >    consistent with: a changed/blocked Seeking Alpha upstream, an actor schema/regression, an auth
  >    issue, or endpoint filtering. We cannot see inside the actor's backend, so don't write the plan
  >    around a guessed cause. Write it around the OBSERVED symptom only: *"this actor returns 200-empty
  >    or 500 intermittently and cannot be relied on."* (This is the same trap as the 2026-06-13
  >    comm-check failure — don't name a provider/backend cause you didn't verify.)
  > 2. **Re-probe timing must NOT be anchored to the 2026-06-14 Apify reset.** This doc itself says the
  >    Apify $5 reset resets OUR budget, which is not the constraint — what has to recover is the actor's
  >    upstream, on its own timeline. So "re-probe after 6-14" is anchored to an irrelevant event.
  >    **Re-probe on a periodic schedule or a manual gate**, not because the Apify billing cycle rolled over.
- **If Seeking Alpha stays dead, the only free Apify-adjacent win is the Finviz direct scrape** (no Apify, $0) — but gate it hard with the existing `_headline_relevant` filter, because its per-ticker page is ~94% off-ticker sector news. Honest value: a cheap supplementary news tier, not a high-signal source.
- **Reddit Lite and the paid SA scrapers stay out** — both blow the free $5 for any real polling cadence.

**Net: the $5 budget is fine ($4.65 free); the problem is that the one source that fit the budget isn't delivering data today. The honest call is to re-test after the reset before committing build effort.**
