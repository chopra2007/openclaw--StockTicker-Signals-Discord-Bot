# YouTube Transcript Scanner — Work Plan

**Date:** 2026-04-06  
**Repo:** `openclaw--StockTicker-Signals-Discord-Bot`

---

## Requirements Summary

Track configured YouTube channel IDs, detect new videos via RSS (free, no API key), extract auto-generated transcripts, persist them to DB + JSON files, optionally summarize via LLM and post a Discord alert.

**Constraints:**
- Free only — no YouTube Data API key required
- No regression to existing ticker signal pipeline
- Mirror existing scanner patterns (async, rate-limited, try/except isolated)

---

## Technology Decisions

| Concern | Choice | Rationale |
|---------|--------|-----------|
| Channel polling | YouTube RSS feeds (`youtube.com/feeds/videos.xml?channel_id=...`) | Free, no auth, standard Atom XML, already used pattern (Nitter RSS) |
| Transcript extraction | `youtube-transcript-api` PyPI package | Free, no API key, pure Python, handles auto-generated + manual captions, raises `TranscriptsDisabled` / `NoTranscriptFound` for clean error handling |
| Storage | Dedicated `youtube_videos` + `youtube_transcripts` DB tables | Existing `ticker_signals.raw_text` truncates at 2000 chars — transcripts are 10K–100K chars |
| Export format | JSON files in `artifacts/transcripts/` via atomic `.tmp → rename` | Crash-safe; LLM consumers can read independently |
| LLM summarization | Existing OpenRouter integration (reuse `analysis/llm_scorer.py` pattern) | Avoid new dependencies; summarize and optionally post to Discord |
| Discord notification | Optional embed reply when transcript + summary ready | Mirrors Phase 2 follow-up pattern from existing pipeline |
| Integration point | `run_live()` at `main.py:198` — new `asyncio.create_task(youtube_poll_loop(stop_event))` | Consistent with `sec_8k_watcher_loop`, `sec_edgar_polling_loop` |

---

## Acceptance Criteria

1. **[Testable]** New videos from configured `youtube.channel_ids` are discovered within one poll cycle (default 600s).
2. **[Testable]** Each video is stored in `youtube_videos` with a `transcript_status` of `pending → saved/missing/failed`.
3. **[Testable]** `video_id` dedup: reprocessing the same video is idempotent — no duplicate DB rows, no duplicate files.
4. **[Testable]** Transcripts are exported to `artifacts/transcripts/<channel_id>/<video_id>.json` via atomic write.
5. **[Testable]** Missing captions set status `missing` — loop continues without exception.
6. **[Testable]** Scanner is disabled (no-op) when `youtube.enabled: false` in config.
7. **[Testable]** `max_videos_per_channel` (default 3) limits per-cycle processing.
8. **[Testable]** All 3 test files pass (`test_youtube_scanner`, `test_transcript_export`, `test_db_youtube`).
9. **[Testable]** No existing test regression — `pytest tests/ -v` still passes 149+ tests.
10. **[Testable]** LLM summary (when enabled) is stored in `youtube_transcripts.summary_text` and posted as Discord embed.

---

## Implementation Steps

### Step 1 — Install dependency

**File:** `requirements.txt` (add line)

```
youtube-transcript-api>=0.6.3
```

Run: `pip install youtube-transcript-api`

No API key or auth needed.

---

### Step 2 — Config additions

**File:** `config/consensus.yaml`

Add `youtube` block:

```yaml
youtube:
  enabled: false                          # default off until channels configured
  channel_ids: []                         # list of UC... channel IDs
  poll_interval_seconds: 600
  max_videos_per_channel: 3
  preferred_languages: ["en"]
  export_dir: "artifacts/transcripts"
  max_concurrency: 4
  summarize: false                        # LLM summary + Discord notification
```

Access pattern (existing):
```python
cfg.get("youtube.enabled", False)
cfg.get("youtube.channel_ids", [])
```

---

### Step 3 — Database schema

**File:** `consensus_engine/db.py`

Add to `_create_tables()` (after existing `CREATE TABLE` blocks):

```sql
CREATE TABLE IF NOT EXISTS youtube_videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    fetched_at REAL NOT NULL,
    transcript_status TEXT NOT NULL DEFAULT 'pending',
    language TEXT,
    is_auto_generated INTEGER DEFAULT 0,
    export_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_youtube_videos_channel ON youtube_videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_youtube_videos_status ON youtube_videos(transcript_status);
CREATE INDEX IF NOT EXISTS idx_youtube_videos_published ON youtube_videos(published_at);

CREATE TABLE IF NOT EXISTS youtube_transcripts (
    video_id TEXT PRIMARY KEY,
    transcript_text TEXT NOT NULL,
    transcript_hash TEXT NOT NULL,
    summary_text TEXT,
    saved_at REAL NOT NULL
);
```

Add DB helper methods to `ConsensusDB` class:

```python
async def has_video_been_processed(self, video_id: str) -> bool: ...
async def upsert_youtube_video(self, video_id, channel_id, title, published_at, fetched_at) -> None: ...
async def save_youtube_transcript(self, video_id, transcript_text, transcript_hash, summary_text=None) -> None: ...
async def mark_youtube_video_status(self, video_id, status, language=None, is_auto=False, export_path=None) -> None: ...
```

---

### Step 4 — Export utility

**File:** `consensus_engine/utils/transcript_export.py` (new file)

```python
import hashlib, json, os, time
from pathlib import Path

def export_transcript_json(channel_id, video_id, title, published_at,
                           language, is_auto_generated, transcript_text,
                           export_dir="artifacts/transcripts") -> str:
    """Atomically write transcript JSON. Returns final path."""
    out_dir = Path(export_dir) / channel_id
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / f"{video_id}.json"
    tmp_path = final_path.with_suffix(".tmp")
    payload = {
        "channel_id": channel_id,
        "video_id": video_id,
        "title": title,
        "published_at": published_at,
        "language": language,
        "is_auto_generated": is_auto_generated,
        "fetched_at": time.time(),
        "transcript_text": transcript_text,
    }
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(tmp_path, final_path)  # atomic
    return str(final_path)

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
```

---

### Step 5 — Scanner module

**File:** `consensus_engine/scanners/youtube.py` (new file)

Key functions:

```python
async def fetch_channel_videos_rss(session, channel_id, limit) -> list[dict]:
    """Fetch video metadata from YouTube RSS feed. Returns list of {video_id, title, published_at}."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    # Parse Atom XML with feedparser or xml.etree.ElementTree (stdlib, no deps)
    # Extract yt:videoId, title, published fields

async def fetch_transcript(video_id, preferred_languages) -> tuple[str, str, bool]:
    """Fetch transcript via youtube-transcript-api. Returns (text, language, is_auto).
    Raises TranscriptsDisabled / NoTranscriptFound for clean error handling."""
    # Run in executor (blocking library call)
    # YouTubeTranscriptApi.get_transcript(video_id, languages=preferred_languages)
    # Join segments into full text

async def process_video(video_meta: dict, semaphore: asyncio.Semaphore, export_dir: str) -> None:
    """Process one video: dedup, fetch transcript, save, export. Never raises."""
    async with semaphore:
        video_id = video_meta["video_id"]
        if await db.has_video_been_processed(video_id):
            return
        await db.upsert_youtube_video(...)
        try:
            text, lang, is_auto = await fetch_transcript(video_id, preferred_languages)
            h = compute_hash(text)
            path = export_transcript_json(...)
            await db.save_youtube_transcript(video_id, text, h)
            await db.mark_youtube_video_status(video_id, "saved", lang, is_auto, path)
            if cfg.get("youtube.summarize", False):
                summary = await _summarize(text, video_meta["title"])
                await db.save_youtube_transcript(video_id, text, h, summary)
                await _post_discord_summary(video_meta, summary)
        except (TranscriptsDisabled, NoTranscriptFound):
            await db.mark_youtube_video_status(video_id, "missing")
        except Exception as e:
            log.warning("youtube: process_video failed for %s: %s", video_id, e)
            await db.mark_youtube_video_status(video_id, "failed")

async def youtube_scan_once() -> None:
    """One full cycle: poll all channels, process new videos."""
    channel_ids = cfg.get("youtube.channel_ids", [])
    if not channel_ids:
        return
    limit = cfg.get("youtube.max_videos_per_channel", 3)
    concurrency = cfg.get("youtube.max_concurrency", 4)
    export_dir = cfg.get("youtube.export_dir", "artifacts/transcripts")
    semaphore = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        all_videos = []
        for channel_id in channel_ids:
            try:
                videos = await fetch_channel_videos_rss(session, channel_id, limit)
                all_videos.extend(videos)
            except Exception as e:
                log.warning("youtube: RSS fetch failed for %s: %s", channel_id, e)
        await asyncio.gather(*[process_video(v, semaphore, export_dir) for v in all_videos])

async def youtube_poll_loop(stop_event: asyncio.Event) -> None:
    """Background loop. Runs youtube_scan_once() every poll_interval_seconds."""
    if not cfg.get("youtube.enabled", False):
        return
    interval = cfg.get("youtube.poll_interval_seconds", 600)
    log.info("youtube: poll loop started (interval=%ds)", interval)
    while not stop_event.is_set():
        try:
            await youtube_scan_once()
        except Exception as e:
            log.error("youtube: scan cycle error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
```

---

### Step 6 — Main loop integration

**File:** `consensus_engine/main.py`

At the top imports (around line 17):
```python
from consensus_engine.scanners.youtube import youtube_poll_loop
```

In `run_live()` (after line 199, alongside other loop tasks):
```python
asyncio.create_task(youtube_poll_loop(stop_event)),
```

---

### Step 7 — Tests

**File:** `tests/test_youtube_scanner.py`
- RSS parse: valid XML → correct video_id/title/published_at extraction
- RSS parse: malformed feed → empty list, no exception
- Dedup: calling `process_video` twice for same `video_id` → second call is no-op
- Missing captions: `NoTranscriptFound` raised → status set to `missing`, no exception propagated

**File:** `tests/test_transcript_export.py`
- Atomic write: verify `.tmp` file is replaced, not left behind
- Path format: `{export_dir}/{channel_id}/{video_id}.json`
- JSON payload contract: all required keys present with correct types
- Deterministic hash: same text → same hash

**File:** `tests/test_db_youtube.py`
- Schema creation: tables and indexes exist after `init_db()`
- `has_video_been_processed`: returns False for unknown, True after upsert
- `mark_youtube_video_status`: upsert → mark → verify status column
- Idempotency: double upsert does not raise

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| YouTube blocks RSS scraping | RSS feeds are public/unauthenticated Atom; no auth needed — same as Nitter RSS pattern |
| `youtube-transcript-api` breaks on YouTube changes | Library is actively maintained; pin version in requirements.txt; status `failed` keeps loop alive |
| Transcript size inflates SQLite | Separate `youtube_transcripts` table; full text stored once with hash; add optional compression later |
| Channel list grows, loop time increases | `max_concurrency` semaphore + `max_videos_per_channel` cap bounds each cycle |
| Partial write on crash | Atomic `.tmp → os.replace` pattern |
| Auto-captions delayed (not available immediately after upload) | Status `missing` is retried next cycle — `pending` is only the initial insert state |

---

## Verification Steps

1. `pip install youtube-transcript-api && python -c "from youtube_transcript_api import YouTubeTranscriptApi; print('ok')"` — confirms install
2. `python -m pytest tests/test_youtube_scanner.py tests/test_transcript_export.py tests/test_db_youtube.py -v` — all pass
3. `python -m pytest tests/ -v` — no regression (149+ existing tests still pass)
4. Configure 1 channel in `consensus.yaml`, set `enabled: true`, run `--once` mode, verify:
   - `youtube_videos` rows exist in DB with `transcript_status IN ('saved','missing')`
   - JSON files exist in `artifacts/transcripts/<channel_id>/`
5. Run with `enabled: false` — confirm zero DB writes, zero file writes

---

## Rollout Strategy

- **Phase 1 (this plan):** Schema + scanner + export + tests. Default `enabled: false`.
- **Phase 2:** Enable for 1 channel, verify status transitions and file output.
- **Phase 3:** Enable `summarize: true`, add LLM summary + Discord notification.
- **Phase 4:** Scale channel list, add pruner for old transcripts (> 30 days).

---

## Definition of Done

- [ ] `youtube-transcript-api` in `requirements.txt`
- [ ] `youtube` config block in `consensus.yaml` (`enabled: false` default)
- [ ] `youtube_videos` + `youtube_transcripts` tables created in `db.py`
- [ ] DB helper methods implemented and tested
- [ ] `consensus_engine/utils/transcript_export.py` implemented with atomic write
- [ ] `consensus_engine/scanners/youtube.py` implemented with all 4 functions
- [ ] `youtube_poll_loop` wired into `run_live()` in `main.py`
- [ ] All 3 test files pass
- [ ] No regression in existing 149+ tests
- [ ] Plan committed and pushed
