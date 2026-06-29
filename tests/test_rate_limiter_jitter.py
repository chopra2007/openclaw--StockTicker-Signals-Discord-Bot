"""C1 (reliability-hardening): EQUAL jitter on the backoff schedule + a one-time
per-source kickoff stagger.

Equal jitter = d/2 + uniform(0, d/2), so the wait stays in [d/2, d]. This
de-synchronizes retries across sources WITHOUT the failure mode of full jitter
(uniform(0, d)), which can pick a near-zero wait and re-probe a dead source
almost immediately — halving the effective mean and doubling probes of a known-
bad source. jitter_mode="none" restores the exact pre-change schedule."""
import time

import pytest

from consensus_engine import config
from consensus_engine.utils.rate_limiter import RateLimiter


def _mode(monkeypatch, mode):
    real = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: mode if k == "rate_limiter.jitter_mode" else real(k, d))


def test_equal_jitter_in_range_and_actually_varies(monkeypatch):
    """Must stay in [d/2, d]=[15,30] AND actually introduce spread (the old
    no-jitter code emits exactly 30, so a constant value fails this)."""
    _mode(monkeypatch, "equal")
    samples = []
    for _ in range(200):
        rl = RateLimiter()
        for _ in range(3):  # count==3 -> d = 30
            rl.report_failure("s")
        samples.append(rl._blocked_until["s"] - time.time())
    assert min(samples) >= 15.0, f"equal jitter must never drop below d/2=15, got {min(samples)}"
    assert max(samples) <= 30.0, f"equal jitter must not exceed d=30, got {max(samples)}"
    assert (max(samples) - min(samples)) > 5.0, "equal jitter must spread the backoff, not be constant"


def test_equal_jitter_never_near_zero(monkeypatch):
    """The whole point: a dead source is never re-probed almost immediately."""
    _mode(monkeypatch, "equal")
    mins = []
    for _ in range(200):
        rl = RateLimiter()
        for _ in range(3):
            rl.report_failure("s")
        mins.append(rl._blocked_until["s"] - time.time())
    assert min(mins) >= 15.0, f"equal jitter must never drop below d/2=15, got {min(mins)}"


def test_jitter_none_is_exact_schedule(monkeypatch):
    _mode(monkeypatch, "none")
    rl = RateLimiter()
    for _ in range(3):
        rl.report_failure("src")
    remaining = rl._blocked_until["src"] - time.time()
    assert 29.0 <= remaining <= 30.0, f"jitter_mode=none must be exactly d=30, got {remaining}"


def test_retry_after_unaffected_by_jitter(monkeypatch):
    """An explicit server Retry-After (C3) is honored verbatim (capped), not jittered."""
    _mode(monkeypatch, "equal")
    rl = RateLimiter()
    rl.report_failure("src", retry_after=50)
    remaining = rl._blocked_until["src"] - time.time()
    assert 45 < remaining <= 50


async def test_kickoff_stagger_on_first_request(monkeypatch):
    _mode(monkeypatch, "equal")
    monkeypatch.setattr("consensus_engine.utils.rate_limiter.random.uniform",
                        lambda a, b: 0.3)
    rl = RateLimiter()
    t0 = time.time()
    ok = await rl.acquire("fresh_source")
    assert ok is True
    # a fresh source's reserved slot is pushed out by the kickoff stagger
    assert rl._last_request["fresh_source"] >= t0 + 0.29


async def test_no_stagger_when_jitter_none(monkeypatch):
    _mode(monkeypatch, "none")
    rl = RateLimiter()
    t0 = time.time()
    await rl.acquire("fresh_source")
    # no stagger -> reserved at ~now (a fresh source has no min-interval wait)
    assert rl._last_request["fresh_source"] - t0 < 0.05
