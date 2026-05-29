# Gemini video-eval reference assertions — 2/7 chronic failure

**Status:** OPEN — chronic failure since 2026-04-23.
**Created:** 2026-05-12

**Layperson:** The daily cron `scripts/run_reference_assertions_cron.sh` is a regression test that asks Gemini to extract evidence-spans from a fixed YouTube video (`4mSyMr8PGLI`) and checks ~7 assertions. It's been stuck at **2/7 passing every day since 2026-04-23** because Gemini's video-ingest times out (was 120s timeout, bumped to 240s on 2026-05-12). Even with the bump, the chance of all-7-pass is low without a deeper fix.

## Observed pattern (from `.omc/logs/v2_assertions_*.log`)
- Steady: both `GEMINI_API_KEY` + `GEMINI_API_KEY2` time out → 2/7 pass
- Best case (Apr 29, May 2): only one key times out → 4/7 pass
- Apr 23 saw explicit 429 RESOURCE_EXHAUSTED

## Root cause (likely)
Gemini free-tier video-ingest latency for a long trading-recap video; the call is `Part.from_uri(file_uri=YT_URL, mime_type="video/*")` which re-ingests on Google's backend every time (no Files API caching).

## Fix options (ranked)

1. **Files API + caching** (best): upload the reference video once via `client.files.upload(...)` and reference the cached `file_uri` for every subsequent call. Eliminates re-ingest cost entirely. Cleanest fix.
2. **Paid Gemini API key**: drops the variance entirely; priority queue processes consistently in <60s. ~$0.30/day at current budgets.
3. **Already-done**: timeout bump 120→240s (config/consensus.yaml:305). May convert some 2/7 days to 4/7 or 7/7, but doesn't help if Gemini is taking >240s.
4. **Pin a shorter reference video**: replace `4mSyMr8PGLI` with a 5-10 min video that's known to ingest in <120s. Loses regression coverage for long-form quote extraction.

## Where to dig
- Call site: `consensus_engine/analysis/gemini_video_parser.py:812` (`_extract_evidence_single_pass`)
- Script: `scripts/run_reference_assertions.py` (VIDEO_ID = "4mSyMr8PGLI")
- Daily logs: `.omc/logs/v2_assertions_YYYYMMDD.log`
- Config: `config/consensus.yaml` lines 300-322 (the whole `youtube.gemini:` block)

## Out-of-scope-for-now caveats
- Wrapper script exits 0 (cron is happy) but inner-python exits 1 — DoD §7c ambiguity. Not a crash; a "signal in the log" per the script's own docstring.
- This pre-dates the 2026-05-12 batch and the prior 2026-05-11 batch — not a regression from any recent work.

---

### Session notes — 2026-05-29 (discover run todo-2-3-17)

**ROOT CAUSE was misdiagnosed.** Since 2026-05-15 the chain ran captions BEFORE Gemini video, so the cron was testing the captions path, not Gemini — and "json_ok=0" was a false alarm (captions LLM returns markdown-fenced JSON). Files API caching (the old #1 fix) targeted a dead path.

**FIXED this session (shipped):**
- The real blocker was a Gemini limit: `gemini-2.5-flash-lite`/`flash` 503 "high demand" for video; `gemini-flash-latest` works. Fixed in [[reference-gemini-video-models]] + TODO #17 Task B (model swap + fps 0.5 + chain reorder so Gemini is primary).
- Harness (`run_reference_assertions.py`) now forces captions+whisper OFF so it regression-tests the Gemini path specifically. Result: **4/7** (was 1/7 on the dead path).
- Removed two false-failures: idempotency is now report-only (a live LLM isn't byte-identical run-to-run); dump writes to a per-user temp path (was crashing on a root-owned `/tmp/yt_v2_dump.json`).

**REMAINING (gated on #17 Task C):** A1/A2/A3 check chart-derived levels/setups/catalysts. Gemini extracts the chart numbers into `youtube_visual_evidence`, but nothing turns them into `youtube_levels` yet — that wiring IS #17 Task C. So full 7/7 green requires Task C. A5/A4/A6/A7 pass.
