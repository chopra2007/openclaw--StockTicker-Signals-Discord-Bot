# Cross-model review brief — signal-features-2026-06-09

You are giving a SECOND OPINION on a filtered set of upgrades for a **signal-first retail
stock-alert Discord bot** (Python). Design goal: **precision over recall** (2 great alerts beat
15 mediocre), **free/near-free data only**, **catch setups before mainstream news / r/wallstreetbets**.
A 5-pass analysis (system map → audit → filter → adversarial+re-verify) already ran. Full detail is in
two files in this workspace you SHOULD read: `.claude/discover/signal-features-2026-06-09/pass-2-filtered.md`
and `.../pass-3-adversarial.md`. Below is the refined feature set after Pass-3.

## The refined feature set (post-adversarial verdicts)

Internal fixes (no new data — fix dead/wrong logic or use data already pulled):
- **I1** Sign the YouTube boost (today a *bearish* YouTube consensus RAISES a long score; flip existing flags ON). *build-with-changes: require channel-age + ≥10 graded outcomes before trust counts.*
- **I2** Weight analysts by track record (rolling_accuracy) instead of flat +20. *build-with-changes: Wilson lower-bound, n≥10 floor, wire shadow-grading of un-alerted signals, notional cap vs accuracy-farming.*
- **I3** Compute the live `contradiction_index` (today hardcoded 0 → the "sources disagree" downgrade + warning bar are dead). *build-with-changes: count opposing sources by ACTOR identity, not source type; ≥2 distinct actors before downgrade.*
- **I4** Reconcile the two scorers — show the gated number, not the inflated additive sum the user currently reads. *build-with-changes: explicit "confidence degraded: budget" state, no silent revert to the higher number.*
- **I5** Graduate SEC insider scoring by role + open-market $ (today flat +15 for a $10M CEO buy or a routine award). *build-with-changes: absent 10b5-1 flag → cap +8, no negative branch; recency on transaction date.*
- **I6** Scale options by premium size, same-direction confluence only. *build-with-changes: DROP the opposing/negative branch (public options side-inference is refuted); aligned nudge only.*
- **I7** Scale the consensus boost by calibrated Bayesian log-odds, not raw cluster count. *build-with-changes: concrete I7↔I8 de-correlation + regression test.*
- **I8** Wire the analyst-swarm (herding) size into the score. *build-with-changes (safeguards rated "no" otherwise): treat unknown pairwise correlation as HIGH not zero, else a fresh coordinated ring scores full weight. Without the fix, DROP.*
- **I9** Reconnect the inert `min_base_score_for_alert` knob (one line; documented dial currently does nothing). *clean.*
- **I10** Require a hard-evidence component (catalyst/SEC/technical/options) for a STRONG alert; crowd-only caps at WATCHLIST. *build-with-changes: gate the high-conviction carve-out on track record, not base_score≥30.*
- **I11** LLM-fallback catalyst classification for catalysts the substring matcher misses. *build-with-changes + HIGH security fix mandatory: prompt-injectable via news body — delimiter-isolate, +8 cap, verbatim-quote, second-source corroboration.*
- **I12** Magnitude-scale earnings beat/miss (today flat tier). *clean-ish: absolute-$ floor + freshness gate + cap +15.*
- **I13** ApeWisdom mention-count z-score gate (today fires on bare presence). *build-with-changes: actor-independent + hard corroborator (Reddit surges ARE the pump vector).*
- **I14** Surface the regime z-score as risk context + sharper STRONG widening in panic tape. **BUILD (clean, no change).**
- **I15** Recency + size weighting in Wolf confluence votes. *build-with-changes: critical @-ping needs actor-independence + ≥1 non-controllable source.*
- **I18** Populate the dead reliability/freshness/verdict render block. **DEFER until I3+I4 ship hardened.**

External adds (free data, all narrowed to confluence/veto, never standalone triggers):
- **E1** FINRA free daily short-VOLUME confluence modifier. *build-narrowed: free edge is weak/MM-hedging-contaminated (Kelley-Tetlock); confluence-only, net out exempt column.*
- **E2** Cross-asset regime confirm/veto (VIX term structure + HY-credit + risk-on/off via FRED+yfinance) multiplying an already-triggered bullish alert's confidence. *build-with-changes: symmetric ≤1.15 up-cap; FRED leg behind its own flag; VIX leg shadow-first.*
- **E3** Gamma-exposure (GEX) flip level as a labeled heuristic hint in `!all`. *build-narrowed: regime label only, no precise number (incremental info collapses after controlling for VIX); suppress flips outside 50–200% of spot.*
- **E6** Manufactured-agreement / coordinated-burst gate (the bot ingests public tweets/Reddit/YouTube — a real, cited attack surface). *build-narrowed: gate on account-diversity/coordination, never suppress the underlying signal, reconcile with I3.*
- **DROPPED: E5** (LLM bull/bear debate) — unverified + amplifies hallucination on a tight free LLM budget.

## What I want from you (be concise, Gemini quota is small)

For the SET as a whole and for any feature you feel strongly about, answer:
1. **Keep:** which features are the highest-value, do-first wins for *precision over recall* on a free-data retail bot?
2. **Drop:** which features, if any, would you DROP or further defer even though the analysis kept them — and why? (Especially: is I8 worth the coordinated-ring risk? Is E3/GEX worth it given the incremental-info collapse? Is I11 worth the prompt-injection surface?)
3. **Hidden risks:** name any material risk, failure mode, or interaction the 5-pass analysis did NOT already cover (it already covered: wrong-sign bugs, survivorship loops, thin-sample noise, actor-vs-type source independence, prompt injection, budget-day degradation, regression-gate/flag-off discipline). Only NEW risks.
4. **Sequencing:** any change to the build order? (Current: Wave1 I9/I12/I16/I14-display; Wave2 I1/I2/I5/I6/I8/I7; Wave3 I3/I10/E6; Wave4 I4/I14-widen/E2; Wave5 I18.)
