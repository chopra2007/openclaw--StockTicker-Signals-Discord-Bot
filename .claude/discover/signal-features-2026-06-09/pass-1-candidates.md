# Pass 1 — Candidate Features (unfiltered merge: internal audit + external research)

This is the wide-net candidate list. Pass 2 filters/dedups/ranks; Pass 3 stress-tests + cross-model;
Pass 4 plans. Two sources feed it:

- **Internal** (no new data — fix dead/wrong logic or use data already pulled): full detail in
  [`pass-1-internal-audit.md`](pass-1-internal-audit.md). Summarized below as I1–I18.
- **External** (deep-research, cited): E1–E6 below. Every external claim carries its verification
  status. **deep-research hit an account session limit mid-verification** — items marked
  *unverified* abstained on the session limit (3 abstain), they were NOT refuted.

---

## Internal candidates (I1–I18) — no new data source

Source-grounded against Pass 0. Full mechanism/module/kill-switch in `pass-1-internal-audit.md`.

| # | Candidate | Tier | One-line mechanism | Touches |
|---|---|---|---|---|
| I1 | **Sign the YouTube boost** (flip `youtube_score` flags ON) | quick-win | bearish YT consensus must SUBTRACT, not add; sign/decay/trust code already exists, byte-identical when off | `consensus.yaml:745-747` |
| I2 | **Weight analysts by `rolling_accuracy`** | quick-win | replace flat +20 with `20×clamp(acc,0.3,1.5)`; proven analyst worth more | `cross_reference.py:483` |
| I3 | **Wire live `contradiction_index` producer** (revive dead A1) | medium | compute directional disagreement across already-gathered sources; penalty + bar light up | `cross_reference.py` (producer) |
| I4 | **Reconcile the two scorers** — show the gated number | medium | display `min(xref,precision)` or single calibrated score; weak alerts stop looking strong | `main.py:1255-1290`, `discord.py:447` |
| I5 | **Graduate SEC by role + open-market $** | medium | +8/+15/+20 by size & C-suite, ≤0 on net selling; data already parsed | `cross_reference.py:236,485` |
| I6 | **Sign + scale options by premium + side** | medium | $5M directional sweep ≠ tiny far-dated contract; put-wall on a long subtracts | `cross_reference.py:487` |
| I7 | **Scale `consensus_boost` by Bayesian log-odds** | medium | cluster QUALITY (priors), not just count, drives the cap-60 term | `consolidation.py:163-178` |
| I8 | **Wire herding `effective_size` into score** | medium | trusted-analyst swarm finally adds points (correlation-discounted) | `main.py:1156`, `models.py` |
| I9 | **Reconnect the inert `min_base_score_for_alert` knob** | quick-win | one-line: read the YAML key instead of hardcoded `>=20` | `main.py:1066` |
| I10 | **Require a hard-evidence component for STRONG** | quick-win | crowd-only stacks cap at WATCHLIST until a catalyst/SEC/technical/options confirms | `engine.py:262` |
| I11 | **LLM-fallback catalyst classification** | medium | reuse the existing scorer call to label catalysts the 19 substring lists miss | `llm_scorer.py`, `cross_reference.py:528` |
| I12 | **Magnitude-scaled earnings beat/miss** | quick-win | +5 per 10% surprise (cap +15); blowout ≠ in-line | `cross_reference.py` catalyst path |
| I13 | **ApeWisdom mention-count z-score gate** | medium | +10 only when mentions >2σ over the ticker's own 30-day baseline, not on bare presence | `social.py:205`, `cross_reference.py:97` |
| I14 | **Surface regime z-score as risk context + sharper STRONG widening** | quick-win | show the macro-risk read; scale the panic widening by how far z exceeds `panic_z` | `discord.py`, `engine.py:247` |
| I15 | **Recency + size weighting in Wolf confluence** | medium | decay stale votes, scale by $ size; let SEC vote bear on net selling | `wolf_confluence.py:146-163` |
| I16 | **Benchmark-adjust Wolf outcomes** | quick-win | credit "moved_with" only if proxy beat SPY (already pulled), not if it merely rose | `wolf_outcomes.py:144` |
| I17 | **Activate isotonic calibration gating** (≥50 graded rows) | moonshot | route trained P(up) into the STRONG/WATCHLIST gate, not just display; shadow first | `consensus.yaml:377`, `engine.py:228-277` |
| I18 | **Populate the dead reliability render block** | medium | set freshness/verdict/top-drivers from data on hand; lights up `discord.py:402-424` | `cross_reference.py`, `discord.py:402` |

**Dependency note:** I3 (contradiction producer) + I4 (reconcile scorers) are prerequisites for I18
(reliability block) and the honest Phase-2 skip text. I17 (calibration gating) should land AFTER I4
so the calibrated probability operates on one coherent score.

---

## External candidates (E1–E6) — deep-research, cited

### E1 — FINRA Daily Short-Volume ingester → short-volume-%-of-total confluence signal
- **Status:** data fact VERIFIED 3-0 (FINRA primary docs). Free, public, keyless, posted ≤6 PM ET same day, per-ticker `total_volume` + `short_volume` → short-%-of-total directly computable.
- **Evidence the signal leads price:** Boehmer-Jones-Wu-Zhang (*Review of Finance* 2020, VERIFIED 3-0): a 1-SD rise in prior-week shorting → ~3.8 bps/day lower returns next 2 days, persists ~1 month; heavier shorting appears the **week before** negative earnings, downgrades, forecast cuts. Refs: newyorkfed.org Boehmer PDF; academic.oup.com/rof/article/24/6/1203; FINRA daily-short-sale-volume-files.
- **DECISIVE caveat (verified):** the academic edge uses **proprietary NYSE order-level** short data. Free FINRA short **VOLUME** ≠ short **INTEREST/position**; it's inflated by market-maker hedging and is off-exchange-only. Kelley & Tetlock: *retail* short flow does NOT predict returns. → A free-data bot captures a **weaker, noisier** version. Weight as a **confluence input, never a standalone trigger; never display/score it as "directional short selling."**
- **Mechanism:** new `scanners/finra_short_volume.py` ingester → daily short-%-of-total + its 30-day z-score per ticker → small cross-reference confluence term, signed bearish only on a surge **confirmed by another source**; surfaced as risk context.
- **Tier:** Medium. **Module:** new scanner + `cross_reference.py` scoring + reliability weighting.

### E2 — Cross-asset regime layer (FRED + yfinance) → confirm/veto confidence multiplier
- **Status:** VIX-term-structure + credit-spread mechanisms are HIGH-tier in the cross-asset deep-read; the FRED-API access fact abstained on the session limit (unverified, but FRED is a known free official source). See `.omc/research/cross-asset-vol-term-structure-findings.md`.
- **Mechanism (precision-first framing — CONFIRM/VETO, not a new alert generator):** one `cross_asset` module computing a market-wide regime score from free data:
  - **VIX term structure** VIX/VIX3M backwardation (>1.0) = near-term stress flag (`^VIX`,`^VIX3M` on yfinance, or FRED VIXCLS). HIGH tier (Macrosynergy). *Directional-conditional — backwardation precedes positive S&P drift; easy to invert. Use as regime flag, not predictor.*
  - **HY credit divergence** HYG/LQD ratio falling while SPY makes highs = credit withdrawing confirmation, ~4-6wk lead at inflections; FRED `BAMLH0A0HYM2`. HIGH tier (Gilchrist-Zakrajšek AER 2012 / Fed EBP). *Market-wide filter, not per-ticker.*
  - **Risk-on/off** DXY + copper/gold + yields agreement (yfinance). MEDIUM. *Confirm/veto only — correlations break in acute stress.*
- **Use:** multiply an already-triggered **bullish** alert's confidence DOWN when the cross-asset backdrop is risk-off / backwardation / deteriorating-credit. Raises precision without new standalone alerts. Feeds the existing `regime_classifier`.
- **Tier:** Medium (the veto layer) → Moonshot (full cross-asset module). **Module:** new `analysis/cross_asset.py` + FRED client + `regime.py`/`engine.py` input.

### E3 — Gamma-exposure (GEX) / dealer-positioning level from yfinance chains
- **Status:** blog/practitioner-grade (SpotGamma); OSS reference `github.com/Matteo-Ferrara/gex-tracker` (verified as a fetched source). Not peer-reviewed for "leads price."
- **Mechanism:** compute net dealer gamma from the option chain the bot **already pulls** (yfinance) → the "gamma flip" level (below it, dealer hedging amplifies moves; above it, dampens). Surface the flip level as dynamic support/resistance + a volatility-regime hint in `!all`/levels.
- **Tier:** Medium/Moonshot. **Module:** new `analysis/gamma.py` (lift gex-tracker math) + `options.py` chain reuse + `!all` embed. **Risk:** dealer-positioning sign assumptions are model-dependent; label clearly as a heuristic.

### E4 — Options-flow calibration correction (folds into I6)
- **Status:** VERIFIED. Pan & Poteshman (NBER w10925): the -53 bps/no-reversal edge is from **proprietary signed open-buy** P/C. A specific *public* P/C "predicts >40 bps next day" claim was **REFUTED 0-3**; public/tape-inferred P/C reverses within 1-2 days.
- **Action (not a standalone feature):** when wiring I6, cap the free options signal's **horizon** (intraday/1-2 day confluence) and never let public P/C inherit the academic edge in scoring or thesis text. Merge as a constraint on I6.

### E5 — LLM bull/bear debate + critic/reflection loop for thesis synthesis *(unverified lead)*
- **Status:** UNVERIFIED (abstained on session limit). TradingAgents (`github.com/TauricResearch/TradingAgents`) bull-vs-bear debate + reflection/memory loop; FinCon (`arxiv 2407.06567`) manager-analyst hierarchy + "Conceptual Verbal Reinforcement" critic loop.
- **Mechanism:** for high-conviction theses (Wolf / HIGH-conviction tweets), run a structured bull-case/bear-case pass + a critic before posting, instead of a single thesis call. Aligns with the bot's existing LLM thesis layer and the discover/ultracode pattern.
- **Tier:** Moonshot, unverified. **Module:** `llm_scorer.py` / Wolf thesis path. **Re-verify before building.**

### E6 — Adversarial input-integrity defense *(unverified lead)*
- **Status:** UNVERIFIED (abstained). `arxiv 2512.02261`: injecting fabricated/coordinated counterfeit narratives into an agent's news/social feeds measurably degrades returns (return 11.59%→5.26%, Sharpe 4.34→3.20) — the **exact attack surface** a tweet/Reddit/YouTube-ingesting bot faces.
- **Mechanism:** coordinated-burst / duplicate-narrative detection on the ingest (many near-identical posts in a short window = suspicious), down-weight rather than reward. Partially overlaps I3 (contradiction) — but I3 catches *disagreement*, this catches *manufactured agreement*.
- **Tier:** Medium, unverified. **Module:** ingest path (`discord_tweetshift.py`/`social.py`) + `cross_reference.py`. **Re-verify before building.**

---

## Redundancy pre-flags (for Pass 2 to confirm against Pass 0)
- ApeWisdom as a *source* already exists (ON) — E-side ApeWisdom value collapses into **I13** (count z-score), not a new source.
- The bot already has unusual-options-flow, max-pain, peer RS, regime classifier, Form-4 clusters, calibration *infra* — so E4 is a **correction**, not new; E2 *extends* the existing regime classifier rather than replacing it.
- Short **interest** (point-in-time) is already pulled via yfinance snapshot; **E1 is short-VOLUME FLOW** (daily velocity), a genuinely different, currently-absent stream.
