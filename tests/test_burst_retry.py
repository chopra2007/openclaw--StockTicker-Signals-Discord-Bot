"""Tests for the shared burst-retry classifier/parser (item A + G, deep-dive-2026-06-08)."""
import asyncio
import time

from consensus_engine.utils.burst_retry import (
    RetryClass,
    classify_retry,
    parse_retry_after,
    next_backoff,
    is_per_day_quota,
)

# Real-ish Gemini 429 bodies (per-minute token quota vs per-day request quota).
GEMINI_PER_MINUTE_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', "
    "'message': 'You exceeded your current quota. quota_metric: "
    "generativelanguage.googleapis.com/free_tier_input_token_count, retryDelay: \"54s\"'}}"
)
GEMINI_PER_DAY_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED', "
    "'message': 'Quota exceeded for quota metric GenerateContentFreeTierRequestsPerDay', "
    "'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}}"
)


def test_classify_429_status_is_quota_blocked():
    assert classify_retry(http_status=429) is RetryClass.QUOTA_BLOCKED


def test_classify_5xx_is_transient():
    assert classify_retry(http_status=502) is RetryClass.TRANSIENT
    assert classify_retry(http_status=503) is RetryClass.TRANSIENT
    assert classify_retry(http_status=504) is RetryClass.TRANSIENT


def test_classify_4xx_is_permanent():
    assert classify_retry(http_status=400) is RetryClass.PERMANENT
    assert classify_retry(http_status=404) is RetryClass.PERMANENT


def test_classify_empty_body_is_transient_not_permanent():
    # vision_completion returns "" on a transport blip — must retry, never abandon.
    assert classify_retry(http_status=None, body="") is RetryClass.TRANSIENT


def test_classify_timeout_exception_is_transient():
    assert classify_retry(exc=asyncio.TimeoutError()) is RetryClass.TRANSIENT


def test_classify_gemini_quota_exc_is_quota_blocked():
    assert classify_retry(exc=Exception(GEMINI_PER_MINUTE_429)) is RetryClass.QUOTA_BLOCKED
    assert classify_retry(exc=Exception(GEMINI_PER_DAY_429)) is RetryClass.QUOTA_BLOCKED


def test_parse_retry_after_from_retrydelay():
    assert parse_retry_after(GEMINI_PER_MINUTE_429) == 54.0


def test_parse_retry_after_retry_in_phrasing():
    assert parse_retry_after("Please retry in ~30s") == 30.0


def test_parse_retry_after_header():
    assert parse_retry_after("Retry-After: 12") == 12.0


def test_parse_retry_after_none_when_absent():
    assert parse_retry_after(GEMINI_PER_DAY_429) is None
    assert parse_retry_after("") is None
    assert parse_retry_after(None) is None


def test_parse_retry_after_ratelimit_reset_ms():
    future_ms = int((time.time() + 40) * 1000)
    got = parse_retry_after(f"x-ratelimit-reset: {future_ms}")
    assert got is not None and 30 < got < 45


def test_is_per_day_quota_discriminates():
    assert is_per_day_quota(GEMINI_PER_DAY_429) is True
    assert is_per_day_quota(GEMINI_PER_MINUTE_429) is False


def test_next_backoff_caps_and_grows():
    d1 = next_backoff(1)
    d5 = next_backoff(5)
    assert d1 < d5
    assert next_backoff(10) <= 60.0 * 1.25  # cap + max jitter
    # deterministic (resume-safe): same input -> same output
    assert next_backoff(3) == next_backoff(3)
