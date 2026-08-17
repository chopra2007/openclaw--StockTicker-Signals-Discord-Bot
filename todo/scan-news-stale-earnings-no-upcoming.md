# `!scan`'s news section shows stale earnings and never mentions an upcoming report

**Status:** DONE 2026-08-16
**Created:** 2026-08-16

**CURRENT STATUS (2026-08-17):** DONE. Recent earnings can win the news search only for seven calendar
days after the company actually reported. The quarter-end date is never used as a substitute. `!scan`
now checks a ticker-filtered 90-day Finnhub calendar and shows the earliest non-past report date on its
own line. Live Discord checks showed NVDA's next report on 2026-08-26 and correctly omitted the line
for SPY.

## What the user saw

Ran `!scan NVDA` on 2026-08-16. The news section showed "Recent earnings catalyst for NVDA: 2026-06-30"
— an earnings print from about 7 weeks earlier — even though there's been plenty of real NVDA news
since then, and NVDA's next earnings report is coming up soon. Neither the fresher news nor the
upcoming report showed up anywhere on the card.

## Root cause — two separate bugs, confirmed by reading the code and live data

**1. No staleness check, and "first hit wins" with no fallback.**
`news_cascade()` (`consensus_engine/scanners/news.py:519`) runs tiers in priority order —
`["recent_earnings", "finnhub", "google_rss", "brave", "searxng"]` (line 531-534) — and stops at the
FIRST tier that returns a hit. `_search_recent_earnings` (`news.py:189`) is tier #1 and has no age
limit: it returns the most recent reported quarter no matter how many weeks old it is. So a 7-week-old
earnings recap permanently blocks the cascade from ever reaching `finnhub`/`google_rss`/`brave` —
those tiers are never even tried once earnings wins.

**2. The earnings source only looks backward, never forward.**
`fetch_recent_earnings_for_ticker()` (`consensus_engine/scanners/earnings_calendar.py:96`) calls
`_fetch_finnhub_company_earnings()`, which hits Finnhub's `/stock/earnings` endpoint — **historical
prints only**. Confirmed live on 2026-08-16: NVDA's real returned rows top out at period `2026-06-30`
(already reported, EPS $1.87 vs est $1.79); nothing for the upcoming quarter appears at all, because
this endpoint doesn't carry forward-looking dates. There IS a `pending_quarters` branch (line 128-136)
that's meant to detect "quarter ended but hasn't printed yet" — but it can only see a pending quarter
if the endpoint already lists it with a known period date, which for NVDA it currently doesn't. Even
if it did, the code just returns `None` for that case (skips the catalyst entirely) instead of
surfacing "next earnings expected around DATE" as a catalyst of its own.

## The job

1. **Add a staleness cutoff to the recent-earnings tier.** e.g. only let `_search_recent_earnings`
   count as a "hit" if the print is within some window (a couple of weeks?) — otherwise fall through to
   the next tier so fresher real news isn't blocked. Needs a decision on the exact cutoff.
2. **Add a genuinely forward-looking earnings-date source.** Finnhub has a separate `/calendar/earnings`
   endpoint (forward-looking, by date range) that isn't used anywhere in this file — that's the fix for
   "next earnings coming up," not the `/stock/earnings` history endpoint. Surface it as its own line
   ("NVDA next reports ~Aug 27") whenever a print is due soon, independent of whether the last print
   was stale.

## Files / code involved

- `consensus_engine/scanners/news.py:519` — `news_cascade()`, tier priority + first-hit-wins logic
- `consensus_engine/scanners/news.py:189` — `_search_recent_earnings()`, the tier with no staleness cap
- `consensus_engine/scanners/earnings_calendar.py:96` — `fetch_recent_earnings_for_ticker()`, backward-only
- Finnhub `/calendar/earnings` — not currently called anywhere; needed for the forward-looking date

## Decisions made

- A recent earnings result is usable for seven calendar days after the actual report date.
- Show the next report date whenever Finnhub returns one within the 90-day lookahead.

### Session notes — 2026-08-17
- **Worked on:** Added the seven-day actual-report freshness rule, stale-news fallback, Pacific-date filtering, ticker-filtered calendar lookup, and the separate next-earnings line.
- **Decisions:** Use a 90-day lookahead; never substitute a quarter-end date for the actual report date; omit the line when no future date is available.
- **Next:** none — built, tested, deployed, and verified with real NVDA and SPY scans in Discord.
