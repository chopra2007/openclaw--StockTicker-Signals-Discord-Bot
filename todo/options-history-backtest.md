# Buy 2 years of options history (~$29) and backtest the options signals

**Status:** PARKED (2026-07-03) — nothing built. The buy-2yr-history route needs paid data the user has deferred (no spend now). Free alternative already accruing via #55's forward-loggers (`options_flow` 110k+ rows + 5d/20d outcome grading); the same unusual-flow backtest can run on collected data for $0 in ~a few months. No action now.
**Created:** 2026-06-28

**CURRENT STATUS (2026-07-03):** Nothing built. The buy-2yr-history route is **PARKED** — it needs paid data the user has deferred (no spend now). A **free alternative is already accruing**: #55's forward-loggers (`options_flow` 110k+ rows and growing, plus 5d/20d outcome grading) capture the same fields going forward, so the same backtest (did the vol/OI≥5, vol≥500, premium≥$250k unusual-flow rule actually predict the move?) can run on collected data for $0 in ~a few months. No action now — let #55 accrue, then build the replay harness. Independent of #57 (Schwab's snapshot logger only holds ~days of derived summaries, not raw chains).

## The goal in one line
Pay ~$29 once for 2 years of historical US options chains, then use it to (a)
backtest the unusual-options-flow alerts (built & live but never tested against
real moves) and (b) feed the failed market top/bottom detector the option-surface
data it was missing.

## Source decision (research, 2026-06-28)
**Winner: massive.com — which is Polygon.io renamed** (they rebranded the company
on 2026-10-30; their own blog post is "Polygon.io is Now Massive"). It is a real
historical options-data provider.
- **Options Starter plan: $29/month.** Includes 2 years of historical US equity
  options, greeks, implied volatility, daily open interest, volume per contract,
  unlimited API calls, AND **bulk flat-file download (CSV via S3)**.
- Tactic: subscribe one month, bulk-download the full 2-year history, cancel →
  realistically **~$29 one-time**. License is individual/non-professional —
  fine for our internal research/backtest.
- This is cheaper than the ~$50 AlphaVantage plan we'd previously settled on
  (`project_vol_indicator_free_exhausted.md`).
- URLs: `https://massive.com/pricing?product=options` ·
  rebrand `https://massive.com/blog/polygon-is-now-massive` ·
  flat files `https://massive.com/docs/flat-files/quickstart`

**edeltapro.com — NOT usable (logged so we don't revisit).** It's a closed
web-based options backtesting/trading platform ($99/mo, 30-day trial) with 10+
years of EOD data *inside the tool*, but its FAQ confirms **no API, no CSV
export** — you can only test strategies in their UI, so it cannot feed our own
signal code. Dead end for this purpose. (`https://www.edeltapro.com/pricing`)

## Alternatives, ranked (for the record)
| Provider | 2yr history? | Cost | Bulk export | Notes |
|---|---|---|---|---|
| **Massive (ex-Polygon) Options Starter** | yes | **$29/mo (~$29 one-time)** | yes (CSV flat files) | the pick |
| AlphaVantage Premium | back to 2008 | $49.99/mo | API only | deeper, pricier; we hold a free key (options premium-locked) |
| ThetaData Value | 4yr | $40/mo | API | has intraday; free tier only 30 days |
| ORATS | 25yr | $99/mo | API/download | overkill |
| DoltHub free options DB | 2019–Jun 2024 | $0 | dolt clone | **misses the recent ~2yr** = the window with the big moves; supplement only |
| Marketstack (we have a key) | n/a | — | — | **no options data at all** |
| Tradier | real-time only | — | — | no deep history |

## What it unblocks
- **#18 (options-flow alerts)** — built and live, but its predictive value was
  NEVER backtested. With 2yr of daily chains we can replay each day's
  volume/open-interest/premium per strike, fire our unusual-flow rule
  (vol/OI ≥ 5, vol ≥ 500, premium ≥ $250k), and measure whether those alerts
  actually preceded the many 5%+ drops and rallies of the last 2 years.
- **#47 (market top/bottom detector)** — the decomposed option surface
  (greeks/IV) is the missing ingredient the vol-indicator QQQ near-miss
  (p = 0.064) needed (`vol-indicator-accuracy-research.md`).

## Caveat to flag before any live change
Massive's Starter **history is end-of-day**, not full intraday tick. That's
enough to backtest whether the *signal predicts moves*, but our live scanner runs
on ~15-min-fresh intraday data — so a future intraday check (ThetaData or Massive
Advanced) may still be owed before changing live alerts.

## Next steps
1. User approves the ~$29 spend.
2. Subscribe to Massive Options Starter, pull the full 2-year flat-file history, cancel.
3. Backtest the #18 unusual-flow rule against the 2yr history (did alerts precede the 5%+ moves?).
4. Feed the option-surface (greeks/IV) into the #47 top/bottom detector research.

## Open questions
- Spend approval (~$29).
- Storage location/format for the downloaded chains (so #47 + #18 backtests can both read it).

## Related items
- #18 (options flow) · #47 (top/bottom detector) · #54-area vol-indicator memory.
- Companion to #55 (forward-logging) — that one collects NEW point-in-time data
  going forward; this one BUYS the past 2 years we can't collect retroactively.
