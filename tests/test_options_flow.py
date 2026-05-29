"""#18: near-real-time unusual options flow — detection, staleness, persistence, cooldown."""
import time, tempfile, os
import types
import pandas as pd
import pytest

from consensus_engine.scanners.options import (
    _scan_chain_for_flow, scan_options_flow, format_flow_alert,
)
from consensus_engine.models import FlowHit
from consensus_engine import db


def _chain(calls_rows, puts_rows=None):
    return types.SimpleNamespace(
        calls=pd.DataFrame(calls_rows),
        puts=pd.DataFrame(puts_rows or []),
    )


def _row(strike, vol, oi, last_price, age_min=0, sym="X"):
    ts = pd.Timestamp(time.time() - age_min * 60, unit="s", tz="UTC")
    return {"strike": strike, "volume": vol, "openInterest": oi, "lastPrice": last_price,
            "lastTradeDate": ts, "contractSymbol": sym}


def test_balanced_thresholds_qualify_and_reject():
    chain = _chain([
        _row(100, 5000, 500, 6.0),     # ratio 10x, $3.0M premium -> QUALIFY
        _row(110, 5000, 2000, 6.0),    # ratio 2.5x -> reject (ratio)
        _row(120, 100, 5, 6.0),        # vol 100 < 500 -> reject (volume)
        _row(130, 5000, 500, 0.10),    # premium $50k < $250k -> reject (premium)
    ])
    hits = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                max_stale_sec=0, now=time.time())
    assert len(hits) == 1
    assert hits[0].strike == 100 and hits[0].side == "CALL"
    assert hits[0].vol_oi_ratio == 10.0
    assert hits[0].premium_usd == 5000 * 6.0 * 100


def test_staleness_filter_skips_old_trades():
    now = time.time()
    chain = _chain([_row(100, 5000, 500, 6.0, age_min=120)])  # 2h old
    fresh = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                 min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                 max_stale_sec=0, now=now)        # staleness disabled
    stale = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                 min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                 max_stale_sec=3600, now=now)     # 60-min cap
    assert len(fresh) == 1 and len(stale) == 0


def test_format_flow_alert_contents():
    hit = FlowHit(ticker="TSLA", side="CALL", strike=435.0, expiry="2026-05-29",
                  volume=201399, open_interest=11760, vol_oi_ratio=17.1,
                  premium_usd=8_260_000.0, last_trade_ts=time.time(), spot=430.0)
    txt = format_flow_alert(hit)
    assert "TSLA" in txt and "BULLISH" in txt and "17.1x" in txt and "$8.26M" in txt


@pytest.fixture
async def tmp_db():
    prev = db.DB_PATH
    db._db = None
    db.DB_PATH = tempfile.mktemp(suffix=".db")
    await db.init_db()
    yield
    await db.close_db()
    try:
        os.unlink(db.DB_PATH)
    except OSError:
        pass
    db.DB_PATH = prev
    db._db = None


async def test_persist_read_and_cooldown(tmp_db):
    hits = [
        FlowHit("AAPL", "CALL", 200, "2026-06-20", 5000, 500, 10.0, 3_000_000, time.time(), 195),
        FlowHit("NVDA", "PUT", 210, "2026-06-20", 9000, 600, 15.0, 5_000_000, time.time(), 211),
    ]
    await db.insert_options_flow(hits, alerted_tickers={"AAPL"})

    aapl = await db.get_options_flow_for_ticker("AAPL", days=7)
    assert len(aapl) == 1 and aapl[0]["premium_usd"] == 3_000_000

    # AAPL was alerted -> cooldown timestamp present; NVDA was not -> None
    assert await db.get_last_flow_alert_ts("AAPL") is not None
    assert await db.get_last_flow_alert_ts("NVDA") is None
