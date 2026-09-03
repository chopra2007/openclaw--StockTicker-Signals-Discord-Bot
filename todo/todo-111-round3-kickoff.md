# TODO #111 round 3 — kickoff

> **ROUND 3 IS FINISHED — 2026-09-03.** Do not start it again. Six mechanisms,
> ten entry rules, all rejected; the loop is STOPPED on `owner_only_decision`
> with $0.00 spent and the sealed period never opened. Read
> `todo/todo-111-round3-result.md` first — it has
> the results and the three choices now waiting on the owner. Everything below
> is the brief this round was run from, kept as the record.

Read this file, then `todo/todo-111-round2-resume.md` in full. The owner is not
a coder: plain language, no jargon, all times in Pacific.

## Where things stand

Round 2 measured eleven entry triggers and rejected all eleven. A randomly
chosen entry reaches the +1.0% target before the -0.5% stop **34.47%** of the
time; the best of the eleven reached **35.29%**; the bar is **60%**. That
ledger stands as the record and is not re-run.

The owner's verdict on it: those eleven were each a single condition on a
single chart of a single stock, so he counts the whole set as **roughly one
idea**. Round 3 is for genuinely different mechanisms, and for methods that are
allowed to be more complex.

## Round 3 is already frozen and running

| Thing | Path |
|---|---|
| Frozen mission | `.omx/plans/todo-111-trading-edge-round3-mission.json` |
| Mission hash | `1480996caeecda8505f3bbb13829bb58fd16221ac988ef41f545a7b286faa61b` |
| Loop state | `.omx/outcome-loop/todo-111-trading-edge-round3/` |
| Controller | `controller-main-opus5` / thread `session_01B9fuFtdLhYsfq8Mm9t3UTR` |
| Frozen finish line | `scripts/research/todo_111_trading_edge_round2_gate.py` (unchanged) |

Stage `DISCOVERY`, attempt 1 of 5, $0.00 spent. Check it with:

```
python3 plugins/outcome-loop/scripts/outcome_loop.py status \
  --root . --mission-id todo-111-trading-edge-round3
```

**Re-freeze the controller identity if this is a new thread:** `init` recorded
the thread above. A different thread must not pretend to be it.

## The finish line — unchanged, and it cannot be argued down

- **Shares:** close on the first touch of **+1.0%** in the trade's direction or
  **-0.5%** against it. Reach the target first in **60 of every 100 trades**,
  average **+0.40%** per trade counting losers, over **200+ trades**.
- **Options:** same shape at **+20% / -20%**, **60 in 100**, average **+4.00%**,
  over **100+ trades**.
- **No trade open longer than 14 trading days**, whatever its profit.
- Exits decided on **one-minute prices or finer**. Daily bars are refused.
- Returns are **gross** — the owner subtracts costs himself.
- Entry must name what was observed. A fixed schedule is not a trigger.
- Plus: a fresh untouched period, and a separate read-only agent reproduces it.

Note the two share numbers are the same number: 60 wins at +1.0% against 40
losses at -0.5% averages exactly +0.40%.

## What round 3 changes

**1. The rejected-family rule is narrowed.** The owner signed off on 2026-09-03.
Two strategies are cleared to build and test:

- **Fifteen-minute opening-range breakout** — the high and low of the first
  fifteen minutes after the open, traded on a break of either side.
- **Overnight-range breakout** — the high and low made between the previous
  close and the current open, traded on a break of either side during regular
  hours.

Nothing else is unblocked. Still closed: the #106 opening continuation, prior
value-area failure and Fibonacci methods; the #97 gap fade and its five
siblings; the #103 intraday dislocation family; the #93 opening auction. The
exception does not extend by analogy to anything that merely resembles the two
named strategies.

**2. A single condition on a single chart is not a mechanism.** Methods are
expected to combine things. The directions the owner named or implied:

- two or more conditions that must agree
- the time of day used as a condition, not just a filter
- the character of the day itself — already a trending day, a range day, an
  unusually volatile day
- the stock's behaviour relative to its sector or to the whole group of names
- **information that is not in the price series at all** — this project already
  collects insider filings, analyst mentions, options flow and news signals

**3. Keep going.** Work continues until a rule clears the bar or a stop
condition frozen in the mission is genuinely reached. Running out of ideas is
not a stop condition. Neither is a discouraging result. Record each rejection
with its numbers and move to the next mechanism.

## The tools that already exist — reuse, do not rebuild

| File | What it does |
|---|---|
| `scripts/research/todo_111_round2_bracket.py` | the first-touch bracket engine. Enters at the open of the bar AFTER the signal, assumes the stop came first when one bar could have touched both, fills a gap-through at the open, never claims a better-than-target fill, caps holding at 14 sessions |
| `scripts/research/todo_111_round2_prescreen.py` | the cheap screen: a family function returns signal indices and directions, the harness does the rest. Add new families to its `FAMILIES` dict |
| `scripts/research/todo_111_round2_baseline.py` | the unconditional baseline |
| `scripts/research/todo_111_round2_market_move.py` | the whole group's half-hour move, minute by minute — already built, at `research-data/todo-111-round2/market-move-equs.parquet` |

**The pre-screen rule:** measure a new idea cheaply first. The baseline is 34
in 100. An idea that cannot reach roughly **40 in 100** on development data can
never reach 60, and it is killed there and written into the rejection ledger.
Do not spend a full frozen backtest on it. That rule is the owner's decision 4
and it is what kept round 2 cheap.

## The data

- **40,278,360 one-minute bars**, 120 parquet files, at
  `/home/openclaw/.openclaw/research-data/todo-111-round2/minutes/`.
  60 NYSE large caps on two independent feeds: `equs__<SYMBOL>.parquet`
  (EQUS.MINI, 2023-03-28 to 2026-08-21) and `xnys__<SYMBOL>.parquet`
  (XNYS.PILLAR, 2023-01-03 to 2026-08-21).
- EQUS.MINI is about 20% of the tape, so a bar's high and low can understate
  the true range and miss a touch. XNYS.PILLAR is the second opinion. A result
  that holds on only one feed is not a result.
- **For the overnight-range strategy, check this first.** EQUS.MINI carries
  extended-hours bars from 04:00 to 19:59 New York, but they are sparse — JPM
  has only about 7 or 8 pre-market bars a day, because a bar exists only when a
  trade prints on that venue. XNYS.PILLAR has **no pre-market bars at all**. So
  the overnight range has to be built from thin prints on a fifth of the tape,
  and that limitation must be stated in the result, not buried.
- Options: the only local chains are **weekly end-of-day** (DoltHub, 2019-02 to
  2022-12). They cannot see whether an option touched +20% before -20%, so the
  option half of the finish line is **untestable** until the owner buys intraday
  option prices. `data/options-dx-2023/*.zip` are 2,618-byte failed downloads.

## The seal

Declared in round 2 and still in force:

- **Development, free to look at:** everything before **2025-07-01**. The last
  entry signal is taken three weeks earlier so no trade runs into the seal.
- **Sealed, untouched:** **2025-07-01 onward**, about fourteen months. The
  pre-screen physically drops those bars rather than trusting a filter.
- It is opened once, for a rule that has already been frozen. Round 2 never
  opened it.

## Standing rules that do not change

- No order of any kind, real or paper.
- $0.00 spend, 0 purchases. No payment, signup, login challenge, CAPTCHA or
  provider agreement completed on the owner's behalf — each is an owner-only
  stop, queued into one decision list at the end.
- No push to GitHub mid-session, no public output, no production alert enabled,
  never print or store a secret.
- Never weaken the frozen gate.
- The builder must be a different agent and thread from the controller; the
  reviewer must be a new read-only agent that never edits what it reviews.
- `COMPLETE` counts only when `final-gate` writes it.
- Save work after each step so no step is ever repeated.
- Run `sudo python3 scripts/check_ownership.py --fix` after commits — root-owned
  git objects are a known trap here.

## The one decision still waiting on the owner

Intraday option prices. Without them the option half of the finish line cannot
be tested at all. Everything else is unblocked.
