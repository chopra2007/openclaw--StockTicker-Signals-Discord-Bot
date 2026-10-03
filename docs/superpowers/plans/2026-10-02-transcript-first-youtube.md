# Transcript-first YouTube Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Use Usetranscribe for speech and use a smaller separate Gemini request for visual evidence.

**Architecture:** The shared free-first transcript cascade runs before full-video transcription. Timestamped source segments are read in bounded text chunks without dropping the tail. An independent visual worker samples tiny clips, saving successful batches and resuming failures independently of transcript ingestion.

**Tech Stack:** Python, aiohttp, google-genai, SQLite, existing VPS service.

**Spec:** User-approved transcript-first design in this chat; implementation details in `docs/reference/USETRANSCRIBE_YOUTUBE.md`.

## Global Constraints

- Preserve live uncommitted work; no GitHub push during this session.
- No new audio download or transcription on the successful transcript path.
- Hosted video still incurs audio input tokens; report measured usage, not zero-audio claims.
- Keep source quotes, source times, generated summaries and visual observations distinct.
- Visual quota failures must not discard transcripts or rerun spoken analysis.

## Review Focus

- A company mentioned only at the end of a long transcript is still read.
- Fabricated source quotes and invented timestamps cannot become timed spoken evidence.
- A valid transcript with no tickers succeeds without full-video transcription.
- A restart resumes failed visual work without duplicating visual rows or alerts.
- Sparse frames can miss short displays; report sampling and real usage honestly.

### Task 1: Read full source text with source times

**Files:** `consensus_engine/analysis/captions_llm_parser.py`, `consensus_engine/utils/usetranscribe.py`, `tests/test_captions_llm_parser.py`, `tests/test_transcript_first.py`.

**Interfaces:** Add `get_cached_record(video_id) -> dict | None`; optional `source_segments` to `extract_evidence_from_captions`; preserve existing return shape.

- [ ] Write and run failing tests for tail coverage, source timestamps, rejected fabricated quotes, empty successful extraction, and failure in a middle chunk.
- [ ] Split all text into bounded calls. For timed sources, request segment IDs and ground each quote in its specified source range. Merge and deduplicate actual source spans.
- [ ] Run caption and transcript tests; commit functional change.

```python
assert [span.ts_sec for span in bundle.spans] == [1120]
assert all(len(prompt) < 20000 for prompt in prompts)
```

### Task 2: Separate visual capture and durable retry

**Files:** `consensus_engine/analysis/gemini_video_parser.py`, new `consensus_engine/analysis/youtube_visual_jobs.py`, `consensus_engine/local_video_ingest.py`, `consensus_engine/scanners/youtube.py`, config and dedicated tests.

**Interfaces:** `extract_visual_evidence_with_gemini(video_id, published_at)` returns existing bundle/telemetry shape; visual jobs save the spoken bundle so retries require no transcript LLM.

- [ ] Write and run failing tests proving captions win before Gemini speech, visual-only prompts have no spoken output, quota queues visual work, retries survive restart, and completed visual persistence is idempotent.
- [x] Reuse existing Gemini key rotation, budget and usage accounting. Live probes selected up to 60 four-second clips at 0.25 fps, ten per request, medium resolution, 3,000 output tokens and disabled thinking on Gemini 2.5 Flash; no speech spans accepted.
- [x] Queue pending visual jobs atomically without waiting for Google. An independent worker files visuals and conservative levels through existing validation without posting alerts. Freeze prepared levels and reuse the saved run after a crash.
- [ ] Keep full Gemini speech as last resort if transcript acquisition or text analysis fails.
- [ ] Run relevant scanner, classifier, transcript and visual tests; commit functional change.

```python
speech.assert_not_awaited()
assert telemetry.chain_winner == "transcript+visual/v1"
```

### Task 3: Verify and deploy

**Files:** `docs/reference/USETRANSCRIBE_YOUTUBE.md`, test fixtures where production defaults require deterministic isolation.

- [ ] Probe the sample video using real provider and Gemini calls in an isolated database; inspect source quotes, chart values and token accounting.
- [ ] Compare visual input token counts with the earlier full-video run and collect actual text-call usage separately.
- [ ] Run the full production test suite against the baseline: 4321 passed, 121 skipped, unrelated Databento research collection error already tracked.
- [ ] Obtain independent code review, fix material issues, deploy preserving live changes, restart and verify both services, symlink, logs and a real ingest path.
- [ ] Update documentation with exact measurements, provider limits and sparse-frame limitations; commit without GitHub push.

## Execution evidence

The feature branch is `codex/usetranscribe-youtube`, based on `e2bf28c`.
Staging is `/tmp/youtube-split-stage`; the live checkout remains separate.
Targeted tests passed 175 cases with one existing deselection before final review fixes.
Independent review reproduced quote punctuation, overlap, duration, attribution and
restart issues; regression tests were written before each fix.
The real sample completed 84 visual observations and five chart levels. Measured
combined usage is 40,336 tokens against the previous 73,776 (45% fewer).
Staging full-suite research failures are missing ignored artifacts, outside this
change; authoritative full-suite verification runs in the live checkout's isolated
process environment after deployment.
