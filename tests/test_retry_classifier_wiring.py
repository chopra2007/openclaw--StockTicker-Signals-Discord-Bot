"""C3 (reliability-hardening): wire the existing burst_retry classifier +
parse_retry_after into the news cascade and llm_client, with rate_limiter as the
SINGLE backoff authority. Conservative + flag-gated (retry.use_classifier,
default OFF): we only OVERRIDE the normal backoff when the server gave a real
Retry-After hint; otherwise behavior is unchanged.

The LLM Retry-After is capped at retry.llm_retry_after_cap_s (120) so a raw
hint like 86399s can never block the LLM bucket for hours (the blank-thesis
amplifier)."""
import time

import pytest

from consensus_engine import config
from consensus_engine.utils.rate_limiter import RateLimiter


# ---- rate_limiter Retry-After extension (the single backoff authority) ----

def test_report_failure_without_retry_after_unchanged():
    rl = RateLimiter()
    # 2 failures: no backoff yet (exponential only kicks in at >=3)
    rl.report_failure("src")
    rl.report_failure("src")
    assert rl.is_blocked("src") is False


def test_report_failure_honors_retry_after_immediately():
    rl = RateLimiter()
    rl.report_failure("src", retry_after=50)  # first failure, but server said wait 50s
    assert rl.is_blocked("src") is True
    remaining = rl._blocked_until["src"] - time.time()
    assert 45 < remaining <= 50


def test_report_failure_caps_retry_after_at_600():
    rl = RateLimiter()
    rl.report_failure("src", retry_after=99999)
    remaining = rl._blocked_until["src"] - time.time()
    assert 595 < remaining <= 600, f"Retry-After must cap at 600s, got {remaining}"


# ----------------------------- news cascade -------------------------------

def _flag(monkeypatch, on):
    real = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: on if k == "retry.use_classifier" else real(k, d))


async def test_news_failure_flag_off_is_plain_report(monkeypatch):
    from consensus_engine.scanners import news
    _flag(monkeypatch, False)
    calls = []
    monkeypatch.setattr(news.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append((s, retry_after)))
    await news._report_news_failure("brave_search", status=429,
                              body='{"error":"rate limit"} Retry-After: 30')
    assert calls == [("brave_search", None)], "flag OFF must be a plain report_failure"


async def test_news_failure_quota_with_hint_paces(monkeypatch):
    from consensus_engine.scanners import news
    _flag(monkeypatch, True)
    calls = []
    monkeypatch.setattr(news.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append((s, retry_after)))
    await news._report_news_failure("brave_search", status=429,
                              body="rate limit exceeded. Retry-After: 45")
    assert len(calls) == 1
    src, ra = calls[0]
    assert src == "brave_search"
    assert ra == 45.0, f"QUOTA + hint must pass the parsed Retry-After, got {ra}"


async def test_news_failure_transient_no_override(monkeypatch):
    from consensus_engine.scanners import news
    _flag(monkeypatch, True)
    calls = []
    monkeypatch.setattr(news.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append((s, retry_after)))
    await news._report_news_failure("finnhub_news", status=503, body="service unavailable")
    assert calls == [("finnhub_news", None)], "transient 5xx keeps normal backoff"


# ------------------------------- llm_client -------------------------------

def _llm_flag(monkeypatch, on, cap=120):
    from consensus_engine import llm_client
    real = llm_client.cfg.get
    cfgmap = {"retry.use_classifier": on, "retry.llm_retry_after_cap_s": cap}
    monkeypatch.setattr(llm_client.cfg, "get",
                        lambda k, d=None: cfgmap.get(k, real(k, d)))


def test_llm_retry_caps_at_120(monkeypatch):
    from consensus_engine import llm_client
    _llm_flag(monkeypatch, True, cap=120)
    calls = []
    monkeypatch.setattr(llm_client.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append((s, retry_after)))
    # a 429 whose hint (86399s, e.g. per-day) must be capped to 120
    llm_client._note_llm_retry("openrouter", 429, "quota exceeded retryDelay: 86399s", None)
    assert len(calls) == 1
    assert calls[0][0] == "openrouter"
    assert calls[0][1] == 120.0, f"LLM Retry-After must cap at 120, got {calls[0][1]}"


def test_llm_retry_no_hint_is_noop(monkeypatch):
    from consensus_engine import llm_client
    _llm_flag(monkeypatch, True)
    calls = []
    monkeypatch.setattr(llm_client.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append((s, retry_after)))
    # 429 with NO parseable Retry-After -> preserve current no-backoff behavior
    llm_client._note_llm_retry("openrouter", 429, "Too Many Requests", None)
    assert calls == [], "a hint-less 429 must NOT introduce LLM bucket backoff"


def test_llm_retry_flag_off_is_noop(monkeypatch):
    from consensus_engine import llm_client
    _llm_flag(monkeypatch, False)
    calls = []
    monkeypatch.setattr(llm_client.rate_limiter, "report_failure",
                        lambda s, retry_after=None: calls.append((s, retry_after)))
    llm_client._note_llm_retry("openrouter", 429, "quota retryDelay: 30s", None)
    assert calls == [], "flag OFF must be a no-op"
