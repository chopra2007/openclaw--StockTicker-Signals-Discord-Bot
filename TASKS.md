# TASKS.md - Persistent Reddit Crawler & Research Pipeline

## SCHEDULE
Run every 4 hours via OpenClaw scheduler (cron) or heartbeat integration.

## TASK 1 — Incremental Crawl (reddit_crawler.py)
**Target Subreddits:** wallstreetbets, stocks, investing, options, pennystocks, squeeze_plays
**Strategy:**
- Fetch last 24h of posts/comments.
- Primary Endpoint: Pushshift JSON (`https://api.pushshift.io/reddit/search/submission/...`)
- Fallback Endpoint: Reddit JSON (`https://www.reddit.com/r/{sub}/new/.json`)
- Rotate subreddit order each run.
- Sleep 8-12 seconds between requests to avoid rate limits.
- **Cache:** Store in `~/.openclaw/workspace/reddit_cache.db`.
  - Table: `posts` (id TEXT PRIMARY KEY, subreddit TEXT, created_utc INTEGER, title TEXT, selftext TEXT, author TEXT, score INTEGER, num_comments INTEGER, fetched_at INTEGER)
  - Only insert if `id` does not exist. Process only new rows.

## TASK 2 — Ticker Extraction (2-Stage)
**Regex:** `\b[A-Z]{1,5}\b|\$[A-Z]{1,5}\b`
**Validation:** Match against valid US exchange symbols (NYSE/NASDAQ/AMEX).
**Blacklist Filter:** Cross-reference extracted candidates against `TICKER_FILTER.md` (AI, ON, IT, DD, THE, FOR, ARE, etc.).

## TASK 3 — Metrics & Thresholding
Compute per-ticker metrics:
- `mentions_24h`
- `unique_authors`
- `upvote_velocity` (score sum / age hours)
- `momentum` (24h vs previous 24h baseline)

**Threshold to trigger research:**
`mentions_24h >= 8` AND (`momentum > 1.5x baseline` OR `unique_authors >= 5`)

## TASK 4 — Sub-Agent Research
For tickers meeting the threshold, spawn a researcher sub-agent (`sessions_spawn`):
- Summarize Reddit sentiment (short bullet points).
- Search recent catalysts (news, 8-K, earnings, short interest spike).
- Flag risks (low float, dilution, pump patterns).

## TASK 5 — Discord Report (!trend digest)
Output a ranked brief posted directly to the Discord channel at the end of every run.
