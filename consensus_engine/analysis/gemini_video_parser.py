"""Gemini fast-path for YouTube video analysis.

Passes a YouTube URL directly to Gemini. The ``extract_evidence_with_gemini``
path asks only for literal, timestamped evidence spans — classification is
done downstream by the deterministic Python classifier (Stage B).
"""

import asyncio
import json
import logging
import os
import re
import time

from consensus_engine import config as cfg, db
from consensus_engine.models import (
    EvidenceBundle, EvidenceSpan, RunTelemetry,
)

log = logging.getLogger("consensus_engine.analysis.gemini_video_parser")

# Technical-analysis abbreviations that look like tickers but aren't.
_TA_ABBREVIATIONS = {
    "RSI", "EMA", "MACD", "VWAP", "SMA", "ATR", "MA", "BB", "ADX",
    "OBV", "CCI", "DMI", "ROC", "PSAR", "STOCH", "MFI",
}

_EVIDENCE_PROMPT = """You are a transcription assistant for a financial YouTube video. You do NOT classify. You do NOT label support/resistance. You do NOT give direction or conviction. Your job is only to extract verbatim timestamped evidence.

Watch the full video and respond ONLY with this exact JSON shape (no markdown fences, no commentary). The angle-bracket tokens below are placeholders — replace them with values extracted from the actual video; never echo the placeholder text or any example value:
{
  "duration_sec": <integer total video duration in seconds>,
  "visual_evidence": [
    {"ts_sec": <integer second offset when this is visible on screen>, "value": "<the literal text, price, or ticker visible on the chart, overlay, or scanner UI>", "kind": "<price|ticker|label|date|other>", "where": "<short description of where on screen — e.g. 'chart axis label', 'flow tool row', 'overlaid annotation', 'video title card'>"}
  ],
  "segments": [
    {"ts_start_sec": <integer second offset where this segment begins>, "title": "<short title of this segment as spoken or shown on screen>"}
  ],
  "spans": [
    {"ts_sec": <integer second offset>, "quote": "<verbatim sentence as spoken in the audio>", "tickers": [<zero or more uppercase symbols actually mentioned>], "numbers": [<zero or more numeric values present in the quote>], "dates_mentioned": [<zero or more date strings exactly as spoken>]}
  ]
}

Extraction rules:
- Include EVERY span mentioning a ticker, a price, or a date. Skip pure chit-chat and off-topic banter.
- `ts_sec` is an integer second offset from the video start. Use the speaker's actual time, not the segment's.
- `quote` must be verbatim or near-verbatim auto-caption text — NO paraphrase, NO summarization.
- `tickers` = UPPERCASE real stock/ETF symbols only (e.g., NVDA, SPY, MSFT). Reject technical-analysis abbreviations (RSI, EMA, MACD, VWAP, SMA, ATR, MA). Empty array if none.
- CRITICAL — only include a ticker in `tickers` if EITHER the symbol is literally spoken in the quote (e.g., "NVDA", "Nvidia"), OR it is visibly displayed as a chart label / on-screen text within ±5 seconds of `ts_sec`. Do NOT infer tickers from sector context, related-stock chatter, or general topic. If the quote does not name a specific company, leave `tickers` empty.
- A span about "the chip sector" without a named company has `tickers: []`. A span about Burry buying AMC has `tickers: ["AMC"]` only — never add NVDA, GOOGL, or other "related" names.
- `numbers` = raw numeric values that appear in the quote (e.g., 400.15, 18). Empty array if none.
- `dates_mentioned` = raw date strings exactly as spoken ("April 29", "next Wednesday", "Friday"). Do NOT resolve to ISO dates.
- Do NOT emit direction, conviction, support/resistance labels, setup_type, or any macro summary. Those come from post-processing.
- Scale span count to the ACTUAL `duration_sec` you observed — roughly 1–2 spans per minute of real video. Never invent timestamps beyond `duration_sec`. If no qualifying spans, return an empty `spans` array.

VISUAL EVIDENCE — the whole reason this is a video task instead of a transcript task:
- `visual_evidence` is for things you can SEE on the chart, overlays, scanner UI, or on-screen text that are NOT spoken in the audio within ±10 seconds of `ts_sec`.
- Include: price levels marked on a chart but not said aloud (e.g. an axis tick at "$742.83" while the speaker only says "this level"); ticker symbols visible on a flow scanner table but not named in the audio; option strikes, expirations, premium amounts in screenshots; dates on a calendar; labels overlaid on the chart ("inverse H&S", "gamma wall").
- Exclude anything the speaker also says aloud at the same moment — that is already captured in `spans`.
- If you see a chart with prices labeled and the speaker only refers to "this level" or "here", that is the most valuable case to record.
- DEDUP: each distinct `value` MUST appear at most ONCE in the array. If the same label (e.g. "739.88") is visible on screen across many frames, emit a single entry with `ts_sec` set to the first moment it appears. Do NOT repeat the same value at different timestamps.
- CAP: return at most 50 entries total. Prioritise the most informative visual-only items (precise chart-axis numbers, scanner UI values, overlay labels) over generic UI text.
- Return an empty array only if the video shows no visible numbers, tickers, or labels that the audio doesn't also state."""


# B3 (#17, opt-in via youtube.visual.per_number_ticker_tagging, default OFF):
# ask Gemini to tag each visual number with the stock it belongs to so a
# multi-stock video stops dumping every number onto its top ticker. "null"
# is explicitly allowed so an ambiguous number is left unlabeled rather than
# hallucinated onto the wrong stock.
_B3_TICKER_ADDENDUM = """

PER-NUMBER TICKER TAGGING (additional requirement):
- For EACH `visual_evidence` entry, also include a `"ticker"` field naming the stock that the number/label belongs to — the symbol shown on the SAME chart or panel where the value appears.
- Use null whenever the owning stock is unclear, or the value is not stock-specific (a market-wide index level, a generic UI label, a calendar date). NEVER guess: an unlabeled number is far better than a wrong ticker.
- Example: a video showing an NVDA chart at 182.40 and later an AMD chart at 164.10 tags the first entry "ticker":"NVDA" and the second "ticker":"AMD"; a generic "VIX 14.2" overlay gets "ticker":null."""


def _evidence_prompt() -> str:
    """Evidence prompt, with the B3 per-number ticker addendum when enabled."""
    from consensus_engine import config as cfg
    if cfg.get("youtube.visual.per_number_ticker_tagging", False):
        return _EVIDENCE_PROMPT + _B3_TICKER_ADDENDUM
    return _EVIDENCE_PROMPT


# ─── Multi-key rotation (free-tier quota overflow) ─────────────────────────
#
# Supports multiple Gemini API keys via env vars GEMINI_API_KEY, GEMINI_API_KEY2,
# GEMINI_API_KEY3, ... When one hits a 429/RESOURCE_EXHAUSTED, the caller marks
# it exhausted until the next UTC midnight and rotates to the next available key.
# When all configured keys are exhausted, callers receive None and the scanner
# falls back to the legacy transcript pipeline.
_GEMINI_KEY_ENV_NAMES = ("GEMINI_API_KEY", "GEMINI_API_KEY2", "GEMINI_API_KEY3")
_key_exhausted_until: dict[str, float] = {}
_key_rotation_idx = 0


def _get_gemini_keys() -> list[tuple[str, str]]:
    """Return [(env_label, api_key)] for every configured non-empty Gemini key."""
    result: list[tuple[str, str]] = []
    for env_name in _GEMINI_KEY_ENV_NAMES:
        v = os.environ.get(env_name, "").strip()
        if v:
            result.append((env_name, v))
    return result


def _next_quota_reset_ts() -> float:
    """Epoch seconds at the next Gemini free-tier quota reset.

    Google resets daily (RPD) quotas at midnight Pacific Time, not UTC:
    https://ai.google.dev/gemini-api/docs/rate-limits#quotas-reset
    """
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        pt = ZoneInfo("America/Los_Angeles")
    except Exception:
        # Fallback on systems without tzdata: approximate with UTC-8 (no DST).
        pt = timezone(timedelta(hours=-8))
    now_pt = datetime.now(pt)
    tomorrow_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow_pt.timestamp()


# Backwards-compat alias for any test that referenced the old name.
_next_utc_midnight_ts = _next_quota_reset_ts


def _key_is_available(label: str) -> bool:
    return time.time() >= _key_exhausted_until.get(label, 0)


def _mark_key_exhausted(label: str, exc: Exception | None = None) -> None:
    """Bench a key after a 429. Distinguish per-MINUTE token 429s (short bench, key
    returns this minute) from genuine per-DAY caps (bench to Pacific midnight).

    Item G fix (deep-dive-2026-06-08): the old code benched to midnight on ANY quota
    error, so one transient per-minute 429 killed a key for the whole day and cascaded
    into the 42-alert burst. Now: bench only the parsed retry-after when a short
    retryDelay is present; bench to midnight only when the error names a per-day quota;
    otherwise a conservative 60s. Always misclassify toward the LONGER bench, never
    hammer a daily-dead key every 60s."""
    from consensus_engine.utils.burst_retry import parse_retry_after, is_per_day_quota
    body = str(exc) if exc is not None else ""
    retry_after = parse_retry_after(body)
    if is_per_day_quota(body):
        until = _next_quota_reset_ts()
        log.warning("gemini_video_parser: key %s per-DAY quota — benched until Pacific midnight", label)
    elif retry_after is not None and retry_after < 120:
        until = time.time() + retry_after + 2
        log.warning("gemini_video_parser: key %s per-minute 429 — benched %.0fs (retry-after)", label, retry_after)
    elif retry_after is not None:
        # a long retryDelay (>=120s) is effectively a daily/long bench
        until = time.time() + retry_after + 2
        log.warning("gemini_video_parser: key %s long 429 — benched %.0fs (retry-after)", label, retry_after)
    else:
        until = time.time() + 60
        log.warning("gemini_video_parser: key %s 429 w/o hint — conservative 60s bench", label)
    _key_exhausted_until[label] = until


def _reset_key_exhaustion() -> None:
    """Test helper — clear exhaustion state. Not called in production code."""
    _key_exhausted_until.clear()
    global _key_rotation_idx
    _key_rotation_idx = 0


def _get_available_gemini_client(skip: set[str] | None = None):
    """Return (client, label) for the next round-robin available key.

    ``skip`` is a set of labels to exclude (used during retry after 429). Returns
    (None, None) when no keys are configured or all are exhausted.
    """
    skip = skip or set()
    keys = _get_gemini_keys()
    if not keys:
        log.debug("gemini_video_parser: no Gemini API keys configured")
        return (None, None)
    available = [(l, k) for l, k in keys if _key_is_available(l) and l not in skip]
    if not available:
        return (None, None)
    global _key_rotation_idx
    label, key = available[_key_rotation_idx % len(available)]
    _key_rotation_idx += 1
    try:
        from google import genai
        return (genai.Client(api_key=key), label)
    except Exception as e:
        log.warning("gemini_video_parser: failed to init client for %s: %s", label, e)
        return (None, None)


def _is_quota_error(exc: Exception) -> bool:
    """Detect Gemini 429 / RESOURCE_EXHAUSTED / quota exceeded errors."""
    msg = str(exc).lower()
    return (
        "429" in msg
        or "resource_exhausted" in msg
        or "quota" in msg
        or "rate limit" in msg
    )


def _categorize_failure(exc: Exception | None) -> str:
    """Classify an F2 failure into one of: timeout, quota, unavailable,
    token_limit, unknown. Used to populate RunTelemetry.f2_failure_category
    so observability can spot patterns without inspecting raw exception text."""
    import asyncio as _asyncio
    if exc is None:
        return "unknown"
    if isinstance(exc, _asyncio.TimeoutError):
        return "timeout"
    if _is_quota_error(exc):
        return "quota"
    msg = (str(exc) + " " + repr(exc)).lower()
    if "503" in msg or "unavailable" in msg or "service_unavailable" in msg:
        return "unavailable"
    if "token" in msg and ("limit" in msg or "exceeded" in msg or "too many" in msg):
        return "token_limit"
    if "invalid_argument" in msg and "token" in msg:
        return "token_limit"
    return "unknown"


def _log_f2_failure(
    video_id: str,
    category: str,
    exc: Exception | None,
    extra: str = "",
) -> None:
    """Emit one structured WARNING per F2 failure with credential-safe
    exception text. Both str(exc) and repr(exc) are scrubbed because gRPC
    errors put secrets in the repr but not the str (or vice versa)."""
    from consensus_engine.utils.log_scrub import scrub
    if exc is None:
        log.warning(
            "F2 failure category=%s video=%s%s exc=None",
            category, video_id, f" {extra}" if extra else "",
        )
        return
    log.warning(
        "F2 failure category=%s video=%s%s exc=%s repr=%s",
        category, video_id, f" {extra}" if extra else "",
        scrub(str(exc)), scrub(repr(exc)),
    )


def _get_gemini_client():
    """Legacy helper: return the next-available Gemini client, or None."""
    client, _label = _get_available_gemini_client()
    return client


_MEDIA_RESOLUTION_MAP = {
    "low": "MEDIA_RESOLUTION_LOW",
    "medium": "MEDIA_RESOLUTION_MEDIUM",
    "high": "MEDIA_RESOLUTION_HIGH",
    "default": None,
    "": None,
    "unspecified": None,
}


def _build_generation_config(media_resolution_cfg: str):
    """Return a GenerateContentConfig with media_resolution set, or None.

    ``media_resolution_cfg`` maps yaml strings to google-genai enum values. At
    "low" each video frame is tokenized at 66 tokens (vs 258 at default) —
    ~3× cheaper. Returns ``None`` when nothing needs overriding so the SDK
    applies its own defaults.
    """
    mapped = _MEDIA_RESOLUTION_MAP.get(media_resolution_cfg)
    if not mapped:
        return None
    try:
        from google.genai import types
        return types.GenerateContentConfig(media_resolution=getattr(types.MediaResolution, mapped))
    except Exception as e:
        log.debug("gemini_video_parser: could not build GenerateContentConfig: %s", e)
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
    from consensus_engine.analysis.ticker_grounding import filter_tickers_by_grounding

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
    drop_count = 0
    for sp in data.get("spans", []) or []:
        if not isinstance(sp, dict):
            continue
        quote = str(sp.get("quote", "")).strip()
        if not quote:
            continue
        # Filter tickers to those grounded in this span's quote.
        raw_tickers = _clean_tickers(sp.get("tickers", []))
        grounded, dropped = filter_tickers_by_grounding(raw_tickers, quote)
        if dropped:
            log.info(
                "ticker_grounding: dropped %s from span ts=%s video=%s quote=%r",
                dropped, sp.get("ts_sec"), video_id, quote[:80],
            )
            drop_count += len(dropped)
        spans.append(EvidenceSpan(
            ts_sec=_parse_ts_str(sp.get("ts_sec", 0)),
            quote=quote,
            tickers=grounded,
            numbers=_clean_numbers(sp.get("numbers", [])),
            dates_mentioned=_clean_dates(sp.get("dates_mentioned", [])),
        ))
    if drop_count:
        log.warning(
            "ticker_grounding: video=%s dropped %d ungrounded ticker labels across spans",
            video_id, drop_count,
        )

    visual_evidence = _clean_visual_evidence(
        data.get("visual_evidence", []), duration_sec
    )

    return EvidenceBundle(
        video_id=video_id,
        duration_sec=duration_sec,
        publish_ts=published_at,
        segments=segments,
        spans=spans,
        visual_evidence=visual_evidence,
    )


def _is_negative_ts(ts) -> bool:
    """True if a raw timestamp is numerically negative.

    ``_parse_ts_str`` clamps negatives to 0, so the raw value must be checked
    before parsing to honor the "drop ts_sec < 0" rule.
    """
    if isinstance(ts, bool):
        return False
    if isinstance(ts, (int, float)):
        return ts < 0
    if isinstance(ts, str):
        s = ts.strip()
        if s.startswith("-"):
            return True
    return False


def _clean_visual_evidence(raw: object, duration_sec: int | None) -> list[dict]:
    """Normalize, dedup, range-filter, and cap on-screen visual-evidence items.

    - Each entry normalized to {ts_sec:int, value:str, kind:str, where:str}.
    - Dedup by ``value`` (keep first occurrence).
    - Drop entries whose ``ts_sec`` is outside [0, duration_sec]; if
      ``duration_sec`` is None the upper-bound check is skipped.
    - Hard-cap at 50 entries (the soft prompt cap is ignored by the model).
    """
    out: list[dict] = []
    seen_values: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        if _is_negative_ts(item.get("ts_sec", 0)):
            continue
        ts_sec = _parse_ts_str(item.get("ts_sec", 0))
        value = str(item.get("value", "")).strip()
        if not value:
            continue
        if value in seen_values:
            continue
        if duration_sec is not None and ts_sec > duration_sec:
            continue
        seen_values.add(value)
        entry = {
            "ts_sec": ts_sec,
            "value": value,
            "kind": str(item.get("kind", "")),
            "where": str(item.get("where", "")),
        }
        # B3: keep the per-number ticker tag when Gemini supplied one (only
        # asked for when the feature is on). Validate it looks like a symbol;
        # null/blank/junk → untagged (falls back to top-ticker attribution).
        raw_tkr = item.get("ticker")
        if isinstance(raw_tkr, str):
            cand = raw_tkr.strip().upper().lstrip("$")
            if 1 <= len(cand) <= 5 and cand.isalpha():
                entry["ticker"] = cand
        out.append(entry)
        if len(out) >= 50:
            break
    return out


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
    # Orchestrator: pick initial tier from yaml + budget, call Stage A once,
    # optionally escalate one tier up if the span count is poor. Persistence
    # happens here (once) so two escalation attempts don't create duplicate runs.
    telemetry = RunTelemetry()
    orchestrator_start = time.monotonic()

    try:
        from consensus_engine.engine import BudgetManager
        budget_probe = BudgetManager()
        budget_pct = await _best_effort_gemini_budget_pct(budget_probe)
    except Exception as e:
        log.debug("extract_evidence_with_gemini: budget probe failed: %s", e)
        budget_pct = None

    cfg_res = str(cfg.get("youtube.gemini.media_resolution", "auto")).strip().lower()
    initial_tier = _pick_media_resolution(cfg_res, budget_pct)

    # Chunked long-video path: when enabled and the video exceeds the threshold,
    # split into sequential windows rather than letting Gemini silently truncate.
    # We fetch the true duration from Invidious (same call the partial-read alarm
    # uses after the fact) so we can decide BEFORE sending to Gemini.
    bundle: EvidenceBundle | None = None
    used_chunked_path = False
    if bool(cfg.get("youtube.gemini.chunked_long_videos", True)):
        chunk_threshold = int(cfg.get("youtube.gemini.chunk_threshold_sec", 1200))
        try:
            from consensus_engine.utils.transcript_fetch import fetch_youtube_duration
            pre_duration = await fetch_youtube_duration(video_id)
        except Exception as _e:
            log.debug("extract_evidence_with_gemini: pre-fetch duration failed for %s: %s", video_id, _e)
            pre_duration = None
        if pre_duration is not None and pre_duration > chunk_threshold:
            log.info(
                "extract_evidence_with_gemini: %s is %ds > threshold %ds — using chunked path",
                video_id, pre_duration, chunk_threshold,
            )
            bundle, telemetry = await _extract_evidence_chunked(
                video_id, channel_name, published_at,
                media_resolution=initial_tier,
                duration_sec=pre_duration,
            )
            used_chunked_path = True

    if not used_chunked_path:
        bundle, telemetry = await _extract_evidence_single_pass(
            video_id, channel_name, published_at, media_resolution=initial_tier,
        )

    if (
        not used_chunked_path
        and bundle is not None
        and bool(cfg.get("youtube.gemini.auto_escalate_enabled", True))
    ):
        min_spans = int(cfg.get("youtube.gemini.auto_escalate_min_spans", 20))
        min_duration_min = int(cfg.get("youtube.gemini.auto_escalate_min_duration_min", 15))
        budget_pct_for_default = float(cfg.get("youtube.gemini.budget_pct_for_default", 50))
        budget_pct_for_medium = float(cfg.get("youtube.gemini.budget_pct_for_medium", 75))
        next_tier = _should_escalate(
            span_count=telemetry.span_count or 0,
            duration_sec=bundle.duration_sec,
            current_tier=initial_tier,
            budget_pct=budget_pct,
            cfg_min_spans=min_spans,
            cfg_min_duration_min=min_duration_min,
            budget_pct_for_default=budget_pct_for_default,
            budget_pct_for_medium=budget_pct_for_medium,
        )
        if next_tier:
            log.info(
                "extract_evidence_with_gemini: auto-escalating %s from %s → %s "
                "(spans=%d < %d, duration=%ss)",
                video_id, initial_tier, next_tier, telemetry.span_count or 0,
                min_spans, bundle.duration_sec,
            )
            bundle2, tel2 = await _extract_evidence_single_pass(
                video_id, channel_name, published_at, media_resolution=next_tier,
            )
            if bundle2 is not None and (tel2.span_count or 0) > (telemetry.span_count or 0):
                bundle, telemetry = bundle2, tel2

    # Hallucination quarantine (item B, deep-dive-2026-06-08): a Gemini response that
    # returns evidence spans but NO prompt_token_count is physically impossible (you cannot
    # analyze a video without feeding it in) — it is the fabricated-recap signature that
    # poisoned the brief with NVDA 850 / MSFT 415 / SPY 500 / TSLA 175. Discard it BEFORE
    # any persist so nothing is stored and the video stays retryable (reuses the existing
    # Gemini-failure path; interacts cleanly with item G's quota_blocked re-queue).
    if bundle is not None and bundle.spans and telemetry.saw_null_input_tokens:
        log.warning(
            "QUARANTINE %s: gemini returned %d spans but NULL prompt_token_count "
            "(hallucination signature) — discarding, video stays retryable",
            video_id, len(bundle.spans),
        )
        telemetry.f2_failure_category = "gemini_no_input_tokens"
        telemetry.latency_ms = int((time.monotonic() - orchestrator_start) * 1000)
        return (None, telemetry)

    # Persist spans exactly once — on the winner.
    if bundle is not None:
        model = cfg.get("youtube.gemini.model", "gemini-2.5-flash")
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
        if bundle.visual_evidence:
            try:
                await db.insert_youtube_visual_evidence(video_id, bundle.visual_evidence)
            except Exception as e:
                log.debug("extract_evidence_with_gemini: visual_evidence persist failed: %s", e)
        log.info(
            "extract_evidence_with_gemini: %s → %d spans, %d segments, %d visual, %dms",
            video_id, len(bundle.spans), len(bundle.segments),
            len(bundle.visual_evidence), telemetry.latency_ms,
        )

    # Orchestrator latency covers both passes if escalation ran.
    telemetry.latency_ms = int((time.monotonic() - orchestrator_start) * 1000)
    return (bundle, telemetry)


_RESOLUTION_TIERS = ("low", "medium", "default", "high")


def _pick_media_resolution(config_value: str, budget_pct_used: float | None) -> str:
    """Pick an effective media_resolution tier.

    ``config_value`` can be an explicit tier ("low"/"medium"/"high"/"default")
    or "auto" / "" / "unspecified". In auto mode the tier is chosen from the
    current budget utilisation so the system conserves quota when depleted:

        budget_pct_used < budget_pct_for_default (default 50)  →  "default"
        budget_pct_used < budget_pct_for_medium  (default 75)  →  "medium"
        budget_pct_used >= budget_pct_for_medium               →  "low"

    A missing budget reading (None) is treated optimistically as "default" —
    we'd rather overshoot on one call than starve a video that already
    consumed 700K tokens to extract spans.
    """
    cfg_val = (config_value or "").strip().lower()
    if cfg_val in _RESOLUTION_TIERS:
        return cfg_val
    if cfg_val in ("", "unspecified"):
        return "default"
    if cfg_val == "auto":
        if budget_pct_used is None:
            return "default"
        thresh_default = float(cfg.get("youtube.gemini.budget_pct_for_default", 50))
        thresh_medium = float(cfg.get("youtube.gemini.budget_pct_for_medium", 75))
        if budget_pct_used < thresh_default:
            return "default"
        if budget_pct_used < thresh_medium:
            return "medium"
        return "low"
    return cfg_val  # unknown literal — pass through, SDK will error if invalid


def _should_escalate(
    *,
    span_count: int,
    duration_sec: int | None,
    current_tier: str,
    budget_pct: float | None,
    cfg_min_spans: int,
    cfg_min_duration_min: int,
    budget_pct_for_default: float = 50.0,
    budget_pct_for_medium: float = 75.0,
) -> str | None:
    """Return the next resolution tier to retry at, or None to stop."""
    if current_tier in ("default", "high"):
        return None
    if span_count >= cfg_min_spans:
        return None
    if duration_sec is not None and duration_sec < cfg_min_duration_min * 60:
        return None  # short video — not worth the extra quota
    if budget_pct is not None and budget_pct >= budget_pct_for_medium:
        # Too little budget left to spend on a retry.
        return None
    if current_tier == "low":
        return "medium"
    if current_tier == "medium":
        if budget_pct is not None and budget_pct >= budget_pct_for_default:
            return None  # don't jump to default when budget is moderately tight
        return "default"
    return None


async def _best_effort_gemini_budget_pct(budget_manager) -> float | None:
    """Return pct_used (0–100) for Gemini input tokens, or None on failure."""
    try:
        return await budget_manager.pct_used("gemini_input_tokens")
    except Exception as e:
        log.debug("_best_effort_gemini_budget_pct: %s", e)
        return None


def _compute_chunk_windows(
    duration_sec: int,
    chunk_window_sec: int,
    overlap_sec: int,
    max_windows: int,
) -> list[tuple[int, int]]:
    """Return a list of (start_sec, end_sec) windows covering ``duration_sec``.

    Windows are ``chunk_window_sec`` wide with ``overlap_sec`` of overlap at each
    boundary so context isn't lost at the seam. The list is capped at
    ``max_windows`` (tail loss is logged by the caller).

    Example: duration=6314, window=900, overlap=30, max=6 →
      (0, 900), (870, 1770), (1740, 2640), (2610, 3510), (3480, 4380), (4350, 5250)
    The last window's end may exceed duration_sec; callers should clamp.
    """
    if duration_sec <= 0 or chunk_window_sec <= 0:
        return [(0, duration_sec)]
    step = max(1, chunk_window_sec - overlap_sec)
    windows: list[tuple[int, int]] = []
    start = 0
    while start < duration_sec:
        end = min(start + chunk_window_sec, duration_sec)
        windows.append((start, end))
        if end >= duration_sec:
            break
        start += step
        if len(windows) >= max_windows:
            break
    return windows


def _merge_chunked_bundles(
    per_window: list[tuple[EvidenceBundle | None, int, int]],
    video_id: str,
    published_at: str,
    true_duration_sec: int,
) -> EvidenceBundle:
    """Merge per-window EvidenceBundles into one complete bundle.

    ``per_window`` is a list of ``(bundle_or_None, win_start_sec, win_end_sec)``.
    Merging rules:
    - Spans are concatenated in window order, then deduped by (ts_sec, quote)
      closeness (within 3 seconds AND quote prefix match) to remove overlap
      boundary duplicates. Timestamps beyond true_duration_sec are clamped.
    - Visual evidence is deduped by ``value`` (keep first across all windows).
    - Segments are merged in order, deduped by ts_start_sec.
    - duration_sec is set to true_duration_sec (the actual video length).
    """
    all_spans: list[EvidenceSpan] = []
    all_visual: list[dict] = []
    all_segments: list[dict] = []
    seen_visual_values: set[str] = set()
    seen_segment_starts: set[int] = set()

    for bundle, win_start, win_end in per_window:
        if bundle is None:
            continue
        # Gemini timestamps are relative to the clip start (0 = win_start in the
        # real video). Add win_start so all timestamps are in real-video coordinates.
        for span in bundle.spans:
            ts = min(span.ts_sec + win_start, true_duration_sec)
            all_spans.append(EvidenceSpan(
                ts_sec=ts,
                quote=span.quote,
                tickers=span.tickers,
                numbers=span.numbers,
                dates_mentioned=span.dates_mentioned,
            ))
        for vis in bundle.visual_evidence:
            val = vis.get("value", "")
            if val and val not in seen_visual_values:
                seen_visual_values.add(val)
                ts = min(_parse_ts_str(vis.get("ts_sec", 0)) + win_start, true_duration_sec)
                entry = dict(vis)
                entry["ts_sec"] = ts
                all_visual.append(entry)
        for seg in (bundle.segments or []):
            ts_start = seg.get("ts_start_sec", 0) + win_start
            if ts_start not in seen_segment_starts:
                seen_segment_starts.add(ts_start)
                adjusted_seg = dict(seg)
                adjusted_seg["ts_start_sec"] = ts_start
                all_segments.append(adjusted_seg)

    # Sort spans by timestamp
    all_spans.sort(key=lambda s: s.ts_sec)

    # Dedup overlap-boundary spans: drop a span if an earlier span within
    # 3 seconds shares the first 40 chars of the quote.
    deduped_spans: list[EvidenceSpan] = []
    for span in all_spans:
        is_dup = False
        for prev in reversed(deduped_spans[-10:]):
            if span.ts_sec - prev.ts_sec > 3:
                break
            if span.quote[:40] == prev.quote[:40]:
                is_dup = True
                break
        if not is_dup:
            deduped_spans.append(span)

    all_segments.sort(key=lambda s: s.get("ts_start_sec", 0))

    return EvidenceBundle(
        video_id=video_id,
        duration_sec=true_duration_sec,
        publish_ts=published_at,
        segments=all_segments,
        spans=deduped_spans,
        visual_evidence=all_visual[:50],  # honour the existing 50-cap
    )


async def _extract_evidence_chunked(
    video_id: str,
    channel_name: str,
    published_at: str,
    media_resolution: str,
    duration_sec: int,
) -> tuple[EvidenceBundle | None, RunTelemetry]:
    """Chunked Gemini extraction for long videos.

    Splits the video into sequential windows (config: youtube.gemini.chunk_window_sec,
    chunk_max_windows), calls _extract_evidence_single_pass per window with start/end
    offsets, merges the results. If the budget guard or a 429 trips mid-way, keeps
    whatever windows succeeded and lets the partial-read alarm fire.

    Returns (merged_EvidenceBundle, combined_RunTelemetry).
    """
    chunk_window_sec = int(cfg.get("youtube.gemini.chunk_window_sec", 900))
    overlap_sec = int(cfg.get("youtube.gemini.chunk_overlap_sec", 30))
    max_windows = int(cfg.get("youtube.gemini.chunk_max_windows", 6))

    windows = _compute_chunk_windows(duration_sec, chunk_window_sec, overlap_sec, max_windows)

    if len(windows) < len(_compute_chunk_windows(duration_sec, chunk_window_sec, overlap_sec, 999)):
        uncapped_count = len(_compute_chunk_windows(duration_sec, chunk_window_sec, overlap_sec, 999))
        covered_sec = windows[-1][1] if windows else 0
        log.warning(
            "extract_evidence_chunked: %s capped at %d/%d windows — tail from %ds lost",
            video_id, len(windows), uncapped_count, covered_sec,
        )

    log.info(
        "extract_evidence_chunked: %s duration=%ds → %d windows (window=%ds overlap=%ds)",
        video_id, duration_sec, len(windows), chunk_window_sec, overlap_sec,
    )

    combined_tel = RunTelemetry()
    combined_tel.json_parse_ok = True
    per_window_results: list[tuple[EvidenceBundle | None, int, int]] = []
    total_start = time.monotonic()

    for idx, (win_start, win_end) in enumerate(windows):
        log.info(
            "extract_evidence_chunked: %s window %d/%d [%ds–%ds]",
            video_id, idx + 1, len(windows), win_start, win_end,
        )
        bundle_w, tel_w = await _extract_evidence_single_pass(
            video_id, channel_name, published_at, media_resolution,
            start_offset_sec=win_start,
            end_offset_sec=win_end,
        )
        per_window_results.append((bundle_w, win_start, win_end))
        # Accumulate token counts
        combined_tel.input_tokens += tel_w.input_tokens
        combined_tel.output_tokens += tel_w.output_tokens
        if not tel_w.json_parse_ok:
            combined_tel.json_parse_ok = False
        if tel_w.f2_failure_category in ("quota",):
            # Budget/quota exhausted mid-video — stop now, keep what we have
            log.warning(
                "extract_evidence_chunked: %s budget/quota hit at window %d/%d — stopping early",
                video_id, idx + 1, len(windows),
            )
            break

    combined_tel.latency_ms = int((time.monotonic() - total_start) * 1000)

    successful = [(b, s, e) for b, s, e in per_window_results if b is not None]
    if not successful:
        combined_tel.json_parse_ok = False
        return (None, combined_tel)

    merged = _merge_chunked_bundles(successful, video_id, published_at, duration_sec)
    combined_tel.span_count = len(merged.spans)
    combined_tel.json_parse_ok = True
    return (merged, combined_tel)


async def _extract_evidence_single_pass(
    video_id: str,
    channel_name: str,
    published_at: str,
    media_resolution: str,
    *,
    start_offset_sec: int | None = None,
    end_offset_sec: int | None = None,
) -> tuple[EvidenceBundle | None, RunTelemetry]:
    """One Gemini extraction round at the given media_resolution.

    When ``start_offset_sec`` / ``end_offset_sec`` are provided, the video part
    is sent with VideoMetadata offsets so Gemini only ingests that window (used
    by the chunked long-video path).

    Does: rate-limit acquire, budget gate, key rotation retry on 429, JSON parse,
    bundle build, token-usage accounting. Does NOT persist evidence spans — the
    orchestrator persists once on whichever pass wins.
    """
    telemetry = RunTelemetry()
    start_ts = time.monotonic()

    try:
        from consensus_engine.utils.rate_limiter import rate_limiter
        from consensus_engine.engine import BudgetManager
        await rate_limiter.acquire("gemini")
        budget = BudgetManager()
        if not await budget.can_consume_gemini():
            log.warning("extract_evidence_single_pass: Gemini budget exhausted, skipping %s", video_id)
            telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
            telemetry.json_parse_ok = False
            return (None, telemetry)
    except Exception as e:
        log.debug("extract_evidence_single_pass: budget/rate gate failed: %s", e)
        budget = None

    model_primary = cfg.get("youtube.gemini.model", "gemini-2.5-flash")
    model_fallbacks = [
        m for m in (cfg.get("youtube.gemini.model_fallbacks", []) or [])
        if m and m != model_primary
    ]
    models_to_try = [model_primary] + model_fallbacks
    fps_cfg = cfg.get("youtube.gemini.fps", None)
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    timeout_sec = int(cfg.get("youtube.gemini.timeout_sec", 120))
    # 503 "high demand" is common on free-tier video models; latency is not a
    # constraint, so retry once with backoff before falling to the next model.
    _503_backoffs = [0, 6]

    from google.genai import types

    gen_config = _build_generation_config(media_resolution)

    def _video_part():
        # fps via VideoMetadata cuts input tokens (~225k→144k at 0.5fps, no
        # measured quality loss); plain URI part when fps is unset (=1fps).
        # When offsets are provided (chunked path), VideoMetadata is always
        # used so start_offset/end_offset can be set alongside fps.
        if fps_cfg or start_offset_sec is not None:
            vm_kwargs: dict = {}
            if fps_cfg:
                vm_kwargs["fps"] = float(fps_cfg)
            if start_offset_sec is not None:
                vm_kwargs["start_offset"] = f"{start_offset_sec}s"
            if end_offset_sec is not None:
                vm_kwargs["end_offset"] = f"{end_offset_sec}s"
            return types.Part(
                file_data=types.FileData(file_uri=youtube_url, mime_type="video/*"),
                video_metadata=types.VideoMetadata(**vm_kwargs),
            )
        return types.Part.from_uri(file_uri=youtube_url, mime_type="video/*")

    response = None
    raw = None
    used_model = None
    tried_labels: set[str] = set()
    configured_keys = _get_gemini_keys()
    max_attempts = max(1, len(configured_keys))
    for _attempt in range(max_attempts):
        client, key_label = _get_available_gemini_client(skip=tried_labels)
        if client is None:
            telemetry.f2_failure_category = "quota"
            _log_f2_failure(
                video_id, "quota", None,
                extra=f"reason=no_available_key tried={len(tried_labels)} configured={len(configured_keys)}",
            )
            telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
            telemetry.json_parse_ok = False
            return (None, telemetry)

        key_quota_hit = False
        for _m in models_to_try:
            for _bo in _503_backoffs:
                if _bo:
                    await asyncio.sleep(_bo)
                try:
                    def _sync_call(_client=client, _model=_m):
                        return _client.models.generate_content(
                            model=_model,
                            contents=[
                                types.Part.from_text(text=_evidence_prompt()),
                                _video_part(),
                            ],
                            config=gen_config,
                        )

                    loop = asyncio.get_event_loop()
                    response = await asyncio.wait_for(
                        loop.run_in_executor(None, _sync_call),
                        timeout=timeout_sec,
                    )
                    raw = response.text
                    used_model = _m
                    # B0: capture why generation stopped. An output-token
                    # truncation surfaces here as finish_reason=MAX_TOKENS —
                    # previously invisible (only response.text was read).
                    _finish = None
                    try:
                        _cands = getattr(response, "candidates", None) or []
                        if _cands:
                            _frv = getattr(_cands[0], "finish_reason", None)
                            _finish = getattr(_frv, "name", str(_frv)) if _frv is not None else None
                    except Exception:
                        pass
                    log.info(
                        "extract_evidence_single_pass: %s succeeded via %s model=%s fps=%s finish=%s",
                        video_id, key_label, _m, fps_cfg, _finish,
                    )
                    break  # backoff loop
                except asyncio.TimeoutError as e:
                    telemetry.f2_failure_category = "timeout"
                    _log_f2_failure(video_id, "timeout", e, extra=f"key={key_label} model={_m}")
                    telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
                    telemetry.json_parse_ok = False
                    return (None, telemetry)
                except Exception as e:
                    if _is_quota_error(e):
                        _log_f2_failure(video_id, "quota", e, extra=f"key={key_label} model={_m} action=rotate_key")
                        _mark_key_exhausted(key_label, e)
                        tried_labels.add(key_label)
                        key_quota_hit = True
                        break  # backoff loop
                    category = _categorize_failure(e)
                    telemetry.f2_failure_category = category
                    if category == "unavailable":
                        # 503 "high demand": retry this model with backoff, then
                        # fall through to the next fallback model.
                        _log_f2_failure(video_id, category, e, extra=f"key={key_label} model={_m} action=retry_then_next_model")
                        continue  # next backoff
                    # unknown/other failure: try the next fallback model
                    _log_f2_failure(video_id, category, e, extra=f"key={key_label} model={_m} action=next_model")
                    break  # backoff loop → next model
            if raw is not None or key_quota_hit:
                break  # model loop
        if raw is not None:
            break  # key loop
        if not key_quota_hit:
            # All models failed on this key for non-quota reasons (503/other);
            # rotating keys won't fix model availability, so stop.
            break

    if raw is None:
        telemetry.f2_failure_category = telemetry.f2_failure_category or "quota"
        _log_f2_failure(
            video_id, telemetry.f2_failure_category, None,
            extra="reason=all_models_or_keys_exhausted",
        )
        telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
        telemetry.json_parse_ok = False
        return (None, telemetry)

    telemetry.latency_ms = int((time.monotonic() - start_ts) * 1000)
    in_tok, out_tok = _extract_token_counts(response)
    # Capture the RAW NULL signal here — input_tokens is coerced to 0 below, destroying it.
    # spans-but-NULL-prompt_token_count is the hallucination fingerprint (item B).
    telemetry.saw_null_input_tokens = (in_tok is None)
    if in_tok is not None:
        telemetry.input_tokens = in_tok
    if out_tok is not None:
        telemetry.output_tokens = out_tok

    if budget is not None:
        try:
            await budget.consume_gemini(
                telemetry.input_tokens or 0,
                telemetry.output_tokens or 0,
            )
        except Exception as e:
            log.debug("extract_evidence_single_pass: consume_gemini failed: %s", e)

    data = _parse_gemini_response(raw)
    if data is None:
        log.warning("extract_evidence_single_pass: unparseable response for %s", video_id)
        telemetry.json_parse_ok = False
        return (None, telemetry)

    telemetry.json_parse_ok = True
    bundle = _build_evidence_bundle(data, video_id, published_at)
    telemetry.span_count = len(bundle.spans)
    return (bundle, telemetry)
