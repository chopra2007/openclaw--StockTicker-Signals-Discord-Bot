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

from consensus_engine import config as cfg, db
from consensus_engine.models import (
    ParsedVideo, Direction, Conviction, PriceLevel, MacroThesis,
    VideoOptionIdea, VideoTradeSetup,
)
from consensus_engine.utils.tickers import extract_tickers

log = logging.getLogger("consensus_engine.analysis.video_parser")

_MACRO_NORM = {"bullish": "long", "bearish": "short", "neutral": "neutral"}

# ── Two-stage parser constants ─────────────────────────────────────────────────
PARSER_VERSION = "v2"

_MAX_LLM_CALLS = 8  # hard cap per video

_MENTIONS_PROMPT = """You are extracting structured financial mentions from a YouTube transcript.

Respond ONLY in this exact JSON (no markdown):
{
  "tickers": [{"symbol": "NVDA", "mention_count": 3, "source_snippet": "exact quote ≤120 chars"}],
  "price_spans": [{"ticker": "NVDA", "price": 850.0, "source_snippet": "exact quote ≤120 chars"}],
  "option_keywords_found": false
}

Rules:
- Only real stock tickers (AAPL, NVDA, SPY). Exclude RSI, EMA, MACD, VWAP, etc.
- price_spans: only explicit price numbers tied to a specific ticker.
- option_keywords_found: true if transcript mentions calls, puts, strike, expiry, debit, credit, spreads, or LEAPS.
- source_snippet: shortest exact phrase from transcript containing the entity (≤120 chars).
- If nothing found, return empty arrays."""

_DIRECTION_PROMPT = """You are classifying directional sentiment for specific tickers in a YouTube transcript.

Tickers to classify: {ticker_list}

Respond ONLY in this exact JSON (no markdown):
{{"tickers": [{{"symbol": "NVDA", "direction": "long|short|neutral", "conviction": "high|medium|low", "context": "one-sentence reason", "source_snippet": "exact quote ≤120 chars"}}]}}

Rules:
- long=bullish, short=bearish, neutral=no clear bias.
- high=explicit position/trade, medium=strong opinion, low=tentative/watching.
- Only classify tickers from the provided list."""

_MACRO_PROMPT = """You are extracting the macro market thesis from a YouTube financial transcript.

Respond ONLY in this exact JSON (no markdown):
{"macro_thesis": {"direction": "bullish|bearish|neutral", "themes": ["theme1"], "timeframe": "short|medium|long", "summary": "1-2 sentence summary"}}

Rules:
- direction: overall market/macro bias expressed in the video.
- themes: up to 5 specific themes mentioned (e.g. "Fed rate cuts", "earnings season").
- timeframe: short=days/weeks, medium=1-3 months, long=6+ months."""

_OPTIONS_PROMPT = """You are extracting options trade mentions from transcript snippets.

Snippets:
{snippets}

Respond ONLY in this exact JSON (no markdown):
{"options": [{"ticker": "TSLA", "option_type": "call|put", "strike": 250.0, "expiry": "weekly", "strategy": "single|spread|leaps|debit|credit", "source": "flow_observation|personal_idea", "conviction": "high|medium|low", "context": "exact quote"}]}

Rules:
- strike: null if not mentioned. expiry: exact phrase from transcript.
- source: flow_observation if describing market activity; personal_idea if speaker's own trade.
- Skip options without a specific ticker. Return empty array if nothing clear found."""

_SETUPS_PROMPT = """You are linking entry/stop/target prices into coherent trade setups.

Price spans by ticker:
{price_spans_by_ticker}

Respond ONLY in this exact JSON (no markdown):
{"setups": [{"ticker": "NVDA", "entry_low": 845.0, "entry_high": 855.0, "stop": 820.0, "targets": [920.0], "timeframe": "intraday|swing|positional|long-term", "setup_type": "breakout|pullback|earnings|trend", "context": "exact quote"}]}

Rules:
- entry_low/entry_high: same value if exact entry, range if zone given.
- stop and targets: null/[] if not mentioned.
- Only create a setup if at least an entry price exists.
- Never combine prices from different tickers.
- If only isolated prices with no relational context, return empty array."""

_STAGE1_MODEL = "openrouter/minimax/minimax-m2.5:free"
_STAGE2_DIR_MODEL = cfg.get("video_parser.models.direction", "z-ai/glm-4.5-air:free")
_STAGE2_MACRO_MODEL = "openrouter/minimax/minimax-m2.5:free"
_STAGE2_OPTIONS_MODEL = cfg.get("video_parser.models.options", "z-ai/glm-4.5-air:free")
_STAGE2_SETUPS_MODEL = "openrouter/minimax/minimax-m2.5:free"
_MAX_STAGE1_WORDS = 10000  # above this, split into 2 chunks


async def _call_extraction_model(
    system_prompt: str,
    user_prompt: str,
    model: str = "poolside/laguna-m.1:free",
    max_tokens: int = 2048,
) -> tuple[str, bool]:
    """Call OpenRouter with a given model. Returns (content, ok)."""
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        return "", False
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    log.warning("_call_extraction_model: HTTP %d for model %s", resp.status, model)
                    return "", False
                data = await resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        return content.strip(), bool(content)
    except Exception as e:
        log.warning("_call_extraction_model error (%s): %s", model, e)
        return "", False


_OPTION_KEYWORD_RE = re.compile(
    r'\b(calls?|puts?|strike|expir\w+|debit|credit|spread|LEAPS?|weekly|monthly)\b',
    re.IGNORECASE,
)


def _find_option_snippets(text: str, window: int = 300) -> list[str]:
    """Return up to 5 text windows (≤300 chars) around option keywords."""
    snippets = []
    for m in _OPTION_KEYWORD_RE.finditer(text):
        start = max(0, m.start() - window // 2)
        end = min(len(text), m.end() + window // 2)
        snippet = text[start:end].strip()
        if snippet and not any(snippet in s for s in snippets):
            snippets.append(snippet)
        if len(snippets) >= 5:
            break
    return snippets


def _parse_json_safe(raw: str, fallback: dict) -> dict:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return fallback


async def _extract_mentions_pass(transcript_text: str, chunk_id: int = 0) -> dict:
    """Stage 1: extract ticker mentions, price spans, option keyword flag."""
    raw, ok = await _call_extraction_model(
        _MENTIONS_PROMPT,
        f"Transcript:\n\n{transcript_text[:8000]}",
        model=_STAGE1_MODEL,
    )
    if not ok:
        return {"tickers": [], "price_spans": [], "option_keywords_found": False}
    result = _parse_json_safe(raw, {"tickers": [], "price_spans": [], "option_keywords_found": False})
    # Inject chunk_id into every record
    for t in result.get("tickers", []):
        t.setdefault("chunk_id", chunk_id)
    for p in result.get("price_spans", []):
        p.setdefault("chunk_id", chunk_id)
    return result


async def _extract_direction_pass(transcript_text: str, ticker_symbols: list[str]) -> list[dict]:
    """Stage 2a: classify direction+conviction for a known ticker list."""
    if not ticker_symbols:
        return []
    ticker_list = ", ".join(ticker_symbols)
    prompt = _DIRECTION_PROMPT.format(ticker_list=ticker_list)
    raw, ok = await _call_extraction_model(
        prompt,
        f"Transcript (first 3000 words):\n\n{' '.join(transcript_text.split()[:3000])}",
        model=_STAGE2_DIR_MODEL,
        max_tokens=1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"tickers": []})
    return [t for t in data.get("tickers", []) if isinstance(t, dict) and t.get("symbol")]


async def _extract_macro_pass(transcript_text: str) -> dict:
    """Stage 2b: extract macro thesis from first 2000 words."""
    excerpt = " ".join(transcript_text.split()[:2000])
    raw, ok = await _call_extraction_model(
        _MACRO_PROMPT,
        f"Transcript:\n\n{excerpt}",
        model=_STAGE2_MACRO_MODEL,
        max_tokens=512,
    )
    if not ok:
        return {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""}
    data = _parse_json_safe(raw, {})
    macro = data.get("macro_thesis", {})
    direction = str(macro.get("direction", "neutral")).lower()
    return {
        "direction": direction,
        "themes": macro.get("themes", []) if isinstance(macro.get("themes"), list) else [],
        "timeframe": str(macro.get("timeframe", "short")).lower(),
        "summary": str(macro.get("summary", "")),
    }


async def _extract_mentions_pass_budgeted(text: str, chunk_id: int, caller) -> dict:
    raw, ok = await caller(
        _MENTIONS_PROMPT,
        f"Transcript:\n\n{text[:8000]}",
        _STAGE1_MODEL,
    )
    if not ok:
        return {"tickers": [], "price_spans": [], "option_keywords_found": False}
    result = _parse_json_safe(raw, {"tickers": [], "price_spans": [], "option_keywords_found": False})
    for t in result.get("tickers", []):
        t.setdefault("chunk_id", chunk_id)
    for p in result.get("price_spans", []):
        p.setdefault("chunk_id", chunk_id)
    return result


async def _extract_direction_pass_budgeted(transcript_text: str, ticker_symbols: list[str], caller) -> list[dict]:
    if not ticker_symbols:
        return []
    ticker_list = ", ".join(ticker_symbols)
    prompt = _DIRECTION_PROMPT.format(ticker_list=ticker_list)
    raw, ok = await caller(
        prompt,
        f"Transcript (first 3000 words):\n\n{' '.join(transcript_text.split()[:3000])}",
        _STAGE2_DIR_MODEL,
        1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"tickers": []})
    return [t for t in data.get("tickers", []) if isinstance(t, dict) and t.get("symbol")]


async def _extract_macro_pass_budgeted(transcript_text: str, caller) -> dict:
    excerpt = " ".join(transcript_text.split()[:2000])
    raw, ok = await caller(_MACRO_PROMPT, f"Transcript:\n\n{excerpt}", _STAGE2_MACRO_MODEL, 512)
    if not ok:
        return {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""}
    data = _parse_json_safe(raw, {})
    macro = data.get("macro_thesis", {})
    direction = _MACRO_NORM.get(str(macro.get("direction", "neutral")).lower(), "neutral")
    return {
        "direction": direction,
        "themes": macro.get("themes", []) if isinstance(macro.get("themes"), list) else [],
        "timeframe": str(macro.get("timeframe", "short")).lower(),
        "summary": str(macro.get("summary", "")),
    }


async def _extract_options_pass_budgeted(snippets: list[str], ticker_symbols: list[str], caller) -> list[VideoOptionIdea]:
    snippets_text = "\n---\n".join(snippets)
    raw, ok = await caller(
        _OPTIONS_PROMPT.format(snippets=snippets_text),
        "Extract all options mentions from the snippets above.",
        _STAGE2_OPTIONS_MODEL,
        1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"options": []})
    out = []
    for o in data.get("options", []):
        if not isinstance(o, dict):
            continue
        ticker = str(o.get("ticker", "")).upper()
        if not ticker or ticker not in ticker_symbols:
            continue
        opt_type = str(o.get("option_type", "")).lower()
        if opt_type not in ("call", "put"):
            continue
        out.append(VideoOptionIdea(
            ticker=ticker, option_type=opt_type,
            strike=float(o["strike"]) if o.get("strike") is not None else None,
            expiry=o.get("expiry"), strategy=o.get("strategy"),
            source=o.get("source"), conviction=o.get("conviction", "medium"),
            context=str(o.get("context", "")),
            source_snippet=str(o.get("context", ""))[:200],
            chunk_id=0,
        ))
    return out


async def _extract_setups_pass_budgeted(price_spans: list[dict], caller) -> list[VideoTradeSetup]:
    by_ticker: dict[str, list[dict]] = {}
    for ps in price_spans:
        sym = str(ps.get("ticker", "")).upper()
        if sym:
            by_ticker.setdefault(sym, []).append(ps)
    if not by_ticker:
        return []
    spans_text = "\n".join(
        f"{sym}: " + "; ".join(f"${p['price']:.2f} ({p.get('source_snippet', '')})" for p in spans)
        for sym, spans in by_ticker.items()
    )
    raw, ok = await caller(
        _SETUPS_PROMPT.format(price_spans_by_ticker=spans_text),
        "Link these price spans into trade setups.",
        _STAGE2_SETUPS_MODEL,
        1024,
    )
    if not ok:
        return []
    data = _parse_json_safe(raw, {"setups": []})
    out = []
    for s in data.get("setups", []):
        if not isinstance(s, dict) or not s.get("ticker"):
            continue
        ticker = str(s["ticker"]).upper()
        entry_low = float(s["entry_low"]) if s.get("entry_low") is not None else None
        if entry_low is None:
            continue
        entry_high = float(s.get("entry_high") or entry_low)
        stop = float(s["stop"]) if s.get("stop") is not None else None
        targets = [float(t) for t in (s.get("targets") or []) if t is not None]
        rr = _compute_risk_reward(entry_low, entry_high, stop, targets)
        context = str(s.get("context", ""))
        out.append(VideoTradeSetup(
            ticker=ticker, entry_low=entry_low, entry_high=entry_high,
            stop=stop, targets=targets,
            timeframe=s.get("timeframe"), setup_type=s.get("setup_type"),
            context=context, source_snippet=context[:200],
            chunk_id=0, risk_reward=rr,
        ))
    return out


def _compute_risk_reward(
    entry_low: float | None, entry_high: float | None,
    stop: float | None, targets: list[float],
) -> float | None:
    """Compute R/R: (first_target - midpoint_entry) / (midpoint_entry - stop)."""
    if entry_low is None or stop is None or not targets:
        return None
    mid = ((entry_low or 0) + (entry_high or entry_low or 0)) / 2
    if mid <= stop:
        return None
    rr = (targets[0] - mid) / (mid - stop)
    return round(rr, 2) if rr > 0 else None


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
    """Call OpenRouter via the configured llm.model fallback chain."""
    from consensus_engine.llm_client import call_with_fallback
    return await call_with_fallback(
        role="primary",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4096,
        temperature=0.1,
    )


async def _call_groq_full(user_prompt: str, max_tokens: int = 2048) -> tuple[str, str]:
    """Call Groq and return (content, finish_reason). Falls back to OpenRouter on error."""
    groq_key = cfg.get_api_key("groq")
    if not groq_key:
        content = await _call_openrouter(user_prompt)
        return content, "stop"

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
                "max_tokens": max_tokens,
                "temperature": 0.1,
            }
            async with session.post(
                url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    log.warning("Groq error (%d) in full call, falling back", resp.status)
                    content = await _call_openrouter(user_prompt)
                    return content, "stop"
                data = await resp.json()

        choice = data.get("choices", [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        finish_reason = choice.get("finish_reason") or "stop"
        if not content:
            content = await _call_openrouter(user_prompt)
            return content, "stop"
        return content.strip(), finish_reason
    except Exception as e:
        log.warning("Groq full call error: %s, falling back", e)
        content = await _call_openrouter(user_prompt)
        return content, "stop"


def _parse_llm_response(raw: str, video_id: str, transcript: str) -> dict:
    """Parse the LLM JSON response into structured data. Falls back to regex on failure."""
    from consensus_engine.analysis.ticker_grounding import is_ticker_grounded

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
            # Normalize LLM variations (bullish→long, bearish→short) and reject unknowns
            _TICKER_DIR_NORM = {"bullish": "long", "long": "long", "bearish": "short", "short": "short"}
            direction = _TICKER_DIR_NORM.get(direction, "neutral")
            conviction = t.get("conviction", "medium").lower()
            context = t.get("context", "")
            # Ground against ticker's own context, falling back to full transcript
            # (transcript can be 10K+ words; context is the LLM's own quoted reason).
            if symbol and not (
                is_ticker_grounded(symbol, context)
                or is_ticker_grounded(symbol, transcript)
            ):
                continue
            # Negation gate: flip direction if context contradicts it
            direction = _apply_negation(direction, context)
            normalized_tickers.append({
                "symbol": symbol,
                "direction": direction,
                "conviction": conviction,
                "mention_count": t.get("mention_count", 1),
                "context": context,
            })

    # Parse price levels
    price_levels = []
    for level in data.get("price_levels", []):
        if isinstance(level, dict):
            try:
                price = float(level.get("price", 0))
                if price > 0:  # Valid price
                    lv_ticker = str(level.get("ticker", "")).upper()
                    lv_condition = str(level.get("condition", ""))
                    if lv_ticker and not is_ticker_grounded(lv_ticker, lv_condition):
                        continue
                    price_levels.append({
                        "ticker": lv_ticker,
                        "type": str(level.get("type", "support")).lower(),
                        "price": price,
                        "condition": lv_condition,
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

# Negation patterns that flip a bullish read to neutral
_BULL_NEGATIONS = (
    "not bullish", "not long", "not buying", "don't buy", "wouldn't buy",
    "no longer long", "no longer bullish", "not a bull", "avoid buying",
    "stay away", "not going long", "wouldn't be long",
)
# Negation patterns that flip a bearish read to neutral
_BEAR_NEGATIONS = (
    "not bearish", "not short", "don't short", "covering short",
    "no longer short", "no longer bearish", "not a bear",
)

# Financial context words that validate a plain (non-$) ticker mention
_FINANCIAL_CONTEXT_RE = re.compile(
    r'\b(buy|sell|long|short|bullish|bearish|calls?|puts?|position|trade|entry|exit|'
    r'price|target|support|resistance|breakout|breakdown|invest|hold|watching|'
    r'level|move|setup|thesis|sector|earnings|catalyst)\b',
    re.IGNORECASE,
)
_DOLLAR_TICKER_RE = re.compile(r'\$([A-Z]{1,5})\b')


def _apply_negation(direction: str, context: str) -> str:
    """Flip direction to neutral if context contains negation indicators."""
    ctx = context.lower()
    if direction == "long" and any(neg in ctx for neg in _BULL_NEGATIONS):
        return "neutral"
    if direction == "short" and any(neg in ctx for neg in _BEAR_NEGATIONS):
        return "neutral"
    return direction


def _has_financial_context(ticker: str, text: str) -> bool:
    """Return True if ticker appears with $ prefix OR near financial context words.

    Used in fallback parsing to reject plain-word false positives (e.g. "GAS",
    "OIL") that appear without trading context.
    """
    # $TICKER prefix is strongest signal
    if re.search(rf'\${re.escape(ticker)}\b', text):
        return True
    # Scan 120-char window around each mention for financial vocabulary
    for m in re.finditer(rf'\b{re.escape(ticker)}\b', text):
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        if _FINANCIAL_CONTEXT_RE.search(text[start:end]):
            return True
    return False


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

    # Disambiguation gate: reject plain-word tickers without financial context
    tickers_found = [t for t in tickers_found if _has_financial_context(t, transcript)]
    # Grounding (alias-aware) — redundant with extract_tickers but cheap and
    # ensures Path C output is consistent with Paths A/B.
    from consensus_engine.analysis.ticker_grounding import is_ticker_grounded
    tickers_found = [t for t in tickers_found if is_ticker_grounded(t, transcript)]

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
        direction = _MACRO_NORM.get(direction, direction)
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
    """Two-stage extraction pipeline with budget enforcement and provenance tracking."""
    min_words = int(cfg.get("youtube.min_transcript_length", 250))
    words = transcript_text.split()
    if len(words) < min_words:
        log.info("video_parser: transcript too short for %s (%d words)", video_id, len(words))
        return ParsedVideo(
            video_id=video_id, channel_name=channel_name, raw_transcript=transcript_text,
            tickers=[], price_levels=[],
            macro_thesis=MacroThesis(direction=Direction.NEUTRAL, themes=[], timeframe="short", summary="too short"),
            overall_conviction=Conviction.LOW,
        )

    # Create (or resume) analysis run
    run_id = await db.create_analysis_run(video_id, PARSER_VERSION)
    budget_used = 0

    async def _call_with_budget(system_prompt: str, user_prompt: str, model: str, max_tokens: int = 2048) -> tuple[str, bool]:
        nonlocal budget_used
        if budget_used >= _MAX_LLM_CALLS:
            return "", False
        content, ok = await _call_extraction_model(system_prompt, user_prompt, model, max_tokens)
        budget_used += 1
        return content, ok

    status = "complete"
    try:
        # ── Stage 1: candidate extraction (1–2 calls) ──────────────────────
        if len(words) <= _MAX_STAGE1_WORDS:
            s1 = await _extract_mentions_pass_budgeted(transcript_text, 0, _call_with_budget)
            all_tickers_raw = s1.get("tickers", [])
            all_price_spans = s1.get("price_spans", [])
            option_keywords_found = s1.get("option_keywords_found", False)
        else:
            # Split into 2 chunks
            mid = len(words) // 2
            chunk1 = " ".join(words[:mid + 150])
            chunk2 = " ".join(words[mid - 150:])
            s1a = await _extract_mentions_pass_budgeted(chunk1, 0, _call_with_budget)
            s1b = await _extract_mentions_pass_budgeted(chunk2, 1, _call_with_budget)
            all_tickers_raw = s1a.get("tickers", []) + s1b.get("tickers", [])
            all_price_spans = s1a.get("price_spans", []) + s1b.get("price_spans", [])
            option_keywords_found = s1a.get("option_keywords_found", False) or s1b.get("option_keywords_found", False)

        # Deduplicate ticker symbols
        seen: dict[str, dict] = {}
        for t in all_tickers_raw:
            sym = str(t.get("symbol", "")).upper()
            if sym and sym not in _INDICATOR_NAMES:
                if sym not in seen or t.get("mention_count", 1) > seen[sym].get("mention_count", 1):
                    seen[sym] = t
        unique_symbols = list(seen.keys())

        # ── Stage 2a: direction/conviction (1 call) ─────────────────────────
        direction_records: dict[str, dict] = {}
        if unique_symbols and budget_used < _MAX_LLM_CALLS:
            dir_list = await _extract_direction_pass_budgeted(transcript_text, unique_symbols, _call_with_budget)
            direction_records = {r["symbol"]: r for r in dir_list if r.get("symbol")}

        # Merge mentions + direction
        normalized_tickers = []
        for sym, mention in seen.items():
            dr = direction_records.get(sym, {})
            direction = dr.get("direction", "neutral")
            context = dr.get("context", mention.get("source_snippet", ""))
            direction = _apply_negation(direction, context)
            normalized_tickers.append({
                "symbol": sym,
                "direction": direction,
                "conviction": dr.get("conviction", "medium"),
                "mention_count": mention.get("mention_count", 1),
                "context": context,
                "source_snippet": dr.get("source_snippet") or mention.get("source_snippet", ""),
                "chunk_id": mention.get("chunk_id", 0),
            })

        # ── Stage 2b: macro (1 call) ─────────────────────────────────────────
        macro_data = {"direction": "neutral", "themes": [], "timeframe": "short", "summary": ""}
        if budget_used < _MAX_LLM_CALLS:
            macro_data = await _extract_macro_pass_budgeted(transcript_text, _call_with_budget)
        else:
            status = "partial"

        # ── Stage 2c: options (1 call, only if keywords found) ───────────────
        options_out: list[VideoOptionIdea] = []
        if option_keywords_found and budget_used < _MAX_LLM_CALLS:
            option_snippets = _find_option_snippets(transcript_text)
            if option_snippets:
                options_out = await _extract_options_pass_budgeted(option_snippets, unique_symbols, _call_with_budget)

        # ── Stage 2d: setups (1 call, only if price spans exist) ────────────
        setups_out: list[VideoTradeSetup] = []
        if all_price_spans and budget_used < _MAX_LLM_CALLS:
            setups_out = await _extract_setups_pass_budgeted(all_price_spans, _call_with_budget)

        if budget_used >= _MAX_LLM_CALLS and status != "partial":
            status = "partial"

    except Exception as e:
        log.warning("video_parser: pipeline error for %s: %s", video_id, e)
        normalized_tickers = []
        macro_data = {"direction": "neutral", "themes": [], "timeframe": "short", "summary": "parse error"}
        options_out = []
        setups_out = []
        status = "failed"

    await db.update_analysis_run(run_id, status=status, call_budget_used=budget_used)

    # Build PriceLevel objects from raw price spans (legacy-compatible)
    price_levels = [
        PriceLevel(
            ticker=ps.get("ticker", ""),
            level_type="support",
            price=ps.get("price", 0.0),
            condition=ps.get("source_snippet", ""),
            consequence="",
            confidence=0.7,
        )
        for ps in all_price_spans if ps.get("price", 0) > 0
    ]

    _raw_macro_dir = macro_data.get("direction", "neutral")
    _norm_macro_dir = _MACRO_NORM.get(_raw_macro_dir, _raw_macro_dir)  # already-normalized values pass through
    macro_thesis = MacroThesis(
        direction=Direction(_norm_macro_dir),
        themes=macro_data.get("themes", []),
        timeframe=macro_data.get("timeframe", "short"),
        summary=macro_data.get("summary", ""),
    )

    # Derive overall conviction from highest in tickers
    conv_order = {"high": 3, "medium": 2, "low": 1}
    top_conv = max((conv_order.get(t.get("conviction", "low"), 1) for t in normalized_tickers), default=2)
    overall_conviction = {3: Conviction.HIGH, 2: Conviction.MEDIUM, 1: Conviction.LOW}.get(top_conv, Conviction.MEDIUM)

    # Write signal_events for telemetry (unchanged from v1)
    _conviction_quality = {"high": 0.9, "medium": 0.6, "low": 0.3}
    parse_latency = 0.0
    for t in normalized_tickers:
        if not t.get("symbol"):
            continue
        q = _conviction_quality.get(t.get("conviction", "medium"), 0.6)
        q = min(q * (1.0 + 0.05 * (t.get("mention_count", 1) - 1)), 1.0)
        try:
            await db.record_signal_event(
                source_type="youtube", source_detail=video_id,
                ticker=t["symbol"], direction=t.get("direction", "neutral"),
                quality_score=round(q, 4), latency_sec=round(parse_latency, 3),
                provenance=f"youtube://{channel_name}/{video_id}",
                model_version=f"video_parser_{PARSER_VERSION}",
            )
        except Exception as exc:
            log.debug("video_parser: signal_event insert failed for %s/%s: %s", video_id, t["symbol"], exc)

    return ParsedVideo(
        video_id=video_id,
        channel_name=channel_name,
        raw_transcript=transcript_text,
        tickers=normalized_tickers,
        price_levels=price_levels,
        macro_thesis=macro_thesis,
        overall_conviction=overall_conviction,
        parsed_at=time.time(),
        run_id=run_id,
        options=options_out,
        setups=setups_out,
        parser_version="v2-transcript",
    )
