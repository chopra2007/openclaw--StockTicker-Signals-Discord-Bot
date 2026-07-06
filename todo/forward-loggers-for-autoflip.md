# Build the two forward-loggers that feed the autonomous auto-flip engine

**Status:** OPEN
**Created:** 2026-07-05

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
