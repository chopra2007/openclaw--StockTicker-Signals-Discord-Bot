#!/usr/bin/env python3
"""Step 2b: Live verification of the chunked long-video path.

Runs the real pipeline path on video e_iCwe2yX14 (true length 6314s / 105.2 min)
with chunk_max_windows=2 to save quota. Confirms the merged result contains content
from BOTH windows (coverage well past the old 1121s ceiling).

Quota cost: exactly 2 Gemini calls (one per window).
Usage: python3 verify_chunked_live.py
"""

import asyncio
import os
import sys

# Load env
_env_path = "/root/.openclaw/.env"
with open(_env_path) as f:
    for line in f:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:]
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            os.environ.setdefault(k.strip(), v)

# Add workspace to path
sys.path.insert(0, "/home/openclaw/.openclaw/workspace")

# Point to the real config
os.environ.setdefault("CONSENSUS_CONFIG", "/home/openclaw/.openclaw/workspace/config/consensus.yaml")

VIDEO_ID = "e_iCwe2yX14"
TRUE_DURATION_SEC = 6314
# The old ceiling: if we see content past this, chunking worked
OLD_CEILING_SEC = 1121


async def main():
    from consensus_engine.analysis.gemini_video_parser import _extract_evidence_chunked

    print(f"Live verification: chunked extraction on {VIDEO_ID}")
    print(f"True length: {TRUE_DURATION_SEC}s ({TRUE_DURATION_SEC/60:.1f} min)")
    print(f"Old ceiling: {OLD_CEILING_SEC}s ({OLD_CEILING_SEC/60:.1f} min)")
    print(f"Config: chunk_window_sec=900, chunk_max_windows=2 (2 calls)")
    print()

    # Temporarily patch chunk_max_windows to 2 to save quota
    import consensus_engine.config as cfg_mod
    _orig_get = cfg_mod.get

    def _cfg_patched(key, default=None):
        if key == "youtube.gemini.chunk_max_windows":
            return 2
        return _orig_get(key, default)

    cfg_mod.get = _cfg_patched

    try:
        bundle, tel = await _extract_evidence_chunked(
            VIDEO_ID, "LiveStream", "2026-06-10T00:00:00Z",
            media_resolution="low",
            duration_sec=TRUE_DURATION_SEC,
        )
    finally:
        cfg_mod.get = _orig_get

    if bundle is None:
        print("FAIL: bundle is None — both windows failed. Check quota/keys.")
        return

    print(f"Merged bundle: {len(bundle.spans)} spans, {len(bundle.visual_evidence)} visual, duration_sec={bundle.duration_sec}")
    print(f"Tokens used: input={tel.input_tokens}, output={tel.output_tokens}")
    print(f"Latency: {tel.latency_ms}ms")
    print()

    if not bundle.spans:
        print("FAIL: no spans returned.")
        return

    span_timestamps = sorted(s.ts_sec for s in bundle.spans)
    max_ts = max(span_timestamps)
    min_ts = min(span_timestamps)
    print(f"Span timestamp range: {min_ts}s – {max_ts}s")

    # Window 1 covers 0–900s, window 2 covers 870–1770s
    # We need spans from BOTH windows to confirm coverage
    w1_spans = [s for s in bundle.spans if s.ts_sec < 870]
    w2_spans = [s for s in bundle.spans if s.ts_sec >= 870]

    print(f"Spans in window 1 (0–870s): {len(w1_spans)}")
    print(f"Spans in window 2 (870s+):  {len(w2_spans)}")
    print()

    if w2_spans:
        latest_w2 = max(s.ts_sec for s in w2_spans)
        print(f"Latest span in window 2: {latest_w2}s ({latest_w2/60:.1f} min)")
        if latest_w2 > OLD_CEILING_SEC:
            print(f"PASS: coverage {latest_w2}s >> old ceiling {OLD_CEILING_SEC}s")
        else:
            print(f"FAIL: latest span {latest_w2}s is still within old ceiling {OLD_CEILING_SEC}s")
    else:
        print("FAIL: no spans from window 2 (870s+)")

    print()
    print("Sample spans from each window:")
    if w1_spans:
        s = w1_spans[0]
        print(f"  W1 @ {s.ts_sec}s: {s.quote[:80]!r}")
    if w2_spans:
        s = w2_spans[0]
        print(f"  W2 @ {s.ts_sec}s: {s.quote[:80]!r}")


if __name__ == "__main__":
    asyncio.run(main())
