# Implementation Plan: Vault + Atlas + Alfred

**Spec:** `docs/superpowers/specs/2026-04-21-vault-atlas-alfred-design.md`

## Context

Add persistent research memory and a morning briefing to OpenClaw. Three components: a markdown vault (derived artifact), Atlas (ticker research agent with durable work queue), and Alfred (Discord briefing agent with outbox). Approach A: integrated into the consensus engine alongside existing poll loops.

## Critical Files

- `consensus_engine/db.py` — add 3 new tables + 6 new functions
- `consensus_engine/main.py` — add 3 new loops to `asyncio.gather()`
- `config/consensus.yaml` — add `alfred`, `atlas`, `vault` config sections
- **New:** `consensus_engine/research/atlas.py`
- **New:** `consensus_engine/briefing/alfred.py`

## Steps

### 1. DB Schema (`consensus_engine/db.py`)

Add to `_SCHEMA` (alongside existing `CREATE TABLE IF NOT EXISTS` blocks):

```sql
research_jobs(id, ticker, reason, status, attempts, lease_expires_at, created_at, finished_at)
research_sections(ticker, source, content, last_good_content, fetched_at, last_good_at, status)
briefing_runs(session_key, session_start_utc, session_end_utc, rendered_content, discord_message_id, status, created_at, posted_at, archived_at)
```

Add functions:
- `enqueue_atlas_job(ticker, reason)` — coalesces if pending/running job exists
- `acquire_atlas_lease(lease_ttl)` → job dict or None
- `finish_atlas_job(job_id, status)`
- `upsert_research_section(ticker, source, content, status)` — preserves `last_good_content` on failure
- `get_research_sections(ticker)` → dict of source → section
- `get_briefing_run(session_key)` → dict or None
- `upsert_briefing_run(session_key, **fields)`
- `get_top_tickers_session(session_start_utc, session_end_utc, limit)` → list of tickers

### 2. Config (`config/consensus.yaml`)

Append:
```yaml
alfred:
  enabled: true
  post_window_et: ["08:50", "09:00"]
  market_holidays: []

atlas:
  enabled: true
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

### 3. Atlas (`consensus_engine/research/atlas.py`)

**Session helper** (reuse across atlas + alfred):
```python
from zoneinfo import ZoneInfo
ET = ZoneInfo('America/New_York')
def current_et_session() -> tuple[float, float, str]:
    """Returns (session_start_utc, session_end_utc, session_key YYYY-MM-DD)"""
```

**Source adapters** (each writes to `research_sections` independently):
- `fetch_analyst_section(ticker)` — query `ticker_signals` WHERE `source_type='twitter'` last 30d → LLM summary via existing `llm_scorer` pattern
- `fetch_sec_section(ticker)` — EDGAR API: 8-K Item 2.02, then 10-Q → LLM key metrics
- `fetch_news_section(ticker)` — SearXNG `:8888` `"TICKER" stock news` last 12h → LLM top-5 summary

**Worker:**
```python
async def atlas_worker_loop(stop_event):
    while not stop_event.is_set():
        job = await db.acquire_atlas_lease(cfg.get('atlas.lease_ttl_seconds', 1800))
        if job:
            await _process_job(job)
        else:
            await asyncio.sleep(30)
```

**Sweep trigger:**
```python
async def atlas_sweep_loop(stop_event):
    # Fires at sweep_time_et daily, enqueues top N tickers
```

**Markdown renderer:**
```python
def render_ticker_markdown(ticker, sections) -> str: ...
async def write_ticker_vault(ticker, sections, vault_path): ...
# Uses: tmp = vault_path + '.tmp'; write(tmp); os.replace(tmp, final)
```

**Public API for `db.py` alert hook:**
```python
async def enqueue_atlas_job(ticker: str, reason: str) -> None:
    await db.enqueue_atlas_job(ticker, reason)
```

Hook into `db.insert_alert()` — add at end: `asyncio.create_task(enqueue_atlas_job(ticker, 'alert'))` — note: task only enqueues into DB, never fetches directly, so it's safe and fast.

### 4. Alfred (`consensus_engine/briefing/alfred.py`)

**Session builder:**
```python
async def build_briefing_data(session_start_utc, session_end_utc) -> dict:
    # Queries: alert_history (alerted_at), youtube_levels, youtube_signals,
    #          youtube_macro, ticker_signals (top 5), research_sections (last-good)
```

**Outbox sender:**
```python
async def post_briefing(session_key, data, vault_path):
    run = await db.get_briefing_run(session_key)
    if run and run['status'] == 'archived': return  # already done

    if not run or run['status'] == 'pending':
        content = await _render_briefing(data)
        await db.upsert_briefing_run(session_key, rendered_content=content, status='pending')

    run = await db.get_briefing_run(session_key)
    if run['status'] == 'pending':
        msg_id = await _send_discord(run['rendered_content'])
        await db.upsert_briefing_run(session_key, discord_message_id=msg_id, status='posted')

    run = await db.get_briefing_run(session_key)
    if run['status'] == 'posted':
        await _write_vault_briefing(run, vault_path)
        await db.upsert_briefing_run(session_key, status='archived')
```

**Loop:**
```python
async def alfred_loop(stop_event):
    # Wakes every 60s; checks if current ET time is in post_window_et
    # Skips weekends + market_holidays
    # Calls post_briefing() for today's session_key
```

### 5. Wire into `main.py`

Add to the existing `asyncio.gather()` call:
```python
atlas_worker_loop(stop_event),
atlas_sweep_loop(stop_event),
alfred_loop(stop_event),
```

## Reuse Existing Code

- `consensus_engine/utils/http.py:get_session()` — for EDGAR and SearXNG HTTP calls
- `consensus_engine/analysis/llm_scorer.py` — LLM calls for section synthesis
- `_send_youtube_alert()` pattern in `consensus_engine/scanners/youtube.py` — Discord posting
- `consensus_engine/config.py:cfg.get()` — all config access
- `consensus_engine/utils/rate_limiter.py` — wrap EDGAR calls

## Verification

```bash
# 1. Test Atlas end-to-end
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

# 2. Verify research_sections (last_good_content preserved on failure)
python3 -m pytest tests/ -v -k 'atlas or research'

# 3. Test Alfred dry-run (no Discord post)
python3 -m consensus_engine --dry-run --once

# 4. Verify briefing_runs outbox state
python3 -m pytest tests/ -v -k 'alfred or briefing'

# 5. Full suite
python3 -m pytest tests/ -v
```
