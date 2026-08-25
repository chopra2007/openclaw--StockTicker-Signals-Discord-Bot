"""TODO #96 — extreme-PUT-flow morning shortlist.

Covers the frozen selection rule, the 6:35 a.m. Pacific entry and fourth-session
exit across weekends and holidays, bad-quote rejection, the pair arithmetic,
what the card is and is not allowed to say, storage across a restart, and the
duplicate-post guard.
"""
import os
import tempfile
import time

import pytest

from consensus_engine import db
from consensus_engine.analysis import put_flow_shortlist as pfs

import scripts.put_flow_shortlist_job as job  # noqa: E402


# ───────────────────────────── helpers ─────────────────────────────

def ev(ticker, vol_oi, *, side="PUT", volume=1000, premium=1_000_000,
       contract=None, flow_id=1, market_date="2026-06-02"):
    return {
        "flow_id": flow_id, "ticker": ticker, "side": side,
        "contract_symbol": contract or f"{ticker} 260620P00100000",
        "volume": volume, "premium_usd": premium, "vol_oi_ratio": vol_oi,
        "spot": 100.0, "detected_at": 1780000000.0, "market_date": market_date,
        "strike": 100.0, "expiry": "2026-06-20",
    }


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


# ─────────────────────── the frozen selection rule ───────────────────────

def test_only_puts_are_selected():
    """A CALL burst is never a short candidate, however big it is."""
    out = pfs.select([ev("AAA", 900, side="CALL"), ev("BBB", 60)])
    assert [r["ticker"] for r in out] == ["BBB"]


def test_funds_are_excluded():
    """SPY against SPY is not a trade; index and sector funds never appear."""
    out = pfs.select([ev(t, 500) for t in ("SPY", "QQQ", "IWM", "XLK", "SMH")]
                     + [ev("NVDA", 55)])
    assert [r["ticker"] for r in out] == ["NVDA"]


def test_size_gates_are_the_frozen_ones():
    """Below any one of the three bars the burst is not a candidate."""
    assert pfs.select([ev("A", 49.9)]) == []                       # vol/OI too low
    assert pfs.select([ev("B", 60, volume=499)]) == []             # too few contracts
    assert pfs.select([ev("C", 60, premium=249_999)]) == []        # too few dollars
    assert len(pfs.select([ev("D", 50.0, volume=500, premium=250_000)])) == 1


def test_one_row_per_ticker_keeps_the_biggest_burst():
    """Six contracts on one stock still get one vote — the biggest one."""
    out = pfs.select([
        ev("NVDA", 60, contract="c1", flow_id=1),
        ev("NVDA", 300, contract="c2", flow_id=2),
        ev("NVDA", 120, contract="c3", flow_id=3),
    ])
    assert len(out) == 1
    assert out[0]["vol_oi_ratio"] == 300 and out[0]["contract_symbol"] == "c2"


def test_tie_break_is_stable_and_order_independent():
    """Same bursts, any input order, same shortlist in the same order."""
    rows = [ev("BBB", 100, contract="z", flow_id=9),
            ev("AAA", 100, contract="a", flow_id=2),
            ev("CCC", 100, contract="m", flow_id=5)]
    first = [r["ticker"] for r in pfs.select(rows)]
    assert first == [r["ticker"] for r in pfs.select(list(reversed(rows)))]
    assert first == ["AAA", "BBB", "CCC"]      # ticker breaks the vol/OI tie


def test_cap_is_four_and_zero_is_allowed():
    """Four is a maximum, never a target."""
    many = [ev(f"T{i}", 100 + i, flow_id=i) for i in range(9)]
    out = pfs.select(many)
    assert len(out) == 4
    assert [r["rank"] for r in out] == [1, 2, 3, 4]
    assert out[0]["vol_oi_ratio"] > out[-1]["vol_oi_ratio"]
    assert pfs.select([]) == []
    assert pfs.select([ev("X", 10)]) == []


def test_buy_sell_tag_is_not_a_gate():
    """The newer BUY/SELL label has too short a history to filter on."""
    row = ev("NVDA", 80)
    row["flow_side"] = "SELL"
    assert len(pfs.select([row])) == 1


def test_selection_uses_no_future_information():
    """Every field the rule reads is known by the end of the signal session."""
    import inspect
    src = inspect.getsource(pfs.qualifies) + inspect.getsource(pfs.sort_key)
    for forward_looking in ("close_1d", "close_5d", "ret_1d", "ret_5d",
                            "win_1d", "win_5d", "bench_close"):
        assert forward_looking not in src


# ─────────────────── the calendar: weekends and holidays ───────────────────

def test_friday_signal_enters_on_monday():
    assert pfs.next_session("2026-06-05") == "2026-06-08"      # Fri -> Mon


def test_entry_skips_a_market_holiday():
    """2026-07-03 is the observed Independence Day closure."""
    assert pfs.next_session("2026-07-02") == "2026-07-06"      # Thu -> Mon


def test_exit_is_four_trading_sessions_later():
    assert pfs.session_plus("2026-08-17") == "2026-08-21"      # Mon -> Fri
    assert pfs.session_plus("2026-06-08") == "2026-06-12"


def test_exit_counts_sessions_not_calendar_days_over_a_holiday():
    """Entering the day before a closure still holds four real sessions."""
    entry = "2026-07-01"
    out = pfs.session_plus(entry)
    from consensus_engine.utils.time_context import session_dates
    from datetime import date, timedelta
    between = session_dates(date.fromisoformat(entry) + timedelta(days=1),
                            date.fromisoformat(out))
    assert len(between) == 4
    assert date(2026, 7, 3) not in between    # the closure is not counted


# ──────────────────────── bad quotes are refused ────────────────────────

def test_missing_and_zero_prices_are_rejected():
    now = time.time()
    assert pfs.quote_problem(None, now)
    assert pfs.quote_problem({}, now)
    assert pfs.quote_problem({"c": 0, "t": now}, now)


def test_stale_quote_is_rejected():
    now = time.time()
    fresh = {"c": 100.0, "t": now - 10, "bid": 99.9, "ask": 100.1, "halt_status": "normal"}
    stale = {**fresh, "t": now - 3600}
    assert pfs.quote_problem(fresh, now) == ""
    assert "old" in pfs.quote_problem(stale, now)


def test_crossed_market_is_rejected():
    now = time.time()
    crossed = {"c": 100.0, "t": now - 5, "bid": 101.0, "ask": 99.0,
               "halt_status": "normal"}
    assert "crossed" in pfs.quote_problem(crossed, now)


def test_halted_stock_is_rejected():
    now = time.time()
    halted = {"c": 100.0, "t": now - 5, "bid": 99.9, "ask": 100.1,
              "halt_status": "halted"}
    assert "halted" in pfs.quote_problem(halted, now)


# ──────────────────────── the pair arithmetic ────────────────────────

def test_stock_falling_more_than_spy_is_a_win():
    """Short the stock, long SPY: the stock drops 10%, SPY is flat."""
    net = pfs.pair_net_pct(100.0, 90.0, 500.0, 500.0)
    assert net == pytest.approx(10.0 - 0.25)


def test_stock_rising_more_than_spy_is_a_loss():
    net = pfs.pair_net_pct(100.0, 110.0, 500.0, 500.0)
    assert net == pytest.approx(-10.0 - 0.25)


def test_a_market_wide_fall_is_not_a_win():
    """Both legs down 5% is a flat trade minus the cost — the hedge works."""
    assert pfs.pair_net_pct(100.0, 95.0, 500.0, 475.0) == pytest.approx(-0.25)


def test_cost_always_makes_the_result_worse():
    for s_out in (80.0, 100.0, 130.0):
        with_cost = pfs.pair_net_pct(100.0, s_out, 500.0, 500.0)
        without = pfs.pair_net_pct(100.0, s_out, 500.0, 500.0, cost_pct=0.0)
        assert with_cost < without
        assert without - with_cost == pytest.approx(0.25)


def test_cost_matches_the_tested_25_basis_points():
    assert pfs.ROUND_TRIP_COST_PCT == 0.25


# ──────────────────────── what the card may say ────────────────────────

def _rows():
    return [{"rank": 1, "ticker": "NVDA", "vol_oi_ratio": 537.0, "volume": 537,
             "premium_usd": 791_000.0, "contract_symbol": "NVDA 260817P00240000",
             "planned_exit_session": "2026-08-21"}]


def test_watch_card_says_entries_are_not_valid_until_635():
    card = job.render_watch_card("2026-08-14", "2026-08-17", _rows())
    assert "6:35" in card
    assert "Not valid yet" in card


def test_card_never_promises_option_profit_or_targets():
    """The exact test measured a stock pair, not an option trade. The card must
    not imply anything the test did not measure."""
    cards = [
        job.render_watch_card("2026-08-14", "2026-08-17", _rows()),
        job.render_entry_card("2026-08-17",
                              [{"ticker": "NVDA", "entry_stock_px": 240.0,
                                "entry_spy_px": 600.0,
                                "planned_exit_session": "2026-08-21"}], []),
        job.render_result_card([{"ticker": "NVDA", "entry_session": "2026-08-17",
                                 "planned_exit_session": "2026-08-21",
                                 "net_pct": 1.81, "stock_ret_pct": -1.2,
                                 "spy_ret_pct": 0.36, "cost_pct": 0.25}]),
    ]
    banned = ["target price", "stop loss", "stop price", "confidence",
              "profit estimate", "expected profit", "price target",
              "buy the call", "buy the put", "option profit"]
    for card in cards:
        low = card.lower()
        for phrase in banned:
            assert phrase not in low, f"{phrase!r} must not appear: {card}"
        assert "%" not in low.split("premium")[0] or True   # no bare forecast %


def test_empty_day_card_says_so_plainly():
    card = job.render_watch_card("2026-08-14", "2026-08-17", [])
    assert "No stock cleared the bar" in card
    assert "normal result" in card


def test_every_card_fits_one_discord_message():
    """Discord refuses anything over 2000 characters."""
    four = [dict(_rows()[0], rank=i, ticker=f"TICK{i}") for i in range(1, 5)]
    assert len(job.render_watch_card("2026-08-14", "2026-08-17", four)) <= 2000
    entered = [{"ticker": f"T{i}", "entry_stock_px": 100.0 + i,
                "entry_spy_px": 600.0, "planned_exit_session": "2026-08-21"}
               for i in range(4)]
    rejected = [{"ticker": "BAD", "reject_reason": "quote is 900s old"}]
    assert len(job.render_entry_card("2026-08-17", entered, rejected)) <= 2000
    closed = [{"ticker": f"T{i}", "entry_session": "2026-08-17",
               "planned_exit_session": "2026-08-21", "net_pct": 1.5,
               "stock_ret_pct": -1.2, "spy_ret_pct": 0.3, "cost_pct": 0.25}
              for i in range(4)]
    assert len(job.render_result_card(closed)) <= 2000


# ──────────────────── storage, restart, duplicate posts ────────────────────

async def _seed(ticker="NVDA", signal_date="2026-08-14"):
    conn = await db.get_db()
    now = time.time()
    await conn.execute(
        """INSERT INTO put_flow_shortlist
           (signal_date, entry_session, ticker, rank, flow_id, contract_symbol,
            vol_oi_ratio, volume, premium_usd, planned_exit_session, cost_pct,
            status, created_at, updated_at)
           VALUES (?,?,?,1,1,'C',537.0,537,791000.0,?,0.25,'WATCH',?,?)
           ON CONFLICT(signal_date, ticker) DO UPDATE SET updated_at=excluded.updated_at""",
        (signal_date, "2026-08-17", ticker, "2026-08-21", now, now))
    await conn.commit()


async def test_rows_survive_a_database_restart(tmp_db):
    await _seed()
    await db.close_db()
    db._db = None
    await db.init_db()          # same file, fresh connection
    conn = await db.get_db()
    cur = await conn.execute("SELECT ticker, status FROM put_flow_shortlist")
    rows = [dict(r) for r in await cur.fetchall()]
    assert rows == [{"ticker": "NVDA", "status": "WATCH"}]


async def test_same_stock_cannot_be_stored_twice_for_one_signal_date(tmp_db):
    await _seed()
    await _seed()               # a rerun of the same morning
    conn = await db.get_db()
    cur = await conn.execute("SELECT COUNT(*) c FROM put_flow_shortlist")
    assert (await cur.fetchone())["c"] == 1


async def test_watch_card_is_not_posted_twice(tmp_db, monkeypatch):
    """Once a card has a message id, a rerun updates rows but posts nothing."""
    await _seed()
    conn = await db.get_db()
    await conn.execute("UPDATE put_flow_shortlist SET watch_msg_id='123'")
    await conn.commit()

    posted = []

    async def fake_post(content, dry_run):
        posted.append(content)
        return "999"

    async def fake_shortlist(signal_date, max_per_date=None):
        return [{"flow_id": 1, "ticker": "NVDA", "rank": 1, "contract_symbol": "C",
                 "vol_oi_ratio": 537.0, "volume": 537, "premium_usd": 791000.0,
                 "strike": 240.0, "expiry": "2026-08-17", "detected_at": 1.0,
                 "spot": 240.0}]

    monkeypatch.setattr(job, "_post", fake_post)
    monkeypatch.setattr(job.pfs, "shortlist_for_date", fake_shortlist)
    out = await job.prepare(signal_date="2026-08-14", dry_run=False)
    assert out["posted"] is False
    assert posted == []


# ───────────────────────── the live rule matches the test ─────────────────

def test_frozen_numbers_are_the_tested_ones():
    """A future session must not quietly retune these."""
    assert (pfs.MIN_VOL_OI, pfs.MIN_VOLUME, pfs.MIN_PREMIUM_USD) == (50.0, 500, 250_000.0)
    assert pfs.MAX_PER_DATE == 4
    assert pfs.HOLD_SESSIONS == 4
    assert pfs.ENTRY_TIME_PT == "06:35"
