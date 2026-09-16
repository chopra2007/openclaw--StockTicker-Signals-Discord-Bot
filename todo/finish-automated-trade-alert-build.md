# Finish the automated trade-alert build
**Status:** OPEN
**Created:** 2026-09-09

**CURRENT STATUS (2026-09-12 21:30 PDT):** Paused cleanly, one decision waiting.
Twenty-one milestones accepted: M2.2, M4.1, M4.2, M4.5, M4.6, M5.1, M5.3, M5.5,
M6.1, M6.2, M6.3, M6.4, M7.1, M7.2, M7.3, M7.4, M7.5, M8.1, M8.2, M8.3, M8.4.
M8.5 is the next one and sits part-built; nothing is broken and no repair is
outstanding. The decision is money, not code: the weekly Claude allowance is
spent (100% used, about 2 days 8 hours to reset) and the build had started
drawing on paid extra usage, which the kickoff does not authorize, so it was
paused rather than left spending overnight - either approve the overage or let
it wait for the weekly reset. Two machinery faults found and fixed on
2026-09-11/12 (the Claude launch command was missing `--verbose`; the test run
had outgrown its own 420-second kill timer, now 1200) are written up below, and
both had been misread in the earlier notes. M7.5's reviewer objection was real
and is fixed: the replay now keeps the price level it announced and refuses a
later one that differs. 145 controller tests pass. Next: read
`/root/trade-alerts-builder/PAUSE_CHECKPOINT.md`, which carries the whole
situation and the exact resume steps.

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
