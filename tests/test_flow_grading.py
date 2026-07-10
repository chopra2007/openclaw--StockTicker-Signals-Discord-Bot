"""#57: grading stored options-flow hits — event dedup, direction, market adjustment."""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

from consensus_engine import db

_SPEC = importlib.util.spec_from_file_location(
    "grade_options_flow",
    Path(__file__).resolve().parent.parent / "scripts" / "grade_options_flow.py",
)
grader = importlib.util.module_from_spec(_SPEC)
sys.modules["grade_options_flow"] = grader
_SPEC.loader.exec_module(grader)


# --- trading-day indexing ---------------------------------------------------

BARS = {   # a week with a weekend gap: Fri 06-05 then Mon 06-08
    "2026-06-01": 100.0, "2026-06-02": 101.0, "2026-06-03": 102.0,
    "2026-06-04": 103.0, "2026-06-05": 104.0, "2026-06-08": 105.0,
    "2026-06-09": 106.0,
}


def test_bar_zero_is_the_hit_session():
    assert grader.close_n_trading_days_later(BARS, "2026-06-01", 0) == 100.0


def test_horizon_skips_the_weekend():
    # 5 trading days after Mon 06-01 is Mon 06-08, not Sat 06-06.
    assert grader.close_n_trading_days_later(BARS, "2026-06-01", 5) == 105.0


def test_window_not_yet_elapsed_returns_none():
    assert grader.close_n_trading_days_later(BARS, "2026-06-08", 5) is None


def test_hit_outside_a_session_rolls_to_next_bar():
    # 2026-06-06 is a Saturday; bar 0 becomes Mon 06-08.
    assert grader.close_n_trading_days_later(BARS, "2026-06-06", 0) == 105.0


def test_no_bars_returns_none():
    assert grader.close_n_trading_days_later({}, "2026-06-01", 1) is None


# --- market adjustment ------------------------------------------------------

def test_excess_move_subtracts_the_benchmark():
    row = {"close_0d": 100.0, "close_5d": 110.0,      # ticker +10%
           "bench_close_0d": 200.0, "bench_close_5d": 208.0}   # SPY +4%
    assert grader.excess_move(row, 5) == pytest.approx(0.06)


def test_excess_move_is_negative_when_the_stock_lags_a_rising_market():
    row = {"close_0d": 100.0, "close_5d": 102.0,
           "bench_close_0d": 100.0, "bench_close_5d": 108.0}
    assert grader.excess_move(row, 5) == pytest.approx(-0.06)


def test_a_stock_that_falls_less_than_the_market_still_beat_it():
    """The whole point of the benchmark: June fell, so a raw loss can be a win."""
    row = {"close_0d": 100.0, "close_5d": 98.0,        # -2%
           "bench_close_0d": 100.0, "bench_close_5d": 95.0}   # SPY -5%
    assert grader.excess_move(row, 5) > 0


def test_excess_move_none_when_a_leg_is_missing():
    assert grader.excess_move(
        {"close_0d": 100.0, "close_5d": None,
         "bench_close_0d": 100.0, "bench_close_5d": 105.0}, 5) is None
    assert grader.excess_move(
        {"close_0d": 100.0, "close_5d": 105.0,
         "bench_close_0d": None, "bench_close_5d": 105.0}, 5) is None


# --- the luck test ----------------------------------------------------------

def test_identical_rates_score_zero():
    assert grader._z_two_prop(50, 100, 50, 100) == pytest.approx(0.0)


def test_thin_samples_refuse_to_answer():
    assert grader._z_two_prop(4, 5, 1, 5) is None
    assert grader._z_two_prop(50, 100, 1, 5) is None


def test_a_big_clean_gap_clears_the_bar():
    z = grader._z_two_prop(70, 100, 30, 100)
    assert z is not None and z > 1.96


def test_sign_follows_the_call_leg():
    assert grader._z_two_prop(30, 100, 70, 100) < 0


# --- direction grading + event dedup (DB) -----------------------------------

async def _insert_flow(**kw):
    conn = await db.get_db()
    cur = await conn.execute(
        """INSERT INTO options_flow (ticker, side, strike, expiry, volume,
             open_interest, vol_oi_ratio, premium_usd, last_trade_ts, spot,
             contract_symbol, alerted, detected_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (kw["ticker"], kw["side"], 100.0, "2026-06-19", 1000, 50, 20.0,
         500_000.0, kw["detected_at"], kw["spot"], kw["contract_symbol"],
         kw.get("alerted", 0), kw["detected_at"]),
    )
    await conn.commit()
    return cur.lastrowid


async def _outcome(flow_id):
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM options_flow_outcomes WHERE flow_id=?", (flow_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


@pytest.mark.parametrize("side,close,expect_win", [
    ("CALL", 110.0, 1),   # call, stock rose
    ("CALL", 90.0, 0),    # call, stock fell
    ("PUT", 90.0, 1),     # put, stock fell
    ("PUT", 110.0, 0),    # put, stock rose
    ("CALL", 100.0, 0),   # flat move predicts nothing -> loss for both
    ("PUT", 100.0, 0),
])
async def test_direction_grading(side, close, expect_win):
    await db.init_db()
    fid = await _insert_flow(ticker="AAA", side=side, spot=100.0,
                             contract_symbol=f"AAA{side}{close}",
                             detected_at=time.time() - 20 * 86400)
    await db.upsert_flow_outcome(
        flow_id=fid, ticker="AAA", side=side, contract_symbol="c",
        market_date="2026-06-10", detected_at=1.0, entry_spot=100.0,
        close_0d=100.0, close_1d=close, close_5d=close,
    )
    row = await _outcome(fid)
    assert row["win_1d"] == expect_win
    assert row["win_5d"] == expect_win
    await db.close_db()


async def test_null_close_leaves_the_horizon_ungraded():
    await db.init_db()
    fid = await _insert_flow(ticker="BBB", side="CALL", spot=100.0,
                             contract_symbol="BBBC",
                             detected_at=time.time() - 20 * 86400)
    await db.upsert_flow_outcome(
        flow_id=fid, ticker="BBB", side="CALL", contract_symbol="c",
        market_date="2026-06-10", detected_at=1.0, entry_spot=100.0,
        close_0d=100.0, close_1d=110.0, close_5d=None,
    )
    row = await _outcome(fid)
    assert row["win_1d"] == 1
    assert row["win_5d"] is None and row["close_5d"] is None
    await db.close_db()


async def test_refill_fills_the_null_without_clobbering_the_filled():
    await db.init_db()
    fid = await _insert_flow(ticker="CCC", side="CALL", spot=100.0,
                             contract_symbol="CCCC",
                             detected_at=time.time() - 20 * 86400)
    common = dict(flow_id=fid, ticker="CCC", side="CALL", contract_symbol="c",
                  market_date="2026-06-10", detected_at=1.0, entry_spot=100.0,
                  close_0d=100.0, close_1d=110.0)
    await db.upsert_flow_outcome(**common, close_5d=None)
    await db.upsert_flow_outcome(**common, close_5d=120.0)   # horizon now elapsed
    row = await _outcome(fid)
    assert row["close_1d"] == 110.0 and row["win_1d"] == 1
    assert row["close_5d"] == 120.0 and row["win_5d"] == 1
    await db.close_db()


async def test_repeated_detections_of_one_contract_collapse_to_one_event():
    """The scanner re-detects a live contract every poll cycle. Grading must count
    that once, at its FIRST detection (the spot a trader could have acted on)."""
    await db.init_db()
    base = 1780_400_000.0   # a Monday inside US market hours
    first = await _insert_flow(ticker="DDD", side="CALL", spot=100.0,
                               contract_symbol="DDD260619C00100000",
                               detected_at=base)
    for i in range(1, 12):   # 11 more cycles, drifting spot
        await _insert_flow(ticker="DDD", side="CALL", spot=100.0 + i,
                           contract_symbol="DDD260619C00100000",
                           detected_at=base + i * 300)

    events = await db.get_flow_events()
    ddd = [e for e in events if e["ticker"] == "DDD"]
    assert len(ddd) == 1, f"expected 1 event, got {len(ddd)}"
    assert ddd[0]["flow_id"] == first
    assert ddd[0]["spot"] == 100.0      # entry = first sighting, not the last
    await db.close_db()


async def test_the_same_contract_on_a_new_day_is_a_new_event():
    await db.init_db()
    base = 1780_400_000.0
    await _insert_flow(ticker="EEE", side="CALL", spot=100.0,
                       contract_symbol="EEE260619C00100000", detected_at=base)
    await _insert_flow(ticker="EEE", side="CALL", spot=105.0,
                       contract_symbol="EEE260619C00100000",
                       detected_at=base + 86400)
    events = [e for e in await db.get_flow_events() if e["ticker"] == "EEE"]
    assert len(events) == 2
    assert {e["market_date"] for e in events} == {
        e["market_date"] for e in events}   # distinct dates
    assert len({e["market_date"] for e in events}) == 2
    await db.close_db()


async def test_ungraded_only_skips_fully_graded_events():
    await db.init_db()
    old = time.time() - 30 * 86400
    fid = await _insert_flow(ticker="FFF", side="CALL", spot=100.0,
                             contract_symbol="FFFC", detected_at=old)
    assert any(e["flow_id"] == fid for e in await db.get_flow_events(ungraded_only=True))
    await db.upsert_flow_outcome(
        flow_id=fid, ticker="FFF", side="CALL", contract_symbol="FFFC",
        market_date="2026-06-10", detected_at=old, entry_spot=100.0,
        close_0d=100.0, close_1d=110.0, close_5d=120.0,
    )
    assert not any(e["flow_id"] == fid for e in await db.get_flow_events(ungraded_only=True))
    await db.close_db()


async def test_partially_graded_event_stays_eligible_for_refill():
    await db.init_db()
    old = time.time() - 30 * 86400
    fid = await _insert_flow(ticker="GGG", side="PUT", spot=100.0,
                             contract_symbol="GGGP", detected_at=old)
    await db.upsert_flow_outcome(
        flow_id=fid, ticker="GGG", side="PUT", contract_symbol="GGGP",
        market_date="2026-06-10", detected_at=old, entry_spot=100.0,
        close_0d=100.0, close_1d=95.0, close_5d=None,
    )
    assert any(e["flow_id"] == fid for e in await db.get_flow_events(ungraded_only=True))
    await db.close_db()


async def test_zero_spot_rows_are_never_graded():
    """spot=0 would make every return infinite."""
    await db.init_db()
    await _insert_flow(ticker="HHH", side="CALL", spot=0.0,
                       contract_symbol="HHHC", detected_at=time.time() - 30 * 86400)
    assert not [e for e in await db.get_flow_events() if e["ticker"] == "HHH"]
    await db.close_db()
