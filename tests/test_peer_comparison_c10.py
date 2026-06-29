"""C10 (reliability-hardening): the 12s wait_for ceiling silently dropped the
relative-strength field whenever peer yfinance calls were throttled. Raise it to
config (features.peer_comparison.timeout_s, default 22) and route peer fetches
through the shared C20 Yahoo semaphore so they're bounded with the rest.

(.info sector/industry is already DB-cached and stable, so its front-load is a
one-time-per-ticker cost — no concurrency restructure needed.)"""
import asyncio

import pytest

from consensus_engine.analysis import peer_comparison as pc
from consensus_engine.utils import yahoo_limit


def _enable(monkeypatch, timeout_s):
    real = pc.cfg.get
    cfgmap = {
        "features.peer_comparison.enabled": True,
        "features.peer_comparison.timeout_s": timeout_s,
    }
    monkeypatch.setattr(pc.cfg, "get", lambda k, d=None: cfgmap.get(k, real(k, d)))


async def test_short_timeout_drops(monkeypatch):
    _enable(monkeypatch, 0.05)

    async def slow(*a, **k):
        await asyncio.sleep(0.4)
        return {"verdict": "outperforming"}

    monkeypatch.setattr(pc, "_compute", slow)
    out = await pc.compute_relative_strength("AAPL")
    assert out is None, "a compute slower than the ceiling must time out -> None"


async def test_generous_timeout_keeps_result(monkeypatch):
    _enable(monkeypatch, 5)

    async def slow(*a, **k):
        await asyncio.sleep(0.05)
        return {"verdict": "outperforming"}

    monkeypatch.setattr(pc, "_compute", slow)
    out = await pc.compute_relative_strength("AAPL")
    assert out == {"verdict": "outperforming"}, \
        "a compute within the raised ceiling must NOT be dropped (the C10 fix)"


async def test_default_ceiling_is_raised_above_12(monkeypatch):
    """The old hard-coded ceiling was 12s; the default must now be >12."""
    real = pc.cfg.get
    captured = {}

    def spy(k, d=None):
        if k == "features.peer_comparison.timeout_s":
            captured["default"] = d
        if k == "features.peer_comparison.enabled":
            return True
        return real(k, d)

    monkeypatch.setattr(pc.cfg, "get", spy)

    async def quick(*a, **k):
        return None

    monkeypatch.setattr(pc, "_compute", quick)
    await pc.compute_relative_strength("AAPL")
    assert captured.get("default", 0) > 12, \
        f"default ceiling must be raised above the old 12s, got {captured.get('default')}"


async def test_gather_pct_uses_yahoo_semaphore(monkeypatch):
    entered = []

    class _TS:
        def __init__(self, inner):
            self._inner = inner

        async def __aenter__(self):
            entered.append(1)
            return await self._inner.__aenter__()

        async def __aexit__(self, *a):
            return await self._inner.__aexit__(*a)

    yahoo_limit._sem = None
    yahoo_limit._sem_loop = None
    real = yahoo_limit.get_yahoo_semaphore
    monkeypatch.setattr(pc, "get_yahoo_semaphore", lambda: _TS(real()))
    monkeypatch.setattr(pc, "_pct_change", lambda t, w: 1.23)  # no network

    out = await pc._gather_pct(["AAPL", "MSFT"], 5)
    assert out == {"AAPL": 1.23, "MSFT": 1.23}
    assert len(entered) == 2, "each peer fetch must pass through the Yahoo semaphore"
