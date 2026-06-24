# Signal-features discover — Phase 2 (Waves 3-4) + activation

**Status:** OPEN
**Created:** 2026-06-09

Follow-on work from the `signal-features-2026-06-09` discover run. Phase 1 (9 fixes) is
built, tested, and committed flag-OFF (commit `cb2729b`). This tracks what's left.

**TOP user-requested goal (2026-06-09):** fix the conviction scoring so nuanced/tentative
analyst calls aren't penalized — see "User insight" below. Until then the alert-score dial
(`min_base_score_for_alert`) has been turned **OFF (set to 0, live)** so it can't delete real
calls; do not re-raise it before conviction scoring is fixed.

## What's done (Phase 1 — Waves 1-2, commit cb2729b, all flag-OFF)
I9 (alert-floor knob), I4-display-honesty, I14-display (regime line), I16 (Wolf benchmark),
I1 (sign the YouTube boost), I2 (analyst track-record weight), I5 (SEC graduated by role/$),
I6 (options same-direction-only), I12 (earnings magnitude). Full suite clean (1975 pass, only
the sanctioned baseline fails). 50+ dedicated tests. Nothing activated live.

## Next step A — activate Phase 1 (separate user sign-off, per house rule)
Each flag lands OFF + shadow-first. To go live: run a shadow window, read the shadow logs
(`[I1]`/`[I2]`/`[I4-display]`/`[I9]` lines), tune the shadow-derived placeholders
(`earnings_magnitude.min_abs_eps`, `sec_graduated_scoring.recency_days`,
`recency_window.max_age_min.*`), then flip flags in `config/consensus.yaml` one at a time and
`sudo systemctl restart consensus-engine.service` (chown openclaw:openclaw if edited as root).
Highest-ROI to flip first: **I1** (stops bearish YouTube raising a long score) and **I9**.

## Next step B — build Phase 2 (Waves 3-4), fully specified in the plan
Plan: `.claude/discover/signal-features-2026-06-09/final-plan.md` (§2/§5/§6/§8.B per item).
All flag-OFF + shadow-first + the same regression gate. Build in this order (dependencies):
- **Wave 3:** I3 (live contradiction_index PRODUCER — actor-identity counted, ≥2 distinct
  actors; consumer already live), I10 (STRONG needs a hard-evidence component), E6
  (manufactured-agreement / coordinated-burst gate — account-diversity, never suppress),
  I13 (ApeWisdom mention z-score, confirm-only + new DB series + backfill), I15 (Wolf
  confluence recency+size votes, actor-independence for the critical @-ping).
- **Wave 4:** I4-full (single-score reconciliation), I7 (consensus_boost via Bayesian
  log-odds), I14-widening (graduated panic cutoff in regime.py), E2 (cross-asset VIX-term +
  FRED/HY veto multiplier), E1 (FINRA free short-volume confluence term + new DB series).
- **Cross-cutting prerequisite:** the **common-recency-window synchronizer**
  (`analysis/recency_window.py`) that I3/I13/I15/E1/E2 all call — stops "phantom confluence"
  (a 12h-old short spike paired with a 1-min SEC buy). Build it before/with Wave 3.

## Deferred (documented, not in Phase 2 either)
- **I18** (reliability/freshness/verdict render block) — DEFER until I3 + I4 ship hardened AND
  pass an adversarial-input shadow window. A wrong authoritative verdict block is worse than a
  blank one.

## Dropped (do NOT rebuild without new evidence)
- **I8** (analyst-swarm herding) — Gemini + adversarial critic agreed: a fresh coordinated
  ring scores full weight (`co_post_rate=0` on no-history pairs), and herding rewards the
  crowded/late signal (against "before mainstream").
- **E3** (gamma-exposure / GEX) — incremental info collapses after controlling for VIX
  (its own re-verify: rho -0.36 -> -0.03); a wrong flip level is the NVDA-850 error class.
- **I11** (LLM-fallback catalyst) — DEFERRED: +8 not worth the prompt-injection surface (only
  HIGH security item); real catalysts already fire via I5/I12. If revived, the mandatory fix
  is delimiter-isolation + `<news_body>` untrusted-data instruction + +8 cap + verbatim-quote
  + second-source corroboration + defusedxml.

## Files / where to pick up cold
- Plan + all 5 passes: `.claude/discover/signal-features-2026-06-09/` (state.json, pass-0..3,
  final-plan.md, pass-5-execution-log.md).
- Phase-1 commit: `cb2729b`. Resume Pass 5 build with the `discover: resume
  signal-features-2026-06-09` trigger if desired, or just build from final-plan.md §8.B.

## User insight (2026-06-09) — conviction heuristic mis-reads nuance
~98% of the tracked analysts' real calls sound tentative ("watching... might add if it
reclaims 250") — that nuance is their normal register, NOT noise. Only ~2% are blunt
"all-in, strike/target/stop" calls. But `tweet_parser.py:_infer_conviction` scores
"watching/might/maybe" as LOW (base_score 20), so nearly all genuine calls sit at the floor.
Consequences / actions:
- **Do NOT use the I9 `min_base_score_for_alert` bar (or the conviction tier) as a noise
  filter** — raising it deletes the 98% real signal. Leave it at 20. (I9 still correctly
  connects the dial; just don't turn it up for these analysts.)
- **Candidate Phase-2 rework:** recalibrate conviction so tentative wording isn't penalized —
  derive it from the setup/structure or the LLM's read, not from "watching" vs "all in"
  keywords. Noise control stays downstream (cross-ref, precision engine, I2/I3/I10).
- See memory [[project_analyst_tweet_register]].

## Open questions
- E2's FRED leg: re-verify FRED API access before building that leg (kept behind its own flag).
- I13/E1 backfill: each needs a DB migration + 14-30 day baseline backfill before the flag is
  eligible for sign-off.

### Session notes — 2026-06-10
- **Worked on:** Phase 2 BUILT COMPLETE — all 10 features + the common-recency-window
  synchronizer committed flag-OFF: recency_window, I3+E6 (contradiction producer +
  manufactured-agreement gate), I10 (STRONG hard evidence, shadow line fires live via the
  I4-full main.py threading), I13 (ApeWisdom z-gate; apewisdom_mentions table schema v19;
  live scan persisted 200 rows; baseline accumulates forward ~14 days before flag-eligible),
  I15 (weighted Wolf confluence votes — live A/B on the real 22 theses found+fixed two
  producer/consumer mismatches), I4-full (single score), I7 (log-odds), I14-widening,
  E2 (VIX-term multiplier, live probe ratio 0.983; FRED leg NOT built — no key), E1 (FINRA
  short-volume: schema v20, 4,300 rows / 205 tickers / 21 trading days backfilled live after
  fixing 3 production-only bugs; daily systemd timer finra-short-volume.timer keeps it fresh).
  Also shipped the TOP goal: conviction scoring fixed (tentative register no longer floors
  real calls; LLM prompt got a setup-quality rubric) — live, no flag.
- **Decisions:** Phase-1 flags activated this session (see TODO #32 "Next step A" — done).
  Phase-2 flags stay OFF pending their shadow windows: [I3]/[I10] shadow lines accumulate in
  the journal now; E2 wants ~2 weeks of [E2 shadow]; I13 needs ~14 days of baseline; E1's
  gate can open once its z-surge + corroborator coincide (data is fresh daily via the timer).
- **Next:** after the shadow window, read the [I3]/[I10]/[E2 shadow] journal distributions,
  tune recency_window.max_age_min.* + the shadow-derived placeholders, then flip Phase-2
  flags one at a time. I18 stays deferred (needs I3+I4 hardened + adversarial-input window).

### Session notes — 2026-06-13 (discover run todo-sweep)
- **Backtested every Phase-2 feature against DB+journal instead of waiting for shadow windows.** Key finding: the shadow windows are **empty by design** ([I3]/[I10]/[E2]/[I7] only log when their flag is ON or on rare events) — "wait 14 days then flip" was never going to work. Backtest is the only gate.
- **Flip now (proven, touch live paths):** E1 (FINRA short-vol; ~3% fire rate on live code) + I15 (weighted Wolf votes; only demotes 2 over-ranked theses, 0 spurious @-pings).
- **Hold:** I3/I10/E2-VIX are bounded-safe but **inert** until the **dual-score divergence** is fixed (precision score caps ~56, never hits STRONG; alert uses a separate ≥75 path). Gemini review: do NOT flip them while inert (they'd all activate at once when I4-full lands → alert-storm). Order: E1+I15 → I4-full → then I3/I10/E2-VIX one-at-a-time.
- **Wait:** I13 (ApeWisdom) flip-eligible ~2026-06-24 (~11 more baseline days). **Unbuildable:** E2-FRED (no key). **Keep:** I9 floor at 0.
- 3 gaps block Phase-2 value: regime_daily empty, consolidation stuck shadow-only, dual-score divergence. Full plan: .claude/discover/todo-sweep-2026-06-13/research/signals-phase2.md + final-plan.md §3/§5.

### Session notes — 2026-06-16 (run todo-active-sweep-2026-06-16, Codex-reviewed)
- **Worked on:** flipped **I10** (`strong_requires_hard_evidence`) LIVE after a 0/56-demotion backtest + 14d shadow agreement (downgrade-only); seeded `regime_daily` (247 rows) so **I14-display** is live (`Regime: normal`, shift 0, no scoring change) + installed a self-healing daily timer.
- **Key correction (Codex + critics):** the "I4-full keystone / I3·I10·E2 inert until single_score" theory is FALSE — I4-full only rewrites a displayed number (0 tier moves) and the others gate on their own flags. So I10 was flippable on its own.
- **Decisions:** I4-full, I3, E2, I7, I14-widening, I13 all stay OFF with named exceptions (see `signal-flip-status-2026-06-15.md` "Activation log — 2026-06-16"). I3 needs the dead-`min_actors` wired before flip; I14-widening is a config no-op (graduated==static at ceiling 90); I7 needs code enablers; I13 reminder scheduled for ~2026-06-24.
- **Next:** (per one-at-a-time policy) I3 after a `min_actors` decision; I13 after June 24 baseline; E2 needs forward stressed data + a corrected harness + symmetric-config rethink.

### Update — 2026-06-21
- **I4-full (`single_score`) is now FLIPPED ON** (user "flip on the switch so we can monitor it", via #50). Supersedes the "stay OFF" notes above for I4-full only. Flipped during weekend pause; live soak starts Sun 11:00 PDT. Per the one-at-a-time order, the next switches (I3 already on; I10 already on; E2 last) are unaffected. Detail + evidence: `scan-marketview-score-coherence.md` and `.claude/go-live-evidence/features_single_score_enabled.md`.

### Session notes — 2026-06-24 (discover run todo-sweep-2026-06-24)
- **Worked on:** the three remaining OFF switches, verified against real code/DB (not the file). Net: **nothing flips safely today**, but built the E2 enabler that was the blocker.
- **I13 (apewisdom_zscore): NOT flip-ready — proved with gate math.** The gate is per-ticker ≥14 DISTINCT calendar days (cross_reference.py:121) AND non-zero variance of the daily-max series (:131). Live DB: apewisdom_mentions has only **13 distinct collection days** (2026-06-10..06-24, gaps 06-13/06-20), the best ticker has exactly 13, avg 5.43 days/ticker → **ZERO tickers qualify**. ApeWisdom has no historical API so the gap can't be backfilled. Premature flip would silently drop the presence-based +10 (cross_reference.py:209) = a real scoring regression for zero benefit. **Action:** built `/root/task_system/scripts/i13_apewisdom_recheck.sh` (uses the EXACT gate semantics) + scheduled it for **2026-06-27 09:00 PDT** (task 1782325891_d686e4) — it pings notifications.log with flip instructions the moment ≥1 ticker hits 14 days w/ variance. No auto-flip. Confirmed the daily ApeWisdom ingest is alive (data through 06-24 18:12).
- **E2 (cross_asset): built SHADOW mode + offline replay; shadow flipped ON, master stays OFF.** The soak the policy demanded was impossible because `[E2 shadow]` only logged when the master was already ON. Fix: added `features.cross_asset.shadow` (default true) — when master OFF + shadow ON, the engine computes VIX+FRED ratios (15-min TTL cache, executor, so no live-path latency) and logs `[E2 shadow-only] … would_apply=False`, returning 1.0 (live score untouched). Verified by direct invocation (real fetch VIX 0.929→1.071, credit 0.963→1.014, combined 1.043, **returned 1.0**) + engine restart healthy. Config: `shadow:true, enabled:false`. 42 cross_asset tests pass.
  - **Offline replay built** (`scripts/backtest_e2_cross_asset.py`) over 2894 stored alerts (result: `.claude/discover/todo-sweep-2026-06-24/e2-replay-result.md`). Verified faithful to `engine._classify` (`raw_high = base_high*mult + regime_shift`; regime_shift=0 across the whole 2026 window so the replay omitting it is exact). **KEY FINDING: combined E2 would change ~36% of STRONG classifications** (215 of 600 demoted on calm days because the calm "confirm" mult 1.15 raises the threshold to the 90 ceiling, demoting 80-89 scores). **Direction question for the human before the MASTER flip:** `_ratio_to_multiplier` makes stress (backwardation, ratio>1)→0.85→*lowers* the STRONG bar (more alerts) and calm (contango)→1.15→*raises* it (fewer alerts). Confirm this "stress lowers the bar / calm raises it" direction is intended (contrarian) and not inverted vs the "veto bullish in stress" framing — and review the 36% blast radius — before flipping `features.cross_asset.enabled`. Shadow soak now accrues the live distribution to support that decision.
- **I7 (consensus_logodds) + I14-widening: confirmed PROVEN NO-OPS — left OFF, no flip.** I7: source_performance table = 0 rows → consolidation always cold-start + all 2601 consolidated_events single-cluster → log-odds = 0 lift. Needs a code writer + multi-cluster conditions, not a flip. I14-widening: graduated shift clamps to cutoff_ceiling(90)−high(80)=10 == static panic shift 10 (regime.py:62), and regime_daily has zero panic days ever → config no-op. Flipping either would falsely record "enabled" while changing nothing.
- **Next:** I13 auto-reminder fires 06-27; E2 master flip awaits a human direction-review + shadow-soak read; I7/I14-widening need their named code/config enablers (own task).
