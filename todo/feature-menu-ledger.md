# Feature menu — the researched ideas, and what happened to each

**Status:** ONGOING — work the tiers top-down; closes only when every idea is BUILT or PASSED
**Created:** 2026-07-14
**Last full code re-verification:** 2026-07-14 (every open idea grepped against the live code)

**CURRENT STATUS (2026-07-14, run `menu-top10`): ALL FOUR TIERS ARE EMPTY — the menu is EXHAUSTED.**
Every open idea is now either BUILT or PASSED. The split is **25 BUILT · 6 ALREADY LIVE · 3 KILLED ·
80 PASSED · 0 OPEN** (114 total ✓). **The final 5 were built 2026-07-14 (this run), all flag-OFF, each
proved on real data:** F7 short-alert squeeze-risk guard (`short_squeeze_guard.enabled`), F4
hedge-vs-directional flow shadow log (`flow_hedge_discount.collect`), F6 weekly Brier/calibration report
to #errors (`calibration_report.enabled`), F9 SEC XBRL fundamentals on the `!all` card
(`sec_xbrl.enabled`), F10 backtest-to-live decay tracker (`decay_tracker.enabled`). See the BUILT table
for the real output each produced. **Earlier this run:** the 3 TIER-1 builds + the user's drops (FOMC
reader, learned weights, c72/F5 crowding-guard, c88/F8 target-spread, all 3 TIER-4). **Nothing is open.**
To generate NEW ideas, run **#75**; to turn the built-but-off switches ON, that's **#67**.

**There are no candidates left — all 114 are closed** (BUILT / LIVE / KILLED / PASSED). If you need more,
reopen from the SOFT reserve pool (25 ideas, see below) or run #75. Re-verified against the live code,
not against the discover run's artifacts.

**What changed on 2026-07-14 (run `menu-top10`, TODO #76):** a 12-candidate pool (the 11 tiered ideas
+ c102) was cut to 10 by kill-test, then the user chose to build **TIER 1 only** this session. So:
**3 BUILT** (T1-a footer denominator, T1-b VVIX gauge, T1-c `!sweep`) · **2 PASSED** (T3-b FOMC reader,
T3-d learned weights — user accepted both drops) · **c102 promoted PASSED → OPEN** (its blocker shipped).
**The user then dropped five more of the open ideas (2026-07-14):** F5/c72 (crowding-guard generalization
— independent YouTube channels agreeing is confluence, not crowding), F8/c88 (analyst target-spread
logger — a daily logger that mostly re-writes the same numbers), and all three TIER-4 ideas (c8 market-wide
put/call, c42 CFTC COT, c91 GDELT — the user passed on the whole weak tier). **Then, in the same run, the
last 5 open ideas were BUILT** (F7 squeeze-risk guard, F4 flow shadow log, F6 calibration report, F9 SEC
XBRL, F10 decay tracker — all flag-OFF, proved on real data; see the BUILT table + the final session
note). **The menu is now exhausted: 0 OPEN.**

*(Arithmetic: 25 + 6 + 3 + 80 + 0 = 114 = the 113 numbered ideas + the one killed idea that was never
given a number. Checks out — see the roster's footnotes.)*

**Were the 74 rejected on merit, or did we just run out of build budget? Verified 2026-07-14 — MERIT,
not resources.** A capacity cap *did* exist (pass-2 kept only the **top 7** and logged 24 ideas as
"filtered due to capacity"), **but the later merit pass rescued all 24** — they are now **13 BUILT,
5 OPEN, 2 KILLED, and 4 PASSED** (c88/c8/c42/c91, all dropped by the user on merit 2026-07-14 — not
resource cuts). Nothing was dropped for lack of resources and left there. **However,
the 74 are not equally dead: 48 are firm** (13 hard-no — the data doesn't exist / is proven no-edge /
fights the project's own rules; 30 redundant; 5 out of scope) **and 26 are SOFT** — 22 are "low
value / secondary" **judgment calls that were never proven unworkable**, and **4 were dropped with no
reason ever written down** (c31 Hidden Markov regime · c41 institutional-vs-retail put/call · c47
signal-to-noise dashboard · c95 EIA oil & gas). **Those 26 are the reserve pool** if the open
candidates run out — cheaper to reopen than to pay for a fresh research run. *(c102, the short-alert
squeeze-risk guard, WAS the most promotable of these — its expired reason was confirmed on 2026-07-14
and it has been **promoted out of PASSED into the open candidates**, with a build plan already written.
The reserve pool is now 25.)*

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

# TIER 1 — EMPTY. All three were BUILT on 2026-07-14 (run `menu-top10`). ✅

T1-a ("N of M sources" footer), T1-b (VVIX fear-of-fear gauge) and T1-c (`!sweep` watchlist command) are
shipped flag-OFF, each proved on real data — see the **BUILT** table below for the flags and the actual
output each one produced. Nothing to pick here. **Start at TIER 2.**

---


# TIER 2 — EMPTY. All were built or dropped on 2026-07-14 (run `menu-top10`). ✅

All three TIER-2 open ideas are now BUILT (flag-OFF, proved on real data — see the **BUILT** table):
**T2-e / F7** short-alert squeeze-risk guard (`short_squeeze_guard.enabled`), **T2-a / F4**
hedge-vs-directional flow shadow log (`flow_hedge_discount.collect`), **T2-c / F6** weekly
Brier/calibration report (`calibration_report.enabled`). *(T2-b crowding-guard and T2-d target-spread
were DROPPED by the user — reasons in the PASSED section; do not re-propose.)*

---

# TIER 3 — EMPTY. Both open ideas built 2026-07-14; the rest PASSED. ✅

Both TIER-3 open ideas are now BUILT (flag-OFF, proved on real data): **T3-a / F9** SEC XBRL
fundamentals feed (`sec_xbrl.enabled`), **T3-c / F10** backtest-to-live decay tracker
(`decay_tracker.enabled`). *(T3-b FOMC reader and T3-d learned weights were PASSED — reasons in the
PASSED section; do not re-propose.)*

---

# TIER 4 — EMPTY. All three PASSED on the user's call, 2026-07-14. ✅

The user reviewed the three weak ideas and passed on all of them. Reasons are in the PASSED section
below; do not re-propose them.

*(For the record, the catches that made them weak: **Market-wide put/call ratio** — its free CBOE source
has been stale since Oct 2020, and per-ticker put/call already exists. **CFTC Commitments of Traders** —
free but weekly, lagged, and futures-only, wrong speed for a 15-minute per-stock bot. **GDELT global
news tone** — very noisy, can't reliably tell which company an article is about, and the repo's own
research already scored it bottom-30%; the curated SerpAPI/RSS/Brave news already in the bot is sharper.)*

---

# CLOSED — not candidates. Do not propose these.

## BUILT — 25

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

**+3 built 2026-07-14 (run `menu-top10`, TODO #76)** — all of TIER 1, shipped flag-OFF, each proved on
real data before commit. TIER 1 is now EMPTY.

| Idea | Flag | Proof it works (real output, not "code looks right") |
|---|---|---|
| **T1-a · "N of M sources" footer** | `features.sources_denominator.enabled` | Real `!all NVDA`: flag ON → footer `Sources: 21 of 27 attempted`; OFF → `Sources: 21` (byte-identical to the old string). M is `len(_classify_items)` at runtime — the literal 27 appears nowhere in the diff. |
| **T1-b · VVIX fear-of-fear gauge** | `features.vvix_residual.enabled` (+ `collect: true` fills `vol_of_vol_daily` from the daily writer) | Real row written: `2026-07-14, VVIX 93.28, VIX 16.50, residual −0.0257, pct 0.373`. Residual + percentile independently recomputed with `numpy.polyfit` — matched to 4 dp. Renders on `!market` as *"Normal — protection against volatility costs about what the VIX explains."* **Descriptive only**; a test asserts `cross_reference.py` contains neither `vvix` nor `vol_of_vol`, so it can never become the #47 predictor. |
| **T1-c · `!sweep` watchlist command** | `features.sweep.enabled` (max_tickers 15, concurrency 3) | Real sweep of 3: `IBM 82 🟢 · META 55 🔴 · JPM 49 🔴`. **Coherence proved live, twice: `!sweep IBM` = 82 = `!scan IBM` (build session), and an independent verifier re-ran both paths later and got 65 = 65.** The number moves with the market — the point is that the two paths always agree at the same moment. Named `!sweep`/`!universe` — `!scan` is untouched (a test locks both). |

**+5 built 2026-07-14 (run `menu-top10`, TODO #76) — the FINAL five, emptying the menu.** All flag-OFF,
each proved on real data before commit.

| Idea | Flag | Proof it works (real output, not "code looks right") |
|---|---|---|
| **T2-e / F7 · Short-alert squeeze-risk guard** (c102) | `features.short_squeeze_guard.enabled` (data from `short_interest.collect:true`) | New `_compute_squeeze_risk_pts` returns a NEGATIVE capped term (default −4) ONLY on a SHORT signal with a crowded, RISING short (days_to_cover ≥ 3 AND pct_change > 0); on LONG / falling / stale / thin it returns 0. Shares the ONE existing `get_latest_finra_short_interest` read (test asserts exactly one DB call feeds both the r12 bullish leg and this guard). Flag OFF → function never called, breakdown byte-identical. 10 unit tests. **Class C — demotes SHORT alerts, needs a shadow compare of scored shorts before ON.** |
| **T2-a / F4 · Hedge-vs-directional flow classifier** | `features.flow_hedge_discount.collect` (`.enabled` reserved) | SHADOW LOG only. `FlowHit` gained `delta` (Schwab greeks; None on yfinance). New `scanners/flow_hedge.py` `classify()` computes delta-weighted notional + pairs comparable opposite-side legs → `directional` / `paired` / `delta_unknown`, logging one `flow_shadow` line per hit. `scripts/flow_hedge_shadow_review.py` summarizes them. **`format_flow_alert` is byte-identical — a test locks the exact string with and without delta.** Wired into the flow loop only when `collect:true`. |
| **T2-c / F6 · Brier/calibration report** | `features.calibration_report.enabled` | Real run on the live 644 MB DB posted (dry-run) a plain-English summary to #errors: *"24h: Brier 0.250 vs base-rate 0.248 … AUC 0.505"* — i.e. it honestly shows the score barely beats a coin. New `format_discord()` in `eval/report.py`; `scripts/calibration_report.py` (read-only, `--dry-run`); weekly `calibration-report.timer`. Corrupt DB → exit 1 (systemd OnFailure), no post. Thin sample (n<10) → raw ratio, never a Brier. 6 unit tests. |
| **T3-a / F9 · SEC XBRL fundamentals feed** | `features.sec_xbrl.enabled` (display-only) | Real SEC fetch: **NVDA** latest quarter revenue **$44.06B, +69% YoY**, net margin 43%, EPS $0.76; **AAPL** $95.4B via the `RevenueFromContractWithCustomer*` tag (the revenue-tag fallback the plan flagged); **MU** $9.3B +37%. New `scanners/sec_xbrl.py` REUSES `sec_edgar`'s CIK map + UA (test asserts the import). `company_fundamentals` table + `scripts/sec_xbrl_daily.py` + daily timer. ONE `🏢 Fundamentals` line on `!all`; flag OFF → the field is absent, `!all` embed byte-identical (test). Never scored. |
| **T3-c / F10 · Backtest-to-live decay tracker** | `features.decay_tracker.enabled` | Real run on the live DB froze **14 baselines** (per decision tier, catalyst type, and flow side) and flagged **3 decays / 6 OK / 5 insufficient** with Wilson lower bounds. New `signal_baselines` table + `scripts/signal_decay_check.py` (`--freeze-baselines`, `--dry-run`, `--force-alert`) + daily timer. Alerts #errors via `ops_alert` (transition-only + flap guard, verified). Thin sample (n<30) → INSUFFICIENT, raw ratio. **NEVER un-flips a flag — reports only.** 4 unit tests. |

**A trap the plan itself walked into, caught during the build:** the build plan said to rank `!sweep` on
`breakdown.total`. That is the RAW ADDITIVE sum — but `!scan` reports the **precision-gated** score
(`analyze_signal`), and the code says why: *"the one 0-100 band scale (not the raw additive sum) … that
coherence is the whole point of #50."* Ranking on `breakdown.total` would have made `!sweep NVDA` and
`!scan NVDA` print **different numbers for the same ticker** — re-creating the exact bug TODO #50 was
built to remove. `!sweep` now runs the identical path `!scan` runs. Cost of that correctness: a sweep
spends the same API budget the live alerts use, hence the ticker cap.

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
| 24 ideas | **13 BUILT · 5 OPEN (in the tiers above) · 2 KILLED on evidence · 4 PASSED** (c88/c8/c42/c91, all dropped by the user on merit 2026-07-14 — not resource cuts) |

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
ever gave a reason for. That is your real reserve pool if the 5 open candidates run out.

**One PASSED idea's reason has already expired:** **c102 (short-alert squeeze-risk guard)** was rejected
only because it *"depends on the short-interest leg landing first"* — and that leg has since **shipped**
(c9). Its blocker is gone. It is the single most promotable idea in the PASSED bucket.

---

## PASSED — 2 more on 2026-07-14 (run `menu-top10`, user accepted both drops)

These two entered the 12-candidate pool for the "10 strongest" selection and were dropped on the
kill-test. **Neither was dropped as "already built" — both are genuinely unbuilt.** They were dropped
because building them now buys little:

| Idea | Why it was PASSED (2026-07-14) |
|---|---|
| **T3-b · FOMC hawk/dove statement reader** | **Worst payoff per line on the menu.** Only **8 statements a year**, and a Fed statement carries **zero per-ticker attribution** — it says nothing about whether NVDA is a buy. Building it needs a new fetcher + an LLM stance parser + a stance-persistence table. FOMC dates *already* do the one job that matters here: they drive an alert blackout (`data/macro_events.yaml:5-11` → `analysis/contradiction.py:24-72`). **Re-open only if** the bot ever needs a macro-regime input that the existing cross-asset legs can't supply. |
| **T2-b · Generalize the crowding guard (c72)** | **DROPPED on the user's call, 2026-07-14.** The build (F5) would have added `youtube_* → 'video_crowd'` dedup — treating several YouTube channels saying the same thing as one crowded vote and discounting them. The user rejects the premise: **independent channels agreeing is confluence, not crowding** — that's the signal we want, not noise to suppress. The two narrow guards already live (`wolf_confluence.py`, `herding.py`) and the OFF `social_family_dedup` flag (#67's decision) are untouched — only the YouTube generalization is killed. **Do not re-propose.** |
| **T2-d · Analyst price-target spread logger (c88)** | **DROPPED on the user's call, 2026-07-14.** The build (F8) logged the high-vs-low analyst target gap **daily**, but analysts rarely move targets, so it mostly re-writes the same three numbers, and shows the user nothing for months (no history to compare against). Not worth the plumbing as planned. The targets themselves stay on the `!all` card (`🎯 $215 avg ($180–$260)`) — only the daily spread-logger is killed. **Do not re-propose** unless it's redesigned to log only on change. |
| **T3-d · Learned (continuous) signal weights** | **The blocker is data, not code — so more code today changes nothing.** Its old gate ("needs the 0-100 score") is genuinely gone: the score is live. But the real gate is **outcome-data volume**, and that is owned by #67/#73 (the Friday-outcome backfill + the shadow soak). The offline `logistic_challenger` (`eval/report.py:286-366`) already fits real coefficients with a ticker embargo — they are simply never persisted or served at inference, and persisting them is a **score-touching blast-radius change** that belongs with the auto-flip engine, not a side build. **Re-open when** the graded-outcome table is rich enough for the auto-flip engine to trust a continuous weight — i.e. after #73's soak fills in. This is the strongest re-open candidate in the PASSED bucket once the data lands. |

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
| c1 | VVIX "fear-of-fear" gauge | **BUILT 2026-07-14** | `features.vvix_residual.enabled` — residual vs the VIX, descriptive only. Real row: VVIX 93.28 / VIX 16.50, pct 0.373 |
| c2 | VIX/VIX3M calm-vs-panic term structure | LIVE | Already in the cross-asset regime code |
| c3 | Dealer gamma (GEX) map | BUILT | `features.dealer_gamma.enabled` |
| c4 | IV skew: puts vs calls | BUILT | `features.iv_skew.enabled` |
| c5 | Machine-readable buy/sell tags on alerts | PASSED | Overlaps shipped decision-first alerts; nothing downstream would use the tags |
| c6 | Short-end VIX9D term-structure leg | PASSED | Minor extension of existing term structure; marginal once VVIX covers vol-of-vol |
| c7 | Yield curve, dollar, real yields | BUILT | `features.cross_asset.macro_legs` |
| c8 | Market-wide put/call ratio | **PASSED 2026-07-14 (user)** | Passed by the user: its free CBOE source has been dead since Oct 2020; per-ticker put/call already exists |
| c9 | FINRA short interest + days-to-cover | BUILT | `features.short_interest.enabled` |
| c10 | Treasury/FOMC event-risk overlay | PASSED | FOMC and CPI dates already ingested; the staleness add-on is thin |
| c11 | Max-pain reliability label | **KILLED** | Premise false — max-pain is already shown unconditionally |
| c12 | Hedge-vs-directional flow discount | **BUILT 2026-07-14** (F4) | `features.flow_hedge_discount.collect` — SHADOW LOG only (delta-weighted notional + leg-pairing); live flow alert byte-identical |
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
| c23 | Explicit 0–100 score | **BUILT 2026-07-14** (footer half) | Score was already LIVE. The footer half shipped: `features.sources_denominator.enabled` → real `!all NVDA`: `Sources: 21 of 27 attempted` |
| c24 | Realized-vs-implied vol as move-confidence weight | PASSED | Subsumed by the cheap/rich-vol flag — same implied-minus-realized spread |
| c25 | Options pinning probability | BUILT | `features.oi_pinning.enabled` |
| c26 | Kelly position-size suggestion | PASSED | Position sizing is outside the alert-only scope; edge estimates too noisy |
| c27 | Cross-ticker correlation-break detector | PASSED | Secondary; peer relative-strength already separates stock-specific moves |
| c28 | Post-earnings drift (PEAD) | BUILT | `features.pead.enabled` |
| c29 | 12-1 month momentum rank | PASSED | Factor work already proven no-edge on free daily data |
| c30 | Amihud illiquidity confidence discount | PASSED | Minor confidence tweak; overlaps the liquidity-gate family |
| c31 | Hidden Markov regime detector | PASSED | Reason not recorded in the artifacts |
| c32 | Automated Brier calibration report | **BUILT 2026-07-14** (F6) | `features.calibration_report.enabled` — weekly timer posts the Brier/AUC summary to #errors |
| c33 | GARCH volatility cross-check | PASSED | Heavy model for marginal gain over the cheap/rich-vol leg |
| c34 | Social message-volume spike detector | PASSED | Incremental attention proxy; StockTwits and ApeWisdom trending already ingested |
| c35 | Overnight gap-fill probability model | PASSED | Niche swing heuristic; lower priority than the options legs |
| c36 | AAII weekly sentiment survey | PASSED | Weekly contrarian survey; secondary low-cadence source |
| c37 | NAAIM manager exposure index | PASSED | Same weekly-survey class as AAII; secondary |
| c38 | Wikipedia pageview attention spike | PASSED | Weak standalone attention proxy |
| c39 | EDGAR full-text 8-K keyword scanner | PASSED | 8-K detection already ships; 8-Ks never trigger standalone alerts |
| c40 | Full VIX-futures term-structure curve | PASSED | Richer than the front curve but heavy to ingest; marginal gain |
| c41 | Institutional vs retail put/call divergence | PASSED | Reason not recorded in the artifacts |
| c42 | CFTC Commitments of Traders | **PASSED 2026-07-14 (user)** | Passed by the user: weekly, lagged, futures-only — wrong speed for a 15-minute per-stock bot |
| c43 | Economic Policy Uncertainty index | PASSED | Monthly cadence and noisy; secondary macro source |
| c44 | Trading-halt tripwire | BUILT | `features.trading_halts.enabled` |
| c45 | 13F institutional-holdings change | PASSED | 45-day lag; slower and less valuable than Form 144 or Congress |
| c46 | Backtest-to-live decay tracker | **BUILT 2026-07-14** (F10) | `features.decay_tracker.enabled` — daily; froze 14 baselines, alerts #errors on decay (transition-only); never un-flips |
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
| c59 | Learned signal weights | **PASSED 2026-07-14** | Blocker is DATA not code: outcome-data volume, owned by #67/#73. Coefficients already fit offline; persisting them is a score-touching change for the auto-flip engine. **Strongest re-open once #73 soak fills in** |
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
| c72 | Signal-crowding guard | **PASSED 2026-07-14 (user)** | DROPPED by the user: its build (F5) would treat independent YouTube channels agreeing as "crowding" and discount them — but that is **confluence, not crowding**. The two live narrow guards are untouched |
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
| c87 | FOMC hawk/dove statement reader | **PASSED 2026-07-14** | 8 statements/year, zero per-ticker attribution, needs a new fetcher + LLM stance parser. FOMC dates already drive the alert blackout. Worst payoff per line on the menu |
| c88 | Analyst price-target disagreement | **PASSED 2026-07-14 (user)** | DROPPED by the user: its build (F8) logged the target spread daily but mostly re-writes the same numbers (analysts rarely move targets) and shows nothing for months. Targets stay on the `!all` card |
| c89 | Quad-witching / OpEx-week overlay | PASSED | Narrower variant of seasonality; low impact |
| c90 | Options bid-ask spread deterioration gate | PASSED | Data-quality gate; overlaps the liquidity family |
| c91 | GDELT global news tone | **PASSED 2026-07-14 (user)** | Passed by the user: noisy, weak per-ticker attribution; the repo's own research already scored it bottom-30% |
| c92 | SEC Form 144 intent-to-sell | BUILT | `features.form144.enabled` |
| c93 | Google Trends search-volume leg | PASSED | Fragile unofficial scraper; terms-of-service risk |
| c94 | SEC XBRL fundamentals feed | **BUILT 2026-07-14** (F9) | `features.sec_xbrl.enabled` — display-only `!all` line; real NVDA $44.06B/+69% YoY; !all embed byte-identical OFF |
| c95 | EIA weekly oil and gas inventories | PASSED | Reason not recorded in the artifacts |
| c96 | Census advance retail-sales leg | PASSED | Sector-narrow; the release dates are already tracked |
| c97 | OpenSecrets lobbying-spend leg | PASSED | Noisy leading indicator; low source quality. *(This ID is duplicated in the artifacts — counted once.)* |
| c98 | USASpending federal contract awards | PASSED | Narrow to government-contractor names; secondary |
| c99 | BLS JOLTS labor-market leg | PASSED | Monthly macro; NFCI and yield/dollar legs already cover the backdrop |
| c100 | FINRA TRACE corporate-bond credit leg | PASSED | Single-name bond data is sparse and heavy to integrate |
| c101 | Crowded-trade monitor across tickers | PASSED | Overlaps c72, the crowding guard |
| c102 | Short-alert squeeze-risk guard | **BUILT 2026-07-14** (F7) | `features.short_squeeze_guard.enabled` — negative squeeze_risk term demotes a SHORT on a crowded, rising short; shares the r12 DB read; breakdown byte-identical OFF |
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
| c113 | Universe screener across the watchlist | **BUILT 2026-07-14** | `features.sweep.enabled` → `!sweep` / `!universe` (NOT `!scan`, which is untouched). Real sweep: IBM 82 / META 55 / JPM 49; `!sweep IBM` == `!scan IBM` == 82 |
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
- **Tally (final, 2026-07-14):** 25 BUILT + 6 LIVE + 3 KILLED + 80 PASSED + 0 OPEN = **114 verdicts
  over 113 IDs.** The 25 BUILT = 16 July-run + 1 found-already-live (c60 EPS revisions) + 3 TIER-1
  (menu-top10) + 5 final (F4/F6/F7/F9/F10, this run: c12, c32, c46, c94, c102). **OPEN is now 0 — the
  menu is exhausted.**

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

### Session notes — 2026-07-14 (run `menu-top10` — TIER 1 built)
- **Worked on:** picked the 10 strongest of 12 candidates (kill-test dropped 2), then — on the user's
  call — built **TIER 1 only**: T1-a footer denominator, T1-b VVIX gauge, T1-c `!sweep`. All flag-OFF,
  all proved on real data, 2991 tests pass with zero regressions, checked by a separate verifier agent.
- **Verdicts written back:** 3 BUILT · 2 PASSED (FOMC reader, learned weights — user accepted both) ·
  c102 PROMOTED PASSED → OPEN (its short-interest blocker has shipped). TIER 1 is now empty.
- **The other 7 are PLANNED, not just listed** — full plans (verified line numbers, risk callouts, a
  probe each) are in `todo/feature-menu-build-plans.md`. **Read that before re-planning any of them.**
  It was copied out of the discover run's artifacts on purpose: those live under `.claude/`, which is
  git-ignored and sat in a throwaway worktree — the plans would have been deleted with it.
- **Two plan errors caught while building** (recorded at the top of the plans file): it wanted `!sweep`
  ranked on the raw additive `breakdown.total` (would have disagreed with `!scan` — the #50 bug), and it
  under-specified the VVIX fetch (yfinance returns ^VVIX in New York time and ^VIX in Chicago time, so a
  naive join silently matches zero bars). **A plan is a hypothesis; verify it against live code.**
- **Switches:** the 3 new flags are registered on **TODO #67**, the single list of built-but-off
  switches awaiting the user's yes/no — not here.

### Session notes — 2026-07-14 (F5 + F8 dropped)
- **Worked on:** the user reviewed the open ideas and **killed two — F5/T2-b (c72) the crowding-guard
  generalization, and F8/T2-d (c88) the analyst target-spread logger.**
  - **F5:** its build would treat several independent YouTube channels saying the same thing as
    "crowding" and discount them — but independent channels agreeing is **confluence, not crowding**.
  - **F8:** it logged the high-vs-low analyst target gap **daily**, but analysts rarely move targets, so
    it mostly re-writes the same numbers and shows the user nothing for months. Not worth it as planned
    (a redesign that logs only on change might revive it).
  - Moved both OPEN → PASSED in the tiers, the roster (c72, c88), and both tallies; marked F5 and F8
    DROPPED in the build-plans file. Open count 10 → 8. The two already-live narrow crowding guards, the
    OFF `social_family_dedup` flag (#67), and the analyst targets on the `!all` card are all untouched.
- **Next:** open tiers now hold F4, F6, F7, F9, F10 (planned) + the T3/T4 ideas.

### Session notes — 2026-07-14 (TIER 4 passed)
- **Worked on:** the user **passed on all three TIER-4 ideas** — c8 market-wide put/call (free CBOE
  source dead since Oct 2020), c42 CFTC COT (weekly, lagged, futures-only), c91 GDELT news tone (noisy,
  weak per-ticker attribution, repo's own research scored it bottom-30%). Moved all three OPEN → PASSED
  in the tiers, roster, and every tally. TIER 4 is now empty. Open count 8 → 5.
- **Result:** the 5 remaining open ideas are exactly the 5 with full build plans (F4, F6, F7, F9, F10):
  hedge-vs-directional flow discount, Brier/calibration report, short-alert squeeze-risk guard, SEC XBRL
  fundamentals, backtest-to-live decay tracker. Nothing left on the menu is unplanned.
- **Next:** build from F4/F6/F7 (Tier 2, lighter) before F9/F10 (Tier 3, heavy).

### Session notes — 2026-07-14 (run `menu-top10` — the FINAL 5 built; menu EXHAUSTED)
- **Worked on:** built the last 5 open ideas, all flag-OFF, each proved on real data:
  - **F7** short-alert squeeze-risk guard (`short_squeeze_guard.enabled`) — `_compute_squeeze_risk_pts`
    demotes a SHORT on a crowded, RISING short. Shares the ONE existing `get_latest_finra_short_interest`
    read the r12 bullish leg uses (no 2nd DB call); each leg gated by its OWN flag so r12 stays
    byte-identical. 10 tests.
  - **F4** hedge-vs-directional flow classifier (`flow_hedge_discount.collect`) — SHADOW LOG only.
    `FlowHit.delta` (Schwab greeks) → `scanners/flow_hedge.py` classify (delta-weighted notional + leg
    pairing) → `flow_shadow` log lines → `scripts/flow_hedge_shadow_review.py`. `format_flow_alert`
    byte-identical (test locks the string). **Note: delta only comes from the Schwab chain, which is
    currently expired — until re-login, collected hits log `delta_unknown`.**
  - **F6** Brier/calibration report (`calibration_report.enabled`) — `format_discord()` + weekly
    `calibration-report.timer` → #errors. Real dry-run on the 644 MB live DB: 24h Brier 0.250 vs
    base-rate 0.248, AUC 0.505 — the report honestly shows the score barely beats a coin. Corrupt DB →
    exit 1 (OnFailure), no post.
  - **F9** SEC XBRL fundamentals (`sec_xbrl.enabled`) — `scanners/sec_xbrl.py` REUSES `sec_edgar`'s CIK
    map + UA. Real fetch: NVDA $44.06B/+69% YoY, AAPL $95.4B (via RevenueFromContractWithCustomer*), MU
    $9.3B/+37%. `company_fundamentals` table + daily timer + ONE `!all` line; embed byte-identical OFF.
  - **F10** backtest-to-live decay tracker (`decay_tracker.enabled`) — `signal_baselines` table +
    `scripts/signal_decay_check.py` + daily timer. Real run: froze 14 baselines, flagged 3 decay / 6 OK
    / 5 insufficient with Wilson LBs. Alerts #errors transition-only (flap-guarded). **Never un-flips.**
- **Result:** **all four tiers are EMPTY; the menu is exhausted.** 25 BUILT · 6 LIVE · 3 KILLED · 80
  PASSED · 0 OPEN. The 5 new flags are registered on **#67** (the built-but-off switch list). To generate
  NEW ideas run **#75**; the SOFT reserve pool (25 judgment-call/no-reason drops) is the cheaper first stop.
- **Verification:** all 5 have unit tests (byte-identical OFF paths locked); flag_flip_gate clean (no
  OFF→ON); a separate verifier agent re-ran the full suite vs `.test-baseline`.
