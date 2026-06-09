"""Shared retry-classification helpers for the two burst-prone pipelines:
item A (Wolf chart vision via OpenRouter) and item G (YouTube → transcript via Gemini).

This is a *pattern* shared by both, NOT a shared runtime pacer/queue/key-budget — A and G
have different providers, quota shapes, and durability needs (see deep-dive-2026-06-08 design).
Each pipeline feeds its own raw signal (HTTP status for A, exception for G) and keeps its own
pacing loop, queue, and key rotation. Only these three pure functions are shared.
"""
from __future__ import annotations

import enum
import re


class RetryClass(enum.Enum):
    QUOTA_BLOCKED = "quota_blocked"   # 429 / RESOURCE_EXHAUSTED / token-quota -> retry forever, paced
    TRANSIENT = "transient"           # 5xx / timeout / reset / empty -> retry, capped, time-boxed
    PERMANENT = "permanent"           # 4xx / no-captions / malformed -> give up after N


# server-suggested-wait patterns: "retry in ~54s", retryDelay: "54s", Retry-After: 54
_RETRY_AFTER_PATTERNS = (
    re.compile(r'retry[_\s-]?delay["\s:]+["\']?(\d+(?:\.\d+)?)\s*s', re.I),
    re.compile(r'retry\s+in\s+~?\s*(\d+(?:\.\d+)?)\s*s', re.I),
    re.compile(r'retry[-_\s]?after["\s:]+["\']?(\d+(?:\.\d+)?)', re.I),
)
# X-RateLimit-Reset is an epoch in ms on OpenRouter; handled separately below.
_RESET_MS_PATTERN = re.compile(r'x-?ratelimit-?reset["\s:]+["\']?(\d{12,})', re.I)


def classify_retry(*, http_status: int | None = None,
                   exc: Exception | None = None,
                   body: str | None = None) -> RetryClass:
    """Map a raw failure signal onto the two-bucket retry model.

    A feeds ``http_status`` (+ optional ``body``); G feeds ``exc``. Quota/rate ->
    QUOTA_BLOCKED (retry forever, paced); 5xx/timeout/empty -> TRANSIENT (retry,
    time-boxed); 4xx/malformed -> PERMANENT (give up after N).
    """
    blob = ""
    if body:
        blob += " " + body
    if exc is not None:
        blob += " " + str(exc) + " " + repr(exc)
    low = blob.lower()

    # Exception-driven (G): timeout is transient even if no status.
    if exc is not None:
        import asyncio as _asyncio
        if isinstance(exc, (_asyncio.TimeoutError, TimeoutError)):
            return RetryClass.TRANSIENT

    # Explicit HTTP status (A) takes precedence when present.
    if http_status is not None:
        if http_status == 429:
            return RetryClass.QUOTA_BLOCKED
        if http_status >= 500:
            return RetryClass.TRANSIENT
        if http_status in (408,):
            return RetryClass.TRANSIENT
        if 400 <= http_status < 500:
            return RetryClass.PERMANENT
        if http_status == 0 or http_status is None:
            return RetryClass.TRANSIENT

    # Text-driven (quota first — it can co-occur with a 429 in the body).
    if ("429" in low or "resource_exhausted" in low or "quota" in low
            or "rate limit" in low or "rate_limit" in low
            or "too many requests" in low):
        return RetryClass.QUOTA_BLOCKED
    if ("503" in low or "502" in low or "504" in low or "unavailable" in low
            or "timeout" in low or "timed out" in low or "connection reset" in low
            or "service_unavailable" in low):
        return RetryClass.TRANSIENT
    if exc is None and http_status is None and not low.strip():
        # empty body / no signal -> transient (retry), never permanent
        return RetryClass.TRANSIENT
    if ("400" in low or "401" in low or "403" in low or "404" in low
            or "invalid_argument" in low or "permission" in low
            or "not found" in low or "no captions" in low or "malformed" in low):
        return RetryClass.PERMANENT
    # Unknown text with no clear marker -> transient (fail-soft toward retrying, never abandon).
    return RetryClass.TRANSIENT


def parse_retry_after(payload: str | None) -> float | None:
    """Extract a server-suggested wait (seconds) from an error string / 429 body.

    Handles "retry in ~54s", retryDelay: "54s", Retry-After: 54, and an
    X-RateLimit-Reset epoch-ms (converted to a relative wait via time.time()).
    Returns None when nothing parseable is present (caller falls back to a fixed pace).
    """
    if not payload:
        return None
    text = str(payload)
    for pat in _RETRY_AFTER_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                v = float(m.group(1))
                if 0 < v < 86400:
                    return v
            except (TypeError, ValueError):
                pass
    m = _RESET_MS_PATTERN.search(text)
    if m:
        import time as _time
        try:
            reset_s = float(m.group(1)) / 1000.0
            delta = reset_s - _time.time()
            if 0 < delta < 86400:
                return delta
        except (TypeError, ValueError):
            pass
    return None


def next_backoff(attempt: int, base: float = 2.0, cap: float = 60.0) -> float:
    """Capped exponential backoff with deterministic jitter.

    Jitter is derived from the attempt index (NOT random) so the value is
    reproducible and resume-safe. attempt is 1-based.
    """
    a = max(1, int(attempt))
    raw = base * (2 ** (a - 1))
    delay = min(raw, cap)
    # deterministic jitter in [0, 0.25*delay) keyed off the attempt index
    jitter = ((a * 2654435761) % 1000) / 1000.0 * 0.25 * delay
    return round(delay + jitter, 3)


def is_per_day_quota(payload: str | None) -> bool:
    """True when a Gemini/OpenRouter quota error names a PER-DAY limit (vs per-minute).

    Used by G to decide bench duration: a per-day cap benches to Pacific midnight; a
    per-minute 429 benches only the parsed retry-after. Misclassify toward the LONGER
    bench (treat ambiguous as NOT per-day only when a short retryDelay is present).
    """
    if not payload:
        return False
    low = str(payload).lower()
    return ("perday" in low or "per_day" in low or "per day" in low
            or "requestsperday" in low or "requests_per_day" in low
            or "generate_content_free_tier_requests" in low and "day" in low)
