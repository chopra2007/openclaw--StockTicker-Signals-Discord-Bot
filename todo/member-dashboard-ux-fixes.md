# Member dashboard: owner's issue list and fix plan (2026-10-06)

Owner's report after first real use of https://akash.ignorelist.com. Each issue has the cause found
and the "done" test. The site's goal: a clean, professional place where members see what the bot
sees (fresh, readable, actionable) and can research any ticker like `!all`, at a glance.

## Feature goals (the yardstick)

- **Research feed:** what the bot is seeing *right now* that a person would want to read: analyst
  calls with their reasoning, and the bot's own alerts with the reason. Recent only, newest first,
  every card has real content. A human can scroll it calmly.
- **Trade setups:** the bot's recent alerts turned into actionable setups: ticker, direction,
  entry zone, target, stop (invalidation), score, price. A card without levels is not a setup.
- **Ticker research (`!all` on a web page):** summary readable in seconds (direction, confidence,
  2-4 short points), trade plan as clear numbers, expected moves, the few option trades that
  matter, SEC filings. Nothing drowns the rest.
- **Whole site:** looks like a professional financial product: clean, simple, consistent, no
  disclaimers or system jargon repeated on every card.

## Issues, causes, done-tests

1. **Research feed shows tickers with only "Unavailable".**
   Cause: the feed publishes every bot row, including rows that carry no readable content
   (old `research_sections` rows have no text by design; old raw mentions from Aug 31 are still
   shown), and has no recency limit (90 days).
   Done: every feed card shows real text; nothing older than 7 days; no "Unavailable" score/price
   rows (missing numbers are simply omitted).
2. **Trade setups: "Unable to load content", or Entry/Target/Invalidation all "Unavailable".**
   Cause A: page loads fail with `database is locked` (64 times in 3 h): the feed copier holds long
   write transactions while scanning the bot's 1.5M-row mention backlog. Cause B: no bot table
   stores entry/target/stop for alerts; the setup cards never compute them. Old alerts (July) shown.
   Done: no load errors over a 30-min watch; each setup card shows entry, target and stop computed
   by the same trade-plan math as `!all`; only recent alerts (≤ 7 days); cards without levels hidden.
3. **"Research only" on every card and inside every dropdown.** Done: the phrase appears nowhere.
4. **Ticker research page.**
   A. Options Activity lists so many contracts it drowns the page. Done: top 5 contracts by
      premium, compact table, the rest hidden.
   B. Summary shows "**TL;DR:**" and one long run-on paragraph; trade setup buried in it.
      Done: no markdown symbols; summary = one headline line + short bullet points; trade plan
      (entry/targets/stop) shown as its own clear block of numbers.
5. **Visual / UI.**
   A. Clutter text ("Cache valid until … · Analysis member-research-v1", "Source access is
      checked on every response…", observed/projected/computed stamps everywhere). Done: removed;
      at most one quiet "Updated 1:23 PM" per section.
   B. Looks amateur. Done: professional redesign: clear type scale, consistent spacing, tidy
      cards, numbers aligned, good on phone and desktop.
6. **Overview text contradicts the page, feed cycles 3,500 → error → 3,500.**
   Cause: the overview says nothing runs until you search, yet two feeds load; the browser pulls
   up to 2,000 cards every 15 s and wipes the list on each error (the lock errors above).
   Done: overview copy matches what is shown; feed shows a fixed, readable number of recent cards
   (e.g. 30) that update in place without wiping.

## Order of work
1. Stop the long feed transactions (stop scanning raw mentions; drop content-less sources) → errors gone.
2. Feed: recent-only, content-only, capped; browser stops pulling thousands.
3. Setups: compute levels for recent alerts with the `!all` trade-plan math.
4. Ticker page: summary format, trade-plan block, options top 5.
5. Remove "Research only" + clutter; redesign the look.
6. Verify every done-test above on the live site (screenshots), then commit.

## Status 2026-10-06 ~14:15 PDT (paused for compact)
Done and live (checked in a real browser as test member `claude_qa`; screenshots in session scratchpad):
1 feed = analyst calls with text, ≤7 days, 30 newest, no "Unavailable" ✓ · 2 setups = alerts + trade plan from
the `!all` math (`setup_levels`, filled ~1 ticker / 3 min when idle) ✓, lock errors 0 since 13:54 (watch
running until 14:24) · 3 "Research only" gone everywhere ✓ · 4A options top 5 ✓ · 4B headline + points +
trade-plan block, no TL;DR ✓ · 5A clutter removed ✓ · 5B redesign (Inter, dark finance theme) ✓ · 6 overview
copy fixed, feed updates in place every 30 s, no wipe ✓.
Also: Schwab calls wait ≤25 s for a free slot instead of failing a section; History/Assistant pages not yet
screenshotted (sign-in throttle hit) — do that first next session.

## TESTING PHASE: member throttles lifted (owner, 2026-10-06) — restore at "ready to ship"
Switch: `/etc/member-dashboard/testing-phase` exists → off (`member_dashboard/testing_phase.py`).
Lifted: sign-in 5/15 min + 50/address + backoff (auth.py); research 2 active tickers, 60 s refresh
cooldown, 10 computes/hour, 60 requests/min (jobs.py); assistant 20 messages/hour (assistant.py).
Kept on: $3/day AI cap, Schwab 15/min share, 50 queued jobs global, one assistant answer at a time.
To ship: `rm /etc/member-dashboard/testing-phase && systemctl restart member-dashboard-api`, then suspend
test member `claude_qa`, then verify each limit.

## Round 2 — owner report 2026-10-06 evening (after the first redesign)
Yardstick: feels like a modern iPhone app; every word and section has a purpose; the assistant works like
ChatGPT/Claude; research reads like a real analyst note (news + catalysts, not just price talk).

1. **Assistant says "Market Assistant is unavailable."** Cause: for "is NVDA a buy?" the model can only *start*
   a report (request_research), never read live data in the same answer; an answer with no stored evidence is
   discarded. Done: ticker questions answered from live data (price, signal, trade plan, news) in one go;
   general finance questions answered too.
2. **Assistant needs a typed title.** Done: no title box; title = the first question.
3. **Enter doesn't send.** Done: Enter sends, Shift+Enter = new line.
4. **Assistant UI from 2005.** Done: modern chat (bubbles, pill composer, typing dots, suggestions, past chats list).
5. **"Ask the assistant" leaves the ticker page.** Done: opens an inline chat panel right under the button,
   already about that ticker.
6. **Custom stock analysis = generic price talk.** Cause: the dashboard analysis had no news feed and no analyst
   posts ("not reachable"). Done: recent news headlines (7 days) and the bot's analyst calls for the ticker feed
   the write-up; points name real catalysts; news list with links on the page.
7. **SEC filings empty for NVDA/MU.** Cause: only the last 72 hours were searched. Done: last 90 days, newest
   15, plain names ("Quarterly report", "Insider trade").
8. **Look and wording.** Done: Apple-style look (system font, light/dark, grouped rounded lists, frosted top
   bar, big titles); no redundant or hard-to-read text anywhere.
History page: passable, only restyled with the rest.
Status 2026-10-06 15:35 PDT: all 8 round-2 items done and checked live as `claude_qa` (desktop, phone light + dark,
no console errors): assistant answers NVDA/MU/AMD from live data with news in ~6 s, general questions answered,
off-topic refused; Enter sends; title = first question; Ask opens in place on the ticker page; MU/NVDA analysis
leads with news + analyst calls, specific risks; SEC shows 90 days with plain names. Browser test specs updated
to the new wording but NOT run: their test server needs port 3444, which the live site uses.

## Round 3 — owner 2026-10-06 ~15:40 PDT
1. Ticker page: "Risks" right after "Trade plan". Done (live order: Trade plan > Risks > Latest news > Analyst calls).
2. "Latest news" rows must open the articles. Cause: Google News links are redirects, which the site's link-safety
   rule strips. Fix: the server asks Google for each of the top 5 real article addresses (falls back to the Google
   link); rows are tappable with an arrow. Verified live on NVDA: 5/5 links go to Yahoo, Barron's, Motley Fool,
   Seeking Alpha.
