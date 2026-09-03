# Build a profitable trading feature through the outcome loop
**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-09-02):** Round-2 mission is FROZEN and validated,
nothing run yet. Files: `.omx/plans/todo-111-trading-edge-round2-mission.json`
and `scripts/research/todo_111_trading_edge_round2_gate.py`. New finish line is
a target-and-stop rule exited on first touch, with a hard 14-trading-day cap,
gross returns, and a $0 budget this session. Full detail in the newest session
note at the bottom of this file. Prior status, still true of round 1:

Loop is PARKED, not done. The one rule that
cleared the frozen bar holds each position three months; the owner trades minutes
to days, so it is a measurement, not a usable trade. On 2026-09-03 the owner set
the terms for a fresh session to continue (nothing executed yet): (1) add a hard
**14-trading-day holding cap** to the frozen gate — no longer-held rule can pass,
whatever its profit; the current gate checks profit/sample/robustness only and
has no trade-length rule, which is how the 3-month rule slipped through; (2) try
**5 genuinely different ideas per session**, multiple sessions expected; (3) do
real new research and idea generation, not a re-run of the old 6-family slate;
(4) first read the previous session's build to fix two process failures — the
loop hung at the test/verify/audit stages and never reached COMPLETE, and it
burned tokens running many tests that were never going to pass (needs a cheap
pre-screen); (5) find an **intraday (minute-level) option price source** — the
free weekly end-of-day chains cannot test intra-trade management like "close at
50% profit if touched". Credit spreads are NOT a closed family despite the
rejection ledger: only the single-stock, hold-to-expiry, no-stop version failed.
Full detail and the decision list: this file's newest session note and
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


### Session notes — 2026-09-03 (owner decisions for the next session — NOT executed this session)
- **Worked on:** Owner reviewed the loop's state and the candidate-1 credit-spread rejection. Conclusion: #111 is NOT done. "Passed but unusable" (the 3-month momentum rule) is worthless to the owner. The loop tried very little (3 mechanisms), tested a horizon the owner never accepts, and the rejection ledger over-generalised from one badly-designed test. All of the below is to be carried out in a FRESH session, not here.
- **Decision 1 — 14-day holding cap.** Add a hard rule to the frozen gate (`scripts/research/todo_111_proven_trading_edge_gate.py`) and the mission goal: every trade must open and close within **14 trading days**. Any rule that holds longer CANNOT pass, regardless of profit. This is the hole that let the 3-month rule through — the current gate checks profit/sample/robustness only, nothing about trade length.
- **Decision 2 — 5 ideas per session.** Try 5 genuinely different profit mechanisms per session (not 5 total for the mission). Multiple sessions expected. Raise/replace the mission's `maxAttempts: 5` accordingly.
- **Decision 3 — real new work, not a slate re-run.** More research, more understanding of why past attempts failed, genuinely new ideas, and more testing. Do not just walk the existing 6-family slate.
- **Decision 4 — fix last session's process failures first.** Before generating candidates, read the previous session's build (the outcome-loop run under `.omx/outcome-loop/todo-111-proven-trading-edge/` and the three attempt evidence folders). Two failures to solve:
  - The loop **hung at the testing and verification/audit stages** — got stuck in REVIEW, repair cycles, never reached COMPLETE.
  - It **burned tokens running many tests that were never going to pass** — need a cheap pre-screen so obviously-dead ideas are killed before a full frozen backtest.
- **Decision 5 — intraday option prices are required.** To test a managed credit spread ("buy it back if it touches 50% profit at any point", stop at 2-3x credit, 21-DTE time exit) you need **minute-by-minute (or at least intraday) option pricing**. The free DoltHub `post-no-preference/options` feed is **weekly end-of-day only** — it cannot see an intra-trade touch. Finding an intraday option price source (free first; the $50 single-purchase allowance is available with owner approval) is a prerequisite for the whole managed-credit-spread family.
- **Credit spreads are NOT a closed family.** The ledger's "do not re-propose selling option premium at any delta/width/holding time" is too broad. Only the single-stock, held-to-expiry, no-stop version was tested. A properly-designed version — index (SPX/XSP), take profit at 50%, time-exit by 21 DTE, hard stop at 2-3x credit, staggered weekly entries — was never tried and is a valid candidate once intraday pricing exists.
- **Also still untested from the original slate:** earnings implied-volatility crush (short strangle), put/call skew relative value (risk reversal), long-dated call on a persistent trend.
- **Close out the momentum attempt.** Record candidate 3 as "measured, does not meet the 14-day horizon" and stop polishing its write-up. Do not run its formal review envelope / `final-gate` just to reach COMPLETE on an unusable rule.
- **Next:** fresh session — start by reading the previous build for the hang/token-waste fix (Decision 4), then update the gate + mission (Decisions 1, 2), then research an intraday option price source (Decision 5), then generate 5 new candidate families and run them.


### Session notes — 2026-09-02 (round-2 plan reworked — still nothing built)
- **Worked on:** Re-read the round-1 build and every prior short-horizon
  verdict, researched intraday option price sources and the candidate
  mechanisms, and wrote the reworked plan:
  **`todo/todo-111-round2-strategy.md`**. No code changed, no data bought,
  no test run.
- **The finding that reframes the mission:** every short-horizon failure in this
  project (#103 +5.1 bps, #104 +1.0/−0.4/+3.3 bps, #106 +4.7 bps) missed a
  ~40 bps need *with trading made free*, while the only pass held three months
  and cleared its bar by 47x. Edge grows with holding time; cost does not. At a
  14-day cap, share rules barely clear the 1% bar in the best case ever
  measured — so round 2 is effectively an **options** mission (4 of 5
  candidates).
- **Pre-screen designed (Decision 4b):** both round-1 rejections were
  predictable from one division before any backtest. Candidate 1 needed a ~90%
  win rate and had 71.5%; candidate 2's gross decay was +0.70%/month against a
  +1.0% bar. Three kill numbers, 30 minutes each, no ceremony: gross size at
  zero cost, move-to-cost ratio (under 3 = stop), structural win rate.
- **Hang cause found (Decision 4a):** all seven reviewer findings were
  hand-typed numbers in the write-up files drifting from what the code produced.
  Fix: no number typed by hand, exercise the review envelope early on a
  throwaway result, cap repair cycles at one.
- **Gate hole confirmed:** `todo_111_proven_trading_edge_gate.py` has no
  trade-length rule at all. The 14-trading-day cap has to be added to the
  checker, not just the mission text.
- **Intraday option data found (Decision 5):** optionsDX sells SPY/SPX/QQQ/VIX/
  NVDA/TSLA/AAPL/UVXY/SLV chains with bid/ask + greeks, 2010–2023, at end-of-day
  through minutely, $0–$50 a symbol-year, and its FAQ says free variants need no
  billing details. Backups: Databento CBBO-1m (minute NBBO back to 2013,
  $125 free credit for a new team) and ThetaData $40/mo or Polygon $29/mo.
- **Killed by research, do not spend a session on it:** post-earnings drift at
  ≤14 days — published reviews say the drift is mild through the first two weeks
  and only accelerates at days 20–75, and it has largely vanished for large
  liquid US names.
- **Two owner decisions are open** (share bar vs 14-day cap; optionsDX checkout
  or the $50 purchase). Both are in section 9 of the plan file.
- **Next:** owner answers the two decisions, then a fresh session works section
  10 of the plan in order.

### Session notes — 2026-09-02 (round-2 mission frozen — nothing run yet)
- **Worked on:** Ran `/loopgoal` and interviewed the owner into a new, separate
  round-2 mission. Round 1's mission and gate are untouched and stay on record.
  New files: `.omx/plans/todo-111-trading-edge-round2-mission.json` and
  `scripts/research/todo_111_trading_edge_round2_gate.py`.
- **The finish line changed shape.** Round 1 asked for an average return over a
  hold to a date. Round 2 is a target-and-stop rule exited on FIRST TOUCH:
  - Shares: +1.0% target, -0.5% stop, whichever is touched first. Must win
    60 in 100, average at least +0.40% a trade, over 200+ trades.
  - Options: +20% target, -20% stop, first touch. Must win 60 in 100, average
    at least +4.00% a trade, over **100+** trades (raised from 40 mid-interview
    once it was shown the local weekly chains hold ~300,000 observations, so
    100 costs nothing).
  - Hard **14-trading-day cap** on every trade. The gate refuses a longer hold
    whatever the profit. Verified: a 63-day hold is rejected by the checker.
  - Trades may be staggered; several may be open at once.
  - Returns are **gross** — no commission, spread or slippage. The owner
    subtracts costs himself. A bundle claiming to be net of costs is refused.
  - Exit must be decided on **one-minute prices or finer**. Verified: a bundle
    saying `one_day` is rejected, and a data-feasibility file with only daily
    sources is rejected.
  - Entry must name what was observed. A fixed schedule ("buy at the open every
    day") is refused.
- **Dropped at the owner's request:** the best-ticker-removal test (his note: a
  20%-loss name shorted beats a 10%-gain name bought, so removing the top
  contributor misreads a direction-agnostic rule) and the harsh-fill retest
  (moot once returns are gross). Kept: fresh untouched period, independent
  reproduction by a separate read-only agent.
- **Budget is $0.00 this session, 0 purchases.** Every login, signup, payment
  and CAPTCHA is deferred to a single owner decision list written at the end.
  `place_real_money_order` and `place_paper_order` stay forbidden — the owner
  did not tick that box in the interview, but it is a standing hard rule of
  #111 and nothing this session asked to relax it. 5 attempts, then stop.
- **Correction to an earlier note in this file:** local minute data is not a
  ~41-day rolling window. `/home/openclaw/.openclaw/research-data/databento/`
  `opening-auctions/selected60_2023-01_to_2026-08/` holds **2.1 GB of real
  one-minute bars for 60 symbols, Jan 2023 to Aug 2026** (equs-mini from
  2023-03-28, xnys-pillar from 2023-01-01), already downloaded, no login. This
  is what makes a first-touch share test possible at all.
- **Intraday OPTION prices are still missing.** `data/options-dx-2023/*.zip`
  are 2,618 bytes each — failed downloads, not data. The local DoltHub chains
  (509 weekly snapshot dates, 2019-02 to 2022-12, ~610 symbols) are weekly
  end-of-day and cannot see a touch. So the option half of the finish line is
  blocked until the owner decides on a data purchase or a login.
- **Proof the gate works:** `validate-mission` returns `"valid": true`
  (sha256 9e82e293…). Fake pass exits 0. Fake fail (untouched win rate 59.9%
  against a 60.0% bar) exits 1. 63-day hold exits 1. Daily-bar exit exits 1.
  All four feasibility modes pass on real evidence and the data mode refuses a
  daily-only source.
- **Next:** owner starts the loop, or it waits. Kickoff line:
  `Run the outcome-loop mission at .omx/plans/todo-111-trading-edge-round2-mission.json`
