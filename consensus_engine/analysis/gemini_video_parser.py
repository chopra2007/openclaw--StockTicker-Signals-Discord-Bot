"""Gemini fast-path for YouTube video analysis.

Passes a YouTube URL directly to gemini-2.5-flash-lite. One API call
extracts tickers, price levels (including visually annotated chart lines),
options, trade setups, and macro thesis. Returns ParsedVideo or None on failure.
"""

import asyncio
import json
import logging
import os
import re
import time

from consensus_engine import config as cfg, db
from consensus_engine.models import (
    ParsedVideo, Direction, Conviction, PriceLevel, MacroThesis,
    VideoOptionIdea, VideoTradeSetup,
)

log = logging.getLogger("consensus_engine.analysis.gemini_video_parser")

_MACRO_NORM = {"bullish": "long", "bearish": "short", "neutral": "neutral"}

_GEMINI_PROMPT = """You are a financial analyst extracting structured trade intelligence from a YouTube video.

Watch the full video and respond ONLY with this exact JSON (no markdown, no extra text):
{
  "tickers": [
    {"symbol": "NVDA", "direction": "long|short|neutral", "conviction": "high|medium|low", "mention_count": 3, "context": "why this direction — quote or paraphrase"}
  ],
  "price_levels": [
    {"ticker": "NVDA", "type": "support|resistance|target|breakdown", "price": 850.0, "context": "quote or description of where this level comes from"}
  ],
  "macro_thesis": {
    "direction": "bullish|bearish|neutral",
    "themes": ["theme1", "theme2"],
    "timeframe": "short|medium|long",
    "summary": "1-2 sentence summary of the macro view"
  },
  "options": [
    {"ticker": "TSLA", "option_type": "call|put", "strike": 250.0, "expiry": "weekly", "strategy": "single|spread|leaps|debit|credit", "source": "flow_observation|personal_idea", "conviction": "high|medium|low", "context": "exact quote or paraphrase"}
  ],
  "setups": [
    {"ticker": "NVDA", "entry_low": 845.0, "entry_high": 855.0, "stop": 820.0, "targets": [920.0], "timeframe": "intraday|swing|positional|long-term", "setup_type": "breakout|pullback|earnings|trend", "context": "exact quote or paraphrase"}
  ],
  "overall_conviction": "high|medium|low"
}

Extraction rules:
- Only real stock tickers (AAPL, NVDA, SPY, etc.). Exclude RSI, EMA, MACD, VWAP, SMA, ATR, etc.
- price_levels: include BOTH verbally mentioned prices AND price levels visible as annotated lines or labels on charts in the video.
- options: empty array if none discussed. strike is null if not mentioned.
- setups: link entry/stop/target only when the speaker presents them together. Empty array if unclear.
- context: quote or closely paraphrase the speaker for every extracted item.
- If no tickers found, return empty arrays for tickers, price_levels, options, setups."""


def _get_gemini_client():
    """Return a configured Gemini client, or None if API key is absent."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        log.debug("gemini_video_parser: GEMINI_API_KEY not set")
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        log.warning("gemini_video_parser: failed to init client: %s", e)
        return None


def _parse_gemini_response(raw: str) -> dict | None:
    """Parse JSON from Gemini response, stripping markdown fences if present."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        log.debug("gemini_video_parser: JSON parse failed, raw=%r", cleaned[:200])
        return None


def _build_parsed_video(
    data: dict, video_id: str, channel_name: str, published_at: str, run_id: int
) -> ParsedVideo:
    """Convert Gemini JSON response dict into a ParsedVideo."""
    # Tickers
    raw_tickers = data.get("tickers", [])
    _dir_norm = {"long": "long", "short": "short", "neutral": "neutral",
                 "bullish": "long", "bearish": "short"}
    normalized_tickers = []
    for t in raw_tickers:
        if not isinstance(t, dict):
            continue
        sym = str(t.get("symbol", "")).upper()
        if not sym:
            continue
        direction = _dir_norm.get(str(t.get("direction", "neutral")).lower(), "neutral")
        normalized_tickers.append({
            "symbol": sym,
            "direction": direction,
            "conviction": str(t.get("conviction", "medium")).lower(),
            "mention_count": int(t.get("mention_count", 1)),
            "context": str(t.get("context", "")),
            "source_snippet": str(t.get("context", ""))[:200],
            "chunk_id": 0,
        })

    # Price levels
    price_levels = []
    for lv in data.get("price_levels", []):
        if not isinstance(lv, dict):
            continue
        try:
            price = float(lv["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0:
            continue
        price_levels.append(PriceLevel(
            ticker=str(lv.get("ticker", "")).upper(),
            level_type=str(lv.get("type", "support")).lower(),
            price=price,
            condition=str(lv.get("context", "")),
            consequence="",
            confidence=0.8,
        ))

    # Macro thesis
    macro_data = data.get("macro_thesis", {})
    raw_dir = str(macro_data.get("direction", "neutral")).lower()
    macro_thesis = MacroThesis(
        direction=Direction(_MACRO_NORM.get(raw_dir, "neutral")),
        themes=macro_data.get("themes", []) if isinstance(macro_data.get("themes"), list) else [],
        timeframe=str(macro_data.get("timeframe", "short")).lower(),
        summary=str(macro_data.get("summary", "")),
    )

    # Options
    options: list[VideoOptionIdea] = []
    for o in data.get("options", []):
        if not isinstance(o, dict):
            continue
        ticker = str(o.get("ticker", "")).upper()
        opt_type = str(o.get("option_type", "")).lower()
        if not ticker or opt_type not in ("call", "put"):
            continue
        strike = None
        if o.get("strike") is not None:
            try:
                strike = float(o["strike"])
            except (ValueError, TypeError):
                pass
        options.append(VideoOptionIdea(
            ticker=ticker, option_type=opt_type,
            strike=strike, expiry=o.get("expiry"),
            strategy=o.get("strategy"), source=o.get("source"),
            conviction=str(o.get("conviction", "medium")).lower(),
            context=str(o.get("context", "")),
            source_snippet=str(o.get("context", ""))[:200],
            chunk_id=0,
        ))

    # Setups
    setups: list[VideoTradeSetup] = []
    for s in data.get("setups", []):
        if not isinstance(s, dict):
            continue
        ticker = str(s.get("ticker", "")).upper()
        entry_low = None
        if s.get("entry_low") is not None:
            try:
                entry_low = float(s["entry_low"])
            except (ValueError, TypeError):
                pass
        if not ticker or entry_low is None:
            continue
        entry_high = float(s["entry_high"]) if s.get("entry_high") is not None else entry_low
        stop = float(s["stop"]) if s.get("stop") is not None else None
        targets = []
        for t in (s.get("targets") or []):
            try:
                targets.append(float(t))
            except (ValueError, TypeError):
                pass
        # Compute R/R
        rr = None
        if stop and targets:
            mid = (entry_low + entry_high) / 2
            if mid > stop:
                rr = round((targets[0] - mid) / (mid - stop), 2)
        context = str(s.get("context", ""))
        setups.append(VideoTradeSetup(
            ticker=ticker, entry_low=entry_low, entry_high=entry_high,
            stop=stop, targets=targets,
            timeframe=s.get("timeframe"), setup_type=s.get("setup_type"),
            context=context, source_snippet=context[:200],
            chunk_id=0, risk_reward=rr,
        ))

    # Overall conviction
    conv_map = {"high": Conviction.HIGH, "medium": Conviction.MEDIUM, "low": Conviction.LOW}
    overall = conv_map.get(str(data.get("overall_conviction", "medium")).lower(), Conviction.MEDIUM)

    return ParsedVideo(
        video_id=video_id, channel_name=channel_name,
        raw_transcript="",  # Gemini path — no transcript text stored
        tickers=normalized_tickers, price_levels=price_levels,
        macro_thesis=macro_thesis, overall_conviction=overall,
        parsed_at=time.time(), run_id=run_id,
        options=options, setups=setups,
    )


async def parse_video_with_gemini(
    video_id: str,
    channel_name: str,
    published_at: str,
) -> ParsedVideo | None:
    """Analyze a YouTube video via Gemini. Returns ParsedVideo or None on any failure.

    Passes the YouTube URL directly — Gemini processes the full video including
    visually annotated chart levels. No transcript download needed.
    """
    client = _get_gemini_client()
    if client is None:
        return None

    model = cfg.get("youtube.gemini_model", "gemini-2.5-flash-lite")
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        from google.genai import types

        def _sync_call():
            return client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_text(text=_GEMINI_PROMPT),
                    types.Part.from_uri(
                        file_uri=youtube_url,
                        mime_type="video/*",
                    ),
                ],
            )

        # Run sync Gemini SDK call in thread executor (it's not async-native)
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=60,
        )
        raw = response.text
    except asyncio.TimeoutError:
        log.warning("gemini_video_parser: timeout for %s", video_id)
        return None
    except Exception as e:
        log.warning("gemini_video_parser: API error for %s: %s", video_id, e)
        return None

    data = _parse_gemini_response(raw)
    if data is None:
        log.warning("gemini_video_parser: unparseable response for %s", video_id)
        return None

    parser_version = f"gemini/{model}"
    try:
        run_id = await db.create_analysis_run(video_id, parser_version)
    except Exception as e:
        log.warning("gemini_video_parser: could not create analysis run for %s: %s", video_id, e)
        return None

    parsed = _build_parsed_video(data, video_id, channel_name, published_at, run_id)
    log.info(
        "gemini_video_parser: %s → %d tickers, %d levels, %d options, %d setups",
        video_id, len(parsed.tickers), len(parsed.price_levels),
        len(parsed.options), len(parsed.setups),
    )
    return parsed
