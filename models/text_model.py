"""Text model wrapper for tweet -> structured signal synthesis."""

import json
import re
from typing import Any

from . import model_config
from .openrouter_client import chat_completion

TEXT_PROMPT = """You are a stock market tweet classifier and trading signal synthesizer.

Given tweet text and optional vision analysis JSON, return ONLY valid JSON with this schema:
{
  "type": "A|B|C|D",
  "tickers": ["TICKER1"],
  "direction": "long|short|neutral",
  "options": {
    "present": true,
    "strike": null,
    "expiry": null,
    "type": null,
    "target_price": null,
    "profit_target_pct": null
  },
  "conviction": "high|medium|low",
  "catalyst_horizon": "short|long|none",
  "catalyst_kind": "options|M&A|release|lawsuit|scandal|moat|guidance|product-far|none",
  "catalyst_likelihood": 0.0,
  "summary": "",
  "final_signal": {
    "ticker": "",
    "signal": "bullish | bearish | neutral",
    "confidence": 0.0,
    "reason": "",
    "key_levels": {
      "bull_case": null,
      "base_case": null,
      "bear_case": null
    },
    "source_types": ["text"]
  }
}

Rules:
- If options details exist (strike/expiry/call/put), classify type C.
- If no specific ticker, type D and empty tickers.
- Exclude technical indicators (RSI, EMA, MACD, VWAP, SMA, ATR, RVOL) as tickers.
- Use vision context if provided to enrich confidence, reason, and key_levels.
- Ensure source_types includes "image" when vision context is provided.
- conviction reflects SETUP QUALITY, never the wording register. These analysts
  habitually hedge ("watching", "might add if it reclaims a level") — hedged
  wording around a concrete setup is still a real call.
  high = complete trade plan (entry + target + stop, or options strike/expiry
  with a target) or an explicit all-in conviction statement.
  medium = a directional call on a specific ticker, even in hedged wording,
  with at least one concrete level or setup element.
  low = ONLY when there is no actionable content at all (vague market musing,
  no ticker-specific level, entry, or plan).

Catalyst classification (#55) — answer "is there a real, datable reason this
stock should move, and when?":
- catalyst_horizon "short": a discrete event that resolves within ~30 days —
  options expiry play, earnings/guidance print, M&A/buyout news, product launch
  or release date, lawsuit ruling, scandal, FDA/regulatory decision.
- catalyst_horizon "long": a structural thesis with no near date — widening moat,
  multi-year guidance ramp, a product still years out, secular share gain.
- catalyst_horizon "none": no bet at all — pure news recap, chart commentary with
  no reason, market musing, or you cannot tell. Default to "none" when unsure.
  A post with NO directional catalyst must be "none", even if it names a ticker.
- catalyst_kind: which of the listed kinds it is, else "none".
- catalyst_likelihood: 0.0-1.0, how likely the catalyst actually happens as stated
  (a rumor is low; a scheduled earnings date is high). Use 0.0 when horizon="none".
"""


def _default_payload() -> dict[str, Any]:
    return {
        "type": "D",
        "tickers": [],
        "direction": "neutral",
        "options": {
            "present": False,
            "strike": None,
            "expiry": None,
            "type": None,
            "target_price": None,
            "profit_target_pct": None,
        },
        "conviction": "medium",
        # #55: fail-closed. A parse failure yields horizon='none', so an
        # unreadable post is SKIPPED by the catalyst scorer, never scored wrong.
        "catalyst_horizon": "none",
        "catalyst_kind": "none",
        "catalyst_likelihood": 0.0,
        "summary": "",
        "final_signal": {
            "ticker": "",
            "signal": "neutral",
            "confidence": 0.0,
            "reason": "",
            "key_levels": {"bull_case": None, "base_case": None, "bear_case": None},
            "source_types": ["text"],
        },
    }


def _parse_json_response(raw: str) -> dict[str, Any]:
    if not raw:
        return _default_payload()
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        payload = _default_payload()
        payload.update({k: v for k, v in data.items() if k in payload})
        final_signal = data.get("final_signal", {}) if isinstance(data, dict) else {}
        if isinstance(final_signal, dict):
            merged = payload["final_signal"]
            merged.update({k: v for k, v in final_signal.items() if k in merged})
            payload["final_signal"] = merged
        return payload
    except Exception:
        return _default_payload()


async def analyze_tweet(tweet_text: str, analyst: str, vision_output: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    user_context = {
        "analyst": analyst,
        "tweet_text": tweet_text,
        "vision_output": vision_output or [],
    }
    raw = await chat_completion(
        model_config.TEXT_MODEL,
        [
            {"role": "system", "content": TEXT_PROMPT},
            {"role": "user", "content": json.dumps(user_context)},
        ],
        max_tokens=1800,
        temperature=0.1,
    )
    parsed = _parse_json_response(raw)
    if vision_output and "image" not in parsed["final_signal"].get("source_types", []):
        parsed["final_signal"]["source_types"] = list({*parsed["final_signal"].get("source_types", []), "image"})
    return parsed
