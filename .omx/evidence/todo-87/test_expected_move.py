# EVIDENCE COPY — original path: tests/test_expected_move.py
# copied 2026-08-17 for TODO #87 (read-only evidence, do not edit)
# full file, 504 lines

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


# --- real exchange calendar (holidays, early closes, weekends) ---------------
def test_time_to_expiration_skips_a_market_holiday():
    """Thu 2026-07-02 after the close -> Mon 2026-07-06 expiry is ONE session:
    Fri 2026-07-03 is the Independence Day holiday. A weekday count says 2."""
    now = datetime(2026, 7, 2, 17, 0, tzinfo=EDT)
    tte = em.time_to_expiration("2026-07-06", now)
    assert tte["sessions_remaining"] == 1
    assert tte["trading_days"] == pytest.approx(1.0)


def test_time_to_expiration_weekend_counts_monday_only():
    now = datetime(2026, 8, 15, 10, 0, tzinfo=EDT)  # Saturday
    tte = em.time_to_expiration("2026-08-17", now)
    assert tte["session_fraction_today"] == 0.0
    assert tte["trading_days"] == pytest.approx(1.0)


def test_time_to_expiration_uses_the_early_close():
    """2026-11-27 is a half day: the NYSE closes at 13:00 ET, so at 12:00 ET
    one hour of a 3.5-hour session is left -> 2/7 of a session."""
    now = datetime(2026, 11, 27, 12, 0, tzinfo=timezone(timedelta(hours=-5)))
    tte = em.time_to_expiration("2026-11-27", now)
    assert tte["sessions_remaining"] == 0
    assert tte["trading_days"] == pytest.approx(1.0 / 3.5, abs=1e-3)


def test_time_to_expiration_intraday_fraction_shrinks_through_the_day():
    early = em.time_to_expiration(
        "2026-08-14", datetime(2026, 8, 14, 10, 30, tzinfo=EDT))
    late = em.time_to_expiration(
        "2026-08-14", datetime(2026, 8, 14, 15, 30, tzinfo=EDT))
    assert 0 < late["trading_days"] < early["trading_days"] < 1.0


def test_market_open_respects_the_early_close():
    ET = timezone(timedelta(hours=-5))
    assert em.market_is_open(datetime(2026, 11, 27, 12, 0, tzinfo=ET)) is True
    assert em.market_is_open(datetime(2026, 11, 27, 14, 0, tzinfo=ET)) is False


def test_sessions_until_is_holiday_aware():
    now = datetime(2026, 7, 2, 17, 0, tzinfo=EDT)
    assert em.sessions_until("2026-07-06", now) == 1
    assert em.sessions_until("2026-07-09", now) == 4
    assert em.sessions_until("2026-07-02", now) == 0


# --- weekly expiration selection --------------------------------------------
DAILY_EXPS = ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
              "2026-08-21", "2026-08-24", "2026-08-25", "2026-08-28"]


def test_select_expiration_weekly_targets_five_sessions():
    now = datetime(2026, 8, 14, 17, 0, tzinfo=EDT)  # Friday, after the close
    exp, label = em.select_expiration(DAILY_EXPS, now, horizon="weekly")
    assert exp == "2026-08-21"          # Mon..Fri = 5 sessions out
    assert "Weekly" in label and "5 trading sessions" in label


def test_select_expiration_weekly_on_a_weekly_only_chain():
    """A ticker listing only Friday weeklies still gets a real listed date."""
    now = datetime(2026, 8, 14, 17, 0, tzinfo=EDT)
    exps = ["2026-08-21", "2026-08-28", "2026-09-18"]
    exp, label = em.select_expiration(exps, now, horizon="weekly")
    assert exp == "2026-08-21"
    assert "5 trading sessions" in label


def test_select_expiration_weekly_monthly_only_never_invents_a_date():
    now = datetime(2026, 8, 14, 17, 0, tzinfo=EDT)
    exps = ["2026-09-18"]
    exp, label = em.select_expiration(exps, now, horizon="weekly")
    assert exp == "2026-09-18"          # the only listed date
    assert "24 trading sessions" in label   # honest about how far out it is


def test_select_expiration_weekly_never_picks_todays_expiry():
    """Mid-session on a day that is itself an expiry, weekly still looks a full
    trading week ahead — 5 sessions from Monday 08-17 is Monday 08-24."""
    now = datetime(2026, 8, 17, 11, 0, tzinfo=EDT)  # Monday, market open
    exp, label = em.select_expiration(["2026-08-17"] + DAILY_EXPS, now,
                                      horizon="weekly")
    assert exp == "2026-08-24"
    assert "5 trading sessions" in label


def test_select_expiration_weekly_raises_without_a_future_expiry():
    now = datetime(2026, 8, 28, 17, 0, tzinfo=EDT)
    with pytest.raises(em.EMUnavailable):
        em.select_expiration(["2026-08-28"], now, horizon="weekly")


def test_select_expiration_daily_default_unchanged_on_friday_after_close():
    now = datetime(2026, 8, 14, 17, 0, tzinfo=EDT)
    exp, label = em.select_expiration(DAILY_EXPS, now)
    assert exp == "2026-08-17"
    assert "Next session" in label


def test_select_expiration_daily_on_the_weekend():
    now = datetime(2026, 8, 15, 12, 0, tzinfo=EDT)  # Saturday
    exp, label = em.select_expiration(DAILY_EXPS, now)
    assert exp == "2026-08-17"
    assert "weekend" in label.lower()


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


def test_select_atm_rejects_a_crossed_book():
    """bid above ask is a broken quote — the mid means nothing. Step out."""
    calls, puts = _spy_chain()
    calls.loc[calls["strike"] == 734.0, "bid"] = 9.99   # bid > ask 3.10
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    assert c.strike != 734.0


def test_select_atm_rejects_all_crossed_books():
    calls, puts = _spy_chain()
    for df in (calls, puts):
        df["bid"] = df["ask"] + 1.0
    with pytest.raises(em.EMUnavailable):
        em.select_atm(calls, puts, 734.30, min_open_interest=100)


def test_select_atm_rejects_missing_quotes():
    calls, puts = _spy_chain()
    for df in (calls, puts):
        df[["bid", "ask"]] = 0.0
    with pytest.raises(em.EMUnavailable):
        em.select_atm(calls, puts, 734.30, min_open_interest=100)


def test_select_atm_rejects_wide_spreads():
    calls, puts = _spy_chain()
    calls["ask"] = calls["bid"] * 3.0        # ~100% spread everywhere
    with pytest.raises(em.EMUnavailable):
        em.select_atm(calls, puts, 734.30, min_open_interest=100,
                      max_spread_pct=0.25)


def test_select_atm_never_steps_far_from_spot():
    """No strike near spot -> honest refusal, not a far-OTM straddle. 500 is
    234 points (many strike steps) below the 733-735 grid."""
    calls, puts = _spy_chain()
    with pytest.raises(em.EMUnavailable):
        em.select_atm(calls, puts, 500.0, min_open_interest=100)


def test_select_atm_allows_one_strike_step_on_a_wide_grid():
    """A $3.62 stock listed in $1 strikes has nothing within 5% — its $4 strike
    IS the at-the-money one, so the distance guard must not reject it."""
    calls = pd.DataFrame([_row(3.0, 0.75, 0.85, 0.80, 0.60, 20, 400),
                          _row(4.0, 0.20, 0.25, 0.22, 0.58, 30, 900),
                          _row(5.0, 0.05, 0.10, 0.07, 0.62, 10, 700)])
    puts = pd.DataFrame([_row(3.0, 0.10, 0.15, 0.12, 0.61, 15, 500),
                         _row(4.0, 0.55, 0.65, 0.60, 0.59, 25, 800),
                         _row(5.0, 1.35, 1.50, 1.40, 0.63, 5, 300)])
    c, p = em.select_atm(calls, puts, 3.62, min_open_interest=100)
    assert c.strike == 4.0 and p.strike == 4.0


def test_select_atm_mid_never_falls_back_to_a_stale_last_trade():
    """Every accepted leg has a live two-sided quote, so `mid` is bid/ask —
    a stale lastPrice can never become the straddle price."""
    calls, puts = _spy_chain()
    for df in (calls, puts):
        df["lastPrice"] = 99.0               # absurd stale print
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    assert c.mid == pytest.approx((c.bid + c.ask) / 2)
    assert p.mid == pytest.approx((p.bid + p.ask) / 2)


@pytest.mark.asyncio
async def test_compute_em_falls_back_when_schwab_quotes_fail_quality(monkeypatch):
    """A bad Schwab quote snapshot must try the delayed fallback before the
    command tells the user that a liquid ticker is illiquid."""
    calls, puts = _spy_chain()
    schwab_calls, schwab_puts = calls.copy(), puts.copy()
    schwab_calls[["bid", "ask"]] = 0.0
    schwab_puts[["bid", "ask"]] = 0.0
    now = datetime(2026, 6, 25, 17, 36, tzinfo=EDT)

    def bundle(source, bundle_calls, bundle_puts):
        return {
            "spot": 734.30,
            "expiration": "2026-06-26",
            "session_label": "Next session (market closed)",
            "calls": bundle_calls,
            "puts": bundle_puts,
            "history": pd.DataFrame(),
            "history_label": "no price history",
            "source": source,
        }

    monkeypatch.setattr(em, "now_eastern", lambda: now)
    monkeypatch.setattr(
        em, "_fetch_bundle",
        lambda ticker, now_et, horizon: bundle(
            "schwab", schwab_calls, schwab_puts),
    )
    monkeypatch.setattr(
        em, "_yfinance_bundle",
        lambda ticker, now_et, horizon: bundle("yfinance", calls, puts),
    )

    result = await em.compute_em("SPY")

    assert result.source == "yfinance"
    assert result.atm_strike == 734.0
    assert result.primary_em == pytest.approx(5.635, abs=1e-3)


@pytest.mark.asyncio
async def test_compute_em_does_not_call_ticker_illiquid_when_schwab_is_down(
        monkeypatch):
    """If live data failed and delayed quotes are zeros, name the temporary
    data problem instead of falsely labelling SPY or TSLA illiquid."""
    calls, puts = _spy_chain()
    calls[["bid", "ask"]] = 0.0
    puts[["bid", "ask"]] = 0.0
    now = datetime(2026, 6, 25, 17, 36, tzinfo=EDT)
    bundle = {
        "spot": 734.30,
        "expiration": "2026-06-26",
        "session_label": "Next session (market closed)",
        "calls": calls,
        "puts": puts,
        "history": pd.DataFrame(),
        "history_label": "no price history",
        "source": "yfinance",
        "_schwab_unavailable": True,
    }
    monkeypatch.setattr(em, "now_eastern", lambda: now)
    monkeypatch.setattr(em, "_fetch_bundle",
                        lambda ticker, now_et, horizon: bundle)

    with pytest.raises(em.EMUnavailable, match="temporarily unavailable") as exc:
        await em.compute_em("SPY")

    assert "illiquid" not in str(exc.value).lower()


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
def _make_result(horizon="daily", expiration="2026-06-26",
                 now=datetime(2026, 6, 25, 17, 36, tzinfo=EDT), band=True):
    calls, puts = _spy_chain()
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    tte = em.time_to_expiration(expiration, now)
    calc = em.calculate_expected_moves(734.30, c, p, tte, 0.85)
    raw = calc["raw_straddle_em"]
    sd = calc["iv_em_1sd"]
    return em.ExpectedMoveResult(
        ticker="SPY", spot=734.30, expiration=expiration,
        session_label="Next session (market closed)", market_open=False,
        atm_strike=734.0, call=c, put=p, em=calc, primary_em=raw,
        upper=734.30 + raw, lower=734.30 - raw,
        iv_band_upper=734.30 + sd if band else None,
        iv_band_lower=734.30 - sd if band else None,
        tte=tte, quote_ts=c.last_trade, history=pd.DataFrame(), history_label="",
        horizon=horizon,
    )


def test_build_em_embed_structure():
    embed = em.build_em_embed(_make_result(), with_image=True)
    assert embed["title"].startswith("📊")
    assert "SPY" in embed["title"]
    assert embed["color"] == 0xFEE75C
    names = [f["name"] for f in embed["fields"]]
    assert names == ["Expected move", "Expected range", "Price", "Expiration",
                     "ATM call 734", "ATM put 734", "Reference"]
    assert embed["image"]["url"] == "attachment://SPY_em.png"


def test_build_em_embed_daily_labels():
    embed = em.build_em_embed(_make_result(), with_image=False)
    assert "Daily Expected Move" in embed["title"]
    assert "**Daily**" in embed["description"]
    assert "Weekly" not in str(embed)
    assert "1 trading session left" in embed["description"]


def test_build_em_embed_weekly_labels():
    r = _make_result(horizon="weekly", expiration="2026-07-02",
                     now=datetime(2026, 6, 25, 17, 36, tzinfo=EDT))
    embed = em.build_em_embed(r, with_image=False)
    assert "Weekly Expected Move" in embed["title"]
    assert "**Weekly**" in embed["description"]
    assert "Daily" not in str(embed)
    assert "5 trading sessions left" in embed["description"]
    assert "`2026-07-02`" in embed["description"]


def test_build_em_embed_shows_both_legs_quotes():
    embed = em.build_em_embed(_make_result(), with_image=False)
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert "bid 3.08 / ask 3.10" in fields["ATM call 734"]
    assert "bid 2.53 / ask 2.56" in fields["ATM put 734"]
    assert "OI 2,186" in fields["ATM call 734"]
    assert "OI 7,648" in fields["ATM put 734"]


def test_build_em_embed_range_matches_the_headline_estimate():
    """Every displayed level comes from the SAME estimate as the headline."""
    r = _make_result()
    embed = em.build_em_embed(r, with_image=False)
    fields = {f["name"]: f["value"] for f in embed["fields"]}
    assert f"{r.spot + r.primary_em:,.2f}" in fields["Expected range"]
    assert f"{r.spot - r.primary_em:,.2f}" in fields["Expected range"]
    assert f"±${r.primary_em:,.2f}" in fields["Expected move"]
    pct = r.em["raw_straddle_em_pct"] * 100
    assert f"±{pct:.2f}%" in fields["Expected move"]


def test_reference_band_is_one_sd_to_expiration_not_one_session():
    """Weekly must show a WEEKLY 1-sigma band, not the one-session band."""
    daily = _make_result()
    weekly = _make_result(horizon="weekly", expiration="2026-07-02")
    d_width = daily.iv_band_upper - daily.spot
    w_width = weekly.iv_band_upper - weekly.spot
    scale = (weekly.tte["T_365"] / daily.tte["T_365"]) ** 0.5
    assert w_width == pytest.approx(d_width * scale, rel=1e-6)
    assert w_width > d_width * 2          # ~5 sessions vs 1
    assert weekly.em["iv_em_1sd"] > weekly.em["iv_em_252"]


def test_one_sd_band_uses_the_same_clock_as_the_quoted_iv():
    """The chains quote implied vol on a CALENDAR-year clock, so the 1-sigma
    band scales with calendar time. Over a weekend that band is wider than the
    trading-day version — the mixed-units bug this replaces made it narrower."""
    calls, puts = _spy_chain()
    c, p = em.select_atm(calls, puts, 734.30, min_open_interest=100)
    # Friday after the close, Monday expiry: 1 session but ~3 calendar days.
    tte = em.time_to_expiration("2026-08-17", datetime(2026, 8, 14, 17, 0, tzinfo=EDT))
    calc = em.calculate_expected_moves(734.30, c, p, tte, 0.85)
    assert tte["sessions_remaining"] == 1
    assert calc["iv_em_1sd"] > calc["iv_em_to_expiration"]
    assert calc["iv_em_1sd"] == pytest.approx(
        734.30 * calc["atm_iv"] * tte["T_365"] ** 0.5, rel=1e-9)


def test_reference_band_omitted_when_iv_unusable():
    """No 1-sigma band -> say so; never relabel the straddle range as 68%."""
    embed = em.build_em_embed(_make_result(band=False), with_image=False)
    ref = [f for f in embed["fields"] if f["name"] == "Reference"][0]["value"]
    assert "68" not in ref
    assert "No usable implied volatility" in ref


def test_reference_band_labels_68_percent_only_with_the_1sd_band():
    embed = em.build_em_embed(_make_result(), with_image=False)
    ref = [f for f in embed["fields"] if f["name"] == "Reference"][0]["value"]
    assert "68% of the time" in ref
    r = _make_result()
    assert f"{r.iv_band_lower:,.2f}" in ref and f"{r.iv_band_upper:,.2f}" in ref


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


def test_footer_labels_schwab_realtime_not_delayed():
    """#57: a Schwab-sourced result must be labelled real-time, NEVER 'delayed'."""
    r = _make_result()
    r.source = "schwab"
    footer = em.build_em_embed(r, with_image=False)["footer"]["text"]
    assert "Schwab" in footer
    assert "real-time" in footer.lower()
    assert "delayed" not in footer.lower()
    assert "yfinance" not in footer.lower()


def test_footer_defaults_to_yfinance_delayed():
    """Default/absent source keeps the honest yfinance 'delayed' label (regression)."""
    r = _make_result()
    assert r.source == "yfinance"
    footer = em.build_em_embed(r, with_image=False)["footer"]["text"]
    assert "yfinance" in footer.lower()
    assert "delayed" in footer.lower()
