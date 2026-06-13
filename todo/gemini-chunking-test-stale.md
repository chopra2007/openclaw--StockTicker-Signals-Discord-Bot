# Fix the stale YouTube video-parser test (chunking)

**Status:** DONE 2026-06-13
**Created:** 2026-06-11

**DONE 2026-06-13 (discover run `todo-sweep-2026-06-13`):** one-line fix — added `patch("consensus_engine.utils.transcript_fetch.fetch_youtube_duration", new=AsyncMock(return_value=600))` to `test_extract_evidence_parses_spans` so it takes the single-pass path (the test feeds a real video id `4mSyMr8PGLI` whose live Invidious duration 2458 > 1200 was triggering the chunked path → duration 2458 not 2340). Parser was correct; test was stale. All original assertions pass unchanged; the 2 chunked-route tests still pass (3 passed in 20s). Removed from `.test-baseline`. Committed this session.

A unit test fails and is currently parked in `.test-baseline` so it doesn't block pushes. It is NOT a real product bug — the live YouTube reading works fine (`!yt-health` shows ~93% parse-ok across 122 videos). The test's fake data just wasn't updated when an earlier feature landed.

## The failure
`tests/test_gemini_video_parser.py::test_extract_evidence_parses_spans`
```
assert bundle.duration_sec == 2340
E   AssertionError: assert 2458 == 2340
```
The test feeds a fake Gemini reply with `duration_sec: 2340` and spans at 2024/2142/2172, but the parser returns 2458 and three spans all near 2458.

## Root cause (confirmed)
Commit `9c8f889` ("#17 CRITICAL: chunked Gemini reads give long YouTube videos full coverage") changed the parser to read long videos in **multiple chunks** and stitch them, adding a per-chunk time offset to each chunk's timestamps. The test still mocks a **single** Gemini response, so that one response gets reused for every chunk and the offsets inflate the timestamps/duration (hence 2458 instead of 2340). The test was never updated for chunking, and never added to the baseline — so the full-suite run flagged it.

## What worked
- Confirmed it fails 3/3 in isolation (not flaky) and imports none of the TODO #36 files → it's pre-existing, unrelated to the six-fix bundle.
- Parked it in `.test-baseline` (commit on master) so the regression gate is accurate.

## Next steps (priority order)
1. Decide the intended behavior: should `duration_sec` come from the LLM's reported value, or be derived from chunk boundaries? Read `consensus_engine/analysis/gemini_video_parser.py` around line 375 (`data.get("duration_sec")`) and the chunk-merge logic added in `9c8f889`.
2. Update the test mock to be chunk-aware (e.g. make `generate_content` return a per-chunk response, or assert the post-chunking expected values) — OR fix the parser if 2458 is genuinely wrong.
3. Once green, REMOVE the line `tests/test_gemini_video_parser.py::test_extract_evidence_parses_spans` from `.test-baseline`.

## Files
- `tests/test_gemini_video_parser.py` (the stale test, ~line 99)
- `consensus_engine/analysis/gemini_video_parser.py` (chunk-merge + `duration_sec` at ~375)
- `.test-baseline` (currently lists this test as a known failure)

## Why this matters
Low urgency (no user-facing breakage), but a baselined test is a blind spot — if the parser later regresses for real, this test can't catch it while it's parked. Worth a small, clean fix.
