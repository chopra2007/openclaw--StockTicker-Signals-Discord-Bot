"""#18: near-real-time unusual options flow — detection, staleness, persistence, cooldown."""
import time, tempfile, os
import types
import pandas as pd
import pytest

from consensus_engine.scanners.options import (
    _scan_chain_for_flow, scan_options_flow, format_flow_alert, classify_flow_side,
    _flow_tier,
)
from consensus_engine.models import FlowHit
from consensus_engine import config, db


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
    # TODO #98: direction now names the option SIDE (CALL/PUT), not a
    # BULLISH/BEARISH stock-direction call -- see format_flow_alert docstring.
    hit = FlowHit(ticker="TSLA", side="CALL", strike=435.0, expiry="2026-05-29",
                  volume=201399, open_interest=11760, vol_oi_ratio=17.1,
                  premium_usd=8_260_000.0, last_trade_ts=time.time(), spot=430.0,
                  flow_side="BUY", flow_side_note="at-ask")
    txt = format_flow_alert(hit)
    assert "TSLA" in txt and "CALL-side" in txt and "17.1x" in txt and "$8.26M" in txt
    assert "BULLISH" not in txt and "BEARISH" not in txt


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


# ---------------------------------------------------------------------------
# classify_flow_side — buy/sell-side from the trade price vs. same-snapshot
# bid/ask (options-flow-buyresell-sweeps). bid=2.00, ask=2.10 (10c spread) is
# the fixture used throughout: 25% of the spread is 2.5c.
# ---------------------------------------------------------------------------

def test_side_at_ask_is_buy():
    assert classify_flow_side(2.10, bid=2.00, ask=2.10) == ("BUY", "at-ask")


def test_side_at_bid_is_sell():
    assert classify_flow_side(2.00, bid=2.00, ask=2.10) == ("SELL", "at-bid")


def test_side_within_25pct_of_ask_is_buy():
    assert classify_flow_side(2.08, bid=2.00, ask=2.10) == ("BUY", "at-ask")


def test_side_within_25pct_of_bid_is_sell():
    assert classify_flow_side(2.02, bid=2.00, ask=2.10) == ("SELL", "at-bid")


def test_side_exact_midpoint_is_ambiguous():
    assert classify_flow_side(2.05, bid=2.00, ask=2.10) == ("AMBIGUOUS", "")


def test_side_middle_band_is_ambiguous():
    assert classify_flow_side(2.06, bid=2.00, ask=2.10) == ("AMBIGUOUS", "")
    assert classify_flow_side(2.04, bid=2.00, ask=2.10) == ("AMBIGUOUS", "")


def test_side_above_ask_is_aggressive_buy():
    assert classify_flow_side(2.15, bid=2.00, ask=2.10) == ("BUY", "AA")


def test_side_below_bid_is_aggressive_sell():
    assert classify_flow_side(1.90, bid=2.00, ask=2.10) == ("SELL", "BB")


def test_side_boundary_25pct_from_ask_is_buy():
    assert classify_flow_side(2.075, bid=2.00, ask=2.10) == ("BUY", "at-ask")


def test_side_boundary_25pct_from_bid_is_sell():
    assert classify_flow_side(2.025, bid=2.00, ask=2.10) == ("SELL", "at-bid")


def _side_collect_flag(monkeypatch, on):
    real = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: on if k == "options_flow.side_collect" else real(k, d))


def _side_flags(monkeypatch, collect, labels_live):
    real = config.get
    def _get(k, d=None):
        if k == "options_flow.side_collect":
            return collect
        if k == "options_flow.side_labels_live":
            return labels_live
        return real(k, d)
    monkeypatch.setattr(config, "get", _get)


def _hit(side, flow_side, note=""):
    return FlowHit("TSLA", side, 435.0, "2026-05-29", 201399, 11760, 17.1,
                   8_260_000.0, time.time(), 430.0, bid=2.00, ask=2.10,
                   flow_side=flow_side, flow_side_note=note)


def test_format_flow_alert_appends_side_tag_when_collected(monkeypatch):
    _side_flags(monkeypatch, collect=True, labels_live=False)
    txt = format_flow_alert(_hit("CALL", "BUY", "at-ask"))
    assert "side: BUY (at-ask)" in txt


def test_format_flow_alert_ambiguous_side_tag_has_no_note(monkeypatch):
    _side_flags(monkeypatch, collect=True, labels_live=False)
    txt = format_flow_alert(_hit("CALL", "AMBIGUOUS"))
    assert "side: AMBIGUOUS" in txt and "()" not in txt


def test_format_flow_alert_no_side_tag_when_collect_off(monkeypatch):
    _side_flags(monkeypatch, collect=False, labels_live=False)
    txt = format_flow_alert(_hit("CALL", "BUY", "at-ask"))
    assert "side:" not in txt


def test_format_flow_alert_direction_unchanged_when_labels_live_off(monkeypatch):
    # TODO #98: the direction word now always names the option SIDE
    # (CALL/PUT) regardless of side_labels_live -- a SELL on a CALL must
    # still read "CALL-side activity", never a BULLISH/BEARISH stock call.
    _side_flags(monkeypatch, collect=True, labels_live=False)
    txt = format_flow_alert(_hit("CALL", "SELL", "at-bid"))
    assert "CALL-side" in txt
    assert "BULLISH" not in txt and "BEARISH" not in txt


@pytest.mark.parametrize("side,flow_side,expect", [
    ("CALL", "BUY",  "CALL-side"),
    ("PUT",  "SELL", "PUT-side"),
    ("CALL", "SELL", "CALL-side"),
    ("PUT",  "BUY",  "PUT-side"),
])
def test_format_flow_alert_direction_from_side_flags_live(monkeypatch, side, flow_side, expect):
    # TODO #98: options_flow.side_labels_live no longer changes the direction
    # word -- it always names the option side. The real BUY/SELL transaction
    # side still comes through the separate [side: ...] tag (tested below).
    _side_flags(monkeypatch, collect=True, labels_live=True)
    txt = format_flow_alert(_hit(side, flow_side, "at-ask"))
    assert expect in txt
    assert "BULLISH" not in txt and "BEARISH" not in txt


def test_format_flow_alert_ambiguous_direction_when_labels_live(monkeypatch):
    _side_flags(monkeypatch, collect=True, labels_live=True)
    txt = format_flow_alert(_hit("CALL", "AMBIGUOUS"))
    assert "CALL-side" in txt
    assert "BULLISH" not in txt and "BEARISH" not in txt


async def test_insert_options_flow_shadow_logs_side_when_collect_on(tmp_db, monkeypatch):
    _side_collect_flag(monkeypatch, True)
    hit = FlowHit("AAPL", "CALL", 200, "2026-06-20", 5000, 500, 10.0, 3_000_000,
                  time.time(), 195, bid=2.00, ask=2.10, flow_side="BUY",
                  flow_side_note="at-ask")
    await db.insert_options_flow([hit])
    rows = await db.get_options_flow_for_ticker("AAPL", days=7)
    assert rows[0]["flow_side"] == "BUY"
    assert rows[0]["bid"] == 2.00 and rows[0]["ask"] == 2.10


async def test_insert_options_flow_omits_side_when_collect_off(tmp_db, monkeypatch):
    _side_collect_flag(monkeypatch, False)
    hit = FlowHit("AAPL", "CALL", 200, "2026-06-20", 5000, 500, 10.0, 3_000_000,
                  time.time(), 195, bid=2.00, ask=2.10, flow_side="BUY",
                  flow_side_note="at-ask")
    await db.insert_options_flow([hit])
    rows = await db.get_options_flow_for_ticker("AAPL", days=7)
    assert rows[0]["flow_side"] is None
    assert rows[0]["bid"] is None and rows[0]["ask"] is None


@pytest.mark.parametrize("last_price,bid,ask", [
    (2.05, 0.0, 2.10),          # bid missing
    (2.05, 2.00, 0.0),          # ask missing
    (2.05, float("nan"), 2.10),  # bid NaN
    (2.05, 2.00, float("nan")),  # ask NaN
    (2.05, 2.10, 2.00),          # crossed quote (ask < bid)
    (2.05, 2.05, 2.05),          # zero spread (ask == bid)
    (0.0, 2.00, 2.10),           # last_price missing
    (float("nan"), 2.00, 2.10),  # last_price NaN
])
def test_side_degenerate_inputs_fail_to_ambiguous(last_price, bid, ask):
    assert classify_flow_side(last_price, bid, ask) == ("AMBIGUOUS", "")


# ---------------------------------------------------------------------------
# _flow_tier — the SWEEP tier (options-flow-buyresell-sweeps). Needs BOTH a
# distinctly higher vol/OI bar AND an aggressive (through-the-quote) fill;
# either alone stays "base".
# ---------------------------------------------------------------------------

def _flow_hit(vol_oi_ratio, flow_side, note):
    return FlowHit("TSLA", "CALL", 435.0, "2026-05-29", 201399, 11760,
                   vol_oi_ratio, 8_260_000.0, time.time(), 430.0,
                   flow_side=flow_side, flow_side_note=note)


def test_flow_tier_sweep_needs_high_ratio_and_aggressive_fill():
    assert _flow_tier(_flow_hit(60.0, "BUY", "AA")) == "sweep"


def test_flow_tier_base_when_ratio_high_but_not_aggressive():
    # at-ask (near the quote) is not through-the-quote aggressive -> base.
    assert _flow_tier(_flow_hit(60.0, "BUY", "at-ask")) == "base"


def test_flow_tier_base_when_aggressive_but_ratio_not_high():
    assert _flow_tier(_flow_hit(25.0, "BUY", "AA")) == "base"


def test_flow_tier_base_when_side_ambiguous():
    assert _flow_tier(_flow_hit(60.0, "AMBIGUOUS", "")) == "base"


def test_format_flow_alert_sweep_tier_uses_sweep_header(monkeypatch):
    _side_flags(monkeypatch, collect=True, labels_live=True)
    txt = format_flow_alert(_flow_hit(60.0, "BUY", "AA"))
    assert "🔥" in txt and "SWEEP" in txt
    assert "UNUSUAL OPTIONS FLOW" not in txt


def test_format_flow_alert_base_tier_uses_base_header(monkeypatch):
    _side_flags(monkeypatch, collect=True, labels_live=True)
    txt = format_flow_alert(_flow_hit(25.0, "BUY", "at-ask"))
    assert "UNUSUAL OPTIONS FLOW" in txt and "🔥" not in txt
