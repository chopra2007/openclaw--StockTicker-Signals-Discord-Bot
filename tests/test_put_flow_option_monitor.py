"""TODO #100 — the put-flow option-trade OBSERVER.

Every test uses a temporary database via ``consensus_engine.db.DB_PATH`` and
never touches the network: the live Schwab poll is injected as ``quote_fn`` and
the clock / sleep are injected too, so a whole 6.5-hour session runs in
milliseconds.

Covers: deterministic contract selection and each tie-break; NO_OPTION_TRADE on
every liquidity gate; long-PUT and spread entry / liquidation math; one and two
leg commissions; a single batched quote request; the 15-second cadence with no
overlapping polls; minute aggregation; TARGET / STOP / TIME_EXIT and the
same-poll conservative STOP; stale / crossed / missing / zero-bid / delayed
quotes; restart recovery writing a visible gap; duplicate minute and event
protection; 16 overlapping positions and 32 spread legs; a market holiday and a
shortened session; Pacific timestamps; an observer failure cannot alter a
stock-pair trade; dry-run cannot write; raw chains never reach a rendered string.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.analysis import put_flow_option_monitor as mon
# captured before the _no_health fixture patches it, so a test can restore it
from consensus_engine.alerts.ops_alert import report_ops_state as _REAL_REPORT_OPS_STATE

PT = ZoneInfo("America/Los_Angeles")
ROOT_DIR = Path(__file__).resolve().parent.parent

ENTRY_SESSION = "2026-08-25"     # Tuesday
EXIT_SESSION = "2026-08-31"     # 4th NYSE session after entry
QUAL_EXPIRY = "2026-09-18"       # inside [exit+7 .. entry+45] = [2026-09-07 .. 2026-10-09]


# ─────────────────────────── fixtures ───────────────────────────

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


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    values = {
        "put_flow_shortlist.option_trade.select_enabled": True,
        "put_flow_shortlist.option_trade.monitor_enabled": True,
        "put_flow_shortlist.option_trade.poll_seconds": 15,
        "put_flow_shortlist.option_trade.quote_max_age_sec": 120,
        "put_flow_shortlist.option_trade.start_pt": "06:34",
        "put_flow_shortlist.option_trade.stop_pt": "13:01",
        "put_flow_shortlist.option_trade.min_open_interest": 100,
        "put_flow_shortlist.option_trade.max_spread_pct_of_mid": 0.10,
        "put_flow_shortlist.option_trade.commission_per_contract_side_usd": 0.45,
        "put_flow_shortlist.option_trade.max_legs": 32,
    }
    real = cfg.get
    monkeypatch.setattr(cfg, "get",
                        lambda k, d=None: values.get(k, real(k, d)))


@pytest.fixture(autouse=True)
def _no_health(monkeypatch):
    """Capture the health alert instead of hitting Discord."""
    m = AsyncMock(return_value=False)
    import consensus_engine.alerts.ops_alert as oa
    monkeypatch.setattr(oa, "report_ops_state", m)
    return m


# ─────────────────────────── seed helpers ───────────────────────────

async def seed_shortlist(ticker="NVDA", *, entry_session=ENTRY_SESSION,
                         exit_session=EXIT_SESSION, signal_date="2026-08-24",
                         entry_stock_px=240.0, status="ENTERED") -> int:
    conn = await db.get_db()
    now = time.time()
    cur = await conn.execute(
        "INSERT INTO put_flow_shortlist (signal_date, entry_session, ticker, rank, "
        "status, planned_exit_session, entry_stock_px, entry_spy_px, cost_pct, "
        "created_at, updated_at) VALUES (?,?,?,1,?,?,?,?,0.25,?,?)",
        (signal_date, entry_session, ticker, status, exit_session, entry_stock_px,
         640.0, now, now))
    await conn.commit()
    return cur.lastrowid


async def seed_contract(shortlist_id, ticker="NVDA", *, symbol, strike,
                        expiry=QUAL_EXPIRY, bid=2.0, ask=2.2, oi=500,
                        multiplier=100, non_standard=0, deliverable_note="",
                        quote_quality="OK"):
    conn = await db.get_db()
    now = time.time()
    await conn.execute(
        "INSERT OR IGNORE INTO put_flow_option_snapshots (shortlist_id, ticker, stage, "
        "capture_session, captured_at, contract_symbol, expiry, strike, option_type, "
        "bid, ask, last, mark, open_interest, multiplier, non_standard, "
        "deliverable_note, underlying_px, quote_quality, created_at) "
        "VALUES (?,?,'ENTRY',?,?,?,?,?,'PUT',?,?,?,?,?,?,?,?,?,?,?)",
        (shortlist_id, ticker, ENTRY_SESSION, now, symbol, expiry, strike,
         bid, ask, (bid + ask) / 2, (bid + ask) / 2, oi, multiplier, non_standard,
         deliverable_note, 240.0, quote_quality, now))
    await conn.commit()


async def seed_manual_selection(shortlist_id, *, structure="ATM_PUT",
                                exit_policy="PT25_SL35", long_symbol="L", short_symbol=None,
                                entry_cost=2.0, target_liq_value=2.5, stop_liq_value=1.3,
                                max_exit_session=EXIT_SESSION) -> int:
    """Insert a SELECTED row directly, for exercising monitor-only code paths."""
    conn = await db.get_db()
    now = time.time()
    cur = await conn.execute(
        "INSERT INTO put_flow_option_selections (shortlist_id, ticker, signal_date, "
        "entry_session, rule_version, rule_fingerprint, structure, long_symbol, "
        "short_symbol, expiry, entry_cost, entry_commission, target_liq_value, "
        "stop_liq_value, max_exit_session, max_exit_pt, exit_policy, selection_status, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'SELECTED',?,?)",
        (shortlist_id, "NVDA", "2026-08-24", ENTRY_SESSION, mon.RULE_VERSION,
         mon.RULE_FINGERPRINT, structure, long_symbol, short_symbol, QUAL_EXPIRY,
         entry_cost, 0.45 * (2 if short_symbol else 1), target_liq_value,
         stop_liq_value, max_exit_session, "06:35", exit_policy, now, now))
    await conn.commit()
    return cur.lastrowid


async def one_selection(structure="ATM_PUT", exit_policy="PT25_SL35",
                        strikes=((235, "N235"), (240, "N240"), (245, "N245")),
                        **ckw) -> dict:
    sid = await seed_shortlist()
    for strike, sym in strikes:
        await seed_contract(sid, symbol=sym, strike=strike, **ckw)
    return await mon.select_for_position(sid, structure=structure,
                                         exit_policy=exit_policy)


async def count(sql, params=()):
    conn = await db.get_db()
    cur = await conn.execute(sql, params)
    return (await cur.fetchone())[0]


async def rows(sql, params=()):
    conn = await db.get_db()
    cur = await conn.execute(sql, params)
    return [dict(r) for r in await cur.fetchall()]


# ─────────────────────────── fake clock / poll ───────────────────────────

class FakeClock:
    def __init__(self, start: float):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float):
        self.t += s


def pt_epoch(session: str, hhmm: str) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    d = date.fromisoformat(session)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=PT).timestamp()


def make_sleep(clock: FakeClock, log: list):
    async def _sleep(sec: float):
        log.append(sec)
        clock.advance(sec)
    return _sleep


def q(bid=2.0, ask=2.2, last=2.1, quote_time=None, now_ref=None):
    """One Schwab /quotes entry as consensus_engine.scanners.schwab_client maps it."""
    t = quote_time if quote_time is not None else (now_ref or time.time())
    return {"c": last, "bid": bid, "ask": ask, "quote_time": t, "t": t,
            "v": 0, "halt_status": "normal"}


# ═══════════════════════════ selection: deterministic pick ═══════════════════════════

async def test_atm_picks_the_strike_closest_to_entry_price(tmp_db):
    r = await one_selection("ATM_PUT", "PT25_SL35")
    assert r["status"] == "SELECTED"
    assert r["plan"]["long_symbol"] == "N240"
    assert r["plan"]["expiry"] == QUAL_EXPIRY
    assert r["plan"]["short_symbol"] is None


async def test_otm5_picks_the_strike_closest_to_95_percent(tmp_db):
    r = await one_selection(
        "OTM5_PUT", "PT25_SL35",
        strikes=((228, "N228"), (235, "N235"), (240, "N240")))
    # 0.95 * 240 = 228
    assert r["plan"]["long_symbol"] == "N228"


async def test_spread_picks_both_legs_at_the_same_expiration(tmp_db):
    sid = await seed_shortlist()
    for strike, sym in ((240, "L240"), (228, "S228"), (245, "L245")):
        await seed_contract(sid, symbol=sym, strike=strike, bid=4.8, ask=5.0)
    r = await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                      exit_policy="PT25_SL35")
    assert r["status"] == "SELECTED"
    assert r["plan"]["long_symbol"] == "L240"
    assert r["plan"]["short_symbol"] == "S228"


async def test_tie_break_equal_distance_then_higher_open_interest(tmp_db):
    # 238 and 242 are both 2 away from 240; higher OI wins.
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="A238", strike=238, oi=100)
    await seed_contract(sid, symbol="A242", strike=242, oi=900)
    r = await mon.select_for_position(sid, structure="ATM_PUT",
                                      exit_policy="PT25_SL35")
    assert r["plan"]["long_symbol"] == "A242"


async def test_tie_break_equal_distance_equal_oi_then_symbol_ascending(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="ZZZ238", strike=238, oi=500)
    await seed_contract(sid, symbol="AAA242", strike=242, oi=500)
    r = await mon.select_for_position(sid, structure="ATM_PUT",
                                      exit_policy="PT25_SL35")
    assert r["plan"]["long_symbol"] == "AAA242"


async def test_tie_break_earliest_qualifying_expiration(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="EARLY", strike=240, expiry="2026-09-11")
    await seed_contract(sid, symbol="LATE", strike=240, expiry="2026-10-02")
    r = await mon.select_for_position(sid, structure="ATM_PUT",
                                      exit_policy="PT25_SL35")
    assert r["plan"]["expiry"] == "2026-09-11"
    assert r["plan"]["long_symbol"] == "EARLY"


# ═══════════════════════════ selection: NO_OPTION_TRADE gates ═══════════════════════════

async def test_no_trade_when_spread_is_wider_than_10pct_of_mid(tmp_db):
    r = await one_selection("ATM_PUT", "PT25_SL35",
                            strikes=((240, "N240"),), bid=1.0, ask=1.5)
    assert r["status"] == "NO_OPTION_TRADE"
    assert "spread" in r["reject_reason"] and "10%" in r["reject_reason"]
    assert await count(
        "SELECT COUNT(*) FROM put_flow_option_selections "
        "WHERE selection_status='NO_OPTION_TRADE'") == 1


async def test_no_trade_when_open_interest_below_100(tmp_db):
    r = await one_selection("ATM_PUT", "PT25_SL35",
                            strikes=((240, "N240"),), oi=50)
    assert r["status"] == "NO_OPTION_TRADE"
    assert "open interest" in r["reject_reason"]


async def test_no_trade_on_a_one_sided_quote(tmp_db):
    r = await one_selection("ATM_PUT", "PT25_SL35",
                            strikes=((240, "N240"),), bid=0.0, ask=2.2,
                            quote_quality="NO_TWO_SIDED")
    assert r["status"] == "NO_OPTION_TRADE"
    assert "bid" in r["reject_reason"]


async def test_no_trade_on_a_non_standard_deliverable(tmp_db):
    r = await one_selection("ATM_PUT", "PT25_SL35",
                            strikes=((240, "N240"),), non_standard=1,
                            deliverable_note="100 sh + $40 special cash")
    assert r["status"] == "NO_OPTION_TRADE"
    assert "non-standard" in r["reject_reason"]


async def test_no_trade_when_no_expiration_is_in_window(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="TOOSOON", strike=240, expiry="2026-09-01")
    await seed_contract(sid, symbol="TOOLATE", strike=240, expiry="2026-11-20")
    r = await mon.select_for_position(sid, structure="ATM_PUT",
                                      exit_policy="PT25_SL35")
    assert r["status"] == "NO_OPTION_TRADE"
    assert "no listed expiration" in r["reject_reason"]


async def test_no_trade_when_no_entry_slice_stored(tmp_db):
    sid = await seed_shortlist()
    r = await mon.select_for_position(sid, structure="ATM_PUT",
                                      exit_policy="PT25_SL35")
    assert r["status"] == "NO_OPTION_TRADE"
    assert "no ENTRY option-chain slice" in r["reject_reason"]


# ═══════════════════════════ entry / liquidation math + commissions ═══════════════════════════

async def test_long_put_entry_cost_target_stop_and_commission(tmp_db):
    r = await one_selection("ATM_PUT", "PT25_SL35",
                            strikes=((240, "N240"),), bid=2.0, ask=2.2)
    p = r["plan"]
    assert p["entry_cost"] == pytest.approx(2.2)             # long ask
    assert p["long_entry_bid"] == pytest.approx(2.0)         # long bid = liq basis
    assert p["entry_commission"] == pytest.approx(0.45)      # 1 leg, entry side
    assert p["target_liq_value"] == pytest.approx(2.2 * 1.25)
    assert p["stop_liq_value"] == pytest.approx(2.2 * 0.65)


async def test_spread_entry_debit_is_long_ask_minus_short_bid(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="L240", strike=240, bid=4.8, ask=5.0)
    await seed_contract(sid, symbol="S228", strike=228, bid=1.5, ask=1.6)
    r = await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                      exit_policy="PT25_SL35")
    p = r["plan"]
    assert p["entry_cost"] == pytest.approx(5.0 - 1.5)       # 3.5
    assert p["entry_commission"] == pytest.approx(0.90)      # 2 legs, entry side
    assert p["target_liq_value"] == pytest.approx(3.5 * 1.25)


async def test_time_only_policy_has_no_target_or_stop(tmp_db):
    r = await one_selection("ATM_PUT", "TIME_ONLY", strikes=((240, "N240"),))
    assert r["plan"]["target_liq_value"] is None
    assert r["plan"]["stop_liq_value"] is None


# ═══════════════════════════ run_session: one batched quote ═══════════════════════════

async def test_run_uses_one_batched_quote_call_for_all_legs(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="L240", strike=240, bid=4.8, ask=5.0)
    await seed_contract(sid, symbol="S228", strike=228, bid=1.5, ask=1.6)
    await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                  exit_policy="PT25_SL35")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = Mock(return_value={"L240": q(1.0, 1.2, now_ref=clock()),
                            "S228": q(0.5, 0.7, now_ref=clock())})
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    assert qf.call_count == 1
    assert sorted(qf.call_args[0][0]) == ["L240", "S228"]
    assert res["quote_batches"] == 1


async def test_sixteen_overlapping_positions_send_thirty_two_legs_in_one_call(tmp_db):
    syms = []
    for i in range(16):
        sid = await seed_shortlist(ticker=f"T{i}")
        lo, sh = f"L{i}", f"S{i}"
        await seed_contract(sid, ticker=f"T{i}", symbol=lo, strike=240, bid=4.8, ask=5.0)
        await seed_contract(sid, ticker=f"T{i}", symbol=sh, strike=228, bid=1.5, ask=1.6)
        await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                      exit_policy="TIME_ONLY")
        syms += [lo, sh]
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = Mock(side_effect=lambda symbols: {s: q(1.0, 1.2, now_ref=clock()) for s in symbols})
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    assert qf.call_count == 1
    assert sorted(qf.call_args[0][0]) == sorted(syms)
    assert len(qf.call_args[0][0]) == 32
    assert res["selections_monitored"] == 16
    assert await count("SELECT COUNT(*) FROM put_flow_option_minutes "
                       "WHERE session_date=?", (ENTRY_SESSION,)) == 32


# ═══════════════════════════ run_session: cadence + aggregation ═══════════════════════════

async def _long_only_selection(exit_policy="PT25_SL35", max_exit=EXIT_SESSION):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="N240", strike=240, bid=2.0, ask=2.2)
    r = await mon.select_for_position(sid, structure="ATM_PUT", exit_policy=exit_policy)
    if max_exit != EXIT_SESSION:
        conn = await db.get_db()
        await conn.execute("UPDATE put_flow_option_selections SET max_exit_session=? "
                           "WHERE id=?", (max_exit, r["selection_id"]))
        await conn.commit()
    return r["selection_id"]


async def test_fifteen_second_cadence_with_no_overlapping_polls(tmp_db):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:34"))
    sleeps: list = []
    # each poll "costs" 3 seconds of wall time inside quote_fn
    def qf(symbols):
        clock.advance(3.0)
        return {s: q(2.3, 2.5, now_ref=clock()) for s in symbols}
    await mon.run_session(session=ENTRY_SESSION, quote_fn=qf, clock=clock,
                          sleep_fn=make_sleep(clock, sleeps),
                          # stop one minute after start -> 4 polls
                          )
    # every gap between polls is exactly 15s: 3s of work + 12s of sleep
    assert sleeps, "expected at least one poll"
    assert all(abs(s - 12.0) < 1e-9 for s in sleeps)


async def test_minute_aggregation_across_several_polls(tmp_db):
    sel_id = await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:34"))
    bids = iter([2.00, 2.50, 1.80, 2.20,   # minute 06:34, 4 polls
                 2.10, 2.10, 2.10, 2.10])  # minute 06:35
    def qf(symbols):
        b = next(bids, 2.1)
        return {s: q(b, b + 0.2, now_ref=clock()) for s in symbols}
    await mon.run_session(session=ENTRY_SESSION, quote_fn=qf, clock=clock,
                          sleep_fn=make_sleep(clock, []))
    m = await rows("SELECT * FROM put_flow_option_minutes WHERE minute_pt='06:34'")
    assert len(m) == 1
    row = m[0]
    assert row["poll_count"] == 4
    assert row["usable_polls"] == 4
    assert row["bid_open"] == pytest.approx(2.00)
    assert row["bid_high"] == pytest.approx(2.50)
    assert row["bid_low"] == pytest.approx(1.80)
    assert row["bid_close"] == pytest.approx(2.20)
    assert row["minute_pt"] == "06:34"       # Pacific clock, never ET


# ═══════════════════════════ run_session: events ═══════════════════════════

async def test_target_event_records_liquidation_pnl_for_a_long_put(tmp_db):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    # entry_cost 2.2, target liq = 2.75; long bid 2.90 clears it
    qf = lambda s: {sym: q(2.90, 3.10, now_ref=clock()) for sym in s}
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    ev = await rows("SELECT * FROM put_flow_option_events WHERE event_type='TARGET'")
    assert len(ev) == 1
    e = ev[0]
    assert e["liq_value"] == pytest.approx(2.90)
    assert e["gross_pnl_usd"] == pytest.approx((2.90 - 2.2) * 100)
    assert e["commission_usd"] == pytest.approx(0.90)          # long put round trip
    assert e["net_pnl_usd"] == pytest.approx((2.90 - 2.2) * 100 - 0.90)
    assert e["net_pct"] == pytest.approx(100 * ((2.90 - 2.2) * 100 - 0.90) / 220)
    assert res["events_written"] >= 1


async def test_stop_event_for_a_spread_uses_long_bid_minus_short_ask(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="L240", strike=240, bid=4.8, ask=5.0)
    await seed_contract(sid, symbol="S228", strike=228, bid=1.5, ask=1.6)
    await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                  exit_policy="PT25_SL35")
    # entry_cost 3.5, stop liq = 2.275; liq = 2.0 - 0.5 = 1.5 -> STOP
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {"L240": q(2.0, 2.2, now_ref=clock()),
                    "S228": q(0.3, 0.5, now_ref=clock())}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    ev = await rows("SELECT * FROM put_flow_option_events WHERE event_type='STOP'")
    assert len(ev) == 1
    assert ev[0]["liq_value"] == pytest.approx(1.5)
    assert ev[0]["commission_usd"] == pytest.approx(1.80)      # two-leg round trip
    assert ev[0]["net_pnl_usd"] == pytest.approx((1.5 - 3.5) * 100 - 1.80)


async def test_same_poll_target_and_stop_records_the_stop(tmp_db):
    sid = await seed_shortlist()
    # manual row where stop_liq > target_liq, so one liq value trips both
    sel = await seed_manual_selection(sid, long_symbol="N240", entry_cost=2.0,
                                      target_liq_value=2.0, stop_liq_value=3.0,
                                      max_exit_session="2026-09-30")
    await seed_contract(sid, symbol="N240", strike=240)
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {"N240": q(2.5, 2.7, now_ref=clock())}   # 2.5 >= 2.0 and <= 3.0
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    assert await count("SELECT COUNT(*) FROM put_flow_option_events "
                       "WHERE selection_id=? AND event_type='STOP'", (sel,)) == 1
    assert await count("SELECT COUNT(*) FROM put_flow_option_events "
                       "WHERE selection_id=? AND event_type='TARGET'", (sel,)) == 0


async def test_time_exit_on_the_frozen_exit_date(tmp_db):
    # TIME_ONLY policy, exit date == the session being monitored
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="N240", strike=240, bid=2.0, ask=2.2)
    await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="TIME_ONLY")
    clock = FakeClock(pt_epoch(EXIT_SESSION, "06:36"))
    qf = lambda s: {"N240": q(1.7, 1.9, now_ref=clock())}
    res = await mon.run_session(session=EXIT_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    ev = await rows("SELECT * FROM put_flow_option_events WHERE event_type='TIME_EXIT'")
    assert len(ev) == 1
    assert ev[0]["liq_value"] == pytest.approx(1.7)
    assert ev[0]["net_pnl_usd"] == pytest.approx((1.7 - 2.2) * 100 - 0.90)


async def test_first_event_wins_duplicate_events_are_not_written(tmp_db):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {sym: q(2.90, 3.10, now_ref=clock()) for sym in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    clock2 = FakeClock(pt_epoch(ENTRY_SESSION, "06:50"))
    qf2 = lambda s: {sym: q(3.50, 3.70, now_ref=clock2()) for sym in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf2,
                          clock=clock2, sleep_fn=AsyncMock())
    assert await count("SELECT COUNT(*) FROM put_flow_option_events "
                       "WHERE event_type='TARGET'") == 1


# ═══════════════════════════ run_session: bad quotes ═══════════════════════════

@pytest.mark.parametrize("bad,label", [
    (lambda s, c: {}, "missing"),                                  # symbol absent
    (lambda s, c: {list(s)[0]: q(0.0, 2.2, now_ref=c())}, "zero_bid"),
    (lambda s, c: {list(s)[0]: q(2.5, 2.0, now_ref=c())}, "crossed"),
    (lambda s, c: {list(s)[0]: q(2.0, 2.2, quote_time=c() - 6000)}, "stale"),
    (lambda s, c: {list(s)[0]: q(2.0, 2.2, quote_time=c() - 400)}, "delayed"),
])
async def test_bad_quotes_never_trigger_an_event(tmp_db, bad, label):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: bad(s, clock)
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    assert await count("SELECT COUNT(*) FROM put_flow_option_events "
                       "WHERE event_type IN ('TARGET','STOP')") == 0
    # a minute row is still written so the gap is visible, not hidden
    assert await count("SELECT COUNT(*) FROM put_flow_option_minutes") >= 1
    assert res["usable_observations"] == 0


# ═══════════════════════════ restart recovery ═══════════════════════════

async def test_restart_writes_monitor_restart_and_a_visible_quote_gap(tmp_db):
    sel = await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    c1 = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {sym: q(2.3, 2.5, now_ref=c1()) for sym in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf, clock=c1,
                          sleep_fn=AsyncMock())
    c2 = FakeClock(pt_epoch(ENTRY_SESSION, "07:20"))
    qf2 = lambda s: {sym: q(2.3, 2.5, now_ref=c2()) for sym in s}
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf2,
                                clock=c2, sleep_fn=AsyncMock())
    assert res["restart"] is True
    assert await count("SELECT COUNT(*) FROM put_flow_option_events "
                       "WHERE selection_id=? AND event_type='MONITOR_RESTART'", (sel,)) == 1
    # TWO gaps, and both are real. The first run started at 06:40, ten minutes
    # after the 06:30 session start, so 06:30-06:40 was never watched either.
    # Recording only the restart gap would make a monitor that started late look
    # identical to one that started on time.
    gap = await rows("SELECT * FROM put_flow_option_events "
                     "WHERE selection_id=? AND event_type='QUOTE_GAP' "
                     "ORDER BY event_seq", (sel,))
    assert len(gap) == 2
    assert (gap[0]["gap_start_pt"], gap[0]["gap_end_pt"]) == ("06:30", "06:40")
    assert "never started" in gap[0]["note"]
    assert (gap[1]["gap_start_pt"], gap[1]["gap_end_pt"]) == ("06:40", "07:20")
    assert "was not running" in gap[1]["note"]
    run = await rows("SELECT * FROM put_flow_option_monitor_runs WHERE session_date=?",
                     (ENTRY_SESSION,))
    assert run[0]["restart_count"] == 1


async def test_duplicate_minute_is_written_only_once(tmp_db):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    base = pt_epoch(ENTRY_SESSION, "06:40")
    for _ in range(3):
        clock = FakeClock(base + 2)   # same wall-clock minute every time
        qf = lambda s: {sym: q(2.3, 2.5, now_ref=clock()) for sym in s}
        await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                              clock=clock, sleep_fn=AsyncMock())
    assert await count("SELECT COUNT(*) FROM put_flow_option_minutes "
                       "WHERE minute_pt='06:40'") == 1


# ═══════════════════════════ holiday + shortened session ═══════════════════════════

def test_trading_day_calendar_knows_holidays_and_weekends():
    assert mon.is_trading_day("2026-08-25") is True
    assert mon.is_trading_day("2026-08-29") is False       # Saturday
    assert mon.is_trading_day("2026-11-26") is False       # Thanksgiving


async def test_run_session_does_nothing_on_a_market_holiday(tmp_db):
    await _long_only_selection(exit_policy="TIME_ONLY", max_exit="2026-11-26")
    res = await mon.run_session(session="2026-11-26", once=True,
                                quote_fn=Mock(), clock=FakeClock(pt_epoch("2026-11-26", "07:00")),
                                sleep_fn=AsyncMock())
    assert res["skipped"] == "not a trading day"
    assert await count("SELECT COUNT(*) FROM put_flow_option_monitor_runs") == 0
    assert await count("SELECT COUNT(*) FROM put_flow_option_minutes") == 0


async def test_shortened_session_stops_at_the_early_close(tmp_db):
    # 2026-11-27 closes 13:00 ET = 10:00 Pacific; a poll at 10:05 is past the
    # clamped stop, so a non-once run makes zero quote batches.
    await _long_only_selection(exit_policy="TIME_ONLY", max_exit="2026-12-31")
    clock = FakeClock(pt_epoch("2026-11-27", "10:05"))
    qf = Mock(return_value={})
    res = await mon.run_session(session="2026-11-27", quote_fn=qf, clock=clock,
                                sleep_fn=AsyncMock())
    assert res["quote_batches"] == 0
    assert qf.call_count == 0


# ═══════════════════════════ safety: observer never alters the pair ═══════════════════════════

async def test_selection_failure_returns_error_and_leaves_the_shortlist_row_untouched(
        tmp_db, monkeypatch):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="N240", strike=240)
    before = (await rows("SELECT * FROM put_flow_shortlist WHERE id=?", (sid,)))[0]
    monkeypatch.setattr(mon, "_build_plan",
                        Mock(side_effect=RuntimeError("boom")))
    r = await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="PT25_SL35")
    assert r["status"] == "ERROR"
    assert "boom" in r["error"]
    after = (await rows("SELECT * FROM put_flow_shortlist WHERE id=?", (sid,)))[0]
    assert after == before


async def test_a_schwab_error_in_run_session_never_raises(tmp_db):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    sid_row_before = (await rows("SELECT * FROM put_flow_shortlist"))[0]
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    def boom(symbols):
        raise RuntimeError("schwab is down")
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=boom,
                                clock=clock, sleep_fn=AsyncMock())
    assert res["error"] is None                 # the batch error was swallowed
    assert res["missing_observations"] >= 1
    after = (await rows("SELECT * FROM put_flow_shortlist"))[0]
    assert after == sid_row_before             # the stock pair is untouched


async def test_health_alert_fires_once_when_nothing_usable_was_stored(tmp_db, _no_health):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {}      # nothing ever answers
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    assert _no_health.await_count == 1
    assert _no_health.await_args.kwargs["down"] is True


async def test_health_is_silent_when_observations_landed(tmp_db, _no_health):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {sym: q(2.3, 2.5, now_ref=clock()) for sym in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    # still called (to report the healthy state) but with down=False
    assert _no_health.await_args.kwargs["down"] is False


# ═══════════════════════════ dry-run cannot write ═══════════════════════════

async def test_dry_run_selection_writes_nothing(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="N240", strike=240)
    r = await mon.select_for_position(sid, structure="ATM_PUT",
                                      exit_policy="PT25_SL35", dry_run=True)
    assert r["status"] == "SELECTED"
    assert await count("SELECT COUNT(*) FROM put_flow_option_selections") == 0


async def test_dry_run_session_writes_nothing(tmp_db):
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {sym: q(2.90, 3.10, now_ref=clock()) for sym in s}
    res = await mon.run_session(session=ENTRY_SESSION, once=True, dry_run=True,
                                quote_fn=qf, clock=clock, sleep_fn=AsyncMock())
    assert res["dry_run"] is True
    assert await count("SELECT COUNT(*) FROM put_flow_option_monitor_runs") == 0
    assert await count("SELECT COUNT(*) FROM put_flow_option_minutes") == 0
    assert await count("SELECT COUNT(*) FROM put_flow_option_events") == 0


# ═══════════════════════════ no raw chain ever rendered ═══════════════════════════

async def test_summary_text_never_contains_the_raw_chain(tmp_db):
    sid = await seed_shortlist()
    all_syms = []
    for k in range(20):
        strike = 200 + k * 5
        sym = f"NVDA__{strike}"
        all_syms.append(sym)
        await seed_contract(sid, symbol=sym, strike=strike)
    r = await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="PT25_SL35")
    text = mon.summarize_selection(r)
    chosen = r["plan"]["long_symbol"]
    assert chosen in text
    other = [s for s in all_syms if s != chosen]
    assert not any(s in text for s in other)
    assert "putExpDateMap" not in text and "strike" not in text.lower()


async def test_pacific_timestamps_in_owner_facing_values(tmp_db):
    sel = await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:41"))
    qf = lambda s: {sym: q(2.90, 3.10, now_ref=clock()) for sym in s}
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    ev = (await rows("SELECT * FROM put_flow_option_events WHERE event_type='TARGET'"))[0]
    assert ev["minute_pt"] == "06:41"                 # Pacific HH:MM
    assert ev["session_date"] == ENTRY_SESSION
    text = mon.summarize_run(res)
    assert "ET" not in text and "Eastern" not in text


# ═══════════════════════════ C1 — spread legs the same contract ═══════════════════════════

async def test_c1_spread_legs_resolving_to_one_contract_is_no_option_trade(tmp_db):
    """C1: if the long and short legs land on the SAME contract symbol, the
    answer is NO_OPTION_TRADE with an exact reason — never widen a gate."""
    sid = await seed_shortlist(entry_stock_px=100.0)
    await seed_contract(sid, symbol="ONLY100", strike=100, bid=4.0, ask=4.2, oi=500)
    r = await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                      exit_policy="TIME_ONLY")
    assert r["status"] == "NO_OPTION_TRADE"
    assert r["reject_reason"] == "spread legs resolved to the same contract"


# ═══════════════════════════ C2 — ATM/OTM5 collapse marker ═══════════════════════════

async def test_c2_atm_and_otm5_on_one_contract_are_flagged_collapsed(tmp_db):
    """C2: when ATM_PUT and OTM5_PUT resolve to the exact same contract, both
    rows are still written but structures_collapsed=1 on every one of them."""
    sid = await seed_shortlist(entry_stock_px=100.0)
    # nearest strike to 100 AND to 95 is 98
    await seed_contract(sid, symbol="C98", strike=98, bid=3.0, ask=3.2, oi=800)
    await seed_contract(sid, symbol="C105", strike=105, bid=6.0, ask=6.3, oi=500)
    await mon.select_for_shortlist(sid)

    longs = await rows(
        "SELECT structure, long_symbol, selection_status, structures_collapsed "
        "FROM put_flow_option_selections WHERE shortlist_id=? "
        "AND structure IN ('ATM_PUT','OTM5_PUT')", (sid,))
    assert len(longs) == 6                              # 2 structures x 3 exits
    assert all(x["long_symbol"] == "C98" for x in longs)
    assert all(x["selection_status"] == "SELECTED" for x in longs)
    assert all(x["structures_collapsed"] == 1 for x in longs)
    # the spread rows (same contract for both legs -> C1) are NOT collapse-flagged
    spread = await rows("SELECT structures_collapsed FROM put_flow_option_selections "
                        "WHERE shortlist_id=? AND structure='PUT_DEBIT_SPREAD'", (sid,))
    assert all(x["structures_collapsed"] == 0 for x in spread)


async def test_c2_distinct_atm_and_otm5_contracts_are_not_collapsed(tmp_db):
    sid = await seed_shortlist(entry_stock_px=240.0)
    for strike, sym in ((240, "D240"), (228, "D228")):
        await seed_contract(sid, symbol=sym, strike=strike, bid=4.0, ask=4.2, oi=800)
    await mon.select_for_shortlist(sid)
    flags = await rows("SELECT structures_collapsed FROM put_flow_option_selections "
                       "WHERE shortlist_id=? AND structure IN ('ATM_PUT','OTM5_PUT')",
                       (sid,))
    assert flags and all(x["structures_collapsed"] == 0 for x in flags)


# ═══════════════════════════ C3 — nearest strike, veto only ═══════════════════════════

async def test_c3_nearest_strike_failing_a_gate_is_no_trade_not_the_next_strike(tmp_db):
    """C3: the closest listed strike is chosen and a liquidity test can only
    veto it. A cleaner strike further out is never substituted."""
    sid = await seed_shortlist(entry_stock_px=240.0)
    await seed_contract(sid, symbol="NEAR240", strike=240, bid=1.0, ask=1.5, oi=500)  # 40% spread
    await seed_contract(sid, symbol="FAR250", strike=250, bid=3.0, ask=3.1, oi=900)   # clean
    r = await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="TIME_ONLY")
    assert r["status"] == "NO_OPTION_TRADE"
    assert "spread" in r["reject_reason"]
    assert "FAR250" not in (r["reject_reason"] or "")


# ═══════════════════════════ deliverable note is not "non-standard" ═══════════════════════════

async def test_standard_100_root_deliverable_note_does_not_veto(tmp_db):
    """A normal put's note reads '100 NVDA' — that is standard and must select."""
    r = await one_selection("ATM_PUT", "TIME_ONLY", strikes=((240, "N240"),),
                            deliverable_note="100 NVDA")
    assert r["status"] == "SELECTED"


async def test_blank_deliverable_note_does_not_veto(tmp_db):
    r = await one_selection("ATM_PUT", "TIME_ONLY", strikes=((240, "N240"),),
                            deliverable_note="")
    assert r["status"] == "SELECTED"


# ═══════════════════════════ 2026-08-26 ground truth ═══════════════════════════

async def _seed_gt(ticker, entry_px, contracts, *, expiry, entry_session="2026-08-26",
                   exit_session="2026-09-01"):
    sid = await seed_shortlist(ticker=ticker, entry_session=entry_session,
                               exit_session=exit_session, entry_stock_px=entry_px)
    for sym, strike, bid, ask, oi in contracts:
        await seed_contract(sid, ticker=ticker, symbol=sym, strike=strike,
                            expiry=expiry, bid=bid, ask=ask, oi=oi)
    return sid


async def test_ground_truth_2026_08_26_selection_outcomes(tmp_db):
    # DKS $121.98 -> ATM $120 clean; $115 (nearest to 0.95x) has an 11% spread
    await _seed_gt("DKS", 121.98, [
        ("DKS_P115", 115, 3.30, 3.70, 800),
        ("DKS_P120", 120, 4.90, 5.10, 3158),
        ("DKS_P125", 125, 6.50, 6.70, 500),
    ], expiry="2026-09-18")
    # SUI $126.25 -> every nearest strike fails the spread test
    await _seed_gt("SUI", 126.25, [
        ("SUI_P120", 120, 2.30, 2.60, 700),
        ("SUI_P125", 125, 3.30, 3.70, 900),
        ("SUI_P130", 130, 5.00, 5.60, 400),
    ], expiry="2026-09-18")
    # MSTR $124.06 -> nearest strike $124 has a 10.6% spread
    await _seed_gt("MSTR", 124.06, [
        ("MSTR_P118", 118, 5.50, 6.20, 600),
        ("MSTR_P124", 124, 8.00, 8.90, 509),
        ("MSTR_P130", 130, 10.0, 11.2, 500),
    ], expiry="2026-09-11")
    # MARA $11.49 -> ATM $11.5 clean; $11.0 (nearest to 0.95x) has a 15% spread
    await _seed_gt("MARA", 11.49, [
        ("MARA_P11", 11.0, 0.55, 0.64, 300),
        ("MARA_P115", 11.5, 0.80, 0.88, 443),
        ("MARA_P12", 12.0, 1.10, 1.20, 500),
    ], expiry="2026-09-11")
    # AMZN etc: entered, no stored slice at all
    for t in ("AMZN", "GOOGL", "META", "BMNR"):
        await seed_shortlist(ticker=t, entry_session="2026-08-26",
                             exit_session="2026-09-01")

    out = await mon.select_open_positions(session="2026-08-26")

    async def status(ticker, structure):
        r = await rows(
            "SELECT s.selection_status, s.reject_reason, s.long_symbol "
            "FROM put_flow_option_selections s JOIN put_flow_shortlist sh "
            "ON sh.id = s.shortlist_id WHERE sh.ticker=? AND s.structure=? LIMIT 1",
            (ticker, structure))
        return r[0] if r else None

    dks_atm = await status("DKS", "ATM_PUT")
    assert dks_atm["selection_status"] == "SELECTED"
    assert dks_atm["long_symbol"] == "DKS_P120"
    assert (await status("DKS", "OTM5_PUT"))["selection_status"] == "NO_OPTION_TRADE"
    assert (await status("DKS", "PUT_DEBIT_SPREAD"))["selection_status"] == "NO_OPTION_TRADE"

    for st in ("ATM_PUT", "OTM5_PUT", "PUT_DEBIT_SPREAD"):
        assert (await status("SUI", st))["selection_status"] == "NO_OPTION_TRADE"
        assert (await status("MSTR", st))["selection_status"] == "NO_OPTION_TRADE"

    mara_atm = await status("MARA", "ATM_PUT")
    assert mara_atm["selection_status"] == "SELECTED"
    assert mara_atm["long_symbol"] == "MARA_P115"
    assert (await status("MARA", "OTM5_PUT"))["selection_status"] == "NO_OPTION_TRADE"

    # the four with no slice are recorded distinctly, not silently dropped
    assert out["no_entry_slice"] == 4 * 9
    amzn = await status("AMZN", "ATM_PUT")
    assert amzn["selection_status"] == "NO_OPTION_TRADE"
    assert "no ENTRY option-chain slice" in amzn["reject_reason"]


# ═══════════════════════════ minutes keyed by contract, not selection ═══════════════════════════

async def test_one_minute_row_per_contract_even_with_several_selections(tmp_db):
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="N240", strike=240, bid=2.0, ask=2.2)
    await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="TIME_ONLY")
    await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="PT25_SL35")
    conn = await db.get_db()
    await conn.execute("UPDATE put_flow_option_selections SET max_exit_session='2026-09-30' "
                       "WHERE shortlist_id=?", (sid,))
    await conn.commit()
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = Mock(side_effect=lambda s: {x: q(2.3, 2.5, now_ref=clock()) for x in s})
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=clock, sleep_fn=AsyncMock())
    assert qf.call_count == 1
    assert list(qf.call_args[0][0]) == ["N240"]
    assert await count("SELECT COUNT(*) FROM put_flow_option_minutes "
                       "WHERE contract_symbol='N240'") == 1
    assert res["selections_monitored"] == 2


async def test_target_and_stop_apply_a_shared_contract_to_every_selection(tmp_db):
    """One contract, two exit policies: a quote that trips PT25 must write a
    TARGET for the PT25 selection and leave the TIME_ONLY one running."""
    sid = await seed_shortlist()
    await seed_contract(sid, symbol="N240", strike=240, bid=2.0, ask=2.2)
    await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="TIME_ONLY")
    await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="PT25_SL35")
    conn = await db.get_db()
    await conn.execute("UPDATE put_flow_option_selections SET max_exit_session='2026-09-30' "
                       "WHERE shortlist_id=?", (sid,))
    await conn.commit()
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {x: q(2.90, 3.10, now_ref=clock()) for x in s}   # liq 2.90 >= 2.75
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    ev = await rows("SELECT s.exit_policy, e.event_type FROM put_flow_option_events e "
                    "JOIN put_flow_option_selections s ON s.id = e.selection_id "
                    "WHERE e.event_type IN ('TARGET','STOP')")
    assert len(ev) == 1
    assert ev[0]["exit_policy"] == "PT25_SL35"
    assert ev[0]["event_type"] == "TARGET"


async def test_open_legs_over_the_cap_are_truncated_to_max_legs(tmp_db):
    for i in range(17):                                   # 34 legs, cap 32
        sid = await seed_shortlist(ticker=f"K{i}")
        await seed_contract(sid, ticker=f"K{i}", symbol=f"KL{i}", strike=240, bid=4.8, ask=5.0)
        await seed_contract(sid, ticker=f"K{i}", symbol=f"KS{i}", strike=228, bid=1.5, ask=1.6)
        await mon.select_for_position(sid, structure="PUT_DEBIT_SPREAD",
                                      exit_policy="TIME_ONLY")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = Mock(side_effect=lambda s: {x: q(1.0, 1.2, now_ref=clock()) for x in s})
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    assert qf.call_count == 1
    assert len(qf.call_args[0][0]) == 32


# ═══════════════════════════ health: down once, recovery once, then silent ═══════════════════════════

async def test_health_down_then_recovery_then_silent(tmp_db, monkeypatch):
    import consensus_engine.alerts.ops_alert as oa
    monkeypatch.setattr(oa, "report_ops_state", _REAL_REPORT_OPS_STATE)
    monkeypatch.setattr(oa, "errors_channel_id", lambda: "123456")
    sent = AsyncMock(return_value="msg-1")
    monkeypatch.setattr("consensus_engine.alerts.discord.send_message", sent,
                        raising=False)

    sid = await seed_shortlist(entry_session="2026-08-25", exit_session="2026-09-01")
    await seed_contract(sid, symbol="N240", strike=240, bid=2.0, ask=2.2)
    await mon.select_for_position(sid, structure="ATM_PUT", exit_policy="PT25_SL35")
    conn = await db.get_db()
    await conn.execute("UPDATE put_flow_option_selections SET max_exit_session='2026-09-30' "
                       "WHERE shortlist_id=?", (sid,))
    await conn.commit()

    async def run_on(day, usable):
        clk = FakeClock(pt_epoch(day, "06:40"))
        if usable:
            qf = lambda s: {x: q(2.3, 2.5, now_ref=clk()) for x in s}
        else:
            qf = lambda s: {}
        return await mon.run_session(session=day, once=True, quote_fn=qf, clock=clk,
                                     sleep_fn=AsyncMock())

    await run_on("2026-08-25", usable=False)
    assert sent.await_count == 1
    assert "🔴" in sent.await_args.args[1]

    await run_on("2026-08-26", usable=True)
    assert sent.await_count == 2
    assert "🟢" in sent.await_args.args[1]

    await run_on("2026-08-27", usable=True)
    assert sent.await_count == 2                          # steady healthy -> silent


# ═══════════════════════════ job: JSON alone on stdout ═══════════════════════════

def test_job_select_only_emits_only_json_on_stdout():
    r = subprocess.run(
        [sys.executable, "scripts/put_flow_option_monitor_job.py",
         "--run", "--once", "--dry-run", "--session", "2026-08-29", "--force"],
        capture_output=True, text=True, cwd=str(ROOT_DIR))
    assert r.returncode == 0, r.stderr
    parsed = json.loads(r.stdout)                         # the ONLY thing on stdout
    assert parsed["session"] == "2026-08-29"
    assert parsed["skipped"] == "not a trading day"


# ═══════════════════════════ defect A — no leaked http session ═══════════════════════════

async def test_run_session_closes_the_shared_http_session(tmp_db, monkeypatch):
    closer = AsyncMock()
    monkeypatch.setattr("consensus_engine.utils.http.close_session", closer,
                        raising=False)
    await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {x: q(2.3, 2.5, now_ref=clock()) for x in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=clock, sleep_fn=AsyncMock())
    closer.assert_awaited()


async def test_run_session_closes_http_session_even_on_error(tmp_db, monkeypatch):
    closer = AsyncMock()
    monkeypatch.setattr("consensus_engine.utils.http.close_session", closer,
                        raising=False)
    # force the body to blow up after entry
    monkeypatch.setattr(mon, "_load_active",
                        AsyncMock(side_effect=RuntimeError("boom")))
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=lambda s: {},
                                clock=FakeClock(pt_epoch(ENTRY_SESSION, "06:40")),
                                sleep_fn=AsyncMock())
    assert res["error"] == "boom"
    closer.assert_awaited()


# ═══════════════════════════ defect B — backwards QUOTE_GAP is an anomaly ═══════════════════════════

async def test_backwards_quote_gap_is_recorded_as_a_clock_anomaly(tmp_db):
    sel = await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    # first run late in the session so a stored minute lands at ~12:58
    c1 = FakeClock(pt_epoch(ENTRY_SESSION, "12:58"))
    qf = lambda s: {x: q(2.3, 2.5, now_ref=c1()) for x in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf, clock=c1,
                          sleep_fn=AsyncMock())
    # restart with the clock moved BACKWARDS to 07:00
    c2 = FakeClock(pt_epoch(ENTRY_SESSION, "07:00"))
    qf2 = lambda s: {x: q(2.3, 2.5, now_ref=c2()) for x in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf2, clock=c2,
                          sleep_fn=AsyncMock())
    gap = (await rows("SELECT * FROM put_flow_option_events "
                      "WHERE selection_id=? AND event_type='QUOTE_GAP'", (sel,)))[-1]
    assert gap["gap_start_pt"] == "12:58" and gap["gap_end_pt"] == "07:00"
    assert gap["note"].startswith("CLOCK ANOMALY")
    assert "–" not in gap["note"] or "not after" in gap["note"]


async def test_forward_quote_gap_still_reads_as_a_normal_interval(tmp_db):
    sel = await _long_only_selection(exit_policy="PT25_SL35", max_exit="2026-09-30")
    c1 = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))
    qf = lambda s: {x: q(2.3, 2.5, now_ref=c1()) for x in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf, clock=c1,
                          sleep_fn=AsyncMock())
    c2 = FakeClock(pt_epoch(ENTRY_SESSION, "07:20"))
    qf2 = lambda s: {x: q(2.3, 2.5, now_ref=c2()) for x in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf2, clock=c2,
                          sleep_fn=AsyncMock())
    gap = (await rows("SELECT * FROM put_flow_option_events "
                      "WHERE selection_id=? AND event_type='QUOTE_GAP'", (sel,)))[-1]
    assert gap["note"] == "no observations 06:40–07:20 Pacific (monitor was not running)"
    assert not gap["note"].startswith("CLOCK ANOMALY")


async def test_a_session_the_monitor_never_ran_still_leaves_a_visible_hole(tmp_db):
    """The 2026-08-27 failure: the service died on startup, six selections went
    unwatched from 06:30 to 16:58, and nothing in the events table said so. The
    old code only recorded a gap when a PRIOR run row existed, so a day the
    monitor missed entirely looked exactly like a day it watched."""
    sel = await _long_only_selection(exit_policy="TIME_ONLY", max_exit="2026-09-30")
    late = FakeClock(pt_epoch(ENTRY_SESSION, "11:30"))
    qf = lambda s: {sym: q(2.3, 2.5, now_ref=late()) for sym in s}
    res = await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                                clock=late, sleep_fn=AsyncMock())
    assert res["restart"] is False          # genuinely the first run of the day
    gap = await rows("SELECT * FROM put_flow_option_events "
                     "WHERE selection_id=? AND event_type='QUOTE_GAP'", (sel,))
    assert len(gap) == 1
    assert gap[0]["gap_start_pt"] == "06:30"
    assert gap[0]["gap_end_pt"] == "11:30"
    assert "never started" in gap[0]["note"]


async def test_a_punctual_first_start_records_no_gap(tmp_db):
    """The other side of it: starting on time must stay silent, or every normal
    morning would file a gap for the second it took to boot."""
    await _long_only_selection(exit_policy="TIME_ONLY", max_exit="2026-09-30")
    ontime = FakeClock(pt_epoch(ENTRY_SESSION, "06:30") + 20)
    qf = lambda s: {sym: q(2.3, 2.5, now_ref=ontime()) for sym in s}
    await mon.run_session(session=ENTRY_SESSION, once=True, quote_fn=qf,
                          clock=ontime, sleep_fn=AsyncMock())
    assert await count("SELECT COUNT(*) FROM put_flow_option_events "
                       "WHERE event_type='QUOTE_GAP'") == 0


async def test_the_run_row_is_written_even_when_the_loop_throws(tmp_db):
    """An audit row that claims zero while the tables hold data is worse than no
    audit row. On 2026-08-27 one said 0 minutes and 0 events while 2 minutes and
    36 events were stored."""
    await _long_only_selection(exit_policy="TIME_ONLY", max_exit="2026-09-30")
    clock = FakeClock(pt_epoch(ENTRY_SESSION, "06:40"))

    def exploding(symbols):
        raise RuntimeError("schwab exploded mid-poll")

    res = await mon.run_session(session=ENTRY_SESSION, once=True,
                                quote_fn=exploding, clock=clock,
                                sleep_fn=AsyncMock())
    run = await rows("SELECT * FROM put_flow_option_monitor_runs WHERE session_date=?",
                     (ENTRY_SESSION,))
    assert len(run) == 1                      # the row exists despite the throw
    assert run[0]["finished_at"] is not None
    # and the stock-pair side is untouched: the observer swallowed the failure
    assert res["error"] is None or isinstance(res["error"], str)


# ═════════════ the CLI wrapper systemd actually runs ═════════════

def test_every_module_attribute_the_cli_uses_actually_exists():
    """This is the test that would have caught the 2026-08-27 outage.

    The module's `enabled()` was split into `select_enabled()` and
    `monitor_enabled()`, but `scripts/put_flow_option_monitor_job.py` still
    called `mon.enabled()`. Nothing failed in the unit tests, because they
    import the module directly and never touch the CLI. The systemd service
    crashed on startup every 15 seconds for a whole trading day -- 2,309
    restarts -- and the day's option data was lost.

    So: parse the CLI and assert every `mon.<name>` it reaches for is really
    there. No network, no database, no subprocess.
    """
    import ast
    from pathlib import Path
    from consensus_engine.analysis import put_flow_option_monitor as module

    cli = Path(__file__).resolve().parent.parent / "scripts" / "put_flow_option_monitor_job.py"
    tree = ast.parse(cli.read_text())

    # find the local alias for the monitor module (`... import x as mon`)
    alias = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and \
                node.module.endswith("analysis"):
            for a in node.names:
                if a.name == "put_flow_option_monitor":
                    alias = a.asname or a.name
    assert alias, "the CLI no longer imports put_flow_option_monitor"

    used = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == alias}
    assert used, "the CLI does not call into the monitor module at all"

    missing = sorted(a for a in used if not hasattr(module, a))
    assert not missing, (
        f"{cli.name} calls {alias}.{{{', '.join(missing)}}} but the module has "
        f"no such attribute — this is exactly the bug that took the monitor "
        f"down for a full session")
