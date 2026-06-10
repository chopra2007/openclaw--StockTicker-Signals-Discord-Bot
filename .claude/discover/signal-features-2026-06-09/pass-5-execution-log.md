# Pass 5 — Execution Log (signal-features-2026-06-09)

**Mode:** build-now / autonomous. **Outcome:** Phase 1 (9 features) built, tested, verified
end-to-end, committed locally `cb2729b`. Push deferred to session close per CLAUDE.md (gate runs
there). Phase 2 (Waves 3-4) + deferred I18 fully specified in `final-plan.md` and tracked as
TODO #32. **Nothing activated live** (house rule: flag-OFF; live activation = separate sign-off).

## What was implemented (Phase 1 — Waves 1-2, all flag-OFF)

| ID | Feature | Files | Flag |
|---|---|---|---|
| I9 | Reconnect inert `min_base_score_for_alert` knob + would-suppress shadow log | main.py | (value-neutral at 20; no flag) |
| I4-display | Show the precision-gated number, not the inflated additive sum; "confidence degraded: budget" state | main.py, discord.py, engine.py (budget-skip set) | `features.score_display_honesty.enabled` |
| I14-display | Regime risk-context line ("warming up" on cold-start) | discord.py | `features.regime_context_line.enabled` |
| I16 | Benchmark-adjust Wolf outcomes vs SPY (sign-aware for inverse; raw+adjusted; recap-only) | analysis/wolf_outcomes.py | `wolf.outcomes.benchmark_adjusted` |
| I1 | Sign the YouTube boost (bearish now subtracts; min-2-channel floor, age/N≥10 trust, bearish cap -8, null-ts=stale) | cross_reference.py + config | `features.youtube_score.{direction_aware,recency_decay,channel_reliability}` |
| I2 | Weight analysts by Wilson-LB track record (new `get_analyst_precision_lb`, min_n=10, floor 0.5, uplift cap) | db.py, cross_reference.py, config | `features.analyst_accuracy_weight.enabled` |
| I5 | Graduate SEC by role + open-market $ (+8/+15/+20; 10b5-1→cap +8; net-sell withholds; recency-gated) | cross_reference.py | `features.sec_graduated_scoring.enabled` |
| I6 | Scale options by premium, SAME-DIRECTION only (drop opposing branch; staleness gate; no "smart money" narration) | models.py, options.py, cross_reference.py, narrator.py | `features.options_graduated_scoring.enabled` |
| I12 | Magnitude-scaled earnings beat/miss (+5/10%, cap +15; abs-$ floor; freshness gate; threads numeric eps) | models.py, news.py, cross_reference.py, config | `features.earnings_magnitude.enabled` |

Scaffolding: per-source budget-skip tracking (engine.py), `CatalystResult`/`OptionsResult`
fields (models.py), all new flags added to the conftest force-off fixture (the documented
flag-default-off pattern).

## Tests
50+ new dedicated tests across 7 files (test_phase1_display, test_wolf_outcomes_benchmark,
test_i1/i2/i5/i6/i12). Each proves flag-ON behavior AND flag-OFF byte-identical legacy behavior.

## Verification (Definition of Done)
- **Full suite (separate verifier, not the author):** `1975 passed, 1 failed, 1 skipped` (368s).
  The sole failure is the sanctioned pre-existing baseline `test_sunday_recap_and_addon_restart_safe`
  (the only entry in `.test-baseline`). **Zero regressions.**
- **No accidental activation:** all 10 new flags confirmed OFF; `min_base_score_for_alert=20`.
- **End-to-end:** `python3 -m consensus_engine --dry-run --once` ran a real poll cycle (EXIT=0,
  fetched 200 signals, DB init). Pytrends-429/Exa-backoff are pre-existing known states.
- **Always-on:** `consensus-engine.service` + `openclaw-gateway.service` both active;
  `/root/.openclaw` → `/home/openclaw/.openclaw` intact.

## Notable in-flight corrections (honest deviations from the plan)
- **I5 anchor error:** the plan cited `sec_edgar.py:253-332` for role/$/10b5-1 parsing; that code
  actually lives in `sec_form4_cluster.py`. Resolved by reusing those primitives and adding a
  separate `_run_sec_graduation` helper, keeping `_run_sec_check`'s 2-tuple contract intact (so
  no caller/mock broke).
- **I9 test example:** the plan's "base-22 tweet" isn't constructible (conviction scores are only
  20/25/30); proved the knob mechanism with a base-25 tweet suppressed at knob 26 instead.

## Cross-model (ccg) note
Gemini gave the second opinion; **Codex was unavailable** (auth token revoked —
`refresh_token_invalidated`; needs an interactive `codex login`). The cross-model pass still
drove the build-tightening (drop I8, drop E3, defer I11). To restore the Codex lens for Phase 2,
re-auth Codex.

## Follow-on (tracked)
- **TODO #32** (`todo/signal-features-phase2.md`): build Phase 2 (Waves 3-4) + the common-recency-window
  synchronizer; then activate Phase 1 after a shadow window. Deferred: I18. Dropped: I8, E3, I11.
- **Push:** happens at session close ("bye") through the regression gate.

---

# Phase 2 — Execution Log addendum (2026-06-10)

**Outcome:** Phase 2 BUILT COMPLETE (all 10 features + the recency synchronizer, flag-OFF) and
**Phase 1 ACTIVATED live** (8 flags ON, commit 451bfee) in the same session, with the conviction
rework (the user's top goal) shipped live un-flagged. Full suite: **2,178 pass / 1 sanctioned
baseline / 0 regressions** (serial, separate verifier + confirming rerun).

## Built (commits 26df885..752f6fc)
recency_window helper · I3+E6 (contradiction producer + manufactured-agreement, one pass) ·
I10 (STRONG hard evidence; shadow fires even flag-off) · I13 (apewisdom_mentions v19; live scan
persisted 200 rows; forward-accumulating baseline, no API history) · I15 (weighted Wolf votes) ·
I4-full (single score + threads breakdown/analyst/tech-count into analyze_signal so I10 sees
live data) · I7 (sigmoid log-odds) · I14-widening (z-scaled panic shift) · E2 (VIX-term
multiplier; FRED leg not built — no key) · E1 (FINRA short-volume v20 + daily systemd timer).

## What live testing caught that unit tests did not (5 production-only defects)
1. **E1:** live CNMS files carry fractional share volumes — strict int() parse dropped every row.
2. **E1:** stream `.read(n)` returns the first network chunk only — files truncated to A-tickers.
3. **E1:** 30-sample-day gate over a 30-calendar-day baseline window could never open (→ 45d/20d).
4. **I15:** `get_confluence_stances` carried no as_of/size/actor — every weighted leg dropped as
   null-timestamp-stale; AND the global minutes-scale recency caps deleted Wolf's deliberately
   21-day rows (→ producer now supplies fields; freshness cap = the confluence window itself).
5. **#17 chunking:** Gemini returns CLIP-relative timestamps — without adding win_start, all
   window-2 spans landed on window-1 times.

## Verifier value
The separate verifier caught 3 I15 + 4 E2 test failures my targeted slices missed
(`-k confluence` does not match test_i15_weighted_votes.py; E2's tests used
run_until_complete on the stale global loop — order-dependent). Both fixed, suite green.

## Activation + live verification (engine restarted 03:11 PT, gateway READY 03:12)
- Real `!all NVDA` via webhook (13:22 PT): clean embed — TP $253.59 / SL $175.8 on a $200.42
  stock (sane, #31 gate active), confluence field surfaces "Wolf BEAR vs Twitter/YouTube"
  divided view, Confidence LOW displayed honestly, no smart-money framing.
- Shadow lines on real traffic: [I1] signed=15 unsigned=15 (dir=neutral — correct), [I5] $MSFT
  graduated=8 (unknown role → conservative tier), [I9] ×8 with would-suppress previews.
- I16 live A/B on the real 13 theses: raw never replaced; SMH bear correctly re-read as
  flat-vs-benchmark. I15 live A/B on the real 22 theses: flag-on == legacy tiers on fresh data.
- Services active, symlink intact, no drift/LLM-health alert, migrations v19+v20 applied.

## Still pending (tracked in TODO #32 / #17)
Phase-2 flags stay OFF for their shadow windows (I3/I10 lines accumulate now; E2 wants ~2
weeks; I13 needs ~14 days of baseline; E1 data refreshes daily via timer). I18 deferred.
#17: >90-min videos still cap at 6 windows (decision: more quota vs Supadata credits vs accept).
