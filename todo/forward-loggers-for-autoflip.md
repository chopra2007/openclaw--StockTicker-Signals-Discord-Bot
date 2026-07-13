# Build the two forward-loggers that feed the autonomous auto-flip engine

**Status:** DONE 2026-07-09
**Created:** 2026-07-05

**CURRENT STATUS (2026-07-09) — DONE.** Both loggers are live, both auto-flip switches are unblocked, and **zero live alerts changed**.

**Logger 1 — the 5 display signals.** `consensus_engine/analysis/display_signals.py` computes max-pain, analyst momentum, EPS revisions, peer relative-strength and chart patterns, and merges them into `decision_snapshots.feature_vector_json`. It runs **off the alert path**: `main.py` writes the snapshot row, then schedules the collector, which merges into the already-written row (`db.merge_snapshot_feature_vector`). The alert path gains **zero** latency — better than the planned "measure it and hope", because there is nothing to measure. Collection takes 1–3s wall-clock, all five in parallel, each independently timed out and failure-safe.

Two integration traps found and fixed:
- The readiness check (`auto_flip_check.py::check_display_signals_lift`) reads **top-level numeric** keys named exactly `max_pain`, `analyst_momentum`, `eps_revision`, `peer_rs`, `chart_pattern`. Nested values, or the string pattern label, would have been silently skipped — the switch would have looked "logged" forever while `n` stayed 0. The logger now writes those five flat numbers (chart pattern encoded as a signed confidence) alongside the rich `display_signals` sub-dict.
- The subagent's report on `compute_max_pain`'s return shape was wrong (it returns `weekly`/`monthly` legs, not `weekly_exp`/`max_pain`). Verified against the live function before use.

**Logger 2 — per-analyst outcomes.** `compute_source_performance_live` grades analysts at **24h and 5d, never 1h** (an analyst call graded one hour later is measuring noise — that is the wrong horizon #55 benched at). Runs daily off the existing `source-performance-shadow-daily.timer`. Needed a new `alert_history.price_5d_later` column plus a fill in `price_outcome_loop`; `scripts/backfill_alert_5d_outcomes.py` filled the back-catalogue (2,909 rows; 422 of 550 analyst-bearing alerts now have a 5-day outcome, up from 73 — a per-row yfinance loop got rate-limited, so it batches bars per ticker like `grade_options_flow.py`).

**Why writing the LIVE table is safe.** Every live reader now resolves its horizon through `db.analyst_horizon()`, which returns `'1h'` until `scoring.analyst_accuracy_weight.enabled` flips it to `'24h'`. The producer never writes a 1h row, so all four readers keep missing and stay cold-start. **A latent hazard was found and fixed here:** the consolidation prior (`analysis/consolidation.py`) read `source_performance` with **no horizon filter at all** — the moment any row landed, at any horizon, it would have gone warm and started adding `consensus_boost` to live alerts. Proven in a live probe: filtered read returns `None` (cold), unfiltered returns `0.515` (warm). Also fixed: `get_analyst_precision_lb` had its default changed to `None` without resolving it, which would have made the analyst weighting silently dead *after* the flip.

**Live evidence (2026-07-09):** live table holds 28 analysts / 54 rows / 0 rows at 1h. With the flag OFF every reader returns `None`. With it simulated ON, `The_RockTrading` reads accuracy 0.515, Wilson-LB 0.418. `auto_flip_check.py` now sees the data and reports **`analyst_accuracy_promote: NOT ready — n=99/need 90, metric=0.418 (need >0.5)`** — over the sample bar, under the accuracy bar, correctly declining to promote. That is the engine working, not failing.

**Owed:** `fold_display_signals` needs ≥90 resolved 24h outcomes on snapshots written *after* this went live; it will report `not_ready` until then and re-test itself every 2 days. Nothing further for a human to do.

## What this is
The 2026-07-05 research run (#61) built an autonomous "test every 2 days, flip when
confident" engine (`/root/task_system/scripts/auto_flip_check.py` + `pending_switches.json` +
`auto-flip-check.timer`). It has two switches registered but BLOCKED because the data they need
was never logged. This task builds the two forward-loggers so the data accrues; once it does, the
auto-flip engine flips each switch on its own (no further human step).

## The two loggers (priority order)

### 1. Log the 5 display-only signals into decision_snapshots (feeds `fold_display_signals`)
- **Why:** the honesty eval (`consensus_engine/eval/`) proved the score has ~no edge partly because
  the rich signals aren't in the feature vector — only `final_score` has variance in 3,112/3,134
  rows. The 5 signals (max-pain, analyst momentum, EPS-revision, peer relative-strength, chart
  patterns) are computed only in the `!all` DISPLAY path, never on the alert/scoring path, so they
  are logged NOWHERE. Folding them into the score can't be validated until they're logged.
- **Where:** the decision-snapshot write is `consensus_engine/main.py:1618 record_decision_snapshot`;
  the `fv` dict is built at `main.py:1581-1617`. Add the 5 signals to `fv`.
- **The hard part:** these signals need their own fetches (yfinance/options), which are expensive on
  the hot alert path. Options: (a) compute them lazily with per-signal timeouts + failure-safe
  (mirror `scanners/snapshot.py`'s lazy pattern), gated behind a new `features.forward_log_display_signals`
  flag default-ON (logging only, no scoring change); or (b) a separate off-hot-path batch job that
  backfills the 5 signals for recent snapshot rows. Prefer (a) if latency impact is small — MEASURE
  the added `!all`/alert latency before/after.
- **DoD:** new snapshots carry all 5 signal values in `feature_vector_json`; ≥90 resolved 24h
  outcomes accrue; then the auto-flip engine's readiness check (each signal beats incumbent held-out
  Brier at 24h, n≥90, Wilson-LB>0.50) runs every 2 days. Also needs a scoring CONSUMER behind
  `scoring.fold_display_signals.enabled` (the flag the registry targets — doesn't exist yet) that
  actually folds a validated signal in.

### 2. Wire the per-analyst outcome producer to fill source_performance (feeds `analyst_accuracy_promote`)
- **Why:** `source_performance` is EMPTY (0 rows); only `source_performance_shadow` has a 54-row
  current snapshot (not a time series). The analyst-accuracy consuming flags are already
  `enabled:true` but no-op because the table is empty (per TODO #55). The scorer was benched at the
  WRONG horizon (1h, expected-null for a slow signal); the retest belongs at 24h/5d.
- **What:** build the production writer that records per-analyst resolved 24h/5d outcomes into
  `source_performance`. Repoint the horizon from 1h to argmax-IC over {24h,5d}.
- **DoD:** ≥1 analyst reaches n≥90 with Wilson-LB>0.50 at 24h or 5d surviving BH-FDR q≤0.10 → the
  auto-flip engine promotes it. Note: eval already found a marginal contrarian pocket —
  `catalyst=Analyst Downgrade` 24h hit 57.5%, n=174, Wilson-LB 0.500 (borderline) — worth a look.

## Files / infra involved
- `consensus_engine/main.py` (snapshot write), `consensus_engine/db.py` (record_decision_snapshot),
  the 5 producers (`scanners/snapshot.py`, `analysis/peer_comparison.py`, `scanners/options.py`,
  `analysis/patterns.py`), `consensus_engine/eval/` (readiness metrics).
- Registry: `/root/task_system/pending_switches.json`. Engine: `auto_flip_check.py`.

## Open questions
- Hot-path latency budget for (1a) vs building the batch backfill (1b)?
- Does `fold_display_signals` need the scoring consumer built at the same time, or log-first-then-consume?

### Session notes — 2026-07-09
- **Planned:** build order + design choices in `.omc/plans/active-items-completion-2026-07-09.md` Phase C (lazy per-signal timeouts, log-only flag ON, scoring consumer built but OFF, analyst outcomes at 24h/5d not 1h). Completing this item also closes #61.
