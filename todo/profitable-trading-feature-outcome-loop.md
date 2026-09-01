# Build a profitable trading feature through the outcome loop
**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-09-01):** READY FOR A FRESH SESSION. TODO #110 is complete:
the reusable loop passed 125 focused tests, 3,970 full-project tests, two saved
proof missions, cleanup review, code review, and design review. TODO #111 has not
started. Its frozen mission and one-line kickoff are ready under `.omx/plans/`.

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
