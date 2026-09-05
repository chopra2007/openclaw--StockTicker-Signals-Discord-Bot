# Build a profitable trading feature through the outcome loop
**Status:** OPEN
**Created:** 2026-08-29

**CURRENT STATUS (2026-09-05, latest):** **The sealed 2022-2026 window is now
OPEN and all five finalists have been measured on it. Nothing is proven, and
nothing is live.** Of the five frozen finalists, **two are dead** — they lose
money after commission on fresh data — and **three survive as "promising, not
proven"**. The best of them (test 11: sell a put spread when options are
charging a lot for fear, take profit at +50% of the credit, stop at -200%)
clears **every numeric bar** the frozen rules set for a proven winner: 265
development trades and 136 sealed, **74.3% wins**, positive after commission,
positive against maximum risk. **I would still not trade it**: it made **$249
in total while at one point sitting $1,284 underwater**, tying up $1,698, at a
profit factor of **1.06** — it wins $1.06 for every $1.00 it loses. The frozen
rules require "acceptable drawdown"; that is not acceptable. Every finalist
shrank sharply from development to sealed: per trade after commission, test 1
+$0.05 → **-$0.004**, test 11 +$0.14 → +$0.02, test 26 +$0.12 → +$0.09, test 28
+$0.18 → **-$0.03**, test 40 +$0.19 → +$0.04. **Money: $12.4457 of the $20.00
ceiling.** Results: `research-data/todo-111-tournament/results_sealed.json`.

**An important correction to my own earlier conclusion this session.** Partway
through, the data provider throttled us (4.4GB, 1,172 requests, 7 seconds a
request becoming minutes) and the call-spread mechanism was left
half-downloaded. On that partial data it was TOP of the table, so I excluded it
— a half-downloaded sample is not a random one — and froze five finalists that
were **all put credit spreads**, writing that "the edge is one-sided". The
download then finished, and on complete data **the call spreads are the best
mechanism in the tournament, about eight times better per dollar at risk than
the best put spread**. The finalists were re-frozen (commit `2bdc8e1`,
superseding `25faa1c`) as **1, 11, 26, 28, 40** across three mechanisms and two
structures. Revising was legitimate because no sealed outcome had been read, but
the earlier list was a product of missing data.

**A pattern that showed up twice and is worth knowing:** both winning
mechanisms work in ONE direction only and the mirror of each loses money —
selling put spreads works while selling call spreads loses (-11.47%, -29.30%),
and buying call spreads in an uptrend works while buying put spreads in a
downtrend loses badly (-8.87%, -17.23%, -3.47%). Do not assume a "bearish
version" of a working rule will work.

**What lost money, settled on complete data rather than excluded for a gap:**
every volatility-buying test (straddles and strangles, -0.75% to -6.00%), every
call credit spread at every boundary, the iron condors (best makes $764 against
a $1,984 drawdown), and every downside directional spread.

**Three defects were found and fixed, all in rules I wrote, all recorded as
dated amendments before the outcomes that could have motivated them:** the event
trigger compared a ten-day option price against a one-day stock move so "options
look cheap" could never fire (sample went from 0/181 to 101/77 once corrected);
six releases fall on Good Friday when the market is shut and one gap poisoned
the next twelve readings (44 dates looked broken, only 6 were); and mechanism 6
had no expiry window. Mechanism 6's selection gate PASSED a three-way
reconstruction test but its data was never bought.

Spent **$5.09** this session, **$8.57** of the $20 ceiling in total, $5 sealed
reserve intact. Nothing live, no order real or paper. Write-ups:
`todo/todo-111-tournament-result.md`,
`todo/todo-111-tournament-finalists.md`,
`todo/todo-111-tournament-frozen-matrix.md`. **Next session starts here:** the
event legs and the 242 sealed chain snapshots are downloading; when they land,
run `python3 scripts/research/todo_111_tourney_sealed.py evaluate 1 11 26 28 40`
(about $2.75), then have a reviewer who did not write the code reproduce any
sealed winner. Prior status:

**CURRENT STATUS (2026-09-03):** The **option half is no longer
blocked**, and the session ended with **two owner decisions that change how the
next test is run**. With the owner's Databento authorisation, minute-level
option bid/ask was bought for the first time in this project — $3.4836 of a $20
ceiling, about $121.52 of the $125 credit left. **Selling** a SPY expected-move
iron condor was frozen before anything was bought and is **REJECTED on
development**: 241 trades 2014-2021, win rate 29.88% against a 60% bar, -14.75%
a trade against +4.00%. The sealed 2022-2026 window was never opened. **The two
decisions, both for the next session, neither executed:** (1) **all future fills
are at the midpoint of the bid and ask**, not the bad side of each quote — a
standing change that overrides the handoff and the frozen rule file, and one
that matters because the bad-side round trip costs a median 9% of the credit;
(2) **BUYING that same condor is now a live candidate** — the exact mirror is a
**70.12% win rate** (169 of 241) and a naive +14.75% a trade, better than
anything this project has tested, but it has never been computed with the buyer
paying to get in, so midpoint fills, gap concentration and the buyer's own
denominator all have to be measured first, on data already on disk. He wants
more than one strategy running, so a pass joins the others rather than replacing
them. Detail: `.omc/research/todo-111-condor/` and the two newest session notes
at the bottom. Prior status:

**CURRENT STATUS (2026-09-03):** Round 3 is **finished and stopped**; the owner
has since made two decisions and both are recorded below. Six genuinely
different mechanisms, ten entry rules, **all ten rejected** against matched
same-time-of-day baselines. The two strategies the owner named were built and
tested first: the 15-minute opening-range breakout reached the +1% target before
the -0.5% stop **34.08%** of the time (32,010 trades) against **34.00%** for
trading at that hour with no trigger at all, and the overnight-range breakout
**34.23%** against the same 34.00%. Best of the whole set was an 11:00 trend-day
trade at **35.94%**; the bar is **60%**. A ceiling test then settled whether an
eleventh idea was worth building: cherry-picking the 20 best stock/hour/direction
combinations with full hindsight reached **44.11%** and carried forward to only
**37.93%**, so about 38% of an apparent edge in these bars survives fresh data —
that bounds any picking rule, though not literally every trigger. Two directions
remain untestable and neither is a rejection: the option half (no intraday option
prices — the one decision still waiting on the owner) and anything using
information outside the price series (the bot's 1.58M signal records all start
July 2026, years after the July-2025 development cutoff; a waiting problem, not a
money one). Loop STOPPED on the frozen `owner_only_decision` condition, 13
evidence artifacts, $0.00 spent, no order real or paper, sealed period never
opened. **The owner's two decisions:** (1) the months-long #111 momentum method
**stays an option rather than a rejection**, because he can run more than one
strategy at once, so its three-month holds no longer disqualify it — it is not
live and nothing was enabled; (2) he asked to test an even **+0.5% / -0.5%**
bracket, which was measured the same session: win rates rise to roughly a coin
flip (baseline 34.00% → **49.66%**, opening-range breakout → **50.27%**,
overnight breakout → **50.07%**, trend-day trade → **53.06%**) while the average
per trade stays flat, because at +0.5/-0.5 the win rate needed to average +0.40%
a trade rises from 60 in 100 to **90 in 100**. Same distance from the bar, new
shape. Write-ups: `todo/todo-111-round3-result.md`,
`todo/todo-111-round3-rejection-ledger.md`, numbers in
`.omc/research/todo-111-round3*`. Prior status:

Round-2 mission is FROZEN and validated. Files:
`.omx/plans/todo-111-trading-edge-round2-mission.json`
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


### Session notes — 2026-09-03 (round 2, first measurement pass)
- **Worked on:** ran the round-2 mission from `init` onward: extracted the local one-minute bars, measured the baseline, declared the sealed period, wrote and passed all four feasibility checks, then pre-screened eleven entry triggers.
- **The baseline.** A randomly chosen entry, closed on the first touch of +1.0% for or -0.5% against, hits the target first **34.47%** of the time on EQUS.MINI over 695,484 sampled trades, and **34.56%** on XNYS.PILLAR over 730,536. Theory said 33.3% (the stop is a third of the 1.5% round trip). Two independent feeds agree to within a tenth of a point.
- **Eleven ideas, eleven rejections.** Best 35.29% (quiet half hour then a break out of it), worst 33.68% (one-minute volume spike, ridden). The whole spread from best to worst is 1.6 points, around a baseline of 34.5, against a bar of 60. Full table with the reasoning behind each idea: `.omc/research/todo-111-round2/rejection-ledger.md`.
- **Why they all sat still.** To win 60 in 100 on a 2:1 bracket a trigger has to predict an average **+0.40% move per trade**. Every earlier short-horizon study here (#103, #104, #106) measured 1 to 5 basis points of gross edge. The ask is roughly a hundred times what has ever been measured.
- **The bar is one condition, not two.** 60 wins at +1.0% against 40 losses at -0.5% averages exactly +0.40%. The win rate and the average say the same thing, so there is no way to satisfy one and miss the other.
- **The sealed period was never opened.** Development is everything before 2025-07-01; the fourteen months after it are untouched. The pre-screen physically drops the sealed bars rather than trusting a filter, and the last entry signal is taken three weeks before the seal so no trade can run into it.
- **No candidate was registered.** The loop is still at `DISCOVERY`, attempt 1 of 5. That is deliberate: the owner's decision 4 asked for a cheap pre-screen precisely so a dead idea never consumes a full frozen backtest. Seven evidence files are recorded in the loop's ledger (baseline, rejection ledger, the four feasibility files, the raw pre-screen numbers).
- **The option half could not be tested at all.** There is no intraday option price history on this machine. The free DoltHub chains are one end-of-day snapshot a week, and `data/options-dx-2023/*.zip` are 2,618-byte failed downloads. Without minute-level option prices there is no way to see whether an option touched +20% before -20%.
- **Nothing spent, nothing live.** $0.00 against a $0.00 cap, no purchase, no signup, no login attempted, no order real or paper, no alert enabled, nothing pushed.
- **Built this session:** `scripts/research/todo_111_round2_baseline.py`, `..._prescreen.py`, `..._market_move.py`, plus a chunked first-touch search in `..._bracket.py` verified identical to the full scan on 24,000 sampled trades.
- **Next:** the owner decides on intraday option data. For shares, the untried categories are event-driven ideas (excluding the families already rejected in #93, #97, #103, #106) and anything using information that is not in the price series.

### Session notes — 2026-09-03 (round 3 run end to end, then the owner's two decisions)
- **Worked on:** ran round 3 from `DISCOVERY` to `STOPPED`. Six genuinely different mechanisms, ten entry rules, a hindsight ceiling test, and — after the owner's reply — a test of the bracket's shape itself.
- **The two strategies the owner named, both built and tested in both directions.** 15-minute opening-range breakout: 32,010 trades, target first **34.08%**, against **34.00%** for trading at the same time of day with no trigger at all. Overnight-range breakout: 15,073 trades, **34.23%** against the same 34.00%. Faded versions were worse (33.41% and 33.72%).
- **Four more mechanisms, one per direction the owner pointed at.** Two conditions that must agree (break + the other 59 names moving the same way): 34.63%. The day's character (break only on unusually wide mornings): 34.35%. The time of day as the reason to trade (at 11:00, buy what climbed all morning): **35.94%**, best of the whole set. Range-day fade: 33.36%. Cross-sectional rank of all 60 names: 34.19% momentum, 33.95% reversal.
- **Matched baselines are new in round 3.** Round 2 scored everything against one all-day baseline of 34.47%. The bracket's odds are not the same at 09:45 as at 15:30, so each family here is compared with a no-trigger baseline that trades at the same time of day (34.00% at 11:30, 34.77% at 11:00).
- **The ceiling test — the reusable result.** Split development in half at 2024-05-01; with full hindsight pick the 20 best combinations of stock, hour and direction in the first half; trade exactly those in the second. Hindsight: **44.11%**. Carried forward: **37.93%** on 5,057 trades against a 34.28% baseline. About 38% of an apparent edge in these bars survives fresh data. It bounds any *picking* rule; it is not a proof about every trigger, since a trigger reacts to the day as it happens.
- **Information outside the price series is blocked by time, not money.** The bot's own database holds 1,581,606 ticker signals and 213,713 options-flow rows, and the oldest are dated 2026-07-30 and 2026-06-01. Development ends 2025-07-01, so the entire collection sits inside the sealed period. Nothing to test on for roughly two more years; the collecting is already running. Measured live in `.omc/research/todo-111-round3/feasibility-data.json`.
- **The option half is still untestable.** Unchanged from round 2: weekly end-of-day chains only.
- **Loop STOPPED on the frozen `owner_only_decision` condition**, 13 evidence artifacts, $0.00 spent, no order real or paper, sealed period never opened.
- **The owner's two decisions, given after seeing the above.**
  1. **The months-long momentum method stays an option, not a rejection.** His words: *"since I can trade more than one strategy simultaneously, i'd like to keep this as an option"*. So #111 momentum (+6.89% development, +10.74% sealed, verified three times, three-month holds) is no longer disqualified by the minutes-to-days horizon — it can run alongside a short-horizon rule rather than instead of one. It is not live and nothing was enabled.
  2. **Test an even bracket, +0.5% target against -0.5% stop.** Done the same session, and the answer is arithmetic rather than opinion: the win rate rises to almost exactly a coin flip and the money does not move. No-trigger baseline 34.00% → **49.66%**; opening-range breakout 34.08% → **50.27%**; overnight breakout 34.23% → **50.07%**; the 11:00 trend-day trade 35.94% → **53.06%**. Average per trade stayed flat or slightly negative in every case. The catch: at +1.0/-0.5 a rule needs 60 wins in 100 to average +0.40% a trade, and at +0.5/-0.5 the same +0.40% needs **90 wins in 100**, because each win now pays half as much while each loss still costs the same. Every family stayed the same distance from its own bar. Numbers: `.omc/research/todo-111-round3-bracket-shape-equs.json`, harness `scripts/research/todo_111_round3_bracket_shape.py`.
- **Built this session:** `scripts/research/todo_111_round3_prescreen.py` (add a family to `FAMILIES` and it is measured), `..._panel.py` (anything ranking names against each other), `..._ceiling.py` (the hindsight test, reusable on any new data), `..._ledger.py` (writes the ledger so no number is typed by hand), `..._feasibility_data.py`, `..._bracket_shape.py`.
- **Verified end to end, not just by reading the code:** JPM 2023-04-04, 15 opening-range bars, range 129.18–130.57, first break below at 09:46, short entered at the next bar's open 129.06, target touched at 11:18 the same day for +1.0%.
- **Committed:** `15de447`. Write-ups at `todo/todo-111-round3-result.md` and `todo/todo-111-round3-rejection-ledger.md`.
- **Next:** the outstanding owner decision is intraday option prices — still the only way to test the option half. On shares, the untried ground that the ceiling test does not cover is a trigger that reacts to the day as it happens using information from outside the price series, and that has no history to run on until roughly 2028. A fourth round on these bars is not worth freezing.


### Session notes — 2026-09-03 (SPY expected-move iron condor — REJECTED on development)
- **Worked on:** the owner's Databento authorisation. Built and ran the whole option half of #111 that every earlier round listed as untestable. The blocker was never the idea, it was minute-level option bid/ask; that is now bought and on disk.
- **Frozen before anything was bought.** Entry weeks were chosen from free data only — VIX against SPY's own 20-day movement (a gap of at least 2 volatility points), plus a calm-market filter on the 14-day average true range. 279 development weeks, 160 in a sealed 2022-2026 window, both counted before a dollar was spent. Rule file `.omc/research/todo-111-condor/FROZEN-RULE.md`, sha256 `5668ed1e…`, plus `policy-clarifications.md` for three mechanical points. The rule was amended once, for two selector defects (a 37-day target that kept picking thin weekly expiries with no $5 wing, and a far wing with a 0.00 bid being treated as unlisted) — both found and fixed **before any trade return existed**, superseded hash recorded in the file.
- **REJECTED.** 241 condors, 2014-2021. Win rate **29.88%** against a 60% bar, average **-14.75%** a trade against +4.00%. The put spread alone: 36.10% and -8.86%. The call spread alone: 28.63% and -10.93%. All three declared in advance, all three fail wide.
- **The two findings worth keeping.** (1) **A percentage stop does not cap the loss on short premium.** It can only act while the market is open, and the position gaps overnight: 43 trades finished worse than -25%, 14 worse than -40%, 5 worse than -100%, worst -339%. Average winner +20.8%, average loser -29.9% — that shape needs a 59% win rate just to break even. It is the round-1 nine-to-one loser, shrunk by management but not removed. (2) **A ±20% band is close to the cost of trading four legs.** Getting in and straight out costs a median 9% of the credit, and on the first trade in the sample it cost 21.5%, tripping the stop one minute after entry.
- **The sealed 2022-2026 window was never opened.** Its data was estimated ($2.81) and reserved, then not bought — a candidate that fails development does not earn a second look, and the window stays clean.
- **Money: $3.4836 of a $20.00 ceiling**, 527 requests, every one cost-estimated before it was sent. About **$121.52** of the $125 Databento credit is left. Ledger: `research-data/todo-111-condor/spend_ledger.json`.
- **Data quality, checked before the result was read:** 246 four-leg files, **0 problems** — right dataset and schema, right contracts, no duplicate timestamps, no negative prices. All four legs quoted in **100%** of regular-session minutes; missing-minute rate 1.4e-06. No minute was invented. One trade re-computed by hand matched the script exactly (2014-01-03: credit $0.93, close $1.13, -21.51%).
- **Sample fairness:** 38 of 279 weeks dropped, nearly all because a $5 wing strike was not listed. The dropped weeks were **calmer** (median VIX 13.3 against 14.4), so the drop did not quietly remove the hard weeks.
- **Built:** `scripts/research/todo_111_condor_signal.py`, `..._pull.py`, `..._validate.py`, `..._backtest.py`. Write-up: `.omc/research/todo-111-condor/DEVELOPMENT-RESULT.md`.
- **Nothing live.** No order real or paper, no alert enabled, nothing pushed.
- **Next:** the option half is no longer data-blocked — minute bid/ask for any SPY contract back to April 2013 costs about $0.004 a trade, and $121 of credit is left. The next short-premium candidate has to answer the two findings above before it is worth freezing: a wider bracket, fewer legs, or an exit that does not depend on a price being quotable at the moment it is needed.


### Session notes — 2026-09-03 (owner's two decisions after the condor result — NOT executed this session)
- **Decision 1 — fills move to the midpoint. This is a standing change to every future test.** Buys and sells are priced halfway between the bid and the ask, not on the bad side of each quote. His words: *"i want buys and sells at the halfway point between the bid/ask. no more bad side of every quote, just in the middle."* This overrides the "sell at bid, buy at ask" instruction in the Databento handoff (`.omc/plans/todo-111-databento-download-handoff.md`) and the fill clause in `.omc/research/todo-111-condor/FROZEN-RULE.md`. It matters a lot here: getting in and straight out of four legs at the bad side costs a median **9% of the credit**, and that cost, charged twice, is what turned the mirrored condor from +14.75% into roughly break-even. **Every frozen rule written from now on states midpoint fills.** The existing condor data supports a re-run at midpoint with no new purchase — the raw bid and ask for all four legs, every minute, are already on disk.
- **Decision 2 — the reversed condor is now a live candidate, and it may be the best thing tested so far.** BUYING the expected-move iron condor is the exact mirror of the rule that was rejected: **70.12% win rate** (169 of 241) against the 60% bar, and a naive **+14.75%** a trade against the +4.00% bar. His words: *"a 70%+ win rate is better than anything we've ever tested. This may be the most winning strategy so far."* Buying the call spread alone mirrors to **71.37%** and +10.93%. Nothing else in this project has come near a 70% win rate — every share family sat at 34%.
- **What is NOT yet known about it, and must be measured before it is believed.** The +14.75% is the seller's loss with the sign flipped; it has never been computed with the buyer actually paying to get in. Three things to settle, in this order, all on data already bought: (1) re-run the mirror with **midpoint fills on both sides** — the single number that decides it; (2) check the concentration — a handful of overnight gaps carry much of it (5 mirrored trades over +100%, one +339%), and stripping those takes the naive average from about +14.75% to about +11.5%; (3) restate the returns against **what a buyer actually risks** (the debit paid), not against the seller's credit, because the two denominators are different sizes. Only after those three does the sealed 2022-2026 window get opened, and that costs about **$2.81** of the ~$121.52 Databento credit still available.
- **He wants more than one strategy running.** Consistent with his 2026-09-03 decision to keep the months-long momentum method as an option: a candidate that passes does not replace the others, it joins them. Do not frame future results as a single winner-takes-all choice.
- **Nothing was executed for either decision this session.** No re-run, no new purchase, no order real or paper, no alert enabled.
- **Next session starts here:** re-run the condor mirror at midpoint fills on the existing files, then decide about the sealed window.


### Session notes — 2026-09-05 (the sealed window opened — 2 dead, 3 promising, nothing proven)
- **The sealed 2022-2026 test ran on all five frozen finalists at once**, after every finalist was frozen and before any outcome was read. Command: `python3 scripts/research/todo_111_tourney_sealed.py evaluate 1 11 26 28 40`. Results `research-data/todo-111-tournament/results_sealed.json`, stamped `frozen_finalist_ids` and `frozen_at_utc`.
- **Every finalist shrank, several of them to nothing.** Per trade after the stated $0.45/contract/side commission, development → sealed: test 1 **+$0.0547 → -$0.0036**; test 11 +$0.1431 → **+$0.0201**; test 26 +$0.1212 → **+$0.0908**; test 28 **+$0.1828 → -$0.0320**; test 40 +$0.1867 → **+$0.0396**. Win rates fell 5-17 points across the board. Two went negative; the other three kept 20-75% of their development edge.
- **Verdicts.** REJECTED: tests **1** (loses after commission, profit factor 0.99) and **28** (loses after commission). PROMISING, NOT PROVEN: tests **11**, **26**, **40**.
- **Test 11 clears every numeric bar for HISTORICAL WINNER and I still would not trade it.** 265 development trades, 136 sealed, **74.3% wins** (95% CI 66.3-80.9%), average gross **+4.38%**, **+$0.0201** a trade after commission, **+0.44%** on maximum risk, concentration clean (best trade 3%, best 5 trades 12%, best year 17%). But **total profit $248.70 against a maximum drawdown of $1,284.40** — you sit five times your eventual gain underwater — with **$1,697.50** of risk on at once and a **profit factor of 1.06**. Section 11 requires "acceptable drawdown"; that is not acceptable. The independent reproduction section 11 also requires has **not** been done.
- **A bug in my own verdict code, found because the owner questioned a number.** He asked why a strategy with only 56 sealed trades was entered in a contest whose top verdict needs 100. Checking that surfaced something worse: `apply_cheap_rejection` reads `dev_trades`, but the sealed results file holds **sealed trades only**, so that field was **0 for every finalist** and rule 1 ("fewer than 30 development trades") fired on all five — including tests with 265 development trades. Everything was stamped **REJECTED**, and I reported "all five lost their edge, nothing passed" to the owner. That was wrong. Fixed by judging the sealed period on sealed numbers while taking development counts from `results_dev.json`; re-ran; three of the five are PROMISING, NOT PROVEN. **Lesson: a rejection rule written for one period silently mislabels every result when reused on another.**
- **A real design flaw the owner named, and he is right.** The finalist bar is 30 trades (section 10) but the top verdict needs 100 in **both** periods (section 11). I knew before opening the window that tests 26, 28 and 40 could only supply 56, 29 and 93 sealed trades — three of five finalists entered a contest they could not mathematically win. My reason (cutting them would have left only put spreads, repeating the one-sided error I had already made once) was a reason for a **different** fix: **widen the weekly entry grid**. One entry per ISO week caps a selective trigger far below 100 sealed trades. Two or three candidate days a week would have given test 26 roughly 150 instead of 56. Do this before any further round.
- **Downloading got 10x faster and the fix is committed.** The serial downloader was buying one contract every **54.5s** with ~3.5 hours to go. Measured 1, 3 and 10 concurrent shards on the same work: **54.5s → 18.0s → 5.6s** per file, perfectly linear, so it was provider queueing and not an account cap. The remaining 231 contracts finished in about 20 minutes. `finish_pull.py` now takes a `shard/of` argument. Two safety fixes were needed for concurrency: `ledger_lock()` adds an `flock` (the old `threading.Lock` guards one process only, so two shards could each append and the second write would drop the first), and the ledger is now written through a temp file and renamed (`json.dump` truncates in place, so a shard calling `spent_all()` mid-write read half a file and died — that killed 2 of the 10 shards; they died before spending, and the ledger was verified afterwards: 2,221 entries, all 1,706 leg files recorded, no payment lost). Commit `466e195`.
- **Money: $12.4457 of the $20.00 ceiling**, every request cost-estimated before it was sent.
- **Nothing live.** No order real or paper, no alert enabled, no switch changed.
- **Next session starts here, in order:** (1) have a reviewer that did **not** write this code reproduce test 11's and test 26's load-bearing trades from the raw quote files — section 11 requires it and the bug above makes it matter more; (2) widen the entry grid to 2-3 candidate days a week and re-measure, which is the only way tests 26 and 40 can reach a 100-trade sealed sample; (3) mechanism 5 (scheduled events) has complete data on disk and was never scored — it is free to run.
