# Continue the trade-alert build (Codex kickoff)

## Read these first, in order
1. `trade_alerts_build_docs/HANDOFF_OPEN_ISSUES.md` — every open issue, ranked,
   plus the traps that cost hours if you do not know them. This is the main file.
2. `trade_alerts_build_docs/DECISIONS_AND_OPEN_QUESTIONS.md` — decisions D-101 to
   D-116. D-112 to D-116 are the live ones.
3. `TODO.md` entry 117 for the short version.

## The goal
An alert bot that tells the owner to take a trade, and an honest, measured answer
to whether those alerts make money. The owner takes every alert within 30 seconds
of it firing and does not skip any. The system decides the thresholds, not the
owner. Optimising thresholds by measuring returns is allowed and expected — but
the proof must come from the held-out names, once.

## Start here — task 1, the ETF-only bug
Right now **only the four ETFs are being measured.** All five stock names — NVDA,
MSFT, AAPL, TSLA, LLY — are silently discarded. Any result produced before this is
fixed is an ETF-only study wearing a nine-name label.

The loader is already fixed: `open_core17_ohlcv_1m_file` and
`iter_ohlcv_1m_records` in `consensus_engine/core17_bar_loader.py` accept an
`instrument_types` mapping (symbol -> `ETF`/`EQUITY`) and raise on a missing
symbol instead of defaulting.

**What is missing:** `run_retained_counts` in
`consensus_engine/retained_count_run.py` calls its opener as
`opener(job_dir, filename)` with no third argument, so the mapping never arrives
and every bar keeps the default `ETF` label.

Thread the per-ticker mapping through `run_retained_counts` to the opener, then
run the 2% gate, then re-run the full count. Do **not** "fix" this by relabelling
the stocks as ETFs.

## Before any long run — MANDATORY (D-116)

**Note: the gate script is written but not yet proven.** It correctly reported the
five stocks at zero and the four ETFs working, then a memory fix filtered on the
wrong field name and made it report all nine as zero. Fix the field name and
confirm the four ETFs come back non-zero before trusting it.
    cd /home/openclaw/.openclaw/workspace
    PYTHONPATH=. python3 /root/trade-alerts-builder/m91_sample_gate.py

Runs the first 2%, prints usable moments **per ticker** and **per adapter**, and
exits non-zero if any scores zero. Non-zero exit means stop and fix. Never start a
multi-hour run without it: a full run already finished "successfully" while
measuring four of nine names, because a 44% combined success rate looked plausible
and hid five zeros.

## Running long jobs (D-114)
Launch detached or it dies with your session — this destroyed two runs, 2h07m each,
with no partial output:

    setsid nohup env PYTHONPATH=. python3 <script> args </dev/null >log 2>&1 &

Shard by ticker across **three** processes (not four — 4 cores, 7.7 GB RAM, no
swap, and the build's test suite needs a core). Helpers in
`/root/trade-alerts-builder/`: `m91_count_part.py` (one shard, refuses any ticker
outside the nine training names) and `m91_count_merge.py` (sums the parts).

## The task order after that
1. Fix the instrument-type plumbing, re-run the count, confirm all nine names
   produce non-zero readings.
2. **Cost the exit side.** This is the one thing blocking a profit figure. Entry
   fills are real — first trade print in the 0-30s window, real half-spread,
   slippage and commission. The exit side records spread, slippage and commission
   as OFF and untested. Until an exit costs the same way, nothing can be ranked.
3. Close the two D-104 gaps, or keep every dependent rule switched off and
   labelled untested. Never approximate a missing field and test through it.
4. Then the walk-forward search: tune the 18 candidates on the nine training
   names, and only then test once on the eight held-out names against the frozen
   bar in D-108.
5. If signals fire, buy targeted option quotes for only the chosen days and
   strikes (~$0.41 per name-day, ~90 name-days fit the remaining budget) and test
   the two preregistered exit arms in D-109.

## Hard rules
- **The eight held-out names are sealed: GOOGL, AMZN, META, AVGO, BRK.B, IWM, GLD,
  VXX.** Never read them during tuning. One shot at the end. No peeking, no
  re-running after a bad result.
- **No profit number exists yet, and none should be believed until the exit side
  is costed.** The build currently refuses to rank the 18 candidates. That refusal
  is correct. Do not work around it by approximating a missing cost.
- **Zero is a failure, not a result.** If a name you were told to measure returns
  nothing, stop and report it. Never average it into a total.
- Databento budget: **$37.53 left of $60.** Spendable without further approval.
- No live activation, no orders, no deployment, no broker/Discord/provider live
  calls, no bot restarts. All switches stay off.
- Do not stop `consensus-engine.service` while the build runs — it frees ~960 MB
  but the controller checks the bot is alive and halts.
- Never claim a milestone complete when it is not.

## The build controller (if you use it rather than working directly)
Lives in `/root/trade-alerts-builder/`. `./buildctl status|start|pause|resume|stop`
— exactly one word. State is `state.json`.
- **Never edit a workspace file while a review is pending** — it causes
  "source changed before review". Check the stage first.
- Any git operation trips the tamper alarm, because it fingerprints `.git`.
  Harmless; clear it and re-snapshot.
- To force a legitimate rebuild, write the real reasons into `review_issues` in
  `state.json` and set `stage` to `"build"`. Do not edit `state.json` any other way
  and never reopen an accepted milestone.
- Known weakness: on a repeated blocker it writes a new sub-step and hits the same
  wall again instead of halting. It did this nine times in one morning, ~35 minutes
  each. Halt it yourself if you see the same blocker twice.

## Every mistake that wasted time in the previous session — do not repeat these

Written 2026-09-20 by the Claude session that made them. Ordered by cost.

### 1. A wrong label cost ~6h20m and ~1.26M tokens
`HistoryConventions.price` and `.volume` are **unit** labels, not price-source
labels. The previous session wrote `"TRADE"` for both, reading them as "where the
price came from". No adapter accepts that, so a full run returned zero usable
moments out of 515,727. Correct values: `price="USD_PER_SHARE"`,
`volume="SHARES"` (D-113).
**Lesson:** before filling in any label field, read the code that consumes it and
copy the accepted value. Do not infer a field's meaning from its name.

### 2. Nine identical retries, ~35 min each
When blocked, the controller writes a *new* sub-step and hits the same wall again.
It repeated one blocker nine times (M9.1BE to M9.1BM) before halting.
**Lesson:** if you see the same blocker twice, halt it yourself. Do not let it grind.

### 3. Two runs died, 2h07m of work lost each, no partial output
Both were launched inside the agent session and were never detached, so they died
with it. The kernel log showed **no** out-of-memory kill — the first diagnosis
("probably memory") was wrong and cost a wrong fix.
**Lesson:** `setsid nohup ... </dev/null &` for anything longer than a few minutes,
and check `journalctl -k` for an actual OOM line before blaming memory.

### 4. "source changed before review" — hit twice
Editing any workspace file while a review is pending invalidates the run. The
second time it nearly threw away a 2-hour count run.
**Lesson:** check the stage first. If a run is in progress, write your notes
outside the repo and merge them in when it halts.

### 5. Stopping the services halted the build
`systemctl stop consensus-engine.service` frees ~960 MB, but the controller checks
the bot is alive and stops with "a live bot program needs attention".
**Lesson:** leave it running while the build runs.

### 6. `pkill -f <name>` killed the invoking shell — twice
`pkill` matched the calling shell's own process group; the second time it killed
the relaunch in the same command (exit code 144).
**Lesson:** never `pkill` and relaunch in one command. Kill by explicit PID, verify
it is gone, then launch separately with `setsid`.

### 7. Caching whole files to answer a question about six days
A sample-run cache held **2.6 GB** on a 7.7 GB box with no swap, and the OS killed
a process. The "fix" for that then filtered on the wrong field name and zeroed the
whole result — a broken check that reports failure everywhere is as bad as one that
reports success everywhere.
**Lesson:** cache only what the sample needs, and after changing a check, confirm
it still passes on data you know is good. A check must be proven in both directions.

### 8. Nearly committed 125 MB of cached market data
`data/` holds `consensus.db` and cached JSON. Caught only by sizing untracked paths
before staging.
**Lesson:** `du -sh` untracked paths before `git add`. Keep `data/` untracked.

### 9. Trusting a total instead of a per-ticker split
A 44% success rate looked plausible. It was four ETFs at 100% and five stocks at
exactly zero. The contract tests passed the whole time — they check the code does
what it says, not that the run measured what it was told to.
**Lesson:** never report or trust a combined total for work split across named
things. Split it. Treat any zero as a failure. This is what D-116's 2% gate exists
to enforce.

### 10. Nobody was watching for 6h20m — the largest single cost
The build stopped at 02:50 and was not looked at until 09:15. The watchdog only
auto-resumes stops it already recognises; anything else sits silently forever and
notifies no one. The owner found it, not the agent.
**Lesson:** a stalled build is the expensive failure, not the mistake that stalled
it. Check the stage on a fixed cadence, and add a notification for any stop the
watchdog cannot clear itself. Never assume "it is running" without looking.

### 11. Asserting a command's behaviour from memory instead of reading it
The previous session claimed `buildctl resume --clear-attention` would work.
`buildctl` takes exactly one word; the flag was silently ignored, so a "fix" that
did nothing was reported as done. The real path is
`python3 controller.py --clear-attention resume`.
**Lesson:** read the script before stating what a flag does. Verify the effect
afterwards rather than assuming the command worked.

### 12. Repeating a mistake ten minutes after writing the lesson for it
`pkill -f <name>` killed the invoking shell for a **third** time — after the
lesson in item 6 had already been written down, because the pattern matched the
shell's own command line containing that text.
**Lesson:** a written lesson does not protect you. When killing a process, list it
with `ps -eo pid,args | grep "[m]y_pattern"` (the bracket stops grep matching
itself), confirm the PID is the real target, then kill that PID alone.
