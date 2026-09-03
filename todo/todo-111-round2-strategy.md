# TODO #111, round 2 — reworked plan and strategy

**Written:** 2026-09-02 (Pacific). Nothing built, nothing run, nothing bought.
This replaces the "walk the old six-family slate" approach. Read it before
generating any candidate.

---

## 1. The one number that explains every failure so far

Every trading idea this project has tested at a short horizon lost, and the
reason was never trading costs. It was that the move being predicted was far
smaller than the cost of trading it.

| Attempt | Horizon | Profit per trade **with trading made completely free** | Needed |
|---|---|---|---|
| #103 intraday snap-back / follow-through (6 rules) | 30 min | best +5.1 bps | +40 bps |
| #104 three share methods | 30 min – 5 days | +1.0 / −0.4 / +3.3 bps | +40 / +80 bps |
| #106 day-trader methods (3 rules) | median 3 min | best +4.7 bps | +40 bps |
| #111 candidate 3 momentum | 3 months | +875 bps | +100 bps |

A basis point is one hundredth of one percent.

Read the last row against the first three. The only thing that ever cleared the
bar held for three months, and it cleared it by a factor of about 47 — its
break-even cost is 3.79% per side and we charged 0.10%.

**The rule this gives us: how big the move is grows with how long you hold.
What it costs to trade does not.** At three minutes a big US stock has maybe 20
basis points of movement to find and it costs 20 basis points to trade. At three
months it has 900 and still costs 20. That ratio, not cleverness, decided every
result above.

## 2. What that means for a 14-trading-day cap

The owner's new cap (open and close inside 14 trading days) puts us in the
middle of that scale. Rough arithmetic: a quarter is about 63 trading days, so
14 days is about a fifth of one. If the momentum signal paid out evenly over
time — it may not — a fifth of +8.75% is about **+1.9% a trade, against the 1%
share bar**. Just above water.

That is the honest shape of this mission now:

- **Share rules at 14 days barely clear the 1% bar even in the best case we
  have ever measured.** Anything weaker than the strongest signal this project
  has found will miss.
- **Options are where the room is.** A 3% stock move becomes a 30% option move.
  That is why the option bar is 20% and the share bar is 1%. The catch is that
  the option bid/ask is 5–15% of the premium, so the same move-to-cost test
  applies, just with different numbers.
- **Events are the other source of room.** Earnings, weekends, index
  rebalances and drug approvals compress a large move into a few days. Outside
  an event, 14 days of a large-cap stock is mostly noise.

**Flag for the owner:** four of the five candidates below are options trades.
That is not a preference, it is where the arithmetic points once trades must
close inside 14 days. If the owner wants share trades specifically, say so —
the honest answer is that the 1%-per-trade share bar and the 14-day cap
together leave very little room, and we should discuss the bar rather than
discover it on attempt four.

## 3. The cheap pre-screen (owner Decision 4b — token waste)

**Both of last session's rejections were predictable from one division, before
a single backtest was written.**

- Candidate 1, put credit spreads: at delta −0.20 the loser is about **nine
  times** the winner. To break even you need to win about 90% of the time. The
  observed win rate was **71.5%**. That is a ten-minute calculation. Instead it
  cost a full frozen backtest of 18,992 trades to reach −323% a trade.
- Candidate 2, leveraged-fund decay: the decay itself measures **+0.70% a
  month gross**. The bar is **+1.00%**. It fails before a single cost is
  charged. That is one measurement on free daily prices.

So, before any candidate gets a frozen test, it must survive three numbers.
Time-box: **under 30 minutes each, no ceremony, no frozen fingerprint.**

1. **Gross size.** Measure the raw mechanism with all costs set to zero and no
   stops, targets or filters. If it does not clear the bar naked, stop. (This
   alone would have killed #103, #104, #106 and candidate 2.)
2. **Move-to-cost ratio.** Gross size ÷ round-trip cost. **Under 3, stop.**
   Candidate 3 scored 47. The intraday families scored under 0.3.
3. **Structural win rate.** Average winner ÷ average loser gives the win rate
   the structure demands. Compare it with the win rate actually observed. If
   the gap is negative, stop. (This kills candidate 1.)

Write each pre-screen result into a one-page file with the number, even for
ideas that die. That file is the cheap half of the rejection ledger.

## 4. Why the loop hung, and the fix (owner Decision 4a)

The loop got stuck in REVIEW through repair cycles and never reached COMPLETE.
The cause is in the handoff: **all seven reviewer findings were wrong numbers
in the write-up files, not wrong arithmetic in the rule.** Hand-typed figures
in `concentration-audit.json`, `final-proof-bundle.json`,
`point-in-time-audit.json` and the rest drifted away from what the code
produced, and each drift bought another review round.

Three fixes:

1. **No number is ever typed by hand.** Every evidence file is written by the
   script that computed it. If a human or agent needs a figure in prose, the
   prose quotes a field from a generated file. This removes the entire class of
   finding that stalled the loop.
2. **Run the review envelope once, early, on a throwaway result.**
   `prepare-review` → reviewer signature → `review-result` → `final-gate`, on a
   deliberately small dry-run, before the real candidate exists. The mechanics
   get proven when nothing is at stake. Last session the envelope was never
   exercised at all and the loop died in front of it.
3. **Cap repair cycles at one per candidate.** A second repair cycle means the
   candidate goes back to the ledger and the session moves on. Polishing a
   write-up is not progress.

## 5. Gate and mission changes (owner Decisions 1 and 2)

**Verified today: the gate script has no trade-length rule of any kind.**
`scripts/research/todo_111_proven_trading_edge_gate.py` checks profit, trade
count, the untouched period, concentration, fills, reproduction and
permissions. Nothing about how long a position is held. That is exactly the
hole the three-month rule walked through.

Changes to make:

1. **Hard 14-trading-day cap in the gate.** Every result file must carry
   `maxHoldingTradingDays` and a per-trade holding column, and the checker
   refuses any bundle where the longest trade exceeds 14 trading days —
   whatever the profit. Applies to the development result, the untouched
   result, the harsh-fill rerun and the independent reproduction alike.
2. **Same sentence in the mission goal text**, so a builder reads it before
   choosing a horizon rather than after.
3. **Attempts.** Raise `maxAttempts` from 5 so that five candidates per session
   over several sessions fits. Suggest 20, with the session-by-session record
   kept in the TODO notes.
4. **Do not run the momentum candidate's review envelope.** Record it as
   "measured, +8.75% a trade, does not meet the 14-day horizon" and close it.
   Reaching COMPLETE on a rule the owner cannot trade is not worth a session.

## 6. Intraday option prices (owner Decision 5)

The free DoltHub chain is weekly end-of-day snapshots, so it cannot see whether
a trade touched 50% profit mid-week. Three leads found today, best first.

### optionsDX — the best fit
`optionsdx.com/shop` sells full option chains with **bid, ask, last, greeks,
implied volatility and the underlying price**, as monthly CSVs.

- Symbols: SPY, SPX, QQQ, VIX, UVXY, NVDA, TSLA, AAPL, SLV, and Deribit BTC.
- Years: **2010 through 2023**, sold one year at a time.
- Frequency, per year: **End of Day, 30 minutes, 15 minutes, 5 minutes, or
  minutely.**
- Price: SPY and SPX range **$0.00 to $50.00**; QQQ, VIX, TSLA, AAPL, NVDA,
  UVXY and SLV range **$0.00 to $20.00**. Some variants are genuinely free —
  their FAQ says free data needs **no billing information at all**, just a
  checkout that hands you a download link.
- **Open question to probe first:** which year/frequency combinations are the
  free ones. Almost certainly End of Day. The variation prices load by
  JavaScript so the shop page does not reveal them; add one variant to a cart
  and read the price back.
- **Why it matters even at end-of-day:** a Friday-close to Monday-close trade
  needs only two end-of-day quotes, and end-of-day is what the free tier most
  likely is. Intraday is required only for "close if it touches 50%".
- Caveat: data stops at 2023, and access is a 100-day link to a Citrix
  ShareFile account — download once, keep the files.

### Databento — broadest, probably free, needs the owner
- **CBBO-1m**: minute-by-minute national best bid and offer for US options,
  back to **April 2013**, pay-as-you-go per gigabyte.
- **$125 of free credit for a new team**, expiring six months after signup —
  more than the $50 cap allows us to spend, at zero cost.
- Blocker: this project's stored Databento key returns 401 and about $8.47 of
  credit is unreachable. A new account is a signup and an agreement, which the
  mission makes an **owner-only step**.

### Paid monthly, both inside the cap
- **ThetaData "Value" — $40/month**, full OPRA quote history.
- **Polygon Options Starter — $29/month**, 2 years of history, minute
  aggregates, unlimited calls. Quotes need the $79 tier, so Starter gives
  minute bars but not bid/ask.
Both are subscriptions: pull the data, then cancel before renewal.

**Recommended order:** probe the optionsDX free tier (costs nothing, needs a
checkout the owner may want to do) → if intraday is needed and not free, ask
the owner about the $50 optionsDX purchase for one symbol-year → Databento only
if a wider symbol set turns out to matter.

## 7. Five candidate families for round 2

Each one names the single number that kills it, so it can die in half an hour
instead of half a session.

### C1 — Weekend premium on index options (Friday to Monday)
**Mechanism.** Option prices are annualised on a 365-day calendar, so a
contract sold Friday and expiring Monday is priced as if Saturday and Sunday
carry ordinary weekday risk. They do not — the market is shut.
**Why it is not the rejected family.** That was single-name spreads held to
expiry at delta −0.20. This is the index, held one trading day, and the edge is
a calendar artifact rather than a bet on direction.
**Supporting evidence, two independent kinds.** This project already measured
the calendar-versus-trading-day clock in its own data (memory
`reference_option_iv_calendar_clock.md`: the coverage of the 68% band collapses
to 55.8% on weekend-crossing rows). Separately, an OptionMetrics study of
1-day-to-expiry at-the-money SPX put writes, March 2018 to September 2025,
found Monday expirations carry **about two thirds of the strategy's whole
profit** — dropping them takes cumulative return from 28.07% to 8.94%.
**Hold:** 3 calendar days, 1 trading day. **Data:** optionsDX SPX or SPY
end-of-day is enough.
**Kill number:** their +7.3 bps figure is of index notional, not of premium
collected, and the mission measures credit trades as a percentage of premium.
Convert it first. If a Friday-to-Monday put-write does not clear +20% of the
credit collected, gross, stop.

### C2 — Managed index credit spread (the owner's own idea)
**Mechanism.** Sell an SPX or XSP put spread, take the profit at 50% of the
credit whenever it is touched, hard stop at 2–3× the credit, forced exit by 21
days to expiry. Staggered weekly entries.
**Why it is not the rejected family.** The rejected version was single-stock,
held to expiry, with no stop and no target. Managing the trade is the whole
mechanism here: the nine-to-one loser that killed candidate 1 is exactly what a
2× stop removes.
**Hold:** up to 14 trading days by construction. **Data:** needs intraday
option prices — this is the family that justifies the optionsDX purchase.
**Kill number:** re-run candidate 1's own trade file with a 2× credit stop and
a 50% target applied at the weekly snapshots we already have. If a crude
weekly-resolution version does not move it from −323% to somewhere near
positive, no amount of intraday resolution will save it. **This costs nothing
and should be the first thing done.**

### C3 — Earnings: sell volatility only where it is persistently overpriced
**Mechanism.** Implied volatility into a scheduled earnings date prices a
bigger move than the stock usually makes, and it collapses the next morning.
**The filter is the edge, not the trade.** Published work reports that names
whose historical realised earnings move divided by their implied move sits
below about 0.8 gave a 63.4% win rate and +6.8% average, while names above that
ratio gave 47.2% and −1.4%. Selling every earnings straddle is not a strategy;
selling the persistently-overpriced fifth of them might be.
**Hold:** 1 to 2 days across the report. **Data:** DoltHub weekly chains plus
`data/mmhl_earnings`, free. Alignment is the risk — a Monday snapshot lands the
session before a report only about a fifth of the time.
**Kill number:** count how many earnings dates in `data/mmhl_earnings` have a
usable chain snapshot the session before. **Under 40 usable trades, stop** —
that is the option bar's sample minimum and no cleverness fixes it.

### C4 — Proven strength signal, held two weeks, with option leverage
**Mechanism.** The 12-month relative strength ranking (skip the most recent
month, top twenty) is the one signal this project has proven strong, three
times over, by three independent verifiers. Instead of holding shares three
months, buy a 30–45 day call on each name and exit on day 10.
**Why this is a new test, not a tweak.** The handoff is explicit: shortening
the hold is a fresh frozen test, and every short-horizon attempt in this
project's history has failed. Do not assume it carries over.
**Hold:** 10 trading days. **Data:** DoltHub stocks and options, both free.
**Kill number:** measure the plain 10-trading-day share return of the top
twenty first, with zero costs and no options at all. If it is not comfortably
above 1.5%, the option version cannot pay for its own bid/ask. **This is a
20-minute measurement and it should be run before anything else in this
family.**

### C5 — Put versus call skew, as a relative-value trade
**Mechanism.** Hedging demand makes downside puts persistently dearer than
matched upside calls. Sell the expensive side against the cheap side and
collect the difference, rather than betting on direction.
**Status.** On the original slate, never run. The DoltHub chains carry implied
volatility and delta per contract, so the skew is directly measurable for free.
**Hold:** 5 to 14 days. **Data:** free.
**Kill number:** a two-leg option trade pays two bid/ask spreads. Measure the
average skew in implied-volatility points and the average spread cost in the
same units. **If the skew is not at least three times the cost, stop** — and
check that the pair is genuinely delta-matched, because a mismatched pair is a
direction bet wearing a disguise.

## 8. Killed by research today — do not spend a session on these

- **Post-earnings drift at 14 days or less.** The published reviews say the
  drift is *mild* through the first two trading weeks and only accelerates
  between days 20 and 75, and that the classic effect has largely disappeared
  for large liquid US stocks. It fails on horizon and on size at the same time.
- **Anything intraday on large-cap shares.** Three separate frozen studies in
  this project (#103, #104, #106) measured the gross edge at 1 to 5 basis
  points against a 40 basis point need, with costs switched off entirely.

## 9. Two decisions that are the owner's

1. **The share bar versus the 14-day cap.** 1% net per trade inside 14 trading
   days, over 200 trades, is at or above the best result this project has ever
   measured, pro-rated. Either the mission is effectively options-only — which
   is fine, and four of the five candidates above are options — or the share
   bar wants a conversation. Deciding now beats discovering it on attempt four.
2. **Data access.** The optionsDX free tier needs a checkout (no card, but an
   account). The $50 allowance would buy one symbol-year of intraday chains if
   candidate 2 needs a real touch test. A Databento account would be free under
   its $125 new-team credit but needs a signup and an agreement. All three are
   owner-only steps under the mission's own rules.

## 10. Order of work for the next session

1. Update the gate and the mission: 14-trading-day cap, raised attempt count.
2. Prove the review envelope on a throwaway result, end to end, before any real
   candidate exists.
3. Run the three free kill numbers that need no new data and no new code:
   C2's stop-and-target replay on the existing candidate-1 trade file, C4's
   plain 10-day share return, C3's usable-earnings-snapshot count.
4. Probe the optionsDX free tier; bring the owner a single yes/no if a purchase
   is warranted.
5. Only then freeze and run whichever candidates survived, five per session.
