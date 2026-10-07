# Builder brief: "market" — Overview, market strip, watchlist, track record

Read `todo/member-dashboard-design-build-common.md` first, then `todo/member-dashboard-design-review.md`.
You own problems P4-P10, P27, P28 and gap features 2 (market strip), 4 (track record), 5 (watchlist).

## Files you own
Backend: new modules you create (e.g. `member_dashboard/market_board.py`, `member_dashboard/track_record.py`), a new
migration `member_dashboard/migrations/012_*.sql`, a new `member_dashboard/routes/market.py`, router registration in
`member_dashboard/app.py`, the worker idle chore wiring in `member_dashboard/worker.py` / `runtime.py` /
`launch.py` (wherever `setup_levels` is wired), feed/supervisor code only if track record needs it
(`publication.py`, `market_reader.py`: additive only), `member_dashboard/contracts.py` (new models only).
Web: `src/app/page.tsx`, `feed-panel.tsx`, `alert-card.tsx`, `setup-card.tsx`, `feed-card.tsx`, `app-shell.tsx`,
`session.tsx` (account menu), new `market-strip.tsx`, `watch-button.tsx`, `watchlist` page + route
`src/app/watchlist/page.tsx`, `track-record` page `src/app/record/page.tsx`, new schemas appended to
`src/lib/contracts.ts`, home/nav CSS in `globals.css`.
Tests: new test files for your modules + `test_feed.py`, `test_feed_latest.py`, `test_store.py`, `test_market_reader.py`.
The migration test `test_migration_is_idempotent` already fails (expects 10, there are 11); after your migration it
must expect the real count, so fix that test.

First learn the process roles: which process may call Schwab (look at how `setup_levels.refresh_one` gets its
collector in the worker), which reads the bot database (`market_reader.py`, the supervisor/publication loop), and
how routes read the dashboard DB. Put each piece in the process that already has that access.

## Features
1. **Market strip** (top of Overview): S&P 500, Nasdaq, Dow, Russell 2000, VIX with price and coloured day change.
   One Schwab `/quotes` call for `$SPX,$COMPX,$DJI,$RUT,$VIX` (plus watchlist tickers, see 2) at most once a minute
   while anyone is signed in or during market hours, saved in a dashboard table, served by an API route. On phone it
   scrolls sideways. Show the quote time ("4:00 PM") once.
2. **Watchlist**: members star tickers (`watch-button.tsx`, a small star toggle with aria-pressed, used by the lead
   on the report page and by you on Overview cards if it fits). New table (member, ticker, added_at), routes GET/PUT/
   DELETE with the same auth + CSRF as other member routes, cap 50 tickers per member. Watchlist page lists price +
   day change (from the same snapshot quotes; snapshot includes every watched ticker, cap 100 symbols per call) and a
   "New alert" badge when the bot alerted on it in the last 24 h. Empty state tells the member how to add one.
   Add it to the nav (top nav + phone tab bar).
3. **Track record** (`/record`, linked from Overview with a short summary line): the bot's own alerts from the bot
   DB `alert_history` (`alerted_at`, `ticker`, `price_at_alert`, `price_1h_later`, `price_24h_later`,
   `price_5d_later`). Before building, check whether every row was actually posted to the #alerts channel
   (`alert_messages` table?) and only count posted alerts. Show: for 1 hour / 1 day / 5 days: how many alerts, how
   many were up, the median move, and the S&P (SPY daily closes from Schwab, one call a day) over the same days so
   members see the move versus the market. Use whole-number percentages and always show the count next to a rate
   (no rate on fewer than 20 alerts). Below: the last 50 alerts with their three moves, coloured. Members trade
   minutes to days, so 1 h and 1 day lead.
4. **Overview fixes**: P5 day change next to prices where the data has it; P6 one time format ("52m ago", with the
   clock time in a tooltip/title); P7 alerts show only bullish/bearish counts that exist ("1 bullish") and drop the
   grey "unclear" bar; P8 setup rows: Entry / Stop / Target 1 on one line each with % distance, other targets behind
   tap; no wrapping on 1366 or 390; P9 drop "Score 65" or explain it ("Score 65/100"); P10 compact phone alert rows.
   P27 tab bar: more opaque frosted background so text behind it never shows through. P28 account circle gets a
   visible menu affordance (chevron or "Account" label on desktop) and a sign-out item.
