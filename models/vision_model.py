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
- Direction basis: annotated_setup, price_action, fundamental_event, or none.
- Setup direction: long, short, or unclear. This is the author's illustrated
  directional intent, separately from overall sentiment about current price.
- Describe the visible evidence for the direction separately from general summary.
- A chart being green, old trade profits, or merely displaying bull/base/bear
  scenarios does not establish a current bias. Use neutral and basis none unless
  visible annotations, price action at a named level, or an explicit event
  comparison supports a direction. Do not invent a ticker or unreadable values.
- Sentiment describes the illustrated setup, not whether the trade already won.
  An upward arrow aimed through resistance is a conditional bullish setup; a
  downward arrow through support is bearish. Price targets and probabilities
  are not required to identify that intent. Confidence measures whether you
  can read that evidence clearly, not the probability of a profitable trade.
- Do not expand chart abbreviations unless their meanings are given in the image.
- A bullish breakout arrow at resistance can have setup_direction long even
  while current consolidation has neutral overall sentiment. Hypothetical
  opposite scenarios alone do not erase the annotated setup's direction.
- A call/put contract by itself has unclear setup direction unless buy/sell
  side, entry and profit/stop plan, or an independent underlying setup is visible.

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
  "direction_basis": "none",
  "setup_direction": "unclear",
  "direction_evidence": "",
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
        "direction_basis": "none",
        "setup_direction": "unclear",
        "direction_evidence": "",
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
    for model in dict.fromkeys([model_config.VISION_MODEL, *model_config.VISION_FALLBACK_MODELS]):
        raw = await chat_completion(
            model, [{"role": "user", "content": content}],
            max_tokens=1600, temperature=0.0,
        )
        parsed = _parse_json_response(raw)
        if raw and parsed != _default_vision_output():
            return parsed
    return _default_vision_output()
