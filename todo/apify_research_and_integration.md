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
