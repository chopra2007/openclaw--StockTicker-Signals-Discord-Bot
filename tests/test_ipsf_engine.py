"""Focused tests for the TODO #104 research engine (scripts/research/ipsf_*).

Hand-built bars only. No network, no database, no real research data. These
tests check the fill rules that decide whether a backtest is honest: the stop
counts first, a gap exits at the real trade, a minute with no bar can never
fill, one leg of a pair is not a pair, and the account limits actually bind.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "research"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ipsf_engine as eng  # noqa: E402
import ipsf_metrics as met  # noqa: E402


POLICY = {
    "methods": {
        "M1": {"score_threshold": 1.0, "stop_risk_unit_multiple": 1.25,
               "stop_frac_min": 0.0030, "stop_frac_max": 0.0150,
               "block_minutes": 30, "delayed_entry_minutes": 1,
               "max_entries_per_day": 4, "max_entry_slide_minutes": 4,
               "halt_missing_minutes": 5},
        "M2": {"move_floor": 0.03, "volume_threshold": 1.0,
               "stop_atr_multiple": 1.5, "stop_frac_min": 0.02,
               "stop_frac_max": 0.08, "max_hold_sessions": 5},
        "M3": {"formation_sessions": 120, "trading_sessions": 60,
               "max_hold_sessions": 5, "entry_z": 2.0, "pairs_kept": 10,
               "convergence_band": 0.5, "stop_rel_multiple": 1.5,
               "stop_frac_min": 0.025, "stop_frac_max": 0.08},
    },
    "costs": {"single": {"normal": 0.0020, "harsh": 0.0035},
              "pair": {"normal": 0.0040, "harsh": 0.0070}},
    "portfolio": {"starting_capital": 100000.0, "risk_per_position": 0.0025,
                  "max_total_risk": 0.01, "max_slots": 4,
                  "max_gross_exposure": 0.40, "max_leg_notional": 10000.0,
                  "capacity_fraction": 0.005, "short_charge_annual": 0.02,
                  "min_shares": 20, "fixed_notional_path": 10000.0,
                  "tick_size": 0.01, "slippage_allowance": 0.0010},
    "statistics": {"seed": 20260828, "resamples": 200,
                   "development_confidence": 0.9833, "later_confidence": 0.95},
    "gates": {"development": {}, "later_period": {}},
}


def sig_row(symbol="AAA", date="2024-01-03", block=600, score=1.5,
            risk_unit=0.0040, dv=5e8):
    return pd.DataFrame([{
        "date": date, "symbol": symbol, "block": block, "score": score,
        "pred": 0.001 * np.sign(score), "scale": 0.0006,
        "risk_unit": risk_unit, "prior20_block_dollar_volume": dv,
        "n_bars": 30, "n_in_block": 55, "mkt": 0.0,
    }])


def bars(date, symbol, block, rows, fill=True):
    """rows = list of (minute_offset, open, high, low, close).

    With `fill`, the untouched minutes of the block are filled with flat bars
    at the previous close, so a fixture never accidentally trips the halt rule
    (5 or more consecutive missing minutes).
    """
    given = {m: (o, h, lo, c) for (m, o, h, lo, c) in rows}
    out = []
    last = None
    for m in range(30):
        if m in given:
            o, h, lo, c = given[m]
        elif fill and last is not None:
            o = h = lo = c = last
        else:
            continue
        out.append({"date": date, "symbol": symbol, "block": block,
                    "minute": block + m, "open": o, "high": h, "low": lo,
                    "close": c, "volume": 1000})
        last = c
    return pd.DataFrame(out)


# --------------------------------------------------------------------------- #
# Method 1 fill rules
# --------------------------------------------------------------------------- #
def test_entry_is_the_first_trade_of_the_block_and_exit_is_the_last():
    sig = eng.m1_signals(sig_row(), POLICY)
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.2, 99.9, 100.1),
              (1, 100.1, 100.3, 100.0, 100.2),
              (29, 100.2, 100.5, 100.1, 100.4)])
    out = eng.m1_price_trades(sig, b, POLICY)
    r = out.iloc[0]
    assert r["entry_px"] == 100.0            # open of the first bar
    assert r["exit_px"] == 100.4             # close of the last bar
    assert r["exit_reason"] == "time_exit"
    assert r["gross_return"] == pytest.approx(100.4 / 100.0 - 1)


def test_stop_counts_first_when_stop_and_time_exit_share_a_bar():
    sig = eng.m1_signals(sig_row(risk_unit=0.0024), POLICY)   # long, stop 30 bps
    # the final bar dips through the stop AND is the time-exit bar
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.2, 99.95, 100.1),
              (29, 100.1, 100.6, 99.60, 100.5)])
    out = eng.m1_price_trades(sig, b, POLICY)
    r = out.iloc[0]
    assert r["exit_reason"] == "stop"
    assert r["exit_px"] == pytest.approx(100.0 * (1 - 0.0030))
    assert r["gross_return"] < 0             # the favourable close is ignored


def test_a_bar_that_opens_through_the_stop_exits_at_the_real_trade():
    sig = eng.m1_signals(sig_row(risk_unit=0.0024), POLICY)
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.1, 99.9, 100.0),
              (5, 98.0, 98.5, 97.5, 98.2),      # gaps far through the stop
              (29, 99.0, 99.2, 98.8, 99.1)])
    out = eng.m1_price_trades(sig, b, POLICY)
    r = out.iloc[0]
    assert r["exit_reason"] == "stop_gap"
    assert r["exit_px"] == 98.0               # the printed open, not the stop
    assert r["exit_px"] < 100.0 * (1 - 0.0030)


def test_short_side_stop_uses_the_high():
    sig = eng.m1_signals(sig_row(score=-1.5, risk_unit=0.0024), POLICY)
    assert sig.iloc[0]["side"] == -1
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.1, 99.9, 100.0),
              (10, 100.1, 100.9, 100.0, 100.8),   # high pierces the short stop
              (29, 99.0, 99.2, 98.8, 99.0)])
    out = eng.m1_price_trades(sig, b, POLICY)
    r = out.iloc[0]
    assert r["exit_reason"] == "stop"
    assert r["exit_px"] == pytest.approx(100.0 * 1.0030)
    assert r["gross_return"] == pytest.approx(-0.0030)


def test_a_minute_with_no_bar_never_fills():
    sig = eng.m1_signals(sig_row(), POLICY)
    out = eng.m1_price_trades(sig, pd.DataFrame(columns=[
        "date", "symbol", "block", "minute", "open", "high", "low", "close",
        "volume"]), POLICY)
    assert bool(out.iloc[0]["void"]) is True
    assert out.iloc[0]["void_reason"] == "no_bars"
    assert pd.isna(out.iloc[0]["gross_return"])


def test_delayed_entry_uses_the_next_printed_minute_not_an_invented_one():
    sig = eng.m1_signals(sig_row(), POLICY)
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.1, 99.9, 100.0),
              (4, 101.0, 101.2, 100.9, 101.1),   # nothing printed 601-603
              (29, 102.0, 102.2, 101.8, 102.0)], fill=False)
    b = b[b["minute"] != 600 + 0].reset_index(drop=True) if False else b
    out = eng.m1_price_trades(sig, b, POLICY, entry_delay_minutes=1)
    assert out.iloc[0]["entry_px"] == 101.0
    assert out.iloc[0]["entry_minute"] == 604


def test_bars_after_the_block_ends_are_ignored():
    sig = eng.m1_signals(sig_row(), POLICY)
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.1, 99.9, 100.0),
              (29, 100.0, 100.2, 99.9, 100.1),
              (35, 200.0, 200.0, 200.0, 200.0)])   # next block, must not leak
    out = eng.m1_price_trades(sig, b, POLICY)
    assert out.iloc[0]["exit_px"] == 100.1
    assert out.iloc[0]["exit_minute"] == 629


def test_score_below_the_frozen_tail_is_not_a_candidate():
    assert len(eng.m1_signals(sig_row(score=0.9), POLICY)) == 0
    assert len(eng.m1_signals(sig_row(score=-0.9), POLICY)) == 0
    assert len(eng.m1_signals(sig_row(score=1.0), POLICY)) == 1


def test_stop_distance_is_clipped_both_ways():
    tiny = eng.m1_signals(sig_row(risk_unit=0.00001), POLICY).iloc[0]
    huge = eng.m1_signals(sig_row(risk_unit=0.50), POLICY).iloc[0]
    assert tiny["stop_frac"] == pytest.approx(0.0030)
    assert huge["stop_frac"] == pytest.approx(0.0150)


# --------------------------------------------------------------------------- #
# portfolio
# --------------------------------------------------------------------------- #
def trade(symbol, date, block, gross, stop=0.003, legs=1, side=1, hold=0.0):
    """One priced candidate ready for the account."""
    return {
        "method": "M1", "date": date, "symbol": symbol, "block": block,
        "side": side, "score": 2.0, "entry_minute": block, "entry_px": 100.0,
        "exit_px": 100.0 * (1 + side * gross), "exit_minute": block + 29,
        "exit_reason": "time_exit", "stop_frac": stop, "gross_return": gross,
        "prior20_window_dollar_volume": 1e9, "market_return": 0.0,
        "hold_days": hold, "void": False,
        "void_reason": None, "entry_slide_minutes": 0, "halt": False,
        "entry_seq": (date, block),
        "exit_seq": (date, block + 29), "legs": legs,
        "long_symbol": None, "short_symbol": None,
    }


def test_cost_is_charged_once_and_reduces_the_return():
    t = pd.DataFrame([trade("AAA", "2024-01-03", 600, 0.01)])
    taken, _ = eng.simulate(t, POLICY, 0.0020)
    assert taken.iloc[0]["net_return"] == pytest.approx(0.01 - 0.0020)


def test_only_four_slots_are_ever_open():
    rows = [trade(f"S{i}", "2024-01-03", 600, 0.01) for i in range(6)]
    taken, _ = eng.simulate(pd.DataFrame(rows), POLICY, 0.0020)
    assert len(taken) == 4


def test_the_same_stock_cannot_be_held_twice_at_once():
    rows = [trade("AAA", "2024-01-03", 600, 0.01),
            trade("AAA", "2024-01-03", 600, 0.01)]
    taken, _ = eng.simulate(pd.DataFrame(rows), POLICY, 0.0020)
    assert len(taken) == 1


def test_a_slot_is_released_once_the_earlier_trade_has_finished():
    rows = [trade(f"S{i}", "2024-01-03", 600, 0.01) for i in range(4)]
    rows.append(trade("LATER", "2024-01-03", 660, 0.01))   # a later block
    taken, _ = eng.simulate(pd.DataFrame(rows), POLICY, 0.0020)
    assert len(taken) == 5


def test_position_size_respects_the_risk_cap_and_the_leg_cap():
    t = pd.DataFrame([trade("AAA", "2024-01-03", 600, 0.01, stop=0.003)])
    taken, _ = eng.simulate(t, POLICY, 0.0020)
    r = taken.iloc[0]
    # 0.25% of $100,000 risked at a 0.30% stop wants $83,333 -> capped at $10,000
    assert r["notional"] <= POLICY["portfolio"]["max_leg_notional"] + 100.0
    assert r["shares"] == 100


def test_capacity_cap_binds_on_a_thin_name():
    row = trade("THIN", "2024-01-03", 600, 0.01)
    row["prior20_window_dollar_volume"] = 1_000_000.0   # 0.5% = $5,000
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    assert taken.iloc[0]["notional"] <= 5_000.0


def test_a_position_too_small_to_matter_is_dropped():
    row = trade("THIN", "2024-01-03", 600, 0.01)
    row["prior20_window_dollar_volume"] = 100_000.0     # 0.5% = $500 -> 5 shares
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    assert len(taken) == 0


def test_a_five_minute_hole_after_entry_closes_the_trade_at_the_last_price():
    sig = eng.m1_signals(sig_row(), POLICY)
    b = bars("2024-01-03", "AAA", 600,
             [(0, 100.0, 100.1, 99.9, 100.05),
              (1, 100.05, 100.1, 100.0, 100.10),
              (20, 105.0, 105.1, 104.9, 105.0)], fill=False)
    out = eng.m1_price_trades(sig, b, POLICY)
    r = out.iloc[0]
    assert r["exit_reason"] == "halt"
    assert r["exit_px"] == 100.10          # last price before the hole
    assert bool(r["halt"]) is True


def test_a_short_multi_day_trade_pays_the_short_charge():
    row = trade("AAA", "2024-01-03", 600, 0.01, side=-1, hold=5.0)
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    extra = 0.02 * (5.0 * 365.0 / 252.0) / 365.0
    assert taken.iloc[0]["cost_frac"] == pytest.approx(0.0020 + extra)


def test_a_long_trade_pays_no_short_charge():
    row = trade("AAA", "2024-01-03", 600, 0.01, side=1, hold=5.0)
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    assert taken.iloc[0]["cost_frac"] == pytest.approx(0.0020)


def test_a_cheap_stock_pays_more_than_the_flat_cost():
    """One cent crossed twice is 20 bps on a $5 stock, so the flat 20 bp
    allowance would leave nothing for slippage."""
    row = trade("CHEAP", "2024-01-03", 600, 0.01)
    row["entry_px"] = 5.0
    row["exit_px"] = 5.05
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    assert taken.iloc[0]["cost_frac"] == pytest.approx(2 * 0.01 / 5.0 + 0.0010)
    assert taken.iloc[0]["cost_frac"] > 0.0020


def test_the_market_move_is_taken_out_of_the_reported_profit():
    row = trade("AAA", "2024-01-03", 600, 0.01, side=1)
    row["market_return"] = 0.004        # the whole market rose 40 bps
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    r = taken.iloc[0]
    assert r["net_return"] == pytest.approx(0.01 - 0.0020)
    assert r["net_market_adjusted_return"] == pytest.approx(0.01 - 0.0020 - 0.004)


def test_a_short_gets_the_market_move_added_back_not_subtracted():
    row = trade("AAA", "2024-01-03", 600, 0.01, side=-1)
    row["market_return"] = 0.004
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    r = taken.iloc[0]
    assert r["net_market_adjusted_return"] > r["net_return"]


def test_a_pair_has_no_market_exposure_to_take_out():
    row = trade("A/B", "2024-01-03", 600, 0.01, legs=2, stop=0.03)
    row["long_symbol"], row["short_symbol"] = "A", "B"
    row["market_return"] = 0.004
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0040)
    r = taken.iloc[0]
    assert r["net_market_adjusted_return"] == pytest.approx(r["net_return"])


def test_the_equal_dollar_path_gives_every_trade_the_same_notional():
    rows = [trade("AAA", "2024-01-03", 600, 0.01, stop=0.003),
            trade("BBB", "2024-01-03", 630, 0.01, stop=0.012)]
    taken, _ = eng.simulate(pd.DataFrame(rows), POLICY, 0.0020,
                            fixed_notional=10000.0)
    assert len(taken) == 2
    assert taken["notional"].nunique() == 1


def test_a_voided_candidate_never_becomes_a_trade():
    row = trade("AAA", "2024-01-03", 600, 0.01)
    row["void"] = True
    row["gross_return"] = np.nan
    taken, _ = eng.simulate(pd.DataFrame([row]), POLICY, 0.0020)
    assert len(taken) == 0


# --------------------------------------------------------------------------- #
# metrics
# --------------------------------------------------------------------------- #
def test_break_even_win_rate_matches_the_definition():
    assert met.break_even_win_rate(0.01, 0.01) == pytest.approx(0.5)
    assert met.break_even_win_rate(0.02, 0.01) == pytest.approx(1 / 3)


def test_longest_losing_run():
    assert met.longest_losing_run(np.array([1, -1, -1, 1, -1, -1, -1])) == 3


def test_profit_factor_and_concentration():
    rows = [trade("AAA", "2024-01-03", 600, 0.02),
            trade("BBB", "2024-01-04", 600, 0.02),
            trade("AAA", "2024-01-05", 600, -0.01)]
    taken, eq = eng.simulate(pd.DataFrame(rows), POLICY, 0.0020)
    m = met.metrics(taken, eq, ["2024-01-03", "2024-01-04", "2024-01-05"],
                    POLICY)
    assert m["trades"] == 3
    assert m["profit_factor"] > 1
    assert 0 < m["max_stock_share_of_profit"] <= 1


def test_bootstrap_low_end_is_below_the_average():
    rows = []
    days = [f"2024-01-{d:02d}" for d in range(1, 29)]
    for i, d in enumerate(days):
        rows.append(trade(f"S{i%5}", d, 600, 0.01 if i % 2 else -0.005))
    taken, _ = eng.simulate(pd.DataFrame(rows), POLICY, 0.0020)
    b = met.block_bootstrap(taken, days, 0.9833, 200, 20260828)
    assert b["avg_net_return_low"] <= taken["net_return"].mean()
    assert b["avg_net_return_low"] <= b["avg_net_return_high"]


def test_the_equal_dollar_path_does_not_let_its_own_losses_pick_its_trades():
    """The account limits on the equal-dollar path are held against the STARTING
    capital. Held against current equity, a losing run shrinks the account, the
    exposure cap bites, and the run's own losses start choosing which trades it
    can afford."""
    rows = []
    # 40 heavy losers first, then 40 more trades on later days
    for i in range(40):
        rows.append(trade(f"L{i}", f"2024-01-{(i % 28) + 1:02d}", 600, -0.05))
    for i in range(40):
        rows.append(trade(f"W{i}", f"2024-02-{(i % 28) + 1:02d}", 600, 0.05))
    df = pd.DataFrame(rows)
    fixed, _ = eng.simulate(df, POLICY, 0.0020, fixed_notional=10000.0)
    compounding, _ = eng.simulate(df, POLICY, 0.0020)
    # every candidate is affordable at a flat $10,000 against the starting
    # $100,000, so the equal-dollar path must not drop any of them
    assert len(fixed) == len(df)
    # the compounding path legitimately shrinks with the account
    assert len(compounding) <= len(fixed)


def test_a_fund_is_not_a_share():
    import ipsf_daily
    assert "TQQQ" in ipsf_daily.NOT_A_COMPANY
    assert "UVXY" in ipsf_daily.NOT_A_COMPANY
    assert "SPY" in ipsf_daily.NOT_A_COMPANY
    assert "AAPL" not in ipsf_daily.NOT_A_COMPANY


def test_the_equity_readings_come_back_in_date_order():
    rows = [trade("AAA", "2024-01-03", 600, 0.01),
            trade("BBB", "2024-01-04", 600, 0.01),
            trade("CCC", "2024-01-05", 600, 0.01)]
    rows[0]["exit_seq"] = ("2024-01-09", 629)     # a later exit, entered first
    df = pd.DataFrame(rows)
    _, eq = eng.simulate(df, POLICY, 0.0020)
    assert list(eq["date"]) == sorted(eq["date"])

