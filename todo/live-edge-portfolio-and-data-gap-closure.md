# Portfolio proof, forward option/borrow data, and honest displays

**Status:** OPEN — collection is live and proven in production 2026-08-26; first closed trade with a full option quote pair due 2026-09-01
**Created:** 2026-08-25

**CURRENT STATUS (2026-08-26, afternoon):** All three jobs are DONE, verified
and live — and the last thing that was owed has now happened. At 6:35 a.m.
Pacific the collection ran for real in production: **877 option rows and 8
borrow rows landed**, 818 of them with genuine two-sided prices. The four
positions that entered this morning (DKS, SUI, MSTR, MARA) have **real entry
option quotes** — the first in this project's history. The 6:50 check passed
silently and the 6:55 report wrote itself to the notifications file.

**Two independent verification passes ran, and both found real problems** —
which is the point of running them:

- The portfolio rebuild came back CONFIRMED with no defect, across 12
  hand-checked positions and eight different random seeds.
- The code verification passed 16 of its 17 checks and **found one genuine
  bug**: the "write nothing" flag used during a rehearsal run could get stuck
  on if anything failed mid-run, so a later real collection would report rows
  it had silently not written. Fixed in commit `ffd401b` with a guard that
  cannot leak, and re-proved against the verifier's own attack.
- It also surfaced a **pre-existing crash** in the `!em` card: when an option
  chain came back with no trade timestamps — which Schwab's own client causes
  on about a fifth of liquid tickers, NVDA and META among them — the whole card
  died instead of falling back. Fixed in commit `edaeb5c`.

**Tests:** the full repository suite passed on the exact final code —
3,652 passed, 0 failed, 2 skipped. `.test-baseline` is empty, so that is zero
regressions.

**Live output re-read after the last code change:** the engine was restarted and
`!em NVDA` was posted to Discord and read back. Headline is the raw straddle
(±$12.60), the tighter 0.85 band is labelled beneath it (±$10.71), the
calibration line is present, there is no 68% claim, and every time is Pacific.
An @-mention answers.

**Proven in production, 2026-08-26 6:35 a.m. Pacific.** Not a rehearsal on a
copy — the real morning job, writing to the real database:

- 877 option rows and 8 borrow rows stored across all 8 open positions.
- 818 of them carry a genuine two-sided price; 59 had no usable bid or ask and
  are labelled that way; none were stale and none went missing.
- The four names that entered this morning — DKS, SUI, MSTR and MARA — have
  **real entry option quotes**, taken at the same moment as the fill. A sample
  row: `DKS 260918P00120000`, bid 4.90 / ask 5.10, Schwab's mark 5.00, implied
  volatility 47.0%, delta -0.433, open interest 3,158, quote 0 seconds old,
  stock at $121.98 and SPY at $765.66. That is the first option quote this
  project has ever captured at the moment of one of its own trades.
- All 8 borrow rows came back shortable, not hard to borrow, rate 0.0 — stored
  raw, units still UNKNOWN, no money derived from them.
- The 6:50 check passed silently (`"ok": true`, 8 of 8 positions with rows) and
  the 6:55 report wrote itself to the notifications file.

**The next real milestone is 2026-09-01**, when DKS, SUI, MSTR and MARA close.
Those will be the first trades in this project's history with a complete entry
AND exit option quote — the pair that makes option profit answerable at all.
The four older positions (AMZN, GOOGL, META, BMNR) close 2026-08-31 but started
tracking mid-trade, so their option profit stays permanently unknowable.

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

## What the independent checks actually covered

Two separate agents, neither of which wrote the code they checked.

**The portfolio rebuild** was forbidden to read the builder's script. It worked
only from the hashed rule sheet and the raw price files. Verdict CONFIRMED:
every headline number matched, the fingerprint matched, and 12 positions it
chose itself were worked out by hand — including two pairs where the same stock
had overlapping trades open and a six-deep chain on Amazon. It checked the short
leg's direction explicitly, because getting that sign backwards is a mistake
this project has made before. It re-ran the one failing check with eight
different random starting numbers: all eight failed at 20% borrow, all eight
passed at 0%, and the two groups never came close to swapping. So the failure is
real, not luck.

**The code check** made real Schwab calls and rendered real Discord cards. What
it proved:

- Nothing is quietly dropped: a real chain returned 354 puts, 114 fell inside
  the strike window, and exactly 114 rows were stored.
- It cannot invent a price. A contract with no bid or ask but a last price of
  $5.55 stored the last price and left bid, ask and mark empty. A contract that
  vanished between captures stored as missing with everything empty — not
  filled in from the earlier real prices.
- A broken collection cannot break a trade. With the chain fetch forced to fail
  every time, the entry and exit still recorded correctly.
- The frozen rule file has zero changes across every commit, and the
  options-flow selection and scoring code has zero changes — only wording moved.
- The expected-move formula is byte-identical, proven by diffing the function.
- Repeat runs cannot duplicate a row, even with a different clock, a different
  Schwab answer, or a failure part-way through.

## Fixed along the way (found by verification, not by tests)

Both were found by running real code and attacking the claims, not by reading
the code and agreeing with it. Neither would have been caught by the test suite
as it stood.

1. **The rehearsal flag could get stuck on** (`ffd401b`). A "write nothing"
   rehearsal run set a flag at the start and cleared it at the end, with nothing
   protecting the middle. Any error in between left it stuck on for the rest of
   that run of the program, and a later real collection would then report
   contracts it had silently not written. It was hidden in practice because the
   only caller passes a fixed value and each morning is a fresh run, but the
   promise as written was false. Now the flag is always put back, even when
   something fails.
2. **`!em` crashed on a chain with no trade timestamps** (`edaeb5c`).
   Pre-existing, not from this work. The check for "no timestamp" missed the
   value pandas actually uses, and formatting it threw an error that took the
   whole card down. This was a live path: Schwab's own client sets exactly that
   value whenever its date conversion overflows, which it does on roughly a
   fifth of liquid tickers — NVDA, AMD, META, GOOGL, MSFT and QQQ are named in
   its own code comment. Fixed here rather than filed away, because it is a
   file this session already changed and it breaks a command the owner uses.

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
