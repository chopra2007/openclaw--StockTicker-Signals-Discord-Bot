# Final Plan: Week 2 + Bug Triage

## Context

All 6 OPEN_QUESTIONS.md answers are in. The adversarial review found 9 ranked issues. Most dangerous: (1) video_parser crashes on valid LLM output due to enum mismatch, (2) reliability engine silently missing, (3) precision engine not actually the decision-maker despite Q2 resolving that it should replace cross_reference. These must be fixed before any new Week 2 feature lands.

---

## Phase 0: Critical Bug Fixes (no new features ship until these are done)

### 0a. Fix video_parser macro direction enum mismatch
**File:** `consensus_engine/analysis/video_parser.py:538-544`

LLM prompt (`_SYSTEM_PROMPT` line 54) asks for `bullish|bearish|neutral`.
`Direction` enum (`models.py:180-183`) only accepts `long|short|neutral`.
Chunk merge at line 422 uses `long/short/neutral` keys — so even the intermediate vote is broken.

**Fix:** Add normalization before constructing `Direction`:
```python
_MACRO_NORM = {"bullish": "long", "bearish": "short", "neutral": "neutral"}
raw_dir = macro_data.get("direction", "neutral").lower()
direction = Direction(_MACRO_NORM.get(raw_dir, "neutral"))
```
Also update the chunk merge dict keys at line 422 to accept `bullish/bearish/neutral` by running the same normalization on each chunk's direction value before tallying votes.

Either also update the system prompt to say `long|bearish|neutral` to match the enum, or keep normalizing — normalizing is more defensive given the LLM is free-form.

### 0b. Gate reliability engine behind config flag
**File:** `consensus_engine/cross_reference.py:322-371`

Modules `consensus_engine.analysis.reliability_engine` and `consensus_engine.analysis.snapshot_builder` do not exist. The broad `except Exception` at line 369 silently swallows the ImportError every call.

**Fix:** Check the flag before attempting the import. Log at WARNING level on startup (not DEBUG) when the path is enabled but modules are absent.
```python
if cfg.get("alerts.reliability_engine_enabled", False):
    try:
        from consensus_engine.analysis.reliability_engine import ...
        ...
    except ImportError as exc:
        log.warning("reliability engine enabled but not installed: %s", exc)
```
Default `alerts.reliability_engine_enabled = false` in config. This makes the absence visible instead of silent.

### 0c. Precision engine as the decision-maker
**Files:** `consensus_engine/main.py:541-574`

Q2 answer: precision engine replaces cross_reference. Currently both run in parallel and all downstream decisions (follow-up, breakdown persistence, alert suppression) use `xref`.

**Fix (pragmatic transition — full removal is Week 6):**
- After `asyncio.gather`, if `precision` result is non-null and not skipped:
  - Use `precision["classification"]` to gate alert suppression (`IGNORE` → skip follow-up)
  - Still call `send_detail_followup(xref, ...)` for enrichment/formatting (xref stays as an explanation layer)
  - Persist precision's `classification` in `alert_breakdown` alongside xref score
- `cross_reference` output continues to fill `breakdown`, `technical`, `other_analysts`, `catalyst` fields (it's still useful for detail formatting)
- Log clearly when precision overrides xref: `"$%s: precision=%s overrides xref_score=%.1f"`

This is minimal: precision gates the decision, xref enriches the detail. Full deprecation of xref is Week 6.

### 0d. Fix channel_id stored as channel_name
**File:** `consensus_engine/scanners/youtube.py:247, 267, 287`

All three calls pass `channel_id` (e.g. `UCxxxxxx`) to the `channel_name` parameter.

**Fix for now:** Pass the channel display name from `video_meta` if available. The RSS feed returns the channel name as part of the entry (author field). Check if `video_meta` already carries a display name; if so, use it. If not, use `channel_id` but rename internally to `channel_id` field until the registry (Phase 2) is in place. Document the gap clearly in a `# TODO` comment rather than silently using the wrong value.

---

## Phase 1: Test Suite Correctness

### 1a. Fix wrong patch target in scanner tests
**File:** `tests/test_youtube_scanner.py:115-131`

Patches `consensus_engine.scanners.youtube.fetch_transcript`, but real code imports `fetch_transcript_cascade` from `consensus_engine.utils.transcript_fetch`.

**Fix:** Change mock target to `consensus_engine.utils.transcript_fetch.fetch_transcript_cascade`.

### 1b. Add video_parser unit tests
**File:** `tests/test_video_parser.py` (new file)

Needed tests:
1. Prompt-compliant LLM JSON with `bullish`/`bearish` → parses to `Direction.LONG`/`Direction.SHORT`
2. Mixed chunk directions → correct majority vote after normalization
3. Invalid macro direction (`"sideways"`) → falls back to `neutral`
4. Empty / null LLM output → returns empty `ParsedVideo`, no exception
5. `finish_reason=length` response → explicit log + handled gracefully (see Phase 3 hygiene)
6. Transcript length gate (short transcript → skips chunking)

---

## Phase 2: Channel Registry

### 2a. Add `youtube_channels` table
**File:** `consensus_engine/db.py`

Schema:
```sql
CREATE TABLE IF NOT EXISTS youtube_channels (
    channel_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 1,
    trust_score REAL NOT NULL DEFAULT 1.0,
    added_at TEXT DEFAULT (datetime('now'))
);
```

Populate from `sources.json` (already the approval list). All approved channels seed at `trust_score = 1.0` per Q3 answer.

### 2b. Channel lookup in scanner
**File:** `consensus_engine/scanners/youtube.py:247`

Replace raw `channel_id` pass with a `db.get_channel_display_name(channel_id)` lookup that returns the display name from `youtube_channels`, falling back to `channel_id` if not found (with a WARNING log for unapproved channels).

### 2c. Trust gate for standalone alerts (Phase 3 dependency)
A helper `db.get_channel_trust(channel_id) -> float` returns `trust_score` from the registry. Used by standalone alert trigger in Phase 3.

---

## Phase 3: Week 2 Features

### 3a. `youtube_macro` table
**File:** `consensus_engine/db.py`

Schema (from ytplan.md lines 144-156):
```sql
CREATE TABLE IF NOT EXISTS youtube_macro (
    id INTEGER PRIMARY KEY,
    video_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    themes TEXT,          -- JSON array
    timeframe TEXT,
    summary TEXT,
    confidence REAL DEFAULT 0.5,
    published_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

Write macro_thesis from parser output in `scanners/youtube.py` (after the existing `insert_youtube_signal` calls), only when `parsed.macro_thesis` is non-null.

### 3b. Standalone YouTube alerts
**File:** `consensus_engine/scanners/youtube.py` (after parser runs)

Trigger conditions:
- `parsed.overall_conviction == Conviction.HIGH`
- At least one ticker with `direction != neutral`
- `db.get_channel_trust(channel_id) >= cfg.get("youtube.min_trust", 0.5)`

Alert format: `🎬 YouTube Signal: $TICKER [LONG/SHORT] — {channel_display_name}`
Send via existing `discord.send_alert()`. Config key: `youtube.standalone_alerts` (default: `true`).

### 3c. Discord commands
**File:** `consensus_engine/alerts/commands.py`

Three new commands:

**`!yt <URL>`**
1. Extract video ID from URL
2. Fetch metadata via oEmbed (`https://www.youtube.com/oembed?url=<url>&format=json`) — gets title + channel name
3. If transcript not already in DB, run `fetch_transcript_cascade(video_id)` then `parse_video_transcript()`
4. Reply with parsed tickers, conviction, macro direction, levels found

**`!yt-mentions $TICKER`**
Query `youtube_signals WHERE ticker = ? AND published_at > datetime('now', '-7 days')` ordered by conviction, return top 5 as formatted list.

**`!macro`**
Query `youtube_macro` last 7 days, group by direction, return top 3 themes + direction breakdown. Format: `📊 Macro Digest: BULLISH (4 channels) / BEARISH (2) / NEUTRAL (1) — Top themes: X, Y, Z`

### 3d. Daily macro digest (6 AM M-F)
**File:** `consensus_engine/main.py` or new `consensus_engine/schedulers/macro_digest.py`

Add a background loop that:
- Checks if current UTC time is 11:00 (6 AM ET) on a weekday
- Runs the same `!macro` query
- Posts to Discord `#alerts` channel
- Uses a last-sent timestamp in DB or a simple file flag to prevent duplicate posts within the same day

Config key: `youtube.macro_digest_utc_hour` (default: 11, i.e. 6 AM ET).

### 3e. Level proximity alerter
**File:** `consensus_engine/main.py` or `consensus_engine/scanners/youtube.py`

Run on every tweet poll cycle (per Q4). For each level in `youtube_levels` (last 14 days), fetch current price. If `abs(current_price - level.price) / level.price < cfg.get("youtube.level_alert_proximity_pct", 0.005)`:
- Post Discord alert: `🎯 $TICKER approaching {level_type} @ {level.price} (flagged by {channel} {N} days ago)`
- Record alert in a `youtube_level_alerts` table with cooldown — suppress re-firing same level within 4 hours

---

## Phase 4: Hygiene

### 4a. Atomic budget management
**File:** `consensus_engine/engine.py:72-116`

Collapse `can_consume()` + `consume()` two-step into a single atomic SQL:
```sql
UPDATE api_usage_daily
SET {col} = {col} + ?
WHERE day_utc = ? AND {col} + ? <= ?
```
Check `rowcount`. If 0 rows updated, budget exceeded — return `False`. Eliminates TOCTOU race under concurrent `analyze_signal()` tasks.

### 4b. Close aiohttp session on daemon exit
**File:** `consensus_engine/main.py` (shutdown path) + `consensus_engine/utils/http.py`

`close_session()` is defined but never called. Add call in the daemon teardown / signal handler path.

### 4c. Handle `finish_reason=length`
**File:** `consensus_engine/analysis/video_parser.py:122-160`

After parsing `data["choices"][0]`, check `finish_reason`. If `"length"`:
- Log at WARNING: `"video_parser: response truncated for video_id=%s, retrying with fewer tokens"`
- Retry once with `max_tokens` halved and transcript chunk reduced by 25%
- If retry also truncated, log ERROR and return partial result (don't crash)

---

## Phase 5: Roadmap & Doc Reconciliation

Update `plans/ROADMAP.md`:
1. Mark all 6 open questions as resolved and move them to a `## ✅ Resolved Decisions` section
2. Change precision engine section from "Independent track / open question" to `## ✅ Precision-First Decision Engine (ACTIVE)` — state it's the gating layer, cross_reference is enrichment
3. Update Week 2 task list to reflect what's actually already implemented vs. what's in this plan
4. Add a `## Current Decision Architecture` section at the top:
   > "Precision engine gates suppression/alert/IGNORE. Cross-reference provides breakdown enrichment. Reliability engine is Week 4, currently disabled via config flag."
5. Remove the duplicate "Open question" entry in the precision section (already answered in OPEN_QUESTIONS.md)

---

## Verification

After each phase:
- `python3 -m pytest tests/ -v` — must pass 280+ tests, zero RuntimeWarnings
- Phase 0c: run `python3 -m consensus_engine --dry-run --once` and confirm precision classification appears in logs
- Phase 3b: send a test video through the scanner with HIGH conviction ticker, confirm Discord message fires
- Phase 3c: DM `!yt <url>` to bot and confirm reply
- Phase 3d: set `macro_digest_utc_hour` to 1 minute ahead, confirm post fires once and not twice

---

## Critical Files

| File | Change |
|---|---|
| `consensus_engine/analysis/video_parser.py` | Enum normalization (0a), finish_reason handling (4c) |
| `consensus_engine/cross_reference.py` | Gate reliability engine (0b) |
| `consensus_engine/main.py` | Precision as decision-maker (0c), daily macro digest (3d), session close (4b) |
| `consensus_engine/scanners/youtube.py` | channel_name fix (0d), standalone alerts (3b), macro table write (3a) |
| `consensus_engine/engine.py` | Atomic budget (4a) |
| `consensus_engine/db.py` | youtube_channels table (2a), youtube_macro table (3a), helper fns |
| `consensus_engine/alerts/commands.py` | !yt, !yt-mentions, !macro (3c) |
| `consensus_engine/utils/http.py` | close_session wired up (4b) |
| `tests/test_youtube_scanner.py` | Fix patch target (1a) |
| `tests/test_video_parser.py` | New file (1b) |
| `plans/ROADMAP.md` | Doc reconciliation (Phase 5) |
