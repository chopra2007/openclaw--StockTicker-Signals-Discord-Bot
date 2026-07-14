# Feature menu — the researched ideas, and what happened to each

**Status:** ONGOING — work the tiers top-down; closes only when every idea is BUILT or PASSED
**Created:** 2026-07-14
**Last full code re-verification:** 2026-07-14 (every open idea grepped against the live code)

**CURRENT STATUS (2026-07-14):** **34 ideas tracked — 17 BUILT, 3 KILLED, 14 OPEN.** The 14 open
ideas are now sorted **strongest first, in four tiers**, so a session can start at the top and work
down. Nothing already built or already passed on appears in the candidate tiers — re-verified against
the live code, not against the discover run's artifacts.

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

## PASSED — 79 rejected in the July run, with reasons

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

## Related

- **#75** — the loop that generates NEW ideas. Run it when all four tiers are empty.
- **#67** — turning ON the 16 already built. Different job: those need a yes/no, not a build.
- **#6** — the `!all` command's own quality-lever menu (a separate, narrower list).
