# Feature menu — the researched ideas, and what happened to each

**Status:** ONGOING — pick one per session; closes only when every idea is BUILT or PASSED
**Created:** 2026-07-14

**CURRENT STATUS (2026-07-14):** **34 ideas tracked. 16 BUILT, 3 KILLED, 15 still open** (8 ready to
build now, 7 conditional). This is the standing menu — pick one per session. Every idea already has a
verdict written next to it, so no session ever re-researches settled ground. Nothing here needs new
research; the research is done (#75 is the loop that generates *new* ideas when this list runs thin).

**Cheapest thing to build right now: #25 (analyst price-target disagreement)** — the data already
flows through `snapshot.py`, so it is a computed field on `!all`, not a new integration.

---

## How to use this

1. Pick an idea from **READY TO BUILD** below.
2. Build it under the normal rules — flag OFF, real-data test, regression baseline, separate verifier.
3. **Write the verdict back here** — `BUILT` (with the flag name) or `PASSED` (with the reason).
4. An idea you decide against is `PASSED`, not deleted. The reason is the whole point: it stops the
   next session, and the next research run, from proposing it again.

The list is exhausted when nothing sits under READY TO BUILD or CONDITIONAL.

---

## READY TO BUILD — 8 open

These passed research **and** the adversarial kill-test, and simply weren't built in the July run.

| # | Idea | What the user would actually see | Cost / catch |
|---|---|---|---|
| **25** | Analyst price-target disagreement | A "nobody agrees on this one" warning on `!all` when analysts' targets are far apart | **Cheapest.** Inputs already flow through `snapshot.py` — a computed field, no new fetch. Catch: yfinance gives a coarse range, not true dispersion — edge may be small |
| **27** | `!scan` universe screener | One command sweeps the whole watchlist and shows setups side by side | Free, reuses existing code. Catch: it is convenience, not new intelligence — the flow loop already sweeps the same names. The real gain is seeing the **quiet** names the poll never mentions |
| **1** | VVIX/VIX "fear-of-fear" gauge | A calm-vs-fragile market label next to alerts | Free (`^VVIX`+`^VIX`). **Hard constraint:** must be the residual vs the existing E2 leg, and **descriptive only — never an alert gate.** Gating on it re-creates the VIX predictor already rejected in #47. Study: `.claude/discover/next-features-jul2026/VVIX-RESEARCH-FINDINGS.md` |
| **2** | Explicit 0–100 score | One headline number + "4 of 5 signals live", so you can see what built the score and when it ran on partial data | Free. Catch: the premise is half-false — per-leg weighting is *already* explicit. Real value is only the 0–100 normalisation + the "legs N of total" provenance line. Must **annotate** the existing score, not become a second competing number |
| **11** | Market-wide put/call ratio | A whole-market fear/greed dial | Catch: no robust free source proven, and it overlaps E2's market-regime multiplier. Must justify what it adds |
| **21** | CFTC Commitments of Traders | How the big futures speculators are positioned (crowded long/short) | Free, weekly. Catch: **weekly and lagged**, futures-only — awkward for a 15-minute per-stock bot. Codex dissented ("too slow/macro"). Descriptive view at best |
| **24** | GDELT global news tone | A free worldwide news-sentiment read | Free. Catch: **very noisy**, weak per-ticker attribution, big filtering build. The curated SerpAPI/RSS/Brave news already in the bot is probably sharper |
| **6** | Signal-crowding guard | Catch two signals secretly measuring the same thing and inflating confidence | **CANNOT BUILD YET** — needs ≥6 months of stored per-leg daily snapshots; correlations stay noisy until then. *Actionable now: start logging the per-leg values so this becomes buildable later.* |

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

The July run considered **113** ideas and rejected 79 with written reasons, clustered as: overlaps a
kept idea; conflicts with the project's own rules (confirm-gates fight the instant-trigger
philosophy; 8-Ks never trigger standalone); out of scope (position sizing, portfolio P&L — the bot is
alert-only); dead-end data (sector/factor rotation, already proven no-edge; pytrends, fragile);
ops niceties (health dashboards, provenance tags).

**Read the reasons before proposing anything "new" that sounds like one of these.**

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
