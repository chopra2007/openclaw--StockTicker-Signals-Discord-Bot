# RESEARCH MISSION — How do practitioners actually detect equity-index tops & bottoms accurately?

You are a research analyst. Do NOT start coding. Your job is a fact-finding mission, then a plan,
then an adversarial review of that plan. We have already spent significant effort and hit a wall;
we do not want to reinvent the wheel. Find how OTHERS have actually achieved this, then design a
better path grounded in what demonstrably works for them.

## THE GOAL (clear and concise)
Detect US equity-index (SPY / QQQ) **tops and bottoms early — before the move — with FEW false
alarms.** Concretely: flag an intermediate **top** ahead of a ≥8% peak-to-trough drop (within ~60
trading days), and a **bottom** ahead of a ≥8% rally, firing *during* the turning window, not after.
The detector must have a **real, out-of-sample-validated edge with a low false-positive rate** — not
an in-sample curve fit. No look-ahead. (The ≥8% / ~60-day figures are our working definition of an
"intermediate" turn; if a different but still economically meaningful event definition or horizon
makes the problem more tractable or more accurate, propose it and justify it — see SCOPE below.)

## HARD CONSTRAINT — DATA COST (non-negotiable, read this first)
- **NO paid services of any kind.** Zero budget. No subscriptions, no one-time purchases, no
  metered/credit APIs, no "just $X/month," no "cancel after one pull." If it costs money, it is out.
- **Free trials are acceptable — but ONLY when confirmed on two points:** (a) the trial is real and
  actually obtainable by us (not a "contact sales / request a demo" black box), AND (b) it delivers
  the **historical depth** needed for whatever honest out-of-sample test your method requires — not
  just live/forward data from the sign-up date onward. A trial that only streams data *forward* is
  useless for backtesting. State the trial length and whether validation can realistically finish
  inside it.
- **If the only approach with a demonstrated real edge requires paid data with no qualifying free
  trial, do NOT propose it as the build.** Still report it (we need to understand what the edge truly
  requires and how much signal lives behind a paywall), but mark it **explicitly out of scope**, and
  then either (i) propose the best FREE / qualifying-free-trial alternative, or (ii) conclude an
  honest NO-GO under the free-only constraint. Do not soften a paywalled answer into a free one.

## SCOPE — stay open; do NOT inherit our setup as a requirement
Everything below under "DATA WE USED" and "HOW WE BACK-TESTED" describes **what we happened to do** —
it is context, **not a specification you must match.** In particular:
- **No fixed history length.** We are NOT requiring "15+ years of daily data or nothing." An approach
  that works on a shorter span, a longer free archive, a different market with usable history, or even
  a regime-specific window is welcome — the test just has to be genuinely out-of-sample and honest.
- **No fixed data granularity.** Daily was our choice. Intraday, tick-level, weekly, or event-driven
  data are all on the table if free (or free-trial-viable) and if they make the signal clearer. Our
  single biggest difficulty was the **tiny event count** (~7–12 usable tops in a 16-year daily sample);
  an approach that *sidesteps* that — e.g. more events from intraday data, from more indices, from a
  longer free archive, or from a graded/continuous target instead of a binary one — is exactly the kind
  of new idea we want.
- **No fixed event definition.** Binary "≥8% within 60 days" was ours. A continuous severity target, a
  different threshold/horizon, or a hazard/survival framing are all acceptable if they are economically
  meaningful and pre-registered before scoring.
- **The only non-negotiables are the honesty principles** (no look-ahead, genuine out-of-sample
  evidence, a fair null, robustness across assets/regimes, raw counts, pre-registration) — NOT the
  specific window, granularity, or sample we used. Optimize for *accuracy and low false positives*,
  and choose the data and validation design that best serve that — then justify the choice.

## THE LEADING HYPOTHESIS WE TESTED
A real top (outside a sudden news crash) is a multi-week **distribution phase**: range-compression /
churn near the highs, market breadth narrowing, up-volume drying up on the rally, and a vol-of-vol
(VVIX) shift versus spot vol (VIX) as price rolls over — no single sign, the *combination and its
timing*. Bottoms are the mirror: a capitulation **climax** (panic, VIX spike, snap-back).

## WHAT WE TRIED
- **Single signals (16):** VIX level & term structure, VVIX, realized vol, RSI / trend-extension,
  equal-weight-vs-cap-weight breadth (RSP/SPY, QQQE/QQQ), credit spread (Moody's BAA−10Y), SKEW,
  TLT safe-haven, distribution/accumulation (OBV + Bollinger-width + near-high).
- **The multi-signal confluence:** breadth-narrowing *gate* + range-compression + near-high +
  up-volume-shrink, with variants adding a price-break trigger, a beta-adjusted VVIX-vs-VIX residual,
  and a genuine advance/decline "Absolute Breadth Index" leg.
- **A two-stage model:** detect the distribution-watch *state*, then require a price break *inside* it.
- **A continuous composite score** (geometric mean of each component's trailing percentile) to avoid
  brittle on/off thresholds and use far more data points.
- **Bottoms:** capitulation + VIX-extreme + VVIX-rollover + snap-back, plus an intraday VIX-reversal.
- **The free option/breadth/flow tier we already exhausted (all NO-GO under our honesty bar):**
  variance-risk-premium (VRP), Zweig breadth thrust and Lowry 90/90 on *true* NYSE up/down volume,
  dealer-gamma exposure (GEX) and dark-pool index (DIX) from SqueezeMetrics' free series, and CBOE
  put/call ratios. None of these added a validated edge — so a new plan must NOT simply re-propose them.

## DATA WE USED (free; this is context, not a requirement)
SPY/QQQ/RSP/QQQE/HYG/LQD/TLT OHLCV (dividend-adjusted, yfinance); VIX/VIX3M/VVIX/VXN/SKEW; FRED BAA10Y
credit spread (long history); a free broad-US advance/decline breadth feed (thetrading.tools); free
true-NYSE up/down volume (a multi-decade archive, frozen 2020) and forward-collected NYSE breadth; free
SqueezeMetrics GEX/DIX (2011+); free CBOE put/call ratios (2019+). Mostly daily granularity. You are
not bound to these instruments, this granularity, or this span.

## HOW WE BACK-TESTED (the honesty *principles* any new plan must respect — the specifics are ours, adapt them)
- **Point-in-time only:** a feature at day *t* uses only data ≤ *t* (we enforced this with a truncation
  test: the value computed on the full series must equal the value computed on the prefix up to *t*).
- **Look-ahead-safe entry:** signal on the close, enter at the next bar's open, measure forward.
- **Episodes:** collapse repeated same-side alerts within a short window to one event (we used 20 days).
- **Target events (our setup, and our core pain point):** a running-peak drawdown scan finds independent
  ≥8% tops — only **~12 in our 2010–2026 daily sample** (~10 excluding the 2020 COVID and 2025 tariff
  news-crashes; ~7 are slow "distribution" tops). **This tiny event count was the central difficulty,
  and a better approach is encouraged to overcome it** (more events via finer granularity, more markets,
  a longer free archive, or a graded target) rather than accept it.
- **Edge = conditional precision/hit-rate vs the unconditional base rate AND vs a random-timing null.**
- **The decisive upgrades (from a cross-model review — keep the principle, adapt the specifics):**
  1. **Opportunity-set null** — the random-timing comparison draws only from *eligible* "watch" days
     (e.g. near-the-highs), not all days, because the signal only fires where the event is already
     more likely. (Comparing to all days is too easy and inflates the apparent edge.)
  2. **Out-of-sample hold-out** — discover on one period, confirm cold on a later one (we used 2010–2021
     discover / 2022–2026 confirm; pick whatever split fits your data and justify it).
  3. **Robustness transfer** — apply the exact frozen parameters to a *different* asset or regime with
     NO re-tuning; failure there exposes overfitting. For us, **cross-asset transfer to QQQ has been the
     persistent killer** (Phase-2 edge −0.028, Phase-3 +0.024, dealer-gamma +0.268 at p=0.064 — the
     closest miss). Any new method must show it generalizes beyond the data it was tuned on.
  4. **Leave-one-episode-out**, a **multiple-testing reality check** across a small *frozen* grid, and
     **raw counts reported, not just percentages.**
  5. **Pre-registration frozen before scoring.**

## WHAT DID NOT WORK (results)
- Single signals: no demonstrable edge (kill-gate fail).
- The binary confluence: best top precision +12 percentage points over base, but only p≈0.13 against
  the opportunity-set null (not significant). An earlier "+13pp / p=0.03" was inflated by an artifact
  leg (raw VVIX/VIX slope) and by using a too-easy all-days null.
- **Cross-asset transfer to QQQ was NEGATIVE** — the strongest evidence the S&P result was overfit.
- The continuous composite score: rank-correlation with future drawdowns ≈ **−0.09 across 3,815 days
  (p≈0.85)** — essentially zero, with full statistical power (so "too few examples" is not the cause
  *for that particular test*).
- Two-stage watch→break: +8–10pp on the S&P but not significant and did not transfer to QQQ.
- The bottom detector's high apparent precision was an artifact of the base rate: once already 5%+
  down, an 8% bounce within 60 days happens ~92% of the time anyway, so it added no edge. Confirmed
  twice more on a multi-decade true-volume Lowry 90/90 test and a dark-pool capitulation test.
- The free non-VIX inputs we since added (VRP, true up/down-volume breadth thrust, dealer gamma,
  dark-pool, put/call) each came back NO-GO under the same bar — so the free *daily* search is, as of
  now, considered exhausted. (This is a reason to look at different granularity or different methods,
  not a reason to give up.)

## WHY WE BELIEVE IT DID NOT WORK (our hypotheses — verify or refute these)
1. The premise "compression/churn near the highs precedes a top" appears, in this data, to be mostly
   a **calm-market signature that usually precedes more calm**, not distribution before a drop.
   Near-high compression is common and benign; genuine tops are too rare (~7–10 in 16 years of daily
   data) to separate from the many times the market just keeps grinding up.
2. The institutional-distribution fingerprint the thesis describes (smart-money tail-hedging, selling
   into strength) may simply **not be visible in daily price/volume/breadth** — it likely requires
   richer inputs: **decomposed options positioning / dealer gamma from the full option surface,
   tick-level or true-exchange order flow.** We may be measuring the phenomenon with too blunt an
   instrument — and the sharper instruments we found so far sit behind paywalls, which the hard
   constraint above forbids us to buy. (Finding a free or free-trial path to a sharper instrument, or a
   sharper *method* on cheap data, is precisely the prize.)

## YOUR MISSION (three deliverables)
1. **FACT-FINDING.** How do others actually do this — with *demonstrated out-of-sample accuracy and
   low false positives*, not marketing? Survey academic literature, practitioner methods, open-source
   projects, commercial tools/vendors, and quant write-ups for equity-index top/bottom or
   distribution/accumulation detection. For each credible approach, extract: (a) the exact **data
   inputs** (instruments, **and granularity** — daily / intraday / tick / event-driven — plus anything
   beyond OHLCV: options positioning, dealer gamma, breadth internals, put/call, flow, credit,
   cross-asset); (b) the **method**; (c) the **evidence of real edge** (out-of-sample, with sample size,
   the time span tested, and false-alarm rate — be skeptical of in-sample-only or cherry-picked "called
   the top" claims); (d) the **cost & access** of each required input, classified into exactly three
   buckets — **(i) FREE** (open/public, no card), **(ii) FREE-TRIAL-VIABLE** (a confirmed free trial
   that delivers enough backtestable history within the trial window — name the vendor, trial length,
   history depth, and how you confirmed it), or **(iii) PAID-ONLY** (out of scope per the hard
   constraint). Explicitly name which inputs carry the signal and which are noise, and **flag clearly
   whenever the signal-carrying input falls in the PAID-ONLY bucket** — that is the central tension of
   this mission. Note when an approach's edge depends on a long history versus when it works on a short
   or intraday sample — we want to know the full range of what's possible, not just the long-history path.
2. **PLAN.** From the findings, propose a concrete, testable plan for a more accurate detector built
   **using only FREE or FREE-TRIAL-VIABLE inputs.** Specify: the data to acquire (instruments,
   **granularity**, source, access path, and — for any trial — its length and confirmed historical
   depth); the method; the **event/target definition** you'll use (binary, graded, hazard — your choice,
   justified); and the **validation protocol.** The protocol must honor our honesty *principles*
   (point-in-time, opportunity-set/fair null, out-of-sample hold-out, robustness transfer to another
   asset or regime, leave-one-episode-out, raw counts, pre-registration) and state the expected
   false-positive control — but you choose the time span, granularity, and sample that best fit the
   method, and justify them. If the best path you can find under the free-only constraint is materially
   weaker than a paywalled one, **say so plainly** and present both: the free/trial build you recommend,
   and (separately, clearly marked out of scope) the paid approach we are choosing not to buy — so the
   decision is informed, not hidden.
3. **ADVERSARIAL REVIEW** of your own plan, focused on **accuracy and limiting false positives.**
   Attack it: where will it overfit; where is the null too easy; where will it fail to transfer across
   assets/regimes; is your event sample large enough for the claim you want to make (and if you used
   finer granularity to get more events, are those events truly independent or just autocorrelated
   slices of the same move?); what is the realistic false-alarm rate; which data is survivorship-biased,
   restated, or look-ahead-contaminated; and what would make it fail in live, real-time use.
   **Additionally stress-test the free-trial assumption specifically:** does each "free trial" you
   relied on actually deliver enough *history* for your test (versus forward-only data)? Will the trial
   expire before validation completes? Is the trial data the same product as the paid feed, or a
   degraded/sampled version? Could it be revoked or rate-limited mid-build? Then state which parts of
   the plan survive the review and which must change.

Be concrete, cite sources, and prefer evidence over assertion. Assume the goal is achievable by
someone with the right inputs and the right method — but our inputs are constrained to **free or
confirmed-free-trial data only**, while the time span, granularity, and event definition are open for
you to choose. Your job is to find the most accurate, low-false-positive path *inside the cost
constraint*, and if no such path clears the bar, to say so honestly rather than re-confirm that the
blunt daily-data version fails.

If you have any questions, ask me now before doing any research.
