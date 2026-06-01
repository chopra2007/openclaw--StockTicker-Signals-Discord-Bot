#!/usr/bin/env python3
"""Pass-3 live vision feasibility probe: can native Gemini flash read a REAL Wolf chart?
Reads a real chart from /tmp/wolf_charts, sends bytes to gemini-flash-latest, prints JSON.
Throwaway probe (lives in the run dir, not committed)."""
import os, sys, glob, json
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.openclaw/.env"))
key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY2")
if not key:
    print("NO_GEMINI_KEY in env"); sys.exit(2)

charts = sorted(glob.glob("/tmp/wolf_charts/*.jpg") + glob.glob("/tmp/wolf_charts/*.png"))
if not charts:
    print("NO_CHARTS at /tmp/wolf_charts"); sys.exit(3)

PROMPT = (
    "You are reading a hand-annotated trading chart screenshot from a market newsletter. "
    "Extract ONLY what is visibly present. If a number is unclear, use null and a low confidence "
    "rather than guessing. Return ONLY raw JSON, first character '{', with this schema:\n"
    '{"instrument": "<ticker/index or null>", "timeframe": "<daily/weekly/null>", '
    '"direction": "bullish|bearish|neutral|null", '
    '"levels": [{"price": <number or null>, "role": "support|resistance|target|null", "label": "<text or null>", "confidence": <0-1>}], '
    '"patterns": ["..."], "indicators": [{"name": "<e.g. 3C>", "reading": "<text>"}], '
    '"raw_caption": "<one-line summary of the chart\'s message>"}'
)

try:
    from google import genai
    from google.genai import types
except Exception as e:
    print("SDK_IMPORT_FAIL:", e); sys.exit(4)

client = genai.Client(api_key=key)
models = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest"]

for chart in charts[:2]:
    with open(chart, "rb") as f:
        data = f.read()
    print(f"\n===== CHART: {chart} ({len(data)} bytes) =====")
    ok = False
    for m in models:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=[
                    types.Part.from_text(text=PROMPT),
                    types.Part.from_bytes(data=data, mime_type="image/jpeg"),
                ],
            )
            txt = (resp.text or "").strip()
            print(f"[model={m}] raw response:\n{txt}")
            ok = True
            break
        except Exception as e:
            print(f"[model={m}] ERROR: {type(e).__name__}: {str(e)[:300]}")
    if not ok:
        print("ALL_MODELS_FAILED for this chart")
print("\nPROBE_DONE")
