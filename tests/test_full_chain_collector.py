from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pandas as pd
import pytest

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


def test_select_contracts_limits_strikes_and_nearest_expirations():
    rows = []
    for expiry in ("2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25", "2026-10-02"):
        for strike in (80, 90, 100, 110, 120):
            for side in ("C", "P"):
                raw = f"AAPL  {expiry[2:].replace('-', '')}{side}{strike * 1000:08d}"
                rows.append({"raw_symbol": raw, "expiration": expiry,
                             "strike_price": strike})
    frame = pd.DataFrame(rows)
    selected = collector.select_contracts(
        frame, {"AAPL": 100.0}, date(2026, 8, 31), 0.15, 4,
    )
    assert set(selected["strike_price"]) == {90, 100, 110}
    assert selected["expiration"].dt.date.nunique() == 4
    assert len(selected) == 3 * 2 * 4


def test_spx_weekly_root_is_joined_to_spx_underlying():
    assert collector._parent_from_raw_symbol("SPXW  260831P06000000") == "SPX"


def test_stock_poll_saves_quote_sizes_and_borrow_facts(tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    cfg["universe"]["trade_names"] = ["AAPL"]
    cfg["universe"]["stock_context"] = ["SPY"]
    monkeypatch.setattr(collector, "stock_poll_allowed", lambda now: True)
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


def test_merge_option_rows_keeps_last_quote_sizes_volume_and_contract_facts():
    cbbo = pd.DataFrame([{ "ts_recv": "2026-08-31T13:31:00Z",
                           "symbol": "AAPL  260904C00100000", "price": 2.5,
                           "bid_px_00": 2.4, "ask_px_00": 2.6,
                           "bid_sz_00": 10, "ask_sz_00": 11}])
    bars = pd.DataFrame([{ "ts_event": "2026-08-31T13:31:00Z",
                          "symbol": "AAPL  260904C00100000", "open": 2.4,
                          "high": 2.7, "low": 2.3, "close": 2.5, "volume": 22}])
    definitions = pd.DataFrame([{ "raw_symbol": "AAPL  260904C00100000",
                                  "ticker": "AAPL", "expiration": "2026-09-04",
                                  "strike_price": 100.0}])
    merged = collector._merge_option_frames(cbbo, bars, definitions)
    row = merged.iloc[0]
    assert row["price"] == 2.5
    assert row["bid_sz_00"] == 10 and row["ask_sz_00"] == 11
    assert row["volume"] == 22
    assert row["ticker"] == "AAPL" and row["option_type"] == "C"


def test_option_download_refuses_a_request_above_the_daily_cost_limit():
    class Metadata:
        @staticmethod
        def get_cost(**kwargs):
            return 2.01

    class Client:
        metadata = Metadata()

    with pytest.raises(RuntimeError, match="above the \\$2.00 daily limit"):
        collector._download_frames(
            Client(), "OPRA.PILLAR", ["AAPL  260904C00100000"],
            "cbbo-1m", "2026-08-31T13:30:00Z", "2026-08-31T20:01:00Z", 2.00,
        )


def test_verify_day_requires_real_option_and_open_interest_rows(tmp_path):
    cfg = settings(tmp_path)
    day = date(2026, 8, 31)
    report = collector.verify_day(cfg, day)
    assert report["passed"] is False
    assert report["checks"]["option_chain_exists"] is False
    assert report["checks"]["open_interest_exists"] is False
