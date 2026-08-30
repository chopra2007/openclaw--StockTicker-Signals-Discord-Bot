from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.full_chain_collector as collector


def settings(tmp_path: Path) -> dict:
    result = collector.load_settings()
    result["capture"]["data_root"] = str(tmp_path)
    return result


def test_universe_is_twenty_trade_names_plus_separate_context(tmp_path):
    cfg = settings(tmp_path)
    trade = cfg["universe"]["trade_names"]
    assert len(trade) == 20
    assert len(set(trade)) == 20
    assert "SPY" not in trade and "QQQ" not in trade
    assert collector.universe(cfg, "options")[-3:] == ["SPY", "QQQ", "SPX"]
    assert collector.universe(cfg, "stocks")[-5:] == ["SPY", "QQQ", "XLK", "SMH", "SPX"]


def test_stock_poll_window_uses_pacific_calendar():
    saturday = datetime(2026, 8, 29, 18, 0, tzinfo=timezone.utc)
    monday_open_window = datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    monday_too_late = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)
    assert collector.stock_poll_allowed(saturday) is False
    assert collector.stock_poll_allowed(monday_open_window) is True
    assert collector.stock_poll_allowed(monday_too_late) is False


def test_stock_poll_saves_quote_sizes_and_borrow_facts(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    cfg["universe"]["trade_names"] = ["AAPL"]
    cfg["universe"]["stock_context"] = ["SPY"]
    monkeypatch.setattr(collector, "stock_poll_allowed", lambda now: True)
    monkeypatch.setattr(collector, "option_poll_allowed", lambda now: False)
    monkeypatch.setattr(
        collector.schwab_client,
        "get_quotes",
        lambda symbols: {
            symbol: {"c": 100, "bid": 99.9, "ask": 100.1, "bid_size": 8,
                     "ask_size": 6, "quote_time": 1, "t": 1, "o": 98,
                     "h": 101, "l": 97, "v": 1000, "halt_status": "normal",
                     "shortable": True, "hard_to_borrow": False, "htb_rate": 0}
            for symbol in symbols
        },
    )
    result = collector.capture_stock_poll(
        cfg, datetime(2026, 8, 31, 18, 1, tzinfo=timezone.utc),
    )
    saved = pd.read_parquet(result["path"])
    assert result["written"] == 3
    assert set(saved["ticker"]) == {"AAPL", "SPY", "SPX"}
    assert saved["bid_size"].tolist() == [8.0, 8.0, 8.0]
    assert saved["shortable"].all()


def _chain() -> collector.schwab_client.Chain:
    contracts = pd.DataFrame([
        {"contractSymbol": "AAPL  260904C00100000", "strike": 100.0,
         "lastPrice": 2.5, "bid": 2.4, "ask": 2.6, "mark": 2.5,
         "bidSize": 10, "askSize": 11, "volume": 22, "openInterest": 50,
         "impliedVolatility": 0.3, "providerQuoteTime": 1_788_200_000_000,
         "lastTradeDate": pd.Timestamp("2026-08-31T18:00:00Z"),
         "expiry": "2026-09-04", "multiplier": 100, "nonStandard": False,
         "deliverableNote": "", "delta": .5, "gamma": .1, "theta": -.1,
         "vega": .2, "rho": .01},
        {"contractSymbol": "AAPL  260904C00120000", "strike": 120.0,
         "lastPrice": 0.1, "bid": 0.05, "ask": 0.15, "mark": 0.1,
         "bidSize": 2, "askSize": 3, "volume": 1, "openInterest": 5,
         "impliedVolatility": .4, "providerQuoteTime": 1_788_200_000_000,
         "lastTradeDate": pd.NaT, "expiry": "2026-09-04", "multiplier": 100,
         "nonStandard": False, "deliverableNote": "", "delta": .1,
         "gamma": .01, "theta": -.01, "vega": .02, "rho": .001},
    ])
    return collector.schwab_client.Chain(
        calls=contracts, puts=contracts.iloc[0:0], underlying_price=100.0,
        is_delayed=False, expirations=["2026-09-04"],
    )


def test_schwab_option_poll_filters_band_and_saves_full_quote(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    cfg["universe"]["trade_names"] = ["AAPL"]
    cfg["universe"]["option_context"] = []
    cfg["universe"]["collect_spx_forward"] = False
    monkeypatch.setattr(collector, "option_poll_allowed", lambda now: True)
    seen = {}

    def get_chain(ticker, **kwargs):
        seen.update(kwargs)
        return _chain()

    monkeypatch.setattr(collector.schwab_client, "get_option_chain", get_chain)
    result = collector.capture_option_poll(
        cfg, datetime(2026, 8, 31, 18, 1, tzinfo=timezone.utc),
        {"AAPL": {"c": 100, "bid": 99.9, "ask": 100.1}},
    )
    saved = pd.read_parquet(result["path"])
    assert result["rows_written"] == 1
    assert saved.iloc[0]["contract_symbol"] == "AAPL  260904C00100000"
    assert saved.iloc[0]["bid_size"] == 10
    assert saved.iloc[0]["underlying_bid"] == 99.9
    assert seen == {"nearest": 4, "strike_count": 500}


def test_daily_compaction_creates_chain_and_open_interest_files(tmp_path):
    cfg = settings(tmp_path)
    day = date(2026, 8, 31)
    captured = datetime(2026, 8, 31, 18, 1, tzinfo=timezone.utc)
    rows = collector._option_rows(
        "AAPL", _chain(), {"c": 100, "bid": 99.9, "ask": 100.1}, captured, .15,
    )
    collector._atomic_write_parquet(rows, collector._option_part_path(cfg, captured))
    result = collector.compact_option_day(cfg, day)
    assert result == {"minute_files": 1, "option_rows": 1, "open_interest_rows": 1}
    assert collector._day_path(cfg, "option_chains", day).exists()
    assert collector._day_path(cfg, "open_interest", day).exists()


def test_verify_day_requires_real_option_and_open_interest_rows(tmp_path):
    cfg = settings(tmp_path)
    day = date(2026, 8, 31)
    report = collector.verify_day(cfg, day)
    assert report["passed"] is False
    assert report["checks"]["option_chain_exists"] is False
    assert report["checks"]["open_interest_exists"] is False
