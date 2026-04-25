"""Tweet Parser — multimodal intent extraction from analyst tweets.

Uses a hybrid router:
- Text-only tweets -> text model
- Tweets with images -> vision model(s) + text model synthesis

Falls back to regex extraction on failures.
"""

import logging
import json
import re
from typing import Optional

import aiohttp

from consensus_engine.models import (
    ParsedTweet, OptionsDetail, TweetType, Direction, Conviction,
)
from consensus_engine.utils.tickers import extract_tickers
from models.router import process_tweet as process_multimodal_tweet

log = logging.getLogger("consensus_engine.analysis.tweet_parser")


def _build_parser_prompt(analyst: str, text: str) -> str:
    """Retained for backward compatibility in tests and tooling."""
    return f"Analyst: @{analyst}\nTweet: {text}"


def _parse_model_payload(payload: dict, url: str, analyst: str, original_text: str) -> ParsedTweet:
    """Parse multimodal model output into ParsedTweet. Falls back to regex on failure."""
    if isinstance(payload, str):
        cleaned = payload.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
        except Exception:
            return _fallback_parse(url, analyst, original_text)

    if not isinstance(payload, dict):
        return _fallback_parse(url, analyst, original_text)

    raw_type = str(payload.get("type", "A")).upper()
    type_map = {"A": TweetType.TICKER_CALLOUT, "B": TweetType.MACRO,
                "C": TweetType.OPTIONS_TRADE, "D": TweetType.SENTIMENT}
    tweet_type = type_map.get(raw_type, TweetType.TICKER_CALLOUT)

    raw_dir = str(payload.get("direction", "neutral")).lower()
    dir_map = {"long": Direction.LONG, "short": Direction.SHORT, "neutral": Direction.NEUTRAL}
    direction = dir_map.get(raw_dir, Direction.NEUTRAL)

    raw_conv = str(payload.get("conviction", "medium")).lower()
    conv_map = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}
    llm_conviction = conv_map.get(raw_conv, Conviction.MEDIUM)

    tickers = payload.get("tickers", [])
    if not isinstance(tickers, list):
        tickers = []
    tickers = [t.upper() for t in tickers if isinstance(t, str)]

    options_data = payload.get("options", {})
    options = None
    if isinstance(options_data, dict) and options_data.get("present"):
        options = OptionsDetail(
            present=True,
            strike=_to_float(options_data.get("strike")),
            expiry=options_data.get("expiry"),
            option_type=options_data.get("type"),
            target_price=_to_float(options_data.get("target_price")),
            profit_target_pct=_to_float(options_data.get("profit_target_pct")),
        )

    conviction = _resolve_conviction(llm_conviction, _infer_conviction(original_text, options))

    summary = str(payload.get("summary", ""))

    parsed = ParsedTweet(
        tweet_url=url,
        analyst=analyst,
        raw_text=original_text,
        tweet_type=tweet_type,
        tickers=tickers,
        direction=direction,
        options=options,
        conviction=conviction,
        summary=summary or original_text[:100],
    )
    parsed.final_signal = payload.get("final_signal") if isinstance(payload.get("final_signal"), dict) else None
    vision_outputs = payload.get("vision_outputs")
    if isinstance(vision_outputs, list):
        parsed.vision_outputs = vision_outputs
    return parsed


# Backward-compatible alias expected by existing tests
_parse_llm_response = _parse_model_payload


_INDICATOR_NAMES = {"RSI", "EMA", "MACD", "VWAP", "SMA", "RVOL", "ATR", "ADX", "MFI", "OBV", "CCI", "DMI", "DOJI", "BOLL"}


_LONG_KEYWORDS = {"long", "buy", "buying", "bullish", "calls", "moon", "breakout", "gap up", "ripping"}
_SHORT_KEYWORDS = {"short", "put", "puts", "bearish", "dump", "gap down", "crash", "selling", "fade"}


_HIGH_CONVICTION_KEYWORDS = re.compile(
    r"\b(highest conviction|high conviction|hc|all in|loaded up|loading up|"
    r"backing up the truck|yolo)\b",
    re.IGNORECASE,
)
_LOW_CONVICTION_KEYWORDS = re.compile(
    r"\b(watching|might|maybe|could|considering|thinking about|tentative|"
    r"on watch|keeping an eye)\b",
    re.IGNORECASE,
)
_STOP_LOSS_PATTERN = re.compile(r"\b(sl|stop|stop loss|stop-loss)\b", re.IGNORECASE)
_TARGET_PATTERN = re.compile(r"(\btarget\b|🎯|\btp\b)", re.IGNORECASE)
_ENTRY_PATTERN = re.compile(r"\b(at|@)\s*\$?\d", re.IGNORECASE)


def _infer_conviction(text: str, options: Optional[OptionsDetail]) -> Conviction:
    """Deterministic conviction tier from tweet text and options shape.

    Returns HIGH or LOW only when the heuristic is decisive. MEDIUM is the
    default when no rule matches — callers can fall back to LLM output.
    """
    if not text:
        return Conviction.MEDIUM

    has_sl = bool(_STOP_LOSS_PATTERN.search(text))
    has_target = bool(_TARGET_PATTERN.search(text))
    has_entry = bool(_ENTRY_PATTERN.search(text))

    if options and options.present and options.strike and options.expiry \
            and (options.target_price or options.profit_target_pct) and has_sl:
        return Conviction.HIGH

    if _HIGH_CONVICTION_KEYWORDS.search(text):
        return Conviction.HIGH

    if has_entry and has_target and has_sl:
        return Conviction.HIGH

    if _LOW_CONVICTION_KEYWORDS.search(text) and not (has_entry and has_target and has_sl) \
            and not (options and options.present):
        return Conviction.LOW

    return Conviction.MEDIUM


def _resolve_conviction(llm: Conviction, heuristic: Conviction) -> Conviction:
    """Heuristic wins when decisive (HIGH/LOW); otherwise preserve LLM output."""
    if heuristic in (Conviction.HIGH, Conviction.LOW):
        return heuristic
    return llm


def _fallback_parse(url: str, analyst: str, text: str) -> ParsedTweet:
    """Regex fallback when model fails. Extracts tickers and detects direction from keywords."""
    tickers = [t for t in extract_tickers(text) if t not in _INDICATOR_NAMES]
    tweet_type = TweetType.TICKER_CALLOUT if tickers else TweetType.SENTIMENT

    lower = text.lower()
    long_hits = sum(1 for kw in _LONG_KEYWORDS if kw in lower)
    short_hits = sum(1 for kw in _SHORT_KEYWORDS if kw in lower)
    if long_hits > short_hits:
        direction = Direction.LONG
    elif short_hits > long_hits:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    return ParsedTweet(
        tweet_url=url,
        analyst=analyst,
        raw_text=text,
        tweet_type=tweet_type,
        tickers=tickers,
        direction=direction,
        options=None,
        conviction=_infer_conviction(text, None),
        summary=text[:100],
    )


def _to_float(val) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def parse_tweet(
    url: str,
    analyst: str,
    text: str,
    image_url: Optional[str] = None,
    image_urls: Optional[list[str]] = None,
) -> ParsedTweet:
    """Parse a tweet using hybrid multimodal routing with regex fallback."""
    images = list(image_urls or [])
    if image_url and image_url not in images:
        images.append(image_url)

    try:
        payload = await process_multimodal_tweet({
            "url": url,
            "analyst": analyst,
            "text": text,
            "image_urls": images,
        })
        parsed = _parse_model_payload(payload, url, analyst, text)
    except Exception as e:
        log.warning("Tweet parse error for @%s: %s", analyst, e)
        parsed = _fallback_parse(url, analyst, text)

    parsed.image_url = images[0] if images else None
    parsed.image_urls = images
    if not parsed.final_signal:
        parsed.final_signal = {
            "ticker": parsed.tickers[0] if parsed.tickers else "",
            "signal": "bullish" if parsed.direction == Direction.LONG else "bearish" if parsed.direction == Direction.SHORT else "neutral",
            "confidence": float(parsed.base_score / 100),
            "reason": parsed.summary,
            "key_levels": {"bull_case": None, "base_case": None, "bear_case": None},
            "source_types": ["text"] + (["image"] if images else []),
        }
    return parsed


# =============================================================================
# Image Analysis - Vision-enabled LLM to analyze tweet images
# =============================================================================

IMAGE_SYSTEM_PROMPT = """You are a financial analyst examining a chart or image from a stock market tweet.

Analyze this image and extract any trading information visible. Look for:
1. Stock tickers (often shown in chart titles, labels, or annotations)
2. Price levels (support, resistance, targets, entry prices)
3. Direction indicators (bullish/bearish labels, arrows, color coding)
4. Chart patterns (breakouts, breakdowns, consolidations)
5. Any text annotations with trade ideas

Respond ONLY in this exact JSON format:
{
  "tickers": ["TICKER1"],  // stock symbols visible in the image
  "direction": "long|short|neutral",  // overall direction suggested by the chart
  "price_levels": {
    "support": [<numbers>],
    "resistance": [<numbers>],
    "targets": [<numbers>]
  },
  "summary": "<what the chart shows in one sentence>"
}

If no trading information is visible, return:
{
  "tickers": [],
  "direction": "neutral",
  "price_levels": {},
  "summary": "No clear trading information visible"
}
"""


async def analyze_tweet_image(image_url: str, session: aiohttp.ClientSession, api_key: str) -> dict:
    """Fetch and analyze an image from a tweet using vision-capable LLM."""
    if not image_url or not api_key:
        return {"tickers": [], "direction": "neutral", "price_levels": {}, "summary": ""}
    
    try:
        # Fetch the image
        async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                log.debug("Failed to fetch image: %d", resp.status)
                return {"tickers": [], "direction": "neutral", "price_levels": {}, "summary": ""}
            image_data = await resp.read()
        
        # For now, we'll use a simple approach - base64 encode and send to a vision model
        # This is a placeholder - in production you'd use Claude/GPT-4V
        # The key insight is: we CAN analyze images, we just need to implement it
        
        # Return placeholder - actual vision LLM integration would go here
        return {"tickers": [], "direction": "neutral", "price_levels": {}, "summary": ""}
        
    except Exception as e:
        log.debug("Image analysis error: %s", e)
        return {"tickers": [], "direction": "neutral", "price_levels": {}, "summary": ""}
