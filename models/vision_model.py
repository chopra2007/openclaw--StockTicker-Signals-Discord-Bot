"""Vision model wrapper for financial-image understanding."""

import json
import re
from typing import Any

from . import model_config
from .openrouter_client import chat_completion

VISION_PROMPT = """You are a financial analyst.

Analyze the provided image and extract structured investment insight.

DO NOT just read text. INTERPRET the content.

Specifically identify:
- Institution/source (if visible)
- Company/ticker
- Type of analysis (e.g., bull/bear case, earnings model, price target report)
- Key scenarios (bull, base, bear)
- Price targets associated with each scenario
- Probabilities (if shown)
- Key drivers and risks
- Overall sentiment (bullish / bearish / neutral)

Return ONLY valid JSON:

{
  "source": "",
  "ticker": "",
  "analysis_type": "",
  "scenarios": {
    "bull_case": { "price": null, "details": "" },
    "base_case": { "price": null, "details": "" },
    "bear_case": { "price": null, "details": "" }
  },
  "probabilities": {},
  "sentiment": "",
  "confidence": 0.0,
  "summary": ""
}"""


def _default_vision_output() -> dict[str, Any]:
    return {
        "source": "",
        "ticker": "",
        "analysis_type": "",
        "scenarios": {
            "bull_case": {"price": None, "details": ""},
            "base_case": {"price": None, "details": ""},
            "bear_case": {"price": None, "details": ""},
        },
        "probabilities": {},
        "sentiment": "neutral",
        "confidence": 0.0,
        "summary": "",
    }


def _parse_json_response(raw: str) -> dict[str, Any]:
    if not raw:
        return _default_vision_output()
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        base = _default_vision_output()
        base.update({k: v for k, v in data.items() if k in base})
        return base
    except Exception:
        return _default_vision_output()


async def analyze_image(image_url: str) -> dict[str, Any]:
    content = [
        {"type": "text", "text": VISION_PROMPT},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    raw = await chat_completion(
        model_config.VISION_MODEL,
        [{"role": "user", "content": content}],
        max_tokens=1600,
        temperature=0.0,
    )
    return _parse_json_response(raw)
