# YouTube description fetch + storage — yt-grounding follow-up

> **STATUS: IMPLEMENTED — PR #13 merged at commit `00cdda1` on 2026-04-28.**
>
> This document is the original implementation spec. Two deviations from spec landed during execution:
>
> 1. **`upsert_youtube_video` uses `INSERT OR IGNORE`, NOT `INSERT OR REPLACE`** as section (c) shows. Worker-1 picked the safer pattern: existing rows are never touched on re-poll, preserving `transcript_status` / `language` / `is_auto_generated` / `export_path` processing state. Side effect — see [ADVERSARIAL_REVIEW.md](ADVERSARIAL_REVIEW.md) Finding #2: existing 69 videos with `description=NULL` will *not* be enriched on re-poll. New videos get descriptions immediately. A separate refresh-script PR would be needed if historical enrichment becomes operationally important; not done because operational impact is small.
>
> 2. **Two test fixtures patched** during execution (`tests/test_backfill_youtube_grounding.py`, `tests/test_backfill_rollback.py`) — their hand-rolled `youtube_videos` schemas didn't include the new `description` column and were crashing with `no such column: description`. Fix landed in commit `51fdcfd` alongside the scanner edits.
>
> Trust-level caveat (Adversarial Review Open Question): description text is now an allowlist grounding pool material, treated equally with title. Documented as a one-paragraph caveat on `build_video_allowlist`'s docstring at `consensus_engine/analysis/ticker_grounding.py:143-156`. Sponsor copy and watchlist dumps in descriptions can broaden the allowlist — Layers 2 (per-span quote) and 4 (price-sanity) remain the deeper safety nets.

**Date:** 2026-04-28
**Branch target:** `feat/yt-description-fetch` (already created)
**Predecessor PR:** #12 (yt-grounding 5-layer hallucination defense)

**Sizing:** TINY (~70 LOC + ~40 test LOC).

---

## Why this exists

PR #12 deliberately scoped *out* description-fetching because (a) it required a DB migration and the hallucination fix carved off "no migrations" for scope discipline, and (b) the title-only allowlist was already sufficient to neutralize the `vkqchQQnm88` incident. After ship, the global-backfill dry-run revealed the predicted false-positive rate: 6 of the 7 flagged videos had generic titles ("This Rally Is Not Normal", "Top 5 Stocks NOW") where legitimate ticker mentions cannot be grounded against title alone, and Path-B-only videos have no spans to fall back on.

Adding `description` as an allowlist pool material:
- Recovers the discriminating power that title-alone lacks for market-recap / list-format videos.
- Lets a future global backfill safely catch real hallucinations without drowning in false positives.
- Is a one-column schema change — the smallest migration possible.

---

## Problem (recap)

For Path B-only videos, `build_video_allowlist` currently has only the YouTube **title** to ground candidate tickers. Most finance YouTube titles are clickbait/generic — they don't enumerate the tickers discussed inside. The video's textual `description` (already present on YouTube alongside the video) typically does, especially for list-style and recap videos. Operators currently must skip global backfill because of the precision/recall tradeoff title-only forces.

---

## RALPLAN-DR Summary

### Principles
1. **Smallest migration possible** — one nullable text column with a `DEFAULT NULL`. Idempotent additive-only ALTER.
2. **No new HTTP calls** — reuse the existing RSS Atom feed already fetched in `fetch_channel_videos_rss`.
3. **Preserve the grounding contract** — `build_video_allowlist` re-gains its original 4-arg signature dropped in iter-1 of PR #12; backfill restores description into the evidence pool.
4. **Backwards compatible** — videos already in DB with `description=NULL` are treated identically to today (allowlist falls back to title + spans).

### Decision Drivers (top 3)
1. Recover precision on the 6 false-positive videos from the global-backfill dry-run.
2. Single-column migration — must be safely re-runnable, must not require backfilling old rows.
3. ~70 LOC implementation + 1 follow-up backfill cycle to enrich existing rows with descriptions when each video is next polled (or never — `NULL` is fine; new videos benefit immediately).

### Viable Options

**Option A (chosen): RSS `<media:group>/<media:description>` parse + DB column.**
- The Atom feed already fetched at `youtube.py:35-77` contains a `<media:description>` element under the `media` namespace (`http://search.yahoo.com/mrss/`). Zero extra HTTP calls. Roughly the first ~500 chars of the video's description (RSS truncates).
- Pros: free; idempotent; matches existing parser pattern.
- Cons: RSS truncates description (~5KB cap historically); does NOT contain pinned-comment text that some channels use for ticker lists.

**Option B: YouTube oEmbed API.**
- `https://www.youtube.com/oembed?url=<video_url>` returns `title` and `author_name` only — NOT description. Rejected: doesn't actually return description.

**Option C: Scrape the video page via the existing Playwright stealth browser.**
- Pros: full description, sometimes including pinned comment.
- Cons: extra browser round-trip per video (the bot already opens a stealth browser per scan cycle, but transcript extraction is the cost-driver); much heavier than RSS parse; failure modes (description loaded lazily) need engineering.
- Rejected for this PR; viable as a future enhancement layered on top of Option A.

**Option D: YouTube Data API v3.**
- Pros: structured, no scraping.
- Cons: requires an API key + quota management; goes against the "no API key, no cookies, no maintenance" rationale codified in `youtube.py:7-10`. Rejected.

### Pre-mortem

1. **RSS truncates description and we get insufficient ticker mentions.** Mitigation: keep title + spans + (now) description in the pool; when description is short or empty, behaviour is identical to today. Failure mode is graceful — same false-positive rate as PR #12 in the worst case.
2. **Existing rows have `description=NULL`; old videos can't be backfilled retroactively.** Mitigation: documented and accepted. Operator who cares about historical accuracy can re-poll the channels (RSS is idempotent and cheap), or write a one-shot rebuild script as a separate follow-up. Out of scope here.
3. **Migration runs while the engine is live.** Mitigation: `ALTER TABLE youtube_videos ADD COLUMN description TEXT` is non-blocking on SQLite for a small table (~thousands of rows in this codebase). The pattern already used at `db.py:562-563` for the `suppressed`/`suppression_reason` columns is identical and proven safe in this engine.

---

## Implementation

### (a) DB column

**File:** `consensus_engine/db.py`

In the `youtube_videos` `CREATE TABLE` statement (around line 160-170), add the column:

```diff
 CREATE TABLE IF NOT EXISTS youtube_videos (
     video_id TEXT PRIMARY KEY,
     channel_id TEXT NOT NULL,
     title TEXT,
+    description TEXT,
     published_at TEXT,
     fetched_at REAL NOT NULL,
     transcript_status TEXT NOT NULL DEFAULT 'pending',
     language TEXT,
     is_auto_generated INTEGER DEFAULT 0,
     export_path TEXT
 );
```

For idempotent migration of existing DBs (since `CREATE TABLE IF NOT EXISTS` is a no-op when the table already exists), use the same `_ensure_columns(table, [...])` pattern used at `db.py:562-563`. Add to the existing migration block:

```python
await _ensure_columns(conn, "youtube_videos", [
    ("description", "TEXT"),
])
```

Place this near the other migration calls so it runs at every `init_db()`.

**LOC delta:** +5 (1 new column line in CREATE + 3 lines in `_ensure_columns` block + 1 import if needed).

### (b) RSS parser

**File:** `consensus_engine/scanners/youtube.py`

Add the `media` namespace constant near the existing `_ATOM_NS` and `_YT_NS` constants:

```python
_MEDIA_NS = "http://search.yahoo.com/mrss/"
```

Update `fetch_channel_videos_rss` to extract description from the `<media:group>/<media:description>` path inside each entry:

```diff
     for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
         video_id_el = entry.find(f"{{{_YT_NS}}}videoId")
         title_el = entry.find(f"{{{_ATOM_NS}}}title")
         published_el = entry.find(f"{{{_ATOM_NS}}}published")
+        media_group = entry.find(f"{{{_MEDIA_NS}}}group")
+        description = ""
+        if media_group is not None:
+            desc_el = media_group.find(f"{{{_MEDIA_NS}}}description")
+            if desc_el is not None and desc_el.text:
+                description = desc_el.text
         if video_id_el is None:
             continue
         videos.append({
             "video_id": video_id_el.text or "",
             "channel_id": channel_id,
             "title": (title_el.text or "") if title_el is not None else "",
+            "description": description,
             "published_at": (published_el.text or "") if published_el is not None else "",
         })
```

**LOC delta:** +9.

### (c) Persist description

**File:** `consensus_engine/db.py`

Update `upsert_youtube_video` to accept and persist `description`:

```diff
 async def upsert_youtube_video(
     video_id: str,
     channel_id: str,
     title: str,
     published_at: str,
     fetched_at: float,
+    description: str = "",
 ) -> None:
     conn = await get_db()
     await conn.execute(
-        "INSERT OR REPLACE INTO youtube_videos (video_id, channel_id, title, published_at, fetched_at) "
-        "VALUES (?, ?, ?, ?, ?)",
-        (video_id, channel_id, title, published_at, fetched_at),
+        "INSERT OR REPLACE INTO youtube_videos (video_id, channel_id, title, description, published_at, fetched_at) "
+        "VALUES (?, ?, ?, ?, ?, ?)",
+        (video_id, channel_id, title, description, published_at, fetched_at),
     )
     await conn.commit()
```

Update `get_youtube_video` to include description in the returned row:

```diff
 async def get_youtube_video(video_id: str) -> dict | None:
     conn = await get_db()
     cur = await conn.execute(
-        "SELECT video_id, channel_id, title, published_at FROM youtube_videos WHERE video_id = ?",
+        "SELECT video_id, channel_id, title, description, published_at FROM youtube_videos WHERE video_id = ?",
         (video_id,),
     )
     row = await cur.fetchone()
     return dict(row) if row else None
```

**LOC delta:** +4 (signature, INSERT, SELECT).

### (d) Plumb into scanner

**File:** `consensus_engine/scanners/youtube.py`

Update the `process_video` call to `upsert_youtube_video` to forward the new field:

```diff
         await db.upsert_youtube_video(
             video_id=video_id,
             channel_id=channel_id,
             title=video_meta["title"],
+            description=video_meta.get("description", ""),
             published_at=video_meta["published_at"],
             fetched_at=time.time(),
         )
```

**LOC delta:** +1.

### (e) Restore allowlist signature

**File:** `consensus_engine/analysis/ticker_grounding.py`

Re-add `video_description` parameter to `build_video_allowlist` (PR #12 dropped it because there was no source). Default to empty string for backwards compatibility:

```diff
 def build_video_allowlist(
     video_title: str,
+    video_description: str = "",
     span_quotes: list[str] | None = None,
     extra_texts: list[str] | None = None,
     candidate_tickers: list[str] | None = None,
 ) -> set[str]:
     """Build the set of tickers acceptably grounded in this video's evidence.

     A ticker is in the allowlist if it is grounded (literal or alias match) in
-    any of: title, any span quote, any extra text.
+    any of: title, description, any span quote, any extra text.
     ...
     """
     if not candidate_tickers:
         return set()
-    pool = [video_title or ""]
+    pool = [video_title or "", video_description or ""]
     pool.extend(q for q in span_quotes or [] if q)
     if extra_texts:
         pool.extend(t for t in extra_texts if t)
     ...
```

**LOC delta:** +3.

### (f) Plumb description into both allowlist call sites

**File:** `consensus_engine/scanners/youtube.py`

In `_process_video_two_stage`, pass the description from the DB lookup:

```diff
     video_meta_row = await db.get_youtube_video(video_id)
     title = video_meta_row.get("title", "") if video_meta_row else ""
+    description = video_meta_row.get("description", "") if video_meta_row else ""
     ...
     allowlist = build_video_allowlist(
         video_title=title,
+        video_description=description,
         span_quotes=span_quotes,
         candidate_tickers=list(candidate_set),
     )
```

In the legacy persist block, pass description from `video_meta`:

```diff
     allowlist = build_video_allowlist(
         video_title=title,
+        video_description=video_meta.get("description", ""),
         span_quotes=evidence_texts,
         candidate_tickers=list(candidate_set),
     )
```

**LOC delta:** +4.

### (g) Backfill script — restore description in evidence pool

**File:** `scripts/backfill_youtube_grounding.py`

`_evidence_pool_for_video` currently fetches title + spans only. Add description:

```diff
     title_row = await (await conn.execute(
-        "SELECT title FROM youtube_videos WHERE video_id = ?", (video_id,)
+        "SELECT title, description FROM youtube_videos WHERE video_id = ?", (video_id,)
     )).fetchone()
     title = title_row["title"] if title_row else ""
+    description = title_row["description"] if title_row else ""

     pool: list[str] = []
+    if description:
+        pool.append(description)
     cur = await conn.execute(
         "SELECT quote FROM youtube_evidence_spans WHERE video_id = ?", (video_id,)
     )
     pool.extend(r["quote"] for r in await cur.fetchall())

     return title, pool
```

This adds description as a trustworthy ground (it's YouTube metadata, not LLM-generated) — same trust class as title. The Path-B-context exclusion principle from PR #12's hotfix `3325bb2` is preserved.

**LOC delta:** +5.

---

## Tests

### `tests/scanners/test_youtube_rss.py` — new (~25 LOC)

Test RSS parser extracts description from a fixture XML containing `<media:group><media:description>` element.

```python
import pytest
from consensus_engine.scanners.youtube import fetch_channel_videos_rss

# Use aiohttp test fixtures or monkeypatch session.get to return canned XML.
# Assert returned dict includes "description" key with expected text.
```

### `tests/analysis/test_ticker_grounding.py` — extend (~15 LOC)

Add a test that confirms description is consulted in the allowlist:

```python
def test_allowlist_uses_description():
    allow = ticker_grounding.build_video_allowlist(
        video_title="Top 5 Stocks NOW",
        video_description="Stocks discussed: $AAPL, $MSFT, $TSLA. Don't miss this one!",
        span_quotes=[],
        candidate_tickers=["AAPL", "MSFT", "TSLA", "NVDA"],
    )
    assert allow == {"AAPL", "MSFT", "TSLA"}
    assert "NVDA" not in allow  # not in title or description
```

---

## Verification

```bash
# Migration is idempotent
python3 -c "import asyncio; from consensus_engine import db; asyncio.run(db.init_db())"
sqlite3 consensus.db "PRAGMA table_info(youtube_videos);" | grep description
# Expected: <ordinal>|description|TEXT|0||0

# Tests pass
python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5

# Functional smoke
python3 -c "
import asyncio
from consensus_engine.scanners.youtube import fetch_channel_videos_rss
import aiohttp

async def go():
    async with aiohttp.ClientSession() as s:
        # MeetKevin's channel as a known-public test target
        videos = await fetch_channel_videos_rss(s, 'UCUvvj5lwue7PspotMDjk5UA', 1)
        for v in videos:
            print(v['video_id'], 'title=', v['title'][:60], 'desc_len=', len(v.get('description','')))

asyncio.run(go())
"
# Expected: at least one row with desc_len > 0

# After deploy (engine restart), the next polled video gets description persisted
sqlite3 consensus.db "SELECT video_id, length(description) FROM youtube_videos WHERE description IS NOT NULL ORDER BY fetched_at DESC LIMIT 5;"

# Once a few new videos have descriptions, re-run backfill dry-run on the false-positive set
python3 scripts/backfill_youtube_grounding.py --dry-run --video ZdNS_5eND7E
# Should now narrow off_allowlist substantially (NVDA / SMH / SPY etc. likely retained
# if they appear in the description, suppression-only-on-true-hallucinations).
```

---

## Acceptance

- [ ] `youtube_videos.description` column exists; migration runs idempotently on a fresh DB and on an upgrade-in-place DB.
- [ ] RSS parser populates `description` on new fetches.
- [ ] `build_video_allowlist` accepts `video_description=""` (backwards compatible) and uses it as a grounding pool.
- [ ] Both Path A and Path B/C call sites pass description.
- [ ] Backfill script includes description in the trustworthy-evidence pool.
- [ ] All existing tests still pass (700+1 skip baseline from PR #12).
- [ ] New tests pass: RSS parser extracts description; allowlist uses description.
- [ ] After engine restart and one full poll cycle, at least one new `youtube_videos` row has a non-empty description.

---

## Out of scope

- Backfilling description for already-persisted videos (operator can re-poll channels; idempotent).
- Pinned-comment scraping (Option C; future enhancement).
- YouTube Data API v3 integration (Option D; rejected on key/quota grounds).
- Adjusting allowlist precision thresholds — title+description+spans is enough for the false-positive videos identified post-PR-#12.

---

## Sizing total

- Implementation: ~31 LOC
- Tests: ~40 LOC
- Migration: 1 column, idempotent
- Effort: half-day

Single PR. No risk to live service beyond the migration runtime (sub-second on this DB size).