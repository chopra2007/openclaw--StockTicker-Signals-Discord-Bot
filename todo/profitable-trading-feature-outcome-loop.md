# Build a profitable trading feature through the outcome loop
**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-09-03):** A rule PASSED the frozen bar on both periods
and was reproduced trade-for-trade by three independent verifiers — but it holds
each position for THREE MONTHS, and the owner trades minutes to days, never
months. So it is a valid measurement, not a usable trade. The loop is parked at
stage REVIEW, attempt 3 of 5, repair cycle 1; the arithmetic is verified and the
seven write-up errors the verifiers found are corrected, but the formal review
envelope and `final-gate` were never run. The two free data unlocks found on the
way (weekly option chains with real bid/ask 2019-2026, and whole-US-market daily
prices INCLUDING delisted companies, both free and no-login) are worth more to
this project than the trading result. Full detail:
`.omc/research/todo-111-proven-trading-edge/HANDOFF.md`.

## Goal

Use the proven outcome-loop plugin from TODO #110 to find, honestly test, build,
and independently verify a profitable trading feature. Completion means a
built feature that passes strict untouched historical testing after realistic
costs and independent reproduction. It does not mean guaranteed future profit.

## Mission-specific permissions and limits

- Real-money brokerage orders are forbidden.
- Paper, simulated, or play-money brokerage orders are allowed only after the
  program confirms that the selected account cannot place a real-money trade.
  Any ambiguity is a hard stop for that order.
- Use free and already-owned data first.
- Total new data spending is capped at one one-time purchase of no more than
  $50 for the entire mission, not per candidate.
- Do not purchase data automatically. Before asking for the owner's payment
  approval, prove that the source can support at least five meaningfully
  different feature or method families, and verify its exact fields, dates,
  history, and sample output.
- Legitimate free trials are allowed. Cancel before renewal when the data has
  been retrieved. Do not rely on refund abuse.
- Existing browser access may be used for research, free sites, downloads, and
  normal account access. Payment, a new legal agreement, a login challenge, or
  a CAPTCHA may require the owner.
- Do not default to collecting new market data and waiting. Use existing
  historical evidence now.
- A positive historical options result may justify a later paper soak. Free
  website or API contract-price history is acceptable for the historical test
  even without historical execution proof, provided the exact source and fill
  assumptions are disclosed and harsh alternatives are tested.

## What prior attempts established

- The intraday dislocation family failed. Its best rule earned far less than
  the amount needed to cover costs.
- The professional day-trader bundle showed that context filters improved an
  opening-range rule, but the remaining move was still far too small.
- The tested opening continuation, prior value-area failure, and
  Fibonacci/failed-extension methods are closed to retuning.
- Schedule 13D remains untested because the required point-in-time security and
  corporate-action history was missing. Do not spend roughly $299 on that path.
- Several older trading ideas also failed. Read their final verdicts and the
  data-blocked inventory before proposing candidates so rejected families are
  not quietly recycled.

## Required loop behavior

1. Inventory every usable local, free web, API, and existing-account data source
   before selecting candidates.
2. Produce a slate of roughly five to ten meaningfully different profit
   mechanisms. Different thresholds, holding times, or indicator combinations
   inside one mechanism do not count as separate families.
3. Rank candidates by economic reason, available point-in-time data, expected
   move relative to costs, sample size, and risk of misleading results.
4. Run the data-feasibility gate before writing a large execution plan. A
   candidate that cannot be tested with available evidence is skipped, not
   executed into a late `NOT TESTABLE` verdict.
5. Freeze each chosen test before outcomes are examined. Combinations of
   indicators may be the primary rule when the combination itself has a clear
   reason; do not require each ingredient to win alone.
6. Test realistic fills, fees, spread, slippage, borrow limits, gaps, missing
   prices, concentration, losses, and untouched time periods as applicable.
7. Send the frozen mission and raw artifacts to a separate read-only reviewer.
   The reviewer must rerun important results through an independent code path
   and attack future information, survivorship, selection, fill, and cost
   assumptions.
8. If a candidate fails, record exactly why, update the rejected-family ledger,
   and continue with a genuinely different candidate.
9. When a candidate passes, build the owner-only feature, replay it, inspect the
   actual Discord output, and run the full project checks.
10. Finish only when the machine pass gate, independent reviewer, implementation
    checks, and user-visible proof all agree.

## Historical options evidence rule

Free historical options charts or API prices can support a backtest when the
contract, strike, expiration, date, and entry/exit times are recoverable. If the
source supplies only last price, midpoint, or chart marks rather than executable
bid and ask prices, the report must say so plainly and repeat the result with
conservative fills and costs. A passing result is a historical candidate that
may justify paper testing; it is not historical proof of actual fills.

## Main files to read first

- `.omc/research/professional-day-trader-methods/FINAL-VERDICT.md`
- `.omc/research/professional-day-trader-methods/adversarial-review.md`
- `.omc/research/schedule-13d-follower-edge/FINAL-VERDICT.md`
- `.omc/research/immediate-profitable-share-feature/FINAL-VERDICT.md`
- `.omc/research/intraday-dislocation/FINAL-VERDICT.md`
- `todo/data-blocked-feature-inventory.md`
- The completed plugin and mission template from TODO #110.

## Completion requirements

- The reusable plugin's false-pass and valid-pass tests have already succeeded.
- At least five genuinely distinct candidate families were considered with a
  completed data-feasibility result before any optional data purchase.
- The winning rule passes its frozen numerical profit and risk gates on
  development and untouched historical periods after realistic costs.
- No future information, current-survivor selection, final-minute volume, or
  other unavailable-at-decision facts enter the result.
- No single stock, analyst, date, or unusual trade explains the pass.
- A separate reviewer independently reproduces the load-bearing result and
  approves the claim.
- The feature is built owner-only, produces clear Pacific-time output, and is
  verified through its real user-visible path.
- No real-money order is placed.

## True owner-only blockers

- Approving the single optional data purchase, capped at $50 total.
- Completing a payment, login challenge, CAPTCHA, or new provider agreement.
- Enabling a production alert or any action that could reach a real brokerage
  account.

### Session notes — 2026-09-02
- **Worked on:** Ran `/loopgoal #111` and interviewed the owner into a frozen mission + checker: `.omx/plans/todo-111-proven-trading-edge-mission.json` and `scripts/research/todo_111_proven_trading_edge_gate.py` (validates clean; fake-pass at 21.5% exits 0, fake-fail at 19.9% is refused, all four feasibility modes pass).
- **Decisions:** Two-track profit bar — shares 1% average per trade after costs over 200+ trades, options 20% over 40+ trades, losers included. Credit-spread return = (premium collected − premium paid to close) ÷ premium collected. Random-entry control DROPPED — the owner trades long, short, debit and credit spreads, so market drift can't fake a direction-agnostic rule. Finish line also drops the Discord-output and full-test-suite checks at the owner's request; it keeps the untouched period, independent reproduction, best-ticker-removed retest, and harsh option fills. Budget $50 / one purchase / owner approves first / paid only after free is exhausted. 5 attempts, then write handoff notes and stop.
- **Next:** Start the loop with the kickoff line above; the builder and reviewer must be separate agents from the controller.


### Session notes — 2026-09-03
- **Worked on:** Ran the outcome-loop mission end to end. Three candidates, each frozen before any outcome was read.
- **Candidate 1 REJECTED** — selling out-of-money put credit spreads held to expiry, 18,992 trades 2019-2022: **-323% per trade** against a +20% bar, -136% dollar-weighted. Losers are ~9x winners at those strikes and a 71.5% win rate cannot pay for it. Fails at every credit size and in every year.
- **Candidate 2 REJECTED** — shorting both legs of ten matched leveraged fund pairs monthly, 967 trades 2010-2018: **-0.61% per trade** against a +1.0% bar. The decay is real and measured at +0.70%/month gross, which is under the bar before any cost.
- **Candidate 3 PASSED the bar** — twelve-month relative strength skipping the last month, top twenty, three-month hold. Development (2019-02..2022-09) **+6.89%** over 880 trades; untouched, sealed until the development number was locked (2023-01..2026-05) **+10.74%** over 820; combined **+8.75%** over 1,700. Equal-weight benchmark +3.12%.
- **But it does not fit the owner.** Three-month holds against minutes-to-days trading. Recorded as the binding limit at the top of the handoff and in the proof bundle. Not usable as-is; do not re-propose it as a trade.
- **Two free data unlocks** (both new to this project, both no-login, no key, no cost, via `https://www.dolthub.com/api/v1alpha1/<owner>/<db>/master?q=<sql>` and cloned locally with the `dolt` CLI):
  - `post-no-preference/options` — weekly EOD option chains with **real bid and ask** plus greeks, ~610 symbols, 2019-02 to now. The old "no free option bid/ask history exists" note was about MINUTE quotes.
  - `post-no-preference/stocks` — daily OHLCV for the **whole US market including delisted companies**, plus split, dividend and symbol tables. This removes the survivorship limit that capped every earlier share study here.
- **Independent verification:** three read-only verifiers, none of which wrote a line of the code they judged, each rebuilt the pipeline from raw tables. All landed on 6.8943 / 10.7419 / 8.7502, matching trade for trade (largest disagreement 5e-07). One found a real defect (a ticker becoming a different company across a HOLE in the data was never caught, because the check only looked for a price jump); it was repaired with two frozen clauses and the fix RAISED development from +6.56% to +6.89%, because every trade it removed was built on a broken signal.
- **Both formal verdicts were REJECT/repair**, and every finding was a wrong number in the write-up rather than in the rule. All seven corrected, including one that was backwards: renamed companies were claimed to cost the rule, when the forced early exit actually helped those trades.
- **Not done:** the formal review envelope (`prepare-review` -> reviewer signature -> `review-result`) and `final-gate`. The loop never reached COMPLETE. Also unverified by anyone: the +3.12% benchmark and the "new to the feed" split.
- **Nothing is live.** No order of any kind, nothing bought, the $50 allowance untouched, no production alert enabled.
- **Next:** decide whether the minutes-to-days horizon is worth a fresh mission using the two new data sources, and whether to close this loop formally or leave it parked.
