# Spec 04 — YouTube Level Alert 24h Per-Ticker-Per-Price Dedup

**Audit reference:** `plans/AUDIT_RESEARCH_2026-04-24.md`
**Owner module:** `consensus_engine/main.py` + `consensus_engine/db.py`
**Status:** Implementation-ready. No source modifications performed in this spec.

---

## Section 1 — Investigation findings

### 1.1 Alert flow (`consensus_engine/main.py:404–451`)

`_check_youtube_level_alerts()` runs every `fetch_loop` cycle (default `interval=300s`, see `main.py:369–380`). Per cycle:

1. Pull DISTINCT tickers from `youtube_levels` extracted in the last 14 days (`main.py:411–414`).
2. For each ticker, fetch live price via `_fetch_yfinance_price` (`main.py:422`).
3. Pull all stored levels for that ticker via `db.get_youtube_levels_for_ticker(ticker, days=14)` (`main.py:425`).
4. For each level, if `abs(current_price - lv_price) / lv_price < proximity_pct` (default 0.005 = 0.5%, key `youtube.level_alert_proximity_pct`, `main.py:407,430`):
   - Call `db.was_level_recently_alerted(ticker, lv_price)` (`main.py:431`). On `False`, post to alerts channel and `db.record_level_alert(...)`.

### 1.2 `was_level_recently_alerted` — actual implementation

**File:line:** `consensus_engine/db.py:1782–1793`

```python
async def was_level_recently_alerted(ticker: str, price: float, cooldown_seconds: int = 14400) -> bool:
    """Return True if a level alert for this ticker/price was fired within cooldown window."""
    conn = await get_db()
    cutoff = time.time() - cooldown_seconds
    cursor = await conn.execute(
        """SELECT 1 FROM youtube_level_alerts
           WHERE ticker = ? AND ABS(price - ?) / ? < 0.01 AND alerted_at >= ?
           LIMIT 1""",
        (ticker, price, price, cutoff),
    )
    row = await cursor.fetchone()
    return row is not None
```

**Single caller**, default cooldown applied (`grep -rn was_level_recently_alerted` returns only `main.py:431` + the definition).

**Root cause of repeat alerts:** The query is structurally correct — it does enforce per-ticker-per-price uniqueness within ±1% — but `cooldown_seconds=14400` (4 hours) means a level resets ~6 times per day. With a 5-minute loop and a level that lingers in proximity, this yields the observed 5–7 fires per 24h per (ticker, level).

**The audit text frames this as "the SQL query is too permissive."** That's only partially right: the *time window* is too short. The price-band tolerance (±1%) is already tighter than the audit's recommended ±0.5% would be at the alert-trigger boundary, so the actual fix is **(a) lengthen the cooldown to 24h** and **(b) optionally tighten the price band from 1% to 0.5%** to match the proximity_pct entry-trigger so we don't accidentally cluster two different levels (e.g., $230 support and $232 resistance would currently be deduped as the same level under ±1%; under ±0.5% they would not).

### 1.3 Schema — `youtube_level_alerts`

**File:line:** `consensus_engine/db.py:302–311`

```sql
CREATE TABLE IF NOT EXISTS youtube_level_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    level_type TEXT NOT NULL,
    price REAL NOT NULL,
    channel_name TEXT,
    alerted_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yla_ticker ON youtube_level_alerts(ticker);
CREATE INDEX IF NOT EXISTS idx_yla_alerted ON youtube_level_alerts(alerted_at);
```

Two indexes already exist: `(ticker)` and `(alerted_at)`. **No composite index** on `(ticker, alerted_at)`. SQLite's planner can typically intersect single-column indexes effectively at this row volume (the table grows by ~25 rows/day per the audit), but a composite index is cheap insurance.

### 1.4 `near_price_dedup_pct=0.5` semantics

**Config:** `config/consensus.yaml:275` under the `youtube:` block.

**Python references** (`grep -rn near_price_dedup`):

- `consensus_engine/analysis/video_classifier.py:680–696` — function `_suppress_near_price_dedup(levels, pct_window=0.005)`.
- `video_classifier.py:785` — single call site, **uses the hardcoded default `0.005`**.

```python
def _suppress_near_price_dedup(
    levels: list[CandidateLevel], pct_window: float = 0.005
) -> None:
    """Within same ticker+level_type, mark duplicates within ±0.5% as suppressed."""
    by_key: dict[tuple[str, str], list[CandidateLevel]] = {}
    for lvl in levels:
        by_key.setdefault((lvl.ticker, lvl.level_type), []).append(lvl)
    for group in by_key.values():
        group.sort(key=lambda l: l.price)
        kept_prices: list[float] = []
        for lvl in group:
            if any(abs(lvl.price - kp) <= pct_window * max(kp, 1e-9)
                   for kp in kept_prices):
                lvl.suppressed = True
                lvl.suppression_reason = "near_price_dedup"
            else:
                kept_prices.append(lvl.price)
```

**Critical finding:** The `youtube.near_price_dedup_pct` config key is **dead code**. No Python reads it (`grep -rn 'youtube\.near_price_dedup_pct\|near_price_dedup_pct' consensus_engine/` returns zero hits in source). The function takes its `pct_window` from the function-default 0.005 only.

**Scope of `_suppress_near_price_dedup`:** intra-video (one classification pass). It collapses near-duplicate CandidateLevel rows extracted from a single video before they are stored. It is **not** the alert-time dedup. It is unrelated to the 76% repeat-alert problem.

---

## Section 2 — Fix 1: `was_level_recently_alerted` SQL tightening

### 2.1 Diff (anchor: `consensus_engine/db.py:1782–1793`)

**Before:**

```python
async def was_level_recently_alerted(ticker: str, price: float, cooldown_seconds: int = 14400) -> bool:
    """Return True if a level alert for this ticker/price was fired within cooldown window."""
    conn = await get_db()
    cutoff = time.time() - cooldown_seconds
    cursor = await conn.execute(
        """SELECT 1 FROM youtube_level_alerts
           WHERE ticker = ? AND ABS(price - ?) / ? < 0.01 AND alerted_at >= ?
           LIMIT 1""",
        (ticker, price, price, cutoff),
    )
    row = await cursor.fetchone()
    return row is not None
```

**After:**

```python
async def was_level_recently_alerted(ticker: str, price: float, cooldown_seconds: int = 86400) -> bool:
    """Return True if a level alert for this ticker/price was fired within cooldown window.

    Defaults: 24h cooldown, ±0.5% price band (matches youtube.level_alert_proximity_pct
    so the dedup window matches the trigger window). Empirically validated by the
    2026-04-24 signal audit, which observed 76% repeat alerts under the previous
    4h / ±1% configuration.
    """
    conn = await get_db()
    cutoff = time.time() - cooldown_seconds
    cursor = await conn.execute(
        """SELECT 1 FROM youtube_level_alerts
           WHERE ticker = ?
             AND ABS(price - ?) / NULLIF(?, 0) < 0.005
             AND alerted_at >= ?
           LIMIT 1""",
        (ticker, price, price, cutoff),
    )
    row = await cursor.fetchone()
    return row is not None
```

### 2.2 Changes summarized

| Change | Before | After | Rationale |
|---|---|---|---|
| `cooldown_seconds` default | `14400` (4h) | `86400` (24h) | Audit shows 4h yields ~6 fires/day per (ticker, level). 24h matches the human attention span — one alert per level per day. |
| Price-band tolerance | `< 0.01` (±1%) | `< 0.005` (±0.5%) | Match `youtube.level_alert_proximity_pct` (also 0.5%), so dedup band = trigger band. Prevents a $230 support and $232 resistance from being collapsed (both legitimate, different levels). |
| Divisor safety | bare `?` | `NULLIF(?, 0)` | Prevents a `ZeroDivisionError`-equivalent SQLite NULL when an upstream bug stores `price=0`. Caller already filters `lv_price=0` (`main.py:428`), but defense-in-depth costs nothing. |
| Docstring | terse | adds default rationale | Future maintainers see *why* 24h, not just the magic number. |

### 2.3 Index — keep existing, add composite (optional but recommended)

Existing indexes (`db.py:310–311`) cover `ticker` and `alerted_at` separately. The new query filters on both. Add a composite index:

```sql
CREATE INDEX IF NOT EXISTS idx_yla_ticker_alerted ON youtube_level_alerts(ticker, alerted_at);
```

**Insertion point:** `consensus_engine/db.py:311`, immediately after `idx_yla_alerted`. The existing single-column indexes can stay (SQLite ignores them when the composite is more selective; cost is one extra B-tree on a small table).

LOC delta: **+1 line in `db.py`** for the index, **±0 net** for the function (one-line SQL change, one-line default change, plus expanded docstring; treat as ~+8 / −2).

---

## Section 3 — Fix 2: `near_price_dedup_pct` retune

### 3.1 Recommendation: **DO NOT CHANGE**

The audit-suggested retune (0.5 → 1.0 / 1.5) is moot for this bug. Investigation findings:

1. The config key `youtube.near_price_dedup_pct` is **dead code**. No Python module reads it. Changing its value in YAML has zero runtime effect.
2. The function it would notionally control (`_suppress_near_price_dedup` in `analysis/video_classifier.py`) is **intra-video**, not alert-time. It deduplicates CandidateLevel rows produced by a single classification pass before storage — not alerts that fire from already-stored levels.
3. The 76% repeat-alert problem is entirely on the alert-time path (`was_level_recently_alerted`), already addressed by Fix 1.

### 3.2 Optional cleanup — orphan config key

Two acceptable paths; pick one and stick to it. Do **not** do both.

**Path A (preferred for this milestone): wire it up.**

Have `_suppress_near_price_dedup` read the config key and respect operator overrides. Change `analysis/video_classifier.py:785`:

```python
# Before
_suppress_near_price_dedup(levels)

# After
from consensus_engine.config import cfg  # if not already imported
_suppress_near_price_dedup(
    levels,
    pct_window=float(cfg.get("youtube.near_price_dedup_pct", 0.5)) / 100.0,
)
```

Note: the YAML stores the value as a percent (`0.5` meaning 0.5%), but the function expects a fraction (`0.005`). Divide by 100 at the boundary.

**Path B (if not wiring): delete the orphan key.**

Remove `config/consensus.yaml:275` entirely so it doesn't mislead future operators into thinking it does something.

**This spec recommends Path A** — it's a 3-line change that closes a documented config knob without altering current behavior (the default 0.5 matches the existing hardcoded 0.005 fraction). Mark this as a follow-up; it is **not blocking** for the dedup fix.

LOC delta if Path A is taken: **+3 / −1 in `video_classifier.py`**, **0 in YAML**.

---

## Section 4 — Verification

### 4.1 Pre-deploy sanity (current state — should show repeats)

```sql
SELECT ticker || '-' || ROUND(price, 2) AS key,
       COUNT(*) AS fires
FROM youtube_level_alerts
WHERE alerted_at > strftime('%s', 'now', '-1 day')
GROUP BY 1
HAVING COUNT(*) > 1
ORDER BY fires DESC;
```

Expected (matches audit): rows for `TALK-5.17` (7), `XLK-158.00` (7), `SMH-482.50` (5), `BE-230.00` (3).

### 4.2 Post-deploy validation (after Fix 1 has been live ≥24h)

Run the same query. **Pass condition:** zero rows returned, or at most 1–2 rows where `fires=2` (acceptable boundary noise from prices straddling the ±0.5% band at the start vs end of day).

### 4.3 Unit-test sketch (optional, not required by audit)

`tests/test_db_level_dedup.py`:

```python
async def test_dedup_24h_window():
    await db.record_level_alert("FOO", "support", 100.0, "ch")
    assert await db.was_level_recently_alerted("FOO", 100.0) is True
    # Same price 23h later → still suppressed
    # Same price 25h later → allowed
    # Different price (>0.5% away) → allowed immediately
```

(Time mocking via `freezegun` or by passing `cooldown_seconds=` overrides.)

### 4.4 Operational rollback

Setting the cooldown back to 14400 (or below) restores legacy behavior. No schema migration required — the table layout, the column types, and the row format are unchanged. The only thing that changes is the WHERE clause in one query and a default-arg integer.

---

## Section 5 — LOC delta summary

| File | Change | Adds | Deletes |
|---|---|---|---|
| `consensus_engine/db.py` | `was_level_recently_alerted` body + docstring + index | ~+10 | ~−3 |
| `consensus_engine/db.py` | `idx_yla_ticker_alerted` composite index | +1 | 0 |
| `consensus_engine/analysis/video_classifier.py` | (optional Path A) wire `near_price_dedup_pct` config | +3 | −1 |
| `config/consensus.yaml` | unchanged | 0 | 0 |
| **Total (required only)** | | **~+11** | **~−3** |
| **Total (with optional Path A)** | | **~+14** | **~−4** |

No new files. No schema migration. Backward-compatible at the data-layer level (existing `youtube_level_alerts` rows remain valid; the stricter query simply suppresses more of them).
