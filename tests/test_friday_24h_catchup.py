"""#73: Friday's 24h outcomes must survive the weekend pause.

The engine pauses Fri 3pm → Sun 3pm PDT. The live 24h fill reads a spot price
in a 24–48h window, which for a Friday alert falls entirely inside the pause —
so Friday rows aged out permanently unfillable (4% resolution vs ~100% Mon–Wed).
The fix grades aged-out rows from historical daily bars at the next trading
day's close. Covers:

  - the 'price_24h_catchup' selector picks ONLY rows past the live-spot window
  - _fill_alert_24h_catchup writes all three tables the live path writes
    (alert_history, the linked decision_snapshot, the shadow-prediction label)
  - the completed-session guard: a bar dated today is not used for grading
    until the 4pm ET close (else it is a live mid-session price, not a close)
"""

import time
from datetime import datetime, timezone

import pandas as pd
import pytest

import consensus_engine.db as db
from consensus_engine import main as engine_main


@pytest.fixture
def fresh_db(tmp_path):
    """Fresh temp DB (full schema). Never touches the live consensus.db."""
    db.DB_PATH = str(tmp_path / "test.db")
    db._db = None
    yield


@pytest.fixture(autouse=True)
def _reset_db_state():
    yield
    db._db = None
    db.DB_PATH = None


async def _insert_alert(conn, ticker, age_days, price_at_alert=100.0,
                        price_24h_later=None):
    cur = await conn.execute(
        """INSERT INTO alert_history
           (ticker, alerted_at, price_at_alert, price_24h_later)
           VALUES (?, ?, ?, ?)""",
        (ticker, time.time() - age_days * 86400, price_at_alert, price_24h_later),
    )
    await conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# (a) Selector: catch-up band starts where the live-spot band ends
# ---------------------------------------------------------------------------

async def test_catchup_selector_only_sees_aged_out_rows(fresh_db):
    conn = await db.init_db()
    live_band = await _insert_alert(conn, "LIVE", age_days=1.25)   # 30h → live window
    friday = await _insert_alert(conn, "FRI", age_days=3)          # slept through
    ancient = await _insert_alert(conn, "OLD", age_days=40)        # past 30d cap
    filled = await _insert_alert(conn, "DONE", age_days=3,
                                 price_24h_later=105.0)            # already graded

    catchup_ids = {a["id"] for a in
                   await db.get_alerts_needing_price_update("price_24h_catchup")}
    assert friday in catchup_ids
    assert live_band not in catchup_ids   # still the live-spot fill's job
    assert ancient not in catchup_ids     # bounded loop skips ancient rows
    assert filled not in catchup_ids      # only NULLs

    # The one-off backfill (no upper bound) reaches the ancient row too.
    unbounded_ids = {a["id"] for a in await db.get_alerts_needing_price_update(
        "price_24h_catchup", ignore_max_age=True)}
    assert {friday, ancient} <= unbounded_ids
    assert live_band not in unbounded_ids

    # The live-spot selector is unchanged by the new band.
    live_ids = {a["id"] for a in
                await db.get_alerts_needing_price_update("price_24h_later")}
    assert live_ids == {live_band}
    await db.close_db()


# ---------------------------------------------------------------------------
# (b) Friday regression: an aged-out alert resolves via bars, all 3 tables
# ---------------------------------------------------------------------------

async def test_friday_alert_resolves_after_weekend(fresh_db, monkeypatch):
    """A Friday-scored alert (now 3 days old, live window long gone) still gets
    its 24h outcome — on alert_history, its decision_snapshot, and the shadow
    label — graded at the NEXT trading day's close (n_trading_days=1)."""
    conn = await db.init_db()
    alert_id = await _insert_alert(conn, "FRI", age_days=3, price_at_alert=100.0)
    await conn.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, sources_json, recorded_at,
            outcome_price_at_alert, alert_id)
           VALUES ('FRI', 'STRONG', 80.0, '[]', ?, 100.0, ?)""",
        (time.time() - 3 * 86400, alert_id),
    )
    await conn.execute(
        """INSERT INTO shadow_predictions
           (alert_id, predicted_prob, horizon, actual_hit, created_at)
           VALUES (?, 0.7, '24h', NULL, ?)""",
        (alert_id, int(time.time() - 3 * 86400)),
    )
    await conn.commit()

    seen_n = []

    def _fake_close(ticker, alerted_at, n_trading_days):
        seen_n.append(n_trading_days)
        return 104.0  # Monday's close, an UP move from the 100.0 entry

    monkeypatch.setattr(
        engine_main, "_fetch_yfinance_close_n_trading_days_later", _fake_close)

    import asyncio
    import concurrent.futures
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        filled = await engine_main._fill_alert_24h_catchup(
            asyncio.get_running_loop(), executor)
    finally:
        executor.shutdown(wait=False)

    assert filled == 1
    assert seen_n == [1]  # graded at the NEXT trading day's close

    cur = await conn.execute(
        "SELECT price_24h_later FROM alert_history WHERE id = ?", (alert_id,))
    assert (await cur.fetchone())["price_24h_later"] == 104.0
    cur = await conn.execute(
        "SELECT outcome_price_24h FROM decision_snapshots WHERE alert_id = ?",
        (alert_id,))
    assert (await cur.fetchone())["outcome_price_24h"] == 104.0
    cur = await conn.execute(
        "SELECT actual_hit FROM shadow_predictions WHERE alert_id = ?", (alert_id,))
    assert (await cur.fetchone())["actual_hit"] == 1  # 104 > 100 → hit

    # Re-run: the row is no longer NULL → nothing selected, nothing rewritten.
    executor2 = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        assert await engine_main._fill_alert_24h_catchup(
            asyncio.get_running_loop(), executor2) == 0
    finally:
        executor2.shutdown(wait=False)
    await db.close_db()


# ---------------------------------------------------------------------------
# (c) Completed-session guard: today's still-forming bar is never a "close"
# ---------------------------------------------------------------------------

class _FakeTickerWithDates:
    def __init__(self, closes, dates):
        self._df = pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(dates))

    def history(self, **kwargs):
        return self._df


class _FrozenDT(datetime):
    """datetime with a pinned now(); fromtimestamp etc. inherit real behavior."""
    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now.astimezone(tz) if tz is not None else cls._now


def _pin_now(monkeypatch, iso_et):
    from zoneinfo import ZoneInfo
    _FrozenDT._now = datetime.fromisoformat(iso_et).replace(
        tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(engine_main, "datetime", _FrozenDT)


def test_guard_rejects_todays_bar_during_market_hours(monkeypatch):
    import yfinance
    # Friday 2026-07-10 alert; bars: Fri 7/10 (bar 0) and Mon 7/13 (bar 1).
    fri_alert_ts = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc).timestamp()
    fake = _FakeTickerWithDates([100.0, 103.5], ["2026-07-10", "2026-07-13"])
    monkeypatch.setattr(yfinance, "Ticker", lambda t: fake)

    # Monday 10:30 ET — bar 1 is TODAY and still forming → refuse to grade.
    _pin_now(monkeypatch, "2026-07-13T10:30:00")
    assert engine_main._fetch_yfinance_close_n_trading_days_later(
        "X", fri_alert_ts, 1) == 0.0

    # Monday 16:30 ET — the session has closed → Monday's close is a real close.
    _pin_now(monkeypatch, "2026-07-13T16:30:00")
    assert engine_main._fetch_yfinance_close_n_trading_days_later(
        "X", fri_alert_ts, 1) == 103.5

    # Tuesday morning — bar 1 is a fully past session → fine even pre-open.
    _pin_now(monkeypatch, "2026-07-14T09:00:00")
    assert engine_main._fetch_yfinance_close_n_trading_days_later(
        "X", fri_alert_ts, 1) == 103.5
