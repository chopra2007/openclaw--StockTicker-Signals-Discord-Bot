# Build an accurate market top/bottom detector — research how others did it

**Status:** OPEN
**Created:** 2026-06-17

## Goal
Detect US equity-index (SPY/QQQ) **tops and bottoms early — before the move — with few false
alarms.** Flag an intermediate top ahead of a ≥8% drop (within ~60 trading days) and a bottom ahead
of a ≥8% rally, firing during the turning window. Must have a **real, out-of-sample-validated edge
with a low false-positive rate**, not an in-sample curve fit. Free/affordable public data preferred.

## Where this stands (2026-06-17)
The **daily-price/volume/breadth approach is exhausted and ruled out with statistical rigor.** Phase 1
(single signals) and Phase 2 (the multi-signal confluence + a continuous score + a two-stage model)
both came back **NO-GO**. Next phase is a **research mission** (prompt embedded below) to find how
others actually achieve this — almost certainly with richer data inputs we don't yet have.

## What we built (committed code — recoverable)
Repo: `volatility_regime_reversal_indicator/` (part of the main workspace git repo).
- **Phase 1** (commits bf61ed0/fd809dc/a8a8f93/26fc837): honest single-signal backtest harness —
  point-in-time features, next-open entry, episode collapsing, regime-matched null, BH-FDR + max-stat
  reality check, 5-gate kill-gate. Result: FAIL (no single signal has edge). Report:
  `backtest/ABLATION-REPORT.md`. Frozen contract: `backtest/preregistration.yaml`.
- **Phase 2** (commits df3515f + 58398d3, 2026-06-17): the CONFLUENCE the kickoff asked for, CCG-vetted.
  - `src/data/fetch_breadth.py` — free broad-US advance/decline feed (thetrading.tools, 4139 rows
    2010-26) → store series `ABINYSE` (a broad-US ABI PROXY, not NYSE-only; self-normalizing ratio).
    NOTE: `data/store/` is gitignored → re-fetch on a fresh clone; append-only restatement guard.
  - `src/features/utils.py::rolling_ols_residual` — beta-adjusted VVIX-vs-VIX residual (look-ahead-tested).
  - `src/signals/conditions_phase2.py` — 11 frozen constructions + continuous Distribution-Stress
    Index (DSI) + eligibility masks. (Raw VVIX/VIX-slope leg dropped as a search artifact.)
  - `src/backtest/phase2.py` + `src/run_phase2.py` — the confirmatory battery; report:
    `backtest/PHASE2-REPORT.md`. Frozen contract: `backtest/preregistration_phase2.yaml`.
  - Tests: `tests/test_lookahead_phase2.py`, `tests/test_preregistration_phase2.py`. 68 pass.
- Discover run working notes (GITIGNORED, local only): `.claude/discover/vol-indicator-accuracy/`
  (pass-0/3/5 artifacts, ground-truth-episodes.md, ccg-bundle.md, gemini-review.txt, RESEARCH-MISSION.md).

## What held up (INCONCLUSIVE — do NOT treat as validated; tests weren't conclusive)
- The **breadth-narrowing gate** (`concentration_regime = pct_change(RSP/SPY,60) < 0`) beat the bare
  stack at matched alert count (G5 pass, bootstrap diff p05 +0.026). The one component with a hint of
  real information. Untested forward.
- The **DSI is a robust CALM detector** (predicts LOWER forward volatility, rank-IC −0.23 SPY / −0.25
  QQQ, transfers across assets). That's a real relationship — but it's a *different* product (a
  complacency gauge), NOT a top predictor.

## What did NOT work, and why
Results (all from the actual confirmatory run, `backtest/PHASE2-REPORT.md`):
- Single signals: no edge (Phase-1 kill-gate FAIL).
- Binary confluence: best top precision +12pp but opportunity-set null p≈0.13 (not significant). The
  earlier "+13pp/p=0.03" was inflated by an artifact leg (raw VVIX/VIX slope) + a too-easy all-days null.
- **Cross-asset transfer to QQQ = NEGATIVE edge** → strongest sign the S&P result was overfit.
- **Continuous DSI → forward drawdown rank-IC = −0.09 across 3,815 days (p≈0.85)** → essentially zero
  WITH full statistical power, so "too few examples" is NOT the cause.
- Two-stage watch→break: +8–10pp on S&P but not significant and no QQQ transfer.
- Bottom detector's high precision was an artifact: once already 5%+ down, an 8% bounce within 60 days
  happens ~92% of the time anyway (the eligible base rate) → no real edge.
- VVIX/VIX (both slope and residual encodings) and the low-ABI breadth leg added no validated edge.

**Why (our hypotheses — the research mission must verify/refute):**
1. "Compression/churn near the highs precedes a top" is, in this data, mostly a **calm-market
   signature that precedes more calm**, not distribution before a drop. Genuine tops are too rare
   (~7–10 in 16 years) to separate from the many benign calm stretches.
2. The institutional-distribution fingerprint the thesis describes (smart-money tail-hedging, selling
   into strength) is likely **not visible in daily price/volume/breadth** — it needs richer inputs we
   don't have: **options positioning / dealer gamma, tick-level or true-exchange breadth, order flow.**
   We're measuring the phenomenon with too blunt an instrument.

## Cross-model review conclusions (Codex gpt-5.5 + Gemini)
Both said the original design was a NO-GO but the goal is **buildable if restructured** (NOT impossible):
- Codex: two-stage watch→trigger; price-break confirmation; dual breadth; credit as a soft score;
  opportunity-set null. (We built + tested these; they didn't clear the bar.)
- Gemini: continuous score instead of binary thresholds; cross-asset validation; credit momentum;
  liquidity-filtered breadth. (Built + tested the continuous score — failed with full power.)

## Next steps (priority-ordered)
1. **RUN THE RESEARCH MISSION (below).** Fact-find how others actually do this (data + method +
   out-of-sample evidence + false-alarm rates), propose a plan, adversarially review it. This is the
   user's chosen next move ("don't reinvent the wheel"). Prompt is self-contained — can be handed to
   any deep-research tool, or launched in a fresh session reading `.claude/discover/vol-indicator-
   accuracy/RESEARCH-MISSION.md` (also embedded below for git-recoverability).
2. After research: likely **acquire/forward-collect richer inputs** (options positioning / dealer
   gamma via CBOE delayed quotes; true NYSE breadth via WSJ; put/call) — these can't be backfilled,
   so start collecting NOW to build forward history, judge in months.
3. **Forward-test the breadth-narrowing gate** live on fresh data (the only honest way to confirm a
   backward-looking lead).
4. (Optional pivot) Ship the **DSI calm/complacency gauge** as an honest context feature — it works
   and transfers, just a different product than a crash predictor.

## Open questions
- Which non-daily inputs actually carry the distribution signal, and which are free/affordable?
- Is there published evidence of any method with real out-of-sample top/bottom accuracy + low false
  positives, or is most of it in-sample/marketing?
- Can the target be reframed (predict a fragile regime, not a binary crash) into something validatable?
- Is true NYSE-only breadth (vs the broad-US proxy) materially better, and worth forward-collecting?

## How to pick this up cold
Read `backtest/PHASE3-REPORT.md` (latest verdict), then `backtest/PHASE2-REPORT.md`, then this file.
The harness + honesty machinery are reusable; any new method MUST plug into it (point-in-time,
opportunity-set null, cross-asset transfer, temporal hold-out, pre-registration).

---

## Phase 3 — RAN, honest NO-GO both sides (2026-06-18)
Built the research mission's free, buildable-now subset and judged it under the SAME honesty harness
plus a benchmark battle + a pre-registered alert budget (7-gate kill-gate). Report:
`backtest/PHASE3-REPORT.md`. Frozen contract: `backtest/preregistration_phase3.yaml`. Code:
`src/features/utils.py` (new `variance_risk_premium`, `zweig_breadth_thrust`),
`src/signals/conditions_phase3.py`, `src/backtest/phase3.py`, `src/run_phase3.py`. Tests:
`tests/test_lookahead_phase3.py`, `tests/test_preregistration_phase3.py`. Full suite 90 green.

**What we built (Track A):**
- TOP: a 4-leg WATCH-STATE composite (low variance-risk-premium = complacency; high VIX/VIX3M term
  stress; high VVIX-vs-VIX residual; breadth narrowing) → a 2-stage TRIGGER (watch-state in its own
  top quintile AND SPY closes below its 50-day average). The first time we've actually tested VRP.
- BOTTOM: capitulation washout → a RARE breadth thrust. Canonical NYSE Zweig (0.40→0.615) fires only
  ~6x in 16y / none post-2019 on our broad-US feed, so we used a self-normalizing percentile thrust
  (10-day adv-ratio EMA's trailing-252 percentile 0.10→0.90), gated by a washout within the prior 25d.

**Result — NO-GO both sides (the anticipated, honest outcome):**
- TOP (best T_watch_break): edge +0.090 (precision 0.310 vs eligible-base 0.221) but oppset null_p
  0.384 — NOT significant. 9 of 29 alerts preceded a ≥8% top; recall 4/10 organic (clears the floor).
  QQQ transfer edge +0.024 (p 0.522) — POSITIVE (Phase-2 was −0.028) but not significant. The dumb
  200-day-break baseline had HIGHER precision (0.478) but caught 0/10 tops early (precise-but-late) →
  detector loses the benchmark battle.
- BOTTOM (best B_thrust): edge NEGATIVE −0.154 (precision 0.769 vs eligible-base 0.923), null_p 0.970.
  The 92% base-rate trap CONFIRMED AGAIN: among −5% pullback days, 92.3% precede an 8% bounce within
  60d; the rare thrust did not beat that (even underperformed — it fires late, after the bounce starts).
  `washout_only` (0.957) beat the gated thrust (0.769) → the thrust requirement HURT.
- Ships DESCRIPTIVE-ONLY (a fragility/complacency gauge); NO live alert flipped on. Confirms the
  research's core finding: free VIX-derived data + broad-US breadth can't hit the exact ≥8% turn.

**What shipped LIVE (Track B — forward-collection, can't be backfilled):**
- `src/data/fetch_putcall.py` → `CBOE_PUTCALL` (total/equity/index/etp put-call ratios; free CBOE
  daily page, backfillable to ~2019-10-15).
- `src/data/fetch_nyse_breadth.py` → `NYSE_BREADTH` (true NYSE adv/dec ISSUES **and UP/DOWN VOLUME**
  — the volume our ABINYSE proxy lacks; unlocks a future Lowry 90/90). Snapshot-only source, no free
  history → forward-collected.
- `scripts/collect_daily.sh` + `vol-collect-daily.timer/.service` (daily 22:30 UTC, runs as root, the
  store is root-owned). Append-only + restatement guard. NOTE: `data/store/` is gitignored.

## Next steps (priority-ordered)
1. **JUDGE TRACK B IN A FEW MONTHS.** Once CBOE put/call + true NYSE up/down volume have built forward
   history, add them as new legs: a put/call leg in `top_watch_state` and a Lowry 90/90 up/down-volume
   confirmation in `b_thrust`. Each is a one-line append + a prereg cell + a look-ahead-test entry, then
   re-run `python3 -m src.run_phase3`. This is the real bet for a future GO.
2. **Acquire the richer paid inputs** the research endorses if budget allows (ORATS near-EOD SPX/QQQ
   options for decomposed tail/jump/skew measures; dealer-gamma reconstruction; Norgate point-in-time
   constituents). They plug into the same watch-state composite.
3. The DSI/watch-state can still ship as an honest descriptive complacency gauge (works, transfers; a
   different product than a crash predictor).

## Update 2026-06-19 — options 1 + 3 actioned
- **(3) SHIPPED the descriptive complacency gauge:** `python3 -m src.show_fragility` prints today's
  fragility/complacency reading (overall + 4 components, plain-English, honest "NOT a crash predictor"
  caveat). Display-only, no alerts. Refactored the 4 legs into `conditions_phase3.watch_state_components`
  (single source of truth; verdict byte-identical). Smoke test added; suite 95 green.
- **(1) SCHEDULED the re-test:** reminder `task_1781855064_53203d.timer` fires **2026-07-19 (1mo)** ->
  appends to notifications.log. Full turnkey steps in `volatility_regime_reversal_indicator/PHASE3-FOLLOWUP.md`
  (add put/call leg to watch-state + Lowry 90/90 up/down-vol leg to b_thrust, freeze prereg, re-run).
  At the 1-month mark: CBOE put/call backfills to 2019, so its TOP watch-state leg is testable then;
  NYSE up/down-volume is forward-only (~1 month accrued, still too thin for the Lowry bottom leg — note
  coverage and defer that leg until 6-12 months exist).

## Update 2026-06-19 — "no-wait" path: tested the free data NOW instead of waiting; FREE SEARCH EXHAUSTED
User asked how to hit the goal without waiting 1-3 months. Found + ingested 3 free, no-wait data sources
(verified live), then ran two new pre-registered backtests + separate-architect verification. Both honest
NO-GO. Net: the free-data search for a validated SPY/QQQ top/bottom detector is now EXHAUSTED.

New free data ingested (fetchers committed; store gitignored):
- `SQZ` = SqueezeMetrics dealer-gamma (gex) + dark-pool (dix), 2011-05..2026, 3806 rows. The one free,
  NON-VIX-derived signal the research endorsed that we lacked. `src/data/fetch_squeeze.py`.
- `NYSE_UDVOL` = unicorn.us.com TRUE NYSE up/down VOLUME, 1965-03-01..2020-02-10, 13867 rows (archive
  froze 2020-02-10). This is what the Track-B forward feed collects one day at a time — but free + 55yr.
  `src/data/fetch_updown_volume.py`. (Sanity: 2008-10-09 = 95.5% down vol; 2008-10-13 = 95% up vol.)
- `GSPC` = ^GSPC index for the long-window price/outcome series. `src/data/fetch_gspc.py`.
- (put/call deep backfill to 2019 also run — low-prio top sentiment leg.)

**Phase 4 — Lowry 90/90 BOTTOM detector on 55yr real volume (commit 7116765): NO-GO.** `src/run_phase4.py`,
`conditions_phase4.py`, `preregistration_phase4.yaml`, `PHASE4-BOTTOM-REPORT.md`. 49 collapsed 90/90
episodes; primary w10 35/49 prec 0.714 vs equally-distressed base 0.704 = edge +0.011 null_p 0.538; best
cell w5 27/37 prec 0.730 edge +0.026 null_p 0.469. Controls (thrust-only 0.636, capit-only 0.678) ~as
strong -> the capitulation->thrust SEQUENCE adds nothing beyond "distressed days bounce anyway". Kill-gate
4/7 fail. 55yr finally gave real power and the edge STILL isn't there -> not a data problem.

**Dealer-gamma TOP+BOTTOM detector w/ QQQ transfer (commit 3ecd406): NO-GO both sides.** `src/run_gamma.py`,
`conditions_gamma.py`, `preregistration_gamma.yaml`, `PHASE-GAMMA-REPORT.md`. TOP best lead
G_neg_gamma_break[50] (gex<0 AND SPY<50d-MA) edge +0.128 oppset p=0.092 (suggestive). Harness max-edge
cell clears G1+G2 in-sample (edge +0.381 p=0.016) but is a 10-fire small-sample artifact -> fails G3
**QQQ transfer (edge +0.268 p=0.064 — the CLOSEST miss in the whole project)**, G4 recall (0 organic
tops), G5 control, G6 trend benchmark. BOTTOM dix-capitulation edge -0.004 (washout carries it). QQQ
cross-asset transfer is AGAIN the binding constraint (Phase 2 -0.028, Phase 3 +0.024, gamma +0.268 p=0.064).

CONCLUSION: every free lever (price/vol/breadth compression, VRP, VVIX-residual, Zweig/Lowry breadth
thrust on true volume, dealer gamma, dark-pool) is NO-GO under the honesty bar. Per the research, a
validated TOP detector needs PAID decomposed option-surface data (ORATS ~$99/mo, free trial; full history
on day one). The gamma top signal almost cleared the QQQ transfer (p=0.064) and is the best lead — it +
the paid surface is the next attempt. DECISION PENDING with user: (a) try the ORATS free trial, or
(b) stop at free and ship the gamma/90-90 readings descriptive-only. Suite 141 green.

## Update 2026-06-19 (cont.) — Alpha Vantage = a cheap PAID path to the option surface; DECISION PENDING
The free search is exhausted (above). The next attempt needs paid decomposed option-surface data, and
Alpha Vantage turns out to be a better/cheaper source than ORATS:
- **AV `HISTORICAL_OPTIONS`** returns the FULL historical option chain for any US symbol (SPY/QQQ incl.)
  on any date back to **2008**, with **implied volatility + every greek (delta, gamma, theta, vega, rho)**.
  Verified LIVE on the demo key (IBM 2017-11-15 = 998 contracts w/ greeks+IV). CSV or JSON. Also
  `HISTORICAL_PUT_CALL_RATIO` (back to 2008). This IS the research-endorsed surface (VRP / decomposed
  skew / tail asymmetry / gamma) — we compute the measures ourselves from the raw chains.
- **Cost:** cheapest premium tier **$49.99/mo includes end-of-day options** (ORATS is $99/mo). We only
  pull the history ONCE → one month, backfill SPY+QQQ 2008-2026 (~9k calls @ 75/min ≈ 2h), store, then
  CANCEL → effectively **~$50 one-time**.
- **User's existing key** is in `/root/.openclaw/.env.service` (+ /home/... symlink) as
  `ALPHAVANTAGE_API_KEY`. It is **FREE-TIER** (valid — confirmed via GLOBAL_QUOTE SPY=$746.74 — but
  options endpoints return "This is a premium endpoint"). Free tier has NOTHING useful for this detector:
  options/put-call/vol-to-OI all premium-locked; OHLCV+technicals are redundant (we have prices);
  Treasury/FedFunds are macro/low-relevance; NEWS_SENTIMENT is free+new but only 2022+ history and is the
  sentiment family that already failed (note: NEWS_SENTIMENT may be useful for the consensus_engine alert
  bot — separate task, not this one).
- **Also done this session:** `CBOE_PUTCALL` deep-backfilled to **1678 rows, 2019-10-15..2026-06-17**
  (was 33). The low-prio put/call TOP sentiment leg is now testable too (still expected weak — sentiment).

**DECISION PENDING WITH USER (the fork):**
- **(A) Spend ~$50 (one month AV premium), go for a real PREDICTOR.** Next-session turnkey: user upgrades
  the AV plan (key unchanged, premium unlocks instantly) → write `src/data/fetch_av_options.py`
  (HISTORICAL_OPTIONS per trading day, datatype=csv, append-only store of raw chains for SPY+QQQ
  2008-2026) → compute surface legs (variance risk premium, downside-semivariance VRP, DECOMPOSED
  negative skew, dealer-gamma exposure) → freeze a phase-5 prereg → run the full honest backtest INCL the
  SPY→QQQ transfer (the persistent killer) + the gamma near-miss (best lead, was edge +0.268 p=0.064).
  Odds: MEDIUM, not a sure thing.
- **(B) Stop at the free ceiling, ship DISPLAY-ONLY.** Three plain-English readouts (no predictions, no
  Discord alerts): the complacency gauge (already built: `python3 -m src.show_fragility`), + add a
  dealer-gamma reading + a 90/90 panic-thrust state. Then mark #47 done at the free ceiling.

User leaning unclear at session close (was asking clarifying questions about cost + what display-only
means). Resume by re-presenting this fork. NOTHING built for either path yet — awaiting the choice.

## APPENDIX — the research-mission prompt (canonical location)

The full, current research-mission prompt lives in its own file:

**`volatility_regime_reversal_indicator/RESEARCH-MISSION-FREE-ONLY.md`** (committed 87c0d14, 2026-06-20)

That file is the authoritative version. It adds two constraints the user requested on 2026-06-20
that the old embedded copy here did NOT have:
1. **No paid services whatsoever.** Free trials are acceptable only if confirmed to deliver enough
   backtestable history (a forward-only trial is useless).
2. **Open scope — no "15+ years of daily data or nothing."** Data span, granularity (daily / intraday /
   tick / weekly), and event definition (binary / graded / hazard) are all open to the researcher; only
   the honesty principles (point-in-time, fair null, out-of-sample hold-out, cross-asset/regime
   transfer, raw counts, pre-registration) are non-negotiable.

The earlier inline copy of the prompt was removed from this file to avoid two versions drifting apart.
Hand a fresh session the file above (not this TODO) when running the research mission.

---

## Update 2026-06-24 (run `todo-sweep-2026-06-24`) — research mission RAN; the one new free lead = NO-GO; display readouts shipped
Ran the free-only research mission. It surfaced exactly **one** genuinely-new, free, backtestable lead not already killed:
**cross-sectional return dispersion** (Maio & Saffi 2016, J. Financial Markets — high dispersion of constituent
returns OOS-forecasts a LOWER forward equity premium; correct sign for a top precursor; free via yfinance constituents;
a mechanism distinct from everything tried). Everything else the survey raised was rejected with cited reasons:
HMM/regime-switching (lagging, detects "during the end of the crash", not early), implied/realized correlation
(coincident base-rate trap, surges DURING selloffs), CBOE SKEW + VIX term structure (non-directional / bottom-only,
already in our data), Google Trends (per-query renormalization breaks point-in-time reproducibility), standalone LPPLS
(no published clean false-positive rate), hazard/survival (reframes the SAME ~12 thin events, no new data). Also noted:
FRED now only distributes a rolling 3-yr window of HY OAS — use Treasury slope (T10Y3M/T10Y2Y) for any future credit angle.

**BUILT + TESTED dispersion under the existing honesty harness** (`src/data/fetch_constituents.py`,
`src/features/utils.py` dispersion legs, `backtest/preregistration_dispersion.yaml` frozen before scoring,
`src/signals/conditions_dispersion.py`, `src/run_dispersion.py`, look-ahead + prereg tests; 161 suite green).
Fetched 148/150 S&P + 97/100 Nasdaq-100 daily closes (2 delisted each), panel 2006-2026, 12 in-window tops scored.
**HONEST VERDICT: NO-GO** (report `backtest/PHASE-DISPERSION-REPORT.md`, verified by my own run):
- G1 precision: edge **+0.043pp** (need +8), oppset null_p **0.306** (need <0.05) — FAIL.
- G2 MTC reality_p 0.393 — FAIL. G3 **QQQ transfer edge +0.010, null_p 0.474 — FAIL** (the persistent killer again).
- G4 recall 11/12 organic — PASS (only gate passed). G5: the near-high gate HURT precision (gated 0.268 < dispersion-only
  control 0.354) — the OPPOSITE of the thesis. Dispersion correlates with volatile/stressed regimes generally, not
  distribution tops specifically. (Survivorship caveat pre-registered: precision is an upper bound, so the real result is
  if anything weaker.)
- **Conclusion: the FREE-data search for a validated SPY/QQQ top/bottom predictor is now TRULY exhausted** — every lever
  (price/vol/breadth, VRP, VVIX-residual, Zweig/Lowry on true volume, dealer gamma, dark-pool, put/call, **and now
  cross-sectional dispersion**) is NO-GO under the honesty bar. The QQQ cross-asset transfer is the consistent binding
  constraint (best-ever near-miss stays the dealer-gamma top at p=0.064).

**SHIPPED (path B — display-only, descriptive):** added two blocks to `python3 -m src.show_fragility` (verified by my own
run): a **dealer-gamma block** (GEX trailing-252 percentile 71st, neg-gamma regime OFF, DIX 35th) and a **same-day 90/90
state** (NYSE up/down-vol share vs the 90% line — today 49.1%/50.9% → NEITHER; explicitly notes trailing-percentile context
is still accruing, only ~6 forward rows). Both carry the existing "descriptive only — NOT a predictor (NO-GO)" caveat. The
complacency gauge + gamma + 90/90 readouts together complete path B.

**DECISION FORK (now the only open question for #47):** the goal (an *accurate* predictor) is unreachable on free data —
proven exhaustively. Two honest end-states: **(A)** the user reverses the no-paid directive and spends **~$50 one-time**
(one month Alpha Vantage premium → backfill SPY+QQQ option surface 2008-26 → compute decomposed VRP/skew/gamma legs →
re-run the harness incl. the QQQ transfer + the gamma near-miss; key already in `.env.service`, MEDIUM odds), or **(B)** accept
the free ceiling and close #47 with the display-only product shipped. Per the 2026-06-20 "no paid" directive the current
answer is B; surfacing A as the standing reversible decision.
