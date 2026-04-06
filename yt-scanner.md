# YouTube Transcript Pipeline — Implementation Plan

Date: 2026-04-06  
Repo: `openclaw--StockTicker-Signals-Discord-Bot`

## Objective

Implement a robust YouTube transcript ingestion pipeline that:

1. tracks configured YouTube channel IDs,
2. detects new videos via RSS/API,
3. fetches auto-generated captions/transcripts,
4. persists transcript artifacts reliably for downstream LLM summarization.

This document focuses on **failure modes, correctness risks, and optimization opportunities** before implementation.

---

## Adversarial Review (Current Codebase)

### A) Architectural mismatch risk: market-signal path vs transcript-content path

The current pipeline and models center on short-lived ticker signals, not large document ingestion.

- `TickerSignal.raw_text` is truncated to 2000 chars at DB insert.
- Transcripts can be tens of thousands of characters.

**Risk:** data loss if transcripts are routed through existing ticker signal storage.

**Decision:** transcripts must use dedicated tables + file export, not `ticker_signals`.

---

### B) Missing source type semantics for YouTube content

`SourceType` currently includes social/news/SEC/tweet sources only.

**Risk:** forcing YouTube into existing source enums can confuse cross-reference scoring and downstream logic.

**Decision:** keep transcript ingestion out of score-related signal flow; add dedicated DB entities and background loop.

---

### C) No existing idempotency contract for video-level processing

There is no table for `video_id` tracking today.

**Risk:** duplicate polling cycles repeatedly process/export the same videos, creating redundant files and unnecessary API load.

**Decision:** enforce `video_id` primary key + explicit processing states (`pending`, `missing`, `saved`, `exported`, `failed`).

---

### D) Timestamp and ordering ambiguity from feeds

YouTube RSS timestamps can drift and feeds may reorder items.

**Risk:** “last seen timestamp” only approaches can skip videos or process duplicates.

**Decision:** use `video_id` as truth for dedupe; timestamps are metadata only.

---

### E) Captions availability is non-deterministic

Some videos have:

- no captions,
- delayed auto-captions,
- captions in languages not requested.

**Risk:** hard-fail behavior blocks entire scan loop.

**Decision:** mark per-video status and continue; scanner loop must never crash on caption absence.

---

### F) Export consistency risk

Direct writes to final path can leave partial JSON during crashes.

**Risk:** downstream LLM consumers read corrupted/incomplete files.

**Decision:** atomic write (`.tmp` -> rename) and idempotent export flags in DB.

---

### G) Throughput/rate-limit risk

Channel count can grow; naive serial fetches increase runtime and ban risk.

**Risk:** long loop times, stale ingestion, provider throttling.

**Decision:** bounded concurrency with semaphore + small jitter + explicit per-provider rate-limit buckets.

---

### H) Content bloat risk

Large transcripts inflate SQLite and disk usage.

**Risk:** storage bloat and slower query performance.

**Decision:** persist full transcript once, add transcript hash, optional compression later, and retain metadata indexes.

---

## Clean Final Implementation (Single Unified Design)

## 1) Config additions

Add a single `youtube` block in `config/consensus.yaml`:

```yaml
youtube:
  enabled: true
  channel_ids: []
  poll_interval_seconds: 600
  max_videos_per_channel: 3
  preferred_languages: ["en"]
  export_dir: "artifacts/transcripts"
  rss_only: true
  max_concurrency: 4
```

Add optional API key:

```yaml
api_keys:
  youtube_data: "$YOUTUBE_DATA_API_KEY"
```

---

## 2) Database schema

Add two tables in `consensus_engine/db.py` schema:

### `youtube_videos`
- `video_id TEXT PRIMARY KEY`
- `channel_id TEXT NOT NULL`
- `title TEXT`
- `published_at TEXT`
- `fetched_at REAL NOT NULL`
- `transcript_status TEXT NOT NULL` (`pending|missing|saved|exported|failed`)
- `language TEXT`
- `is_auto_generated INTEGER DEFAULT 0`
- `export_path TEXT`

Indexes:
- `idx_youtube_videos_channel`
- `idx_youtube_videos_status`
- `idx_youtube_videos_published`

### `youtube_transcripts`
- `video_id TEXT PRIMARY KEY`
- `transcript_text TEXT NOT NULL`
- `transcript_hash TEXT NOT NULL`
- `saved_at REAL NOT NULL`

Add DB methods:
- `has_video_been_processed(video_id)`
- `upsert_youtube_video(...)`
- `save_youtube_transcript(...)`
- `mark_youtube_video_status(video_id, status, ...)`

---

## 3) Scanner module

Create `consensus_engine/scanners/youtube.py` with these responsibilities:

1. `fetch_channel_videos_rss(channel_id, limit)`
2. `fetch_transcript(video_id, preferred_languages)`
3. `process_video(video)`
4. `youtube_scan_once()`

Implementation notes:
- RSS-first discovery.
- `video_id` dedupe first.
- Per-video try/except isolation.
- Bounded concurrency (`asyncio.Semaphore`).
- Structured logs with channel/video IDs.

---

## 4) Export utility

Create `consensus_engine/utils/transcript_export.py`:

- `export_transcript_json(video_meta, transcript, export_dir) -> path`
- ensure parent dirs exist,
- write temp file then `os.replace`.

Export schema:

```json
{
  "channel_id": "UC...",
  "video_id": "abc123",
  "title": "...",
  "published_at": "2026-04-06T10:00:00Z",
  "language": "en",
  "is_auto_generated": true,
  "fetched_at": 1770000000,
  "transcript_text": "..."
}
```

---

## 5) Main loop integration

In `consensus_engine/main.py`, add:

- `youtube_poll_loop(stop_event)`
- include task in `run_live()` task list.

Loop behavior:
- If `youtube.enabled` false: no-op.
- Call `youtube_scan_once()` each interval.
- Never raise uncaught exceptions out of loop.

---

## 6) Reliability guardrails

- All network operations use timeout and retry with backoff.
- Missing captions set status `missing` (not error).
- Non-retryable parser errors set status `failed` and continue.
- Duplicate video IDs must be idempotent.

---

## 7) Performance optimizations

- Deduplicate before transcript fetch.
- Limit items per channel per cycle.
- Bounded concurrency for transcript pulls.
- Optional future optimization: content hash check to skip no-change writes.

---

## 8) Test plan (must pass before rollout)

Create tests:

1. `tests/test_youtube_scanner.py`
   - RSS parse success + malformed feed
   - dedupe on existing `video_id`
   - status transitions for missing captions

2. `tests/test_transcript_export.py`
   - atomic write behavior
   - deterministic path format
   - JSON payload contract

3. `tests/test_db_youtube.py`
   - schema creation
   - upsert/mark/save methods
   - idempotency checks

4. Integration smoke
   - mock scanner cycle with 2 channels, mixed caption availability

---

## 9) Rollout strategy

Phase 1: schema + config + scanner behind `youtube.enabled=false` default.  
Phase 2: enable for 1 channel, verify status transitions + file exports.  
Phase 3: scale channel list and monitor loop duration, failures, disk growth.

---

## 10) Definition of done

- New videos from configured channels are discovered and deduped.
- Transcripts (when available) saved in DB and exported as JSON files.
- Missing-captions/videos are handled without loop failure.
- Tests for parser/db/export pass.
- No regression to existing live tasks.
