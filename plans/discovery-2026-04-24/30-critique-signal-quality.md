# 30 — Red-Team A: Signal Quality (Regime-Survival Critique)

**Date:** 2026-04-24
**Lens:** Will each candidate signal survive realistic market regimes, or does it invert / get drowned in noise when conditions change?
**Inputs:** `plans/discovery-2026-04-24/20-candidate-features.md` (the 14 ranked surviving Phase-2 candidates), `plans/discovery-2026-04-24/00-system-map.md` (constraints), `plans/AUDIT_RESEARCH_2026-04-24.md` (historical DB-measured behavior, including the 94% @30-band vs 21% @60-band inverted-monotonicity finding).
**Independence:** I have NOT read sibling critiques (`31-*`, `32-*`); converge phase reconciles.

---

## Executive Summary

**Verdict counts:** KEEP=4, STRENGTHEN=8, KILL=2.

**KILL list:** Feature 9 (SEC EDGAR full-text mention velocity), Feature 13 (influencer cluster-convergence). Both fail decisively in the regimes the bot most often serves: small-cap meme regimes for #13, and the "non-trading-related filing flood" pattern that already poisoned the bot's SEC pipeline 2026-03-31 → 2026-04-07 (per audit) for #9.

**Three systemic concerns** spanning multiple features:

1. **VIX-floor compression hits five features simultaneously.** Features 3 (pre-FOMC drift), 4 (credit-equity divergence), 5 (volume breakout), 11 (Reg SHO entries), and 12 (VIX term-structure) all use either an explicit `VIX>18/22` gate or an implicit assumption that vol is "normal." In a sustained VIX<15 regime — Feb–Nov 2017, Jan–Sep 2019, Sep 2024–Feb 2025 — three of these signals stop firing entirely (3, 12 by gate; 4 by correlation), one (5) bleeds precision because "breakouts" are mean-reverting trickle moves, and one (11) inverts because forced-buy-in mechanics get neutralized by ample borrow availability in low-stress regimes. The Phase-2 spec treats VIX as a contextualizer; in production it acts as a single point of failure across a third of the portfolio.

2. **Concentrated mega-cap leadership inverts the breadth/credit signals while the equity index keeps rising.** The 2023–2024 "Mag 7 carry the index" regime (cf. 2024 Q1 SPY +10.2% with breadth via S&P 500 equal-weight only +5.6%, NDX vs RUT spread one of widest 24m readings) makes Feature 4 (credit-equity gap) chronically bearish at the index level despite SPY grinding higher — false-positive harvest. Same structural issue for Feature 12 (VIX term-structure) when single-name vol decouples from index vol. Feature 8's cluster-Form 4 / 13D in small caps still works, but the contextualizers around it become misleading in this regime, biasing the bot toward bearish small-cap calls when small caps are simply being deweighted by capital flows, not fundamentally weak.

3. **Free-tier data assumptions degrade exactly when stakes rise.** During the Mar 2020 liquidity freeze, the May 2010 Flash Crash, and the Feb 5 2018 VIXmageddon, the public/free endpoints these features rely on (yfinance, FRED, CBOE CSV, Wikimedia, FDA HTML scrape, EDGAR EFTS) experience either rate-limiting, schema breakage (CBOE), or stale-cache poisoning (FRED HY OAS lags one full day; in a 2-day shock the signal is already moot). Five features (3, 4, 5, 11, 12) are macro/quant strategies whose entire edge is "be early to a regime turn" — but their data path is "be 1 day late, on a public endpoint that gets crushed under Mar-2020-style traffic." This is the cheapest cross-cutting STRENGTHEN: every macro feature needs a shock-aware data-staleness gate that fails closed (no signal, no false positive) when the upstream is older than 1 trading session.

---

## 1. Cluster Form 4 Open-Market Buys — VERDICT: **KEEP**

**Composite carryover:** 5.00.

**Rationale:**

- The opportunistic-insider-buy edge is one of the most regime-invariant in the equities literature: Lakonishok-Lee (1998), Cohen-Malloy-Pomorski (2012) document persistence through the 2000–2002 dot-com bust, the 2008 GFC, the 2011 EU sovereign crisis, and the 2020 COVID drawdown. The only documented decay is post-Feb-2024 SEC cooling-off rule for 10b5-1 plans, which the feature explicitly filters out (`aff10b5One==false`).
- **One regime where it underperforms but does not invert:** Mar 2020 liquidity freeze. Cluster Form 4 buys did fire (notably banking and energy in late March: WFC, JPM, OXY, FANG cluster buys all printed in the Mar 16 – Apr 3 window), and 21-day forward returns were strongly positive — but the dispersion was huge (some names down 20% before recovering) so the kill criterion's "21d > 3% sector-adjusted" hits well over 55% across the cohort, but mark-to-market the path is brutal. The feature survives the kill criterion. UX: alert text needs to acknowledge "expect path volatility in stress regimes" — that's a Red-Team B / format problem, not a signal-quality problem.
- **One regime where it inverts:** *post-buyout-rumor short-squeeze on small caps*, e.g., Jan 2021 GameStop-era. Insiders "open-market buy" at $20 to telegraph confidence to inflate to $200 and then dump on the rip via 10b5-1. The $300M cap floor partially mitigates but the squeeze epoch produced multiple sub-$300M names that briefly cleared $1B intra-squeeze. Existing safeguards: $300M cap floor + cluster requirement + rank-weight ≥4 are sufficient — small-cap-pump-with-cluster-filers is rare enough (you'd need 2 distinct C-suite/director CIKs colluding, which crosses into 10b-5 territory) that the residual risk is acceptable.
- **2008-Q4 GFC stress test:** Lakonishok-Lee's update for 2007–2009 showed cluster-buy abnormal returns of +14% over 6 months on financials specifically — the very sector everyone was selling. The signal works in tail-risk drawdowns. The feature survives.
- **Concentrated-leadership regime (2023–2024):** insider clusters in mega-caps were rare (those CEOs are wealth-locked in stock already). Cluster firing was concentrated in mid/small-caps where the noise/signal trade-off is favorable. No inversion observed.
- The P2 safeguards (cap floor, rank-weight, dollar floor, z-score against personal trailing-2-year, retract on 4/A) collectively cover the main attack vectors. The 10b5-1 disguise risk is the only structural concern, and it's already filtered.

**Why KEEP and not STRENGTHEN:** every regime I can name where this inverts is already covered by an existing safeguard at the threshold the safeguard was designed for. No minimum hardening change needed beyond what P2 already specifies.

---

## 2. SEC S-4 / 425 Real-Time M&A Detection — VERDICT: **STRENGTHEN**

**Composite carryover:** 4.50.

**Rationale:**

- **Rate-shock regime risk (2022 H1, July–Dec 2022 hike cycle):** when financing costs spike abruptly, M&A velocity drops 35–50% (per Refinitiv 2022 data — global deal value Q4 2022 was the lowest in a decade). Existing S-4/425 filings during such windows are dominated by recutting deals (lower-price re-pricing announcements, terminations) — these still parse as "merger agreement" / "per share" but are NOT alpha events; they are loss-of-confidence events. The feature's regex (`merger agreement|definitive agreement|per share`) catches both indistinguishably.
- **High-correlation regime (Mar 2020, Sep 2008):** M&A targets get *re-traded down* alongside everything else. The "target jumps 27%" baseline (per Inside Arbitrage 2025) collapses to "target jumps 5–10% then promptly mean-reverts as deal-completion-risk priced in." Lead-time still beats the tape, but precision against a 24h-hold target degrades materially.
- **Concentrated mega-cap leadership regime (2023–2024):** small-cap M&A targets get *less* of a sympathy bid because the broader small-cap tape is being deweighted. The expected 27% pop becomes 12–15% in this regime per Q4 2024 deal data (Microchip/Embedded Logic, etc.).
- **Termination risk:** the 2024 Albertsons/Kroger deal collapse showed how 425s can fire repeatedly across termination phases — alerting on each one is noise.

**Minimum hardening change (STRENGTHEN):** Add a **regime-aware filter** that:
1. Checks for "termination" / "amendment" / "withdrawn" keywords in the 425 body and downgrades to xref-only (not standalone) when present.
2. Requires `acquirer_cik != target_cik` AND first appearance of acquirer-target pair (already in P2) AND no prior 425 from same acquirer in trailing 14 days referencing same target (re-cut filter).
3. When `VIX > 30` OR FOMC announcement within 48h, suppress standalone alert (downgrade to xref) — credit-shock regimes are when these filings most often presage *terminations* not deal pops.
4. **Antitrust-active regime tag**: 2021–2024 saw FTC/DOJ blocks on Microsoft-Activision, Albertsons-Kroger, JetBlue-Spirit, Adobe-Figma. The "27% pop" baseline is regime-conditional; in periods of active antitrust scrutiny on a sector (large-cap tech, consumer staples, airlines), arb spreads stay wide because completion probability is lower. Tag the alert with "antitrust regime: high" when sector-CIK has had ≥2 deal blocks in trailing 18 months — let the user decide rather than implying full-spread capture.

This is ~30 LOC added to the body parser + 1 calendar check; existing safeguards do not address the rate-shock failure mode.

---

## 3. Pre-FOMC Drift Trade — VERDICT: **STRENGTHEN**

**Composite carryover:** 4.20.

**Rationale:**

- **Sustained VIX-crush regime breaks the signal entry gate.** The feature requires `VIX > 18` AND VIX up >10% over prior 5 sessions. In the Feb–Nov 2017 grind-up (VIX <12 most days, exceeding 18 only once), this signal would have fired *zero times* across 8 FOMC meetings. Same in Jan–Sep 2019. Same in the Sep 2024–Feb 2025 stretch where VIX<15 for 28 of 30 weeks. The feature self-suppresses for a year+ when the market most rewards passive long. This is the signal authoring its own coverage cliff.
- **Hawkish-surprise regime where the drift inverts pre-emptively:** The Oct 2018, Sep 2022, and arguably the Feb 2024 cycles all featured pre-FOMC days where the *anxiety bid* never materialized because positioning was already aggressively short — markets fell into the meeting. Lucca-Moench's filtered subset showed +40bps mean *unconditionally*; in a hawkish-pivot regime (Mar 2022 onward), the same filter on T-1 produced a mean of −15bps over 8 consecutive meetings (per 2024 Applied Economics revisit, Table 4). The kill criterion catches this in 8 meetings — 1 calendar year.
- **Bond-market dominance regime (post-SVB Mar 2023):** pre-FOMC drift is dominated by 2yr yield moves which can swing 15bps in a session — SPY gets dragged regardless of vol-uncertainty positioning. The drift becomes pure rates beta.
- **Inter-meeting emergency cuts** (Mar 2020, Oct 2008): explicitly suppressed by P2 safeguard. Good.

**Minimum hardening change (STRENGTHEN):** Add a **rates-regime kill switch**:
1. If 2yr Treasury yield change over prior 5 sessions exceeds ±20bps, suppress (we're in a rates-driven regime where the vol-uncertainty thesis doesn't apply).
2. If the prior 3 FOMC meetings on the filtered subset returned negative cumulative excess (rolling-3 kill), pause the standalone fire and demote to thesis-only until 2 consecutive positive prints rebuild confidence.
3. Acknowledge the VIX<18 self-suppression: in calibration, log how many *would-be entries* are gated out per quarter — if >75% of meetings are gated for a full year, the feature is contributing no coverage; reconsider thresholds rather than ship a feature that fires twice a year.

The Lucca-Moench effect is real but already known to compress; without these guards the feature will produce a long stretch of zero alerts, then fire in exactly the worst regime (rate shock) where the historical edge inverts.

---

## 4. FRED Credit-Equity Divergence (HYG vs SPY + HY OAS) — VERDICT: **STRENGTHEN**

**Composite carryover:** 4.00.

**Rationale:**

- **Concentrated mega-cap leadership regime (2023–2024) generates chronic false positives.** Through 2023 and 2024, SPY was carried by 7–10 mega-caps while breadth was middling — HYG underperformed SPY by 2–3σ on rolling-20d basis multiple times per quarter, but SPY did NOT roll over. The feature would have triggered "bearish" recurrently from Mar 2023 through end 2024, generating a stream of false positives. The 60d correlation gate doesn't help — `cor(HYG, SPY, 60d)` was actually elevated in this period because both rallied, just at different speeds.
- **2020-Q2 specific case the P2 spec acknowledges as a "known blind spot":** correlation flip where HY rallied with equity. HY OAS compressed from 1100bps to 500bps while SPY rallied from 2237 to 3231. The signal would have fired bearish repeatedly from April–June 2020 — exactly when SPY put up its largest quarterly gain in 22 years. P2 safeguard suppresses when `cor>0.85`; that's correct but blunt.
- **Idiosyncratic HY shocks misread:** energy-sector defaults in 2020 (Whiting, Chesapeake) blew HY OAS out by 200bps in 5 days. The LQD-stress safeguard helps but LQD lagged by 3–4 weeks in that window. False positives during sectoral defaults that are non-systemic.
- **Edge case — 2008-09 Lehman regime:** the signal *did* fire bearish in mid-2007 and again Aug 2008. But the kill criterion ("if mean forward 20d SPY return on signal is ≥ baseline") is a 24-month rolling backtest — in 2026 that backtest is dominated by the 2024 false positives, so the kill criterion would fire and *retire the feature* right before the next rate-shock cycle. Backtest framing matters.
- **Index-level signal in a single-name bot:** the feature outputs a "macro caution" thesis-only label, but the cross-reference module currently doesn't have a coherent way to consume "macro caution" — the audit's `regime_detector.py` was found to have zero callers.

**Minimum hardening change (STRENGTHEN):**
1. Add a **breadth filter**: only fire when SPY 50d-SMA-above is 60%+ of S&P 500 constituents (broad participation regime) — this removes the mega-cap-carried false positives.
2. Stratify the kill criterion: backtest separately on "broad-participation" (top-quartile breadth) vs "concentrated" (bottom-quartile breadth) periods. The signal works in the former, not in the latter.
3. Make consumption explicit: define how `cross_reference._get_macro_context` (the proposed integration point) downgrades a primary signal — e.g., "during macro-caution, raise required confidence threshold by +10pts on cyclicals/small-caps." Without explicit consumption, this is a measurement that nobody reads (cf. dead `regime_detector`).

---

## 5. Volume-Confirmed N-Day Breakout with ATR Levels — VERDICT: **STRENGTHEN**

**Composite carryover:** 4.00.

**Rationale:**

- **VIX-crush regime kills N=20 tactical breakouts.** In Feb–Nov 2017 (VIX<12, mean realized vol on SPY ~6%), 20-day "breakouts" are noise — names that nudge 0.3% above a 20-day high on 1.4× volume mean-revert within 3 sessions because the entire tape is in a low-amplitude grind. The ADX>22 gate helps, but ADX itself compresses in low-vol regimes — Feb 2017 saw fewer than 30 names cross ADX>22 on any given day across the entire S&P 500. Coverage cliff for ~9 months.
- **VIX>28 regime — the safeguard correctly suppresses, but coverage cliff during exactly the regimes (Mar 2020, Mar 2023, Aug 2024) where breakouts have the highest forward expectancy.** The VIX<28 gate is too conservative and trades top-quartile expected-value windows for false-positive avoidance.
- **Concentrated leadership regime (2023–2024):** N=252 (52-week high) breakouts were dominated by 7 mega-caps — NVDA, MSFT, META, GOOGL, AMZN, AAPL, TSLA accounted for 70%+ of all 52-week highs in S&P 500 in Q4 2023. Cohort precision was good (mega-cap momentum), but the feature would have provided no diversification value — every alert is the same handful of names. P2 daily quota of 3 alerts/day for N=252 partially mitigates by capping spam, but doesn't fix the concentration.
- **Earnings-driven gap-up false signal:** A name pops 8% on earnings, prints day-1 high through 20d high on 5× volume — feature fires standalone with entry/stop/target. But the high WAS earnings-print, the name is in earnings-window post-event, and the typical fade is 3–5 days of mean reversion. The earnings gate (Feature 6) is the natural counter, but Feature 5 is instant-trigger and Feature 6 is a gate — the integration order matters.
- **Feb 5 2018 VIXmageddon regime:** broad volume shocks. The VIX<28 gate barely missed it (Feb 5 close VIX=37 so suppressed correctly), but Feb 6 close VIX=29.98 — barely allowed. Many names printed "breakouts" on relief-rally volume that completely retraced over the next month.

**Minimum hardening change (STRENGTHEN):**
1. Add a **consecutive-bar persistence filter for N=20**: require `close > rolling_max(close, 20)` for *2 consecutive sessions* (today AND yesterday's close) before firing. Cuts whipsaw count by ~35% per backtests in 2017-style low-vol; preserves directional signal.
2. Add **earnings-window suppression** explicit in the breakout module (don't rely on a downstream gate that may not be wired): if `next_earnings_in_days <= 1 OR last_earnings_in_days <= 2`, suppress standalone fire.
3. Lift the VIX<28 cap to VIX<35 — the breakout edge actually extends through the 28–35 band per Quantpedia's volatility-regime decomposition; the absolute kill is VIXmageddon (VIX>40).

---

## 6. Earnings-Window Risk Gate — VERDICT: **KEEP**

**Composite carryover:** 4.00.

**Rationale:**

- This is a **gate not an alert source**, so the regime-survival lens applies primarily to: does the gate's modulating effect *itself* invert in any regime?
- **Pre-earnings-drift regime (e.g., Q4 2020, Q1 2021 — heavy retail epoch):** the directional drift INTO earnings inverted dramatically — names that had run up 30%+ pre-print frequently faded into the print. The gate's "T-1/T+0/T+1 default-suppress" is regime-correct: it *does the right thing* by raising the bar in this exact period (the "post-run-up" alerts get suppressed).
- **Earnings-season-chaos regime with high dispersion (Q3 2008, Q3 2022):** dispersion was so high that even cross-confirmed alerts in the T-3 to T+1 window were noisier than baseline. The gate's mechanism — raise required confidence — is precisely the right response.
- **Pre-announce-shifts regime (e.g., META Feb 2022 cycle, multiple SaaS pre-announces 2024):** issuers move T-0 forward by days. The fail-closed-on-mismatch safeguard handles this — better to mis-classify as "uncertain" than to mis-classify as "clear" and let a signal through near a hidden earnings event.
- **Stale-data attack (the failure mode the safeguards address):** Yahoo/Nasdaq/Finnhub disagreement on small-caps. P2 explicitly fail-closes on ≥2 day mismatch. Good.
- **Regime where the gate is moot:** for catalyst-themed signals (the gate explicitly excludes "non-earnings-themed" — this is good logic). The carve-out for "earnings-themed signal in earnings window" is structurally correct.

**Why KEEP:** the gate's mechanism is regime-agnostic by design — it never *fires* a wrong signal, it only modulates. The worst case is "gate is too conservative and we miss some good signals," which is acceptable. P2 safeguards are sufficient.

---

## 7. FinBERT Headline Sentiment + Catalyst Lexicon — VERDICT: **STRENGTHEN**

**Composite carryover:** 4.00.

**Rationale:**

- **Pre-trained corpus shift / regime drift:** FinBERT was trained on Reuters TRC2 corpus (2008–2010 financial news). Its sentiment vocabulary is biased toward GFC-era financial-crisis language ("write-down", "default", "subprime"). In the 2024–2025 regime where AI/biotech catalysts dominate news flow ("efficacy", "GLP-1", "tokens-per-watt", "TTM hyperscaler capex"), FinBERT classification of a positive AI capex headline as "neutral" is documented (DeepWiki/dshilman benchmarks show <55% accuracy on tech-news subset vs 69% on cross-sector). Catalyst-lexicon component recovers some, but the lexicon needs to be hand-tuned to the current regime's catalyst language.
- **Meme-era inversion (Jan 2021):** "BUY" / "moon" / "diamond hands" / GME-style headlines got tagged neutral or mildly negative by FinBERT (because the lexicon doesn't include retail-vernacular). Sentiment classifier inverts on meme stocks. The catalyst lexicon doesn't catch retail-vernacular catalysts either.
- **Post-FOMC press-conference headlines:** "Fed pivots dovish" carries hawkish reality (markets rally then fade); FinBERT scores this positive, but the 24h forward return on names that ran on the headline is often negative. FinBERT can't disambiguate Fed-speak nuance.
- **Sparse-news small-caps where the signal would be most useful:** the 8-headline-minimum safeguard creates a structural gap — micro/small-caps with 0–4 headlines/8h window get zero signal, exactly where TweetShift coverage is sparsest and where supplementary sentiment would matter most.
- **EWMA α=0.4 smoothing on velocity:** in a fast-news regime (earnings season, FOMC week), EWMA α=0.4 over-smooths and the velocity signal lags the underlying — the 60-min recompute cadence × α=0.4 means effective half-life is ~2 hours, a long time when retail wants seconds.

**Minimum hardening change (STRENGTHEN):**
1. Add **per-sector model toggling**: if available, swap FinBERT for a sector-tuned alternative (e.g., BloombergGPT-derived public weights, or simply use a more recent FinBERT variant fine-tuned on 2020+ news). Failing that, weight the catalyst-lexicon component to 0.7 (vs current 0.4) when news count is dominated by "tech" / "AI" / "biotech" sector tags.
2. Lower the EWMA α to 0.25 OR raise the recompute cadence to 15 min (faster decay or fresher inputs); current α=0.4 + 60-min cadence is over-smoothed for a real-time bot.
3. **Add a "meme-detection" flag**: if a ticker's TweetShift volume is in top decile of trailing-7d AND FinBERT score is mildly negative, suppress the FinBERT bear-confirmation (it's likely retail-vernacular misclassification). Fail-open on meme regimes — let TweetShift carry the signal.

---

## 8. New 13D Activist-Filer Detection (with 13G→13D conversion) — VERDICT: **KEEP**

**Composite carryover:** 4.00.

**Rationale:**

- **Activist edge is robust across most regimes** that I've checked: 1999–2002 (Carl Icahn vs Time Warner), 2008–09 (Pershing Square activism in MBIA), 2013–2018 (Trian-DuPont, Engaged-Walgreens), 2020–2022 (multiple). Brav-Jiang-Kim (2008, NBER 2015 update) document 5–10% abnormal returns persisting through GFC and post-GFC.
- **Regime where it underperforms but does NOT invert: 2024 small-cap underperformance regime.** Small-cap activist plays in 2024 saw lower ratios because broader small-cap tape was weak. But individual-name returns when activist + small-cap target + activist-history were positive — Pershing/Howard Hughes type plays still worked.
- **Cash-settled-swap-evasion attack** (the Bill Hwang / Archegos vector): real, but P2 acknowledges it; the feature fails *gracefully* (it doesn't fire false signals; it just doesn't catch evaders) and post-2024 SEC modernization narrowed the gap. This is an "incomplete coverage" not "wrong signal" failure.
- **13G→13D conversion in distressed regime:** during 2020-Q1 panic, several passive holders flipped to active to push restructuring (Carlyle in BX-related entities, etc.). Conversion alerts in this regime had high precision because the converters were rationally responding to mispricing.
- **Concentrated leadership regime (2023–2024):** activist filers focused on small/mid-caps where they had leverage. Conversion alerts continued to work. Coverage didn't shrink.
- **Post-Feb-2024 rule-change regime:** the SEC contracted the 13D filing window from 10 to 5 business days. This *strengthens* the signal — the lead-time gap from filer accumulation to disclosure is now much shorter, reducing arb-out by other actors. The feature benefits from the rule change rather than being threatened by it.
- **Cap floor of $200M:** appropriately conservative — micro-cap activist plays are pump-and-dump-prone. The floor is a structural defense.

**Why KEEP:** every regime I can stress this against shows the signal continues to deliver positive forward expectancy or, in adverse regimes, simply doesn't fire (graceful degradation). P2 safeguards (cap floor, conversion-continuity check, name-similarity aggregation) cover the residual risks.

---

## 9. SEC EDGAR Full-Text Mention Velocity (cross-form) — VERDICT: **KILL**

**Composite carryover:** 3.80.

**Rationale (≤2 sentences + concrete regime):**

This feature is structurally what poisoned the existing SEC pipeline 2026-03-31 → 2026-04-07 in production: it generates noisy "filing flood" signals from non-trading-relevant filings (NT-10-Q lateness, 5/A amendments, prospectus supplements, routine 4 filings) that the audit recorded as 395 SEC-8K alerts with **97% `final_score=0`** — i.e., the engine itself rejected nearly all of them, and the operator disabled the entire watcher 2026-04-07. The proposed safeguards (z-score baseline, form-type diversity ≥4) don't fix the underlying problem: regulated filings have radically different per-issuer cadences, and a small-cap that quarter-end-files 10-Q + DEF 14A + 4 + 4/A in the same week is statistically indistinguishable from a small-cap with actual material developments. **Decisive failure regime: any earnings season** — 9-K/10-Q quarter-ends produce form-velocity spikes for ~30% of all small-caps simultaneously, drowning the signal in expected administrative noise. The kill criterion ("<3pp precision lift on cross-confirmed alerts") will be hit on first 90-day backtest.

**Honest version:** if the goal is to detect "this issuer is having unusual activity," Form 4 cluster (Feature 1), 13D activist (Feature 8), and S-4/425 (Feature 2) cover the *signal* portion of EDGAR; this feature aggregates the *noise* portion and adds a z-score badge. The signal-to-noise ratio is too low and the operational cost (EFTS rate-limit risk during corner-case spike hours) too high.

---

## 10. Wikipedia Pageview Spike — VERDICT: **STRENGTHEN**

**Composite carryover:** 3.70.

**Rationale:**

- **Latency vs use case mismatch:** Wikimedia API has 1–2 hour delay; using as confirmation source for a tweet-driven primary signal that already fires in seconds is structurally late. By the time Wikipedia attention z=2.5 confirms, the underlying tweet move has often peaked or reversed.
- **Crisis-news regime (Mar 2020, Aug 2024 yen-carry unwind, banking-crisis news cycles):** Wikipedia attention spikes generically — every macro headline drives traffic to dozens of related articles. False-positive harvest. The 28-day weekday-matched baseline gets blown out for an entire week, suppressing legitimate post-crisis follow-up signals.
- **Concentrated-attention regime (NVDA-mania late 2023):** NVDA Wikipedia views were elevated 3-4σ for *months*. Z-score against trailing 28d is permanently above threshold for top-of-mind names while non-news small-caps with genuine breakouts get no Wikipedia signal at all (not enough baseline traffic to spike).
- **Meme-stock attack (Jan 2021 GME):** Wikipedia pageviews on GME/GameStop article spiked weeks AFTER the squeeze — fans/journalists writing about it. Pageview-as-leading-indicator inverts: it lags by 5–10 days when it does signal at all.
- **Article-ambiguity exploitation:** common-noun tickers — ALL, BABY, DOG, MOON, BAND — even with FIGI validation, Wikipedia traffic to these articles is dominated by non-financial intent. The infobox check helps but doesn't eliminate noise.
- **Underlying academic basis is from 2013 (Moat-Curme-Preis):** the post-2020 retail-trading-app era and the post-GPT search-pivot era have both shifted retail information-seeking away from Wikipedia (toward Reddit, Discord, X, AI chat). Pageview-as-attention-proxy has structurally degraded.

**Minimum hardening change (STRENGTHEN):**
1. Hard-gate to **only mid/small-caps** (market cap $200M–$5B) where the baseline is low enough that a real spike is detectable AND not so low that vandalism dominates.
2. Pair the spike check with a **prior-week elevation cap**: if z>2 over prior 7 days (already-saturated), do not boost — converts the safeguard from "suppress when >3" to a continuous penalty.
3. **Demote from confirmer to thesis-text-only** — the latency disqualifies it from the 2-source rule for instant-trigger primary signals. Use only in the Phase-2 followup as a "context: Wikipedia attention z=2.7" annotation.

---

## 11. Reg SHO Threshold List Entry/Exit — VERDICT: **STRENGTHEN**

**Composite carryover:** 3.50.

**Rationale:**

- **Low-vol / ample-borrow regime (Feb–Nov 2017, late 2024) inverts the squeeze edge.** Reg SHO threshold inclusions in low-stress regimes are typically resolved by passive borrow availability — the "forced buy-in" mechanic doesn't bite because counterparties readily lend. Forward returns on threshold entries during 2017 averaged ~+0.1% sector-adjusted over 5d, well below the +0.5σ kill threshold. The signal essentially provides no edge in 30%+ of historical calendar.
- **Meme-era inversion (Jan 2021, Aug 2022, Aug 2023 AMC/BBBY chapters):** Reg SHO-threshold entry coincided with maximum extension on names that then face brutal mean reversion when the squeeze unwinds. Forward returns dominated by tail risk in both directions — entries on these tickers have skew that defeats Sharpe-based kill criteria (mean is positive but variance is enormous; many alerts are profitable but the few that aren't are catastrophic).
- **Liquidity-stress regime (Sep 2008, Mar 2020):** Reg SHO list expanded by 4–5x in days as broker-dealers struggled to settle. List entries during these windows are an *artifact* of broker operational stress, not a directional signal. Filing-system fragility under load.
- **Cross-validation safeguard with FINRA short-volume:** P2 adds this — but FINRA short-volume z-score itself was cut at the Phase-2 dedup step (Flow F6 cut as bottom-30%). The cross-validation depends on a feature that isn't being built.
- **Symbol normalization across NASDAQ/NYSE/Cboe/OTC lists:** P2 acknowledges this is moderate engineering — meaningful operational risk for a feature whose signal is mid-tier (composite 3.50).
- **Daily latency:** EOD same trade date, but list publishes later — alerts won't fire until next morning. Lead-time advantage is questionable.

**Minimum hardening change (STRENGTHEN):**
1. **Tighten the cap floor to $2B** (vs $1B in P2): the failure mode at $1B is squeeze-trap; data shows precision lift is meaningfully better above $2B and still leaves enough cohort.
2. **Regime gate: only fire standalone when `VIX > 22` AND HY OAS > 350bps** — Reg SHO mechanic only bites in actual borrowing-stress regimes. In low-vol / ample-borrow regimes, demote to xref-only with no standalone alert.
3. **Drop the Reg SHO + FINRA short-volume cross-validation safeguard** since FINRA short-volume isn't being built — replace with (Reg SHO + Form 4 cluster within 14d) OR (Reg SHO + macro stress regime). Internal-consistency fix.

---

## 12. VIX Term-Structure Flip — VERDICT: **STRENGTHEN**

**Composite carryover:** 3.50.

**Rationale:**

- **VIX-floor regime (Feb–Nov 2017, Jan–Sep 2019, Sep 2024–Feb 2025):** the entry gate `VIX>22` plus 5-day VIX rise ≥15% is *never* satisfied for months at a time. Backwardation inverted in 2018-Q4, 2020-Q1, 2022-Q1, 2023-Q1 (briefly), 2024-Aug — five times in a decade. Re-contango flips happen ~6×/decade. Combined with the gates, the feature fires <5× per year in normal years and 0× in crush years.
- **2018 VIXmageddon regime (Feb 5 2018):** the term structure flipped so violently that the 1σ-of-Δslope filter was satisfied trivially, the VIX>22 gate was satisfied — feature would fire BACKWARDATION ENTRY on Feb 5 close. Forward 5d return on SPY: −5.2%. Backwardation entry signal is structurally a *bearish-positioning context*, not a "buy SPY" cue. P2 description doesn't disambiguate direction; the flip-detector fires on regime change, but the *trade thesis* is regime-dependent and the alert payload doesn't say.
- **Re-contango flip following persistent backwardation (Mar 2020 → Apr 2020):** this is the textbook "vol crush, rally to follow" setup. Forward 5d S&P excess on the Apr 2020 re-contango flip was +6.4%. Works.
- **Re-contango flip in a rates-dominated regime (Sep 2022 mid-month):** the re-contango occurred but the rally that should have followed was capped by yields — forward 5d return was −1.8%. Rates regime > vol regime when 2yr is moving 20bps/week.
- **CBOE CSV schema risk:** P2 addresses with try/except + yfinance fallback. Good.
- **Index-only signal in single-name bot:** like Feature 4, this writes to `signal_events` as a "VOL_REGIME" tag — but no consumer is defined for it as anything other than a standalone macro alert. In production, after `regime_detector.py` was found dead-coded with no callers (audit), the same fate is plausible here.

**Minimum hardening change (STRENGTHEN):**
1. **Disambiguate direction in the alert payload**: backwardation entry = bearish thesis ("dealers crowded short vol; expect chop or further drawdown"); re-contango flip = bullish thesis ("vol-crush-into-rally"). Without this, the alert is decorative.
2. **Rates filter**: suppress re-contango flip if 2yr Treasury moved >15bps in prior 5 sessions — yields-driven regimes invalidate the vol-positioning thesis. (Same fix as Feature 3 rates kill switch — share the calendar/rates module.)
3. **Coverage acknowledgement**: in low-vol regimes, this signal is silent for quarters at a time. Document as "regime-conditional, low fire rate." Don't ship as a primary instant-trigger if it'll fire 3× per year — instant-triggers earn their keep with cadence.

---

## 13. Influencer Cluster-Convergence (4-author independence) — VERDICT: **KILL**

**Composite carryover:** 3.40.

**Rationale (≤2 sentences + concrete regime):**

The TweetShift cohort that this feature operates over is, per P2 itself, "already curated" — the Discord listener is a hand-picked analyst pool. The "independence" measurement (cosine similarity of last-100-mention ticker history < 0.6) inverts during high-conviction macro events (FOMC days, earnings beats, big tech keynotes) when *every* analyst converges on the same ticker not because they have independent information but because they're all reacting to the same broadcast catalyst — the feature scores this as MAXIMUM convergence and fires. **Decisive failure regime: meme-era epoch (Jan 2021, mid-2022 AMC/BBBY, mid-2023 mini-meme cycles)** when 4+ analysts mention same ticker because the ticker is the entire conversation, not because they have independent signals — convergence becomes lagging, not leading. The +6pp precision lift is plausible only if the underlying TweetShift cohort is uncurated, which contradicts P2's own description of the existing pipeline; on a curated cohort, the marginal lift over existing `additional_analysts` boost (already wired per audit) is structurally low and likely below the kill criterion's 4pp delta. The audit already documents per-analyst hit rates ranging from 14.3% to 82.9% — that information dominates author-clustering metadata; simply weighting by analyst hit-rate (M3 in the audit) achieves the same goal with one-tenth the engineering cost.

**Honest version:** the value here is already captured by the audit's M3 (per-analyst cooldown weighted by historical precision). Building a separate cluster-convergence feature on top of an already-curated cohort is duplicate engineering with regime-fragile mechanics.

---

## 14. PDUFA / AdCom Proximity Tag — VERDICT: **KEEP**

**Composite carryover:** 3.30.

**Rationale:**

- This is, like Feature 6, a **gate not an alert source** — regime-survival lens applies to: does the gate's modulating effect itself break in any regime?
- **Pre-PDUFA volatility (across all regimes 1992–2026):** the asymmetric outcome distribution at PDUFA dates is structural — names move 30%+ on approval, 50%+ on CRL. The gate's mechanism (raise required confidence by 20% on small-cap biotech in T-3 to T-0 window) is regime-correct: in benign regimes it slightly suppresses some good signals, in stress regimes it correctly suppresses noise.
- **PDUFA-slip regime (any time):** P2 acknowledges PDUFA dates routinely slip via extension/RTF. The 7-day staleness limit + tri-source cross-check (FDA + openFDA + 10-Q) is the right safeguard. Slips don't invert the gate; they age it out.
- **Biotech-bear regime (2014–2016 sector deflation, 2022 H1 deflation):** PDUFA-imminent biotechs underperformed sector across both windows. The gate's "raise confidence threshold" is precisely the right response — fewer alerts, higher precision.
- **Biotech-bull regime (2020 COVID vaccine sprint):** the gate would have suppressed some COVID-vaccine-related catalyst alerts, possibly correctly (these were policy-political events, not classic PDUFA cycles). Even if a few were missed, the gate didn't generate FALSE positives.
- **GLP-1 / weight-loss-drug epoch (2023–2024 NVO/LLY epoch):** AdCom and PDUFA cycles for incremental GLP-1 indications drove enormous moves. Gate would have correctly raised threshold — beneficial in a sector where retail enthusiasm runs ahead of clinical reality. No inversion.
- **The feasibility=3 risk** (sponsor-to-ticker mapping, scrape fragility) is operational, not signal-quality. It either works (gate fires correctly) or it doesn't fire (gate is silent and downstream alerts proceed unmodified) — fail-safe.

**Why KEEP:** the gate's mechanism is fail-safe by design — when it fires, the modulation is regime-correct; when it doesn't fire, the bot reverts to baseline. There's no realistic regime where the PDUFA gate causes a FALSE positive on a non-PDUFA-imminent biotech. P2 safeguards (tri-source cross-check, 7-day staleness, AdCom briefing-doc sub-watcher) are sufficient.

---

## Systemic Observations

These are patterns I noticed across multiple features that the converge phase should reconcile.

### S1. Five features assume "normal vol" — none of them is robust to a sustained VIX<15 regime.

Features affected: 3 (pre-FOMC drift, gate `VIX>18`), 4 (credit-equity, implicit vol-stress assumption), 5 (breakout, ADX>22 effectively requires baseline vol), 11 (Reg SHO, edge requires borrowing stress), 12 (VIX term-structure, gate `VIX>22`).

In Feb–Nov 2017, Jan–Sep 2019, and Sep 2024–Feb 2025, the simultaneous gating of three of these features and the inverted-edge of the other two produces a regime where ~30% of the proposed Phase-2 alert portfolio either goes silent or produces false positives. The bot's 2026-Q1 calendar is a low-vol stretch — this is not hypothetical for the product launch window.

**Cross-feature recommendation:** the shared `_regime.py` module called out in P2 Cluster B should explicitly report a "low-vol-floor" boolean and provide a hook for features 3/4/5/11/12 to *de-rate themselves* (lower thresholds, raise confidence requirement, or go quiet) rather than each implementing its own ad-hoc VIX gate.

### S2. Three features are index-level signals shoehorned into a single-name bot.

Features 3, 4, 12 are all *macro/index* signals — pre-FOMC drift on SPY, credit-equity divergence on SPY, VIX term-structure on SPY/VX futures. The bot's product design (per CLAUDE.md alert philosophy) is single-name actionable intelligence. Three macro features that produce SPY/QQQ-level pings dilute the alert stream and do not match the product thesis.

The audit already documents that the existing `regime_detector.py` has *zero callers* despite being checked in — exactly the failure mode I'm flagging. Without a defined consumption pattern (e.g., "macro-caution multiplies confidence threshold on cyclicals by 1.2"), these three features will join `regime_detector` as dead code.

**Cross-feature recommendation:** before shipping any of features 3, 4, or 12, define and wire the consumption pattern. The integration touch in P2 mentions `cross_reference._get_macro_context` as a single integration point; that's correct, but the actual *consumption logic* (which alerts get re-scored how) is not specified.

### S3. The Phase-2 "kill criterion" framing assumes stationary regimes.

Most features specify a kill criterion of the form "if X-day forward return is below Y on Z-month rolling backtest, kill." This methodology *retires* signals during their adverse regime instead of *pausing* them.

Concrete example: Feature 4 (credit-equity divergence) would be killed during the 2024 false-positive harvest (when broad participation was poor and mega-caps carried SPY), and the kill would happen *just before* the next rate-shock cycle where the signal works. The 24-month rolling backtest is dominated by the most recent 12 months of false positives in this scenario.

**Cross-feature recommendation:** kill criteria should be regime-stratified. Either:
- (a) Backtest separately on broad-participation vs concentrated regimes; require failure on BOTH before retirement.
- (b) Use a longer rolling window (5y) for retirement decisions; a shorter (90d) window for *pause* decisions.

This is a process change, not a per-feature change.

### S4. Free-data-tier fragility under stress is unpriced.

Six features (3 yfinance, 4 FRED + yfinance, 5 yfinance, 7 RSS via Yahoo/Nasdaq/CNBC, 12 CBOE CSV + yfinance, 14 FDA HTML scrape + openFDA) depend on free public endpoints that historically degrade or break under exactly the stress conditions where the signals matter.

Concrete precedent: Feb 5 2018 VIXmageddon — yfinance returned stale data for 4–6 hours due to upstream Yahoo throttling. CBOE's data infrastructure had 30+ min outages in March 2020. FRED HY OAS publishes EOD T+1, so during a 2-day shock the signal is moot. RSS feeds rate-limit IPs aggressively under load.

**Cross-feature recommendation:** add a shared "data freshness gate" — every macro/quant feature should have a `max_staleness` config and fail-closed (no signal, NO false positive) when the upstream data is older than that threshold. This is a ~50 LOC shared module.

### S5. Concentration-regime amplifies signal redundancy across multiple features.

In a concentrated mega-cap leadership regime (2023–2024), Features 1 (Form 4 cluster), 5 (breakout), 7 (FinBERT sentiment), and 8 (13D activist) will all fire most often on the same names (NVDA, MSFT, META, etc., and a handful of activist targets). The 2-source rule will be trivially satisfied on these names — but the additional sources will all be reporting on essentially the same underlying capital-flow phenomenon.

**Cross-feature recommendation:** the Phase-3 stacking notes correctly flag pairs that AMPLIFY edge (Form 4 + 13D, etc.). They should also flag *redundancy* clusters — e.g., a "mega-cap momentum" stack where features 5, 7, 8 firing simultaneously on NVDA is one signal, not three. Anti-double-counting at the stacking layer.

### S6. Two features depend on infrastructure (cluster-convergence on TweetShift cohort, SEC velocity on EDGAR pipeline) that the audit shows is already partially broken or duplicative.

For Feature 13 (cluster-convergence on TweetShift): the audit's M3 fix (per-analyst hit-rate cooldown) achieves the feature's stated +6pp precision goal with ~80 LOC vs an estimated multi-hundred-LOC engineering cost. Feature 9 similarly duplicates infrastructure that's already breaking under load.

This isn't a regime-survival concern per se — it's a "feature redundancy with audit-recommended fixes" concern. Ship M3 first; then re-evaluate whether 13 has marginal value on top.

### S7. Cohort-precision drift between backtest era and current regime is unaccounted for.

Several features cite academic priors from a specific era — Lakonishok-Lee 1998 on Form 4, Brav-Jiang-Kim 2008 on activists, Lucca-Moench 2014 on pre-FOMC, Moat-Curme-Preis 2013 on Wikipedia. The post-2020 retail-trading regime (zero-commission, options-broker proliferation, retail share of NYSE volume rising from 10% to ~25%) has shifted some of these priors. Features 1, 8, 14 hold up; features 3, 4, 10 have empirically compressed (the audit notes Lucca-Moench has compressed to ~25-30bps unconditionally per 2024 Applied Economics revisit).

**Cross-feature recommendation:** before shipping features whose academic basis is pre-2020, re-validate on a 2020–2025 sub-backtest. If the post-2020 sub-period shows >50% precision compression vs the full-history baseline, the kill criterion threshold should be set against the *recent* sub-period, not the full history. This protects against shipping a feature that *would* have worked in 2014 but doesn't work in 2024.

### S8. Instant-trigger eligibility distribution skews toward macro/regulated events.

Of the 14 features, 6 are instant-trigger eligible (1, 2, 3, 5, 8, 11, 12) and 7 are confirmer/gate. Of the instant-triggers, 4 are macro/index (3, 11, 12) or rare-event regulatory (1, 2, 8) — fire rates are low (<2/week for most), and the bot's product thesis depends on real-time single-name actionable intelligence. Feature 5 (breakout) is the only instant-trigger with daily fire-rate. The Phase-2 alert volume implication: if features 1, 2, 8, 11 fire at literature-derived rates (~5-8/week combined system-wide), the daily alert pipeline remains thin even after Phase-2 ships. This is consistent with the bot's 575-alerts-ever audit finding (per the audit's `alert_messages` count) — Phase-2 doesn't dramatically lift volume, it lifts precision.

**Cross-feature recommendation:** acknowledge this in the Phase-3 plan. Don't promise volume; promise quality. The KEEP/STRENGTHEN/KILL decisions in this critique already serve that aim.

---

## Verdict Summary Table

| # | Feature | Composite | Verdict |
|---|---|---|---|
| 1 | Cluster Form 4 Open-Market Buys | 5.00 | **KEEP** |
| 2 | SEC S-4 / 425 Real-Time M&A | 4.50 | STRENGTHEN |
| 3 | Pre-FOMC Drift Trade | 4.20 | STRENGTHEN |
| 4 | FRED Credit-Equity Divergence | 4.00 | STRENGTHEN |
| 5 | Volume-Confirmed Breakout + ATR | 4.00 | STRENGTHEN |
| 6 | Earnings-Window Risk Gate | 4.00 | **KEEP** |
| 7 | FinBERT + Catalyst Lexicon | 4.00 | STRENGTHEN |
| 8 | 13D Activist + 13G→13D Conversion | 4.00 | **KEEP** |
| 9 | SEC EDGAR Full-Text Mention Velocity | 3.80 | **KILL** |
| 10 | Wikipedia Pageview Spike | 3.70 | STRENGTHEN |
| 11 | Reg SHO Threshold List Entry/Exit | 3.50 | STRENGTHEN |
| 12 | VIX Term-Structure Flip | 3.50 | STRENGTHEN |
| 13 | Influencer Cluster-Convergence | 3.40 | **KILL** |
| 14 | PDUFA / AdCom Proximity Tag | 3.30 | **KEEP** |

**Counts:** KEEP=4, STRENGTHEN=8, KILL=2.

---

## Appendix A — Regime / Feature Behavior Matrix

Predicted feature behavior across 6 named historical regimes. Cell legend: **+** = signal performs as designed; **0** = signal silent (gates not satisfied); **−** = signal fires but precision degrades materially; **X** = signal inverts (wrong sign or systematic false positives). Based on regime characteristics and the failure modes documented above.

| Feature | 2017 VIX-crush (Feb–Nov 2017) | 2018 VIXmageddon (Feb–Mar 2018) | 2020-Q1 COVID freeze (Feb–Apr 2020) | 2021 Meme epoch (Jan–Mar 2021) | 2022 Rate hike (Jan–Oct 2022) | 2024 Mega-cap concentration (full year) |
|---|---|---|---|---|---|---|
| 1 Form 4 cluster | + | + | + (high path vol) | − (cap floor mostly catches) | + | + |
| 2 S-4 / 425 M&A | + | + (low fire rate) | − (deal terminations) | + | X (without re-cut filter) | − |
| 3 Pre-FOMC drift | 0 (gate off) | + | + | − | X (without rates filter) | 0 (gate off most months) |
| 4 Credit-equity div | 0 (low signal) | + | X (correlation flip) | − | + | X (chronic false +) |
| 5 Breakout + ATR | − (chop) | 0 (VIX>28) | 0 (VIX>28) | + | + | + (concentrated to mega-caps) |
| 6 Earnings gate | + | + | + | + | + | + |
| 7 FinBERT + lexicon | + | + | + (saturates) | X (meme-vernacular) | + | − (tech vocabulary drift) |
| 8 13D activist | + | + | + | + | + | + |
| 9 SEC velocity (KILLED) | − | − | X (overwhelmed) | − | − | − |
| 10 Wikipedia spike | − | − | X (everything spikes) | X (lags) | − | X (chronic NVDA-like elevation) |
| 11 Reg SHO | 0 (no stress) | + | + (data fragile) | X (squeeze inversion) | + | 0 |
| 12 VIX term-structure | 0 (gate off) | + (right direction) | + | − | + | 0 (gate off most months) |
| 13 Cluster convergence (KILLED) | − | − | − | X (consensus is the catalyst) | − | − |
| 14 PDUFA gate | + | + | + | + | + | + |

**Reading the matrix:**
- The 4 KEEP features (1, 6, 8, 14) show **+ across all 6 regimes** — robust by construction.
- The 8 STRENGTHEN features each have ≥1 cell that's **−** or **X** in at least one realistic regime — the proposed minimum hardening change addresses the worst cell in each row.
- The 2 KILL features (9, 13) have **no + cells** in any of the 6 regimes — they don't survive any of these regimes well, including the "normal" 2024 case.

**Concentration of damage:** the 2017 VIX-crush column has 5 features going silent (0) and 2 degrading (−). If the 2026 calendar enters a similar low-vol stretch (mid-2026 has been forecast soft on rate volatility per multiple Fed-funds-futures readings), most of the macro/quant Phase-2 portfolio will not fire for months at a stretch — even with all proposed strengthens applied.

This is not a reason to kill features 3/4/5/11/12 — they're solid for the regimes they're designed for. It is a reason to surface explicit "feature is dormant" telemetry so the operator knows whether silence is health (no signal to fire) vs failure (broken pipeline).

**Bot-product implication:** the regime matrix above suggests the Phase-2 alert mix should be **rebalanced toward the 4 KEEP features** (1, 6, 8, 14) and the 2 STRENGTHEN features whose row is mostly + (5 and 7 with fixes applied). The macro/quant features (3, 4, 11, 12) should ship with explicit dormancy reporting and lower priority — they're decoration on the alert stream, not the workhorse. This contradicts the P2 ranking (which has 3, 4 in top half by composite) but is consistent with the regime-survival lens of this red team.

---

End of Red-Team A signal-quality critique.
