# Milestone 0 / Spec 01 — Phantom Killer

**Goal:** Remove three phantom configuration entries that lie about non-existent functionality, plus one residual dangling comment they left behind.

**Audit source:** `plans/AUDIT_RESEARCH_2026-04-24.md` Part 3.5, 3.7, and Part 4.4 (KILL list).

**Scope:** Surgical deletions only. No replacements, no shims, no behavioral changes.

---

## Current-state addendum (read first)

A pre-flight verification of the workspace at the time this spec was written shows that the team-verify pipeline already executed most of the YAML deletions in commit `95a78ea` ("KILL: remove max_alerts_per_hour, reliability_engine_enabled, regime_detector config stanza + orphan .pyc files" — see `.omc/handoffs/team-verify-report.md`). Specifically:

- `grep -n "max_alerts_per_hour" config/consensus.yaml` → 0 matches
- `grep -n "regime_detector" config/consensus.yaml` → 0 matches
- `grep -n "reliability_engine" config/consensus.yaml` → 0 matches
- `grep -n "reliability_engine_enabled" consensus_engine/` → 0 matches
- `grep -n "reliability_engine_enabled" tests/` → 0 matches

Therefore changes (a), (b), and most of (c) below describe the *intended* end-state and serve as a regression spec — the implementer should re-run the verification grep first and confirm zero matches. If matches reappear (e.g. after a bad merge), apply the diff blocks below.

The **only remaining live work item** is the residual dangling comment at `consensus_engine/cross_reference.py:326-327` (change (c) item 3), which still references the now-removed reliability_engine code path.

The audit referenced specific line numbers (`:188`, `:194`, `:197-202`) that were valid at audit time. The spec preserves those line references so the diff blocks are reviewable against the audit, but the implementer should locate keys by grep, not by line number — the file has shifted.

---

## (a) Remove `max_alerts_per_hour` from `config/consensus.yaml`

**File:** `config/consensus.yaml`
**Audit-time line:** 188 (under the `alerts:` block)
**Rationale:** Audit Part 3.7 found zero code references for this key across `consensus_engine/`. A "max alerts per hour" guardrail that is not enforced anywhere is a phantom — it lies to future readers about behavior that does not exist. Re-verified: `grep -rn "max_alerts_per_hour" consensus_engine/ config/ tests/` returns 0 matches. The audit recommends *delete*, not enforce; precision impact is +0 either way.

```diff
 alerts:
   cooldown_hours: 6
-  max_alerts_per_hour: 10
   embed_color_long: 0x00FF00
   embed_color_short: 0xFF0000
```

If the key has additional inline comments on the same line, remove them with the line. No replacement key is added.

**LOC delta:** -1 line.

---

## (b) Remove `regime_detector:` block from `config/consensus.yaml`

**File:** `config/consensus.yaml`
**Audit-time lines:** 197-202 (top-level `regime_detector:` stanza)
**Rationale:** Audit Part 3.5 / Part 4.4 noted the stanza declared `enabled: true` with zero call sites in `main.py`, `cross_reference.py`, or `engine.py`. The source module `consensus_engine/analysis/regime_detector.py` exists and is imported by `tests/test_degraded_mode.py` (lines 286, 320, 353), but no production code path reads `cfg.get("regime_detector.*")`. The config block is therefore a phantom feature flag for an un-wired module. Removing the YAML stanza only — **the source file `consensus_engine/analysis/regime_detector.py` MUST be preserved** because (i) future milestones (`plans/discovery-2026-04-24/40-implementation-plan.md`) plan to wire it, and (ii) `tests/test_degraded_mode.py` imports it directly and would break if deleted.

```diff
-# Regime detector — abstain on adverse market conditions
-regime_detector:
-  enabled: true
-  vol_spike_threshold: 3.0          # SPY 1-day return z-score; > 3 = vol spike
-  breadth_min_bull_pct: 0.30        # < 30% bullish breadth = bearish regime
-  contradiction_index_max: 0.60     # cross-source disagreement ceiling
-  abstain_score_boost: 20           # add to required base_score in adverse regime
```

The exact comment text and surrounding blank lines may differ slightly; remove the stanza header (`regime_detector:`), every indented child key, any leading section comment that pertains exclusively to this stanza, and a single trailing blank line if it leaves a double-blank.

**Do NOT touch:**
- `consensus_engine/analysis/regime_detector.py` — preserved for future wire-up.
- `tests/test_degraded_mode.py` — direct module import, unaffected by YAML removal.

**LOC delta:** -7 lines (6 stanza lines + 1 section comment).

---

## (c) Remove `reliability_engine_enabled` flag, guarded import, and dangling comment

**Rationale:** Audit Part 3.5 / Part 4.4 #3 found the source file `consensus_engine/analysis/reliability_engine.py` is **missing from disk** — only the `__pycache__/reliability_engine.cpython-310.pyc` bytecode artifact remained at audit time. The YAML flag `alerts.reliability_engine_enabled: false` therefore controlled an import of a module that no longer existed; flipping it to `true` would have crashed every cross-reference call. The audit verdict was "restore or delete within a week" — the team chose delete. Three residue points must be removed.

### (c.1) YAML flag deletion

**File:** `config/consensus.yaml`
**Audit-time line:** 194 (under the `alerts:` block)

```diff
 alerts:
   cooldown_hours: 6
   embed_color_long: 0x00FF00
   embed_color_short: 0xFF0000
   min_base_score_for_alert: 20
-  reliability_engine_enabled: false  # source file missing — flag is a footgun
   embed_color_neutral: 0xFFAA00
```

**LOC delta:** -1 line.

### (c.2) Guarded import block in `cross_reference.py`

**File:** `consensus_engine/cross_reference.py`
**Audit-time lines:** ~327-330 (try/except import guarded by the YAML flag)
**Current state:** Already removed in commit `95a78ea`. Verified by `grep -n "reliability_engine" consensus_engine/cross_reference.py` → 1 match (the dangling comment only — no import block remains).

If a regression reintroduces the block it will look approximately like:

```diff
-    if cfg.get("alerts.reliability_engine_enabled", False):
-        try:
-            from consensus_engine.analysis.reliability_engine import score_reliability
-            reliability_pts = await score_reliability(ticker, signal_events, cfg)
-            result.final_score += reliability_pts
-        except ImportError:
-            log.warning("reliability_engine import failed; flag is on but module missing")
```

Remove the entire conditional and its body. Do NOT replace with a stub. The always-on `signal_events` read at the current `cross_reference.py:328-332` already covers the data-path consumer that the deleted block used to feed.

**LOC delta:** -7 lines (only if regressed; currently 0).

### (c.3) Dangling comment at `cross_reference.py:326-327`

**File:** `consensus_engine/cross_reference.py`
**Lines:** 326-327
**Rationale:** The 2-line comment references "KILL 3 removed the reliability_engine guarded read" — historical churn metadata that is meaningless to a reader who never saw the deleted block. The comment also implicitly documents code that no longer exists. Replace the two-line history-comment with a single-line description of what the always-on `signal_events` read actually does.

Current text (lines 322-332 for context):

```diff
     # Record per-component latency metrics
     for metric_key, ms_value in metrics.items():
         await db.record_metric(f"xref_{metric_key}", ms_value)

-    # Q2b: always-on signal_events read so tweet rows (now routed via insert_signal)
-    # reach a consumer after KILL 3 removed the reliability_engine guarded read.
+    # Always-on signal_events read so tweet rows (routed via insert_signal) reach a consumer.
     try:
         signal_events = await db.get_signal_events_for_ticker(ticker, window_seconds=3600)
         log.debug("cross_reference $%s: signal_events in 1h window=%d", ticker, len(signal_events))
     except Exception as exc:  # pragma: no cover - defensive; DB read must never block scoring
         log.warning("cross_reference: signal_events read failed for $%s: %s", ticker, exc)
```

**LOC delta:** -1 line (2 removed, 1 added).

---

## Verification

Run the following greps from the workspace root *after* applying all changes. Each must return zero matches in the listed paths.

```bash
# (a) max_alerts_per_hour fully removed
grep -rn "max_alerts_per_hour" consensus_engine/ config/ tests/

# (b) regime_detector removed from config — source file and test imports stay
grep -n "^regime_detector:" config/consensus.yaml
grep -n "regime_detector\." config/consensus.yaml

# Module file MUST still exist (preserved for future wire-up)
ls consensus_engine/analysis/regime_detector.py

# Test imports MUST still resolve (do not delete)
grep -n "from consensus_engine.analysis.regime_detector" tests/

# (c) reliability_engine_enabled flag, import block, and KILL-3 reference all gone
grep -rn "reliability_engine_enabled" consensus_engine/ config/ tests/
grep -rn "reliability_engine" consensus_engine/cross_reference.py
grep -n "KILL 3" consensus_engine/cross_reference.py

# .pyc orphan should also be gone (already cleaned in commit 95a78ea — confirm)
ls consensus_engine/analysis/__pycache__/reliability_engine* 2>/dev/null || echo "ok: no orphan .pyc"
```

Acceptance: all greps return zero matches except the `regime_detector.py` source-file `ls` (must succeed) and the `tests/` import grep (must return ≥3 matches in `tests/test_degraded_mode.py`).

Test suite: `python3 -m pytest tests/ -v` — all previously-passing tests must still pass. The change is config-only + comment-only; no behavioral test should be affected.

---

## LOC delta — total

| Change | LOC delta |
|--------|-----------|
| (a) `max_alerts_per_hour` YAML key | -1 |
| (b) `regime_detector:` YAML stanza | -7 |
| (c.1) `reliability_engine_enabled` YAML key | -1 |
| (c.2) guarded import block in `cross_reference.py` | -7 (only if regressed; currently 0) |
| (c.3) dangling KILL-3 comment in `cross_reference.py` | -1 (2 removed, 1 added) |
| **Total** | **-10 lines** (or -17 if (c.2) regressed) |

---

## Out of scope (do not touch)

- `consensus_engine/analysis/regime_detector.py` — preserved for milestone 40 wire-up.
- `consensus_engine/analysis/calibration.py` — separate spec.
- `plans/AUDIT_RESEARCH_2026-04-24.md` and any other historical document — historical record, not active config.
- `plans/ytfinal.md` — historical plan that references `reliability_engine_enabled`; do not edit historical plans.
- `README.md` line that lists the deleted keys — already updated in commit `95a78ea`; verify, do not duplicate.
