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
