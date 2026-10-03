"""Caption-text → EvidenceBundle extractor.

Used by F1 (auto-captions). YouTube auto-captions are plain prose
("look at apple, tesla, micron") with no `$XXX` ticker markup and no
reliable casing, so a regex-based ticker extractor catches almost
nothing. Instead, send the caption text to a fast LLM with a structured
JSON prompt that maps company names → tickers.

Same output shape as `gemini_video_parser.extract_evidence_with_gemini`
so downstream consumers (`classify_evidence`, allowlist, persistence)
need no changes.

Default model chain (configured under `youtube.captions.llm`):
  google/gemini-2.5-flash  (primary — paid but cheap & reliable)
  → openai/gpt-oss-120b   (paid; the :free tier 429s on transcript-sized payloads)
  → z-ai/glm-4.5-air:free
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from consensus_engine import config as cfg
from consensus_engine.llm_client import call_with_fallback
from consensus_engine.models import EvidenceBundle, EvidenceSpan, RunTelemetry

log = logging.getLogger("consensus_engine.analysis.captions_llm_parser")

# Bound each call, rather than dropping the end of a long video.
_MAX_CAPTION_CHARS = 15000

_TA_ABBREVIATIONS = {
    "RSI", "EMA", "MACD", "VWAP", "SMA", "ATR", "MA", "BB", "ADX",
    "OBV", "CCI", "DMI", "ROC", "PSAR", "STOCH", "MFI",
}

_SYSTEM_PROMPT = (
    "You extract stock tickers from finance video transcripts. "
    "Return ONLY raw JSON — no markdown fences, no ```json, no commentary, no explanation. "
    "The first character of your response must be '{' and the last must be '}'."
)

_USER_PROMPT_TEMPLATE = """Extract every stock ticker mentioned in this transcript — by company name OR by symbol.

Return ONLY valid JSON. Do NOT wrap it in ```json fences. Do NOT add any text before or after. Start your response with {{ and end with }}:

{{
  "spans": [
    {{"quote": "verbatim quote from the transcript that mentions a ticker", "tickers": ["AAPL", "NVDA"]}}
  ]
}}

Rules:
- "Apple" → AAPL, "Tesla" → TSLA, "Micron" → MU, "Nvidia" → NVDA, "the Q's" → QQQ, etc. Map company name to its primary US-listed ticker.
- Indices: "S&P 500" → SPY, "Dow" → DIA, "Nasdaq" → QQQ, "Russell 2000" → IWM. "10-year yield" → no ticker.
- Exclude technical-analysis abbreviations: {ta_abbrevs}. These are indicators, not stocks.
- One span per quote. Include a quote ONLY if it has at least one resolved ticker.
- `quote` = a meaningful sentence (10-300 chars) drawn from the transcript text. Verbatim or close.
- `tickers` = uppercase US-listed symbols. Empty array means drop the span entirely (do not include it).
- Aim for 5-40 spans total for a 10-40 minute video. Empty `spans` array if no tickers found.

Transcript:
{transcript}"""


def _build_chain() -> list[str]:
    primary = cfg.get("youtube.captions.llm.model", "google/gemini-2.5-flash")
    fallbacks = cfg.get("youtube.captions.llm.fallback_models", []) or []
    seen: set[str] = set()
    chain: list[str] = []
    for m in [primary, *fallbacks]:
        if m and m not in seen:
            chain.append(m)
            seen.add(m)
    return chain


def _strip_json_fence(text: str) -> str:
    """Some models wrap JSON in ```json ... ``` fences despite instructions."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def _parse_json_safely(raw: str) -> tuple[dict[str, Any] | None, bool]:
    """Parse JSON from LLM response.

    Returns ``(data, clean)`` where ``clean=True`` means the response parsed
    without needing fallback recovery (no markdown fences, no regex extraction).
    ``clean=False`` means either parse failed outright (data is None) or the
    response needed fence-stripping / regex recovery to extract valid JSON.
    """
    if not raw:
        return None, False
    stripped = _strip_json_fence(raw)
    # Clean parse: fence-stripping was a no-op (or fences were all it needed)
    # We consider it clean only when the stripped form equals the trimmed raw
    # (i.e. the model returned bare JSON without fences).
    is_clean = stripped == raw.strip()
    try:
        return json.loads(stripped), is_clean
    except json.JSONDecodeError:
        # Fallback: try to extract the first {...} block from the raw response.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0)), False
            except json.JSONDecodeError:
                return None, False
        return None, False


def _normalize_spans(raw_spans: list[Any]) -> list[EvidenceSpan]:
    out: list[EvidenceSpan] = []
    ts_sec = 0
    for entry in raw_spans:
        if not isinstance(entry, dict):
            continue
        quote = (entry.get("quote") or "").strip()
        if not quote:
            continue
        tickers_raw = entry.get("tickers") or []
        if not isinstance(tickers_raw, list):
            continue
        tickers: list[str] = []
        for t in tickers_raw:
            if not isinstance(t, str):
                continue
            tu = t.strip().upper().lstrip("$")
            if not tu or not re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", tu):
                continue
            if tu in _TA_ABBREVIATIONS:
                continue
            if tu not in tickers:
                tickers.append(tu)
        if not tickers:
            continue
        out.append(EvidenceSpan(
            ts_sec=ts_sec,
            quote=quote[:500],
            tickers=tickers,
        ))
        ts_sec += 30
    return out


async def extract_evidence_from_captions(
    video_id: str,
    transcript: str,
    published_at: str,
    telemetry: RunTelemetry,
    *,
    source_segments: list[dict] | None = None,
) -> EvidenceBundle | None:
    """Read every chunk; source timestamps and quotes are verified locally."""
    if not transcript or not transcript.strip():
        return None
    chunks = []
    if source_segments:
        current, ids, size = [], {}, 0
        for index, segment in enumerate(source_segments):
            text = segment["text"].strip()
            # A pathological long segment is still read in bounded pieces.
            for offset in range(0, len(text), _MAX_CAPTION_CHARS - 100):
                line = f'[{index}] {text[offset:offset + _MAX_CAPTION_CHARS - 100]}'
                if current and size + len(line) > _MAX_CAPTION_CHARS:
                    chunks.append(("\n".join(current), ids))
                    overlap = []
                    for previous in reversed(current[-4:]):
                        if sum(len(v) + 1 for v in overlap) + len(previous) + 1 > 2000:
                            break
                        overlap.insert(0, previous)
                    while overlap and sum(len(v) + 1 for v in overlap) + len(line) + 1 > _MAX_CAPTION_CHARS:
                        overlap.pop(0)
                    keep = {int(v.split("]", 1)[0][1:]) for v in overlap}
                    current, ids = overlap, {i: s for i, s in ids.items() if i in keep}
                    size = sum(len(v) + 1 for v in current)
                current.append(line)
                ids[index] = segment
                size += len(line) + 1
        if current:
            chunks.append(("\n".join(current), ids))
    else:
        # Word boundary splits preserve text even without provider timestamps.
        remainder = transcript
        while remainder:
            cut = min(len(remainder), _MAX_CAPTION_CHARS)
            if cut < len(remainder):
                space = remainder.rfind(" ", 0, cut)
                if space > 0:
                    cut = space + 1
            chunks.append((remainder[:cut], None))
            remainder = remainder[cut:]
    all_spans, seen, clean = [], set(), True
    for text, source in chunks:
        chunk = await _extract_chunk(video_id, text, published_at, telemetry, source)
        if chunk is None:
            return None  # never mark a partially read transcript complete
        clean = clean and telemetry.json_parse_ok
        for span in chunk.spans:
            key = (span.ts_sec if source else None, span.quote.casefold(), tuple(span.tickers))
            if key not in seen:
                seen.add(key)
                if not source:
                    span.ts_sec = len(all_spans) * 30  # legacy untimed fallback
                all_spans.append(span)
    if not all_spans and not source_segments:
        return None
    telemetry.span_count = len(all_spans)
    telemetry.json_parse_ok = clean
    duration = int(max(s["end"] for s in source_segments)) if source_segments else None
    return EvidenceBundle(video_id, duration, published_at,
                          segments=source_segments or [{"text": transcript}], spans=all_spans)


async def _extract_chunk(video_id, transcript, published_at, telemetry, source=None):
    """Send caption text to the LLM chain and convert the JSON response into
    an EvidenceBundle. Returns None when the chain fails or yields no spans."""
    if not transcript or not transcript.strip():
        return None

    truncated = transcript  # the chunk builder already bounds calls without dropping words

    chain = _build_chain()
    if not chain:
        log.error("captions_llm: model chain empty for %s — config missing?", video_id)
        return None

    max_tokens = int(cfg.get("youtube.captions.llm.max_tokens", 4096))
    temperature = float(cfg.get("youtube.captions.llm.temperature", 0.2))
    timeout = int(cfg.get("youtube.captions.llm.timeout", 45))

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        ta_abbrevs=", ".join(sorted(_TA_ABBREVIATIONS)),
        transcript=truncated,
    )
    if source:
        user_prompt += (
            '\nEach source line starts with its integer segment ID in brackets. '
            'For each span also return "start_segment" and "end_segment" IDs. '
            'Quotes MUST be copied exactly from contiguous source text, joining adjacent lines if needed. '
            'Do not rewrite grammar, add words, or replace company names with symbols in quotes. '
            'Each quote must be at most 500 characters. Include numerical values and '
            'dates_mentioned only when literally in that quote. Do not invent timestamps.'
        )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    t0 = time.monotonic()
    content = await call_with_fallback(
        role=None,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        chain=chain,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if not content:
        log.warning("captions_llm: chain exhausted for %s (%dms)", video_id, elapsed_ms)
        return None

    parsed, json_clean = _parse_json_safely(content)
    if not parsed or not isinstance(parsed, dict):
        log.warning(
            "captions_llm: invalid JSON for %s (%dms): %.200s",
            video_id, elapsed_ms, content,
        )
        return None

    if not json_clean:
        log.debug(
            "captions_llm: LLM returned non-bare JSON (fence/recovery) for %s — parse succeeded but json_parse_ok=False",
            video_id,
        )

    raw_spans = parsed.get("spans") or []
    if not isinstance(raw_spans, list):
        log.warning("captions_llm: 'spans' not a list for %s — got %s", video_id, type(raw_spans).__name__)
        return None

    spans = _normalize_spans(raw_spans)
    if source:
        spans = []
        from consensus_engine.analysis.ticker_grounding import filter_tickers_by_grounding
        def normalized(value):
            return " ".join(value.casefold().split())
        # Derive timestamps from source text locally. A model's segment IDs
        # are hints only; incorrect IDs must not move a real quote in time.
        joined, positions = "", []
        for index, segment in sorted(source.items()):
            text = normalized(segment["text"])
            start = len(joined)
            joined += text + " "
            positions.append((start, len(joined), segment))
        for entry in raw_spans:
            if not isinstance(entry, dict):
                continue
            quote = entry.get("quote")
            if not isinstance(quote, str) or not normalized(quote) or len(quote) > 500:
                continue
            offset = joined.find(normalized(quote))
            if offset < 0:
                continue
            end = offset + len(normalized(quote))
            if (offset and joined[offset - 1].isalnum() and quote[0].isalnum()) or (
                end < len(joined) and quote[-1].isalnum() and (
                    joined[end].isalnum() or re.match(r"[.,]\d", joined[end:]))
            ):
                continue
            segment = next(s for start, end, s in positions if start <= offset < end)
            cleaned = _normalize_spans([entry])
            if not cleaned:
                continue
            span = cleaned[0]
            span.ts_sec = int(segment["start"])
            span.tickers, _ = filter_tickers_by_grounding(span.tickers, quote)
            if not span.tickers:
                continue
            span.numbers = [float(n.replace(",", "")) for n in re.findall(r"(?<!\w)\d[\d,]*(?:\.\d+)?", quote)]
            dates = entry.get("dates_mentioned", [])
            span.dates_mentioned = [d for d in dates if isinstance(d, str) and d.casefold() in quote.casefold()] if isinstance(dates, list) else []
            spans.append(span)

    duration_sec = (len(spans) - 1) * 30 + 30
    bundle = EvidenceBundle(
        video_id=video_id,
        duration_sec=duration_sec,
        publish_ts=published_at,
        segments=[{"text": transcript[:5000]}],
        spans=spans,
    )

    telemetry.span_count = len(spans)
    telemetry.json_parse_ok = json_clean
    unique_tickers = {t for sp in spans for t in sp.tickers}
    log.info(
        "captions_llm: %s → %d spans, %d unique tickers, %dms, json_clean=%s",
        video_id, len(spans), len(unique_tickers), elapsed_ms, json_clean,
    )
    return bundle
