# Prove a high-conviction opening-auction trading edge

**Status:** DONE — rejected
**Created:** 2026-08-23

**CURRENT STATUS (2026-08-24):** CLOSED — no edge found, three ideas tested and all rejected. The final bounded pass tested the two genuinely new mechanisms (auction pressure versus the actual price response, and prior-close-to-next-open pressure transfer) as six rules frozen before any result existed. All six lost money. The ranked strategy produced 25 trades where 200 were required and lost 29.7 basis points each; nine of ten pass/fail gates failed. Before trading costs the best rule earned +10 basis points against the roughly +35 needed. An independent reviewer rebuilt every headline number and 50 individual trades from the raw exchange files with their own code, matched them exactly, and found no timing, direction, join or cost error. The 182 held-out evaluation dates were never read and stay sealed. Nothing was spent; no live scanner was built. Do not buy more auction data for this idea. Full write-up: `.omc/research/opening-auction-pressure-response/final-research-verdict.md`.

## Goal

Find and independently prove a real, tradeable signal that can produce zero to four high-conviction stock setups during 6:15–6:45 a.m. Pacific. It must still work after a five-minute reaction delay and realistic trading costs. Build a live scanner only after the historical test passes. Twenty setups in a day is a research ceiling, not a quota.

## What worked so far

- The research process rejected weak results instead of promoting them.
- The first attempt tested ordinary opening-range breakout and VWAP-reclaim ideas and found no reliable advantage.
- The second attempt built and independently checked earnings, company-news, and biotechnology-event lanes. It found important timing and data-quality errors before anything went live.
- Historical data is now in hand for a different direction: how the exchange's opening buy/sell imbalance changes before the open, how its indicated clearing price moves, and what the stock does afterward.
- The main collection contains 60 liquid New York Stock Exchange names from 2023 through August 21, 2026: 45,313,852 imbalance records plus two independent sources of one-minute prices. Total: 85,592,212 records and 1,955,770,368 downloaded bytes. The whole research-data folder is 2.1 GB.
- Databento charges totaled $116.528388, leaving $8.471612 of the $125 free credit. Do not download more paid data without a fresh cost check.

## What did not work and why

- The first price-pattern search found opening-range breakout and VWAP reclaim no better than chance. More tuning of the same indicators risks fitting noise.
- The earnings-reaction test accidentally used a finished 30-minute bar before that bar was available. Correcting the clock erased the apparent result.
- Material company news rarely arrived inside the owner's 6:15–6:45 a.m. Pacific window, and corrected versions stayed near or below chance.
- The biotechnology lane had only three defensible events after audit, and the original test used SEC filing times even though the news had reached the market hours earlier.
- None of those failed lanes should be mixed into this auction test to manufacture a passing result.
- The opening-auction imbalance test itself was killed at its pre-registered feasibility gate on 2026-08-24, before any idea was frozen and before the held-out final period was touched. Sorting 34,588 development-period ticker-days into ten buckets by signed imbalance ratio (buy imbalance vs sell imbalance at the 09:30 ET print) and measuring the market-adjusted 60-minute return from 09:35 ET produced no usable spread: the biggest-buy bucket came in 6.88bps BELOW the middle bucket when the idea predicted at least 15bps above, and the biggest-sell bucket was flat at 0.07bps below. The bucket table zig-zags with no trend, and the strongest buy-imbalance bucket had the most negative return of all ten — the opposite of what was predicted. That is noise, not a faint edge.
- The held-out evaluation period (dates after 2025-11-28, 182 of 912 trading dates) was never read, so it stays clean for a genuinely different question.
- The final pass — auction pressure versus price response (lane A) and prior-close-to-next-open pressure transfer (lane B) — was rejected on 2026-08-24 at the internal validation gate, 9 of 10 gates failed. Six rules were frozen before any result existed and all six lost money: A1 -7.9, A2 -11.1, A3 -13.2, B1 -25.3, B2 -8.9, B3 -9.9 basis points per trade after the 15 basis-point cost. Before costs the best was +10.0 and the worst -18.0, against roughly +35 needed to clear the gate. Across 2,792 candidates the average was -12.3 basis points; the 25 trades the ranked model actually selected did worse still at -29.7, and were beaten by both the middle-ranked candidates and matched no-signal stocks on the same days. Independently reproduced from the raw exchange files. Full write-up: `.omc/research/opening-auction-pressure-response/final-research-verdict.md`.

## The plan that was executed (kept as history — all six rules were rejected on 2026-08-24)

1. Freeze at most six rules before reading new results. Lane A measures how imbalance grows, persists, cancels, or flips between 6:15 and 6:30 a.m. Pacific, then compares that pressure with the actual opening-price response through the realistic 6:35 entry. Lane B compares the prior day's closing-auction pressure with the current opening-auction path, including fixed month-end and quarter-end groups.
2. Split the existing 730 development dates again in time order into training and internal validation. Use a small constrained ranking model and a plain-rule comparison. Allow zero picks and cap selection at the best four stocks per day. Do not read the untouched final 182 dates during this work.
3. Use only information available by the simulated alert, wait five minutes, enter no earlier than 6:35 a.m. Pacific, and keep the 60-minute outcome as the primary result. Apply realistic costs, market adjustment, matched no-signal days, and one event per ticker and date.
4. Require at least 200 independent internal-validation trades, at least a 60% win rate under the frozen definition, positive average return after costs with its 95% confidence range above zero, positive results in at least three of four time blocks, and no single ticker producing more than 10% of total profit. The top-ranked group must also clearly beat the middle-ranked and no-signal groups.
5. Only if those gates pass, freeze the complete rule and run it once on the untouched final 182 dates. A separate reviewer must reproduce the results directly from the saved records.
6. Build nothing live unless the final test passes. If either lane fails internal validation, record the honest negative result and close #93. Do not buy more data or mine more versions of these same auction fields.

## Historical data location

- Entire 2.1 GB collection: `/home/openclaw/.openclaw/research-data/databento/opening-auctions`
- Main 60-stock records: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08`
- Download manifest, costs, date coverage, record counts, hashes, and known degraded dates: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/manifest.json`
- Selected symbols: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/selected_symbols.csv`
- Per-symbol coverage check: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/symbol_coverage.csv`
- Supporting universe-selection records: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/universe-selection`
- Single-stock pilot, correctly labeled because Databento's raw symbol `ALL` means Allstate rather than all stocks: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/pilot-ticker-ALL_2018-05_to_2026-08`

## Previous prompts and findings

- Execution-ready next plan: `.omx/plans/todo-93-auction-pressure-response-research.md`
- Original execution prompt: `.omc/plans/high-conviction-short-duration-scanner-prompt.md`
- Original prompt backup: `.omc/plans/high-conviction-short-duration-scanner-prompt-v1-backup.md`
- First attempt findings: `.omc/plans/high-conviction-short-duration-scanner-phaseA-retrospective.md`
- Event-reaction research prompt: `.omc/plans/event-reaction-short-duration-scanner-research-prompt.md`
- Event-reaction execution findings: `.omc/plans/event-reaction-short-duration-scanner-retrospective.md`
- Independent final verdict: `.omc/research/event-reaction-short-duration/final-research-verdict.md`
- Full event-reaction evidence, raw tables, frozen ideas, builder reports, and independent audits: `.omc/research/event-reaction-short-duration/`

## Open questions — all three now answered

- *Which auction fields are present early enough for a 6:15 a.m. Pacific alert?* Answered: `total_imbalance_qty`, `paired_qty` and `side` are populated from 5:00 a.m. Pacific onward. The four price-like auction fields are empty on this feed and were never usable.
- *Does the advantage predict continuation, reversal, or something conditional?* Answered: none of the three. Rules betting with the pressure, against it, and conditionally on the calendar all landed near zero before costs.
- *Is the effect large enough after costs to justify paying for a live feed?* Answered: no. There is no effect to pay for.

## Guardrails

- Stock results do not prove historical option profit. Exact option claims still require dated contract quotes.
- Do not use information published after the simulated alert.
- Do not repeatedly retune thresholds against the untouched final period.
- Do not build or enable live alerts unless the independent historical test passes.

### Session notes — 2026-08-24
- **Worked on:** Phase 1c feasibility probe of opening-auction imbalance deciles on the development period only, then the early-kill close-out (Phase 5b).
- **Decisions:** Killed the lane at the pre-registered gate — mechanical, not a judgment call, and independently re-checked by `scripts/check_gate.py`. Phases 2–5a (hypothesis freeze, builder, audit, eval test) were never run. Evaluation period left untouched.
- **Next:** Do not resume this direction without a genuinely new angle. The Databento data, confirmed field meanings, and the beta-scaled cross-sectional return code are all reusable at no new data cost if one appears.

### Session notes — 2026-08-24 (next-action decision)
- **Worked on:** Re-read #93, both failed research retrospectives, the final auction verdict, and the confirmed fields and timing in the paid Databento records.
- **Decisions:** One final no-cost research pass is justified, but only on two genuinely different mechanisms: pressure-versus-price mismatch and prior-close-to-current-open pressure transfer. Static imbalance direction will not be retested.
- **Next:** Write a short frozen research specification for the two lanes and their six-rule maximum, then run only the development/internal-validation work. Keep the final 182 dates sealed unless every gate passes.

### Session notes — 2026-08-24 (plan written)
- **Worked on:** Wrote the execution-ready, no-new-spending plan at `.omx/plans/todo-93-auction-pressure-response-research.md`.
- **Decisions:** Fixed six hypotheses, four walk-forward validation blocks, hard statistical gates, one-time final evaluation, independent audits, and an automatic stop if the existing data cannot prove the edge.
- **Next:** Execute the plan with `$autoresearch-goal`; do not run another planning or discovery pass first.

### Session notes — 2026-08-24 (execution and close)
- **Worked on:** Executed `.omx/plans/todo-93-auction-pressure-response-research.md` end to end, phases 0 through 5.
- **What ran:** Streamed all 45,313,852 auction messages and 19,653,306 one-minute bars from the local files; built a 43,453-row development panel over the 730 dates ending 2025-11-28; froze the six rules; ran the four-block walk-forward; had an independent reviewer reproduce it from raw records.
- **Result:** REJECTED at the Phase 5 internal gate, 9 of 10 gates failed. Plain-rule averages after costs: A1 -7.9, A2 -11.1, A3 -13.2, B1 -25.3, B2 -8.9, B3 -9.9 basis points. Before costs the best was +10.0 (B2) against roughly +35 needed.
- **Honest weaknesses recorded, not hidden:** the direction-shuffle control was vacuous (never more than one trade per day, so shuffling within a day does nothing); only validation block 1 selected any trades, so gate 6 is undecidable rather than cleanly failed; and one wording ambiguity about the trailing-60-session window was found by the reviewer, measured, and shown not to change the verdict (`threshold-sensitivity.json`).
- **Not done, deliberately:** phases 6, 7 and 8 (one-time evaluation run, final audit, production decision) were never started, because the plan stops on a failed internal gate. The evaluation period is untouched.
- **Next:** Nothing. Do not retune, do not widen the window, do not buy more data. The reusable assets are the paid Databento collection, the panel builder (`scripts/research/auction_pressure_build_dev.py`), and the mechanical gate checker (`scripts/research/check_auction_pressure_gate.py`).
