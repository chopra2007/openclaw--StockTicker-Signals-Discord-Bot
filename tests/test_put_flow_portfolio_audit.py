"""Focused tests for the TODO #96 portfolio audit (scripts/research/put_flow_portfolio_audit.py).

Uses small synthetic fixtures with hand-calculated expected numbers -- no
dependency on the real 181-trade dataset, so these tests stay meaningful even
if the underlying research data changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from research import put_flow_portfolio_audit as mod  # noqa: E402


LEG_NOTIONAL = 6250.0   # 1/16 of a $100,000 starting capital
COST_PCT = 0.0025


def write_bars(tmp_path: Path, ticker: str, day_prices: dict[str, dict[str, float]]) -> None:
    (tmp_path / f"{ticker}.bars5m.json").write_text(json.dumps(day_prices))


@pytest.fixture(autouse=True)
def isolated_bars_dir(tmp_path, monkeypatch):
    """Point the module at a scratch bars directory and clear its caches."""
    monkeypatch.setattr(mod, "BARS_DIR", tmp_path)
    mod._bars_cache.clear()
    mod._daily_cache.clear()
    yield tmp_path
    mod._bars_cache.clear()
    mod._daily_cache.clear()


def two_position_fixture(tmp_path: Path):
    """AAA (short wins) and BBB (short loses), both open 2026-01-05->2026-01-06.

    Hand-calculated at leg_notional=$6,250, cost=0.25%, borrow=0%:
      A: stock -10%, SPY +1%  -> pair_net = 0.01 - (-0.10) - 0.0025 = 0.1075
                                   realized_pnl = 6250 * 0.1075 = 671.875
      B: stock +10%, SPY +1%  -> pair_net = 0.01 - 0.10 - 0.0025 = -0.0925
                                   realized_pnl = 6250 * -0.0925 = -578.125
      combined realized = 93.75  -> final equity = 100,093.75 on $100,000 capital
    """
    write_bars(tmp_path, "AAA", {"2026-01-05": {"09:35": 100.0}, "2026-01-06": {"09:35": 90.0}})
    write_bars(tmp_path, "BBB", {"2026-01-05": {"09:35": 50.0}, "2026-01-06": {"09:35": 55.0}})
    write_bars(tmp_path, "SPY", {"2026-01-05": {"09:35": 200.0}, "2026-01-06": {"09:35": 202.0}})
    a = {"ticker": "AAA", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-06", "rank": 1,
         "stock_entry_px": 100.0, "stock_exit_px": 90.0,
         "spy_entry_px": 200.0, "spy_exit_px": 202.0}
    b = {"ticker": "BBB", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-06", "rank": 2,
         "stock_entry_px": 50.0, "stock_exit_px": 55.0,
         "spy_entry_px": 200.0, "spy_exit_px": 202.0}
    return [a, b]


def test_hand_calculated_equity_curve(tmp_path):
    trades = two_position_fixture(tmp_path)
    calendar = ["2026-01-05", "2026-01-06"]
    port = mod.build_portfolio(trades, calendar, capital=100000.0,
                                leg_notional=LEG_NOTIONAL, cost_pct=COST_PCT, borrow_pct=0.0)

    by_ticker = {p["ticker"]: p for p in port["positions"]}
    assert by_ticker["AAA"]["realized_pnl"] == pytest.approx(671.875, abs=1e-6)
    assert by_ticker["BBB"]["realized_pnl"] == pytest.approx(-578.125, abs=1e-6)

    assert port["final_equity"] == pytest.approx(100093.75, abs=1e-6)
    assert port["cumulative_net_return_pct"] == pytest.approx(0.09375, abs=1e-9)

    rows = {r["date"]: r for r in port["equity_rows"]}
    # entry day: both positions have paid their entry-day cost, nothing else moved yet
    assert rows["2026-01-05"]["equity"] == pytest.approx(100000 - 2 * LEG_NOTIONAL * COST_PCT, abs=1e-6)
    # exit day: both realized P&Ls are banked
    assert rows["2026-01-06"]["equity"] == pytest.approx(100093.75, abs=1e-6)


def test_overlap_both_positions_count_on_shared_open_day(tmp_path):
    """Two positions open on the same day both contribute to that day's exposure."""
    trades = two_position_fixture(tmp_path)
    calendar = ["2026-01-05", "2026-01-06"]
    port = mod.build_portfolio(trades, calendar, capital=100000.0,
                                leg_notional=LEG_NOTIONAL, cost_pct=COST_PCT, borrow_pct=0.0)
    rows = {r["date"]: r for r in port["equity_rows"]}
    # entry day: both A and B are open (neither has exited yet) -> 2 pairs, $25,000 gross
    assert rows["2026-01-05"]["open_pairs"] == 2
    assert rows["2026-01-05"]["gross_exposure"] == pytest.approx(2 * 2 * LEG_NOTIONAL, abs=1e-6)
    # exit day: both close, so capacity (exclusive-of-exit) is back to zero that morning
    assert rows["2026-01-06"]["open_pairs"] == 0


def test_cost_charged_exactly_once_per_pair(tmp_path):
    trades = two_position_fixture(tmp_path)
    marks = mod.position_daily_marks(trades[0], LEG_NOTIONAL, COST_PCT, 0.0, "09:35")
    # stock_ret=-0.10, spy_ret=+0.01 -> pre-cost pnl = 6250*(0.10+0.01)=687.5
    # realized = 687.5 - 6250*0.0025 = 671.875, i.e. cost hit exactly once
    pre_cost_pnl = LEG_NOTIONAL * (0.10 + 0.01)
    assert marks["2026-01-06"] == pytest.approx(pre_cost_pnl - LEG_NOTIONAL * COST_PCT, abs=1e-9)
    # if cost were charged twice, the number below would NOT match
    assert marks["2026-01-06"] != pytest.approx(pre_cost_pnl - 2 * LEG_NOTIONAL * COST_PCT, abs=1e-9)


def test_borrow_stress_reduces_profit_and_uses_correct_day_count(tmp_path):
    trades = two_position_fixture(tmp_path)
    marks_0 = mod.position_daily_marks(trades[0], LEG_NOTIONAL, COST_PCT, 0.0, "09:35")
    marks_20 = mod.position_daily_marks(trades[0], LEG_NOTIONAL, COST_PCT, 20.0, "09:35")
    # held exactly 1 calendar day (2026-01-05 -> 2026-01-06)
    expected_borrow_charge = LEG_NOTIONAL * 0.20 * 1 / 365.0
    assert marks_0["2026-01-06"] - marks_20["2026-01-06"] == pytest.approx(expected_borrow_charge, abs=1e-9)
    # borrow always REDUCES the realized dollar profit, never adds to it
    assert marks_20["2026-01-06"] < marks_0["2026-01-06"]


def test_borrow_direction_hurts_even_a_losing_short(tmp_path):
    """Borrow is charged on the short leg's notional regardless of whether the
    trade won or lost -- it should make BBB's already-negative result worse."""
    trades = two_position_fixture(tmp_path)
    b = trades[1]
    marks_0 = mod.position_daily_marks(b, LEG_NOTIONAL, COST_PCT, 0.0, "09:35")
    marks_20 = mod.position_daily_marks(b, LEG_NOTIONAL, COST_PCT, 20.0, "09:35")
    assert marks_20["2026-01-06"] < marks_0["2026-01-06"]


def test_no_future_information(tmp_path):
    """A position's marks never reach past its own exit_date, even if a later
    (wrong) price exists in the bars file."""
    write_bars(tmp_path, "AAA", {
        "2026-01-05": {"09:35": 100.0},
        "2026-01-06": {"09:35": 90.0},
        "2026-01-07": {"09:35": 1.0},   # a deliberately absurd future price
    })
    write_bars(tmp_path, "SPY", {
        "2026-01-05": {"09:35": 200.0},
        "2026-01-06": {"09:35": 202.0},
        "2026-01-07": {"09:35": 999.0},  # a deliberately absurd future price
    })
    a = {"ticker": "AAA", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-06", "rank": 1,
         "stock_entry_px": 100.0, "stock_exit_px": 90.0,
         "spy_entry_px": 200.0, "spy_exit_px": 202.0}
    marks = mod.position_daily_marks(a, LEG_NOTIONAL, COST_PCT, 0.0, "09:35")
    assert set(marks) == {"2026-01-05", "2026-01-06"}
    assert marks["2026-01-06"] == pytest.approx(671.875, abs=1e-6)


def test_missing_required_mark_is_a_hard_error_not_a_fill(tmp_path):
    """A missing intermediate mark must raise, never silently reuse a nearby
    or last-known price."""
    write_bars(tmp_path, "AAA", {
        "2026-01-05": {"09:35": 100.0},
        "2026-01-06": {},   # missing the 09:35 mark entirely
        "2026-01-07": {"09:35": 90.0},
    })
    write_bars(tmp_path, "SPY", {
        "2026-01-05": {"09:35": 200.0},
        "2026-01-06": {"09:35": 201.0},
        "2026-01-07": {"09:35": 202.0},
    })
    a = {"ticker": "AAA", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-07", "rank": 1,
         "stock_entry_px": 100.0, "stock_exit_px": 90.0,
         "spy_entry_px": 200.0, "spy_exit_px": 202.0}
    with pytest.raises(ValueError):
        mod.position_daily_marks(a, LEG_NOTIONAL, COST_PCT, 0.0, "09:35")


def test_admission_overflow_rule_rank_then_date(tmp_path):
    """Capacity of 2: on one shared entry date, rank 1 and 2 are admitted,
    rank 3 is rejected as overflow."""
    trades = [
        {"ticker": "AAA", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-07", "rank": 1},
        {"ticker": "BBB", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-07", "rank": 2},
        {"ticker": "CCC", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-07", "rank": 3},
    ]
    admitted, overflow = mod.admit_positions(trades, cap=2, no_stacking=False)
    assert {t["ticker"] for t in admitted} == {"AAA", "BBB"}
    assert [t["ticker"] for t in overflow] == ["CCC"]
    assert overflow[0]["overflow_reason"] == "capacity_full"


def test_admission_frees_slot_on_exit_day_before_new_entrants(tmp_path):
    """A slot vacated by an exit on day D is available to a new entrant that
    also starts on day D (same-morning turnover)."""
    trades = [
        {"ticker": "AAA", "market_date": "2026-01-01", "entry_date": "2026-01-02",
         "exit_date": "2026-01-06", "rank": 1},
        {"ticker": "BBB", "market_date": "2026-01-01", "entry_date": "2026-01-02",
         "exit_date": "2026-01-06", "rank": 2},
        # both slots free again on 2026-01-06 -> CCC and DDD should both fit
        {"ticker": "CCC", "market_date": "2026-01-05", "entry_date": "2026-01-06",
         "exit_date": "2026-01-08", "rank": 1},
        {"ticker": "DDD", "market_date": "2026-01-05", "entry_date": "2026-01-06",
         "exit_date": "2026-01-08", "rank": 2},
    ]
    admitted, overflow = mod.admit_positions(trades, cap=2, no_stacking=False)
    assert {t["ticker"] for t in admitted} == {"AAA", "BBB", "CCC", "DDD"}
    assert overflow == []


def test_no_stacking_control_removes_repeated_ticker(tmp_path):
    """The no-stacking control rejects a second signal on a ticker that
    already has an open admitted position, even with capacity to spare."""
    trades = [
        {"ticker": "AAA", "market_date": "2026-01-01", "entry_date": "2026-01-02",
         "exit_date": "2026-01-08", "rank": 1},
        # a repeat signal on AAA while the first is still open
        {"ticker": "AAA", "market_date": "2026-01-04", "entry_date": "2026-01-05",
         "exit_date": "2026-01-09", "rank": 1},
    ]
    admitted_stack, _ = mod.admit_positions(trades, cap=16, no_stacking=False)
    admitted_nostack, rejected_nostack = mod.admit_positions(trades, cap=16, no_stacking=True)

    assert len(admitted_stack) == 2          # stacking allows both dated positions
    assert len(admitted_nostack) == 1        # no-stacking keeps only the first
    assert admitted_nostack[0]["entry_date"] == "2026-01-02"
    assert len(rejected_nostack) == 1
    assert rejected_nostack[0]["overflow_reason"] == "ticker_already_open_no_stacking"


def test_no_stacking_control_admits_after_the_first_closes(tmp_path):
    """Once the first position on a ticker has exited, a later signal on the
    same ticker is admitted again under no-stacking."""
    trades = [
        {"ticker": "AAA", "market_date": "2026-01-01", "entry_date": "2026-01-02",
         "exit_date": "2026-01-05", "rank": 1},
        {"ticker": "AAA", "market_date": "2026-01-05", "entry_date": "2026-01-06",
         "exit_date": "2026-01-09", "rank": 1},
    ]
    admitted, rejected = mod.admit_positions(trades, cap=16, no_stacking=True)
    assert len(admitted) == 2
    assert rejected == []
