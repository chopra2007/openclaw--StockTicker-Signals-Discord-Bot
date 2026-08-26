"""TODO #98 — display-honesty fixes for expected move and ordinary options-
flow alerts. No math or selection behavior changes; these tests prove:

1. calculate_expected_moves() is numerically unchanged.
2. !em's embed headlines the raw straddle and drops the 68%/1-SD claim.
3. The shared calibration note carries the measured 61.6% / 55.0% / 3,721.
4. format_flow_alert() drops the BULLISH/BEARISH/"fresh positioning"/
   "instant trigger" wording for BUY, SELL and AMBIGUOUS hits, keeps the
   real side tag, and the SWEEP tier still gets its own header.
5. The flow qualification/scoring path (_scan_chain_for_flow) is unchanged.
6. Every owner-visible time string here is Pacific, never "ET"/"Eastern".
"""
import time
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from consensus_engine.scanners import expected_move as em
from consensus_engine.scanners.options import (
    _scan_chain_for_flow, format_flow_alert,
)
from consensus_engine.models import FlowHit

EDT = timezone(timedelta(hours=-4))


# ---------------------------------------------------------------------------
# 1. calculate_expected_moves() numerically unchanged
# ---------------------------------------------------------------------------
def test_calculate_expected_moves_numerically_unchanged():
    call = em.OptionQuote(strike=734.0, bid=3.08, ask=3.10, last=3.08,
                           iv=0.1359, volume=76897, open_interest=2186)
    put = em.OptionQuote(strike=734.0, bid=2.53, ask=2.56, last=2.55,
                          iv=0.1249, volume=64256, open_interest=7648)
    tte = em.time_to_expiration("2026-06-26",
                                 datetime(2026, 6, 25, 17, 36, tzinfo=EDT))
    calc = em.calculate_expected_moves(734.30, call, put, tte, 0.85)

    # Hand-computed from the raw straddle mid and the 0.85 multiplier —
    # a display-order/label fix must never move these numbers.
    expected_raw = call.mid + put.mid
    assert calc["raw_straddle_em"] == pytest.approx(expected_raw, rel=1e-12)
    assert calc["adjusted_straddle_em"] == pytest.approx(expected_raw * 0.85, rel=1e-12)
    assert calc["multiplier"] == 0.85
    assert calc["raw_straddle_em_pct"] == pytest.approx(expected_raw / 734.30, rel=1e-12)
    assert calc["adjusted_straddle_em_pct"] == pytest.approx(
        (expected_raw * 0.85) / 734.30, rel=1e-12)


# ---------------------------------------------------------------------------
# 2 & 3. !em embed — raw straddle headline, no 68%/1-SD claim, calibration note
# ---------------------------------------------------------------------------
def _spy_chain():
    def row(strike, bid, ask, last, iv, vol, oi):
        return {"strike": strike, "bid": bid, "ask": ask, "lastPrice": last,
                "impliedVolatility": iv, "volume": vol, "openInterest": oi,
                "lastTradeDate": pd.Timestamp("2026-06-25T20:14:59Z")}
    calls = pd.DataFrame([row(734.0, 3.08, 3.10, 3.08, 0.1359, 76897, 2186)])
    puts = pd.DataFrame([row(734.0, 2.53, 2.56, 2.55, 0.1249, 64256, 7648)])
    return calls, puts


def _make_result():
    calls, puts = _spy_chain()
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    tte = em.time_to_expiration("2026-06-26",
                                 datetime(2026, 6, 25, 17, 36, tzinfo=EDT))
    calc = em.calculate_expected_moves(734.30, c, p, tte, 0.85)
    raw, sd = calc["raw_straddle_em"], calc["iv_em_1sd"]
    return em.ExpectedMoveResult(
        ticker="SPY", spot=734.30, expiration="2026-06-26",
        session_label="Next session (market closed)", market_open=False,
        atm_strike=734.0, call=c, put=p, em=calc, primary_em=raw,
        upper=734.30 + raw, lower=734.30 - raw,
        iv_band_upper=734.30 + sd, iv_band_lower=734.30 - sd,
        tte=tte, quote_ts=c.last_trade, history=pd.DataFrame(), history_label="",
        horizon="daily",
    )


def test_em_embed_headline_is_the_raw_straddle():
    r = _make_result()
    embed = em.build_em_embed(r, with_image=False)
    move_field = [f for f in embed["fields"] if f["name"] == "Expected move"][0]
    assert f"${r.primary_em:,.2f}" in move_field["value"]
    assert r.primary_em == r.em["raw_straddle_em"]  # headline IS the raw straddle


def test_em_embed_has_no_probability_claim():
    embed = em.build_em_embed(_make_result(), with_image=False)
    blob = str(embed)
    assert "68% of the time" not in blob  # the old positive-claim phrasing
    assert "1 standard deviation —" not in blob


def test_em_embed_calibration_note_present():
    embed = em.build_em_embed(_make_result(), with_image=False)
    ref = [f for f in embed["fields"] if f["name"] == "Reference"][0]["value"]
    assert "61.6%" in ref
    assert "55.0%" in ref
    assert "3,721" in ref


def test_calibration_note_short_and_long_carry_the_same_numbers():
    short = em.calibration_note(short=True)
    long_ = em.calibration_note(short=False)
    for note in (short, long_):
        assert "61.6%" in note and "55.0%" in note and "3,721" in note
        assert "68% of the time" not in note  # never asserted as fact


# ---------------------------------------------------------------------------
# 4. format_flow_alert() — BUY / SELL / AMBIGUOUS, no overclaiming, SWEEP intact
# ---------------------------------------------------------------------------
def _hit(side="CALL", flow_side="BUY", note="at-ask", vol_oi_ratio=17.1):
    return FlowHit(ticker="TSLA", side=side, strike=435.0, expiry="2026-05-29",
                    volume=201399, open_interest=11760, vol_oi_ratio=vol_oi_ratio,
                    premium_usd=8_260_000.0, last_trade_ts=time.time(), spot=430.0,
                    flow_side=flow_side, flow_side_note=note)


_FORBIDDEN = ("proven", "BULLISH", "BEARISH", "fresh positioning",
              "Unusual-flow instant trigger")


@pytest.mark.parametrize("side,flow_side,note", [
    ("CALL", "BUY", "at-ask"),
    ("CALL", "SELL", "at-bid"),
    ("PUT", "AMBIGUOUS", ""),
])
def test_format_flow_alert_no_overclaiming(monkeypatch, side, flow_side, note):
    from consensus_engine import config
    monkeypatch.setattr(config, "get",
                         lambda k, d=None: True if k == "options_flow.side_collect" else d)
    txt = format_flow_alert(_hit(side, flow_side, note))
    assert "TSLA" in txt
    for bad in _FORBIDDEN:
        assert bad not in txt


def test_format_flow_alert_keeps_the_real_side_tag(monkeypatch):
    from consensus_engine import config
    monkeypatch.setattr(config, "get",
                         lambda k, d=None: True if k == "options_flow.side_collect" else d)
    txt = format_flow_alert(_hit("CALL", "BUY", "at-ask"))
    assert "side: BUY (at-ask)" in txt


def test_format_flow_alert_sweep_tier_keeps_its_own_header(monkeypatch):
    from consensus_engine import config
    monkeypatch.setattr(config, "get", lambda k, d=None: d)
    txt = format_flow_alert(_hit("CALL", "BUY", "AA", vol_oi_ratio=60.0))
    assert "🔥" in txt and "SWEEP" in txt
    assert "UNUSUAL OPTIONS FLOW" not in txt
    for bad in _FORBIDDEN:
        assert bad not in txt


# ---------------------------------------------------------------------------
# 5. Flow qualification/scoring path unchanged
# ---------------------------------------------------------------------------
def test_scan_chain_for_flow_selection_unchanged():
    """TODO #98 touches display wording only -- the selection/scoring path
    must produce byte-identical results on a fixed fixture."""
    def row(strike, vol, oi, last_price):
        return {"strike": strike, "volume": vol, "openInterest": oi,
                "lastPrice": last_price,
                "lastTradeDate": pd.Timestamp(time.time(), unit="s", tz="UTC"),
                "contractSymbol": "X"}
    import types
    chain = types.SimpleNamespace(
        calls=pd.DataFrame([row(100, 5000, 500, 6.0)]),
        puts=pd.DataFrame([]),
    )
    hits = _scan_chain_for_flow("ABC", chain, "2026-06-20", 105.0,
                                 min_vol_oi=5.0, min_volume=500, min_premium=250_000,
                                 max_stale_sec=0, now=time.time())
    assert len(hits) == 1
    h = hits[0]
    assert (h.side, h.strike, h.volume, h.open_interest) == ("CALL", 100, 5000, 500)
    assert h.vol_oi_ratio == 10.0
    assert h.premium_usd == 5000 * 6.0 * 100


# ---------------------------------------------------------------------------
# 6. Owner-visible times are Pacific
# ---------------------------------------------------------------------------
def test_em_embed_footer_time_is_pacific_not_eastern():
    r = _make_result()
    embed = em.build_em_embed(r, with_image=False)
    footer = embed["footer"]["text"]
    assert "ET" not in footer.split()
    assert "Eastern" not in footer
    # A quote timestamp is present here, so the footer must carry a Pacific tz name.
    if r.quote_ts:
        assert any(tz in footer for tz in ("PDT", "PST"))


def test_em_footer_survives_a_missing_quote_timestamp():
    """`!em` used to crash outright when a chain carried no trade timestamp.

    The Schwab client sets every lastTradeDate to pandas' NaT whenever its
    epoch-ms conversion overflows, which it does on a large minority of liquid
    tickers (see _chain_map_to_df). NaT is truthy, so the old `if not ts` guard
    let it through, and formatting NaT raises ValueError — taking the whole
    card down. Found by the independent verifier as a pre-existing bug.
    """
    import pandas as pd
    from types import SimpleNamespace
    from consensus_engine.scanners.expected_move import _fmt_quote_time

    for source, expected in (("schwab", "Schwab · real-time quotes"),
                             ("yfinance", "yfinance · delayed quotes")):
        r = SimpleNamespace(quote_ts=pd.NaT, source=source)
        assert _fmt_quote_time(r) == expected

    # A real timestamp must still be formatted, in Pacific.
    ts = pd.Timestamp("2026-08-26 13:14:00", tz="America/New_York")
    r = SimpleNamespace(quote_ts=ts, source="schwab")
    out = _fmt_quote_time(r)
    assert "Schwab · real-time · quote" in out
    assert "PDT" in out and "ET" not in out
