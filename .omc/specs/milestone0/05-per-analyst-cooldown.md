# Milestone 0 / Spec 05 — Per-Analyst Cooldown (clamped-weight rewrite)

> **DEPENDENCY: Must merge after `02-phase2-drop.md`.**
> **Rationale:** This spec re-tunes cooldown scaling using `source_performance.rolling_accuracy` ("hit_rate_1h"). Per the audit, **78.4 % of alerts currently lose their Phase-2 follow-up**, so `rolling_accuracy` is undercounted today. Landing this rewrite *before* the Phase-2 fix would (a) bake in artificially short cooldowns for analysts who happen to have non-zero hit rates despite the loss, and (b) leave high-hit-rate analysts (whose missing follow-ups would have been *positive*) wrongly stuck on the 6 h fallback. Wait until Phase-2 telemetry is whole, then enable this rewrite.

---

## 0. Audit source

`plans/AUDIT_RESEARCH_2026-04-24.md` §M3 ("Replace blanket 6 h cooldown with per-analyst precision weighting") + §218 (verdict "too blunt — replace with per-analyst cooldown"). Empirical spread: TeresaTrades 82.9 % @ n=41 vs kpak82 14.3 % @ n=7.

## 0.1 Important pre-flight finding (read this first)

A grep at spec-write time shows **`check_alert_cooldown` is already partially per-analyst** as of `consensus_engine/db.py:714-781` — it accepts `(ticker, analyst, base_score)`, calls `get_analyst_precision()`, has a HIGH-conviction bypass, and a `floor_minutes` enforcement. The audit text quoting "ticker-level COUNT(*) at db.py:672-682" is **stale** — that was the pre-M3 state. M3 already shipped a *first-pass* implementation that linearly interpolates between `cooldown_hours*60` and `floor_minutes`.

**This spec is therefore not a green-field implementation. It is a formula swap and bound-tightening.** Specifically:

| Current (db.py:768-777) | This spec |
|---|---|
| `precision is None → scaled_minutes = cooldown_hours*60` (cold start = 6 h ✓) | Same (cold start = 6 h) |
| `precision present → scaled_minutes = max(floor_minutes, floor_minutes + (default_minutes - floor_minutes) * (1.0 - precision))` (linear) | `weight = clamp(precision * 2, 0.5, 2.0); cooldown_h = min(24, base_6h / weight)` |
| No `n < 5` low-confidence guard at the call site (the guard lives inside `get_analyst_precision`, which already returns `None` when `sample_count < 5`) | **Reused as-is** (`get_analyst_precision` already returns `None` for `sample_count < 5`; spec maps that to weight=1.0) |
| No 24 h upper cap | Add 24 h cap |

The behavioural deltas are: (1) the scaling **curve** changes (clamped doubled-precision-weight vs linear), (2) the worst-precision analysts are capped at 24 h instead of `cooldown_hours*60` (= 6 h), and (3) high-precision analysts are **shorter** than 6 h (e.g. TeresaTrades 0.829 → 3.62 h). The HIGH-conviction bypass, blanket-fallback path, and floor enforcement stay verbatim.

**Decision: rewrite `check_alert_cooldown` in place — DO NOT add a parallel `check_per_analyst_cooldown` function.** Justification: (a) every caller already passes `(ticker, analyst, base_score)`; a parallel function would duplicate the bypass/floor/blanket scaffolding for no benefit; (b) tests in `tests/test_per_analyst_cooldown.py` already target the existing name with the existing signature.

---

## 1. Investigation findings

### 1.1 Current implementation — `consensus_engine/db.py:714-781`

```python
async def check_alert_cooldown(
    ticker: str,
    analyst: str | None = None,
    base_score: int | None = None,
) -> bool:
    """Return True when an alert for (ticker, analyst, base_score) is allowed."""
    cooldown_hours = cfg.get("alerts.cooldown_hours", 6)
    per_analyst_enabled = cfg.get("alerts.per_analyst_cooldown.enabled", True)
    high_conv_bypass = cfg.get("alerts.per_analyst_cooldown.high_conviction_bypass", True)
    high_conv_threshold = cfg.get("precision_engine.thresholds.high_conviction_threshold", 30)
    floor_minutes = cfg.get("alerts.per_analyst_cooldown.floor_minutes", 30)

    conn = await get_db()

    async def _blanket_blocked() -> bool:
        cutoff = time.time() - (cooldown_hours * 3600)
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM alert_history WHERE ticker = ? AND alerted_at > ?",
            (ticker, cutoff),
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0

    async def _analyst_blocked_within(window_minutes: int) -> bool:
        cutoff = time.time() - (window_minutes * 60)
        cursor = await conn.execute(
            """SELECT COUNT(*) as cnt FROM alert_history
               WHERE ticker = ? AND analyst_mentions LIKE ? AND alerted_at > ?""",
            (ticker, f'%"{analyst}"%', cutoff),
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0

    if not per_analyst_enabled or analyst is None:
        return not await _blanket_blocked()

    if (high_conv_bypass and base_score is not None
        and base_score >= high_conv_threshold):
        return True

    precision = await get_analyst_precision(analyst, horizon="1h")
    if precision is None:
        scaled_minutes = cooldown_hours * 60
    else:
        default_minutes = cooldown_hours * 60
        scaled_minutes = max(
            floor_minutes,
            int(floor_minutes + (default_minutes - floor_minutes) * (1.0 - precision)),
        )
    if await _analyst_blocked_within(scaled_minutes):
        return False
    return not await _analyst_blocked_within(floor_minutes)
```

### 1.1a Comparison vs current live formula

The live code at `db.py:767-777` **already** scales cooldown inversely with precision — higher precision yields a shorter `scaled_minutes`. The function-of-precision is linear:

```
scaled_minutes(p) = max(floor_minutes,
                        floor_minutes + (default - floor) * (1 - p))
                  = max(30, 30 + 330 * (1 - p))     # with default=360, floor=30
```

So:

| precision | live `scaled_minutes` | live `cooldown_h` |
|---|---|---|
| 1.0 | max(30, 30) = 30 min | 0.5 h |
| 0.829 | max(30, 30 + 330·0.171) = ~86 min | ~1.43 h |
| 0.5 | 30 + 330·0.5 = 195 min | 3.25 h |
| 0.143 | 30 + 330·0.857 = ~313 min | ~5.22 h |
| 0.0 / cold | default = 360 min | 6 h |

That curve is **directionally correct** (higher precision → shorter cooldown) but bottoms out at the 30-minute floor for any precision ≥ ~0.91, and tops out at exactly 6 h for the worst (or unknown) analyst — there is **no upper cap above 6 h**, so a 14 %-precision analyst has the same effective cooldown as a cold-start one.

**Delta this spec introduces** (smaller than the original spec language implied):

1. **24 h ceiling.** Low-precision analysts (e.g. kpak82 at 0.143) now go to 12 h instead of being clamped at the same 6 h as a cold-start analyst. That separates "known bad" from "unknown".
2. **Doubled scale (`precision * 2`).** A 0.5-precision analyst now sits at the *baseline* 6 h instead of 3.25 h; a 1.0-precision analyst sits at the 3 h cap (after `min(max_cap, base/weight)`) instead of 0.5 h. The previous linear curve was **too aggressive** at the high end — 30-minute cooldowns on a 100 %-rate analyst is barely above the floor. The new curve hits 3 h at the cap, which leaves room for the floor to remain meaningfully lower.
3. **Concave shape.** `base / weight` curves; linear was straight. The concave shape compresses the gap between "good" and "great" analysts and stretches the gap between "bad" and "terrible".

So the spec is **value-add = (24 h cap) + (doubled-precision-weight scale) + (concave curve)**. The framing is "tightening an existing per-analyst formula with an explicit upper cap and a `precision * 2` scale", **not** "introducing per-analyst weighting" (which already exists).

### 1.2 `source_performance` schema — `consensus_engine/db.py:293-300`

```sql
CREATE TABLE IF NOT EXISTS source_performance (
    entity_id        TEXT NOT NULL,           -- analyst handle (e.g. 'TeresaTrades')
    horizon          TEXT NOT NULL,           -- '1h' | '24h' | etc.
    rolling_accuracy REAL DEFAULT 0.0,        -- "hit_rate_1h" when horizon='1h'
    sample_count     INTEGER DEFAULT 0,       -- number of resolved alerts feeding this stat
    updated_at       REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (entity_id, horizon)
);
```

**Mapping to audit terminology:** the audit refers to `hit_rate_1h`; the actual column is `rolling_accuracy` filtered by `horizon='1h'`. The `get_analyst_precision(analyst, horizon='1h')` helper at `db.py:700-711` already does this lookup and **returns `None` when `sample_count < 5`** — the audit's "low-confidence n<5" rule is already enforced upstream. No additional check needed at the call site.

### 1.3 Call sites of `check_alert_cooldown`

```text
consensus_engine/main.py:609          await db.check_alert_cooldown(ticker, tweet.analyst, tweet.base_score)
tests/test_degraded_mode.py:122       patch(...)  return_value=True
tests/test_degraded_mode.py:173       patch(...)  return_value=True
tests/test_per_analyst_cooldown.py    full coverage of new signature
tests/integration/test_alert_flow_end_to_end.py:84  comment only
```

**Production caller** is exactly **one line** at `main.py:609`. It already passes `(ticker, tweet.analyst, tweet.base_score)`. **No call-site changes required by this spec.** `tweet.analyst` and `tweet.base_score` are already in scope at that frame.

### 1.4 `alert_history` schema — `consensus_engine/db.py:90-106`

```sql
CREATE TABLE IF NOT EXISTS alert_history (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    confidence_score    REAL,
    catalyst            TEXT,
    catalyst_type       TEXT,
    consensus_breakdown TEXT,
    technical_data      TEXT,
    analyst_mentions    TEXT,                 -- JSON array, e.g. '["TeresaTrades"]'
    alerted_at          REAL NOT NULL,
    price_at_alert      REAL,
    price_1h_later      REAL,
    price_24h_later     REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alert_history(ticker);
CREATE INDEX IF NOT EXISTS idx_alerts_time   ON alert_history(alerted_at);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker_time ON alert_history(ticker, alerted_at);
```

**Critical finding — divergence from audit prose:** `alert_history` does **NOT** have an `analyst_handle` column. Analysts are stored in `analyst_mentions` as a **JSON-array TEXT blob** (e.g. `'["TeresaTrades"]'`). The existing per-analyst lookup uses `analyst_mentions LIKE '%"<analyst>"%'` (db.py:749). The audit's suggested SQL `WHERE analyst_handle = ?` would fail.

**Implications:**
1. The new query MUST use the same `LIKE '%"<analyst>"%'` predicate. Switching to a normalised column would require a schema migration that is explicitly out of scope for this spec.
2. **No B-tree index** can directly serve a `LIKE '%X%'` predicate (leading `%` defeats indexing). The composite `idx_alerts_ticker_time(ticker, alerted_at)` already in place is the best we can do — SQLite will use it to narrow on `ticker = ? AND alerted_at > ?` first, then row-scan the (small) survivor set for the `analyst_mentions LIKE` filter. **No new index is added.** (See §3.3 below — original audit suggested an index on `(ticker, analyst_handle, alerted_at)` but that was based on the wrong-schema assumption.)

---

## 2. New cooldown logic (clamped-weight formula)

### 2.1 Inputs (config — already exist)

| key | default | source |
|---|---|---|
| `alerts.cooldown_hours` | 6 | `config/consensus.yaml:187` |
| `alerts.per_analyst_cooldown.enabled` | true | `:194` |
| `alerts.per_analyst_cooldown.floor_minutes` | 30 | `:195` |
| `alerts.per_analyst_cooldown.high_conviction_bypass` | true | `:196` |
| `precision_engine.thresholds.high_conviction_threshold` | 30 | `:298` |
| `alerts.per_analyst_cooldown.max_cooldown_hours` | **NEW** — default 24 | added by this spec |

### 2.2 Decision tree

```
1. per_analyst_enabled = false  OR  analyst is None
        → return NOT _blanket_blocked()       (legacy ticker-level 6 h)
2. high_conv_bypass AND base_score >= high_conv_threshold (30)
        → return True                          (skip every cooldown including floor)
3. precision = get_analyst_precision(analyst, '1h')
   IF precision is None  (cold-start OR sample_count < 5)
        weight = 1.0
   ELSE
        weight = clamp(precision * 2, 0.5, 2.0)   # clamp(x, lo, hi) = min(hi, max(lo, x))
   cooldown_h = min(max_cooldown_hours, cooldown_hours / weight)   # 24 h cap
   scaled_minutes = max(floor_minutes, int(cooldown_h * 60))
4. IF _analyst_blocked_within(scaled_minutes) → False
5. IF _analyst_blocked_within(floor_minutes)   → False              (always-on floor)
6. ELSE                                         → True
```

### 2.3 Cold-start & low-confidence consolidation

`get_analyst_precision()` returns `None` for **both** "no row exists" (cold start) **and** "row exists with sample_count < 5" (low confidence). This spec maps both paths to `weight = 1.0 → cooldown_h = 6 h` via the explicit `if precision is None: weight = 1.0` branch. The previous linear-formula version of this code achieved the same 6 h baseline through a different arm (`scaled_minutes = cooldown_hours * 60`); the new arm computes `weight` first, then derives `cooldown_h = base / weight`. Output is identical for cold-start, mechanism is now uniform with the precision-known path.

### 2.4 Worked examples

The `precision * 2` scale makes a 50 %-precision analyst the *baseline*: anyone above 50 % is faster than 6 h, anyone below is slower than 6 h.

| analyst | rolling_accuracy | sample_count | weight | cooldown_h | scaled_minutes (with floor=30) |
|---|---|---|---|---|---|
| TeresaTrades | 0.829 | 41 | clamp(1.658) = 1.658 | 6 / 1.658 = **3.62 h** | 217 min |
| kpak82 | 0.143 | 7 | clamp(0.286) = 0.500 (floor) | 6 / 0.5 = **12 h** | 720 min |
| (cold start) | — | — | 1.0 (None branch) | **6 h** | 360 min |
| low-conf analyst | 0.95 | 2 | 1.0 (None branch — n<5) | **6 h** | 360 min |
| superstar | 1.000 | 50 | clamp(2.000) = 2.000 (cap) | min(24, 6/2.0) = **3 h** | 180 min |
| 50 %-baseline | 0.500 | 30 | clamp(1.000) = 1.000 | 6 / 1.0 = **6 h** | 360 min |
| floor-near | 0.05 | 30 | clamp(0.10) = 0.500 (floor) | min(24, 6/0.5) = **12 h** | 720 min |
| edge case 0.0 | 0.000 | 30 | clamp(0.000) = 0.500 (floor) | min(24, 6/0.5) = **12 h** | 720 min |

The four boundary examples called out by the audit / Codex review:

- `precision=1.0` → `weight=2.0` (cap) → `cooldown_h = min(24, 6/2.0) = 3 h`
- `precision=0.829` (TeresaTrades) → `weight=1.658` → `cooldown_h = 6/1.658 = 3.62 h` ✓ matches audit
- `precision=0.143` (kpak82) → `weight·raw = 0.286` → clamp to `0.5` → `cooldown_h = 12 h` ✓ matches audit
- `precision=0.0` → `weight·raw = 0.0` → clamp to `0.5` → `cooldown_h = 12 h`

> **Floor still wins:** the per-analyst pass returns False if blocked-within-`scaled_minutes`, AND additionally if blocked-within-`floor_minutes`. The 100 %-precision analyst test (`test_floor_minutes_blocks_even_100pct_precision_analyst`) continues to pass because the floor check is unconditional — even with the new 3 h cap, the 30 min floor is still enforced separately.

### 2.5 SQL — unchanged (kept verbatim from current implementation)

**Lookup:** delegated to `get_analyst_precision()`:

```sql
SELECT rolling_accuracy, sample_count
FROM source_performance
WHERE entity_id = ? AND horizon = ?
```

**Per-analyst recent-alert check** (parameterised, mirrors `_analyst_blocked_within`):

```sql
SELECT COUNT(*) AS cnt FROM alert_history
WHERE ticker = ?
  AND analyst_mentions LIKE ?           -- pattern: '%"<analyst>"%'
  AND alerted_at > ?                    -- cutoff = unix-now - window_minutes*60
```

> Audit's draft used `strftime('%s','now', '-Xh')`. The existing code uses `time.time() - window*60` passed as a Python float. Keep the **Python-side cutoff** — it matches surrounding style and avoids SQLite/Python clock drift edge cases. Same plan, same row scan.

---

## 3. Diffs

### 3.1 `consensus_engine/db.py` — replace lines 767–781 (the per-analyst scaling block)

```diff
@@ consensus_engine/db.py: async def check_alert_cooldown
     # HIGH-conviction bypass: skips every cooldown including the floor.
     if (
         high_conv_bypass
         and base_score is not None
         and base_score >= high_conv_threshold
     ):
         return True

-    # Per-analyst path with precision weighting (fallback: default cooldown_hours).
-    precision = await get_analyst_precision(analyst, horizon="1h")
-    if precision is None:
-        scaled_minutes = cooldown_hours * 60
-    else:
-        # Map precision [0.0, 1.0] -> scaled_minutes [cooldown_hours*60, floor_minutes]
-        default_minutes = cooldown_hours * 60
-        scaled_minutes = max(
-            floor_minutes,
-            int(floor_minutes + (default_minutes - floor_minutes) * (1.0 - precision)),
-        )
+    # Per-analyst path: weight = clamp(precision * 2, 0.5, 2.0).
+    # cooldown_h = min(max_cap, base / weight); 50%-precision = baseline 6 h.
+    # Cold-start AND sample_count<5 both arrive as precision=None -> weight=1.0 (= base 6 h).
+    max_cooldown_hours = cfg.get("alerts.per_analyst_cooldown.max_cooldown_hours", 24)
+    precision = await get_analyst_precision(analyst, horizon="1h")
+    if precision is None:
+        weight = 1.0
+    else:
+        weight = min(2.0, max(0.5, precision * 2.0))
+    cooldown_h = min(max_cooldown_hours, cooldown_hours / weight)
+    scaled_minutes = max(floor_minutes, int(cooldown_h * 60))
     if await _analyst_blocked_within(scaled_minutes):
         return False
     # Always enforce floor regardless of precision
     return not await _analyst_blocked_within(floor_minutes)
```

**Verification of the four worked examples against the diff above** (mental trace):

- `precision=1.0` → `precision*2 = 2.0` → `min(2, max(0.5, 2.0)) = 2.0` → `cooldown_h = min(24, 6/2.0) = 3.0 h` → `scaled_minutes = max(30, 180) = 180`. ✓
- `precision=0.829` → `precision*2 = 1.658` → `min(2, max(0.5, 1.658)) = 1.658` → `cooldown_h = min(24, 6/1.658) = 3.6188 h` → `scaled_minutes = max(30, int(217.13)) = 217`. ✓
- `precision=0.143` → `precision*2 = 0.286` → `min(2, max(0.5, 0.286)) = 0.5` → `cooldown_h = min(24, 6/0.5) = 12.0 h` → `scaled_minutes = max(30, 720) = 720`. ✓
- `precision=0.0` → `precision*2 = 0.0` → `min(2, max(0.5, 0.0)) = 0.5` → `cooldown_h = min(24, 6/0.5) = 12.0 h` → `scaled_minutes = max(30, 720) = 720`. ✓

**LOC delta:** −7 / +10 → **net +3 LOC** in `db.py`.

### 3.2 `config/consensus.yaml` — register the new cap

```diff
@@ config/consensus.yaml: alerts:
   per_analyst_cooldown:
     enabled: true
     floor_minutes: 30               # even 100%-precision analyst can't fire faster than this
     high_conviction_bypass: true    # base_score >= high_conviction_threshold skips cooldown entirely
+    max_cooldown_hours: 24          # upper bound; clamps low-precision analysts (weight=0.5 → 12 h)
```

**LOC delta:** +1 LOC in `config/consensus.yaml`.

### 3.3 No new index

**Decision: do not add an index.** The audit suggested `CREATE INDEX … ON alert_history(ticker, analyst_handle, alerted_at)`, but `analyst_handle` does not exist as a column (see §1.4) and the actual filter is `analyst_mentions LIKE '%"<a>"%'`. SQLite cannot use a B-tree index for a leading-`%` LIKE. The existing `idx_alerts_ticker_time(ticker, alerted_at)` already prunes by ticker + recency before the LIKE filter row-scans the survivors. Survivor sets are tiny (single-digit rows per (ticker, 24 h)) so the LIKE is O(1) in practice.

If a future spec adds a normalised `analyst_handle` column (separate migration), only then would the audit's index recommendation apply.

**LOC delta:** 0.

### 3.4 No caller updates

The single production caller at `consensus_engine/main.py:609` already passes `(ticker, tweet.analyst, tweet.base_score)`. The two test patches in `tests/test_degraded_mode.py` mock the symbol with `return_value=True` and are signature-agnostic. Tests in `tests/test_per_analyst_cooldown.py` already match the new signature.

**LOC delta:** 0.

### 3.5 Total LOC delta

| file | delta |
|---|---|
| `consensus_engine/db.py` | +3 |
| `config/consensus.yaml` | +1 |
| `consensus_engine/main.py` | 0 |
| index DDL | 0 |
| **TOTAL** | **+4 LOC** |

---

## 4. Verification

### 4.1 Unit tests (existing — must stay GREEN)

`tests/test_per_analyst_cooldown.py` (5 tests). The tests assert behaviour that the new formula preserves:

- `test_cooldown_passes_for_different_analyst_on_same_ticker` — independence across analysts. **Passes** (analyst-scoped LIKE filter unchanged).
- `test_cooldown_blocks_same_analyst_within_floor_minutes` — same analyst within 30 min blocked. **Passes** (`_analyst_blocked_within(floor_minutes)` final guard).
- `test_cooldown_falls_back_to_ticker_level_6h_when_disabled` — `enabled=false` → blanket. **Passes** (branch 1 unchanged).
- `test_high_conviction_base_score_bypasses_cooldown` — `base_score >= 30` bypasses. **Passes** (branch 2 unchanged).
- `test_floor_minutes_blocks_even_100pct_precision_analyst` — 100 % precision still floor-blocked. **Passes** (under new formula: precision=1.0 → weight=2.0 → cooldown=3 h, floor still enforced separately at 30 min). NB: the test asserts the *floor* still blocks; it does not assert the upstream cooldown value — so the change from "30 min" (legacy linear at 100 %) to "3 h" (this spec) does not affect the assertion.

Run: `python3 -m pytest tests/test_per_analyst_cooldown.py -v`.

### 4.2 New regression test (add — see TDD note at bottom)

Add `test_clamped_weight_formula` covering the three new boundary cases:

```python
async def test_clamped_weight_caps_low_precision_at_max_cap(test_db):
    """A 5%-precision analyst hits weight floor 0.5 → cooldown=12 h, capped under max=24 h."""
    cfg._config["alerts"]["per_analyst_cooldown"]["max_cooldown_hours"] = 24
    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO source_performance VALUES ('kpak82','1h',0.05,30,unixepoch())"
    )
    await conn.commit()
    await _insert_alert("NVDA", "kpak82", age_seconds=11*3600)   # 11 h ago, inside 12 h
    assert await db.check_alert_cooldown("NVDA", "kpak82", base_score=25) is False

    await _insert_alert("AAPL", "kpak82", age_seconds=13*3600)   # 13 h ago, outside 12 h
    assert await db.check_alert_cooldown("AAPL", "kpak82", base_score=25) is True


async def test_clamped_weight_high_precision_caps_at_three_hours(test_db):
    """A 100%-precision analyst → weight=2.0 (cap) → cooldown=3 h."""
    conn = await db.get_db()
    await conn.execute(
        "INSERT INTO source_performance VALUES ('TeresaTrades','1h',1.000,41,unixepoch())"
    )
    await conn.commit()
    await _insert_alert("AMD", "TeresaTrades", age_seconds=2*3600 + 30*60)   # 2.5 h ago
    assert await db.check_alert_cooldown("AMD", "TeresaTrades", base_score=25) is False

    await _insert_alert("INTC", "TeresaTrades", age_seconds=3*3600 + 5*60)   # 3.08 h ago
    assert await db.check_alert_cooldown("INTC", "TeresaTrades", base_score=25) is True


async def test_clamped_weight_cold_start_defaults_to_six_hours(test_db):
    """Analyst with no source_performance row (cold start) → weight=1.0 → cooldown=6 h."""
    await _insert_alert("TSLA", "newbie", age_seconds=5*3600)
    assert await db.check_alert_cooldown("TSLA", "newbie", base_score=25) is False
    await _insert_alert("MSFT", "newbie", age_seconds=7*3600)
    assert await db.check_alert_cooldown("MSFT", "newbie", base_score=25) is True
```

### 4.3 SQL verification probes (post-deploy on prod DB)

```sql
-- (a) Confirm a high-precision analyst (TeresaTrades) is no longer suppressed
-- after a low-precision analyst fired the same ticker.
SELECT a.ticker,
       a1.alerted_at AS kpak_at,
       a2.alerted_at AS teresa_at,
       (a2.alerted_at - a1.alerted_at)/3600.0 AS hours_apart
FROM alert_history a1
JOIN alert_history a2
  ON a1.ticker = a2.ticker
 AND a2.alerted_at > a1.alerted_at
WHERE a1.analyst_mentions LIKE '%"kpak82"%'
  AND a2.analyst_mentions LIKE '%"TeresaTrades"%'
  AND a1.alerted_at > strftime('%s','now','-7 days');
-- Expectation post-deploy: ≥1 row where 0.5 < hours_apart < 6  (TeresaTrades fired
-- INSIDE the legacy 6 h ticker block — the bug being fixed). Pre-deploy: 0 such rows.

-- (b) Per-ticker per-day alert volume must remain bounded.
SELECT ticker, date(alerted_at,'unixepoch') AS day, COUNT(*) AS alerts
FROM alert_history
WHERE alerted_at > strftime('%s','now','-14 days')
GROUP BY ticker, day
HAVING alerts > 10
ORDER BY alerts DESC;
-- Expectation: zero rows (per-ticker per-day alert count stays ≤ 10 — kept low by
-- floor_minutes=30 even for a 3 h-cap analyst → max 48 same-analyst alerts/day,
-- and aggregating across analysts for a viral ticker stays in single digits in practice).

-- (c) Cold-start analysts still cool 6 h.
SELECT a.analyst, a1.alerted_at, a2.alerted_at,
       (a2.alerted_at - a1.alerted_at)/3600.0 AS hours_apart
FROM alert_history a1, alert_history a2,
     (SELECT json_extract(analyst_mentions,'$[0]') AS analyst FROM alert_history) a
WHERE a1.ticker = a2.ticker
  AND a2.alerted_at > a1.alerted_at
  AND a1.analyst_mentions = a2.analyst_mentions
  AND NOT EXISTS (SELECT 1 FROM source_performance
                  WHERE entity_id = a.analyst AND horizon='1h' AND sample_count >= 5);
-- Expectation: every (a1,a2) pair has hours_apart >= 6.0 (cold-start path = 6 h cooldown).
```

### 4.4 Acceptance criteria

1. All 5 existing tests in `test_per_analyst_cooldown.py` GREEN.
2. The 3 new regression tests in §4.2 GREEN.
3. Probe (a) returns ≥1 row over a 7-day window (proof the previously-suppressed-confirming-tweet pattern is now alerting).
4. Probe (b) returns 0 rows (no ticker spam).
5. Probe (c) confirms cold-start = 6 h.
6. Telemetry: log a single line per alert decision: `cooldown_decision analyst=<a> precision=<p|None> weight=<w> cooldown_h=<x.xx> scaled_min=<n> blocked=<bool>` for 7 days post-deploy. Sample 100 random rows; precision/weight/cooldown_h must satisfy the formula in §2.2.

---

## 5. Out of scope (explicitly)

- **Schema migration to add `analyst_handle` column** — would let us replace the JSON-LIKE filter with an indexed equality. Future spec.
- **Sub-floor or per-analyst-floor** — out of scope. Floor remains a single global `floor_minutes` setting.
- **Removing the blanket-fallback path** — kept behind `enabled=false` flag for instant rollback.
- **Alternative scale factors (e.g. `precision * 1.5` or `precision^0.7`)** — out of scope. `precision * 2` is the audit's specified formula; tuning the multiplier belongs to a follow-up calibration spec.

---

## 6. Rollback

Single-config rollback to legacy ticker-level 6 h:

```yaml
alerts:
  per_analyst_cooldown:
    enabled: false
```

No code revert needed — branch 1 of the decision tree handles `enabled=false`.

---

## 7. TDD note

Per project TDD policy, write the §4.2 tests **first** (RED), then apply the §3.1 diff (GREEN). The existing 5 tests already pass under the current code, so they stay GREEN throughout — no churn.

---

## 8. Revision history

- **Initial draft (2026-04-24):** clamped-weight formula with `weight = clamp(precision, 0.5, 2.0)`. Surfaced doubling rescale as an optional flip.
- **Revised 2026-04-24 in response to Codex review:**
  - **(#1) Corrected formula** from `clamp(precision, 0.5, 2.0)` to `clamp(precision * 2, 0.5, 2.0)` to match the audit's worked examples (TeresaTrades 0.829 → cooldown 3.62 h; kpak82 0.143 → cooldown 12 h). The previous formula inverted the audit's intent: with `precision ∈ [0, 1]` the upper clamp at 2.0 was unreachable and high-precision analysts ended up with *longer* cooldowns than the 6 h baseline (e.g. 0.829 → 7.24 h). Section 2.2 (decision tree), §2.4 (worked examples), and §3.1 (diff) all updated; arithmetic verification of the four canonical examples added inline below the diff.
  - **(#2) Reframed §1.1 / §0.1 as tightening, not introduction.** The live `db.py:767-777` formula already shortens cooldown as precision rises (linear interpolation between `floor_minutes` and `cooldown_hours*60`). New §1.1a ("Comparison vs current live formula") quotes the live curve, tabulates it at the four canonical precision points, and explains the actual delta this spec introduces: (a) 24 h ceiling separating "known bad" from "unknown", (b) `precision * 2` doubled scale, and (c) concave `base/weight` shape replacing the linear curve.
  - **(#3) Mechanism for `None` precision:** chose the *refactor* arm — explicitly compute `weight = 1.0 if precision is None else clamp(precision * 2, 0.5, 2.0)` so all paths flow through the unified `cooldown_h = base / weight` derivation. Output is identical to the live code's separate `scaled_minutes = cooldown_hours * 60` arm (both produce 6 h baseline) but the mechanism is now uniform with the precision-known path. Documented in §2.3.
  - LOC delta unchanged at **+4 total** (`db.py` +3, `config/consensus.yaml` +1).
