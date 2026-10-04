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
    ParsedTweet, TickerPostView, OptionsDetail, TweetType, Direction, Conviction,
    locate_unique_source_span,
)
from consensus_engine.utils.tickers import extract_tickers
from models.router import process_tweet as process_multimodal_tweet
from .analyst_evidence import (
    comparison_direction, direction_context, direction_is_supported, safe_image_evidence, shared_ticker_subject, ticker_text_context, unsided_option,
)

log = logging.getLogger("consensus_engine.analysis.tweet_parser")

ANALYST_VIEW_PARSER_VERSION = "analyst-view-v2"
_UNSAFE_VIEW_CODES = {
    "generic_activity", "neutral", "unsided_option", "multi_ticker_ambiguous",
    "missing", "invalid_span",
}
_SAFE_VIEW_CODES = {"explicit_clause", "reason_only", "direction_only"}
_SOURCE_TICKER_RE = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,10})(?![A-Za-z0-9])")


def _unclear_view(ticker: str, decision_code: str = "missing") -> TickerPostView:
    return TickerPostView(
        ticker=ticker.upper(),
        direction="unclear",
        reason_kind="none",
        decision_code=decision_code if decision_code in _UNSAFE_VIEW_CODES else "invalid_span",
        parser_version=ANALYST_VIEW_PARSER_VERSION,
    )


def _ticker_in_span(ticker: str, span: str) -> bool:
    symbol = re.escape(ticker.lstrip("$"))
    return bool(re.search(rf"(?<![A-Za-z0-9])\$?{symbol}(?![A-Za-z0-9])", span, re.IGNORECASE))


def _validate_ticker_view(
    item: object,
    ticker: str,
    all_tickers: list[str],
    original_text: str,
) -> TickerPostView:
    if not isinstance(item, dict):
        return _unclear_view(ticker)

    decision_code = str(item.get("decision_code", "missing")).lower()
    if decision_code not in _SAFE_VIEW_CODES:
        return _unclear_view(ticker, decision_code)
    direction = str(item.get("direction", "unclear")).lower()
    reason_kind = str(item.get("reason_kind", "none")).lower()
    reason_text = item.get("reason_text")
    reason_requested = decision_code in {"explicit_clause", "reason_only"}
    direction_requested = decision_code in {"explicit_clause", "direction_only"}

    span = locate_unique_source_span(original_text, reason_text) if reason_requested else None
    if reason_requested and (
        span is None or reason_kind not in {"position", "setup", "event_claim"}
    ):
        return _unclear_view(ticker, "invalid_span")

    if span is not None:
        if shared_ticker_subject(original_text, span, ticker):
            return _unclear_view(ticker, "multi_ticker_ambiguous")
        start, end = span
        reason_text = original_text[start:end]
        if len(all_tickers) > 1 and not _ticker_in_span(ticker, reason_text):
            boundaries = list(re.finditer(r"[\n;!?]|\.(?!\d)", original_text[:start]))
            clause_start = boundaries[-1].end() if boundaries else 0
            # Check the original subject before context trims prior tickers.
            # A shared '$A and $B' subject cannot become B-only evidence.
            prefix = original_text[clause_start:end]
            if any(_ticker_in_span(other, prefix) for other in all_tickers if other != ticker):
                return _unclear_view(ticker, "multi_ticker_ambiguous")
            context = direction_context(original_text, span, ticker).strip()
            context = re.sub(r"\s+(?:and|while|but)$", "", context, flags=re.I)
            expanded_span = locate_unique_source_span(original_text, context)
            if (expanded_span is None or not _ticker_in_span(ticker, context)
                    or any(_ticker_in_span(other, context) for other in all_tickers if other != ticker)):
                return _unclear_view(ticker, "multi_ticker_ambiguous")
            start, end = expanded_span
            span, reason_text = expanded_span, original_text[start:end]
        for other in all_tickers:
            if other != ticker and _ticker_in_span(other, reason_text):
                return _unclear_view(ticker, "multi_ticker_ambiguous")
        if unsided_option(reason_text):
            return _unclear_view(ticker, "unsided_option")
    else:
        start = end = None
        reason_text = None
        reason_kind = "none"

    direction_is_safe = False
    if direction_requested and direction in {"long", "short"}:
        evidence_text = direction_context(original_text, span, ticker) if span else (
            original_text if len(all_tickers) == 1 else "")
        direction_is_safe = direction_is_supported(direction, evidence_text)
        if unsided_option(evidence_text):
            return _unclear_view(ticker, "unsided_option")
    elif span is not None and decision_code == "reason_only":
        evidence_text = direction_context(original_text, span, ticker)
        comparison = comparison_direction(evidence_text)
        if comparison and not unsided_option(evidence_text):
            direction, direction_is_safe = comparison, True

    # A genuine stock setup is independent of an option-performance recap. A
    # neutral event plus unsided contracts still cannot establish direction.
    if unsided_option(original_text) and not direction_is_safe:
        return _unclear_view(ticker, "unsided_option")

    reason_is_safe = span is not None
    if direction_is_safe and reason_is_safe:
        final_code = "explicit_clause"
    elif reason_is_safe:
        direction = "unclear"
        final_code = "reason_only"
    elif direction_is_safe:
        reason_kind = "none"
        final_code = "direction_only"
    else:
        return _unclear_view(ticker, "generic_activity")

    return TickerPostView(
        ticker=ticker,
        direction=direction,
        reason_text=reason_text,
        reason_start=start,
        reason_end=end,
        reason_kind=reason_kind,
        decision_code=final_code,
        parser_version=ANALYST_VIEW_PARSER_VERSION,
    )


def _parse_ticker_views(payload: dict, tickers: list[str], original_text: str) -> list[TickerPostView]:
    raw_views = payload.get("ticker_views", [])
    raw_views = raw_views if isinstance(raw_views, list) else []
    normalized_tickers = list(dict.fromkeys(ticker.upper() for ticker in tickers))
    source_tickers = list(dict.fromkeys([
        *normalized_tickers,
        *(match.upper() for match in _SOURCE_TICKER_RE.findall(original_text)),
    ]))
    views = []
    for ticker in normalized_tickers:
        candidates = [
            item for item in raw_views
            if isinstance(item, dict) and str(item.get("ticker", "")).upper() == ticker
        ]
        if len(candidates) != 1:
            code = "multi_ticker_ambiguous" if len(candidates) > 1 else "missing"
            views.append(_unclear_view(ticker, code))
        else:
            item = candidates[0]
            if item.get("decision_code") == "image_evidence":
                outputs = payload.get("vision_outputs", [])
                index = item.get("vision_index")
                evidence = None
                if isinstance(outputs, list) and type(index) is int and 0 <= index < len(outputs):
                    evidence = safe_image_evidence(outputs[index], ticker, item.get("direction"))
                    opposite = "short" if item.get("direction") == "long" else "long"
                    # Prompt instructions are not a conflict gate. Reject opposing
                    # reliable charts and opposing text for this same ticker.
                    chart_conflict = any(safe_image_evidence(output, ticker, opposite) for output in outputs)
                    text_conflict = direction_is_supported(opposite, ticker_text_context(original_text, ticker))
                    if chart_conflict or text_conflict:
                        evidence = None
                views.append(TickerPostView(
                    ticker=ticker, direction=item["direction"], reason_kind="image",
                    decision_code="image_evidence", parser_version=ANALYST_VIEW_PARSER_VERSION,
                    image_evidence=evidence,
                ) if evidence else _unclear_view(ticker))
            else:
                view = _validate_ticker_view(item, ticker, source_tickers, original_text)
                opposite = "short" if view.direction == "long" else "long"
                outputs = payload.get("vision_outputs", [])
                if view.direction in {"long", "short"} and isinstance(outputs, list) and any(
                    safe_image_evidence(output, ticker, opposite) for output in outputs
                ):
                    view = _unclear_view(ticker, "neutral")
                if view.direction == "unclear" and (
                    view.decision_code in {"neutral", "generic_activity"} and len(source_tickers) == 1
                    or view.decision_code == "multi_ticker_ambiguous" and (
                        item.get("decision_code") == "multi_ticker_ambiguous"
                        or isinstance(item.get("reason_text"), str) and _ticker_in_span(ticker, item["reason_text"])
                    )
                ):
                    # An ETF appended to a chart caption or a separate forecast
                    # must not erase a clear, uniquely quoted ticker clause.
                    repaired_views = []
                    for anchor in re.finditer(rf"(?<![A-Za-z0-9])\$?{re.escape(ticker)}(?![A-Za-z0-9])", original_text, re.I):
                        start = anchor.start()
                        boundary = re.search(r"[;!?]|\.(?!\d)|\$[A-Za-z]{1,10}\b", original_text[anchor.end():])
                        end = anchor.end() + boundary.start() if boundary else len(original_text)
                        quote = original_text[start:end].rstrip()
                        quote = re.sub(r"\s+(?:and|while|but)$", "", quote, flags=re.I)
                        inferred = comparison_direction(quote, numeric_only=view.decision_code != "multi_ticker_ambiguous")
                        if view.decision_code != "multi_ticker_ambiguous":
                            scope = original_text if len(source_tickers) == 1 else ticker_text_context(original_text, ticker)
                            if comparison_direction(scope, numeric_only=True) != inferred:
                                inferred = None
                        if inferred:
                            repaired = _validate_ticker_view(
                                {"decision_code": "explicit_clause", "direction": inferred,
                                 "reason_kind": "setup", "reason_text": quote},
                                ticker, source_tickers, original_text,
                            )
                            if repaired.direction in {"long", "short"}:
                                repaired_views.append(repaired)
                    if len({candidate.direction for candidate in repaired_views}) == 1:
                        recovered = repaired_views[0]
                        opposite = "short" if recovered.direction == "long" else "long"
                        if not direction_is_supported(opposite, ticker_text_context(original_text, ticker)):
                            view = recovered
                if view.direction == "unclear" and isinstance(outputs, list):
                    supported_images = [
                        (side, evidence) for side in ("long", "short") for output in outputs
                        if (evidence := safe_image_evidence(output, ticker, side)) is not None
                    ]
                    sides = {side for side, _ in supported_images}
                    if len(sides) == 1:
                        side, evidence = supported_images[0]
                        opposite = "short" if side == "long" else "long"
                        if not direction_is_supported(opposite, ticker_text_context(original_text, ticker)):
                            view = TickerPostView(
                                ticker=ticker, direction=side, reason_kind="image", decision_code="image_evidence",
                                parser_version=ANALYST_VIEW_PARSER_VERSION, image_evidence=evidence,
                            )
                # Recovered text is subject to the same chart conflict check.
                if view.direction in {"long", "short"} and isinstance(outputs, list) and any(
                    safe_image_evidence(output, ticker, "short" if view.direction == "long" else "long")
                    for output in outputs
                ):
                    view = _unclear_view(ticker, "neutral")
                views.append(view)
    return views


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
            action=options_data.get("action"),
            strategy=options_data.get("strategy"),
            leg_count=_to_int(options_data.get("leg_count")),
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
        ticker_views=_parse_ticker_views(payload, tickers, original_text),
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
_STOP_LOSS_PATTERN = re.compile(r"\b(sl|stop|stop loss|stop-loss)\b", re.IGNORECASE)
_TARGET_PATTERN = re.compile(r"(\btarget\b|🎯|\btp\b)", re.IGNORECASE)
_ENTRY_PATTERN = re.compile(r"\b(at|@)\s*\$?\d", re.IGNORECASE)


def _infer_conviction(text: str, options: Optional[OptionsDetail]) -> Conviction:
    """Deterministic conviction tier from tweet text and options shape.

    Returns HIGH only when the setup structure (or an explicit conviction
    statement) is decisive; MEDIUM otherwise. The heuristic never returns LOW:
    ~98% of the tracked analysts' REAL calls use a tentative register
    ("watching... might add if it reclaims 250") — that wording is their
    normal voice, not noise, so register words must not floor the score
    (user 2026-06-09; TODO #32). LOW is the LLM's call only, based on whether
    the tweet has any actionable content.
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

    parsed = ParsedTweet(
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
    parsed.ticker_views = [_unclear_view(ticker) for ticker in tickers]
    return parsed


def _to_float(val) -> Optional[float]:
    """Safely convert a value to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _to_int(val) -> Optional[int]:
    """Safely convert a whole-number value to int."""
    if val is None:
        return None
    try:
        number = float(val)
    except (ValueError, TypeError):
        return None
    return int(number) if number.is_integer() else None


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
