# yt-grounding Path B hard-delete (date-gated 2026-05-28)

**Status:** DONE 2026-05-28 — Path B deleted, dual-use config keys kept, tests fixed, suite green. (soak)
**Created:** 2026-05-09

**Layperson:** The old YouTube-parsing code is dormant but still on disk as a safety net. After 30 days with no problems reported, rip it out.

**Earliest date:** 2026-05-28 (PR #12 merged 2026-04-28 — gated on 30-day soak).

**What to delete:**
- `parse_video_with_gemini` function in `consensus_engine/analysis/gemini_video_parser.py`
- `_GEMINI_PROMPT` constant
- Path B fallback branch in `consensus_engine/scanners/youtube.py:528-539` (line numbers may have drifted)
- The `_build_parsed_video` function (Path B-specific)
- `youtube.gemini_enabled` and `youtube.legacy_fallback` config keys (and their consumers)
- Path B grounding hooks in `_build_parsed_video` (Layer 2 Path B integration)

**Acceptance:** PR shipping the deletions is merged; full test suite still passes; no Path B import errors at engine startup.

**Memory pointer:** also delete `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/project_yt_grounding_followups.md` once this lands.

### Session notes — 2026-05-28 (DONE — discover run todo-autobatch)
- **Worked on:** Deleted Path B (`parse_video_with_gemini`, `_build_parsed_video`, `_GEMINI_PROMPT`, file-local `_MACRO_NORM`, 7 orphaned model imports) + the unreachable Gemini fast-path block in `youtube.py`. Fixed/retargeted the breaking tests (deleted 2 genuinely-dead, retargeted 2 that test still-live persistence to the transcript path).
- **Decision (deviation from this file):** KEPT config keys `youtube.gemini_enabled` and `youtube.legacy_fallback`. Verified in code they are NOT Path-B-only — `gemini_enabled` gates the LIVE two-stage path (youtube.py:688), `legacy_fallback` gates the LIVE !yt error handler (commands.py:1434). Deleting them would change live behavior, which is beyond "remove dead code." The original "delete the keys" line assumed they were Path-B-only; the code disproved that.
- **Verified:** clean engine import + restart (no Path B ImportError), youtube poll loop running, full suite 1362 passed / 0 failed (baseline 1351, zero regressions). Both services active.
- **Memory file deleted:** `project_yt_grounding_followups.md` + its MEMORY.md index line removed.
