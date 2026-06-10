#!/usr/bin/env python3
"""STEP 1 probe — does VideoMetadata start_offset/end_offset defeat Gemini's input truncation?

Video: e_iCwe2yX14 (true length 6314s / 105.2 min)
Previous probes saw only 619–1121s (first 10–18 min). This probe asks Gemini for
a 5-minute window at 3600–3900s (60–65 min into the video), well past the old ceiling.

If PASS: the window returns content clearly from ~60 min (timestamps inside 3600–3900s,
quotes/topics that match that part of the video, NOT the opening minutes).
If FAIL: returns opening-minutes content or refuses.

Usage: python3 probe_chunk_offset.py
Quota budget: 1–2 calls max.
"""

import json
import os
import sys
import time

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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEY2 = os.environ.get("GEMINI_API_KEY2", "")

VIDEO_ID = "e_iCwe2yX14"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
TRUE_LENGTH_SEC = 6314
WINDOW_START = 3600  # 60 min in
WINDOW_END = 3900    # 65 min in

PROMPT = f"""You are watching a 5-minute CLIP of a financial YouTube video (the clip covers
seconds {WINDOW_START}–{WINDOW_END} of a longer video).

Your task:
1. Report EXACTLY what timestamp range you can actually see (first and last second you observe).
2. Give 2–3 verbatim spoken quotes from the CLIP, each with the approximate second offset when spoken.
3. Describe briefly what topic the speaker is discussing in this clip.

Output valid JSON only, no markdown fences:
{{
  "observed_start_sec": <integer>,
  "observed_end_sec": <integer>,
  "quotes": [
    {{"ts_sec": <integer>, "quote": "<verbatim>"}}
  ],
  "topic": "<brief description of what the speaker is discussing in this clip>"
}}
"""


def run_probe(api_key: str, key_label: str):
    print(f"\n--- Running probe with {key_label} ---")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    video_part = types.Part(
        file_data=types.FileData(file_uri=VIDEO_URL, mime_type="video/*"),
        video_metadata=types.VideoMetadata(
            start_offset=f"{WINDOW_START}s",
            end_offset=f"{WINDOW_END}s",
            fps=0.2,  # very low fps — we want transcript content, not vision
        ),
    )

    gen_config = types.GenerateContentConfig(
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
    )

    t0 = time.time()
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=[
                types.Part.from_text(text=PROMPT),
                video_part,
            ],
            config=gen_config,
        )
        elapsed = time.time() - t0
        print(f"Call completed in {elapsed:.1f}s")

        # Token counts
        meta = getattr(response, "usage_metadata", None)
        if meta:
            print(f"Input tokens: {getattr(meta, 'prompt_token_count', '?')}")
            print(f"Output tokens: {getattr(meta, 'candidates_token_count', '?')}")

        # Finish reason
        cands = getattr(response, "candidates", None) or []
        if cands:
            fr = getattr(cands[0], "finish_reason", None)
            print(f"Finish reason: {getattr(fr, 'name', str(fr)) if fr is not None else 'unknown'}")

        raw = response.text
        print(f"\nRaw response:\n{raw}\n")

        # Try to parse
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            import re
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
        try:
            parsed = json.loads(cleaned)
            print("=== PARSED RESULT ===")
            print(json.dumps(parsed, indent=2))

            obs_start = parsed.get("observed_start_sec", -1)
            obs_end = parsed.get("observed_end_sec", -1)

            print(f"\n=== PROBE VERDICT ===")
            print(f"True video length: {TRUE_LENGTH_SEC}s ({TRUE_LENGTH_SEC/60:.1f} min)")
            print(f"Requested window:  {WINDOW_START}s–{WINDOW_END}s ({WINDOW_START//60}–{WINDOW_END//60} min)")
            print(f"Observed window:   {obs_start}s–{obs_end}s")

            # PASS condition: the observed timestamps are clearly past the old ceiling (1121s)
            if obs_start is not None and obs_start >= 3000:
                print("VERDICT: PASS — Gemini returned content from deep in the video (past old 1121s ceiling)")
            elif obs_start is not None and obs_start < 300:
                print("VERDICT: FAIL — Gemini returned opening content despite offset request")
            else:
                print(f"VERDICT: UNCLEAR — observed_start={obs_start}, inspect quotes above")

        except json.JSONDecodeError as e:
            print(f"JSON parse failed: {e}")
            print("Cannot auto-determine verdict — inspect raw response above")

        return True

    except Exception as e:
        elapsed = time.time() - t0
        print(f"Call FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print(f"Probe: VideoMetadata offset chunking test")
    print(f"Video: {VIDEO_ID} (true length {TRUE_LENGTH_SEC}s / {TRUE_LENGTH_SEC/60:.1f} min)")
    print(f"Requesting window: {WINDOW_START}s–{WINDOW_END}s (60–65 min in)")
    print(f"Model: gemini-flash-latest, fps=0.2, media_resolution=LOW")

    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not found in env")
        sys.exit(1)

    success = run_probe(GEMINI_API_KEY, "GEMINI_API_KEY")
    if not success:
        print("\nKey 1 failed. Trying Key 2...")
        if GEMINI_API_KEY2:
            run_probe(GEMINI_API_KEY2, "GEMINI_API_KEY2")
        else:
            print("No Key 2 configured")
