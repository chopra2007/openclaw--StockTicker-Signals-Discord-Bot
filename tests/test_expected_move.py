"""Tests for the !em expected-move scanner (no network — synthetic chains)."""

from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from consensus_engine.scanners import expected_move as em


# --- synthetic option-chain helpers (SPY-like numbers) ----------------------
def _row(strike, bid, ask, last, iv, vol, oi, ts="2026-06-25T20:14:59Z"):
    return {
        "strike": strike, "bid": bid, "ask": ask, "lastPrice": last,
        "impliedVolatility": iv, "volume": vol, "openInterest": oi,
        "lastTradeDate": pd.Timestamp(ts),
    }


def _spy_chain():
    calls = pd.DataFrame([
        _row(733.0, 3.64, 3.75, 3.68, 0.141, 4000, 5636),
        _row(734.0, 3.08, 3.10, 3.08, 0.1359, 76897, 2186),
        _row(735.0, 2.51, 2.53, 2.52, 0.132, 6000, 8067),
    ])
    puts = pd.DataFrame([
        _row(733.0, 2.15, 2.17, 2.16, 0.128, 5000, 3963),
        _row(734.0, 2.53, 2.56, 2.55, 0.1249, 64256, 7648),
        _row(735.0, 2.95, 3.01, 2.97, 0.122, 4000, 5113),
    ])
    return calls, puts


EDT = timezone(timedelta(hours=-4))


# --- expiration selection ---------------------------------------------------
EXPS = ["2026-06-25", "2026-06-26", "2026-06-29"]


def test_select_expiration_market_open_uses_today():
    now = datetime(2026, 6, 25, 11, 0, tzinfo=EDT)  # Thu, RTH
    exp, label = em.select_expiration(EXPS, now)
    assert exp == "2026-06-25"
    assert "Today" in label


def test_select_expiration_after_close_uses_next_session():
    now = datetime(2026, 6, 25, 17, 36, tzinfo=EDT)  # Thu, after close
    exp, label = em.select_expiration(EXPS, now)
    assert exp == "2026-06-26"
    assert "Next session" in label


def test_select_expiration_empty_raises():
    with pytest.raises(em.EMUnavailable):
        em.select_expiration([], datetime(2026, 6, 25, 17, 36, tzinfo=EDT))


def test_time_to_expiration_next_trading_day():
    now = datetime(2026, 6, 25, 17, 36, tzinfo=EDT)
    tte = em.time_to_expiration("2026-06-26", now)
    assert tte["trading_days"] == 1.0
    assert tte["T_252"] == pytest.approx(1 / 252)


# --- ATM selection ----------------------------------------------------------
def test_select_atm_picks_closest_to_spot():
    calls, puts = _spy_chain()
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    assert c.strike == 734.0 and p.strike == 734.0


def test_select_atm_steps_out_when_closest_illiquid():
    calls, puts = _spy_chain()
    # Kill the 734 strike's quotes (zero bid/ask) -> should fall to 735 (next closest).
    for df in (calls, puts):
        df.loc[df["strike"] == 734.0, ["bid", "ask"]] = 0.0
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    assert c.strike == 735.0


def test_select_atm_raises_when_all_illiquid():
    calls, puts = _spy_chain()
    for df in (calls, puts):
        df[["bid", "ask"]] = 0.0
    with pytest.raises(em.EMUnavailable):
        em.select_atm(calls, puts, 734.30, min_open_interest=100)


def test_select_atm_respects_oi_floor():
    calls, puts = _spy_chain()
    # 734 has put OI 7648, call OI 2186; raise floor above both neighbors but
    # below 734 so 734 is the only one that clears -> still 734.
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=2000)
    assert c.strike == 734.0


# --- expected-move math -----------------------------------------------------
def test_calculate_expected_moves_matches_reference():
    calls, puts = _spy_chain()
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    tte = em.time_to_expiration("2026-06-26", datetime(2026, 6, 25, 17, 36, tzinfo=EDT))
    calc = em.calculate_expected_moves(734.30, c, p, tte, multiplier=0.85)

    assert calc["raw_straddle_em"] == pytest.approx(5.635, abs=1e-3)
    assert calc["adjusted_straddle_em"] == pytest.approx(5.635 * 0.85, abs=1e-3)
    assert calc["atm_iv"] == pytest.approx((0.1359 + 0.1249) / 2, abs=1e-4)
    assert calc["iv_em_252"] == pytest.approx(734.30 * calc["atm_iv"] * (1 / 252) ** 0.5, abs=1e-3)
    # to-expiration EM equals the 1-day 252 EM when exactly one trading day out
    assert calc["iv_em_to_expiration"] == pytest.approx(calc["iv_em_252"], abs=1e-6)
    # straddle-implied IV should exceed Yahoo's understated blended IV here
    assert calc["straddle_implied_iv"] > calc["atm_iv"]


# --- embed ------------------------------------------------------------------
def _make_result():
    calls, puts = _spy_chain()
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    tte = em.time_to_expiration("2026-06-26", datetime(2026, 6, 25, 17, 36, tzinfo=EDT))
    calc = em.calculate_expected_moves(734.30, c, p, tte, 0.85)
    raw = calc["raw_straddle_em"]
    iv252 = calc["iv_em_252"]
    return em.ExpectedMoveResult(
        ticker="SPY", spot=734.30, expiration="2026-06-26",
        session_label="Next session (market closed)", market_open=False,
        atm_strike=734.0, call=c, put=p, em=calc, primary_em=raw,
        upper=734.30 + raw, lower=734.30 - raw,
        iv_band_upper=734.30 + iv252, iv_band_lower=734.30 - iv252,
        tte=tte, quote_ts=c.last_trade, history=pd.DataFrame(), history_label="",
    )


def test_build_em_embed_structure():
    embed = em.build_em_embed(_make_result(), with_image=True)
    assert embed["title"].startswith("📊")
    assert "SPY" in embed["title"]
    assert embed["color"] == 0xFEE75C
    names = [f["name"] for f in embed["fields"]]
    assert names == ["Expected move", "Upper / Lower", "Spot", "Reference"]
    assert embed["image"]["url"] == "attachment://SPY_em.png"


def test_build_em_embed_has_no_warning_line():
    """User removed the '⚠ delayed / not a forecast' line; footer stays quiet."""
    embed = em.build_em_embed(_make_result(), with_image=True)
    blob = str(embed)
    assert "⚠" not in blob
    assert "not a forecast" not in blob.lower()
    # provenance is still disclosed, factually, in the footer
    assert "delayed" in embed["footer"]["text"].lower()
    assert "yfinance" in embed["footer"]["text"].lower()


def test_build_em_embed_no_image_omits_image_key():
    embed = em.build_em_embed(_make_result(), with_image=False)
    assert "image" not in embed
