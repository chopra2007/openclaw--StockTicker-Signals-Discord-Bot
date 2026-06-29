"""Tests for 5d/20d trading-day outcome tracking on decision_snapshots (schema v22).

Covers:
  - migration adds outcome_price_5d/20d idempotently, existing rows/data survive
  - get_snapshots_needing_outcome age gate (old rows in, fresh rows out)
  - _fetch_yfinance_close_n_trading_days_later picks the Nth TRADING-day bar
  - backfill_decision_outcomes only ever fills NULLs (safe to re-run)
"""

import sqlite3
import time

import pandas as pd
import pytest

import consensus_engine.db as db
from consensus_engine import main as engine_main


# ---------------------------------------------------------------------------
# DB lifecycle helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_db(tmp_path):
    """Fresh temp DB (full v22 schema). Never touches the live consensus.db."""
    db.DB_PATH = str(tmp_path / "test.db")
    db._db = None
    yield
    # teardown handled by _reset_db_state


@pytest.fixture(autouse=True)
def _reset_db_state():
    yield
    db._db = None
    db.DB_PATH = None


async def _table_columns(conn, table) -> list[str]:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return [r["name"] for r in await cur.fetchall()]


async def _insert_snapshot(conn, ticker, age_days, p5=None, p20=None):
    """Insert a decision_snapshots row aged `age_days` calendar days, returns id."""
    recorded_at = time.time() - age_days * 86400
    cur = await conn.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, contradiction_index, sources_json,
            recorded_at, outcome_price_at_alert, outcome_price_1h, outcome_price_24h,
            outcome_price_5d, outcome_price_20d)
           VALUES (?, 'STRONG', 80.0, 0.0, '[]', ?, 100.0, 101.0, 102.0, ?, ?)""",
        (ticker, recorded_at, p5, p20),
    )
    await conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# (a) Migration: additive + idempotent + data survives
# ---------------------------------------------------------------------------

async def test_migration_adds_columns_idempotently_and_preserves_data(tmp_path):
    """Build a PRE-v22 decision_snapshots (no 5d/20d cols) with a row, then init_db:
    the two columns are added, the old row + its 1h/24h data survive, and re-running
    the migration is a no-op (no error, no duplicate columns)."""
    dbfile = str(tmp_path / "old.db")
    raw = sqlite3.connect(dbfile)
    raw.execute(
        """CREATE TABLE decision_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, decision TEXT NOT NULL, final_score REAL NOT NULL,
            contradiction_index REAL DEFAULT 0.0, sources_json TEXT NOT NULL,
            feature_vector_json TEXT, weights_json TEXT, recorded_at REAL NOT NULL,
            outcome_price_at_alert REAL, outcome_price_1h REAL, outcome_price_24h REAL)"""
    )
    raw.execute(
        """INSERT INTO decision_snapshots
           (ticker, decision, final_score, sources_json, recorded_at,
            outcome_price_at_alert, outcome_price_1h, outcome_price_24h)
           VALUES ('AAPL', 'STRONG', 88.0, '[]', ?, 100.0, 101.0, 102.0)""",
        (time.time() - 40 * 86400,),
    )
    raw.commit()
    raw.close()

    db.DB_PATH = dbfile
    db._db = None
    conn = await db.init_db()

    cols = await _table_columns(conn, "decision_snapshots")
    assert "outcome_price_5d" in cols
    assert "outcome_price_20d" in cols

    cur = await conn.execute(
        """SELECT ticker, final_score, outcome_price_1h, outcome_price_24h,
                  outcome_price_5d, outcome_price_20d
           FROM decision_snapshots"""
    )
    rows = await cur.fetchall()
    assert len(rows) == 1, "existing row must survive the migration"
    row = rows[0]
    assert row["ticker"] == "AAPL"
    assert row["final_score"] == 88.0
    assert row["outcome_price_1h"] == 101.0   # existing data byte-identical
    assert row["outcome_price_24h"] == 102.0
    assert row["outcome_price_5d"] is None     # new cols default NULL on old rows
    assert row["outcome_price_20d"] is None

    cur = await conn.execute("SELECT MAX(version) AS v FROM schema_version")
    assert (await cur.fetchone())["v"] >= 22

    # Idempotency: re-running the column migration must not raise or duplicate.
    await db._run_column_migrations(conn)
    cols_again = await _table_columns(conn, "decision_snapshots")
    assert cols_again.count("outcome_price_5d") == 1
    assert cols_again.count("outcome_price_20d") == 1

    # A full re-init (simulates a restart) is also clean and keeps the row.
    await db.close_db()
    db._db = None
    conn2 = await db.init_db()
    cur = await conn2.execute("SELECT COUNT(*) AS c FROM decision_snapshots")
    assert (await cur.fetchone())["c"] == 1
    await db.close_db()


# ---------------------------------------------------------------------------
# (b) Age gate: old enough rows selected, fresh ones not
# ---------------------------------------------------------------------------

async def test_get_snapshots_needing_outcome_age_gate(fresh_db):
    conn = await db.init_db()
    old5 = await _insert_snapshot(conn, "OLD5", age_days=10)    # >= 7d → eligible 5d
    fresh = await _insert_snapshot(conn, "FRESH", age_days=2)   # too young for 5d
    old20 = await _insert_snapshot(conn, "OLD20", age_days=35)  # >= 28d → eligible 20d
    mid = await _insert_snapshot(conn, "MID", age_days=10)      # too young for 20d

    five = await db.get_snapshots_needing_outcome(
        "outcome_price_5d", min_age_days=7, max_age_days=30)
    five_ids = {r["id"] for r in five}
    assert old5 in five_ids
    assert mid in five_ids          # 10d old is eligible for 5d
    assert fresh not in five_ids
    assert old20 not in five_ids    # 35d > max_age 30 → excluded from the bounded loop

    twenty = await db.get_snapshots_needing_outcome(
        "outcome_price_20d", min_age_days=28, max_age_days=45)
    twenty_ids = {r["id"] for r in twenty}
    assert old20 in twenty_ids
    assert old5 not in twenty_ids
    assert mid not in twenty_ids
    assert fresh not in twenty_ids

    # Unbounded (backfill mode) sees the 35d row for 5d too.
    five_unbounded = await db.get_snapshots_needing_outcome(
        "outcome_price_5d", min_age_days=7, max_age_days=None)
    assert old20 in {r["id"] for r in five_unbounded}

    assert await db.get_snapshots_needing_outcome("bogus", min_age_days=7) == []
    await db.close_db()


# ---------------------------------------------------------------------------
# (c) Fetch helper indexes by TRADING day, not calendar day
# ---------------------------------------------------------------------------

class _FakeTicker:
    def __init__(self, closes):
        self._closes = closes

    def history(self, **kwargs):
        return pd.DataFrame({"Close": self._closes})


def test_fetch_helper_picks_nth_trading_day(monkeypatch):
    import yfinance
    # 25 trading-day bars; bar index == its value tag so we can prove which one is read.
    closes = [float(200 + i) for i in range(25)]  # bar 5 -> 205.0, bar 20 -> 220.0
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(closes))

    alerted_at = time.time() - 60 * 86400
    assert engine_main._fetch_yfinance_close_n_trading_days_later("X", alerted_at, 5) == 205.0
    assert engine_main._fetch_yfinance_close_n_trading_days_later("X", alerted_at, 20) == 220.0


def test_fetch_helper_returns_zero_when_window_not_elapsed(monkeypatch):
    import yfinance
    closes = [float(200 + i) for i in range(10)]  # only 10 bars; not enough for 20d
    monkeypatch.setattr(yfinance, "Ticker", lambda t: _FakeTicker(closes))
    alerted_at = time.time() - 8 * 86400
    assert engine_main._fetch_yfinance_close_n_trading_days_later("X", alerted_at, 20) == 0.0


# ---------------------------------------------------------------------------
# (d) Backfill fills only NULLs and is safe to re-run
# ---------------------------------------------------------------------------

async def test_backfill_only_fills_nulls(fresh_db, monkeypatch):
    conn = await db.init_db()
    # A: old enough for both, both NULL  -> both filled
    a = await _insert_snapshot(conn, "AAA", age_days=40)
    # B: old enough for both, 5d already set -> only 20d filled, 5d untouched
    b = await _insert_snapshot(conn, "BBB", age_days=40, p5=99.0)
    # C: too fresh -> neither filled
    c = await _insert_snapshot(conn, "CCC", age_days=2)

    monkeypatch.setattr(
        engine_main, "_fetch_yfinance_close_n_trading_days_later",
        lambda ticker, alerted_at, n: 123.45,
    )

    filled = await engine_main.backfill_decision_outcomes()
    assert filled == {"outcome_price_5d": 1, "outcome_price_20d": 2}

    async def _vals(snap_id):
        cur = await conn.execute(
            "SELECT outcome_price_5d, outcome_price_20d FROM decision_snapshots WHERE id = ?",
            (snap_id,),
        )
        r = await cur.fetchone()
        return r["outcome_price_5d"], r["outcome_price_20d"]

    assert await _vals(a) == (123.45, 123.45)
    assert await _vals(b) == (99.0, 123.45)     # pre-set 5d preserved
    assert await _vals(c) == (None, None)        # too fresh, left NULL

    # Re-run: nothing is NULL+eligible anymore -> no further writes.
    filled2 = await engine_main.backfill_decision_outcomes()
    assert filled2 == {"outcome_price_5d": 0, "outcome_price_20d": 0}
    assert await _vals(a) == (123.45, 123.45)
    assert await _vals(b) == (99.0, 123.45)
    await db.close_db()
