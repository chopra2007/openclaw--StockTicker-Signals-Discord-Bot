# yt-grounding Path B hard-delete (date-gated 2026-05-28)

**Status:** OPEN — date-gated, earliest action 2026-05-28.
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
