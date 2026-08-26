"""TODO #98 — forward option-chain and borrow collection for TODO #96 positions.

Mocks `schwab_client.get_option_chain` / `get_quotes` throughout — no network
calls. Uses a temporary database, same pattern as test_put_flow_shortlist.py.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

import pandas as pd
import pytest

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.analysis import put_flow_option_capture as pfoc
from consensus_engine.scanners.schwab_client import Chain


# ───────────────────────────── fixtures / helpers ─────────────────────────

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
def _enabled(monkeypatch):
    """Force the config switch on regardless of the live yaml, and pin the
    other option_capture keys to known values for deterministic assertions."""
    values = {
        "put_flow_shortlist.option_capture.enabled": True,
        "put_flow_shortlist.option_capture.min_days_after_stock_exit": 7,
        "put_flow_shortlist.option_capture.max_days_after_entry": 45,
        "put_flow_shortlist.option_capture.strike_low_pct": 0.70,
        "put_flow_shortlist.option_capture.strike_high_pct": 1.10,
        "put_flow_shortlist.option_capture.quote_max_age_sec": 900,
        "put_flow_shortlist.option_capture.max_contracts_per_capture": 400,
    }
    real_get = cfg.get
    monkeypatch.setattr(cfg, "get",
                        lambda key, default=None: values.get(key, real_get(key, default)))


async def _seed_row(ticker="NVDA", entry_session="2026-08-25",
                    exit_session="2026-08-31", shortable=True) -> dict:
    conn = await db.get_db()
    now = time.time()
    cur = await conn.execute(
        """INSERT INTO put_flow_shortlist
           (signal_date, entry_session, ticker, rank, status,
            planned_exit_session, entry_stock_px, entry_spy_px,
            shortable, cost_pct, created_at, updated_at)
           VALUES (?,?,?,1,'ENTERED',?,?,?,?,0.25,?,?)""",
        ("2026-08-24", entry_session, ticker, exit_session, 240.0, 640.0,
         int(shortable), now, now))
    await conn.commit()
    cur = await conn.execute("SELECT * FROM put_flow_shortlist WHERE id=?",
                             (cur.lastrowid,))
    return dict(await cur.fetchone())


def _put_df(rows: list[dict]) -> pd.DataFrame:
    cols = ["contractSymbol", "strike", "lastPrice", "bid", "ask", "volume",
            "openInterest", "impliedVolatility", "expiry", "providerQuoteTime",
            "multiplier", "nonStandard", "deliverableNote",
            "delta", "gamma", "theta", "vega", "rho"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)[cols]


def _contract(sym, strike, expiry, *, bid=1.0, ask=1.2, last=1.1,
             qt_ms=None, volume=10, oi=100, iv=0.4) -> dict:
    return {"contractSymbol": sym, "strike": strike, "lastPrice": last,
            "bid": bid, "ask": ask, "volume": volume, "openInterest": oi,
            "impliedVolatility": iv, "expiry": expiry,
            "providerQuoteTime": qt_ms if qt_ms is not None else int(time.time() * 1000),
            "multiplier": 100.0, "nonStandard": False, "deliverableNote": "",
            "delta": -0.3, "gamma": 0.02, "theta": -0.05, "vega": 0.1, "rho": -0.01}


def _chain(rows: list[dict], underlying_price=240.0, is_delayed=False) -> Chain:
    return Chain(calls=_put_df([]), puts=_put_df(rows),
                underlying_price=underlying_price, is_delayed=is_delayed,
                expirations=sorted({r["expiry"] for r in rows}))


def _quote(px=240.0, shortable=True, hard_to_borrow=False, htb_rate=0.0,
          quote_time=None) -> dict:
    return {"c": px, "bid": px - 0.05, "ask": px + 0.05, "quote_time": quote_time or time.time(),
            "t": quote_time or time.time(), "shortable": shortable,
            "hard_to_borrow": hard_to_borrow, "htb_rate": htb_rate}


# ───────────────────────── window math ─────────────────────────

def test_expiration_window_is_exit_plus_7_to_entry_plus_45():
    row = {"entry_session": "2026-08-25", "planned_exit_session": "2026-08-31"}
    lo, hi = pfoc.expiration_window(row)
    assert lo == "2026-09-07"    # 2026-08-31 + 7 calendar days
    assert hi == "2026-10-09"    # 2026-08-25 + 45 calendar days


def test_strike_window_is_70_to_110_pct_of_spot():
    lo, hi = pfoc.strike_window(200.0)
    assert lo == pytest.approx(140.0)
    assert hi == pytest.approx(220.0)


# ───────────────────────── ENTRY: whole slice, bounded ─────────────────────

async def test_entry_stores_the_whole_surviving_slice_not_one_pick(tmp_db, monkeypatch):
    row = await _seed_row()
    rows = [
        _contract("NVDA1", 200.0, "2026-09-10"),   # in window (0.70*240=168..264)
        _contract("NVDA2", 240.0, "2026-09-10"),
        _contract("NVDA3", 260.0, "2026-09-10"),
        _contract("NVDA4", 100.0, "2026-09-10"),   # below 70% -> excluded
        _contract("NVDA5", 300.0, "2026-09-10"),   # above 110% -> excluded
    ]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))

    out = await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))
    assert out["error"] is None
    assert out["contracts_captured"] == 3

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT contract_symbol FROM put_flow_option_snapshots WHERE stage='ENTRY'")
    stored = {r["contract_symbol"] for r in await cur.fetchall()}
    assert stored == {"NVDA1", "NVDA2", "NVDA3"}


async def test_entry_never_picks_a_best_contract(tmp_db, monkeypatch):
    """Even when one contract is clearly the most liquid, every surviving
    contract is stored — nothing here ranks or selects."""
    row = await _seed_row()
    rows = [_contract("A", 230.0, "2026-09-10", volume=99999, oi=99999),
            _contract("B", 235.0, "2026-09-10", volume=1, oi=1)]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))
    out = await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))
    assert out["contracts_captured"] == 2


# ───────────────────────── MARK/EXIT: same symbols only ────────────────────

async def test_mark_and_exit_capture_exactly_the_entry_symbols(tmp_db, monkeypatch):
    row = await _seed_row()
    entry_rows = [_contract("NVDA1", 200.0, "2026-09-10"),
                 _contract("NVDA2", 240.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(entry_rows))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    # A fresh chain now also carries a brand-new contract NVDA3 -- MARK/EXIT
    # must never pick it up; only NVDA1/NVDA2 (stored at ENTRY) are re-priced.
    later_rows = [_contract("NVDA1", 200.0, "2026-09-10", bid=2.0, ask=2.2),
                 _contract("NVDA2", 240.0, "2026-09-10", bid=1.5, ask=1.7),
                 _contract("NVDA3", 260.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(later_rows))

    out = await pfoc.capture_mark(row, stock_quote=_quote(230.0), spy_quote=_quote(645.0))
    assert out["contracts_captured"] == 2
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT contract_symbol FROM put_flow_option_snapshots WHERE stage='MARK'")
    assert {r["contract_symbol"] for r in await cur.fetchall()} == {"NVDA1", "NVDA2"}

    out2 = await pfoc.capture_exit(row, stock_quote=_quote(225.0), spy_quote=_quote(648.0))
    assert out2["contracts_captured"] == 2
    cur = await conn.execute(
        "SELECT contract_symbol, capture_session FROM put_flow_option_snapshots "
        "WHERE stage='EXIT'")
    exit_rows = [dict(r) for r in await cur.fetchall()]
    assert {r["contract_symbol"] for r in exit_rows} == {"NVDA1", "NVDA2"}
    assert all(r["capture_session"] == "2026-08-31" for r in exit_rows)


# ─────────────── positions that never got a real ENTRY slice ───────────────
# (e.g. the four live TODO #96 trades that entered before this module
# existed: AMZN/GOOGL/META/BMNR, 2026-08-25 -> 2026-08-31)

async def test_first_mark_establishes_tracking_tagged_mark_not_entry(tmp_db, monkeypatch):
    """A position with NO stored ENTRY slice gets its tracked set established
    by the first MARK call, using the bounded window rule, anchored on
    TODAY's stock price -- and the resulting rows are tagged 'MARK', never
    'ENTRY' (rule point 1 and 2)."""
    row = await _seed_row(ticker="AMZN", entry_session="2026-08-25",
                          exit_session="2026-08-31")
    # No capture_entry() call at all -- exactly the real AMZN/GOOGL/META/BMNR
    # situation. Strike window is anchored on the CAPTURE day's price (230),
    # not the stored entry_stock_px (240) from _seed_row.
    rows = [_contract("AMZN1", 170.0, "2026-09-10"),   # 0.70*230=161..253
           _contract("AMZN2", 230.0, "2026-09-10"),
           _contract("AMZN3", 100.0, "2026-09-10")]     # below window -> excluded
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))

    out = await pfoc.capture_mark(row, stock_quote=_quote(230.0), spy_quote=_quote(645.0))
    assert out["error"] is None
    assert out["established_mid_trade"] is True
    assert out["entry_source"] == "MARK"
    assert out["contracts_captured"] == 2

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT stage, contract_symbol, underlying_px FROM put_flow_option_snapshots "
        "WHERE shortlist_id=?", (row["id"],))
    stored = [dict(r) for r in await cur.fetchall()]
    assert all(r["stage"] == "MARK" for r in stored)     # never 'ENTRY'
    assert {r["contract_symbol"] for r in stored} == {"AMZN1", "AMZN2"}
    assert all(r["underlying_px"] == 230.0 for r in stored)   # capture-day price


async def test_later_mark_and_exit_track_the_established_set(tmp_db, monkeypatch):
    """After the first MARK establishes tracking, later MARK/EXIT calls
    re-price exactly that set, same as a normal ENTRY-based position."""
    row = await _seed_row(ticker="GOOGL", entry_session="2026-08-25",
                          exit_session="2026-08-31")
    first_rows = [_contract("G1", 200.0, "2026-09-10"),
                 _contract("G2", 240.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(first_rows))
    from datetime import datetime
    from zoneinfo import ZoneInfo
    first_mark_ts = datetime(2026, 8, 26, 6, 35, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    await pfoc.capture_mark(row, stock_quote=_quote(230.0), spy_quote=_quote(645.0),
                            now=first_mark_ts)

    # A different chain on a later day, with a brand-new contract G3 -- the
    # established set (G1/G2) is still the only thing tracked.
    later_rows = [_contract("G1", 200.0, "2026-09-10"),
                 _contract("G2", 240.0, "2026-09-10"),
                 _contract("G3", 260.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(later_rows))
    out = await pfoc.capture_exit(row, stock_quote=_quote(225.0), spy_quote=_quote(648.0))
    assert out["entry_source"] == "MARK"
    assert out["established_mid_trade"] is False
    assert out["contracts_captured"] == 2
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT contract_symbol FROM put_flow_option_snapshots WHERE stage='EXIT'")
    assert {r["contract_symbol"] for r in await cur.fetchall()} == {"G1", "G2"}


async def test_pnl_unknown_for_a_position_established_mid_trade(tmp_db, monkeypatch):
    row = await _seed_row(ticker="META", entry_session="2026-08-25",
                          exit_session="2026-08-31")
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain([_contract("M1", 200.0, "2026-09-10")]))
    await pfoc.capture_mark(row, stock_quote=_quote(230.0), spy_quote=_quote(645.0))
    await pfoc.capture_exit(row, stock_quote=_quote(225.0), spy_quote=_quote(648.0))

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT * FROM put_flow_option_snapshots WHERE stage='MARK' LIMIT 1")
    mark_row = dict(await cur.fetchone())
    cur = await conn.execute(
        "SELECT * FROM put_flow_option_snapshots WHERE stage='EXIT' LIMIT 1")
    exit_row = dict(await cur.fetchone())
    out = pfoc.option_leg_pnl(mark_row, exit_row)
    assert out["status"] == "UNKNOWN"
    assert out["reason"] == "no entry quote for this position"


async def test_report_distinguishes_real_entry_from_mid_trade_tracking(tmp_db, monkeypatch):
    real_entry_row = await _seed_row(ticker="NVDA", entry_session="2026-08-25",
                                     exit_session="2026-08-31")
    mid_trade_row = await _seed_row(ticker="BMNR", entry_session="2026-08-25",
                                    exit_session="2026-08-31")
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain([_contract("X1", 200.0, "2026-09-10")]))
    await pfoc.capture_entry(real_entry_row, stock_quote=_quote(240.0),
                             spy_quote=_quote(640.0))
    await pfoc.capture_mark(mid_trade_row, stock_quote=_quote(230.0),
                            spy_quote=_quote(645.0))

    rep = await pfoc.report()
    assert rep["entry_source_summary"] == {"with_real_entry": 1, "mid_trade_no_entry": 1}
    assert "1 have a real" in rep["text"]
    assert "1 are tracking started mid-trade" in rep["text"]
    assert "option profit for them can never be measured" in rep["text"]


# ───────────────────────── idempotency: no duplicates ──────────────────────

async def test_repeated_capture_cannot_duplicate_a_row(tmp_db, monkeypatch):
    row = await _seed_row()
    rows = [_contract("NVDA1", 200.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))

    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))
    await pfoc.capture_entry(row, stock_quote=_quote(241.0), spy_quote=_quote(641.0))

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM put_flow_option_snapshots WHERE stage='ENTRY'")
    assert (await cur.fetchone())["n"] == 1

    # The SECOND call's different quote must NOT have overwritten the first.
    cur = await conn.execute(
        "SELECT underlying_px FROM put_flow_option_snapshots WHERE stage='ENTRY'")
    assert (await cur.fetchone())["underlying_px"] == 240.0

    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM put_flow_borrow_snapshots WHERE stage='ENTRY'")
    assert (await cur.fetchone())["n"] == 1


# ───────────────────────── stale / missing honesty ──────────────────────

async def test_stale_quote_is_stored_and_labelled_never_invented(tmp_db, monkeypatch):
    row = await _seed_row()
    old_ms = int((time.time() - 3000) * 1000)   # older than 900s max age
    rows = [_contract("NVDA1", 200.0, "2026-09-10", bid=1.0, ask=1.1, qt_ms=old_ms)]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT quote_quality, bid, ask FROM put_flow_option_snapshots WHERE stage='ENTRY'")
    r = dict(await cur.fetchone())
    assert r["quote_quality"] == "STALE"
    assert r["bid"] == 1.0 and r["ask"] == 1.1     # stored, not dropped


async def test_missing_contract_is_null_never_filled_from_last_or_later(tmp_db, monkeypatch):
    row = await _seed_row()
    entry_rows = [_contract("NVDA1", 200.0, "2026-09-10", last=5.0)]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(entry_rows))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    # The contract has vanished from the chain by MARK time.
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain([]))
    out = await pfoc.capture_mark(row, stock_quote=_quote(230.0), spy_quote=_quote(645.0))
    assert out["missing"] == 1

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT quote_quality, bid, ask, last, mark FROM put_flow_option_snapshots "
        "WHERE stage='MARK'")
    r = dict(await cur.fetchone())
    assert r["quote_quality"] == "MISSING"
    assert r["bid"] is None and r["ask"] is None and r["last"] is None and r["mark"] is None

    # A LATER (EXIT) snapshot re-appearing must never retroactively fill MARK.
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain([_contract("NVDA1", 200.0, "2026-09-10")]))
    await pfoc.capture_exit(row, stock_quote=_quote(225.0), spy_quote=_quote(648.0))
    cur = await conn.execute(
        "SELECT bid FROM put_flow_option_snapshots WHERE stage='MARK'")
    assert (await cur.fetchone())["bid"] is None    # still null


# ───────────────────────── option_leg_pnl ──────────────────────

def test_pnl_uses_entry_ask_and_exit_bid():
    entry = {"stage": "ENTRY", "quote_quality": "OK", "ask": 2.00, "bid": 1.80}
    exit_ = {"stage": "EXIT", "quote_quality": "OK", "ask": 3.10, "bid": 2.90}
    out = pfoc.option_leg_pnl(entry, exit_)
    assert out["status"] == "OK"
    assert out["entry_ask"] == 2.00 and out["exit_bid"] == 2.90
    assert out["pnl_per_contract"] == pytest.approx(0.90)


@pytest.mark.parametrize("entry_q,exit_q", [
    ("STALE", "OK"), ("OK", "STALE"), ("NO_TWO_SIDED", "OK"),
    ("OK", "MISSING"), ("MISSING", "MISSING"),
])
def test_pnl_is_unknown_unless_both_sides_are_ok(entry_q, exit_q):
    entry = {"stage": "ENTRY", "quote_quality": entry_q, "ask": 2.0, "bid": 1.8}
    exit_ = {"stage": "EXIT", "quote_quality": exit_q, "ask": 3.0, "bid": 2.8}
    out = pfoc.option_leg_pnl(entry, exit_)
    assert out["status"] == "UNKNOWN"
    assert "pnl_pct" not in out


def test_pnl_is_unknown_when_entry_side_is_mark_established():
    """A MARK-established 'first tracked' row is a real market price, but it
    is NOT a real entry quote — it must never price the entry leg."""
    entry = {"stage": "MARK", "quote_quality": "OK", "ask": 2.0, "bid": 1.8}
    exit_ = {"stage": "EXIT", "quote_quality": "OK", "ask": 3.0, "bid": 2.8}
    out = pfoc.option_leg_pnl(entry, exit_)
    assert out["status"] == "UNKNOWN"
    assert out["reason"] == "no entry quote for this position"


# ───────────────────────── borrow: raw, unproven units ──────────────────────

async def test_borrow_fields_are_raw_and_units_unknown(tmp_db, monkeypatch):
    row = await _seed_row()
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain([_contract("NVDA1", 200.0, "2026-09-10")]))
    q = _quote(240.0, shortable=True, hard_to_borrow=True, htb_rate=12.5)
    await pfoc.capture_entry(row, stock_quote=q, spy_quote=_quote(640.0))

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT shortable, hard_to_borrow, htb_rate, rate_units FROM "
        "put_flow_borrow_snapshots WHERE stage='ENTRY'")
    r = dict(await cur.fetchone())
    assert r["shortable"] == 1 and r["hard_to_borrow"] == 1
    assert r["htb_rate"] == 12.5     # stored exactly as Schwab sent it
    assert r["rate_units"] == "UNKNOWN"
    assert pfoc.HTB_RATE_UNITS == "UNKNOWN"


# ───────────────────────── fail-soft ──────────────────────

async def test_a_schwab_exception_for_one_ticker_does_not_abort_the_run(tmp_db, monkeypatch):
    good = await _seed_row(ticker="NVDA", entry_session="2026-08-20",
                           exit_session="2026-08-26")
    bad = await _seed_row(ticker="TSLA", entry_session="2026-08-20",
                          exit_session="2026-08-26")

    # NVDA already has an ENTRY slice; TSLA also does, so both are "open".
    def chain_factory(sym, **_):
        if sym == "NVDA":
            return _chain([_contract("NVDA1", 200.0, "2026-09-05")])
        raise RuntimeError("TSLA")
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda sym, **k: chain_factory(sym, **k))
    await pfoc.capture_entry(good, stock_quote=_quote(240.0), spy_quote=_quote(640.0))
    # Force TSLA's ENTRY row too, working around the raising mock via a
    # temporary good chain, so a real ENTRY slice exists for the MARK test.
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda sym, **k: _chain([_contract("TSLA1", 200.0, "2026-09-05")]))
    await pfoc.capture_entry(bad, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    # Now MARK: NVDA succeeds, TSLA's chain fetch raises.
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda sym, **k: chain_factory(sym, **k))

    def get_quotes(symbols):
        return {s: _quote(240.0) for s in symbols}
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_quotes", get_quotes)

    out = await pfoc.capture_open_positions(session="2026-08-24", stage="MARK")
    assert out["positions_expected"] == 2
    assert "TSLA" in out["errors"]
    assert out["positions_captured"] == 1     # NVDA succeeded despite TSLA's failure

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT errors_json FROM put_flow_capture_runs WHERE capture_session=? "
        "AND stage='MARK'", ("2026-08-24",))
    errors_json = (await cur.fetchone())["errors_json"]
    assert "TSLA" in json.loads(errors_json)


async def test_run_row_keeps_stale_and_no_two_sided_separate_where_possible(tmp_db, monkeypatch):
    """put_flow_capture_runs has no no-two-sided column, so the DB row's
    stale_quotes is the merged count -- but the function's RETURNED dict
    must keep the two apart, and report() (which reads the raw snapshot
    rows, not this audit row) must too."""
    import datetime as _dt
    today = pfoc.pacific_session(time.time())
    today_d = _dt.date.fromisoformat(today)
    entry_session = (today_d - _dt.timedelta(days=5)).isoformat()
    exit_session = (today_d + _dt.timedelta(days=5)).isoformat()
    row = await _seed_row(ticker="NVDA", entry_session=entry_session,
                          exit_session=exit_session)
    rows = [_contract("N1", 200.0, "2026-09-05", qt_ms=int((time.time() - 3000) * 1000)),
           _contract("N2", 210.0, "2026-09-05", bid=0, ask=0)]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_quotes",
        lambda symbols: {s: _quote(240.0) for s in symbols})
    out = await pfoc.capture_open_positions(session=today, stage="MARK")
    assert out["stale_quotes"] == 2               # DB-column value: merged
    assert out["no_two_sided_quotes"] == 1         # returned dict: kept apart

    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT stale_quotes FROM put_flow_capture_runs WHERE capture_session=? "
        "AND stage='MARK'", (today,))
    assert (await cur.fetchone())["stale_quotes"] == 2   # the db row itself is merged

    rep = await pfoc.report(session=today)
    mark = rep["by_stage"]["MARK"]["contracts"]
    assert mark["STALE"] == 1 and mark["NO_TWO_SIDED"] == 1   # report keeps them apart


# ───────────────────────── report matches storage ──────────────────────

async def test_report_counts_match_rows_actually_stored(tmp_db, monkeypatch):
    row = await _seed_row()
    rows = [_contract("NVDA1", 200.0, "2026-09-10"),
           _contract("NVDA2", 240.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    rep = await pfoc.report(session="2026-08-25")
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS n FROM put_flow_option_snapshots WHERE stage='ENTRY' "
        "AND capture_session='2026-08-25'")
    n = (await cur.fetchone())["n"]
    assert sum(rep["by_stage"]["ENTRY"]["contracts"].values()) == n == 2
    assert rep["option_pnl_status"] == "UNKNOWN"
    assert "no frozen evaluator" in rep["option_pnl_reason"]
    assert isinstance(rep["text"], str) and "ENTRY" in rep["text"]


# ───────────────────────── Pacific time only ──────────────────────

async def test_all_owner_visible_time_is_pacific_no_et_label(tmp_db, monkeypatch):
    row = await _seed_row()
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain([_contract("NVDA1", 200.0, "2026-09-10")]))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))
    rep = await pfoc.report()
    text = rep["text"]
    assert "ET" not in text.split() and "Eastern" not in text
    assert str(pfoc.PT) == "America/Los_Angeles"
    assert pfoc.pacific_session(time.time())    # does not raise, returns a date string


# ───────────── a dry run writes nothing, and counts never contradict ─────────
#
# Both of these were REAL defects found by running the live 6:35 sequence
# against a copy of the production database, not by reading the code. The dry
# run used to write the option and borrow rows and skip only the audit row, so
# the morning proof check then reported "the collection never ran" while 586
# contracts sat in the table, and the plain-English report read "0 of 0
# positions captured, 586 option contracts stored".

async def test_dry_run_writes_absolutely_nothing(tmp_db, monkeypatch):
    row = await _seed_row()
    rows = [_contract("NVDA1", 200.0, "2026-09-10"),
            _contract("NVDA2", 210.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_quotes",
        lambda syms: {s: _quote(240.0) for s in syms})

    out = await pfoc.capture_open_positions(session=row["entry_session"],
                                            stage="ENTRY", dry_run=True)
    assert out["dry_run"] is True
    assert out["contracts_captured"] == 2      # it still REPORTS what it would do

    conn = await db.get_db()
    for table in ("put_flow_option_snapshots", "put_flow_borrow_snapshots",
                  "put_flow_capture_runs"):
        cur = await conn.execute(f"SELECT COUNT(*) AS n FROM {table}")
        assert (await cur.fetchone())["n"] == 0, f"dry run wrote to {table}"

    # And the flag must not leak into the next, real call.
    await pfoc.capture_open_positions(session=row["entry_session"],
                                      stage="ENTRY", dry_run=False)
    cur = await conn.execute("SELECT COUNT(*) AS n FROM put_flow_option_snapshots")
    assert (await cur.fetchone())["n"] == 2


async def test_report_never_says_zero_positions_beside_stored_contracts(
        tmp_db, monkeypatch):
    row = await _seed_row()
    rows = [_contract("NVDA1", 200.0, "2026-09-10")]
    monkeypatch.setattr(
        "consensus_engine.scanners.schwab_client.get_option_chain",
        lambda *a, **k: _chain(rows))
    await pfoc.capture_entry(row, stock_quote=_quote(240.0), spy_quote=_quote(640.0))

    # No audit row exists — capture_entry() alone does not write one. The report
    # must still count the positions that really have stored rows.
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) AS n FROM put_flow_capture_runs")
    assert (await cur.fetchone())["n"] == 0

    out = await pfoc.report()
    entry = out["by_stage"]["ENTRY"]
    stored = sum(entry["contracts"].values())
    assert stored == 1
    assert entry["positions_captured"] == 1, "counted 0 positions beside stored rows"
    assert entry["positions_expected"] == 1
    assert "0 of 0 positions" not in out["text"]
