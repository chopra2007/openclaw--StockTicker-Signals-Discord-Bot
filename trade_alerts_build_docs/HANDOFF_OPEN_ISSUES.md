# Trade-alert build — open issues and handoff notes

Written 2026-09-19 Pacific for whoever picks this up next, including a non-Claude
agent. Everything here is either verified in the code or taken from the build's own
records. Where something is unverified it says so.

## 1. What this build is and where it stands

The goal is an alert bot that tells the owner to take a trade, and a measured,
honest answer to whether those alerts make money. The owner takes every alert
within 30 seconds; the system, not the owner, decides the thresholds.

55 milestones are accepted. The controller is stopped at M9.1BT. What exists: four
playbooks running on real one-minute bars, an 18-candidate threshold sweep, a
30-second entry fill using real spreads and commission, a two-part exit, and a
price-level catalog.

**There is no profit number yet, and none should be believed until there is one.**
Two reasons, both real: the exit side has no quote data costed, and two D-104 data
gaps stand. The build refuses to rank the 18 candidates for exactly this reason.
That refusal is correct. Do not work around it by approximating a missing cost.

## 2. Open issues, most blocking first

### 2.1 The exit side is uncosted — this is the single thing blocking a profit figure
Entry fills are real: first valid trade print inside the 0-30s window, real
half-spread from the quote at that print, plus slippage and commission. The exit
side records spread, slippage and commission as OFF and untested in `cost_scope`.
Until an exit costs the same way, no candidate can be ranked and no return is real.

### 2.2 Two D-104 gaps, dependents switched off
Recorded gaps where a data field is missing. The rule is absolute: never
approximate a missing field and test through it. Every rule depending on these is
off and labelled untested. Also open: the M9.1S quote-decision / M4.4-confidence
gap, and the daily ATR/tick gap.

### 2.3 Five adapters never called
From the M9.1BC count run, `not_called`: `atr_1m`, `vwap_slope`, `vwap_crosses`,
`quote_decision`, `hod_comp_rs_policy_inputs`. Nobody has established whether these
are legitimately out of scope for the two active playbooks or silently skipped.
Unverified either way.

### 2.4 ETF-only measurement bug — sample fixed, full run still required
The first non-empty count run (D-115, 2026-09-19,
`M9_1BN_RETAINED_COUNTS.json`) returned 76,404 ready moments per adapter out of
171,909 — 44%. Every rejected moment is `INCOMPATIBLE_INSTRUMENT_TYPE`, and the
count is exactly 171,909 × 5/9. Five of the nine names are stocks, so **all stock
moments are being thrown away and only SPY, QQQ, XLV and USO are measured.**
Cause: `open_core17_ohlcv_1m_file` stamped every bar `ETF` by default and took no
per-ticker type, while D-112 correctly calls the five stocks `EQUITY`.

The loader accepts an `instrument_types`
mapping (symbol -> `ETF`/`EQUITY`); it wins over the old default and skips a
symbol missing from that mapping rather than falling back. On 2026-09-20 the shared count path was
fixed to pass that mapping into the loader. The D-116 sample then returned 1,386
usable readings for each of the five stocks and four ETFs. The full count still
must be rerun. Do **not** relabel the stocks as ETFs.
Separately, the `vwap_level` adapter rejects the same 95,505 moments with
`NO_TRADED_SESSION_BAR_YET`; same root cause or not is unestablished.

### 2.4b Historical empty count run — diagnosed
M9.1BC checked 515,727 decision moments and returned `ready: []`. The cause was a
wrong unit label, now fixed by D-113. D-115 and the clean D-116 sample are now
non-empty. The full corrected nine-name count still has not completed.

### 2.5 Repeated-blocker controller repair — implemented
When the builder cannot proceed it writes a *new* sub-step and hits the same wall
again. On 2026-09-19 it repeated an identical blocker nine times (M9.1BE to
M9.1BM), roughly 35 minutes each, about 1.26M tokens, before halting. It should
halt on the first repeat. The controller now records attempts before launch and
stops when the same normalized blocker appears twice, even under a renamed step.

### 2.6 Stop notification — implemented
`resume-watchdog.py` auto-resumes only stops it already recognises. Anything else
leaves the build sitting silently. On 2026-09-19 that was a 6h20m silent stall.
The system-managed watcher now allows one recovery for an exact diagnosed process
death and sends an operations notice for unknown stops or an exhausted allowance.

### 2.7 Long jobs now checkpoint outside the builder session
The M9.1BM/BN builder started the real count run, split it into three parallel
processes across the nine tickers, and its session died with no partial output
kept. The controller records this as `builder process failed`. The watchdog treats
it as benign and retries, so it self-heals — but every death threw away the whole
run under the old launcher.

**Root cause found, 2026-09-19:** the run was launched inside the builder's own
agent session and was never detached, so it died when that session ended. Two
deaths, 2h07m of work lost each time, no partial output. The kernel log shows **no**
out-of-memory kill, so memory was not the cause. **D-114** is the fix: launch long
jobs through `trade-alerts-offline-count@1..3.service`. Each shard now writes a
checkpoint after every ticker and skips completed tickers after a restart. Helpers
remain under `/root/trade-alerts-builder/`.

### 2.8 Skipped and degraded sessions are unreviewed
The count run skipped 108 ticker-days: 90 `NO_USABLE_BARS` (these line up with ten
market holidays across nine names, which looks right) and 18 `DEGRADED_SESSION`
(2025-10-10 and 2025-10-13 on all nine). 18 more ticker-days have no prior session.
Nobody has confirmed the degraded days should be dropped rather than used.

### 2.9 The held-out test has not been run
Nine training names: NVDA, MSFT, AAPL, TSLA, LLY, SPY, QQQ, XLV, USO.
Eight held out and **never yet read**: GOOGL, AMZN, META, AVGO, BRK.B, IWM, GLD, VXX.
The holdout is still sealed. Tune on the nine, then prove once on the eight,
against the frozen success bar in D-108. One shot. Do not peek.

### 2.10 The two option-exit arms are untested
D-109 preregisters two exit styles: sell most contracts at +20% and the last at
+100% or breakeven stop; or the same with a 15% trailing stop on the last contract
once past +20%. Neither has been tested. Testing them needs option quotes that
have not been bought.

### 2.11 Budget
Databento authority is $60 total. $22.47 spent, **$37.53 left**. Targeted option
quotes run about $0.41 per name-day, so roughly 90 name-days fit in what remains.
Buy only the specific days and strikes the signals pick, after they exist.

### 2.12 The box is small — keep long runs bounded
7.7 GB RAM, 4 cores, **no swap**. Keep both bot programs running because the
controller treats either one stopping as a health failure. The three offline shard
units are each capped at one CPU and 1.7 GB.
Also watch `archives/storage-manager/manager.py scan` in the builder directory — it
was observed pinning a whole core while the count run needed it. Nobody has checked
what schedules it or whether it needs to run that often.

## 2.13 MANDATORY before any long run — the 2% gate (D-116)

Do not start a count run, sweep or backtest without running the 2% sample first.
It takes minutes; a full run takes hours, and D-115 proved a full run can finish
"successfully" while measuring only four of the nine names.

    cd /home/openclaw/.openclaw/workspace
    PYTHONPATH=. python3 /root/trade-alerts-builder/m91_sample_gate.py

It prints usable moments **per ticker** and **per adapter**, never one combined
total, and **exits non-zero** if any assigned ticker or any adapter scores zero.
A non-zero exit means stop and fix — do not start the full run.

Why it matters: the reported 44% success rate was four ETFs at 100% and five
stocks at exactly zero, averaged together. A combined total launders a hole; a
per-ticker split makes it obvious at a glance. Zero is a failure, not a result.
The contract tests all passed while this bug was live — they check the code does
what it says, not that the run measured what it was told to.

## 2.14 The 2% gate passed on 2026-09-20 Pacific
The gate now reads the real session field, passes the instrument mapping through
the shared count path, and checks every ticker against every expected called
adapter. It returned 1,386 usable readings for each of the nine names and 4,158
for each expected adapter path. Observed memory was about 178 MB.

## 2.15 M9.1BT acceptance blocked by protected-file change

The controller's saved acceptance result has `exit_code: 0`, `stable: true`,
`artifacts: true`, but `protected: false`. Its reported error was
`acceptance verification failed`. This means its protected-file fingerprints
changed during that run; it is not a reported failing test. The saved result
does not identify the changed protected path or its writer. Do not guess either,
change protection, or repeat the same run without resolving that outside gate.
`M9_1BT_DIAGNOSIS.json` preserves both published phases and their exact figures.
The existing shared count-path edits are preserved and need fresh controller
proof; the old test output does not establish acceptance of today's full delta.
The full count output is still absent. ROADMAP carries the blocked row and the
conditional M9.1BU continuation; no long job was launched in this diagnosis.

## 3. Traps that will cost you hours if you do not know them

1. **Never edit any file in the workspace while a review is pending.** The
   controller hashes the file list before review; any edit gives
   `source changed before review`. Check the stage first. This cost time twice in
   one day.
2. **Any git operation trips the tamper alarm**, because the controller
   fingerprints files under `.git`. A commit is enough. Harmless, but you must
   clear it and re-snapshot.
3. **The honest way to force a rebuild** is to write the real reasons into
   `review_issues` in `state.json` and set `stage` to `build`. Do not edit
   `state.json` any other way, and never reopen an accepted milestone.
4. **`READY.json` is a hash gate.** Edit anything it covers (BUILD.md, REVIEW.md,
   the controller, the schema, the test files) and `buildctl start` refuses until
   it is re-sealed.
5. **`buildctl` takes exactly one word**: status, start, pause, resume, stop.
6. **OPRA parent symbology drops the dot**: `BRKB.OPT`, not `BRK.B.OPT`.
7. **EQUS.MINI carries roughly one fifth of the full tape.** Absolute share-volume
   thresholds are not comparable across feeds. Bars are stamped at bar START.
8. **Never launch a long job from inside an agent session.** Start the three
   `trade-alerts-offline-count@.service` shards so systemd owns them. See D-114.
9. Databento prices arrive as integers scaled by 1,000,000,000. The loader divides
   before any adapter sees them, so adapter-level prices are plain dollars per share.

## 4. Decisions on file
D-101 to D-113 in `DECISIONS_AND_OPEN_QUESTIONS.md`. Most recent:
- **D-112** — which retained files may be read, which tickers, which conventions.
- **D-113** — the unit labels: `price = "USD_PER_SHARE"`, `volume = "SHARES"`.
  This corrects D-112, which wrongly used `"TRADE"` for both and caused the empty
  count run described in 2.4.

## 5. Standing constraints
No live activation. No broker, Discord or provider live calls. No orders. No
deployment. No bot restarts. No new strategy rules without an owner decision on
file. All switches stay off. Credentials never appear in command arguments; the
Databento key is read from `/root/.openclaw/.env`, and any new key must exist in
both `.env` and `.env.service`. Never claim a milestone complete when it is not.
