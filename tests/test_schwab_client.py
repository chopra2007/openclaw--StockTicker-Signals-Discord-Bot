"""Unit tests for the Schwab market-data client (TODO #57).

Deterministic — no network. HTTP is mocked by monkeypatching `_get`. Canned
responses mirror the real Schwab field names captured from the live probe. Guards
the load-bearing conversions (IV ÷100, epoch-ms → NY tz, quote mapping, the
7-day re-auth wall) that a silent bug would make 100x-wrong.
"""
import json
import math
import time

import pandas as pd
import pytest

from consensus_engine.scanners import schwab_client as sc


# --- pure helpers ----------------------------------------------------------
def test_iv_from_pct():
    assert sc._iv_from_pct(34.066) == pytest.approx(0.34066)
    assert math.isnan(sc._iv_from_pct(-999.0))   # Schwab 'no data' sentinel
    assert math.isnan(sc._iv_from_pct(0))
    assert math.isnan(sc._iv_from_pct(None))


def test_num_sanitizes():
    assert sc._num(100.5) == 100.5
    assert math.isnan(sc._num(-999.0))           # sentinel
    assert math.isnan(sc._num(1e300))            # glitch tick → NaN (overflow guard)
    assert math.isnan(sc._num(float("inf")))
    assert math.isnan(sc._num("not-a-number"))


def test_to_schwab_symbol():
    assert sc.to_schwab_symbol("AAPL") == "AAPL"
    assert sc.to_schwab_symbol("^VIX") == "$VIX"       # index symbology
    assert sc.to_schwab_symbol("^VIX3M") == "$VIX3M"
    assert sc.to_schwab_symbol("BRK.B") == "BRK/B"     # dotted class shares


def test_period_to_calendar_days():
    assert sc._period_to_calendar_days("2d") == 7      # N + weekend pad
    assert sc._period_to_calendar_days("15d") == 20
    assert sc._period_to_calendar_days("2y") == 740
    assert sc._period_to_calendar_days(None) == 40


# --- quote mapping ---------------------------------------------------------
def test_map_quote_uses_regular_last_and_ms_to_sec():
    entry = {
        "quote": {"lastPrice": 289.0, "closePrice": 281.74, "netPercentChange": 2.57,
                  "openPrice": 281.17, "highPrice": 289.94, "lowPrice": 280.695,
                  "totalVolume": 65100155, "quoteTime": 1782863991793,
                  "tradeTime": 1782863991793},
        "regular": {"regularMarketLastPrice": 289.36, "regularMarketPercentChange": 2.70},
    }
    q = sc._map_quote(entry)
    assert q["c"] == 289.36               # regularMarketLastPrice, not the AH lastPrice
    assert q["pc"] == 281.74
    assert q["dp"] == pytest.approx(2.70)
    assert q["v"] == 65100155             # Finnhub free tier always left this 0
    assert q["t"] == 1782863991           # epoch-ms → epoch-seconds


# --- chain mapping ---------------------------------------------------------
_SAMPLE_CONTRACT = {
    "symbol": "AAPL  260701C00285000", "strikePrice": 285.0, "last": 4.85,
    "bid": 4.5, "ask": 5.0, "totalVolume": 39590, "openInterest": 3923,
    "volatility": 34.066, "tradeTimeInLong": 1782849591734, "putCall": "CALL",
    "delta": 0.814, "gamma": 0.057, "theta": -0.427, "vega": 0.039, "rho": 0.005,
}


def test_chain_map_to_df_columns_and_conversions():
    exp_map = {"2026-07-01:1": {"285.0": [_SAMPLE_CONTRACT]}}
    df = sc._chain_map_to_df(exp_map)
    assert len(df) == 1
    row = df.iloc[0]
    # yfinance column names the scanner reads:
    for col in ("contractSymbol", "strike", "lastPrice", "bid", "ask", "volume",
                "openInterest", "impliedVolatility", "lastTradeDate", "expiry"):
        assert col in df.columns
    assert row["strike"] == 285.0
    assert row["volume"] == 39590
    assert row["impliedVolatility"] == pytest.approx(0.34066)   # ÷100, not 34
    assert row["expiry"] == "2026-07-01"
    # lastTradeDate: epoch-ms → tz-aware America/New_York
    assert isinstance(row["lastTradeDate"], pd.Timestamp)
    assert str(row["lastTradeDate"].tz) == "America/New_York"


def test_chain_map_to_df_empty():
    df = sc._chain_map_to_df({})
    assert df.empty
    assert "impliedVolatility" in df.columns   # still typed columns


def test_get_option_chain_and_by_expiry(monkeypatch):
    canned = {
        "status": "SUCCESS", "underlyingPrice": 289.36, "isDelayed": False,
        "numberOfContracts": 2,
        "callExpDateMap": {"2026-07-01:1": {"285.0": [dict(_SAMPLE_CONTRACT)]}},
        "putExpDateMap": {"2026-07-01:1": {"285.0": [dict(_SAMPLE_CONTRACT, putCall="PUT")]}},
    }
    monkeypatch.setattr(sc, "_get", lambda path, params=None: canned)
    # nearest resolution also calls _get(/expirationchain) — our stub returns the
    # chain dict for any path, so pass an explicit to_date to avoid that branch.
    ch = sc.get_option_chain("AAPL", to_date="2026-07-01")
    assert ch is not None
    assert ch.underlying_price == 289.36
    assert ch.is_delayed is False
    assert not ch.calls.empty and not ch.puts.empty
    be = ch.by_expiry("2026-07-01")
    assert len(be.calls) == 1 and len(be.puts) == 1


def test_get_option_chain_empty_returns_none(monkeypatch):
    monkeypatch.setattr(sc, "_get", lambda path, params=None: {"status": "SUCCESS", "numberOfContracts": 0})
    assert sc.get_option_chain("AAPL", to_date="2026-07-01") is None


def test_get_price_history_reshape(monkeypatch):
    candles = [
        {"open": 311.7, "high": 315.0, "low": 309.5, "close": 312.0, "volume": 70026752, "datetime": 1780030800000},
        {"open": 286.7, "high": 288.3, "low": 279.8, "close": 281.7, "volume": 66427002, "datetime": 1782709200000},
    ]
    monkeypatch.setattr(sc, "_get", lambda path, params=None: {"candles": candles, "empty": False, "symbol": "AAPL"})
    df = sc.get_price_history("AAPL", period="1mo", interval="1d")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert str(df.index.tz) == "America/New_York"
    # 1780030800000 ms = 2026-05-29 05:00 UTC = 2026-05-29 in ET (off-by-one guard)
    assert df.index[0].date().isoformat() == "2026-05-29"


def test_get_quote_maps(monkeypatch):
    entry = {"quote": {"lastPrice": 289.0, "closePrice": 281.74, "totalVolume": 65100155,
                       "quoteTime": 1782863991793, "openPrice": 281.17,
                       "highPrice": 289.94, "lowPrice": 280.695, "netPercentChange": 2.57},
             "regular": {"regularMarketLastPrice": 289.36, "regularMarketPercentChange": 2.70}}
    monkeypatch.setattr(sc, "_get", lambda path, params=None: {"AAPL": entry})
    q = sc.get_quote("AAPL")
    assert q["c"] == 289.36 and q["v"] == 65100155


# --- token / re-auth math --------------------------------------------------
def test_needs_refresh_and_reauth_days(monkeypatch):
    now = time.time()
    # fresh access token, login 1 day ago
    doc = {"creation_timestamp": now, "_refresh_created": now - 86400,
           "token": {"access_token": "abc", "expires_in": 1800, "refresh_token": "r"}}
    monkeypatch.setattr(sc, "_load_token", lambda: doc)
    assert sc._needs_refresh(doc) is False
    assert sc.reauth_days_left() == pytest.approx(6.0, abs=0.05)   # 7 - 1
    # stale access token (created 31 min ago) → needs refresh
    stale = dict(doc, creation_timestamp=now - 1900)
    assert sc._needs_refresh(stale) is True


def test_reauth_expired_detection(monkeypatch):
    now = time.time()
    doc = {"creation_timestamp": now, "_refresh_created": now - 8 * 86400,
           "token": {"access_token": "abc", "expires_in": 1800, "refresh_token": "r"}}
    monkeypatch.setattr(sc, "_load_token", lambda: doc)
    assert sc.reauth_days_left() < 0   # past the 7-day wall
