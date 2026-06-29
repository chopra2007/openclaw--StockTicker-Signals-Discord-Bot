"""Phase 5 correctness fixes:

C12 (options staleness): _ts_to_epoch returns 0.0 on an unparseable
lastTradeDate, and the guard `if max_stale_sec and lt and ...` then treats 0.0
as falsy and SKIPS the staleness check -> a contract with no verifiable
timestamp could fire an instant alert silently. The contract already passed the
vol/premium/ratio gates (real activity), so we never DROP it (that would lose a
real signal); when options_flow.staleness_failclosed is on we TAG it
"[staleness unverified]" (in the alert) and log it. Flag OFF = unchanged.

C19 (social): _has_market_cap fell open (return True) on an exception, letting
an unvalidated ticker through. validate_ticker_market_cap itself fails closed,
so the wrapper *can* too -- but because a flip to fail-closed can drop a
corroborating social source on a transient error, it is flag-gated
(social.market_cap_failclosed, default OFF). Flag OFF = unchanged fail-open.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from consensus_engine import config
from consensus_engine.scanners import options
from consensus_engine.models import FlowHit


def _flag(monkeypatch, on):
    real = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: on if k == "options_flow.staleness_failclosed" else real(k, d))


def _qualifying_chain(last_trade_date):
    """One CALL that clears every gate (vol 1000, oi 100 -> 10x, premium 500k)
    with a caller-supplied lastTradeDate (None -> unparseable -> lt=0.0)."""
    calls = pd.DataFrame([{
        "contractSymbol": "C_A", "strike": 100.0, "volume": 1000.0,
        "openInterest": 100.0, "lastPrice": 5.0, "lastTradeDate": last_trade_date,
    }])
    return SimpleNamespace(calls=calls, puts=pd.DataFrame())


def _scan(chain, now):
    return options._scan_chain_for_flow(
        "AAPL", chain, "2026-07-03", 99.0,
        min_vol_oi=5.0, min_volume=500, min_premium=250_000.0,
        max_stale_sec=3600, now=now,
    )


def test_c12_flag_off_unparseable_allowed_untagged(monkeypatch):
    _flag(monkeypatch, False)
    hits = _scan(_qualifying_chain(None), now=1_700_000_000.0)
    assert len(hits) == 1, "flag OFF: unparseable timestamp must still be allowed (unchanged)"
    assert hits[0].staleness_unverified is False


def test_c12_flag_on_unparseable_allowed_but_tagged(monkeypatch, caplog):
    _flag(monkeypatch, True)
    with caplog.at_level("WARNING"):
        hits = _scan(_qualifying_chain(None), now=1_700_000_000.0)
    assert len(hits) == 1, "a real qualifying contract must NOT be dropped (north-star)"
    assert hits[0].staleness_unverified is True
    assert any("staleness unverified" in r.message.lower() for r in caplog.records)


def test_c12_genuinely_stale_still_dropped(monkeypatch):
    """A parseable but OLD timestamp is dropped exactly as before, flag or not."""
    _flag(monkeypatch, True)
    old = pd.Timestamp("2026-06-20 00:00:00", tz="UTC")
    now = pd.Timestamp("2026-06-27 00:00:00", tz="UTC").timestamp()  # a week later
    hits = _scan(_qualifying_chain(old), now=now)
    assert hits == [], "a genuinely stale contract must still be dropped"


def test_c12_alert_shows_unverified_tag():
    hit = FlowHit(ticker="AAPL", side="CALL", strike=100.0, expiry="2026-07-03",
                  volume=1000, open_interest=100, vol_oi_ratio=10.0,
                  premium_usd=500_000.0, last_trade_ts=0.0, spot=99.0,
                  contract_symbol="C_A", staleness_unverified=True)
    text = options.format_flow_alert(hit)
    assert "staleness unverified" in text.lower()


def _mc_flag(monkeypatch, on):
    real = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: on if k == "social.market_cap_failclosed" else real(k, d))


async def test_c19_flag_on_fails_closed_on_error(monkeypatch):
    """Flag ON: a validation error treats the ticker as not-a-real-stock."""
    from consensus_engine.scanners import social
    _mc_flag(monkeypatch, True)
    monkeypatch.setattr("consensus_engine.utils.tickers.validate_ticker_market_cap",
                        AsyncMock(side_effect=RuntimeError("finnhub down")))
    assert await social._has_market_cap("XYZ") is False, "flag ON must fail CLOSED on error"


async def test_c19_flag_off_fails_open_on_error(monkeypatch):
    """Flag OFF (default): unchanged -- a transient error must NOT drop the ticker."""
    from consensus_engine.scanners import social
    _mc_flag(monkeypatch, False)
    monkeypatch.setattr("consensus_engine.utils.tickers.validate_ticker_market_cap",
                        AsyncMock(side_effect=RuntimeError("finnhub down")))
    assert await social._has_market_cap("XYZ") is True, "flag OFF must fail OPEN (unchanged)"


async def test_c19_has_market_cap_passes_valid(monkeypatch):
    from consensus_engine.scanners import social
    monkeypatch.setattr("consensus_engine.utils.tickers.validate_ticker_market_cap",
                        AsyncMock(return_value=True))
    assert await social._has_market_cap("AAPL") is True
