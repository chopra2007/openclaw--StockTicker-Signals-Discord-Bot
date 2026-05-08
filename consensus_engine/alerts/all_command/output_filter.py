"""Narrative sanitization, contradiction detection, and data-only fallback.

Sanitizes LLM output before exposure to Discord:
- Markdown links `[text](url)` -> `text (url)` (defeats clickable phishing)
- `@everyone` / `@here` mentions replaced with `[mention removed]`
- Control characters stripped

Detects direction contradictions between narrative and structured signal; if
the LLM goes off-rails, retries once with a hardened prompt and ultimately
falls back to a deterministic 2-line data-only render.
"""
from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Optional

from consensus_engine.alerts.all_command.structured_fields import StructuredFields
from consensus_engine.models import ScoreBreakdown

log = logging.getLogger("consensus_engine.alerts.all_command.output_filter")


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MENTION_RE = re.compile(r"@(?:everyone|here)\b", re.IGNORECASE)
_BEARISH_WORDS = re.compile(
    r"\b(bearish|sell|short|downside|tanking|crash|plunge)\b", re.IGNORECASE)
_BULLISH_WORDS = re.compile(
    r"\b(bullish|buy|long|upside|rally|breakout|surge)\b", re.IGNORECASE)


def sanitize_narrative(text: str) -> str:
    """Strip markdown links, control chars, and @everyone/@here mentions."""
    if not text or not isinstance(text, str):
        return ""
    out = _MARKDOWN_LINK_RE.sub(r"\1 (\2)", text)
    out = _CONTROL_RE.sub("", out)
    out = _MENTION_RE.sub("[mention removed]", out)
    return out


def detect_contradiction(narrative: str, structured: StructuredFields) -> bool:
    """Return True if the narrative direction contradicts structured.direction.

    BULLISH structured + bearish narrative words -> contradiction.
    BEARISH structured + bullish narrative words -> contradiction.
    NEUTRAL structured -> no contradiction (LLM is free to discuss either side).
    """
    if not narrative or structured is None:
        return False
    direction = (structured.direction or "").upper()
    if direction == "BULLISH":
        return bool(_BEARISH_WORDS.search(narrative))
    if direction == "BEARISH":
        return bool(_BULLISH_WORDS.search(narrative))
    return False


async def sanitize_or_retry(
    narrative: str,
    structured: StructuredFields,
    retry_fn: Callable[[], Awaitable[str]],
) -> tuple[str, str]:
    """Sanitize narrative; on contradiction retry once via retry_fn.

    Returns (sanitized_text, status). status is one of:
        "ok"                -> sanitized narrative is safe to emit
        "fallback_data_only" -> retry also contradicted; caller renders fallback
    """
    sanitized = sanitize_narrative(narrative)
    if not detect_contradiction(sanitized, structured):
        return sanitized, "ok"

    log.warning(
        "output_filter: contradiction detected vs direction=%s; retrying once",
        getattr(structured, "direction", "?"),
    )
    try:
        retry_text = await retry_fn()
    except Exception as e:
        log.warning("output_filter: retry_fn raised %s; falling back", e)
        return "", "fallback_data_only"

    sanitized_retry = sanitize_narrative(retry_text or "")
    if not sanitized_retry or detect_contradiction(sanitized_retry, structured):
        return "", "fallback_data_only"
    return sanitized_retry, "ok"


def render_data_only_fallback(
    structured: StructuredFields,
    score_breakdown: ScoreBreakdown,
    sources: list[str],
) -> str:
    """Deterministic 2-line render used when narrative is auto-redacted."""
    direction = getattr(structured, "direction", "NEUTRAL") or "NEUTRAL"
    label = getattr(structured, "confidence_label", "LOW") or "LOW"
    final_score = (
        getattr(score_breakdown, "total", None)
        if score_breakdown is not None
        else None
    )
    score_str = str(final_score) if final_score is not None else "—"
    return (
        "_(Narrative auto-redacted; structured signal below.)_\n"
        f"**Direction:** {direction} · **Confidence:** {label} · "
        f"**Score:** {score_str}"
    )
