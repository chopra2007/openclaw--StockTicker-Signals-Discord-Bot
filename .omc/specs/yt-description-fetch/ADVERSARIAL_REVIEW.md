# Adversarial Review: `yt-description-fetch` Spec

Reviewed file: `.omc/specs/yt-description-fetch/README.md`
Review date: `2026-04-28`

## Bottom line

The feature idea is reasonable, but the spec is stale and one of its main implementation instructions is unsafe. If someone follows the README literally, they risk damaging existing video state while also missing the real remaining work.

## Findings

### 1. The spec proposes an unsafe DB write pattern

The README says to change `upsert_youtube_video()` to use `INSERT OR REPLACE`.

Why this is dangerous in plain terms:

- `REPLACE` does not "edit one field"; it effectively deletes the old row and inserts a new one.
- The `youtube_videos` row contains more than just title/published time. It also stores processing state like:
  - `transcript_status`
  - `language`
  - `is_auto_generated`
  - `export_path`
- Replacing the row can wipe or reset that state.
- The scanner decides whether a video is already handled by checking `transcript_status`, so resetting it can cause incorrect behavior.

Relevant code:

- `consensus_engine/db.py:160`
- `consensus_engine/db.py:1335`
- `consensus_engine/db.py:1348`

### 2. The README claims old videos will eventually get descriptions, but the current flow does not do that

The spec says old rows can get descriptions the next time those videos are polled.

That is not how the current scanner behaves:

- The poller filters out videos that are already processed before sending them to `process_video()`.
- `process_video()` also exits early if the video is already processed.
- The DB helper currently uses `INSERT OR IGNORE`, so existing rows are not refreshed.

Result:

- already-processed videos will not be enriched automatically
- historical rows will stay without descriptions unless a new explicit refresh path is added

Relevant code:

- `consensus_engine/scanners/youtube.py:595`
- `consensus_engine/scanners/youtube.py:975`
- `consensus_engine/db.py:1359`

### 3. Much of the spec is already implemented, so the document is stale

The README presents several items as proposed work even though they already exist in the codebase:

- `youtube_videos.description` already exists in schema creation
- the migration list already includes `youtube_videos.description`
- the RSS parser already extracts `<media:description>`
- `build_video_allowlist()` already accepts `video_description`
- the backfill script already reads `description`

Result:

- the implementation plan overstates the remaining work
- an engineer following it literally would redo completed steps
- the real remaining work is narrower than the README suggests

Relevant code:

- `consensus_engine/db.py:160`
- `consensus_engine/db.py:591`
- `consensus_engine/scanners/youtube.py:36`
- `consensus_engine/analysis/ticker_grounding.py:127`
- `scripts/backfill_youtube_grounding.py:33`

### 4. The test plan misses a real breakage in the current tree

The README says to add new tests, but it does not call out that an existing backfill test fixture is now out of date.

Current issue:

- `tests/test_backfill_youtube_grounding.py` creates `youtube_videos` without a `description` column
- `scripts/backfill_youtube_grounding.py` now selects `title, description`
- this causes the test to fail with `sqlite3.OperationalError: no such column: description`

Observed command:

```bash
python3 -m pytest tests/test_backfill_youtube_grounding.py -q -x
```

Observed failure:

```text
sqlite3.OperationalError: no such column: description
```

Relevant code:

- `tests/test_backfill_youtube_grounding.py:31`
- `scripts/backfill_youtube_grounding.py:52`

## What is actually left to do

The remaining work appears much smaller than the README claims:

1. Pass `video_description` into the allowlist at the remaining call sites.
2. Decide whether historical rows should ever be refreshed.
3. If yes, add a safe metadata update path instead of `INSERT OR REPLACE`.
4. Update stale tests and fixtures to include the `description` column.

## Open question

The spec treats YouTube description text as equally trustworthy as the title. That may be acceptable, but it should be explicit because many finance descriptions contain ticker dumps, sponsor copy, or unrelated watchlists. If broadening the allowlist this way is intentional, the spec should say so clearly.
