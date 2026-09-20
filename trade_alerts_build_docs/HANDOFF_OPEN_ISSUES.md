# Trade-alert build — open issues and handoff notes

Written 2026-09-19 Pacific for whoever picks this up next, including a non-Claude
agent. Everything here is either verified in the code or taken from the build's own
records. Where something is unverified it says so.

## 1. What this build is and where it stands

The goal is an alert bot that tells the owner to take a trade, and a measured,
honest answer to whether those alerts make money. The owner takes every alert
within 30 seconds; the system, not the owner, decides the thresholds.

54 milestones accepted. The current step is M9.1BM/M9.1BN. What exists: four
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

### 2.4 Only the four ETFs are actually being measured — NEW, most important open bug
The first non-empty count run (D-115, 2026-09-19,
`M9_1BN_RETAINED_COUNTS.json`) returned 76,404 ready moments per adapter out of
171,909 — 44%. Every rejected moment is `INCOMPATIBLE_INSTRUMENT_TYPE`, and the
count is exactly 171,909 × 5/9. Five of the nine names are stocks, so **all stock
moments are being thrown away and only SPY, QQQ, XLV and USO are measured.**
Cause: `open_core17_ohlcv_1m_file` stamped every bar `ETF` by default and took no
per-ticker type, while D-112 correctly calls the five stocks `EQUITY`.

**Half fixed as of 2026-09-19.** The loader now accepts an `instrument_types`
mapping (symbol -> `ETF`/`EQUITY`); it wins over the old default and raises if a
symbol is missing rather than falling back — the right behaviour. **But the count
run does not pass it yet.** `run_retained_counts` calls its opener as
`opener(job_dir, filename)` with no third argument, so every bar still gets the
default `ETF` label and the result above is unchanged. **Next step: thread the
per-ticker mapping through `run_retained_counts` to the opener, then re-run the
count.** Do **not** relabel the stocks as ETFs. Until the re-run lands, any result
is an ETF-only study wearing a nine-name label.
Separately, the `vwap_level` adapter rejects the same 95,505 moments with
`NO_TRADED_SESSION_BAR_YET`; same root cause or not is unestablished.

### 2.4b The count run before that produced no ready moment at all
M9.1BC checked 515,727 decision moments and returned `ready: []`. The cause was a
wrong unit label, now fixed by D-113. The corrected run has not yet completed, so
**nobody has yet seen a non-empty ready count**. Until that lands, treat the whole
adapter chain as unproven end to end on real data.

### 2.5 The build grinds instead of stopping on a repeated blocker
When the builder cannot proceed it writes a *new* sub-step and hits the same wall
again. On 2026-09-19 it repeated an identical blocker nine times (M9.1BE to
M9.1BM), roughly 35 minutes each, about 1.26M tokens, before halting. It should
halt on the first repeat. Not fixed. `controller.py` is the place to fix it.

### 2.6 Nothing tells a human when the build stops
`resume-watchdog.py` auto-resumes only stops it already recognises. Anything else
leaves the build sitting silently. On 2026-09-19 that was a 6h20m silent stall.
No notification exists. Not fixed.

### 2.7 Builder sessions die mid-run
The M9.1BM/BN builder started the real count run, split it into three parallel
processes across the nine tickers, and its session died with no partial output
kept. The controller records this as `builder process failed`. The watchdog treats
it as benign and retries, so it self-heals — but every death throws away the whole
run. Work is not checkpointed.

**Root cause found, 2026-09-19:** the run was launched inside the builder's own
agent session and was never detached, so it died when that session ended. Two
deaths, 2h07m of work lost each time, no partial output. The kernel log shows **no**
out-of-memory kill, so memory was not the cause. **D-114** is the fix: launch long
jobs with `setsid nohup ... </dev/null &`, shard by ticker across three cores, merge
the parts. Helpers: `m91_count_part.py` and `m91_count_merge.py` in
`/root/trade-alerts-builder/`. The work is still not checkpointed — a death still
costs the whole run — so that remains open.

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

### 2.12 The box is small — free it before a long run
7.7 GB RAM, 4 cores, **no swap**. Two services can be stopped when the owner is not
using the bot, freeing about 960 MB: `systemctl stop consensus-engine.service
openclaw-gateway.service`. Restart them before any live or Discord-facing work.
Also watch `archives/storage-manager/manager.py scan` in the builder directory — it
was observed pinning a whole core while the count run needed it. Nobody has checked
what schedules it or whether it needs to run that often.

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
8. **Never launch a long job from inside an agent session.** It dies with the
   session. Use `setsid nohup ... </dev/null &`. See D-114.
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
