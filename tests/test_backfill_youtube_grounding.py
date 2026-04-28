"""Tests for Layer 5: backfill_youtube_grounding script."""
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
def fixture_db(tmp_path, monkeypatch):
    """Build a small sqlite fixture mimicking the real schema for backfill tests."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE youtube_videos (video_id TEXT PRIMARY KEY, title TEXT, description TEXT, channel_id TEXT, published_at TEXT);
        CREATE TABLE youtube_evidence_spans (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, quote TEXT);
        CREATE TABLE youtube_levels (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, level_type TEXT, price REAL, condition_text TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
        CREATE TABLE youtube_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, source_snippet TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
        CREATE TABLE youtube_setups (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, context_text TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
        CREATE TABLE youtube_options (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, ticker TEXT, context_text TEXT, suppressed INTEGER DEFAULT 0, suppression_reason TEXT);
    """)
    conn.execute("INSERT INTO youtube_videos VALUES (?, ?, ?, ?, ?)",
                 ("vkq", "AMC GAMESTOP KOSS - IT HAS BEGUN", None, "ch1", "2026-04-23T00:00:00Z"))
    conn.execute("INSERT INTO youtube_evidence_spans (video_id, quote) VALUES (?, ?)",
                 ("vkq", "Burry bought more AMC at the dip"))
    conn.execute("INSERT INTO youtube_evidence_spans (video_id, quote) VALUES (?, ?)",
                 ("vkq", "GameStop short squeeze setup"))
    # Hallucinated NVDA rows + legitimate AMC/GME
    conn.execute("INSERT INTO youtube_levels (video_id, ticker, level_type, price, condition_text) VALUES (?, ?, ?, ?, ?)",
                 ("vkq", "NVDA", "entry_low", 845.0, "AI sector strength"))
    conn.execute("INSERT INTO youtube_levels (video_id, ticker, level_type, price, condition_text) VALUES (?, ?, ?, ?, ?)",
                 ("vkq", "AMC", "target", 2.0, "Burry buying"))
    conn.execute("INSERT INTO youtube_signals (video_id, ticker, source_snippet) VALUES (?, ?, ?)",
                 ("vkq", "NVDA", "AI sector strength"))
    conn.commit()
    conn.close()

    monkeypatch.setattr(backfill.db, "DB_PATH", str(db_path))
    monkeypatch.setattr(backfill.db, "init_db", _make_simple_init(str(db_path)))
    _reset_db()

    yield db_path

    _reset_db()


def test_dry_run_makes_no_writes(fixture_db):
    asyncio.run(backfill.main(dry_run=True, video_filter="vkq"))
    conn = sqlite3.connect(fixture_db)
    suppressed = conn.execute("SELECT COUNT(*) FROM youtube_levels WHERE suppressed=1").fetchone()[0]
    assert suppressed == 0


def test_apply_suppresses_only_off_allowlist(fixture_db):
    asyncio.run(backfill.main(dry_run=False, video_filter="vkq"))
    conn = sqlite3.connect(fixture_db)
    nvda_suppressed = conn.execute(
        "SELECT suppressed, suppression_reason FROM youtube_levels WHERE ticker='NVDA'"
    ).fetchone()
    amc_suppressed = conn.execute(
        "SELECT suppressed FROM youtube_levels WHERE ticker='AMC'"
    ).fetchone()
    assert nvda_suppressed == (1, "hallucination_backfill")
    assert amc_suppressed == (0,)


def test_idempotent(fixture_db):
    asyncio.run(backfill.main(dry_run=False, video_filter="vkq"))
    _reset_db()
    asyncio.run(backfill.main(dry_run=False, video_filter="vkq"))  # second run no-ops
    conn = sqlite3.connect(fixture_db)
    nvda_suppressed = conn.execute(
        "SELECT COUNT(*) FROM youtube_levels WHERE ticker='NVDA' AND suppressed=1"
    ).fetchone()[0]
    assert nvda_suppressed == 1
