# Builder brief: "report" — the ticker report page

Read `todo/member-dashboard-design-build-common.md` first, then `todo/member-dashboard-design-review.md`.
You own problems P11-P21 and gap features 1 (key stats + day change + after hours + earnings date) and 3 (chart).

## Files you own
Backend: `member_dashboard/analysis_collector.py`, `member_dashboard/research.py` (`_study` and helpers only),
`member_dashboard/contracts.py` (AnalysisPayload + new models only), `consensus_engine/scanners/schwab_client.py`
(additive only: a new method; never change existing methods — the live bot uses them).
Web: `src/components/ticker-report.tsx`, `research-section.tsx`, `expected-move.tsx`, a new `price-chart.tsx`,
the analysis part of `src/lib/contracts.ts`, report CSS in `globals.css`, additions to `src/lib/format.ts`.
Tests: `tests/member_dashboard/test_analysis_collector.py`, `test_research_parity.py`, `test_jobs.py`, `test_trade_map.py`.

## Backend
The analysis study already fetches a Schwab quote + one year of daily candles (`AnalysisCollector.market`) and
works out price, day change, 52-week range, averages and the next earnings date (`facts()`; `street.py`).
Add to `AnalysisPayload` (optional fields, so old stored reports still load):
- `company` name; `quote`: price, change $, change %, previous close, open, high, low, volume, average volume
  (from candles), 52-week high/low, P/E and market cap if Schwab's quote `fundamental` block gives them,
  after-hours/premarket price + change when present (Schwab quote `extended` block / `postMarketChange`), quote time;
  `next_earnings` date.
- `chart`: daily closes for 1 year (from the candles already fetched) and intraday bars for the last 5 trading days
  (ONE extra `get_price_history` call, e.g. 5d / 15m — check `_FREQ_MAP`/`_PERIOD_MAP` for what works). Keep it
  compact: [epoch, close] pairs, capped lengths.
- For extra quote fields add one new method on the Schwab client (e.g. `get_quote_details`) that asks `/quotes` with
  `fields=quote,fundamental,extended`; don't change `_map_quote`.
Every source observation must pass the existing `_authorize` / evidence checks the way `_study` does today.
If a field is missing, leave it out (never show "Unavailable").

## Web (follow the design plan's wireframe)
- Hero: ticker + company name, big price, coloured day change "+$4.10 (+1.74%) today", after-hours line, one
  "Updated 9:54 PM" for the whole report. SOUN must show a price (P20). Price falls back to the expected-move spot
  when the analysis has none.
- Chart (`price-chart.tsx`, inline SVG): edge to edge on phone, line green if up over the range, red if down, range
  tabs 1D 5D 1M 6M 1Y, dotted previous-close line on 1D, buy zone / stop / target lines from the trade plan (thin,
  labelled at the right edge), tap/drag (pointer events) shows price + date/time under the finger in the hero.
  Keyboard: tabs are buttons. Respects reduced motion.
- Key stats grid: two columns of label + number (Open, High, Low, Prev close, Volume, Avg volume, 52W high,
  52W low, P/E, Mkt cap, Next earnings).
- Split the giant Analysis card (P12): "The call" (headline + catalysts as short points, each body clamped to
  2 lines with tap to expand), "Trade plan" (one row per level: label, price, % from current price, short reason on
  a second line; reward/risk as "Reward to target 1 is 0.8x the risk" or similar plain wording, P19), "Risks",
  "Latest news", "Analyst calls" each as its own grouped list.
- Remove the duplicate ranges (P13): Outlook keeps only "Next year" (Wall Street targets). The week/month ranges
  are already in the expected-move sections; merge em_daily + em_weekly into one "Expected move" group with two
  rows ("By Oct 9: ±$4.85 (2.0%), $234.39-$244.09") so each date shows once and the "today" label is honest.
- One "Updated" stamp per report (P14). Short paragraphs (P15). One text width per group (P16).
- SEC (P17): one summary line first ("Insiders sold $314.5M on the open market in 90 days" — compute from the
  rows), then only non-routine rows; routine ones behind "Show all 15". Replace "144" with "Planned sale".
- Options on phone (P18): contract as "Put $240 · Oct 7" on one line (no wrapping), the three volume stats in one
  row of three.
- "The house view" and similar jargon (P21): plain words ("Our read"). If the text comes from the AI prompt, fix the
  prompt wording in `analysis_collector.py`.
- Desktop ≥1024 px: main column + right rail (key stats, expected move, options, insiders, analyst calls).
- Leave a spot in the report actions row for a watchlist star; another builder creates `watch-button.tsx` and the
  lead wires it in. Don't create it yourself.

Verify visually yourself before reporting: run the existing renderer only through type-check + your own reasoning;
the lead does live screenshots after release.
