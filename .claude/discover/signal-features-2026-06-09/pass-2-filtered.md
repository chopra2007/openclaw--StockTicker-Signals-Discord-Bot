# Pass 2 — Filtered & Ranked Feature Set (signal-features-2026-06-09)

Architect synthesis of the analyst keep/drop/merge verdicts + the critic's failure modes.
Inputs: Pass 0 system map, Pass 1 internal audit (I1–I18), Pass 1 candidates (E1–E6),
driver spec STEP 5 (precision over recall · catch before mainstream · surface contradictions ·
kill underperformers · free data). House rule for every user-facing change: **flag-OFF by default,
shadow-first, kill-switch wired.**

**Merge applied:** E4 (public-P/C-has-no-edge correction) folds into I6 as a horizon + thesis-text
constraint — no standalone build. No other merges. 23 candidates in → 23 survive the verdict pass
(analyst kept all) → ranked and bottom tier dropped below.

---

## Ranking method

Each survivor scored 1–5 on three axes, composite = sum (max 15):

- **signal_quality** — how well-evidenced the edge is. Verified academic = 5; a config-flip that
  fixes a *verified wrong-sign bug in our own code* = 5 (the edge is "stop doing the wrong thing,"
  which is certain); practitioner/blog-grade = 2–3; single abstained-unverified claim = 1–2.
- **impact** — precision/recall improvement for THIS bot. Wrong-sign fix on a large scoring term = 5;
  recap-only / display-only = 2.
- **feasibility** — low complexity, reuses existing data + code = 5; one-line config flip = 5;
  new scanner + new schema + backfill = 2; multi-pass LLM loop on unproven pattern = 1.

Drop rule: composite ≤ 6, OR (unverified + only support is a single abstained claim AND feasibility low).

---

## Survivors (ranked)

| id | name | tier | signal_quality | impact | feasibility | composite | one-line rationale |
|---|---|---|---|---|---|---|---|
| **I9** | Reconnect inert `min_base_score_for_alert` knob | Quick win | 5 | 4 | 5 | **14** | One-line read of a documented dead knob; restores a real volume/precision dial, value-neutral at default 20. |
| **I1** | Sign the YouTube boost (flip flags ON) | Quick win | 5 | 5 | 4 | **14** | Verified wrong-sign bug: bearish YT currently RAISES a long score; code already exists, byte-identical when off. |
| **I2** | Weight analysts by `rolling_accuracy` | Quick win | 4 | 5 | 4 | **13** | The single largest non-boost term is track-record-blind; data already stored in `source_performance`. |
| **I12** | Magnitude-scaled earnings beat/miss | Quick win | 4 | 4 | 5 | **13** | Beat/miss size already computed, only shown as text; clean post-event signal, low blast radius. |
| **I16** | Benchmark-adjust Wolf outcomes (beat SPY) | Quick win | 4 | 3 | 5 | **12** | Corrects the feedback signal that drives source trust; recap-only, SPY already pulled, no live-alert risk. |
| **I5** | Graduate SEC by role + open-market $ | Medium | 4 | 4 | 4 | **12** | $10M CEO buy and a director award both score +15 today; role/$/buy-sell already parsed in `sec_edgar.py`. |
| **I3** | Wire live `contradiction_index` producer | Medium | 4 | 4 | 3 | **11** | Revives the dead "surface contradictions" goal from data already gathered; prereq for I18. |
| **I8** | Wire herding `effective_size` into score | Medium | 4 | 3 | 4 | **11** | Correlation-discounted swarm metric is computed + logged but adds zero points; wiring, not new math. |
| **I10** | Require hard-evidence component for STRONG | Quick win | 4 | 4 | 3 | **11** | Crowd-only stacks can clear 80 with no catalyst; adds an AND-clause reading components already in the breakdown. |
| **I7** | Scale `consensus_boost` by Bayesian log-odds | Medium | 4 | 3 | 4 | **11** | The largest scoring term (cap 60) is the least calibrated; log-odds already computed, logged shadow-only. |
| **I4** | Reconcile the two scorers (show gated number) | Medium | 4 | 4 | 3 | **11** | User reads the inflated additive sum; the precision engine actually decides. Prereq for I17/I18. |
| **I14** | Surface regime z-score as risk context + sharper widening | Quick win | 3 | 3 | 4 | **10** | Bot's one macro-risk read barely touches output; risk-context line is cheap, the widening change needs a cap. |
| **I18** | Populate the dead reliability render block | Medium | 4 | 3 | 3 | **10** | ~30 lines, zero new modules; lights up freshness/verdict/drivers from data on hand. Depends on I3+I4. |
| **I11** | LLM-fallback catalyst classification | Medium | 3 | 3 | 3 | **9** | Recovers off-list catalyst false-negatives by reusing the existing scorer call; adversarial-text risk capped. |
| **I15** | Recency + size weighting in Wolf confluence | Medium | 3 | 3 | 3 | **9** | Stale tiny vote == fresh $5M sweep today; feeds a critical-tier @-ping, so size-weighting needs caps. |
| **I6** | Sign + scale options by premium + side (E4 folded in) | Medium | 3 | 3 | 3 | **9** | Put-wall on a long adds points today; but public P/C has NO verified edge — scope to confluence, short horizon. |
| **I13** | ApeWisdom mention-count z-score gate | Medium | 3 | 3 | 3 | **9** | Presence-flag → relative-surge; but Reddit surges ARE the pump vector, so confirm-only + new column needed. |
| **E2** | Cross-asset regime confirm/veto multiplier | Medium | 4 | 3 | 2 | **9** | VIX-term + HY-credit are HIGH-tier cited; extends existing regime engine as a veto, never a new alert generator. |
| **E1** | FINRA daily short-VOLUME confluence input | Medium | 3 | 2 | 2 | **7** | New free keyless stream, but it's short *volume* not *interest* — weak noisy proxy, EOD-stale, new scanner+schema. |
| **E3** | Gamma-exposure (GEX) flip level in `!all` | Moonshot | 2 | 3 | 2 | **7** | Reuses chains we pull; blog-grade, model-dependent sign — a wrong flip level is the NVDA-850 error class. |
| **E6** | Adversarial input-integrity (manufactured-agreement) | Medium | 2 | 3 | 2 | **7** | Real attack surface, but unverified defense + collides with legit breaking-news bursts. *Re-verify in Pass 3.* |
| ~~E5~~ | LLM bull/bear debate + critic loop | ~~Moonshot~~ | 1 | 2 | 1 | **4** | **DROPPED** — unverified single abstained claim, low feasibility, amplifies hallucination on the LLM budget. |

**Bottom tier dropped:** E5 (composite 4 ≤ 6, AND unverified-only-abstained AND feasibility low — fails both drop tests).
All 22 others survive. E1 / E3 / E6 sit at composite 7 (just above the cut) and carry **re-verify-in-Pass-3** flags.

---

## Per-survivor detail

Ordered by composite. Each block: function · rationale · failure modes (from critic) · safeguards
(architect additions) · rank · kill-switch metric.

---

### I9 — Reconnect inert `min_base_score_for_alert` knob — composite 14 (Quick win)
- **Function:** Replace the hardcoded `quality_score >= 20` at `main.py:1066` with
  `cfg.get("alerts.min_base_score_for_alert", 20)` so the documented `consensus.yaml:363` knob is live.
- **Rationale:** Verified dead knob (Gap #4). The operator has a painted-on dial. Value-neutral at the
  current default of 20 — no behavior change today, restores a real precision lever.
- **Failure modes (critic):** (low) silently arms a live lever — a future YAML edit changes the firehose
  with no code review; the −5 neutral discount interaction (effective floor 25 for neutral) not re-examined.
  (medium) a non-coder raising it to 30 could silently kill a large fraction of alerts with no volume preview.
- **Safeguards (architect):**
  - Ship the wiring at default 20 so it is **truly inert until deliberately changed** — this is the safe
    half of the change and needs no flag.
  - Add a **shadow volume-preview log line**: on each gate evaluation, log
    `would_suppress_at_25 / _at_30` counts so any future raise has a measured impact readout first.
  - Keep the −5 neutral discount explicit in the comparison and document the effective neutral floor.
- **Kill-switch metric:** none needed at default 20 (restores intended behavior). If a future raise is
  applied and weekly alert volume drops >40% with no 1h-hit-rate gain on the retained set, revert the knob.

---

### I1 — Sign the YouTube boost — composite 14 (Quick win)
- **Function:** Flip `features.youtube_score.direction_aware` + `recency_decay` (+ `channel_reliability`)
  ON at `consensus.yaml:745-747`. Sign/decay/trust logic already exists at `cross_reference.py:383-413`,
  byte-identical when off. Bearish YT consensus then SUBTRACTS instead of adds.
- **Rationale:** Verified wrong-sign term (mis-weight table, Gap-class). Today a flood of cheap bearish
  videos pushes a long score UP toward STRONG — manufacturing false positives. Highest-ROI false-positive killer.
- **Failure modes (critic):** (high) signing turns this into a precision tool for shorts — coordinated
  bearish-video flooding can drag a true long below STRONG and suppress it; no per-channel trust gate while
  `channel_reliability` is off. (high) `consensus_dir` is a bare majority with no minimum-channel floor — one
  bearish video flips it and subtracts up to 15. (high) **regression**: `youtube_score.*` is NOT in the
  conftest force-off list, so flipping it changes live `youtube_pts` sign/magnitude and breaks passing tests.
  (medium) YT consensus is reactive — signing a stale bearish consensus negative suppresses longs at
  capitulation bottoms. (low) missing `extracted_at` timestamps can divide-by-zero / treat undated as fresh.
- **Safeguards (architect):**
  - **Turn `channel_reliability` ON in the same change** (don't defer it) so anonymous spun-up channels
    can't vote at full weight — directly neutralizes the manipulation + bare-majority modes.
  - **Add a minimum-channel floor** before `consensus_dir` can sign negative: require ≥2 distinct trusted
    channels agreeing before a bearish subtraction fires; below the floor, fall back to a 0 contribution
    (not a positive add — that re-introduces the original bug).
  - **Cap the negative magnitude** below the positive (e.g. bearish subtraction max −8 vs bullish +15) so a
    contradicting-but-stale YT camp dents but cannot solo-suppress a real long — addresses capitulation-bottom mode.
  - **`recency_decay` ON with a null-timestamp guard**: undated mentions treated as *stale* (down-weighted),
    never fresh; guard the divide so missing `extracted_at` → minimum weight, no div-by-zero.
  - **Regression**: add `features.youtube_score.*` to the conftest autouse force-off fixture (mirrors the
    documented `wolf.confluence.*` pattern) so general tests stay on the unsigned baseline; the dedicated
    YT-signing feature test forces the flags ON itself.
  - Shadow-first: log signed vs unsigned `youtube_pts` for a week before the flags gate live alerts.
- **Kill-switch metric:** if STRONG-alert count drops >40% over one week with no 1h-forward hit-rate gain,
  the conviction-map magnitudes are too large — revert `direction_aware` first.

---

### I2 — Weight analysts by `rolling_accuracy` — composite 13 (Quick win)
- **Function:** Replace the flat `×20` at `cross_reference.py:483` with a per-analyst sum
  `20 × clamp(accuracy_ratio, 0.3, 1.5)` using the existing `db.py:1078` rolling-accuracy helper;
  cold-start (None, <5 samples) keeps the neutral 20.
- **Rationale:** The single largest non-boost term is track-record-blind; accuracy is already stored and
  used as a herding trust floor / consolidation prior, just never on the headline term.
- **Failure modes (critic):** (medium) cold-start blind spot — new high-signal analysts (the "before
  mainstream" edge) get zero uplift; the change only re-weights the established crowd. (high) survivorship
  loop — down-weighting a "loser" suppresses their alerts, removing future outcome data, freezing the estimate
  permanently. (high) thin-sample noise — n=5 accuracy is a coin-flip (binomial std ~0.22); per the thin-sample
  memory, 3/5 vs 2/5 should not move points. (high) **regression** — largest non-boost term, not in force-off list.
  (medium) gaming — farm accuracy on safe calls, spend it on a pump.
- **Safeguards (architect):**
  - **Raise the sample floor to n ≥ 10** (not the documented 5) before any non-neutral weight applies —
    directly honors the thin-sample memory; below 10, weight = 1.0 (neutral 20).
  - **Wilson lower-bound, not raw ratio**: use the lower bound of the accuracy confidence interval so a
    thin or noisy record stays near neutral — kills the n=5 coin-flip swing.
  - **Floor the discount at 0.5, never 0**, and keep grading suppressed analysts in shadow (continue logging
    their would-be outcomes even when down-weighted) so the survivorship loop can recover — a cold-good
    analyst is dampened, never silenced into a frozen estimate.
  - **Regression**: gate behind a flag in the conftest force-off list; mock `rolling_accuracy` in the
    dedicated feature test so general scoring tests keep the flat-+20 baseline.
  - Shadow-first: log weighted vs flat analyst_pts for 30 analyst-driven alerts before gating.
- **Kill-switch metric:** if STRONG-tier precision over 30 analyst-driven alerts falls below the flat-+20
  baseline, revert the multiplier.

---

### I12 — Magnitude-scaled earnings beat/miss — composite 13 (Quick win)
- **Function:** In cross_reference catalyst scoring, bump the flat "Earnings Beat" 25 toward a magnitude
  scale (+5 per 10% surprise, cap +15) when the recap already fetched in `news.py:150-153` carries
  `eps_surprise_pct`; symmetric miss penalty.
- **Rationale:** Beat/miss magnitude is a clean post-event catalyst; both fields computed, only shown as text.
- **Failure modes (critic):** (high) post-earnings drift is not monotonic in surprise — a +40% blowout often
  "sells the news"; scaling UP adds the most points exactly where it fades. (medium) `eps_surprise_pct`
  denominator blows up near-zero consensus EPS — a $0.01 beat on a $0.001 estimate = +900% → caps at +15 on a
  trivial beat. (medium) stale-recap timing — recap fires days late after the gap is traded. (low-med)
  **regression** — flat-25 tests flip; symmetric miss adds an untested negative path.
- **Safeguards (architect):**
  - **Add an absolute-dollar-surprise floor alongside the %** (e.g. require |EPS surprise| ≥ a small absolute
    threshold AND a sane consensus-EPS denominator) so near-zero-EPS turnarounds can't manufacture a +900%
    surprise — neutralizes the denominator-instability mode.
  - **Cap the bonus at +15 and keep the base tier as the floor** so the change can only refine, not dominate;
    drift non-monotonicity is contained because a blowout gets at most +15 over the existing tier, not a runaway.
  - **Staleness gate**: only apply the magnitude bonus when the recap is within the fresh post-print window
    (`earnings_calendar` already returns None outside it) — never apply a days-old recap.
  - **Regression**: flag-gated; the dedicated test asserts the new magnitude path, general earnings-beat tests
    force the flag off and keep flat 25.
- **Kill-switch metric:** if magnitude-scaled earnings STRONGs don't beat flat-tier earnings STRONGs on 24h
  outcome over 20 prints, revert to flat 25.

---

### I16 — Benchmark-adjust Wolf outcomes — composite 12 (Quick win)
- **Function:** In `wolf_outcomes.py:144-146`, credit "moved_with" only if the proxy beat SPY over the same
  window (SPY OHLCV already pulled for `regime.py`), not if it merely rose.
- **Rationale:** Corrects the feedback signal that drives source trust; recap-only, no live-alert blast radius.
- **Failure modes (critic):** (medium) benchmark mismatch — a sector/defensive call can be "right" yet lag SPY
  in a rip; SPY is the wrong benchmark for sector/inverse/single-name scope_types. (medium) inverse-proxy sign
  trap — benchmark-adjusting an inverse proxy needs the SPY comparison to be sign-aware or it credits the
  opposite. (low) small-n recap meaninglessness — benchmark split thins an already-small sample. (low)
  **regression** — confined to wolf_outcomes tests.
- **Safeguards (architect):**
  - **Scope-aware benchmark**: compare a sector call to its sector ETF, a single-name to SPY, and make the
    inverse-proxy comparison sign-aware (flip the benchmark sign for inverse scopes) — reuses `wolf_scope`'s
    existing scope_type + inverse-proxy flag, no new data.
  - **Surface BOTH raw and benchmark-adjusted numbers** in the Sunday recap rather than replacing the raw one,
    so a thin-n benchmark split can't silently hide the underlying record (honors thin-sample memory).
  - Recap-only: no live alert touched, so this can ship behind the Wolf-recap path without a STRONG-gate flag.
- **Kill-switch metric:** none needed for live alerts (recap-only). If benchmark-adjustment makes the recap
  statistically meaningless at small n, keep showing both raw + adjusted (already the safeguard) and don't
  wire it into source trust until n is adequate.

---

### I5 — Graduate SEC by role + open-market $ — composite 12 (Medium)
- **Function:** Have `_run_sec_check` (`cross_reference.py:236`) return the parsed max open-market BUY dollars
  + reporter role (already produced in `sec_edgar.py:253-332`), then graduate `sec_pts` at
  `cross_reference.py:485`: +8 any Form-4, +15 >$250k buy, +20 C-suite buy, ≤0 on net selling. Reuse the
  `_MIN_PURCHASE_DOLLARS` floor from `sec_form4_cluster.py`.
- **Rationale:** A $10M CEO buy and a routine director award both score +15 today; the data is fully parsed.
- **Failure modes (critic):** (medium) Form-4 reporting lag — a "large buy" can fire on a 2–4-day-old, already-
  priced event. (high) 10b5-1 plan false signal — scheduled buys/sells carry no info but parse identically.
  (high) net-selling negative branch backfires — routine 10b5-1 / option-exercise sales dominate insider
  volume; a "<0 on net selling" rule manufactures false bearish drag on healthy companies. (medium) role-parse
  brittleness — "CEO" vs "Chief Executive Officer" vs "Principal Executive Officer." (medium) **regression** —
  flat-+15 tests flip; `_run_sec_check` signature change ripples to callers/mocks.
- **Safeguards (architect):**
  - **Detect and exclude 10b5-1 / planned trades**: parse the Form-4 footnote/plan flag where present; when a
    transaction is plan-coded, do NOT credit it as a discretionary buy and do NOT apply the net-selling
    negative branch — neutralizes both the false-buy and false-bear modes (the two high-severity items).
  - **Make the net-selling branch ≤0 → floor at 0 for the additive sum by default** (no negative bearish drag
    on the cross-ref score); only allow it to *withhold* the buy credit, not subtract. A true bearish insider
    signal is left to the dedicated SEC path, not this additive term.
  - **Canonicalize role strings** against a small synonym map (CEO/CFO/COO/President/PEO/PFO) before the
    C-suite +20 tier; unknown titles default to the +8 baseline, never the +20 tier.
  - **Recency gate**: only credit the graduated buy when the filing's transaction date is within a recent
    window so a stale already-priced buy doesn't inflate a fresh alert.
  - **Regression**: keep the `_run_sec_check` boolean return as a compatibility field; add the dollars/role as
    new return fields. Flag-gate the graduated scoring so flat-+15 tests pass with the flag off.
- **Kill-switch metric:** if SEC-driven STRONGs underperform non-SEC STRONGs on 1h/24h outcome over 20 alerts,
  revert to flat +15.

---

### I3 — Wire live `contradiction_index` producer — composite 11 (Medium)
- **Function:** In `cross_reference.score_ticker`, after sources are gathered, collect each contributing
  source's signed direction (analyst/tweet, signed YT `consensus_dir`, options dominant side, SEC buy/sell),
  weight by points contributed, set `result.contradiction_index = min(opposing, supporting) / total` before
  return. The dead penalty (`contradiction.py:96-116`) and discord bar (`discord.py:415`) light up automatically.
- **Rationale:** Revives the explicit "surface contradictions" goal from data already gathered. Prereq for I18.
- **Failure modes (critic):** (high) false contradiction from unsigned/missing directions — options "side" is
  only a boolean and SEC is buys-only until I6/I5 land, so the fraction is meaningless without them; dependency
  not enforced. (high) manipulation amplifier — inject ANY opposing source to push index ≥0.5 and trigger the
  STRONG→WATCHLIST downgrade (denial-of-signal attack). (medium) legitimate-disagreement penalty — the best
  asymmetric setups have a vocal bear camp; the index penalizes all disagreement symmetrically. (high)
  **regression** — first live value lights up two dead consumers (engine gate + discord bar); the ≥0.5 branch
  is untested. (medium) weighting ambiguity — a negative-point source (after I1 signs YT) breaks
  min(opposing,supporting)/total; edge cases produce index >1 or NaN.
- **Safeguards (architect):**
  - **Enforce the I5+I6 dependency**: only count a source toward the index if it carries a *real* sign — until
    I6 lands, options contributes no direction; until I5 lands, SEC contributes no sign. Compute the index over
    signed sources only; if <2 signed sources, index = 0 (not a fabricated split).
  - **Require ≥2 independent opposing sources** (not one) before the index can reach the ≥0.5 downgrade
    threshold — defeats the single-injected-source denial-of-signal attack.
  - **Use a downgrade, not a hard veto, and floor it**: a high contradiction caps the tier at WATCHLIST rather
    than killing the alert, so a vocal-bear-camp asymmetric setup is surfaced-with-caution, not suppressed.
  - **Math guard**: compute weights on **absolute** point magnitudes; clamp the index to [0, 1]; NaN/empty →
    0. Closes the negative-weight / >1 / NaN edge cases.
  - **Regression**: flag-gate the producer; with the flag off the index stays 0.0 and existing tests pass
    unchanged. Add a dedicated test for the ≥0.5 downgrade branch (currently untested).
  - Shadow-first: log the computed index on every alert for a week before it gates.
- **Kill-switch metric:** if it downgrades more eventually-correct STRONGs than incorrect ones over 20
  contested tickers (track 1h outcome on downgraded vs non-downgraded), loosen the ≥0.5 gate or revert.

---

### I8 — Wire herding `effective_size` into score — composite 11 (Medium)
- **Function:** Change the `main.py:1156` `detect_cluster(..., new_event_id=0, ...)` call to a real event id
  and add `ClusterResult.effective_size` into a new `ScoreBreakdown` herding term (+5 per effective member
  above the minimum, cap ~15), gated by the existing herding trust floor.
- **Rationale:** A correlation-discounted swarm metric is computed + logged but adds zero points. Wiring, not new math.
- **Failure modes (critic):** (high) herding rewards crowding — a swarm IS the crowded, late signal, working
  against "before mainstream." (high) coordinated-account manipulation — a pump ring posting from multiple
  watched handles manufactures an `effective_size` swarm; the correlation discount assumes organic correlation.
  (medium) wiring side effect — `new_event_id=0 → real id` changes what `detect_cluster` persists and how
  cluster rows join events; historical rows at id 0 may double-count/mis-join. (medium) **regression** — new
  ScoreBreakdown field changes the dataclass + every constructor/serializer; positional constructors break.
- **Safeguards (architect):**
  - **Gate the herding term behind the trust floor AND a distinct-account-diversity check**: require the
    effective members to be ≥N *independent* trusted handles (not just N posts) before any points — a
    same-source / templated burst collapses `effective_size` and earns nothing, addressing both the
    crowding-late and the coordinated-ring modes.
  - **Cap the term low (≤15)** so a swarm nudges but never carries an alert to STRONG on its own — keeps the
    "before mainstream" edge dominant over the crowding signal.
  - **Data-model safety**: leave historical id-0 cluster rows alone (don't backfill); apply the real-event-id
    wiring forward-only and add a migration note that pre-change rows are observability-only.
  - **Regression**: add the new field with a default; use keyword construction for `ScoreBreakdown`; flag-gate
    so the term is 0 when off and existing totals are unchanged.
- **Kill-switch metric:** if herding-boosted STRONGs don't beat non-herding STRONGs on 1h outcome over 20
  swarm events, drop the term.

---

### I10 — Require a hard-evidence component for STRONG — composite 11 (Quick win)
- **Function:** Add an AND-clause at `engine.py:262`: STRONG requires
  `score ≥ high_confidence AND (news_catalyst>0 OR sec_filing>0 OR technical>0 OR options_flow>0)`.
  Crowd-only stacks cap at WATCHLIST.
- **Rationale:** Analysts(60)+social(35)+trends(5) overshoot 80 with zero hard catalyst on an uncalibrated sum.
- **Failure modes (critic):** (high) blocks the fastest signals — a fresh analyst tweet with strong crowd
  agreement *before* any news/SEC/technical can only reach WATCHLIST, defeating "catch before mainstream."
  (medium) `technical>0` is a weak proxy — one cheap filter (RVOL +2) satisfies the gate, so the bar is
  porous. (medium) budget interaction — on a quota-exhausted day a real-but-unfetched catalyst is demoted by
  infra state, not signal quality. (high) **regression** — any fixture reaching ≥80 on crowd terms flips
  STRONG→WATCHLIST.
- **Safeguards (architect):**
  - **Carve out the high-conviction "before mainstream" path**: a single very-high-conviction trusted-analyst
    tweet (base_score ≥ `high_conviction_threshold`, the existing 30 knob) is itself counted as hard evidence
    for STRONG — so a genuine early call is not demoted, only a *diffuse crowd-only* stack is. Directly
    neutralizes the highest-severity "blocks the fastest signal" mode.
  - **Distinguish "absent" from "unfetched"**: when a catalyst/options fetch was *skipped for budget* (not
    fetched-and-empty), do not treat its absence as failing the hard-evidence gate — fall back to WATCHLIST
    only when the confirming fetch ran and returned nothing. Closes the budget-state demotion mode.
  - **Raise the technical bar**: require technical ≥ a 2-filter threshold (not a single RVOL fire) to count as
    hard evidence — closes the porous-gate mode.
  - **Regression**: flag-gate the AND-clause; with the flag off, classification is unchanged and crowd-only
    tests keep passing. Shadow-log which STRONGs *would* demote for a week before gating.
- **Kill-switch metric:** if STRONG count collapses and the 1h hit-rate of the newly-demoted-to-WATCHLIST set
  matches retained STRONGs over 50 alerts, the hard-evidence set is too strict — broaden it.

---

### I7 — Scale `consensus_boost` by Bayesian log-odds — composite 11 (Medium)
- **Function:** In `consolidation.py:163-178`, replace `consensus_boost = round(effective_n × pts_per_cluster)`
  with a value scaled by a sigmoid of the already-computed `combined_log_odds` (`consolidation.py:151`), so
  cluster QUALITY (priors) not raw count drives the cap-60 term.
- **Rationale:** The largest scoring term is the least calibrated; the log-odds is computed then logged shadow-only.
- **Failure modes (critic):** (high) priors ARE `rolling_accuracy` → same feedback-loop + thin-sample
  pathology as I2, now compounded in the cap-60 term; cold-start collapses log-odds toward neutral, gutting the
  largest term during the bot's own cold-start. (medium) sigmoid saturation hides cluster count — two strong
  clusters and one over-confident correlated cluster both saturate near 1.0. (medium) double-counting with I8 —
  same analysts feed both terms. (medium-high) **regression** — every consolidated-alert expected total
  changes; the cold-start-zero contract must be preserved.
- **Safeguards (architect):**
  - **Reuse I2's hardened accuracy primitive** (Wilson lower bound, n≥10 floor, 0.5 discount floor) for the
    priors so the feedback-loop / thin-sample pathology is fixed once and inherited here — do NOT re-implement
    raw accuracy. This is why I7 lands AFTER I2.
  - **Preserve the cold-start-zero contract explicitly**: when priors are absent (cold-start), keep the
    existing `consensus_boost = 0` path verbatim — the sigmoid scaling applies only once real priors exist,
    so the largest term is never silently gutted during cold-start.
  - **Blend, don't replace**: scale a *portion* of the boost by log-odds while retaining a count-based floor,
    so saturation can't fully erase the independent-cluster-count information.
  - **De-correlate with I8**: when a cluster's members also drive the herding term, discount one of the two so
    the same agreement isn't paid twice (reconcile I7↔I8 in the same change).
  - **Regression**: flag-gate; cold-start-zero tests must pass unchanged; the dedicated test asserts the
    sigmoid-scaled value with the flag on.
- **Kill-switch metric:** if STRONG-tier hit rate falls below the `effective_n` baseline over 30 consolidated
  alerts, revert to count-based boost.

---

### I4 — Reconcile the two scorers (show the gated number) — composite 11 (Medium)
- **Function:** At the render contract (`main.py:1255-1290` + `discord.py:447`) stop printing the raw additive
  xref total. Minimal first step: render `final = min(xref_total, precision_total)` so displayed confidence
  can never exceed the gated number. Full path: feed xref components into `engine.analyze_signal` as features
  → one calibrated number. Prereq for I17/I18.
- **Rationale:** The user reads the inflated additive sum; a separate precision engine actually decides.
- **Failure modes (critic):** (high) `min()` under-reports on budget-exhausted days — precision total is low
  because paid sources were skipped, not because the signal is weak → a hollow-precision-cliff in the headline.
  (high) decision/display still divorced — `min()` can show a number below the medium cutoff on an alert the
  engine classed STRONG ("STRONG, score 58" looks like a bug). (medium) full feature-merge is a large refactor
  of two scorers from different inputs; every per-source candidate (I2/I5/I6/I7) changes the merge inputs, so
  order-of-landing matters. (high) **regression** — touches the most-asserted headline string.
- **Safeguards (architect):**
  - **Land I4 LAST among the scoring changes** (after I1/I2/I5/I6/I7) so the reconciled number reflects the
    corrected components — pins the order-of-landing the critic flagged as unpinned.
  - **Avoid the bare `min()`**: when the precision total is *budget-depressed* (a paid source was skipped),
    fall back to the xref total for display rather than showing a quota-driven low number — closes the
    hollow-precision-cliff and the "STRONG, 58" contradiction in one rule.
  - **Show class + number consistently**: render the precision *class* and a number that cannot contradict it
    (display number ≥ the class's cutoff floor); never a STRONG with a sub-65 number.
  - **Regression**: flag-gate the render change; with the flag off the legacy headline is unchanged and
    snapshot tests pass. Shadow-log reconciled vs displayed for a week.
- **Kill-switch metric:** if users see the displayed number drop below the precision class label they expect,
  the `min()` collapse is too blunt — switch to the single-engine feature-merge path.

---

### I14 — Surface regime z-score as risk context + sharper STRONG widening — composite 10 (Quick win)
- **Function:** Surface the regime label + realized-vol z-score (`regime.py:35-72`) as a one-line risk-context
  field in the Phase-2 embed (`discord.py`), and scale the panic STRONG-cutoff widening by how far z exceeds
  `panic_z` rather than the flat +10 (`engine.py:247-249`).
- **Rationale:** The bot's one macro-risk read barely touches output.
- **Failure modes (critic):** (medium) regime z is coincident/lagging — widening harder in already-panic tape
  suppresses longs at max-pessimism mean-reversion lows. (medium) cold-start identity — needs 30 `regime_daily`
  rows or returns identity; the widening is silently inert on a fresh deploy. (medium) graduated shift
  over-tightening — z=4 could push the cutoff to 95+, disabling STRONG entirely (recall cliff, no floor).
  (low) **regression** — changing the flat +10 changes the STRONG cutoff for regime-tagged tests.
- **Safeguards (architect):**
  - **Cap the graduated widening** (e.g. max shift +15, hard cutoff ceiling ~90) so an extreme z spike can
    never disable STRONG entirely — closes the recall-cliff mode.
  - **Ship the risk-context display FIRST and independently of the widening change**: the one-line label is
    pure-additive low-risk; the cutoff-widening is the riskier half and gets its own flag.
  - **Cold-start honesty**: when regime is in identity (<30 rows) show the label as "regime: warming up"
    rather than implying an active protection that isn't there.
  - **Exempt high-conviction longs from the *extra* widening** so a genuine early call isn't suppressed at a
    capitulation bottom — only diffuse low-conviction longs get the sharper panic gate.
  - **Regression**: flag-gate the graduated shift; the display line touches embed structure, so update the
    embed-snapshot tests deliberately in the same change.
- **Kill-switch metric:** if the sharper panic widening suppresses STRONGs that would have hit their 1h target
  during high-vol regimes (track over 2 weeks of panic-tagged days), revert to flat +10.

---

### I18 — Populate the dead reliability render block — composite 10 (Medium)
- **Function:** Set the three fields the `discord.py:402-424` block already wants, ~30 lines in
  `cross_reference.py`, zero new modules: (a) `reliability_weights` = per-source recency from `extracted_at` /
  news timestamps / options staleness → freshness label; (b) `reliability_decision` = CONFIRM/MIXED/CAUTION
  from the reconciled score + `contradiction_index`; (c) drivers = top-2 ScoreBreakdown components by points.
  **Depends on I3 + I4 landing first.**
- **Rationale:** Lights up the freshness/verdict/driver context that turns a bare number into actionability.
- **Failure modes (critic):** (high) hard dependency on I3+I4 producing *trustworthy* values — a fabricated
  contradiction or a quota-depressed reconciled number renders a confidently WRONG verdict, and a CONFIRM/
  CAUTION label reads as more authoritative than a bare number → worse than the current blank block. (medium)
  heterogeneous timestamps — differing clocks / missing `extracted_at` can label a stale source "fresh" (the
  documented tz trap). (medium) top-2 drivers by points mislead after signing — a negative-point source has
  large magnitude; abs-vs-signed must be defined or it hides the contradiction. (medium) **regression** — the
  whole block renders for the first time; embed snapshot tests flip.
- **Safeguards (architect):**
  - **Hard-gate on I3+I4 being live AND past their shadow window**: do not enable I18 until the contradiction
    producer and the reconciled number have passed their own kill-switch checks — a wrong verdict block is
    worse than none, so it inherits the trust of its inputs by construction.
  - **Timestamp hygiene**: normalize all source clocks to UTC before computing recency; a null/missing
    `extracted_at` renders as "freshness unknown," never "0m fresh" — closes the stale-as-fresh tz trap.
  - **Drivers by absolute magnitude, sign-labeled**: surface the top-2 by |points| and annotate sign (e.g.
    "YouTube −8 (bearish)"), so the contradiction the block exists to show is visible, not hidden.
  - **Conservative verdict mapping**: CAUTION on any non-trivial contradiction or any stale top driver; CONFIRM
    only when sources agree AND are fresh AND the reconciled number is not budget-depressed.
  - **Regression**: flag-gate the whole block; with the flag off it stays dead and existing embed tests pass.
- **Kill-switch metric:** if the freshness/verdict block is judged noisy or wrong in live review over 10
  alerts, hide it behind the flag while the inputs are tuned.

---

### I11 — LLM-fallback catalyst classification — composite 9 (Medium)
- **Function:** Have the `llm_scorer` call already running on the same news text (`cross_reference.py:528`)
  also emit a `catalyst_type` from a fixed enum as JSON, used ONLY when the 19-substring matcher
  (`news.py:_classify_catalyst`) returns None. No second model call.
- **Rationale:** Real catalysts phrased off-list zero out the entire news tier (up to +25).
- **Failure modes (critic):** (high) LLM catalyst hallucination → +25 on a non-event (M&A / FDA / Gov-Contract
  are each +25); per the prompt-echo memory, realistic enum example values get echoed as extractions. (high)
  prompt-injection via news body — Google News RSS / Brave / SearXNG are attacker-controllable; a crafted
  headline both injects the LLM and triggers +25. (medium) latency/cost — if the scorer is skipped (budget /
  no news), there is no call to piggyback, so a second call IS needed, contradicting the premise. (medium)
  **regression** — off-list phrases that scored 0 now score non-zero.
- **Safeguards (architect):**
  - **Cap the LLM-fallback catalyst tier well below the substring tier** (e.g. an LLM-labelled catalyst earns
    at most +8, never the +25 M&A/FDA tier) — a hallucinated high-tier event cannot manufacture a STRONG. The
    +25 tiers remain reachable only via the deterministic substring match.
  - **Use `<placeholder>` enum syntax in the prompt** (per the prompt-echo memory) and require the model to
    quote the substring of the news text that justifies the label; reject the label if the quote isn't present
    (reuse the existing quote-substring anti-fabrication discipline) — neutralizes hallucination + injection.
  - **Treat news body as untrusted**: wrap the text in clear delimiters and instruct the model to classify
    only, never to follow instructions in the text — standard injection containment.
  - **Only piggyback, never add a call**: when the scorer didn't run (budget/no news), the fallback simply
    doesn't fire (catalyst stays None) — honors the "no second model call" premise exactly.
  - **Regression**: flag-gate; off-list-zero tests pass with the flag off.
- **Kill-switch metric:** if LLM-labelled catalysts produce more false-positive STRONGs than substring-only
  over 30 alerts, disable the fallback.

---

### I15 — Recency + size weighting in Wolf confluence — composite 9 (Medium)
- **Function:** In `wolf_confluence.py:146-163`, replace each source's binary one-vote with an age-decayed,
  size-scaled vote (SEC insider $, options premium, YT `n_channels`); let SEC vote bear on net selling.
- **Rationale:** A 20-day-old tweet and a fresh $5M sweep vote equally today; this feeds a critical-tier @-ping.
- **Failure modes (critic):** (high) Wolf confluence is critical-tier @-ping eligible — size-weighting lets ONE
  manipulable input (a public options print) solo-push a thesis to critical tier and fire a user @-ping. (medium)
  SEC-can-vote-bear re-imports the I5 10b5-1/diversification-sale false-bear problem into the macro brain.
  (medium) incommensurable units — combining $ + premium + channel-counts needs an arbitrary normalization; a
  $5M sweep always outweighs any plausible `n_channels`. (low-med) **regression** — Wolf flags partially in the
  conftest force-off list; lower risk to general Wolf tests.
- **Safeguards (architect):**
  - **No single source may reach critical tier alone**: require ≥2 independent sources agreeing before the
    critical-tier @-ping can fire, regardless of any one source's size weight — directly neutralizes the
    solo-push-to-@-ping attack (the highest-severity mode).
  - **Cap each source's weight** (normalize every source to a bounded 0–1 contribution via per-source
    percentile, not raw dollars) so a $5M sweep can't dominate `n_channels` — closes the incommensurable-units mode.
  - **Reuse I5's 10b5-1 exclusion** for the SEC-bear vote: a planned/diversification sale never casts a bear
    vote — fixes the imported false-bear mode. I15 therefore lands AFTER I5.
  - **Age decay with a floor**: stale signals decay toward (not to) zero so a thesis isn't whipsawed by a
    single fresh print.
  - **Regression**: confluence flags already force-off in conftest; the dedicated test forces them on.
- **Kill-switch metric:** if critical-tier Wolf confluence posts don't precede the thesis-direction move more
  often than surface-tier over a month of Sunday recaps, revert to unweighted votes.

---

### I6 — Sign + scale options by premium + side (E4 folded in) — composite 9 (Medium)
- **Function:** Pass the #18 flow watcher's premium notional + vol/OI ratio into `cross_reference.py:487` and
  graduate `options_pts`: +6 unusual, +10 for >$250k single-strike premium aligned with the tweet, signed
  NEGATIVE when the dominant flow opposes the tweet. **E4 constraint folded in:** cap the signal's horizon to
  intraday/1–2-day confluence and never let public/tape-inferred P/C inherit the academic edge in score or thesis.
- **Rationale:** A $5M sweep and a 3×-OI far-dated contract add the same +10 today; a put-wall on a long adds points.
- **Failure modes (critic):** (high) **public options data carries NO academic edge (E4 VERIFIED)** — the
  Pan-Poteshman edge is proprietary signed open-buy flow; public P/C was REFUTED 0-3 and reverses in 1-2 days;
  scaling points by public premium imports a non-predictive signal and risks a false "smart-money" thesis
  framing. (high) dealer-hedging contamination — a large put "wall" is often protective hedging by a holder
  (bullish), yet the signed branch subtracts (a new wrong-sign error). (high) single-leg side inference is
  unreliable — a put can be a short put (bullish); inferring direction from raw vol/OI is the exact fallacy E4
  refutes. (medium) latency — flow is ~15-min delayed / prior-session after hours. (medium) **regression** —
  options_pts boolean tests flip; OptionsResult dataclass shape changes.
- **Safeguards (architect):**
  - **E4 enforcement is mandatory, not a footnote** (the critic's own E4 failure mode): the options term is
    **confluence-only with a hard intraday/1–2-day horizon attribute** carried on the contribution; it can
    never solo-trigger or push to STRONG, and the **narrator prompt is explicitly forbidden** from describing
    public flow as "smart money positioning." Add a regression assertion that the horizon attribute is present.
  - **Do NOT sign single-leg side as direction**: because side inference is the refuted fallacy, the negative
    branch fires ONLY on a clear opposing *sweep with premium above the floor* (not a static OI "wall," which
    is likely a hedge) — neutralizes the dealer-hedging and short-put wrong-sign modes. When the side is
    ambiguous, contribute 0, never a sign.
  - **Magnitude-cap the whole term low** so even an aligned $5M sweep is a confluence nudge, not a driver.
  - **Staleness gate** (reuse the #18 watcher's existing gate): no options contribution older than the gate;
    after-hours prior-session snapshots are marked stale and contribute 0.
  - **Regression**: add premium/side as new OptionsResult fields with defaults; flag-gate the graduated/signed
    scoring so the boolean-+10 tests pass with the flag off.
- **Kill-switch metric:** precision on options-confirmed STRONGs vs the boolean baseline over 20 alerts; if no
  gain and the sign-flip suppresses known-good longs, drop the negative branch first.

---

### I13 — ApeWisdom mention-count z-score gate — composite 9 (Medium)
- **Function:** Persist the ApeWisdom mention count + 24h delta as a numeric column (today only inside a
  display string at `social.py:205-206`), then change `social_apewisdom` at `cross_reference.py:97-105` from
  "+10 if mentions≥1" to "+10 only when mentions >2σ above the ticker's own 30-day baseline."
- **Rationale:** A ticker with 2 mentions and one with 2000 score identically today; z-score = the "rising
  before mainstream" primitive.
- **Failure modes (critic):** (high) Reddit/ApeWisdom mention surges ARE the canonical pump-and-dump vector — a
  z-score gate REWARDS the manufactured-attention attack with +10 and points the bot at the crowd top. (high)
  30-day bootstrap problem — a new ticker has no baseline, so any mention is infinite-σ → always fires +10,
  degenerating to the old presence flag for exactly the most-manipulated new names. (medium) ApeWisdom is a
  derived aggregator — a z-spike can be an upstream methodology/backfill artifact, not real Reddit activity;
  needs a new numeric column + 24h delta (schema/backfill). (medium) **regression** — needs a new numeric
  column + 30-day baseline read in `db.py`; until backfilled the term returns 0 for all tickers; db tripwire.
- **Safeguards (architect):**
  - **Confirm-only, never standalone**: the z-surge contributes points ONLY when at least one *independent*
    non-social source already corroborates the same direction — a pure Reddit spike with no confirmation earns
    0. This is the core mitigation for the pump-vector mode (it stops rewarding manufactured attention in isolation).
  - **Require a minimum baseline history**: no z-score credit until the ticker has ≥N days of mention history
    (e.g. 14); below that, fall back to 0 (NOT the old presence +10) — closes the infinite-σ new-ticker degeneracy.
  - **Cap the term low** and treat ApeWisdom as a single noisy source (don't let an upstream artifact swing a tier).
  - **Schema discipline (db tripwire)**: this touches `db.py` — adding the numeric column requires a migration
    + retest of every feature that reads the affected tables; backfill the 30-day baseline before enabling, and
    keep the term flag-OFF (returning 0) until the backfill completes so no historical alert silently changes.
- **Kill-switch metric:** if social-driven alerts precede price moves no better than random over 30 fires, drop
  the social term entirely.

---

### E2 — Cross-asset regime confirm/veto multiplier — composite 9 (Medium) — *re-verify FRED access in Pass 3*
- **Function:** New `analysis/cross_asset.py` computing a market-wide regime score from free data (VIX/VIX3M
  term structure via yfinance; HY-credit HYG/LQD divergence; DXY+copper/gold+yields risk-on/off), feeding the
  existing `regime_classifier`/`engine.py` as a CONFIRM/VETO confidence multiplier on already-triggered
  *bullish* alerts. **Not a new alert generator.**
- **Rationale:** VIX-term-structure + HY-credit are HIGH-tier cited mechanisms; extends, not replaces, regime.py.
- **Failure modes (critic):** (high) correlations break in acute stress — a confidence-DOWN multiplier reliable
  in calm tape and unreliable in stress is a veto that fails exactly when it matters. (high) directional-
  conditional VIX backwardation (verified caveat) — backwardation often PRECEDES positive S&P drift; using it
  to veto longs suppresses them right before the bounce (wrong-sign on the headline input). (medium) FRED
  access unverified (abstained) — the credit-spread path may be a dead data path; only yfinance `^VIX`/`^VIX3M`
  is verified. (medium) market-wide veto crushes recall uniformly — a single score multiplies DOWN every
  bullish alert, suppressing idiosyncratic winners in a multi-week risk-off drift. (medium) **regression** —
  interacts non-linearly with the I14 graduated shift.
- **Safeguards (architect):**
  - **Use as a regime FLAG, not a predictor** (per the verified caveat): VIX backwardation widens the STRONG
    cutoff modestly / annotates risk context — it does NOT directly veto a long, so the wrong-sign "suppress
    before the bounce" mode is avoided.
  - **Multiplier floor**: the confidence multiplier is bounded (e.g. ×0.85 minimum) so a market-wide read can
    *dent* but never *crush* a strong idiosyncratic alert — closes the uniform-recall-crush mode.
  - **yfinance-only first, FRED as an optional enrichment**: build the VIX-term leg (verified data path) first;
    gate the HY-credit/FRED leg behind a separate flag and a Pass-3 FRED-access verification — never ship a
    dead data path. *Re-verify FRED in Pass 3.*
  - **Reconcile with I14**: combine the cross-asset shift and the regime z-shift into ONE bounded cutoff
    adjustment (don't stack two independent widenings) — closes the non-linear-interaction regression.
  - Shadow-first + flag-OFF: log the multiplier on bullish alerts for two weeks before it gates.
- **Kill-switch metric:** if cross-asset-vetoed/down-weighted bullish alerts hit their 1h target as often as
  un-vetoed ones over 30 risk-off-tagged alerts, the veto adds no precision — disable it.

---

### E1 — FINRA daily short-VOLUME confluence input — composite 7 (Medium) — *re-verify edge in Pass 3*
- **Function:** New `scanners/finra_short_volume.py` ingester → daily short-%-of-total + 30-day z-score per
  ticker → a small cross-reference confluence term, signed bearish ONLY on a surge confirmed by another source.
  Free, keyless, posted ≤6 PM ET.
- **Rationale:** A genuinely-absent free stream (short *volume* flow, distinct from the short *interest* snapshot
  already pulled).
- **Failure modes (critic):** (high) self-refuting signal quality — free FINRA short VOLUME ≠ short INTEREST;
  inflated by MM hedging, off-exchange-only; Kelley-Tetlock show retail short flow does NOT predict returns; the
  academic edge used proprietary order-level data the bot can't access — a weak noisy proxy mistakable for the
  strong signal. (high) mislabel-as-directional trap — a high short-% surge *looks* bearish and will tempt a
  directional read in thesis text. (high) crowded-trade/squeeze inversion — the same surge is the precondition
  for a short squeeze (violently bullish); free data can't disambiguate. (medium) latency — EOD-stale, useless
  intraday. (medium) **regression** — new scanner + new time series + 30-day z baseline (schema/backfill, db
  tripwire) + a new ScoreBreakdown term.
- **Safeguards (architect):**
  - **Confluence-only, never standalone, never a sign without confirmation**: the term contributes points ONLY
    when another independent source already agrees on direction — and even then is **surfaced as risk context,
    never as "directional short selling"** (a hard render rule, not a discipline) — neutralizes the
    mislabel-as-directional + squeeze-inversion modes by never letting it act alone.
  - **Display label is fixed and provenance-tagged**: render strictly as "short-volume % (MM-hedging-inflated
    proxy)" so the weak-proxy nature reaches the user — honors the verified caveat at the render layer.
  - **EOD-staleness contract**: tag every value with its FINRA publication time; never feed it into an
    intraday/per-tweet score as if fresh.
  - **Schema discipline (db tripwire)**: the new per-ticker series + 30-day baseline touches `db.py`; backfill
    before enabling, keep the term flag-OFF (returning 0) until backfill completes.
  - ***Re-verify in Pass 3***: confirm the FINRA file format + the leads-price evidence against the *free*
    (not proprietary) stream before any build — the composite sits at the cut line precisely because the
    free-data edge is the weak point.
- **Kill-switch metric:** if FINRA-short-confirmed alerts precede price moves no better than confirmed-without-FINRA
  alerts over 30 fires, drop the term (it adds noise, not signal).

---

### E3 — Gamma-exposure (GEX) flip level in `!all` — composite 7 (Moonshot) — *re-verify sign model in Pass 3*
- **Function:** New `analysis/gamma.py` computing net dealer gamma + the "gamma flip" level from the option
  chain the bot already pulls (yfinance), surfaced as dynamic support/resistance + a vol-regime hint in `!all`.
- **Rationale:** Reuses chains already pulled; no GEX equivalent exists today.
- **Failure modes (critic):** (high) GEX sign is model-dependent and not peer-reviewed (blog/SpotGamma-grade) —
  "dealers short gamma below the flip" is a heuristic that can be flat wrong; a wrong flip level rendered as
  support/resistance is **the NVDA-850 class of error the bot built three gates to prevent.** (high) yfinance
  chain quality — gamma math needs full strike-by-strike OI/gamma; yfinance OI is EOD, delayed, often missing/
  zero rows → a sparse chain yields a meaningless level that still renders as a clean number. (medium)
  display-as-level laundering — the level sits next to real price levels with equal authority and the existing
  `level_display_sanity`/`price_sanity` gates check ratio-to-spot, NOT provenance, so a plausible-but-wrong GEX
  level passes them. (medium) 0DTE/expiry-cliff instability — flips violently around large expiries. (low)
  **regression** — new `!all` field touches aggregator/embed tests + conftest all_command flags.
- **Safeguards (architect):**
  - **Label as a heuristic, never as a price "level"**: render explicitly as "GEX flip (dealer-positioning
    estimate, heuristic)" in a clearly-separate field — it must NOT enter the same support/resistance list the
    sanity gates trust, so the display-laundering + NVDA-850 modes are structurally avoided.
  - **Chain-quality gate**: compute the flip ONLY when the chain has ≥N non-zero-OI strikes across ≥2 expiries;
    a sparse chain → suppress the field entirely (no number) rather than render a meaningless one.
  - **Expiry-staleness contract**: tag the level with the expiries it was computed from and recompute / expire
    it around large/0DTE expiries; never show a mid-week level on Friday.
  - **`!all`-only, display-only, flag-OFF**: never feeds any score; the conftest all_command fixtures keep it
    off so the dedicated test forces it on.
  - ***Re-verify the dealer-sign model in Pass 3*** before any build — the composite is at the cut because the
    sign assumption is the unverified weak point.
- **Kill-switch metric:** if the rendered flip level is wrong (price doesn't respect it as S/R) on >30% of
  reviewed `!all` outputs over 2 weeks, pull the field.

---

### E6 — Adversarial input-integrity (manufactured-agreement) — composite 7 (Medium) — *UNVERIFIED, re-verify in Pass 3*
- **Function:** Coordinated-burst / duplicate-narrative detection on the ingest (many near-identical posts in a
  short window = suspicious) → down-weight rather than reward. Touches the ingest path + `cross_reference.py`.
  Distinct from I3: I3 catches *disagreement*, E6 catches *manufactured agreement*.
- **Rationale:** The attack surface is real and present (the bot ingests public tweets/Reddit/YouTube).
- **Failure modes (critic):** (medium) UNVERIFIED — `arxiv 2512.02261` not confirmed this run; build risk on an
  unproven defense, but under-building is also a risk. (high) burst-detection collides with legitimate breaking
  news — a real catalyst genuinely produces many near-identical posts; down-weighting bursts SUPPRESSES the
  bot's fastest, most valuable "before mainstream" signals (a direct recall hit on the highest-value alerts).
  (high) adversary adapts trivially — paraphrased/templated variants evade similarity detection; a semantic
  detector is expensive and itself LLM-spoofable. (medium) overlap/double-handling with I3 — both adjust the
  same source contributions; un-reconciled they double-penalize or cancel. (medium) **regression** — touches
  the ingest path; "N posts → N signals" and scoring tests flip.
- **Safeguards (architect):**
  - **Never suppress, only flag-for-corroboration**: a detected near-duplicate burst does NOT down-weight the
    signal; it instead *requires* an independent non-burst source before the burst can add confluence points —
    so a real breaking-news burst still alerts (the trigger is signal-first), it just doesn't get *extra*
    crowd-agreement credit from copies of itself. This directly neutralizes the highest-severity
    "suppress breaking news" mode.
  - **Reconcile explicitly with I3**: compute manufactured-agreement and contradiction in one pass over the
    same source set with a defined precedence (corroboration-requirement applied before the contradiction
    index) — closes the double-handling mode. E6 lands AFTER I3.
  - **Detect coordination by account-diversity, not text-similarity alone**: weight on the number of
    *independent* accounts vs near-identical timing, so paraphrase-evasion doesn't defeat it (a paraphrased
    coordinated burst still shows abnormal account-clustering).
  - **Regression**: ingest path stays "N posts → N signals" (no signals dropped); only the confluence credit
    changes, behind a flag, so ingest tests pass with the flag off.
  - ***Re-verify `arxiv 2512.02261` in Pass 3*** before any build.
- **Kill-switch metric:** if the corroboration-requirement suppresses confluence on alerts that go on to hit
  their target as often as un-flagged ones over 30 burst events, the detector is firing on real news — disable it.

---

## Dropped

| id | name | drop reason |
|---|---|---|
| **E5** | LLM bull/bear debate + critic loop | Composite **4 ≤ 6**. Fails BOTH drop tests: unverified, only support is a single abstained claim (TradingAgents/FinCon, not confirmed this run), AND feasibility low (3+ sequential LLM calls per thesis on a free-tier budget that already hits Groq daily-token-cap + Gemini per-day quota — multiplies the documented hollow-fallback failure). Critic: debate amplifies hallucination → confident, well-argued WRONG theses (more persuasive slop, opposite of precision); critic loop rationalizes the prior thesis rather than overturning it. Revisit only if the pattern is independently re-verified AND the LLM budget is no longer the binding constraint. |
| **E4** | Options-flow calibration correction | **Merged into I6** (per analyst verdict + E4's own status line). Not a standalone feature — it is the verified constraint that I6's public-options signal must be horizon-capped (intraday/1–2 day, confluence-only) and never inherit the proprietary academic edge in score or thesis text. Tracked inside the I6 safeguards as a mandatory regression assertion, not a footnote. |

No internal candidate (I1–I18) was dropped — all sit at composite ≥ 9. The lowest-composite *kept* externals
(E1/E3/E6 at 7) clear the ≤6 cut but carry **re-verify-in-Pass-3** flags because each rests on either a weak
free-data proxy (E1), a model-dependent unproven sign (E3), or an unverified abstained paper (E6).

---

## Implementation notes

### Sequencing & dependencies (the critic flagged ordering as the main cross-candidate risk)

**Wave 1 — independent quick wins, ship first (lowest blast radius):**
- **I9** (knob reconnect, inert at default 20) — fully independent.
- **I16** (Wolf-outcome benchmark, recap-only) — independent, no live-alert risk.
- **I12** (earnings magnitude) — independent catalyst-path change.
- **I14 display half** (regime risk-context line) — pure-additive; ship the line before the widening change.

**Wave 2 — per-source scoring corrections (must land before the reconciliation):**
- **I1** (sign YouTube) — independent, but ship `channel_reliability` + min-channel-floor together.
- **I2** (analyst accuracy weighting) — produces the **hardened accuracy primitive** (Wilson LB, n≥10 floor)
  that **I7 must reuse** — so **I2 before I7**.
- **I5** (SEC graduation + 10b5-1 exclusion) — its 10b5-1 exclusion is **reused by I15**, so **I5 before I15**.
- **I6** (options sign/scale + E4 constraint) — must carry the horizon attribute; **its real direction sign is
  a prerequisite for I3's index** (until I6 lands, options contributes no sign to the contradiction index).
- **I8** (herding) — reconcile with I7 (de-correlate shared analysts) in the same wave.
- **I7** (consensus_boost log-odds) — **after I2** (shared accuracy primitive) and reconciled with I8.

**Wave 3 — contradiction + hard-evidence gates (depend on Wave-2 signs existing):**
- **I3** (contradiction_index producer) — depends on **I5 + I6 signs** to avoid fabricating disagreement over
  unsigned sources.
- **I10** (hard-evidence STRONG gate) — independent logic, but pairs naturally with the contradiction work.
- **E6** (manufactured-agreement) — **after I3**, reconciled in one pass (corroboration-before-contradiction).

**Wave 4 — reconciliation + display (must land LAST among scoring changes):**
- **I4** (reconcile the two scorers) — **after I1/I2/I5/I6/I7** so the reconciled number reflects corrected
  components. Pins the order-of-landing the critic said was unpinned.
- **I14 widening half** — reconcile with **E2** into ONE bounded cutoff adjustment (don't stack two widenings).
- **E2** (cross-asset) — yfinance VIX leg first; FRED/HY-credit leg gated behind a separate flag + Pass-3
  FRED-access re-verify.

**Wave 5 — depends on a trustworthy reconciled score + contradiction index:**
- **I18** (reliability render block) — **hard-gated on I3 + I4 being live AND past their shadow windows**; a
  wrong verdict block is worse than a blank one.
- **I17 calibration** *(deferred-style moonshot, not in this filtered set's top tier but noted for dependency)*
  — would land **after I4** so it calibrates ONE coherent score; calibration data is stale the moment the
  Wave-2 weight changes land, so any I17 retrain must use **only post-Wave-2 outcome rows**. (I17 was not
  re-scored here because it falls outside the immediate filtered build; flag if Pass 3 wants it ranked.)

**New-data / new-schema items (slowest, isolate):**
- **E1** (FINRA scanner + new time series), **I13** (ApeWisdom numeric column + 30-day baseline) — both add a
  per-ticker series to `db.py`; backfill before enabling, keep flag-OFF returning 0 until backfill completes.
- **E3** (gamma) — new module, `!all`-only, display-only, no schema.

### Shared-file tripwire (CLAUDE.md DoD — full-feature retest if touched)
Several survivors touch the five tripwire files. **Touching any of these requires retesting every feature that
uses them, not just the changed line:**
- `cross_reference.py` — touched by **I1, I2, I3, I5, I6, I7, I10, I11, I13, I18, E1** (the heaviest contention
  point). Sequence these waves so the file is changed in coherent batches, and run the full cross-reference +
  `!all` + alert path after each batch.
- `config.py` + `config/consensus.yaml` — touched by **I1, I9** (and every flag-gate this plan adds). Adding
  flags that default ON in tests breaks older tests that read live config — use the **autouse conftest
  force-off fixture** (the documented `wolf.confluence.*` / `conftest flag-default-off` pattern) for every new
  user-visible flag, including `features.youtube_score.*`.
- `db.py` — touched by **I2** (accuracy read), **I8** (event-id wiring), **I13 + E1** (new numeric columns).
  Any schema change is the always-on db tripwire: migrate, backfill, retest every reader.
- `narrator.py` — touched by **I6** (E4 constraint: forbid "smart money" framing for public flow) and
  indirectly by any thesis-text change. Retest `!all` narration after.
- `aggregator.py` — touched by **E3** (new `!all` field), **I6** (options ratios). Retest the full `!all`
  ~28-source gather.

### Regression-gate reminder
- **Establish the baseline first**: `make test-baseline` before any feature work; no commit may make a passing
  test fail (set matters, not count).
- **Every new user-facing behavior ships flag-OFF + shadow-first + kill-switch** — this is the house rule and
  it is also the primary regression defense, because a flag-off default keeps the live baseline unchanged.
- **The critic's recurring regression theme**: many of these change a scoring term that feeds nearly every
  end-to-end test (`analyst_pts` cap 60, `sec_pts` flat 15, `options_pts` +10, `consensus_boost` cap 60,
  `youtube_pts` sign). Each must be flag-gated AND its dependent term mocked in general tests, with the new
  behavior asserted only in a dedicated feature test that forces its own flag.
- **Separate verifier at end of feature work** (not the author) re-runs the full suite and diffs the baseline,
  per the regression gate.
- **Always-on checks every restart**: `consensus-engine.service` + `openclaw-gateway.service` both active; no
  GATEWAY-drift / LLM-health alert; `/root/.openclaw` symlink intact.
