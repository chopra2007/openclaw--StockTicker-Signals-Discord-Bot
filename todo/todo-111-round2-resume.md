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

- **60 symbols from the EQUS.MINI feed**, 19,653,306 one-minute bars,
  2023-03-28 to 2026-08-22. 311 MB of parquet.
- The XNYS.PILLAR copy of the same 60 symbols (2023-01-01 onward) was still
  extracting when this note was written. Re-run the extractor to finish it;
  symbols already written are rebuilt harmlessly.

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

## Next steps, in order

1. Finish the XNYS extraction (re-run the extractor).
2. Run the unconditional baseline hit rate. This one number decides whether the
   share side is viable at all.
3. Write the four feasibility evidence files and pass all four gate checks.
4. Register candidate 1, plan, then hand the build to a **separate builder
   agent** — the loop requires the builder's agent and thread to differ from
   the controller, and the reviewer must be a new read-only agent.
5. Queue every owner decision (option data purchase, logins) into a single list
   for the end. Nothing is bought or logged into autonomously.
