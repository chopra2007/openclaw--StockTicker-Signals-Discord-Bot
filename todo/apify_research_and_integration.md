# Apify — Research and Integrate a New Signal Source

**Status:** OPEN
**Created:** 2026-06-10

## Goal

Figure out whether Apify is worth wiring into the bot as a data source, and if so, build the integration. The free plan gives $5/month of compute credits — enough for meaningful polling if the right actor is chosen.

## What we already know

- **Proxy feature**: blocked on the free plan. The error is "Proxy external access feature isn't enabled for your account." Upgrading would be required. Not worth it yet.
- **Actors**: work fine on the free plan. Actors run on Apify's own servers, so they bypass the VPS IP blacklist that blocks Reddit and YouTube directly.
- **Reddit Scraper Lite** (`oAuCIx3ItNrs2okjQ`): confirmed working via the sync endpoint. Returns title, URL, body text, post date, username, subreddit. **Missing: scores, upvote ratios, comment counts.** The Lite actor is cheap (~$0.002/run). Async runs need investigation — a 5-item async run returned 0 dataset items despite succeeding; sync endpoint works reliably.
- **Reddit native API**: blocked on this VPS. Returns HTML instead of JSON. Apify is genuinely needed.
- **Cost estimate**: polling r/wallstreetbets every 30 min with Lite actor ≈ <$3/month.

## Candidates to research

Priority order (rough):

1. **Reddit** — r/wallstreetbets, r/options, r/stocks. Retail sentiment, ticker mentions, meme-stock crowding. Already partially tested. Main open question: can we get scores without the paid actor? Or is title+body sufficient for ticker extraction?
2. **Finviz** — news aggregator per ticker, pulls from 20+ financial sources. Cheap to scrape. Would give a fast per-ticker news feed.
3. **Seeking Alpha** — analyst upgrades/downgrades, earnings previews. Currently no analyst coverage in the bot. Apify has a dedicated actor.
4. **Google News per ticker** — Apify has an actor. Broader coverage than SearXNG for financial news, hits Google's actual news index.

## Open questions

- Can Reddit Scraper Lite return scores, or do we need the full actor (which timed out at 90s sync)?
- What does the Finviz actor actually return — is it per-ticker or site-wide?
- Seeking Alpha: does the free plan give enough compute to run it at useful frequency?
- Which source adds the most signal the bot doesn't already have? (Already have: TweetShift, YouTube/Supadata, Wolf newsletter, options flow, SearXNG web search, SEC filings.)

## Next steps (priority order)

1. Run a live test of the Reddit Scraper Lite on r/wallstreetbets with a longer async timeout. Confirm scores are present or absent. Run an LLM extraction pass on the returned post text to see if ticker mentions are clean enough to feed the signal engine.
2. Find and test the Finviz actor with a specific ticker — measure what fields come back.
3. Find and test the Seeking Alpha actor — measure fields and cost per run.
4. Pick the best candidate, write a design for how it fits into the bot's poll cycle, and bring to user for sign-off before building.

## Files involved

- `/home/openclaw/.openclaw/workspace/.claude/discover/yt-chain-fixes/probe_via_apify_proxy.py` — old proxy probe (not relevant to actors)
- `/root/.openclaw/.env` — `APIFY_TOKEN` and `APIFY_PROXY_PASSWORD` already set
- Actor IDs tested so far: `oAuCIx3ItNrs2okjQ` (Reddit Lite), `flcff389FkdnmdKDk` (Reddit Post Scraper — timed out)

## Probe results — 2026-06-10

Live probes run against the Apify API this session. Spend this session: **$0.19** (Reddit $0.14 + Finviz $0.00005 + Seeking Alpha $0.05). Account total now $0.35 of the $5 monthly credit (cycle resets June 14).

### The async "0 items" mystery — resolved

The data was there all along. All four datasets from the earlier session's runs contain items right now (6, 2, 2, 5 items). A fresh 25-post async run (`AWnSxRjQw71oTsfyj`) returned all 25 items the instant the run status flipped to SUCCEEDED — no write lag. The earlier "0 items" read was a client-side mistake: the dataset address answers with an empty list (not an error) while the run is still going, so reading too early looks exactly like "succeeded with no items". Correct pattern: start run → poll `/v2/actor-runs/{id}` until status SUCCEEDED → read `defaultDatasetId` **from the run object** → fetch items. Note the 25-post run took 114 seconds — that's why the sync endpoint (90s cap) times out on anything but tiny runs.

### 1. Reddit Scraper Lite (`oAuCIx3ItNrs2okjQ`) — works, but pricier than we thought

- **Fields per post:** title, body, url, id, username, communityName, createdAt, scrapedAt, dataType, html. **Definitively NO scores, upvote ratios, or comment counts** — confirmed on 25 real posts. Set `skipComments: true` or comments pollute the results (an earlier 5-item run came back 4 comments + 1 post).
- **Cost reality:** pricing is **per result stored** ($0.004/post) plus $0.02 per GB of memory at start. Our 25-post run cost **$0.14** ($0.04 start at default 2GB + $0.10 for 25 posts). Starting it with 512MB–1GB memory cuts that to ~$0.12.
- **The old "<$3/month" estimate was wrong by ~60x.** At a 30-min poll (1,440 runs/month, 25 posts each): **~$170–200/month**. The free $5 covers roughly **40 runs of 25 posts per month ≈ 1–2 polls per day.**
- Two sample posts (bodies truncated):

```json
{"title": "Supermicro Announces Proposed $7.0 Billion of Equity and Equity-linked Financing Transactions To Fund AI Orders",
 "body": "SMCI is known for shady accounting and despite almost getting delisted for not filing 10-k last year... Then, 3 executives were arrested for smuggling Nvidia chips...",
 "username": "stuntondeezh0es", "communityName": "r/wallstreetbets",
 "createdAt": "2026-06-09T21:47:16.000Z", "dataType": "post",
 "url": "https://www.reddit.com/r/wallstreetbets/comments/1u1iyle/..."}
```
```json
{"title": "UPST May Be On Its Last Leg",
 "body": "TL;DR: it seems unlikely that Upstart will experience the glorious stock gains in 2020-2021... they may be in trouble and need a bank charter...",
 "username": "saboteursolotario", "communityName": "r/wallstreetbets",
 "createdAt": "2026-06-09T20:35:00.000Z", "dataType": "post",
 "url": "https://www.reddit.com/r/wallstreetbets/comments/1u1h0ax/..."}
```

### Ticker-extraction quality on the 25 real posts (manual read, no AI calls)

Verdict: **titles + bodies are good enough to extract tickers, but only with the AI-extraction approach we already use — simple pattern-matching would be noisy.**

- Zero `$TSLA`-style cashtags in the whole 25-post sample.
- Clean cases: post "UPST May Be On Its Last Leg" — ticker is the first word of the title. Post "Supermicro Announces..." — company name in title, bare ticker SMCI in body. Both trivial.
- Trap cases: "With the CPI coming in, Robinhood prediction has that it will be >4.2%" — CPI here is the inflation report, not a stock; bare-uppercase matching would false-positive on CPI, PDT, AI, US, TL;DR. And "I thought spy could be traded during extended hour" — SPY in lowercase, which pattern-matching would miss.
- ~8 of 25 posts are image/meme posts whose body is just boilerplate ("submitted by /u/... [link] [comments]") — title is the only text.
- No score/comment fields means no way to rank by crowd engagement; every post weighs the same.

### 2. Finviz — Apify NOT needed; the VPS can scrape it directly for free

- Direct test: `https://finviz.com/quote.ashx?t=NVDA` from this VPS returned **HTTP 200 with the full page including 100 news headlines** (timestamp, headline, link, source name like "Stocktwits"/"DigiTimes"). Finviz does not block our IP. **Per-ticker news from Finviz costs $0.**
- The Apify store has no Finviz *news* actor anyway — all 5 candidates are stock-screener scrapers (rows of tickers + fundamentals). Probed the cheapest (`nexgendata/finviz-stock-screener`, $0.02/result): it accepts any screener URL, but the run got **403 Forbidden from Finviz's anti-bot on both of Apify's proxy groups** and exited with 0 items (cost: $0.00005). Ironic: Apify's shared proxies are blocked where our own VPS isn't.

### 3. Seeking Alpha (`doesaiknow/seeking-alpha-api-news-dividend-data`) — works, cheap, best fit for the budget

- Run: NVDA news, 10 items, **$0.05, 5 seconds**. Direct access from the VPS is blocked (captcha wall), so Apify genuinely is the way in.
- **Fields per article:** headline, url, article_id, author, date_iso, **comments_count** (engagement!), tickers, category (news/earnings), content_hash, is_new_since_last_run, plus a built-in signal/confidence guess (useless — everything came back "neutral 0.5"). Headlines + metadata only; article bodies are paywalled.
- Per-ticker by design (`tickerSymbols: ["NVDA"]`), ~40 recent articles available per ticker.
- **Pricing: $0.005 per item, NO start fee** — a poll that finds nothing new costs $0. With `onlyNewSinceLastRun: true` it becomes a delta feed: you only pay for new articles. NVDA produces roughly 5–10 articles/day → **~$1–1.50/month per ticker at ANY poll frequency** (cost scales with article count, not run count). A 3-ticker watchlist ≈ $3.50–4.50/month — fits inside the free $5.

### Monthly cost at a 30-min poll cadence (1,440 runs/month)

| Source | Cost/run | Monthly at 30-min | Fits free $5? |
|---|---|---|---|
| Reddit Lite, 25 posts | $0.12–0.14 | ~$170–200 | No — only ~1–2 runs/DAY fit |
| Reddit Lite, 10 posts | $0.06 | ~$86 | No |
| Seeking Alpha delta, per ticker | $0 when no news; $0.005/new article | ~$1–1.50/ticker | Yes, up to ~3 tickers |
| Finviz | n/a — scrape direct from VPS | $0 | n/a |

### Recommendation

- **Most non-overlapping signal in kind: Reddit/WSB retail sentiment** — nothing in the bot covers retail crowding today (TweetShift is analyst Twitter). But the Lite actor's per-post pricing makes real-time polling impossible on the free plan, and the missing score/comment fields blunt its main value (you can't tell a 5,000-upvote frenzy from a zero-vote shitpost). Honest ceiling: 1–2 daily snapshots, titles-only signal, ~$4/month — a daily "what's WSB obsessing over" pulse, not a live source.
- **Best practical Apify pick: Seeking Alpha delta feed.** Genuinely new coverage type (analyst/news wire with engagement counts — the bot has no analyst coverage), per-ticker, real engagement field (comments_count), delta pricing that fits the free plan at full 30-min cadence for a small watchlist.
- **Finviz: build it WITHOUT Apify.** Direct scrape from this VPS works today and is free; a per-ticker news feed (100 headlines/ticker) is sitting there at `finviz.com/quote.ashx?t=TICKER`.
- Suggested split if we proceed: Seeking Alpha via Apify (watchlist tickers, 30-min delta polls) + Finviz direct scraper (free) + optional Reddit once-daily snapshot. Design doc for user sign-off is the next step per this TODO.

### Session notes — 2026-06-13 (discover run todo-sweep)
- **Live re-validation: the recommended actor (`doesaiknow` Seeking Alpha) is DEAD today** — 0 items (NVDA) / 500 error (AAPL); it's a proxy to the author's own backend, outside our control. Worked 6-10, broken 6-13 (the "code works, API doesn't" trap). Budget fine: $4.65 of $5 free, resets 2026-06-14.
- **Likely SKIP #34:** the bot already has free per-ticker news via the `google_rss` cascade tier (config:98) + Finnhub. The only unique Apify value was Seeking Alpha's analyst/engagement layer — and that actor's dead. Gemini suggested Yahoo Finance RSS as a free alternative, but I smoke-tested it → **404 (deprecated)**.
- **Plan:** re-probe `doesaiknow` after the 6-14 reset (~$0.05); build the Seeking Alpha news-cascade tier (flag-OFF, budget fail-safe at $4) ONLY if it returns data 2 days running with its unique engagement field; else drop. Full plan: .claude/discover/todo-sweep-2026-06-13/research/apify.md + final-plan.md §3.

### Correction — 2026-06-13 (deeper diagnosis after user pushback)
The "actor is DEAD/down" wording above was WRONG (asserted without checking the codes — the exact "never assume down" failure). Real diagnosis: the actor runs fine every time (HTTP 200, exit 0, $0 for 0-item runs); its upstream backend returns **0 items for every ticker AND both endpoints (news + dividends)**, each logging `credits_estimate: 5`. It returned 10 NVDA items on 6-10 with the identical input; the earlier AAPL 500 is now a 200 (intermittent). Our Apify account is fine ($4.65/$5). → Most likely an **upstream credit/rate limit on the author's private backend**, NOT an outage. Also: the Apify $5 reset (6-14) does NOT fix this (that's our budget, not the constraint); only the author's backend recovering does — re-probe periodically, don't tie it to the Apify reset.
