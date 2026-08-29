"""Mechanics tests for the TODO #106 research simulator.

Hand-built bars only.  No real market data, no real return: this checks the
frozen fill rules do what `mechanical-definitions.md` section 8 says.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/research"))

import pdtm_engine as E  # noqa: E402


class FakePanel:
    def __init__(self, o, h, l, c):
        f = lambda x: np.array([x], dtype=np.float32)
        self.o, self.h, self.l, self.c = f(o), f(h), f(l), f(c)


def _panel(bars):
    """bars: list of (open, high, low, close) or None for a minute that never traded."""
    n = 390
    o, h, l, c = ([np.nan] * n for _ in range(4))
    for i, b in enumerate(bars):
        if b is not None:
            o[i], h[i], l[i], c[i] = b
    return FakePanel(o, h, l, c)


def _sig(**kw):
    base = dict(row=0, symbol="X", date="2024-01-02", sector="S",
                method="T", side=1, confirm_min=0, stop=99.0, target=101.5,
                risk_frac=0.01)
    base.update(kw)
    return pd.DataFrame([base])


def test_entry_is_the_open_of_the_next_traded_minute():
    p = _panel([(100, 100, 100, 100), None, (98, 102, 98, 101)] + [None] * 387)
    t = E.simulate(p, _sig(confirm_min=0), 0.0)
    assert t.entry_min.iloc[0] == 2          # minute 1 never traded
    assert t.entry_px.iloc[0] == pytest.approx(98.0)


def test_stop_wins_when_stop_and_target_are_both_touched_in_one_bar():
    p = _panel([(100, 100, 100, 100), (100, 102, 98, 100)] + [None] * 388)
    t = E.simulate(p, _sig(stop=99.0, target=101.0), 0.0)
    assert t.exit_reason.iloc[0] == "stop"
    assert t.exit_px.iloc[0] == pytest.approx(99.0)


def test_a_gap_through_the_stop_exits_at_the_real_print_not_the_stop():
    p = _panel([(100, 100, 100, 100), (100, 100, 100, 100), (95, 96, 94, 95)] + [None] * 387)
    t = E.simulate(p, _sig(confirm_min=0, stop=99.0, target=110.0), 0.0)
    assert t.exit_reason.iloc[0] == "stop"
    assert t.exit_px.iloc[0] == pytest.approx(95.0)   # not 99.0


def test_time_exit_uses_the_last_real_trade_at_or_before_1255_pacific():
    bars = [None] * 390
    bars[0] = (100, 100, 100, 100)
    bars[1] = (100, 100, 100, 100)
    bars[E.LAST_EXIT_MIN] = (103, 103, 103, 103)
    bars[E.LAST_EXIT_MIN + 1] = (200, 200, 200, 200)   # after the cut-off
    t = E.simulate(_panel(bars), _sig(confirm_min=0, stop=50.0, target=999.0), 0.0)
    assert t.exit_reason.iloc[0] == "time"
    assert t.exit_px.iloc[0] == pytest.approx(103.0)


def test_cost_is_charged_once_per_completed_trade():
    p = _panel([(100, 100, 100, 100), (100, 102, 100, 102)] + [None] * 388)
    a = E.simulate(p, _sig(stop=90.0, target=101.0), 0.0)
    b = E.simulate(p, _sig(stop=90.0, target=101.0), 20.0)
    assert a.gross.iloc[0] == pytest.approx(b.gross.iloc[0])
    assert a.net.iloc[0] - b.net.iloc[0] == pytest.approx(0.0020)


def test_short_side_mirrors_the_long_side():
    p = _panel([(100, 100, 100, 100), (100, 100, 98, 98)] + [None] * 388)
    t = E.simulate(p, _sig(side=-1, stop=110.0, target=99.0), 0.0)
    assert t.exit_reason.iloc[0] == "target"
    assert t.gross.iloc[0] == pytest.approx(0.01)      # 100 -> 99 short = +1%


def test_stress_entry_delays_by_one_traded_minute():
    p = _panel([(100, 100, 100, 100), (101, 101, 101, 101), (102, 102, 102, 102)] + [None] * 387)
    t0 = E.simulate(p, _sig(confirm_min=0, stop=50.0, target=999.0), 0.0, entry_delay=0)
    t1 = E.simulate(p, _sig(confirm_min=0, stop=50.0, target=999.0), 0.0, entry_delay=1)
    assert t0.entry_px.iloc[0] == pytest.approx(101.0)
    assert t1.entry_px.iloc[0] == pytest.approx(102.0)


def test_one_position_per_company_per_day_discards_the_overlap():
    trades = pd.DataFrame([
        dict(symbol="X", date="2024-01-02", entry_min=10, exit_min=60, net=0.01),
        dict(symbol="X", date="2024-01-02", entry_min=30, exit_min=90, net=0.01),
        dict(symbol="X", date="2024-01-02", entry_min=70, exit_min=100, net=0.01),
        dict(symbol="Y", date="2024-01-02", entry_min=30, exit_min=90, net=0.01),
    ])
    kept = E.one_position_per_symbol(trades)
    assert len(kept) == 3
    assert list(kept[kept.symbol == "X"].entry_min) == [10, 70]
