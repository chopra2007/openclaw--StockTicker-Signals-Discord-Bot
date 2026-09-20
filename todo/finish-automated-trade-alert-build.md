# Finish the automated trade-alert build
**Status:** OPEN
**Created:** 2026-09-09

**CURRENT STATUS (2026-09-19 PDT):** **Running unattended, 53 steps accepted,
deep inside the M9.1 historical-replay family (past M9.1BC).** The earlier
2026-09-16 M0.2/M9.3 stop is long cleared; that account is kept below as
history.

What is built and tested on stored data: all four playbooks read real minute
bars; a runner that sweeps 18 candidate settings across the nine training
tickers; the entry model that fills a trade at the real price within 30 seconds
of the alert, charging the real spread and commission (D-106); a two-part exit;
and the catalog of price levels the stops and targets hang off.

**No profit figure exists yet.** The build refuses to rank the 18 candidates
because the exit side has no quote data costed and two D-104 gaps are open.
That refusal is correct and must not be worked around by approximating the
missing costs.

Latest stop, cleared 2026-09-19: the build asked which purchased files it was
allowed to read. Answered as **D-112** in
`trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md` and referenced from
the M9.1BD roadmap row — the one-minute bar job directory
(`research-data/databento/core17-1y_2025-09_to_2026-09/ohlcv-1m/`
`EQUS-20260916-47J8PRKRBB`), manifest-verified files only, the nine D-107
training tickers only, per-ticker EQUITY/ETF labels, and the full
`HistoryConventions` set (bars stamped at START, premarket+regular,
PROVISIONAL under D-110). The eight held-out tickers stay sealed.

Two structural fixes that unstuck the build for good:
- `MAX_PUBLISHED_ARTIFACT_FILES` raised 128 to 512 in `controller.py`. Each new
  adapter added recorded files; the bundle hit 129 and would have blocked every
  future step.
- Step IDs can now carry two letters (`M9.1AA` onward) in `controller.py` and
  both result schemas. The build previously died at `M9.1Z`.
Both were followed by the full 176-test controller run and a READY.json reseal.

Money: Databento authority $60 fresh total, $22.47 spent, **$37.53 left**.

Operational: `buildctl resume --clear-attention` does nothing — `buildctl`
takes only one word. Use `python3 controller.py --clear-attention resume`, then
`./buildctl start`. `resume-watchdog.py` auto-restarts the build after
known-harmless stops (mainly `.git/index` fingerprint trips) and logs anything
it refuses to touch to `resume-watchdog.log`.

**Trap to avoid:** editing any workspace file while a review is pending causes
"source changed before review". Check the stage first; only edit when the build
is halted.

## Goal

Finish the protected trade-alert roadmap through the existing automated
controller while preserving every actual-data, definition, profit, live, and
approval gate.

## Finished work at this handoff

- M5.3 historical replay passed protected proof and independent review.
- `state.json` records M5.3 in both `completed` and `history`.
- The M5.5 packet now carries `recorded_acceptances` and
  `acceptance_history` from `state.json`.
- The exact M5.3-to-M5.5 save-and-reload test passes.
- All 124 controller tests pass.
- The controller, builder AI, reviewer AI, protected tests, and watcher are
  stopped. `trade-alerts-build.service` is inactive and `PAUSED` exists.

## Exact resume point

1. Read `/root/trade-alerts-builder/CONTINUE_AUTOMATED.md` and
   `/root/trade-alerts-builder/PAUSE_CHECKPOINT.md`.
2. Confirm the controller is still paused and no duplicate process exists.
3. Run `omx ralplan preflight --json`. Do not bypass a failed preflight.
4. Use only `/root/trade-alerts-builder/buildctl resume`.
5. Let the controller clear the stale interrupted M5.5 reviewer record and
   independently repair the false blocked result.
6. Start M5.5 durable session and delivery recovery only when the controller
   returns to its normal build stage with M5.3 acceptance visible.

M5.4 remains data-blocked. Earlier actual-source, strategy-definition,
executable-profit, and live-delivery gates remain open. All switches stay off.
No purchase, deployment, live alert, brokerage action, or real-money trade is
authorized by this TODO item.

### Session notes — 2026-09-09
- **Worked on:** Accepted M5.3, diagnosed and fixed the M5.5 acceptance-handoff bug, added the exact saved-state test, and paused every builder process.
- **Decisions:** Resume only through the single protected controller; M5.5 is next and M5.3 must not be repeated.
- **Next:** Run preflight, resume the controller, repair the false M5.5 blocked result through review, and start the real M5.5 work.

## Where it stands, 2026-09-10

Accepted so far (11): M2.2, M4.1, M4.2, M4.5, M4.6, M5.1, M5.3, M5.5, M6.1,
M6.2, M6.3. M5.5 was the first milestone built and reviewed entirely on Claude
Code; M6.1 through M6.3 followed on the same routing with no controller change
needed between them.

Six machinery traps were found and closed, each with a test or a written rule.
They are described with dates in `/root/trade-alerts-builder/MONITORING.md`:

1. The controller refuses to build while an undeclared coding session has the
   workspace as its working directory. Its own children are exempt, and so is a
   session listed in `supervisors.json`.
2. A protected file changed by anyone - including the owner's own TODO.md - froze
   the milestone until the stop was cleared. Clearing now re-snapshots and
   records the difference.
3. The reviewer could not read the evidence it was judging, because read-only
   mode confines file reading to its own folder. It is now given the build run.
4. `next_milestone` must lead with a milestone id, and that id must read as an
   open row in the ROADMAP progress list, where the last row naming an id wins.
5. A usage-window limit was counted as a build failure. Any 429 is now a wait and
   costs no repair.
6. Evidence figures were written from the builder's own test run instead of the
   controller's published artifacts.

Pace on the subscription is about one milestone per five-hour window, with most
of the wall clock spent waiting for the window rather than working.

## Open gates, unchanged

M5.4 and every earlier actual-data, definition, source, options and profit gate
remain open and separate. M0.3B's proposed rule packet is still not adopted and
its owner question still has no answer. No switch was turned on, nothing was
deployed, and no live or paid provider call was made.

## Where it stands, 2026-09-12 21:30 PDT

Paused cleanly. Twenty-one milestones accepted, through M8.4. M8.5 is part-built,
no repair outstanding, no attention flag. `PAUSED` exists and the service is
inactive.

### The one open decision: spending

The weekly Claude allowance is spent - 100% used, about 2 days 8 hours to reset -
and the build had begun drawing on paid extra usage. The kickoff authorizes the
subscription and no other spending, so it was paused rather than left running
overnight on the owner's money. Either approve the overage explicitly or wait for
the weekly reset.

### Two machinery faults fixed 2026-09-11/12

Both had been misread in the earlier notes, so the record is corrected here.

**The Claude launch command was missing `--verbose`.** Claude Code 2.1.269
refuses `--output-format stream-json` under `-p` without it. The switch from
Codex to Claude happened 2026-09-11 at about 14:45, and the first Claude job ever
launched died in 1.8 seconds; the controller scored it as a builder failure.
Every job would have died the same way. Fixed in `_agent`, guarded by a test.

Correction: the four `max_output_tokens` failures the old notes blamed for M7.5's
repair limit were Codex jobs, not Claude - every one of those logs is in Codex's
event format. The output-budget stop the notes called "deliberately not built"
had in fact been built.

**The test run outgrew its own kill timer.** The protected launcher killed the
broad run at a hard 420 seconds and the traceback was a plain timeout, never a
failing test. M7.5's accepted run had taken 413.8 seconds against that cap;
M8.4's tests crossed it. Measured uncapped: 2436 tests pass in 425.9 seconds. The
cap is now 1200. M8.1's accepted run then took 433.3 seconds.

Since both fixes landed, M8.1 through M8.4 were accepted, three of them with zero
repairs and no supervisor intervention.

### M7.5, settled

The reviewer's objection was real: after a heads-up the replay froze whatever
structure the next crossing supplied, so a later crossing with different prices
or a different ATR could move the level the milestone calls frozen. The repair
keeps the announced structure and refuses any later one that differs, with long
and short tests. Accepted, verdict pass.

### Two state edits, both recorded

`state.json` is normally never hand-edited. A transport failure had overwritten
M7.5's reviewer objection with `builder process failed`, and it was restored as a
byte copy from the saved reviewer record. Separately, one `waiting_until`
timestamp was cleared on the owner's direct request after the five-hour window
had visibly reset. Full detail in `/root/trade-alerts-builder/PAUSE_CHECKPOINT.md`.

### Next session

Read `/root/trade-alerts-builder/CONTINUE_AUTOMATED.md`, then
`PAUSE_CHECKPOINT.md`. Declare the session in `supervisors.json` before resuming,
and expect one `protected files changed since this milestone started` stop,
because this file and `TODO.md` were edited here.

## Where it stands, 2026-09-15/16 - Codex usage cap, then switched back to Claude

### What actually happened to Codex (read the machine state, not the old handoff prose)

The build had moved onto Codex on 2026-09-11 around 14:45. Codex reached
milestone M4.7A and, on 2026-09-14 at 06:04 PDT, made its one real attempt
(`repairs` went from 0 to 1): it edited `consensus_engine/event_store.py`,
`consensus_engine/options_portfolio.py`, and their tests/docs, then ran
verification. Two tests failed:
`tests/trade_alerts_contracts/test_options_portfolio.py::test_both_stock_directions_and_signed_delta_boundaries[SHORT-PUT--0.5]`
and `[SHORT-PUT--0.7]`, both raising
`consensus_engine.trade_alerts_models.RecordError: SHORT risk and targets have
invalid geometry` (169 of 171 tests in that run passed). That failure is still
the real, current blocker on M4.7A - nothing since has touched it.

At 06:19 PDT the very next attempt (attempt 2, wall time 3.9 seconds) hit
Codex's hard usage cap: `"You've hit your usage limit. Visit
https://chatgpt.com/codex/settings/usage to purchase more credits or try again
at Sep 19th, 2026 9:40 PM."` The controller correctly did not count this as a
repair. But it also kept retrying automatically every 30 minutes - attempts 3
through 72, every single one from 06:49 PDT on the 14th through 17:54 PDT on
the 15th, about 35 hours - and every one hit the identical usage-cap message in
under 4 seconds and did nothing. `repairs` stayed at 1 the entire time; the
"usage limit is a wait, not a failure" rule worked exactly as designed, it just
kept waiting for four and a half days (the cap does not clear until 2026-09-19).

The controller only stopped polling when a separate, unrelated check tripped:
at 18:24 PDT on the 15th it noticed `TODO.md` had changed since M4.7A's build
started (a normal side effect of other work in this same workspace) and set
`stage: awaiting_attention`, `attention: "protected files changed since this
milestone started"`. `trade-alerts-build.service` went inactive at that point
and has stayed inactive since; there is no `PAUSED` file. This is a real,
unresolved attention flag, separate from the underlying test failure - both
have to be dealt with before the milestone can move again.

The six helper directories the earlier Codex session log named
(`/root/m85_fix`, `/root/records_comparison_fix`, `/root/routing_review`,
`/root/data_access_map`, `/root/provider_docs`, `/root/research_authority`) no
longer exist on disk - nothing was left half-written there to build on or clean
up.

### Switched back to Claude

The owner asked to move the controller off Codex and back onto Claude models
rather than wait out the cap. This was already done once before, 2026-09-09 to
2026-09-11 (preserved at
`/root/trade-alerts-builder/repairs/codex-subscription/before/`); this was a
merge of that preserved Claude launch path back into the current
`controller.py`, not a rebuild, keeping every fix the file gained during the
Codex period (the output-exhaustion stop, re-targeted at Claude's real
`stop_reason: "max_tokens"` signal instead of Codex's schema-formatting bug;
the anchored milestone-ID pattern; `finalize` outranking `escalated`).
Routing is now Sonnet 5 at `low` effort for all ordinary work (build, review,
repair, hard review, finalize) and Opus 5 at `medium` effort for the one
escalation after a failed repair (`escalate_after_repairs: 1`, unchanged).
Full detail, including exactly what was kept from the Codex-period file and
why the old "effort must be medium" guard was deliberately removed, is in
`/root/trade-alerts-builder/repairs/claude-routing-restored/CHANGE_NOTES.md`.
The full controller test suite (165 tests, 48 subtests) passes, and two real
`claude -p` sessions were run through the actual launcher against a disposable
throwaway job directory (not the real build workspace) to prove the build and
review launch paths both work and that the reviewer's Write tool is genuinely
denied, not just denied in a mocked test.

`/root/trade-alerts-builder/archives/storage-manager/README.md` had a stale
paragraph claiming Google Drive access needs "the supervising connected Codex
task" - corrected; the server-native rclone transfer (already live and
verified since 2026-09-13) is the real path now, and it needs no AI session of
any kind, Codex or otherwise.

Nothing in production was touched: `trade-alerts-build.service` is still
inactive, no `PAUSED` file was created or removed, no milestone was re-opened,
`state.json` was not hand-edited, and nothing was committed or pushed.

### Correction, 2026-09-16: Opus was not actually warranted next

The paragraph below originally said the next build attempt would escalate
straight to Opus, since `repairs` was already 1. That was wrong to accept
uncorrected: the one recorded repair came from Codex's `gpt-5.6-sol` at
`medium_build`, `repairs: 0` at the time - not from a failed Sonnet attempt.
Jumping to Opus would have skipped giving Sonnet its own attempt at this
specific bug. `repairs` itself is a fact of the milestone's history and was
not hand-edited; instead `escalate_after_repairs` was raised from 1 to 2, so
Sonnet gets one real attempt (and, if that fails, one repair) before Opus
escalates, regardless of which provider produced the repairs already on the
counter. `medium_build`, `repair`, and `hard_review` also now run at Sonnet
**medium** effort instead of `low` - the bug blocking M4.7A was made by a
medium-effort model, and this build's domain logic (options risk/target
geometry) has produced real bugs before. Detail and updated test evidence:
`/root/trade-alerts-builder/repairs/claude-routing-restored/CHANGE_NOTES.md`.
The short kickoff for the next session is
`todo/kickoffs/continue-trade-alert-build.md`.

### Single next action

Two separate things are blocking M4.7A, and both need a human decision before
the controller runs again:

1. **The attention flag** ("protected files changed since this milestone
   started") needs `/root/trade-alerts-builder/buildctl resume
   --clear-attention` - the controller's own checked recovery path. This was
   deliberately not run as part of this switch, since starting the controller
   on a half-switched or freshly-switched configuration is exactly what the
   kickoff said not to do.
2. **The real test failure** (`SHORT risk and targets have invalid geometry`
   on `SHORT-PUT` at delta -0.5 and -0.7) is still unfixed. With `repairs: 1`
   and `escalate_after_repairs: 2`, the next build attempt on M4.7A uses the
   `repair` profile - Sonnet 5 at medium effort, not Opus.

Do both together: clear the attention flag, then let the controller make
Sonnet's repair attempt on M4.7A. If that attempt also fails, the next one
escalates to Opus automatically.

### Addition, 2026-09-16: what happens if Opus also fails

Previously this said "if Opus's attempt also fails, the milestone should go
to a human." That's no longer the whole story. If Opus's own attempt also
fails, the controller now runs one more read-only session ("triage") that
checks `ROADMAP.md` for a genuinely different, dependency-ready milestone -
it never touches code and never re-judges the three failed attempts. If one
exists, M4.7A is recorded in the blocked-milestone registry (never deleted)
and the build moves on to that milestone automatically, with a fresh repair
count. If nothing independent is ready, or the triage session itself fails
for a non-quota reason, it falls back to exactly the old behavior - a human
has to look, with the reason recorded in `last_failure`. Detail, code, and 11
new tests: `/root/trade-alerts-builder/repairs/claude-routing-restored/CHANGE_NOTES.md`
and `/root/trade-alerts-builder/test_triage.py`. `max_repairs` was also
raised from 1 to 2 as part of this - at 1, Opus would never actually have
gotten a turn (see that same CHANGE_NOTES.md for why).

## Where it stands, 2026-09-15 22:45 PDT - M4.7A ACCEPTED, now stopped on disk space and money

### M4.7A is done

The blocker that had held this milestone since 2026-09-14 is fixed and the
milestone is accepted (recorded `completed_at: 2026-09-15T22:17:19-07:00`,
review run `runs/20260915-221533-965276-review`). Accepted milestones went from
38 to 39.

The actual bug was in the test, not in the risk logic. The failing test
`test_both_stock_directions_and_signed_delta_boundaries` built a SHORT
candidate by flipping only the `direction` field with `replace()`, leaving the
LONG-shaped stop and target in place. That produced an impossible trade - stop
below entry and target above entry on a SHORT - so the geometry check in
`consensus_engine/trade_alerts_models.py` correctly rejected it. Sonnet 5 at
medium effort, `repair` profile, found this and corrected the test's
construction. The protected verification then ran the suite twice for
repeatability: 65 passed, exit code 0, both runs.

So the Sonnet-gets-its-own-attempt decision (raising `escalate_after_repairs`
from 1 to 2) was the right call - Sonnet solved it and Opus was never needed
for M4.7A.

### Then M9.3, and a real stop

With M4.7A accepted the controller moved to M9.3 and hit a genuine wall, in
two stages:

1. Sonnet returned `status: blocked` naming `M0.2` as the next milestone, and
   reported `trade_alerts_build_docs/ROADMAP.md` as a changed file. But the
   file already contained the needed note, so nothing actually changed on disk.
   The controller compares reported changes against the real file manifest,
   found an empty delta, and rejected the submission as incomplete evidence.
   It tried the same thing twice, tripped the repeat-failure guard
   (`failure_recurrence >= 2`) and froze with `diagnosis_required: true`.
2. After clearing that, the attempt escalated to Opus 5 at medium effort as
   designed (`repairs: 2` met `escalate_after_repairs: 2`). Opus did not fail -
   it returned a clean, definitive answer: M9.3 cannot be implemented because
   the M0.2 provider/queue/storage/disk/memory budgets and the validated input
   continuity they depend on are unresolved and need an owner or data decision
   ("estimates above the USD 24 unreserved amount, unknown billing, unknown
   OPRA HTTP 400 cause, unpriced dates, unresolved local capacity"), plus a
   separately reviewed repair for the earlier storage/temp-folder failure.

Because Opus returned `blocked` with no `next_milestone`, the controller took
its "genuinely blocked, stop for a human" branch (controller.py line 1540)
rather than the triage branch. The triage feature only fires when
`repairs > max_repairs`, which never happened here - Opus answered cleanly
instead of failing.

### The concrete, measurable part of the blocker: disk space

`/` is 75 GB, 65 GB used, **7.2 GB free (90% full)**. The build's frozen
reserve requires 12,000,000,000 bytes (12 GB). That single fact is why the
whole M0.2 family is blocked, and M9.3 sits behind it. Roughly 5 GB has to be
freed. Where the space actually is:

| Location | Size | Notes |
|---|---|---|
| `~/.openclaw/research-data` | 19 GB | paid market data (Databento etc.) - should NOT be deleted |
| `~/.openclaw/workspace` | 6.3 GB | of which `.omc` is 2.9 GB (tool caches) |
| `~/.openclaw/db-backups` | 4.7 GB | old database backups |
| `/root/trade-alerts-builder` | 3.9 GB | the build's own run history |
| `/var/log/journal` | 2.5 GB | system logs, safely vacuumable to ~200 MB |
| `/root/.cursor-server` | 2.7 GB | |
| `~/.openclaw/npm` | 2.6 GB | |
| `/root/.codex` | 1.8 GB | Codex CLI data, no longer the build's router |

Nothing was deleted - freeing space is the owner's call, and the paid market
data is the largest single item.

### Correction to the kickoff file: the resume command does not work as written

`todo/kickoffs/continue-trade-alert-build.md` says to run
`/root/trade-alerts-builder/buildctl resume --clear-attention`. That command
silently does nothing useful: `buildctl` only accepts a single word
(`if len(sys.argv) == 2`), so the extra flag makes it fall through to
`status` and just print the current state. The flag lives on the controller,
not on buildctl. The command that actually works is:

```
cd /root/trade-alerts-builder && python3 controller.py --clear-attention resume
```

then `./buildctl start` to restart the service.

### Single next action - needs an owner decision

The build cannot move on its own. Two choices, not mutually exclusive:

1. **Free about 5 GB** so the M0.2 family's 12 GB reserve is satisfied. The
   safe, non-destructive start is vacuuming the system journal (2.5 GB to
   ~200 MB). Getting the rest means deciding about `db-backups` (4.7 GB),
   `.omc` caches (2.9 GB), `.codex` (1.8 GB) or old builder runs - a decision
   about what is disposable. The 19 GB of paid market data should stay.
2. **Answer M0.2's data and money questions**: the billing position, the cause
   of the OPRA HTTP 400, and the unpriced dates. Opus flagged estimates above
   the USD 24 unreserved amount, and no new spending is authorized by this
   TODO item.

If neither is wanted right now, the other option is to authorize the build to
skip M9.3 and work an independent milestone instead. About 76 roadmap
milestones are neither completed nor in the blocked registry, so there is
other work available - but routing to one means either a builder that returns
`blocked` **with** a ready `next_milestone`, or letting the triage session
choose, and triage currently only runs after a repair-limit failure. That is a
behavior change to the governed controller, so it was not made unilaterally.

All switches remain off. Nothing was activated, deployed, restarted, pushed,
purchased, or deleted. `state.json` was not hand-edited; the only controller
action taken was its own `--clear-attention resume`.

## Handoff — read this first (2026-09-19 Pacific, updated)

`trade_alerts_build_docs/HANDOFF_OPEN_ISSUES.md` is the single list of every open
issue, every trap, and what to do next. It is written for any agent picking this
up, including a non-Claude one. Highlights:

- 54 steps accepted; current step M9.1BM/M9.1BN.
- **No profit number exists yet.** The exit side is uncosted and two D-104 gaps
  stand. The build's refusal to rank the 18 candidates is correct — do not work
  around it by approximating a missing cost.
- **D-113** corrected two unit labels D-112 got wrong: `price = "USD_PER_SHARE"`
  and `volume = "SHARES"` (D-112 wrongly said `"TRADE"` for both). That one label
  made the first real count run return zero usable moments out of 515,727 and
  cost 6h20m and ~1.26M tokens in repeated blocked steps.
- The eight held-out tickers (GOOGL, AMZN, META, AVGO, BRK.B, IWM, GLD, VXX) are
  still sealed and unread. One shot against the D-108 bar.
- Databento budget: $37.53 of $60 left.
- Two unfixed controller weaknesses: it grinds on a repeated blocker instead of
  halting, and nothing notifies a human when it stops.

### 2026-09-19 evening — first real result, and the bug it found

- **55 steps accepted.** The D-113 count run finished:
  **76,404 usable decision moments per playbook out of 171,909 (44%)**.
  Result file: `trade_alerts_build_docs/M9_1BN_RETAINED_COUNTS.json` (D-115).
  First non-empty result in this build.
- **Most important open bug:** every rejection is `INCOMPATIBLE_INSTRUMENT_TYPE`,
  at exactly 5/9 of the total. `open_core17_ohlcv_1m_file` labels every bar `ETF`
  by default, so **all five stock names are discarded and only SPY, QQQ, XLV and
  USO are measured.** Give the loader a per-ticker type. Do not relabel the stocks.
- **D-114:** long jobs must be launched detached (`setsid nohup ... </dev/null &`)
  and sharded by ticker across three cores. Two runs died because they were
  launched inside an AI session; no out-of-memory kill was involved. Sharded run
  took about an hour against a 7-hour single-process estimate. Helpers:
  `m91_count_part.py` and `m91_count_merge.py` in `/root/trade-alerts-builder/`.
- **Do not stop `consensus-engine.service` while the build runs.** It frees ~960 MB
  but the controller checks the bot is alive and halts with "a live bot program
  needs attention".

### MANDATORY before any long run — the 2% gate (D-116, 2026-09-20)

    cd /home/openclaw/.openclaw/workspace
    PYTHONPATH=. python3 /root/trade-alerts-builder/m91_sample_gate.py

Runs the first 2% (~2 sessions per ticker), prints usable moments **per ticker**
and **per adapter**, and **exits non-zero** if any ticker or adapter scores zero.
Non-zero exit = stop and fix; do not start the full run.

Why: the 44% success rate in D-115 was four ETFs at 100% and five stocks at
exactly zero, averaged into a plausible-looking number. A total hides a hole.
Zero is a failure, not a result. The contract tests passed the whole time this
bug was live.
