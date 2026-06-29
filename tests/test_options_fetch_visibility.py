"""C13 (reliability-hardening): a Yahoo option-chain fetch outage must be
visible. The old `except Exception: pass` made an all-expiries-failed fetch
look identical to a clean "no unusual flow" result. Now: count fetch failures
and emit ONE systemic WARNING per ticker when every attempted chain fetch
failed. Behavior (returned data) is unchanged — observability only."""
import sys
import types

import pytest

from consensus_engine.scanners import options


class _AllFailTicker:
    """yfinance Ticker whose option_chain always raises (simulates a 429/outage)."""
    fast_info = None

    def __init__(self, expirations):
        self.options = expirations

    def option_chain(self, e):
        raise RuntimeError("yahoo throttled (429)")


def _install(monkeypatch, expirations):
    monkeypatch.setitem(
        sys.modules, "yfinance",
        types.SimpleNamespace(Ticker=lambda t: _AllFailTicker(expirations)),
    )
    options._fetch_failure_count = 0


async def test_flow_fetch_all_failed_logs_systemic_warning(monkeypatch, caplog):
    _install(monkeypatch, ["2026-07-03", "2026-07-10"])
    with caplog.at_level("WARNING"):
        spot, chains = await options._fetch_flow_chains("AAPL", None, 2)
    # behavior unchanged: no chains returned
    assert chains == []
    # both attempted expiries counted as failures
    assert options._fetch_failure_count == 2
    # exactly one systemic warning, naming the ticker and "ALL"
    systemic = [r for r in caplog.records
                if r.levelname == "WARNING" and "ALL" in r.message and "AAPL" in r.message]
    assert len(systemic) == 1, f"expected 1 systemic WARNING, got {len(systemic)}"


async def test_check_unusual_all_failed_logs_warning(monkeypatch, caplog):
    _install(monkeypatch, ["2026-07-03"])
    with caplog.at_level("WARNING"):
        res = await options.check_unusual_options("AAPL", None)
    assert res is None  # behavior unchanged
    assert options._fetch_failure_count == 1
    assert any("ALL" in r.message and "AAPL" in r.message
               for r in caplog.records if r.levelname == "WARNING")


async def test_no_warning_when_no_expirations(monkeypatch, caplog):
    """A ticker with no listed options is 'genuinely no flow', NOT an outage —
    it must not emit a fetch-failure warning."""
    _install(monkeypatch, [])
    with caplog.at_level("WARNING"):
        spot, chains = await options._fetch_flow_chains("XYZ", None, 2)
    assert chains == []
    assert options._fetch_failure_count == 0
    assert not any("ALL" in r.message for r in caplog.records)
