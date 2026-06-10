# Pass 3 — Stress-Tested Feature Set (signal-features-2026-06-09)

Combines: the adversarial + external re-verification + security review (full detail in
[`pass-3-adversarial.md`](pass-3-adversarial.md)) with the cross-model (ccg) second opinion below.

---

## A. Cross-model synthesis (ccg)

**Models consulted:** Claude (the 5-pass analysis) + **Gemini** (gpt-class second opinion).
**Codex was UNAVAILABLE this run** — its auth token is revoked (`refresh_token_invalidated`, needs an
interactive `codex login` only the user can do). Per the ccg fallback, we proceed with Gemini + Claude and
flag the missing OpenAI-perspective lens. Gemini's raw artifact is in `.omc/artifacts/ask/gemini-*.md`.

### Agreement matrix

| Topic | Claude 5-pass | Gemini | Verdict |
|---|---|---|---|
| Top do-first wins | I1, I9 top composite; I3/I4/I10 high-value gates | I3, I10, I1+I9, I4 | **AGREE** — these are the core build |
| **I8** analyst-swarm | critic rated safeguards **"no"** (fresh ring scores full weight) | **DROP** (herds form after alpha; ring risk > reward) | **AGREE → DROP** |
| **E3** GEX | re-verify: incremental info collapses after VIX; build-narrowed | **DROP** (redundant after VIX; noisy free data) | **AGREE → DROP** |
| **I11** LLM catalyst | build-with-changes + only HIGH security item | **DEFER** (+8 not worth injection surface; I5/I12 catch real catalysts) | **AGREE → DEFER** |
| Sequencing of I4 | reconcile LAST (after component fixes) | move display-honesty to Wave 1 | **RECONCILED** — split I4 (see below) |

**Single-model-support flags (the riskiest per the discover rule):**
- The **time-basis-skew / "phantom confluence"** risk (§B-new) is **Gemini-only** — not raised by any Claude
  pass. Treated as a real new finding and promoted to a cross-cutting safeguard (it's a concrete, checkable
  mechanism, not a vague worry), but flagged here as single-model-support.
- **No Codex lens** this run — any item resting only on Claude's analysis lacks the third model's check.
  The build mitigates this structurally: everything ships flag-OFF + shadow-first + kill-switch, so a
  single-model miss surfaces in shadow before it gates live alerts.

### NEW risk from ccg (promoted to a cross-cutting safeguard)

**Time-basis skew → "phantom confluence."** The bot mixes near-instant data (SEC filings, tweets) with
high-lag free data (FINRA daily short volume = EOD; daily-crawled YouTube/ApeWisdom). A naive confluence/
contradiction computation can pair a 12-hour-old short-volume spike with a 1-minute-old SEC buy and fire a
"perfect" alert for a move that already happened 6 hours ago — un-tradeable.
**Cross-cutting safeguard (applies to I3, I13, I15, E1, E2):** every multi-source computation must tag each
contributing signal with its **data-as-of timestamp** and apply a **common-recency-window rule** — a leg
older than its source's freshness cap either does not count toward confluence or is explicitly down-weighted
and labeled stale. No "phantom confluence" across mismatched time bases. This generalizes the existing
per-source `freshness_max_age` config to the *cross-source* layer.

---

## B. Final stress-tested feature set (what goes into the plan)

House rule on every item: **flag-OFF default · shadow-first · kill-switch wired · regression-gate clean.**
Each item carries its Pass-3 required change (the safeguard that makes it safe to build).

### BUILD — Wave 1 (clean / low-blast-radius, ship first)
- **I9** Reconnect inert `min_base_score_for_alert` knob. *+ shadow volume-preview log of would-suppress-at-25/30.*
- **I12** Magnitude-scaled earnings beat/miss. *+ absolute-$ surprise floor + sane-denominator guard + freshness gate + cap +15.*
- **I16** Benchmark-adjust Wolf outcomes (recap-only). *+ scope-aware benchmark (sector ETF vs SPY, sign-aware for inverse) + show raw AND adjusted.*
- **I14-display** Regime z-score risk-context line in the embed (the display half only; widening deferred to Wave 4). *+ "warming up" label when regime is in cold-start identity.*
- **I4-display-honesty** *(moved early per Gemini)* Stop printing the inflated additive sum; show the precision-gated number, and on a budget-depressed day render an explicit "confidence degraded: budget" state — **never silently revert to the higher number.** *Requires a per-source skipped-for-budget flag (build it first if absent).* The deeper single-score merge stays in Wave 4.

### BUILD — Wave 2 (per-source scoring corrections — the verified wrong-sign fixes)
- **I1** Sign the YouTube boost (flip flags ON). *+ turn `channel_reliability` ON in the same change + min-2-trusted-channel floor before a bearish subtraction + channel-age & N≥10 graded-outcome requirement before trust counts + cap negative magnitude below positive + null-timestamp→stale guard + add `features.youtube_score.*` to the conftest force-off fixture.*
- **I2** Weight analysts by `rolling_accuracy`. *+ Wilson lower-bound (not raw ratio) + n≥10 sample floor + 0.5 discount floor + verify/wire shadow-grading of UN-alerted signals (or drop the recovery claim) + base-rate/per-call notional cap vs accuracy-farming.*
- **I5** Graduate SEC by role + open-market $. *+ when 10b5-1/plan flag is ABSENT → cap at +8 (no +20 tier, no negative branch) + net-selling withholds the buy credit but never subtracts + canonicalize role strings + recency gate on TRANSACTION date.*
- **I6** Scale options by premium, same-direction confluence ONLY. *+ DROP the opposing/negative branch entirely (public side-inference is refuted by E4) + magnitude-cap low + staleness gate + narrator forbidden from "smart money" framing (regression assertion on the horizon attribute).*

### BUILD — Wave 3 (contradiction + hard-evidence gates — depend on Wave-2 signs)
- **I3** Live `contradiction_index` producer. *+ count opposing sources by INDEPENDENT-ACTOR identity (one actor across twitter+options = one source) + require ≥2 distinct actors before the ≥0.5 downgrade + downgrade-not-veto, floored + abs-magnitude math guard, clamp [0,1], NaN→0 + common-recency-window (no stale leg counts) + flag-gated + shadow.* Depends on I5/I6 signs existing.
- **I10** Require a hard-evidence component for STRONG. *+ gate the "before-mainstream" carve-out on analyst TRACK RECORD (I2 Wilson-LB), not base_score≥30 + distinguish absent-vs-unfetched (don't demote on budget-skip) + technical must be ≥2 filters to count.*
- **E6** Manufactured-agreement / coordinated-burst gate. *+ gate on ACCOUNT-DIVERSITY/coordination (distinct origins, near-simultaneous timing, templated wording, no price corroboration), NEVER suppress the underlying signal — only withhold the crowd-agreement bonus + reconcile with I3 in one pass (corroboration-before-contradiction).* After I3.
- **I13** ApeWisdom mention-count z-score gate. *+ confirm-only (independent corroborator required) + the corroborator must be ACTOR-independent and preferably hard/non-manipulable (SEC/earnings/technical) + ≥14-day baseline before any z-credit + new numeric column (db tripwire: migrate+backfill+flag-OFF-returning-0 until backfilled).*
- **I15** Recency + size weighting in Wolf confluence. *+ critical @-ping "independent source" defined by ACTOR identity + require ≥1 non-actor-controllable source before size-weighting escalates to critical + per-source percentile cap + reuse I5's 10b5-1 exclusion for the SEC-bear vote + age-decay-with-floor.* After I5.

### BUILD — Wave 4 (reconciliation + display + cross-asset — land last among scoring)
- **I4-full** Single-score reconciliation (feed xref components into the precision engine / coherent merge). *After I1/I2/I5/I6/I7 so the reconciled number reflects corrected components.*
- **I7** Scale `consensus_boost` by calibrated Bayesian log-odds. *+ reuse I2's hardened accuracy primitive + preserve the cold-start-zero contract verbatim + blend with a low count-floor (saturation can't erase independent-cluster info).* (I7↔I8 de-correlation requirement is MOOT now that I8 is dropped — simpler.) After I2.
- **I14-widening** Graduated panic STRONG-cutoff widening. *+ cap the widening (max +15, ceiling ~90, never disable STRONG) + exempt high-conviction longs + reconcile with E2 into ONE bounded cutoff adjustment.*
- **E2** Cross-asset regime confirm/veto multiplier. *+ use as a regime FLAG not a directional predictor (avoids the verified VIX-backwardation wrong-sign trap) + symmetric caps (veto ≥0.85 floor AND confirm ≤1.15 ceiling) + VIX-term leg (yfinance ^VIX/^VIX3M) shadow-first + FRED/HY-credit leg behind its OWN flag pending FRED-access verification + hard-coded series IDs + FRED key via header not query-param.*
- **E1** FINRA daily short-VOLUME confluence input. *+ confluence-only, never standalone, never rendered as "directional short selling" (fixed provenance label: "short-volume %, MM-hedging-inflated proxy") + net out `ShortExemptVolume` + EOD-staleness tag + common-recency-window rule + new scanner + db series (tripwire: migrate+backfill+flag-OFF until backfilled) + response-size cap + allow_redirects=False + domain re-validation + dtype-pinned parse.*

### DEFER (documented in the plan as staged follow-on, NOT built this run)
- **I18** Reliability render block — DEFER until I3 + I4 ship hardened AND pass an **adversarial-input** shadow window (not just outcome-accuracy). A wrong authoritative verdict block is worse than a blank one.

### DROPPED (cross-model + adversarial converged against)
- **I8** Analyst-swarm herding — Gemini DROP + critic safeguards "no" (fresh coordinated ring scores full weight; `co_post_rate=0` on no-history pairs). Marginal reward (≤15) not worth the coordinated-ring surface, and herding rewards the crowded/late signal — against the "before-mainstream" goal.
- **E3** Gamma-exposure (GEX) — Gemini DROP + its own re-verify showed incremental info collapses after controlling for VIX (rho −0.36 → −0.03, p=0.18); free EOD chains are coarse; wrong flip-level is the NVDA-850 error class.
- **I11** LLM-fallback catalyst — DEFERRED (Gemini: +8 not worth the prompt-injection surface; real catalysts already fire via I5/I12). If revived later, the HIGH security fix (delimiter-isolation + `<news_body>` untrusted-data instruction + +8 cap + verbatim-quote + second-source corroboration + `defusedxml`) is mandatory before it ships.
- **E5** LLM bull/bear debate — dropped in Pass 2 (unverified + amplifies hallucination on a tight free LLM budget).

---

## C. Net result

**14 features BUILD** (Waves 1–4), **1 DEFER** (I18), **3 DROP/DEFER** (I8, E3, I11), 1 prior drop (E5).
The cross-model pass tightened the set — dropping the two riskiest-for-marginal-reward items (I8, E3) and
deferring the only HIGH-security item (I11) — which is the correct move for a precision-over-recall bot.

**Realistic edge of the surviving set:** it stops the bot from *actively scoring against itself* (bearish
YouTube raising a long; put-walls adding points; track-record-blind analyst weighting; crowd-only STRONGs;
a confidence number that doesn't gate), surfaces the contradiction/freshness context the trader needs, and
adds two free *confirmation/veto* layers (cross-asset regime, short-volume) that raise precision without new
standalone noise. **What it does NOT solve:** it cannot manufacture a proprietary-data edge from free feeds
(short-volume and public options are weak, confluence-only); it does not add a fundamentally new *alert
generator* (by design — precision over recall); and the calibration-gating moonshot (I17) and reliability
block (I18) remain staged for after the scoring is coherent.

**Security gate carried into the plan:** the only HIGH item (I11 prompt-injection) is deferred with the
feature; the medium items (defusedxml for RSS, header-not-query-param + RedactingFilter extension for
Finnhub/FRED keys, FINRA size-cap/redirect guard, GEX NaN/zero-strike filter — GEX now moot) are folded into
their features' build steps.
