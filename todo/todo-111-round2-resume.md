# TODO #111 round 2 — resume notes

**Written:** 2026-09-03 (Pacific). Read this first if the chat was compacted.

## Where the work stands

The round-2 mission is frozen, validated, and **running**. The outcome loop was
initialised and is at stage `DISCOVERY`, attempt 1 of 5, $0.00 spent.

| Thing | Path |
|---|---|
| Frozen mission | `.omx/plans/todo-111-trading-edge-round2-mission.json` |
| Frozen pass/fail gate | `scripts/research/todo_111_trading_edge_round2_gate.py` |
| Loop state | `.omx/outcome-loop/todo-111-trading-edge-round2/` |
| Controller id | `controller-main-opus5` / thread `session_01B9fuFtdLhYsfq8Mm9t3UTR` |

Resume the controller with:

```
python3 plugins/outcome-loop/scripts/outcome_loop.py status \
  --root . --mission-id todo-111-trading-edge-round2
```

## The finish line, in one place

Frozen in the gate script. It cannot be lowered, reworded, or argued down.

- **Shares** — enter, then close on the **first touch** of +1.0% in the trade's
  direction or -0.5% against it. Must reach the target first in **60 of every
  100 trades**, average at least **+0.40%** a trade counting losers, over
  **200+ trades**.
- **Options** — same shape at +20% / -20%, **60 of 100**, average **+4.00%**,
  over **100+ trades**.
- **No trade may stay open longer than 14 trading days**, whatever its profit.
- Exits must be decided on **one-minute prices or finer**. Daily bars cannot
  tell whether the target or the stop came first inside a day, and the gate
  refuses a result that used them.
- Returns are **gross** — no commission, no spread, no slippage. The owner
  subtracts costs himself.
- Entry must name what was observed. A fixed schedule is refused.
- Also required: holds on a fresh untouched period, and a separate read-only
  agent reproduces it.

Verified behaviour of the gate: fake pass exits 0; a 59.9% win rate against the
60% bar exits 1; a 63-trading-day hold exits 1; a `one_day` exit resolution
exits 1; all four feasibility modes pass on real evidence.

## What is built so far

- `scripts/research/todo_111_round2_extract_minutes.py` — one-time extraction of
  the local Databento one-minute bars into per-symbol parquet. Safe to re-run.
- `scripts/research/todo_111_round2_bracket.py` — the first-touch bracket
  engine every candidate reuses. Enters at the open of the bar AFTER the signal,
  assumes the stop came first when one bar could have touched both levels,
  fills a gap-through at the open (worse than the stop) but never claims a
  better-than-target fill, and enforces the 14-day cap on session count.

Extracted so far, at `/home/openclaw/.openclaw/research-data/todo-111-round2/minutes/`:

**Extraction is COMPLETE.** 120 parquet files, 40,278,360 one-minute bars:

- `equs__<SYMBOL>.parquet` — 60 symbols from EQUS.MINI, 19,653,306 bars,
  2023-03-28 to 2026-08-22.
- `xnys__<SYMBOL>.parquet` — the same 60 symbols from XNYS.PILLAR,
  20,625,054 bars, 2023-01-01 to 2026-08-22.

Two feeds of the same names is deliberate: EQUS.MINI is about 20% of the tape,
so its high and low can understate the true range and miss a touch. XNYS.PILLAR
is the second opinion. A result that only survives on one feed is not a result.

## The data picture

**Usable now, no login, no cost:**

- One-minute bars, 60 large-cap NYSE names, Jan 2023 - Aug 2026 (2.1 GB at
  `/home/openclaw/.openclaw/research-data/databento/opening-auctions/selected60_2023-01_to_2026-08/`).
  This is what makes a first-touch share test possible. Caveat from memory:
  EQUS.MINI is about 20% of the tape, so its high/low can understate the true
  range; the XNYS.PILLAR copy is a second opinion.
- Opening-auction imbalance records, 45.3 million of them, same symbols and
  span. **Careful:** the opening-auction family was rejected as TODO #93, so
  re-read that verdict before proposing anything built on it.
- DoltHub weekly option chains with real bid/ask, 509 snapshot dates
  2019-02-16 to 2022-12-30, ~610 symbols
  (`/home/openclaw/.openclaw/research-data/todo-111/dolt`).
- DoltHub whole-US-market daily prices including delisted names
  (`.../todo-111/dolt-stocks`), plus `data/mmhl_daily` (540 symbols) and
  `data/mmhl_earnings`.

**Blocked, and this is the owner's decision at the end:**

- **Intraday option prices do not exist here.** The weekly DoltHub chains are
  end-of-day once a week and cannot see whether an option touched +20% before
  -20%. The files in `data/options-dx-2023/*.zip` are 2,618 bytes each —
  failed downloads, not data.
- So the **option half of the finish line cannot be tested at all** until the
  owner buys data or completes a login. Every option family is parked.
- Share families are fully testable on the minute bars, and that is where the
  autonomous work goes.

## The arithmetic that shapes every candidate

A +1.0% target against a -0.5% stop pays two to one, so a coin-flip stock hits
the target first about **33 times in 100** (0.5 divided by 1.5). The bar is
**60 in 100**. The rule has to be nearly twice as accurate as chance.

That is a hard bar, and every short-horizon share study this project has run
(#103, #104, #106) measured a gross edge of 1 to 5 basis points against a
40 basis point need. Those were fixed-horizon tests rather than brackets, but
the underlying move being predicted is the same size. Expect honest rejections;
the loop is built for that and records each one.

**The cheap pre-screen** (do this before any frozen backtest, 30 minutes each):

1. Measure the unconditional hit rate of the bracket across all symbols and
   entry minutes. That is the baseline the candidate must beat.
2. Measure the candidate's conditional hit rate. If it cannot clear roughly
   40 in 100, it cannot reach 60 and it stops there.
3. Record the number in a one-page file even when the idea dies. That file is
   the cheap half of the rejection ledger.

## Measured so far (2026-09-03)

- **Baseline, both feeds:** the +1.0% / -0.5% bracket reaches its target first
  **34.47%** of the time on EQUS.MINI (695,484 sampled trades) and **34.56%**
  on XNYS.PILLAR (730,536). Theory said 33.3%. The bar is 60%.
  Details: `.omc/research/todo-111-round2/baseline-and-seal.md`.
- **The seal is declared:** development is everything before **2025-07-01**;
  the fourteen months after it are untouched. The pre-screen physically drops
  the sealed bars before computing anything.
- **All four feasibility checks pass** against evidence files in
  `.omc/research/todo-111-round2/`.
- **Eleven entry-trigger families pre-screened and all eleven rejected.** Best
  was 35.29%, worst 33.68%, against a 34.47% baseline and a 60% bar. Full table
  and the reasoning behind each idea:
  `.omc/research/todo-111-round2/rejection-ledger.md`. Harness:
  `scripts/research/todo_111_round2_prescreen.py`.
- **Seven evidence files recorded in the loop ledger** (baseline, ledger, the
  four feasibility files, the raw pre-screen numbers). Loop still at
  `DISCOVERY`, attempt 1 of 5, $0.00 spent — deliberately. No candidate earned
  a frozen backtest, and burning an attempt on an idea the pre-screen already
  killed is exactly what the pre-screen exists to prevent.
- **The sealed period was never opened.**

## Owner's instructions, 2026-09-03 — READ BEFORE PROPOSING ANYTHING

Given after seeing the eleven rejections. Not acted on in that session; this is
the standing brief for the next one.

**1. Keep going until a winning method is found.** Eleven rejections is not a
conclusion. Many more methods are to be tested.

**2. The eleven were too simple, and count as roughly ONE idea.** Each was a
single condition on a single chart of a single stock: one trigger, one
direction, nothing else. The owner's words: *"this seems to be 1 idea, what
about the other 4?"* A genuinely different idea is a different **mechanism**,
not a different threshold on the same one.

**3. Methods may need to be more complex.** Combinations are wanted, not
single triggers. Nothing tested so far combined two conditions, used the time
of day, used the day's own context, or used anything outside the price series.

**4. Two specific strategies the owner named, to be tested:**

- **15-minute opening-range breakout.** Take the high and the low of the first
  15 minutes after the open. Buy a break above that high, short a break below
  that low.
- **Overnight-range breakout.** Take the high and low made between yesterday's
  close and today's open — the thin overnight session — and trade the break of
  that range during regular hours.

  **OWNER SIGN-OFF GIVEN, 2026-09-03.** Asked whether to loosen the
  rejected-family rule for these two, the owner answered: *"yes, loosen that
  rule for those two strategies."* So:

  - `reuse_rejected_family` **no longer blocks** the 15-minute opening-range
    breakout or the overnight-range breakout. Both may be built and tested.
  - It **still blocks everything else** already rejected: the #106 opening
    continuation, prior value-area failure and Fibonacci methods, the #97 gap
    fade and the other five methods in that batch, the #103 intraday
    dislocation family, and the #93 opening auction. The loosening is these two
    strategies only, and does not extend by analogy to anything that resembles
    them.
  - The two are not identical to what was rejected anyway: #106 used a
    different opening window, and the overnight range is a different range from
    the opening range.

  **Mechanical catch — read before trying to apply this.** The round-2 mission
  is hash-frozen. The controller compares
  `.omx/outcome-loop/todo-111-trading-edge-round2/mission.json` against
  `mission.sha256` on every command and refuses with *"frozen mission hash
  changed"* if a byte moves, so the forbidden-actions list **cannot be edited
  in place**. Carrying the sign-off into the loop means one of:

  1. freeze a **round-3 mission** with the narrowed forbidden action, same gate
     script and same finish line (cleanest — the round-2 ledger stays intact as
     the record of the eleven rejections); or
  2. re-`init` this mission id from scratch, which throws away the round-2
     ledger.

  Option 1 unless the owner says otherwise.

**5. What "more complex" can mean, as starting material** (the owner did not
specify these; they are the obvious unexplored directions):

- two or more conditions that must agree, rather than one trigger
- the time of day as a condition, not just a filter
- the day's own context: is today already a trend day, a range day, a high-
  volatility day
- the stock's behaviour relative to its sector or the whole group
- anything not in the price series at all — the project already has insider
  filings, analyst mentions, options flow and news signals

## Next steps, in order

1. **Owner decision, still open:** the option half of the finish line cannot be
   tested at all without intraday option prices. Nothing else is blocked.
2. Work the owner's brief above. Start with the two named strategies once the
   rejected-family conflict in point 4 is settled.
3. Only if an idea clears roughly 40 in 100 on the pre-screen: register it as a
   candidate, plan, then hand the build to a **separate builder agent** — the
   loop requires the builder's agent and thread to differ from the controller,
   and the reviewer must be a new read-only agent.
4. Nothing is bought or logged into autonomously.
