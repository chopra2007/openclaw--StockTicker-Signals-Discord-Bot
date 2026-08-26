# Portfolio proof, forward option/borrow data, and honest displays

**Status:** OPEN — collection is live; first real production rows land 2026-08-26
**Created:** 2026-08-25

**CURRENT STATUS (2026-08-25, late evening):** All three jobs are BUILT, TESTED
and ON. The portfolio verdict is in and independently confirmed. The two display
fixes are live and were read back from real output. The forward collection is
armed and proven against real Schwab data in a scratch database — the one thing
still owed is a real PRODUCTION row, which lands at 6:35 a.m. Pacific tomorrow,
2026-08-26. A 6:50 a.m. check and a 6:55 a.m. report are both scheduled.

## 1. Does the morning trade work as a PORTFOLIO? — answered: NOT a clean pass

The published +1.83% for TODO #96 is the average of trades looked at one at a
time. Run as one real account — up to four new trades a morning, four days
each, several open at once, SPY legs stacking — it clears **six of seven**
frozen checks and **fails the seventh once a harsh 20%-a-year stock-borrowing
fee is charged**.

Honest one-liner: **the isolated-trade test passed; portfolio viability did
not.** TODO #96 stays owner-only, stays soaking, and its signal rule was not
touched. Nothing was retuned after seeing the answer.

| | 0% borrow | 20% borrow |
|---|---:|---:|
| Total over 12 weeks | +20.7% | +17.1% |
| Worst peak-to-valley dip | 5.1% | 5.3% |
| Money won per dollar lost | 2.00 | 1.78 |

The failing check is number 4: the 95% range for the typical day's return is
−0.038% to +0.565% at 20% borrow, so it includes zero. At 0% borrow the same
range is +0.013% to +0.607% and passes.

Every rule was written and fingerprinted before any number existed
(`24a94ad3f8faadfb9e028f6bd6b680fe6e23416d27731e8e1e7ed2e4b9a4918a`). A second
agent, forbidden to read the builder's code, rebuilt the whole thing from the
raw price files: **CONFIRMED**, every number matched, 12 trades hand-checked
including overlapping repeats of the same stock, no defect found. It re-ran the
failing check with eight different random starting numbers — all eight failed at
20% borrow and all eight passed at 0%, so the failure is real, not seed luck.

The timing check (6:35 / 6:40 / 6:45 a.m. Pacific, plus an open-to-close stress
row) was a falsification test, not a contest. All four rows are positive with
more than a dollar won per dollar lost. **Production timing was not moved.**

Files: `.omc/research/put-flow-portfolio-audit/` — `RESULT.md`,
`independent-verification.md`, `frozen-portfolio-policy.json` + `.sha256`,
`positions.csv`, `equity-curve.csv`, `gates.json`, `borrow-cases.json`,
`timing-matrix.json`, `concentration.json`, `overflow-rejections.json`.
Code: `scripts/research/put_flow_portfolio_audit.py`,
`tests/test_put_flow_portfolio_audit.py`.

## 2. Saving option prices and borrow costs — LIVE from tomorrow

TODO #97 found that every option question about this project comes back UNKNOWN
forever, because no past session ever saved the option chain at the moment of a
trade — and no borrow cost has ever been recorded at all. Every session not
collected is gone for good. This starts collecting.

At each TODO #96 entry, every daily mark while the pair is open, and the exit,
the system now saves:

- the WHOLE bounded PUT slice — expirations from 7 calendar days after the
  planned stock exit through 45 days after entry, strikes from 70% to 110% of
  the stock price, with contract symbol, expiry, strike, bid, ask, last,
  Schwab's own mark, quote time, volume, open interest, implied volatility and
  every greek, plus the stock price, the SPY price and the row it belongs to;
- Schwab's short-availability and borrow fields for the short leg.

**Never a hand-picked "best" contract** — the whole slice, so a future session
can freeze a long-put or put-spread rule using only what was knowable at entry.

Every row carries an honesty label: `OK` (a real, fresh two-sided quote),
`STALE`, `NO_TWO_SIDED`, or `MISSING`. A stale or missing quote stays that way.
Nothing is ever back-filled from a last price or a later snapshot.

**Two things that are permanently UNKNOWN, and say so:**

1. **Option profit.** No frozen evaluator exists and no complete entry/exit
   quote pair exists yet. The report says UNKNOWN, with the reason.
2. **The units of Schwab's borrow rate.** They could not be proven from
   official material, so `rate_units` is `UNKNOWN`, only the raw rate is
   stored, and **no dollar borrow cost is calculated from it**. The frozen
   0.25%-cost result is never overwritten.

**The four positions open right now (AMZN, GOOGL, META, BMNR) will never have
an entry option quote** — they entered this morning, before this code existed.
Capturing a chain tonight and calling it an entry quote would be a lie about
when it was taken. Instead the first daily mark establishes what to track for
them, and the report shows that as a separate visible line: "tracking started
mid-trade — no entry quote exists for those, so option profit for them can
never be measured."

**Proof so far (real Schwab data, scratch database):** 586 contracts and 4
borrow rows stored across all four tickers; every row correctly labelled STALE
or NO_TWO_SIDED because the market had been shut ten hours; a second identical
run added exactly zero rows.

**Still owed:** a real production row. First chance is 6:35 a.m. Pacific on
2026-08-26.

What runs, all Pacific:
- `put-flow-shortlist-trade.timer` 6:35 a.m. — now runs `--exit --enter
  --capture`, in that order, so each position gets exactly one row per stage
  per day.
- `put-flow-capture-proof.timer` 6:50 a.m. — reads the real table and posts ONE
  #errors message only if the collection stored nothing. Silent when fine.
- Deferred task `task_1787726377_2d53e3` 6:55 a.m. 2026-08-26 — writes the
  plain-English collection report into `/root/task_system/notifications.log`,
  so the next session sees the evidence without being pinged.

Files: `consensus_engine/analysis/put_flow_option_capture.py`,
`tests/test_put_flow_option_capture.py`, the `--capture`, `--capture-report`
and `--capture-proof` commands in `scripts/put_flow_shortlist_job.py`, three
new tables in `consensus_engine/db.py` (`put_flow_option_snapshots`,
`put_flow_borrow_snapshots`, `put_flow_capture_runs`), the
`put_flow_shortlist.option_capture:` block in `config/consensus.yaml`, and
three additive columns (`mark`, `bidSize`, `askSize`) in
`consensus_engine/scanners/schwab_client.py`.

**Storage is local only.** The Schwab personal-use terms forbid posting or
publishing a raw per-strike chain, so nothing renders one to Discord or writes
one into the repository — the database file is not in git.

## 3. Two overstated displays — FIXED

### Expected move

Measured over 3,721 stored checks: the raw option-implied band contained the
real move 61.6% of the time, and the 0.85-adjusted band the bot displayed
contained it only 55.0%. The card claimed "1 standard deviation — about 68% of
the time."

- That claim is gone from `!em` and `!emw`.
- The raw band is the headline; the 0.85-adjusted figure now appears beneath it
  as a clearly labelled tighter band.
- One shared line, in one place (`calibration_note()` in
  `consensus_engine/scanners/expected_move.py`), is used by the `!em` card, the
  morning brief and the SPY/QQQ daily script, so the numbers can never drift
  apart: "How often these were right, over 3,721 past checks to 25 Aug 2026:
  wider band 61.6%, tighter 0.85 band 55.0%. Neither is a 68% or
  one-standard-deviation promise."
- **No formula changed.** `calculate_expected_moves()` returns numerically
  identical values; only the order and the labels moved.

`!all` was checked and needed no change — it uses the option chain only for a
cheap-vs-rich volatility tag, and never shows an option-implied expected-move
band. Its own "expected move" field is an ATR-based swing range, which is a
different thing and was out of scope.

### Ordinary #options-flow alerts

Measured at the next tradeable open: profit factor 1.03, win rate 47.4%, on
2,281 events. Not a proven money-maker.

Kept exactly as they were: which contracts qualify, `min_vol_oi`, every score,
the real BUY/SELL/AMBIGUOUS transaction-side tag, and the separate 50x SWEEP
tier with its own header. **Zero behaviour change.**

Changed, wording only:
- `🟢 BULLISH` / `🔴 BEARISH` (a stock-direction call) → `🟢 CALL-side
  activity` / `🔴 PUT-side activity`
- `— fresh positioning` → `— volume above open interest`
- `_Unusual-flow instant trigger._` → `_Unusual option activity — not a
  confirmed trade signal._`

Side effect worth knowing: `options_flow.side_labels_live` in
`config/consensus.yaml` is now read by no production code — only by research
scripts. It is left in place with a comment, not deleted.

## Open questions

- **Should the 0.85 multiplier itself change, or is honest labelling enough?**
  TODO #97 left this as the owner's call and it is still open. Nothing was
  changed; the multiplier is still 0.85.
- **What are the units of Schwab's `htbRate`?** Until this is proven from
  official Schwab material, no borrow cost can be turned into money. Worth one
  focused look, because it is the missing piece in the portfolio verdict above.
- **Does the portfolio verdict change once real borrow rates accumulate?**
  Check 4 fails at an assumed 20% a year. All four names on the book today came
  back at a borrow rate of 0.0. If the real rates stay near zero, the honest
  stress case is much closer to the 0%-borrow column, which passes. That is a
  question the collection now being live can actually answer — after enough
  sessions.
