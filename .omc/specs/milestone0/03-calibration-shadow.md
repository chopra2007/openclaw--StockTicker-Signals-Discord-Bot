# Milestone-0 / Spec 03 — Calibration in Shadow Mode

**Author:** spec-calibration-shadow
**Date:** 2026-04-24
**Source audit:** `plans/AUDIT_RESEARCH_2026-04-24.md` § 4 ("Calibration — live-facing, untrained")
**Touched files:**
`consensus_engine/main.py`, `consensus_engine/db.py`, `consensus_engine/analysis/calibration.py`,
`config/consensus.yaml`. **No edits** to `consensus_engine/alerts/discord.py` or
`consensus_engine/alerts/commands.py` — the live "Calibrated conf." path is intentionally
left untouched (already gated by the existing `calibration.shadow_mode.enabled` flag, which
this spec does NOT flip).

---

## Decision on snapshot timing

**Verdict: option (i) is already in place.** The snapshot write is **not** the cause of the
empty feature vectors.

### Evidence

`consensus_engine/main.py:713–729` (re-read end-to-end during this spec) shows the snapshot
is written *after* `xref` has resolved:

```
656 async def _run_cross_reference_and_followup(...):
...
675     try:
676         xref = await asyncio.wait_for(asyncio.shield(xref_task), timeout=timeout_sec)
...
694     if xref_timed_out:                       # short-circuit: NO snapshot written
695         await edit_instant_ping(instant_msg_id, "Phase 2 skipped — timeout")
696         return
697     if classification == SignalClass.IGNORE: # short-circuit: NO snapshot written
698         await edit_instant_ping(instant_msg_id, "Phase 2 skipped — low precision")
699         return
700     if xref is None:                          # short-circuit: NO snapshot written
702         return
...
710     followup_id = await send_detail_followup(xref, instant_msg_id, precision=precision)
711     await db.update_alert_message_followup(alert_message_id, followup_id, xref.final_score)
712
713     # Q1 shadow-mode logging: record a decision_snapshots row and merge the
714     # calibrated probability into its feature_vector_json. Never raises.
715     try:
716         final_score = float(xref.final_score)
717         shadow_prob = calibrate(final_score, "1h")
...
722         snapshot_id = await db.record_decision_snapshot(
723             ticker=ticker,
724             decision=(classification.value if classification is not None else "UNCLASSIFIED"),
725             final_score=final_score,
726             sources_json=sources_json,                       # <-- comes from xref.breakdown
727             contradiction_index=float(getattr(xref, "contradiction_index", 0.0) or 0.0),
728         )
```

So the "feature vector empty" symptom in the 22 historical rows is **not** a race; it is
that `_serialize_breakdown(xref.breakdown)` (`main.py:488–500`) only emits the
`ScoreBreakdown` integer dataclass fields (`base`, `news_catalyst`, `social_apewisdom`, …)
and **never** writes `total_sources` or `signal_event_count`. The audit's wording —
"`total_sources:0` and `signal_event_count:0`" — describes *missing* keys read by external
analyzers as `0`, not zero values present in the JSON.

### What this spec does about it

This spec does **not** redefine the snapshot's feature-vector schema (out of scope —
upstream of calibration). It addresses the actual blocker for `retrain()`: the snapshots
have **NULL `outcome_price_at_alert` and NULL `outcome_price_{1h,24h}`** because:
1. `main.py:722–728` does not pass `outcome_price_at_alert` to `record_decision_snapshot`,
   even though the parameter exists (`db.py:1863`).
2. `price_outcome_loop` (`main.py:807–832`) backfills `alert_history.price_{1h,24h}_later`
   but *never touches* `decision_snapshots.outcome_price_{1h,24h}`. There is a working
   helper, `db.update_snapshot_outcomes` (`db.py:1895–1909`), that is unreferenced.

Both gaps are fixed below (Section 4 — backfill wiring, and Section 1's snapshot-call diff).

No startup WARNING is required because option (i) is already in effect for new rows; the
22 legacy rows simply pre-date the price-outcome wiring and will not be retrainable.

---

## 1. Where to call `retrain()`

### 1a. `retrain()` signature & dependencies — read end-to-end at `consensus_engine/analysis/calibration.py`

- **Signature:** `async def retrain(horizon: str = "1h") -> int` (line 75).
  Companion: `async def retrain_all() -> dict[str, int]` (line 129) — the right call
  for a startup hook, retrains both `"1h"` and `"24h"`.
- **Data source:** queries `decision_snapshots` directly (lines 91–99). The WHERE clause
  requires `outcome_price_at_alert IS NOT NULL` AND `outcome_price_{1h|24h} IS NOT NULL`,
  ordered by `recorded_at DESC`, capped at `LIMIT 2000`. **No external label dataset.**
  No reference to `alert_history`.
- **Cold-start guard already in place:** lines 103–108. If `n < MIN_SAMPLES (=50)` it
  logs `INFO "calibration: only %d labeled samples for horizon=%s (need %d) — identity
  fallback retained"` and returns `n`. **No crash, no model overwrite.** This is exactly
  the cold-start log behaviour the brief asked for; nothing to add.
- **Side effects on success:** `_save_models()` (line 124, body 213–224) atomically
  writes `MODEL_PATH = Path(".omc/state/calibration_model.pkl")` via `tmp + os.replace`.
  Creates parents with `path.parent.mkdir(parents=True, exist_ok=True)` (line 216) — so
  `.omc/state/` is created on demand if absent.
- **Failure modes:** isotonic + Platt both fail → `log.warning(...)` + return `n`,
  no model written, no exception propagated.

### 1b. Caller location

**File:** `consensus_engine/main.py`
**Function:** `run_live` (line 272)
**Insertion point:** between line 332 (the `combined_stop` setup) and line 333
(the `tasks = [...]` list construction). One-shot await *before* the long-running
task list is gathered, so a failed retrain logs and the engine continues.

**Rationale:**
- `run_live` is the single entrypoint for live mode (`main.py:867–869`); no other
  startup path needs to know.
- Awaiting it in-line (not as a task) means the model load in `_load_models` on the
  next `calibrate()` call sees the freshly trained `_models` dict already populated
  via `_save_models`'s in-process write (and disk).
- Gated by a new flag — see 1c.
- A periodic refresh is out of scope for milestone-0; the brief explicitly asks for a
  startup hook OR a periodic task, not both. The audit's Q1 budget is ~40 LOC.

### 1c. New config flag

**File:** `config/consensus.yaml`
**Section:** existing `calibration:` block (lines 198–202).
**Add a single key** under `calibration.shadow_mode`:

```yaml
calibration:
  shadow_mode:
    enabled: true
    retrain_on_startup: true       # NEW — gate for the run_live startup retrain hook
  retrain_enabled: false           # (unchanged — kept as the global Q2b feedthrough gate)
```

Default `true`. The existing `retrain_enabled: false` stays untouched — it gates a
*separate* future loop, not the milestone-0 startup hook.

### 1d. Diff for `consensus_engine/main.py`

```diff
@@ consensus_engine/main.py  (run_live, around line 332-333)
         async def stop_watcher():
             """Set combined_stop when either stop_event or pause_event fires."""
             done, _ = await asyncio.wait(
                 [asyncio.create_task(stop_event.wait()), asyncio.create_task(pause_event.wait())],
                 return_when=asyncio.FIRST_COMPLETED,
             )
             combined_stop.set()

+        # Milestone-0 / Spec 03: train calibration once on startup. Gated by config.
+        # retrain_all() is cold-start safe — logs INFO and returns when n < MIN_SAMPLES.
+        if cfg.get("calibration.shadow_mode.retrain_on_startup", True):
+            try:
+                from consensus_engine.analysis.calibration import retrain_all
+                results = await retrain_all()
+                log.info("Calibration startup retrain: %s", results)
+            except Exception as exc:
+                log.warning("Calibration startup retrain failed (continuing): %s", exc)
+
         tasks = [
             asyncio.create_task(stop_watcher()),
             asyncio.create_task(weekend_watchdog()),
```

**LOC:** +9 (including blank lines and comment).

### 1e. Preconditions for retrain to actually fit a model

`retrain()` queries `decision_snapshots` rows with non-NULL outcomes. As of
2026-04-24 there are **0 such rows** — all 22 snapshots have NULL outcomes (see
"Decision on snapshot timing" above). The startup hook will log
`"calibration: only 0 labeled samples for horizon=1h (need 50) — identity fallback
retained"` until the fixes in Sections 1f and 4 below have populated outcomes for
≥ 50 alerts. This is intended and matches the brief's cold-start spec.

### 1f. Fix snapshot-time price recording (preconditions for retrain)

`retrain()` needs `outcome_price_at_alert` to be set at write time (the price-outcome
backfill — Section 4 — fills the 1h/24h fields, but the entry price must be captured
synchronously at alert time to avoid a future-leak).

**File:** `consensus_engine/main.py`
**Function:** `_run_cross_reference_and_followup` (line 656)
**Change:** pass the entry price (already fetched at `main.py:623` and persisted on the
`alert_history` row at `main.py:636`) through to the snapshot.

The entry price is currently scoped only to `process_tweet` (`main.py:623`). The simplest
surgical change: thread it as a parameter into `_run_cross_reference_and_followup`.

**Backward-compat decision (Codex review 2026-04-24, Option A — preferred):** make
`entry_price` an **optional keyword-only argument** with default `None`, and fall back
to fetching it from the price service inside the function body when callers omit it.
This preserves the four existing test call sites at
`tests/test_phase2_timeout.py:99`, `:153`, `:203`, `:252` (all positional 5-arg calls)
and means **no test files need to be edited**. The fallback path also makes the
function safer to call from any future code path that lacks an upfront price.

Diff at the call site (`main.py:644–653`):

> **Note on naming.** `alert_message_id` (positional arg #4 below) is the **existing**
> Discord-message-ID variable for the Phase-1 message — used downstream by
> `update_alert_message_followup` to edit the original Discord post. It is **NOT**
> the renamed shadow-prediction FK and must not be confused with `alert_history_id`.
> The shadow-prediction FK in this spec is `alert_row_id` (= `alert_history.id`).

```diff
@@ consensus_engine/main.py  (process_tweet, around line 644)
         asyncio.create_task(
             _run_cross_reference_and_followup(
                 ticker,
                 alert_tweet,
                 instant_msg_id,
                 alert_message_id,
                 alert_row_id,
+                entry_price=price,
             ),
             name=f"xref-{ticker}-{instant_msg_id}",
         )
```

Diff at the function definition (`main.py:656–662`):

```diff
@@ consensus_engine/main.py  (line 656)
 async def _run_cross_reference_and_followup(
     ticker: str,
     tweet,
     instant_msg_id: str,
     alert_message_id: int,
     alert_row_id: int,
+    *,
+    entry_price: float | None = None,
 ):
     """Run slow xref work after the instant alert has already been persisted."""
+    # Optional kwarg for back-compat with existing tests (test_phase2_timeout.py
+    # call sites are positional, 5-arg). Fallback fetches price on demand so the
+    # snapshot still records a non-NULL entry price even when callers omit it.
+    if entry_price is None or entry_price <= 0:
+        try:
+            entry_price = float(await _fetch_price(ticker) or 0.0)
+        except Exception:
+            entry_price = 0.0
```

Diff at the snapshot write (`main.py:722–728`):

```diff
@@ consensus_engine/main.py  (line 722)
             snapshot_id = await db.record_decision_snapshot(
                 ticker=ticker,
                 decision=(classification.value if classification is not None else "UNCLASSIFIED"),
                 final_score=final_score,
                 sources_json=sources_json,
                 contradiction_index=float(getattr(xref, "contradiction_index", 0.0) or 0.0),
+                outcome_price_at_alert=(float(entry_price) if entry_price and entry_price > 0 else None),
+                alert_id=alert_row_id,
             )
```

**LOC:** +11 (1 kwarg at call site, 3 in signature incl. `*` separator + comment, 6 lines for fallback block, 2 kwargs in DB call). No test-file edits.

---

## 2. MODEL_PATH writeback verification

Already correct, no change needed. Receipts:

- `calibration.py:40`: `MODEL_PATH = Path(".omc/state/calibration_model.pkl")` — relative
  to CWD of the `python3 -m consensus_engine` process, which is `/root/.openclaw/workspace/`
  per the project commands (`CLAUDE.md`). Resolves to
  `/root/.openclaw/workspace/.omc/state/calibration_model.pkl`.
- `calibration.py:213–224` (`_save_models`):
  - line 216: `path.parent.mkdir(parents=True, exist_ok=True)` — directory created
    defensively if `.omc/state/` is missing.
  - lines 218–221: `tmp = path.with_suffix(".tmp")` → `pickle.dump` → `os.replace(tmp, path)`
    — atomic swap, no torn writes.
- Called from `retrain()` at line 124 only on the success path (after a non-`None`
  model is fitted).

No code change. Verification step in §6.

---

## 3. New `shadow_predictions` table

### 3a. Canonical `alert_id` identity — `alert_history.id`

> **Codex re-review fix (2026-04-24):** the original draft of this spec used TWO
> different identities for the column called `alert_id` — `shadow_predictions.alert_id`
> referenced `alert_messages.id` while `decision_snapshots.alert_id` referenced
> `alert_history.id`. That mismatch forced the backfill into a fuzzy ticker+time pairing
> helper to bridge the two. **Both columns now reference `alert_history.id` consistently.**

**Schemas verified:**

```
CREATE TABLE IF NOT EXISTS alert_history (         -- db.py:90-103
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    confidence_score REAL,
    catalyst TEXT,
    catalyst_type TEXT,
    consensus_breakdown TEXT,
    technical_data TEXT,
    analyst_mentions TEXT,
    alerted_at REAL NOT NULL,
    price_at_alert REAL,
    price_1h_later REAL,
    price_24h_later REAL
);

CREATE TABLE IF NOT EXISTS alert_messages (        -- db.py:121-130
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    analyst TEXT NOT NULL,
    instant_msg_id TEXT,
    followup_msg_id TEXT,
    base_score INTEGER DEFAULT 0,
    final_score INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);
```

The two tables have **no foreign-key column linking them today** (their pairing in
`get_analyst_performance_stats` at `db.py:1140-1141` is a fuzzy ticker join that this
spec deliberately avoids extending).

**Why `alert_history.id` is the canonical FK target:**

1. **Availability at every insert site, no extra lookup:**
   - `_run_cross_reference_and_followup` already receives `alert_row_id` (=
     `alert_history.id`) as a positional argument (`main.py:661`). The
     `decision_snapshots` insert (`main.py:722`) and the `shadow_predictions` inserts
     (Section 4a) both fire from inside this function — `alert_row_id` is in scope
     for both. No helper required.
   - `price_outcome_loop` (`main.py:807`) already iterates over `alert_history` rows
     (via `db.get_alerts_needing_price_update`, `db.py:991`) and uses `alert["id"]`
     (= `alert_history.id`) as its update key. Labelling
     `shadow_predictions WHERE alert_id = alert["id"]` is a single direct UPDATE.
2. **`alert_history` is the source of truth for outcomes.** `price_at_alert`,
   `price_1h_later`, `price_24h_later` all live on `alert_history`. Computing
   `actual_hit` for a shadow prediction needs the entry/exit price pair, which lives
   on the same row keyed by `alert_history.id`.
3. **Eliminates the ticker+time fuzzy join.** Pre-fix, the backfill resolved
   `alert_history.id → alert_messages.id` via a `WHERE ticker = ? AND
   ABS(am.created_at - ah.alerted_at) < 60`; two alerts on the same ticker inside the
   same minute (common — multi-analyst storms, the same analyst tweeting the same
   ticker repeatedly) would collide. With `alert_history.id` as the canonical key,
   the backfill becomes a deterministic `WHERE alert_id = ?`.

`alert_messages.id` was rejected because at the time `price_outcome_loop` runs, only
`alert_history.id` is in scope — the loop would have to fuzzy-join through ticker+time
back to `alert_messages` to label rows. That's exactly the bug Codex flagged.

Joins for post-hoc analysis are trivial: `shadow_predictions.alert_id = alert_history.id`,
and `decision_snapshots.alert_id = alert_history.id` — same column meaning, single join key.

### 3b. CREATE TABLE statement

```sql
CREATE TABLE IF NOT EXISTS shadow_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    predicted_prob REAL NOT NULL,
    horizon TEXT NOT NULL,
    actual_hit INTEGER,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_alert ON shadow_predictions(alert_id);
CREATE INDEX IF NOT EXISTS idx_shadow_pending ON shadow_predictions(actual_hit, horizon)
    WHERE actual_hit IS NULL;
```

Notes:
- **Deliberate: no SQLite `FOREIGN KEY` declaration on `shadow_predictions.alert_id`
  or `decision_snapshots.alert_id`.** SQLite's `PRAGMA foreign_keys` is OFF by default
  in this codebase (no `PRAGMA foreign_keys=ON` anywhere in `db.py`); declaring the FK
  would be cosmetic and no rows would be rejected. The `idx_shadow_alert` index covers
  the join path that actually matters. **This applies to both the `shadow_predictions`
  CREATE TABLE here and the `decision_snapshots.alert_id` ALTER TABLE in §3e** — neither
  declares `REFERENCES alert_history(id)` for the same reason. Future readers / spec
  reviewers: the absence of `REFERENCES` is intentional, not an oversight.
- `created_at INTEGER` (unix ts) per the brief. Note that the rest of this codebase uses
  `REAL` (float seconds, e.g. `alert_messages.created_at REAL`). Using `INTEGER` per
  the brief is fine — SQLite is type-affinity, joins on time work either way.
- `actual_hit INTEGER` is NULL until the price-outcome backfill (Section 4) labels it
  as `0` or `1`.
- The partial index on `(actual_hit, horizon) WHERE actual_hit IS NULL` is the index the
  backfill loop scans — it stays small (only unlabelled rows).

### 3c. Where the migration goes

**File:** `consensus_engine/db.py`
**Location:** the `SCHEMA` string literal, immediately after the
`decision_snapshots` block (lines 244–260, ending at line 260's
`CREATE INDEX IF NOT EXISTS idx_snapshots_decision`). `executescript(SCHEMA)` at
`db.py:547` is the single migration entrypoint and uses `IF NOT EXISTS`, so this is
idempotent and re-runnable on every startup.

```diff
@@ consensus_engine/db.py  (SCHEMA string, after line 260)
 CREATE INDEX IF NOT EXISTS idx_snapshots_ticker ON decision_snapshots(ticker);
 CREATE INDEX IF NOT EXISTS idx_snapshots_recorded ON decision_snapshots(recorded_at);
 CREATE INDEX IF NOT EXISTS idx_snapshots_decision ON decision_snapshots(decision);

+CREATE TABLE IF NOT EXISTS shadow_predictions (
+    id INTEGER PRIMARY KEY AUTOINCREMENT,
+    alert_id INTEGER NOT NULL,
+    predicted_prob REAL NOT NULL,
+    horizon TEXT NOT NULL,
+    actual_hit INTEGER,
+    created_at INTEGER NOT NULL
+);
+CREATE INDEX IF NOT EXISTS idx_shadow_alert ON shadow_predictions(alert_id);
+CREATE INDEX IF NOT EXISTS idx_shadow_pending ON shadow_predictions(actual_hit, horizon)
+    WHERE actual_hit IS NULL;
+
 CREATE TABLE IF NOT EXISTS youtube_channels (
```

**LOC:** +11.

### 3d. New helper functions in `db.py`

Two helpers — placed below `update_snapshot_outcomes` at `db.py:1909`:

```diff
@@ consensus_engine/db.py  (after update_snapshot_outcomes, around line 1909)
     await conn.commit()


+# ---------------------------------------------------------------------------
+# Shadow-prediction helpers (Milestone-0 Spec 03)
+# ---------------------------------------------------------------------------
+
+async def insert_shadow_prediction(
+    alert_id: int,
+    predicted_prob: float,
+    horizon: str,
+) -> int:
+    """Record an unlabelled calibration prediction. `alert_id` references
+    `alert_history.id` (Section 3a). Returns the new row ID."""
+    conn = await get_db()
+    cursor = await conn.execute(
+        """INSERT INTO shadow_predictions
+           (alert_id, predicted_prob, horizon, actual_hit, created_at)
+           VALUES (?, ?, ?, NULL, ?)""",
+        (alert_id, float(predicted_prob), horizon, int(time.time())),
+    )
+    await conn.commit()
+    return cursor.lastrowid
+
+
+async def get_pending_shadow_predictions(horizon: str, limit: int = 500) -> list[dict]:
+    """Return shadow_predictions rows where actual_hit IS NULL for one horizon.
+    Joins through alert_history (the canonical FK target) for ticker context."""
+    conn = await get_db()
+    cursor = await conn.execute(
+        """SELECT sp.id, sp.alert_id, sp.predicted_prob, sp.horizon, sp.created_at,
+                  ah.ticker
+           FROM shadow_predictions sp
+           JOIN alert_history ah ON sp.alert_id = ah.id
+           WHERE sp.actual_hit IS NULL AND sp.horizon = ?
+           ORDER BY sp.created_at ASC
+           LIMIT ?""",
+        (horizon, limit),
+    )
+    rows = await cursor.fetchall()
+    return [dict(r) for r in rows]
+
+
+async def update_shadow_actual(prediction_id: int, actual_hit: int) -> None:
+    """Label a shadow prediction with the realised 0/1 outcome."""
+    conn = await get_db()
+    await conn.execute(
+        "UPDATE shadow_predictions SET actual_hit = ? WHERE id = ?",
+        (int(actual_hit), prediction_id),
+    )
+    await conn.commit()
+
+
 # ---------------------------------------------------------------------------
 # Source health helpers
 # ---------------------------------------------------------------------------
```

**LOC:** +37 (helpers + the section banner).

### 3e. Column migration — `decision_snapshots.alert_id`

**File:** `consensus_engine/db.py`
**Mechanism:** add to `_run_column_migrations` (line 460). This is the standard
add-column-if-missing path used elsewhere in the file. Idempotent.

```diff
@@ consensus_engine/db.py  (_run_column_migrations, alongside the other entries)
+        ("decision_snapshots", "alert_id",  "INTEGER"),
```

```diff
@@ consensus_engine/db.py  (record_decision_snapshot, line 1855)
 async def record_decision_snapshot(
     ticker: str,
     decision: str,
     final_score: float,
     sources_json: str,
     contradiction_index: float = 0.0,
     feature_vector_json: str | None = None,
     weights_json: str | None = None,
     outcome_price_at_alert: float | None = None,
+    alert_id: int | None = None,
 ) -> int:
     """Record a decision snapshot. Returns the new row ID."""
     conn = await get_db()
     cursor = await conn.execute(
         """INSERT INTO decision_snapshots
            (ticker, decision, final_score, contradiction_index, sources_json,
-            feature_vector_json, weights_json, recorded_at, outcome_price_at_alert)
-           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
+            feature_vector_json, weights_json, recorded_at, outcome_price_at_alert,
+            alert_id)
+           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
         (ticker, decision, final_score, contradiction_index, sources_json,
-         feature_vector_json, weights_json, time.time(), outcome_price_at_alert),
+         feature_vector_json, weights_json, time.time(), outcome_price_at_alert,
+         alert_id),
     )
     await conn.commit()
     return cursor.lastrowid
```

`alert_id` here is `alert_history.id` (returned by `db.insert_alert` at
`main.py:628–637` and stored in scope as `alert_row_id`) — **the same canonical
identity used by `shadow_predictions.alert_id`** (Section 3a). This is what lets
`price_outcome_loop` later find the snapshot row to backfill — by joining
`decision_snapshots.alert_id = alert_history.id`.

A small lookup helper goes alongside it:

```diff
@@ consensus_engine/db.py  (after update_snapshot_outcomes, around line 1909)
+
+async def get_snapshot_id_for_alert(alert_id: int) -> int | None:
+    """Return the decision_snapshots.id for a given alert_history.id, or None."""
+    conn = await get_db()
+    cursor = await conn.execute(
+        "SELECT id FROM decision_snapshots WHERE alert_id = ? LIMIT 1",
+        (alert_id,),
+    )
+    row = await cursor.fetchone()
+    return row["id"] if row else None
```

**LOC:** +14 (column-migration entry: +1, `record_decision_snapshot` signature/INSERT
edit: +4, helper: +9).

---

## 4. Shadow-mode logging hook

### 4a. Where the per-alert insert happens

**File:** `consensus_engine/main.py`
**Function:** `_run_cross_reference_and_followup`
**Location:** inside the existing `try:` block at lines 715–731, immediately after the
existing `log_shadow_prediction` call on line 729 (which writes to
`decision_snapshots.feature_vector_json` — orthogonal observability path that this spec
preserves).

This is the right place because:
- `xref.final_score` is already computed (line 716).
- `alert_row_id` (= `alert_history.id`, the canonical FK target per Section 3a) is
  already in scope (`main.py:661`) and is also passed to `record_decision_snapshot`
  on the line just above, so both `decision_snapshots.alert_id` and
  `shadow_predictions.alert_id` reference the same value in a single function frame.
- The existing `try/except` at line 715–731 is a "never raises" envelope per the
  inline comment — adding two more rows inside it inherits the safety property.
- It runs only on the success path (after `send_detail_followup` at line 710), which
  matches the brief's "after each Phase-2 alert is sent" requirement.

```diff
@@ consensus_engine/main.py  (inside _run_cross_reference_and_followup, around line 729)
             snapshot_id = await db.record_decision_snapshot(
                 ticker=ticker,
                 decision=(classification.value if classification is not None else "UNCLASSIFIED"),
                 final_score=final_score,
                 sources_json=sources_json,
                 contradiction_index=float(getattr(xref, "contradiction_index", 0.0) or 0.0),
                 outcome_price_at_alert=(float(entry_price) if entry_price and entry_price > 0 else None),
                 alert_id=alert_row_id,
             )
             await log_shadow_prediction(snapshot_id, score=final_score, calibrated_prob=shadow_prob)
+
+            # Milestone-0 Spec 03: emit per-horizon shadow predictions.
+            # alert_id below references alert_history.id (NOT alert_messages.id) —
+            # the canonical identity shared with decision_snapshots.alert_id; see §3a.
+            # The Discord-facing "Calibrated conf." display in alerts/discord.py:101
+            # is intentionally NOT touched — shadow mode is observability only.
+            shadow_prob_24h = calibrate(final_score, "24h")
+            await db.insert_shadow_prediction(alert_row_id, shadow_prob,     "1h")
+            await db.insert_shadow_prediction(alert_row_id, shadow_prob_24h, "24h")
         except Exception as shadow_exc:
             log.debug("shadow calibration logging skipped for $%s: %s", ticker, shadow_exc)
```

**LOC:** +6.

### 4b. Backfill: where `actual_hit` and snapshot outcomes get labelled

**Existing nightly/periodic loops verified:**
- `price_outcome_loop` (`main.py:807–832`) — runs every 300s, already does
  yfinance polling for alerts needing 1h/24h prices, and writes to
  `alert_history.price_{1h,24h}_later`. **This is the right loop to extend** — adding
  `decision_snapshots` and `shadow_predictions` labelling here reuses the same yfinance
  fetch budget and the same 300-second cadence, with no new async task.

> **Codex review fix #2 (2026-04-24).** The previous draft of this section labelled
> shadow predictions via `WHERE ticker = ?` only. That is unsafe: any ticker with two
> or more alerts (extremely common — same analyst tweets the same ticker repeatedly,
> multiple analysts tweet the same ticker on the same day, etc.) would label the
> wrong rows because all unlabelled rows for that ticker share the same SET clause.
> The corrected backfill keys on **`shadow_predictions.alert_id`**, which is
> `alert_history.id` (Section 3a) — the same row `price_outcome_loop` already iterates,
> so the labelling reduces to a direct `WHERE alert_id = ?` update with no helper join.

> **Codex re-review fix (2026-04-24, this revision).** The intermediate draft used
> `alert_messages.id` for `shadow_predictions.alert_id` and `alert_history.id` for
> `decision_snapshots.alert_id` — a foreign-key identity mismatch that forced the
> backfill into a fuzzy ticker+time pairing helper
> (`get_alert_message_ids_for_alert_history`). Both columns now reference
> `alert_history.id` consistently, the helper is removed, and the loop labels shadow
> predictions in a single `UPDATE shadow_predictions SET actual_hit = ? WHERE
> actual_hit IS NULL AND alert_id = ? AND horizon = ?` keyed directly on the
> `alert["id"]` (= `alert_history.id`) the loop already holds.

> **Codex review fix #3 (2026-04-24).** The previous draft mentioned that
> `price_outcome_loop` would update `decision_snapshots.outcome_price_{1h,24h}` via
> `db.update_snapshot_outcomes`, but the diff never actually called it. Without that
> call, `retrain()` (`calibration.py:89–99`) stays blocked because its WHERE clause
> requires those columns non-NULL.  The corrected loop body **explicitly** calls
> `db.update_snapshot_outcomes(snapshot_id, …)` for every priced alert, where
> `snapshot_id` is resolved via the new `decision_snapshots.alert_id` column
> (Section 3e) and the new `db.get_snapshot_id_for_alert` helper.

**File:** `consensus_engine/main.py`
**Function:** `price_outcome_loop` (line 807)

The loop already iterates by horizon field (`price_1h_later`, `price_24h_later`); we
extend it inside the existing per-alert branch to (a) update
`decision_snapshots.outcome_price_{1h,24h}` for the matching snapshot and (b) label
every `shadow_predictions` row whose `alert_id` matches the current
`alert_history.id` and whose `horizon` matches. Because both `decision_snapshots.alert_id`
and `shadow_predictions.alert_id` reference `alert_history.id` (Section 3a), and the loop
iterates `alert_history` rows directly, no fuzzy join or pairing helper is needed —
labelling reduces to one direct UPDATE per (alert, horizon) pair.

#### New helper in `db.py` (alongside §3d)

```diff
@@ consensus_engine/db.py  (after update_shadow_actual)
+
+async def label_shadow_predictions_for_alert_id(
+    alert_history_id: int,
+    horizon: str,
+    entry_price: float,
+    exit_price: float,
+) -> int:
+    """Label unlabelled shadow_predictions rows for a SPECIFIC alert_history.id
+    and horizon.  Returns the number of rows labelled (0 or 1 in normal operation).
+
+    Codex review fix #2 + re-review fix: the WHERE clause keys on alert_id (=
+    alert_history.id, the canonical FK target per Section 3a), NOT on ticker, so
+    multiple alerts for the same ticker get labelled independently with the
+    correct entry/exit pair for each."""
+    if entry_price <= 0 or exit_price <= 0:
+        return 0
+    actual = 1 if exit_price > entry_price else 0
+    conn = await get_db()
+    cursor = await conn.execute(
+        """UPDATE shadow_predictions
+              SET actual_hit = ?
+            WHERE actual_hit IS NULL
+              AND alert_id = ?
+              AND horizon = ?""",
+        (actual, alert_history_id, horizon),
+    )
+    await conn.commit()
+    return cursor.rowcount or 0
```

**LOC:** +21 (one helper; the previously-required `get_alert_message_ids_for_alert_history`
pairing helper is no longer needed because both FK columns now reference
`alert_history.id` directly).

#### Loop-body diff in `main.py`

```diff
@@ consensus_engine/main.py  (price_outcome_loop, around line 817)
     try:
         while not stop_event.is_set():
             try:
                 for field in ("price_1h_later", "price_24h_later"):
+                    horizon = "1h" if field == "price_1h_later" else "24h"
                     alerts = await db.get_alerts_needing_price_update(field)
                     for alert in alerts:
                         price = await loop.run_in_executor(executor, _fetch_yfinance_price, alert["ticker"])
                         if price > 0:
                             await db.update_alert_price(alert["id"], field, price)
+                            # Codex fix #3: update decision_snapshots.outcome_price_{1h,24h}
+                            # so calibration.retrain() can read labelled rows.
+                            snapshot_id = await db.get_snapshot_id_for_alert(alert["id"])
+                            if snapshot_id is not None:
+                                if horizon == "1h":
+                                    await db.update_snapshot_outcomes(snapshot_id, outcome_price_1h=float(price))
+                                else:
+                                    await db.update_snapshot_outcomes(snapshot_id, outcome_price_24h=float(price))
+                            # Codex fix #2 + re-review fix: label shadow_predictions
+                            # by alert_id+horizon, NOT by ticker.  alert["id"] is
+                            # alert_history.id, which is also shadow_predictions.alert_id
+                            # (canonical identity per Section 3a) — direct WHERE alert_id = ?.
+                            entry = float(alert.get("price_at_alert") or 0.0)
+                            if entry > 0:
+                                await db.label_shadow_predictions_for_alert_id(
+                                    alert_history_id=alert["id"],
+                                    horizon=horizon,
+                                    entry_price=entry,
+                                    exit_price=float(price),
+                                )
             except Exception as e:
                 log.error("Price outcome loop error: %s", e, exc_info=True)
```

**LOC:** +17.

`db.get_alerts_needing_price_update` (referenced at `main.py:819`, defined at
`db.py:991`) already returns `price_at_alert` in its SELECT — `entry` comes for free.
The `alert["id"]` it returns is `alert_history.id`, which is exactly the value
stored in BOTH `decision_snapshots.alert_id` (via §3e) and `shadow_predictions.alert_id`
(via §4a). The `get_snapshot_id_for_alert` helper resolves the snapshot row,
and `label_shadow_predictions_for_alert_id` updates the matching shadow rows
directly — no fuzzy join, no pairing helper.

### 4c. What this spec deliberately does NOT change

The brief is explicit and so is this spec:
> The live "Calibrated conf." display in Discord embeds (`alerts/discord.py:101`)
> MUST remain UNCHANGED. Shadow mode means logging predictions, NOT swapping the
> displayed value.

**No edits** to:
- `consensus_engine/alerts/discord.py` (`_calibrated_section`, lines 97–121).
- `consensus_engine/alerts/commands.py` (`_handle_market_view`, lines 854–897).

Both already honour `cfg.get("calibration.shadow_mode.enabled", True)` and render
`"score/100 (uncalibrated): **N/100**"` when no model is loaded — that path remains
the live UX, and once the startup retrain (Section 1) actually loads a trained model,
the existing code seamlessly switches to the calibrated probability lines. No flag
flip, no copy change.

---

## 5. Schema migrations summary

> **Note (Codex review clarification 2026-04-24):** `shadow_predictions` does NOT exist
> in the live codebase today — that is correct, and intentional. This spec is the
> *introduction* of the table; the `CREATE TABLE` statement below is the migration that
> creates it.  Likewise, the `decision_snapshots.alert_id` column is *new* in this spec
> (added via `_run_column_migrations`).

| Migration | File:line | Mechanism |
|---|---|---|
| `CREATE TABLE shadow_predictions` (+2 indices) | `db.py` `SCHEMA` literal, after line 260 | `executescript(SCHEMA)` at `db.py:547`; `IF NOT EXISTS` makes it idempotent on every `init_db`. |
| `ALTER TABLE decision_snapshots ADD COLUMN alert_id INTEGER` | `db.py` `_run_column_migrations` | New entry in the column-migrations list. Idempotent (skipped if column already present). |

One `ALTER TABLE` column migration — `decision_snapshots.alert_id` is added via
`_run_column_migrations` (`db.py:460`).  No new tables on existing
`db.py` POST_MIGRATION_INDICES list (`db.py:448`); `shadow_predictions` columns are
all defined inline in the SCHEMA literal.

No on-disk file moves. `MODEL_PATH = .omc/state/calibration_model.pkl` is created
on first successful `retrain()` via `_save_models` (`calibration.py:213–224`), which
calls `path.parent.mkdir(parents=True, exist_ok=True)` defensively at line 216.

---

## 6. Verification

Run all of these after deploy, in order. Each line is copy-pasteable.

### 6a. Schema landed
```bash
python3 -c "import sqlite3; c=sqlite3.connect('/root/.openclaw/workspace/consensus.db'); \
print('shadow_predictions cols:', [r[1] for r in c.execute('PRAGMA table_info(shadow_predictions)').fetchall()])"
# Expected: ['id', 'alert_id', 'predicted_prob', 'horizon', 'actual_hit', 'created_at']
```

### 6b. New snapshots populate `outcome_price_at_alert`
```bash
python3 -c "import sqlite3, time; c=sqlite3.connect('/root/.openclaw/workspace/consensus.db'); \
cutoff = time.time() - 86400; \
print('snapshots last 24h with non-null entry price:', \
list(c.execute('SELECT COUNT(*) FROM decision_snapshots WHERE recorded_at > ? AND outcome_price_at_alert IS NOT NULL', (cutoff,)).fetchone()))"
# Expected: count > 0 once the engine has run live for >0 alerts post-deploy.
```

### 6c. Shadow predictions inserting
```bash
python3 -c "import sqlite3, time; c=sqlite3.connect('/root/.openclaw/workspace/consensus.db'); \
cutoff = time.time() - 86400; \
print(list(c.execute('SELECT horizon, COUNT(*) FROM shadow_predictions WHERE created_at > ? GROUP BY horizon', (int(cutoff),)).fetchall()))"
# Expected: [('1h', N), ('24h', N)] with matching N (every Phase-2 alert emits both).
```

### 6d. Backfill labelling
```bash
python3 -c "import sqlite3, time; c=sqlite3.connect('/root/.openclaw/workspace/consensus.db'); \
print('pending unlabelled shadow rows older than 25h:', \
c.execute('SELECT COUNT(*) FROM shadow_predictions WHERE actual_hit IS NULL AND created_at < ?', (int(time.time()-25*3600),)).fetchone()[0])"
# Expected: 0 (or near-zero — all >25h-old rows should be labelled by price_outcome_loop).
```

### 6e. Model file exists once n >= 50
```bash
ls -la /root/.openclaw/workspace/.omc/state/calibration_model.pkl
# Pre-50-samples: file absent (expected). Post-50: file present, mtime in last 24h.
grep -c "Calibration startup retrain" /root/.openclaw/workspace/consensus_engine.log
# Expected: >= 1 (proves the run_live hook fired).
```

### 6f. Discord display unchanged
```bash
grep -n "score/100 (uncalibrated)\|Calibrated conf" /root/.openclaw/workspace/consensus_engine/alerts/discord.py
# Expected: lines 112 and 118 unchanged from pre-deploy (this spec must not edit them).
git diff -- consensus_engine/alerts/discord.py consensus_engine/alerts/commands.py
# Expected: empty diff.
```

### 6g. No regressions on the snapshot path
```bash
python3 -c "import sqlite3, time; c=sqlite3.connect('/root/.openclaw/workspace/consensus.db'); \
cutoff = time.time() - 86400; \
print('snapshot count last 24h:', c.execute('SELECT COUNT(*) FROM decision_snapshots WHERE recorded_at > ?', (cutoff,)).fetchone()[0])"
# Expected: count >= 1 if any Phase-2 alerts fired (ensures the new entry_price plumbing
# did not break the call site).
```

---

## 7. LOC delta

| File | LOC delta |
|---|---|
| `consensus_engine/main.py` | +43 (1d: +9 startup hook, 1f: +11 entry-price plumbing+fallback, 4a: +6 shadow-predict insert, 4b: +17 backfill loop extension) |
| `consensus_engine/db.py` | +83 (3c: +11 schema, 3d: +37 three helpers, 3e: +14 column migration + record_decision_snapshot edits + lookup helper, 4b: +21 one label helper — pairing helper removed after FK identity unified to `alert_history.id`) |
| `consensus_engine/analysis/calibration.py` | 0 (no changes — `retrain()`, `_save_models`, `MODEL_PATH` already correct) |
| `consensus_engine/alerts/discord.py` | 0 (intentionally untouched) |
| `consensus_engine/alerts/commands.py` | 0 (intentionally untouched) |
| `tests/test_phase2_timeout.py` | 0 (Option A — `entry_price` made optional kwarg with fallback; existing 5-arg positional calls remain valid) |
| `config/consensus.yaml` | +1 (`retrain_on_startup: true` under existing `calibration.shadow_mode`) |
| **Total** | **+127 LOC** |

Above the audit's headline Q1 budget ("~40 LOC, one flag") — that estimate covered only
the startup-hook fragment.  The remainder is the schema, the column migration (Codex
review fix), the four new DB helpers, the snapshot-outcome backfill (Codex review fix
#3), and the alert-id-keyed shadow-prediction labelling (Codex review fix #2), all of
which the brief explicitly required as out-of-scope-of-Q1's headline number.

---

## 8. Revision history

> **Reader's note for future review passes:** the bullets below describe the
> intermediate drafts of this spec. They contain references to *deleted* helpers
> (`get_alert_message_ids_for_alert_history`) and *renamed* parameters
> (`alert_message_id` → `alert_history_id` in the shadow-prediction labeller).
> These references are historical record, not stale code. The current spec body
> (§3, §4) does **not** call any of those deleted symbols; do not flag them as
> orphans. Separately, the variable name `alert_message_id` also appears in §1d
> as the existing Discord-message-ID parameter of `_run_cross_reference_and_followup`
> in live `main.py` — that occurrence is unrelated to the rename and is correct.

- **2026-04-24** — Original draft, Section 4b labelled shadow predictions by ticker;
  `_run_cross_reference_and_followup` took `entry_price` as a required positional arg;
  `price_outcome_loop` did not call `db.update_snapshot_outcomes`.
- **Revised 2026-04-24 in response to Codex review:**
  - **(#1)** Added clarifying note in Section 5 that `shadow_predictions` is introduced
    by this spec (not pre-existing). No code change required.
  - **(#2)** Backfill keyed on `alert_id` not ticker. Replaced
    `label_shadow_predictions_for_alert(ticker, …)` with
    `label_shadow_predictions_for_alert_id(alert_message_id, …)`; loop body resolves
    `alert_history.id → alert_messages.id` via the standard ticker+timestamp pairing
    helper `get_alert_message_ids_for_alert_history`.
  - **(#3)** Added explicit `db.update_snapshot_outcomes(snapshot_id, …)` call inside
    `price_outcome_loop`. Required two supporting changes:
    (a) new `decision_snapshots.alert_id` column via `_run_column_migrations` so
    snapshots can be located by `alert_history.id`;
    (b) new `db.get_snapshot_id_for_alert(alert_id)` helper.
  - **(#4)** Chose **Option A**: `entry_price` made an optional keyword-only argument
    (`*, entry_price: float | None = None`) with a runtime fallback that calls
    `_fetch_price(ticker)` when omitted. The 4 existing test call sites at
    `tests/test_phase2_timeout.py:99`, `:153`, `:203`, `:252` continue to work
    unchanged. No test-file edits required.
- **Revised 2026-04-24 in response to Codex re-review:** unified `alert_id` to reference
  `alert_history.id` across both `decision_snapshots` and `shadow_predictions`
  (intermediate draft had `shadow_predictions.alert_id → alert_messages.id` while
  `decision_snapshots.alert_id → alert_history.id`, a foreign-key identity mismatch);
  eliminated the ticker+time fuzzy join in backfill. Specific changes:
  - Section 3a rewritten to state the canonical identity decision and rationale;
    `alert_history` schema now shown alongside `alert_messages`.
  - Section 3d: `insert_shadow_prediction` docstring + `get_pending_shadow_predictions`
    JOIN target switched from `alert_messages` to `alert_history`.
  - Section 4a: `insert_shadow_prediction` calls now pass `alert_row_id` (=
    `alert_history.id`), not `alert_message_id`.
  - Section 4b: removed `get_alert_message_ids_for_alert_history` pairing helper;
    `label_shadow_predictions_for_alert_id` parameter renamed
    `alert_message_id → alert_history_id`; loop body simplified to a direct
    `WHERE alert_id = alert["id"]` UPDATE.
  - LOC totals updated: main.py +46 → +43, db.py +97 → +83, total +144 → +127.
