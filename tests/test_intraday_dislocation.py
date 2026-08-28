"""Focused tests for the TODO #103 intraday-dislocation trade-path engine.

These test the frozen fill rules directly, because a fill-rule mistake is the
single most likely way this research produces a false pass.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "research"))

from intraday_dislocation_engine import (  # noqa: E402
    TIME_EXIT_SEARCH,
    bar_lookup,
    run_rule,
    walk_trade,
)


def bars(spec):
    """spec: {minute: (open, high, low, close, volume)} -> engine day dict."""
    return {m: np.array(v, dtype=float) for m, v in spec.items()}


# --------------------------------------------------------------------------
# walk_trade - the frozen fill rules
# --------------------------------------------------------------------------
def test_long_target_touch_fills_at_the_target_not_the_high():
    day = bars({601: (100.0, 100.0, 100.0, 100.0, 10),
                602: (100.1, 103.0, 100.0, 102.0, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "target" and px == 101.0 and minute == 602


def test_long_stop_touch_fills_at_the_stop():
    day = bars({601: (100.0, 100.2, 98.5, 99.0, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "stop" and px == 99.0


def test_same_bar_target_and_stop_counts_the_stop():
    """The dangerous ambiguous case. The stop must win."""
    day = bars({601: (100.0, 102.0, 98.0, 101.0, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "stop" and px == 99.0


def test_open_already_past_the_stop_fills_at_that_open():
    day = bars({601: (97.0, 97.5, 96.0, 96.5, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "stop_gap" and px == 97.0


def test_open_already_past_the_target_fills_at_that_open():
    day = bars({601: (103.0, 104.0, 102.5, 103.5, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "target_gap" and px == 103.0


def test_zero_volume_bar_cannot_fill_anything():
    day = bars({601: (100.0, 102.0, 98.0, 101.0, 0),
                602: (100.0, 100.1, 99.9, 100.0, 10),
                630: (100.5, 100.6, 100.4, 100.5, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "time" and minute == 630


def test_missing_minute_is_skipped_never_backdated():
    day = bars({605: (100.0, 100.1, 99.95, 100.0, 10),
                630: (100.4, 100.5, 100.3, 100.4, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "time" and minute == 630 and px == 100.4


def test_time_exit_searches_forward_then_gives_up():
    day = bars({635: (100.4, 100.5, 100.3, 100.4, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "time" and minute == 635
    assert walk_trade(bars({}), 1, 600, 100.0, 99.0, 101.0, 30) is None
    # an exit more than TIME_EXIT_SEARCH minutes late is not a 30-minute hold;
    # it is reported as unresolvable rather than filled at a fictional price
    late = bars({630 + TIME_EXIT_SEARCH + 1: (100.0, 100.0, 100.0, 100.0, 10)})
    assert walk_trade(late, 1, 600, 100.0, 99.0, 101.0, 30) is None


def test_short_side_mirrors_the_long_side():
    day = bars({601: (100.0, 101.5, 99.8, 101.0, 10)})
    px, minute, kind = walk_trade(day, -1, 600, 100.0, 101.0, 99.0, 30)
    assert kind == "stop" and px == 101.0
    day2 = bars({601: (100.0, 100.2, 98.5, 98.6, 10)})
    px2, _m, kind2 = walk_trade(day2, -1, 600, 100.0, 101.0, 99.0, 30)
    assert kind2 == "target" and px2 == 99.0


def test_exit_never_happens_in_the_entry_minute_itself():
    """A bar at the entry minute must not be used for the exit."""
    day = bars({600: (100.0, 105.0, 95.0, 100.0, 10),
                630: (100.2, 100.3, 100.1, 100.2, 10)})
    _px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "time" and minute == 630


# --------------------------------------------------------------------------
# run_rule - selection, confirmation and timing
# --------------------------------------------------------------------------
POLICY = {
    "per_side_cap": 2, "target_k": 1.5, "stop_k": 1.0,
    "hold_minutes": 30, "cost_bps": 20.0, "short_borrow_bps_per_hold": 5.48,
    "entry_minute_direct": 601, "entry_minute_confirmed": 602,
    "stab_minute_1": 600, "stab_minute_2": 601,
}
RULE_DIRECT_DOWN = {"move": "down", "direction": "long", "confirmed": False}
RULE_CONF_DOWN = {"move": "down", "direction": "long", "confirmed": True}


def make_panel(dev=-0.03, risk_unit=0.02, win_low=99.0, win_high=101.0,
               p1=99.5, extreme_bar=0.01):
    return pd.DataFrame([{
        "date": "2024-01-02", "symbol": "AAA", "eligible": True, "dev": dev,
        "extreme_down": dev <= -extreme_bar, "extreme_up": dev >= extreme_bar,
        "extreme_bar": extreme_bar, "risk_unit": risk_unit, "p1": p1,
        "win_low": win_low, "win_high": win_high,
        "win_dollar_volume": 5e6, "pre_entry_minute_dollar_volume": 2e5,
    }])


def make_bars(rows):
    return pd.DataFrame(
        [{"date": "2024-01-02", "symbol": "AAA", "minute": m,
          "open": o, "high": h, "low": lo, "close": c, "volume": v}
         for m, (o, h, lo, c, v) in rows.items()])


def test_direct_rule_enters_at_the_frozen_minute_and_prices_from_it():
    b = make_bars({601: (100.0, 100.2, 99.9, 100.1, 500),
                   631: (100.6, 100.7, 100.5, 100.6, 500)})
    t = run_rule(make_panel(), bar_lookup(b), POLICY, RULE_DIRECT_DOWN)
    assert len(t) == 1
    row = t.iloc[0]
    assert row.entry_minute == 601 and row.entry_px == 100.0
    # target = entry * (1 + 1.0 * 0.02), stop = entry * (1 - 0.5 * 0.02)
    # target = entry * (1 + 1.5 * 0.02), stop = entry * (1 - 1.0 * 0.02)
    assert row.target_px == pytest.approx(103.0)
    assert row.stop_px == pytest.approx(98.0)
    assert row.exit_kind == "time"
    assert row.gross_bps == pytest.approx(60.0, abs=0.1)
    assert row.net_bps == pytest.approx(40.0, abs=0.1)


def test_missing_entry_bar_produces_no_trade():
    b = make_bars({602: (100.0, 100.2, 99.9, 100.1, 500),
                   631: (100.6, 100.7, 100.5, 100.6, 500)})
    assert run_rule(make_panel(), bar_lookup(b), POLICY, RULE_DIRECT_DOWN).empty


def test_zero_volume_entry_bar_produces_no_trade():
    b = make_bars({601: (100.0, 100.2, 99.9, 100.1, 0),
                   631: (100.6, 100.7, 100.5, 100.6, 500)})
    assert run_rule(make_panel(), bar_lookup(b), POLICY, RULE_DIRECT_DOWN).empty


def test_confirmed_rule_needs_both_stabilisation_bars_and_enters_later():
    ok = make_bars({600: (99.5, 99.8, 99.2, 99.6, 500),
                    601: (99.6, 99.9, 99.4, 99.8, 500),  # close 99.8 > p1 99.5
                    602: (100.0, 100.2, 99.9, 100.1, 500),
                    632: (100.6, 100.7, 100.5, 100.6, 500)})
    t = run_rule(make_panel(), bar_lookup(ok), POLICY, RULE_CONF_DOWN)
    assert len(t) == 1 and t.iloc[0].entry_minute == 602


def test_confirmed_rule_rejects_a_new_low_in_a_stabilisation_bar():
    bad = make_bars({600: (99.5, 99.8, 98.4, 99.6, 500),   # new low below win_low 99.0
                     601: (99.6, 99.9, 99.4, 99.8, 500),
                     602: (100.0, 100.2, 99.9, 100.1, 500),
                     632: (100.6, 100.7, 100.5, 100.6, 500)})
    assert run_rule(make_panel(), bar_lookup(bad), POLICY, RULE_CONF_DOWN).empty


def test_confirmed_rule_rejects_a_price_that_has_not_turned_back():
    """Both bars make no new low, but the price never recovers above P1."""
    flat = make_bars({600: (99.3, 99.4, 99.2, 99.3, 500),
                      601: (99.3, 99.4, 99.1, 99.2, 500),  # close 99.2 < p1 99.5
                      602: (99.3, 99.4, 99.2, 99.3, 500),
                      632: (99.5, 99.6, 99.4, 99.5, 500)})
    assert run_rule(make_panel(), bar_lookup(flat), POLICY, RULE_CONF_DOWN).empty


def test_confirmed_rule_rejects_a_missing_stabilisation_bar():
    bad = make_bars({601: (99.6, 99.9, 99.4, 99.8, 500),
                     602: (100.0, 100.2, 99.9, 100.1, 500),
                     632: (100.6, 100.7, 100.5, 100.6, 500)})
    assert run_rule(make_panel(), bar_lookup(bad), POLICY, RULE_CONF_DOWN).empty


def test_short_rule_pays_the_borrow_charge_and_the_long_rule_does_not():
    b = make_bars({601: (100.0, 100.2, 99.9, 100.1, 500),
                   631: (100.0, 100.1, 99.9, 100.0, 500)})
    short_rule = {"move": "up", "direction": "short", "confirmed": False}
    panel = make_panel(dev=0.03)
    t = run_rule(panel, bar_lookup(b), POLICY, short_rule)
    assert t.iloc[0].net_bps == pytest.approx(-25.48, abs=0.05)
    t2 = run_rule(make_panel(), bar_lookup(b), POLICY, RULE_DIRECT_DOWN)
    assert t2.iloc[0].net_bps == pytest.approx(-20.0, abs=0.05)


def test_entry_delay_moves_the_entry_minute():
    b = make_bars({601: (100.0, 100.2, 99.9, 100.1, 500),
                   603: (100.3, 100.4, 100.2, 100.3, 500),
                   633: (100.9, 101.0, 100.8, 100.9, 500)})
    t = run_rule(make_panel(), bar_lookup(b), POLICY, RULE_DIRECT_DOWN, entry_delay=2)
    assert t.iloc[0].entry_minute == 603 and t.iloc[0].entry_px == 100.3


def test_only_the_most_extreme_two_per_side_are_taken():
    rows = []
    for i, dev in enumerate([-0.011, -0.02, -0.03, -0.04]):
        rows.append({"date": "2024-01-02", "symbol": f"S{i}", "eligible": True,
                     "dev": dev, "extreme_down": True, "extreme_up": False,
                     "extreme_bar": 0.01, "risk_unit": 0.02, "p1": 99.5,
                     "win_low": 99.0, "win_high": 101.0,
                     "win_dollar_volume": 5e6,
                     "pre_entry_minute_dollar_volume": 2e5})
    panel = pd.DataFrame(rows)
    bl = []
    for i in range(4):
        for m, (o, h, lo, c, v) in {601: (100.0, 100.2, 99.9, 100.1, 500),
                                    631: (100.1, 100.2, 100.0, 100.1, 500)}.items():
            bl.append({"date": "2024-01-02", "symbol": f"S{i}", "minute": m,
                       "open": o, "high": h, "low": lo, "close": c, "volume": v})
    t = run_rule(panel, bar_lookup(pd.DataFrame(bl)), POLICY, RULE_DIRECT_DOWN)
    assert sorted(t.symbol) == ["S2", "S3"]


def test_a_below_threshold_move_is_never_selected():
    assert run_rule(make_panel(dev=-0.009), bar_lookup(make_bars(
        {601: (100.0, 100.2, 99.9, 100.1, 500),
         631: (100.6, 100.7, 100.5, 100.6, 500)})), POLICY, RULE_DIRECT_DOWN).empty


def test_the_final_held_minute_is_the_timed_exit_and_nothing_else():
    """A level touched inside the last held minute never reaches the trader:
    he is already out at that bar's open."""
    day = bars({630: (100.2, 105.0, 95.0, 100.3, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "time" and minute == 630 and px == 100.2


def test_a_stop_one_minute_before_the_end_still_counts():
    day = bars({629: (100.0, 100.1, 98.0, 98.5, 10),
                630: (100.2, 100.3, 100.1, 100.2, 10)})
    px, minute, kind = walk_trade(day, 1, 600, 100.0, 99.0, 101.0, 30)
    assert kind == "stop" and minute == 629 and px == 99.0
