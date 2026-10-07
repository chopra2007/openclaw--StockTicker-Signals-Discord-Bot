# Kickoff: fresh-eyes design review + feature gap check (TODO #121)

Site: https://akash.ignorelist.com ("Market Edge"). Code: `web/member-dashboard/` (Next.js) and `member_dashboard/` (API).
Owner is not a coder: report in plain language, times in PDT only.

## Goal
Look at the site as a first-time member who trades stocks over minutes to days. Make it look professional and
purposeful and easy to read, with an iPhone feel. Then find what good stock sites offer that this one lacks.

## Part 1: fresh-eyes review (before reading any code)
1. Sign in as the QA member `claude_qa`. The password is root-only at the path in `todo/member-dashboard-phaseC-plan.md`.
   Never print it.
2. Screenshot every page: Overview, a ticker report (NVDA and one small-cap), Assistant, History, and Sign in.
   Do desktop 1366px and phone 390px, each in light and dark.
3. For each screen, write down:
   - what a new member would try to do first;
   - what confuses them;
   - which words or sections have no clear purpose;
   - anything that repeats or is hard to read: dense numbers, long paragraphs, weak contrast, crowded spacing.
4. Score each page 1–5 on: clarity, readability, trust (does it look professional?), and speed to the key fact.
5. Use the `frontend-design` skill for the design plan. Keep the iPhone look the owner asked for, and avoid generic
   template styling.

## Part 2: feature gap check
Compare against Yahoo Finance, TradingView, Finviz, Seeking Alpha, Unusual Whales, Robinhood and Apple Stocks.
Use web search, and screenshots where pages are public.
- List the features those sites have that this site lacks. Examples to check: a price chart on the report,
  a watchlist, price or alert notifications, an earnings calendar, a market overview (indexes and sectors),
  a screener, news per ticker, and the track record of the bot's past alerts.
- For each gap, note how useful it would be to our members and the cost to build: data we already have
  (Schwab, the bot's database, news feeds) versus data we'd need to buy.
- Rank the top 5 by value ÷ effort.

## Part 3: build
- Fix every design problem found in Part 1.
- Build the top gaps that use data we already have. Ask the owner before anything that costs money or needs a new data source.
- Rules:
  - Never start research from a bare /ticker address.
  - Never expose keys.
  - Run the site tests with `sudo -u openclaw /opt/member-dashboard/testvenv/bin/python -m pytest tests/member_dashboard`.
    There are 5 known failures; the list is in TODO #121 follow-up 7.
  - Type-check in the scratch copy that has the build tools installed.
  - Release with `bash deploy/member-dashboard/release.sh --web`.
- Re-screenshot every page live after release and compare with Part 1.

## Done when
- Every Part 1 problem is fixed or listed with a reason.
- Every page scores 4 or higher on all four measures.
- The top gaps are built and checked live, or listed for the owner's approval.
- The owner gets a short plain-language summary with before and after screenshots.
