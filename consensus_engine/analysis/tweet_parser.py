"""Tweet Parser — LLM-based intent extraction from analyst tweets.

Classifies each tweet as:
  A (ticker callout) — actionable
  B (macro/geo)      — context only
  C (options trade)   — actionable
  D (sentiment)       — context only

Extracts tickers, direction, options details, conviction level.
Falls back to regex extraction if LLM fails.
"""

import json
import logging
import re
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.models import (
    ParsedTweet, OptionsDetail, TweetType, Direction, Conviction,
)
from consensus_engine.utils.tickers import extract_tickers

log = logging.getLogger("consensus_engine.analysis.tweet_parser")

_SYSTEM_PROMPT = """You are a stock market tweet classifier. Given a tweet from a financial analyst, extract structured trade information.

Respond ONLY in this exact JSON format (no extra text, no markdown):
{
  "type": "A|B|C|D",
  "tickers": ["TICKER1"],
  "direction": "long|short|neutral",
  "options": {
    "present": true|false,
    "strike": <number or null>,
    "expiry": "<YYYY-MM-DD or null>",
    "type": "call|put|null",
    "target_price": <number or null>,
    "profit_target_pct": <number or null>
  },
  "conviction": "high|medium|low",
  "summary": "<one-line summary of the trade idea>"
}

Classification rules:
- Type A: Explicit ticker mention with directional language ("buying NVDA", "long USO", "$AAPL looks good")
- Type B: Macro/geopolitical commentary implying trades ("Strait of Hormuz closing", "Fed rate decision")
- Type C: Options trade with any of: strike price, expiry, calls/puts ("TSLA 500c Friday", "buying puts on SPY")
- Type D: General market sentiment with no specific ticker ("market weak", "careful out there"), life quotes, philosophical statements, motivational content, non-financial tweets

CRITICAL — indicator names are NOT tickers:
RSI, EMA, MACD, VWAP, SMA, ATR, RVOL, ADX, MFI, OBV, CCI, DMI, DOJI, BOLL are technical indicator names.
Do NOT include them in the tickers array. If the tweet mentions "RSI oversold on NVDA", the only ticker is NVDA.
If a tweet has NO actual stock ticker, return type D with an empty tickers array.

Conviction rules:
- high: "bought", "loaded", "all in", "adding more", mentions position size
- medium: "buying", "looking at", "watching for entry", "like this setup"
- low: "might", "considering", "interesting", "on radar", "watching"

If the tweet mentions both a ticker AND options details (strike/expiry/calls/puts), classify as C not A.
If no specific ticker is mentioned, tickers should be an empty array.
Always return valid JSON."""


def _build_parser_prompt(analyst: str, text: str) -> str:
    """Build the user prompt for the LLM."""
    return f"Analyst: @{analyst}\nTweet: {text}"


async def _call_openrouter(user_prompt: str) -> str:
    """Call OpenRouter API and return raw response text."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return ""

    model = cfg.get("llm.model", "minimax/minimax-m2.5")

    async with aiohttp.ClientSession() as session:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 512,
            "temperature": 0.1,
        }

        async with session.post(
            url, headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                log.warning("OpenRouter error (%d) for tweet parse", resp.status)
                return ""
            data = await resp.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content.strip()


def _parse_llm_response(raw: str, url: str, analyst: str, original_text: str) -> ParsedTweet:
    """Parse the LLM JSON response into a ParsedTweet. Falls back to regex on failure."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        log.debug("LLM parse failed, falling back to regex for: %s", original_text[:100])
        return _fallback_parse(url, analyst, original_text)

    raw_type = str(data.get("type", "A")).upper()
    type_map = {"A": TweetType.TICKER_CALLOUT, "B": TweetType.MACRO,
                "C": TweetType.OPTIONS_TRADE, "D": TweetType.SENTIMENT}
    tweet_type = type_map.get(raw_type, TweetType.TICKER_CALLOUT)

    raw_dir = str(data.get("direction", "neutral")).lower()
    dir_map = {"long": Direction.LONG, "short": Direction.SHORT, "neutral": Direction.NEUTRAL}
    direction = dir_map.get(raw_dir, Direction.NEUTRAL)

    raw_conv = str(data.get("conviction", "medium")).lower()
    conv_map = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}
    conviction = conv_map.get(raw_conv, Conviction.MEDIUM)

    tickers = data.get("tickers", [])
    if not isinstance(tickers, list):
        tickers = []
    tickers = [t.upper() for t in tickers if isinstance(t, str)]

    options_data = data.get("options", {})
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

    summary = str(data.get("summary", ""))

    return ParsedTweet(
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


_INDICATOR_NAMES = {"RSI", "EMA", "MACD", "VWAP", "SMA", "RVOL", "ATR", "ADX", "MFI", "OBV", "CCI", "DMI", "DOJI", "BOLL"}


def _fallback_parse(url: str, analyst: str, text: str) -> ParsedTweet:
    """Regex fallback when LLM fails. Extracts tickers, defaults to Type A medium."""
    tickers = [t for t in extract_tickers(text) if t not in _INDICATOR_NAMES]
    tweet_type = TweetType.TICKER_CALLOUT if tickers else TweetType.SENTIMENT
    return ParsedTweet(
        tweet_url=url,
        analyst=analyst,
        raw_text=text,
        tweet_type=tweet_type,
        tickers=tickers,
        direction=Direction.NEUTRAL,
        options=None,
        conviction=Conviction.MEDIUM,
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


async def parse_tweet(url: str, analyst: str, text: str, image_url: Optional[str] = None) -> ParsedTweet:
    """Parse a tweet using LLM with regex fallback.

    This is the main entry point called by the pipeline.
    """
    user_prompt = _build_parser_prompt(analyst, text)

    try:
        raw_response = await _call_openrouter(user_prompt)
        if not raw_response:
            parsed = _fallback_parse(url, analyst, text)
        else:
            parsed = _parse_llm_response(raw_response, url, analyst, text)
    except Exception as e:
        log.warning("Tweet parse error for @%s: %s", analyst, e)
        parsed = _fallback_parse(url, analyst, text)

    parsed.image_url = image_url
    return parsed
