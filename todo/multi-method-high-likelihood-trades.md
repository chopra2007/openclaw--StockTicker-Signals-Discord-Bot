# Multi-method high-likelihood trade research

**Status:** DONE (research complete — no method passed)
**Created:** 2026-08-25

**CURRENT STATUS (2026-08-25):** Research run complete. Six trading methods were
frozen in advance and tested honestly. **All six were rejected.** Nothing is
recommended for a build. Two findings about features that are ALREADY LIVE came
out of the run and are the main value delivered — see "What to do next".

Full artifacts: `.omc/research/multi-method-high-likelihood-trades/`
Headline report: `final-ranked-report.md` in that folder.

---

## What was asked

Find genuinely different ways this project could pick a very small number of
trades (zero to four a morning) with a high success rate and real profit after
costs, in the owner's 6:15-6:45 a.m. Pacific window. Research only — change no
production code, config, alert or timer. A finding of "nothing works" was
declared acceptable up front.

## What was done

Method cards, thresholds, entry clocks, exits, costs and pass/fail gates were
all written and **hashed before any result was looked at**
(`frozen-method-cards.sha256`). The evaluation period was sealed in code and
never run, because nothing got far enough to earn it.

Twelve ideas were killed before testing (re-skins of already-dead rules, or
methods needing data that does not exist). Six were tested.

## Results — all six rejected

| Method | Sample | Verdict |
|---|---|---|
| Extreme overnight gap fade, same day | 2,641 trades, 10 years | Win 45.4%, profit factor 0.84 |
| Same, four-day hold | 2,641 trades | Win 43.6%, profit factor 0.95 |
| Unusual options flow, full gate battery | 2,281 events | Win 47.4%, profit factor 1.03 |
| Before-open vs after-close earnings | 13,052 events | Win 48.1%, profit factor 0.86 |
| Last night's volatility reading | 2,716 events | Both tails lose, profit factor 0.66 |
| Attention surge (deliberate dud) | 419 events | Correctly showed nothing |

These are not "not enough data" verdicts. The samples were large. Nothing was
significant even **before** costs were charged.

## Why the rejections are trustworthy

- Pointed at the known-good TODO #96 method, the same harness found a real edge
  (205 trades, +0.92%, profit factor 1.38). It can see an edge when one exists.
  Note that rebuild's profit-factor gate passes on its own; it is the win rate
  and the profit range that fail, so it is unproven rather than worthless.
- A negative-control card, pre-registered to fail, failed. It is not
  manufacturing edges from noise.
- An independent agent rebuilt the numbers from raw records without being
  allowed to read the analysis code, and **found a real defect** in the first
  pass: funds were being silently dropped from the options-flow test (385 of
  2,283 events). Fixed, re-run on the complete universe, re-verified. Verdicts
  unchanged.

## What to do next — three things, in order

**1. The expected-move number shown to the owner is over-confident.**
Measured over 3,721 observations: the raw option-implied move contains the
actual move 61.6% of the time, and **the 0.85-adjusted figure the bot actually
displays contains it only 55.0%** of the time. The commonly assumed figure is
about 68%. Breaches skew downward (20.1% down vs 18.3% up). This is a
display-honesty fix, not a trading method, and it is cheap. Reproduced by two
independent verifiers; adding 23% more data moved every figure by under one
percentage point, so it is not an artefact of which stocks were sampled.

**2. Decide what to do about the live options-flow threshold.**
The `min_vol_oi: 20` threshold in `config/consensus.yaml` was set by grading
that measured **close-to-close** returns — entering at the 1 p.m. Pacific close,
which the owner cannot trade — and that only asked whether calls beat puts more
often, never whether the signal made money. Measured at the next morning's open,
which IS tradeable, and judged on profit: profit factor 1.03, win rate 47.4%.
This does not necessarily mean switch it off — it may still be useful for
directing attention — but it should not be treated as a proven money-maker.

**3. Start forward-collecting option quotes and daily borrow rates. Free.**
Every option question in this run came back UNKNOWN, permanently, because
historical option chains at past intraday moments do not exist here (only one
snapshot a day, after the close). And no borrow-cost data exists at all, which
means no short-side method — **including the live TODO #96 method** — has an
honest net return. Forward collection is the only route to ever answering
either. Every session not collected is gone for good.

## Caution carried forward

TODO #96 is live and soaking until 2026-09-26. Rebuilt with a different but
equally reasonable entry and exit convention (official open/close instead of the
6:35 print and open-to-open), its win rate falls from 65.2% to 51.2%, profit
factor from 2.01 to 1.38, and the range on average profit comes to include zero.
**This does not prove #96 wrong** — the tests are not identical. It does say the
headline is more sensitive to convention than a robust edge usually is. Let the
soak finish before trusting the published figures, and remember borrow cost is
still not charged.

## Files involved

Research scripts (research-only, imported by no production code):
- `scripts/research/mmhl_fetch_daily.py` — long-history daily bar cache
- `scripts/research/mmhl_gap_fade.py` — SD1 / MD1
- `scripts/research/mmhl_flow_gates.py` — MD3
- `scripts/research/mmhl_earnings_timing.py` — MD2
- `scripts/research/mmhl_md4_md5_em1.py` — MD4 / MD5 / EM1

Data cache: `data/mmhl_daily/` (540 tickers), `data/mmhl_earnings/`

## Open questions

- Would buying historical minute data revive any same-day method? Probably not —
  the daily-bar versions of the same mechanisms were rejected on far larger
  samples. Pricing is in `missing-data-prices.md`; recommendation is buy nothing.
- Does the expected-move over-confidence warrant changing the 0.85 multiplier,
  or just labelling the number honestly? Owner's call.
