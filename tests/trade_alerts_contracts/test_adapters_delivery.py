"""M0.4 contracts for history routing, Schwab mapping, and delivery.

These tests use synthetic provider responses and transport objects only.  The
parent build session runs them through its pre-import isolation launcher.
"""

import math
import sys
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

if "trade_alerts_isolation" not in sys.modules:
    pytest.skip("Requires scripts/testing/run_trade_alerts_contracts.py", allow_module_level=True)

import pandas as pd

def _frame():
    return pd.DataFrame({"Open": [1.0], "High": [2.0], "Low": [0.5],
                         "Close": [1.5], "Volume": [10]})


def test_fetch_history_routes_to_yfinance_when_schwab_flag_is_off(monkeypatch):
    from consensus_engine.utils import prices

    calls = {"schwab": 0, "yfinance": 0}
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _frame()

    def fake_schwab(*args, **kwargs):
        calls["schwab"] += 1
        return _frame()

    def fake_factory(ticker):
        calls["yfinance"] += 1
        assert ticker == "SPY"
        return fake_ticker

    monkeypatch.setattr(prices.config, "get", lambda key, default=None: False)
    monkeypatch.setattr("consensus_engine.scanners.schwab_client.get_price_history",
                        fake_schwab)
    monkeypatch.setattr("yfinance.Ticker", fake_factory)

    result = prices.fetch_history("SPY", period="2d", interval="5m", extended_hours=True)

    assert result.equals(_frame())
    assert calls == {"schwab": 0, "yfinance": 1}
    assert fake_ticker.history.call_args.kwargs == {
        "interval": "5m", "prepost": True, "period": "2d",
    }


@pytest.mark.parametrize("schwab_result", [pd.DataFrame(), None])
def test_fetch_history_falls_back_after_empty_schwab(monkeypatch, schwab_result):
    from consensus_engine.utils import prices

    schwab = MagicMock(return_value=schwab_result)
    ticker = MagicMock()
    ticker.history.return_value = _frame()
    monkeypatch.setattr(prices.config, "get", lambda key, default=None: True)
    monkeypatch.setattr("consensus_engine.scanners.schwab_client.get_price_history", schwab)
    monkeypatch.setattr("yfinance.Ticker", lambda ticker_name: ticker)

    result = prices.fetch_history("AAPL", start="2026-01-01", end="2026-01-02")

    assert result.equals(_frame())
    assert schwab.call_count == 1
    assert schwab.call_args.kwargs == {
        "period": None, "interval": "1d", "start": "2026-01-01",
        "end": "2026-01-02", "extended_hours": False,
    }
    assert ticker.history.call_args.kwargs == {
        "interval": "1d", "prepost": False, "start": "2026-01-01",
        "end": "2026-01-02",
    }


def test_fetch_history_uses_only_nonempty_schwab_frame(monkeypatch):
    from consensus_engine.utils import prices

    schwab = MagicMock(return_value=_frame())
    ticker_factory = MagicMock()
    monkeypatch.setattr(prices.config, "get", lambda key, default=None: True)
    monkeypatch.setattr("consensus_engine.scanners.schwab_client.get_price_history", schwab)
    monkeypatch.setattr("yfinance.Ticker", ticker_factory)

    result = prices.fetch_history("QQQ", interval="1m", extended_hours=False)

    assert result.equals(_frame())
    schwab.assert_called_once_with("QQQ", period=None, interval="1m", start=None,
                                  end=None, extended_hours=False)
    ticker_factory.assert_not_called()


def test_fetch_history_exception_falls_back(monkeypatch):
    from consensus_engine.utils import prices
    schwab = MagicMock(side_effect=RuntimeError("synthetic provider failure"))
    ticker = MagicMock()
    ticker.history.return_value = _frame()
    monkeypatch.setattr(prices.config, "get", lambda key, default=None: True)
    monkeypatch.setattr("consensus_engine.scanners.schwab_client.get_price_history", schwab)
    monkeypatch.setattr("yfinance.Ticker", lambda _: ticker)
    assert prices.fetch_history("MSFT").equals(_frame())
    assert schwab.call_count == 1
    ticker.history.assert_called_once()


def test_schwab_quote_mapping_preserves_timestamps_metadata_and_unknown_borrow():
    from consensus_engine.scanners import schwab_client as sc

    mapped = sc._map_quote({
        "quote": {"lastPrice": 99.0, "tradeTime": 1_700_000_001_999,
                   "quoteTime": 1_700_000_002_999, "bidPrice": -999,
                   "askPrice": "bad", "totalVolume": 12},
        "regular": {"regularMarketLastPrice": 100.25,
                     "regularMarketPercentChange": 1.5},
        "reference": {},
    })

    assert mapped["c"] == 100.25
    assert mapped["t"] == 1_700_000_001
    assert mapped["quote_time"] == 1_700_000_002
    assert math.isnan(mapped["bid"]) and math.isnan(mapped["ask"])
    assert mapped["shortable"] is None and mapped["hard_to_borrow"] is None
    assert mapped["htb_rate"] is None


def test_schwab_chain_mapping_keeps_contract_provenance_and_sentinels():
    from consensus_engine.scanners import schwab_client as sc

    contract = {
        "symbol": "XYZ  260101C00100000", "strikePrice": 100,
        "last": -999, "bid": 1.2, "ask": 1.4, "mark": 1.3,
        "bidSize": 7, "askSize": 8, "totalVolume": 11,
        "openInterest": 22, "volatility": 25, "tradeTimeInLong": 1_700_000_000_000,
        "quoteTimeInLong": 1_700_000_001_000, "multiplier": 100,
        "nonStandard": True, "deliverableNote": "cash adjustment",
    }
    row = sc._chain_map_to_df({"2026-01-01:1": {"100": [contract]}}).iloc[0]

    assert math.isnan(row["lastPrice"])
    assert row["impliedVolatility"] == pytest.approx(0.25)
    assert row["providerQuoteTime"] == 1_700_000_001_000
    assert row["multiplier"] == 100
    assert bool(row["nonStandard"]) is True
    assert row["deliverableNote"] == "cash adjustment"
    assert row["lastTradeDate"].astimezone(ZoneInfo("America/Los_Angeles")).strftime(
        "%Y-%m-%d %H:%M:%S") == "2023-11-14 14:13:20"


class _Response:
    def __init__(self, status=200, body=None):
        self.status = status
        self._body = {"id": "msg_1"} if body is None else body
        self.headers = {}

    async def json(self):
        return self._body

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.posts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append((url, headers, json))
        return next(self.responses)


def test_safe_send_kwargs_clips_and_disables_mentions():
    from consensus_engine.alerts import discord
    payload = discord._safe_send_kwargs({"embeds": [{
        "title": "T" * 400, "description": "D" * 5000,
        "fields": [{"name": "N" * 400, "value": "V" * 2000} for _ in range(30)],
    }]})
    embed = payload["embeds"][0]
    assert payload["allowed_mentions"] == {"parse": []}
    assert len(embed["title"]) == 256 and len(embed["description"]) == 4096
    assert len(embed["fields"]) == 25
    assert len(embed["fields"][0]["name"]) == 256
    assert len(embed["fields"][0]["value"]) == 1024


@pytest.mark.asyncio
async def test_safe_send_success_returns_transport_json(monkeypatch):
    from consensus_engine.alerts import discord

    session = _Session([_Response(body={"id": "msg_7"})])
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=session))
    result = await discord._safe_send("https://synthetic.invalid", {}, {"content": "hello"})

    assert result == {"id": "msg_7"}
    assert len(session.posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 204])
async def test_safe_send_failure_returns_none(monkeypatch, status):
    from consensus_engine.alerts import discord
    session = _Session([_Response(status=status)])
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=session))
    assert await discord._safe_send("https://synthetic.invalid", {}, {"content": "x"}) is None


@pytest.mark.asyncio
async def test_safe_send_network_exception_returns_none(monkeypatch):
    from consensus_engine.alerts import discord
    class Broken:
        def post(self, *args, **kwargs):
            raise OSError("synthetic network failure")
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=Broken()))
    assert await discord._safe_send("https://synthetic.invalid", {}, {"content": "x"}) is None


@pytest.mark.asyncio
async def test_send_message_splits_and_returns_last_successful_chunk(monkeypatch):
    from consensus_engine.alerts import discord

    session = _Session([_Response(body={"id": "msg_1"}), _Response(body={"id": "msg_2"})])
    monkeypatch.setattr(discord.cfg, "dry_run", False)
    monkeypatch.setattr(discord.cfg, "get_api_key", lambda _: "synthetic_token")
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=session))
    content = "A" * 2001

    result = await discord.send_message("channel_1", content)

    assert result == "msg_2"
    assert [len(post[2]["content"]) for post in session.posts] == [2000, 1]
    assert all(post[2]["allowed_mentions"] == {"parse": []} for post in session.posts)


@pytest.mark.asyncio
async def test_send_message_dry_run_is_distinct_from_transport_receipt(monkeypatch):
    from consensus_engine.alerts import discord

    transport = AsyncMock()
    monkeypatch.setattr(discord.cfg, "dry_run", True)
    monkeypatch.setattr(discord, "_safe_send", transport)

    result = await discord.send_message("channel_1", "synthetic message")

    assert result == "dry_run_msg_id"
    transport.assert_not_awaited()


def test_quote_explicit_false_and_extended_last(monkeypatch):
    from consensus_engine.scanners import schwab_client as sc
    out = sc._map_quote({"quote": {"lastPrice": 99}, "regular": {},
                         "reference": {"isShortable": False, "isHardToBorrow": False}})
    assert out["c"] == 99
    assert out["shortable"] is False and out["hard_to_borrow"] is False


def test_chain_missing_optional_fields(monkeypatch):
    from consensus_engine.scanners import schwab_client as sc
    row = sc._chain_map_to_df({"2026-01-01:1": {"100": [{"symbol": "X"}]}}).iloc[0]
    assert row["providerQuoteTime"] == 0 and math.isnan(row["multiplier"])
    assert math.isnan(row["delta"]) and pd.isna(row["lastTradeDate"])


def test_get_option_chain_preserves_delayed_flag(monkeypatch):
    from consensus_engine.scanners import schwab_client as sc
    def fake_get(path, params=None):
        return {"status": "SUCCESS", "numberOfContracts": 1, "underlyingPrice": 100,
                "isDelayed": True, "callExpDateMap": {"2026-01-01:1": {"100": [{"symbol": "X"}]}},
                "putExpDateMap": {}}
    monkeypatch.setattr(sc, "_get", fake_get)
    assert sc.get_option_chain("X", to_date="2026-01-01").is_delayed is True


@pytest.mark.asyncio
async def test_safe_send_empty_json_and_400_fallback(monkeypatch):
    from consensus_engine.alerts import discord
    session = _Session([_Response(status=400), _Response(body={})])
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=session))
    out = await discord._safe_send("https://synthetic.invalid", {}, {"embeds": [{"description": "text"}]})
    assert out == {}
    assert session.posts[1][2]["content"] == "text"


@pytest.mark.asyncio
async def test_safe_send_429_retries(monkeypatch):
    from consensus_engine.alerts import discord
    session = _Session([_Response(status=429), _Response(body={"id": "retry"})])
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=session))
    monkeypatch.setattr(discord.asyncio, "sleep", AsyncMock())
    assert await discord._safe_send("https://synthetic.invalid", {}, {"content": "x"}) == {"id": "retry"}


@pytest.mark.asyncio
async def test_send_message_empty_or_missing_token_returns_none(monkeypatch):
    from consensus_engine.alerts import discord
    monkeypatch.setattr(discord.cfg, "dry_run", False)
    monkeypatch.setattr(discord.cfg, "get_api_key", lambda _: None)
    assert await discord.send_message("channel_1", "hello") is None
    assert await discord.send_message("channel_1", "") is None


@pytest.mark.asyncio
async def test_send_message_later_chunk_failure_keeps_prior_id(monkeypatch):
    from consensus_engine.alerts import discord
    session = _Session([_Response(body={"id": "msg_1"}), _Response(status=500)])
    monkeypatch.setattr(discord.cfg, "dry_run", False)
    monkeypatch.setattr(discord.cfg, "get_api_key", lambda _: "synthetic_token")
    monkeypatch.setattr(discord, "get_session", AsyncMock(return_value=session))
    assert await discord.send_message("channel_1", "A" * 2001) == "msg_1"
