# Milestone 0 — Spec Summary

**Date:** 2026-04-24
**Source audit:** `plans/AUDIT_RESEARCH_2026-04-24.md`
**Spec directory:** `.omc/specs/milestone0/`
**Scope:** 5 spec documents addressing the audit's "if you only change 5 things" list. No source files modified by the spec pass.

---

## Spec inventory

| # | File | Purpose | Source files touched | Net LOC |
|---|------|---------|----------------------|---------|
| 01 | `01-phantom-killer.md` | Remove 3 phantom config entries that lie about non-existent functionality | `config/consensus.yaml`, `consensus_engine/cross_reference.py` | **−10** (−17 if regressed) |
| 02 | `02-phase2-drop.md` | Phase-2 timeout wrap + tweet→`signal_events` dual-write | `consensus_engine/main.py` | **+1 / −1** |
| 03 | `03-calibration-shadow.md` | Turn calibration retrain on; shadow-mode log predicted vs hit_24h; new `shadow_predictions` table | `consensus_engine/main.py`, `consensus_engine/db.py`, `config/consensus.yaml` | **+127** (revised twice post-Codex) |
| 04 | `04-yt-level-dedup.md` | Tighten `was_level_recently_alerted` to 24h per-ticker-per-price band ±0.5%; add composite index | `consensus_engine/db.py` (+optional `consensus_engine/analysis/video_classifier.py`) | **~+11 / −3** (+14 / −4 with optional Path A) |
| 05 | `05-per-analyst-cooldown.md` | Replace linear scaling with clamped-weight precision-weighted cooldown; cap at 24h | `consensus_engine/db.py`, `config/consensus.yaml` | **+4** |

---

## Aggregate touched-file map

| File | Touched by | Approx delta |
|------|-----------|--------------|
| `config/consensus.yaml` | 01, 03, 05 | **−9 / +2** (≈ **−7 net**) |
| `consensus_engine/main.py` | 02, 03 | **+44 / −1** (calibration revision added entry_price plumbing, retrain hook, shadow insert, snapshot-outcome backfill) |
| `consensus_engine/db.py` | 03, 04, 05 | **+96 / −3** (~+10 from yt-dedup, +83 from calibration helpers + new `shadow_predictions` + `decision_snapshots.alert_id` migration, +3 from cooldown formula) |
| `consensus_engine/cross_reference.py` | 01 | **−1** (live cleanup of dangling comment) |
| `consensus_engine/analysis/video_classifier.py` | 04 (optional Path A only) | **+3 / −1** if taken |

**Estimated milestone total:** **~+143 / −15 LOC** across 4 required files (5 if Path A is included).

---

## Important pre-flight findings (from spec authors)

These corrections to the audit emerged during spec investigation and must be respected by anyone implementing:

1. **Spec 01 (phantom-killer):** All three YAML phantoms and the guarded import block were already removed by commit `95a78ea`. Only a 2-line dangling "KILL 3" comment at `cross_reference.py:326–327` is live cleanup work. The spec doubles as a regression spec for the YAML state.
2. **Spec 02 (phase2-drop):** Both bugs are **already fixed in code** (`main.py:665–679` wraps with `asyncio.wait_for`+`asyncio.shield`+TimeoutError handler; `db.py:594–618` performs the tweet-only dual-write inside `insert_signal`). Residual work is a one-line log-format normalization at `main.py:679`.
3. **Spec 03 (calibration-shadow):** Snapshot-timing option (i) is already in effect — snapshots are written after xref resolves at `main.py:713–731`. Real blockers are missing `outcome_price_at_alert` plumbing (3 LOC) and `decision_snapshots.outcome_price_{1h,24h}` never being backfilled by `price_outcome_loop` (extended in §4b). MODEL_PATH atomic-write already correct.
4. **Spec 04 (yt-level-dedup):** Root cause is **not** SQL permissiveness — query at `db.py:1782–1793` already enforces per-ticker-per-price uniqueness within ±1%, but its default `cooldown_seconds=14400` (4h) lets each level re-fire ~6×/day. Fix: bump default to `86400` (24h) and tighten band to ±0.5%. The audit-named knob `youtube.near_price_dedup_pct=0.5` is **dead code** — no Python reads it; spec recommends NOT changing the value.
5. **Spec 05 (per-analyst-cooldown):** Audit was stale on current state — `check_alert_cooldown` at `db.py:714–781` is *already* per-analyst with full test coverage. This spec is a formula swap (linear → concave `base/weight` with `weight = clamp(precision * 2, 0.5, 2.0)`) plus a new `max_cooldown_hours: 24` config knob, not a green-field rewrite. The audit's `analyst_handle` column does not exist; analysts live in `alert_history.analyst_mentions` as a JSON-array TEXT blob, so no new index is added (leading-`%` LIKE can't use a B-tree). **Revised post-Codex:** initial spec used `clamp(precision, 0.5, 2.0)`, which inverted intent (upper clamp unreachable for `precision ∈ [0,1]`); now uses the `precision * 2` scale that matches the audit's worked examples (TeresaTrades 0.829 → 3.62h; kpak82 0.143 → 12h).

---

## Sequencing & dependencies

- **Spec 01 (phantom-killer)** — independent; ship anytime.
- **Spec 02 (phase2-drop)** — independent; ship anytime (one log-line edit).
- **Spec 03 (calibration-shadow)** — independent of 01/02/04. Will benefit from 02 being live so price-outcome data is complete; not blocking.
- **Spec 04 (yt-level-dedup)** — independent; ship anytime.
- **Spec 05 (per-analyst-cooldown)** — **HARD DEPENDENCY: must merge after 02-phase2-drop.md.** Reason: hit-rate data in `alert_history` is incomplete until Phase-2 drops are eliminated; per-analyst weights would otherwise be undercounted.

---

---

## Codex adversarial review — outcome

| Spec | Initial verdict | Action taken |
|------|-----------------|---------------|
| 01-phantom-killer.md | APPROVE | none |
| 02-phase2-drop.md | APPROVE | none |
| 03-calibration-shadow.md | 4 issues → 1 new issue → final APPROVE | **Revised twice.** Pass 1: backfill keyed on `alert_id` (not ticker); explicit `update_snapshot_outcomes` call added; `entry_price` made optional kwarg with runtime fallback (Option A — preserves the 4 existing `tests/test_phase2_timeout.py` callers); `shadow_predictions` clarified as new table. Pass 2 (after re-review caught FK-identity mismatch): unified both `decision_snapshots.alert_id` and `shadow_predictions.alert_id` to reference `alert_history.id`; deleted `get_alert_message_ids_for_alert_history` pairing helper; LOC dropped +144 → +127. Disambiguation notes added so revision-history references and the unrelated `main.py:209/225` `alert_message_id` parameter are not mistaken for stale code. |
| 04-yt-level-dedup.md | APPROVE | none |
| 05-per-analyst-cooldown.md | 2 issues → APPROVE | **Revised in place.** Formula corrected to `weight = clamp(precision * 2, 0.5, 2.0)` so worked examples now match the audit (TeresaTrades 0.829 → 3.62h; kpak82 0.143 → 12h). Reframed as tightening of an existing per-analyst formula, not introduction of one. Mechanism for `None` precision unified: `weight = 1.0 if precision is None else clamp(...)`. |

**Final Codex verdict (all 5 specs):** APPROVE. Spec phase complete, ready for implementation hand-off.

---

## What is *not* in this milestone (deferred to later)

- Conviction-parser fix (Q9) — required to unblock M6 (HIGH-conviction `market_ok` exemption); audit estimate 60 LOC; sized in a future milestone.
- SEC watcher re-enable with item-type filter (M1) — depends on M6.
- Volume scanner wire-up (Q5).
- SearXNG body enrichment (Q4).
- Reddit upvote / comment-velocity weighting (Q7).
- `regime_detector` re-wire — config block removed by 01; module deliberately left on disk per `plans/discovery-2026-04-24/40-implementation-plan.md`.
