"""Tests for YouTube DB schema and helper methods."""
import time
import pytest
from consensus_engine import db, config as cfg


@pytest.fixture(autouse=True)
def setup_config():
    cfg.load_config()


@pytest.fixture
async def test_db(tmp_path):
    db_path = str(tmp_path / "test_yt.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


@pytest.fixture
async def tmp_db(tmp_path):
    db_path = str(tmp_path / "test_yt_tmp.db")
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    conn = await db.init_db()
    yield conn
    await db.close_db()


# --- Task 1: youtube_analysis_runs table + provenance columns ---

@pytest.mark.asyncio
async def test_create_analysis_run_returns_id(tmp_db):
    run_id = await db.create_analysis_run("vid123", "v2")
    assert isinstance(run_id, int)
    assert run_id > 0

@pytest.mark.asyncio
async def test_create_analysis_run_idempotent(tmp_db):
    id1 = await db.create_analysis_run("vid123", "v2")
    id2 = await db.create_analysis_run("vid123", "v2")
    assert id1 == id2  # same run returned

@pytest.mark.asyncio
async def test_update_analysis_run_status(tmp_db):
    run_id = await db.create_analysis_run("vid999", "v2")
    await db.update_analysis_run(run_id, status="complete", call_budget_used=5)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT status, call_budget_used FROM youtube_analysis_runs WHERE id=?", (run_id,)
    )
    row = await cur.fetchone()
    assert row["status"] == "complete"
    assert row["call_budget_used"] == 5

@pytest.mark.asyncio
async def test_provenance_columns_exist_on_youtube_signals(tmp_db):
    conn = await db.get_db()
    cur = await conn.execute("PRAGMA table_info(youtube_signals)")
    cols = {r["name"] for r in await cur.fetchall()}
    assert {"run_id", "source_snippet", "chunk_id", "parser_version"}.issubset(cols)

@pytest.mark.asyncio
async def test_provenance_columns_exist_on_youtube_levels(tmp_db):
    conn = await db.get_db()
    cur = await conn.execute("PRAGMA table_info(youtube_levels)")
    cols = {r["name"] for r in await cur.fetchall()}
    assert {"run_id", "source_snippet", "chunk_id", "parser_version", "setup_id"}.issubset(cols)


# --- Task 2: youtube_options + youtube_setups tables ---

@pytest.mark.asyncio
async def test_insert_and_get_youtube_option(tmp_db):
    run_id = await db.create_analysis_run("vidOPT1", "v2")
    await db.insert_youtube_option(
        run_id=run_id, video_id="vidOPT1", ticker="TSLA",
        option_type="call", strike=250.0, expiry="weekly",
        strategy="single", source="flow_observation",
        conviction="high", context_text="seeing massive call sweep at 250",
        source_snippet="seeing massive call sweep at 250 strike",
        chunk_id=0, parser_version="v2",
        channel_name="CheddarFlow", published_at="2026-04-22T10:00:00Z",
    )
    rows = await db.get_youtube_options_for_ticker("TSLA", days=7)
    assert len(rows) == 1
    assert rows[0]["option_type"] == "call"
    assert rows[0]["strike"] == 250.0
    assert rows[0]["source_snippet"] == "seeing massive call sweep at 250 strike"

@pytest.mark.asyncio
async def test_insert_and_get_youtube_setup(tmp_db):
    run_id = await db.create_analysis_run("vidSET1", "v2")
    await db.insert_youtube_setup(
        run_id=run_id, video_id="vidSET1", ticker="NVDA",
        entry_low=845.0, entry_high=855.0, stop_price=820.0,
        targets=[920.0, 980.0], timeframe="swing",
        setup_type="breakout", context_text="buy NVDA at 850 stop 820 target 920",
        source_snippet="buy NVDA at 850, stop 820, target 920",
        chunk_id=0, risk_reward=2.5, parser_version="v2",
        channel_name="ClickCapital", published_at="2026-04-22T10:00:00Z",
    )
    rows = await db.get_youtube_setups_for_ticker("NVDA", days=14)
    assert len(rows) == 1
    import json
    targets = json.loads(rows[0]["targets_json"])
    assert targets == [920.0, 980.0]
    assert rows[0]["risk_reward"] == pytest.approx(2.5)


# --- Task 3: canonical evidence read + level absorption ---

@pytest.mark.asyncio
async def test_canonical_evidence_returns_setups_not_raw_levels(tmp_db):
    """When a setup exists, absorbed levels are excluded from canonical evidence."""
    run_id = await db.create_analysis_run("vidCE1", "v2")
    # Insert a setup
    setup_id = await db.insert_youtube_setup(
        run_id=run_id, video_id="vidCE1", ticker="AAPL",
        entry_low=180.0, entry_high=182.0, stop_price=175.0,
        targets=[195.0], timeframe="swing", setup_type="breakout",
        context_text="buy AAPL 180-182 stop 175 target 195",
        source_snippet="buy AAPL", chunk_id=0, risk_reward=2.6,
        parser_version="v2", channel_name="Chan", published_at=None,
    )
    # Insert levels that belong to this setup (absorbed)
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, extracted_at, setup_id, parser_version, run_id)
           VALUES (?,?,?,?,?,?,?,?)""",
        ("vidCE1", "AAPL", "support", 180.0, time.time(), setup_id, "v2", run_id),
    )
    # Insert an unabsorbed level
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, extracted_at, parser_version, run_id)
           VALUES (?,?,?,?,?,?,?)""",
        ("vidCE1", "AAPL", "resistance", 200.0, time.time(), "v2", run_id),
    )
    await conn.commit()

    rows = await db.get_youtube_evidence_for_ticker("AAPL", days=7)
    types = {r["evidence_type"] for r in rows}
    assert "setup" in types
    # The absorbed level (180.0 support) must not appear as a standalone level
    raw_level_prices = [r["price"] for r in rows if r["evidence_type"] == "level"]
    assert 180.0 not in raw_level_prices
    # The unabsorbed resistance should appear
    assert 200.0 in raw_level_prices

@pytest.mark.asyncio
async def test_canonical_evidence_falls_back_to_levels_when_no_setup(tmp_db):
    run_id = await db.create_analysis_run("vidCE2", "v2")
    conn = await db.get_db()
    await conn.execute(
        """INSERT INTO youtube_levels
           (video_id, ticker, level_type, price, extracted_at, parser_version, run_id)
           VALUES (?,?,?,?,?,?,?)""",
        ("vidCE2", "NVDA", "support", 850.0, time.time(), "v2", run_id),
    )
    await conn.commit()
    rows = await db.get_youtube_evidence_for_ticker("NVDA", days=7)
    assert len(rows) == 1
    assert rows[0]["evidence_type"] == "level"
    assert rows[0]["price"] == 850.0


@pytest.mark.asyncio
async def test_tables_created(test_db):
    conn = await db.get_db()
    cursor = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('youtube_videos','youtube_transcripts')"
    )
    rows = await cursor.fetchall()
    names = {r["name"] for r in rows}
    assert "youtube_videos" in names
    assert "youtube_transcripts" in names


@pytest.mark.asyncio
async def test_has_video_been_processed_unknown(test_db):
    result = await db.has_video_been_processed("nonexistent_id")
    assert result is False


@pytest.mark.asyncio
async def test_upsert_and_has_processed(test_db):
    await db.upsert_youtube_video("vid1", "UC123", "Title", "2026-04-06T00:00:00Z", time.time())
    # still pending → not "processed"
    result = await db.has_video_been_processed("vid1")
    assert result is False

    await db.mark_youtube_video_status("vid1", "saved", language="en", is_auto_generated=True, export_path="/tmp/vid1.json")
    result = await db.has_video_been_processed("vid1")
    assert result is True


@pytest.mark.asyncio
async def test_upsert_idempotent(test_db):
    for _ in range(3):
        await db.upsert_youtube_video("vid2", "UC456", "Dupe Title", "2026-04-06T01:00:00Z", time.time())
    conn = await db.get_db()
    cursor = await conn.execute("SELECT COUNT(*) as cnt FROM youtube_videos WHERE video_id='vid2'")
    row = await cursor.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_mark_status_missing(test_db):
    await db.upsert_youtube_video("vid3", "UC789", "No Captions", "2026-04-06T02:00:00Z", time.time())
    await db.mark_youtube_video_status("vid3", "missing")
    result = await db.has_video_been_processed("vid3")
    assert result is True
    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id='vid3'")
    row = await cursor.fetchone()
    assert row["transcript_status"] == "missing"


@pytest.mark.asyncio
async def test_save_transcript(test_db):
    await db.upsert_youtube_video("vid4", "UCabc", "Has Transcript", "2026-04-06T03:00:00Z", time.time())
    await db.save_youtube_transcript("vid4", "This is the transcript text.", "abc123hash")
    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_text, transcript_hash FROM youtube_transcripts WHERE video_id='vid4'")
    row = await cursor.fetchone()
    assert row["transcript_text"] == "This is the transcript text."
    assert row["transcript_hash"] == "abc123hash"


@pytest.mark.asyncio
async def test_save_transcript_idempotent(test_db):
    await db.upsert_youtube_video("vid5", "UCdef", "Repeated Save", "2026-04-06T04:00:00Z", time.time())
    await db.save_youtube_transcript("vid5", "text v1", "hash1")
    await db.save_youtube_transcript("vid5", "text v2", "hash2")
    conn = await db.get_db()
    cursor = await conn.execute("SELECT transcript_text FROM youtube_transcripts WHERE video_id='vid5'")
    row = await cursor.fetchone()
    assert row["transcript_text"] == "text v2"


# --- P1a: v2 idempotent inserts + evidence spans + catalysts + metrics + rate limit ---


@pytest.mark.asyncio
async def test_insert_youtube_signal_idempotent(tmp_db):
    run_id = await db.create_analysis_run("vidSIG1", "v2")
    for _ in range(2):
        await db.insert_youtube_signal(
            video_id="vidSIG1", channel_name="Chan", ticker="AAPL",
            direction="long", conviction="high", mention_count=1,
            run_id=run_id, parser_version="v2",
        )
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_signals WHERE run_id=? AND ticker='AAPL' AND direction='long'",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_insert_youtube_level_idempotent(tmp_db):
    run_id = await db.create_analysis_run("vidLVL1", "v2")
    for _ in range(2):
        await db.insert_youtube_level(
            video_id="vidLVL1", ticker="NVDA", level_type="support",
            price=850.0, run_id=run_id, parser_version="v2",
        )
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_levels WHERE run_id=? AND ticker='NVDA' AND level_type='support' AND price=850.0",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_insert_youtube_setup_idempotent(tmp_db):
    run_id = await db.create_analysis_run("vidSET2", "v2")
    ids = []
    for _ in range(2):
        sid = await db.insert_youtube_setup(
            run_id=run_id, video_id="vidSET2", ticker="MSFT",
            entry_low=400.0, entry_high=405.0, stop_price=390.0,
            targets=[420.0], timeframe="swing", setup_type="breakout",
            context_text=None, source_snippet=None, chunk_id=0,
            risk_reward=2.0, parser_version="v2",
            channel_name="Chan", published_at=None,
        )
        ids.append(sid)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_setups WHERE run_id=? AND ticker='MSFT' AND entry_low=400.0 AND entry_high=405.0",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 1
    assert ids[0] == ids[1]  # same id returned both times


@pytest.mark.asyncio
async def test_insert_youtube_option_idempotent(tmp_db):
    run_id = await db.create_analysis_run("vidOPT2", "v2")
    for _ in range(2):
        await db.insert_youtube_option(
            run_id=run_id, video_id="vidOPT2", ticker="TSLA",
            option_type="call", strike=250.0, expiry="weekly",
            strategy="single", source="flow", conviction="high",
            context_text=None, source_snippet=None, chunk_id=0,
            parser_version="v2", channel_name="Chan", published_at=None,
        )
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_options WHERE run_id=? AND ticker='TSLA' AND option_type='call' AND strike=250.0 AND expiry='weekly'",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_insert_youtube_evidence_span_idempotent(tmp_db):
    run_id = await db.create_analysis_run("vidES1", "v2")
    for _ in range(2):
        await db.insert_youtube_evidence_span(
            run_id=run_id, video_id="vidES1", ts_sec=120,
            quote="MSFT earnings next Wednesday",
            tickers=["MSFT"], numbers=[], dates=["next Wednesday"],
        )
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_evidence_spans WHERE run_id=? AND ts_sec=120",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_insert_youtube_visual_evidence_writes_rows(tmp_db):
    items = [
        {"ts_sec": 10, "value": "739.88", "kind": "price", "where": "chart axis"},
        {"ts_sec": 30, "value": "NVDA", "kind": "ticker", "where": "flow row"},
    ]
    await db.insert_youtube_visual_evidence("vidVE1", items)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT video_id, ts_sec, value, kind, where_seen FROM youtube_visual_evidence "
        "WHERE video_id=? ORDER BY ts_sec",
        ("vidVE1",),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    assert len(rows) == 2
    assert rows[0]["value"] == "739.88"
    assert rows[0]["kind"] == "price"
    assert rows[0]["where_seen"] == "chart axis"
    assert rows[1]["value"] == "NVDA"


@pytest.mark.asyncio
async def test_insert_youtube_visual_evidence_empty_noop(tmp_db):
    await db.insert_youtube_visual_evidence("vidVE2", [])
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_visual_evidence WHERE video_id=?",
        ("vidVE2",),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 0


@pytest.mark.asyncio
async def test_insert_youtube_catalyst_idempotent(tmp_db):
    run_id = await db.create_analysis_run("vidCAT1", "v2")
    for _ in range(2):
        await db.insert_youtube_catalyst(
            run_id=run_id, video_id="vidCAT1", ticker="MSFT",
            catalyst_type="earnings", mentioned_date="next Wednesday",
            resolved_date="2026-04-29", verified=1,
            context_text="MSFT reports earnings next Wednesday",
            video_timestamp_sec=120, evidence_span_ids="1",
        )
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM youtube_catalysts WHERE run_id=? AND ticker='MSFT' AND resolved_date='2026-04-29' AND catalyst_type='earnings'",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["cnt"] == 1


@pytest.mark.asyncio
async def test_update_analysis_run_metrics(tmp_db):
    run_id = await db.create_analysis_run("vidMET1", "v2")
    await db.update_analysis_run_metrics(
        run_id,
        input_tokens=1000, output_tokens=500, latency_ms=2500,
        json_parse_ok=1, span_count=12, filter_drop_count=3,
    )
    conn = await db.get_db()
    cur = await conn.execute(
        """SELECT input_tokens, output_tokens, latency_ms,
                  json_parse_ok, span_count, filter_drop_count
           FROM youtube_analysis_runs WHERE id=?""",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 500
    assert row["latency_ms"] == 2500
    assert row["json_parse_ok"] == 1
    assert row["span_count"] == 12
    assert row["filter_drop_count"] == 3


@pytest.mark.asyncio
async def test_user_rate_limit(tmp_db, monkeypatch):
    """Log 5 invocations → limit=5/60s is reached (True). Advance mock time past
    the window → limit no longer exceeded (False) until we log again past limit."""
    base = 1_000_000.0
    current = [base]

    def fake_time():
        return current[0]

    monkeypatch.setattr(db.time, "time", fake_time)

    for _ in range(5):
        await db.log_user_command("user1", "yt")
    # 5 rows in 60s → limit of 5 reached
    assert await db.check_user_rate_limit("user1", "yt", limit=5, window_sec=60) is True
    # Lower count under limit
    assert await db.check_user_rate_limit("user1", "yt", limit=6, window_sec=60) is False

    # Advance past the window
    current[0] = base + 61.0
    # All prior rows are now outside the 60s window → not rate-limited
    assert await db.check_user_rate_limit("user1", "yt", limit=5, window_sec=60) is False

    # Log 6 fresh calls at new time → limit=5 now reached again
    for _ in range(6):
        await db.log_user_command("user1", "yt")
    assert await db.check_user_rate_limit("user1", "yt", limit=5, window_sec=60) is True


# --- P-verify hotfix: dedup legacy rows before UNIQUE index creation ---


@pytest.mark.asyncio
async def test_dedup_legacy_signals(tmp_db):
    """3 duplicate (run_id, ticker, direction) rows → 1 remains (lowest id)."""
    conn = await db.get_db()
    # Simulate pre-hotfix state: no UNIQUE index on youtube_signals.
    await conn.execute("DROP INDEX IF EXISTS idx_youtube_signals_uniq")
    run_id = await db.create_analysis_run("vidDUP1", "v2")
    now = time.time()
    for _ in range(3):
        await conn.execute(
            """INSERT INTO youtube_signals
               (video_id, channel_name, ticker, direction, conviction,
                parsed_at, extracted_at, run_id, parser_version)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("vidDUP1", "Chan", "TSLA", "short", "high", now, now, run_id, "v2"),
        )
    await conn.commit()
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM youtube_signals WHERE run_id=? AND ticker='TSLA' AND direction='short'",
        (run_id,),
    )
    assert (await cur.fetchone())["c"] == 3

    await db._dedup_legacy_rows(conn)

    cur = await conn.execute(
        "SELECT COUNT(*) AS c, MIN(id) AS min_id FROM youtube_signals WHERE run_id=? AND ticker='TSLA' AND direction='short'",
        (run_id,),
    )
    row = await cur.fetchone()
    assert row["c"] == 1
    # Surviving row is the oldest (lowest id)
    cur = await conn.execute(
        "SELECT id FROM youtube_signals WHERE run_id=? AND ticker='TSLA' AND direction='short'",
        (run_id,),
    )
    surviving = await cur.fetchone()
    assert surviving["id"] == row["min_id"]


@pytest.mark.asyncio
async def test_dedup_legacy_levels(tmp_db):
    conn = await db.get_db()
    await conn.execute("DROP INDEX IF EXISTS idx_youtube_levels_uniq")
    run_id = await db.create_analysis_run("vidDUP2", "v2")
    now = time.time()
    for _ in range(4):
        await conn.execute(
            """INSERT INTO youtube_levels
               (video_id, ticker, level_type, price, extracted_at, run_id, parser_version)
               VALUES (?,?,?,?,?,?,?)""",
            ("vidDUP2", "NVDA", "support", 850.0, now, run_id, "v2"),
        )
    await conn.commit()

    await db._dedup_legacy_rows(conn)

    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM youtube_levels WHERE run_id=? AND ticker='NVDA' AND level_type='support' AND price=850.0",
        (run_id,),
    )
    assert (await cur.fetchone())["c"] == 1


@pytest.mark.asyncio
async def test_dedup_noop_on_clean_db(tmp_db):
    """All-unique rows → dedup removes nothing."""
    conn = await db.get_db()
    run_id = await db.create_analysis_run("vidCLN", "v2")
    now = time.time()
    # 3 distinct tickers — no duplicates under (run_id, ticker, direction)
    for t in ("AAPL", "NVDA", "TSLA"):
        await conn.execute(
            """INSERT INTO youtube_signals
               (video_id, channel_name, ticker, direction, conviction,
                parsed_at, extracted_at, run_id, parser_version)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("vidCLN", "Chan", t, "long", "high", now, now, run_id, "v2"),
        )
    await conn.commit()
    cur = await conn.execute("SELECT COUNT(*) AS c FROM youtube_signals WHERE run_id=?", (run_id,))
    before = (await cur.fetchone())["c"]
    assert before == 3

    await db._dedup_legacy_rows(conn)

    cur = await conn.execute("SELECT COUNT(*) AS c FROM youtube_signals WHERE run_id=?", (run_id,))
    after = (await cur.fetchone())["c"]
    assert after == before


@pytest.mark.asyncio
async def test_init_db_survives_legacy_duplicates(tmp_path):
    """Simulate production issue: DB has legacy dupes and no UNIQUE index yet.
    init_db() must dedup-then-index without raising IntegrityError, and the
    UNIQUE index must be present afterward.
    """
    import sqlite3 as _sqlite3
    db_path = str(tmp_path / "legacy.db")

    # Build a minimal legacy DB: schema + migrations, NO unique index, with dupes.
    cfg._config["database"] = {"path": db_path, "signal_ttl_hours": 2, "alert_history_days": 90}
    # The autouse _isolate_db fixture sets db.DB_PATH (which takes precedence over the
    # config path) — point it at THIS test's path so init_db and the raw sqlite3 open below
    # operate on the same file.
    db.DB_PATH = db_path
    db._db = None
    await db.init_db()
    # Drop the fresh UNIQUE index to emulate the live DB state
    raw_conn = _sqlite3.connect(db_path)
    raw_conn.execute("DROP INDEX IF EXISTS idx_youtube_signals_uniq")
    raw_conn.execute("DROP INDEX IF EXISTS idx_youtube_levels_uniq")
    raw_conn.execute("DROP INDEX IF EXISTS idx_youtube_setups_uniq")
    raw_conn.execute("DROP INDEX IF EXISTS idx_youtube_options_uniq")
    # Insert legacy duplicates via raw INSERT (bypassing INSERT OR IGNORE helpers)
    now = time.time()
    raw_conn.execute(
        """INSERT INTO youtube_analysis_runs (video_id, parser_version, status, started_at)
           VALUES ('vidLEG', 'v2', 'complete', ?)""",
        (now,),
    )
    run_id = raw_conn.execute(
        "SELECT id FROM youtube_analysis_runs WHERE video_id='vidLEG'"
    ).fetchone()[0]
    for _ in range(4):
        raw_conn.execute(
            """INSERT INTO youtube_signals
               (video_id, channel_name, ticker, direction, conviction,
                parsed_at, extracted_at, run_id, parser_version)
               VALUES ('vidLEG','Chan','TSLA','short','high',?,?,?, 'v2')""",
            (now, now, run_id),
        )
    raw_conn.commit()
    raw_conn.close()
    await db.close_db()

    # Now simulate engine restart: init_db() must NOT raise.
    db._db = None
    await db.init_db()  # would raise IntegrityError without the dedup hotfix

    # UNIQUE index is present
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_youtube_signals_uniq'"
    )
    assert await cur.fetchone() is not None

    # Duplicates collapsed to 1
    cur = await conn.execute(
        "SELECT COUNT(*) AS c FROM youtube_signals WHERE run_id=? AND ticker='TSLA' AND direction='short'",
        (run_id,),
    )
    assert (await cur.fetchone())["c"] == 1
    await db.close_db()


# --- ITEM #7: cross-day retry of failed/budget-skipped videos ---

def _force_max_retries(monkeypatch, cap: int) -> None:
    """Force youtube.max_retries to `cap` regardless of yaml."""
    real_get = db.cfg.get

    def fake_get(key, default=None):
        if key == "youtube.max_retries":
            return cap
        return real_get(key, default)

    monkeypatch.setattr(db.cfg, "get", fake_get)


@pytest.mark.asyncio
async def test_failed_under_cap_is_retryable(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidR1", "UCr", "T", "2026-05-01T00:00:00Z", time.time())
    # one failed attempt (bump → attempt_count=1, < cap)
    await db.mark_youtube_video_status("vidR1", "failed", bump_attempt=True)
    assert await db.has_video_been_processed("vidR1") is False


@pytest.mark.asyncio
async def test_failed_at_cap_is_terminal(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 3)
    await db.upsert_youtube_video("vidR2", "UCr", "T", "2026-05-01T00:00:00Z", time.time())
    for _ in range(3):  # attempt_count reaches the cap of 3
        await db.mark_youtube_video_status("vidR2", "failed", bump_attempt=True)
    assert await db.has_video_been_processed("vidR2") is True


@pytest.mark.asyncio
async def test_missing_stays_terminal(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidR3", "UCr", "T", "2026-05-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidR3", "missing")
    assert await db.has_video_been_processed("vidR3") is True


@pytest.mark.asyncio
async def test_success_states_stay_terminal(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    for i, status in enumerate(("saved", "analyzed_gemini", "analyzed_gemini_v2")):
        vid = f"vidS{i}"
        await db.upsert_youtube_video(vid, "UCr", "T", "2026-05-01T00:00:00Z", time.time())
        await db.mark_youtube_video_status(vid, status)
        assert await db.has_video_been_processed(vid) is True


@pytest.mark.asyncio
async def test_get_retryable_returns_rows_oldest_first(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    # Three failed videos (retryable), published out of order.
    await db.upsert_youtube_video("vidF_mid",  "UCr", "Mid",  "2026-05-02T00:00:00Z", time.time())
    await db.upsert_youtube_video("vidF_old",  "UCr", "Old",  "2026-05-01T00:00:00Z", time.time())
    await db.upsert_youtube_video("vidF_new",  "UCr", "New",  "2026-05-03T00:00:00Z", time.time())
    for vid in ("vidF_mid", "vidF_old", "vidF_new"):
        await db.mark_youtube_video_status(vid, "failed", bump_attempt=True)
    # Excluded rows: a success, a missing, and a capped-out failure.
    await db.upsert_youtube_video("vidF_done", "UCr", "Done", "2026-05-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidF_done", "saved")
    await db.upsert_youtube_video("vidF_miss", "UCr", "Miss", "2026-05-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidF_miss", "missing")
    await db.upsert_youtube_video("vidF_cap", "UCr", "Cap", "2026-05-01T00:00:00Z", time.time())
    for _ in range(5):
        await db.mark_youtube_video_status("vidF_cap", "failed", bump_attempt=True)

    rows = await db.get_retryable_youtube_videos(5)
    ids = [r["video_id"] for r in rows]
    assert ids == ["vidF_old", "vidF_mid", "vidF_new"]  # oldest published_at first


@pytest.mark.asyncio
async def test_bump_attempt_increments_and_stamps(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidB", "UCr", "T", "2026-05-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidB", "failed", bump_attempt=True)
    await db.mark_youtube_video_status("vidB", "failed", bump_attempt=True)
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT attempt_count, last_attempt_at FROM youtube_videos WHERE video_id='vidB'"
    )
    row = await cur.fetchone()
    assert row["attempt_count"] == 2
    assert row["last_attempt_at"] is not None


@pytest.mark.asyncio
async def test_mark_status_no_bump_leaves_counter(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidN", "UCr", "T", "2026-05-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidN", "saved")  # default bump_attempt=False
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT attempt_count, last_attempt_at FROM youtube_videos WHERE video_id='vidN'"
    )
    row = await cur.fetchone()
    assert (row["attempt_count"] or 0) == 0
    assert row["last_attempt_at"] is None


# --- Item G (deep-dive-2026-06-08): quota_blocked durable-queue state machine ---

@pytest.mark.asyncio
async def test_quota_blocked_is_not_terminal(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidQB", "UCr", "T", "2026-06-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidQB", "quota_blocked")
    # not terminal -> still re-processable
    assert await db.has_video_been_processed("vidQB") is False
    # no attempt bump on quota_blocked, and quota_blocked_since stamped
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT attempt_count, quota_blocked_since FROM youtube_videos WHERE video_id='vidQB'"
    )
    row = await cur.fetchone()
    assert (row["attempt_count"] or 0) == 0
    assert row["quota_blocked_since"] is not None


@pytest.mark.asyncio
async def test_quota_blocked_since_clears_on_success(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidQC", "UCr", "T", "2026-06-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidQC", "quota_blocked")
    await db.mark_youtube_video_status("vidQC", "saved")  # recovered
    conn = await db.get_db()
    cur = await conn.execute(
        "SELECT quota_blocked_since FROM youtube_videos WHERE video_id='vidQC'"
    )
    row = await cur.fetchone()
    assert row["quota_blocked_since"] is None


@pytest.mark.asyncio
async def test_drain_includes_quota_blocked_and_pending(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidF", "UCr", "T", "2026-06-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidF", "failed", bump_attempt=True)
    await db.upsert_youtube_video("vidQ", "UCr", "T", "2026-06-02T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidQ", "quota_blocked")
    await db.upsert_youtube_video("vidP", "UCr", "T", "2026-06-03T00:00:00Z", time.time())
    # vidP stays 'pending' (orphaned past RSS window)
    await db.upsert_youtube_video("vidM", "UCr", "T", "2026-06-04T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidM", "missing")  # terminal, must NOT drain
    ids = {v["video_id"] for v in await db.get_retryable_youtube_videos(5)}
    assert {"vidF", "vidQ", "vidP"} <= ids
    assert "vidM" not in ids


@pytest.mark.asyncio
async def test_downgrade_stale_quota_blocked(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("vidOld", "UCr", "T", "2026-05-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidOld", "quota_blocked")
    # backdate quota_blocked_since to 10 days ago
    conn = await db.get_db()
    await conn.execute(
        "UPDATE youtube_videos SET quota_blocked_since=? WHERE video_id='vidOld'",
        (time.time() - 10 * 86400,),
    )
    await conn.commit()
    await db.upsert_youtube_video("vidNew", "UCr", "T", "2026-06-08T00:00:00Z", time.time())
    await db.mark_youtube_video_status("vidNew", "quota_blocked")  # fresh, stays
    n = await db.downgrade_stale_quota_blocked(4)
    assert n == 1
    cur = await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id='vidOld'")
    assert (await cur.fetchone())["transcript_status"] == "failed"
    cur = await conn.execute("SELECT transcript_status FROM youtube_videos WHERE video_id='vidNew'")
    assert (await cur.fetchone())["transcript_status"] == "quota_blocked"


@pytest.mark.asyncio
async def test_backlog_depth_counts(test_db, monkeypatch):
    _force_max_retries(monkeypatch, 5)
    await db.upsert_youtube_video("b1", "UCr", "T", "2026-06-01T00:00:00Z", time.time())
    await db.mark_youtube_video_status("b1", "quota_blocked")
    await db.upsert_youtube_video("b2", "UCr", "T", "2026-06-02T00:00:00Z", time.time())
    await db.mark_youtube_video_status("b2", "failed", bump_attempt=True)
    depth = await db.get_youtube_backlog_depth(5)
    assert depth["quota_blocked"] == 1
    assert depth["retryable_failed"] == 1
    assert depth["total"] == 2


# --- Partial-read detection: store true vs Gemini-observed duration ---

@pytest.mark.asyncio
async def test_set_durations_stores_true_and_observed(test_db):
    await db.upsert_youtube_video("vidDur", "UCr", "T", "2026-06-09T00:00:00Z", time.time())
    # 105-min video, Gemini only saw 18.7 min (the real truncation case)
    await db.set_youtube_video_durations("vidDur", duration_sec=6314, observed_duration_sec=1121)
    row = await db.get_youtube_video("vidDur")
    assert row["duration_sec"] == 6314
    assert row["observed_duration_sec"] == 1121
    # observed is well under the 0.8 floor → this row would trip the partial-read warning
    assert row["observed_duration_sec"] < 0.8 * row["duration_sec"]


@pytest.mark.asyncio
async def test_set_durations_coalesces_missing_value(test_db):
    await db.upsert_youtube_video("vidDur2", "UCr", "T", "2026-06-09T00:00:00Z", time.time())
    await db.set_youtube_video_durations("vidDur2", duration_sec=600, observed_duration_sec=590)
    # A later call where the duration mirror was down (None) must NOT wipe the stored value
    await db.set_youtube_video_durations("vidDur2", duration_sec=None, observed_duration_sec=595)
    row = await db.get_youtube_video("vidDur2")
    assert row["duration_sec"] == 600
    assert row["observed_duration_sec"] == 595
