# Vault + Atlas + Alfred Design

**Date:** 2026-04-21
**Status:** Approved (post-adversarial review)

## Context

OpenClaw generates real-time stock signals but has no persistent research memory. Every alert is evaluated in isolation — there's no accumulated knowledge about a ticker's fundamentals, earnings history, or analyst track record. This design adds three integrated components:

1. **Vault** — local markdown files auto-generated as a derived view from structured DB records
2. **Atlas** — a research agent with a durable work queue that gathers fundamentals, news, and analyst signals per ticker
3. **Alfred** — a morning briefing agent with a transactional outbox that posts to Discord and archives to vault

## Architecture

### Pipeline

```
8:00 AM ET   →  Atlas sweep: enqueue top tickers from yesterday
                  Worker drains queue with per-ticker leases
                  Each source writes its own section independently:
                    ├── TweetShift analyst signals (DB: ticker_signals)
                    ├── SEC/earnings (EDGAR API)
                    └── News (SearXNG :8888)
                  Markdown rendered from DB sections via atomic rename
                  → vault/tickers/TICKER.md (derived artifact)

8:50 AM ET   →  Alfred: reads last-good research_sections + DB data
                  → LLM synthesizes coherent brief
                  → persists to briefing_runs (pending)
                  → posts to Discord → marks briefing_runs (posted)
                  → archives to vault/macro/briefings/YYYY-MM-DD.md
                  → marks briefing_runs (archived)

On alert fire →  Enqueues ticker refresh request into research_jobs
                  Worker picks it up with per-ticker lease
                  → same section-write flow as sweep
```

---

## 1. Vault

**Location:** `/root/.openclaw/vault/` (outside repo, persists independently)

```
vault/
  tickers/          # Derived markdown from research_sections — DO NOT edit manually
    NVDA.md
    AAPL.md
  macro/
    briefings/      # Derived from briefing_runs — DO NOT edit manually
      2026-04-21.md
```

Markdown files are **derived artifacts**, not the source of truth. The DB tables (`research_sections`, `briefing_runs`) are canonical. Files are regenerated via atomic temp-file → rename to prevent partial writes.

### Ticker Note Structure (`vault/tickers/TICKER.md`)

```markdown
# TICKER Research Note
Generated: YYYY-MM-DD HH:MM ET  |  Sources: analyst ✓  sec ✓  news ✓

## Analyst Signals (TweetShift)
[30-day summary from research_sections where source='analyst']

## Earnings & SEC
[From research_sections where source='sec']

## News (last 12h)
[From research_sections where source='news']
```

Each section header shows whether the source succeeded or was last-good from a previous run.

---

## 2. DB Schema Additions

### `research_jobs`
```sql
CREATE TABLE IF NOT EXISTS research_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    reason TEXT NOT NULL,          -- 'alert' or 'sweep'
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_expires_at REAL,         -- epoch; NULL = not leased
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_research_jobs_ticker_status ON research_jobs(ticker, status);
```

### `research_sections`
```sql
CREATE TABLE IF NOT EXISTS research_sections (
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'analyst' | 'sec' | 'news'
    content TEXT,                  -- current content (NULL if last run failed)
    last_good_content TEXT,        -- preserved from last successful fetch
    fetched_at REAL,
    last_good_at REAL,
    status TEXT,                   -- 'ok' | 'failed' | 'skipped'
    PRIMARY KEY (ticker, source)
);
```

### `briefing_runs`
```sql
CREATE TABLE IF NOT EXISTS briefing_runs (
    session_key TEXT PRIMARY KEY,  -- YYYY-MM-DD (trading day)
    session_start_utc REAL NOT NULL,
    session_end_utc REAL NOT NULL,
    rendered_content TEXT,         -- full briefing text, stored before posting
    discord_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | posted | archived | failed
    created_at REAL NOT NULL,
    posted_at REAL,
    archived_at REAL
);
```

---

## 3. Atlas (`consensus_engine/research/atlas.py`)

### Job Queue Architecture

A single `atlas_worker_loop()` drains `research_jobs` with per-ticker leases (30-min TTL). This prevents concurrent runs for the same ticker regardless of whether the trigger was an alert or the sweep.

```python
# Coalescing: if a pending/running job exists for ticker, skip enqueue
# Lease: UPDATE research_jobs SET status='running', lease_expires_at=now()+1800
#        WHERE ticker=? AND status='pending' AND (lease_expires_at IS NULL OR lease_expires_at < now())
```

### Triggers

**Scheduled sweep (8:00 AM ET Mon–Fri):**
- Compute previous trading session via `zoneinfo.ZoneInfo('America/New_York')`
- Query top N tickers by signal count from that session
- Enqueue each as `reason='sweep'` if no fresh job exists (< 7 days since `research_sections` last updated)

**On alert (non-blocking):**
- `insert_alert()` in `db.py` calls `enqueue_atlas_job(ticker, reason='alert')`
- Job is coalesced if a pending/running job already exists for that ticker
- Does not block the alert pipeline

### Source Adapters

Each source writes independently to `research_sections`. A failed source preserves `last_good_content` and sets `status='failed'` — it never erases a previously successful section.

| Source | Implementation |
|---|---|
| `analyst` | Query `ticker_signals` WHERE `source_type='twitter'`, last 30d → LLM summary |
| `sec` | EDGAR full-text: 8-K Item 2.02, then 10-Q/10-K → LLM key metrics |
| `news` | SearXNG `:8888` query `"TICKER" stock news` last 12h → LLM top-5 summary |

After all three sections are written, render markdown via atomic temp-file → rename.

### Staleness

Skip section fetch if `last_good_at > now() - cache_days * 86400` (configurable per source). On-alert runs always refresh `analyst` section regardless of freshness.

---

## 4. Alfred (`consensus_engine/briefing/alfred.py`)

### Session Boundaries

Alfred uses explicit ET session boundaries — not `lookback_hours` heuristics:

```python
from zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')
# session_key = today's trading date in ET
# session_start = previous trading day 4:00 PM ET → UTC
# session_end = today 4:00 PM ET → UTC (or now if before close)
```

Skips weekends and US market holidays (configurable holiday list in `config/consensus.yaml`).

### Data Sources

| Section | Query |
|---|---|
| Overnight alerts | `alert_history` WHERE `alerted_at` BETWEEN `session_start_utc` AND `session_end_utc` |
| Open price levels | `youtube_levels` WHERE not triggered, last 14d |
| YouTube signals | `youtube_signals` WHERE `conviction='high'` AND `direction != 'neutral'`, last 7d — includes thesis text |
| Macro regime | Latest `youtube_macro` entry |
| Top tickers | Top 5 by signal count last 24h + `research_sections` last-good content |

### Outbox State Machine

```
pending → posted → archived
           ↓
         failed (retryable)
```

1. Render briefing text → write to `briefing_runs(session_key, rendered_content, status='pending')`
2. POST to Discord → on success: update `discord_message_id`, `status='posted'`, `posted_at`
3. Write `vault/macro/briefings/YYYY-MM-DD.md` → update `status='archived'`, `archived_at`

On restart, Alfred checks for `status='pending'` or `status='posted'` rows and resumes from the correct step. This prevents double-posts and missed briefs across crashes.

### Schedule

`alfred_loop()` wakes every 60s between 8:45–9:05 AM ET. Posts if session has no `briefing_runs` row or row is in a retryable state. Uses existing Discord bot helper.

---

## 5. Config (`config/consensus.yaml`)

```yaml
alfred:
  enabled: false                       # flip to true after a manual dry-run
  channel_id: "$DISCORD_BRIEFING_CHANNEL_ID"  # dedicated briefings channel (separate from alerts)
  post_window_et: ["08:50", "09:00"]
  market_holidays: []                  # list of YYYY-MM-DD strings to skip

atlas:
  enabled: false                       # flip to true after verifying a single ticker e2e
  cache_days: 7
  max_tickers_sweep: 10
  sweep_time_et: "08:00"
  lease_ttl_seconds: 1800
  sources:
    analyst: true
    sec: true
    news: true

vault:
  path: "/root/.openclaw/vault"
```

Add a matching entry to `api_keys`:

```yaml
api_keys:
  ...
  discord_briefing_channel_id: "$DISCORD_BRIEFING_CHANNEL_ID"  # Alfred briefings target
```

**LLM usage:** Atlas source-summary calls and Alfred brief synthesis reuse the existing `llm_scorer` helper (OpenRouter text model already configured under `api_keys.openrouter`). No new model config is introduced.

---

## 6. Modified Files

| File | Change |
|---|---|
| `consensus_engine/db.py` | Add `research_jobs`, `research_sections`, `briefing_runs` tables; `enqueue_atlas_job()`, `acquire_atlas_lease()`, `upsert_research_section()`, `get_briefing_run()`, `upsert_briefing_run()`, `get_top_tickers_session()` |
| `consensus_engine/main.py` | Add `alfred_loop()`, `atlas_sweep_loop()`, `atlas_worker_loop()` to `asyncio.gather()` |
| `config/consensus.yaml` | Add `alfred`, `atlas`, `vault` sections |

## 7. New Files

| File | Purpose |
|---|---|
| `consensus_engine/research/__init__.py` | Package |
| `consensus_engine/research/atlas.py` | Job queue worker, source adapters, markdown renderer |
| `consensus_engine/briefing/__init__.py` | Package |
| `consensus_engine/briefing/alfred.py` | Session builder, outbox sender, vault archiver |

---

## 8. Verification

```bash
# Test Atlas: enqueue and drain one ticker
python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('/root/.openclaw/.env')
from consensus_engine.research.atlas import enqueue_atlas_job, run_one_job
async def main():
    await enqueue_atlas_job('NVDA', 'manual')
    await run_one_job()
asyncio.run(main())
"
cat /root/.openclaw/vault/tickers/NVDA.md

# Verify research_sections written correctly
python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('/root/.openclaw/.env')
from consensus_engine import db
async def main():
    await db.init_db()
    conn = await db.get_db()
    rows = await (await conn.execute('SELECT ticker, source, status, last_good_at FROM research_sections WHERE ticker=?', ('NVDA',))).fetchall()
    for r in rows: print(dict(r))
asyncio.run(main())
"

# Test Alfred dry-run
python3 -m consensus_engine --dry-run --once

# Verify briefing_runs outbox
python3 -c "
import asyncio, sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('/root/.openclaw/.env')
from consensus_engine import db
async def main():
    await db.init_db()
    conn = await db.get_db()
    rows = await (await conn.execute('SELECT * FROM briefing_runs ORDER BY created_at DESC LIMIT 3')).fetchall()
    for r in rows: print(dict(r))
asyncio.run(main())
"

# Run tests
python3 -m pytest tests/ -v -k 'atlas or alfred or research or briefing'
```
