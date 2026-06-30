# Flip status — what's switched ON, what's still OFF, and how to turn the rest on

**Status:** DONE 2026-06-29
**Created:** 2026-06-15

Single source of truth for every switch touched or considered in the `todo-sweep-2026-06-13`
build (executed 2026-06-15). Plain-English first, exact config key in `code font`.

---

## ⚠️ CURRENT STATE 2026-06-27 (read this first — supersedes the "Still OFF" E2 rows below)

Verified against `config/consensus.yaml` + the running engine (PID restarted 2026-06-27 18:18 PDT) on 2026-06-27:
- **E2 master `cross_asset.enabled` → LIVE since 2026-06-26** (commit `d346521`; calm `confirm_ceiling 1.05` / stress `veto_floor 0.85`, `shadow:false`). The "Still OFF / awaiting decision" E2 rows further down are STALE — superseded by this flip.
- **ON + live:** I4-full, I3, I10, I13, I15, E1, FRED-leg, **E2 master**. So **nothing flippable remains** for #32/#42.
- **Still OFF, by design (proven no-ops — a flip does nothing without new code):** I7 `consensus_logodds` (needs a `source_performance` writer + multi-cluster events) and I14-widening `regime_widening_graduated` (clamp math `90−80=10` == static panic shift; zero panic days ever recorded). I9 alert floor stays `0` (analyst-tweet-register finding).
- **One live-check still OWED:** E2's math is affirmed (shadow soak + 3007-alert replay + 42 tests + the `135c7f5` inversion fix), but the weekend pause began right after the flip, so E2 has not yet applied to a real alert. Scheduled check `e2_first_session_check.sh` (task `1782629564_46f4e7`, Mon 2026-06-29 16:00 PDT) confirms live application via `notifications.log` — then #32/#42 can be marked fully DONE.

---

## ✅ Switched ON this session (LIVE)

| Switch (config key) | What it does | Proof it's safe |
|---|---|---|
| **Wolf direction guard** `wolf.direction_guard.enabled` (was already on; the RULE TEXT was rewritten) | Reads a "bounce up to a level from below + topping pattern" as a SHORT, not a buy; stops "200-day" becoming a fake $200 target | A/B 10×/email on 5 real emails: wrong IGV-buy 5/10 → 0/10; S&P/Nasdaq 9/9 buy → 8/7 sell; controls unchanged |
| **Wolf staleness sweep** `wolf.staleness.enabled` | Nightly: retires (hides, doesn't delete) calls Wolf has gone quiet on | First live run retired 8 genuinely-stale calls, left fresh ones |
| **EPS-revision field** `features.snapshot.eps_revisions` | `!all` shows "EPS rev 34↑ 3↓ (30d)" — analysts raising/cutting estimates | Live `!all NVDA`/`TSLA` rendered it; runs <34s |
| **Stocktwits field** `features.stocktwits_sentiment.enabled` | `!all` shows "💬 Retail 74% bullish · +1/5d · 650k watching" | Live `!all NVDA` rendered it (fetched via `requests` — Cloudflare blocks the bot's normal fetcher) |
| **Chat memory** `chat_memory.enabled` | Saves redacted summaries of past chats so the bot can recall month-old conversations after a restart | Live: bot correctly recalled a ~May-20 conversation; 0 secret leaks; hallucination-trap refused |
| **Weighted Wolf votes** `wolf.confluence.weighted_votes_enabled` (I15) | Down-weights stale/duplicate agreeing sources in the Wolf confluence score | Dry-run on the 17 live theses: 0 tier changes, 0 new @-ping alerts |
| **FINRA short-volume term** `features.finra_short_volume.enabled` (E1) | Adds up to +5 confluence when short-volume spikes on a bullish call | Replay over 1873 past alerts: ≤177 candidates, +5 cap, fails safe on stale data. **LIVE+firing 2026-06-15** — fresh daily data, 2 tickers (CRWV, SMH) qualify today |
| **FRED HY-credit leg** `features.cross_asset.fred_leg_enabled` (E2-FRED) | Second regime leg: down/up-weights bullish alerts when high-yield credit spreads widen (stress) / tighten (calm) | BUILT 2026-06-15 (key provided). 24 unit tests pass; live end-to-end proven (VIX 1.15 + credit 1.023 → 1.086). Leg flag ON but **stays dark** — its master `features.cross_asset.enabled` is still false (see E2 row below) |

**Also applied — NOW LIVE (gateway restarted 2026-06-15 18:58):** OpenClaw transcript
hygiene — `truncateAfterCompaction: true`, `maxActiveTranscriptBytes: "5mb"` (stop the live
chat file ballooning), and repointed `memorySearch.extraPaths` to the live memory folder
(was a stale May-5 copy). All under `agents.defaults` in `openclaw.json`. Gateway came back
healthy on a fresh boot; a live @-mention healthcheck got a reply, so the restart was clean.

### ✅ E1 (FINRA) caveat RESOLVED — now firing on fresh data
E1 was inert over the weekend (FINRA doesn't publish Sat/Sun, term ignores data >24h old).
As of **Mon 2026-06-15**: the daily fetch loop pulled today's file (5,558 rows, latest
published ~3h ago), and **2 tickers (CRWV, SMH) already qualify for the +5** short-squeeze
boost. The weekend caveat no longer applies — E1 is doing real work.

---

## ⛔ Still OFF — why, and what's needed to turn each on

All of these are #32 "Phase-2" signal-scoring switches. The plan AND the outside-model review
require them to go on **one at a time, after the first one (I4-full) has soaked** — never
bundled — because they change live alert behavior and a simultaneous flip would be an
un-debuggable alert storm.

| Switch (config key) | What it does | Why it's OFF | What's needed to flip it ON |
|---|---|---|---|
| **I4-full** `features.single_score.enabled` | Unifies the bot's two different score numbers into one | ✅ **FLIPPED ON 2026-06-21** (user "flip on the switch so we can monitor it", #50). Flipped during weekend pause; live signals resume Sun 11:00 PDT, so the soak window starts this afternoon | DONE — now soaking. Watch `grep 'I4-full shadow'` + `!market-view`. Evidence: `.claude/go-live-evidence/features_single_score_enabled.md`. The next three (I3/I10/E2) were the ones waiting on this soak |
| **I3 contradiction** `features.contradiction_index_live.enabled` | Down-grades a signal when sources flatly disagree | Must wait until AFTER I4-full (else it activates together with I10 + E2-VIX = alert storm) | After I4-full soaks: flip alone, watch |
| **I10 hard-evidence** `features.strong_requires_hard_evidence.enabled` | A "STRONG" alert must have a hard technical component | Only meaningful after I4-full unifies the scores; same one-at-a-time rule | After I4-full soaks: flip alone, watch |
| **E2 cross-asset master** `features.cross_asset.enabled` | The ±15% confirm/veto multiplier — now combines BOTH legs: VIX term-structure + FRED HY-credit (averaged, then clamped) | Turns on a LIVE multiplier + its log at once (no shadow-first), and ±15% can push a score across the alert line. Now activates two legs at once | Flip LAST, after I4-full + an offline replay across calm AND stressed regimes covering BOTH legs (better: add a true shadow-only mode first) |
| **E2 FRED leg** `features.cross_asset.fred_leg_enabled` | The credit-spread half of E2 — high-yield spreads widening = stress = veto; tightening = calm = confirm | **BUILT 2026-06-15** (key now in `.env.service`; was the only blocker). Leg flag is ON, but inert because the E2 master above is off | Nothing to build. It comes alive automatically when the E2 master is flipped — so include the credit leg in that one replay |
| **I7 consensus log-odds** `features.consensus_logodds.enabled` | Scales score by how many independent sources cluster | A pure no-op today — the consolidation engine runs in shadow-only mode and every event is single-cluster | Build the enabler: take consolidation out of shadow-only so multi-cluster events occur, then flip |
| **I14 regime widening** `features.regime_widening_graduated.enabled` | Widens alert thresholds during market panic | A pure no-op today — the `regime_daily` table is empty, so the classifier never reaches "panic" | Build the enabler: seed `regime_daily` with 252-day volatility history, then flip |
| **I13 ApeWisdom z-surge** `features.apewisdom_zscore.enabled` | Flags unusual Reddit/Stocktwits mention spikes | **Data-blocked** — needs a 14-day baseline per ticker; only ~5 days exist (started ~June 10), and there's no historical backfill | Wait until ~**2026-06-24** for enough days to accumulate, re-check the spike distribution, then flip |
| **Alert score floor** `alerts.min_base_score_for_alert` (I9) | A minimum score before any alert fires | Deliberately held at **0** — raising it deletes ~98% of real tentative analyst calls (that's signal, not noise) | Leave at 0 (per the analyst-tweet-register finding) |

---

## Cross-references
- Broader Phase-2 context: `signal-features-phase2.md` (#32).
- Wolf direction/staleness detail: `wolf-hedged-stance-and-stale-theses.md` (#26).
- `!all` levers: `all-command-quality.md` (#6).
- Chat memory: `bot_chat_memory_redesign.md` (#39).
- Full run record: `.claude/discover/todo-sweep-2026-06-13/`.

---

## Activation log — 2026-06-16 (run `todo-active-sweep-2026-06-16`, Codex-reviewed)

**FLIPPED LIVE this session (one scoring switch, per policy):**
- **I10 `strong_requires_hard_evidence` → ON** (`consensus.yaml:804`). Downgrade-only (STRONG→WATCHLIST only when a STRONG lacks ALL hard evidence; never creates an alert). Gate passed: backtest `scripts/backtest_i10_hard_evidence.py` = **0/56** historical STRONGs demote (all carry news/sec/options>0); 14-day `[I10 shadow]` = 8 evals, all `would_demote=False`. Regression gate clean (2243 pass, baseline-only failure). Live-verified: real `!all NVDA` renders clean, engine healthy with flag ON.

**ENABLED LIVE (pure-data, no scoring change):**
- **I14-display via `regime_daily` seed** — `scripts/backfill_regime_daily.py` seeded 247 rows (all `normal`), z-correctness gate 10/10 vs pandas. `lookup_regime()` → `normal, shift=0, cold_start=False`. Display now renders `Regime: normal (z=0.1)` (was "warming up"); **zero cutoff change** (shift 0 verified pre-seed). DB backup `consensus.db.pre-regime-bak`. Daily self-healing timer `regime-daily.timer` installed (22:30 UTC).

**STILL OFF — named exceptions (build→test→flip rule):**
- **I4-full `single_score`** — display-cosmetic, 0 tier moves, un-backtestable on stored data (precision total unstored), NOT a keystone (verified: I3/I10/E2 don't depend on it). Low value; leave OFF.
- **I3 `contradiction_index_live`** — inert now (30d `[I3 shadow]` = 0). Flipping arms a **dead-`min_actors` trap** (a single opposing leg ≥0.5 solo-downgrades a STRONG). EXCEPTION: needs a code decision (wire `min_actors` into `evaluate_contradiction`, or sign-off) before flipping.
- **E2 `cross_asset`** — confirm side not backtestable (gating field unstored), veto side needs forward stressed data (legit wait), FRED dilutes VIX, `regime_widening` is a config no-op. OFF.
- **I7 `consensus_logodds`** — needs CODE enablers (no `source_performance` writer; `signal_events` never forms a 2nd cluster), ~0 lift. OFF (defer comment added at `:808`).
- **I13 `apewisdom_zscore`** — data-blocked until ~2026-06-24 (14-day baseline). Reminder scheduled (task `1781606545_cbbbb2`, no auto-flip).
- **I14-widening `regime_widening_graduated`** — **config no-op**: graduated shift clamps to `cutoff_ceiling-base_high = 90-80 = 10` = static panic shift. Inert by config math, not data. OFF.

**Also this session:** #45 agent tool-loop fixed (`main.py` abort-guard on `meta.aborted` + kill orphaned subprocess + `--timeout` 240→120 / outer wait 270→150 + softened steering; live-verified 26s convergence, no stub); `scripts/backtest.py` ALERT-filter fixed (total_alerts 0→1856); #38 orphan transcripts cleared 143→11 (rest = #39); #20 confluence header marked DONE+LIVE; #41 "Built switches default to ON" rule added to CLAUDE.md.

---

## Activation log — 2026-06-24 (run `todo-sweep-2026-06-24`)

**Verified live (not trusted from this file). Net: nothing flipped to live-applied; built the E2 soak enabler + the I13 auto-reminder.**

- **E2 `cross_asset` — SHADOW mode now ON; master still OFF.** New `features.cross_asset.shadow:true` (config:816). When master OFF + shadow ON, the engine computes the VIX-term + FRED ratio (15-min TTL cache → no live-path latency) and logs `[E2 shadow-only] … would_apply=False`, returning 1.0 (live score untouched). This finally makes the soak accrue — previously `[E2 shadow]` only logged when the master was ON, so the "wait then flip" plan could never gather data. Verified: direct invocation returned 1.0 + logged; engine restarted healthy. **Offline replay built+run** (`scripts/backtest_e2_cross_asset.py`, 2894 alerts; result `.claude/discover/todo-sweep-2026-06-24/e2-replay-result.md`), faithful to `engine._classify` (regime_shift=0 all window). **Blast radius: combined E2 changes ~36% of STRONG classifications** (215/600 demoted on calm days — the 1.15 confirm raises the threshold to the 90 ceiling). **BEFORE the master flip a human must confirm the veto/confirm DIRECTION** (`_ratio_to_multiplier`: stress→0.85→*lower* STRONG bar→more alerts; calm→1.15→*higher* bar→fewer alerts — is this intended contrarian behavior or inverted vs "veto in stress"?) and review the 36% impact. The shadow soak now supplies the live distribution for that decision.
- **I13 `apewisdom_zscore` — still OFF, NOT eligible (gate math).** Only 13 distinct ApeWisdom days exist (06-10..06-24, gaps 06-13/06-20); the gate needs ≥14 distinct days PER TICKER with non-zero variance; ZERO tickers qualify (best=13). No historical backfill possible. **Auto re-check scheduled 2026-06-27 09:00 PDT** (`/root/task_system/scripts/i13_apewisdom_recheck.sh`, task 1782325891_d686e4) — uses the exact gate semantics, pings notifications.log with flip instructions when ≥1 ticker qualifies. No auto-flip.
- **I7 `consensus_logodds` + I14-widening `regime_widening_graduated` — confirmed PROVEN NO-OPS, left OFF.** I7: source_performance empty + all 2601 consolidated_events single-cluster → 0 lift (needs a code writer + multi-cluster, not a flip). I14-widening: graduated clamp 90−80=10 == static panic shift 10, and zero panic days ever recorded → config no-op.
- **I4-full / I3 / I10 / E1 / FRED-leg** — unchanged (already ON). Master E2 is the last one-at-a-time scoring flip pending; I13 is the data-blocked one (auto-reminder live).

### ⏳ AWAITING USER DECISION — E2 master flip (2026-06-24, updated 2026-06-25)

> **✅ CURRENT STATE (read THIS first — do not re-derive direction from the history below):**
> - **The inversion bug is FIXED** (commit 135c7f5, 2026-06-25). `engine.py:325` now DIVIDES: `raw_high = base_high / e2_multiplier`.
> - **CORRECT direction (now in code; E2 still OFF/shadow, so dormant):** market **STRESS → RAISE the STRONG bar (toward 90) → FEWER, more-cautious alerts**; market **CALM → LOWER the bar (toward 70) → MORE, more-willing alerts**. Mnemonic: veto = stress = harder; confirm = calm = easier. Matches the code's documented intent and the user's reasoning.
> - **⚠️ DO NOT change the `/` back to `*`** — multiplying the threshold is the original bug. If a test or replay seems to say stress makes alerts *easier*, that is the OLD direction; the fixed code is the opposite.
> - **What's LEFT before the master flip = a TUNING call only** (the calm-side boost is aggressive — see the magnitude finding below) + reading the shadow soak. The direction itself is settled.

#### History (RESOLVED — context only, describes the OLD buggy behavior)
1. **The inversion bug that WAS fixed (do not reintroduce).** The code's documented intent and its (former, now-corrected) math disagreed:
   - INTENT (cross_asset.py:8-13 + engine.py:289-290): backwardation/stress → "raise the bar (veto direction)" = be MORE cautious; contango/calm → confirm. The variable names agree (`veto_floor` on the stress side, `confirm_ceiling` on the calm side).
   - IMPLEMENTATION (engine.py:325 `raw_high = base_high * e2_multiplier`): stress mult 0.85 → 80×0.85=68→clamp 70 = LOWERS the bar (EASIER, more alerts in stress); calm mult 1.15 → 92→clamp 90 = RAISES the bar (fewer alerts in calm). **Exact opposite of the documented intent.**
   - The user's reasoning (2026-06-25) is correct: a positive catalyst in a crashing market is more likely to fail, so the bot should be MORE selective in stress — which is what the code INTENDED but does backwards. **Fix:** make stress raise the cutoff / calm lower it — minimal change is `base_high / e2_multiplier` (stress 80/0.85=94→90 harder ✓; calm 80/1.15=70 easier ✓), which also matches the engine.py:289 "veto raises the cutoff (clamped 90)" guarantee. Must also update the shadow "would_cross" calc, scripts/backtest_e2_cross_asset.py, and the E2 unit tests, then re-run the replay.
2. **Blast radius (will FLIP direction once the bug is fixed):** the replay over 2,894 alerts showed ~36% of STRONG classifications change. With the current (buggy) math that's demote-on-calm; after the fix it becomes demote-on-stress (the intended behavior). Re-run the replay post-fix to get the corrected impact.
**Status:** E2 shadow mode is ON (logs only, no live effect). Master stays OFF.

**UPDATE 2026-06-25 — inversion bug FIXED (user "fix the inversion now").** `engine.py:325` now uses `base_high / e2_multiplier` (the algebraic inverse — requiring `score*mult >= base_high` is identical to `score >= base_high/mult`), so a veto (stress, mult<1) RAISES the bar and a confirm (calm, mult>1) LOWERS it — matching the documented intent and the user's reasoning. Updated the 2 clamp tests (ceiling now hit by veto/stress, floor by confirm/calm — names now accurate), the replay harness (`base_high / mult` + flipped cross-up/uncross guards + interpretation text). 42 E2 tests pass; no other test encodes the direction. No engine restart needed — the formula is dormant while `cross_asset.enabled=false`.
**NEW magnitude finding from the corrected replay (3007 alerts):** the FIXED direction's dominant real-world effect is the OPPOSITE concern from before — it would **PROMOTE ~261 alerts to STRONG in calm markets** (combined leg: 625→886 baseline→E2, **+42%**), by lowering the bar toward 70 for 76-79 scorers. The "cautious in stress" half barely triggered (only 34 stressed-day alerts in the window, 0 of them STRONG-candidates to demote). **So the remaining decision is now a TUNING one:** the calm-side `confirm_ceiling` (1.15 → bar drops to ~70) is aggressive; consider a gentler confirm_ceiling and/or asymmetric bounds (suppress more in stress than you promote in calm) before flipping the master. Shadow soak continues. Evidence: `.claude/discover/todo-sweep-2026-06-24/e2-replay-result.md`.

---

## UPDATE 2026-06-26 — Active-TODO sweep (`todo-active-sweep-2026-06-26`): I13 LIVE, E6 SHADOW, C2 LIVE

Codex-reviewed plan (GO-WITH-CHANGES). Three flips this sweep; one scoring flip per restart (attribution).

- **I13 `apewisdom_zscore` → ON (LIVE).** The 14-day-per-ticker data gate, blocked on 06-24 (best=13d), is now **satisfied: 112 tickers have ≥14 distinct days** (15 days 06-10..06-26), verified first-hand. Key structural fact (`cross_reference.py:213-223`): flag OFF = flat presence **+10 on EVERY ApeWisdom-listed ticker**; flag ON = z-surge+corroborator gate. So flipping ON can **only lower or keep** the term vs today — **I13 can never create or promote an alert**, only remove meme-presence noise. Backtest (`scripts/backtest_i13_apewisdom_zscore.py`, result in run dir): of 58 STRONG_ALERTs carrying the flat +10, 34 fired below the 80 cutoff (instant-trigger — +10 can't un-fire), 13 in the [80,89] band, **all 13 had a hard corroborator → 0 uncorroborated STRONG demotions**. Going forward, I13 fires +10 for at most **6 of 112** baseline-ready tickers today (vs flat +10 on 298). Flipped `consensus.yaml:814`, engine restarted 03:11, healthy. **Live check owed:** watch ~1 trading day of `[I13]` logs (raw counts already in `cross_reference.py:165`) to confirm rare, corroborated +10s.
- **E6 `manufactured_agreement_gate` → REMOVED / OFF (user declined 2026-06-26, commit 42a3fc1).** Initially built a shadow mode this sweep, but the user rejected the feature outright ("analysts are trustworthy, no coordinated hype"). Reverted the shadow code (`cross_reference.py` back to its prior flag-gated form), removed the shadow config key + conftest entry + shadow test + the E6-only backtest script. Flag fully OFF; the pre-existing E6 core stays dormant (byte-identical no-op). Do NOT re-enable without an explicit user request. (Context for the record: backtest had found it rare — 11 bursts/4613 signals — and the 3 it would have touched were all mega-cap legit-consensus, consistent with the user's point.)
- **C2 fundamentals one-liner (`features.fundamentals_oneliner`) → ON (LIVE, #6).** Adds `PEG · Growth% · Margin% · Beta · Inst%` to the `!all` Snapshot field from the **already-fetched** `.info` dict (zero new network call). Field audit across NVDA/AAPL/SOFI/CRWD/HIMS (6/6) + GEVO microcap (5/6, PEG omits) → ships by graceful-degradation. Live-verified on real data (NVDA/AAPL/GEVO). PEG guarded >0; negative margins render honestly.
- **E2 cross_asset dial set (2026-06-26, user pref): `confirm_ceiling` 1.15 → 1.00; master still OFF.** Verified mechanism (`engine.py:331-336`, `cross_asset.py`): effective STRONG cutoff = clamp(80 / multiplier, 70, 90); multiplier clamps to [veto_floor 0.85, confirm_ceiling]. At 1.15 a calm market lowered the bar 80→70 (more alerts); at **1.00** the calm side is a NO-OP (bar stays 80, no extra alerts) while the stress side (veto_floor 0.85) still raises it 80→90 (fewer alerts in a falling market). Master remains OFF → no live change; this just pre-sets the safe dial for whenever the user turns E2 on.
- **Unchanged:** I7/I14-widening still OFF (proven no-ops). I4-full/I3/I10/I15/E1/FRED-leg still ON. I13 + C2 fundamentals one-liner LIVE.
