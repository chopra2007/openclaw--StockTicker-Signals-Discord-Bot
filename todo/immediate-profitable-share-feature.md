# Find one share-trading rule that actually makes money, and ship it today

**Status:** DONE 2026-08-28 (NO PASS — no rule earned its costs)
**Created:** 2026-08-28

**CURRENT STATUS (2026-08-28):** **NO PASS.** All three rules failed. Every one
of them needed to earn 40 basis points a trade before costs (80 for a two-stock
pair) and they earned +1.0, −0.4 and +3.3. A basis point is one hundredth of one
percent.

The usual objection — "your trading costs were too harsh" — does not apply here.
Set the cost to **zero** and the three rules still earn +1.0, −0.4 and +3.3
against a bar of 20. There is nothing to buy at any price.

Nothing was built, nothing was turned on, production is unchanged, no money was
spent, and the 182 sealed days were never opened. An independent agent rebuilt
all three rules from the raw exchange files without touching the builder's code:
4,554 signals and 3,580 complete trades, all matched. A hostile reviewer tried
to break the result and concluded it stands.

Three real defects were found by those reviewers and fixed — the account's own
losses were choosing which trades it could afford, 24 funds were being traded as
if they were shares, and the cheap-stock cost floor was charged at half rate.
Every fix made the rules look worse.

Full write-up: `.omc/research/immediate-profitable-share-feature/FINAL-VERDICT.md`

## What this is

The owner does not want another research memo. Using only data already on this
machine, test exactly three share-trading rules, end to end, today:

1. **Same time of day continuation** — a stock that tends to move a certain way
   in, say, the 11:00-11:30 half hour keeps doing it. (Heston, Korajczyk and
   Sadka.)
2. **Yesterday's move plus yesterday's volume** — whether a move keeps going or
   snaps back depends on how heavy the trading was. (Llorente, Michaely, Saar
   and Wang.)
3. **Two near-identical companies drifting apart** — buy the laggard, short the
   leader, wait for them to close the gap. (Gatev, Goetzmann and Rouwenhorst.)

Everything is frozen in writing before any profit number is computed. If none of
the three clears every profit and risk gate, the answer is
`NO PASS` and nothing is turned on.

## Closed already — do not re-open

Opening-auction pressure (#93), early-session dislocation (#103), gap fade,
earnings timing, options-flow direction, stored volatility, social attention,
opening-range breakout, VWAP reclaim, sector rotation, and any option rule with
no historical bid and ask.

## Files

- Prompt: `.omc/plans/profitable-feature-today-execution-prompt.md`
- Work folder: `.omc/research/immediate-profitable-share-feature/`
- Research code: `scripts/research/ipsf_*.py`

## Follows

#93 (opening auction, no edge), #97 (six methods, all rejected), #100 (put-flow
options, insufficient data), #103 (intraday dislocation, no edge).


## What this closes, and what it does not

**Closed for good:** the same-half-hour repetition idea. Take the safety exit
away entirely and it is worth minus five hundredths of a basis point across
422,338 observations. Do not re-propose it.

**Closed:** the "big move on heavy volume snaps back" idea, in large US
companies, in these years.

**NOT closed:** pairs trading in general. What was tested closes the position
after five days and 95 of every 100 trades were still apart when the clock ran
out. Holding for seven weeks does capture a real convergence — about 24 basis
points at its best — but a pair costs 40 to trade, so it still does not pay.
Anyone re-proposing pairs must explain how they beat that 40.

**The limit that matters most:** both stock lists were chosen in August 2026, so
every company in them survived to 2026. That flatters buying-the-dip rules. It
makes this NO PASS safer, and it would have to be fixed before any future
result in the same universe could be believed the other way.

---

## Session notes — 2026-08-28

Executed `.omc/plans/profitable-feature-today-execution-prompt.md` end to end in
one session. Ended `NO PASS`.

**Phase 0 first.** Seven tests were failing on GitHub's machine while passing on
this server, because they read files that live only here and are deliberately not
in the repository. Gave them their own small self-contained rulebook and stock
sample written under the test's own temporary folder, and made one child process
point at a throwaway database before it starts. Proved it by hiding those folders
and re-running: 92 passed with them, 92 passed without.

**Locked the rules before looking at any profit.** Data inventory with
fingerprints, three primary papers plus the replication that says pairs trading
stopped paying after 2002, two independent designs, a written reconciliation, and
a clean-room review by an agent that saw no results. Rulebook fingerprint
`b808065c7c769605314922efe3f0f3a7ed2af4551c9c75f3ae06106fb1c995b5`; the research
code refuses to run if it changes.

**What the second designer caught that the first missed.** Fake $0.0001 rows in
the daily price files (one file starts fifteen years before the company listed);
stray one-share prints hours after the 1 p.m. close on 2025 half-days; Method 1's
size filter could not come from the daily files because eleven of the sixty
minute-data names have no daily file; Method 3 could not run on the minute
universe at all. It also reversed my Method 2 direction — the paper puts big,
heavily traded companies on the side where heavy volume means *snap back*, and I
had them continuing.

**What the clean-room reviewer caught.** The signals removed the market's move
but the money did not — over a five-day hold in a rising market that is about the
size of the whole profit bar. Profit is now measured a second time with the
market taken out, and that has to pass too. Also: state what four-of-how-many
means, say whether concentration is a share of trades or profit, give the harsh
cost real teeth, copy the concentration checks into the sealed-period list, and
raise the cost floor for cheap stocks. All adopted before the freeze.

**The run.** M1 1,518 trades / M2 2,461 / M3 789. Before any cost: +1.0, −0.4
and +3.3 basis points against 40 needed (80 for a pair). At a cost of zero, the
same three numbers.

**Three defects the reviewers found after the first run, all fixed, all making
the rules look worse.** The equal-dollar path measured its exposure cap against
current account value, so the run's own losses were choosing which trades it
could afford. Twenty-four funds (SPY, QQQ, TQQQ, UVXY and more) were sitting in
the share universe. The cheap-stock cost floor was charged at half the frozen
rate. After the fixes the numbers landed on the verifier's independently
predicted values, which is two separate rebuilds agreeing.

**Verification.** An independent agent rebuilt everything from the raw exchange
files without importing the builder's engine: 4,554 signals and 3,580 complete
trades, all matched. A hostile reviewer was told to argue the NO PASS is wrong
and concluded it survives.

**Left undone on purpose.** Nothing. Both allowed endings were reachable; the
evidence chose this one.

**Loose thread worth one fresh, pre-registered shot some day:** a pairs rule held
for weeks rather than days. Convergence is real and keeps building for about
seven weeks, peaking near +24 basis points — against a 40 basis-point pair cost.
Anyone re-proposing it must explain how they beat that 40 before writing code.

