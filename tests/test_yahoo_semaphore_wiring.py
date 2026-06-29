"""C20 wiring: every yfinance fetch in options.py must run inside the shared
Yahoo semaphore so the process-wide cap actually bounds concurrent Yahoo hits.
Uses a fake `yfinance` module so the executor fetch returns instantly with no
network, and a tracking wrapper to confirm the semaphore was entered."""
import asyncio
import sys
import types

import pytest

from consensus_engine.scanners import options
from consensus_engine.utils import yahoo_limit


class _TrackingSem:
    def __init__(self, inner, log):
        self._inner = inner
        self._log = log

    async def __aenter__(self):
        self._log.append("enter")
        return await self._inner.__aenter__()

    async def __aexit__(self, *a):
        return await self._inner.__aexit__(*a)


def _install_fake_yfinance(monkeypatch):
    """A yfinance whose Ticker has no expirations -> every fetch returns fast."""
    fake = types.SimpleNamespace(
        Ticker=lambda t: types.SimpleNamespace(options=[], fast_info=None)
    )
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def _track_semaphore(monkeypatch):
    log = []
    yahoo_limit._sem = None
    yahoo_limit._sem_loop = None
    real = yahoo_limit.get_yahoo_semaphore
    monkeypatch.setattr(options, "get_yahoo_semaphore", lambda: _TrackingSem(real(), log))
    return log


async def test_check_unusual_options_acquires_semaphore(monkeypatch):
    _install_fake_yfinance(monkeypatch)
    log = _track_semaphore(monkeypatch)
    await options.check_unusual_options("AAPL", None)
    assert "enter" in log


async def test_fetch_flow_chains_acquires_semaphore(monkeypatch):
    _install_fake_yfinance(monkeypatch)
    log = _track_semaphore(monkeypatch)
    await options._fetch_flow_chains("AAPL", None, 2)
    assert "enter" in log


async def test_compute_max_pain_acquires_semaphore(monkeypatch):
    _install_fake_yfinance(monkeypatch)
    log = _track_semaphore(monkeypatch)
    await options.compute_max_pain("AAPL", None)
    assert "enter" in log
