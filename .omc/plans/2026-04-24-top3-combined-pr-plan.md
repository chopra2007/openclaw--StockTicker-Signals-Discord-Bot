# Top-3 Combined PR + KILL List — Deliberate Consensus Plan (v2, post-consensus)

**Date:** 2026-04-24
**Invocation:** `/oh-my-claudecode:ralplan --deliberate on the top-3 combined PR (Q1 + M3 + Q2 + KILL list from Part 4.4)`
**Inputs:** `plans/AUDIT_RESEARCH_2026-04-24.md` (audit + research + proposals + Part 5 ranking)
**Mode:** Non-interactive, deliberate (pre-mortem + expanded test planning required)
**Revision:** v2 — incorporates Architect amendments + Critic punch-list (iteration 1 of 5)

---

## 0. Scope — what this plan ships in one PR

Six changes bundled into a single branch because their kill-switches, rollback paths, and risk dependencies are entangled:

1. **Q1 — Calibration ON (shadow mode) + honesty fix.** Untrained `calibrate()` is live at `alerts/discord.py:101` and `alerts/commands.py:876`; start logging shadow predictions into the existing `decision_snapshots.feature_vector_json` column (no new table); relabel the user-visible Discord field from "Calibrated conf" / "P(up 1h)" to `"score/100 (uncalibrated)"` while `calibration.shadow_mode.enabled` is true, so Principle 1 ("Truth over visible output") is *actioned*, not just stated.
2. **M3 — Per-analyst cooldown.** Rewrite `db.py:672–682` `check_alert_cooldown(ticker)` into `check_alert_cooldown(ticker, analyst, base_score)` using `source_performance` precision weighting; update the single call site at `main.py:608` in the *same commit* to pass `tweet.analyst` + `tweet.base_score`.
3. **Q2a — Phase-2 timeout + explicit skip message.** In `main.py:664–668`, wrap *only* the `xref_task` with `asyncio.wait_for(xref_task, timeout=cfg.get("intervals.cross_reference_timeout", 120))`; leave the precision task unaffected so a slow xref does not cancel the fast precision engine. Add explicit Discord edit `"Phase 2 skipped — timeout"` / `"Phase 2 skipped — low precision"` so silence never equals failure.
4. **Q2b — signal_events tweet routing.** `insert_signal()` at `db.py:1710` also writes a `signal_events` row for `SourceType.TWITTER` so `get_signal_events_for_ticker()` at `db.py:1736` stops returning empty for tweets. (Consumer note: `cross_reference.py:333` currently reads `signal_events` only inside the `reliability_engine_enabled` guard, which is deleted in KILL 3 — so we also add a read site in the always-on xref path to actually use the new rows.)
5. **KILL 1 (`max_alerts_per_hour`).** Delete the config stanza at `config/consensus.yaml:188`; no enforcement code exists.
6. **KILL 2 (dead `regime_detector` CONFIG only, keep the module).** Delete the `regime_detector:` stanza at `config/consensus.yaml:197–202`. **Do NOT delete `consensus_engine/analysis/regime_detector.py`** — three live tests at `tests/test_degraded_mode.py:286, 320, 353` import `detect_regime` and `pytest tests/ -v` would fail AC-1. The module is orphan-of-production but test-supported; deleting it requires deleting the tests too (out of scope — put in the Q9 PR or a follow-up cleanup PR).
7. **KILL 3 (`reliability_engine_enabled`).** Delete the flag at `config/consensus.yaml:194` AND the guarded import block at `cross_reference.py:326–376`; delete stale `.pyc` files at `consensus_engine/analysis/__pycache__/reliability_engine.cpython-310.pyc` AND `consensus_engine/analysis/__pycache__/snapshot_builder.cpython-310.pyc` (both orphan — `.py` source gone, `.pyc` remaining is a footgun).
8. **KILL 4 (narrow `require_market_confirmation` — atomic rename, no shim).** Rename the config key in all 4 call sites in one commit: `config/consensus.yaml:297`, `engine.py:234`, `engine.py:294`, `tests/test_engine.py:246` — from `require_market_confirmation` to `require_market_confirmation_for_low_conviction`. Skip the gate at `engine.py:294–308` when `base_score >= high_conviction_threshold (default 30)` OR when `catalyst_type LIKE 'sec_%'`. **No deprecation shim** — all 4 sites are under our control; a shim decorates instead of deletes, violating Principle 2.

Excluded (deliberate deferrals, justified below):
- **Q9 conviction parser fix** — unknown-effort, separate PR. M6 (require_market_confirmation exemption) bites on 0.5% of traffic until Q9 lands; we ship the exemption anyway because the code path is simple and the parser fix is unblocked the day it merges.
- **M6 as a standalone item** — subsumed into KILL 4 above (same diff, different framing).
- Everything else in Part 4.1–4.3 (Q3..Q8, Q4..Q7, M1, M2, M4, M5, X1–X4).

---

## 1. RALPLAN-DR Summary

### 1.1 Principles (5) — each paired with the concrete action that enforces it

1. **Truth over visible output.** The `P(up 1h)` field at `alerts/discord.py:101` + `alerts/commands.py:876` is currently `score/100` labelled as a probability. *Action:* Commit F relabels the field to `"score/100 (uncalibrated)"` while `calibration.shadow_mode.enabled=true` and the model is untrained; swaps back to calibrated probability display only when `retrain_enabled=true` AND a model has been persisted. The lie stops at merge time, not weeks later.
2. **Delete, don't decorate.** *Action:* three config stanzas (`max_alerts_per_hour`, `regime_detector:`, `reliability_engine_enabled`) are deleted outright — no deprecation shims. The rename of `require_market_confirmation` in KILL 4 is atomic across all 4 call sites in one commit (no shim); if we cannot coordinate an atomic rename, we keep the old name. No 1-release compatibility wrappers allowed in this PR.
3. **Empirical over declarative.** *Action:* M3 reads `source_performance.rolling_accuracy WHERE horizon='1h'` (schema confirmed at `db.py:293–300`: columns `entity_id, horizon, rolling_accuracy, sample_count`) at cooldown-check time via a new `get_analyst_precision(analyst, horizon='1h')` helper in `db.py`; blanket 6h is replaced with a precision-weighted lookup. Falls back to the blanket when analyst has `sample_count < 5` in `source_performance` for the requested horizon.
4. **Silent failure is the worst failure.** *Action:* Q2a adds explicit `"Phase 2 skipped — <reason>"` Discord edit on every timeout / low-precision path; M3 increments a `cooldown_dropped_reason` metric so suppression is observable in the daily ops summary.
5. **Additive forward-only migrations only.** *Action:* Q1 reuses the existing `decision_snapshots.feature_vector_json` column (confirmed at `db.py:244–251`) to store shadow predictions as JSON. No `CREATE TABLE` in this PR. If the PR is reverted, no orphan table remains — only the column is ever written to, and revert leaves it untouched for anything else that uses it. (The previous v1 draft claimed "no schema migrations" while adding a new table; that was self-contradictory — this revision removes the contradiction by removing the new table.)

### 1.2 Decision drivers (top 3)

1. **Inverted monotonicity at 30/60 band (94.1% vs 20.6% 1h hit).** This is the single most damning data point in the DB. Until calibration is on (even shadow), every threshold and boost is decorative.
2. **78.4% Phase-2 drop rate, currently 75–89% on 2026-04-20/23.** Production regression *right now*. Ships the credibility floor for everything else.
3. **Zero new dependencies, zero schema changes, ~170 LOC.** Reversion for any single component = toggle one flag or revert ≤2 files. Keeps blast radius small.

### 1.3 Viable options (≥2)

**Option A — Single combined PR (this plan).** Q1 + M3 + Q2 + KILL 1–4 in one branch, five independent feature flags, merge as one.
- Pros: shared kill-switch machinery; Q2 data-path fix makes Q1 calibration feature vectors non-empty (`decision_snapshots.signal_event_count` currently 0 for every row); tests and regression metrics run once; one review pass.
- Cons: larger diff (~170 LOC); one failing component blocks the merge; riskier rollback if something regresses mid-deploy.

**Option B — Three-PR sequenced rollout.** PR-1: KILL list + Q2 (cleanup + data-path). PR-2: Q1 (calibration shadow). PR-3: M3 (per-analyst cooldown).
- Pros: smallest unit of rollback per PR; easier to isolate which change caused any precision delta.
- Cons: 3× review overhead; per-PR flag machinery duplicated; we lose the natural dependency ordering inside a single branch (Q1 wants Q2's data-path fix for feature vectors); 2-week slower to ship an integrated empirical win.

**Option C — Q1 alone, defer everything else.** Ship shadow-mode calibration only; revisit the rest after 14 days of calibration telemetry.
- Pros: tiniest diff (~40 LOC); zero risk of production regression; generates labelled data to inform M3/Q2 scope.
- Cons: leaves the 78.4% Phase-2 drop active for 2+ weeks; leaves the analyst spread unexploited; leaves phantom configs lying; calibration shadow data is partially blind because tweets never reach `signal_events` (Q2 dependency).

**Selected: Option A** — drivers 1 and 2 require Q1+Q2 ship together (feature vectors), and drivers 1 and 3 favour bundling to minimise per-change overhead. Option B is valid under a "ship small, ship often" culture but costs 2 review cycles and partially decouples Q1 from Q2's data path. Option C is strictly dominated by A unless rollback risk is mispriced — see §1.5 pre-mortem.

**Invalidation of rejected options:**
- B is invalidated by Q1↔Q2 coupling: calibration training on empty feature vectors is a known failure mode this plan explicitly avoids (see Pre-mortem scenario 2).
- C is invalidated by driver 2: production is currently silently dropping 75–89% of Phase-2 messages; "wait 14 days" normalises a live defect.

### 1.4 Deliberate-mode: pre-mortem (3 scenarios)

**Scenario 1 — Per-analyst cooldown opens a flood on a viral day.** M3 drops the blanket 6h for high-precision analysts (e.g. TeresaTrades @ 82.9%), so a viral ticker like NVDA during earnings gets 8 tweets from the same top analyst in 2h. Channel floods, user desensitises, real signal lost.
- *Mitigation:* M3 ships with a `per_analyst_floor_minutes: 30` config (default). Even an 83%-hit-rate analyst is rate-limited to 2 alerts/ticker/hour. Kill-switch: `alerts.per_analyst_cooldown.enabled: false` restores the `(ticker,)` blanket.
- *Detection:* daily cron SQL `SELECT ticker, COUNT(*) FROM alert_history WHERE alerted_at > strftime('%s','now','-1 day') GROUP BY ticker HAVING COUNT(*) > 4` — any row → investigate.

**Scenario 2 — Calibration shadow training on empty feature vectors.** The `calibrate()` retrain path at `analysis/calibration.py:88–115` reads `decision_snapshots` rows where `outcome_price_at_alert > 0` AND `outcome_price_1h` (or `_24h`) IS NOT NULL; the audit notes that 22 current snapshots show `total_sources:0, signal_event_count:0` because xref writes the snapshot *before* signal_events arrive. Training isotonic/Platt on `final_score → hit_24h` is fine (that single feature is well-populated), but feature-vector-based extensions would be noise.
- *Mitigation:* Q2b's tweet→`signal_events` routing must merge *before* we enable any retraining cron. Until then, `retrain_all()` is gated behind `calibration.retrain_enabled: false` at merge time; shadow mode logs predictions as JSON in `decision_snapshots.feature_vector_json` without touching `_save_models()`. The retrain gate flips only after `signal_event_count > 0` in ≥80% of rows over trailing 7 days.
- *Detection:* nightly metric query against `signal_events`: `SELECT AVG(CASE WHEN EXISTS (SELECT 1 FROM signal_events WHERE signal_events.ticker = decision_snapshots.ticker AND signal_events.recorded_at BETWEEN decision_snapshots.recorded_at - 3600 AND decision_snapshots.recorded_at + 60) THEN 1.0 ELSE 0.0 END) FROM decision_snapshots WHERE recorded_at > strftime('%s','now','-7 days')`. Require ≥0.8 before flipping `retrain_enabled: true`.

**Scenario 3 — KILL 3 + orphan `.pyc` deletion removes a semi-finished feature someone intended to restore.** Both `reliability_engine.cpython-310.pyc` AND `snapshot_builder.cpython-310.pyc` are orphan bytecode in `consensus_engine/analysis/__pycache__/`; their `.py` sources are missing from disk. A WIP branch might intend to restore them.
- *Mitigation:* before the PR merges, run `git log --all --oneline -- consensus_engine/analysis/reliability_engine.py consensus_engine/analysis/snapshot_builder.py` and `git stash list | xargs -I {} git stash show --name-only {}` to confirm no live WIP. Preserve the deleted cross_reference guarded import block (`:326–376`) in the PR description as a quoted diff so a future contributor has the restoration recipe. **`regime_detector.py` stays on disk** — its tests at `tests/test_degraded_mode.py:283–367` depend on it.
- *Detection:* after the PR, `grep -rn "reliability_engine\|compute_weights\|classify_decision\|snapshot_builder" consensus_engine/ tests/` must return zero; `ls consensus_engine/analysis/__pycache__/reliability_engine.* consensus_engine/analysis/__pycache__/snapshot_builder.* 2>/dev/null | wc -l` must return 0. CI adds a lint step that grep-asserts both.

### 1.5 Deliberate-mode: expanded test plan

#### Unit tests (new / updated)

- `tests/test_calibration_shadow.py`
  - `calibrate(score=30, horizon="1h")` returns `0.30` (identity) when `_load_models() == {}`
  - `calibrate(score=30, horizon="1h")` returns isotonic-predicted prob when model exists
  - `retrain(horizon="1h")` returns `n < MIN_SAMPLES` with `_models` unchanged when labelled rows < 50
  - `log_shadow_prediction(score, calibrated_prob)` writes JSON into `decision_snapshots.feature_vector_json` (reuses existing column at `db.py:251`), verified by `SELECT feature_vector_json FROM decision_snapshots ORDER BY id DESC LIMIT 1` containing `{"shadow_prob": <float>, ...}`; does NOT call `_save_models`
  - Discord render helper at `alerts/discord.py:97–107` returns `"score/100 (uncalibrated)"` when `calibration.shadow_mode.enabled=true` AND `_load_models() == {}`; returns calibrated label when a model is loaded
- `tests/test_per_analyst_cooldown.py`
  - `check_alert_cooldown("NVDA", analyst="TeresaTrades", base_score=25)` returns True when last TeresaTrades/NVDA alert was >30 min ago, even with a kpak82/NVDA alert 2h ago
  - falls back to ticker-level 6h when `alerts.per_analyst_cooldown.enabled: false`
  - HIGH-conviction (base_score ≥ 30) bypasses cooldown entirely
  - `floor_minutes` ceiling prevents even 100% analysts from firing twice inside the floor
- `tests/test_phase2_timeout.py`
  - `_run_cross_reference_and_followup` edits the Phase-1 message with `"Phase 2 skipped — timeout"` when `asyncio.wait_for(xref_task, ...)` raises `TimeoutError`
  - the `precision_task` result is *still consumed* when the xref times out (precision engine does not get cancelled). Test: inject a 130s sleep into `cross_reference()` while precision returns in 10ms — assert `precision_result is not None` in the logged metric and `xref_result is None`.
  - edits with `"Phase 2 skipped — low precision"` when `classification == SignalClass.IGNORE`
  - normal path still updates `followup_msg_id` in `alert_messages`
- `tests/test_signal_events_tweet_routing.py`
  - `insert_signal(SourceType.TWITTER, ...)` also writes a `signal_events` row with matching `ticker`, `source_type='tweet'`, `source_detail=<analyst>`, `quality_score=<per_analyst_precision_1h>`
  - `get_signal_events_for_ticker("NVDA", 3600)` returns ≥1 row after inserting a twitter signal
- `tests/test_require_market_confirmation_exemption.py`
  - `engine.analyze_signal("NVDA", base_score=30)` skips `market_ok` gate and returns classification even with `market_ok=False`
  - SEC-catalyst flow (`catalyst_type="sec_8k_item_101"`) skips `market_ok`
  - `base_score=25` path still enforces `market_ok` exactly as before

#### Integration tests

- `tests/integration/test_alert_flow_end_to_end.py`
  - dry-run `--once` against a fixture tweet stream with 3 analysts firing same ticker in 4 hours → 2 instant pings survive (M3), 1 Phase-1 message + 1 Phase-2 edit per surviving alert, shadow calibration log has 2 rows
  - timeout-injection harness: xref coroutine sleeps 130s with `cross_reference_timeout=120` → Phase-1 message edited to "Phase 2 skipped — timeout", `followup_msg_id` remains NULL, alert still counted in `alert_history`
- `tests/integration/test_signal_events_feedthrough.py`
  - insert 5 twitter signals → `cross_reference()` sees `signal_events` rows in its 3600s window

#### Regression tests (existing suite)

- `python3 -m pytest tests/ -v` must pass at 100% of currently-passing count (baseline: capture `pytest tests/ -v --tb=no -q` output in the PR description).
- No new pytest DeprecationWarnings from sklearn pinning.

#### Observability / SLO

- New metrics (written via existing `db.record_metric()` helper):
  - `calibration_shadow_prob_mean_24h` — rolling mean calibrated prob
  - `calibration_shadow_brier_24h` — Brier score vs `hit_24h` when labels available
  - `phase2_timeout_count_1h` and `phase2_silent_drop_count_1h`
  - `cooldown_dropped_reason_distribution_1h` (`per_analyst` vs `floor` vs `ticker_fallback`)
  - `signal_events_tweets_inserted_1h`
- Daily Discord summary (reuses `alerts/commands.py !status` pattern, additive): posts these metrics to `#ops` at `daily_ops_summary_cron_hour_et = 9`.

#### End-to-end smoke

- 24h shadow-mode soak before enabling `retrain_enabled` or flipping the exemption flag. SLO: Phase-2 drop rate drops from >75% to <10% within 1h of merge (timeout fix is load-bearing for this number).

---

## 2. Implementation plan

### 2.1 Files touched (estimated LOC delta)

| File | Change | LOC |
|------|--------|-----|
| `consensus_engine/analysis/calibration.py` | add `log_shadow_prediction()` helper that writes JSON into `decision_snapshots.feature_vector_json`; no behaviour change in `calibrate()` | +30 |
| `consensus_engine/db.py` | rewrite `check_alert_cooldown` signature (`:672–682`); route tweet `insert_signal` into `signal_events` (`:1710`); add helper `get_analyst_precision(analyst, horizon)` reading `source_performance`. **No new table.** | +60 / -10 |
| `consensus_engine/main.py` | **single commit, same hunk**: update call site at `:608` to `await db.check_alert_cooldown(ticker, tweet.analyst, tweet.base_score)`; wrap ONLY `xref_task` in `asyncio.wait_for(xref_task, timeout=cfg.get("intervals.cross_reference_timeout", 120))` at `:664–668`; explicit "Phase 2 skipped — \<reason\>" edit when `TimeoutError` or `SignalClass.IGNORE`; call `log_shadow_prediction` in `_run_cross_reference_and_followup` after xref completes | +40 / -5 |
| `consensus_engine/cross_reference.py` | delete `reliability_engine_enabled` guarded block (`:326–376`); add always-on `signal_events` read used by the xref scoring path (small change — just moves `get_signal_events_for_ticker` read outside the deleted guard into the main xref flow where it contributes to scoring, so Q2b's tweet routing actually reaches a consumer) | +15 / -55 |
| `consensus_engine/engine.py` | atomic rename `require_market_confirmation` → `require_market_confirmation_for_low_conviction` at `:234, :294`; add HIGH-conviction + SEC-catalyst exemption logic; add `high_conviction_threshold` config read | +15 / -2 |
| `consensus_engine/alerts/discord.py` | `_calibrated_section` at `:97–107` returns "`score/100 (uncalibrated)`" when shadow_mode is enabled AND no trained model loaded; add "Phase 2 skipped — \<reason\>" rendering helper | +20 / -2 |
| `consensus_engine/alerts/commands.py` | same relabel as discord.py at `:876` for the `!score` command output | +5 / -1 |
| `consensus_engine/analysis/__pycache__/reliability_engine.cpython-310.pyc` | delete stale bytecode (`.py` gone) | -1 file |
| `consensus_engine/analysis/__pycache__/snapshot_builder.cpython-310.pyc` | delete stale bytecode (`.py` gone) | -1 file |
| ~~`consensus_engine/analysis/regime_detector.py`~~ | **NOT DELETED** — three tests at `tests/test_degraded_mode.py:286,320,353` import `detect_regime`. Plan keeps the module; only the config stanza is removed. | 0 |
| `config/consensus.yaml` | delete `max_alerts_per_hour: 10` (`:188`), `reliability_engine_enabled: false` (`:194`), `regime_detector:` stanza (`:197–202`); **atomic rename** `require_market_confirmation: true` → `require_market_confirmation_for_low_conviction: true` at `:297`; add `alerts.per_analyst_cooldown.*`, `calibration.shadow_mode.*`, `precision_engine.thresholds.high_conviction_threshold: 30`, `precision_engine.thresholds.sec_catalyst_exempt: true` | +15 / -8 |
| `tests/test_engine.py` | atomic rename same config key at `:246` (match engine.py rename) | +1 / -1 |
| `tests/test_calibration_shadow.py` | new | +90 |
| `tests/test_per_analyst_cooldown.py` | new | +110 |
| `tests/test_phase2_timeout.py` | new — includes the precision-survival test | +100 |
| `tests/test_signal_events_tweet_routing.py` | new | +40 |
| `tests/test_require_market_confirmation_exemption.py` | new | +60 |
| `tests/integration/test_alert_flow_end_to_end.py` | extend existing | +60 |
| `README.md` | document the new flags + atomic-rename note | +25 |

Net production LOC ≈ +200 added / -83 removed across 9 source files. Test LOC ≈ +460.

**Note on schema:** no `CREATE TABLE` is added. `feature_vector_json` is reused from the existing `decision_snapshots` schema (`db.py:244–251`). Revert = zero orphan schema.

### 2.2 Config surface (6 new flags, 3 deleted, 1 atomically renamed — no shim)

New, all default to the safest value:
```yaml
calibration:
  shadow_mode:
    enabled: true          # log predictions to decision_snapshots.feature_vector_json; relabel Discord field
  retrain_enabled: false   # flip to true only after Q2b signal_event feedthrough ≥80% for 7 days

alerts:
  per_analyst_cooldown:
    enabled: true
    floor_minutes: 30      # even 100% analyst can't fire faster than this
    high_conviction_bypass: true  # base_score >= high_conviction_threshold skips cooldown entirely

precision_engine:
  thresholds:
    high_conviction_threshold: 30
    sec_catalyst_exempt: true   # bypass require_market_confirmation_for_low_conviction when catalyst_type LIKE 'sec_%'
```

**Atomically renamed in one commit (no shim, no back-compat wrapper)** — all 4 call sites change together:

- `config/consensus.yaml:297`: `require_market_confirmation: true` → `require_market_confirmation_for_low_conviction: true`
- `consensus_engine/engine.py:234`: `cfg.get("precision_engine.thresholds.require_market_confirmation", True)` → `cfg.get("precision_engine.thresholds.require_market_confirmation_for_low_conviction", True)`
- `consensus_engine/engine.py:294`: same as above
- `tests/test_engine.py:246`: same key in the test fixture dict

If any of these 4 sites is missed in review, `pytest tests/` fails — no silent drift.

Deleted (hard delete, no shim):
```yaml
alerts:
  max_alerts_per_hour: 10            # DELETE — zero enforcement code
  reliability_engine_enabled: false  # DELETE — source file gone, import block removed
regime_detector:                     # DELETE config only
  enabled: true                      # module stays on disk (tests depend on it)
  ...
```

### 2.3 Execution order (strict — do not parallelise)

Inside the PR, commits should be logically ordered so bisect is useful:

1. **Commit A — tests first (red).** Add the 5 new test files; they all fail. Confirms the regression harness is wired.
2. **Commit B — KILL list (config + cross_reference dead code + orphan bytecode).** Delete `max_alerts_per_hour`, `reliability_engine_enabled` flag + guarded import block at `cross_reference.py:326–376`, `regime_detector:` config stanza, stale `.pyc` files for `reliability_engine` AND `snapshot_builder`. **Do NOT delete `regime_detector.py`** — the `tests/test_degraded_mode.py` import would break AC-1. All existing tests still pass.
3. **Commit C — Q2b signal_events tweet routing.** Route tweet `insert_signal` into `signal_events`; wire the always-on xref read at `cross_reference.py` so the new rows reach a consumer; test #4 goes green.
4. **Commit D — Q2a phase-2 timeout + explicit skip message.** Wrap `xref_task` (NOT the full `gather`) in `asyncio.wait_for`; add Discord edit "Phase 2 skipped — \<reason\>"; test #3 goes green (including the precision-survival assertion).
5. **Commit E — M3 per-analyst cooldown.** Rewrite `check_alert_cooldown(ticker, analyst, base_score)` in `db.py:672–682` AND update the single call site at `main.py:608` **in the same commit**; add `get_analyst_precision()` helper; test #2 goes green.
6. **Commit F — Q1 calibration shadow mode + honesty fix.** Add `log_shadow_prediction()` writing to `decision_snapshots.feature_vector_json`; relabel Discord field at `alerts/discord.py:97–107` and `alerts/commands.py:876` to "score/100 (uncalibrated)" while shadow_mode is on and no model is loaded; add `retrain_enabled` flag (default `false`); test #1 goes green.
7. **Commit G — KILL 4 atomic rename + exemption.** Rename `require_market_confirmation` → `require_market_confirmation_for_low_conviction` in all 4 call sites (`config/consensus.yaml:297`, `engine.py:234`, `engine.py:294`, `tests/test_engine.py:246`) **in the same commit**; add HIGH-conviction + SEC exemption; test #5 goes green.
8. **Commit H — README + config docs.**

Merge criteria: all 5 new test files green + full `pytest tests/` pass (including `tests/test_degraded_mode.py` which still imports `regime_detector`) + a 2h dry-run `--once --dry-run` burn-in on staging DB with tweet replay.

### 2.4 Rollback matrix

| Failure mode | One-line rollback |
|---|---|
| Calibration shadow writes too much JSON into `decision_snapshots.feature_vector_json` | `calibration.shadow_mode.enabled: false` |
| Calibration retrain produces nonsense | `calibration.retrain_enabled: false` (already default at merge) |
| M3 floods channel on a viral day | `alerts.per_analyst_cooldown.enabled: false` (reverts to blanket 6h ticker-only) |
| Phase-2 timeout fires too aggressively (cancels valid xrefs) | Raise `intervals.cross_reference_timeout` above `120` |
| Signal_events tweet routing writes rows no downstream uses | Revert Commit C (Q2b); Commit B's KILL 3 has already removed the old reliability_engine consumer — there is nothing to re-enable; this revert only stops the new writes. |
| HIGH-conviction exemption or SEC exemption lets junk through | `precision_engine.thresholds.sec_catalyst_exempt: false` AND/OR `precision_engine.thresholds.high_conviction_threshold: 999` |
| Whole PR is bad | `git revert <merge-commit>`. Zero schema orphans (no `CREATE TABLE` was added); 6 config flags default back; source files restored to pre-merge state; 2 orphan `.pyc` files need manual recreation via `python -c "import consensus_engine.analysis.reliability_engine"` only if the .py source is re-added — otherwise they should stay deleted. |

### 2.5 Acceptance criteria (testable, pre-commit)

- AC-1: `pytest tests/ -v` passes **at or above current passing count** (baseline recorded in PR description). Includes `tests/test_degraded_mode.py` which must remain green because `regime_detector.py` is NOT deleted.
- AC-2: `grep -rn "max_alerts_per_hour\|reliability_engine_enabled" consensus_engine/ config/ tests/` returns zero. `grep -rn "^regime_detector:\|regime_detector\.enabled" config/` returns zero (module imports in tests still allowed).
- AC-3: `grep -rn "require_market_confirmation[^_]" consensus_engine/ config/ tests/` returns zero. `grep -rn "require_market_confirmation_for_low_conviction" consensus_engine/ config/ tests/` returns exactly 4 matches (the renamed sites). **No back-compat shim exists** — the old key is completely absent.
- AC-4: After 60s dry-run `--once` against a tweet fixture, `SELECT COUNT(*) FROM signal_events WHERE source_type = 'twitter'` returns ≥1.
- AC-5: After a synthetic 130s `cross_reference()` stall, Discord edit transcript contains `"Phase 2 skipped — timeout"` AND precision engine metric shows a non-null result for that alert (confirms the precision task was NOT cancelled).
- AC-6: `SELECT COUNT(*) FROM decision_snapshots WHERE feature_vector_json LIKE '%shadow_prob%' AND recorded_at > strftime('%s','now','-10 minutes')` > 0 within 10 minutes of live soak.
- AC-7: Staging soak (2h): `SELECT COUNT(*)*1.0 / NULLIF((SELECT COUNT(*) FROM alert_messages WHERE created_at > strftime('%s','now','-2 hours')), 0) FROM alert_messages WHERE followup_msg_id IS NULL AND created_at > strftime('%s','now','-2 hours')` < 0.10. (Down from 0.75–0.89 baseline.)
- AC-8: No new `DeprecationWarning` in pytest output beyond baseline count.
- AC-9: `ls consensus_engine/analysis/__pycache__/reliability_engine.* consensus_engine/analysis/__pycache__/snapshot_builder.* 2>/dev/null | wc -l` returns 0 after Commit B (both orphan .pyc files gone).
- AC-10: `ls consensus_engine/analysis/regime_detector.py 2>/dev/null | wc -l` returns 1 (module is preserved, only config is deleted).
- AC-11: A Phase-2 embed rendered against a tweet WITH `calibration.shadow_mode.enabled=true` and no trained model contains the literal string `"score/100 (uncalibrated)"` — verified via unit test against `_calibrated_section()`.
- AC-12: `grep -rn "get_signal_events_for_ticker" consensus_engine/cross_reference.py` returns at least one match after Commit C. (Ensures Q2b's new tweet rows actually reach a consumer after Commit B deletes the old reliability-engine read.)
- AC-13 (soak-query polish): Replace AC-7's denominator with `created_at BETWEEN strftime('%s','now','-2 hours') AND strftime('%s','now', ?)` where `?` excludes rows younger than `cross_reference_timeout` seconds (default 120), so in-flight alerts aren't counted as orphans. Revised AC-7 SQL: `SELECT COUNT(*)*1.0 / NULLIF((SELECT COUNT(*) FROM alert_messages WHERE created_at BETWEEN strftime('%s','now','-2 hours') AND strftime('%s','now','-120 seconds')), 0) FROM alert_messages WHERE followup_msg_id IS NULL AND created_at BETWEEN strftime('%s','now','-2 hours') AND strftime('%s','now','-120 seconds')` < 0.10.

### 2.6 Verification steps (post-merge, first 24h)

1. **T+5 min:** tail engine log for `calibration: shadow mode enabled`, `per_analyst_cooldown.enabled=true`, `reliability_engine removed (was guarded)`.
2. **T+1 h:** `python3 -m consensus_engine --status` shows nonzero count of `decision_snapshots` rows where `feature_vector_json LIKE '%shadow_prob%'` (shadow predictions flowing into the reused column), `signal_events` tweet rows present, zero "reliability" log lines.
3. **T+24 h:** compute SLO metrics:
   - Phase-2 drop rate trailing 24h: < 10% (acceptance)
   - `cooldown_dropped_reason` distribution: `per_analyst` dominant, `floor` non-zero, `ticker_fallback` = 0
   - Brier score for shadow calibration: log-only — if training has begun, should be < 0.30 for 1h horizon
   - `regime_detector`, `reliability_engine_enabled`, `max_alerts_per_hour` all absent from `config/consensus.yaml`

### 2.7 Scope exclusions (explicit — not in this PR)

- **Q9 conviction parser** — blocks M6 from biting on >0.5% of traffic, but its effort is unknown and it touches the tweet-parsing NLP layer. Separate PR, separate review.
- **M1 SEC re-enable** — benefits most from KILL 4's SEC exemption but has its own watcher/filter complexity (item-type + dollar filter). Separate PR.
- **M2 options features, M4 Haiku tie-break, X1–X4 moonshots** — all additive to this foundation; none blocks it.
- **Vault / Atlas / Alfred** — already shipped in production 2026-04-23.

---

## 3. ADR (Architecture Decision Record)

**Decision:** Bundle Q1 + M3 + Q2 + four KILL actions into one branch gated by five independent config flags, merged after dual unit+integration+staging-soak validation.

**Drivers:**
- Inverted monotonicity (94.1% @30 vs 20.6% @60) demands calibration be *live* before any threshold tuning is meaningful.
- 78.4% Phase-2 orphan rate is a production defect with observable daily regression.
- Per-analyst 1h precision ranges 14%–83% — the blanket cooldown is mis-using the data already on disk.
- Three phantom configs lie to future readers; one (`reliability_engine_enabled`) will crash xref if flipped because its source file is absent.

**Alternatives considered:**
- 3-PR sequenced (Option B) — rejected: Q1 training is partially blind without Q2's data-path fix; 3× review overhead; 2-week delay on an active production defect.
- Q1-only first (Option C) — rejected: leaves 78.4% Phase-2 drop live for 2+ weeks, and Q1's feature vectors remain empty until Q2 ships.
- Defer KILL list — rejected: `reliability_engine_enabled` flag flip is a latent crash; keeping the flag while deleting the source file preserves a footgun.

**Why chosen:** smallest merger-unit that makes calibration non-trivial (Q2b feeds Q1), fixes the single worst production defect (78.4% drop), converts the single largest unexploited per-entity signal into usable rate limiting (M3 analyst spread), removes three decorative configs + one latent crash (KILL 3 orphan `.pyc` footgun), and *actually actions* Principle 1 by relabeling the lying Discord field in Commit F. Six independent flags keep the rollback unit per-component. ~200 LOC production + ~460 LOC tests fits one review cycle.

**Consequences:**
- **Positive:** Phase-2 drop < 10%; calibration begins accumulating labelled data into the existing `decision_snapshots.feature_vector_json` column; per-analyst cooldown starts exploiting the 14%→83% spread; HIGH-conviction + SEC-catalyst tweets stop being filtered by `market_ok`; two phantom configs fully removed; one phantom config stanza removed (the module survives because it has tests); two orphan `.pyc` footguns deleted; Discord "Calibrated conf" lie replaced with honest "score/100 (uncalibrated)" label.
- **Negative:** M6 (require_market_confirmation exemption) only bites on 0.5% of traffic until Q9 ships (separate PR); shadow-mode calibration produces no *calibrated* user-visible change for 2+ weeks (intentional — retrain gate); one larger diff increases per-commit review time.
- **Neutral:** no new `CREATE TABLE` (shadow predictions go into existing `decision_snapshots.feature_vector_json`); atomic 4-site rename for `require_market_confirmation` ships as one commit with no compatibility shim; `regime_detector.py` stays on disk because its tests do (deletion is deferred to a future PR that also deletes `tests/test_degraded_mode.py:283–367`).

**Follow-ups (ordered):**
1. Q9 conviction parser — separate PR, likely 2026-04-29 target.
2. Enable `calibration.retrain_enabled: true` once `AVG(signal_event_count > 0 ? 1 : 0) FROM decision_snapshots(-7d) > 0.8`. Target: 2026-05-08 (2 weeks post-merge).
3. M1 SEC re-enable with item-type + dollar filter — separate PR, depends on this one's KILL 4.
4. Revisit X2 self-play backtest when `alert_history` reaches ≥1500 labelled rows (currently 575).

---

## 4. Out-of-band notes

- `.omc/omc.jsonc` routes `critic` → codex and `planner` → claude HIGH. Ralplan invocation didn't pass `--architect codex` / `--critic codex`, so default Claude-based Architect + Critic will run against this plan below. Note the repo preference but don't override the skill default silently.
- `companyContext.tool` not configured in `.claude/omc.jsonc`; pre-loop context call skipped.
- `feedback_specs_and_plans_location.md`: plan saved to `.omc/plans/2026-04-24-top3-combined-pr-plan.md`; spec not separately written (this document serves as both).
