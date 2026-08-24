# Prove a high-conviction opening-auction trading edge

**Status:** OPEN
**Created:** 2026-08-23

**CURRENT STATUS (2026-08-24):** Killed at feasibility probe [2026-08-24], decile spread top=-6.88bps / bottom=-0.07bps vs the +/-15bps threshold; fillable share 64.8% vs 60% threshold (passed but moot since decile condition failed). No clean monotonic pattern in the decile table — looks like noise. Overall status: this research direction (opening-auction imbalance) does not show a viable edge on the development-period-only probe; do not resume without a genuinely new angle. Full write-up: `.omc/research/opening-auction-imbalance/final-research-verdict.md`.

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

## Priority next steps

1. Read the Databento files without changing live scanner behavior. Resolve symbols as they were known on each date and exclude the degraded or unavailable dates recorded in the manifest.
2. Before looking at results, write down a small set of auction ideas. Test imbalance size relative to paired quantity and normal daily liquidity; imbalance growth, persistence, and reversal; and the indicated clearing price versus the prior close and premarket price. Add minimum-liquidity and spread rules.
3. Use an honest clock. Every input must exist before the alert time. Simulate the owner's 6:15–6:45 a.m. Pacific window, then wait five minutes before entry.
4. Split the dates in order. Use the earlier dates to develop the rule and leave the final 20% untouched until the rule and thresholds are frozen.
5. Compare each result with the broad market and matched no-signal days. Count one event per ticker, date, and direction. Include costs and reject any result driven by one ticker or one day.
6. Require useful trade frequency, not just a high percentage on a tiny sample. The live design may issue no trade; it should normally surface only one to four strong setups.
7. Have a separate review reproduce the headline numbers from the saved records before building production code.
8. If and only if the result passes, verify the price and license for a live New York Stock Exchange imbalance feed before spending money or connecting it to the bot.

## Historical data location

- Entire 2.1 GB collection: `/home/openclaw/.openclaw/research-data/databento/opening-auctions`
- Main 60-stock records: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08`
- Download manifest, costs, date coverage, record counts, hashes, and known degraded dates: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/manifest.json`
- Selected symbols: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/selected_symbols.csv`
- Per-symbol coverage check: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/symbol_coverage.csv`
- Supporting universe-selection records: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/universe-selection`
- Single-stock pilot, correctly labeled because Databento's raw symbol `ALL` means Allstate rather than all stocks: `/home/openclaw/.openclaw/research-data/databento/opening-auctions/pilot-ticker-ALL_2018-05_to_2026-08`

## Previous prompts and findings

- Original execution prompt: `.omc/plans/high-conviction-short-duration-scanner-prompt.md`
- Original prompt backup: `.omc/plans/high-conviction-short-duration-scanner-prompt-v1-backup.md`
- First attempt findings: `.omc/plans/high-conviction-short-duration-scanner-phaseA-retrospective.md`
- Event-reaction research prompt: `.omc/plans/event-reaction-short-duration-scanner-research-prompt.md`
- Event-reaction execution findings: `.omc/plans/event-reaction-short-duration-scanner-retrospective.md`
- Independent final verdict: `.omc/research/event-reaction-short-duration/final-research-verdict.md`
- Full event-reaction evidence, raw tables, frozen ideas, builder reports, and independent audits: `.omc/research/event-reaction-short-duration/`

## Open questions

- Which auction fields are consistently present early enough to support a 6:15 a.m. Pacific alert rather than only a near-open alert?
- Does the advantage predict continuation, reversal, or different behavior under different market conditions?
- Is the surviving effect large enough after costs to justify paying for live imbalance data?

## Guardrails

- Stock results do not prove historical option profit. Exact option claims still require dated contract quotes.
- Do not use information published after the simulated alert.
- Do not repeatedly retune thresholds against the untouched final period.
- Do not build or enable live alerts unless the independent historical test passes.

### Session notes — 2026-08-24
- **Worked on:** Phase 1c feasibility probe of opening-auction imbalance deciles on the development period only, then the early-kill close-out (Phase 5b).
- **Decisions:** Killed the lane at the pre-registered gate — mechanical, not a judgment call, and independently re-checked by `scripts/check_gate.py`. Phases 2–5a (hypothesis freeze, builder, audit, eval test) were never run. Evaluation period left untouched.
- **Next:** Do not resume this direction without a genuinely new angle. The Databento data, confirmed field meanings, and the beta-scaled cross-sectional return code are all reusable at no new data cost if one appears.
