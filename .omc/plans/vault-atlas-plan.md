# Vault + Atlas + Alfred Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent research memory (`Vault`), a ticker research worker (`Atlas`), and a morning Discord briefing (`Alfred`) to OpenClaw's consensus engine.

**Architecture:** Three new concerns wired into the existing `asyncio.gather()` live loop in `consensus_engine/main.py`. Three new DB tables own state (`research_jobs`, `research_sections`, `briefing_runs`). Markdown files under `/root/.openclaw/vault/` are derived artifacts written via atomic rename. Atlas drains a leased job queue; each source writes its section independently, preserving `last_good_content` on failure. Alfred runs a pending→posted→archived outbox to prevent duplicate posts across crashes.

**Tech Stack:** Python 3, asyncio, aiosqlite-style wrapper (`consensus_engine.db.AsyncConnection`), aiohttp, OpenRouter (via `consensus_engine/analysis/llm_scorer.py`), Discord HTTP API, SearXNG (`:8888`), SEC EDGAR (`data.sec.gov`), pytest with `asyncio_mode=auto`.

**Spec:** `.omc/plans/vault-atlas-spec.md` (canonical copy at `docs/superpowers/specs/2026-04-21-vault-atlas-alfred-design.md`)

**Team topology (lanes):**
- **Lane 1 — DB + Config** (blocks Lanes 2 & 3): Tasks 1–6
- **Lane 2 — Atlas** (after Lane 1): Tasks 7–14
- **Lane 3 — Alfred** (after Lane 1, parallel with Lane 2): Tasks 15–20
- **Lane 4 — Wire-up + Verify** (after Lanes 2 & 3): Tasks 21–23

**Conventions:**
- All DB calls go through `consensus_engine.db` helpers — no inline SQL outside `db.py`.
- All config via `cfg.get("dot.path", default)`.
- LLM calls reuse the OpenRouter/model config used by `analysis/llm_scorer.py` (`llm.model`, default `minimax/minimax-m2.5`).
- Tests live under `tests/`; run with `python3 -m pytest tests/ -v -k 'atlas or alfred or research or briefing or vault'`.
- `pytest.ini` already has `asyncio_mode = auto` — tests can be plain `async def test_*`.
- Commit after each task. Commit style: imperative ("Add research_jobs schema").

---

## Lane 1 — DB + Config

### Task 1: Add schema for `research_jobs`, `research_sections`, `briefing_runs`

**Files:**
- Modify: `consensus_engine/db.py` (append to `SCHEMA` string)
- Test: `tests/test_research_schema.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_schema.py
import pytest
from consensus_engine import db


async def test_research_tables_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("consensus_engine.db.DB_PATH", str(tmp_path / "t.db"), raising=False)
    # Force re-init
    import consensus_engine.db as dbmod
    dbmod._db = None
    await dbmod.init_db()
    conn = await dbmod.get_db()
    cur = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('research_jobs','research_sections','briefing_runs')"
    )
    rows = await cur.fetchall()
    names = sorted(r["name"] for r in rows)
    assert names == ["briefing_runs", "research_jobs", "research_sections"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_research_schema.py -v
```
Expected: FAIL — tables don't exist yet.

- [ ] **Step 3: Append schema in `consensus_engine/db.py`**

Find the `SCHEMA = """..."""` string (starts near line 74). Append these three blocks inside it, before the closing `"""`:

```sql
CREATE TABLE IF NOT EXISTS research_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_expires_at REAL,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_research_jobs_ticker_status ON research_jobs(ticker, status);
CREATE INDEX IF NOT EXISTS idx_research_jobs_status ON research_jobs(status);

CREATE TABLE IF NOT EXISTS research_sections (
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT,
    last_good_content TEXT,
    fetched_at REAL,
    last_good_at REAL,
    status TEXT,
    PRIMARY KEY (ticker, source)
);

CREATE TABLE IF NOT EXISTS briefing_runs (
    session_key TEXT PRIMARY KEY,
    session_start_utc REAL NOT NULL,
    session_end_utc REAL NOT NULL,
    rendered_content TEXT,
    discord_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    posted_at REAL,
    archived_at REAL
);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_research_schema.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/db.py tests/test_research_schema.py
git commit -m "Add research_jobs, research_sections, briefing_runs schema"
```

---

### Task 2: Atlas job queue helpers

**Files:**
- Modify: `consensus_engine/db.py` (append helper functions near the other alert/signal helpers, end of file area is fine)
- Test: `tests/test_atlas_queue.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_atlas_queue.py
import time
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_enqueue_creates_pending_job():
    job_id = await db.enqueue_atlas_job("NVDA", "sweep")
    assert job_id is not None
    conn = await db.get_db()
    cur = await conn.execute("SELECT * FROM research_jobs WHERE id=?", (job_id,))
    row = await cur.fetchone()
    assert row["ticker"] == "NVDA"
    assert row["status"] == "pending"
    assert row["reason"] == "sweep"


async def test_enqueue_coalesces_pending():
    first = await db.enqueue_atlas_job("NVDA", "sweep")
    second = await db.enqueue_atlas_job("NVDA", "alert")
    assert second is None  # coalesced
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM research_jobs WHERE ticker='NVDA' AND status='pending'"
    )
    assert (await cur.fetchone())["c"] == 1


async def test_acquire_lease_returns_job_and_marks_running():
    await db.enqueue_atlas_job("AAPL", "sweep")
    job = await db.acquire_atlas_lease(1800)
    assert job is not None
    assert job["ticker"] == "AAPL"
    assert job["status"] == "running"
    # Second acquire gets nothing (lease held)
    job2 = await db.acquire_atlas_lease(1800)
    assert job2 is None


async def test_expired_lease_is_reacquirable():
    await db.enqueue_atlas_job("TSLA", "sweep")
    job = await db.acquire_atlas_lease(1800)
    # Manually expire the lease
    conn = await db.get_db()
    await conn.execute(
        "UPDATE research_jobs SET lease_expires_at=? WHERE id=?",
        (time.time() - 60, job["id"]),
    )
    await conn.commit()
    job2 = await db.acquire_atlas_lease(1800)
    assert job2 is not None
    assert job2["id"] == job["id"]


async def test_finish_atlas_job_sets_done():
    await db.enqueue_atlas_job("MSFT", "sweep")
    job = await db.acquire_atlas_lease(1800)
    await db.finish_atlas_job(job["id"], "done")
    conn = await db.get_db()
    cur = await conn.execute("SELECT status, finished_at FROM research_jobs WHERE id=?", (job["id"],))
    row = await cur.fetchone()
    assert row["status"] == "done"
    assert row["finished_at"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_atlas_queue.py -v
```
Expected: FAIL — helpers don't exist.

- [ ] **Step 3: Implement helpers in `consensus_engine/db.py`**

Append near the end of `db.py` (before any `if __name__` guard; the file currently has function definitions through ~line 1300):

```python
async def enqueue_atlas_job(ticker: str, reason: str) -> int | None:
    """Enqueue a research job. Coalesces: returns None if a pending/running
    job for this ticker already exists.
    """
    conn = await get_db()
    cur = await conn.execute(
        "SELECT id FROM research_jobs WHERE ticker=? AND status IN ('pending','running')",
        (ticker.upper(),),
    )
    if await cur.fetchone():
        return None
    cur = await conn.execute(
        """INSERT INTO research_jobs (ticker, reason, status, attempts, created_at)
           VALUES (?, ?, 'pending', 0, ?)""",
        (ticker.upper(), reason, time.time()),
    )
    await conn.commit()
    return cur.lastrowid


async def acquire_atlas_lease(lease_ttl: float) -> dict | None:
    """Claim the oldest pending job (or one whose lease expired).
    Returns job dict with the lease stamped, or None if queue is idle.
    """
    conn = await get_db()
    now = time.time()
    # Find candidate atomically via UPDATE ... RETURNING-style workflow on sqlite.
    cur = await conn.execute(
        """SELECT id, ticker, reason, attempts FROM research_jobs
           WHERE status='pending' OR (status='running' AND lease_expires_at < ?)
           ORDER BY created_at ASC LIMIT 1""",
        (now,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    job_id = row["id"]
    await conn.execute(
        """UPDATE research_jobs
           SET status='running', lease_expires_at=?, attempts=attempts+1
           WHERE id=?""",
        (now + lease_ttl, job_id),
    )
    await conn.commit()
    return {
        "id": job_id,
        "ticker": row["ticker"],
        "reason": row["reason"],
        "attempts": row["attempts"] + 1,
        "status": "running",
    }


async def finish_atlas_job(job_id: int, status: str) -> None:
    """Mark a job as done or failed."""
    conn = await get_db()
    await conn.execute(
        "UPDATE research_jobs SET status=?, finished_at=? WHERE id=?",
        (status, time.time(), job_id),
    )
    await conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_atlas_queue.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/db.py tests/test_atlas_queue.py
git commit -m "Add Atlas job queue helpers (enqueue, lease, finish)"
```

---

### Task 3: `research_sections` helpers

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_research_sections.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_research_sections.py
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_upsert_ok_stores_content_and_last_good():
    await db.upsert_research_section("NVDA", "analyst", "signals summary", "ok")
    secs = await db.get_research_sections("NVDA")
    assert "analyst" in secs
    assert secs["analyst"]["content"] == "signals summary"
    assert secs["analyst"]["last_good_content"] == "signals summary"
    assert secs["analyst"]["status"] == "ok"
    assert secs["analyst"]["last_good_at"] is not None


async def test_upsert_failed_preserves_last_good():
    await db.upsert_research_section("NVDA", "news", "good content", "ok")
    await db.upsert_research_section("NVDA", "news", None, "failed")
    secs = await db.get_research_sections("NVDA")
    assert secs["news"]["status"] == "failed"
    assert secs["news"]["content"] is None
    assert secs["news"]["last_good_content"] == "good content"


async def test_get_research_sections_empty_ticker_returns_empty():
    secs = await db.get_research_sections("UNKNOWN")
    assert secs == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_research_sections.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement helpers in `consensus_engine/db.py`**

Append after the Atlas queue helpers from Task 2:

```python
async def upsert_research_section(ticker: str, source: str,
                                  content: str | None, status: str) -> None:
    """Upsert a section. On status='ok' updates last_good_content/last_good_at.
    On any other status, preserves prior last_good_content.
    """
    conn = await get_db()
    now = time.time()
    cur = await conn.execute(
        "SELECT last_good_content, last_good_at FROM research_sections WHERE ticker=? AND source=?",
        (ticker.upper(), source),
    )
    existing = await cur.fetchone()

    if status == "ok":
        lg_content = content
        lg_at = now
    else:
        lg_content = existing["last_good_content"] if existing else None
        lg_at = existing["last_good_at"] if existing else None

    await conn.execute(
        """INSERT INTO research_sections
              (ticker, source, content, last_good_content, fetched_at, last_good_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(ticker, source) DO UPDATE SET
              content=excluded.content,
              last_good_content=excluded.last_good_content,
              fetched_at=excluded.fetched_at,
              last_good_at=excluded.last_good_at,
              status=excluded.status""",
        (ticker.upper(), source, content, lg_content, now, lg_at, status),
    )
    await conn.commit()


async def get_research_sections(ticker: str) -> dict[str, dict]:
    """Return {source: {content, last_good_content, fetched_at, last_good_at, status}}."""
    conn = await get_db()
    cur = await conn.execute(
        "SELECT source, content, last_good_content, fetched_at, last_good_at, status "
        "FROM research_sections WHERE ticker=?",
        (ticker.upper(),),
    )
    rows = await cur.fetchall()
    return {r["source"]: dict(r) for r in rows}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_research_sections.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/db.py tests/test_research_sections.py
git commit -m "Add research_sections upsert/read helpers with last-good preservation"
```

---

### Task 4: `briefing_runs` helpers

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_briefing_runs.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_briefing_runs.py
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_upsert_creates_pending_then_transitions():
    await db.upsert_briefing_run(
        "2026-04-21",
        session_start_utc=1.0,
        session_end_utc=2.0,
        rendered_content="brief text",
        status="pending",
    )
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "pending"
    assert run["rendered_content"] == "brief text"

    await db.upsert_briefing_run(
        "2026-04-21",
        discord_message_id="msg123",
        status="posted",
    )
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "posted"
    assert run["discord_message_id"] == "msg123"
    assert run["posted_at"] is not None

    await db.upsert_briefing_run("2026-04-21", status="archived")
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "archived"
    assert run["archived_at"] is not None


async def test_get_missing_returns_none():
    run = await db.get_briefing_run("2099-01-01")
    assert run is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_briefing_runs.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement helpers in `consensus_engine/db.py`**

```python
async def get_briefing_run(session_key: str) -> dict | None:
    conn = await get_db()
    cur = await conn.execute("SELECT * FROM briefing_runs WHERE session_key=?", (session_key,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def upsert_briefing_run(session_key: str, **fields) -> None:
    """Upsert a briefing row. Auto-stamps posted_at on status='posted' and
    archived_at on status='archived'. Requires session_start_utc / session_end_utc
    on first insert.
    """
    conn = await get_db()
    now = time.time()
    existing = await get_briefing_run(session_key)

    if fields.get("status") == "posted" and "posted_at" not in fields:
        fields["posted_at"] = now
    if fields.get("status") == "archived" and "archived_at" not in fields:
        fields["archived_at"] = now

    if existing is None:
        row = {
            "session_key": session_key,
            "session_start_utc": fields.get("session_start_utc", 0.0),
            "session_end_utc": fields.get("session_end_utc", 0.0),
            "rendered_content": fields.get("rendered_content"),
            "discord_message_id": fields.get("discord_message_id"),
            "status": fields.get("status", "pending"),
            "created_at": now,
            "posted_at": fields.get("posted_at"),
            "archived_at": fields.get("archived_at"),
        }
        await conn.execute(
            """INSERT INTO briefing_runs
               (session_key, session_start_utc, session_end_utc, rendered_content,
                discord_message_id, status, created_at, posted_at, archived_at)
               VALUES (:session_key, :session_start_utc, :session_end_utc, :rendered_content,
                       :discord_message_id, :status, :created_at, :posted_at, :archived_at)""",
            row,
        )
    else:
        allowed = {"session_start_utc", "session_end_utc", "rendered_content",
                   "discord_message_id", "status", "posted_at", "archived_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if sets:
            cols = ", ".join(f"{k}=?" for k in sets)
            values = list(sets.values()) + [session_key]
            await conn.execute(
                f"UPDATE briefing_runs SET {cols} WHERE session_key=?", values,
            )
    await conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_briefing_runs.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/db.py tests/test_briefing_runs.py
git commit -m "Add briefing_runs outbox helpers"
```

---

### Task 5: `get_top_tickers_session` helper

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_top_tickers_session.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_top_tickers_session.py
import time
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_top_tickers_by_count_in_window():
    now = time.time()
    conn = await db.get_db()
    rows = [
        ("NVDA", "twitter", "a", "x", "neutral", now - 100, now + 3600),
        ("NVDA", "twitter", "a", "y", "neutral", now - 200, now + 3600),
        ("NVDA", "twitter", "a", "z", "neutral", now - 300, now + 3600),
        ("AAPL", "twitter", "b", "x", "neutral", now - 100, now + 3600),
        ("AAPL", "twitter", "b", "y", "neutral", now - 150, now + 3600),
        ("TSLA", "twitter", "c", "x", "neutral", now - 100, now + 3600),
        # outside window — should be excluded
        ("MSFT", "twitter", "d", "x", "neutral", now - 100000, now + 3600),
    ]
    for r in rows:
        await conn.execute(
            "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)", r,
        )
    await conn.commit()

    top = await db.get_top_tickers_session(now - 3600, now, limit=10)
    # Order: NVDA (3) > AAPL (2) > TSLA (1); MSFT excluded
    assert top[:3] == ["NVDA", "AAPL", "TSLA"]
    assert "MSFT" not in top
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_top_tickers_session.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement helper in `consensus_engine/db.py`**

```python
async def get_top_tickers_session(session_start_utc: float, session_end_utc: float,
                                  limit: int = 10) -> list[str]:
    """Return tickers sorted desc by signal count within [start, end)."""
    conn = await get_db()
    cur = await conn.execute(
        """SELECT ticker, COUNT(*) AS cnt FROM ticker_signals
           WHERE detected_at >= ? AND detected_at < ?
           GROUP BY ticker ORDER BY cnt DESC, ticker ASC LIMIT ?""",
        (session_start_utc, session_end_utc, limit),
    )
    rows = await cur.fetchall()
    return [r["ticker"] for r in rows]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_top_tickers_session.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/db.py tests/test_top_tickers_session.py
git commit -m "Add get_top_tickers_session query for Alfred/Atlas sweep"
```

---

### Task 6: Config additions

**Files:**
- Modify: `config/consensus.yaml`

- [ ] **Step 1: Append new sections**

Append to the end of `config/consensus.yaml`:

```yaml
# -----------------------------------------------------------------------------
# Vault + Atlas + Alfred (research memory + morning briefing)
# -----------------------------------------------------------------------------
vault:
  path: "/root/.openclaw/vault"

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

alfred:
  enabled: false                       # flip to true after a manual dry-run
  channel_id: "$DISCORD_BRIEFING_CHANNEL_ID"
  post_window_et: ["08:50", "09:00"]
  market_holidays: []
```

Then add the api_keys entry near the other Discord keys (around line 13):

```yaml
  discord_briefing_channel_id: "$DISCORD_BRIEFING_CHANNEL_ID"
```

- [ ] **Step 2: Verify config loads**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('/root/.openclaw/.env')
from consensus_engine import config as cfg
assert cfg.get('atlas.enabled') is False
assert cfg.get('alfred.enabled') is False
assert cfg.get('vault.path') == '/root/.openclaw/vault'
assert cfg.get('atlas.cache_days') == 7
assert cfg.get('alfred.post_window_et') == ['08:50', '09:00']
print('OK')
"
```
Expected output: `OK`.

- [ ] **Step 3: Commit**

```bash
git add config/consensus.yaml
git commit -m "Add vault/atlas/alfred config sections (disabled by default)"
```

---

## Lane 2 — Atlas

### Task 7: ET session helper (shared module)

**Files:**
- Create: `consensus_engine/research/__init__.py`
- Create: `consensus_engine/research/sessions.py`
- Test: `tests/test_sessions.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sessions.py
from datetime import datetime
from zoneinfo import ZoneInfo
from consensus_engine.research.sessions import current_et_session, is_market_holiday


def test_current_et_session_returns_key_and_bounds():
    # Monday 2026-04-20 at 09:00 ET
    ref = datetime(2026, 4, 20, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    start, end, key = current_et_session(ref)
    assert key == "2026-04-20"
    assert end > start
    # ~24h window (slightly less due to 4pm boundaries)
    assert 18 * 3600 <= end - start <= 30 * 3600


def test_weekend_session_key_rolls_back_to_friday():
    # Saturday should surface Friday's key (tradeable session)
    sat = datetime(2026, 4, 25, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    _, _, key = current_et_session(sat)
    assert key == "2026-04-24"  # Friday


def test_is_market_holiday_matches_config(monkeypatch):
    monkeypatch.setattr(
        "consensus_engine.research.sessions._holiday_list",
        lambda: ["2026-04-21"],
    )
    d = datetime(2026, 4, 21, tzinfo=ZoneInfo("America/New_York"))
    assert is_market_holiday(d) is True
    d = datetime(2026, 4, 22, tzinfo=ZoneInfo("America/New_York"))
    assert is_market_holiday(d) is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_sessions.py -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create package**

```python
# consensus_engine/research/__init__.py
"""Research subsystem: Atlas ticker research worker + session helpers."""
```

```python
# consensus_engine/research/sessions.py
"""ET trading session helpers shared by Atlas and Alfred."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from consensus_engine import config as cfg

ET = ZoneInfo("America/New_York")


def _holiday_list() -> list[str]:
    return list(cfg.get("alfred.market_holidays", []) or [])


def is_market_holiday(dt: datetime) -> bool:
    key = dt.astimezone(ET).strftime("%Y-%m-%d")
    return key in _holiday_list()


def _prev_trading_day(dt: datetime) -> datetime:
    d = dt
    while True:
        d = d - timedelta(days=1)
        if d.weekday() < 5 and not is_market_holiday(d):
            return d


def _is_trading_day(dt: datetime) -> bool:
    return dt.weekday() < 5 and not is_market_holiday(dt)


def current_et_session(now: datetime | None = None) -> tuple[float, float, str]:
    """Return (session_start_utc, session_end_utc, session_key).

    session_key is the most recent *trading* day in ET (rolling back over
    weekends and market holidays). session_start = prev trading day 16:00 ET.
    session_end = session_key day 16:00 ET (or now() if before 16:00).
    """
    now = now or datetime.now(tz=ET)
    now_et = now.astimezone(ET)

    # Find session date: today if trading day, else most recent trading day.
    cur = now_et.date()
    d = datetime(cur.year, cur.month, cur.day, tzinfo=ET)
    while not _is_trading_day(d):
        d = d - timedelta(days=1)
    session_key = d.strftime("%Y-%m-%d")

    end_et = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)
    if now_et < end_et:
        end_et = now_et
    start_et = _prev_trading_day(d).replace(hour=16, minute=0, second=0, microsecond=0)
    return start_et.timestamp(), end_et.timestamp(), session_key
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_sessions.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/ tests/test_sessions.py
git commit -m "Add ET trading session helper for Atlas/Alfred"
```

---

### Task 8: Analyst source adapter

**Files:**
- Create: `consensus_engine/research/sources.py` (will grow with later tasks)
- Test: `tests/test_atlas_sources.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_atlas_sources.py
import time
import pytest
from consensus_engine import db
from consensus_engine.research import sources


@pytest.fixture(autouse=True)
async def _isolated_db(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_analyst_section_queries_twitter_signals(monkeypatch):
    conn = await db.get_db()
    now = time.time()
    for i, txt in enumerate(["NVDA bullish", "NVDA target $150", "NVDA upgrade"]):
        await conn.execute(
            "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("NVDA", "twitter", f"@analyst{i}", txt, "bullish", now - i * 100, now + 3600),
        )
    await conn.commit()

    captured = {}
    async def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "Three bullish NVDA calls in last 30 days."
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)

    summary = await sources.fetch_analyst_section("NVDA")
    assert summary.startswith("Three bullish")
    assert "NVDA bullish" in captured["prompt"]


async def test_analyst_section_returns_none_when_no_signals(monkeypatch):
    async def fake_llm(prompt: str) -> str:
        raise AssertionError("LLM should not be called when no signals")
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)
    out = await sources.fetch_analyst_section("ZZZZ")
    assert out is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_atlas_sources.py -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement adapter in `consensus_engine/research/sources.py`**

```python
"""Atlas source adapters: analyst signals, SEC filings, news.

Each fetcher returns a markdown section string, or None when there's
nothing to summarize / the upstream call failed. Callers are responsible
for upserting into research_sections.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiohttp

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.research.sources")

_ANALYST_LOOKBACK_SECONDS = 30 * 86400
_NEWS_LOOKBACK_SECONDS = 12 * 3600


async def _summarize_with_llm(prompt: str) -> str:
    """Thin OpenRouter call. Returns the assistant's text, or '' on failure.
    Reuses llm.model from the consensus_engine config (same as llm_scorer).
    """
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        log.warning("OpenRouter key missing; skipping LLM summary")
        return ""
    model = cfg.get("llm.model", "minimax/minimax-m2.5")
    max_tokens = cfg.get("llm.max_tokens", 1024)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content":
                            "You are a concise equity research analyst. "
                            "Summarize in markdown bullet points — no preamble."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    log.warning("LLM summary HTTP %d", resp.status)
                    return ""
                data = await resp.json()
                return (data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content") or "").strip()
    except Exception as exc:
        log.warning("LLM summary error: %s", exc)
        return ""


async def fetch_analyst_section(ticker: str) -> str | None:
    """Summarize last-30d TweetShift/Twitter signals for a ticker.
    Returns markdown, or None if no signals exist in the window.
    """
    conn = await db.get_db()
    cutoff = time.time() - _ANALYST_LOOKBACK_SECONDS
    cur = await conn.execute(
        """SELECT source_detail, raw_text, sentiment, detected_at
           FROM ticker_signals
           WHERE ticker=? AND source_type='twitter' AND detected_at >= ?
           ORDER BY detected_at DESC LIMIT 50""",
        (ticker.upper(), cutoff),
    )
    rows = await cur.fetchall()
    if not rows:
        return None

    lines = []
    for r in rows:
        who = r["source_detail"] or "unknown"
        sent = r["sentiment"] or "neutral"
        txt = (r["raw_text"] or "").replace("\n", " ").strip()
        lines.append(f"- [{sent}] {who}: {txt[:240]}")

    prompt = (
        f"Ticker: {ticker}\n"
        f"Last 30 days of analyst tweets ({len(rows)} total):\n\n"
        + "\n".join(lines)
        + "\n\nWrite 3-6 markdown bullets capturing the dominant thesis, "
          "direction skew, and any price targets. Be specific; quote analysts."
    )
    summary = await _summarize_with_llm(prompt)
    if not summary:
        # Fall back to a raw count so the section isn't empty.
        bulls = sum(1 for r in rows if (r["sentiment"] or "").lower() == "bullish")
        bears = sum(1 for r in rows if (r["sentiment"] or "").lower() == "bearish")
        return f"- {len(rows)} analyst posts in last 30d ({bulls} bullish / {bears} bearish)"
    return summary
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_atlas_sources.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/sources.py tests/test_atlas_sources.py
git commit -m "Add Atlas analyst source adapter (TweetShift 30d summary)"
```

---

### Task 9: News source adapter (SearXNG)

**Files:**
- Modify: `consensus_engine/research/sources.py`
- Test: `tests/test_atlas_sources.py` (extend)

- [ ] **Step 1: Write the failing test — append to `tests/test_atlas_sources.py`**

```python
async def test_news_section_queries_searxng_and_summarizes(monkeypatch):
    async def fake_searxng(query):
        assert "NVDA" in query
        return [
            {"title": "NVDA jumps on AI guidance", "url": "https://x.com/a", "content": "..."},
            {"title": "Nvidia beats estimates", "url": "https://x.com/b", "content": "..."},
        ]
    async def fake_llm(prompt):
        assert "NVDA jumps" in prompt
        return "- AI guidance drove pop\n- Estimates beat"
    monkeypatch.setattr("consensus_engine.scanners.searxng.search_searxng", fake_searxng)
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)

    out = await sources.fetch_news_section("NVDA")
    assert out is not None
    assert "AI guidance" in out


async def test_news_section_returns_none_when_empty(monkeypatch):
    async def empty(q): return []
    monkeypatch.setattr("consensus_engine.scanners.searxng.search_searxng", empty)
    out = await sources.fetch_news_section("ZZZZ")
    assert out is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_atlas_sources.py -v -k news
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/research/sources.py`**

```python
async def fetch_news_section(ticker: str) -> str | None:
    """Query SearXNG for `"TICKER" stock news`, summarize top hits."""
    from consensus_engine.scanners.searxng import search_searxng
    try:
        results = await search_searxng(f'"{ticker}" stock news')
    except Exception as exc:
        log.warning("SearXNG news query failed for %s: %s", ticker, exc)
        return None

    results = results[:10]
    if not results:
        return None

    lines = [f"- {r.get('title', '').strip()} — {r.get('url', '')}" for r in results]
    prompt = (
        f"Ticker: {ticker}\n"
        f"Recent news results:\n\n" + "\n".join(lines) +
        "\n\nWrite 3-5 markdown bullets describing the most material news. "
        "Link to sources. Skip pure PR fluff."
    )
    summary = await _summarize_with_llm(prompt)
    return summary or "\n".join(lines[:5])
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_atlas_sources.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/sources.py tests/test_atlas_sources.py
git commit -m "Add Atlas news source adapter (SearXNG + LLM summary)"
```

---

### Task 10: SEC source adapter

**Files:**
- Modify: `consensus_engine/research/sources.py`
- Test: `tests/test_atlas_sources.py` (extend)

- [ ] **Step 1: Write the failing test — append**

```python
async def test_sec_section_fetches_recent_8k(monkeypatch):
    async def fake_filings(ticker, limit=5):
        return [
            {"form": "8-K", "filed": "2026-04-19", "accession": "0001-abc",
             "items": "Item 2.02", "summary": "Q4 earnings released"},
            {"form": "10-Q", "filed": "2026-03-10", "accession": "0002-def",
             "items": "", "summary": "Quarterly report"},
        ]
    async def fake_llm(prompt):
        assert "Q4 earnings" in prompt
        return "- Q4 beat, revenue $60B"
    monkeypatch.setattr(sources, "_recent_filings", fake_filings)
    monkeypatch.setattr(sources, "_summarize_with_llm", fake_llm)

    out = await sources.fetch_sec_section("NVDA")
    assert out is not None
    assert "Q4" in out


async def test_sec_section_returns_none_on_no_filings(monkeypatch):
    async def empty(ticker, limit=5): return []
    monkeypatch.setattr(sources, "_recent_filings", empty)
    out = await sources.fetch_sec_section("ZZZZ")
    assert out is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_atlas_sources.py -v -k sec
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/research/sources.py`**

```python
_SEC_USER_AGENT = "OpenClaw Signal Engine (ak@openclaw.dev)"


async def _recent_filings(ticker: str, limit: int = 5) -> list[dict]:
    """Return recent 8-K/10-Q/10-K filings for ticker (most recent first)."""
    # Reuse the CIK cache from consensus_engine.scanners.sec_edgar
    from consensus_engine.scanners import sec_edgar
    await sec_edgar._load_ticker_map()
    cik = sec_edgar._ticker_to_cik.get(ticker.upper())
    if not cik:
        return []
    url = f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _SEC_USER_AGENT}) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
    except Exception as exc:
        log.warning("SEC submissions fetch failed for %s: %s", ticker, exc)
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filed = recent.get("filingDate", [])
    accs = recent.get("accessionNumber", [])
    items = recent.get("items", [])
    primary_doc = recent.get("primaryDocDescription", [])

    out: list[dict] = []
    for i, form in enumerate(forms):
        if form not in ("8-K", "10-Q", "10-K"):
            continue
        out.append({
            "form": form,
            "filed": filed[i] if i < len(filed) else "",
            "accession": accs[i] if i < len(accs) else "",
            "items": items[i] if i < len(items) else "",
            "summary": primary_doc[i] if i < len(primary_doc) else "",
        })
        if len(out) >= limit:
            break
    return out


async def fetch_sec_section(ticker: str) -> str | None:
    """Summarize the most recent SEC filings (8-K/10-Q/10-K) for ticker."""
    filings = await _recent_filings(ticker, limit=5)
    if not filings:
        return None
    lines = [
        f"- **{f['form']}** filed {f['filed']} — {f['items'] or f['summary'] or ''}"
        for f in filings
    ]
    prompt = (
        f"Ticker: {ticker}\nRecent SEC filings:\n\n" + "\n".join(lines) +
        "\n\nWrite 3-5 markdown bullets summarizing material financial / "
        "strategic events. Call out earnings prints, guidance changes, "
        "executive departures, or material contracts."
    )
    summary = await _summarize_with_llm(prompt)
    return summary or "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_atlas_sources.py -v
```
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/sources.py tests/test_atlas_sources.py
git commit -m "Add Atlas SEC source adapter (EDGAR recent filings)"
```

---

### Task 11: Markdown renderer + atomic write

**Files:**
- Create: `consensus_engine/research/vault.py`
- Test: `tests/test_vault_render.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vault_render.py
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from consensus_engine.research import vault


def test_render_ticker_markdown_includes_sections_and_freshness():
    now = 1700000000.0
    sections = {
        "analyst": {"content": "bullish tone", "status": "ok", "last_good_at": now, "fetched_at": now},
        "sec": {"content": None, "last_good_content": "Q4 beat", "status": "failed",
                "last_good_at": now - 3600, "fetched_at": now},
        "news": {"content": "top stories", "status": "ok", "last_good_at": now, "fetched_at": now},
    }
    md = vault.render_ticker_markdown("NVDA", sections)
    assert md.startswith("# NVDA Research Note")
    assert "Analyst Signals" in md
    assert "bullish tone" in md
    # SEC falls back to last_good_content and marks stale
    assert "Q4 beat" in md
    assert "stale" in md.lower() or "last-good" in md.lower()
    assert "top stories" in md


async def test_write_ticker_vault_atomic_rename(tmp_path):
    sections = {
        "analyst": {"content": "x", "status": "ok", "last_good_at": 1.0, "fetched_at": 1.0},
    }
    await vault.write_ticker_vault("NVDA", sections, str(tmp_path))
    expected = tmp_path / "tickers" / "NVDA.md"
    assert expected.exists()
    content = expected.read_text()
    assert "NVDA" in content
    # No temp file left behind
    assert not (tmp_path / "tickers" / "NVDA.md.tmp").exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_vault_render.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `consensus_engine/research/vault.py`**

```python
"""Vault markdown rendering + atomic file writes."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("consensus_engine.research.vault")

ET = ZoneInfo("America/New_York")
_ORDER = [("analyst", "Analyst Signals (TweetShift)"),
          ("sec", "Earnings & SEC"),
          ("news", "News (last 12h)")]


def _section_body(section: dict | None) -> tuple[str, bool]:
    """Return (body_text, is_stale). Falls back to last_good_content when current failed."""
    if not section:
        return ("_No data yet._", False)
    if section.get("status") == "ok" and section.get("content"):
        return (section["content"], False)
    if section.get("last_good_content"):
        return (section["last_good_content"], True)
    return ("_Fetch failed and no prior content._", False)


def render_ticker_markdown(ticker: str, sections: dict) -> str:
    now_et = datetime.now(tz=ET).strftime("%Y-%m-%d %H:%M ET")
    flags = []
    for key, _ in _ORDER:
        s = sections.get(key)
        if s and s.get("status") == "ok":
            flags.append(f"{key} ✓")
        elif s and s.get("last_good_content"):
            flags.append(f"{key} (stale)")
        else:
            flags.append(f"{key} ✗")
    header = (
        f"# {ticker} Research Note\n"
        f"Generated: {now_et}  |  Sources: {'  '.join(flags)}\n\n"
    )
    parts = [header]
    for key, title in _ORDER:
        body, stale = _section_body(sections.get(key))
        suffix = "  _(last-good)_" if stale else ""
        parts.append(f"## {title}{suffix}\n{body}\n")
    return "\n".join(parts)


async def write_ticker_vault(ticker: str, sections: dict, vault_path: str) -> str:
    """Atomically write vault/tickers/TICKER.md. Returns the final path."""
    dest_dir = os.path.join(vault_path, "tickers")
    os.makedirs(dest_dir, exist_ok=True)
    final = os.path.join(dest_dir, f"{ticker.upper()}.md")
    tmp = final + ".tmp"
    content = render_ticker_markdown(ticker.upper(), sections)

    def _write():
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, final)

    await asyncio.get_event_loop().run_in_executor(None, _write)
    log.info("Wrote vault note %s", final)
    return final
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_vault_render.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/vault.py tests/test_vault_render.py
git commit -m "Add vault markdown renderer with atomic rename writes"
```

---

### Task 12: Atlas worker loop + `_process_job`

**Files:**
- Create: `consensus_engine/research/atlas.py`
- Test: `tests/test_atlas_worker.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_atlas_worker.py
import asyncio
import os
import pytest
from consensus_engine import db
from consensus_engine.research import atlas


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: {
                            "vault.path": str(tmp_path / "vault"),
                            "atlas.lease_ttl_seconds": 1800,
                            "atlas.cache_days": 7,
                            "atlas.sources": {"analyst": True, "sec": True, "news": True},
                            "alfred.market_holidays": [],
                            "llm.model": "x",
                            "llm.max_tokens": 512,
                        }.get(k, default))
    yield
    dbmod._db = None


async def test_process_job_writes_sections_and_vault(monkeypatch, tmp_path):
    from consensus_engine.research import sources
    async def ok_analyst(t): return "analyst md"
    async def ok_sec(t): return "sec md"
    async def ok_news(t): return "news md"
    monkeypatch.setattr(sources, "fetch_analyst_section", ok_analyst)
    monkeypatch.setattr(sources, "fetch_sec_section", ok_sec)
    monkeypatch.setattr(sources, "fetch_news_section", ok_news)

    job_id = await db.enqueue_atlas_job("NVDA", "sweep")
    job = await db.acquire_atlas_lease(1800)
    await atlas._process_job(job)

    secs = await db.get_research_sections("NVDA")
    assert secs["analyst"]["status"] == "ok"
    assert secs["sec"]["status"] == "ok"
    assert secs["news"]["status"] == "ok"
    vault_file = tmp_path / "vault" / "tickers" / "NVDA.md"
    assert vault_file.exists()
    assert "analyst md" in vault_file.read_text()


async def test_process_job_failed_source_preserves_last_good(monkeypatch, tmp_path):
    from consensus_engine.research import sources
    calls = {"analyst": 0}
    async def flaky_analyst(t):
        calls["analyst"] += 1
        if calls["analyst"] == 1:
            return "first success"
        raise RuntimeError("boom")
    async def ok(t): return "x"
    monkeypatch.setattr(sources, "fetch_analyst_section", flaky_analyst)
    monkeypatch.setattr(sources, "fetch_sec_section", ok)
    monkeypatch.setattr(sources, "fetch_news_section", ok)

    # First run succeeds
    await db.enqueue_atlas_job("NVDA", "sweep")
    job = await db.acquire_atlas_lease(1800)
    await atlas._process_job(job)
    # Second run: analyst raises, should preserve last_good
    await db.enqueue_atlas_job("NVDA", "alert")
    job = await db.acquire_atlas_lease(1800)
    await atlas._process_job(job)

    secs = await db.get_research_sections("NVDA")
    assert secs["analyst"]["status"] == "failed"
    assert secs["analyst"]["last_good_content"] == "first success"
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_atlas_worker.py -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `consensus_engine/research/atlas.py`**

```python
"""Atlas: leased-queue research worker.

Drains `research_jobs`, fans out to source adapters, preserves last-good
content on failure, and renders a per-ticker markdown note into the vault.
"""
from __future__ import annotations

import asyncio
import logging
import time

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.research import sources, vault

log = logging.getLogger("consensus_engine.research.atlas")

_SOURCE_FETCHERS = {
    "analyst": sources.fetch_analyst_section,
    "sec": sources.fetch_sec_section,
    "news": sources.fetch_news_section,
}


def _enabled_sources() -> list[str]:
    toggles = cfg.get("atlas.sources", {}) or {}
    return [s for s in ("analyst", "sec", "news") if toggles.get(s, True)]


def _is_fresh(section: dict | None, cache_days: int, reason: str) -> bool:
    # Alerts always refresh analyst regardless of freshness.
    if not section:
        return False
    last = section.get("last_good_at") or 0
    if not last:
        return False
    return (time.time() - last) < (cache_days * 86400)


async def _run_source(ticker: str, source: str) -> None:
    fetcher = _SOURCE_FETCHERS[source]
    try:
        content = await fetcher(ticker)
    except Exception as exc:
        log.warning("Atlas %s/%s fetch raised: %s", ticker, source, exc)
        await db.upsert_research_section(ticker, source, None, "failed")
        return
    if content is None:
        await db.upsert_research_section(ticker, source, None, "skipped")
    else:
        await db.upsert_research_section(ticker, source, content, "ok")


async def _process_job(job: dict) -> None:
    ticker = job["ticker"]
    reason = job["reason"]
    cache_days = int(cfg.get("atlas.cache_days", 7))
    existing = await db.get_research_sections(ticker)

    tasks = []
    for source in _enabled_sources():
        if reason == "alert" and source == "analyst":
            tasks.append(_run_source(ticker, source))
            continue
        if _is_fresh(existing.get(source), cache_days, reason):
            log.info("Atlas %s/%s fresh, skipping", ticker, source)
            continue
        tasks.append(_run_source(ticker, source))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=False)

    sections = await db.get_research_sections(ticker)
    vault_path = cfg.get("vault.path", "/root/.openclaw/vault")
    try:
        await vault.write_ticker_vault(ticker, sections, vault_path)
        await db.finish_atlas_job(job["id"], "done")
    except Exception as exc:
        log.error("Atlas vault write failed for %s: %s", ticker, exc)
        await db.finish_atlas_job(job["id"], "failed")


async def atlas_worker_loop(stop_event: asyncio.Event) -> None:
    if not cfg.get("atlas.enabled", False):
        log.info("Atlas disabled; worker loop exiting")
        return
    lease_ttl = int(cfg.get("atlas.lease_ttl_seconds", 1800))
    idle_sleep = 30
    while not stop_event.is_set():
        try:
            job = await db.acquire_atlas_lease(lease_ttl)
            if job:
                log.info("Atlas processing %s (%s)", job["ticker"], job["reason"])
                await _process_job(job)
                continue
        except Exception as exc:
            log.error("Atlas worker loop error: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=idle_sleep)
        except asyncio.TimeoutError:
            pass


async def run_one_job() -> bool:
    """Verification helper: drain one job synchronously. Returns True if a job ran."""
    job = await db.acquire_atlas_lease(int(cfg.get("atlas.lease_ttl_seconds", 1800)))
    if not job:
        return False
    await _process_job(job)
    return True


async def enqueue_atlas_job(ticker: str, reason: str) -> int | None:
    """Public API: enqueue a research job. Coalesces duplicate tickers."""
    return await db.enqueue_atlas_job(ticker, reason)
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_atlas_worker.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/atlas.py tests/test_atlas_worker.py
git commit -m "Add Atlas worker loop + per-source job processor"
```

---

### Task 13: Atlas sweep loop (daily 8:00 AM ET)

**Files:**
- Modify: `consensus_engine/research/atlas.py`
- Test: `tests/test_atlas_sweep.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_atlas_sweep.py
import time
import pytest
from consensus_engine import db
from consensus_engine.research import atlas


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: {
                            "atlas.max_tickers_sweep": 3,
                            "atlas.cache_days": 7,
                            "atlas.enabled": True,
                        }.get(k, default))
    yield
    dbmod._db = None


async def test_sweep_enqueues_top_tickers():
    # Seed signals in session window
    conn = await db.get_db()
    now = time.time()
    for t, n in [("NVDA", 5), ("AAPL", 3), ("TSLA", 2), ("MSFT", 1)]:
        for i in range(n):
            await conn.execute(
                "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (t, "twitter", "a", "x", "neutral", now - 3600, now + 3600),
            )
    await conn.commit()

    await atlas._sweep_once(now - 7200, now)

    cur = await conn.execute(
        "SELECT ticker FROM research_jobs WHERE status='pending' ORDER BY created_at"
    )
    rows = await cur.fetchall()
    assert [r["ticker"] for r in rows] == ["NVDA", "AAPL", "TSLA"]


async def test_sweep_skips_fresh_tickers():
    conn = await db.get_db()
    now = time.time()
    await conn.execute(
        "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        ("NVDA", "twitter", "a", "x", "neutral", now - 100, now + 3600),
    )
    # Fresh section already exists
    await db.upsert_research_section("NVDA", "analyst", "recent", "ok")
    await conn.commit()

    await atlas._sweep_once(now - 7200, now)

    cur = await conn.execute("SELECT COUNT(*) AS c FROM research_jobs")
    assert (await cur.fetchone())["c"] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_atlas_sweep.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/research/atlas.py`**

```python
async def _ticker_is_fresh(ticker: str, cache_days: int) -> bool:
    sections = await db.get_research_sections(ticker)
    if not sections:
        return False
    for s in sections.values():
        last = s.get("last_good_at") or 0
        if last and (time.time() - last) < cache_days * 86400:
            return True
    return False


async def _sweep_once(session_start_utc: float, session_end_utc: float) -> int:
    """Enqueue top-N tickers from the session. Returns count enqueued."""
    max_n = int(cfg.get("atlas.max_tickers_sweep", 10))
    cache_days = int(cfg.get("atlas.cache_days", 7))
    tickers = await db.get_top_tickers_session(session_start_utc, session_end_utc, limit=max_n * 2)
    enqueued = 0
    for t in tickers:
        if await _ticker_is_fresh(t, cache_days):
            continue
        if await db.enqueue_atlas_job(t, "sweep") is not None:
            enqueued += 1
            if enqueued >= max_n:
                break
    log.info("Atlas sweep enqueued %d tickers", enqueued)
    return enqueued


async def atlas_sweep_loop(stop_event: asyncio.Event) -> None:
    """Fire a sweep once per trading day at atlas.sweep_time_et."""
    from consensus_engine.research.sessions import current_et_session, is_market_holiday
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")

    if not cfg.get("atlas.enabled", False):
        log.info("Atlas disabled; sweep loop exiting")
        return

    fired_key: str | None = None
    while not stop_event.is_set():
        now = datetime.now(tz=ET)
        sweep_hhmm = str(cfg.get("atlas.sweep_time_et", "08:00"))
        hh, mm = [int(x) for x in sweep_hhmm.split(":")]
        is_trading = now.weekday() < 5 and not is_market_holiday(now)
        at_or_past = (now.hour, now.minute) >= (hh, mm)
        today_key = now.strftime("%Y-%m-%d")
        if is_trading and at_or_past and fired_key != today_key:
            start, end, _ = current_et_session(now)
            try:
                await _sweep_once(start, end)
            except Exception as exc:
                log.error("Atlas sweep failed: %s", exc)
            fired_key = today_key
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_atlas_sweep.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/research/atlas.py tests/test_atlas_sweep.py
git commit -m "Add Atlas daily sweep loop (enqueues top session tickers)"
```

---

### Task 14: Alert hook in `db.insert_alert`

**Files:**
- Modify: `consensus_engine/db.py`
- Test: `tests/test_insert_alert_hook.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insert_alert_hook.py
import pytest
from consensus_engine import db


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: True if k == "atlas.enabled" else default)
    yield
    dbmod._db = None


async def test_insert_alert_enqueues_atlas_job():
    await db.insert_alert("NVDA", 80.0, "earnings beat", "news", "{}", "{}", "{}", 150.0)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT ticker, reason FROM research_jobs WHERE ticker='NVDA'"
    )
    row = await cur.fetchone()
    assert row is not None
    assert row["reason"] == "alert"


async def test_insert_alert_respects_atlas_disabled(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: False if k == "atlas.enabled" else default)
    await db.insert_alert("AAPL", 75.0, "x", "news", "{}", "{}", "{}", 200.0)
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM research_jobs")
    assert (await cur.fetchone())["c"] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_insert_alert_hook.py -v
```
Expected: FAIL — no hook yet.

- [ ] **Step 3: Modify `consensus_engine/db.py::insert_alert`**

Locate `async def insert_alert(` (currently around line 461). Append **inside** the function, right before `return cursor.lastrowid`:

```python
    # Atlas hook: enqueue a research job on every alert (non-blocking, coalesced).
    try:
        if cfg.get("atlas.enabled", False):
            await enqueue_atlas_job(ticker, "alert")
    except Exception as exc:
        log.warning("Atlas alert-enqueue failed: %s", exc)
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_insert_alert_hook.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/db.py tests/test_insert_alert_hook.py
git commit -m "Hook insert_alert into Atlas research_jobs queue"
```

---

## Lane 3 — Alfred

### Task 15: Alfred session builder

**Files:**
- Create: `consensus_engine/briefing/__init__.py`
- Create: `consensus_engine/briefing/alfred.py`
- Test: `tests/test_alfred_session_builder.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alfred_session_builder.py
import time
import pytest
from consensus_engine import db
from consensus_engine.briefing import alfred


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    yield
    dbmod._db = None


async def test_build_briefing_data_bundles_all_sections():
    conn = await db.get_db()
    now = time.time()
    # seed an alert in window
    await db.insert_alert("NVDA", 80.0, "earnings", "news", "{}", "{}", "{}", 150.0)
    # seed a ticker signal so top-tickers has something
    await conn.execute(
        "INSERT INTO ticker_signals (ticker, source_type, source_detail, raw_text, sentiment, detected_at, expires_at) VALUES (?,?,?,?,?,?,?)",
        ("NVDA", "twitter", "a", "x", "bullish", now - 100, now + 3600),
    )
    # seed a research_sections last-good
    await db.upsert_research_section("NVDA", "analyst", "summary text", "ok")
    await conn.commit()

    data = await alfred.build_briefing_data(now - 3600, now + 3600)
    assert "alerts" in data and len(data["alerts"]) == 1
    assert data["alerts"][0]["ticker"] == "NVDA"
    assert "top_tickers" in data and "NVDA" in [t["ticker"] for t in data["top_tickers"]]
    assert data["top_tickers"][0]["sections"]["analyst"]["content"] == "summary text"
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_alfred_session_builder.py -v
```
Expected: FAIL.

- [ ] **Step 3: Create `consensus_engine/briefing/__init__.py`**

```python
"""Briefing subsystem: Alfred morning Discord digest."""
```

- [ ] **Step 4: Create `consensus_engine/briefing/alfred.py`** (session builder portion — other methods added later)

```python
"""Alfred: morning Discord briefing with a transactional outbox."""
from __future__ import annotations

import logging
import time

from consensus_engine import config as cfg
from consensus_engine import db

log = logging.getLogger("consensus_engine.briefing.alfred")


async def build_briefing_data(session_start_utc: float,
                              session_end_utc: float) -> dict:
    """Gather all source data Alfred needs to synthesize a brief."""
    conn = await db.get_db()

    # Overnight alerts
    cur = await conn.execute(
        """SELECT ticker, confidence_score, catalyst, catalyst_type,
                  alerted_at, price_at_alert
           FROM alert_history
           WHERE alerted_at BETWEEN ? AND ?
           ORDER BY alerted_at DESC""",
        (session_start_utc, session_end_utc),
    )
    alerts = [dict(r) for r in await cur.fetchall()]

    # Pending youtube_levels (last 14d, not triggered)
    levels_cutoff = time.time() - 14 * 86400
    cur = await conn.execute(
        """SELECT ticker, level_type, price, condition_text, consequence_text,
                  channel_name, published_at
           FROM youtube_levels
           WHERE extracted_at >= ?
           ORDER BY extracted_at DESC LIMIT 30""",
        (levels_cutoff,),
    )
    levels = [dict(r) for r in await cur.fetchall()]

    # High-conviction youtube_signals, last 7d, directional
    yt_cutoff = time.time() - 7 * 86400
    cur = await conn.execute(
        """SELECT ticker, direction, conviction, channel_name, macro_thesis,
                  published_at
           FROM youtube_signals
           WHERE extracted_at >= ?
             AND conviction='high' AND direction != 'neutral'
           ORDER BY extracted_at DESC LIMIT 20""",
        (yt_cutoff,),
    )
    yt_signals = [dict(r) for r in await cur.fetchall()]

    # Latest macro regime
    cur = await conn.execute(
        "SELECT direction, themes, timeframe, summary, confidence, published_at "
        "FROM youtube_macro ORDER BY id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    macro = dict(row) if row else None

    # Top tickers (last 24h) + their research sections
    top = await db.get_top_tickers_session(session_end_utc - 86400, session_end_utc, limit=5)
    top_tickers = []
    for t in top:
        sections = await db.get_research_sections(t)
        top_tickers.append({"ticker": t, "sections": sections})

    return {
        "session_start_utc": session_start_utc,
        "session_end_utc": session_end_utc,
        "alerts": alerts,
        "levels": levels,
        "yt_signals": yt_signals,
        "macro": macro,
        "top_tickers": top_tickers,
    }
```

- [ ] **Step 5: Run to verify pass**

```bash
python3 -m pytest tests/test_alfred_session_builder.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add consensus_engine/briefing/ tests/test_alfred_session_builder.py
git commit -m "Add Alfred session builder (gathers alerts/levels/signals/macro/top tickers)"
```

---

### Task 16: Alfred brief renderer (LLM synthesis)

**Files:**
- Modify: `consensus_engine/briefing/alfred.py`
- Test: `tests/test_alfred_render.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alfred_render.py
import pytest
from consensus_engine.briefing import alfred


async def test_render_briefing_uses_llm_and_has_fallback(monkeypatch):
    data = {
        "session_start_utc": 0, "session_end_utc": 1,
        "alerts": [{"ticker": "NVDA", "confidence_score": 90, "catalyst": "earnings", "catalyst_type": "news", "alerted_at": 0, "price_at_alert": 150}],
        "levels": [], "yt_signals": [], "macro": None,
        "top_tickers": [{"ticker": "NVDA", "sections": {"analyst": {"content": "bullish"}}}],
    }

    async def fake_llm(prompt):
        assert "NVDA" in prompt
        return "## Morning Brief\nNVDA strong overnight."
    monkeypatch.setattr(alfred, "_llm_synthesize", fake_llm)

    out = await alfred._render_briefing(data)
    assert "Morning Brief" in out
    assert "NVDA" in out


async def test_render_briefing_falls_back_when_llm_empty(monkeypatch):
    data = {
        "session_start_utc": 0, "session_end_utc": 1,
        "alerts": [], "levels": [], "yt_signals": [], "macro": None, "top_tickers": [],
    }

    async def empty(prompt): return ""
    monkeypatch.setattr(alfred, "_llm_synthesize", empty)

    out = await alfred._render_briefing(data)
    # Fallback still produces a valid non-empty brief
    assert "Morning Brief" in out
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_alfred_render.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/briefing/alfred.py`**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

_ET = ZoneInfo("America/New_York")


async def _llm_synthesize(prompt: str) -> str:
    """OpenRouter call using the same llm.model as llm_scorer.py."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return ""
    model = cfg.get("llm.model", "minimax/minimax-m2.5")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content":
                            "You are a pre-market briefing writer. Produce concise, "
                            "actionable markdown. Lead with the most important story. "
                            "Keep under 1500 characters."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": cfg.get("llm.max_tokens", 1024),
                    "temperature": 0.3,
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json()
                return (data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content") or "").strip()
    except Exception as exc:
        log.warning("Alfred LLM call failed: %s", exc)
        return ""


def _fallback_render(data: dict) -> str:
    lines = ["## Morning Brief",
             f"_{datetime.now(tz=_ET).strftime('%Y-%m-%d %H:%M ET')}_", ""]
    if data["alerts"]:
        lines.append("**Overnight alerts:**")
        for a in data["alerts"][:10]:
            lines.append(
                f"- {a['ticker']} ({a['confidence_score']:.0f}) — {a['catalyst']}"
            )
        lines.append("")
    if data["top_tickers"]:
        lines.append("**Top tickers last 24h:**")
        for t in data["top_tickers"]:
            lines.append(f"- {t['ticker']}")
        lines.append("")
    if data["macro"]:
        lines.append(f"**Macro:** {data['macro']['direction']} — {data['macro'].get('summary', '')[:160]}")
    if len(lines) <= 3:
        lines.append("_No material overnight activity._")
    return "\n".join(lines)


async def _render_briefing(data: dict) -> str:
    """Try LLM synthesis; fall back to a template if LLM is unavailable."""
    alert_lines = [
        f"- {a['ticker']} ({a['confidence_score']:.0f}/100) — {a['catalyst']}"
        for a in data["alerts"][:15]
    ]
    level_lines = [
        f"- {l['ticker']} {l['level_type']} ${l['price']}: {l.get('condition_text', '')}"
        for l in data["levels"][:10]
    ]
    yt_lines = [
        f"- {s['ticker']} {s['direction']} ({s['channel_name']}): {s.get('macro_thesis', '')[:140]}"
        for s in data["yt_signals"][:10]
    ]
    macro = data["macro"]
    macro_block = (
        f"Macro: {macro['direction']} — themes={macro.get('themes','')} — {macro.get('summary','')[:200]}"
        if macro else "Macro: no recent regime update"
    )
    top_lines = []
    for t in data["top_tickers"]:
        secs = t["sections"]
        analyst = (secs.get("analyst") or {}).get("content") or (secs.get("analyst") or {}).get("last_good_content") or ""
        top_lines.append(f"- **{t['ticker']}** — {analyst[:300]}")

    prompt = (
        "Build a morning Discord briefing from the data below. "
        "Sections: Overnight, Levels to Watch, High-Conviction Analyst Calls, "
        "Macro, Top Tickers. Keep under 1500 characters total. Markdown.\n\n"
        f"## Overnight alerts\n" + ("\n".join(alert_lines) or "_none_") + "\n\n"
        f"## Levels\n" + ("\n".join(level_lines) or "_none_") + "\n\n"
        f"## YT Signals\n" + ("\n".join(yt_lines) or "_none_") + "\n\n"
        f"## {macro_block}\n\n"
        f"## Top Tickers\n" + ("\n".join(top_lines) or "_none_")
    )
    out = await _llm_synthesize(prompt)
    if out:
        return out
    return _fallback_render(data)
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_alfred_render.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/briefing/alfred.py tests/test_alfred_render.py
git commit -m "Add Alfred brief renderer (LLM + template fallback)"
```

---

### Task 17: Alfred Discord sender

**Files:**
- Modify: `consensus_engine/briefing/alfred.py`
- Test: `tests/test_alfred_discord.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alfred_discord.py
import pytest
from consensus_engine.briefing import alfred


async def test_send_discord_returns_message_id_on_success(monkeypatch):
    class FakeResp:
        status = 200
        async def json(self): return {"id": "99988877"}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class FakeSession:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def post(self, url, headers=None, json=None, timeout=None):
            assert "chan123" in url
            assert json["content"].startswith("hello")
            return FakeResp()

    monkeypatch.setattr("consensus_engine.briefing.alfred.aiohttp.ClientSession", FakeSession)
    monkeypatch.setattr("consensus_engine.config.get_api_key",
                        lambda k: "bot-token" if k == "discord_bot_token" else "")
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "chan123" if "channel" in (k or "") else default)

    msg_id = await alfred._send_discord_briefing("hello world")
    assert msg_id == "99988877"


async def test_send_discord_returns_none_when_no_channel(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: "" if "channel" in (k or "") else default)
    out = await alfred._send_discord_briefing("x")
    assert out is None
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_alfred_discord.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/briefing/alfred.py`**

```python
async def _send_discord_briefing(content: str) -> str | None:
    """POST a briefing to the dedicated channel. Returns Discord message id."""
    token = cfg.get_api_key("discord_bot_token")
    channel_id = str(cfg.get("alfred.channel_id", "") or
                     cfg.get("api_keys.discord_briefing_channel_id", "") or "")
    if not token or not channel_id or not channel_id.isdigit():
        log.warning("Alfred Discord: missing bot token or briefing channel id")
        return None
    if getattr(cfg, "dry_run", False):
        log.info("[DRY-RUN] Alfred would post to %s: %s", channel_id, content[:80])
        return "dry-run"

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    # Discord hard limit is 2000 chars.
    payload = {"content": content[:1990]}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={"Authorization": f"Bot {token}",
                         "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status not in (200, 201):
                    log.warning("Alfred Discord post failed: %d", resp.status)
                    return None
                data = await resp.json()
                return str(data.get("id", ""))
    except Exception as exc:
        log.error("Alfred Discord send error: %s", exc)
        return None
```

Also ensure `alfred.py` imports already include `aiohttp` (added in Task 16).

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_alfred_discord.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/briefing/alfred.py tests/test_alfred_discord.py
git commit -m "Add Alfred Discord briefing sender (dedicated channel)"
```

---

### Task 18: Alfred vault archiver

**Files:**
- Modify: `consensus_engine/briefing/alfred.py`
- Test: `tests/test_alfred_vault.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alfred_vault.py
import os
import pytest
from consensus_engine.briefing import alfred


async def test_write_vault_briefing_creates_dated_file(tmp_path):
    await alfred._write_vault_briefing(
        "2026-04-21",
        "## Morning Brief\nhello",
        str(tmp_path),
    )
    expected = tmp_path / "macro" / "briefings" / "2026-04-21.md"
    assert expected.exists()
    content = expected.read_text()
    assert "Morning Brief" in content
    # Atomic — no leftover .tmp
    assert not (tmp_path / "macro" / "briefings" / "2026-04-21.md.tmp").exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_alfred_vault.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/briefing/alfred.py`**

```python
import asyncio as _asyncio
import os as _os


async def _write_vault_briefing(session_key: str, content: str, vault_path: str) -> str:
    """Atomically write vault/macro/briefings/{session_key}.md."""
    dest_dir = _os.path.join(vault_path, "macro", "briefings")
    _os.makedirs(dest_dir, exist_ok=True)
    final = _os.path.join(dest_dir, f"{session_key}.md")
    tmp = final + ".tmp"

    def _write():
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        _os.replace(tmp, final)

    await _asyncio.get_event_loop().run_in_executor(None, _write)
    log.info("Alfred archived briefing to %s", final)
    return final
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_alfred_vault.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/briefing/alfred.py tests/test_alfred_vault.py
git commit -m "Add Alfred vault archiver for briefings"
```

---

### Task 19: Alfred outbox state machine (`post_briefing`)

**Files:**
- Modify: `consensus_engine/briefing/alfred.py`
- Test: `tests/test_alfred_outbox.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alfred_outbox.py
import pytest
from consensus_engine import db
from consensus_engine.briefing import alfred


@pytest.fixture(autouse=True)
async def _isolated(tmp_path, monkeypatch):
    import consensus_engine.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    dbmod._db = None
    await dbmod.init_db()
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: {
                            "vault.path": str(tmp_path / "vault"),
                        }.get(k, default))
    yield
    dbmod._db = None


async def test_post_briefing_runs_full_state_machine(monkeypatch, tmp_path):
    async def fake_render(data): return "brief content"
    async def fake_send(content): return "msg-42"
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)
    monkeypatch.setattr(alfred, "_send_discord_briefing", fake_send)

    data = {"session_start_utc": 1.0, "session_end_utc": 2.0,
            "alerts": [], "levels": [], "yt_signals": [], "macro": None, "top_tickers": []}
    await alfred.post_briefing("2026-04-21", data)

    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "archived"
    assert run["discord_message_id"] == "msg-42"
    assert (tmp_path / "vault" / "macro" / "briefings" / "2026-04-21.md").exists()


async def test_post_briefing_resumes_from_posted(monkeypatch, tmp_path):
    """If we crashed after posting, re-run should only archive (no double-post)."""
    await db.upsert_briefing_run(
        "2026-04-21",
        session_start_utc=1.0, session_end_utc=2.0,
        rendered_content="already-rendered",
        discord_message_id="old-msg",
        status="posted",
    )
    sent = {"count": 0}
    async def fake_send(content):
        sent["count"] += 1
        return "x"
    async def fake_render(data): return "would-never-be-called"
    monkeypatch.setattr(alfred, "_send_discord_briefing", fake_send)
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)

    await alfred.post_briefing("2026-04-21",
                               {"session_start_utc": 1.0, "session_end_utc": 2.0,
                                "alerts": [], "levels": [], "yt_signals": [],
                                "macro": None, "top_tickers": []})
    run = await db.get_briefing_run("2026-04-21")
    assert run["status"] == "archived"
    assert sent["count"] == 0  # did not re-send


async def test_post_briefing_skips_if_archived(monkeypatch):
    await db.upsert_briefing_run(
        "2026-04-21",
        session_start_utc=1.0, session_end_utc=2.0,
        rendered_content="done", status="archived",
    )
    called = {"render": 0, "send": 0}
    async def fake_render(d): called["render"] += 1; return "x"
    async def fake_send(c): called["send"] += 1; return "y"
    monkeypatch.setattr(alfred, "_render_briefing", fake_render)
    monkeypatch.setattr(alfred, "_send_discord_briefing", fake_send)

    await alfred.post_briefing("2026-04-21",
                               {"session_start_utc": 1.0, "session_end_utc": 2.0,
                                "alerts": [], "levels": [], "yt_signals": [],
                                "macro": None, "top_tickers": []})
    assert called["render"] == 0
    assert called["send"] == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_alfred_outbox.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/briefing/alfred.py`**

```python
async def post_briefing(session_key: str, data: dict) -> None:
    """Drive the pending → posted → archived state machine.
    Idempotent: safe to call repeatedly; no double-posts on restart.
    """
    vault_path = cfg.get("vault.path", "/root/.openclaw/vault")

    run = await db.get_briefing_run(session_key)
    if run and run["status"] == "archived":
        log.info("Alfred %s already archived; skipping", session_key)
        return

    # Stage 1: render + persist as pending
    if not run:
        content = await _render_briefing(data)
        await db.upsert_briefing_run(
            session_key,
            session_start_utc=data["session_start_utc"],
            session_end_utc=data["session_end_utc"],
            rendered_content=content,
            status="pending",
        )
        run = await db.get_briefing_run(session_key)
    elif run["status"] == "pending" and not run.get("rendered_content"):
        content = await _render_briefing(data)
        await db.upsert_briefing_run(session_key, rendered_content=content, status="pending")
        run = await db.get_briefing_run(session_key)

    # Stage 2: post to Discord (only if pending)
    if run["status"] == "pending":
        msg_id = await _send_discord_briefing(run["rendered_content"] or "")
        if not msg_id:
            log.warning("Alfred %s Discord post failed; leaving pending for retry", session_key)
            return
        await db.upsert_briefing_run(session_key, discord_message_id=msg_id, status="posted")
        run = await db.get_briefing_run(session_key)

    # Stage 3: archive to vault
    if run["status"] == "posted":
        await _write_vault_briefing(session_key, run["rendered_content"] or "", vault_path)
        await db.upsert_briefing_run(session_key, status="archived")
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_alfred_outbox.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/briefing/alfred.py tests/test_alfred_outbox.py
git commit -m "Add Alfred outbox state machine (pending→posted→archived)"
```

---

### Task 20: Alfred loop (schedule + holiday gate)

**Files:**
- Modify: `consensus_engine/briefing/alfred.py`
- Test: `tests/test_alfred_loop.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alfred_loop.py
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from consensus_engine.briefing import alfred


def test_in_post_window():
    assert alfred._in_post_window(datetime(2026, 4, 21, 8, 55, tzinfo=ZoneInfo("America/New_York")),
                                  ["08:50", "09:00"])
    assert not alfred._in_post_window(datetime(2026, 4, 21, 9, 30, tzinfo=ZoneInfo("America/New_York")),
                                      ["08:50", "09:00"])


async def test_loop_exits_when_disabled(monkeypatch):
    monkeypatch.setattr("consensus_engine.config.get",
                        lambda k, default=None: False if k == "alfred.enabled" else default)
    stop = asyncio.Event()
    # Should return quickly without blocking
    await asyncio.wait_for(alfred.alfred_loop(stop), timeout=2.0)
```

- [ ] **Step 2: Run to verify failure**

```bash
python3 -m pytest tests/test_alfred_loop.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `consensus_engine/briefing/alfred.py`**

```python
def _in_post_window(now_et: datetime, window: list[str]) -> bool:
    if not window or len(window) != 2:
        return False
    try:
        start_hh, start_mm = [int(x) for x in str(window[0]).split(":")]
        end_hh, end_mm = [int(x) for x in str(window[1]).split(":")]
    except Exception:
        return False
    cur = (now_et.hour, now_et.minute)
    return (start_hh, start_mm) <= cur <= (end_hh, end_mm)


async def alfred_loop(stop_event) -> None:
    from consensus_engine.research.sessions import current_et_session, is_market_holiday

    if not cfg.get("alfred.enabled", False):
        log.info("Alfred disabled; loop exiting")
        return

    while not stop_event.is_set():
        now_et = datetime.now(tz=_ET)
        window = list(cfg.get("alfred.post_window_et", ["08:50", "09:00"]) or [])
        is_trading = now_et.weekday() < 5 and not is_market_holiday(now_et)

        if is_trading and _in_post_window(now_et, window):
            start, end, session_key = current_et_session(now_et)
            run = await db.get_briefing_run(session_key)
            if not run or run["status"] != "archived":
                try:
                    data = await build_briefing_data(start, end)
                    await post_briefing(session_key, data)
                except Exception as exc:
                    log.error("Alfred loop error for %s: %s", session_key, exc)

        try:
            await _asyncio.wait_for(stop_event.wait(), timeout=60)
        except _asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Run to verify pass**

```bash
python3 -m pytest tests/test_alfred_loop.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/briefing/alfred.py tests/test_alfred_loop.py
git commit -m "Add Alfred schedule loop (post_window_et + holiday gating)"
```

---

## Lane 4 — Wire-up + Verify

### Task 21: Wire loops into `main.py`

**Files:**
- Modify: `consensus_engine/main.py`

- [ ] **Step 1: Add imports**

Near the top of `consensus_engine/main.py`, alongside the existing scanner imports, add:

```python
from consensus_engine.research.atlas import atlas_worker_loop, atlas_sweep_loop
from consensus_engine.briefing.alfred import alfred_loop
```

- [ ] **Step 2: Register in `asyncio.gather()`**

Locate the `tasks = [...]` list at ~line 331 (inside `run_live()`). Append three new tasks:

```python
            asyncio.create_task(atlas_worker_loop(combined_stop)),
            asyncio.create_task(atlas_sweep_loop(combined_stop)),
            asyncio.create_task(alfred_loop(combined_stop)),
```

- [ ] **Step 3: Verify imports resolve**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('/root/.openclaw/.env')
import consensus_engine.main as m
assert hasattr(m, 'atlas_worker_loop')
assert hasattr(m, 'atlas_sweep_loop')
assert hasattr(m, 'alfred_loop')
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -v
```
Expected: all passing, including existing 280+ tests plus the new ones added in Lanes 1–3.

- [ ] **Step 5: Commit**

```bash
git add consensus_engine/main.py
git commit -m "Wire atlas_worker/sweep + alfred loops into run_live"
```

---

### Task 22: Manual end-to-end smoke test

**Files:**
- Create: `scripts/verify_vault_atlas.py` (one-shot verifier; OK to leave in repo under `scripts/`)

- [ ] **Step 1: Create verification script**

```python
# scripts/verify_vault_atlas.py
"""End-to-end smoke test for Vault/Atlas/Alfred.

Usage: python3 scripts/verify_vault_atlas.py
Requires: OPENROUTER_API_KEY, DISCORD_BOT_TOKEN, DISCORD_BRIEFING_CHANNEL_ID.
Runs Atlas for NVDA, then Alfred in DRY-RUN mode (no Discord post).
"""
import asyncio
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv("/root/.openclaw/.env")

from consensus_engine import db, config as cfg
from consensus_engine.research.atlas import enqueue_atlas_job, run_one_job
from consensus_engine.briefing import alfred
from consensus_engine.research.sessions import current_et_session


async def main():
    await db.init_db()

    print("=== Atlas: NVDA ===")
    job_id = await enqueue_atlas_job("NVDA", "manual")
    print("Enqueued:", job_id)
    ran = await run_one_job()
    print("Ran:", ran)

    sections = await db.get_research_sections("NVDA")
    for src, row in sections.items():
        print(f"  {src}: status={row['status']} "
              f"has_content={bool(row['content'])} "
              f"has_last_good={bool(row.get('last_good_content'))}")

    vault_path = cfg.get("vault.path", "/root/.openclaw/vault")
    print(f"\n=== Vault note ({vault_path}/tickers/NVDA.md) ===")
    try:
        with open(f"{vault_path}/tickers/NVDA.md") as fh:
            print(fh.read()[:2000])
    except FileNotFoundError:
        print("(not written — check logs above)")

    print("\n=== Alfred: DRY-RUN ===")
    cfg.dry_run = True
    start, end, key = current_et_session()
    data = await alfred.build_briefing_data(start, end)
    print(f"Session {key}: {len(data['alerts'])} alerts, "
          f"{len(data['levels'])} levels, "
          f"{len(data['top_tickers'])} top tickers")
    await alfred.post_briefing(key, data)
    run = await db.get_briefing_run(key)
    print(f"briefing_runs[{key}].status = {run['status']}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it**

```bash
python3 scripts/verify_vault_atlas.py
```

Expected:
- `Atlas: NVDA` prints per-source status (`ok`/`failed`/`skipped`)
- `Vault note` prints the rendered markdown (header + 3 sections)
- `Alfred: DRY-RUN` prints a non-zero row count and `briefing_runs[...].status = archived`
- No Python traceback

If any source errors with a config/auth issue, that's a runtime issue — not a plan defect. Capture the error and address separately.

- [ ] **Step 3: Commit**

```bash
git add scripts/verify_vault_atlas.py
git commit -m "Add end-to-end verify_vault_atlas smoke script"
```

---

### Task 23: Enable in prod + final verification

**Files:**
- Modify: `config/consensus.yaml`

- [ ] **Step 1: Only after Task 22 succeeds cleanly**, flip the two `enabled: false` flags to `true`:

```yaml
atlas:
  enabled: true
  ...

alfred:
  enabled: true
  ...
```

- [ ] **Step 2: Full test suite must pass**

```bash
python3 -m pytest tests/ -v
```
Expected: 100% pass.

- [ ] **Step 3: Dry-run the engine once**

```bash
python3 -m consensus_engine --dry-run --once
```
Expected: no tracebacks; logs mention `atlas_worker_loop` / `alfred_loop` starting.

- [ ] **Step 4: Commit**

```bash
git add config/consensus.yaml
git commit -m "Enable Atlas + Alfred in production config"
```

- [ ] **Step 5: Push**

```bash
git push
```

---

## Self-Review (done by plan author)

**Spec coverage:**
- Vault markdown format with status badges → Task 11 ✓
- `research_jobs`, `research_sections`, `briefing_runs` schema → Task 1 ✓
- Job queue with leases + coalescing → Tasks 2, 12 ✓
- Per-source `last_good_content` preservation → Tasks 3, 8, 12 ✓
- Staleness skip (cache_days) → Task 12 ✓
- On-alert always refresh analyst → Task 12 (`reason == "alert"` branch) ✓
- Atlas sweep at 8:00 ET → Task 13 ✓
- Alert hook → Task 14 ✓
- Alfred session boundaries via ET → Task 7 ✓
- Alfred outbox state machine → Task 19 ✓
- Alfred holiday + weekend skip → Task 7 + Task 20 ✓
- Discord briefing sender — dedicated channel → Task 17 ✓
- Vault archive of briefings → Task 18 ✓
- Config sections (atlas/alfred/vault) → Task 6 ✓
- Wire into `asyncio.gather` → Task 21 ✓

**Placeholder scan:** None.

**Type consistency:** `enqueue_atlas_job` and `acquire_atlas_lease` signatures match across DB layer (Tasks 2, 14) and Atlas module (Task 12). `upsert_research_section` signature consistent across Tasks 3, 8, 12. `post_briefing` / `_render_briefing` / `_send_discord_briefing` / `_write_vault_briefing` names match between definition (Tasks 16–19) and orchestration (Task 19).

---
