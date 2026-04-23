"""Gemini fast-path for YouTube video analysis.

Passes a YouTube URL directly to Gemini. The legacy ``parse_video_with_gemini``
function asks the model to classify in a single JSON call. The new v2 path
``extract_evidence_with_gemini`` asks only for literal, timestamped evidence
spans — classification is done downstream by the deterministic Python
classifier (Stage B).
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
    EvidenceBundle, EvidenceSpan, RunTelemetry,
)

log = logging.getLogger("consensus_engine.analysis.gemini_video_parser")

_MACRO_NORM = {"bullish": "long", "bearish": "short", "neutral": "neutral"}

# Technical-analysis abbreviations that look like tickers but aren't.
_TA_ABBREVIATIONS = {
    "RSI", "EMA", "MACD", "VWAP", "SMA", "ATR", "MA", "BB", "ADX",
    "OBV", "CCI", "DMI", "ROC", "PSAR", "STOCH", "MFI",
}

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


_EVIDENCE_PROMPT = """You are a transcription assistant for a financial YouTube video. You do NOT classify. You do NOT label support/resistance. You do NOT give direction or conviction. Your job is only to extract verbatim timestamped evidence.

Watch the full video and respond ONLY with this exact JSON (no markdown fences, no commentary):
{
  "duration_sec": 2340,
  "segments": [
    {"ts_start_sec": 2022, "title": "Number One Draft Pick: MSFT"}
  ],
  "spans": [
    {"ts_sec": 2024, "quote": "exact verbatim sentence as spoken", "tickers": ["MSFT"], "numbers": [], "dates_mentioned": []},
    {"ts_sec": 2172, "quote": "Bullish bias into April 29th earnings with an entry target at 400.15", "tickers": ["MSFT"], "numbers": [400.15], "dates_mentioned": ["April 29"]}
  ]
}

Extraction rules:
- Include EVERY span mentioning a ticker, a price, or a date. Skip pure chit-chat and off-topic banter.
- `ts_sec` is an integer second offset from the video start. Use the speaker's actual time, not the segment's.
- `quote` must be verbatim or near-verbatim auto-caption text — NO paraphrase, NO summarization.
- `tickers` = UPPERCASE real stock/ETF symbols only (e.g., NVDA, SPY, MSFT). Reject technical-analysis abbreviations (RSI, EMA, MACD, VWAP, SMA, ATR, MA). Empty array if none.
- `numbers` = raw numeric values that appear in the quote (e.g., 400.15, 18). Empty array if none.
- `dates_mentioned` = raw date strings exactly as spoken ("April 29", "next Wednesday", "Friday"). Do NOT resolve to ISO dates.
- Do NOT emit direction, conviction, support/resistance labels, setup_type, or any macro summary. Those come from post-processing.
- Target 30–80 spans for a 40-minute video. If no qualifying spans, return an empty `spans` array."""


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


def _parse_ts_str(ts) -> int:
    """Convert a timestamp to integer seconds.

    Accepts int/float seconds, or strings in ``"ss"``, ``"mm:ss"``, or
    ``"hh:mm:ss"`` form. Returns 0 on any parse failure.
    """
    if isinstance(ts, bool):
        return 0
    if isinstance(ts, (int, float)):
        try:
            return max(0, int(ts))
        except (ValueError, OverflowError):
            return 0
    if not isinstance(ts, str):
        return 0
    s = ts.strip()
    if not s:
        return 0
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return max(0, int(float(parts[0])))
        if len(parts) == 2:
            m, sec = parts
            return max(0, int(m) * 60 + int(float(sec)))
        if len(parts) == 3:
            h, m, sec = parts
            return max(0, int(h) * 3600 + int(m) * 60 + int(float(sec)))
    except (ValueError, TypeError):
        return 0
    return 0


def _clean_tickers(raw: list) -> list[str]:
    """Filter tickers to uppercase real symbols, drop TA abbreviations."""
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for t in raw:
        if not isinstance(t, str):
            continue
        sym = t.strip().upper()
        if not sym or not sym.isalpha() or len(sym) > 6:
            continue
        if sym in _TA_ABBREVIATIONS:
            continue
        out.append(sym)
    return out


def _clean_numbers(raw: list) -> list[float]:
    out: list[float] = []
    if not isinstance(raw, list):
        return out
    for n in raw:
        try:
            out.append(float(n))
        except (TypeError, ValueError):
            continue
    return out


def _clean_dates(raw: list) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for d in raw:
        if isinstance(d, str) and d.strip():
            out.append(d.strip())
    return out


def _build_evidence_bundle(data: dict, video_id: str, published_at: str) -> EvidenceBundle:
    """Convert evidence-only JSON into an EvidenceBundle. Filters TA abbreviations."""
    duration = data.get("duration_sec")
    try:
        duration_sec = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_sec = None

    segments: list[dict] = []
    for seg in data.get("segments", []) or []:
        if not isinstance(seg, dict):
            continue
        segments.append({
            "ts_start_sec": _parse_ts_str(seg.get("ts_start_sec", 0)),
            "title": str(seg.get("title", "")),
        })

    spans: list[EvidenceSpan] = []
    for sp in data.get("spans", []) or []:
        if not isinstance(sp, dict):
            continue
        quote = str(sp.get("quote", "")).strip()
        if not quote:
            continue
        spans.append(EvidenceSpan(
            ts_sec=_parse_ts_str(sp.get("ts_sec", 0)),
            quote=quote,
            tickers=_clean_tickers(sp.get("tickers", [])),
            numbers=_clean_numbers(sp.get("numbers", [])),
            dates_mentioned=_clean_dates(sp.get("dates_mentioned", [])),
        ))

    return EvidenceBundle(
        video_id=video_id,
        duration_sec=duration_sec,
        publish_ts=published_at,
        segments=segments,
        spans=spans,
    )


def _extract_token_counts(response) -> tuple[int | None, int | None]:
    """Pull (input_tokens, output_tokens) from a Gemini response if available."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return (None, None)
    input_tokens = getattr(meta, "prompt_token_count", None)
    output_tokens = (
        getattr(meta, "candidates_token_count", None)
        or getattr(meta, "response_token_count", None)
    )
    try:
        input_tokens = int(input_tokens) if input_tokens is not None else None
    except (TypeError, ValueError):
        input_tokens = None
    try:
        output_tokens = int(output_tokens) if output_tokens is not None else None
    except (TypeError, ValueError):
        output_tokens = None
    return (input_tokens, output_tokens)


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

    This is the legacy single-call path. Phase P6 gates this behind
    ``youtube.use_two_stage`` / ``youtube.legacy_fallback`` flags.
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


async def extract_evidence_with_gemini(
    video_id: str,
    channel_name: str,
    published_at: str,
) -> tuple[EvidenceBundle | None, RunTelemetry]:
    """Stage A: extract literal timestamped evidence spans via Gemini.

    Returns ``(EvidenceBundle, RunTelemetry)``. On timeout, API error, or
    unparseable JSON, returns ``(None, telemetry)`` with ``json_parse_ok=False``
    so the caller can log the failure without losing timing/token info.

    Evidence spans are persisted via ``db.insert_youtube_evidence_span`` so
    every downstream candidate can be traced back to the span(s) that justify
    it.
    """
    telemetry = RunTelemetry()
    start_ts = time.monotonic()

    client = _get_gemini_client()
    if client is None:
        telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
        return (None, telemetry)

    # Pre-call rate limiter + budget gate (fail-open: caller falls back on None).
    try:
        from consensus_engine.utils.rate_limiter import rate_limiter
        from consensus_engine.engine import BudgetManager
        await rate_limiter.acquire("gemini")
        budget = BudgetManager()
        if not await budget.can_consume_gemini():
            log.warning("extract_evidence_with_gemini: Gemini budget exhausted, skipping %s", video_id)
            telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
            telemetry.json_parse_ok = False
            return (None, telemetry)
    except Exception as e:
        log.debug("extract_evidence_with_gemini: budget/rate gate failed: %s", e)
        budget = None

    model = cfg.get("youtube.gemini.model", "gemini-2.5-flash")
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    timeout_sec = int(cfg.get("youtube.gemini.timeout_sec", 120))

    response = None
    try:
        from google.genai import types

        def _sync_call():
            return client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_text(text=_EVIDENCE_PROMPT),
                    types.Part.from_uri(
                        file_uri=youtube_url,
                        mime_type="video/*",
                    ),
                ],
            )

        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(None, _sync_call),
            timeout=timeout_sec,
        )
        raw = response.text
    except asyncio.TimeoutError:
        log.warning("extract_evidence_with_gemini: timeout for %s", video_id)
        telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
        telemetry.json_parse_ok = False
        return (None, telemetry)
    except Exception as e:
        log.warning("extract_evidence_with_gemini: API error for %s: %s", video_id, e)
        telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
        telemetry.json_parse_ok = False
        return (None, telemetry)

    telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
    in_tok, out_tok = _extract_token_counts(response)
    if in_tok is not None:
        telemetry.input_tokens = in_tok
    if out_tok is not None:
        telemetry.output_tokens = out_tok

    # Record actual usage against the daily budget (best-effort; ignore errors).
    if budget is not None:
        try:
            await budget.consume_gemini(
                telemetry.input_tokens or 0,
                telemetry.output_tokens or 0,
            )
        except Exception as e:
            log.debug("extract_evidence_with_gemini: consume_gemini failed: %s", e)

    data = _parse_gemini_response(raw)
    if data is None:
        log.warning("extract_evidence_with_gemini: unparseable response for %s", video_id)
        telemetry.json_parse_ok = False
        return (None, telemetry)

    telemetry.json_parse_ok = True
    bundle = _build_evidence_bundle(data, video_id, published_at)
    telemetry.span_count = len(bundle.spans)

    parser_version = f"gemini-evidence/{model}-v1"
    try:
        run_id = await db.create_analysis_run(video_id, parser_version)
    except Exception as e:
        log.warning("extract_evidence_with_gemini: could not create analysis run for %s: %s", video_id, e)
        return (bundle, telemetry)

    for span in bundle.spans:
        try:
            await db.insert_youtube_evidence_span(
                run_id=run_id,
                video_id=video_id,
                ts_sec=span.ts_sec,
                quote=span.quote,
                tickers=span.tickers,
                numbers=span.numbers,
                dates=span.dates_mentioned,
            )
        except Exception as e:
            log.debug("extract_evidence_with_gemini: span persist failed: %s", e)

    log.info(
        "extract_evidence_with_gemini: %s → %d spans, %d segments, %dms",
        video_id, len(bundle.spans), len(bundle.segments), telemetry.latency_ms,
    )
    return (bundle, telemetry)
