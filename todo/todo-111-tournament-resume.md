# TODO #111 tournament — how to pick this up cold

**Status:** development finished and committed. **The sealed 2022-2026 test has
NOT run.** Nothing is live; no order was ever placed, real or paper.

## Read these first, in this order

1. `todo/todo-111-tournament-result.md` — the plain-English result.
2. `todo/todo-111-tournament-finalists.md` — the five frozen finalists and why.
3. `todo/todo-111-tournament-frozen-matrix.md` — the 58 rules and three dated
   amendments. Nothing in it may change now that outcomes exist.

## The state of the data

| what | where | done? |
|---|---|---|
| development chain snapshots (409 entry days) | `research-data/todo-111-tournament/chains/` + the old condor folder | yes |
| development leg minutes, all 37 funded tests | `research-data/todo-111-tournament/legs/` | yes |
| event (FOMC/CPI/jobs) leg minutes | same | yes |
| sealed chain snapshots, all 242 weeks | `research-data/todo-111-tournament/chains/` | yes |
| **sealed leg minutes** | `research-data/todo-111-tournament/legs/` | **PARTIAL — downloading, 436 contract-days, several hours at the throttled rate** |

## The exact next steps

**1. Already done — the manifest is resolved.** All five finalists resolve
cleanly: 508 contract-days across 186 entry days. Re-run it only if you change
the finalist list:

```
python3 scripts/research/todo_111_tourney_sealed.py manifest 1 11 26 28 40
```

**2. Finish buying the legs.** A download was in flight when this note was
written and will have continued. Re-run it until it says `ALL DONE`; it skips
whatever is already on disk and never pays twice. One contract per request —
anything larger stalls server-side and has to be killed:

```
python3 -u scripts/research/todo_111_tourney_finish_pull.py 2.00
```

That script already has `manifest_sealed` in its queue. It cost-estimates every
request, never pays twice, and refuses to cross the $20 ceiling.

**3. Run the sealed test.** This is the only command anywhere that reads a
sealed outcome:

```
python3 scripts/research/todo_111_tourney_sealed.py evaluate 1 11 26 28 40
```

It refuses to run without that explicit list — there is no "all tests" path —
and it stamps the finalist list and a timestamp into `results_sealed.json`
before it opens a single leg file.

**4. Then, and only then:** have a reviewer that did not write the code
independently recompute any sealed winner's load-bearing trades.

## Things that will bite you if you do not know them

- **Fills are the midpoint** of bid and ask on every leg, entering and exiting.
  Commission is reported separately at $0.45 per contract per side and is never
  folded into the fill.
- **The data provider throttles hard** after a few gigabytes. Requests go from
  about 7 seconds to minutes, and multi-contract requests hang forever in an SSL
  read that no timeout interrupts. `todo_111_tourney_finish_pull.py` works
  around this by running each request in a child process it can kill. Do not
  raise `CHUNK` above 1 without re-testing.
- **Never run two downloaders at once.** They share one spending ledger. One
  duplicate payment already happened that way (about a tenth of a cent).
- **Test 28 cannot become a historical winner in this run.** Its trigger fires
  on only 32 sealed dates against a 100-trade bar. Test 26 fires on 58. Only
  tests 1 and 11 (160 each) can clear it. This is a sample limit, stated in
  advance, not a verdict.

## Money

Spent **$11.99** of the **$20.00** hard ceiling. The sealed legs are the only
purchase left and should cost roughly **$0.50 to $1.00**. Databento credit
remaining is about **$113**.

## What is still genuinely open, beyond the sealed test

- **Mechanism 6 (put-flow on individual stocks)** passed its selection gate on a
  three-way reconstruction test but its data was never bought. It can only ever
  be PROMISING, NOT PROVEN — eleven weeks, one market regime.
- **Mechanism 5 (scheduled events)** has all its data now but was never scored,
  because the finalists were frozen before its legs landed. Worth running.
- **Widening the grid.** Everything used one entry per ISO week. The two best
  rules are sample-starved on the sealed side; more entries per week would fix
  that and costs only data.
