"""Tests for Layer 5 rollback SQL: verify suppression can be reversed."""
import asyncio
import sqlite3

import pytest

from scripts import backfill_youtube_grounding as backfill
from consensus_engine import db as db_module


def _make_simple_init(db_path: str):
    """Return an async init_db that just opens a plain connection (no migrations)."""
    async def _init():
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        db_module._db = db_module.AsyncConnection(conn)
        return db_module._db
    return _init


def _reset_db():
    db_module._db = None


@pytest.fixture
def populated_db(tmp_path, monkeypatch):
    """Build a fixture DB pre-populated with hallucination_backfill suppressions."""
    db_path = tmp_path / "rollback.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE youtube_videos (video_id TEXT PRIMARY KEY, title TEXT, channel_id TEXT, published_at TEXT);
        CREATE TABLE youtube_evidence_spans (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, quote TEXT);
        CREATE TABLE youtube_levels (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, level_type TEXT, price REAL, condition_text TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
        CREATE TABLE youtube_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, source_snippet TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
        CREATE TABLE youtube_setups (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, context_text TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
        CREATE TABLE youtube_options (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, context_text TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
    """)
    conn.execute("INSERT INTO youtube_videos VALUES (?, ?, ?, ?)",
                 ("vkq", "AMC GAMESTOP KOSS - IT HAS BEGUN", "ch1", "2026-04-23T00:00:00Z"))
    conn.execute("INSERT INTO youtube_evidence_spans (video_id, quote) VALUES (?, ?)",
                 ("vkq", "Burry bought more AMC at the dip"))
    conn.execute("INSERT INTO youtube_levels (video_id, ticker, level_type, price, condition_text) VALUES (?, ?, ?, ?, ?)",
                 ("vkq", "NVDA", "entry_low", 845.0, "AI sector strength"))
    conn.execute("INSERT INTO youtube_signals (video_id, ticker, source_snippet) VALUES (?, ?, ?)",
                 ("vkq", "NVDA", "AI sector strength"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(backfill.db, "DB_PATH", str(db_path))
    monkeypatch.setattr(backfill.db, "init_db", _make_simple_init(str(db_path)))
    _reset_db()

    # Run backfill to populate suppressed rows.
    asyncio.run(backfill.main(dry_run=False, video_filter="vkq"))
    _reset_db()

    yield db_path

    _reset_db()


def test_rollback_sql_reverses_one_row(populated_db):
    conn = sqlite3.connect(populated_db)
    conn.execute(
        "UPDATE youtube_levels SET suppressed=0, suppression_reason=NULL "
        "WHERE ticker='NVDA' AND level_type='entry_low'",
    )
    conn.commit()
    nvda_state = conn.execute(
        "SELECT suppressed, suppression_reason FROM youtube_levels "
        "WHERE ticker='NVDA' AND level_type='entry_low'"
    ).fetchone()
    assert nvda_state == (0, None)


def test_full_backfill_rollback(populated_db):
    """Bulk rollback restores all hallucination_backfill rows."""
    conn = sqlite3.connect(populated_db)
    for table in ("youtube_signals", "youtube_levels", "youtube_setups", "youtube_options"):
        conn.execute(
            f"UPDATE {table} SET suppressed=0, suppression_reason=NULL "
            f"WHERE suppression_reason='hallucination_backfill'"
        )
    conn.commit()
    remaining = sum(
        conn.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE suppression_reason='hallucination_backfill'"
        ).fetchone()[0]
        for table in ("youtube_signals", "youtube_levels", "youtube_setups", "youtube_options")
    )
    assert remaining == 0


def test_suppression_rollup_query(populated_db):
    """Operational query for daily reporting: count suppressions by reason."""
    conn = sqlite3.connect(populated_db)
    rollup = dict(conn.execute(
        "SELECT suppression_reason, COUNT(*) FROM youtube_levels "
        "WHERE suppressed=1 GROUP BY suppression_reason"
    ).fetchall())
    assert "hallucination_backfill" in rollup
    assert rollup["hallucination_backfill"] >= 1
