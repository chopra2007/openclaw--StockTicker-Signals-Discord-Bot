# Bot design review & build plan — July 2026

A six-lens research review of the consensus-engine stock-signal Discord bot, grounded in verified
code/DB/log facts and the bot's own logged outcome history, then hardened by two independent
adversarial reviews (GPT-5.5 via codex + a repo-aware critic that re-ran the load-bearing numbers).

- Verified ground truth: `.omc/plans/bot-research-build/facts.md` (+ `facts-*.md`)
- Per-lens cited research: `.omc/plans/bot-research-build/lens1..6-*.md`
- Adversarial pass + reconciliation: recorded at the end of this file.

**Product goal every idea is judged against:** surface higher-probability trades, minimize false
positives — not a screener. **Hard constraint:** free data/tools only.

---

## Executive summary (blunt)

1. **The bot's confidence is measurably wrong, and — worse — the alerts it actually fires are
   near-random.** The score→probability map scores Brier 0.253/0.256 (1h/24h) — worse than always
   guessing the base rate (independently re-verified). And the alerts that reach users
   (`alert_history`, n=3,741) go *up* 24h later only **43.8%** of the time — below a coin flip;
   even the highest-conviction fired alerts (avg confidence 86/100) hit just 51%. The firing gate
   is not selecting a better slice. *(Caveat: the up=hit test assumes mostly-long alerts; a
   direction-aware version is owed before over-claiming — but the product framing and real cards
   are long-biased.)*

2. **The core job is not "add signals" — it's to measure which ideas work, find the pocket of
   edge, and abstain on the rest.** Pooled rank-discrimination is a coin flip (AUC ~0.507 at 24h),
   but the top decile of predictions shows real lift. So the score *may* contain a thin,
   high-precision pocket while the probability mapping is broken. Those are different problems: fix
   the honesty (recalibrate) AND hunt the pocket (precision@k on subgroups), then stop emitting the
   noisy middle.

3. **The bot has no feedback spine.** 93 flags, 75 ON, and nothing standing reads the exact data
   that proves the product goal: `decision_snapshots` (3,134 rows, full feature+weight+score),
   `shadow_predictions` (5,591 resolved), `alert_history` (3,741 with realized prices). "Tested on
   real data" today is a one-off notebook that evaporates.

4. **Only 6 of 12 signals feed the score;** five *validated* ones (max-pain, analyst momentum,
   EPS-revision, peer relative-strength, chart patterns) are display-only. That is headroom — but
   it can only be cashed in *through* measurement (each must earn held-out lift), never by hand-set
   weights. Given AUC ~0.507, expect several to earn nothing.

5. **The output lies with a straight face.** One $MU spike fired **three Discord embeds in one
   second** with two disagreeing scores (25 vs 83). A real `!all` card showed Micron at **$1154
   spot / $1645 target — ~10× off reality** (verbatim-verified), quoted to the cent, tagged "LOW
   confidence" yet written as a full "Long above $1132" order. "83" reads as 83% when the engine
   itself prints "uncalibrated". The one decision-relevant line — invalidation — is a process
   index, not a stop price.

6. **`!all` renders a confident card even when every source silently failed** — `source_failures`
   is computed and never shown; the safety wrappers swallow exceptions to `None` so the classifier
   can't tell a dead source from an empty one.

7. **Latency is already solved — stop optimizing it.** `head_start` is a textbook hedged-request
   implementation; median ~38s over 12 runs/month. The real LLM problem is a *separate* OpenRouter
   402 credit-exhaustion breaker that fires often and silently degrades thesis quality — and the
   breaker's learned OPEN state is thrown away on every restart, so it re-hammers dead providers.

8. **No SQLite backups exist** for a 673MB single-file DB in a tree with ownership-flip crash
   history; newest hand-made `.bak` is a month old. This is the highest-consequence silent risk and
   it sits *under every other recommendation* (they all read this DB).

9. **The Wolf extractor's hardest case is unsolved by construction** (single-shot prompt, IGV
   hard-coded). A proper extractor→verifier redesign exists on paper and is trap-proof — but it's a
   large build on a *side* pipeline, can't be proven on real outcomes (39 scored rows), and its
   "free local NLI" isn't free on this box. It belongs on the roadmap, not this session.

10. **Two documented "dead" verdicts revisited:** market top/bottom predictor stays **NO-GO**
    (horizon mismatch no free combination fixes). But the analyst-track-record scorer was benched
    at the *wrong* horizon (1h, where a slow signal is expected-null) — it deserves a fair 24h/5d
    trial behind a real statistical gate.

**The spine:** protect the data (backup), then build a *simple* honest-measurement loop and let it
tell you the truth (recalibrate + find the edge pocket + abstain), then make the UI honest. Only
after measurement earns it: fold in signals, and the deep Wolf rebuild. Everything speculative
waits behind a measured green light.

---

## Ranked recommendations (buildable now, free data) — post-adversarial

Re-ranked after the adversarial pass. Effort S/M/L; live-risk noted.

### #1 — DB safety net (do first) — S
Nightly `db_maintenance.timer`: `wal_checkpoint(TRUNCATE)` → `quick_check` (alert to
`notifications.log` if not ok) → `VACUUM INTO` snapshot, keep last 7; weekly `integrity_check`.
Protects `decision_snapshots`/`shadow_predictions`/`alert_history` — the data every other item
reads. Zero product risk. *(Ranked #5 in the draft; both adversaries said this is insurance under
everything else — promoted.)*

### #2 — Honest measurement spine + recalibration (the real headline) — M
A read-only `consensus_engine/eval/` module + CLI that (a) **audits the outcome labels** first
(entry ts/price, horizon price, splits, market-hours, dupes), then (b) emits **simple** time-split
metrics: Brier + log-loss, decile calibration table, **precision@k / top-decile lift**,
false-positive rate per score band, per-horizon, and the **fired-alert precision + subgroup hunt**
(which catalyst types / source combos / top-decile slices actually beat the base rate). Then (c)
recalibrate the score→probability map (beta/isotonic, out-of-fold, time-split; promote only if
held-out Brier improves). Wire the CLI into the pre-push gate as a **non-blocking** report.
- **Free-data:** 100% offline on stored rows, zero live risk.
- **DoD (fixed):** not "beat Brier 0.256" (a base-rate constant already does) — instead: the report
  identifies the highest-precision subgroup and its precision@k, and the recalibrated map's decile
  calibration is honest (predicted ≈ realized per bucket).
- **The logistic-on-15-features is ONE measured challenger inside this harness, not a build** — the
  critic measured AUC 0.507, so expect it to tie the recalibrated univariate map. Ship it only if
  it beats the incumbent out-of-fold on precision@k.
- *Adversarial note:* keep metrics simple first pass (skip SmoothECE/Spiegelhalter until the basic
  decision metrics are actually used); use ticker/time-grouped splits with embargo, not random.

### #3 — Spot-price sanity gate (quarantine, don't blind-reject) — S
When `!all`/level rendering produces a spot >N× off the yfinance last close (the $1154-Micron
bug), **quarantine/degrade** — flag "price data suspect, levels withheld" rather than printing a
confident $1132-entry order — instead of blindly rejecting (premarket/news/splits are real).
Kills a live, verbatim-confirmed, trust-destroying bug. Highest value-per-hour in the report.

### #4 — Honest, decision-first output + abstention — M (live-risk: shadow check owed)
One embed per event (ping edits in place when cross-ref lands — kills the 25-vs-83 contradiction
and the 3-embeds-in-one-second fatigue); `ACT`/`WATCH` first token; score → Watch/Lean/Strong
**bucket defined by measured lift** (from #2), raw score to vault; a **price stop** on the card
face; **abstention** — downgrade the noisy middle band to WATCH / suppress below a measured
precision threshold; kill-list of ~8 noise fields to the vault. No "83%" or "Strong" language until
#2 says a bucket is earned.

### #5 — Loud-on-degraded `!all` + freshness watchdog — S–M
`FAILED` sentinel through the `_*_safe` wrappers so the classifier sees real failures + one footer
line naming unavailable sources; promote the ~10 user-facing `log.debug` swallows to `warning` +
tee core-source failures to `notifications.log`; a generic table-driven `freshness_watch.sh` +
timer (cloned from the proven Wolf dark-watch) covering the forward-loggers, FINRA, Schwab,
`market_daily`. Additive, low risk.

### #6 — Stop re-hammering dead LLM providers — XS–S
Call `circuit_breaker.load_persisted()` at engine startup (1 line + test) so the learned
OpenRouter-402 OPEN state survives restarts; classify 402≠429 and trim reserved `max_tokens` so
the 402 fires less. Improves thesis *quality* (the product's real currency) for near-zero effort.

### #7 — Fix duplicate/correlated "confidence manufacturing" — M
Two parts both adversaries flagged: (a) the one-embed-per-event merge (in #4) removes duplicate
alerts; (b) the "2 independent sources" rule counts correlated echoes (StockTwits≈Reddit; a news
item and the flow it caused) as two votes — **start with deterministic source-family rules** (same
family ≠ second confirmation), then measure with a nested-logistic LR test once more history
accrues. Do NOT cluster on ~1 month of data.

### #8 — Analyst-track-record scorer: fair retrial at the right horizon — S + accrual
Repoint outcome measurement to argmax-IC over {24h, 5d, 20d}; gate ON only with Wilson
lower-bound > 0.50 AND n ≥ ~90 AND BH-FDR q≈0.10. Either revives a real signal or retires it
honestly. Runs inside #2's harness.

### #9 — Reliability/correctness bundle (un-bundled by risk) — S each
- Fake-ticker residual holes: ASCII-only format check; loud "valid symbol but no data" reply.
- Market-hours: route the level price through the existing holiday-aware `nyse_open_now()`.
- **Idempotency (separate, LIVE path):** write-ahead the cooldown row / UNIQUE key on
  `alert_history` — needs a shadow check before it ships (kept out of the cheap housekeeping so its
  risk isn't hidden).

### #10 — Perceived-latency streaming (low priority) — S
Stream `!all` synthesis to Discord via throttled edits. Nice, but "faster-looking bad information
is still bad information" — do last, after honesty.

---

## Roadmap / later (NOT this session — measured green light required first)
- **Wolf extractor→verifier redesign** (full design in `lens3-wolf-nlp.md`): a first-class `phase`
  axis (pending/active/counter-trend-bounce/reversal/invalidated/neutral) + extract×3 → consistency
  vote → **discriminative verifier that can only veto** → confidence gate (emit/downgrade/abstain).
  Structurally trap-proof. Build later, with a **hosted different-family NLI judge** (not local
  torch — the box is RAM-tight), hard-gated on the eval set already snapshotted to
  `wolf-eval-corpus/` (IGV + the A/B emails): zero IGV false bulls, no net new invented theses, on
  BOTH recall and false-positive count.
- **Scorer registry** (strangler-fig decompose the 82KB `cross_reference.py`) — only after #2 shows
  a display-only signal actually earns held-out lift. Don't refactor, then find nothing qualifies.
- **Logistic / EV-ranking** — only if #2's subgroup hunt finds recoverable structure; EV ranking
  needs calibrated prob + expected-move distribution + liquidity filters first.

## Kill / defer list
- **Kill:** the "beat Brier 0.256" DoD (a base-rate constant beats it). The ~8 UX noise fields. The
  4 dead DB tables (`source_performance`, `form4_clusters`, `macro_legs_daily`, `youtube_options`).
  Hand-folding display signals with manual weights. The fancy-metric zoo in the first eval pass.
- **Do-not-use (not permanent kill):** ranking alerts by score at 5d/20d — the −0.172 mean-reversion
  holds but only over one Apr–Jun window (22 alert-days); don't use the score for multi-day holds
  until more 20d labels accrue, but don't declare it permanently dead.
- **Park (needs budget):** market top/bottom **predictor** — confirmed NO-GO on free data.
- **Backlog `!all` levers — mostly LOW value:** adding *more* fields (max-pain-into-levels,
  competitor block, chart-pattern-strength) works against the decision-first redesign. Prefer #4's
  cuts over these adds.

## Budget parking lot (excellent ideas that need money)
- Options-history backtest (~$29 massive.com) — free forward-log via `options_flow` is accruing.
- Market top/bottom predictor — needs richer-than-daily paid data.
- $5 OpenRouter credits would lift the free-tier throttling behind the 402 breaker (#6 mitigates
  for $0 first).

## Hidden opportunities (on no backlog)
- **The honest-measurement loop is the highest-value thing here** and was on no list — it converts
  the 93-flag "build → test → flip" ritual into measured decisions and continuously guards against
  false-positive regressions.
- **Abstention as a feature:** if only the top decile has lift, the right default is
  watch/abstain — fewer, truer alerts. This directly serves "minimize false positives."
- **The pending-vs-active problem is one disease in two places** — the Wolf `phase` axis and the
  ACT/WATCH UI. Solving it conceptually once improves both.

## 6–12 month roadmap (priority order)
1. DB safety net (#1) + stop re-hammering providers (#6) — *cheap reliability, now.*
2. Honest measurement spine + recalibration + the edge-pocket hunt (#2) — *the prerequisite.*
3. Spot-price sanity gate (#3) + honest decision-first output & abstention (#4) + loud-on-degraded
   (#5) — *high user value, gated by the measurement.*
4. Source de-dup (#7), analyst-scorer retrial (#8), reliability bundle (#9).
5. Fold display-only signals via scorer registry — *only if #2 earns it.*
6. Wolf extractor→verifier redesign — *the deep AI build, hard-gated, hosted-NLI.*

---

## What the adversarial pass changed (recorded)

Two independent reviewers (codex/GPT-5.5 fed the draft inline; a repo-aware critic that re-ran the
numbers against `consensus.db`). Both converged. Changes made to the draft:

1. **Verified the spine holds.** Brier 0.253/0.256 > base-rate 0.250 re-confirmed exactly; 20d
   sign-flip −0.172 re-confirmed (but flagged as one Apr–Jun window). `calibration.py` univariate,
   `retrain_enabled:false`, breaker `load_persisted` only-in-tests, and the $1154 render all
   independently re-verified.
2. **Demoted the logistic model (#1C):** critic measured AUC 0.507 at 24h — the features barely
   clear a coin flip. It is now a *measured challenger* inside the harness, not an L-effort build.
3. **Fixed #2's Definition of Done:** "beat Brier 0.256" is met by a trivial constant → replaced
   with precision@k / top-decile lift + honest decile calibration.
4. **Promoted the DB safety net** from #5 to #1 — it protects the data every other item depends on.
5. **Pulled the spot-price sanity gate out** into its own top-3 item, and changed it from
   blind-reject to **quarantine/degrade** (codex: premarket/news/splits are real).
6. **Demoted the Wolf redesign to roadmap** — both said not this session (big build, side pipeline,
   39 scored rows can't prove real-outcome gains, "free local NLI" needs a 2–3GB torch install on a
   RAM-tight box). Keep the research + eval corpus; build later with a hosted NLI judge.
7. **Added the missing headline:** fired-alert precision 0.438 at 24h, and **abstention** as a
   first-class idea — the biggest miss in the draft.
8. **Reframed the 20d/multi-day "kill"** as "not validated, don't use there yet."
9. **Simplified the eval first pass** (drop the metric zoo) and added ticker/time-grouped splits +
   label audit + baseline suite + false-positive taxonomy.
10. **Un-bundled #10:** separated the live-path idempotency fix from cheap housekeeping so its risk
    isn't hidden; deferred the scorer registry behind a measured green light.
