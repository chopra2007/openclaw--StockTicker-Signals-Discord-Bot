# Feature menu — the researched ideas, and what happened to each

**Status:** ONGOING — pick one per session; closes only when every idea is BUILT or PASSED
**Created:** 2026-07-14

**CURRENT STATUS (2026-07-14):** **34 ideas tracked. Every open idea re-verified against the LIVE CODE
on 2026-07-14** — and the discover run's "not built" list turned out to be misleading. Of its 8
"survived but not built" ideas, **only 3 are genuinely absent from the codebase** (market-wide
put/call, CFTC, GDELT). Two are effectively already built and live, one would have clobbered an
existing command, and two are half-built.

**The trap this file exists to prevent, and nearly fell into:** the discover artifacts say
"survived_killtest_not_built_this_run". That means *the July run didn't build it* — **NOT** *the bot
lacks it*. Some of those ideas were already in the code, or landed later by another route. **Never
promote an idea to "ready to build" from the artifacts alone. Grep the live code first.** (Caught
2026-07-14 by the user, who asked "are you sure the 8 aren't already built?" The answer was no.)

Current shape: **16 BUILT (July run) · 3 KILLED · 3 genuinely open · 3 smaller-than-they-look ·
2 half-built · 7 conditional.**

---

## How to use this

0. **Before touching any idea: grep the live code for it.** The verdicts below were true on
   2026-07-14. Code moves. A 2-minute grep beats a wasted build.
1. Pick an idea from **READY TO BUILD** below.
2. Build it under the normal rules — flag OFF, real-data test, regression baseline, separate verifier.
3. **Write the verdict back here** — `BUILT` (with the flag name) or `PASSED` (with the reason).
4. An idea you decide against is `PASSED`, not deleted. The reason is the whole point: it stops the
   next session, and the next research run, from proposing it again.

The list is exhausted when nothing sits under READY TO BUILD or CONDITIONAL.

---

## READY TO BUILD — 3 genuinely open

Verified absent from the codebase 2026-07-14 (zero hits, repo-wide).

| # | Idea | What the user would actually see | Cost / catch |
|---|---|---|---|
| **11** | Market-wide put/call ratio | A whole-market fear/greed dial (options bets across the *entire* market, not one ticker) | Per-ticker put/call exists (`scanners/options.py:127`); the market-wide aggregate does not. Catch: no robust free source proven, and it overlaps E2's market-regime multiplier — must justify what it adds. Inherit the known NaN/one-sided-day bug lesson from `display_scale.py:64` |
| **21** | CFTC Commitments of Traders | How the big futures speculators are positioned (crowded long/short) | Free, weekly. Zero code hits for `cftc`/`cot`. Catch: **weekly and lagged**, futures-only — awkward for a 15-minute per-stock bot. Codex dissented ("too slow/macro"). Descriptive view at best |
| **24** | GDELT global news tone | A free worldwide news-sentiment read | Free. Zero code hits for `gdelt`. Catch: **very noisy**, weak per-ticker attribution, big filtering build. The curated SerpAPI/RSS/Brave news already in the bot is probably sharper |

---

## SMALLER THAN THEY LOOK — 3. Read before picking; these are NOT features.

The July run listed these as "not built". **The code says otherwise.** Each is a small delta on
something already live — sizing any of them as a feature wastes the effort you were trying to save.

| # | Idea | What is ALREADY LIVE | What is actually missing |
|---|---|---|---|
| **2** | Explicit 0–100 score | **The 0–100 score exists and is live.** `features.single_score.enabled: true` (`consensus.yaml:871`). Rendered with a 🟢/🟡/🔴 band in `!scan` (`commands.py:744-747`) and in every alert (`main.py:1647-1687` → `discord.py:395-398`). It is the same score the live alerts use | **Only the "N of M signals live" provenance line.** Today the footer shows a bare numerator — `Sources: 4` (`embed.py:1129-1134`) — with no denominator. **This is a ~20-line footer change, not a feature.** Do NOT build a second score |
| **25** | Analyst price-target disagreement | **The targets are already ON SCREEN.** `snapshot.py:207-210` fetches mean/high/low/n_analysts, and `all_command/embed.py:551-557` already renders `🎯 $215 avg ($180–$260) · 58 analysts` on the `!all` card | **Only the derived statistic** — no `(high−low)/mean` spread, no percentile. And to say a spread is *unusually* wide you need a stored history of spreads, **which does not exist**. So this is "start logging, then build later", not a quick win. (An earlier note in this file wrongly called it "the cheapest thing to build" — it isn't.) |
| **27** | `!scan` universe screener | **`!scan` IS ALREADY A LIVE COMMAND** — `commands.py:406-411`. It takes tickers (`!scan nvda amd mu`, cap 5) and is in the help embed. There is also a watchlist-wide sweep, but only as a **background loop** (`main.py:474-481`), not a command | An **on-demand, watchlist-wide** sweep. The gap is real — no command shows you the *quiet* names the poll never mentions. **⚠️ DO NOT name it `!scan`** — that would silently clobber a working, documented command. Pick a new name (`!sweep`, `!universe`) |

---

## HALF-BUILT — 2. The job is "finish/generalize", not "build".

| # | Idea | What already exists | The real job |
|---|---|---|---|
| **6** | Signal-crowding guard | **Crowding guards are already LIVE in two places.** (a) `wolf_confluence.py:84-99` tags every source with an independence bucket and lets each bucket cast **one** net vote ("agreement is counted in buckets, never in rows"). (b) `herding.py:279-285` applies a real **measured pair-correlation discount** to analyst clusters — `effective_size = raw_count − Σ co_post_rate`, proven by `tests/test_analyst_herding.py::test_correlation_discount_reduces_effective_size`. Separately, `social_family_dedup` is built but **switched OFF** (`consensus.yaml:870`) | **Generalize + switch on**, not build. The measured-correlation machinery already exists — it is just scoped to analyst clusters. The open work is extending that idea across the whole score, and flipping `social_family_dedup` on (which needs the blast-radius measurement noted in #67). *(Note: a first pass at this verification wrongly reported the correlation discount as a never-applied stub — it misread `_record_swarm_history`, a separate best-effort history-logging function. The discount is real. Verify before believing a claim like that, including one of mine.)* |
| **1** | VVIX/VIX "fear-of-fear" gauge | Nothing in the bot (zero `vvix` hits). But the bot DOES have a VIX/VIX3M term-structure leg (`analysis/cross_asset.py:15`) — and **a working VVIX-residual implementation already exists in the sibling project** `volatility_regime_reversal_indicator/` (`backtest/phase2.py` `leg_vvix_residual_high`) | **Port it, don't invent it.** Hard constraint: must be the residual vs the existing E2 leg, and **descriptive only — never an alert gate.** Gating on it re-creates the VIX predictor already rejected in #47. Study: `.claude/discover/next-features-jul2026/VVIX-RESEARCH-FINDINGS.md` |

---

## CONDITIONAL — 7 open

Worth it only after a prerequisite exists, or a heavy build for a niche gain. Not ready to pick blind.

| Idea | What it would do | Gate |
|---|---|---|
| Learned signal weights | Let the bot learn which signals deserve more weight | Needs the 0–100 score (**#2**) first |
| Backtest-to-live decay tracker | Warn when a signal that backtested well starts failing live | Value grows as outcome data accrues (see #73's soak) |
| Brier-score calibration automation | Auto-grade how well-calibrated the bot's confidence is | Partly exists in `eval/metrics.py` — the delta is just auto-scheduling |
| Hedge-vs-directional flow discount | Tell a hedge apart from a real bet | May overlap a built options item — **check before building** |
| EPS-estimate revisions momentum | Track analysts quietly raising/lowering earnings estimates | Distinct from the rating momentum already shipped — confirm no overlap |
| FOMC hawk/dove statement reader | Read the Fed statement and say if it turned hawkish | "High potential" but a heavy LLM build |
| SEC XBRL fundamentals feed | Real company financials as a new data class | Strong, but a large build |

---

## BUILT — 16 (July 2026 run, all shipped flag-OFF)

All 16 are live in the code but switched **off**. Turning them on is **#67**, not this item.

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

---

## KILLED — 3. Do not re-propose.

| # | Idea | Why it died |
|---|---|---|
| 3 | Max-pain reliability label | **Premise was false.** Max-pain is already shown unconditionally — the `<= 3` in `options.py` is a 3rd-Friday snap tolerance, not a hide-gate. Building "stop hiding it" is a no-op |
| 19 | Dark-pool / off-exchange volume | FINRA publishes it **2–5 weeks late** (probed live). Useless for a 1h/24h alert |
| 13 | 0DTE directional flow imbalance | Signed/aggressor-side flow **does not exist in any free feed**. The buildable version is just the put/call ratio already shipped |

---

## ALREADY LIVE — 6. Rebuilding these is wasted work.

VIX/VIX3M term-structure regime · anchored VWAP bands · volume-profile levels · FINRA daily
short-volume · analyst-rating momentum · 13D/13G activist-filing scanner.

---

## The 79 rejected, and the vault below them

The July run considered **113 distinct ideas** and rejected 79 with written reasons, clustered as:
overlaps a kept idea; conflicts with the project's own rules (confirm-gates fight the instant-trigger
philosophy; 8-Ks never trigger standalone); out of scope (position sizing, portfolio P&L — the bot is
alert-only); dead-end data (sector/factor rotation, already proven no-edge; pytrends, fragile);
ops niceties (health dashboards, provenance tags).

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

- **#75** — the loop that generates NEW ideas. Run it when this menu is thin.
- **#67** — turning ON the 16 already built. Different job: those need a yes/no, not a build.
- **#6** — the `!all` command's own quality-lever menu (a separate, narrower list).
