# Member dashboard: fresh-eyes design review + feature gap check (2026-10-06 evening, PDT)

Kickoff: `todo/member-dashboard-design-review-kickoff.md`. Before screenshots: job scratch `shots/before/` (24 images:
6 pages x desktop 1366 / phone 390 x light / dark). Competitor research: section "Part 2" below.

## Part 1: fresh-eyes review (as a first-time member, before reading code)

Scores: clarity / readability / trust / speed to the key fact (1-5).

| Page | Before | Main problems |
|---|---|---|
| Sign in | 4 / 4 / 3 / 5 | P1 logo is a blank blue square; P2 phone: card inside a page wastes width; P3 "Contact your administrator" sounds like IT, not a product |
| Overview | 3 / 3 / 3 / 3 | P4 no market context (is the whole market up or down?); P5 prices have no day change; P6 times mixed ("3:23 PM" on alerts, "52m ago" on setups); P7 "1 bullish, 2 unclear" + grey bar is noise; P8 setup boxes wrap ("$176.66 – / $187.46"), 3 targets crammed in one box, no % to stop/target; P9 "Score 65" has no scale; P10 phone alert cards ~200px tall for one fact |
| Report NVDA | 3 / 2 / 3 / 2 | P11 no day change, no chart, no company name, no key stats; P12 one giant "Analysis" card holds summary, outlook, plan, risks, news and calls (phone page is ~6,000 px tall); P13 the same range shows twice with different dates (Outlook "next week $231.75-$246.73 into Oct 12" vs Expected move "this week $231.79-$246.69 by Oct 14"); "Expected move today ... by Oct 9"; P14 "Updated Oct 6, 9:54 PM" repeated 4 times; P15 long paragraphs in Outlook; P16 text column widths differ inside one card; P17 SEC list = 15 rows, mostly "routine tax withholding", "144" is jargon; P18 phone options table wraps "Oct / 7", put/call ratio card alone on its own row; P19 "Target 1 pays 0.8 times the risk to the stop" is hard to read |
| Report SOUN (small cap) | 2 / 2 / 2 / 2 | P20 NO PRICE AT ALL in the header (price only came from expected moves, which were unavailable); P21 "The house view" jargon; plus every NVDA problem |
| Assistant | 4 / 4 / 3 / 4 | P22 phone: chat inside a card inside the page (wasted width, "‹ Chats" link on an empty chat); P23 desktop recent list truncates titles with no date |
| History | 2 / 3 / 3 / 2 | P24 rows show only ticker + time: 9 identical "NVDA" rows can't be told apart (no signal, no price); P25 footer talks about deleting, but no delete is visible; P26 desktop detail pane is a tiny box |
| All pages | | P27 phone bottom tab bar is too see-through (text behind it shows through); P28 the "C" account circle gives no hint it is the menu |

## Design plan (frontend-design pass)

Keep the owner's iPhone look (system font, grouped lists, frosted bars, light/dark). What changes is hierarchy, not
brand. One memorable thing: the ticker hero, the way Apple Stocks does it: big price, coloured day change, an
edge-to-edge chart that turns green or red with the move, range tabs under it. Everything else gets quieter.

- **Colour** (unchanged tokens): bg `#f2f2f7`/`#000`, surface `#fff`/`#1c1c1e`, label `#1c1c1e`/`#f5f5f7`,
  accent `#007aff`/`#0a84ff`, up `#248a3d`/`#30d158`, down `#d70015`/`#ff453a`. Green/red only for price direction.
- **Type**: system SF only. Scale (iOS): large title 34/41 bold, title 22/28 semibold, headline 17 semibold,
  body 17/22, subhead 15/20, footnote 13/18. Hero price 40 bold tabular. All numbers tabular.
- **Layout**: left aligned. Phone = one column, no card-in-card, 16 px gutters. Desktop report = main column (hero,
  chart, the call, trade plan, risks, news) + right rail 340 px (key stats, expected move, options, insiders, analyst
  calls). One "Updated 9:54 PM" per report, in the hero.

```
Phone report                      Desktop report
NVDA  NVIDIA                      NVDA NVIDIA                      [Ask] [Refresh]
$239.24                           $239.24  +$4.10 (+1.7%) today    | Key stats grid
+$4.10 (+1.74%) today             After hours $240.01 (+0.3%)      | Expected move
After hours $240.01 (+0.32%)      [ chart ~~~~~~~~~~~~~~~~~~~~ ]   | Options (top 5)
[ chart ~~~~~~~~~~~~~~~~ ]        1D 5D 1M 6M 1Y                   | Insiders: sold $X
1D 5D 1M 6M 1Y                    The call: headline + 3 points    | Analyst calls
Open 236  High 240 | Vol 180M..   Trade plan (one line per level)  |
The call / Trade plan / Risks     Risks / News                     |
Expected move / Options / ...
```

- **Principles**: every number says which way is good (colour + sign); every level shows its % distance from the
  price; reasons are one short line, tap for more; no number appears twice with different dates; lists show 5 then
  "Show all".

Review against the brief: the first draft kept the single long "Analysis" card and only restyled it. That is the
default "restyle everything" move and doesn't fix P12/P13, so it was replaced by the split above (merge the
week/month Outlook rows into the Expected move card, plan/risks/news become their own groups).

## Part 2: feature gap check (sources verified with real calls 2026-10-06)

Competitors checked: Yahoo Finance, TradingView, Finviz, Seeking Alpha, Unusual Whales, Robinhood, Apple Stocks.

| Gap | Use (1-5) | Free source | Effort |
|---|---|---|---|
| Price chart on the report (1D-1Y tabs) | 5 | Schwab price history (already called) | M |
| Track record of the bot's alerts | 5 | Bot DB `alert_history`: price at alert, +1 h, +24 h, +5 d (8,652 alerts) | M |
| Watchlist | 5 | Site's own database + Schwab quotes | M |
| Key stats (P/E, 52-week, volume vs average, market cap) + after-hours price + earnings date | 4 | Schwab quote (fundamental fields); earnings date already fetched from Nasdaq | S |
| Market strip (S&P, Nasdaq, Dow, Russell, VIX) | 4 | Schwab quotes `$SPX,$COMPX,$DJI,$RUT,$VIX` | S |
| Technical row (RSI, ATR, % from 20/50/200-day average) | 4 | Worked out from Schwab daily prices | S |
| Notifications (new alert / price pings) | 4 | Discord DMs through the bot (M); iPhone web push only from home-screen app (L) | M/L |
| Top movers | 3 | Schwab `/movers` | S |
| Earnings this week (market-wide) | 3 | Nasdaq `api/calendar/earnings` | S |
| Economic calendar | 3 | Nasdaq `api/calendar/economicevents` | S |
| Short interest / borrow | 3 | Nasdaq short-interest page; Schwab quote shortable flags | S |
| More news per ticker | 3 | Finnhub `/company-news` (free) | S |
| Gamma by strike | 3 | Worked out from Schwab chains | M |
| Screener | 3 | No free all-market feed (would need ~6,000 tickers nightly from Schwab) | L |
| Peers | 2 | Finnhub `/stock/peers` | S |
| Past earnings (expected vs actual EPS) | 2 | Finnhub `/stock/earnings` | S |
| Sector heat map | 2 | Schwab quotes for the 11 sector funds | S/M |
| Daily off-exchange short volume | 2 | FINRA daily file | S |
| Fundamentals history | 1 | SEC EDGAR company facts | M |

**Not possible free:** live dark-pool prints (FINRA only gives late weekly totals); a full live options tape; earnings-
call transcripts, analyst upgrade/downgrade history, per-analyst targets, social sentiment, EPS estimate history
(Finnhub free key returns 403 for each); Seeking Alpha-style factor grades (their own model). Level 2 order book is
technically in Schwab's streamer, but needs an always-on connection, and sharing it with members may break Schwab's
individual-developer terms (the same open question applies to every Schwab number the site shows).

**Top 5 by value / effort (built this session):**
1. Key stats + day change + after-hours price + earnings date on the report (S).
2. Market strip on Overview (S).
3. Price chart on the report with the trade plan lines (M).
4. Track record of the bot's alerts, each alert's move next to the S&P's move over the same days (M).
5. Watchlist (M).
Runners-up for later: top movers, earnings this week, technical row, Discord DM notifications.

## Part 3: build status (2026-10-06 ~22:55 PDT, LIVE)
Built by three Sonnet builders (briefs: `member-dashboard-design-build-{common,report,market,polish}.md`), reviewed
and live-checked by the lead. Released 3 times; final after-screenshots: job scratch `shots/after/`, side-by-sides
in `shots/compare/`. Safety copy of the site DB before migration 012: `/var/lib/member-dashboard/web-prerelease-20261006.sqlite3`.

After scores (clarity / readability / trust / speed): Sign in 5/5/4/5 · Overview 4/4/4/5 · Report NVDA 4/4/5/5 ·
Report SOUN 4/4/4/5 · Assistant 4/4/4/4 · History 4/4/4/4 · Watchlist (new) 5/4/4/5 · Track record (new) 4/4/5/4.

Problems: P1-P14, P16-P28 fixed and checked live. P15 partly: the "Next year" Wall Street paragraph is still one
AI-written paragraph of ~4 lines (prompt asks for short bullets elsewhere); left as is.
Features live: 1 key stats + day change + after hours + earnings date; 2 market strip (one Schwab quotes call a
minute while anyone is signed in or the market is open); 3 chart (1D 5D 1M 6M 1Y, trade plan lines, drag to read);
4 track record `/record` (4,300 posted alerts, 90 days; 1-hour counts only market-hours alerts); 5 watchlist
(star on alerts, setups and reports; cap 50).
What the track record says today: after 1 day 48% of alerts were higher (2,055 of 4,249), median −0.1%; the
S&P 500 over the same days was also up 48% of the time. The bot's alerts so far move about like the market.
Known limits: the 1-hour market-hours rule ignores exchange holidays; the old worker took 10 s to stop on restart
and was killed by systemd (new one starts clean).
