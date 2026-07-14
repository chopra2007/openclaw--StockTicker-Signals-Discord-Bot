# Feature menu — the researched ideas, and what happened to each

**Status:** ONGOING — work the tiers top-down; closes only when every idea is BUILT or PASSED
**Created:** 2026-07-14
**Last full code re-verification:** 2026-07-14 (every open idea grepped against the live code)

**CURRENT STATUS (2026-07-14):** **All 113 ideas from the July run are now individually accounted for
in this file** (see **FULL ROSTER** at the bottom — every idea, by name, with its verdict). The split:
**17 BUILT · 6 ALREADY LIVE · 3 KILLED · 74 PASSED · 14 OPEN.**

**Only the 14 OPEN ones are candidates**, and they are sorted **strongest first, in four tiers**, so a
session starts at the top and works down. The other 99 are closed — nothing already built or already
passed on appears in the candidate tiers. Re-verified against the live code, not against the discover
run's artifacts.

*(Arithmetic: 17 + 6 + 3 + 74 + 14 = 114 = the 113 numbered ideas + the one killed idea that was never
given a number. Checks out — see the roster's footnotes.)*

**Were the 74 rejected on merit, or did we just run out of build budget? Verified 2026-07-14 — MERIT,
not resources.** A capacity cap *did* exist (pass-2 kept only the **top 7** and logged 24 ideas as
"filtered due to capacity"), **but the later merit pass rescued all 24** — they are now **13 BUILT,
9 OPEN, 2 KILLED, and 0 PASSED**. Nothing was dropped for lack of resources and left there. **However,
the 74 are not equally dead: 48 are firm** (13 hard-no — the data doesn't exist / is proven no-edge /
fights the project's own rules; 30 redundant; 5 out of scope) **and 26 are SOFT** — 22 are "low
value / secondary" **judgment calls that were never proven unworkable**, and **4 were dropped with no
reason ever written down** (c31 Hidden Markov regime · c41 institutional-vs-retail put/call · c47
signal-to-noise dashboard · c95 EIA oil & gas). **Those 26 are the reserve pool** if the 14 open
candidates run out — cheaper to reopen than to pay for a fresh research run. **And one PASSED idea's
reason has already expired: c102 (short-alert squeeze-risk guard)** was rejected *only* because it
needed the short-interest leg, **which has since shipped** — it is the most promotable idea in the
PASSED bucket.

**One idea was removed from the candidate list this pass:** *EPS-estimate revisions momentum* was
listed as an open candidate. **It is already built and live** (`features.snapshot.eps_revisions: true`,
`consensus.yaml:811` — it prints `EPS rev 34↑ 3↓ (30d)` on the `!all` card). Moved to BUILT. Building
it would have been pure waste.

**The trap this file exists to prevent:** the discover artifacts say
"survived_killtest_not_built_this_run". That means *the July run didn't build it* — **NOT** *the bot
lacks it*. Some of those ideas were already in the code, or landed later by another route. **Never
promote an idea to "ready to build" from the artifacts alone. Grep the live code first.**

---

## How to use this

1. **Start at TIER 1 and work down.** Within a tier, order does not matter — pick any.
2. **Before you build: grep the live code for it anyway.** The verdicts below were true on
   2026-07-14. Code moves. A 2-minute grep beats a wasted build.
3. Build it under the normal rules — flag OFF, real-data test, regression baseline, separate verifier.
4. **Write the verdict back here** — `BUILT` (with the flag name) or `PASSED` (with the reason), and
   move the row down into the BUILT or PASSED section. **A row must never sit in two places.**
5. An idea you decide against is `PASSED`, not deleted. The reason is the whole point: it stops the
   next session, and the next research run, from proposing it again.

**The list is exhausted when all four tiers are empty.**

---

# TIER 1 — STRONG. Build these first. (3 open)

Cheap, the groundwork already exists, and the user sees the result.

### T1-a · "N of M sources" footer  *(what's left of idea #2)*
- **What the user would see:** the footer changes from `Sources: 4` to `Sources: 4 of 9` — you finally
  know whether 4 sources agreed out of 5 that looked, or out of 30.
- **Already live:** the 0–100 score itself. `features.single_score.enabled: true`
  (`consensus.yaml:871`), rendered in every alert (`alerts/discord.py:390-402`). **Do NOT build a
  second score.**
- **The actual job:** the footer prints a bare count — `f"Sources: {sources_count}"`
  (`alerts/all_command/embed.py:1129-1134`). Add the denominator (sources *attempted*, not just the
  ones that fired). **~20 lines.** Cheapest win on the whole menu.

### T1-b · VVIX "fear-of-fear" gauge  *(idea #1)*
- **What the user would see:** a read on whether the market is nervous *about its own nervousness* —
  an early-warning line, descriptive only.
- **Already live:** the VIX/VIX3M term-structure leg (`analysis/cross_asset.py:15`), whose yfinance
  fetcher (`cross_asset.py:129-148`) is a **drop-in template** — adding `^VVIX` is a small extension of
  code that already works. Zero `vvix` hits repo-wide, so the gauge itself is genuinely absent.
- **Don't invent it — port it.** A working VVIX-residual implementation already exists in the sibling
  project `volatility_regime_reversal_indicator/` (`backtest/phase2.py`, `leg_vvix_residual_high`).
- **Hard constraint:** it must be the *residual* vs the existing VIX leg, and **descriptive only —
  never an alert gate.** Gating on it re-creates the VIX predictor already rejected in #47.
- Study: `.claude/discover/next-features-jul2026/VVIX-RESEARCH-FINDINGS.md`

### T1-c · Watchlist-wide sweep command  *(idea #27, renamed)*
- **What the user would see:** one command that scans the *whole* watchlist on demand and surfaces the
  quiet names the poll never mentions.
- **⚠️ DO NOT name it `!scan`.** `!scan` is **already a live, documented command**
  (`alerts/commands.py:406-411`) — it takes explicit tickers, capped at 5. Naming this `!scan` would
  silently clobber it. **Call it `!sweep` or `!universe`.**
- **The real gap:** a watchlist-wide sweep exists only as a **background loop** (`main.py:474-481`),
  never as something you can ask for. No on-demand whole-watchlist command exists in the dispatch table
  (`commands.py:397-578`).
- **Reusable skeleton:** the enqueue-all-tickers loop in `research/atlas.py:131-163`.

---

# TIER 2 — SOLID. Real work, real payoff. (4 open)

### T2-a · Hedge-vs-directional options-flow discount
- **What the user would see:** the bot stops treating a protective hedge as a real directional bet.
- **Verified absent:** zero hits for `hedge` / `protective` / `collar` / `covered` anywhere. Flow is
  classified only by **side and size** — sweep = volume/OI ≥ 5 (`scanners/options.py:22,49-53`),
  dominant side by premium (`options.py:83-137`). A protective put on a long book and an outright
  bearish bet are **indistinguishable to the current code**.
- **Head start:** the Greeks are *already fetched* from Schwab (delta/gamma/theta/vega,
  `scanners/schwab_client.py:329,339`) — but delta is used only for the 25-delta skew basis
  (`options.py:849-873`), never to judge direction.
- **The job:** leg-pairing / multi-leg detection, delta-weighted notional, then a discount applied to
  `options_pts`. This touches a **live instant-trigger** signal, so it needs a shadow log before it
  changes real alerts.

### T2-b · Generalize the crowding guard + flip `social_family_dedup` on
- **What the user would see:** three retail sources shouting the same thing stop counting as three
  independent votes.
- **Already live (two narrow guards):** `analysis/wolf_confluence.py:516-518` (each independence bucket
  casts one net vote) and `analysis/herding.py` (a **real measured pair-correlation discount** on
  analyst clusters — `effective_size = raw_count − Σ co_post_rate`, proven by
  `tests/test_analyst_herding.py::test_correlation_discount_reduces_effective_size`).
- **Built but switched OFF:** `social_family_dedup` (`consensus.yaml:870`) collapses
  ApeWisdom/StockTwits/Reddit into one `retail_crowd` vote (`cross_reference.py:237-253`). Demotion-only
  and byte-identical when off.
- **The job is "generalize + switch on", not "build".** Independence is enforced in three disconnected
  places, and the only one touching the general score breakdown is off. Flipping it needs the
  blast-radius measurement on `decision_snapshots` that the config comment itself demands (that flip is
  #67 work — **coordinate, don't duplicate**).
- *(A previous verification pass wrongly called the correlation discount a never-applied stub — it had
  misread `_record_swarm_history`, a separate logging function. The discount is real. Verify before
  believing a claim like that, including one of mine.)*

### T2-c · Brier-score / calibration automation
- **What the user would see:** a regular, readable "how well-calibrated was the bot?" report — today
  **nobody ever sees these numbers** unless a human runs a CLI by hand.
- **Already live:** the metrics library (`eval/metrics.py:28` `brier_score`, `:40` `base_rate_brier`,
  `:64-74` reliability bins); the live calibration model retrains on every engine start
  (`analysis/calibration.py`, `main.py:971-979`); and the 2-daily auto-flip gate already *consumes*
  Brier (`/root/task_system/scripts/auto_flip_check.py:310-311`).
- **The gap is only the report + the sink:** `python -m consensus_engine.eval` is **manual-only** — no
  cron, no systemd timer, no Discord surface.
- **The job:** schedule it and give it somewhere to land. Small.

### T2-d · Analyst price-target disagreement (spread)
- **What the user would see:** "analysts are unusually split on this name."
- **Already live:** the targets themselves. `scanners/snapshot.py:207-209` fetches mean/high/low, and
  `all_command/embed.py:551-555` already renders `🎯 $215 avg ($180–$260) · 58 analysts`.
- **Genuinely absent:** the derived statistic — zero hits for `target_spread` / `pt_dispersion` / any
  `(high−low)/mean`.
- **The honest catch:** to say a spread is *unusually* wide you need a **stored history of spreads,
  which does not exist**. So this is **"start logging now, build the signal later"** — not a quick win.
  (An earlier note in this file wrongly called it "the cheapest thing to build". It isn't — T1-a is.)

---

# TIER 3 — HEAVY or GATED. Strong ideas, big builds. (4 open)

### T3-a · SEC XBRL fundamentals feed
- Real company financials (`data.sec.gov/api/xbrl/companyfacts`) as a **new data class**. Free.
- **Verified absent:** SEC code touches only the filings/submissions JSON (`scanners/sec_edgar.py:85`);
  zero hits for `xbrl` / `companyfacts` / `frames`. Today's fundamentals are a thin **yfinance**
  one-liner (PEG / revenue growth / margin / beta — `snapshot.py:266-291`), **not persisted, not
  scored**. No financials table exists in the schema.
- **Why heavy:** needs a client, a normalized model + table, persistence, and a consumer. Strong idea —
  size it honestly.

### T3-b · FOMC hawk/dove statement reader
- Read the Fed statement and say whether it turned hawkish. Rated "high potential", but a heavy LLM build.
- **Verified absent:** FOMC exists only as a **static date list** used for an alert blackout
  (`data/macro_events.yaml:5-11` → `analysis/contradiction.py:24-72`). Zero hits for `hawkish` /
  `dovish` / statement-reading anywhere.

### T3-c · Backtest-to-live decay tracker
- Warn when a signal that backtested well starts failing live.
- **Verified absent:** per-signal live grading exists (nightly `flow-grading.timer`, analyst/Wolf
  graders, shared BHAR spine `analysis/benchmark_grading.py`) and backtests exist as one-shot scripts —
  but **nothing stores a baseline, compares it to a rolling live number, or alerts on decay.** The
  auto-flip engine is **one-directional**: it flips flags *on* when evidence earns it; there is no
  un-flip path.
- **Gate:** value grows with outcome data — worth more once #73's soak fills in.

### T3-d · Learned (continuous) signal weights
- Let the bot learn which signals deserve more weight.
- **Its old gate is gone:** this was listed as "needs the 0–100 score first" — **the score is already
  live and ON.** That blocker no longer applies.
- **What already exists:** a per-analyst learned weight (Wilson-LB on track record, `db.py:1643-1673`,
  fed nightly) — but it changes **zero alerts today** because `scoring.analyst_accuracy_weight.enabled:
  false` (`consensus.yaml:62-68`). An offline `logistic_challenger` already fits real coefficients with
  a ticker embargo (`eval/report.py:286-366`) — but **they are never persisted or used at inference.**
  The 2-daily auto-flip tuner only flips booleans on/off; it never writes a continuous weight.
- **The real job:** persist the challenger's coefficients and let them re-weight the score. **The real
  gate is outcome-data volume**, not the score.

---

# TIER 4 — WEAK. Recommend PASS. (3 open)

Read the catch, then either PASS it with that reason or overrule me deliberately. Do not build one of
these just because it is on the list.

| Idea | The catch that makes it weak |
|---|---|
| **Market-wide put/call ratio** (#11) | **The obvious free source is dead.** The CBOE equity put/call CSV has been **stale since Oct 2020** (recorded in `plans/discovery-2026-04-24/31-critique-feasibility.md:222`). Per-ticker put/call already exists (`scanners/options.py:127`). It also overlaps E2's market-regime multiplier. **Beware a stale doc:** `TODO.md:302` claims a timer "keeps logging CBOE put/call" — that collector lives in a **different project** and feeds nothing here. No proven free source ⇒ no build. |
| **CFTC Commitments of Traders** (#21) | Free, but **weekly and lagged, and futures-only** — awkward for a 15-minute per-stock bot. Codex dissented ("too slow/macro"). Descriptive view at best. |
| **GDELT global news tone** (#24) | **The repo's own research already shelved it** — scored **bottom-30%** in `plans/discovery-2026-04-24/20-candidate-features.md:554`. Very noisy, weak per-ticker attribution, big filtering build. The curated SerpAPI/RSS/Brave news already in the bot is sharper. |

---

# CLOSED — not candidates. Do not propose these.

## BUILT — 17

**16 from the July 2026 run, all shipped flag-OFF.** Turning them on is **#67**, not this item.

| # | Idea | Flag |
|---|---|---|
| 4 | Dealer gamma (GEX) map | `features.dealer_gamma.enabled` |
| 5 | Gamma-flip price level | `features.dealer_gamma.enabled` |
| 7 | Cheap-vs-rich volatility flag | `features.iv_rv_tag.enabled` |
| 8 | CBOE SKEW tail-risk gauge | `features.skew_index.enabled` |
| 9 | Volatility squeeze (coiling) | `features.vol_squeeze.enabled` |
| 10 | IV skew (puts vs calls) | `features.iv_skew.enabled` |
| 12 | Options pinning (OI concentration) | `features.oi_pinning.enabled` |
| 14 | Congressional trading tracker | `features.congress_trades.enabled` *(House only — Senate deferred, site is gated)* |
| 15 | SEC Form 144 (intent to sell) | `features.form144.enabled` |
| 16 | Rule 10b5-1 plan scanner | `features.insider_10b5_plans.enabled` |
| 17 | FINRA short interest + days-to-cover | `features.short_interest.enabled` |
| 18 | Trading-halt tripwire | `features.trading_halts.enabled` |
| 20 | Market breadth | `features.market_breadth.enabled` *(RSP/SPY proxy — true advance/decline deferred, no free source)* |
| 22 | Financial Conditions Index (NFCI) | `features.cross_asset.nfci_leg_enabled` |
| 23 | Yield curve + dollar + real yields | `features.cross_asset.macro_legs` |
| 26 | Post-earnings drift (PEAD) | `features.pead.enabled` |

**+1 found already-live during the 2026-07-14 re-verification** — it had been sitting in the candidate
list by mistake:

| Idea | Status |
|---|---|
| **EPS-estimate revisions momentum** | **BUILT AND LIVE.** `features.snapshot.eps_revisions: true` (`consensus.yaml:811`). Prints `EPS rev 34↑ 3↓ (30d)` on the `!all` card (`all_command/embed.py:590-593`) from yfinance's `upLast30days`/`downLast30days` — literally the count of analysts revising **earnings estimates** up/down over 30 days. **This IS the idea, not a proxy.** Distinct from **analyst *rating* momentum** (`Rating trend ▲ 3.82→3.92`, `features.snapshot.analyst_momentum: true`), which is buy/sell **recommendation** drift — different feed, different line, also live. Both are **display-only**; folding them into the score is a *different* job, gated by `scoring.fold_display_signals.enabled: false` (`consensus.yaml:56-61`) — that belongs to #67/#73, not here. |

## ALREADY LIVE — 6. Rebuilding these is wasted work.

VIX/VIX3M term-structure regime · anchored VWAP bands · volume-profile levels · FINRA daily
short-volume · analyst-rating momentum · 13D/13G activist-filing scanner.

## KILLED — 3. Do not re-propose.

| # | Idea | Why it died |
|---|---|---|
| 3 | Max-pain reliability label | **Premise was false.** Max-pain is already shown unconditionally — the `<= 3` in `options.py` is a 3rd-Friday snap tolerance, not a hide-gate. Building "stop hiding it" is a no-op |
| 19 | Dark-pool / off-exchange volume | FINRA publishes it **2–5 weeks late** (probed live). Useless for a 1h/24h alert |
| 13 | 0DTE directional flow imbalance | Signed/aggressor-side flow **does not exist in any free feed**. The buildable version is just the put/call ratio already shipped |

## Were the 74 rejected on merit, or did we just run out of build budget?

**Answered by reading the artifacts on 2026-07-14 — not assumed.** The short answer: **merit, not
resources.** But there is a real wrinkle worth knowing.

**There WAS a capacity cap.** The run's pass-2 ranked the ideas and kept only the **top 7**, logging 24
of them as *"ranked but filtered due to capacity (top 7 cap)"* (`drops-log.md:181`). So at one point
the list really was cut for want of build budget, not merit.

**But a later merit pass rescued every one of them.** `merit-triage.md` ("read every idea, drop
redundant/useless") re-reviewed all 113 and restored the capacity-cut ideas — it even labels 20 of them
*"New free-data signals that just missed the cap"*. Where those 24 stand today:

| Capacity-cut in pass-2 | Where they are now |
|---|---|
| 24 ideas | **13 BUILT · 9 OPEN (in the tiers above) · 2 KILLED on evidence · 0 PASSED** |

**Not one capacity-cut idea sits in the PASSED bucket.** Nothing was dropped for lack of resources and
left there. (Verify: the 24 are c81 c111 c4 c113 c9 c19 c44 c8 c25 c28 c42 c20 c66 c65 c7 c59 c46 c88
c92 c86 c12 c91 c32, plus the un-numbered 0DTE idea.)

### But the 74 are not all equally dead

They were rejected for four different strengths of reason. **Two of these buckets are soft** — if you
ever want more candidates, reopen them there, not by running a new research pass.

| Bucket | Count | Firmness |
|---|---|---|
| **A. Hard no** — the data doesn't exist, is proven no-edge, or it fights your own rules (e.g. Google Trends = fragile scraper + ToS risk; 13F = 45-day lag; sector rotation = already proven no-edge; confirmation-only gates conflict with the instant-trigger philosophy) | 13 | **Firm. Don't reopen.** |
| **B. Redundant** — already covered by something built or by a kept idea (e.g. c70 hedge-flow classifier is a duplicate of the open c12; c24 RV/IV spread *is* the cheap/rich-vol flag) | 30 | **Firm** — but only as long as the thing that covers it stays. |
| **C. Out of scope** — the bot is alert-only (position sizing, portfolio P&L, per-user subscriptions), or an ops/governance nicety | 5 | **Firm** unless the bot's scope changes. |
| **D. Judgment call** — "low value", "secondary", "marginal", "premature". **Nothing here was proven unworkable — a human just ranked it below the others.** | **22** | **SOFT. Reopen freely.** |
| **E. No reason was ever written down** — the artifacts record the drop but not why: c31 Hidden Markov regime detector · c41 institutional-vs-retail put/call divergence · c47 signal-to-noise dashboard · c95 EIA oil & gas inventories | **4** | **SOFT — and unverified.** These were never actually justified. |

**So: 48 of the 74 are firmly dead (A+B+C). 26 are soft (D+E)** — judgment calls and four ideas nobody
ever gave a reason for. That is your real reserve pool if the 14 open candidates run out.

**One PASSED idea's reason has already expired:** **c102 (short-alert squeeze-risk guard)** was rejected
only because it *"depends on the short-interest leg landing first"* — and that leg has since **shipped**
(c9). Its blocker is gone. It is the single most promotable idea in the PASSED bucket.

---

## PASSED — 74 rejected in the July run, with reasons

Clustered as: overlaps a kept idea; conflicts with the project's own rules (confirm-gates fight the
instant-trigger philosophy; 8-Ks never trigger standalone); out of scope (position sizing, portfolio
P&L — the bot is alert-only); dead-end data (sector/factor rotation, already proven no-edge; pytrends,
fragile); ops niceties (health dashboards, provenance tags).

**Read the reasons before proposing anything "new" that sounds like one of these.**

### The count is 113, not 115 — and the artifacts lie about it

Verified by direct count 2026-07-14. The idea IDs run `c1`–`c115`, **but `c58` and `c82` were never
written and `c97` appears twice.** So the ID space is 115 wide and holds **113 real ideas**.
Cross-checked independently: `drops-log.md` has 106 entries + `pass-2-filtered.md` keeps 7 = **113**.
And `merit-triage.md`'s own arithmetic checks out: 27 + 7 + 79 = 113.

**Do not trust these artifact headlines — they are wrong:**
- `feature-ideas-list.txt` claims "Total: 115 candidate ideas" and "106 / 115 dropped", but actually
  lists 40 keeps and 48 drops under a completely different taxonomy. **This file is self-inconsistent
  in two directions and is where the phantom "115" comes from. Disregard its numbers.**
- `pass-1-candidates.md`'s ten section headers declare 139 candidates between them but contain 114
  headings. *Every* section header overstates its own contents.
- `drops-log.md`'s header says its input was the 32-item menu; it actually logs `c#` IDs from the
  113-item list.

**`merit-triage.md` is the one artifact whose numbers hold up.** Cite it, not the others.

- `.claude/discover/next-features-jul2026/merit-triage.md` — the 27 strong + 7 conditional, plain English
- `.claude/discover/next-features-jul2026/PASS-1-FEATURE-MENU.md` — 32 ideas with fuller write-ups
- `.claude/discover/next-features-jul2026/pass-1-candidates.md` — the full 114-idea vault (includes
  ideas that never made the shortlist: Fed-calendar overlay, 8-K surprise scanner, 13F institutional
  holdings, per-alert paper-trade P&L, alert-volume circuit breaker, `!health` dashboard)
- `.claude/discover/next-features-jul2026/pass-3-killtest-report.md` — the kill-test verdicts
- `.claude/discover/next-features-jul2026/outcome.json` — the machine ledger of the run

---

# FULL ROSTER — all 113 ideas, one line each

Every idea the July 2026 run produced, by name, with what happened to it. **This is the master list.**
The clusters above are the working view; this is the audit trail. Extracted from `merit-triage.md`,
`drops-log.md` and `pass-2-filtered.md` on 2026-07-14.

**Status key:** `OPEN` = a candidate, tier shown · `BUILT` = shipped (flag off unless noted; turning on
is #67) · `LIVE` = already in the bot before the run · `KILLED` = premise disproven, never re-propose ·
`PASSED` = rejected with the reason given.

| ID | Idea | Status | Verdict / reason |
|---|---|---|---|
| c1 | VVIX "fear-of-fear" gauge | **OPEN — T1-b** | Is the market nervous about its own nervousness |
| c2 | VIX/VIX3M calm-vs-panic term structure | LIVE | Already in the cross-asset regime code |
| c3 | Dealer gamma (GEX) map | BUILT | `features.dealer_gamma.enabled` |
| c4 | IV skew: puts vs calls | BUILT | `features.iv_skew.enabled` |
| c5 | Machine-readable buy/sell tags on alerts | PASSED | Overlaps shipped decision-first alerts; nothing downstream would use the tags |
| c6 | Short-end VIX9D term-structure leg | PASSED | Minor extension of existing term structure; marginal once VVIX covers vol-of-vol |
| c7 | Yield curve, dollar, real yields | BUILT | `features.cross_asset.macro_legs` |
| c8 | Market-wide put/call ratio | **OPEN — T4** | Recommend PASS: its free CBOE source has been dead since Oct 2020 |
| c9 | FINRA short interest + days-to-cover | BUILT | `features.short_interest.enabled` |
| c10 | Treasury/FOMC event-risk overlay | PASSED | FOMC and CPI dates already ingested; the staleness add-on is thin |
| c11 | Max-pain reliability label | **KILLED** | Premise false — max-pain is already shown unconditionally |
| c12 | Hedge-vs-directional flow discount | **OPEN — T2-a** | Tell a protective hedge apart from a real bet |
| c13 | Monthly alert hit-rate self-audit | PASSED | Hit-rate and false-positive tables already exist; only the schedule is new |
| c14 | Three-tier alert severity | PASSED | Decision-first alerts already prioritize; delivery tiers are secondary |
| c15 | Cool-down before high-severity alerts | PASSED | Conflicts with the instant-trigger rule for insider and flow alerts |
| c16 | Backtest-overfitting guard checklist | PASSED | Subsumed by the decay tracker and walk-forward; a checklist, not code |
| c17 | Options flow as confirmation only | PASSED | Directly conflicts with the unusual-flow instant-trigger exception |
| c18 | Retire ignored alert types | PASSED | Near-duplicate of the alert-monitoring cluster; secondary ops |
| c19 | Congressional trading tracker | BUILT | `features.congress_trades.enabled` *(House only — Senate site is gated)* |
| c20 | Dark-pool / off-exchange volume | **KILLED** | FINRA publishes it 2–5 weeks late — useless for a 1h/24h alert |
| c21 | Cheap-vs-rich volatility flag | BUILT | `features.iv_rv_tag.enabled` |
| c22 | ETF fund-flow anomaly detector | PASSED | No confirmed free flow source; re-approaches the sector-rotation dead end |
| c23 | Explicit 0–100 score | **OPEN — T1-a** | **The score itself is already LIVE and ON.** Only the "N of M sources" footer is left |
| c24 | Realized-vs-implied vol as move-confidence weight | PASSED | Subsumed by the cheap/rich-vol flag — same implied-minus-realized spread |
| c25 | Options pinning probability | BUILT | `features.oi_pinning.enabled` |
| c26 | Kelly position-size suggestion | PASSED | Position sizing is outside the alert-only scope; edge estimates too noisy |
| c27 | Cross-ticker correlation-break detector | PASSED | Secondary; peer relative-strength already separates stock-specific moves |
| c28 | Post-earnings drift (PEAD) | BUILT | `features.pead.enabled` |
| c29 | 12-1 month momentum rank | PASSED | Factor work already proven no-edge on free daily data |
| c30 | Amihud illiquidity confidence discount | PASSED | Minor confidence tweak; overlaps the liquidity-gate family |
| c31 | Hidden Markov regime detector | PASSED | Reason not recorded in the artifacts |
| c32 | Automated Brier calibration report | **OPEN — T2-c** | The maths already exists; nobody ever sees the numbers |
| c33 | GARCH volatility cross-check | PASSED | Heavy model for marginal gain over the cheap/rich-vol leg |
| c34 | Social message-volume spike detector | PASSED | Incremental attention proxy; StockTwits and ApeWisdom trending already ingested |
| c35 | Overnight gap-fill probability model | PASSED | Niche swing heuristic; lower priority than the options legs |
| c36 | AAII weekly sentiment survey | PASSED | Weekly contrarian survey; secondary low-cadence source |
| c37 | NAAIM manager exposure index | PASSED | Same weekly-survey class as AAII; secondary |
| c38 | Wikipedia pageview attention spike | PASSED | Weak standalone attention proxy |
| c39 | EDGAR full-text 8-K keyword scanner | PASSED | 8-K detection already ships; 8-Ks never trigger standalone alerts |
| c40 | Full VIX-futures term-structure curve | PASSED | Richer than the front curve but heavy to ingest; marginal gain |
| c41 | Institutional vs retail put/call divergence | PASSED | Reason not recorded in the artifacts |
| c42 | CFTC Commitments of Traders | **OPEN — T4** | Recommend PASS: weekly, lagged, futures-only — wrong speed for this bot |
| c43 | Economic Policy Uncertainty index | PASSED | Monthly cadence and noisy; secondary macro source |
| c44 | Trading-halt tripwire | BUILT | `features.trading_halts.enabled` |
| c45 | 13F institutional-holdings change | PASSED | 45-day lag; slower and less valuable than Form 144 or Congress |
| c46 | Backtest-to-live decay tracker | **OPEN — T3-c** | Value grows as outcome data accrues (#73's soak) |
| c47 | Signal-to-noise dashboard per alert type | PASSED | Reason not recorded in the artifacts |
| c48 | Kill-switch auto-pause on divergence | PASSED | Overlaps the decay tracker and per-ticker cooldown; ops layer |
| c49 | Frame alerts as hypotheses | PASSED | A wording tweak; low source quality |
| c50 | Anchored VWAP bands | LIVE | Already in the smart-levels engine |
| c51 | Volume-profile levels | LIVE | Already in the smart-levels engine |
| c52 | Per-alert paper-trade P&L tracker | PASSED | Overlaps the decay tracker and the existing evaluation harness |
| c53 | Daily-vs-weekly trend alignment gate | PASSED | Incremental confluence weight; lower value than the new data legs |
| c54 | VPIN flow-toxicity leg | PASSED | Needs intraday trade data; predictive value disputed; heavy build |
| c55 | Conformal-prediction confidence bands | PASSED | Advanced calibration wrapper; premature |
| c56 | CUSUM change-point detector | PASSED | Complements a regime model that isn't shipped; premature |
| c57 | Turn-of-month / day-of-week seasonality | PASSED | Descriptive footnote; low impact |
| c59 | Learned signal weights | **OPEN — T3-d** | Its old gate (needs the 0–100 score) is **gone** — the score is live. Real gate is outcome-data volume |
| c60 | EPS-estimate revision momentum | **BUILT** | **Found already LIVE 2026-07-14** — `features.snapshot.eps_revisions: true`. Was wrongly listed as a candidate |
| c61 | Implied-vs-realized correlation (dispersion) | PASSED | Needs component-vol aggregation; heavy build for a niche regime tag |
| c62 | Headline-vs-filing sentiment divergence | PASSED | Requires both text pipelines to be mature; secondary |
| c63 | FINRA daily short-sale volume | LIVE | Already built |
| c64 | Finnhub earnings beat-streak | PASSED | Overlaps post-earnings drift; secondary |
| c65 | Financial Conditions Index (NFCI) | BUILT | `features.cross_asset.nfci_leg_enabled` |
| c66 | Market breadth (advance/decline) | BUILT | `features.market_breadth.enabled` *(RSP/SPY proxy)* |
| c67 | Crypto risk-on/off leg | PASSED | Crypto-equity link decouples for long stretches; low source quality |
| c68 | Analyst rating momentum | LIVE | Already built (`Rating trend ▲ 3.82→3.92`) |
| c69 | 13D/13G activist-stake scanner | LIVE | Already built |
| c70 | Hedge-vs-directional flow classifier | PASSED | **Duplicate of c12** (which is OPEN at T2-a) |
| c71 | Signal half-life / decay monitor | PASSED | Overlaps c46, the decay tracker |
| c72 | Signal-crowding guard | **OPEN — T2-b** | Two narrow guards already live; job is generalize + switch on |
| c73 | Favorable-regime-only backtest guard | PASSED | Subsumed by walk-forward validation |
| c74 | Flow-specific 2% sizing note | PASSED | Sizing is outside the alert-only scope |
| c75 | Dynamic performance-based reweighting | PASSED | Premature before static and learned weights exist |
| c76 | Walk-forward validation discipline | PASSED | Methodology folded into c59, learned weights |
| c77 | Standard shadow-mode framework | PASSED | Shadow patterns already exist; generalizing them is an ops refactor |
| c78 | `!health` latency dashboard command | PASSED | Existing drift/health alerts plus `--status` cover the core |
| c79 | Per-user watchlist subscriptions | PASSED | Personalization feature; secondary to signal work |
| c80 | Premium-size-tiered flow classification | PASSED | The sweep detector already carries a size threshold |
| c81 | CBOE SKEW crash-insurance index | BUILT | `features.skew_index.enabled` |
| c83 | Gamma-flip price level | BUILT | `features.dealer_gamma.enabled` |
| c84 | Relative Rotation Graph sector momentum | PASSED | Sector rotation already proven no-edge on free daily data |
| c85 | Realized-vol percentile cone | PASSED | Expected-move footnote; overlaps the cheap/rich-vol context |
| c86 | Rule 10b5-1 plan scanner | BUILT | `features.insider_10b5_plans.enabled` |
| c87 | FOMC hawk/dove statement reader | **OPEN — T3-b** | High potential, but a heavy language-model build |
| c88 | Analyst price-target disagreement | **OPEN — T2-d** | Targets already on screen; needs spread history logged first |
| c89 | Quad-witching / OpEx-week overlay | PASSED | Narrower variant of seasonality; low impact |
| c90 | Options bid-ask spread deterioration gate | PASSED | Data-quality gate; overlaps the liquidity family |
| c91 | GDELT global news tone | **OPEN — T4** | Recommend PASS: the repo's own research already scored it bottom-30% |
| c92 | SEC Form 144 intent-to-sell | BUILT | `features.form144.enabled` |
| c93 | Google Trends search-volume leg | PASSED | Fragile unofficial scraper; terms-of-service risk |
| c94 | SEC XBRL fundamentals feed | **OPEN — T3-a** | Strong new data class, but a large build |
| c95 | EIA weekly oil and gas inventories | PASSED | Reason not recorded in the artifacts |
| c96 | Census advance retail-sales leg | PASSED | Sector-narrow; the release dates are already tracked |
| c97 | OpenSecrets lobbying-spend leg | PASSED | Noisy leading indicator; low source quality. *(This ID is duplicated in the artifacts — counted once.)* |
| c98 | USASpending federal contract awards | PASSED | Narrow to government-contractor names; secondary |
| c99 | BLS JOLTS labor-market leg | PASSED | Monthly macro; NFCI and yield/dollar legs already cover the backdrop |
| c100 | FINRA TRACE corporate-bond credit leg | PASSED | Single-name bond data is sparse and heavy to integrate |
| c101 | Crowded-trade monitor across tickers | PASSED | Overlaps c72, the crowding guard |
| c102 | Short-alert squeeze-risk guard | PASSED | Useful, but depended on the short-interest leg — which has since shipped (c9). **Worth a re-look if you ever want a 15th candidate** |
| c103 | Co-pilot human-confirm toggle | PASSED | Workflow change; secondary to signal features |
| c104 | Daily alert-volume circuit breaker | PASSED | Overlaps the alert-fatigue control cluster |
| c105 | Regime-shift disclaimer banner | PASSED | Low source quality; overlaps the decay tracker's surfacing |
| c106 | Backfilled-data provenance tag | PASSED | Data-governance nicety; low impact |
| c107 | Pre-deploy drawdown-simulation gate | PASSED | Overlaps the decay tracker and walk-forward guards |
| c108 | Single-ticker error blast-radius cap | PASSED | The poll loop likely already isolates per-ticker faults; a hardening task |
| c109 | Score-version pinning and rollback | PASSED | Config/ops versioning, not a signal |
| c110 | Social-engagement scoring firewall | PASSED | Defensive check; reactions very likely don't feed scoring |
| c111 | Volatility squeeze (Bollinger/Keltner) | BUILT | `features.vol_squeeze.enabled` |
| c112 | Per-ticker alert cooldown | PASSED | Overlaps the fatigue-guard cluster; needs mature outcome data |
| c113 | Universe screener across the watchlist | **OPEN — T1-c** | **Must NOT be named `!scan`** — that is a live command |
| c114 | Repeat/stacking sweep detector | PASSED | Incremental refinement of unusual flow |
| c115 | Risk-adjusted snapshot command | PASSED | Reporting nicety; secondary to signal work |
| *(none)* | 0DTE directional flow imbalance | **KILLED** | Signed/aggressor-side flow does not exist in any free feed. Never got an ID — it lived only in the triage file |

### Roster footnotes — the ID gaps are real, not lost ideas

- **`c58` and `c82` have no write-up.** `c82` is referenced nowhere at all. `c58` appears only inside
  `drops-log.md` as *"Kyle's-lambda liquidity sizing gate"*, dropped for *"overlaps the c30/c90
  liquidity family; marginal"* — so it is **PASSED**, and nothing is missing.
- **`c97` is duplicated** in the source artifacts (same OpenSecrets idea listed twice). Counted once.
- **The 0DTE idea never got a number** — it exists only in `merit-triage.md` / the kill-test report.
  That is why the roster has 113 numbered rows but 114 verdicts.
- **Tally:** 17 BUILT + 6 LIVE + 3 KILLED + 74 PASSED + 14 OPEN = **114 verdicts over 113 IDs.**

---

## Related

- **#75** — the loop that generates NEW ideas. Run it when all four tiers are empty.
- **#67** — turning ON the 16 already built. Different job: those need a yes/no, not a build.
- **#6** — the `!all` command's own quality-lever menu (a separate, narrower list).

---

### Session notes — 2026-07-14
- **Worked on:** Regrouped the open ideas strongest-to-weakest into 4 tiers; rostered **all 113** ideas individually (previously the 79 rejected lived only in the discover artifacts as clusters); re-verified every open idea against the LIVE CODE with two search agents.
- **Decisions:** (a) **EPS-estimate revisions momentum was removed from the candidate pool — it is already BUILT and LIVE** (`features.snapshot.eps_revisions: true`); it was the exact trap this file exists to prevent. (b) Verified the **74 were rejected on MERIT, not build budget** — a top-7 capacity cap did exist in pass-2 and cut 24 ideas, but the later merit pass rescued all 24 (now 13 BUILT / 9 OPEN / 2 KILLED / **0 PASSED**). (c) Graded the 74: **48 firm, 26 SOFT** (22 "low value" judgment calls never proven unworkable + 4 dropped with **no reason ever written**: c31, c41, c47, c95) — the 26 are the reserve pool, cheaper to reopen than a fresh #75 run. (d) **c102's rejection has expired** — it was blocked only on the short-interest leg, which has since shipped.
- **Next:** Build **T1-a — the `Sources: 4 of 9` footer** (~20 lines; the 0-100 score is already live and ON, so do NOT build a second score). Then T1-b (VVIX, port from the sibling vol project) and T1-c (watchlist sweep command — **must NOT be named `!scan`**).
