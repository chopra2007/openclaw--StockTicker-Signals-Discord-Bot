"""C20 (reliability-hardening): a single process-wide concurrency cap shared by
every unauthenticated yfinance ("Yahoo") fetch — options flow, max-pain, peer
comparison. Bounding total concurrent hits to the Yahoo host is the root-cause
fix for the throttle/timeout class (parallel fetches tripping per-IP 429s).

Signal-first: the cap only ever wraps an enrichment fetch, never the alert
decision, and a contended acquire waits at most ~one fetch."""
import asyncio

import pytest

from consensus_engine.utils import yahoo_limit


def _force_cap(monkeypatch, n):
    from consensus_engine import config
    real = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: n if k == "yahoo.max_concurrency" else real(k, d),
    )
    yahoo_limit._sem = None
    yahoo_limit._sem_loop = None


async def test_returns_asyncio_semaphore():
    yahoo_limit._sem = None
    yahoo_limit._sem_loop = None
    sem = yahoo_limit.get_yahoo_semaphore()
    assert isinstance(sem, asyncio.Semaphore)


async def test_same_instance_within_one_loop():
    yahoo_limit._sem = None
    yahoo_limit._sem_loop = None
    a = yahoo_limit.get_yahoo_semaphore()
    b = yahoo_limit.get_yahoo_semaphore()
    assert a is b


async def test_semaphore_bounds_concurrency(monkeypatch):
    _force_cap(monkeypatch, 2)
    current = 0
    peak = 0

    async def worker():
        nonlocal current, peak
        async with yahoo_limit.get_yahoo_semaphore():
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.02)
            current -= 1

    await asyncio.gather(*[worker() for _ in range(8)])
    assert peak <= 2, f"concurrency exceeded cap: peak={peak}"


async def test_cap_is_config_driven(monkeypatch):
    _force_cap(monkeypatch, 5)
    sem = yahoo_limit.get_yahoo_semaphore()
    assert sem._value == 5


async def test_cap_floors_at_one(monkeypatch):
    _force_cap(monkeypatch, 0)
    sem = yahoo_limit.get_yahoo_semaphore()
    assert sem._value == 1


async def test_bad_cap_falls_back_to_default(monkeypatch):
    _force_cap(monkeypatch, "not-an-int")
    sem = yahoo_limit.get_yahoo_semaphore()
    assert sem._value == 3
