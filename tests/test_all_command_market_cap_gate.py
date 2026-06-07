"""#1 (full-audit-2026-06-06) — fake/penny ticker gate on !all.

When `all_command.market_cap_gate_enabled` is ON, `handle_all` runs
`validate_ticker_market_cap(ticker)` after the format check and, on False,
replies with a one-line rejection and skips the whole pipeline. Common index
ETFs (SPY/QQQ/IWM/DIA) are whitelisted so a 0-market-cap ETF profile isn't
rejected. Default OFF → no gate, pipeline runs as before.

Asserts:
  * flag OFF → gate never calls validate_ticker_market_cap; pipeline runs
  * flag ON + low-cap (False) → rejection reply, pipeline NOT run
  * flag ON + valid (True) → pipeline runs
  * flag ON + whitelisted ETF → pipeline runs without validation call
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from consensus_engine import config as cfg
from consensus_engine.alerts.all_command import aggregator


def _flag_cfg(enabled: bool):
    real_get = cfg.get

    def fake_get(key, default=None):
        if key == "all_command.market_cap_gate_enabled":
            return enabled
        return real_get(key, default)

    return patch("consensus_engine.config.get", side_effect=fake_get)


@pytest.fixture
def captured(monkeypatch):
    """Capture replies + count whether the pipeline (single-flight) ran."""
    state: dict = {"replies": [], "compute_calls": 0}

    async def _reply(channel_id, msg_id, content):
        state["replies"].append(content)
        return "rid"

    async def _single_flight(ticker, compute_fn):
        state["compute_calls"] += 1
        # Return a malformed payload so handle_all bails after gather without
        # touching real Discord/vault — we only care that it was REACHED.
        return {"_stub": True}

    monkeypatch.setattr(aggregator, "send_command_reply", _reply)
    monkeypatch.setattr(aggregator.cache, "all_with_single_flight", _single_flight)
    return state


@pytest.mark.asyncio
async def test_flag_off_skips_gate_and_runs_pipeline(captured):
    """Default-OFF: validate_ticker_market_cap is never called; pipeline runs."""
    vcap = AsyncMock(return_value=False)  # would reject if called
    with _flag_cfg(False), patch.object(aggregator, "validate_ticker_market_cap", vcap):
        await aggregator.handle_all("NVDA", "ch", "msg")
    vcap.assert_not_called()
    assert captured["compute_calls"] == 1
    assert all("isn't a tracked stock" not in r for r in captured["replies"])


@pytest.mark.asyncio
async def test_flag_on_rejects_low_cap(captured):
    """Flag ON + validate returns False → rejection reply, pipeline NOT run."""
    vcap = AsyncMock(return_value=False)
    with _flag_cfg(True), patch.object(aggregator, "validate_ticker_market_cap", vcap):
        await aggregator.handle_all("TINY", "ch", "msg")
    vcap.assert_awaited_once()
    assert captured["compute_calls"] == 0, "pipeline must be skipped on reject"
    assert any("isn't a tracked stock" in r for r in captured["replies"])


@pytest.mark.asyncio
async def test_flag_on_allows_valid(captured):
    """Flag ON + validate returns True → pipeline runs, no rejection."""
    vcap = AsyncMock(return_value=True)
    with _flag_cfg(True), patch.object(aggregator, "validate_ticker_market_cap", vcap):
        await aggregator.handle_all("AAPL", "ch", "msg")
    vcap.assert_awaited_once()
    assert captured["compute_calls"] == 1
    assert all("isn't a tracked stock" not in r for r in captured["replies"])


@pytest.mark.asyncio
async def test_flag_on_whitelists_index_etf(captured):
    """Flag ON + whitelisted ETF (SPY) → pipeline runs, validation skipped."""
    vcap = AsyncMock(return_value=False)  # would reject SPY's 0-cap profile
    with _flag_cfg(True), patch.object(aggregator, "validate_ticker_market_cap", vcap):
        await aggregator.handle_all("SPY", "ch", "msg")
    vcap.assert_not_called()
    assert captured["compute_calls"] == 1
