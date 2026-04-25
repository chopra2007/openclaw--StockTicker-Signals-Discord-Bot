# Milestone 0 — Spec 02: Phase-2 Drop Fix (Bug A + Bug B)

**Audit reference:** `plans/AUDIT_RESEARCH_2026-04-24.md` — Q2, lines 24, 57–59, 215, 249, 295.
**Status at spec time (2026-04-24):** Both bugs already have working fixes in tree. This spec documents the **delta still required** — primarily a structured WARN log line that the audit-suggested implementation calls for but that the in-tree fix does not yet emit in the exact form. No source files are modified by this spec.

---

## Files Touched

| File | Change | Status |
|------|--------|--------|
| `consensus_engine/main.py` | Tighten WARN log format on Phase-2 timeout (Bug A) | **Edit** (~1 line) |
| `consensus_engine/db.py` | Tweet-only dual-write into `signal_events` (Bug B) | **Already landed** — no change |
| `consensus_engine/cross_reference.py` | None — read of `signal_events` is correct once Bug B writes flow | **Read-only** |

**LOC delta total: +1 / −1 (one log-line replacement).** Everything else is verification only.

---

## Bug A — Phase-2 Timeout Wrap

### Rationale (audit citation)
> "78.4% Phase-2 orphan rate ... `main.py:655–701` uses `asyncio.create_task(...)` without `asyncio.wait_for`; `cfg.intervals.cross_reference_timeout=120` is declared at `config/consensus.yaml:88` but never consumed at the call site." — `AUDIT_RESEARCH_2026-04-24.md:59`, Q2 (line 24).

### Verify findings — current code state

`consensus_engine/main.py:656–702` (function `_run_cross_reference_and_followup`) — verified by direct read on 2026-04-24:

- **Line 665:** `xref_task = asyncio.create_task(cross_reference(ticker, tweet))` — task created.
- **Line 672:** `timeout_sec = cfg.get("intervals.cross_reference_timeout", 120)` — config value **is consumed**.
- **Line 676:** `xref = await asyncio.wait_for(asyncio.shield(xref_task), timeout=timeout_sec)` — `wait_for` **is applied** (with `shield` so the underlying task survives, allowing `precision_task` to be awaited cleanly afterward).
- **Lines 677–679:** `except asyncio.TimeoutError:` sets `xref_timed_out = True` and emits `log.warning("Phase-2 xref timed out after %ss for $%s", timeout_sec, ticker)`.
- **Lines 694–696:** when `xref_timed_out`, calls `await edit_instant_ping(instant_msg_id, "Phase 2 skipped — timeout")` and returns.

**Conclusion:** the audit's snapshot of the bug (no `wait_for`, no Discord edit, no log) is **stale**. A Q2 hotfix has already shipped. The only remaining gap is the WARN log message format. The audit spec calls for a structured line of the form:

    Phase 2 skipped — timeout after {timeout_sec}s for ticker={ticker}

The current line reads:

    Phase-2 xref timed out after 120s for $AAPL

The current line is human-readable but lacks the `ticker=` key the spec calls for (machine-grep friendly) and uses different verbiage than the user-facing Discord edit (`"Phase 2 skipped — timeout"`). For grep-parity with the Discord edit and the audit's metric query, normalise to the spec phrasing.

### Diff

`consensus_engine/main.py` line 679 (only):

```diff
@@ consensus_engine/main.py: _run_cross_reference_and_followup
 676             xref = await asyncio.wait_for(asyncio.shield(xref_task), timeout=timeout_sec)
 677         except asyncio.TimeoutError:
 678             xref_timed_out = True
-679             log.warning("Phase-2 xref timed out after %ss for $%s", timeout_sec, ticker)
+679             log.warning("Phase 2 skipped — timeout after %ss for ticker=%s", timeout_sec, ticker)
 680         except Exception as e:
 681             log.error("Phase-2 xref failed for $%s: %s", ticker, e)
```

No other lines in `_run_cross_reference_and_followup` (656–739) require changes.

### Test / sanity check

1. **Unit (smoke):** force `cross_reference` to sleep > `timeout_sec` (monkeypatch). Assert:
   - `edit_instant_ping` was awaited with `"Phase 2 skipped — timeout"`.
   - `log.warning` captured the new format string with `ticker=<TICKER>` substring.
   - `precision_task` is still awaitable (not cancelled) — proves `asyncio.shield` is doing its job.
2. **Empirical (post-deploy, 24 h soak):**
   ```sql
   SELECT COUNT(*) FROM alert_messages
   WHERE followup_msg_id IS NULL
     AND created_at < strftime('%s','now','-1 day');
   ```
   Should drop materially below the 78.4% baseline — every timeout now produces a message edit, so any remaining `NULL followup_msg_id` rows are legitimate `SignalClass.IGNORE` precision skips, not silent drops.
3. **Log grep:** `grep "Phase 2 skipped — timeout" logs/consensus.log` should produce one line per timed-out alert; the count should match the delta between `alert_messages` rows and successful `send_detail_followup` calls.

---

## Bug B — `signal_events` Dual-Write

### Rationale (audit citation)
> "`cross_reference.py:333` reads from `signal_events` which has 23 rows ever, all from one YouTube video (`4mSyMr8PGLI`); tweets write to `ticker_signals` (252 rows) and are effectively invisible to the xref's canonical query." — `AUDIT_RESEARCH_2026-04-24.md:24, 57`.
> Approach (a) per spec: dual-write into `signal_events` in the tweet insertion path. Do **not** retarget `cross_reference.py:333` to `ticker_signals` — 764K ApeWisdom rows would require complex source filtering.

### Verify findings — current code state

**1. `signal_events` schema** — `consensus_engine/db.py:228–242`:

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_detail TEXT,
    ticker TEXT NOT NULL,
    direction TEXT,
    quality_score REAL DEFAULT 0.5,
    latency_sec REAL,
    provenance TEXT,
    model_version TEXT,
    recorded_at REAL NOT NULL
);
```

Existing helper `record_signal_event(...)` at `db.py:1811–1832`. (Used by YouTube path; not used by tweet path.)

**2. Tweet `ticker_signals` insertion path** — `consensus_engine/db.py:578–619`, function `insert_signal(signal: TickerSignal)`. Tweet call sites:
- `main.py:170, 208, 244` — TweetShift Discord-gateway tweet ingest (three retweet/quote/original branches).
- `main.py:585, 601` — `process_tweet` non-actionable + actionable paths.
- `alerts/commands.py:662` — manual `/signal` slash command.

**3. ApeWisdom path — confirmed isolated.** Grep results:
- `scanners/social.py:203` — ApeWisdom scanner builds a `list[TickerSignal]` with `source_type=SourceType.APEWISDOM` and writes via `db.insert_signals(...)` (plural, batch helper at `db.py:622–637`).
- `scanners/social.py:92` — Reddit scanner uses `SourceType.REDDIT`, also batch path.
- The dual-write logic lives **inside `insert_signal` (singular)** at `db.py:594–618` and is gated on `if signal.source_type == SourceType.TWITTER`. The plural `insert_signals` does **not** dual-write at all.

**Therefore ApeWisdom is doubly safe:** (a) it goes through `insert_signals`, not `insert_signal`; and (b) even if it ever called `insert_signal`, the `SourceType.TWITTER` guard would skip it.

**4. The dual-write is already in tree** — `db.py:594–618`, comment-tagged `# Q2b: route tweet signals into signal_events so cross_reference scoring can see them.`

```python
if signal.source_type == SourceType.TWITTER:
    direction = (
        "long" if signal.sentiment == Sentiment.BULLISH
        else "short" if signal.sentiment == Sentiment.BEARISH
        else None
    )
    await db.execute(
        """INSERT INTO signal_events
           (source_type, source_detail, ticker, direction, quality_score,
            latency_sec, provenance, model_version, recorded_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "twitter",
            signal.source_detail,         # analyst handle
            signal.ticker,
            direction,                    # bull/bear → long/short
            0.5,                          # placeholder; M3 will replace per-analyst
            None,                         # latency_sec (n/a)
            "tweet",                      # provenance
            None,                         # model_version
            signal.detected_at,           # recorded_at
        ),
    )
```

**5. The xref read** — `cross_reference.py:326–333` (after `cache_xref(...)`):

```python
# Q2b: always-on signal_events read so tweet rows (now routed via insert_signal)
# reach a consumer after KILL 3 removed the reliability_engine guarded read.
try:
    signal_events = await db.get_signal_events_for_ticker(ticker, window_seconds=3600)
    log.debug("cross_reference $%s: signal_events in 1h window=%d", ticker, len(signal_events))
except Exception as exc:  # pragma: no cover
    log.warning("cross_reference: signal_events read failed for $%s: %s", ticker, exc)
```

The reader **is in place** and now sees tweet rows. The `signal_events` count will grow with every tweet ingested.

### Diff

**No code change required.** The dual-write is already merged at `db.py:594–618`. This section is verification-only.

For an implementer arriving without history, the equivalent diff that produced the current state was:

```diff
@@ consensus_engine/db.py: insert_signal
 578 async def insert_signal(signal: TickerSignal):
 579     """Insert a ticker signal into the database."""
 580     db = await get_db()
 581     await db.execute(
 582         """INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at)
 583            VALUES (?, ?, ?, ?, ?, ?, ?)""",
 584         (
 585             signal.ticker,
 586             signal.source_type.value,
 587             signal.source_detail,
 588             signal.raw_text[:2000],
 589             signal.sentiment.value,
 590             signal.detected_at,
 591             signal.expires_at,
 592         ),
 593     )
+594     # Q2b: route tweet signals into signal_events so cross_reference scoring can see them.
+595     # M3 will replace the 0.5 placeholder with per-analyst precision.
+596     if signal.source_type == SourceType.TWITTER:
+597         direction = (
+598             "long" if signal.sentiment == Sentiment.BULLISH
+599             else "short" if signal.sentiment == Sentiment.BEARISH
+600             else None
+601         )
+602         await db.execute(
+603             """INSERT INTO signal_events
+604                (source_type, source_detail, ticker, direction, quality_score,
+605                 latency_sec, provenance, model_version, recorded_at)
+606                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
+607             (
+608                 "twitter",
+609                 signal.source_detail,
+610                 signal.ticker,
+611                 direction,
+612                 0.5,
+613                 None,
+614                 "tweet",
+615                 None,
+616                 signal.detected_at,
+617             ),
+618         )
 619     await db.commit()
```

**Why ApeWisdom is not affected:** ApeWisdom uses `db.insert_signals(...)` (plural batch path at `db.py:622–637`), not `db.insert_signal(...)` (singular). The dual-write block lives inside the singular path **and** is gated on `SourceType.TWITTER` — so even if a future caller routes ApeWisdom rows through the singular helper, the type check excludes them. The 764K-row pollution scenario described in the spec brief is structurally impossible.

### Test / sanity check

Run **before deploy** (baseline):
```sql
SELECT COUNT(*) FROM signal_events WHERE source_type='twitter';   -- expect 0 or near-0
SELECT COUNT(*) FROM signal_events WHERE source_type='apewisdom'; -- expect 0
SELECT COUNT(*) FROM signal_events;                                -- expect ≈23
```

Run **24 h after deploy**:
```sql
SELECT COUNT(*) FROM signal_events WHERE source_type='twitter';   -- expect > 0, growing daily
SELECT COUNT(*) FROM signal_events WHERE source_type='apewisdom'; -- expect STILL 0  (sentinel)
SELECT source_type, COUNT(*) FROM signal_events GROUP BY source_type;
```

**Pass criteria:**
- `twitter` count grows by roughly the daily tweet-with-ticker volume (compare against `SELECT COUNT(*) FROM ticker_signals WHERE source_type='twitter' AND detected_at > strftime('%s','now','-1 day')`; counts should track 1:1).
- `apewisdom` count remains 0 — proves the gate is correct.
- `cross_reference` debug log: `cross_reference $TICKER: signal_events in 1h window=N` where N > 0 for active tickers — proves the reader sees the new rows.

**Fail criteria (revert):**
- `apewisdom` source_type appears in `signal_events` → gate broken.
- `signal_events` row growth > 10× tweet ingest → unintended call site.

---

## LOC Delta

| File | Lines added | Lines removed | Net |
|------|-------------|---------------|-----|
| `consensus_engine/main.py` | 1 | 1 | 0 |
| `consensus_engine/db.py` | 0 (already landed) | 0 | 0 |
| `consensus_engine/cross_reference.py` | 0 (read-only) | 0 | 0 |
| **Total** | **1** | **1** | **0** |

This is the minimal-diff close-out for Q2. The substantive code work has already shipped; this spec captures one log-format normalisation and the verification harness needed to declare Q2 done.
