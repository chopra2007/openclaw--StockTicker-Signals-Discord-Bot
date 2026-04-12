"""Video Parser — LLM-based extraction from YouTube financial transcripts.

Extracts structured trade intelligence from long-form video content:
- Tickers and directional sentiment (long/short/neutral)
- Price levels (support/resistance/targets)
- Macro thesis and market direction
- Overall conviction level

Mirrors tweet_parser.py but handles chunking for long transcripts.
Uses Groq API (free tier) or OpenRouter as fallback.
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.models import (
    ParsedVideo, Direction, Conviction, PriceLevel, MacroThesis,
)
from consensus_engine.utils.tickers import extract_tickers

log = logging.getLogger("consensus_engine.analysis.video_parser")

_SYSTEM_PROMPT = """You are a financial analyst extracting structured trade intelligence from a YouTube video transcript.

Respond ONLY in this exact JSON format (no extra text, no markdown):
{
  "tickers": [
    {
      "symbol": "SPY",
      "direction": "long|short|neutral",
      "conviction": "high|medium|low",
      "mention_count": 3,
      "context": "why this direction"
    }
  ],
  "price_levels": [
    {
      "ticker": "SPY",
      "type": "support|resistance|target|breakdown",
      "price": 650.0,
      "condition": "if holds above 640",
      "consequence": "rally to 700",
      "confidence": 0.85
    }
  ],
  "macro_thesis": {
    "direction": "bullish|bearish|neutral",
    "themes": ["recession risk", "Fed pivot expected"],
    "timeframe": "short|medium|long",
    "summary": "one paragraph summarizing the macro view"
  },
  "overall_conviction": "high|medium|low"
}

Extraction rules:
- Only include actual stock tickers (SPY, AAPL, NVDA, etc.)
- Exclude technical indicators (RSI, EMA, MACD, VWAP, etc.)
- Exclude exchange/venue names (CME, NYSE, NASDAQ, etc.)
- If a price level is mentioned, extract the specific number
- Conviction levels: high=explicit position, medium=strong opinion, low=tentative view
- For macro thesis, identify dominant themes and timeframe
- If no tickers mentioned, return empty tickers array
- Always return valid JSON, no markdown or extra text."""


def _build_parser_prompt(transcript_chunk: str) -> str:
    """Build the user prompt for the LLM."""
    return f"Transcript excerpt:\n\n{transcript_chunk}"


async def _call_groq(user_prompt: str) -> str:
    """Call Groq API (free tier, 30 req/min) with fallback to OpenRouter."""
    groq_key = cfg.get_api_key("groq")
    if not groq_key:
        log.debug("Groq API key not configured, trying OpenRouter")
        return await _call_openrouter(user_prompt)

    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            }
            model = cfg.get("video_parser.groq_model", "mixtral-8x7b-32768")
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 2048,
                "temperature": 0.1,
            }

            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    log.warning("Groq error (%d), falling back to OpenRouter", resp.status)
                    return await _call_openrouter(user_prompt)
                data = await resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        if not content:
            log.debug("Groq empty content, falling back to OpenRouter")
            return await _call_openrouter(user_prompt)
        return content.strip()
    except Exception as e:
        log.warning("Groq call error: %s, trying OpenRouter", e)
        return await _call_openrouter(user_prompt)


async def _call_openrouter(user_prompt: str) -> str:
    """Call OpenRouter API and return raw response text."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return ""

    model = cfg.get("llm.model", "minimax/minimax-m2.5")

    try:
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
                "max_tokens": 4096,
                "temperature": 0.1,
            }

            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    log.warning("OpenRouter error (%d) for video parse", resp.status)
                    return ""
                data = await resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        return content.strip()
    except Exception as e:
        log.warning("OpenRouter call error: %s", e)
        return ""


def _parse_llm_response(raw: str, video_id: str, transcript: str) -> dict:
    """Parse the LLM JSON response into structured data. Falls back to regex on failure."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)

    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        log.debug("LLM parse failed for video %s, falling back to regex", video_id)
        return _fallback_parse(transcript)

    # Normalize direction enum
    raw_dir = str(data.get("direction", "neutral")).lower()
    dir_map = {"long": Direction.LONG, "short": Direction.SHORT, "neutral": Direction.NEUTRAL}

    # Normalize conviction enum
    raw_conv = str(data.get("overall_conviction", "medium")).lower()
    conv_map = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}

    # Clean and normalize tickers
    tickers = data.get("tickers", [])
    if not isinstance(tickers, list):
        tickers = []

    # Build normalized tickers list
    normalized_tickers = []
    for t in tickers:
        if isinstance(t, dict):
            symbol = str(t.get("symbol", "")).upper()
            direction = t.get("direction", "neutral").lower()
            conviction = t.get("conviction", "medium").lower()
            normalized_tickers.append({
                "symbol": symbol,
                "direction": direction,
                "conviction": conviction,
                "mention_count": t.get("mention_count", 1),
                "context": t.get("context", ""),
            })

    # Parse price levels
    price_levels = []
    for level in data.get("price_levels", []):
        if isinstance(level, dict):
            try:
                price = float(level.get("price", 0))
                if price > 0:  # Valid price
                    price_levels.append({
                        "ticker": str(level.get("ticker", "")).upper(),
                        "type": str(level.get("type", "support")).lower(),
                        "price": price,
                        "condition": str(level.get("condition", "")),
                        "consequence": str(level.get("consequence", "")),
                        "confidence": float(level.get("confidence", 0.8)),
                    })
            except (ValueError, TypeError):
                pass

    # Parse macro thesis
    macro_data = data.get("macro_thesis", {})
    macro_thesis = {
        "direction": str(macro_data.get("direction", "neutral")).lower(),
        "themes": macro_data.get("themes", []) if isinstance(macro_data.get("themes", []), list) else [],
        "timeframe": str(macro_data.get("timeframe", "medium")).lower(),
        "summary": str(macro_data.get("summary", "")),
    }

    return {
        "tickers": normalized_tickers,
        "price_levels": price_levels,
        "macro_thesis": macro_thesis,
        "overall_conviction": conv_map.get(raw_conv, Conviction.MEDIUM),
    }


_INDICATOR_NAMES = {"RSI", "EMA", "MACD", "VWAP", "SMA", "RVOL", "ATR", "ADX", "MFI", "OBV", "CCI", "DMI", "DOJI", "BOLL"}
_LONG_KEYWORDS = {"long", "buy", "bullish", "calls", "breakout", "rally", "pump", "moon"}
_SHORT_KEYWORDS = {"short", "put", "bearish", "dump", "crash", "sell", "drop", "fade"}


def _fallback_parse(transcript: str) -> dict:
    """Regex fallback when LLM fails. Extracts tickers and detects direction from keywords."""
    tickers_found = [t for t in extract_tickers(transcript) if t not in _INDICATOR_NAMES]

    lower = transcript.lower()
    long_hits = sum(1 for kw in _LONG_KEYWORDS if kw in lower)
    short_hits = sum(1 for kw in _SHORT_KEYWORDS if kw in lower)

    if long_hits > short_hits:
        direction = Direction.LONG
    elif short_hits > long_hits:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL

    normalized_tickers = [
        {
            "symbol": t,
            "direction": direction.value,
            "conviction": "medium",
            "mention_count": 1,
            "context": "fallback extraction",
        }
        for t in tickers_found
    ]

    return {
        "tickers": normalized_tickers,
        "price_levels": [],
        "macro_thesis": {
            "direction": direction.value,
            "themes": [],
            "timeframe": "short",
            "summary": "fallback extraction",
        },
        "overall_conviction": Conviction.MEDIUM,
    }


def _chunk_transcript(text: str, chunk_size: int = 300) -> list[str]:
    """Split transcript into overlapping chunks (in words, not chars)."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size // 2):  # 50% overlap
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


async def _chunk_and_analyze(transcript_text: str) -> list[dict]:
    """Split long transcript into chunks and analyze each in parallel."""
    chunks = _chunk_transcript(transcript_text)
    if len(chunks) <= 1:
        # Short transcript, analyze as-is
        prompt = _build_parser_prompt(transcript_text)
        raw = await _call_groq(prompt)
        return [_parse_llm_response(raw, "chunk_0", transcript_text)]

    # Analyze chunks in parallel with semaphore to avoid rate-limiting
    sem = asyncio.Semaphore(2)  # Max 2 concurrent LLM calls
    tasks = []
    for i, chunk in enumerate(chunks):
        async def _analyze_chunk(idx: int, c: str):
            async with sem:
                prompt = _build_parser_prompt(c)
                raw = await _call_groq(prompt)
                return _parse_llm_response(raw, f"chunk_{idx}", c)
        tasks.append(_analyze_chunk(i, chunk))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]


def _merge_chunk_results(chunks: list[dict]) -> dict:
    """Merge results from multiple chunks into a single coherent result."""
    if not chunks:
        return {
            "tickers": [],
            "price_levels": [],
            "macro_thesis": {
                "direction": "neutral",
                "themes": [],
                "timeframe": "short",
                "summary": "no data",
            },
            "overall_conviction": Conviction.MEDIUM,
        }

    if len(chunks) == 1:
        return chunks[0]

    # Merge tickers: union by symbol, keep highest conviction
    ticker_map = {}
    for chunk in chunks:
        for ticker in chunk.get("tickers", []):
            symbol = ticker.get("symbol")
            if symbol not in ticker_map:
                ticker_map[symbol] = ticker
            else:
                # Keep highest conviction
                conv_order = {"high": 3, "medium": 2, "low": 1}
                old_conv = conv_order.get(ticker_map[symbol].get("conviction", "low"), 0)
                new_conv = conv_order.get(ticker.get("conviction", "low"), 0)
                if new_conv > old_conv:
                    ticker_map[symbol] = ticker
                else:
                    # Increment mention count
                    ticker_map[symbol]["mention_count"] = ticker_map[symbol].get("mention_count", 1) + 1

    # Merge price levels: take highest confidence per type per ticker
    level_map = {}
    for chunk in chunks:
        for level in chunk.get("price_levels", []):
            key = (level.get("ticker"), level.get("type"), level.get("price"))
            if key not in level_map:
                level_map[key] = level
            else:
                # Keep higher confidence
                if level.get("confidence", 0) > level_map[key].get("confidence", 0):
                    level_map[key] = level

    # Merge macro thesis: majority-vote direction, union themes
    macro_direction_votes = {"long": 0, "short": 0, "neutral": 0}
    all_themes = set()
    macro_summaries = []
    timeframe_votes = {}

    for chunk in chunks:
        macro = chunk.get("macro_thesis", {})
        direction = macro.get("direction", "neutral")
        macro_direction_votes[direction] = macro_direction_votes.get(direction, 0) + 1

        for theme in macro.get("themes", []):
            all_themes.add(theme)

        summary = macro.get("summary", "")
        if summary:
            macro_summaries.append(summary)

        timeframe = macro.get("timeframe", "short")
        timeframe_votes[timeframe] = timeframe_votes.get(timeframe, 0) + 1

    macro_direction = max(macro_direction_votes, key=macro_direction_votes.get)
    macro_timeframe = max(timeframe_votes, key=timeframe_votes.get) if timeframe_votes else "short"
    macro_summary = " ".join(macro_summaries[:2])  # Top 2 summaries

    # Highest conviction from any chunk
    max_conviction = Conviction.MEDIUM
    for chunk in chunks:
        conv = chunk.get("overall_conviction", Conviction.MEDIUM)
        conv_order = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}
        if conv_order.get(conv, Conviction.MEDIUM) == Conviction.HIGH:
            max_conviction = Conviction.HIGH

    return {
        "tickers": list(ticker_map.values()),
        "price_levels": list(level_map.values()),
        "macro_thesis": {
            "direction": macro_direction,
            "themes": list(all_themes),
            "timeframe": macro_timeframe,
            "summary": macro_summary,
        },
        "overall_conviction": max_conviction,
    }


async def parse_video_transcript(
    video_id: str,
    transcript_text: str,
    channel_name: str,
    published_at: str,
) -> ParsedVideo:
    """Parse a YouTube video transcript using LLM with chunking for long videos.

    This is the main entry point called by the pipeline.
    """
    try:
        # For videos > 2000 words, use chunking
        word_count = len(transcript_text.split())
        if word_count > 2000:
            log.info("video_parser: chunking long transcript for %s (%d words)", video_id, word_count)
            chunk_results = await _chunk_and_analyze(transcript_text)
            parsed_data = _merge_chunk_results(chunk_results)
        else:
            # Short transcript, analyze as-is
            prompt = _build_parser_prompt(transcript_text)
            raw = await _call_groq(prompt)
            parsed_data = _parse_llm_response(raw, video_id, transcript_text)

    except Exception as e:
        log.warning("Video parse error for %s: %s", video_id, e)
        parsed_data = _fallback_parse(transcript_text)

    # Convert parsed_data to ParsedVideo dataclass
    # Build PriceLevel objects
    price_levels = [
        PriceLevel(
            ticker=level["ticker"],
            level_type=level["type"],
            price=level["price"],
            condition=level["condition"],
            consequence=level["consequence"],
            confidence=level["confidence"],
        )
        for level in parsed_data.get("price_levels", [])
    ]

    # Build MacroThesis object
    macro_data = parsed_data.get("macro_thesis", {})
    macro_thesis = MacroThesis(
        direction=Direction(macro_data.get("direction", "neutral")),
        themes=macro_data.get("themes", []),
        timeframe=macro_data.get("timeframe", "short"),
        summary=macro_data.get("summary", ""),
    )

    # Get overall conviction
    conviction_val = parsed_data.get("overall_conviction", Conviction.MEDIUM)
    if isinstance(conviction_val, str):
        conviction_val = Conviction(conviction_val)

    return ParsedVideo(
        video_id=video_id,
        channel_name=channel_name,
        raw_transcript=transcript_text,
        tickers=parsed_data.get("tickers", []),
        price_levels=price_levels,
        macro_thesis=macro_thesis,
        overall_conviction=conviction_val,
        parsed_at=time.time(),
    )
